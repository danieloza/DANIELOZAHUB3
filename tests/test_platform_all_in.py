import pyotp
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth_api import router as auth_router
from app.api import get_db, public_router, router
from app.config import settings
from app.db import Base
from app.idempotency import idempotency_middleware
from app.models import AuditLog, AuthSession, IdempotencyRecord, OutboxEvent, Tenant
from app.platform_api import router as platform_router


def make_client(tmp_path):
    db_path = tmp_path / "test_salonos_all_in.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.state.session_local = testing_session_local
    app.middleware("http")(idempotency_middleware)
    app.include_router(router)
    app.include_router(public_router)
    app.include_router(auth_router)
    app.include_router(platform_router)

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


def _platform_auth_headers(client: TestClient, tenant: str, email: str = "owner@salonos.local", role: str = "owner") -> dict:
    register = client.post(
        "/auth/register",
        json={
            "tenant_slug": tenant,
            "email": email,
            "password": "StrongPass123!",
            "role": role,
        },
    )
    assert register.status_code in {200, 400}
    login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": email,
            "password": "StrongPass123!",
        },
    )
    assert login.status_code == 200
    return {
        "X-Tenant-Slug": tenant,
        "Authorization": f"Bearer {login.json()['access_token']}",
    }


def test_idempotency_replay_and_outbox(tmp_path):
    client = make_client(tmp_path)
    tenant = "idem-all-in"
    payload = {
        "dt": "2030-02-20T10:00:00",
        "client_name": "Idem Test",
        "employee_name": "Magda",
        "service_name": "Strzyzenie",
        "price": 200,
    }
    headers = {"X-Tenant-Slug": tenant, "Idempotency-Key": "visit-create-1"}
    first = client.post("/api/visits", json=payload, headers=headers)
    second = client.post("/api/visits", json=payload, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("X-Idempotency-Replayed") == "true"

    platform_headers = _platform_auth_headers(client, tenant)
    outbox = client.get("/api/platform/outbox/events", headers=platform_headers)
    assert outbox.status_code == 200
    assert any(item["topic"] == "visit.created" for item in outbox.json())


def test_auth_jwt_mfa_flow(tmp_path):
    client = make_client(tmp_path)
    tenant = "auth-all-in"

    reg = client.post(
        "/auth/register",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
            "role": "owner",
        },
    )
    assert reg.status_code == 200

    login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
        },
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    setup = client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    code = pyotp.TOTP(secret).now()

    verify = client.post("/auth/mfa/verify", headers={"Authorization": f"Bearer {token}"}, json={"code": code})
    assert verify.status_code == 200
    assert verify.json()["mfa_enabled"] is True

    login_mfa = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
            "mfa_code": pyotp.TOTP(secret).now(),
        },
    )
    assert login_mfa.status_code == 200
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login_mfa.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "owner"


def test_feature_flags_and_no_show_payment(tmp_path):
    client = make_client(tmp_path)
    tenant = "flags-payments"
    platform_headers = _platform_auth_headers(client, tenant)

    seed_visit = client.post(
        "/api/visits",
        headers={"X-Tenant-Slug": tenant},
        json={
            "dt": "2030-02-20T11:00:00",
            "client_name": "Payment Test",
            "employee_name": "Magda",
            "service_name": "Modelowanie",
            "price": 210,
        },
    )
    assert seed_visit.status_code == 200
    visit_id = seed_visit.json()["id"]

    set_flag = client.put(
        "/api/platform/flags",
        headers=platform_headers,
        json={
            "flag_key": "slots_v2_scoring",
            "enabled": True,
            "rollout_pct": 100,
            "allowlist": [],
        },
    )
    assert set_flag.status_code == 200

    eval_flag = client.get(
        "/api/platform/flags/evaluate",
        headers=platform_headers,
        params={"flag_key": "slots_v2_scoring", "subject_key": "Magda"},
    )
    assert eval_flag.status_code == 200
    assert eval_flag.json()["enabled"] is True

    set_policy = client.put(
        "/api/platform/no-show-policy",
        headers=platform_headers,
        json={"enabled": True, "fee_amount": 50, "grace_minutes": 15},
    )
    assert set_policy.status_code == 200

    mark_no_show = client.patch(
        f"/api/visits/{visit_id}/status",
        headers={
            "X-Tenant-Slug": tenant,
            "X-Actor-Email": "owner@salonos.local",
            "X-Actor-Role": "owner",
        },
        json={"status": "no_show"},
    )
    assert mark_no_show.status_code == 200
    assert mark_no_show.json()["status"] == "no_show"

    payments = client.get("/api/platform/payments/intents", headers=platform_headers)
    assert payments.status_code == 200
    rows = payments.json()
    assert len(rows) >= 1
    assert any(row["reason"] == "no_show_fee" for row in rows)


