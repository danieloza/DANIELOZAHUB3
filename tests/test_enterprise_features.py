import hashlib
import hmac
import json
import time
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api import get_db, public_router, router
from app.config import settings
from app.db import Base
from app.enterprise import enqueue_background_job, utc_now_naive
from app.models import BackgroundJob, Tenant


def make_client(tmp_path):
    db_path = tmp_path / "test_salonos_enterprise.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    client.testing_session_local = testing_session_local
    return client


def _owner_headers(tenant: str) -> dict:
    return {
        "X-Tenant-Slug": tenant,
        "X-Actor-Email": "owner@salonos.local",
        "X-Actor-Role": "owner",
    }


def test_enterprise_endpoints_smoke(tmp_path):
    client = make_client(tmp_path)
    tenant = "ent-smoke"

    seed = client.post(
        "/api/visits",
        headers=_owner_headers(tenant),
        json={
            "dt": "2026-03-10T10:00:00",
            "client_name": "Enterprise Seed",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 210,
        },
    )
    assert seed.status_code == 200

    role_set = client.post(
        "/api/rbac/roles",
        headers=_owner_headers(tenant),
        json={"email": "manager@salonos.local", "role": "manager"},
    )
    assert role_set.status_code == 200

    policy_set = client.put(
        "/api/policies/slot_policy",
        headers=_owner_headers(tenant),
        json={"value": {"buffer_multiplier": 1.2}},
    )
    assert policy_set.status_code == 200
    assert policy_set.json()["value"]["buffer_multiplier"] == 1.2

    job = client.post(
        "/api/jobs",
        headers=_owner_headers(tenant),
        json={
            "job_type": "send_reminder",
            "payload": {"reservation_id": 1},
            "queue": "default",
            "max_attempts": 3,
        },
    )
    assert job.status_code == 200

    conn = client.post(
        "/api/integrations/calendar/connections",
        headers=_owner_headers(tenant),
        json={
            "provider": "google",
            "external_calendar_id": "main",
            "sync_direction": "bidirectional",
            "webhook_secret": "top-secret",
            "enabled": True,
        },
    )
    assert conn.status_code == 200
    assert conn.json()["webhook_secret"] != "top-secret"
    assert "*" in (conn.json()["webhook_secret"] or "")

    hook = client.post(
        "/api/integrations/calendar/webhooks/google",
        headers={"X-Webhook-Secret": "top-secret"},
        json={"id": "evt-1", "action": "updated"},
    )
    assert hook.status_code == 200

    slo = client.post(
        "/api/ops/slo",
        headers=_owner_headers(tenant),
        json={
            "name": "lat95",
            "metric_type": "latency_p95_ms",
            "target": 1500,
            "window_minutes": 15,
            "enabled": True,
        },
    )
    assert slo.status_code == 200

    routes = client.post(
        "/api/ops/alerts/routes",
        headers=_owner_headers(tenant),
        json={
            "channel": "mail",
            "target": "alerts@example.com",
            "min_severity": "medium",
            "enabled": True,
        },
    )
    assert routes.status_code == 200

    retention = client.put(
        "/api/gdpr/retention",
        headers=_owner_headers(tenant),
        json={
            "client_notes_days": 30,
            "audit_logs_days": 30,
            "status_events_days": 30,
            "rate_limit_events_hours": 24,
        },
    )
    assert retention.status_code == 200

    search = client.get(
        "/api/clients/search",
        headers=_owner_headers(tenant),
        params={"q": "Enterprise"},
    )
    assert search.status_code == 200
    client_id = search.json()[0]["id"]

    anon = client.post(
        f"/api/gdpr/clients/{client_id}/anonymize",
        headers=_owner_headers(tenant),
    )
    assert anon.status_code == 200
    assert anon.json()["ok"] is True


