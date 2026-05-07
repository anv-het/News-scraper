"""
JSON file storage with atomic writes and deduplication.
Stores source archives in DATA/<source_name>/<date>.json and mirrors daywise
aggregates into DATA/DAYWISE/YYYY/MM_MonthName/<date>.json.
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime

from utils.time_utils import IST, now_ist, sort_key_desc
from utils.unique_id import UniqueIdAllocator


class JsonStorage:
    """Thread-safe JSON storage for news articles."""

    _SPECIAL_DIRS = {"DAYWISE", "top_news", ".cache"}

    def __init__(self, data_dir: str = "DATA"):
        self._data_dir = data_dir
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        self._backup_lock = threading.Lock()
        self._title_dedup_lock = threading.Lock()
        self._date_title_index: dict[str, set[str]] = {}
        self._unique_id_allocator = UniqueIdAllocator(os.path.join(data_dir, ".unique_id_state.json"))
        os.makedirs(data_dir, exist_ok=True)

    @staticmethod
    def _title_key(item: dict) -> str:
        raw = (item.get("news_caption") or "").strip().lower()
        if not raw:
            return ""
        return " ".join(raw.split())

    def _build_date_title_index(self, date_key: str) -> set[str]:
        daywise_titles = {
            self._title_key(item)
            for item in self._read_json(self._daywise_file(date_key))
            if isinstance(item, dict)
        }

        # Fallback to source daily files when daywise mirror is missing.
        if daywise_titles:
            return {title for title in daywise_titles if title}

        fallback_titles: set[str] = set()
        for source in self._source_dirs():
            src_file = os.path.join(self._data_dir, source, f"{date_key}.json")
            for item in self._read_json(src_file):
                if isinstance(item, dict):
                    title_key = self._title_key(item)
                    if title_key:
                        fallback_titles.add(title_key)
        return fallback_titles

    def _get_date_title_index(self, date_key: str) -> set[str]:
        titles = self._date_title_index.get(date_key)
        if titles is None:
            titles = self._build_date_title_index(date_key)
            self._date_title_index[date_key] = titles
        return titles

    def _filter_new_titles(self, date_key: str, items: list[dict]) -> list[dict]:
        known_titles = self._get_date_title_index(date_key)
        accepted: list[dict] = []

        for item in items:
            title_key = self._title_key(item)
            if title_key and title_key in known_titles:
                continue
            accepted.append(item)
            if title_key:
                known_titles.add(title_key)

        return accepted

    def _get_lock(self, source: str) -> threading.Lock:
        with self._global_lock:
            if source not in self._locks:
                self._locks[source] = threading.Lock()
            return self._locks[source]

    def _source_dir(self, source: str) -> str:
        path = os.path.join(self._data_dir, source)
        os.makedirs(path, exist_ok=True)
        return path

    def _is_source_dir(self, name: str) -> bool:
        return bool(name) and name not in self._SPECIAL_DIRS

    def _source_dirs(self) -> list[str]:
        try:
            return [
                d for d in os.listdir(self._data_dir)
                if os.path.isdir(os.path.join(self._data_dir, d)) and self._is_source_dir(d)
            ]
        except OSError:
            return []

    def _daywise_root(self) -> str:
        path = os.path.join(self._data_dir, "DAYWISE")
        os.makedirs(path, exist_ok=True)
        return path

    def _daywise_date_dir(self, date_key: str) -> str:
        try:
            dt = datetime.strptime(date_key, "%Y-%m-%d")
            year_dir = os.path.join(self._daywise_root(), f"{dt:%Y}")
            month_dir = os.path.join(year_dir, f"{dt:%m}_{dt:%B}")
        except ValueError:
            year_dir = os.path.join(self._daywise_root(), "unknown")
            month_dir = os.path.join(year_dir, "unknown")
        os.makedirs(month_dir, exist_ok=True)
        return month_dir

    def _daywise_file(self, date_key: str) -> str:
        return os.path.join(self._daywise_date_dir(date_key), f"{date_key}.json")

    def _backup_file(self) -> str:
        return os.path.join(self._data_dir, "backup.json")

    @staticmethod
    def _article_identity(item: dict, include_source: bool = False) -> str:
        source = (item.get("source") or "").strip().lower() if include_source else ""
        url = (item.get("news_url") or "").strip()
        if url:
            return f"{source}|url|{url}" if include_source else f"url|{url}"

        caption = (item.get("news_caption") or "").strip().lower()
        date = (item.get("news_date") or "").strip()
        time_str = (item.get("news_time") or "").strip()
        if include_source:
            return f"{source}|fallback|{date}|{time_str}|{caption}"
        return f"fallback|{date}|{time_str}|{caption}"

    def _normalize_items(self, source: str, items: list[dict], fallback_date: str | None = None) -> list[dict]:
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry["source"] = entry.get("source") or source
            if fallback_date and not entry.get("news_date"):
                entry["news_date"] = fallback_date
            normalized.append(entry)
        return normalized

    def _merge_articles(
        self,
        existing: list[dict],
        incoming: list[dict],
        include_source_in_identity: bool = False,
    ) -> list[dict]:
        merged_map: dict[str, dict] = {}

        for article in existing:
            if isinstance(article, dict):
                merged_map[self._article_identity(article, include_source_in_identity)] = article

        for article in incoming:
            if isinstance(article, dict):
                merged_map[self._article_identity(article, include_source_in_identity)] = article

        merged = list(merged_map.values())
        merged.sort(key=sort_key_desc, reverse=True)
        return merged

    def _write_articles(self, filepath: str, existing: list[dict], incoming: list[dict], include_source_in_identity: bool = False) -> int:
        new_unique = self._merge_articles(existing, incoming, include_source_in_identity=include_source_in_identity)
        if new_unique == existing:
            return 0
        self._atomic_write(filepath, new_unique)
        return len(incoming)

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
        Save news items to source daily JSON files and mirror them into daywise JSON files.
        Returns number of items actually saved (after dedup).
        """
        if not news_list:
            return 0

        # Ensure every fetched item has a persistent monotonic unique ID.
        self._unique_id_allocator.assign_if_missing(news_list)

        lock = self._get_lock(source)
        src_dir = self._source_dir(source)
        saved = 0

        with lock:
            # Group by date
            by_date: dict[str, list[dict]] = {}
            for item in news_list:
                date_key = item.get("news_date") or now_ist().strftime("%Y-%m-%d")
                by_date.setdefault(date_key, []).append(
                    self._normalize_items(source, [item], fallback_date=date_key)[0]
                )

            for date_key, items in by_date.items():
                with self._title_dedup_lock:
                    items_to_save = self._filter_new_titles(date_key, items)

                    if not items_to_save:
                        continue

                    filepath = os.path.join(src_dir, f"{date_key}.json")
                    existing = self._read_json(filepath)
                    merged = self._merge_articles(existing, items_to_save, include_source_in_identity=False)

                    if merged != existing:
                        self._atomic_write(filepath, merged)
                        saved += len(merged) - len(existing)

                    daywise_path = self._daywise_file(date_key)
                    daywise_existing = self._read_json(daywise_path)
                    daywise_merged = self._merge_articles(
                        daywise_existing,
                        items_to_save,
                        include_source_in_identity=True,
                    )
                    if daywise_merged != daywise_existing:
                        self._atomic_write(daywise_path, daywise_merged)

        return saved

    def append_backup(self, source: str, news_list: list[dict]):
        """Backup writing is disabled; retained as a no-op for compatibility."""
        return

    def migrate_existing_backups_to_root(self) -> int:
        """Backup migration is disabled; retained as a no-op for compatibility."""
        return 0

    def migrate_existing_source_data_to_daywise(self) -> int:
        """Backfill daywise JSON files from existing source daily files."""
        migrated = 0

        for source in self._source_dirs():
            src_dir = os.path.join(self._data_dir, source)
            try:
                file_names = os.listdir(src_dir)
            except OSError:
                continue

            for fname in file_names:
                if not fname.endswith(".json") or fname == "backup.json":
                    continue

                filepath = os.path.join(src_dir, fname)
                date_key = fname[:-5]
                items = self._normalize_items(source, self._read_json(filepath), fallback_date=date_key)
                if not items:
                    continue

                daywise_path = self._daywise_file(date_key)
                daywise_existing = self._read_json(daywise_path)
                daywise_merged = self._merge_articles(
                    daywise_existing,
                    items,
                    include_source_in_identity=True,
                )
                if daywise_merged != daywise_existing:
                    self._atomic_write(daywise_path, daywise_merged)
                    migrated += len(daywise_merged) - len(daywise_existing)

        return migrated

    def cleanup_duplicate_titles(self, dry_run: bool = True) -> dict:
        """One-time historical cleanup of duplicate titles across stored JSON archives.

        Rules:
        - Source daily files: per-date global title uniqueness across all sources.
        - Daywise files: rebuilt from cleaned source daily files for each date.
        - backup.json: global title uniqueness across all dates.
        """
        stats = {
            "dry_run": dry_run,
            "source_daily_files_scanned": 0,
            "source_daily_files_changed": 0,
            "daywise_files_changed": 0,
            "backup_changed": False,
            "source_daily_duplicates_removed": 0,
            "backup_duplicates_removed": 0,
        }

        date_groups: dict[str, list[tuple[str, str, list[dict]]]] = {}

        for source in sorted(self._source_dirs()):
            src_dir = os.path.join(self._data_dir, source)
            try:
                file_names = sorted(os.listdir(src_dir))
            except OSError:
                continue

            for fname in file_names:
                if not fname.endswith(".json") or fname == "backup.json":
                    continue

                date_key = fname[:-5]
                filepath = os.path.join(src_dir, fname)
                normalized = self._normalize_items(source, self._read_json(filepath), fallback_date=date_key)
                date_groups.setdefault(date_key, []).append((source, filepath, normalized))
                stats["source_daily_files_scanned"] += 1

        for date_key, file_entries in sorted(date_groups.items()):
            flattened: list[tuple[str, dict]] = []
            for _, filepath, items in file_entries:
                for item in items:
                    if isinstance(item, dict):
                        flattened.append((filepath, item))

            flattened.sort(
                key=lambda pair: (
                    sort_key_desc(pair[1]),
                    pair[1].get("source", ""),
                    pair[1].get("news_url", ""),
                ),
                reverse=True,
            )

            seen_titles: set[str] = set()
            kept_by_file: dict[str, list[dict]] = {filepath: [] for _, filepath, _ in file_entries}

            for filepath, article in flattened:
                title_key = self._title_key(article)
                if title_key and title_key in seen_titles:
                    stats["source_daily_duplicates_removed"] += 1
                    continue

                kept_by_file[filepath].append(article)
                if title_key:
                    seen_titles.add(title_key)

            for source, filepath, _ in file_entries:
                new_items = kept_by_file.get(filepath, [])
                new_items.sort(key=sort_key_desc, reverse=True)

                existing = self._normalize_items(source, self._read_json(filepath), fallback_date=date_key)
                if new_items == existing:
                    continue

                stats["source_daily_files_changed"] += 1
                if not dry_run:
                    self._atomic_write(filepath, new_items)

            rebuilt_daywise: list[dict] = []
            for items in kept_by_file.values():
                rebuilt_daywise.extend(items)

            rebuilt_daywise = self._merge_articles([], rebuilt_daywise, include_source_in_identity=True)

            daywise_path = self._daywise_file(date_key)
            existing_daywise = self._read_json(daywise_path)
            existing_daywise = self._merge_articles([], existing_daywise, include_source_in_identity=True)

            if rebuilt_daywise != existing_daywise:
                stats["daywise_files_changed"] += 1
                if not dry_run:
                    self._atomic_write(daywise_path, rebuilt_daywise)

            cleaned_titles = {self._title_key(item) for item in rebuilt_daywise if isinstance(item, dict)}
            self._date_title_index[date_key] = {title for title in cleaned_titles if title}

        backup_path = self._backup_file()
        backup_existing = [item for item in self._read_json(backup_path) if isinstance(item, dict)]
        backup_existing.sort(key=sort_key_desc, reverse=True)

        dedup_backup: list[dict] = []
        seen_backup_titles: set[str] = set()

        for item in backup_existing:
            title_key = self._title_key(item)
            if title_key and title_key in seen_backup_titles:
                stats["backup_duplicates_removed"] += 1
                continue

            dedup_backup.append(item)
            if title_key:
                seen_backup_titles.add(title_key)

        if dedup_backup != backup_existing:
            stats["backup_changed"] = True
            if not dry_run:
                self._atomic_write(backup_path, dedup_backup)

        return stats

    def get_news(
        self,
        source: str | None = None,
        date: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Read news for API/dashboard.

        Source-specific requests read from source archives. All-source requests
        read from the daywise mirror that aggregates source articles.
        """
        date_key = date or now_ist().strftime("%Y-%m-%d")

        if source:
            src_dir = os.path.join(self._data_dir, source)
            if not os.path.isdir(src_dir):
                return []
            filepath = os.path.join(src_dir, f"{date_key}.json")
            items = self._normalize_items(source, self._read_json(filepath), fallback_date=date_key)
            items.sort(key=sort_key_desc, reverse=True)
            return items[:limit]

        daywise_path = self._daywise_file(date_key)
        items = self._read_json(daywise_path)
        if not items:
            # Fall back to rebuilding from source archives if the mirror is missing.
            items = []
            for src in self._source_dirs():
                src_file = os.path.join(self._data_dir, src, f"{date_key}.json")
                items.extend(self._normalize_items(src, self._read_json(src_file), fallback_date=date_key))
            if items:
                merged = self._merge_articles([], items, include_source_in_identity=True)
                self._atomic_write(daywise_path, merged)
                items = merged
        else:
            for it in items:
                if not it.get("source"):
                    it["source"] = ""

        items.sort(key=sort_key_desc, reverse=True)
        return items[:limit]

    def get_stats(self) -> dict:
        """Compute stats across all sources."""
        stats = {"sources": {}, "total_articles": 0}

        try:
            source_dirs = [
                d for d in os.listdir(self._data_dir)
                if os.path.isdir(os.path.join(self._data_dir, d)) and self._is_source_dir(d)
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

    def get_available_dates(self, source: str | None = None) -> list[str]:
        """Return known dates for a source, or across the daywise mirror."""
        dates = set()

        if source:
            src_dir = os.path.join(self._data_dir, source)
            if not os.path.isdir(src_dir):
                return []
            try:
                for fname in os.listdir(src_dir):
                    if fname.endswith(".json") and fname != "backup.json":
                        dates.add(fname[:-5])
            except OSError:
                return []
            return sorted(dates, reverse=True)

        daywise_root = self._daywise_root()
        if os.path.isdir(daywise_root):
            for year_name in os.listdir(daywise_root):
                year_dir = os.path.join(daywise_root, year_name)
                if not os.path.isdir(year_dir):
                    continue
                for month_name in os.listdir(year_dir):
                    month_dir = os.path.join(year_dir, month_name)
                    if not os.path.isdir(month_dir):
                        continue
                    for fname in os.listdir(month_dir):
                        if fname.endswith(".json"):
                            dates.add(fname[:-5])

        if not dates:
            for src in self._source_dirs():
                src_dir = os.path.join(self._data_dir, src)
                try:
                    for fname in os.listdir(src_dir):
                        if fname.endswith(".json") and fname != "backup.json":
                            dates.add(fname[:-5])
                except OSError:
                    continue

        return sorted(dates, reverse=True)
