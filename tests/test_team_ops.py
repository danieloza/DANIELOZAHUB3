from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import get_db, public_router, router
from app.db import Base


def make_client(tmp_path):
    db_path = tmp_path / "test_salonos_team_ops.db"
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


def _headers(tenant: str, role: str = "manager") -> dict[str, str]:
    return {
        "X-Tenant-Slug": tenant,
        "X-Actor-Email": "manager@salonos.local",
        "X-Actor-Role": role,
    }


def test_capability_restricts_service_and_overrides_defaults(tmp_path):
    client = make_client(tmp_path)
    headers = _headers("team-ops-capabilities")

    created_employee = client.post(
        "/api/team/employees",
        headers=headers,
        json={"name": "Nina"},
    )
    assert created_employee.status_code == 200
    employee_id = created_employee.json()["id"]

    capability = client.post(
        f"/api/team/employees/{employee_id}/capabilities",
        headers=headers,
        json={
            "service_name": "Koloryzacja",
            "duration_min": 90,
            "price_override": 350,
            "is_active": True,
        },
    )
    assert capability.status_code == 200
    assert capability.json()["service_name"] == "Koloryzacja"

    allowed_visit = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-09T10:00:00",
            "client_name": "Klient A",
            "employee_name": "Nina",
            "service_name": "Koloryzacja",
            "price": 100,
        },
    )
    assert allowed_visit.status_code == 200
    assert allowed_visit.json()["duration_min"] == 90
    assert allowed_visit.json()["price"] == 350.0

    blocked_visit = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-09T13:00:00",
            "client_name": "Klient B",
            "employee_name": "Nina",
            "service_name": "Modelowanie",
            "price": 100,
        },
    )
    assert blocked_visit.status_code == 400
    assert "not assigned" in blocked_visit.json()["detail"].lower()


def test_leave_approval_blocks_day_availability(tmp_path):
    client = make_client(tmp_path)
    headers = _headers("team-ops-leaves")

    created_employee = client.post(
        "/api/team/employees", headers=headers, json={"name": "Iga"}
    )
    assert created_employee.status_code == 200
    employee_id = created_employee.json()["id"]

    leave = client.post(
        "/api/team/leaves",
        headers=headers,
        json={
            "employee_id": employee_id,
            "start_day": "2026-03-10",
            "end_day": "2026-03-10",
            "reason": "urlop",
        },
    )
    assert leave.status_code == 200
    leave_id = leave.json()["id"]

    approved = client.patch(
        f"/api/team/leaves/{leave_id}/decision",
        headers=headers,
        json={"decision": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    visit = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-10T10:00:00",
            "client_name": "Klient Urlop",
            "employee_name": "Iga",
            "service_name": "Modelowanie",
            "price": 120,
        },
    )
    assert visit.status_code == 400
    assert "unavailable" in visit.json()["detail"].lower()


def test_shift_swap_reassigns_visit_and_updates_day_overrides(tmp_path):
    client = make_client(tmp_path)
    headers = _headers("team-ops-swaps")

    ala = client.post("/api/team/employees", headers=headers, json={"name": "Ala"})
    beata = client.post("/api/team/employees", headers=headers, json={"name": "Beata"})
    assert ala.status_code == 200
    assert beata.status_code == 200
    ala_id = ala.json()["id"]
    beata_id = beata.json()["id"]

    visit = client.post(
        "/api/visits",
        headers=headers,
        json={
            "dt": "2026-03-12T10:00:00",
            "client_name": "Klient C",
            "employee_name": "Ala",
            "service_name": "Modelowanie",
            "price": 150,
            "duration_min": 45,
        },
    )
    assert visit.status_code == 200
    visit_id = visit.json()["id"]

    swap = client.post(
        "/api/team/swaps",
        headers=headers,
        json={
            "shift_day": "2026-03-12",
            "from_employee_id": ala_id,
            "to_employee_id": beata_id,
            "from_start_hour": 9,
            "from_end_hour": 14,
            "to_start_hour": 10,
            "to_end_hour": 18,
            "reason": "zamiana",
        },
    )
    assert swap.status_code == 200
    swap_id = swap.json()["id"]

    swap_approved = client.patch(
        f"/api/team/swaps/{swap_id}/decision",
        headers=headers,
        json={"decision": "approved"},
    )
    assert swap_approved.status_code == 200
    assert swap_approved.json()["status"] == "approved"

    reassigned = client.post(
        f"/api/team/visits/{visit_id}/reassign",
        headers=headers,
        json={"to_employee_id": beata_id, "reason": "zamiana"},
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["employee_name"] == "Beata"

    ala_availability = client.get(
        "/api/availability",
        headers=headers,
        params={
            "employee_name": "Ala",
            "start_day": "2026-03-12",
            "end_day": "2026-03-12",
        },
    )
    assert ala_availability.status_code == 200
    assert ala_availability.json()[0]["start_hour"] == 10
    assert ala_availability.json()[0]["end_hour"] == 18

    beata_availability = client.get(
        "/api/availability",
        headers=headers,
        params={
            "employee_name": "Beata",
            "start_day": "2026-03-12",
            "end_day": "2026-03-12",
        },
    )
    assert beata_availability.status_code == 200
    assert beata_availability.json()[0]["start_hour"] == 9
    assert beata_availability.json()[0]["end_hour"] == 14


def test_time_clock_notifications_and_schedule_audit(tmp_path):
    client = make_client(tmp_path)
    headers = _headers("team-ops-timeclock")

    employee = client.post("/api/team/employees", headers=headers, json={"name": "Ola"})
    assert employee.status_code == 200
    employee_id = employee.json()["id"]

    capability = client.post(
        f"/api/team/employees/{employee_id}/capabilities",
        headers=headers,
        json={"service_name": "Modelowanie", "duration_min": 45},
    )
    assert capability.status_code == 200

    check_in = client.post(
        "/api/team/time-clock/events",
        headers=headers,
        json={
            "employee_id": employee_id,
            "event_type": "check_in",
            "event_dt": "2026-03-11T09:15:00",
            "source": "test",
        },
    )
    assert check_in.status_code == 200

    check_out = client.post(
        "/api/team/time-clock/events",
        headers=headers,
        json={
            "employee_id": employee_id,
            "event_type": "check_out",
            "event_dt": "2026-03-11T17:30:00",
            "source": "test",
        },
    )
    assert check_out.status_code == 200

    report = client.get(
        "/api/team/time-clock/day-report",
        headers=headers,
        params={"day": "2026-03-11"},
    )
    assert report.status_code == 200
    ola_row = next(row for row in report.json() if row["employee_id"] == employee_id)
    assert ola_row["late_minutes"] == 15
    assert ola_row["worked_minutes"] == 495

    notifications = client.get("/api/team/notifications", headers=headers)
    assert notifications.status_code == 200
    capability_notification = next(
        row
        for row in notifications.json()
        if row["event_type"] == "capability_changed"
        and row["employee_id"] == employee_id
    )

    marked = client.patch(
        f"/api/team/notifications/{capability_notification['id']}/status",
        headers=headers,
        json={"status": "sent"},
    )
    assert marked.status_code == 200
    assert marked.json()["status"] == "sent"

    audit = client.get("/api/team/schedule-audit", headers=headers)
    assert audit.status_code == 200
    actions = {row["action"] for row in audit.json()}
    assert "capability.upsert" in actions
    assert "time_clock.event" in actions