def test_auth_login_rate_limit_blocks_bruteforce(tmp_path):
    client = make_client(tmp_path)
    tenant = f"auth-rate-limit-{uuid4().hex[:8]}"

    previous_min = int(settings.AUTH_LOGIN_RL_PER_MIN)
    previous_hour = int(settings.AUTH_LOGIN_RL_PER_HOUR)
    try:
        settings.AUTH_LOGIN_RL_PER_MIN = 1
        settings.AUTH_LOGIN_RL_PER_HOUR = 100

        reg = client.post(
            "/auth/register",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
                "role": "owner",
            },
        )
        assert reg.status_code == 200

        first_bad = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": "203.0.113.1"},
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "WrongPass123!",
            },
        )
        second_bad = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": "203.0.113.1"},
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "WrongPass123!",
            },
        )
        assert first_bad.status_code == 401
        assert second_bad.status_code == 429

        good_other_ip = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": "203.0.113.2"},
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
            },
        )
        assert good_other_ip.status_code == 200
    finally:
        settings.AUTH_LOGIN_RL_PER_MIN = previous_min
        settings.AUTH_LOGIN_RL_PER_HOUR = previous_hour


def test_auth_logout_invalidates_refresh_token(tmp_path):
    client = make_client(tmp_path)
    tenant = "auth-logout-flow"

    reg = client.post(
        "/auth/register",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
            "role": "owner",
        },
    )
    assert reg.status_code == 200

    login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
        },
    )
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    logout = client.post(
        "/auth/logout",
        json={"tenant_slug": tenant, "refresh_token": refresh_token},
    )
    assert logout.status_code == 200
    assert logout.json()["ok"] is True

    refresh = client.post(
        "/auth/refresh",
        json={"tenant_slug": tenant, "refresh_token": refresh_token},
    )
    assert refresh.status_code == 401


def test_auth_sessions_list_revoke_and_cleanup(tmp_path):
    client = make_client(tmp_path)
    tenant = "auth-sessions-flow"

    reg = client.post(
        "/auth/register",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
            "role": "owner",
        },
    )
    assert reg.status_code == 200

    login1 = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
        },
    )
    login2 = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
        },
    )
    assert login1.status_code == 200
    assert login2.status_code == 200
    access2 = login2.json()["access_token"]
    refresh1 = login1.json()["refresh_token"]

    sessions = client.get(
        "/auth/sessions",
        headers={"Authorization": f"Bearer {access2}"},
    )
    assert sessions.status_code == 200
    session_ids = [row["id"] for row in sessions.json()]
    assert len(session_ids) >= 2
    revoke_id = session_ids[-1]

    revoke = client.post(
        f"/auth/sessions/{revoke_id}/revoke",
        headers={"Authorization": f"Bearer {access2}"},
    )
    assert revoke.status_code == 200
    assert revoke.json()["ok"] is True

    refresh_after_revoke = client.post(
        "/auth/refresh",
        json={"tenant_slug": tenant, "refresh_token": refresh1},
    )
    assert refresh_after_revoke.status_code == 401

    with client.testing_session_local() as db:
        tenant_row = db.execute(select(Tenant).where(Tenant.slug == tenant)).scalar_one()
        active_row = (
            db.query(AuthSession)
            .filter(AuthSession.tenant_id == tenant_row.id, AuthSession.is_revoked.is_(False))
            .order_by(AuthSession.id.asc())
            .first()
        )
        assert active_row is not None
        active_row.expires_at = active_row.expires_at - timedelta(days=365)
        db.commit()

    cleanup = client.post(
        "/auth/sessions/cleanup",
        headers={"Authorization": f"Bearer {access2}"},
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["revoked_expired_sessions"] >= 1


def test_auth_register_password_policy_enforced(tmp_path):
    client = make_client(tmp_path)
    tenant = "auth-password-policy"

    previous = (
        settings.AUTH_PASSWORD_MIN_LENGTH,
        settings.AUTH_PASSWORD_REQUIRE_UPPER,
        settings.AUTH_PASSWORD_REQUIRE_LOWER,
        settings.AUTH_PASSWORD_REQUIRE_DIGIT,
        settings.AUTH_PASSWORD_REQUIRE_SPECIAL,
    )
    try:
        settings.AUTH_PASSWORD_MIN_LENGTH = 12
        settings.AUTH_PASSWORD_REQUIRE_UPPER = True
        settings.AUTH_PASSWORD_REQUIRE_LOWER = True
        settings.AUTH_PASSWORD_REQUIRE_DIGIT = True
        settings.AUTH_PASSWORD_REQUIRE_SPECIAL = True

        weak = client.post(
            "/auth/register",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "weakpass123",
                "role": "owner",
            },
        )
        assert weak.status_code == 400

        strong = client.post(
            "/auth/register",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
                "role": "owner",
            },
        )
        assert strong.status_code == 200
    finally:
        (
            settings.AUTH_PASSWORD_MIN_LENGTH,
            settings.AUTH_PASSWORD_REQUIRE_UPPER,
            settings.AUTH_PASSWORD_REQUIRE_LOWER,
            settings.AUTH_PASSWORD_REQUIRE_DIGIT,
            settings.AUTH_PASSWORD_REQUIRE_SPECIAL,
        ) = previous


