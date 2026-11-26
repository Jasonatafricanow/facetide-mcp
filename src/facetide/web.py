"""Local-only, separately launched Facetide browser workbench."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .core import Conflict, LifeStore, NotFound, ValidationError

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
        # Service identity for the read-only summary (WorkBench). Configured, never the browser's session
        # token (that one is handed out by /api/bootstrap). Unset or too short: the route is disabled.
        summary = os.environ.get("FACETIDE_SUMMARY_TOKEN", "")
        self.summary_token = summary if len(summary) >= 24 else None


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
            if req.path == "/api/summary/v1":
                return self.summary()
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
            if req.path == "/api/agent-context":
                q = parse_qs(req.query)
                return self.reply(200, self.server.store.agent_context(
                    q.get("start", [""])[0], q.get("end", [""])[0],
                    int(q.get("history_limit", ["0"])[0])))
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

    def summary(self):
        """facetide.summary.v1: read-only, bearer service token, GET only, no query parameters."""
        if self.server.summary_token is None:
            return self.reply(404, {"error": "Not found"})
        auth = self.headers.get("Authorization", "")
        if not secrets.compare_digest(auth.encode(), f"Bearer {self.server.summary_token}".encode()):
            return self.reply(401, {"error": "Unauthorized"})
        return self.reply(200, self.server.store.dashboard_summary())

    def do_POST(self):
        if not self.allowed():
            return
        req = urlsplit(self.path)
        if req.path not in ("/api/goals", "/api/reviews", "/api/agent-draft", "/api/agent-confirm"):
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
            elif req.path == "/api/agent-draft":
                allowed = {"period_start", "period_end", "evidence", "domains", "axes", "agent_note"}
                if set(body) - allowed:
                    raise ValidationError("Unknown agent draft fields")
                result = self.server.store.stage_agent_review(**body)
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
        except NotFound as exc:
            return self.reply(404, {"error": str(exc)})
        except Conflict as exc:
            return self.reply(409, {"error": str(exc)})
        except (ValueError, TypeError, KeyError) as exc:
            return self.reply(400, {"error": str(exc)})
        except OSError:
            return self.reply(503, {"error": "Data source unavailable"})



class SummaryHandler(WorkbenchHandler):
    """Service listener for a dashboard in another container: GET /api/summary/v1 with the bearer token,
    nothing else (no UI, no bootstrap token, no writes). The Host header is not checked because the caller
    reaches this port by a non-loopback address; the service token is the only gate."""

    def do_GET(self):
        if urlsplit(self.path).path != "/api/summary/v1":
            return self.reply(404, {"error": "Not found"})
        try:
            return self.summary()
        except OSError:
            return self.reply(503, {"error": "Data source unavailable"})

    def do_POST(self):
        return self.reply(404, {"error": "Not found"})

    do_PUT = do_DELETE = do_PATCH = do_POST


class SummaryServer(WorkbenchServer):
    def __init__(self, address, store):
        super().__init__(address, store)
        self.RequestHandlerClass = SummaryHandler


def summary_listen_address(value):
    """FACETIDE_SUMMARY_LISTEN=host:port -> (host, port); empty -> None."""
    if not value:
        return None
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("FACETIDE_SUMMARY_LISTEN must be host:port")
    return host, int(port)


def main():
    parser = argparse.ArgumentParser(description="Facetide local workbench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    store = LifeStore()
    server = WorkbenchServer(("127.0.0.1", args.port), store)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Facetide local UI: {url}", file=sys.stderr)
    listen = summary_listen_address(os.environ.get("FACETIDE_SUMMARY_LISTEN", ""))
    if listen and server.summary_token:
        # Separate socket, summary route only; the UI stays loopback-only.
        side = SummaryServer(listen, store)
        threading.Thread(target=side.serve_forever, daemon=True).start()
        print(f"Facetide summary listener: {listen[0]}:{side.server_port}", file=sys.stderr)
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
