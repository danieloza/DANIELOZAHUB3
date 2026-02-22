from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hmac
import secrets
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from .authn import (
    AuthIdentity,
    authenticate_user,
    change_user_password,
    cleanup_expired_refresh_sessions,
    create_access_token,
    create_refresh_session,
    create_user,
    extract_identity_from_authorization_header,
    generate_mfa_secret,
    get_refresh_session_by_id,
    get_user,
    list_refresh_sessions,
    mfa_uri,
    revoke_refresh_session,
    revoke_all_refresh_sessions_for_user,
    revoke_refresh_session_by_token,
    use_refresh_session,
    verify_mfa_code,
)
from .config import settings
from .db import get_db
from .models import AuthUser, Tenant
from .services import get_or_create_tenant

router = APIRouter(prefix="/auth", tags=["auth"])
_login_failures: dict[str, deque[datetime]] = defaultdict(deque)
_login_failures_lock = Lock()


class AuthRegisterIn(BaseModel):
    tenant_slug: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="reception", min_length=4, max_length=32)


class AuthLoginIn(BaseModel):
    tenant_slug: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=8, max_length=200)
    mfa_code: Optional[str] = Field(default=None, min_length=6, max_length=12)


class AuthRefreshIn(BaseModel):
    tenant_slug: str = Field(min_length=2, max_length=80)
    refresh_token: str = Field(min_length=20, max_length=300)


class AuthLogoutOut(BaseModel):
    ok: bool


class AuthPasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class AuthTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str
    expires_in_seconds: int
    tenant_slug: str
    role: str
    mfa_enabled: bool


class AuthMeOut(BaseModel):
    tenant_slug: str
    email: str
    role: str
    amr: str
    mfa_enabled: bool


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_url: str


class MfaVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class AuthSessionOut(BaseModel):
    id: int
    user_id: int
    is_revoked: bool
    expires_at: datetime
    created_at: datetime


class AuthSessionsCleanupOut(BaseModel):
    tenant_slug: str
    revoked_expired_sessions: int


class AuthPasswordChangeOut(BaseModel):
    ok: bool
    revoked_sessions: int


def _resolve_tenant(db: Session, tenant_slug: str) -> Tenant:
    slug = tenant_slug.strip().lower()
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_slug is required")
    return get_or_create_tenant(db=db, slug=slug, name=slug)


def _identity_from_auth_header(authorization: Optional[str]) -> AuthIdentity:
    identity = extract_identity_from_authorization_header(authorization)
    if not identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing bearer token")
    return identity


