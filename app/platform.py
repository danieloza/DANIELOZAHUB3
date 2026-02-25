import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    FeatureFlag,
    IdempotencyRecord,
    NoShowPolicy,
    OutboxEvent,
    PaymentIntent,
    Tenant,
    VisitInvoice,
)

log = logging.getLogger("salonos.platform")


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_dumps(payload: dict | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=True, sort_keys=True)


def _push_invoice_to_danex(payload: dict) -> str:
    """Senior IT: Direct bridge to Danex Business API for Invoicing Automation."""
    base_url = settings.DANEX_API_URL.rstrip("/")
    email = settings.DANEX_API_EMAIL
    password = settings.DANEX_API_PASSWORD
    
    if not email or not password:
        raise ValueError("DANEX_API_EMAIL/PASSWORD not configured in .env")

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        # 1. Login
        login_resp = client.post("/api/v1/auth/login", data={
            "username": email,
            "password": password
        })
        login_resp.raise_for_status()
        token = login_resp.json().get("access_token")
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Resolve Client (or create if missing)
        client_name = payload.get("client_name", "Nieznany")
        clients_resp = client.get("/api/v1/clients", params={"q": client_name}, headers=headers)
        clients_resp.raise_for_status()
        
        client_id = None
        for c in clients_resp.json():
            if (c.get("name") or "").strip().lower() == client_name.lower():
                client_id = c["id"]
                break
        
        if not client_id:
            new_client_resp = client.post("/api/v1/clients", json={"name": client_name}, headers=headers)
            new_client_resp.raise_for_status()
            client_id = new_client_resp.json()["id"]

        # 3. Create Invoice
        invoice_payload = {
            "client_id": client_id,
            "number": f"SOS-{payload['visit_id']}",
            "total_gross": payload["amount"],
            "status": "draft",
            "date": payload.get("date", datetime.now().isoformat())
        }
        inv_resp = client.post("/api/v1/invoices", json=invoice_payload, headers=headers)
        inv_resp.raise_for_status()
        return str(inv_resp.json()["id"])


def request_fingerprint(
    *,
    method: str,
    path: str,
    tenant_slug: str,
    body: bytes,
) -> str:
    digest = hashlib.sha256()
    digest.update(method.upper().encode("utf-8"))
    digest.update(b"|")
    digest.update(path.encode("utf-8"))
    digest.update(b"|")
    digest.update(tenant_slug.lower().encode("utf-8"))
    digest.update(b"|")
    digest.update(body or b"")
    return digest.hexdigest()


def read_idempotency_record(
    db: Session,
    *,
    tenant_slug: str,
    method: str,
    path: str,
    idempotency_key: str,
) -> IdempotencyRecord | None:
    return db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_slug == tenant_slug.strip().lower(),
            IdempotencyRecord.method == method.strip().upper(),
            IdempotencyRecord.path == path.strip(),
            IdempotencyRecord.idempotency_key == idempotency_key.strip(),
        )
    ).scalar_one_or_none()


def store_idempotency_record(
    db: Session,
    *,
    tenant_slug: str,
    method: str,
    path: str,
    idempotency_key: str,
    request_hash: str,
    status_code: int,
    content_type: str | None,
    response_body: bytes,
) -> IdempotencyRecord:
    tenant = db.execute(
        select(Tenant).where(Tenant.slug == tenant_slug.strip().lower())
    ).scalar_one_or_none()
    row = IdempotencyRecord(
        tenant_slug=tenant_slug.strip().lower(),
        tenant_id=(tenant.id if tenant else None),
        method=method.strip().upper(),
        path=path.strip(),
        idempotency_key=idempotency_key.strip(),
        request_hash=request_hash,
        status_code=int(status_code),
        content_type=(content_type or "").strip() or None,
        response_body_b64=base64.b64encode(response_body or b"").decode("ascii"),
        created_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def decode_idempotency_response_body(row: IdempotencyRecord) -> bytes:
    try:
        return base64.b64decode((row.response_body_b64 or "").encode("ascii"))
    except Exception:
        return b""


def get_idempotency_health(
    db: Session,
    *,
    tenant_slug: str,
) -> dict:
    slug = (tenant_slug or "").strip().lower()
    rows = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.tenant_slug == slug)
        .order_by(IdempotencyRecord.created_at.desc(), IdempotencyRecord.id.desc())
        .all()
    )
    now = utc_now_naive()
    oldest = min((row.created_at for row in rows), default=None)
    oldest_age_seconds = int((now - oldest).total_seconds()) if oldest else 0
    return {
        "tenant_slug": slug,
        "checked_at": now,
        "records_count": int(len(rows)),
        "oldest_record_age_seconds": int(max(0, oldest_age_seconds)),
    }


