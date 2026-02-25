import psutil
from fastapi import APIRouter

router = APIRouter()

@router.get("/health/resources")
def resource_monitor():
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_used_mb": round(psutil.virtual_memory().used / 1024 / 1024, 2),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_free_gb": round(psutil.disk_usage('.').free / 1024 / 1024 / 1024, 2)
    }
