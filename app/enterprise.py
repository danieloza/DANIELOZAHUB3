import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    AlertRoute,
    AuditLog,
    BackgroundJob,
    CalendarConnection,
    CalendarSyncEvent,
    Client,
    ClientNote,
    DataRetentionPolicy,
    ReservationRateLimitEvent,
    ReservationRequest,
    ReservationStatusEvent,
    SloDefinition,
    TenantPolicy,
    TenantUserRole,
    Visit,
    VisitStatusEvent,
)
from .observability import get_ops_alerts, get_ops_metrics_snapshot
from .request_context import actor_email_ctx, actor_role_ctx

VALID_ROLES = {"owner", "manager", "reception"}
VALID_CALENDAR_PROVIDERS = {"google", "outlook"}
VALID_JOB_STATUS = {"queued", "running", "succeeded", "dead_letter", "canceled"}
SEVERITY_ORDER = {"info": 10, "low": 20, "medium": 30, "high": 40, "critical": 50}


DEFAULT_RESERVATION_STATUS_POLICY = {
    "statuses": ["new", "contacted", "confirmed", "rejected"],
    "transitions": {
        "new": ["contacted"],
        "contacted": ["confirmed", "rejected"],
        "confirmed": [],
        "rejected": [],
    },
}

DEFAULT_VISIT_STATUS_POLICY = {
    "statuses": [
        "planned",
        "confirmed",
        "arrived",
        "in_service",
        "done",
        "no_show",
        "canceled",
    ],
    "transitions": {
        "planned": ["confirmed", "arrived", "canceled", "no_show"],
        "confirmed": ["arrived", "canceled", "no_show"],
        "arrived": ["in_service", "canceled"],
        "in_service": ["done", "canceled"],
        "done": [],
        "no_show": ["confirmed", "canceled"],
        "canceled": ["planned", "confirmed"],
    },
}

DEFAULT_SLOT_POLICY = {
    "buffer_multiplier": 1.0,
}

DEFAULT_SLA_POLICY = {
    "contact_minutes": 60,
}

DEFAULT_RETENTION_POLICY = {
    "client_notes_days": 365,
    "audit_logs_days": 365,
    "status_events_days": 365,
    "rate_limit_events_hours": 24,
}


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    return email or None


def _normalize_role(value: str | None) -> str | None:
    role = (value or "").strip().lower()
    if role in VALID_ROLES:
        return role
    return None


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload or {}, ensure_ascii=True, sort_keys=True)


def _json_loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )


def _calendar_webhook_secrets(raw: str | None) -> list[str]:
    items = []
    for part in str(raw or "").split(","):
        value = part.strip()
        if value:
            items.append(value)
    return items


def _secret_matches_any(incoming: str | None, expected: list[str]) -> bool:
    candidate = (incoming or "").strip()
    if not candidate:
        return False
    for exp in expected:
        if hmac.compare_digest(exp, candidate):
            return True
    return False


def upsert_tenant_user_role(
    db: Session,
    tenant_id: int,
    email: str,
    role: str,
) -> TenantUserRole:
    normalized_email = _normalize_email(email)
    normalized_role = _normalize_role(role)
    if not normalized_email:
        raise ValueError("email is required")
    if not normalized_role:
        raise ValueError("Invalid role")

    row = db.execute(
        select(TenantUserRole).where(
            TenantUserRole.tenant_id == tenant_id,
            TenantUserRole.email == normalized_email,
        )
    ).scalar_one_or_none()
    if row is None:
        row = TenantUserRole(
            tenant_id=tenant_id,
            email=normalized_email,
            role=normalized_role,
            created_at=utc_now_naive(),
            updated_at=utc_now_naive(),
        )
        db.add(row)
    else:
        row.role = normalized_role
        row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def list_tenant_user_roles(db: Session, tenant_id: int) -> list[TenantUserRole]:
    return (
        db.query(TenantUserRole)
        .filter(TenantUserRole.tenant_id == tenant_id)
        .order_by(TenantUserRole.email.asc())
        .all()
    )


def resolve_actor_role(
    db: Session,
    tenant_id: int,
    actor_email: str | None,
    actor_role_hint: str | None = None,
) -> str:
    normalized_hint = _normalize_role(actor_role_hint)
    normalized_email = _normalize_email(actor_email)
    if normalized_email:
        row = db.execute(
            select(TenantUserRole).where(
                TenantUserRole.tenant_id == tenant_id,
                TenantUserRole.email == normalized_email,
            )
        ).scalar_one_or_none()
        if row and _normalize_role(row.role):
            return row.role
    if normalized_hint:
        return normalized_hint
    default_role = _normalize_role(getattr(settings, "DEFAULT_ACTOR_ROLE", "reception"))
    return default_role or "reception"


