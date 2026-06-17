import time
import threading
from typing import Any, Dict, Optional

class SessionCache:
    def __init__(self, ttl_seconds: int = 300, max_size: int = 3000):
        """
        Thread-safe in-memory cache for session records.
        :param ttl_seconds: Time-to-live in seconds (default: 5 minutes)
        :param max_size: Maximum number of items allowed in cache (default: 3000 for ~60MB memory limit)
        """
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Retrieve an item from the cache if it exists and has not expired."""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry["timestamp"] < self.ttl:
                    return entry["data"]
                else:
                    # Expired
                    del self._cache[key]
            return None

    def set(self, key: str, value: Any) -> None:
        """Store an item in the cache, evicting the oldest entry if size limit is exceeded."""
        with self._lock:
            if key in self._cache:
                self._cache[key] = {
                    "data": value,
                    "timestamp": time.time()
                }
                return

            if len(self._cache) >= self.max_size:
                # Evict oldest entry based on timestamp
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k]["timestamp"])
                del self._cache[oldest_key]
            
            self._cache[key] = {
                "data": value,
                "timestamp": time.time()
            }

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]

    def clear(self) -> None:
        """Clear all cache contents."""
        with self._lock:
            self._cache.clear()

# Global cache instance
session_cache = SessionCache()
