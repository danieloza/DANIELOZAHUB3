from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import get_db, public_router, router
from app.db import Base


def make_client(tmp_path):
    db_path = tmp_path / "test_salonos.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_create_and_list_visit(tmp_path):
    client = make_client(tmp_path)

    payload = {
        "dt": "2026-02-17T10:30:00",
        "client_name": "Anna Kowalska",
        "employee_name": "Magda",
        "service_name": "Strzyzenie",
        "price": 220,
    }
    created = client.post("/api/visits", json=payload)
    assert created.status_code == 200
    body = created.json()
    assert body["id"] > 0
    assert body["employee"] == "Magda"

    listed = client.get("/api/visits", params={"day": "2026-02-17", "employee_name": "Magda"})
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["client"] == "Anna Kowalska"
    assert rows[0]["service"] == "Strzyzenie"


def test_employee_filter_returns_only_matching_rows(tmp_path):
    client = make_client(tmp_path)

    for employee in ["Magda", "Kamila"]:
        payload = {
            "dt": "2026-02-17T11:00:00",
            "client_name": f"Klient {employee}",
            "employee_name": employee,
            "service_name": "Modelowanie",
            "price": 180,
        }
        res = client.post("/api/visits", json=payload)
        assert res.status_code == 200

    listed = client.get("/api/visits", params={"day": "2026-02-17", "employee_name": "Kamila"})
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["employee"] == "Kamila"


def test_patch_visit_datetime_to_another_day(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T09:00:00",
            "client_name": "Move Me",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 200,
        },
    )
    visit_id = created.json()["id"]

    patched = client.patch(f"/api/visits/{visit_id}", json={"dt": "2026-02-18T13:35:00"})
    assert patched.status_code == 200
    assert patched.json()["dt"].startswith("2026-02-18T13:35:00")

    old_day = client.get("/api/visits", params={"day": "2026-02-17", "employee_name": "Magda"})
    assert old_day.status_code == 200
    assert old_day.json() == []

    new_day = client.get("/api/visits", params={"day": "2026-02-18", "employee_name": "Magda"})
    assert new_day.status_code == 200
    assert len(new_day.json()) == 1

    bad = client.patch(f"/api/visits/{visit_id}", json={})
    assert bad.status_code == 400


def test_delete_visit_and_404_for_missing(tmp_path):
    client = make_client(tmp_path)

    payload = {
        "dt": datetime(2026, 2, 17, 12, 0).isoformat(),
        "client_name": "Jan Test",
        "employee_name": "Taja",
        "service_name": "Tonowanie",
        "price": 260,
    }
    created = client.post("/api/visits", json=payload)
    visit_id = created.json()["id"]

    deleted = client.delete(f"/api/visits/{visit_id}")
    assert deleted.status_code == 204

    missing = client.delete(f"/api/visits/{visit_id}")
    assert missing.status_code == 404


def test_tenant_isolation_by_header(tmp_path):
    client = make_client(tmp_path)
    payload = {
        "dt": "2026-02-17T15:00:00",
        "client_name": "Tenant Client",
        "employee_name": "Magda",
        "service_name": "Modelowanie",
        "price": 180,
    }

    created_a = client.post("/api/visits", json=payload, headers={"X-Tenant-Slug": "tenant-a"})
    assert created_a.status_code == 200

    created_b = client.post("/api/visits", json=payload, headers={"X-Tenant-Slug": "tenant-b"})
    assert created_b.status_code == 200

    listed_a = client.get(
        "/api/visits",
        params={"day": "2026-02-17", "employee_name": "Magda"},
        headers={"X-Tenant-Slug": "tenant-a"},
    )
    listed_b = client.get(
        "/api/visits",
        params={"day": "2026-02-17", "employee_name": "Magda"},
        headers={"X-Tenant-Slug": "tenant-b"},
    )

    assert listed_a.status_code == 200
    assert listed_b.status_code == 200
    assert len(listed_a.json()) == 1
    assert len(listed_b.json()) == 1
    assert listed_a.json()[0]["id"] != listed_b.json()[0]["id"]


