"""
Proxy manager with rotation, bandwidth tracking, and auto-disable.
Supports round-robin and random rotation strategies.
"""

import os
import threading
from dataclasses import dataclass, field


@dataclass
class ProxyEntry:
    host: str
    port: str
    username: str
    password: str
    bandwidth_used_bytes: int = 0
    bandwidth_limit_bytes: int = 0
    enabled: bool = True
    error_count: int = 0

    @property
    def url(self) -> str:
        return f"http://{self.username}:{self.password}@{self.host}:{self.port}"

    @property
    def dict(self) -> dict:
        proxy_url = self.url
        return {"http": proxy_url, "https": proxy_url}

    @property
    def bandwidth_remaining_mb(self) -> float:
        if self.bandwidth_limit_bytes <= 0:
            return float("inf")
        return (self.bandwidth_limit_bytes - self.bandwidth_used_bytes) / (1024 * 1024)


class ProxyManager:
    """Thread-safe proxy rotation manager."""

    def __init__(
        self,
        proxy_file: str = "proxies.txt",
        bandwidth_limit_mb: int = 1024,
        rotation: str = "round_robin",
        redis_client=None,
        redis_prefix: str = "news_scrapper",
    ):
        self._proxies: list[ProxyEntry] = []
        self._index = 0
        self._lock = threading.Lock()
        self._rotation = rotation
        self._redis = redis_client
        self._redis_prefix = redis_prefix

        if os.path.exists(proxy_file):
            self._load_proxies(proxy_file, bandwidth_limit_mb)

    def _load_proxies(self, filepath: str, bandwidth_limit_mb: int):
        limit_bytes = bandwidth_limit_mb * 1024 * 1024
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) >= 4:
                    proxy = ProxyEntry(
                        host=parts[0],
                        port=parts[1],
                        username=parts[2],
                        password=":".join(parts[3:]),  # password may contain colons
                        bandwidth_limit_bytes=limit_bytes,
                    )
                    # Restore bandwidth from Redis if available
                    if self._redis:
                        key = f"{self._redis_prefix}:proxy:bw:{proxy.host}:{proxy.port}"
                        stored = self._redis.get(key)
                        if stored:
                            proxy.bandwidth_used_bytes = int(stored)
                    self._proxies.append(proxy)

    @property
    def count(self) -> int:
        return len(self._proxies)

    @property
    def available_count(self) -> int:
        return sum(1 for p in self._proxies if p.enabled)

    def get_next(self) -> dict | None:
        """Get the next available proxy dict for requests."""
        if not self._proxies:
            return None

        with self._lock:
            attempts = 0
            while attempts < len(self._proxies):
                if self._rotation == "round_robin":
                    proxy = self._proxies[self._index % len(self._proxies)]
                    self._index += 1
                else:
                    import random
                    proxy = random.choice(self._proxies)

                if proxy.enabled and proxy.bandwidth_remaining_mb > 10:
                    return proxy.dict
                attempts += 1

        return None  # all proxies exhausted

    def report_usage(self, proxy_dict: dict | None, bytes_used: int):
        """Report bandwidth usage for a proxy."""
        if not proxy_dict or not bytes_used:
            return
        proxy_url = proxy_dict.get("http", "")
        with self._lock:
            for p in self._proxies:
                if p.url in proxy_url:
                    p.bandwidth_used_bytes += bytes_used
                    if p.bandwidth_remaining_mb <= 0:
                        p.enabled = False
                    # Persist to Redis
                    if self._redis:
                        key = f"{self._redis_prefix}:proxy:bw:{p.host}:{p.port}"
                        self._redis.set(key, str(p.bandwidth_used_bytes))
                    break

    def report_error(self, proxy_dict: dict | None):
        """Report an error for a proxy. Disable after too many errors."""
        if not proxy_dict:
            return
        proxy_url = proxy_dict.get("http", "")
        with self._lock:
            for p in self._proxies:
                if p.url in proxy_url:
                    p.error_count += 1
                    if p.error_count >= 10:
                        p.enabled = False
                    break

    def get_stats(self) -> list[dict]:
        """Get proxy status for monitoring."""
        stats = []
        for p in self._proxies:
            stats.append({
                "host": p.host,
                "port": p.port,
                "enabled": p.enabled,
                "bandwidth_used_mb": round(p.bandwidth_used_bytes / (1024 * 1024), 2),
                "bandwidth_remaining_mb": round(p.bandwidth_remaining_mb, 2),
                "error_count": p.error_count,
            })
        return stats