def require_actor(
    db: Session,
    tenant_id: int,
    actor_email: str | None,
    actor_role_hint: str | None,
    allowed_roles: set[str] | None = None,
) -> tuple[str, str]:
    normalized_email = _normalize_email(actor_email or actor_email_ctx.get())
    actor_role_hint = actor_role_hint or actor_role_ctx.get()
    if not normalized_email:
        raise ValueError("Actor identity is required (X-Actor-Email or Bearer token)")
    role = resolve_actor_role(db, tenant_id, normalized_email, actor_role_hint)
    if allowed_roles and role not in allowed_roles:
        raise PermissionError(f"Actor role '{role}' cannot perform this operation")
    return normalized_email, role


def write_audit_log(
    db: Session,
    tenant_id: int,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    request_id: str | None = None,
    payload: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        tenant_id=tenant_id,
        actor_email=_normalize_email(actor_email),
        actor_role=_normalize_role(actor_role),
        action=(action or "").strip(),
        resource_type=(resource_type or "").strip(),
        resource_id=(str(resource_id) if resource_id is not None else None),
        request_id=(request_id or "").strip() or None,
        payload_json=_json_dumps(payload),
        created_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_audit_logs(
    db: Session,
    tenant_id: int,
    limit: int = 200,
    action: str | None = None,
    actor_email: str | None = None,
    resource_type: str | None = None,
    since_minutes: int | None = None,
) -> list[AuditLog]:
    q = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
    if action:
        q = q.filter(AuditLog.action == action.strip())
    if actor_email:
        q = q.filter(AuditLog.actor_email == _normalize_email(actor_email))
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type.strip())
    if since_minutes is not None:
        cutoff = utc_now_naive() - timedelta(minutes=max(1, int(since_minutes)))
        q = q.filter(AuditLog.created_at >= cutoff)
    return (
        q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(max(1, min(int(limit), 1000)))
        .all()
    )


def _get_policy_default(policy_key: str) -> dict:
    defaults = {
        "reservation_status_policy": DEFAULT_RESERVATION_STATUS_POLICY,
        "visit_status_policy": DEFAULT_VISIT_STATUS_POLICY,
        "slot_policy": DEFAULT_SLOT_POLICY,
        "sla_policy": DEFAULT_SLA_POLICY,
    }
    return json.loads(json.dumps(defaults.get(policy_key, {})))


def get_tenant_policy(db: Session, tenant_id: int, policy_key: str) -> dict:
    row = db.execute(
        select(TenantPolicy).where(
            TenantPolicy.tenant_id == tenant_id,
            TenantPolicy.key == policy_key.strip(),
        )
    ).scalar_one_or_none()
    default_value = _get_policy_default(policy_key)
    if not row:
        return default_value
    value = _json_loads(row.value_json, default_value)
    return value if isinstance(value, dict) else default_value


