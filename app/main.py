import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import public_router, router
from .auth_api import router as auth_api_router
from .authn import extract_identity_from_authorization_header
from .config import settings
from .db import Base, SessionLocal, engine, run_schema_migrations
from .idempotency import idempotency_middleware
from .api_messenger import router as messenger_router
from .api_payments import router as payments_router
from .api_auth import router as legacy_auth_router
from .core.observability import setup_logging, request_tracing_middleware
from .core.email_watcher import check_for_new_bookings
from .core.metrics_ext import PerformanceBudgetMiddleware, generate_latest
from .core.honeypot import HoneypotMiddleware
from .core.audit_pii import PIIAuditMiddleware
from .core.shadow_ban import ShadowBanMiddleware
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
        raise RuntimeError(
            "Database schema check failed. Run migrations before starting API."
        ) from exc

setup_logging()

# Senior IT: Sentry Integration
if settings.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        environment=settings.APP_ENV,
    )

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
import asyncio

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Senior IT: Start background tasks
    async def email_sync_loop():
        while True:
            await check_for_new_bookings()
            await asyncio.sleep(300) # Every 5 minutes
            
    loop_task = asyncio.create_task(email_sync_loop())
    yield
    loop_task.cancel()

app = FastAPI(
    title="SalonOS",
    description="Telegram-driven salon management API",
    version=_read_app_version(),
    lifespan=lifespan
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.state.session_local = SessionLocal

# Senior IT: Security first (Honeypot, ShadowBan)
app.add_middleware(ShadowBanMiddleware)
app.add_middleware(HoneypotMiddleware)
app.add_middleware(PerformanceBudgetMiddleware)
app.add_middleware(PIIAuditMiddleware)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# Senior IT: Global tracing comes first
@app.middleware("http")
async def tracing_wrapper(request: Request, call_next):
    return await request_tracing_middleware(request, call_next)


@app.middleware("http")
async def auth_context_middleware(request: Request, call_next):
    actor_email = (request.headers.get("x-actor-email") or "").strip().lower() or None
    actor_role = (request.headers.get("x-actor-role") or "").strip().lower() or None
    tenant_slug = (request.headers.get("x-tenant-slug") or "").strip().lower() or None

    identity = extract_identity_from_authorization_header(
        request.headers.get("authorization")
    )
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
        if (
            method not in {"GET", "HEAD", "OPTIONS"}
            and path not in _READ_ONLY_BYPASS_PATHS
        ):
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
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    if bool(settings.SECURITY_HEADERS_ENABLED):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com; frame-ancestors 'none'"
        )
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
    return JSONResponse(
        status_code=503, content={"status": "not_ready", "checks": checks}
    )


app.include_router(router)
app.include_router(public_router)
app.include_router(auth_api_router)
app.include_router(platform_router)
app.include_router(messenger_router)
app.include_router(payments_router)
app.include_router(legacy_auth_router)