def test_public_reservation_endpoint(tmp_path):
    client = make_client(tmp_path)

    seed = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "public-tenant"},
    )
    assert seed.status_code == 200

    reservation = client.post(
        "/public/public-tenant/reservations",
        json={
            "requested_dt": "2026-02-20T13:00:00",
            "client_name": "Klient WWW",
            "service_name": "Koloryzacja",
            "phone": "+48123123123",
            "note": "Prosze o kontakt SMS",
        },
    )
    assert reservation.status_code == 200
    body = reservation.json()
    assert body["id"] > 0
    assert body["tenant_slug"] == "public-tenant"
    assert body["status"] == "new"

    missing = client.post(
        "/public/does-not-exist/reservations",
        json={
            "requested_dt": "2026-02-20T13:00:00",
            "client_name": "XX",
            "service_name": "YY",
        },
    )
    assert missing.status_code == 404



def test_list_reservations_per_tenant(tmp_path):
    client = make_client(tmp_path)

    seed_a = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder A",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-a"},
    )
    assert seed_a.status_code == 200

    seed_b = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder B",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-b"},
    )
    assert seed_b.status_code == 200

    r1 = client.post(
        "/public/tenant-a/reservations",
        json={
            "requested_dt": "2026-02-20T10:00:00",
            "client_name": "A1",
            "service_name": "Koloryzacja",
        },
    )
    r2 = client.post(
        "/public/tenant-a/reservations",
        json={
            "requested_dt": "2026-02-20T11:00:00",
            "client_name": "A2",
            "service_name": "Strzyzenie",
        },
    )
    r3 = client.post(
        "/public/tenant-b/reservations",
        json={
            "requested_dt": "2026-02-20T12:00:00",
            "client_name": "B1",
            "service_name": "Modelowanie",
        },
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200

    listed_a = client.get("/api/reservations", headers={"X-Tenant-Slug": "tenant-a"})
    assert listed_a.status_code == 200
    body_a = listed_a.json()
    assert len(body_a) == 2
    assert all(x["tenant_slug"] == "tenant-a" for x in body_a)

    listed_b = client.get("/api/reservations", headers={"X-Tenant-Slug": "tenant-b"})
    assert listed_b.status_code == 200
    body_b = listed_b.json()
    assert len(body_b) == 1
    assert body_b[0]["tenant_slug"] == "tenant-b"

    listed_limit = client.get(
        "/api/reservations",
        params={"limit": 1},
        headers={"X-Tenant-Slug": "tenant-a"},
    )
    assert listed_limit.status_code == 200
    assert len(listed_limit.json()) == 1

def test_reservation_status_workflow(tmp_path):
    client = make_client(tmp_path)

    seed = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-status"},
    )
    assert seed.status_code == 200

    reservation = client.post(
        "/public/tenant-status/reservations",
        json={
            "requested_dt": "2026-02-20T13:00:00",
            "client_name": "Klient",
            "service_name": "Koloryzacja",
        },
    )
    assert reservation.status_code == 200
    reservation_id = reservation.json()["id"]

    contacted = client.patch(
        f"/api/reservations/{reservation_id}/status",
        json={"status": "contacted"},
        headers={"X-Tenant-Slug": "tenant-status"},
    )
    assert contacted.status_code == 200
    assert contacted.json()["status"] == "contacted"

    confirmed = client.patch(
        f"/api/reservations/{reservation_id}/status",
        json={"status": "confirmed"},
        headers={"X-Tenant-Slug": "tenant-status"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"


def test_reservation_status_invalid_transition(tmp_path):
    client = make_client(tmp_path)

    seed = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-invalid"},
    )
    assert seed.status_code == 200

    reservation = client.post(
        "/public/tenant-invalid/reservations",
        json={
            "requested_dt": "2026-02-20T13:00:00",
            "client_name": "Klient",
            "service_name": "Koloryzacja",
        },
    )
    reservation_id = reservation.json()["id"]

    invalid = client.patch(
        f"/api/reservations/{reservation_id}/status",
        json={"status": "confirmed"},
        headers={"X-Tenant-Slug": "tenant-invalid"},
    )
    assert invalid.status_code == 400


def test_convert_reservation_to_visit(tmp_path):
    client = make_client(tmp_path)

    seed = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-convert"},
    )
    assert seed.status_code == 200

    reservation = client.post(
        "/public/tenant-convert/reservations",
        json={
            "requested_dt": "2026-02-20T13:00:00",
            "client_name": "Klient WWW",
            "service_name": "Koloryzacja",
        },
    )
    reservation_id = reservation.json()["id"]

    converted = client.post(
        f"/api/reservations/{reservation_id}/convert",
        json={
            "employee_name": "Magda",
            "price": 280,
        },
        headers={"X-Tenant-Slug": "tenant-convert"},
    )
    assert converted.status_code == 200
    body = converted.json()
    assert body["employee"] == "Magda"
    assert body["client"] == "Klient WWW"

    listed = client.get(
        "/api/reservations",
        headers={"X-Tenant-Slug": "tenant-convert"},
    )
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "confirmed"

