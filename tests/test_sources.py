"""Evidence bridge: temporal truth, sources, revocation and duplicate handling."""
import json
import tempfile
import unittest
from pathlib import Path

from facetide.core import LifeStore, ValidationError
from facetide.sources import JsonlSource


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.evidence_path = root / "observations.jsonl"
        self.store_path = root / "facetide.sqlite3"

    def write_rows(self, rows):
        with self.evidence_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def item(self, ref, **overrides):
        row = {
            "source_type": "mr-memory",
            "source_ref": ref,
            "occurred_at": "2026-10-15",
            "known_at": "2026-11-05T10:00:00+00:00",
            "domain_ids": ["health", "leisure"],
            "evidence_kind": "user_statement",
            "resolution_status": "active",
            "change": "new",
            "summary": "User reported more rest",
        }
        row.update(overrides)
        return row

    def store(self):
        return LifeStore(self.store_path, source=JsonlSource(self.evidence_path))

    def test_cross_domain_and_dual_time(self):
        self.write_rows([self.item("event-1")])
        context = self.store().prepare_review("2026-10-01", "2026-10-31")
        self.assertEqual(len(context["evidence"]), 1)
        self.assertEqual(context["change_candidates"]["new"][0]["domain_ids"],
                         ["health", "leisure"])
        review = self.store().save_review(
            period_start="2026-10-01", period_end="2026-10-31",
            domain_scores={"health": 3}, user_confirmed=True,
            evidence_refs=[{"source_type": "mr-memory", "source_ref": "event-1"}],
        )
        self.assertEqual(review["evidence_refs"][0]["known_at"], "2026-11-05T10:00:00+00:00")
        self.assertNotIn("summary", review["evidence_refs"][0])

    def test_revocation_replaces_prior_source_version(self):
        self.write_rows([
            self.item("event-1"),
            self.item("event-1", resolution_status="retracted", change=None),
        ])
        context = self.store().prepare_review("2026-10-01", "2026-10-31")
        self.assertEqual(len(context["evidence"]), 1)
        self.assertEqual(context["change_candidates"]["new"], [])
        with self.assertRaises(ValidationError):
            self.store().save_review(
                period_start="2026-10-01", period_end="2026-10-31",
                domain_scores={"health": 4}, user_confirmed=True,
                evidence_refs=[{"source_type": "mr-memory", "source_ref": "event-1"}],
            )

    def test_invalid_rows_are_warned_and_dont_poison_data(self):
        self.write_rows([{"bad": "record"}, self.item("valid")])
        result = self.store().prepare_review("2026-10-01", "2026-10-31")
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(len(result["evidence"]), 1)

    def test_source_missing_is_not_decline(self):
        store = self.store()
        result = store.prepare_review("2026-10-01", "2026-10-31")
        self.assertEqual(result["evidence"], [])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["change_candidates"]["receding"], [])

    def test_outside_period_and_fabricated_ref_rejected(self):
        self.write_rows([self.item("old", occurred_at="2026-08-20")])
        store = self.store()
        self.assertEqual(store.prepare_review("2026-10-01", "2026-10-31")["evidence"], [])
        with self.assertRaises(ValidationError):
            store.save_review(
                period_start="2026-10-01", period_end="2026-10-31",
                domain_scores={"health": 3}, user_confirmed=True,
                evidence_refs=[{"source_type": "mr-memory", "source_ref": "old"}],
            )


if __name__ == "__main__":
    unittest.main()
