"""Dashboard and health API server.

This module hosts the HTTP handler and startup helper used by main.py.
"""

import json
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from health.controllers import ApiControllers
from health.openapi_spec import build_openapi_spec
from health.router import HealthApiRouter


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DashboardHandler(SimpleHTTPRequestHandler):
    """Serves dashboard static files and REST API endpoints."""

    storage = None
    workers = None
    config = None
    start_time = 0.0
    api_router: HealthApiRouter | None = None

    def log_message(self, format, *args):
        pass  # suppress default access logging

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/docs", "/docs/"):
            self._serve_swagger_ui()
            return

        if path == "/openapi.json":
            self._send_json(build_openapi_spec(self.config))
            return

        if path.startswith("/api/"):
            self._handle_api(path, parsed.query)
        else:
            self._serve_static(path)

    def _send_json(self, data: dict | list, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _handle_api(self, path: str, query: str):
        if not self.api_router:
            self._send_json({"error": "API router not initialized"}, 500)
            return

        status, payload = self.api_router.handle(path, query)
        if isinstance(payload, dict) and payload.get("_download"):
            self._send_download(
                body=payload["body"],
                filename=payload["filename"],
                content_type=payload["content_type"],
                status=status,
            )
            return

        if isinstance(payload, (dict, list)):
            self._send_json(payload, status)
        else:
            self._send_json({"error": "Invalid API response"}, 500)

    def _send_download(
        self,
        body: bytes,
        filename: str,
        content_type: str,
        status: int = 200,
    ):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _serve_static(self, path: str):
        dashboard_dir = str(PROJECT_ROOT / "dashboard")

        if path == "/" or path == "":
            path = "/index.html"

        # Security: prevent directory traversal
        safe_path = os.path.normpath(path.lstrip("/"))
        if ".." in safe_path:
            self.send_error(403)
            return

        filepath = os.path.join(dashboard_dir, safe_path)
        if not os.path.isfile(filepath):
            # Fallback to index.html for SPA
            filepath = os.path.join(dashboard_dir, "index.html")

        if not os.path.isfile(filepath):
            self.send_error(404)
            return

        content_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        ext = os.path.splitext(filepath)[1]
        ct = content_types.get(ext, "application/octet-stream")

        with open(filepath, "rb") as f:
            body = f.read()

        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _serve_swagger_ui(self):
        # Swagger UI is loaded from CDN and points to this server's /openapi.json
        body = b"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>NewsScrapper API Docs</title>
    <link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\" />
    <style>
      html, body { margin: 0; padding: 0; }
      #swagger-ui { min-height: 100vh; }
    </style>
  </head>
  <body>
    <div id=\"swagger-ui\"></div>
    <script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: '/openapi.json',
        dom_id: '#swagger-ui',
        deepLinking: true,
        displayRequestDuration: true,
        defaultModelsExpandDepth: 1,
        docExpansion: 'list'
      });
    </script>
  </body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def start_dashboard(storage, workers: list, config: dict, start_time: float):
    """Start the dashboard HTTP server in a daemon thread."""
    if not config.get("dashboard_enabled"):
        return None

    host = config["dashboard_host"]
    port = config["dashboard_port"]

    DashboardHandler.storage = storage
    DashboardHandler.workers = workers
    DashboardHandler.config = config
    DashboardHandler.start_time = start_time
    DashboardHandler.api_router = HealthApiRouter(
        ApiControllers(storage, workers, config, start_time, PROJECT_ROOT)
    )

    server = HTTPServer((host, port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="dashboard")
    thread.start()

    return server
