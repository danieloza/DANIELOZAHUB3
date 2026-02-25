import time
import structlog
from fastapi import Request
from prometheus_client import Counter, Histogram, generate_latest

# Senior IT Metrics
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"])

logger = structlog.get_logger("performance.budget")

class PerformanceBudgetMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]
        start_time = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                duration = time.perf_counter() - start_time
                status = message["status"]
                
                # Record Prometheus metrics
                REQUEST_COUNT.labels(method=method, endpoint=path, status=status).inc()
                REQUEST_LATENCY.labels(method=method, endpoint=path).observe(duration)
                
                # Performance Budget check
                if duration > 0.200: # 200ms budget
                    logger.warning(
                        "performance_budget_exceeded",
                        path=path,
                        duration_ms=round(duration * 1000, 2),
                        limit_ms=200
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def __init__(self, app):
        self.app = app
