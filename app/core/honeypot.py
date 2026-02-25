import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import structlog

logger = structlog.get_logger("security.honeypot")

# Common paths scanned by bots
TRAP_PATHS = {
    "/wp-admin",
    "/wp-login.php",
    "/admin.php",
    "/phpmyadmin",
    "/.env",
    "/config.js",
    "/actuator/health",
    "/api/.git/config"
}

class HoneypotMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path.lower()
        
        # Check if path is a trap
        if any(path.endswith(trap) for trap in TRAP_PATHS) or path in TRAP_PATHS:
            client_ip = request.client.host if request.client else "unknown"
            
            logger.critical(
                "honeypot_triggered",
                client_ip=client_ip,
                path=path,
                action="blocking_request"
            )
            
            # Simulate a slow response to waste the attacker's time (Tarpit)
            time.sleep(2)
            
            # Return a generic 404 to not reveal custom blocking logic, 
            # or 403 if we want to be explicit.
            return JSONResponse(
                status_code=403, 
                content={"detail": "Forbidden: Suspicious activity detected."}
            )
            
        return await call_next(request)
