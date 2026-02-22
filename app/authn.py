import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pyotp
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import AuthSession, AuthUser, Tenant

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class AuthIdentity:
    email: str
    role: str
    tenant_slug: str
    user_id: int
    amr: str


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def validate_password_policy(password: str) -> None:
    raw = str(password or "")
    min_len = max(8, int(settings.AUTH_PASSWORD_MIN_LENGTH))
    if len(raw) < min_len:
        raise ValueError(f"password must be at least {min_len} chars")
    if bool(settings.AUTH_PASSWORD_REQUIRE_UPPER) and not re.search(r"[A-Z]", raw):
        raise ValueError("password must contain at least one uppercase letter")
    if bool(settings.AUTH_PASSWORD_REQUIRE_LOWER) and not re.search(r"[a-z]", raw):
        raise ValueError("password must contain at least one lowercase letter")
    if bool(settings.AUTH_PASSWORD_REQUIRE_DIGIT) and not re.search(r"[0-9]", raw):
        raise ValueError("password must contain at least one digit")
    if bool(settings.AUTH_PASSWORD_REQUIRE_SPECIAL) and not re.search(r"[^A-Za-z0-9]", raw):
        raise ValueError("password must contain at least one special character")


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _token_exp(minutes: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=max(1, int(minutes)))


def _jwt_keyring() -> dict[str, str]:
    raw = (settings.AUTH_JWT_KEYS or "").strip()
    ring: dict[str, str] = {}
    if raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        auto_idx = 1
        for item in parts:
            if ":" in item:
                kid, key = item.split(":", 1)
                kid = kid.strip()
                key = key.strip()
                if kid and key:
                    ring[kid] = key
            else:
                ring[f"k{auto_idx}"] = item
                auto_idx += 1
    if not ring:
        ring["default"] = settings.AUTH_SECRET_KEY
    return ring


def _active_jwt_kid(ring: dict[str, str]) -> str:
    configured = (settings.AUTH_JWT_ACTIVE_KID or "").strip()
    if configured and configured in ring:
        return configured
    return next(iter(ring.keys()))


def _decode_jwt_payload_with_keys(token: str, key_candidates: list[str]) -> dict | None:
    for key in key_candidates:
        try:
            return jwt.decode(
                token,
                key,
                algorithms=[settings.AUTH_ALGORITHM],
                audience=settings.AUTH_AUDIENCE,
                issuer=settings.AUTH_ISSUER,
                options={"verify_aud": True, "verify_iss": True},
            )
        except JWTError:
            continue
    return None


def create_access_token(*, identity: AuthIdentity) -> str:
    exp = _token_exp(settings.AUTH_ACCESS_TOKEN_MINUTES)
    ring = _jwt_keyring()
    active_kid = _active_jwt_kid(ring)
    signing_key = ring[active_kid]
    payload = {
        "sub": identity.email,
        "role": identity.role,
        "tenant_slug": identity.tenant_slug,
        "uid": int(identity.user_id),
        "amr": identity.amr,
        "iss": settings.AUTH_ISSUER,
        "aud": settings.AUTH_AUDIENCE,
        "exp": exp,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, signing_key, algorithm=settings.AUTH_ALGORITHM, headers={"kid": active_kid})


def decode_access_token(token: str) -> AuthIdentity | None:
    ring = _jwt_keyring()
    kid = None
    try:
        header = jwt.get_unverified_header(token)
        kid = str(header.get("kid") or "").strip() or None
    except Exception:
        kid = None

    key_candidates: list[str] = []
    if kid and kid in ring:
        key_candidates.append(ring[kid])
    for _, key in ring.items():
        if key not in key_candidates:
            key_candidates.append(key)

    payload = _decode_jwt_payload_with_keys(token, key_candidates)
    if not payload:
        return None

    email = str(payload.get("sub") or "").strip().lower()
    role = str(payload.get("role") or "").strip().lower()
    tenant_slug = str(payload.get("tenant_slug") or "").strip().lower()
    uid = int(payload.get("uid") or 0)
    amr = str(payload.get("amr") or "pwd").strip().lower() or "pwd"
    if not email or not role or not tenant_slug or uid <= 0:
        return None
    return AuthIdentity(email=email, role=role, tenant_slug=tenant_slug, user_id=uid, amr=amr)


def get_user(db: Session, tenant_id: int, email: str) -> AuthUser | None:
    return db.execute(
        select(AuthUser).where(
            AuthUser.tenant_id == tenant_id,
            AuthUser.email == email.strip().lower(),
        )
    ).scalar_one_or_none()


