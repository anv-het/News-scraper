"""Router for health/dashboard API endpoints."""

from __future__ import annotations

from urllib.parse import parse_qs


class HealthApiRouter:
    """Dispatches API paths to controller methods."""

    def __init__(self, controllers):
        self.controllers = controllers

    def handle(self, path: str, query: str):
        path = self._normalize_api_path(path)
        params = parse_qs(query)

        if path == "/api/stats":
            return self.controllers.get_stats()

        if path == "/api/news":
            source = params.get("source", [None])[0]
            date = params.get("date", [None])[0]
            limit = self._int_param(params, "limit", 500)
            return self.controllers.get_news(source=source, date=date, limit=limit)

        if path.startswith("/api/news/"):
            source = path.split("/api/news/")[1].strip("/")
            date = params.get("date", [None])[0]
            limit = self._int_param(params, "limit", 500)
            return self.controllers.get_news(source=source, date=date, limit=limit)

        if path == "/api/sources":
            return self.controllers.get_sources()

        if path == "/api/dates":
            source = params.get("source", [None])[0]
            return self.controllers.get_dates(source)

        if path == "/api/top-news":
            category = params.get("category", [None])[0]
            limit = self._int_param(params, "limit", 100)
            return self.controllers.get_top_news(category=category, limit=limit)

        if path == "/api/health":
            return self.controllers.health_status()

        if path == "/api/health/system":
            return self.controllers.health_system()

        if path == "/api/endpoints":
            return self.controllers.list_endpoints()

        if path == "/api/docs":
            return self.controllers.list_docs()

        if path == "/api/docs/read":
            file_name = params.get("file", [""])[0]
            return self.controllers.read_doc(file_name)

        if path == "/api/docs/download":
            file_name = params.get("file", [""])[0]
            return self.controllers.download_doc(file_name)

        if path == "/api/logs":
            return self.controllers.list_logs()

        if path == "/api/logs/dates":
            file_name = params.get("file", [""])[0]
            return self.controllers.log_dates(file_name)

        if path == "/api/logs/read":
            file_name = params.get("file", [""])[0]
            date = params.get("date", [None])[0]
            limit = self._int_param(params, "limit", 1000)
            return self.controllers.read_log(file_name=file_name, date=date, limit=limit)

        if path == "/api/logs/download":
            file_name = params.get("file", [""])[0]
            return self.controllers.download_log(file_name)

        if path == "/api/timing":
            source = params.get("source", [None])[0]
            return self.controllers.get_timing_metrics(source=source)

        return 404, {"error": "Not found"}

    @staticmethod
    def _normalize_api_path(path: str) -> str:
        """Normalize prefixed API paths to legacy /api/* format.

        This allows requests under /news_scrapper/api/* while preserving
        backward compatibility for existing /api/* clients.
        """
        prefix = "/news_scrapper"
        if path.startswith(prefix + "/api/"):
            return path[len(prefix) :]
        return path

    @staticmethod
    def _int_param(params: dict, key: str, default: int) -> int:
        try:
            return int(params.get(key, [default])[0])
        except (TypeError, ValueError):
            return default
