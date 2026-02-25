import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TENANT_SLUG = os.getenv("TENANT_SLUG", "").strip()
BOT_ACTOR_EMAIL = os.getenv("BOT_ACTOR_EMAIL", "bot@salonos.local").strip().lower()
BOT_ACTOR_ROLE = os.getenv("BOT_ACTOR_ROLE", "manager").strip().lower()


def _headers() -> dict:
    headers: dict[str, str] = {}
    if TENANT_SLUG:
        headers["X-Tenant-Slug"] = TENANT_SLUG
    if BOT_ACTOR_EMAIL:
        headers["X-Actor-Email"] = BOT_ACTOR_EMAIL
    if BOT_ACTOR_ROLE:
        headers["X-Actor-Role"] = BOT_ACTOR_ROLE
    return headers


def api_get(path: str, params: dict | None = None):
    r = requests.get(
        f"{API_BASE_URL}{path}", params=params, headers=_headers(), timeout=10
    )
    r.raise_for_status()
    return r


def api_get_json(path: str, params: dict | None = None):
    return api_get(path, params=params).json()


def api_post(path: str, json: dict):
    r = requests.post(
        f"{API_BASE_URL}{path}", json=json, headers=_headers(), timeout=10
    )
    r.raise_for_status()
    return r.json()


def api_patch(path: str, json: dict):
    r = requests.patch(
        f"{API_BASE_URL}{path}", json=json, headers=_headers(), timeout=10
    )
    r.raise_for_status()
    return r.json()


def api_delete(path: str):
    r = requests.delete(f"{API_BASE_URL}{path}", headers=_headers(), timeout=10)
    r.raise_for_status()
    return None


def overlaps(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    return a_start < b_end and b_start < a_end


def fetch_busy_intervals(
    day_iso: str, employee_name: str, default_duration_min: int
) -> list[tuple[datetime, datetime]]:
    try:
        r = api_get("/api/visits", {"day": day_iso, "employee_name": employee_name})
        visits = r.json()
    except Exception:
        return []

    busy: list[tuple[datetime, datetime]] = []
    for v in visits or []:
        try:
            start = datetime.fromisoformat(v["dt"])
            dur = int(v.get("duration_min") or default_duration_min)
            end = start + timedelta(minutes=dur)
            busy.append((start, end))
        except Exception:
            continue
    return busy


def fetch_visits_for_day(day_iso: str, employee_name: str) -> list[dict]:
    try:
        return (
            api_get_json(
                "/api/visits", {"day": day_iso, "employee_name": employee_name}
            )
            or []
        )
    except Exception:
        return []


def fetch_slot_recommendations(
    day_iso: str, employee_name: str, service_name: str, duration_min: int | None = None
) -> list[dict]:
    params = {
        "day": day_iso,
        "employee_name": employee_name,
        "service_name": service_name,
        "limit": 6,
    }
    if duration_min:
        params["duration_min"] = int(duration_min)
    try:
        return api_get_json("/api/slots/recommendations", params) or []
    except Exception:
        return []


def fetch_day_pulse(day_iso: str) -> dict | None:
    try:
        return api_get_json("/api/pulse/day", {"day": day_iso})
    except Exception:
        return None


def fetch_client_search(query: str, limit: int = 10) -> list[dict]:
    try:
        return api_get_json("/api/clients/search", {"q": query, "limit": limit}) or []
    except Exception:
        return []


def fetch_client_detail(client_id: int) -> dict | None:
    try:
        return api_get_json(f"/api/clients/{int(client_id)}")
    except Exception:
        return None


def create_client_note(client_id: int, note: str) -> dict | None:
    try:
        return api_post(f"/api/clients/{int(client_id)}/notes", {"note": note})
    except Exception:
        return None


def fetch_employee_availability(
    employee_name: str, start_day: str, end_day: str
) -> list[dict]:
    try:
        return (
            api_get_json(
                "/api/availability",
                {
                    "employee_name": employee_name,
                    "start_day": start_day,
                    "end_day": end_day,
                },
            )
            or []
        )
    except Exception:
        return []


def set_employee_day_off(
    employee_name: str,
    day_iso: str,
    is_day_off: bool = True,
    start_hour: int | None = None,
    end_hour: int | None = None,
    note: str | None = None,
) -> dict | None:
    payload = {
        "employee_name": employee_name,
        "day": day_iso,
        "is_day_off": bool(is_day_off),
        "start_hour": start_hour,
        "end_hour": end_hour,
        "note": note,
    }
    try:
        return api_post("/api/availability/day", payload)
    except Exception:
        return None


def add_employee_block(
    employee_name: str, start_dt_iso: str, end_dt_iso: str, reason: str | None = None
) -> dict | None:
    payload = {
        "employee_name": employee_name,
        "start_dt": start_dt_iso,
        "end_dt": end_dt_iso,
        "reason": reason,
    }
    try:
        return api_post("/api/availability/blocks", payload)
    except Exception:
        return None


def set_service_buffer(
    service_name: str, before_min: int, after_min: int
) -> dict | None:
    try:
        return api_post(
            f"/api/buffers/service/{service_name}",
            {"before_min": int(before_min), "after_min": int(after_min)},
        )
    except Exception:
        return None


def set_employee_buffer(
    employee_name: str, before_min: int, after_min: int
) -> dict | None:
    try:
        return api_post(
            f"/api/buffers/employee/{employee_name}",
            {"before_min": int(before_min), "after_min": int(after_min)},
        )
    except Exception:
        return None


def fetch_assistant_actions(limit: int = 10) -> list[dict]:
    try:
        return api_get_json("/api/reservations/assistant", {"limit": int(limit)}) or []
    except Exception:
        return []


def fetch_team_employees() -> list[dict]:
    try:
        return api_get_json("/api/team/employees") or []
    except Exception:
        return []