def test_auth_max_active_sessions_limit_revokes_oldest(tmp_path):
    client = make_client(tmp_path)
    tenant = "auth-max-sessions"
    previous_max = int(settings.AUTH_MAX_ACTIVE_SESSIONS_PER_USER)
    try:
        settings.AUTH_MAX_ACTIVE_SESSIONS_PER_USER = 1
        reg = client.post(
            "/auth/register",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
                "role": "owner",
            },
        )
        assert reg.status_code == 200

        login1 = client.post(
            "/auth/login",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
            },
        )
        login2 = client.post(
            "/auth/login",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
            },
        )
        assert login1.status_code == 200
        assert login2.status_code == 200

        refresh1 = client.post(
            "/auth/refresh",
            json={"tenant_slug": tenant, "refresh_token": login1.json()["refresh_token"]},
        )
        assert refresh1.status_code == 401
    finally:
        settings.AUTH_MAX_ACTIVE_SESSIONS_PER_USER = previous_max


def test_auth_change_password_revokes_sessions_and_requires_new_credentials(tmp_path):
    client = make_client(tmp_path)
    tenant = "auth-change-password"
    reg = client.post(
        "/auth/register",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
            "role": "owner",
        },
    )
    assert reg.status_code == 200

    login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
        },
    )
    assert login.status_code == 200
    access = login.json()["access_token"]
    refresh = login.json()["refresh_token"]

    changed = client.post(
        "/auth/password/change",
        headers={"Authorization": f"Bearer {access}"},
        json={"current_password": "StrongPass123!", "new_password": "NewStrong123!"},
    )
    assert changed.status_code == 200
    assert changed.json()["ok"] is True
    assert changed.json()["revoked_sessions"] >= 1

    old_login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "StrongPass123!",
        },
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant,
            "email": "owner@salonos.local",
            "password": "NewStrong123!",
        },
    )
    assert new_login.status_code == 200

    refresh_old = client.post(
        "/auth/refresh",
        json={"tenant_slug": tenant, "refresh_token": refresh},
    )
    assert refresh_old.status_code == 401


def test_outbox_dead_letter_retry_and_health(tmp_path):
    client = make_client(tmp_path)
    tenant = "outbox-health"
    platform_headers = _platform_auth_headers(client, tenant)
    payload = {
        "dt": "2030-02-20T10:00:00",
        "client_name": "Outbox Test",
        "employee_name": "Magda",
        "service_name": "Strzyzenie",
        "price": 200,
    }
    create = client.post("/api/visits", json=payload, headers={"X-Tenant-Slug": tenant})
    assert create.status_code == 200

    previous = (
        bool(settings.EVENT_BUS_ENABLED),
        settings.REDIS_URL,
        int(settings.OUTBOX_MAX_RETRIES),
    )
    try:
        settings.EVENT_BUS_ENABLED = True
        settings.REDIS_URL = "redis://127.0.0.1:6399/0"
        settings.OUTBOX_MAX_RETRIES = 1

        dispatch = client.post("/api/platform/outbox/dispatch", headers=platform_headers)
        assert dispatch.status_code == 200
        assert dispatch.json()["dead_lettered"] >= 1

        health = client.get("/api/platform/outbox/health", headers=platform_headers)
        assert health.status_code == 200
        assert health.json()["dead_letter_count"] >= 1

        retry = client.post(
            "/api/platform/outbox/retry-failed",
            headers=platform_headers,
            params={"include_dead_letter": True, "limit": 100},
        )
        assert retry.status_code == 200
        assert retry.json()["retried"] >= 1
    finally:
        settings.EVENT_BUS_ENABLED, settings.REDIS_URL, settings.OUTBOX_MAX_RETRIES = previous


