from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import get_db, public_router, router
from app.db import Base


def make_client(tmp_path):
    db_path = tmp_path / "test_salonos_team.db"
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
    return TestClient(app)


def _headers(tenant: str = "team-tenant", role: str = "manager") -> dict[str, str]:
    return {
        "X-Tenant-Slug": tenant,
        "X-Actor-Email": "manager@salonos.local",
        "X-Actor-Role": role,
    }


def test_team_employee_crud_and_reactivate(tmp_path):
    client = make_client(tmp_path)
    headers = _headers()

    created = client.post(
        "/api/team/employees",
        headers=headers,
        json={"name": "Ola", "commission_pct": 42.0},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["name"] == "Ola"
    assert body["is_active"] is True
    employee_id = body["id"]

    listed = client.get("/api/team/employees", headers=headers)
    assert listed.status_code == 200
    assert any(row["id"] == employee_id for row in listed.json())

    archived = client.delete(f"/api/team/employees/{employee_id}", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False

    active_list = client.get("/api/team/employees", headers=headers)
    assert active_list.status_code == 200
    assert all(row["id"] != employee_id for row in active_list.json())

    all_list = client.get("/api/team/employees?include_inactive=true", headers=headers)
    assert all_list.status_code == 200
    inactive_row = next(row for row in all_list.json() if row["id"] == employee_id)
    assert inactive_row["is_active"] is False

    reactivated = client.post(
        "/api/team/employees",
        headers=headers,
        json={"name": "Ola", "commission_pct": 45.0},
    )
    assert reactivated.status_code == 200
    reactivated_body = reactivated.json()
    assert reactivated_body["id"] == employee_id
    assert reactivated_body["is_active"] is True
    assert reactivated_body["commission_pct"] == 45.0


def test_weekly_schedule_controls_working_hours(tmp_path):
    client = make_client(tmp_path)
    headers = _headers("team-weekly")

    created = client.post(
        "/api/team/employees",
        headers=headers,
        json={"name": "Nina"},
    )
    assert created.status_code == 200
    employee_id = created.json()["id"]

    set_schedule = client.put(
        f"/api/team/employees/{employee_id}/weekly-schedule",
        headers=headers,
        json={
            "days": [
                {"weekday": 0, "is_day_off": False, "start_hour": 9, "end_hour": 12},
                {"weekday": 1, "is_day_off": True},
            ]
        },
    )
    assert set_schedule.status_code == 200

    schedule = client.get(
        f"/api/team/employees/{employee_id}/weekly-schedule", headers=headers
    )
    assert schedule.status_code == 200
    rows = schedule.json()
    monday = next(row for row in rows if row["weekday"] == 0)
    tuesday = next(row for row in rows if row["weekday"] == 1)
    assert monday["start_hour"] == 9
    assert monday["end_hour"] == 12
    assert monday["source"] == "weekly"
    assert tuesday["is_day_off"] is True
    assert tuesday["source"] == "weekly"

    availability = client.get(
        "/api/availability",
        headers=headers,
        params={
            "employee_name": "Nina",
            "start_day": "2026-03-09",
            "end_day": "2026-03-10",
        },
    )
    assert availability.status_code == 200
    by_day = {row["day"]: row for row in availability.json()}
    assert by_day["2026-03-09"]["start_hour"] == 9
    assert by_day["2026-03-09"]["end_hour"] == 12
    assert by_day["2026-03-09"]["source"] == "weekly"
    assert by_day["2026-03-10"]["is_day_off"] is True
    assert by_day["2026-03-10"]["source"] == "weekly"

    outside_hours = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-09T13:00:00",
            "client_name": "Late Client",
            "employee_name": "Nina",
            "service_name": "Modelowanie",
            "price": 180,
            "duration_min": 30,
        },
    )
    assert outside_hours.status_code == 400
    assert "working hours" in outside_hours.json()["detail"].lower()

    inside_hours = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-09T10:00:00",
            "client_name": "Morning Client",
            "employee_name": "Nina",
            "service_name": "Modelowanie",
            "price": 180,
            "duration_min": 30,
        },
    )
    assert inside_hours.status_code == 200


def test_archived_employee_cannot_receive_new_visit(tmp_path):
    client = make_client(tmp_path)
    headers = _headers("team-archive")

    created = client.post("/api/team/employees", headers=headers, json={"name": "Iga"})
    assert created.status_code == 200
    employee_id = created.json()["id"]

    archived = client.delete(f"/api/team/employees/{employee_id}", headers=headers)
    assert archived.status_code == 200

    visit = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-09T10:30:00",
            "client_name": "Client",
            "employee_name": "Iga",
            "service_name": "Strzyzenie",
            "price": 200,
        },
    )
    assert visit.status_code == 400
    detail = visit.json()["detail"].lower()
    assert "unavailable" in detail or "archived" in detail
