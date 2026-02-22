import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Lock

import redis

from .config import settings

_logger = logging.getLogger("salonos.observability")

_HTTP_EVENTS_MAX = 20000
_http_events: deque[dict] = deque(maxlen=_HTTP_EVENTS_MAX)
_events_lock = Lock()


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def configure_logging() -> None:
    if _logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def emit_json_log(payload: dict) -> None:
    safe_payload = dict(payload)
    safe_payload.setdefault("ts", utc_now_naive().isoformat() + "Z")
    _logger.info(json.dumps(safe_payload, ensure_ascii=True))


def _redis_client() -> redis.Redis | None:
    redis_url = (settings.REDIS_URL or "").strip()
    if not redis_url:
        return None
    try:
        return redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


def _stream_name() -> str:
    name = (settings.OPS_EVENTS_STREAM or "").strip()
    return name or "salonos.http_events"


def _parse_event_ts(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _to_bool(raw: str | None) -> bool:
    value = str(raw or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _load_recent_redis_events(window_minutes: int) -> list[dict]:
    if not bool(settings.OPS_EVENTS_PERSIST_ENABLED):
        return []
    client = _redis_client()
    if client is None:
        return []

    cutoff = utc_now_naive() - timedelta(minutes=max(1, int(window_minutes)))
    try:
        rows = client.xrevrange(_stream_name(), count=_HTTP_EVENTS_MAX)
    except Exception:
        return []

    out: list[dict] = []
    for _event_id, fields in rows:
        ts = _parse_event_ts(fields.get("ts"))
        if ts is None or ts < cutoff:
            continue
        try:
            out.append(
                {
                    "ts": ts,
                    "method": str(fields.get("method") or "").upper(),
                    "path": str(fields.get("path") or ""),
                    "status_code": int(fields.get("status_code") or 0),
                    "duration_ms": float(fields.get("duration_ms") or 0.0),
                    "request_id": str(fields.get("request_id") or ""),
                    "tenant_slug": str(fields.get("tenant_slug") or "").strip().lower() or None,
                    "timeout_like": _to_bool(fields.get("timeout_like")),
                }
            )
        except Exception:
            continue
    return out


def record_http_event(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    request_id: str,
    tenant_slug: str | None = None,
) -> None:
    event = {
        "ts": utc_now_naive(),
        "method": method.upper(),
        "path": path,
        "status_code": int(status_code),
        "duration_ms": float(duration_ms),
        "request_id": request_id,
        "tenant_slug": (tenant_slug or "").strip().lower() or None,
        "timeout_like": float(duration_ms) >= float(settings.OPS_TIMEOUT_LIKE_MS),
    }
    with _events_lock:
        _http_events.append(event)
    if bool(settings.OPS_EVENTS_PERSIST_ENABLED):
        client = _redis_client()
        if client is not None:
            try:
                client.xadd(
                    _stream_name(),
                    {
                        "ts": event["ts"].isoformat() + "Z",
                        "method": event["method"],
                        "path": event["path"],
                        "status_code": str(event["status_code"]),
                        "duration_ms": str(event["duration_ms"]),
                        "request_id": event["request_id"],
                        "tenant_slug": event["tenant_slug"] or "",
                        "timeout_like": "1" if bool(event["timeout_like"]) else "0",
                    },
                    maxlen=_HTTP_EVENTS_MAX * 5,
                    approximate=True,
                )
            except Exception:
                pass


def _recent_http_events(window_minutes: int) -> list[dict]:
    now = utc_now_naive()
    cutoff = now - timedelta(minutes=max(1, int(window_minutes)))
    redis_events = _load_recent_redis_events(window_minutes)
    with _events_lock:
        local_events = [e for e in list(_http_events) if e["ts"] >= cutoff]
    if not redis_events:
        return local_events

    # Merge and dedupe by request fingerprint so local fallback does not inflate counts.
    merged: list[dict] = []
    seen: set[tuple[str, str, int, int]] = set()
    for e in redis_events + local_events:
        stamp = int(e["ts"].timestamp())
        key = (
            str(e.get("request_id") or ""),
            str(e.get("path") or ""),
            int(e.get("status_code") or 0),
            stamp,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
    return merged


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    items = sorted(values)
    idx = int(round((len(items) - 1) * p))
    return float(items[max(0, min(idx, len(items) - 1))])


def get_ops_metrics_snapshot(window_minutes: int = 15) -> dict:
    events = _recent_http_events(window_minutes)
    durations = [float(e["duration_ms"]) for e in events]

    by_status_class = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    by_path: dict[str, int] = {}
    error_5xx_count = 0
    timeout_like_count = 0
    tenant_event_count: dict[str, int] = {}
    for e in events:
        status = int(e["status_code"])
        cls = f"{status // 100}xx"
        if cls in by_status_class:
            by_status_class[cls] += 1
        by_path[e["path"]] = by_path.get(e["path"], 0) + 1
        if status >= 500:
            error_5xx_count += 1
        if e.get("timeout_like"):
            timeout_like_count += 1
        tenant = e.get("tenant_slug")
        if tenant:
            tenant_event_count[tenant] = tenant_event_count.get(tenant, 0) + 1

    top_paths = [
        {"path": path, "count": count}
        for path, count in sorted(by_path.items(), key=lambda x: (-x[1], x[0]))[:10]
    ]
    return {
        "window_minutes": int(window_minutes),
        "checked_at": utc_now_naive(),
        "requests_total": len(events),
        "error_5xx_count": int(error_5xx_count),
        "timeout_like_count": int(timeout_like_count),
        "latency_ms_p50": round(_percentile(durations, 0.50), 2),
        "latency_ms_p95": round(_percentile(durations, 0.95), 2),
        "by_status_class": by_status_class,
        "top_paths": top_paths,
        "tenant_event_count": tenant_event_count,
    }


def get_ops_alerts(
    *,
    window_minutes: int = 15,
    integrity_issues_count: int | None = None,
) -> list[dict]:
    metrics = get_ops_metrics_snapshot(window_minutes=window_minutes)
    alerts: list[dict] = []
    if metrics["error_5xx_count"] > 0:
        alerts.append(
            {
                "code": "ops_5xx_detected",
                "severity": "high",
                "message": f"Detected {metrics['error_5xx_count']} server errors in last {window_minutes} min",
            }
        )
    if metrics["timeout_like_count"] > 0:
        alerts.append(
            {
                "code": "ops_timeout_like_detected",
                "severity": "medium",
                "message": f"Detected {metrics['timeout_like_count']} timeout-like requests in last {window_minutes} min",
            }
        )
    if integrity_issues_count is not None and int(integrity_issues_count) > 0:
        alerts.append(
            {
                "code": "integrity_issues_detected",
                "severity": "high",
                "message": f"Detected {int(integrity_issues_count)} conversion integrity issues",
            }
        )

    if not alerts:
        alerts.append(
            {
                "code": "ops_ok",
                "severity": "info",
                "message": "No operational alerts",
            }
        )
    return alerts
