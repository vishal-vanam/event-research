from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Dict

from app.config import settings


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class SimpleTTLCache:
    """
    Very small in-memory TTL cache.
    - Not shared between processes (each gunicorn worker has its own copy).
    - Good enough to avoid hammering external APIs for the same input.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self._store: Dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if not entry:
            return None
        now = datetime.now(timezone.utc)
        if entry.expires_at <= now:
            # expired -> evict
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        now = datetime.now(timezone.utc)
        self._store[key] = CacheEntry(
            value=value,
            expires_at=now + self.ttl,
        )


# Global cache instance for the app
combined_cache = SimpleTTLCache(ttl_seconds=settings.cache_ttl_seconds)
