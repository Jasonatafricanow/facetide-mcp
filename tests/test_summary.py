"""facetide.summary.v1: read-only life summary for WorkBench behind a configured service token."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from facetide.core import LifeStore
from facetide.web import WorkbenchServer
from test_agent_handoff import payload

TOKEN = "summary-test-token-0123456789abcdef"


class SummaryApi(unittest.TestCase):
    def start(self, token=TOKEN):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = LifeStore(Path(folder.name) / "data.sqlite3")
        env = {"FACETIDE_SUMMARY_TOKEN": token} if token is not None else {}
        with mock.patch.dict(os.environ, env, clear=False):
            if token is None:
                os.environ.pop("FACETIDE_SUMMARY_TOKEN", None)
            self.server = WorkbenchServer(("127.0.0.1", 0), self.store)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(timeout=3)))

    def get(self, path="/api/summary/v1", token=TOKEN, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            conn.request(method, path, headers=headers)
            reply = conn.getresponse()
            return reply.status, json.loads(reply.read() or b"{}")
        finally:
            conn.close()

    def review(self, start, end, scores, **kw):
        return self.store.save_review(period_start=start, period_end=end, domain_scores=scores,
                                      user_confirmed=True, **kw)

    def test_disabled_without_a_configured_service_token(self):
        self.start(token=None)
        self.assertEqual(self.get()[0], 404)

    def test_rejects_unauthorised_callers_including_the_browser_session_token(self):
        self.start()
        self.assertEqual(self.get(token=None)[0], 401)
        self.assertEqual(self.get(token="wrong")[0], 401)
        self.assertEqual(self.get(token=self.server.token)[0], 401)
        self.assertEqual(self.get(method="POST")[0], 404)  # no write path

    def test_latest_previous_nulls_and_no_private_fields(self):
        self.start()
        old = self.review("2026-10-01", "2026-10-31", {"health": 6, "career": 7.5}, personal_growth="older growth")
        first = self.review("2026-11-01", "2026-11-15", {"health": 5}, user_notes="private note",
                            self_realization="building the workbench")
        revised = self.review("2026-11-01", "2026-11-15", {"health": 5.5, "family": 8},
                              self_realization="building the workbench", revision_of=first["review_id"])
        status, body = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(body["contract"], "facetide.summary.v1")
        self.assertEqual(body["score_scale"], {"min": 0, "max": 10, "step": 0.5})
        latest, previous = body["latest"], body["previous"]
        self.assertEqual(latest["review_id"], revised["review_id"])  # latest revision of the latest period
        self.assertEqual(previous["review_id"], old["review_id"])    # not the superseded revision
        self.assertEqual(len(latest["domain_scores"]), 7)
        self.assertEqual(latest["domain_scores"]["family"], 8)
        self.assertIsNone(latest["domain_scores"]["social"])         # not scored -> null, never invented
        self.assertIsNone(latest["personal_growth"])
        self.assertEqual(latest["self_realization"], "building the workbench")
        text = json.dumps(body, ensure_ascii=False)
        for private in ("private note", "user_notes", "evidence_refs", "approved_draft", "goals_snapshot"):
            self.assertNotIn(private, text)

    def test_unconfirmed_agent_drafts_never_appear(self):
        self.start()
        self.store.stage_agent_review(**payload())
        status, body = self.get()
        self.assertEqual(status, 200)
        self.assertIsNone(body["latest"])
        self.assertIsNone(body["previous"])

    def test_goals_are_listed_without_indicators(self):
        self.start()
        self.store.upsert_goal(title="Sleep before 1am", enough_condition="5 nights a week",
                               domain_ids=["health"], user_confirmed=True)
        goals = self.get()[1]["goals"]
        self.assertEqual([(g["title"], g["status"], g["domain_ids"]) for g in goals],
                         [("Sleep before 1am", "building", ["health"])])
        self.assertNotIn("indicators", goals[0])


if __name__ == "__main__":
    unittest.main()


class SummaryListener(unittest.TestCase):
    """FACETIDE_SUMMARY_LISTEN: a second socket that a dashboard in another container can reach."""

    def setUp(self):
        from facetide.web import SummaryServer
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        with mock.patch.dict(os.environ, {"FACETIDE_SUMMARY_TOKEN": TOKEN}):
            self.server = SummaryServer(("127.0.0.1", 0), LifeStore(Path(folder.name) / "data.sqlite3"))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(timeout=3)))

    def call(self, path, token=TOKEN, method="GET", host="172.27.0.1:8875"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            headers = {"Host": host, **({"Authorization": f"Bearer {token}"} if token else {})}
            conn.request(method, path, headers=headers)
            reply = conn.getresponse()
            return reply.status, json.loads(reply.read() or b"{}")
        finally:
            conn.close()

    def test_summary_answers_a_non_loopback_host(self):
        status, body = self.call("/api/summary/v1")
        self.assertEqual(status, 200)
        self.assertEqual(body["contract"], "facetide.summary.v1")

    def test_token_still_required(self):
        self.assertEqual(self.call("/api/summary/v1", token=None)[0], 401)
        self.assertEqual(self.call("/api/summary/v1", token="wrong-token-0123456789abcdef")[0], 401)

    def test_nothing_else_is_served(self):
        for path in ("/", "/api/bootstrap", "/api/snapshot", "/api/history", "/app.js"):
            self.assertEqual(self.call(path)[0], 404, path)
        self.assertEqual(self.call("/api/reviews", method="POST")[0], 404)

    def test_listen_address_parsing(self):
        from facetide.web import summary_listen_address
        self.assertIsNone(summary_listen_address(""))
        self.assertEqual(summary_listen_address("0.0.0.0:8875"), ("0.0.0.0", 8875))
        for bad in ("8875", "host:", "host:0", "host:x"):
            with self.assertRaises(ValueError):
                summary_listen_address(bad)
