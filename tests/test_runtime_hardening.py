from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_health_ready_ok_without_redis():
    previous_redis = settings.REDIS_URL
    previous_event_bus = bool(settings.EVENT_BUS_ENABLED)
    try:
        settings.REDIS_URL = ""
        settings.EVENT_BUS_ENABLED = False
        client = TestClient(app)
        response = client.get("/health/ready")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["checks"]["db"] == "ok"
        assert payload["checks"]["redis"] == "skipped"
    finally:
        settings.REDIS_URL = previous_redis
        settings.EVENT_BUS_ENABLED = previous_event_bus


def test_security_headers_are_present():
    previous_security_headers = bool(settings.SECURITY_HEADERS_ENABLED)
    try:
        settings.SECURITY_HEADERS_ENABLED = True
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Referrer-Policy") == "no-referrer"
    finally:
        settings.SECURITY_HEADERS_ENABLED = previous_security_headers


def test_maintenance_mode_blocks_business_endpoints():
    previous_maintenance_mode = bool(settings.MAINTENANCE_MODE)
    previous_retry_after = int(settings.MAINTENANCE_RETRY_AFTER_SECONDS)
    try:
        settings.MAINTENANCE_MODE = True
        settings.MAINTENANCE_RETRY_AFTER_SECONDS = 30
        client = TestClient(app)
        blocked = client.post(
            "/api/visits",
            json={
                "dt": "2030-01-01T10:00:00",
                "client_name": "Maintenance",
                "employee_name": "Magda",
                "service_name": "Strzyzenie",
                "price": 120,
            },
        )
        assert blocked.status_code == 503
        assert blocked.headers.get("Retry-After") == "30"

        health = client.get("/health")
        assert health.status_code == 200
    finally:
        settings.MAINTENANCE_MODE = previous_maintenance_mode
        settings.MAINTENANCE_RETRY_AFTER_SECONDS = previous_retry_after


def test_read_only_mode_blocks_mutations_but_allows_auth_login():
    previous_read_only = bool(settings.MAINTENANCE_READ_ONLY)
    try:
        settings.MAINTENANCE_READ_ONLY = True
        client = TestClient(app)
        blocked = client.post(
            "/api/visits",
            json={
                "dt": "2030-01-01T10:00:00",
                "client_name": "ReadOnly",
                "employee_name": "Magda",
                "service_name": "Strzyzenie",
                "price": 120,
            },
        )
        assert blocked.status_code == 503

        allowed_auth = client.post(
            "/auth/login",
            json={
                "tenant_slug": "readonly-tenant",
                "email": "missing@salonos.local",
                "password": "BadPass123!",
            },
        )
        assert allowed_auth.status_code in {200, 400, 401, 403, 429}
        assert allowed_auth.status_code != 503
    finally:
        settings.MAINTENANCE_READ_ONLY = previous_read_only
