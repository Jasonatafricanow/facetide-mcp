"""Period state synthesis tests; separate objective evidence from human scores."""
import tempfile
import unittest
from pathlib import Path

from facetide.core import LifeStore, ValidationError
from facetide.state import DIRECTIONS


class FakeSource:
    def __init__(self, records):
        self.records = records

    def query(self, start, end, domains):
        return [dict(r) for r in self.records if start <= r["occurred_at"] <= end], []


def record(name, date, domain):
    return {
        "source_type": "mrmem", "source_ref": name,
        "occurred_at": date, "known_at": date,
        "domain_ids": [domain], "summary": name,
        "evidence_kind": "user_statement",
        "resolution_status": "active", "change": None,
    }


def ref(name):
    return {"source_type": "mrmem", "source_ref": name}


class LongitudinalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = FakeSource([
            record("career-oct", "2026-10-12", "career"),
            record("health-oct", "2026-10-20", "health"),
            record("career-nov", "2026-11-03", "career"),
            record("health-nov", "2026-11-04", "health"),
        ])
        self.store = LifeStore(Path(self.temp.name) / "db.sqlite3", source=self.source)

    @staticmethod
    def payload(career, health, direction="initial"):
        domain_ids = ["career", "finance", "health", "family", "social", "leisure", "environment"]
        result = []
        for d in domain_ids:
            observed = d in {"career", "health"}
            ids = [career] if d == "career" else [health] if d == "health" else []
            result.append({
                "domain_id": d,
                "coverage": "partial" if observed else "unobserved",
                "picture": f"Grounded {d} state" if observed else "",
                "direction": direction if observed else "uncertain",
                "direction_reason": "Compared to verified prior state" if direction == "improved" and observed else "",
                "confidence": "medium" if observed else "unknown",
                "evidence_refs": [ref(i) for i in ids],
                "goal_fit": "not_assessed",
                "goal_ids": [],
                "tradeoffs": [],
                "question": "What matters most?" if d == "health" else "",
            })
        return result

    @staticmethod
    def axes(ids):
        return [
            {"axis": "personal_growth", "status": "proposed",
             "narrative": "A change in perspective described by the user",
             "evidence_refs": [ref(ids[0])]},
            {"axis": "self_realization", "status": "unknown",
             "narrative": "", "evidence_refs": []},
        ]

    def compile(self, start, end, domains, axes):
        context = self.store.get_state_context(start, end)
        return self.store.compile_state_report(
            period_start=start, period_end=end, context_token=context["context_token"],
            domains=domains, axes=axes,
        )

    def test_first_state_has_seven_domains_two_axes_no_scores(self):
        ctx = self.store.get_state_context("2026-10-01", "2026-10-31")
        self.assertIsNone(ctx["previous_state"])
        self.assertEqual(ctx["source_count"], 2)
        report = self.compile("2026-10-01", "2026-10-31",
                              self.payload("career-oct", "health-oct"),
                              self.axes(["career-oct"]))
        self.assertEqual(len(report["domains"]), 7)
        self.assertEqual(len(report["axes"]), 2)
        self.assertEqual(report["domains"][0]["picture"], "Grounded career state")
        self.assertEqual(report["status"], "agent_proposal")
        self.assertTrue(self.store.get_state_report("2026-10-01", "2026-10-31")["validation"]["valid"])
        self.assertIsNone(self.store.get_snapshot()["domains"][0]["score"])
        self.assertEqual(self.store.get_state_report("2026-10-01","2026-10-31")["report"]["report_id"], report["report_id"])

    def test_comparison_requires_actual_valid_previous_baseline(self):
        with self.assertRaises(ValidationError):
            self.compile("2026-11-01", "2026-11-05",
                         self.payload("career-nov", "health-nov", direction="improved"),
                         self.axes(["career-nov"]))
        old = self.compile("2026-10-01", "2026-10-31",
                           self.payload("career-oct", "health-oct"), self.axes(["career-oct"]))
        new = self.compile("2026-11-01", "2026-11-05",
                           self.payload("career-nov", "health-nov", direction="improved"),
                           self.axes(["career-nov"]))
        self.assertEqual(new["baseline_report_id"], old["report_id"])
        self.assertEqual(new["domains"][0]["direction"], "improved")
        self.assertTrue(self.store.get_state_report("2026-11-01", "2026-11-05")["validation"]["valid"])

    def test_cross_domain_tradeoffs_and_goal_alignment_are_source_anchored(self):
        goal = self.store.upsert_goal(title="Sustainable working week",
            enough_condition="Enough rest without losing income",
            domain_ids=["career","health"],user_confirmed=True)
        states=self.payload("career-oct", "health-oct")
        states[0]["goal_fit"]="strained"
        states[0]["goal_ids"]=[goal["goal_id"]]
        states[0]["tradeoffs"]=[{
            "other_domain":"health", "claim":"Work affected rest",
            "evidence_refs":[ref("career-oct"),ref("health-oct")]
        }]
        r=self.compile("2026-10-01","2026-10-31",states,self.axes(["career-oct"]))
        self.assertEqual(r["domains"][0]["goal_fit"],"strained")
        self.assertEqual(r["domains"][0]["tradeoffs"][0]["other_domain"],"health")
        self.assertEqual(r["domains"][0]["question"],"")

    def test_retractions_invalidate_past_and_future_proposals(self):
        self.compile("2026-10-01", "2026-10-31",
                     self.payload("career-oct", "health-oct"), self.axes(["career-oct"]))
        self.source.records[0]["resolution_status"]="retracted"
        stale = self.store.get_state_report("2026-10-01", "2026-10-31")
        self.assertFalse(stale["validation"]["valid"])
        self.assertEqual(stale["validation"]["stale_refs"][0]["source_ref"],"career-oct")
        with self.assertRaises(ValidationError):
            self.compile("2026-11-01","2026-11-05",
                         self.payload("career-nov","health-nov",direction="improved"),
                         self.axes(["career-nov"]))

    def test_source_changed_rejects_stale_token(self):
        context=self.store.get_state_context("2026-10-01","2026-10-31")
        self.source.records[0]["summary"]="Edited original meaning"
        with self.assertRaises(ValidationError):
            self.store.compile_state_report(
                period_start="2026-10-01",period_end="2026-10-31",
                context_token=context["context_token"],
                domains=self.payload("career-oct","health-oct"),
                axes=self.axes(["career-oct"]),
            )

    def test_deduplicated_repeat_and_append_only_correction(self):
        original=self.compile("2026-10-01","2026-10-31",
                              self.payload("career-oct","health-oct"),self.axes(["career-oct"]))
        repeated=self.compile("2026-10-01","2026-10-31",
                              self.payload("career-oct","health-oct"),self.axes(["career-oct"]))
        self.assertEqual(original["report_id"],repeated["report_id"])
        self.assertTrue(repeated["unchanged"])
        edited=self.payload("career-oct","health-oct")
        edited[0]["picture"]="A revised, source-supported interpretation"
        revision=self.compile("2026-10-01","2026-10-31",edited,self.axes(["career-oct"]))
        self.assertEqual(revision["supersedes"], original["report_id"])
        self.assertNotEqual(original["report_id"],revision["report_id"])

    def test_reject_fabricated_states_and_axes(self):
        reports=self.payload("career-oct","health-oct")
        reports[0]["evidence_refs"]=[ref("fabricated")]
        with self.assertRaises(ValidationError):
            self.compile("2026-10-01","2026-10-31",reports,self.axes(["career-oct"]))
        reports=self.payload("career-oct","health-oct")
        reports[1]["coverage"]="unobserved"
        with self.assertRaises(ValidationError):
            self.compile("2026-10-01","2026-10-31",reports,self.axes(["career-oct"]))
        with self.assertRaises(ValidationError):
            self.compile("2026-10-01","2026-10-31",
                self.payload("career-oct","health-oct"),
                [{"axis":"personal_growth","status":"proposed","narrative":"Imagined cause","evidence_refs":[]},
                 {"axis":"self_realization","status":"unknown","narrative":"","evidence_refs":[]}])

    def test_state_trend_without_comparison_rejected(self):
        for direction in DIRECTIONS - {"initial","uncertain"}:
            with self.subTest(direction=direction), self.assertRaises(ValidationError):
                self.compile("2026-10-01", "2026-10-31",
                             self.payload("career-oct","health-oct",direction=direction),
                             self.axes(["career-oct"]))


if __name__ == "__main__":
    unittest.main()
