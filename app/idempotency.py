from fastapi import Request, Response

from .config import settings
from .db import SessionLocal
from .platform import (
    decode_idempotency_response_body,
    read_idempotency_record,
    request_fingerprint,
    store_idempotency_record,
)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SKIP_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def _tenant_slug(request: Request) -> str:
    raw = (
        (request.headers.get("x-tenant-slug") or settings.DEFAULT_TENANT_SLUG or "")
        .strip()
        .lower()
    )
    return raw or settings.DEFAULT_TENANT_SLUG


def _session_local(request: Request):
    return getattr(request.app.state, "session_local", SessionLocal)


async def idempotency_middleware(request: Request, call_next):
    if request.method.upper() not in MUTATING_METHODS:
        return await call_next(request)
    if request.url.path.startswith(SKIP_PATH_PREFIXES):
        return await call_next(request)

    idempotency_key = (request.headers.get("idempotency-key") or "").strip()
    if not idempotency_key:
        return await call_next(request)

    tenant_slug = _tenant_slug(request)
    request_body = await request.body()
    fingerprint = request_fingerprint(
        method=request.method,
        path=request.url.path,
        tenant_slug=tenant_slug,
        body=request_body,
    )

    session_local = _session_local(request)
    with session_local() as db:
        existing = read_idempotency_record(
            db=db,
            tenant_slug=tenant_slug,
            method=request.method,
            path=request.url.path,
            idempotency_key=idempotency_key,
        )
        if existing:
            if existing.request_hash != fingerprint:
                return Response(
                    status_code=409,
                    content='{"detail":"Idempotency key reused with different payload"}',
                    media_type="application/json",
                )
            return Response(
                content=decode_idempotency_response_body(existing),
                status_code=int(existing.status_code),
                media_type=existing.content_type or "application/json",
                headers={"X-Idempotency-Replayed": "true"},
            )

    async def _receive():
        return {"type": "http.request", "body": request_body, "more_body": False}

    replayable_request = Request(request.scope, _receive)
    response = await call_next(replayable_request)

    response_body = b""
    async for chunk in response.body_iterator:
        response_body += chunk

    replayable_response = Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )

    if response.status_code < 500:
        with session_local() as db:
            store_idempotency_record(
                db=db,
                tenant_slug=tenant_slug,
                method=request.method,
                path=request.url.path,
                idempotency_key=idempotency_key,
                request_hash=fingerprint,
                status_code=response.status_code,
                content_type=response.media_type
                or response.headers.get("content-type"),
                response_body=response_body,
            )

    return replayable_response
