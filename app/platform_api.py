import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .authn import AuthIdentity, extract_identity_from_authorization_header
from .db import get_db
from .models import Tenant
from .platform import (
    cleanup_idempotency_records,
    cleanup_outbox_events,
    capture_payment_intent,
    create_payment_intent,
    dispatch_outbox_events,
    get_idempotency_health,
    get_outbox_health,
    get_or_create_no_show_policy,
    is_feature_enabled,
    list_feature_flags,
    list_outbox_events,
    list_payment_intents,
    retry_outbox_events,
    upsert_feature_flag,
    upsert_no_show_policy,
)
from .services import get_or_create_tenant

router = APIRouter(prefix="/api/platform", tags=["platform"])
READ_ROLES = {"owner", "manager", "reception"}
MUTATE_ROLES = {"owner", "manager"}


class FeatureFlagSetIn(BaseModel):
    flag_key: str = Field(min_length=2, max_length=120)
    enabled: bool
    rollout_pct: int = Field(default=0, ge=0, le=100)
    allowlist: list[str] = Field(default_factory=list)


class NoShowPolicyIn(BaseModel):
    enabled: bool
    fee_amount: float = Field(ge=0)
    grace_minutes: int = Field(default=10, ge=0, le=240)


class PaymentIntentIn(BaseModel):
    amount: float = Field(gt=0)
    reason: str = Field(default="deposit", min_length=2, max_length=80)
    reservation_id: Optional[int] = None
    visit_id: Optional[int] = None
    client_id: Optional[int] = None
    currency: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


def _require_identity(request: Request) -> AuthIdentity:
    identity = extract_identity_from_authorization_header(request.headers.get("authorization"))
    if not identity:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid bearer token")
    return identity


def _require_role(identity: AuthIdentity, allowed_roles: set[str]) -> None:
    role = (identity.role or "").strip().lower()
    if role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden role")


def _resolve_tenant(db: Session, request: Request, x_tenant_slug: Optional[str], identity: AuthIdentity) -> Tenant:
    header_slug = (x_tenant_slug or request.headers.get("x-tenant-slug") or "").strip().lower()
    token_slug = (identity.tenant_slug or "").strip().lower()
    if header_slug and token_slug and header_slug != token_slug:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch with bearer token")
    slug = header_slug or token_slug
    if not slug:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-Tenant-Slug")
    return get_or_create_tenant(db=db, slug=slug, name=slug)


