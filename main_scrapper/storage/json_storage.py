"""
JSON file storage with atomic writes, deduplication, and backup management.
Stores news in DATA/<source_name>/<date>.json and DATA/<source_name>/backup.json.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime

from utils.time_utils import IST, now_ist, sort_key_desc


class JsonStorage:
    """Thread-safe JSON storage for news articles."""

    def __init__(self, data_dir: str = "DATA"):
        self._data_dir = data_dir
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        os.makedirs(data_dir, exist_ok=True)

    def _get_lock(self, source: str) -> threading.Lock:
        with self._global_lock:
            if source not in self._locks:
                self._locks[source] = threading.Lock()
            return self._locks[source]

    def _source_dir(self, source: str) -> str:
        path = os.path.join(self._data_dir, source)
        os.makedirs(path, exist_ok=True)
        return path

    def _atomic_write(self, filepath: str, data: list[dict]):
        """Write JSON atomically using temp file + rename."""
        dir_path = os.path.dirname(filepath)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Windows can throw transient PermissionError when target is briefly locked.
            # Retry a few times before failing the write.
            attempts = 5
            for i in range(attempts):
                try:
                    if os.path.exists(filepath):
                        os.replace(tmp_path, filepath)
                    else:
                        os.rename(tmp_path, filepath)
                    break
                except PermissionError:
                    if i == attempts - 1:
                        raise
                    time.sleep(0.05 * (2 ** i))
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _read_json(self, filepath: str) -> list[dict]:
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def save_news(self, source: str, news_list: list[dict]) -> int:
        """
        Save news items to daily JSON files.
        Returns number of items actually saved (after dedup).
        """
        if not news_list:
            return 0

        lock = self._get_lock(source)
        src_dir = self._source_dir(source)
        saved = 0

        with lock:
            # Group by date
            by_date: dict[str, list[dict]] = {}
            for item in news_list:
                date_key = item.get("news_date") or now_ist().strftime("%Y-%m-%d")
                by_date.setdefault(date_key, []).append(item)

            for date_key, items in by_date.items():
                filepath = os.path.join(src_dir, f"{date_key}.json")
                existing = self._read_json(filepath)

                # Deduplicate by news_url
                seen_urls = {
                    it.get("news_url") for it in existing if it.get("news_url")
                }
                new_unique = [
                    it for it in items
                    if not it.get("news_url") or it["news_url"] not in seen_urls
                ]

                if not new_unique:
                    continue

                merged = existing + new_unique
                merged.sort(key=sort_key_desc, reverse=True)
                self._atomic_write(filepath, merged)
                saved += len(new_unique)

        return saved

    def append_backup(self, source: str, news_list: list[dict]):
        """Append news to the source's backup.json (all-time collection)."""
        if not news_list:
            return

        lock = self._get_lock(source)
        src_dir = self._source_dir(source)
        backup_path = os.path.join(src_dir, "backup.json")

        with lock:
            existing = self._read_json(backup_path)

            # Deduplicate by news_url
            seen_urls = {
                it.get("news_url") for it in existing if it.get("news_url")
            }
            new_unique = [
                it for it in news_list
                if not it.get("news_url") or it["news_url"] not in seen_urls
            ]

            if not new_unique:
                return

            merged = new_unique + existing  # newest first
            merged.sort(key=sort_key_desc, reverse=True)
            self._atomic_write(backup_path, merged)

    def get_news(
        self,
        source: str | None = None,
        date: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Read news for API/dashboard. If source is None, read from all sources."""
        results = []

        if source:
            sources = [source]
        else:
            try:
                sources = [
                    d for d in os.listdir(self._data_dir)
                    if os.path.isdir(os.path.join(self._data_dir, d))
                ]
            except OSError:
                return []

        for src in sources:
            src_dir = os.path.join(self._data_dir, src)
            if not os.path.isdir(src_dir):
                continue

            if date:
                filepath = os.path.join(src_dir, f"{date}.json")
                items = self._read_json(filepath)
                for it in items:
                    it["source"] = src
                results.extend(items)
            else:
                # Get today's news by default
                today = now_ist().strftime("%Y-%m-%d")
                filepath = os.path.join(src_dir, f"{today}.json")
                items = self._read_json(filepath)
                for it in items:
                    it["source"] = src
                results.extend(items)

        results.sort(key=sort_key_desc, reverse=True)
        return results[:limit]

    def get_stats(self) -> dict:
        """Compute stats across all sources."""
        stats = {"sources": {}, "total_articles": 0}

        try:
            source_dirs = [
                d for d in os.listdir(self._data_dir)
                if os.path.isdir(os.path.join(self._data_dir, d))
            ]
        except OSError:
            return stats

        for src in source_dirs:
            src_dir = os.path.join(self._data_dir, src)
            total = 0
            files = []

            for fname in os.listdir(src_dir):
                if fname.endswith(".json") and fname != "backup.json":
                    filepath = os.path.join(src_dir, fname)
                    items = self._read_json(filepath)
                    total += len(items)
                    files.append(fname.replace(".json", ""))

            # Get today's count
            today = now_ist().strftime("%Y-%m-%d")
            today_file = os.path.join(src_dir, f"{today}.json")
            today_items = self._read_json(today_file)
            today_count = len(today_items)

            # Last article time
            last_article = ""
            if today_items:
                last = today_items[0]
                last_article = f"{last.get('news_date', '')} {last.get('news_time', '')}"

            files.sort(reverse=True)

            stats["sources"][src] = {
                "total_articles": total,
                "today_articles": today_count,
                "last_article": last_article,
                "dates_available": files[:30],
            }
            stats["total_articles"] += total

        return stats

    def get_all_news_for_date(self, date: str | None = None) -> list[dict]:
        """Get all news from all sources for a specific date."""
        if not date:
            date = now_ist().strftime("%Y-%m-%d")
        return self.get_news(source=None, date=date, limit=10000)