def upsert_tenant_policy(
    db: Session,
    tenant_id: int,
    policy_key: str,
    value: dict,
    actor_email: str | None = None,
) -> TenantPolicy:
    key = (policy_key or "").strip()
    if not key:
        raise ValueError("policy_key is required")
    if not isinstance(value, dict):
        raise ValueError("policy value must be an object")

    row = db.execute(
        select(TenantPolicy).where(
            TenantPolicy.tenant_id == tenant_id,
            TenantPolicy.key == key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = TenantPolicy(
            tenant_id=tenant_id,
            key=key,
            value_json=_json_dumps(value),
            updated_by=_normalize_email(actor_email),
            updated_at=utc_now_naive(),
        )
        db.add(row)
    else:
        row.value_json = _json_dumps(value)
        row.updated_by = _normalize_email(actor_email)
        row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def get_policy_status_config(
    db: Session, tenant_id: int, policy_key: str
) -> tuple[set[str], dict[str, set[str]]]:
    raw = get_tenant_policy(db, tenant_id, policy_key)
    statuses = {
        str(x).strip().lower() for x in raw.get("statuses", []) if str(x).strip()
    }
    transitions_raw = raw.get("transitions", {})
    transitions: dict[str, set[str]] = {}
    if isinstance(transitions_raw, dict):
        for source, targets in transitions_raw.items():
            source_key = str(source).strip().lower()
            if not source_key:
                continue
            target_set = {
                str(x).strip().lower() for x in (targets or []) if str(x).strip()
            }
            transitions[source_key] = target_set
    return statuses, transitions


def get_slot_buffer_multiplier(db: Session, tenant_id: int) -> float:
    raw = get_tenant_policy(db, tenant_id, "slot_policy")
    value = raw.get("buffer_multiplier", 1.0)
    try:
        parsed = float(value)
    except Exception:
        parsed = 1.0
    return max(0.0, min(parsed, 5.0))


def get_sla_contact_minutes(db: Session, tenant_id: int) -> int:
    raw = get_tenant_policy(db, tenant_id, "sla_policy")
    value = raw.get("contact_minutes", DEFAULT_SLA_POLICY["contact_minutes"])
    try:
        parsed = int(value)
    except Exception:
        parsed = DEFAULT_SLA_POLICY["contact_minutes"]
    return max(1, min(parsed, 24 * 60))


def enqueue_background_job(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    tenant_id: int | None = None,
    queue: str = "default",
    max_attempts: int = 5,
    run_after: datetime | None = None,
) -> BackgroundJob:
    row = BackgroundJob(
        tenant_id=tenant_id,
        queue=(queue or "default").strip(),
        job_type=(job_type or "").strip(),
        payload_json=_json_dumps(payload),
        status="queued",
        attempts=0,
        max_attempts=max(1, min(int(max_attempts), 20)),
        run_after=run_after or utc_now_naive(),
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_background_jobs(
    db: Session,
    tenant_id: int | None = None,
    queue: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[BackgroundJob]:
    q = db.query(BackgroundJob)
    if tenant_id is not None:
        q = q.filter(BackgroundJob.tenant_id == tenant_id)
    if queue:
        q = q.filter(BackgroundJob.queue == queue.strip())
    if status:
        q = q.filter(BackgroundJob.status == status.strip())
    return (
        q.order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )


def get_background_jobs_health(
    db: Session,
    tenant_id: int | None = None,
    stale_running_minutes: int = 15,
) -> dict:
    now = utc_now_naive()
    stale_cutoff = now - timedelta(minutes=max(1, int(stale_running_minutes)))
    q = db.query(BackgroundJob)
    if tenant_id is not None:
        q = q.filter(BackgroundJob.tenant_id == tenant_id)
    rows = q.all()

    queued = [r for r in rows if r.status == "queued"]
    running = [r for r in rows if r.status == "running"]
    dead_letter = [r for r in rows if r.status == "dead_letter"]
    succeeded = [r for r in rows if r.status == "succeeded"]

    due_queued = [r for r in queued if (r.run_after or now) <= now]
    stale_running = [r for r in running if (r.updated_at or now) <= stale_cutoff]

    oldest_queued = min((r.run_after or now) for r in queued) if queued else None
    oldest_queued_age_sec = (
        int((now - oldest_queued).total_seconds()) if oldest_queued else 0
    )

    return {
        "tenant_id": (int(tenant_id) if tenant_id is not None else None),
        "checked_at": now,
        "queued_count": int(len(queued)),
        "running_count": int(len(running)),
        "succeeded_count": int(len(succeeded)),
        "dead_letter_count": int(len(dead_letter)),
        "due_queued_count": int(len(due_queued)),
        "stale_running_count": int(len(stale_running)),
        "oldest_queued_age_seconds": int(max(0, oldest_queued_age_sec)),
    }


def build_background_job_alerts(health: dict) -> list[dict]:
    alerts: list[dict] = []
    if int(health.get("dead_letter_count", 0)) > 0:
        alerts.append(
            {
                "code": "jobs_dead_letter_detected",
                "severity": "high",
                "message": f"Detected {int(health.get('dead_letter_count', 0))} dead-letter jobs",
            }
        )
    if int(health.get("stale_running_count", 0)) > 0:
        alerts.append(
            {
                "code": "jobs_stale_running_detected",
                "severity": "high",
                "message": f"Detected {int(health.get('stale_running_count', 0))} stale running jobs",
            }
        )
    if int(health.get("due_queued_count", 0)) >= 50:
        alerts.append(
            {
                "code": "jobs_queue_backlog_detected",
                "severity": "medium",
                "message": f"Detected backlog of {int(health.get('due_queued_count', 0))} due queued jobs",
            }
        )
    return alerts


def claim_due_background_jobs(
    db: Session,
    worker_id: str,
    queue: str = "default",
    limit: int = 20,
) -> list[BackgroundJob]:
    now = utc_now_naive()
    rows = (
        db.query(BackgroundJob)
        .filter(
            BackgroundJob.status == "queued",
            BackgroundJob.queue == queue.strip(),
            BackgroundJob.run_after <= now,
        )
        .order_by(BackgroundJob.run_after.asc(), BackgroundJob.id.asc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    for row in rows:
        row.status = "running"
        row.worker_id = (worker_id or "").strip()[:80] or "worker"
        row.attempts = int(row.attempts or 0) + 1
        row.updated_at = now
    db.commit()
    return rows


def _retry_backoff_seconds(attempt: int) -> int:
    attempt_i = max(1, int(attempt))
    return min(3600, int(30 * (2 ** (attempt_i - 1))))


def mark_background_job_success(
    db: Session,
    job_id: int,
    result: dict | None = None,
) -> BackgroundJob | None:
    row = db.execute(
        select(BackgroundJob).where(BackgroundJob.id == job_id)
    ).scalar_one_or_none()
    if not row:
        return None
    row.status = "succeeded"
    row.result_json = _json_dumps(result)
    row.finished_at = utc_now_naive()
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def mark_background_job_failure(
    db: Session,
    job_id: int,
    error_message: str,
) -> BackgroundJob | None:
    row = db.execute(
        select(BackgroundJob).where(BackgroundJob.id == job_id)
    ).scalar_one_or_none()
    if not row:
        return None
    row.last_error = (error_message or "").strip()[:500] or "Unknown error"
    row.updated_at = utc_now_naive()
    if int(row.attempts or 0) >= int(row.max_attempts or 1):
        row.status = "dead_letter"
        row.finished_at = utc_now_naive()
    else:
        row.status = "queued"
        row.run_after = utc_now_naive() + timedelta(
            seconds=_retry_backoff_seconds(int(row.attempts or 1))
        )
    db.commit()
    db.refresh(row)
    return row


def retry_dead_letter_job(db: Session, job_id: int) -> BackgroundJob | None:
    row = db.execute(
        select(BackgroundJob).where(BackgroundJob.id == job_id)
    ).scalar_one_or_none()
    if not row:
        return None
    if row.status != "dead_letter":
        return row
    row.status = "queued"
    row.attempts = 0
    row.last_error = None
    row.result_json = None
    row.finished_at = None
    row.run_after = utc_now_naive()
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def cancel_queued_background_job(
    db: Session,
    tenant_id: int,
    job_id: int,
) -> BackgroundJob | None:
    row = db.execute(
        select(BackgroundJob).where(
            BackgroundJob.id == job_id,
            BackgroundJob.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if not row:
        return None
    if row.status != "queued":
        return row
    row.status = "canceled"
    row.last_error = "Canceled by operator"
    row.finished_at = utc_now_naive()
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def cleanup_background_jobs(
    db: Session,
    tenant_id: int,
    statuses: list[str] | None = None,
    older_than_hours: int = 24 * 7,
) -> dict:
    target_statuses = [
        str(s).strip().lower()
        for s in (statuses or ["succeeded", "dead_letter", "canceled"])
        if str(s).strip()
    ]
    if not target_statuses:
        target_statuses = ["succeeded", "dead_letter", "canceled"]
    cutoff = utc_now_naive() - timedelta(hours=max(1, int(older_than_hours)))
    q = db.query(BackgroundJob).filter(
        BackgroundJob.tenant_id == tenant_id,
        BackgroundJob.status.in_(target_statuses),
        BackgroundJob.updated_at < cutoff,
    )
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return {
        "tenant_id": int(tenant_id),
        "deleted_jobs": int(deleted or 0),
        "statuses": target_statuses,
        "cutoff": cutoff,
    }


def upsert_calendar_connection(
    db: Session,
    tenant_id: int,
    provider: str,
    external_calendar_id: str,
    sync_direction: str = "bidirectional",
    webhook_secret: str | None = None,
    outbound_webhook_url: str | None = None,
    enabled: bool = True,
) -> CalendarConnection:
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider not in VALID_CALENDAR_PROVIDERS:
        raise ValueError("Unsupported calendar provider")
    ext_id = (external_calendar_id or "").strip()
    if not ext_id:
        raise ValueError("external_calendar_id is required")

    row = db.execute(
        select(CalendarConnection).where(
            CalendarConnection.tenant_id == tenant_id,
            CalendarConnection.provider == normalized_provider,
            CalendarConnection.external_calendar_id == ext_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = CalendarConnection(
            tenant_id=tenant_id,
            provider=normalized_provider,
            external_calendar_id=ext_id,
            created_at=utc_now_naive(),
            updated_at=utc_now_naive(),
        )
        db.add(row)

    row.sync_direction = (sync_direction or "bidirectional").strip().lower()
    row.webhook_secret = (webhook_secret or "").strip() or None
    row.outbound_webhook_url = (outbound_webhook_url or "").strip() or None
    row.enabled = bool(enabled)
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def list_calendar_connections(
    db: Session, tenant_id: int, provider: str | None = None
) -> list[CalendarConnection]:
    q = db.query(CalendarConnection).filter(CalendarConnection.tenant_id == tenant_id)
    if provider:
        q = q.filter(CalendarConnection.provider == provider.strip().lower())
    return q.order_by(
        CalendarConnection.provider.asc(), CalendarConnection.id.asc()
    ).all()


def enqueue_calendar_sync_event(
    db: Session,
    tenant_id: int,
    provider: str,
    action: str,
    payload: dict,
    visit_id: int | None = None,
    source: str = "salonos",
    external_event_id: str | None = None,
) -> CalendarSyncEvent:
    row = CalendarSyncEvent(
        tenant_id=tenant_id,
        provider=(provider or "").strip().lower(),
        source=(source or "salonos").strip().lower(),
        external_event_id=(external_event_id or "").strip() or None,
        visit_id=visit_id,
        action=(action or "").strip(),
        payload_json=_json_dumps(payload),
        status="pending",
        retries=0,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    enqueue_background_job(
        db=db,
        job_type="calendar_sync_push",
        payload={"sync_event_id": row.id},
        tenant_id=tenant_id,
        queue="integrations",
        max_attempts=8,
    )
    return row


def list_calendar_sync_events(
    db: Session,
    tenant_id: int,
    status: str | None = None,
    limit: int = 200,
) -> list[CalendarSyncEvent]:
    q = db.query(CalendarSyncEvent).filter(CalendarSyncEvent.tenant_id == tenant_id)
    if status:
        q = q.filter(CalendarSyncEvent.status == status.strip())
    return (
        q.order_by(CalendarSyncEvent.created_at.desc(), CalendarSyncEvent.id.desc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )


def replay_calendar_sync_event(
    db: Session,
    tenant_id: int,
    event_id: int,
) -> CalendarSyncEvent | None:
    row = db.execute(
        select(CalendarSyncEvent).where(
            CalendarSyncEvent.id == event_id,
            CalendarSyncEvent.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if not row:
        return None
    payload = _json_loads(row.payload_json, {})
    if not isinstance(payload, dict):
        payload = {}
    payload["replay_of_event_id"] = int(row.id)
    replay_action = f"{row.action}_replay"
    return enqueue_calendar_sync_event(
        db=db,
        tenant_id=tenant_id,
        provider=row.provider,
        action=replay_action,
        payload=payload,
        visit_id=row.visit_id,
        source="salonos",
        external_event_id=None,
    )


def _verify_calendar_webhook_signature(
    *,
    expected_secret: str,
    payload: dict,
    webhook_timestamp: str | None,
    webhook_signature: str | None,
) -> bool:
    incoming_sig = (webhook_signature or "").strip().lower()
    if incoming_sig.startswith("sha256="):
        incoming_sig = incoming_sig[7:].strip()
    if not incoming_sig:
        if bool(settings.CALENDAR_WEBHOOK_SIGNATURE_REQUIRED):
            raise PermissionError("Missing calendar webhook signature")
        return False

    ts_raw = (webhook_timestamp or "").strip()
    if not ts_raw:
        raise PermissionError("Missing webhook timestamp")
    try:
        ts = int(ts_raw)
    except Exception:
        raise PermissionError("Invalid webhook timestamp")

    now_ts = int(datetime.now(timezone.utc).timestamp())
    ttl = max(30, int(settings.CALENDAR_WEBHOOK_SIGNATURE_TTL_SECONDS))
    if abs(now_ts - ts) > ttl:
        raise PermissionError("Expired webhook timestamp")

    signed_payload = f"{ts_raw}.{_canonical_json(payload)}"
    expected_sig = hmac.new(
        expected_secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_sig, incoming_sig):
        raise PermissionError("Invalid calendar webhook signature")
    return True


def ingest_calendar_webhook(
    db: Session,
    provider: str,
    webhook_secret: str | None,
    payload: dict,
    webhook_timestamp: str | None = None,
    webhook_signature: str | None = None,
) -> CalendarSyncEvent:
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider not in VALID_CALENDAR_PROVIDERS:
        raise ValueError("Unsupported provider")

    conn = (
        db.query(CalendarConnection)
        .filter(
            CalendarConnection.provider == normalized_provider,
            CalendarConnection.enabled.is_(True),
        )
        .order_by(CalendarConnection.id.asc())
        .first()
    )
    if conn is None:
        raise ValueError("Calendar provider is not configured")

    expected_secrets = _calendar_webhook_secrets(conn.webhook_secret)
    incoming = (webhook_secret or "").strip()
    if expected_secrets:
        signature_required = bool(settings.CALENDAR_WEBHOOK_SIGNATURE_REQUIRED)
        signature_ok = False
        last_error: Exception | None = None
        if (webhook_signature or "").strip() or signature_required:
            for secret in expected_secrets:
                try:
                    if _verify_calendar_webhook_signature(
                        expected_secret=secret,
                        payload=payload,
                        webhook_timestamp=webhook_timestamp,
                        webhook_signature=webhook_signature,
                    ):
                        signature_ok = True
                        break
                except PermissionError as exc:
                    last_error = exc
            if not signature_ok and last_error is not None and signature_required:
                raise last_error
        if not signature_ok and signature_required:
            raise PermissionError("Missing or invalid calendar webhook signature")
        if (
            not signature_ok
            and not signature_required
            and not _secret_matches_any(incoming, expected_secrets)
        ):
            raise PermissionError("Invalid calendar webhook secret")

    external_event_id = (
        str(payload.get("id") or payload.get("event_id") or "").strip() or None
    )
    action = str(payload.get("action") or "webhook_update").strip() or "webhook_update"
    if external_event_id:
        existing = db.execute(
            select(CalendarSyncEvent).where(
                CalendarSyncEvent.tenant_id == conn.tenant_id,
                CalendarSyncEvent.provider == normalized_provider,
                CalendarSyncEvent.source == "external",
                CalendarSyncEvent.external_event_id == external_event_id,
                CalendarSyncEvent.action == action,
            )
        ).scalar_one_or_none()
        if existing:
            return existing
    return enqueue_calendar_sync_event(
        db=db,
        tenant_id=conn.tenant_id,
        provider=normalized_provider,
        action=action,
        payload=payload,
        visit_id=None,
        source="external",
        external_event_id=external_event_id,
    )


def get_or_create_retention_policy(db: Session, tenant_id: int) -> DataRetentionPolicy:
    row = db.execute(
        select(DataRetentionPolicy).where(DataRetentionPolicy.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if row:
        return row
    row = DataRetentionPolicy(
        tenant_id=tenant_id,
        client_notes_days=DEFAULT_RETENTION_POLICY["client_notes_days"],
        audit_logs_days=DEFAULT_RETENTION_POLICY["audit_logs_days"],
        status_events_days=DEFAULT_RETENTION_POLICY["status_events_days"],
        rate_limit_events_hours=DEFAULT_RETENTION_POLICY["rate_limit_events_hours"],
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_retention_policy(
    db: Session,
    tenant_id: int,
    client_notes_days: int,
    audit_logs_days: int,
    status_events_days: int,
    rate_limit_events_hours: int,
    actor_email: str | None = None,
) -> DataRetentionPolicy:
    row = get_or_create_retention_policy(db, tenant_id)
    row.client_notes_days = max(1, min(int(client_notes_days), 3650))
    row.audit_logs_days = max(1, min(int(audit_logs_days), 3650))
    row.status_events_days = max(1, min(int(status_events_days), 3650))
    row.rate_limit_events_hours = max(1, min(int(rate_limit_events_hours), 24 * 365))
    row.updated_by = _normalize_email(actor_email)
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def run_retention_cleanup(db: Session, tenant_id: int) -> dict:
    policy = get_or_create_retention_policy(db, tenant_id)
    now = utc_now_naive()
    notes_cutoff = now - timedelta(days=int(policy.client_notes_days))
    audit_cutoff = now - timedelta(days=int(policy.audit_logs_days))
    events_cutoff = now - timedelta(days=int(policy.status_events_days))
    rl_cutoff = now - timedelta(hours=int(policy.rate_limit_events_hours))

    deleted_notes = (
        db.execute(
            delete(ClientNote).where(
                ClientNote.tenant_id == tenant_id,
                ClientNote.created_at < notes_cutoff,
            )
        ).rowcount
        or 0
    )
    deleted_audit = (
        db.execute(
            delete(AuditLog).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.created_at < audit_cutoff,
            )
        ).rowcount
        or 0
    )
    deleted_res_status = (
        db.execute(
            delete(ReservationStatusEvent).where(
                ReservationStatusEvent.tenant_id == tenant_id,
                ReservationStatusEvent.created_at < events_cutoff,
            )
        ).rowcount
        or 0
    )
    deleted_visit_status = (
        db.execute(
            delete(VisitStatusEvent).where(
                VisitStatusEvent.tenant_id == tenant_id,
                VisitStatusEvent.created_at < events_cutoff,
            )
        ).rowcount
        or 0
    )
    deleted_rl = (
        db.execute(
            delete(ReservationRateLimitEvent).where(
                ReservationRateLimitEvent.tenant_id == tenant_id,
                ReservationRateLimitEvent.created_at < rl_cutoff,
            )
        ).rowcount
        or 0
    )
    db.commit()
    return {
        "tenant_id": int(tenant_id),
        "deleted_client_notes": int(deleted_notes),
        "deleted_audit_logs": int(deleted_audit),
        "deleted_reservation_status_events": int(deleted_res_status),
        "deleted_visit_status_events": int(deleted_visit_status),
        "deleted_rate_limit_events": int(deleted_rl),
        "checked_at": utc_now_naive(),
    }


def preview_retention_cleanup(db: Session, tenant_id: int) -> dict:
    policy = get_or_create_retention_policy(db, tenant_id)
    now = utc_now_naive()
    notes_cutoff = now - timedelta(days=int(policy.client_notes_days))
    audit_cutoff = now - timedelta(days=int(policy.audit_logs_days))
    events_cutoff = now - timedelta(days=int(policy.status_events_days))
    rl_cutoff = now - timedelta(hours=int(policy.rate_limit_events_hours))

    would_delete_notes = db.execute(
        select(func.count(ClientNote.id)).where(
            ClientNote.tenant_id == tenant_id,
            ClientNote.created_at < notes_cutoff,
        )
    ).scalar_one()
    would_delete_audit = db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.created_at < audit_cutoff,
        )
    ).scalar_one()
    would_delete_res_status = db.execute(
        select(func.count(ReservationStatusEvent.id)).where(
            ReservationStatusEvent.tenant_id == tenant_id,
            ReservationStatusEvent.created_at < events_cutoff,
        )
    ).scalar_one()
    would_delete_visit_status = db.execute(
        select(func.count(VisitStatusEvent.id)).where(
            VisitStatusEvent.tenant_id == tenant_id,
            VisitStatusEvent.created_at < events_cutoff,
        )
    ).scalar_one()
    would_delete_rl = db.execute(
        select(func.count(ReservationRateLimitEvent.id)).where(
            ReservationRateLimitEvent.tenant_id == tenant_id,
            ReservationRateLimitEvent.created_at < rl_cutoff,
        )
    ).scalar_one()

    return {
        "tenant_id": int(tenant_id),
        "would_delete_client_notes": int(would_delete_notes or 0),
        "would_delete_audit_logs": int(would_delete_audit or 0),
        "would_delete_reservation_status_events": int(would_delete_res_status or 0),
        "would_delete_visit_status_events": int(would_delete_visit_status or 0),
        "would_delete_rate_limit_events": int(would_delete_rl or 0),
        "checked_at": utc_now_naive(),
    }


def anonymize_client_data(db: Session, tenant_id: int, client_id: int) -> Client | None:
    client = db.execute(
        select(Client).where(Client.tenant_id == tenant_id, Client.id == client_id)
    ).scalar_one_or_none()
    if not client:
        return None

    old_name = client.name
    old_phone = client.phone
    client.name = f"anon-client-{client.id}"
    client.phone = None

    db.execute(
        update(ClientNote)
        .where(ClientNote.tenant_id == tenant_id, ClientNote.client_id == client.id)
        .values(note="[redacted]")
    )

    if old_name:
        q = update(ReservationRequest).where(
            ReservationRequest.tenant_id == tenant_id,
            ReservationRequest.client_name == old_name,
        )
        if old_phone:
            q = q.where(ReservationRequest.phone == old_phone)
        db.execute(
            q.values(
                client_name=f"anon-client-{client.id}", phone=None, note="[redacted]"
            )
        )

    db.commit()
    db.refresh(client)
    return client


def delete_client_if_possible(
    db: Session, tenant_id: int, client_id: int
) -> tuple[bool, str]:
    client = db.execute(
        select(Client).where(Client.tenant_id == tenant_id, Client.id == client_id)
    ).scalar_one_or_none()
    if not client:
        return False, "Client not found"

    visits_count = db.execute(
        select(func.count(Visit.id)).where(
            Visit.tenant_id == tenant_id, Visit.client_id == client.id
        )
    ).scalar_one()
    if int(visits_count or 0) > 0:
        return False, "Client has visits; use anonymization instead of delete"

    db.execute(
        delete(ClientNote).where(
            ClientNote.tenant_id == tenant_id,
            ClientNote.client_id == client.id,
        )
    )
    db.delete(client)
    db.commit()
    return True, "deleted"


def upsert_slo_definition(
    db: Session,
    tenant_id: int,
    name: str,
    metric_type: str,
    target: float,
    window_minutes: int,
    enabled: bool = True,
) -> SloDefinition:
    normalized_name = (name or "").strip()
    normalized_metric = (metric_type or "").strip().lower()
    if not normalized_name:
        raise ValueError("name is required")
    if normalized_metric not in {
        "latency_p95_ms",
        "error_rate_5xx",
        "integrity_issues",
    }:
        raise ValueError("Unsupported metric_type")

    row = db.execute(
        select(SloDefinition).where(
            SloDefinition.tenant_id == tenant_id,
            SloDefinition.name == normalized_name,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SloDefinition(
            tenant_id=tenant_id,
            name=normalized_name,
            metric_type=normalized_metric,
            created_at=utc_now_naive(),
            updated_at=utc_now_naive(),
        )
        db.add(row)
    row.target = float(target)
    row.window_minutes = max(1, min(int(window_minutes), 1440))
    row.enabled = bool(enabled)
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def list_slo_definitions(db: Session, tenant_id: int) -> list[SloDefinition]:
    rows = (
        db.query(SloDefinition)
        .filter(SloDefinition.tenant_id == tenant_id)
        .order_by(SloDefinition.name.asc())
        .all()
    )
    if rows:
        return rows
    seeded = [
        ("latency_p95", "latency_p95_ms", 1200.0, 15, True),
        ("error_rate_5xx", "error_rate_5xx", 0.01, 15, True),
        ("integrity", "integrity_issues", 0.0, 15, True),
    ]
    out = []
    for name, metric, target, window, enabled in seeded:
        out.append(
            upsert_slo_definition(
                db=db,
                tenant_id=tenant_id,
                name=name,
                metric_type=metric,
                target=target,
                window_minutes=window,
                enabled=enabled,
            )
        )
    return out


def evaluate_slos(db: Session, tenant_id: int) -> list[dict]:
    # local import avoids circular import with services->enterprise usage
    from .services import get_conversion_integrity_report

    rows = list_slo_definitions(db, tenant_id)
    out: list[dict] = []
    for row in rows:
        if not bool(row.enabled):
            continue
        metrics = get_ops_metrics_snapshot(window_minutes=int(row.window_minutes))
        integrity = get_conversion_integrity_report(
            db=db, tenant_id=tenant_id, limit=100
        )
        requests_total = int(metrics.get("requests_total", 0))
        error_rate = (
            float(metrics.get("error_5xx_count", 0)) / float(requests_total)
            if requests_total > 0
            else 0.0
        )

        metric_type = (row.metric_type or "").strip().lower()
        current_value = 0.0
        target = float(row.target or 0)
        ok = True
        if metric_type == "latency_p95_ms":
            current_value = float(metrics.get("latency_ms_p95", 0.0))
            ok = current_value <= target
        elif metric_type == "error_rate_5xx":
            current_value = float(error_rate)
            ok = current_value <= target
        elif metric_type == "integrity_issues":
            current_value = float(integrity.get("issues_count", 0))
            ok = current_value <= target

        out.append(
            {
                "name": row.name,
                "metric_type": metric_type,
                "window_minutes": int(row.window_minutes),
                "target": target,
                "current": round(current_value, 6),
                "ok": bool(ok),
                "checked_at": utc_now_naive(),
            }
        )
    return out


def upsert_alert_route(
    db: Session,
    tenant_id: int,
    channel: str,
    target: str,
    min_severity: str = "medium",
    enabled: bool = True,
) -> AlertRoute:
    normalized_channel = (channel or "").strip().lower()
    normalized_target = (target or "").strip()
    severity = (min_severity or "medium").strip().lower()
    if not normalized_channel:
        raise ValueError("channel is required")
    if not normalized_target:
        raise ValueError("target is required")
    if severity not in SEVERITY_ORDER:
        raise ValueError("Invalid min_severity")

    row = (
        db.query(AlertRoute)
        .filter(
            AlertRoute.tenant_id == tenant_id,
            AlertRoute.channel == normalized_channel,
            AlertRoute.target == normalized_target,
        )
        .first()
    )
    if row is None:
        row = AlertRoute(
            tenant_id=tenant_id,
            channel=normalized_channel,
            target=normalized_target,
            created_at=utc_now_naive(),
            updated_at=utc_now_naive(),
        )
        db.add(row)
    row.min_severity = severity
    row.enabled = bool(enabled)
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def list_alert_routes(db: Session, tenant_id: int) -> list[AlertRoute]:
    return (
        db.query(AlertRoute)
        .filter(AlertRoute.tenant_id == tenant_id)
        .order_by(AlertRoute.channel.asc(), AlertRoute.id.asc())
        .all()
    )


def dispatch_alerts_to_routes(
    db: Session,
    tenant_id: int,
    window_minutes: int = 15,
) -> dict:
    # local import avoids circular import with services->enterprise usage
    from .platform import get_outbox_health
    from .services import get_conversion_integrity_report

    integrity = get_conversion_integrity_report(db=db, tenant_id=tenant_id, limit=100)
    alerts = get_ops_alerts(
        window_minutes=window_minutes,
        integrity_issues_count=int(integrity.get("issues_count", 0)),
    )
    jobs_health = get_background_jobs_health(
        db=db, tenant_id=tenant_id, stale_running_minutes=15
    )
    jobs_alerts = build_background_job_alerts(jobs_health)
    if jobs_alerts:
        alerts = [a for a in alerts if str(a.get("code")) != "ops_ok"]
        alerts.extend(jobs_alerts)
    outbox_health = get_outbox_health(db=db, tenant_id=tenant_id)
    if int(outbox_health.get("dead_letter_count", 0)) > 0:
        alerts = [a for a in alerts if str(a.get("code")) != "ops_ok"]
        alerts.append(
            {
                "code": "outbox_dead_letter_detected",
                "severity": "high",
                "message": f"Detected {int(outbox_health.get('dead_letter_count', 0))} outbox dead-letter events",
            }
        )
    routes = [r for r in list_alert_routes(db, tenant_id) if bool(r.enabled)]
    dispatched = 0
    for route in routes:
        route_min = SEVERITY_ORDER.get(
            (route.min_severity or "medium").strip().lower(), 30
        )
        for alert in alerts:
            alert_sev = SEVERITY_ORDER.get(
                str(alert.get("severity", "info")).lower(), 10
            )
            if alert_sev < route_min:
                continue
            enqueue_background_job(
                db=db,
                tenant_id=tenant_id,
                queue="alerts",
                job_type="alert_route_delivery",
                payload={
                    "route": {"channel": route.channel, "target": route.target},
                    "alert": alert,
                },
                max_attempts=4,
            )
            dispatched += 1
    return {
        "alerts_count": len(alerts),
        "routes_count": len(routes),
        "dispatched_jobs": int(dispatched),
    }
