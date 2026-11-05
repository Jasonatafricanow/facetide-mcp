"""Local browser API and CSRF regression tests."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from facetide.core import LifeStore
from facetide.web import WorkbenchServer


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