def create_user(
    db: Session,
    tenant: Tenant,
    email: str,
    password: str,
    role: str = "reception",
) -> AuthUser:
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise ValueError("email is required")
    validate_password_policy(password)

    existing = get_user(db, tenant.id, normalized_email)
    if existing:
        raise ValueError("User already exists")

    row = AuthUser(
        tenant_id=tenant.id,
        email=normalized_email,
        password_hash=hash_password(password),
        role=(role or "reception").strip().lower(),
        is_active=True,
        mfa_enabled=False,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def authenticate_user(
    db: Session,
    tenant: Tenant,
    email: str,
    password: str,
) -> AuthUser | None:
    row = get_user(db, tenant.id, email)
    if not row or not row.is_active:
        return None
    if not verify_password(password, row.password_hash):
        return None
    return row


def create_refresh_session(db: Session, tenant_id: int, user_id: int) -> tuple[str, AuthSession]:
    max_active = max(1, int(settings.AUTH_MAX_ACTIVE_SESSIONS_PER_USER))
    active_rows = (
        db.query(AuthSession)
        .filter(
            AuthSession.tenant_id == tenant_id,
            AuthSession.user_id == user_id,
            AuthSession.is_revoked.is_(False),
            AuthSession.expires_at > utc_now_naive(),
        )
        .order_by(AuthSession.created_at.asc(), AuthSession.id.asc())
        .all()
    )
    overflow = max(0, len(active_rows) - max(0, max_active - 1))
    if overflow > 0:
        for row in active_rows[:overflow]:
            row.is_revoked = True

    raw = secrets.token_urlsafe(48)
    expires = utc_now_naive() + timedelta(days=max(1, int(settings.AUTH_REFRESH_TOKEN_DAYS)))
    row = AuthSession(
        tenant_id=tenant_id,
        user_id=user_id,
        refresh_token_hash=hash_token(raw),
        is_revoked=False,
        expires_at=expires,
        created_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return raw, row


def use_refresh_session(db: Session, tenant_id: int, refresh_token: str) -> AuthSession | None:
    token_hash = hash_token(refresh_token)
    row = db.execute(
        select(AuthSession).where(
            AuthSession.tenant_id == tenant_id,
            AuthSession.refresh_token_hash == token_hash,
        )
    ).scalar_one_or_none()
    if not row or row.is_revoked:
        return None
    if row.expires_at <= utc_now_naive():
        row.is_revoked = True
        db.commit()
        return None
    return row


def revoke_refresh_session(db: Session, session_id: int) -> None:
    row = db.execute(select(AuthSession).where(AuthSession.id == session_id)).scalar_one_or_none()
    if not row:
        return
    row.is_revoked = True
    db.commit()


def revoke_refresh_session_by_token(db: Session, tenant_id: int, refresh_token: str) -> bool:
    token_hash = hash_token(refresh_token)
    row = db.execute(
        select(AuthSession).where(
            AuthSession.tenant_id == tenant_id,
            AuthSession.refresh_token_hash == token_hash,
        )
    ).scalar_one_or_none()
    if not row:
        return False
    if not row.is_revoked:
        row.is_revoked = True
        db.commit()
    return True


def list_refresh_sessions(
    db: Session,
    *,
    tenant_id: int,
    user_id: int | None = None,
    include_revoked: bool = False,
    limit: int = 100,
) -> list[AuthSession]:
    q = db.query(AuthSession).filter(AuthSession.tenant_id == tenant_id)
    if user_id is not None:
        q = q.filter(AuthSession.user_id == user_id)
    if not include_revoked:
        q = q.filter(AuthSession.is_revoked.is_(False))
    return q.order_by(AuthSession.created_at.desc(), AuthSession.id.desc()).limit(max(1, min(limit, 1000))).all()


def get_refresh_session_by_id(db: Session, *, tenant_id: int, session_id: int) -> AuthSession | None:
    return db.execute(
        select(AuthSession).where(
            AuthSession.tenant_id == tenant_id,
            AuthSession.id == session_id,
        )
    ).scalar_one_or_none()


def cleanup_expired_refresh_sessions(db: Session, *, tenant_id: int) -> int:
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.tenant_id == tenant_id,
            AuthSession.is_revoked.is_(False),
            AuthSession.expires_at <= utc_now_naive(),
        )
        .values(is_revoked=True)
    )
    db.commit()
    return int(result.rowcount or 0)


def revoke_all_refresh_sessions_for_user(db: Session, *, tenant_id: int, user_id: int) -> int:
    result = db.execute(
        update(AuthSession)
        .where(
            AuthSession.tenant_id == tenant_id,
            AuthSession.user_id == user_id,
            AuthSession.is_revoked.is_(False),
        )
        .values(is_revoked=True)
    )
    db.commit()
    return int(result.rowcount or 0)


def change_user_password(
    db: Session,
    *,
    tenant_id: int,
    email: str,
    old_password: str,
    new_password: str,
) -> AuthUser:
    row = get_user(db, tenant_id, email)
    if not row or not row.is_active:
        raise ValueError("User not found")
    if not verify_password(old_password, row.password_hash):
        raise ValueError("Invalid current password")
    validate_password_policy(new_password)
    if verify_password(new_password, row.password_hash):
        raise ValueError("New password must differ from current password")
    row.password_hash = hash_password(new_password)
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def generate_mfa_secret() -> str:
    return pyotp.random_base32()


def mfa_uri(email: str, secret: str, issuer: str = "SalonOS") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_mfa_code(secret: str, code: str) -> bool:
    if not secret:
        return False
    return bool(pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1))


def extract_identity_from_authorization_header(authorization_header: str | None) -> AuthIdentity | None:
    raw = (authorization_header or "").strip()
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    if not token:
        return None
    return decode_access_token(token)
