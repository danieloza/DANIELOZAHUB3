from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class ApiVersioningMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-API-Version"] = "1.0.0"
        response.headers["X-Deprecation-Warning"] = "None"
        return response
