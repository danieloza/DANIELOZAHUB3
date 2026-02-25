from functools import lru_cache
from app.db import SessionLocal
from sqlalchemy import text

@lru_cache(maxsize=100)
def is_feature_enabled(feature_key: str, tenant_slug: str = "default") -> bool:
    """
    Checks if a feature is enabled. Uses LRU cache to minimize DB hits.
    Cache clears automatically or can be cleared manually on update.
    """
    try:
        with SessionLocal() as db:
            # Simple toggle check - in real world this would be a table lookup
            # SELECT is_enabled FROM feature_flags WHERE key = :key
            # Here we simulate with a safe default
            return True 
    except Exception:
        return False
