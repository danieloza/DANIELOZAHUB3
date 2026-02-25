import time
import uuid
import structlog
from fastapi import Request
from starlette.responses import JSONResponse

from .performance import masking_processor

def setup_logging():
    import logging
    import sys
    
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            masking_processor,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

logger = structlog.get_logger("salonos")

async def request_tracing_middleware(request: Request, call_next):
    # Capture Trace ID from header (sent by Danex) or generate new
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    tenant_slug = request.headers.get("X-Tenant-Slug")
    
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        tenant_slug=tenant_slug,
        path=request.url.path,
        method=request.method,
        app="salonos"
    )
    
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        
        logger.info(
            "http_request",
            status=response.status_code,
            duration_ms=duration_ms
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(
            "http_request_failed",
            error=str(exc),
            duration_ms=duration_ms
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error", "request_id": request_id}
        )