def cleanup_idempotency_records(
    db: Session,
    *,
    tenant_slug: str,
    older_than_hours: int,
) -> dict:
    slug = (tenant_slug or "").strip().lower()
    cutoff = utc_now_naive() - timedelta(hours=max(1, int(older_than_hours)))
    deleted = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.tenant_slug == slug,
            IdempotencyRecord.created_at < cutoff,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return {
        "tenant_slug": slug,
        "deleted_records": int(deleted or 0),
        "cutoff": cutoff,
    }


def enqueue_outbox_event(
    db: Session,
    *,
    topic: str,
    payload: dict,
    tenant_id: int | None = None,
    key: str | None = None,
) -> OutboxEvent:
    row = OutboxEvent(
        tenant_id=tenant_id,
        topic=(topic or "").strip(),
        key=(key or "").strip() or None,
        payload_json=_json_dumps(payload),
        status="pending",
        retries=0,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_outbox_events(
    db: Session,
    *,
    tenant_id: int | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[OutboxEvent]:
    q = db.query(OutboxEvent)
    if tenant_id is not None:
        q = q.filter(OutboxEvent.tenant_id == tenant_id)
    if status:
        q = q.filter(OutboxEvent.status == status.strip().lower())
    return (
        q.order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )


def _redis_client() -> redis.Redis | None:
    if not settings.REDIS_URL:
        return None
    try:
        return redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def dispatch_outbox_events(
    db: Session,
    *,
    tenant_id: int | None = None,
    batch_size: int = 50,
) -> dict:
    rows = list_outbox_events(
        db=db, tenant_id=tenant_id, status="pending", limit=batch_size
    )
    if not rows:
        return {"processed": 0, "published": 0, "failed": 0, "dead_lettered": 0}

    client = _redis_client()
    published = 0
    failed = 0
    dead_lettered = 0
    max_retries = max(1, int(settings.OUTBOX_MAX_RETRIES))
    for row in rows:
        try:
            payload = json.loads(row.payload_json or "{}")

            if row.topic == "invoice.create_requested":
                # Senior IT: Automated Accounting Sync (Salonos -> Danex)
                ext_inv_id = _push_invoice_to_danex(payload)
                
                # Update status in local VisitInvoice
                visit_id = payload.get("visit_id")
                if visit_id:
                    v_inv = db.execute(
                        select(VisitInvoice).where(VisitInvoice.visit_id == visit_id)
                    ).scalar_one_or_none()
                    if v_inv:
                        v_inv.external_invoice_id = ext_inv_id
                        v_inv.status = "sent"
                        v_inv.updated_at = utc_now_naive()

            if settings.EVENT_BUS_ENABLED and client is not None:
                payload = json.loads(row.payload_json or "{}")
                fields = {
                    "event_id": str(row.id),
                    "topic": row.topic,
                    "tenant_id": str(row.tenant_id or ""),
                    "key": row.key or "",
                    "payload_json": _json_dumps(payload),
                }
                client.xadd(
                    settings.EVENT_BUS_STREAM,
                    fields=fields,
                    maxlen=50000,
                    approximate=True,
                )
            row.status = "published"
            row.published_at = utc_now_naive()
            row.last_error = None
            published += 1
        except Exception as exc:
            row.retries = int(row.retries or 0) + 1
            row.last_error = str(exc)[:500]
            if int(row.retries) >= max_retries:
                row.status = "dead_letter"
                dead_lettered += 1
            else:
                row.status = "failed"
            failed += 1
        row.updated_at = utc_now_naive()
    db.commit()
    return {
        "processed": len(rows),
        "published": published,
        "failed": failed,
        "dead_lettered": dead_lettered,
    }


def retry_outbox_events(
    db: Session,
    *,
    tenant_id: int | None = None,
    include_dead_letter: bool = False,
    limit: int = 100,
) -> dict:
    statuses = {"failed"}
    if include_dead_letter:
        statuses.add("dead_letter")
    q = db.query(OutboxEvent).filter(OutboxEvent.status.in_(list(statuses)))
    if tenant_id is not None:
        q = q.filter(OutboxEvent.tenant_id == tenant_id)
    rows = (
        q.order_by(OutboxEvent.updated_at.asc(), OutboxEvent.id.asc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    retried = 0
    for row in rows:
        row.status = "pending"
        row.last_error = None
        row.updated_at = utc_now_naive()
        retried += 1
    db.commit()
    return {"retried": int(retried)}


def cleanup_outbox_events(
    db: Session,
    *,
    tenant_id: int | None = None,
    older_than_hours: int = 24 * 7,
) -> dict:
    cutoff = utc_now_naive() - timedelta(hours=max(1, int(older_than_hours)))
    q = db.query(OutboxEvent).filter(
        OutboxEvent.status.in_(["published", "dead_letter"]),
        OutboxEvent.updated_at < cutoff,
    )
    if tenant_id is not None:
        q = q.filter(OutboxEvent.tenant_id == tenant_id)
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return {
        "tenant_id": (int(tenant_id) if tenant_id is not None else None),
        "deleted_events": int(deleted or 0),
        "cutoff": cutoff,
    }


def get_outbox_health(db: Session, *, tenant_id: int | None = None) -> dict:
    q = db.query(OutboxEvent)
    if tenant_id is not None:
        q = q.filter(OutboxEvent.tenant_id == tenant_id)
    rows = q.all()
    now = utc_now_naive()
    pending = [r for r in rows if r.status == "pending"]
    failed = [r for r in rows if r.status == "failed"]
    dead_letter = [r for r in rows if r.status == "dead_letter"]
    published = [r for r in rows if r.status == "published"]
    oldest_pending = min((r.created_at for r in pending), default=None)
    oldest_pending_age = (
        int((now - oldest_pending).total_seconds()) if oldest_pending else 0
    )
    return {
        "tenant_id": (int(tenant_id) if tenant_id is not None else None),
        "checked_at": now,
        "pending_count": int(len(pending)),
        "failed_count": int(len(failed)),
        "dead_letter_count": int(len(dead_letter)),
        "published_count": int(len(published)),
        "oldest_pending_age_seconds": int(max(0, oldest_pending_age)),
    }


def _stable_hash_int(text: str) -> int:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def upsert_feature_flag(
    db: Session,
    *,
    tenant_id: int,
    flag_key: str,
    enabled: bool,
    rollout_pct: int = 0,
    allowlist: list[str] | None = None,
    updated_by: str | None = None,
) -> FeatureFlag:
    key = (flag_key or "").strip().lower()
    if not key:
        raise ValueError("flag_key is required")
    pct = max(0, min(int(rollout_pct), 100))
    allowlist_values = sorted(
        {(x or "").strip() for x in (allowlist or []) if (x or "").strip()}
    )
    row = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.flag_key == key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = FeatureFlag(
            tenant_id=tenant_id,
            flag_key=key,
            updated_at=utc_now_naive(),
        )
        db.add(row)
    row.enabled = bool(enabled)
    row.rollout_pct = pct
    row.allowlist_csv = ",".join(allowlist_values) if allowlist_values else None
    row.updated_by = (updated_by or "").strip().lower() or None
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def list_feature_flags(db: Session, *, tenant_id: int) -> list[FeatureFlag]:
    return (
        db.query(FeatureFlag)
        .filter(FeatureFlag.tenant_id == tenant_id)
        .order_by(FeatureFlag.flag_key.asc())
        .all()
    )


def is_feature_enabled(
    db: Session,
    *,
    tenant_id: int,
    flag_key: str,
    subject_key: str | None = None,
) -> bool:
    row = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.flag_key == flag_key.strip().lower(),
        )
    ).scalar_one_or_none()
    if not row or not row.enabled:
        return False

    subject = (subject_key or "").strip()
    if not subject:
        return int(row.rollout_pct or 0) >= 100

    allowlist = {x.strip() for x in (row.allowlist_csv or "").split(",") if x.strip()}
    if subject in allowlist:
        return True
    pct = max(0, min(int(row.rollout_pct or 0), 100))
    if pct <= 0:
        return False
    bucket = (
        _stable_hash_int(f"{settings.FEATURE_FLAGS_SALT}:{row.flag_key}:{subject}")
        % 100
    )
    return bucket < pct


def get_or_create_no_show_policy(db: Session, *, tenant_id: int) -> NoShowPolicy:
    row = db.execute(
        select(NoShowPolicy).where(NoShowPolicy.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if row:
        return row
    row = NoShowPolicy(
        tenant_id=tenant_id,
        enabled=False,
        fee_amount=0,
        grace_minutes=10,
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def upsert_no_show_policy(
    db: Session,
    *,
    tenant_id: int,
    enabled: bool,
    fee_amount: float,
    grace_minutes: int,
    updated_by: str | None = None,
) -> NoShowPolicy:
    row = get_or_create_no_show_policy(db=db, tenant_id=tenant_id)
    row.enabled = bool(enabled)
    row.fee_amount = max(0.0, float(fee_amount))
    row.grace_minutes = max(0, int(grace_minutes))
    row.updated_by = (updated_by or "").strip().lower() or None
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def create_payment_intent(
    db: Session,
    *,
    tenant_id: int,
    amount: float,
    reason: str,
    reservation_id: int | None = None,
    visit_id: int | None = None,
    client_id: int | None = None,
    currency: str | None = None,
    metadata: dict | None = None,
) -> PaymentIntent:
    if (reason or "").strip().lower() == "no_show_fee" and visit_id is not None:
        existing = db.execute(
            select(PaymentIntent).where(
                PaymentIntent.tenant_id == tenant_id,
                PaymentIntent.visit_id == visit_id,
                PaymentIntent.reason == "no_show_fee",
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    row = PaymentIntent(
        tenant_id=tenant_id,
        reservation_id=reservation_id,
        visit_id=visit_id,
        client_id=client_id,
        amount=max(0.0, float(amount)),
        currency=(currency or settings.PAYMENT_DEFAULT_CURRENCY).strip().upper()
        or "PLN",
        reason=(reason or "deposit").strip().lower(),
        status="pending",
        provider=settings.PAYMENT_PROVIDER_MODE,
        metadata_json=_json_dumps(metadata),
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def capture_payment_intent(
    db: Session,
    *,
    tenant_id: int,
    payment_intent_id: int,
    provider_ref: str | None = None,
) -> PaymentIntent | None:
    row = db.execute(
        select(PaymentIntent).where(
            PaymentIntent.id == payment_intent_id,
            PaymentIntent.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()
    if not row:
        return None
    if row.status == "captured":
        return row
    row.status = "captured"
    row.provider_ref = (provider_ref or "").strip() or row.provider_ref
    row.captured_at = utc_now_naive()
    row.updated_at = utc_now_naive()
    db.commit()
    db.refresh(row)
    return row


def list_payment_intents(
    db: Session,
    *,
    tenant_id: int,
    status: str | None = None,
    limit: int = 200,
) -> list[PaymentIntent]:
    q = db.query(PaymentIntent).filter(PaymentIntent.tenant_id == tenant_id)
    if status:
        q = q.filter(PaymentIntent.status == status.strip().lower())
    return (
        q.order_by(PaymentIntent.created_at.desc(), PaymentIntent.id.desc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )
