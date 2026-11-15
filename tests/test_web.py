"""Local browser API and CSRF regression tests."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from facetide.core import LifeStore
from facetide.web import WorkbenchServer
from test_agent_handoff import payload


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.server = WorkbenchServer(("127.0.0.1", 0),
                                      LifeStore(Path(self.folder.name) / "data.sqlite3"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, payload=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            data = None if payload is None else json.dumps(payload)
            conn.request(method, path, body=data, headers=headers or {})
            reply = conn.getresponse()
            return reply.status, dict(reply.getheaders()), reply.read()
        finally:
            conn.close()

    def test_static_workbench_is_served_without_sensitive_headers(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"facetide", body)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn(self.server.token.encode(), body)
        for asset in ("/app.js", "/style.css"):
            status, _, content = self.request("GET", asset)
            self.assertEqual(status, 200)
            self.assertGreater(len(content), 1000)

    def test_host_and_mutation_csrf_guards(self):
        status, _, _ = self.request("GET", "/api/snapshot",
                                    headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        data = {
            "period_start": "2026-11-01", "period_end": "2026-11-05",
            "domain_scores": {"health": 3}, "user_confirmed": True,
        }
        headers = {"Content-Type": "application/json"}
        status, _, _ = self.request("POST", "/api/reviews", data, headers)
        self.assertEqual(status, 403)
        headers["X-Facetide-Token"] = self.server.token
        headers["Origin"] = "https://attacker.example"
        status, _, _ = self.request("POST", "/api/reviews", data, headers)
        self.assertEqual(status, 403)

    def test_full_local_review_write_then_read(self):
        boot = json.loads(self.request("GET", "/api/bootstrap")[2])
        self.assertEqual(boot["token"], self.server.token)
        headers = {"Content-Type": "application/json",
                   "X-Facetide-Token": boot["token"],
                   "Origin": f"http://127.0.0.1:{self.server.server_port}"}
        goal = {
            "title": "Restore a sustainable sleep schedule",
            "enough_condition": "Most mornings feel rested",
            "domain_ids": ["health", "leisure"],
            "user_confirmed": True,
        }
        status, _, content = self.request("POST", "/api/goals", goal, headers)
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(content)["version"], 1)
        review = {
            "period_start": "2026-11-01", "period_end": "2026-11-05",
            "domain_scores": {"health": 3}, "user_confirmed": True,
            "personal_growth": "Learned where to draw boundaries",
        }
        status, _, _ = self.request("POST", "/api/reviews", review, headers)
        self.assertEqual(status, 201)
        snapshot = json.loads(self.request("GET", "/api/snapshot")[2])
        self.assertEqual(snapshot["latest_review"]["domain_scores"]["health"], 3)
        self.assertEqual(len(snapshot["goals"]), 1)
        history = json.loads(self.request("GET", "/api/history")[2])
        self.assertEqual(history["total"], 1)


    def test_agent_handoff_can_be_confirmed_by_local_workbench(self):
        domains = [
            {"domain_id": name, "coverage": "unknown", "observation": "",
             "evidence_refs": [], "direction": "unknown",
             "meaning": {"assessment": "uncertain", "basis": "unknown",
                         "why": "", "evidence_refs": []}}
            for name in ("career", "finance", "health", "family", "social",
                         "leisure", "environment")
        ]
        axes = [
            {"axis": name, "status": "unknown", "narrative": "",
             "evidence_refs": [], "basis": "unknown"}
            for name in ("personal_growth", "self_realization")
        ]
        draft = self.server.store.stage_agent_review(
            period_start="2026-11-01", period_end="2026-11-05",
            evidence=[], domains=domains, axes=axes)
        confirmation = {
            "draft_id": draft["draft_id"], "expected_hash": draft["draft_hash"],
            "domain_scores": {"health": 3}, "user_confirmed": True,
        }
        status, _, _ = self.request("POST", "/api/agent-confirm", confirmation,
                                    {"Content-Type": "application/json"})
        self.assertEqual(status, 403)
        headers = {
            "Content-Type": "application/json",
            "X-Facetide-Token": self.server.token,
            "Origin": f"http://127.0.0.1:{self.server.server_port}",
        }
        status, _, content = self.request("POST", "/api/agent-confirm", confirmation, headers)
        self.assertEqual(status, 201)
        body = json.loads(content)
        self.assertEqual(body["approved_draft_id"], draft["draft_id"])
        self.assertEqual(body["review"]["domain_scores"], {"health": 3})
        context = json.loads(self.request(
            "GET", "/api/context?start=2026-11-01&end=2026-11-05")[2])
        self.assertEqual(context["agent_handoff"]["draft"]["draft_id"], draft["draft_id"])

    def test_context_query_is_read_only(self):
        status, _, body = self.request("GET", "/api/context?start=2026-11-01&end=2026-11-05")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["evidence"], [])
        status, _, _ = self.request("GET", "/api/context?start=2026-11-06&end=2026-11-05")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()


class AgentHandoffHttpTests(unittest.TestCase):
    """HTTP agent-context/agent-draft must match the compact MCP contract."""

    setUp, stop, request = WorkbenchTests.setUp, WorkbenchTests.stop, WorkbenchTests.request

    def post(self, path, payload, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Facetide-Token"] = self.server.token
        status, _, content = self.request("POST", path, payload, headers)
        return status, json.loads(content)

    def get(self, path):
        status, _, content = self.request("GET", path)
        return status, json.loads(content)

    def no_review_saved(self):
        self.assertEqual(self.server.store.get_history()["total"], 0)
        self.assertIsNone(self.server.store.get_snapshot()["latest_review"])

    def test_agent_context_matches_compact_mcp_context(self):
        import os
        from unittest import mock
        from facetide import server as mcp_server
        self.server.store.stage_agent_review(**payload())
        status, http_result = self.get("/api/agent-context?start=2026-11-01&end=2026-11-05&history_limit=3")
        self.assertEqual(status, 200)
        with mock.patch.dict(os.environ, {"FACETIDE_DB_PATH": str(self.server.store.path)}):
            mcp_result = mcp_server.facetide_context("2026-11-01", "2026-11-05", 3)
        self.assertEqual(http_result, json.loads(json.dumps(mcp_result, ensure_ascii=False)))
        self.assertEqual(http_result["protocol"], "facetide.agent_handoff.v1")
        self.assertIsNotNone(http_result["latest_draft"])
        for bad in ("history_limit=21", "history_limit=x", "history_limit=0&start=2026-11-05&end=2026-11-01"):
            query = bad if "start=" in bad else "start=2026-11-01&end=2026-11-05&" + bad
            self.assertEqual(self.get("/api/agent-context?" + query)[0], 400, bad)

    def test_agent_draft_stages_only_and_never_becomes_a_review(self):
        self.assertEqual(self.post("/api/agent-draft", payload(), token=False)[0], 403)
        status, staged = self.post("/api/agent-draft", payload())
        self.assertEqual(status, 201)
        self.assertEqual(staged["status"], "agent_proposal")
        self.no_review_saved()
        _, context = self.get("/api/agent-context?start=2026-11-01&end=2026-11-05")
        self.assertEqual(context["latest_draft"]["draft_hash"], staged["draft_hash"])
        self.assertIsNone(context["confirmed_review"])

    def test_agent_draft_rejects_review_fields_instead_of_saving_a_review(self):
        for extra in ({"user_confirmed": True}, {"domain_scores": {"health": 3}}):
            status, _ = self.post("/api/agent-draft", {**payload(), **extra})
            self.assertEqual(status, 400, extra)
        incomplete = payload()
        incomplete["domains"] = incomplete["domains"][:6]
        self.assertEqual(self.post("/api/agent-draft", incomplete)[0], 400)
        missing = payload()
        del missing["axes"]
        self.assertEqual(self.post("/api/agent-draft", missing)[0], 400)
        self.no_review_saved()
        _, context = self.get("/api/agent-context?start=2026-11-01&end=2026-11-05")
        self.assertIsNone(context["latest_draft"])

    def test_confirm_requires_explicit_flag_and_current_hash(self):
        _, staged = self.post("/api/agent-draft", payload())
        base = {"draft_id": staged["draft_id"], "expected_hash": staged["draft_hash"],
                "domain_scores": {"health": 3}}
        self.assertEqual(self.post("/api/agent-confirm", {**base, "user_confirmed": False})[0], 400)
        self.assertEqual(self.post("/api/agent-confirm", {**base, "expected_hash": "0" * 64, "user_confirmed": True})[0], 400)
        self.no_review_saved()
        status, confirmed = self.post("/api/agent-confirm", {**base, "user_confirmed": True})
        self.assertEqual(status, 201)
        self.assertEqual(confirmed["review"]["domain_scores"], {"health": 3})
