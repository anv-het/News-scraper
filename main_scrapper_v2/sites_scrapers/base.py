"""
Base scraper class that all site scrapers must extend.
Provides the standard interface for the orchestrator.
"""

import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod

import requests

from utils.time_utils import (
    IST, now_ist, format_date, format_time, format_scraped_at, time_ago_str,
)
from utils.proxy import ProxyManager


class _SrcLog:
    """Lightweight source-tagged logger for scraper classes."""
    __slots__ = ("_logger", "_src")

    def __init__(self, source_name: str):
        self._logger = logging.getLogger("scrapper")
        self._src = source_name

    def debug(self, msg: str):
        self._logger.debug(msg, extra={"source": self._src})

    def info(self, msg: str):
        self._logger.info(msg, extra={"source": self._src})

    def warning(self, msg: str):
        self._logger.warning(msg, extra={"source": self._src})

    def error(self, msg: str):
        self._logger.error(msg, extra={"source": self._src})


class BaseScraper(ABC):
    """
    Abstract base class for all site scrapers.

    Subclasses MUST implement:
        name        – unique identifier (matches sites.yaml key)
        fetch_news  – return list of new news dicts

    Subclasses MAY override:
        setup       – called once before the polling loop starts
    """

    name: str = ""

    def __init__(
        self,
        config: dict,
        proxy_manager: ProxyManager | None = None,
        redis_cache=None,
    ):
        self.config = config
        self.proxy_manager = proxy_manager
        self.redis = redis_cache
        self.session: requests.Session = requests.Session()
        self._seen_ids: set[str] = set()
        self._lock = threading.Lock()
        self._log = _SrcLog(self.name or self.__class__.__name__)
        self._session_created_at = 0  # Timestamp when session was last refreshed
        self._setup_session()

    def _setup_session(self):
        ua = self.config.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36",
        )
        self.session.headers.update({
            "User-Agent": ua,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        })

        if self.config.get("use_proxy") and self.proxy_manager:
            proxy_dict = self.proxy_manager.get_next()
            if proxy_dict:
                self.session.proxies.update(proxy_dict)

        self._session_created_at = time.time()

    def _refresh_session(self):
        """Refresh the session by clearing cookies and resetting to a clean state."""
        old_proxies = dict(self.session.proxies) if self.session.proxies else {}

        # Clear the session
        self.session.close()
        self.session = requests.Session()

        # Reset session with same config
        self._setup_session()

        self._log.debug("Session refreshed (cookies cleared, new connection pool)")


    def setup(self):
        """Called once before polling starts. Override for session init, etc."""
        pass

    @abstractmethod
    def fetch_news(self) -> list[dict]:
        """
        Fetch latest news and return NEW items only.
        Each item must be a dict with keys:
            news_date, news_time, scraped_at, news_caption,
            news_summary, news_url, image_url, time_ago
        """
        ...

    # ── Deduplication helpers ────────────────────────────────────────

    def _is_seen(self, item_id: str) -> bool:
        """Check if item_id was already processed (Redis + local set)."""
        if item_id in self._seen_ids:
            return True
        if self.redis and self.redis.available:
            if self.redis.is_seen(self.name, item_id):
                self._seen_ids.add(item_id)
                return True
        return False

    def _mark_seen(self, item_id: str):
        """Mark item_id as seen in local set and Redis."""
        self._seen_ids.add(item_id)
        if self.redis and self.redis.available:
            self.redis.mark_seen(self.name, item_id)

    def _mark_seen_bulk(self, item_ids: list[str]):
        for iid in item_ids:
            self._seen_ids.add(iid)
        if self.redis and self.redis.available:
            self.redis.mark_seen_bulk(self.name, item_ids)

    # ── Utility ──────────────────────────────────────────────────────

    def _build_item(
        self,
        dt,
        caption: str,
        summary: str,
        news_url: str,
        image_url: str = "",
    ) -> dict:
        """Build a standard news item dict from parsed data."""
        if dt:
            news_date = format_date(dt)
            news_time = format_time(dt)
            ago = time_ago_str(dt)
        else:
            n = now_ist()
            news_date = format_date(n)
            news_time = format_time(n)
            ago = "just now"

        return {
            "news_date": news_date,
            "news_time": news_time,
            "scraped_at": format_scraped_at(),
            "news_caption": caption,
            "news_summary": summary,
            "news_url": news_url,
            "image_url": image_url,
            "time_ago": ago,
            "source": self.name,  # Add source from scraper name
        }

    @staticmethod
    def clean_html(text: str) -> str:
        """Strip HTML tags from text."""
        return re.sub(r"<[^>]+>", "", text).strip() if text else ""

    def _safe_get(self, url: str, **kwargs) -> requests.Response | None:
        """GET with error handling and detailed logging. Returns None on failure."""
        timeout = kwargs.pop("timeout", None)
        if timeout is None:
            cfg_timeout = self.config.get("timeout", 10)
            timeout = (3, cfg_timeout)  # (connect, read)
        try:
            resp = self.session.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            body_preview = ""
            if e.response is not None:
                body_preview = e.response.text[:300].replace("\n", " ")
            if status == 403:
                self._log.warning(f"BLOCKED (HTTP 403 Forbidden) | {url}")
            elif status == 429:
                retry_after = (
                    e.response.headers.get("Retry-After", "?")
                    if e.response is not None else "?"
                )
                self._log.warning(
                    f"RATE LIMITED (HTTP 429) retry-after={retry_after} | {url}"
                )
            elif status == 401:
                self._log.warning(f"AUTH REQUIRED (HTTP 401) | {url}")
            elif status == 503:
                self._log.warning(f"SERVICE UNAVAILABLE (HTTP 503) | {url}")
            else:
                self._log.warning(
                    f"HTTP {status} | {url} | {body_preview[:150]}"
                )
            return None
        except requests.ConnectionError as e:
            self._log.error(f"CONNECTION ERROR: {e} | {url}")
            return None
        except requests.Timeout as e:
            self._log.warning(f"TIMEOUT: {e} | {url}")
            return None
        except requests.RequestException as e:
            self._log.error(
                f"REQUEST ERROR ({type(e).__name__}): {e} | {url}"
            )
            return None
