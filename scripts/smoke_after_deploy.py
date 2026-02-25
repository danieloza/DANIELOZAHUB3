import argparse
import json
from datetime import datetime, timezone

import requests


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(url: str, timeout: float) -> dict:
    response = requests.get(url, timeout=timeout)
    return {
        "url": url,
        "status_code": response.status_code,
        "ok": response.status_code < 500,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SalonOS post-deploy smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    targets = [
        f"{args.base_url.rstrip('/')}/ping",
        f"{args.base_url.rstrip('/')}/health",
        f"{args.base_url.rstrip('/')}/docs",
        f"{args.base_url.rstrip('/')}/openapi.json",
    ]
    results = [_check(url, args.timeout) for url in targets]
    ok = all(item["ok"] for item in results)
    report = {
        "checked_at": _utc_now_iso(),
        "base_url": args.base_url,
        "ok": ok,
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
