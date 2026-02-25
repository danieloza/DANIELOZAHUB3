from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import random

SHADOW_BANNED_IPS = {"1.2.3.4"} # Example

class ShadowBanMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        
        if client_ip in SHADOW_BANNED_IPS:
            # Randomly succeed or fail to confuse the attacker
            if random.random() < 0.8:
                # Fake success response without processing
                return JSONResponse(status_code=200, content={"status": "ok", "id": 999999})
            else:
                return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
                
        return await call_next(request)