def test_convert_reservation_is_idempotent(tmp_path):
    client = make_client(tmp_path)

    seed = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-idempotent"},
    )
    assert seed.status_code == 200

    reservation = client.post(
        "/public/tenant-idempotent/reservations",
        json={
            "requested_dt": "2026-02-20T13:00:00",
            "client_name": "Klient WWW",
            "service_name": "Koloryzacja",
        },
    )
    reservation_id = reservation.json()["id"]

    first = client.post(
        f"/api/reservations/{reservation_id}/convert",
        json={"employee_name": "Magda", "price": 280},
        headers={"X-Tenant-Slug": "tenant-idempotent"},
    )
    second = client.post(
        f"/api/reservations/{reservation_id}/convert",
        json={"employee_name": "Magda", "price": 280},
        headers={"X-Tenant-Slug": "tenant-idempotent"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_reservation_history_and_metrics(tmp_path):
    client = make_client(tmp_path)

    seed = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-observability"},
    )
    assert seed.status_code == 200

    reservation = client.post(
        "/public/tenant-observability/reservations",
        json={
            "requested_dt": "2026-02-20T13:00:00",
            "client_name": "Klient",
            "service_name": "Koloryzacja",
        },
    )
    reservation_id = reservation.json()["id"]

    contacted = client.patch(
        f"/api/reservations/{reservation_id}/status",
        json={"status": "contacted"},
        headers={"X-Tenant-Slug": "tenant-observability", "X-Actor-Email": "admin@danex.pl"},
    )
    assert contacted.status_code == 200

    converted = client.post(
        f"/api/reservations/{reservation_id}/convert",
        json={"employee_name": "Magda", "price": 210},
        headers={"X-Tenant-Slug": "tenant-observability", "X-Actor-Email": "admin@danex.pl"},
    )
    assert converted.status_code == 200

    history = client.get(
        f"/api/reservations/{reservation_id}/history",
        headers={"X-Tenant-Slug": "tenant-observability"},
    )
    assert history.status_code == 200
    body = history.json()
    assert len(body) >= 3
    assert body[0]["action"] == "created"
    assert body[1]["to_status"] == "contacted"
    assert body[-1]["action"] == "converted_to_visit"

    metrics = client.get(
        "/api/reservations/metrics",
        headers={"X-Tenant-Slug": "tenant-observability"},
    )
    assert metrics.status_code == 200
    m = metrics.json()
    assert m["total"] == 1
    assert m["converted"] == 1
    assert m["conversion_rate"] == 1.0


def test_public_reservation_idempotency_key(tmp_path):
    client = make_client(tmp_path)

    seed = client.post(
        "/api/visits",
        json={
            "dt": "2026-02-17T08:30:00",
            "client_name": "Seeder",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 100,
        },
        headers={"X-Tenant-Slug": "tenant-idem-key"},
    )
    assert seed.status_code == 200

    payload = {
        "requested_dt": "2026-02-20T13:00:00",
        "client_name": "Klient WWW",
        "service_name": "Koloryzacja",
    }

    first = client.post(
        "/public/tenant-idem-key/reservations",
        headers={"Idempotency-Key": "idem-123"},
        json=payload,
    )
    second = client.post(
        "/public/tenant-idem-key/reservations",
        headers={"Idempotency-Key": "idem-123"},
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