@router.put("/flags", response_model=dict)
def set_feature_flag(
    payload: FeatureFlagSetIn,
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, MUTATE_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    try:
        row = upsert_feature_flag(
            db=db,
            tenant_id=tenant.id,
            flag_key=payload.flag_key,
            enabled=payload.enabled,
            rollout_pct=payload.rollout_pct,
            allowlist=payload.allowlist,
            updated_by=identity.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {
        "id": row.id,
        "flag_key": row.flag_key,
        "enabled": row.enabled,
        "rollout_pct": row.rollout_pct,
        "allowlist": [x for x in (row.allowlist_csv or "").split(",") if x],
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


@router.get("/flags", response_model=list[dict])
def get_feature_flags(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    rows = list_feature_flags(db=db, tenant_id=tenant.id)
    return [
        {
            "id": row.id,
            "flag_key": row.flag_key,
            "enabled": row.enabled,
            "rollout_pct": row.rollout_pct,
            "allowlist": [x for x in (row.allowlist_csv or "").split(",") if x],
            "updated_by": row.updated_by,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get("/flags/evaluate", response_model=dict)
def evaluate_feature_flag(
    flag_key: str = Query(..., min_length=2, max_length=120),
    subject_key: Optional[str] = Query(default=None),
    request: Request = None,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    return {
        "flag_key": flag_key,
        "subject_key": subject_key,
        "enabled": bool(is_feature_enabled(db=db, tenant_id=tenant.id, flag_key=flag_key, subject_key=subject_key)),
    }


@router.put("/no-show-policy", response_model=dict)
def set_no_show_policy(
    payload: NoShowPolicyIn,
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, MUTATE_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    row = upsert_no_show_policy(
        db=db,
        tenant_id=tenant.id,
        enabled=payload.enabled,
        fee_amount=payload.fee_amount,
        grace_minutes=payload.grace_minutes,
        updated_by=identity.email,
    )
    return {
        "enabled": row.enabled,
        "fee_amount": float(row.fee_amount),
        "grace_minutes": row.grace_minutes,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


@router.get("/no-show-policy", response_model=dict)
def get_no_show_policy(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    row = get_or_create_no_show_policy(db=db, tenant_id=tenant.id)
    return {
        "enabled": row.enabled,
        "fee_amount": float(row.fee_amount),
        "grace_minutes": row.grace_minutes,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


@router.post("/payments/intents", response_model=dict)
def create_payment_intent_endpoint(
    payload: PaymentIntentIn,
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    row = create_payment_intent(
        db=db,
        tenant_id=tenant.id,
        amount=payload.amount,
        reason=payload.reason,
        reservation_id=payload.reservation_id,
        visit_id=payload.visit_id,
        client_id=payload.client_id,
        currency=payload.currency,
        metadata=payload.metadata,
    )
    return {
        "id": row.id,
        "amount": float(row.amount),
        "currency": row.currency,
        "reason": row.reason,
        "status": row.status,
        "provider": row.provider,
        "metadata": json.loads(row.metadata_json or "{}"),
        "created_at": row.created_at,
    }


@router.post("/payments/intents/{payment_intent_id}/capture", response_model=dict)
def capture_payment_intent_endpoint(
    payment_intent_id: int,
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    provider_ref: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, MUTATE_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    row = capture_payment_intent(db=db, tenant_id=tenant.id, payment_intent_id=payment_intent_id, provider_ref=provider_ref)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment intent not found")
    return {
        "id": row.id,
        "status": row.status,
        "provider_ref": row.provider_ref,
        "captured_at": row.captured_at,
    }


@router.get("/payments/intents", response_model=list[dict])
def list_payment_intents_endpoint(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    rows = list_payment_intents(db=db, tenant_id=tenant.id, status=status_filter, limit=limit)
    return [
        {
            "id": row.id,
            "amount": float(row.amount),
            "currency": row.currency,
            "reason": row.reason,
            "status": row.status,
            "reservation_id": row.reservation_id,
            "visit_id": row.visit_id,
            "client_id": row.client_id,
            "provider": row.provider,
            "provider_ref": row.provider_ref,
            "captured_at": row.captured_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/outbox/dispatch", response_model=dict)
def dispatch_outbox(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    batch_size: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, MUTATE_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    return dispatch_outbox_events(db=db, tenant_id=tenant.id, batch_size=batch_size)


@router.get("/outbox/events", response_model=list[dict])
def get_outbox_events(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    rows = list_outbox_events(db=db, tenant_id=tenant.id, status=status_filter, limit=limit)
    return [
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "topic": row.topic,
            "key": row.key,
            "status": row.status,
            "retries": row.retries,
            "last_error": row.last_error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "published_at": row.published_at,
        }
        for row in rows
    ]


@router.post("/outbox/retry-failed", response_model=dict)
def retry_failed_outbox(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    include_dead_letter: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, MUTATE_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    return retry_outbox_events(
        db=db,
        tenant_id=tenant.id,
        include_dead_letter=include_dead_letter,
        limit=limit,
    )


@router.get("/outbox/health", response_model=dict)
def outbox_health(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    return get_outbox_health(db=db, tenant_id=tenant.id)


@router.post("/outbox/cleanup", response_model=dict)
def cleanup_outbox(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    older_than_hours: int = Query(default=24 * 7, ge=1, le=24 * 365),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, MUTATE_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    return cleanup_outbox_events(db=db, tenant_id=tenant.id, older_than_hours=older_than_hours)


@router.get("/idempotency/health", response_model=dict)
def idempotency_health(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, READ_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    return get_idempotency_health(db=db, tenant_slug=tenant.slug)


@router.post("/idempotency/cleanup", response_model=dict)
def idempotency_cleanup(
    request: Request,
    x_tenant_slug: Optional[str] = Header(default=None),
    older_than_hours: int = Query(default=168, ge=1, le=24 * 365),
    db: Session = Depends(get_db),
):
    identity = _require_identity(request)
    _require_role(identity, MUTATE_ROLES)
    tenant = _resolve_tenant(db, request, x_tenant_slug, identity)
    return cleanup_idempotency_records(
        db=db,
        tenant_slug=tenant.slug,
        older_than_hours=older_than_hours,
    )
