"""Controllers for health, docs, logs, and existing dashboard data APIs."""

from __future__ import annotations

import mimetypes
import os
import platform
import re
import time
from datetime import datetime
from pathlib import Path

from health.openapi_spec import endpoint_catalog
from categorizing.top_news import get_top_news_manager


class ApiControllers:
    """Controller methods used by the health API router."""

    def __init__(self, storage, workers: list, config: dict, start_time: float, project_root: Path, top_news_mgr=None):
        self.storage = storage
        self.workers = workers or []
        self.config = config or {}
        self.start_time = start_time
        self.project_root = Path(project_root)
        self.docs_dir = self.project_root / "DOCS"
        self.logs_dir = self.project_root / self.config.get("log_dir", "logs")
        self.top_news_mgr = top_news_mgr

    def get_stats(self):
        stats = self.storage.get_stats()
        stats["uptime_seconds"] = int(time.time() - self.start_time)
        stats["workers"] = {}
        for w in self.workers:
            stats["workers"][w.scraper.name] = {
                "status": w.status,
                "total_fetched": w.total_fetched,
                "consecutive_errors": w.consecutive_errors,
                "consecutive_empty": w.consecutive_empty,
                "last_success": w.last_success_time,
                "is_blocked": w.is_blocked,
                "poll_interval": [w.poll_min, w.poll_max],
                "last_error": w.last_error,
                "last_error_time": w.last_error_time,
            }
        return 200, stats

    def get_news(self, source: str | None, date: str | None, limit: int):
        news = self.storage.get_news(source=source, date=date, limit=limit)

        # Respect limit after filtering
        return 200, news[:limit]

    def get_sources(self):
        sites_cfg = self.config.get("sites", {})
        sources = []
        for name, cfg in sites_cfg.items():
            sources.append(
                {
                    "name": name,
                    "display_name": cfg.get("display_name", name),
                    "enabled": cfg.get("enabled", True),
                    "description": cfg.get("description", ""),
                    "poll_interval": cfg.get("poll_interval", [5, 10]),
                }
            )
        return 200, sources

    def get_top_news(self, category: str | None, limit: int):
        """Get top news articles, optionally filtered by category."""
        if not self.top_news_mgr:
            return 200, []

        top_news = self.top_news_mgr.get_top_news(limit=limit, category=category)

        return 200, top_news

    def get_dates(self, source: str | None):
        dates = self.storage.get_available_dates(source=source)
        return 200, dates

    def health_status(self):
        uptime_sec = max(0, int(time.time() - self.start_time))
        return 200, {
            "statusCode": 200,
            "data": {
                "status": "UP",
                "uptime": self._format_uptime(uptime_sec),
                "environment": os.getenv("ENVIRONMENT", "development"),
                "os": platform.system(),
                "startTime": datetime.fromtimestamp(self.start_time).strftime("%d/%m/%Y, %H:%M:%S"),
                "system": platform.processor() or platform.platform(),
            },
            "message": "News-scrapper system is healthy",
        }

    def health_system(self):
        data = {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        }
        return 200, {"statusCode": 200, "data": data, "message": "System details"}

    def list_endpoints(self):
        return 200, {
            "statusCode": 200,
            "data": endpoint_catalog(),
            "message": "Available API endpoints with descriptions",
        }

    def list_docs(self):
        files = []
        if self.docs_dir.is_dir():
            for p in sorted(self.docs_dir.iterdir()):
                if p.is_file():
                    files.append(
                        {
                            "name": p.name,
                            "size": p.stat().st_size,
                            "modified": int(p.stat().st_mtime),
                        }
                    )
        return 200, {"statusCode": 200, "data": files, "message": "Docs file list"}

    def read_doc(self, file_name: str):
        path = self._safe_join(self.docs_dir, file_name)
        if not path or not path.is_file():
            return 404, {"statusCode": 404, "data": None, "message": "Document not found"}

        text = path.read_text(encoding="utf-8", errors="replace")
        return 200, {
            "statusCode": 200,
            "data": {"name": path.name, "content": text},
            "message": "Document content",
        }

    def download_doc(self, file_name: str):
        return self._build_download(self.docs_dir, file_name)

    def list_logs(self):
        files = []
        if self.logs_dir.is_dir():
            for p in sorted(self.logs_dir.iterdir()):
                if p.is_file():
                    files.append(
                        {
                            "name": p.name,
                            "size": p.stat().st_size,
                            "modified": int(p.stat().st_mtime),
                        }
                    )
        return 200, {"statusCode": 200, "data": files, "message": "Log file list"}

    def log_dates(self, file_name: str):
        path = self._safe_join(self.logs_dir, file_name)
        if not path or not path.is_file():
            return 404, {"statusCode": 404, "data": [], "message": "Log file not found"}

        dates = set()
        date_re = re.compile(r"^(\d{4}-\d{2}-\d{2})")
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = date_re.match(line)
                if m:
                    dates.add(m.group(1))
        return 200, {
            "statusCode": 200,
            "data": sorted(dates, reverse=True),
            "message": "Available log dates",
        }

    def read_log(self, file_name: str, date: str | None, limit: int):
        path = self._safe_join(self.logs_dir, file_name)
        if not path or not path.is_file():
            return 404, {"statusCode": 404, "data": None, "message": "Log file not found"}

        lines = []
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if date and not line.startswith(date):
                    continue
                lines.append(line.rstrip("\n"))

        if limit > 0:
            lines = lines[-limit:]

        return 200, {
            "statusCode": 200,
            "data": {"name": path.name, "date": date, "lines": lines, "count": len(lines)},
            "message": "Log content",
        }

    def download_log(self, file_name: str):
        return self._build_download(self.logs_dir, file_name)

    def get_timing_metrics(self, source: str | None = None):
        """Get timing metrics for scraper pipeline operations.

        NOTE: Timing metrics feature is not yet implemented.
        This endpoint returns a placeholder response.
        """
        return 200, {
            "statusCode": 501,
            "data": None,
            "message": "Timing metrics feature not yet implemented",
        }

    def _build_download(self, base_dir: Path, file_name: str):
        path = self._safe_join(base_dir, file_name)
        if not path or not path.is_file():
            return 404, {"statusCode": 404, "data": None, "message": "File not found"}

        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return 200, {
            "_download": True,
            "body": body,
            "filename": path.name,
            "content_type": content_type,
        }

    @staticmethod
    def _format_uptime(total_sec: int) -> str:
        days, rem = divmod(total_sec, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{days}d {hours}h {minutes}m {seconds}s"

    @staticmethod
    def _safe_join(base_dir: Path, file_name: str) -> Path | None:
        if not file_name:
            return None
        candidate = (base_dir / file_name).resolve()
        base = base_dir.resolve()
        if candidate == base or base not in candidate.parents:
            return None
        return candidate