def test_calendar_webhook_hardening_signature_and_dedupe(tmp_path):
    client = make_client(tmp_path)
    tenant = "ent-webhook-hardening"

    conn = client.post(
        "/api/integrations/calendar/connections",
        headers=_owner_headers(tenant),
        json={
            "provider": "google",
            "external_calendar_id": "main",
            "sync_direction": "bidirectional",
            "webhook_secret": "top-secret",
            "enabled": True,
        },
    )
    assert conn.status_code == 200

    payload = {"id": "evt-unique-1", "action": "updated"}
    first = client.post(
        "/api/integrations/calendar/webhooks/google",
        headers={"X-Webhook-Secret": "top-secret"},
        json=payload,
    )
    second = client.post(
        "/api/integrations/calendar/webhooks/google",
        headers={"X-Webhook-Secret": "top-secret"},
        json=payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    prev_required = bool(settings.CALENDAR_WEBHOOK_SIGNATURE_REQUIRED)
    try:
        settings.CALENDAR_WEBHOOK_SIGNATURE_REQUIRED = True
        missing_sig = client.post(
            "/api/integrations/calendar/webhooks/google",
            headers={"X-Webhook-Secret": "top-secret"},
            json={"id": "evt-unique-2", "action": "updated"},
        )
        assert missing_sig.status_code == 403

        ts = str(int(time.time()))
        signed_payload = {"id": "evt-unique-3", "action": "updated"}
        canonical = json.dumps(
            signed_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        signature = hmac.new(
            b"top-secret",
            f"{ts}.{canonical}".encode(),
            hashlib.sha256,
        ).hexdigest()
        signed = client.post(
            "/api/integrations/calendar/webhooks/google",
            headers={
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Signature": signature,
            },
            json=signed_payload,
        )
        assert signed.status_code == 200
    finally:
        settings.CALENDAR_WEBHOOK_SIGNATURE_REQUIRED = prev_required


def test_ops_jobs_health_and_alerts_include_queue_risks(tmp_path):
    client = make_client(tmp_path)
    tenant = "ent-jobs-health"

    seed = client.post(
        "/api/visits",
        headers=_owner_headers(tenant),
        json={
            "dt": "2026-03-10T10:00:00",
            "client_name": "Enterprise Seed",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 210,
        },
    )
    assert seed.status_code == 200

    with client.testing_session_local() as db:
        tenant_row = db.execute(
            select(Tenant).where(Tenant.slug == tenant)
        ).scalar_one()
        dead_job = enqueue_background_job(
            db=db,
            tenant_id=tenant_row.id,
            queue="default",
            job_type="send_reminder",
            payload={},
            max_attempts=1,
        )
        stale_job = enqueue_background_job(
            db=db,
            tenant_id=tenant_row.id,
            queue="default",
            job_type="send_reminder",
            payload={},
            max_attempts=3,
        )

        dead_row = db.execute(
            select(BackgroundJob).where(BackgroundJob.id == dead_job.id)
        ).scalar_one()
        stale_row = db.execute(
            select(BackgroundJob).where(BackgroundJob.id == stale_job.id)
        ).scalar_one()
        dead_row.status = "dead_letter"
        dead_row.updated_at = utc_now_naive() - timedelta(minutes=30)
        stale_row.status = "running"
        stale_row.updated_at = utc_now_naive() - timedelta(minutes=30)
        db.commit()

    health = client.get(
        "/api/ops/jobs/health",
        headers=_owner_headers(tenant),
        params={"stale_running_minutes": 15},
    )
    assert health.status_code == 200
    assert health.json()["dead_letter_count"] >= 1
    assert health.json()["stale_running_count"] >= 1

    alerts = client.get(
        "/api/ops/alerts",
        headers={"X-Tenant-Slug": tenant},
        params={"window_minutes": 15},
    )
    assert alerts.status_code == 200
    codes = {row["code"] for row in alerts.json()}
    assert "jobs_dead_letter_detected" in codes
    assert "jobs_stale_running_detected" in codes


def test_ops_status_jobs_cancel_cleanup_calendar_replay_and_gdpr_preview(tmp_path):
    client = make_client(tmp_path)
    tenant = "ent-ops-suite"
    headers = _owner_headers(tenant)

    visit = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-10T10:00:00",
            "client_name": "Suite Seed",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 210,
        },
    )
    assert visit.status_code == 200

    status_resp = client.get(
        "/api/ops/status", headers=headers, params={"window_minutes": 15}
    )
    assert status_resp.status_code == 200
    status_json = status_resp.json()
    assert "jobs_health" in status_json
    assert "outbox_health" in status_json

    job1 = client.post(
        "/api/jobs",
        headers=headers,
        json={
            "job_type": "send_reminder",
            "payload": {"reservation_id": 1},
            "queue": "default",
            "max_attempts": 3,
        },
    )
    assert job1.status_code == 200
    job1_id = int(job1.json()["id"])

    canceled = client.post(f"/api/jobs/{job1_id}/cancel", headers=headers)
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"

    job2 = client.post(
        "/api/jobs",
        headers=headers,
        json={
            "job_type": "send_reminder",
            "payload": {"reservation_id": 2},
            "queue": "default",
            "max_attempts": 3,
        },
    )
    assert job2.status_code == 200
    job2_id = int(job2.json()["id"])

    with client.testing_session_local() as db:
        row2 = db.execute(
            select(BackgroundJob).where(BackgroundJob.id == job2_id)
        ).scalar_one()
        row2.status = "succeeded"
        row2.updated_at = utc_now_naive() - timedelta(days=10)
        row1 = db.execute(
            select(BackgroundJob).where(BackgroundJob.id == job1_id)
        ).scalar_one()
        row1.updated_at = utc_now_naive() - timedelta(days=10)
        db.commit()

    cleanup = client.post(
        "/api/jobs/cleanup",
        headers=headers,
        params={"older_than_hours": 24, "statuses": "canceled,succeeded"},
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["deleted_jobs"] >= 2

    conn = client.post(
        "/api/integrations/calendar/connections",
        headers=headers,
        json={
            "provider": "google",
            "external_calendar_id": "main",
            "sync_direction": "bidirectional",
            "webhook_secret": "top-secret",
            "enabled": True,
        },
    )
    assert conn.status_code == 200

    evt = client.post(
        "/api/integrations/calendar/webhooks/google",
        headers={"X-Webhook-Secret": "top-secret"},
        json={"id": "evt-replay-1", "action": "updated"},
    )
    assert evt.status_code == 200
    source_event_id = int(evt.json()["id"])

    replay = client.post(
        f"/api/integrations/calendar/events/{source_event_id}/replay",
        headers=headers,
    )
    assert replay.status_code == 200
    assert int(replay.json()["id"]) != source_event_id
    assert replay.json()["action"].endswith("_replay")

    preview = client.get("/api/gdpr/cleanup/preview", headers=headers)
    assert preview.status_code == 200
    preview_json = preview.json()
    assert "would_delete_client_notes" in preview_json
    assert "would_delete_audit_logs" in preview_json
