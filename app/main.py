import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

import redis

from .auth_api import router as auth_router
from .authn import extract_identity_from_authorization_header
from .api import public_router, router
from .config import settings
from .db import Base, SessionLocal, engine, run_schema_migrations
from .idempotency import idempotency_middleware
from .observability import configure_logging, emit_json_log, record_http_event
from .platform_api import router as platform_router
from .request_context import actor_email_ctx, actor_role_ctx, tenant_slug_ctx

_MAINTENANCE_BYPASS_PREFIXES = (
    "/health",
    "/ping",
    "/docs",
    "/redoc",
    "/openapi.json",
)
_READ_ONLY_BYPASS_PATHS = {
    "/auth/login",
    "/auth/refresh",
    "/auth/logout",
}


def _read_app_version() -> str:
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
        return value or "0.1.0"
    except Exception:
        return "0.1.0"


run_schema_migrations()
if settings.DATABASE_URL.startswith("sqlite"):
    Base.metadata.create_all(bind=engine)
elif bool(settings.DB_AUTO_CREATE_ALL):
    Base.metadata.create_all(bind=engine)
elif bool(settings.DB_SCHEMA_CHECK_ON_STARTUP):
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM tenants LIMIT 1"))
    except Exception as exc:
        raise RuntimeError("Database schema check failed. Run migrations before starting API.") from exc
configure_logging()

app = FastAPI(
    title="SalonOS",
    description="Telegram-driven salon management API",
    version=_read_app_version(),
)
app.state.session_local = SessionLocal


@app.middleware("http")
async def auth_context_middleware(request: Request, call_next):
    actor_email = (request.headers.get("x-actor-email") or "").strip().lower() or None
    actor_role = (request.headers.get("x-actor-role") or "").strip().lower() or None
    tenant_slug = (request.headers.get("x-tenant-slug") or "").strip().lower() or None

    identity = extract_identity_from_authorization_header(request.headers.get("authorization"))
    if identity:
        actor_email = actor_email or identity.email
        actor_role = actor_role or identity.role
        tenant_slug = tenant_slug or identity.tenant_slug

    actor_email_ctx.set(actor_email)
    actor_role_ctx.set(actor_role)
    tenant_slug_ctx.set(tenant_slug)
    return await call_next(request)


@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    path = request.url.path or ""
    method = request.method.upper()
    retry_after = str(max(1, int(settings.MAINTENANCE_RETRY_AFTER_SECONDS)))

    if bool(settings.MAINTENANCE_MODE):
        if not any(path.startswith(prefix) for prefix in _MAINTENANCE_BYPASS_PREFIXES):
            return JSONResponse(
                status_code=503,
                content={"detail": "Service temporarily unavailable: maintenance mode"},
                headers={"Retry-After": retry_after},
            )

    if bool(settings.MAINTENANCE_READ_ONLY):
        if method not in {"GET", "HEAD", "OPTIONS"} and path not in _READ_ONLY_BYPASS_PATHS:
            return JSONResponse(
                status_code=503,
                content={"detail": "Service is in read-only mode"},
                headers={"Retry-After": retry_after},
            )
    return await call_next(request)


@app.middleware("http")
async def app_idempotency_middleware(request: Request, call_next):
    return await idempotency_middleware(request, call_next)


@app.middleware("http")
async def request_observability_middleware(request: Request, call_next):
    request_id = (request.headers.get("x-request-id") or "").strip() or str(uuid.uuid4())
    tenant_slug = (request.headers.get("x-tenant-slug") or "").strip().lower() or None
    start = time.perf_counter()

    try:
        response = await call_next(request)
        status_code = int(response.status_code)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
        record_http_event(
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=duration_ms,
            request_id=request_id,
            tenant_slug=tenant_slug,
        )
        emit_json_log(
            {
                "level": "error",
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
                "tenant_slug": tenant_slug,
                "error": str(exc),
            }
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"}, headers={"X-Request-ID": request_id})

    duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
    record_http_event(
        method=request.method,
        path=request.url.path,
        status_code=status_code,
        duration_ms=duration_ms,
        request_id=request_id,
        tenant_slug=tenant_slug,
    )
    emit_json_log(
        {
            "level": "info",
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "tenant_slug": tenant_slug,
        }
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    if bool(settings.SECURITY_HEADERS_ENABLED):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/ping")
def ping():
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    checks = {
        "db": "ok",
        "redis": "skipped",
        "event_bus": "skipped",
    }

    db_ok = True
    redis_ok = True

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        checks["db"] = "error"
        db_ok = False

    redis_url = (settings.REDIS_URL or "").strip()
    if redis_url:
        try:
            client = redis.from_url(redis_url, decode_responses=True)
            client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"
            redis_ok = False

    if bool(settings.EVENT_BUS_ENABLED):
        checks["event_bus"] = "ok" if redis_ok else "error"

    if db_ok and (not bool(settings.EVENT_BUS_ENABLED) or redis_ok):
        return {"status": "ready", "checks": checks}
    return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})


app.include_router(router)
app.include_router(public_router)
app.include_router(auth_router)
app.include_router(platform_router)
