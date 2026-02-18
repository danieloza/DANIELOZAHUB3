# -*- coding: utf-8 -*-

import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
TENANT_SLUG = os.getenv("TENANT_SLUG", "").strip()


def _headers() -> dict:
    if not TENANT_SLUG:
        return {}
    return {"X-Tenant-Slug": TENANT_SLUG}


def api_get(path: str, params: dict | None = None):
    r = requests.get(f"{API_BASE_URL}{path}", params=params, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r


def api_post(path: str, json: dict):
    r = requests.post(f"{API_BASE_URL}{path}", json=json, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def api_patch(path: str, json: dict):
    r = requests.patch(f"{API_BASE_URL}{path}", json=json, headers=_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def api_delete(path: str):
    r = requests.delete(f"{API_BASE_URL}{path}", headers=_headers(), timeout=10)
    r.raise_for_status()
    return None


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def fetch_busy_intervals(day_iso: str, employee_name: str, default_duration_min: int) -> list[tuple[datetime, datetime]]:
    try:
        r = api_get("/api/visits", {"day": day_iso, "employee_name": employee_name})
        visits = r.json()
    except Exception:
        return []

    busy: list[tuple[datetime, datetime]] = []
    for v in (visits or []):
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
        r = api_get("/api/visits", {"day": day_iso, "employee_name": employee_name})
        return r.json() or []
    except Exception:
        return []
