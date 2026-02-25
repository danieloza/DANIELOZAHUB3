import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger("security.audit.pii")

# Endpoints that expose personal data
SENSITIVE_PATHS = {
    "/api/visits",
    "/api/clients",
    "/api/reservations"
}

class PIIAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        path = request.url.path
        if any(path.startswith(sp) for sp in SENSITIVE_PATHS):
            actor = request.headers.get("x-actor-email", "anonymous")
            request_id = request.headers.get("x-request-id", "unknown")
            
            logger.info(
                "pii_data_accessed",
                path=path,
                actor=actor,
                method=request.method,
                request_id=request_id,
                status=response.status_code
            )
            
        return response
