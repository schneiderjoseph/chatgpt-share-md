"""Zero-dependency HTTP server providing the web UI and /api/convert endpoint."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .converter import ConvertError, convert_html_to_markdown, convert_source

HTML_TEMPLATE_PATH = Path(__file__).parent / "template.html"


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Standardize HTTP logging
        super().log_message(format, *args)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            if not HTML_TEMPLATE_PATH.exists():
                self.send_error(500, "HTML template missing")
                return
            content = HTML_TEMPLATE_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/robots.txt":
            robots = (
                "User-agent: *\n"
                "Allow: /\n\n"
                "# AI search & indexing bots\n"
                "User-agent: GPTBot\n"
                "Allow: /\n\n"
                "User-agent: ClaudeBot\n"
                "Allow: /\n\n"
                "User-agent: PerplexityBot\n"
                "Allow: /\n\n"
                "User-agent: CCBot\n"
                "Allow: /\n\n"
                "Sitemap: /sitemap.xml\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(robots)))
            self.end_headers()
            self.wfile.write(robots)
            return

        if self.path == "/sitemap.xml":
            sitemap = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                '  <url>\n'
                '    <loc>https://chatgpt-share-md.org/</loc>\n'
                '    <changefreq>weekly</changefreq>\n'
                '    <priority>1.0</priority>\n'
                '  </url>\n'
                '</urlset>\n'
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(sitemap)))
            self.end_headers()
            self.wfile.write(sitemap)
            return

        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        if self.path == "/api/convert":
            length_header = self.headers.get("Content-Length")
            if not length_header:
                self._send_json(400, {"success": False, "error": "Missing Content-Length header"})
                return

            try:
                length = int(length_header)
                # Limit payload to 15MB
                if length > 15 * 1024 * 1024:
                    self._send_json(413, {"success": False, "error": "Payload too large (max 15MB)"})
                    return
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8"))
            except Exception as exc:
                self._send_json(400, {"success": False, "error": f"Invalid JSON payload: {exc}"})
                return

            url = (data.get("url") or "").strip()
            raw_html = (data.get("html") or "").strip()
            include_tools = bool(data.get("include_tools", False))
            include_system = bool(data.get("include_system", False))

            if not url and not raw_html:
                self._send_json(
                    400,
                    {
                        "success": False,
                        "error": "Either 'url' or 'html' must be provided in the request body.",
                    },
                )
                return

            try:
                if raw_html:
                    markdown, metadata = convert_html_to_markdown(
                        raw_html,
                        source=url or "pasted-html",
                        include_tools=include_tools,
                        include_system=include_system,
                    )
                else:
                    markdown, metadata = convert_source(
                        url,
                        include_tools=include_tools,
                        include_system=include_system,
                    )

                self._send_json(
                    200,
                    {
                        "success": True,
                        "markdown": markdown,
                        "metadata": metadata,
                    },
                )
            except ConvertError as exc:
                self._send_json(422, {"success": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"success": False, "error": f"Conversion error: {exc}"})
            return

        self.send_error(404, "Not Found")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(encoded)


def start_server(host: str = "0.0.0.0", port: int = 8080) -> int:
    server = ThreadingHTTPServer((host, port), WebHandler)
    print(f"ChatGPT-to-Markdown web interface running at http://{host}:{port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
    return 0
