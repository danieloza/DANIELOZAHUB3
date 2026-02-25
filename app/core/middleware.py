import time
import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = structlog.get_logger("salonos.middleware")


class DistributedTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Senior IT: Capture request_id from Danex or generate new if missing
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            app="salonos",
        )

        start_time = time.perf_counter()

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            process_time = (time.perf_counter() - start_time) * 1000
            logger.error(
                "request_failed",
                error=str(exc),
                duration_ms=round(process_time, 2),
            )
            raise

        process_time = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id

        logger.info(
            "request_finished",
            status=response.status_code,
            duration_ms=round(process_time, 2),
        )

        return response
