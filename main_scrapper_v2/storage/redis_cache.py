"""
Redis cache for seen-ID tracking and stats.
Falls back gracefully if Redis is unavailable.
"""

import logging

logger = logging.getLogger("scrapper")


class RedisCache:
    """Thin wrapper around Redis for deduplication and stats."""

    def __init__(
        self,
        enabled: bool = False,
        url: str = "redis://localhost:6379/0",
        prefix: str = "news_scrapper",
        seen_ttl_days: int = 90,
    ):
        self._enabled = enabled
        self._prefix = prefix
        self._ttl = seen_ttl_days * 86400
        self._client = None

        if enabled:
            try:
                import redis
                self._client = redis.from_url(url, decode_responses=True)
                self._client.ping()
                logger.info("Redis connected: %s", url, extra={"source": "redis"})
            except Exception as e:
                logger.warning(
                    "Redis unavailable (%s), falling back to file-based dedup",
                    e,
                    extra={"source": "redis"},
                )
                self._client = None
                self._enabled = False

    @property
    def available(self) -> bool:
        return self._enabled and self._client is not None

    def _key(self, *parts: str) -> str:
        return ":".join([self._prefix] + list(parts))

    # ── Seen-ID tracking ─────────────────────────────────────────────

    def is_seen(self, source: str, item_id: str) -> bool:
        if not self.available:
            return False
        try:
            return self._client.sismember(self._key("seen", source), item_id)
        except Exception:
            return False

    def mark_seen(self, source: str, item_id: str):
        if not self.available:
            return
        try:
            key = self._key("seen", source)
            self._client.sadd(key, item_id)
        except Exception:
            pass

    def mark_seen_bulk(self, source: str, item_ids: list[str]):
        if not self.available or not item_ids:
            return
        try:
            key = self._key("seen", source)
            self._client.sadd(key, *item_ids)
        except Exception:
            pass

    def get_seen_count(self, source: str) -> int:
        if not self.available:
            return 0
        try:
            return self._client.scard(self._key("seen", source))
        except Exception:
            return 0

    # ── Stats tracking ───────────────────────────────────────────────

    def update_stats(self, source: str, new_count: int):
        if not self.available:
            return
        try:
            key = self._key("stats", source)
            pipe = self._client.pipeline()
            pipe.hincrby(key, "total_fetched", new_count)
            pipe.hset(key, "last_fetch_time", __import__("time").time())
            pipe.execute()
        except Exception:
            pass

    def set_health(self, source: str, status: str, detail: str = ""):
        if not self.available:
            return
        try:
            key = self._key("health", source)
            self._client.hset(key, mapping={
                "status": status,
                "detail": detail,
                "updated_at": __import__("time").time(),
            })
        except Exception:
            pass

    def get_health(self, source: str) -> dict:
        if not self.available:
            return {}
        try:
            return self._client.hgetall(self._key("health", source))
        except Exception:
            return {}

    def get_all_stats(self) -> dict:
        if not self.available:
            return {}
        try:
            result = {}
            for key in self._client.scan_iter(f"{self._prefix}:stats:*"):
                source = key.split(":")[-1]
                result[source] = self._client.hgetall(key)
            return result
        except Exception:
            return {}