def _client_ip_from_request(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first[:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return "unknown"


def _login_rate_limit_key(tenant_slug: str, email: str, client_ip: str) -> str:
    return f"{tenant_slug.strip().lower()}|{email.strip().lower()}|{client_ip.strip().lower()}"


def _redis_client() -> redis.Redis | None:
    if not settings.REDIS_URL:
        return None
    try:
        return redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def _login_rate_limit_redis_key(tenant_slug: str, email: str, client_ip: str) -> str:
    key = _login_rate_limit_key(tenant_slug, email, client_ip)
    return f"salonos:auth:fail:z:{key}"


def _prune_login_failures(now: datetime) -> None:
    retention_h = max(1, int(settings.AUTH_LOGIN_RL_EVENT_RETENTION_HOURS))
    cutoff = now - timedelta(hours=retention_h)
    to_delete = []
    for key, events in _login_failures.items():
        while events and events[0] < cutoff:
            events.popleft()
        if not events:
            to_delete.append(key)
    for key in to_delete:
        _login_failures.pop(key, None)


def _is_login_rate_limited(tenant_slug: str, email: str, client_ip: str) -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    redis_client = _redis_client()
    if redis_client is not None:
        per_min = max(1, int(settings.AUTH_LOGIN_RL_PER_MIN))
        per_hour = max(1, int(settings.AUTH_LOGIN_RL_PER_HOUR))
        retention_h = max(1, int(settings.AUTH_LOGIN_RL_EVENT_RETENTION_HOURS))
        now_ts = int(datetime.now(timezone.utc).timestamp())
        minute_cutoff_ts = now_ts - 60
        hour_cutoff_ts = now_ts - 3600
        retention_cutoff_ts = now_ts - (retention_h * 3600)
        redis_key = _login_rate_limit_redis_key(tenant_slug, email, client_ip)
        try:
            pipe = redis_client.pipeline()
            pipe.zremrangebyscore(redis_key, 0, retention_cutoff_ts)
            pipe.zcount(redis_key, minute_cutoff_ts, "+inf")
            pipe.zcount(redis_key, hour_cutoff_ts, "+inf")
            pipe.expire(redis_key, (retention_h * 3600) + 3600)
            result = pipe.execute()
            min_count = int(result[1] or 0)
            hour_count = int(result[2] or 0)
            return min_count >= per_min or hour_count >= per_hour
        except Exception:
            pass

    key = _login_rate_limit_key(tenant_slug, email, client_ip)
    minute_cutoff = now - timedelta(minutes=1)
    hour_cutoff = now - timedelta(hours=1)
    per_min = max(1, int(settings.AUTH_LOGIN_RL_PER_MIN))
    per_hour = max(1, int(settings.AUTH_LOGIN_RL_PER_HOUR))

    with _login_failures_lock:
        _prune_login_failures(now)
        events = _login_failures.get(key) or deque()
        minute_count = sum(1 for ts in events if ts >= minute_cutoff)
        hour_count = sum(1 for ts in events if ts >= hour_cutoff)
        return minute_count >= per_min or hour_count >= per_hour


def _record_login_failure(tenant_slug: str, email: str, client_ip: str) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    redis_client = _redis_client()
    if redis_client is not None:
        retention_h = max(1, int(settings.AUTH_LOGIN_RL_EVENT_RETENTION_HOURS))
        now_ts = int(datetime.now(timezone.utc).timestamp())
        retention_cutoff_ts = now_ts - (retention_h * 3600)
        redis_key = _login_rate_limit_redis_key(tenant_slug, email, client_ip)
        member = f"{now_ts}:{secrets.token_hex(8)}"
        try:
            pipe = redis_client.pipeline()
            pipe.zadd(redis_key, {member: now_ts})
            pipe.zremrangebyscore(redis_key, 0, retention_cutoff_ts)
            pipe.expire(redis_key, (retention_h * 3600) + 3600)
            pipe.execute()
            return
        except Exception:
            pass

    key = _login_rate_limit_key(tenant_slug, email, client_ip)
    with _login_failures_lock:
        _prune_login_failures(now)
        _login_failures[key].append(now)


def _clear_login_failures(tenant_slug: str, email: str, client_ip: str) -> None:
    redis_client = _redis_client()
    if redis_client is not None:
        try:
            redis_key = _login_rate_limit_redis_key(tenant_slug, email, client_ip)
            redis_client.delete(redis_key)
        except Exception:
            pass
    key = _login_rate_limit_key(tenant_slug, email, client_ip)
    with _login_failures_lock:
        _login_failures.pop(key, None)


@router.post("/register", response_model=AuthMeOut)
def register(
    payload: AuthRegisterIn,
    x_admin_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    # Register is admin-protected when ADMIN_API_KEY is configured.
    expected = (settings.ADMIN_API_KEY or "").strip()
    incoming = (x_admin_api_key or "").strip()
    if expected and not hmac.compare_digest(expected, incoming):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin API key")

    tenant = _resolve_tenant(db, payload.tenant_slug)
    try:
        row = create_user(
            db=db,
            tenant=tenant,
            email=payload.email,
            password=payload.password,
            role=payload.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return AuthMeOut(
        tenant_slug=tenant.slug,
        email=row.email,
        role=row.role,
        amr="pwd",
        mfa_enabled=bool(row.mfa_enabled),
    )


@router.post("/login", response_model=AuthTokenOut)
def login(payload: AuthLoginIn, request: Request, db: Session = Depends(get_db)):
    tenant = _resolve_tenant(db, payload.tenant_slug)
    client_ip = _client_ip_from_request(request)
    if _is_login_rate_limited(tenant.slug, payload.email, client_ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed login attempts")
    user = authenticate_user(db, tenant, payload.email, payload.password)
    if not user:
        _record_login_failure(tenant.slug, payload.email, client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if bool(settings.AUTH_REQUIRE_MFA) and not bool(user.mfa_enabled):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MFA setup required")

    if user.mfa_enabled:
        if not payload.mfa_code or not verify_mfa_code(user.mfa_secret or "", payload.mfa_code):
            _record_login_failure(tenant.slug, payload.email, client_ip)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")
        amr = "pwd+mfa"
    else:
        amr = "pwd"

    identity = AuthIdentity(
        email=user.email,
        role=user.role,
        tenant_slug=tenant.slug,
        user_id=user.id,
        amr=amr,
    )
    access_token = create_access_token(identity=identity)
    refresh_token, _session = create_refresh_session(db, tenant.id, user.id)
    _clear_login_failures(tenant.slug, payload.email, client_ip)
    return AuthTokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_seconds=int(settings.AUTH_ACCESS_TOKEN_MINUTES) * 60,
        tenant_slug=tenant.slug,
        role=user.role,
        mfa_enabled=bool(user.mfa_enabled),
    )


@router.post("/refresh", response_model=AuthTokenOut)
def refresh(payload: AuthRefreshIn, db: Session = Depends(get_db)):
    tenant = _resolve_tenant(db, payload.tenant_slug)
    session = use_refresh_session(db, tenant.id, payload.refresh_token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = db.execute(
        select(AuthUser).where(AuthUser.id == session.user_id, AuthUser.tenant_id == tenant.id)
    ).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    revoke_refresh_session(db, session.id)
    identity = AuthIdentity(
        email=user.email,
        role=user.role,
        tenant_slug=tenant.slug,
        user_id=user.id,
        amr="refresh",
    )
    access_token = create_access_token(identity=identity)
    refresh_token, _new_session = create_refresh_session(db, tenant.id, user.id)
    return AuthTokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_seconds=int(settings.AUTH_ACCESS_TOKEN_MINUTES) * 60,
        tenant_slug=tenant.slug,
        role=user.role,
        mfa_enabled=bool(user.mfa_enabled),
    )


@router.post("/logout", response_model=AuthLogoutOut)
def logout(payload: AuthRefreshIn, db: Session = Depends(get_db)):
    tenant = _resolve_tenant(db, payload.tenant_slug)
    revoked = revoke_refresh_session_by_token(db, tenant.id, payload.refresh_token)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return AuthLogoutOut(ok=True)


@router.get("/sessions", response_model=list[AuthSessionOut])
def list_sessions(
    scope: str = Query(default="self", pattern="^(self|tenant)$"),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _identity_from_auth_header(authorization)
    tenant = db.execute(select(Tenant).where(Tenant.slug == identity.tenant_slug)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    if scope == "tenant":
        if identity.role not in {"owner", "manager"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden scope")
        rows = list_refresh_sessions(db, tenant_id=tenant.id, user_id=None, include_revoked=False, limit=500)
    else:
        rows = list_refresh_sessions(db, tenant_id=tenant.id, user_id=identity.user_id, include_revoked=False, limit=200)
    return [
        AuthSessionOut(
            id=row.id,
            user_id=row.user_id,
            is_revoked=bool(row.is_revoked),
            expires_at=row.expires_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/sessions/{session_id}/revoke", response_model=AuthLogoutOut)
def revoke_session(
    session_id: int,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _identity_from_auth_header(authorization)
    tenant = db.execute(select(Tenant).where(Tenant.slug == identity.tenant_slug)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    row = get_refresh_session_by_id(db, tenant_id=tenant.id, session_id=session_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if identity.role not in {"owner", "manager"} and int(row.user_id) != int(identity.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden session")
    revoke_refresh_session(db, row.id)
    return AuthLogoutOut(ok=True)


@router.post("/sessions/cleanup", response_model=AuthSessionsCleanupOut)
def cleanup_sessions(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _identity_from_auth_header(authorization)
    if identity.role not in {"owner", "manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner/manager can cleanup tenant sessions")
    tenant = db.execute(select(Tenant).where(Tenant.slug == identity.tenant_slug)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    cleaned = cleanup_expired_refresh_sessions(db, tenant_id=tenant.id)
    return AuthSessionsCleanupOut(tenant_slug=tenant.slug, revoked_expired_sessions=cleaned)


@router.post("/password/change", response_model=AuthPasswordChangeOut)
def change_password(
    payload: AuthPasswordChangeIn,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _identity_from_auth_header(authorization)
    tenant = db.execute(select(Tenant).where(Tenant.slug == identity.tenant_slug)).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    try:
        _ = change_user_password(
            db=db,
            tenant_id=tenant.id,
            email=identity.email,
            old_password=payload.current_password,
            new_password=payload.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    revoked = revoke_all_refresh_sessions_for_user(db, tenant_id=tenant.id, user_id=identity.user_id)
    return AuthPasswordChangeOut(ok=True, revoked_sessions=int(revoked))


@router.get("/me", response_model=AuthMeOut)
def me(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _identity_from_auth_header(authorization)
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == identity.tenant_slug)
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    user = get_user(db, tenant.id, identity.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return AuthMeOut(
        tenant_slug=identity.tenant_slug,
        email=identity.email,
        role=identity.role,
        amr=identity.amr,
        mfa_enabled=bool(user.mfa_enabled),
    )


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _identity_from_auth_header(authorization)
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == identity.tenant_slug)
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    user = get_user(db, tenant.id, identity.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    secret = generate_mfa_secret()
    user.mfa_secret = secret
    user.mfa_enabled = False
    user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return MfaSetupOut(secret=secret, otpauth_url=mfa_uri(user.email, secret))


@router.post("/mfa/verify", response_model=AuthMeOut)
def mfa_verify(
    payload: MfaVerifyIn,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _identity_from_auth_header(authorization)
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == identity.tenant_slug)
    ).scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown tenant")
    user = get_user(db, tenant.id, identity.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    if not verify_mfa_code(user.mfa_secret or "", payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code")
    user.mfa_enabled = True
    user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return AuthMeOut(
        tenant_slug=tenant.slug,
        email=user.email,
        role=user.role,
        amr="pwd+mfa",
        mfa_enabled=True,
    )
