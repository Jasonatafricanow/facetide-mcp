"""Host LLM handoff contract tests: evidence, attribution and user approval."""
import tempfile
import sqlite3
import unittest
from pathlib import Path

from facetide.core import LifeStore, ValidationError


def payload():
    evidence = [
        {"evidence_id": "sb1", "provider": "statebar", "source_ref": "state-1",
         "source_tool": "user_state.get_state",
         "occurred_at": "2026-11-03T10:00:00+00:00",
         "valid_until": "2026-11-05T18:00:00+00:00",
         "status": "active", "kind": "state", "summary": "A project is active"},
        {"evidence_id": "mem1", "provider": "mrmem", "source_ref": "memory-1",
         "source_tool": "memory_read", "occurred_at": "2026-10-09",
         "status": "active", "kind": "user_statement",
         "summary": "User values work progress without giving up rest"},
    ]
    dims = ["career", "finance", "health", "family", "social", "leisure", "environment"]
    domains = []
    for key in dims:
        known = key in ("career", "leisure")
        refs = ["sb1"] if key == "career" else ["mem1"] if key == "leisure" else []
        domains.append({
            "domain_id": key, "coverage": "partial" if known else "unknown",
            "observation": "A relevant observation" if known else "",
            "evidence_refs": refs, "direction": "unknown",
            "meaning": {"assessment": "mixed" if key == "career" else "uncertain",
                        "basis": "user_explicit" if key == "career" else "unknown",
                        "why": "Work may cost valued rest" if key == "career" else "",
                        "evidence_refs": ["mem1"] if key == "career" else []},
            "question": "Still acceptable?" if key == "career" else "",
        })
    axes = [
        {"axis": "personal_growth", "status": "proposed",
         "narrative": "A new boundary around work effort was expressed",
         "evidence_refs": ["mem1"], "basis": "agent_hypothesis"},
        {"axis": "self_realization", "status": "unknown",
         "narrative": "", "evidence_refs": [], "basis": "unknown"},
    ]
    return {"period_start": "2026-11-01", "period_end": "2026-11-05",
            "evidence": evidence, "domains": domains, "axes": axes}


class AgentHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LifeStore(Path(self.temp.name) / "facetide.sqlite3")

    def test_brief_routes_host_agent_without_calling_source_itself(self):
        result = self.store.agent_brief("2026-11-01", "2026-11-05")
        self.assertEqual(result["protocol"], "facetide.agent_handoff.v1")
        self.assertEqual(len(result["domains"]), 7)
        self.assertIn("user_state.get_state", result["source_tools"]["statebar"])
        self.assertEqual(result["schema"]["title"], "Facetide Agent Handoff v1")
        self.assertEqual(result["schema"]["properties"]["domains"]["minItems"], 7)

    def test_full_draft_integrity_and_unscored_7plus2(self):
        result = self.store.stage_agent_review(**payload())
        draft = self.store.get_agent_review("2026-11-01", "2026-11-05")["draft"]
        self.assertEqual(draft["draft_id"], result["draft_id"])
        self.assertEqual(draft["draft_hash"], result["draft_hash"])
        self.assertEqual(draft["domains"][0]["meaning"]["assessment"], "mixed")
        self.assertEqual(draft["evidence"][0]["source_ref"], "state-1")
        self.assertEqual(draft["evidence"][0]["verification"], "host_attested")
        self.assertTrue(all(d["score"] is None for d in self.store.get_snapshot()["domains"]))
        context = self.store.prepare_review("2026-11-01", "2026-11-05")
        self.assertEqual(context["agent_handoff"]["draft"]["draft_id"], result["draft_id"])

    def test_explicit_confirm_freezes_draft_with_user_scores(self):
        result = self.store.stage_agent_review(**payload())
        required = {"draft_id": result["draft_id"], "expected_hash": result["draft_hash"],
                    "domain_scores": {"career": 3}}
        with self.assertRaises(ValidationError):
            self.store.confirm_agent_review(**required, user_confirmed=False)
        with self.assertRaises(ValidationError):
            self.store.confirm_agent_review(**{**required, "expected_hash": "tampered"},
                                            user_confirmed=True)
        saved = self.store.confirm_agent_review(**required, user_confirmed=True,
                                                personal_growth="I chose this tradeoff",
                                                user_notes="Approved after edits")
        self.assertEqual(saved["review"]["domain_scores"], {"career": 3})
        self.assertEqual(saved["review"]["personal_growth"], "I chose this tradeoff")
        with self.store._connection() as db:
            link = db.execute("SELECT * FROM agent_review_links WHERE review_id=?",
                              (saved["review"]["review_id"],)).fetchone()
            self.assertEqual(link["draft_id"], result["draft_id"])
        self.assertEqual(LifeStore(self.store.path).get_history()["total"], 1)

    def test_cannot_fabricate_why_user_values_something(self):
        body = payload()
        body["domains"][0]["meaning"]["basis"] = "unknown"
        with self.assertRaises(ValidationError):
            self.store.stage_agent_review(**body)
        body = payload()
        body["domains"][0]["meaning"]["evidence_refs"] = ["fictional"]
        with self.assertRaises(ValidationError):
            self.store.stage_agent_review(**body)
        body = payload()
        body["axes"][0]["evidence_refs"] = []
        with self.assertRaises(ValidationError):
            self.store.stage_agent_review(**body)

    def test_unknown_domains_and_actual_source_validity_are_preserved(self):
        body = payload()
        body["evidence"][0]["status"] = "expired"
        result = self.store.stage_agent_review(**body)
        draft = self.store.get_agent_review("2026-11-01", "2026-11-05")["draft"]
        self.assertEqual(draft["evidence"][0]["status"], "expired")
        self.assertEqual(result["status"], "agent_proposal")
        body = payload()
        body["domains"] = body["domains"][:-1]
        with self.assertRaises(ValidationError):
            self.store.stage_agent_review(**body)
        body = payload()
        body["domains"][1]["observation"] = "No records proves decline"
        with self.assertRaises(ValidationError):
            self.store.stage_agent_review(**body)

    def test_invalid_timestamp_and_refs_fail_cleanly(self):
        wrong = payload()
        wrong["evidence"][0]["occurred_at"] = "2026-11-03junk"
        with self.assertRaises(ValidationError):
            self.store.stage_agent_review(**wrong)
        wrong = payload()
        wrong["domains"][0]["evidence_refs"] = [{}]
        with self.assertRaises(ValidationError):
            self.store.stage_agent_review(**wrong)

    def test_staging_never_rewrites_draft_or_user_goals(self):
        first = self.store.stage_agent_review(**payload())
        second_payload = payload()
        second_payload["domains"][0]["meaning"]["basis"] = "agent_hypothesis"
        second = self.store.stage_agent_review(**second_payload)
        self.assertNotEqual(first["draft_id"], second["draft_id"])
        with self.store._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM agent_handoff_drafts").fetchone()[0], 2)

    def test_confirmed_history_survives_a_new_unapproved_draft(self):
        first = self.store.stage_agent_review(**payload())
        saved = self.store.confirm_agent_review(
            draft_id=first["draft_id"], expected_hash=first["draft_hash"],
            domain_scores={"career": 3}, user_confirmed=True)
        second = self.store.stage_agent_review(**payload())
        for review in (saved["review"], self.store.get_history()["reviews"][0],
                       self.store.get_snapshot()["latest_review"],
                       self.store.get_period_review("2026-11-01", "2026-11-05"),
                       self.store.agent_brief("2026-12-01", "2026-12-31")["previous_user_review"]):
            approved = review["approved_draft"]
            self.assertEqual(approved["draft_id"], first["draft_id"])
            self.assertEqual(len(approved["domains"]), 7)
            self.assertEqual(len(approved["evidence"]), 2)
            self.assertEqual(approved["verification"], "host_attested")
        self.assertEqual(self.store.get_agent_review("2026-11-01", "2026-11-05")
                         ["draft"]["draft_id"], second["draft_id"])

    def test_link_failure_rolls_back_confirmed_review(self):
        staged = self.store.stage_agent_review(**payload())
        with self.store._connection() as db:
            db.execute("""CREATE TRIGGER fail_link BEFORE INSERT ON agent_review_links
                          BEGIN SELECT RAISE(ABORT, 'injected link failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.confirm_agent_review(
                draft_id=staged["draft_id"], expected_hash=staged["draft_hash"],
                domain_scores={"career": 3}, user_confirmed=True)
        self.assertEqual(self.store.get_history()["total"], 0)


if __name__ == "__main__":
    unittest.main()