def test_outbox_cleanup_removes_old_published_and_dead_letter(tmp_path):
    client = make_client(tmp_path)
    tenant = "outbox-cleanup"
    platform_headers = _platform_auth_headers(client, tenant)
    create = client.post(
        "/api/visits",
        headers={"X-Tenant-Slug": tenant},
        json={
            "dt": "2030-02-20T10:00:00",
            "client_name": "Cleanup Outbox",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 200,
        },
    )
    assert create.status_code == 200

    with client.testing_session_local() as db:
        tenant_row = db.execute(select(Tenant).where(Tenant.slug == tenant)).scalar_one()
        row = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.tenant_id == tenant_row.id)
            .order_by(OutboxEvent.id.desc())
            .first()
        )
        assert row is not None
        row.status = "published"
        row.updated_at = row.updated_at - timedelta(days=10)
        db.commit()

    cleanup = client.post(
        "/api/platform/outbox/cleanup",
        headers=platform_headers,
        params={"older_than_hours": 24},
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["deleted_events"] >= 1


def test_idempotency_health_and_cleanup(tmp_path):
    client = make_client(tmp_path)
    tenant = "idem-cleanup"
    platform_headers = _platform_auth_headers(client, tenant)
    payload = {
        "dt": "2030-02-20T10:00:00",
        "client_name": "Idem Cleanup",
        "employee_name": "Magda",
        "service_name": "Strzyzenie",
        "price": 200,
    }
    create = client.post(
        "/api/visits",
        headers={"X-Tenant-Slug": tenant, "Idempotency-Key": "idem-cleanup-key"},
        json=payload,
    )
    assert create.status_code == 200

    health = client.get("/api/platform/idempotency/health", headers=platform_headers)
    assert health.status_code == 200
    assert health.json()["records_count"] >= 1

    with client.testing_session_local() as db:
        row = (
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.tenant_slug == tenant)
            .order_by(IdempotencyRecord.id.asc())
            .first()
        )
        assert row is not None
        row.created_at = row.created_at - timedelta(days=10)
        db.commit()

    cleanup = client.post(
        "/api/platform/idempotency/cleanup",
        headers=platform_headers,
        params={"older_than_hours": 24},
    )
    assert cleanup.status_code == 200
    assert cleanup.json()["deleted_records"] >= 1


def test_platform_requires_bearer_token(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/platform/flags", headers={"X-Tenant-Slug": "missing-token"})
    assert response.status_code == 401


def test_auth_require_mfa_blocks_non_mfa_user(tmp_path):
    client = make_client(tmp_path)
    tenant = "auth-mfa-required"
    previous = bool(settings.AUTH_REQUIRE_MFA)
    try:
        settings.AUTH_REQUIRE_MFA = True
        reg = client.post(
            "/auth/register",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
                "role": "owner",
            },
        )
        assert reg.status_code == 200

        blocked = client.post(
            "/auth/login",
            json={
                "tenant_slug": tenant,
                "email": "owner@salonos.local",
                "password": "StrongPass123!",
            },
        )
        assert blocked.status_code == 403
    finally:
        settings.AUTH_REQUIRE_MFA = previous


def test_audit_logs_filters(tmp_path):
    client = make_client(tmp_path)
    tenant = "audit-filters"
    headers = {"X-Tenant-Slug": tenant, "X-Actor-Email": "owner@salonos.local", "X-Actor-Role": "owner"}
    create = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2030-02-20T10:00:00",
            "client_name": "Audit Filter",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 200,
        },
    )
    assert create.status_code == 200

    logs = client.get(
        "/api/audit/logs",
        headers=headers,
        params={
            "limit": 100,
            "action": "visit.create",
            "actor_email": "owner@salonos.local",
            "resource_type": "visit",
            "since_minutes": 60,
        },
    )
    assert logs.status_code == 200
    rows = logs.json()
    assert len(rows) >= 1
    assert any(row["action"] == "visit.create" and row["resource_type"] == "visit" for row in rows)
