"""OpenAPI specification builder for health and dashboard APIs."""


API_PREFIX = "/news_scrapper"


def _with_prefix(path: str) -> str:
    return f"{API_PREFIX}{path}"


def _paths_definition() -> dict:
    return {
            _with_prefix("/api/health"): {
                "get": {
                    "tags": ["Health"],
                    "summary": "Service health status",
                    "description": "Returns service UP status, uptime, environment, OS, start time, and system details.",
                    "responses": {"200": {"description": "Healthy service status payload."}},
                }
            },
            _with_prefix("/api/health/system"): {
                "get": {
                    "tags": ["Health"],
                    "summary": "Runtime system details",
                    "description": "Returns Python version, machine architecture, full platform string, and CPU count.",
                    "responses": {"200": {"description": "System information payload."}},
                }
            },
            _with_prefix("/api/stats"): {
                "get": {
                    "tags": ["Monitoring"],
                    "summary": "Worker and crawler stats",
                    "description": "Returns crawler statistics including worker health, fetched counts, errors, and uptime seconds.",
                    "responses": {"200": {"description": "Current crawler stats."}},
                }
            },
            _with_prefix("/api/sources"): {
                "get": {
                    "tags": ["Sources"],
                    "summary": "Configured sources",
                    "description": "Lists all configured sources with display name, enabled flag, description, and poll interval.",
                    "responses": {"200": {"description": "Source configuration list."}},
                }
            },
            _with_prefix("/api/news"): {
                "get": {
                    "tags": ["News"],
                    "summary": "Query news items",
                    "description": "Fetches news records with optional source, date, and limit filters.",
                    "parameters": [
                        {
                            "name": "source",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                            "description": "Source key (example: groww, bbc).",
                        },
                        {
                            "name": "date",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "example": "2026-03-20"},
                            "description": "Date in YYYY-MM-DD format.",
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 500},
                            "description": "Maximum items to return.",
                        },
                    ],
                    "responses": {"200": {"description": "News items list."}},
                }
            },
            _with_prefix("/api/news/{source}"): {
                "get": {
                    "tags": ["News"],
                    "summary": "Query source-specific news",
                    "description": "Fetches news for a single source path param with optional date and limit filters.",
                    "parameters": [
                        {
                            "name": "source",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Source key.",
                        },
                        {
                            "name": "date",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "example": "2026-03-20"},
                            "description": "Date in YYYY-MM-DD format.",
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 500},
                            "description": "Maximum items to return.",
                        },
                    ],
                    "responses": {"200": {"description": "News items list for source."}},
                }
            },
            _with_prefix("/api/dates"): {
                "get": {
                    "tags": ["News"],
                    "summary": "Available data dates",
                    "description": "Lists available crawl dates globally or for one source.",
                    "parameters": [
                        {
                            "name": "source",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                            "description": "Optional source key to filter dates.",
                        }
                    ],
                    "responses": {"200": {"description": "Date list in descending order."}},
                }
            },
            _with_prefix("/api/docs"): {
                "get": {
                    "tags": ["Docs"],
                    "summary": "List docs files",
                    "description": "Lists markdown and other files inside the DOCS directory with metadata.",
                    "responses": {"200": {"description": "Docs file list."}},
                }
            },
            _with_prefix("/api/docs/read"): {
                "get": {
                    "tags": ["Docs"],
                    "summary": "Read docs file",
                    "description": "Reads full text content of a selected DOCS file.",
                    "parameters": [
                        {
                            "name": "file",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "example": "README.md"},
                            "description": "File name in DOCS directory.",
                        }
                    ],
                    "responses": {"200": {"description": "Document content payload."}},
                }
            },
            _with_prefix("/api/docs/download"): {
                "get": {
                    "tags": ["Docs"],
                    "summary": "Download docs file",
                    "description": "Downloads a selected file from the DOCS directory.",
                    "parameters": [
                        {
                            "name": "file",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "example": "README.md"},
                            "description": "File name in DOCS directory.",
                        }
                    ],
                    "responses": {"200": {"description": "Binary file response."}},
                }
            },
            _with_prefix("/api/logs"): {
                "get": {
                    "tags": ["Logs"],
                    "summary": "List log files",
                    "description": "Lists available files in log directory with size and modified timestamp.",
                    "responses": {"200": {"description": "Log files list."}},
                }
            },
            _with_prefix("/api/logs/dates"): {
                "get": {
                    "tags": ["Logs"],
                    "summary": "List dates in a log file",
                    "description": "Parses one log file and returns distinct YYYY-MM-DD date values present in lines.",
                    "parameters": [
                        {
                            "name": "file",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "example": "scrapper.log"},
                            "description": "Log file name.",
                        }
                    ],
                    "responses": {"200": {"description": "Available date list for the log file."}},
                }
            },
            _with_prefix("/api/logs/read"): {
                "get": {
                    "tags": ["Logs"],
                    "summary": "Read log lines",
                    "description": "Reads log lines from selected file, optionally filtering by date and truncating by limit.",
                    "parameters": [
                        {
                            "name": "file",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "example": "scrapper.log"},
                            "description": "Log file name.",
                        },
                        {
                            "name": "date",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "example": "2026-03-20"},
                            "description": "Optional date filter in YYYY-MM-DD.",
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 1000},
                            "description": "Return only the last N matching lines.",
                        },
                    ],
                    "responses": {"200": {"description": "Log lines payload."}},
                }
            },
            _with_prefix("/api/logs/download"): {
                "get": {
                    "tags": ["Logs"],
                    "summary": "Download log file",
                    "description": "Downloads selected log file as an attachment.",
                    "parameters": [
                        {
                            "name": "file",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string", "example": "scrapper.log"},
                            "description": "Log file name.",
                        }
                    ],
                    "responses": {"200": {"description": "Binary file response."}},
                }
            },
        }


def endpoint_catalog() -> list[dict]:
    """Human-friendly endpoint catalog used by API and docs.

    Returns a compact list that can be consumed by UI/API clients.
    """
    catalog = []
    for path, methods in _paths_definition().items():
        for method, meta in methods.items():
            catalog.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "tag": (meta.get("tags") or ["General"])[0],
                    "summary": meta.get("summary", ""),
                    "description": meta.get("description", ""),
                }
            )
    return catalog


def build_openapi_spec(config: dict) -> dict:
    title = f"{config.get('project_name', 'NewsScrapper')} Health API"

    return {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": "1.0.0",
            "description": "Operational APIs for health checks, sources, news data, docs, and logs.",
        },
        "paths": _paths_definition(),
    }
