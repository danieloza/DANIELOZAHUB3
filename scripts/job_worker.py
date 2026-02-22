import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.enterprise import (  # noqa: E402
    claim_due_background_jobs,
    mark_background_job_failure,
    mark_background_job_success,
    run_retention_cleanup,
    utc_now_naive,
)
from app.models import CalendarConnection, CalendarSyncEvent  # noqa: E402
from app.pdf_export import build_month_report_pdf  # noqa: E402
from app.services import month_report  # noqa: E402


def _payload(job) -> dict:
    try:
        return json.loads(job.payload_json or "{}")
    except Exception:
        return {}


def _first_webhook_secret(raw: str | None) -> str | None:
    for part in str(raw or "").split(","):
        value = part.strip()
        if value:
            return value
    return None


def _handle_generate_pdf_report(db, job) -> dict:
    payload = _payload(job)
    tenant_id = int(job.tenant_id or 0)
    year = int(payload.get("year"))
    month = int(payload.get("month"))
    total, count, by_emp = month_report(db, tenant_id, year, month)
    month_label = f"{year:04d}-{month:02d}"
    pdf_bytes = build_month_report_pdf(month_label, total, count, by_emp)
    out_dir = ROOT / "logs" / "generated_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"tenant_{tenant_id}_{month_label}_{job.id}.pdf"
    out_path.write_bytes(pdf_bytes)
    return {"file": str(out_path), "size_bytes": len(pdf_bytes)}


def _handle_cleanup_retention(db, job) -> dict:
    tenant_id = int(job.tenant_id or 0)
    return run_retention_cleanup(db, tenant_id=tenant_id)


def _handle_calendar_sync_push(db, job) -> dict:
    payload = _payload(job)
    event_id = int(payload.get("sync_event_id"))
    event = db.execute(select(CalendarSyncEvent).where(CalendarSyncEvent.id == event_id)).scalar_one_or_none()
    if not event:
        raise RuntimeError("calendar sync event not found")

    conn = (
        db.query(CalendarConnection)
        .filter(
            CalendarConnection.tenant_id == event.tenant_id,
            CalendarConnection.provider == event.provider,
            CalendarConnection.enabled.is_(True),
        )
        .order_by(CalendarConnection.id.asc())
        .first()
    )
    if conn is None:
        event.status = "failed"
        event.last_error = "No enabled calendar connection"
        event.retries = int(event.retries or 0) + 1
        event.updated_at = utc_now_naive()
        db.commit()
        raise RuntimeError("No enabled calendar connection")

    body = {
        "provider": event.provider,
        "source": event.source,
        "action": event.action,
        "visit_id": event.visit_id,
        "external_event_id": event.external_event_id,
        "payload": json.loads(event.payload_json or "{}"),
    }
    event.status = "running"
    event.updated_at = utc_now_naive()
    db.commit()
    try:
        if conn.outbound_webhook_url:
            headers = {"Content-Type": "application/json"}
            secret = _first_webhook_secret(conn.webhook_secret)
            if secret:
                headers["X-Webhook-Secret"] = secret
            response = requests.post(conn.outbound_webhook_url, json=body, headers=headers, timeout=10)
            response.raise_for_status()

        event.status = "synced"
        event.last_error = None
        event.updated_at = utc_now_naive()
        db.commit()
        return {"sync_event_id": event.id, "provider": event.provider, "sent": bool(conn.outbound_webhook_url)}
    except Exception as exc:
        event.status = "failed"
        event.retries = int(event.retries or 0) + 1
        event.last_error = str(exc)[:500]
        event.updated_at = utc_now_naive()
        db.commit()
        raise


def _handle_alert_route_delivery(db, job) -> dict:
    payload = _payload(job)
    route = payload.get("route") or {}
    alert = payload.get("alert") or {}
    channel = str(route.get("channel") or "").strip().lower()
    target = str(route.get("target") or "").strip()
    if not channel or not target:
        raise RuntimeError("Invalid alert route payload")

    message = {
        "text": f"[SalonOS:{alert.get('severity', 'info')}] {alert.get('code', 'alert')}: {alert.get('message', '')}",
        "alert": alert,
    }
    if channel in {"slack", "teams", "webhook"}:
        response = requests.post(target, json=message, timeout=10)
        response.raise_for_status()
    elif channel == "mail":
        out_dir = ROOT / "logs" / "alert_mail_fallback"
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"mail_alert_job_{job.id}.json"
        file_path.write_text(json.dumps({"to": target, "message": message}, ensure_ascii=True), encoding="utf-8")
    else:
        raise RuntimeError(f"Unsupported alert channel: {channel}")
    return {"channel": channel, "target": target}


def _handle_send_reminder(db, job) -> dict:
    payload = _payload(job)
    out_dir = ROOT / "logs" / "reminders"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"reminder_job_{job.id}.json"
    file_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    return {"stored": str(file_path)}


HANDLERS = {
    "generate_pdf_report": _handle_generate_pdf_report,
    "cleanup_retention": _handle_cleanup_retention,
    "calendar_sync_push": _handle_calendar_sync_push,
    "alert_route_delivery": _handle_alert_route_delivery,
    "send_reminder": _handle_send_reminder,
}


def process_once(queue: str, worker_id: str, batch_size: int) -> int:
    with SessionLocal() as db:
        jobs = claim_due_background_jobs(db=db, worker_id=worker_id, queue=queue, limit=batch_size)

    processed = 0
    for job in jobs:
        with SessionLocal() as db:
            try:
                handler = HANDLERS.get(job.job_type)
                if handler is None:
                    raise RuntimeError(f"Unsupported job type: {job.job_type}")
                result = handler(db, job)
                mark_background_job_success(db=db, job_id=job.id, result=result)
            except Exception as exc:
                mark_background_job_failure(db=db, job_id=job.id, error_message=str(exc))
            processed += 1
    return processed


def main() -> int:
    parser = argparse.ArgumentParser(description="SalonOS background job worker")
    parser.add_argument("--queue", default="default", help="Queue name (default/default, exports, alerts, integrations)")
    parser.add_argument("--worker-id", default=f"worker-{os.getpid()}", help="Worker identifier")
    parser.add_argument("--batch-size", type=int, default=10, help="Jobs fetched per poll")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Poll interval when queue is empty")
    parser.add_argument("--once", action="store_true", help="Process only one poll cycle and exit")
    args = parser.parse_args()

    while True:
        processed = process_once(queue=args.queue, worker_id=args.worker_id, batch_size=max(1, args.batch_size))
        if args.once:
            break
        if processed == 0:
            time.sleep(max(0.2, float(args.poll_seconds)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
