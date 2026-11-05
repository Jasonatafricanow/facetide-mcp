"""Local-only, separately launched Facetide browser workbench."""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .core import LifeStore, ValidationError

ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store):
        super().__init__(address, WorkbenchHandler)
        self.store = store
        self.token = secrets.token_urlsafe(32)


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def reply(self, status, payload, mime="application/json; charset=utf-8"):
        data = json.dumps(payload, ensure_ascii=False).encode() if not isinstance(payload, bytes) else payload
        self.send_response(status)
        for key, val in {
            "Content-Type": mime, "Content-Length": str(len(data)),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        }.items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        accepted = (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
        if self.headers.get("Host") not in accepted:
            self.reply(403, {"error": "Host must be loopback"})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        req = urlsplit(self.path)
        try:
            if req.path == "/api/bootstrap":
                return self.reply(200, {"token": self.server.token, "version": __version__,
                                        "source": type(self.server.store.source).__name__})
            if req.path == "/api/snapshot":
                return self.reply(200, self.server.store.get_snapshot())
            if req.path == "/api/history":
                q = parse_qs(req.query)
                return self.reply(200, self.server.store.get_history(
                    domain_id=q.get("domain_id", [None])[0], limit=int(q.get("limit", ["100"])[0])))
            if req.path == "/api/context":
                q = parse_qs(req.query)
                return self.reply(200, self.server.store.prepare_review(
                    q.get("start", [""])[0], q.get("end", [""])[0]))
            if req.path == "/api/state":
                q = parse_qs(req.query)
                return self.reply(200, self.server.store.get_state_report(
                    q.get("start", [""])[0], q.get("end", [""])[0]))
            if req.path in ASSETS:
                name, mime = ASSETS[req.path]
                return self.reply(200, files("facetide").joinpath("static", name).read_bytes(), mime)
            return self.reply(404, {"error": "Not found"})
        except (ValueError, TypeError) as exc:
            return self.reply(400, {"error": str(exc)})
        except OSError:
            return self.reply(503, {"error": "Data source unavailable"})

    def do_POST(self):
        if not self.allowed():
            return
        req = urlsplit(self.path)
        if req.path not in ("/api/goals", "/api/reviews", "/api/agent-confirm"):
            return self.reply(404, {"error": "Not found"})
        expected_origin = (f"http://127.0.0.1:{self.server.server_port}",
                           f"http://localhost:{self.server.server_port}")
        if self.headers.get("Origin") and self.headers["Origin"] not in expected_origin:
            return self.reply(403, {"error": "Invalid origin"})
        if not secrets.compare_digest(self.headers.get("X-Facetide-Token", ""),
                                      self.server.token):
            return self.reply(403, {"error": "Invalid session token"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.reply(415, {"error": "Expected JSON"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 131072:
                return self.reply(413, {"error": "Invalid request size"})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValidationError("Expected an object")
            if req.path == "/api/goals":
                allowed = {"title", "enough_condition", "domain_ids", "user_confirmed",
                           "status", "indicators", "goal_id", "expected_version"}
                if set(body) - allowed:
                    raise ValidationError("Unknown goal fields")
                result = self.server.store.upsert_goal(**body)
            elif req.path == "/api/agent-confirm":
                allowed = {"draft_id", "expected_hash", "domain_scores", "user_confirmed",
                           "personal_growth", "self_realization", "user_notes", "revision_of"}
                if set(body) - allowed:
                    raise ValidationError("Unknown agent confirmation fields")
                result = self.server.store.confirm_agent_review(**body)
            else:
                allowed = {"period_start", "period_end", "domain_scores", "user_confirmed",
                           "change_band", "evidence_refs", "personal_growth",
                           "self_realization", "user_notes", "revision_of"}
                if set(body) - allowed:
                    raise ValidationError("Unknown review fields")
                result = self.server.store.save_review(**body)
            return self.reply(201, result)
        except (ValueError, TypeError, KeyError) as exc:
            return self.reply(400, {"error": str(exc)})
        except OSError:
            return self.reply(503, {"error": "Data source unavailable"})


def main():
    parser = argparse.ArgumentParser(description="Facetide local workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    server = WorkbenchServer(("127.0.0.1", args.port), LifeStore())
    url = f"http://127.0.0.1:{args.port}"
    print(f"Facetide local UI: {url}", file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
