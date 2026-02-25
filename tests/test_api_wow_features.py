from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import get_db, public_router, router
from app.db import Base


def make_client(tmp_path):
    db_path = tmp_path / "test_salonos_wow.db"
    database_url = f"sqlite:///{db_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
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


def _seed_visit(client: TestClient, tenant_slug: str = "wow-tenant"):
    created = client.post(
        "/api/visits",
        headers={"X-Tenant-Slug": tenant_slug},
        json={
            "dt": "2026-03-10T10:00:00",
            "client_name": "Alicja Test",
            "client_phone": "+48111222333",
            "employee_name": "Magda",
            "service_name": "Strzyzenie",
            "price": 250,
            "duration_min": 30,
        },
    )
    assert created.status_code == 200
    return created.json()


def test_visit_status_history_flow(tmp_path):
    client = make_client(tmp_path)
    visit = _seed_visit(client, "status-wow")
    visit_id = visit["id"]

    r1 = client.patch(
        f"/api/visits/{visit_id}/status",
        headers={
            "X-Tenant-Slug": "status-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        json={"status": "confirmed"},
    )
    assert r1.status_code == 200

    r2 = client.patch(
        f"/api/visits/{visit_id}/status",
        headers={
            "X-Tenant-Slug": "status-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        json={"status": "arrived"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "arrived"

    history = client.get(
        f"/api/visits/{visit_id}/history",
        headers={
            "X-Tenant-Slug": "status-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
    )
    assert history.status_code == 200
    rows = history.json()
    assert len(rows) >= 3
    assert rows[-1]["to_status"] == "arrived"


def test_buffers_and_smart_slots(tmp_path):
    client = make_client(tmp_path)
    _seed_visit(client, "slots-wow")

    set_buf = client.post(
        "/api/buffers/employee/Magda",
        headers={
            "X-Tenant-Slug": "slots-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        json={"before_min": 15, "after_min": 15},
    )
    assert set_buf.status_code == 200

    blocked = client.post(
        "/api/visits",
        headers={
            "X-Tenant-Slug": "slots-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        json={
            "dt": "2026-03-10T10:30:00",
            "client_name": "Kolizja",
            "employee_name": "Magda",
            "service_name": "Modelowanie",
            "price": 220,
            "duration_min": 30,
        },
    )
    assert blocked.status_code == 400

    slots = client.get(
        "/api/slots/recommendations",
        headers={
            "X-Tenant-Slug": "slots-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        params={
            "day": "2026-03-10",
            "employee_name": "Magda",
            "service_name": "Modelowanie",
            "limit": 5,
        },
    )
    assert slots.status_code == 200
    assert len(slots.json()) >= 1


def test_crm_search_detail_and_notes(tmp_path):
    client = make_client(tmp_path)
    visit = _seed_visit(client, "crm-wow")
    _ = visit

    search = client.get(
        "/api/clients/search",
        headers={
            "X-Tenant-Slug": "crm-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        params={"q": "1112"},
    )
    assert search.status_code == 200
    rows = search.json()
    assert len(rows) == 1
    client_id = rows[0]["id"]

    detail = client.get(
        f"/api/clients/{client_id}",
        headers={
            "X-Tenant-Slug": "crm-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
    )
    assert detail.status_code == 200
    assert detail.json()["visits_count"] >= 1

    note = client.post(
        f"/api/clients/{client_id}/notes",
        headers={"X-Tenant-Slug": "crm-wow", "X-Actor-Email": "owner@salon.pl"},
        json={"note": "Klientka preferuje poranne terminy."},
    )
    assert note.status_code == 200
    assert "preferuje" in note.json()["note"]


def test_availability_blocks_pulse_and_assistant(tmp_path):
    client = make_client(tmp_path)
    _seed_visit(client, "ops-wow")

    target_day = date(2026, 3, 11)
    day_off = client.post(
        "/api/availability/day",
        headers={
            "X-Tenant-Slug": "ops-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        json={
            "employee_name": "Kamila",
            "day": target_day.isoformat(),
            "is_day_off": True,
        },
    )
    assert day_off.status_code == 200
    assert day_off.json()["is_day_off"] is True

    block = client.post(
        "/api/availability/blocks",
        headers={
            "X-Tenant-Slug": "ops-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        json={
            "employee_name": "Magda",
            "start_dt": "2026-03-10T12:00:00",
            "end_dt": "2026-03-10T13:00:00",
            "reason": "Szkolenie",
        },
    )
    assert block.status_code == 200

    avail = client.get(
        "/api/availability",
        headers={
            "X-Tenant-Slug": "ops-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        params={
            "employee_name": "Kamila",
            "start_day": target_day.isoformat(),
            "end_day": (target_day + timedelta(days=1)).isoformat(),
        },
    )
    assert avail.status_code == 200
    assert avail.json()[0]["is_day_off"] is True

    reservation = client.post(
        "/public/ops-wow/reservations",
        json={
            "requested_dt": "2026-03-12T14:00:00",
            "client_name": "Nowa Klientka",
            "service_name": "Koloryzacja",
        },
    )
    assert reservation.status_code == 200

    pulse = client.get(
        "/api/pulse/day",
        headers={
            "X-Tenant-Slug": "ops-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        params={"day": "2026-03-10"},
    )
    assert pulse.status_code == 200
    assert pulse.json()["visits_count"] >= 1

    assistant = client.get(
        "/api/reservations/assistant",
        headers={
            "X-Tenant-Slug": "ops-wow",
            "X-Actor-Email": "tests@salonos.local",
            "X-Actor-Role": "manager",
        },
        params={"limit": 5},
    )
    assert assistant.status_code == 200
    assert len(assistant.json()) >= 1
