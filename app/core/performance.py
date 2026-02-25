import time
import structlog
from fastapi import Request

def masking_processor(logger, method_name, event_dict):
    """Masks sensitive data like phone numbers in logs."""
    for key in ["phone", "client_phone", "contact"]:
        if key in event_dict:
            val = str(event_dict[key])
            event_dict[key] = f"{val[:3]}***{val[-2:]}" if len(val) > 5 else "***"
    return event_dict

class SlowQueryMiddleware:
    def __init__(self, app):
        self.app = app
        self.logger = structlog.get_logger("performance.db")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.perf_counter()
        await self.app(scope, receive, send)
        duration = time.perf_counter() - start_time
        
        if duration > 0.5: # 500ms
            self.logger.warning("slow_request_detected", path=scope["path"], duration_s=round(duration, 3))
