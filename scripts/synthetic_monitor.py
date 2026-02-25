import argparse
import json
from datetime import datetime, timedelta, timezone

import requests


def _iso_future(hours: int = 4) -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=hours)
    return dt.replace(microsecond=0).isoformat()


def _must_ok(response, step: str) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{step} failed: HTTP {response.status_code} body={response.text}"
        )
    return response.json() if response.text else {}


def run_flow(base_url: str, tenant_slug: str) -> dict:
    actor_headers = {
        "X-Tenant-Slug": tenant_slug,
        "X-Actor-Email": "synthetic@salonos.local",
        "X-Actor-Role": "manager",
    }
    public_payload = {
        "requested_dt": _iso_future(6),
        "client_name": "Synthetic Client",
        "service_name": "Modelowanie",
        "phone": "+48123000999",
        "note": "synthetic",
    }
    create = requests.post(
        f"{base_url}/public/{tenant_slug}/reservations", json=public_payload, timeout=10
    )
    reservation = _must_ok(create, "create_reservation")
    reservation_id = int(reservation["id"])

    contacted = requests.patch(
        f"{base_url}/api/reservations/{reservation_id}/status",
        headers=actor_headers,
        json={"status": "contacted"},
        timeout=10,
    )
    _must_ok(contacted, "status_contacted")

    convert = requests.post(
        f"{base_url}/api/reservations/{reservation_id}/convert",
        headers=actor_headers,
        json={"employee_name": "Magda", "price": 200},
        timeout=10,
    )
    visit = _must_ok(convert, "convert_to_visit")
    visit_id = int(visit["id"])

    integrity = requests.get(
        f"{base_url}/api/integrity/conversions",
        headers={"X-Tenant-Slug": tenant_slug},
        timeout=10,
    )
    integrity_json = _must_ok(integrity, "integrity_check")
    if not bool(integrity_json.get("ok", False)):
        raise RuntimeError("integrity_check failed: conversion report not ok")

    return {
        "tenant_slug": tenant_slug,
        "reservation_id": reservation_id,
        "visit_id": visit_id,
        "integrity_ok": bool(integrity_json.get("ok", False)),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synthetic monitor for reservation->convert flow"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant", default="synthetic-monitor")
    args = parser.parse_args()

    report = run_flow(
        base_url=args.base_url.rstrip("/"), tenant_slug=args.tenant.strip().lower()
    )
    print(json.dumps({"ok": True, "report": report}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
