import functools
import json
from typing import Any, Callable
from diskcache import Cache

# Cache directory within the project
cache = Cache("./.cache")

def smart_cache(ttl_seconds: int = 60):
    """
    Decorator to cache function results on disk.
    Great for expensive calculations like availability or reports.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create a unique key based on function name and arguments
            key_parts = [func.__name__]
            for arg in args:
                key_parts.append(str(arg))
            for k, v in sorted(kwargs.items()):
                key_parts.append(f"{k}={v}")
            
            key = ":".join(key_parts)
            
            # Try to get from cache
            cached_val = cache.get(key)
            if cached_val is not None:
                return cached_val
            
            # Compute and store
            result = func(*args, **kwargs)
            cache.set(key, result, expire=ttl_seconds)
            return result
        return wrapper
    return decorator

def clear_cache(pattern: str = None):
    if pattern:
        # DiskCache doesn't support glob delete easily, so we clear all for safety in this MVP
        # In a real scenario, we'd iterate keys.
        cache.clear()
    else:
        cache.clear()
