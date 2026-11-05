"""End-to-end 7+2 source aggregation and agent-compiled projections.

No real user records, private service, or model credentials are required.
"""
import tempfile
import unittest
from pathlib import Path

from facetide.core import DOMAINS, LifeStore, ValidationError
from facetide.compiler import AXES, CompilationError


class MutableEvidenceSource:
    def __init__(self, records):
        self.records = records

    def query(self, period_start, period_end, domains):
        return [
            dict(r) for r in self.records
            if period_start <= r["occurred_at"][:10] <= period_end
        ], []


def evidence(source_type, source_ref, date, **fields):
    return {
        "source_type": source_type, "source_ref": source_ref,
        "occurred_at": date, "known_at": "2026-11-05T10:00:00+00:00",
        "domain_ids": fields.get("domain_ids", []),
        "evidence_kind": fields.get("evidence_kind", "user_statement"),
        "resolution_status": fields.get("resolution_status", "active"),
        "change": None, "summary": fields.get("summary", source_ref),
    }


class CompilationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = MutableEvidenceSource([
            evidence("mrmem", "change-job", "2026-10-04", summary="Changed role"),
            evidence("memory", "income", "2026-10-12", summary="Changed savings goals"),
            evidence("nutrition-mcp", "monthly-health", "2026-10-20",
                     domain_ids=["health"], evidence_kind="fact", summary="Sleep records improved"),
            evidence("mrmem", "partner", "2026-10-22", summary="Discussed family cooperation"),
            evidence("mrmem", "friends", "2026-10-23", summary="Made a new friend"),
            evidence("memory", "leisure", "2026-10-24", summary="Enjoyed hiking"),
            evidence("mrmem", "housing", "2026-10-25", summary="Organized workspace"),
            evidence("memory", "unrelated", "2026-10-27", summary="Unrelated shopping ad"),
            evidence("memory", "old-event", "2026-10-30", resolution_status="retracted"),
        ])
        self.store = LifeStore(Path(self.temp.name) / "facetide.sqlite3", source=self.source)

    def first_batch(self, limit=20):
        return self.store.get_compilation_batch("2026-10-01", "2026-10-31", 0, limit)

    def mapping(self, batch):
        assignments = {
            "change-job": (["career", "finance"], ["personal_growth"], "new"),
            "income": (["finance"], [], "stable"),
            "monthly-health": (["health"], [], "stable"),
            "partner": (["family"], ["personal_growth"], "new"),
            "friends": (["social"], [], "new"),
            "leisure": (["leisure"], [], "new"),
            "housing": (["environment"], ["self_realization"], "new"),
            "unrelated": ([], [], "unknown"),
        }
        rows = []
        for r in batch["evidence"]:
            if r["resolution_status"] != "active":
                continue
            dims, axes, change = assignments[r["source_ref"]]
            rows.append({
                "source_type": r["source_type"], "source_ref": r["source_ref"],
                "domain_ids": dims, "axis_ids": axes, "change": change,
                "observation": "Source-backed: " + r["summary"] if dims else "",
                "reason": "Classifier read the scoped record",
                "confidence": "medium",
            })
        return rows

    def compile(self, batch, **kwargs):
        return self.store.compile_batch(
            period_start="2026-10-01", period_end="2026-10-31",
            offset=batch["offset"], limit=batch["limit"],
            batch_fingerprint=batch["batch_fingerprint"],
            annotations=self.mapping(batch), **kwargs,
        )

    def test_multi_source_seven_plus_two(self):
        batch = self.first_batch()
        self.assertEqual(batch["total"], 9)
        self.assertEqual(batch["evidence"][-1]["classification"], "invalid")
        self.compile(batch, axis_insights=[
            {
                "axis": "personal_growth",
                "summary": "The job change led to a revised view of meaningful work",
                "evidence_refs": [{"source_type": "mrmem", "source_ref": "change-job"},
                                  {"source_type": "memory", "source_ref": "income"}],
            },
            {
                "axis": "self_realization",
                "summary": "Reorganized the shared workspace",
                "evidence_refs": [{"source_type": "mrmem", "source_ref": "housing"}],
            },
        ])
        context = self.store.prepare_review("2026-10-01", "2026-10-31")
        self.assertEqual(context["compilation"]["active_items"], 8)
        self.assertEqual(context["compilation"]["compiled_items"], 8)
        self.assertEqual(context["compilation"]["pending"], 0)
        cards = {c["domain_id"]: c for c in context["domain_cards"]}
        self.assertEqual(set(cards), set(DOMAINS))
        self.assertTrue(all(c["evidence"] for c in cards.values()))
        self.assertEqual({e["source_ref"] for e in cards["career"]["evidence"]}, {"change-job"})
        self.assertIn("change-job", [e["source_ref"] for e in cards["finance"]["evidence"]])
        self.assertEqual(context["compilation"]["unclassified"], 1)
        self.assertIn("Source-backed", cards["career"]["evidence"][0]["summary"])
        self.assertEqual(set(context["axis_drafts"]), set(AXES))
        self.assertTrue(context["axis_drafts"]["personal_growth"]["insights"])
        self.assertTrue(context["axis_drafts"]["self_realization"]["insights"])
        self.assertTrue(all(d["score"] is None for d in self.store.get_snapshot()["domains"]))

    def test_page_process_and_restart_idempotent(self):
        first = self.first_batch(limit=4)
        self.assertEqual(first["next_offset"], 4)
        self.compile(first)
        self.assertEqual(self.store.prepare_review("2026-10-01","2026-10-31")["compilation"]["compiled_items"],4)
        second = self.store.get_compilation_batch("2026-10-01","2026-10-31",4,20)
        self.compile(second)
        self.compile(first)  # stable idempotent upsert
        self.assertEqual(self.store.prepare_review("2026-10-01","2026-10-31")["compilation"]["compiled_items"],8)
        reopened = LifeStore(self.store.path, source=self.source)
        self.assertEqual(reopened.prepare_review("2026-10-01","2026-10-31")["compilation"]["compiled_items"],8)

    def test_refuse_unanchored_or_stale_agent_projection(self):
        batch = self.first_batch()
        missing = self.mapping(batch)[:-1]
        with self.assertRaises(CompilationError):
            self.store.compile_batch(
                period_start="2026-10-01",period_end="2026-10-31",offset=0,limit=20,
                batch_fingerprint=batch["batch_fingerprint"],annotations=missing)
        with self.assertRaises(CompilationError):
            self.compile(batch, axis_insights=[{"axis": "personal_growth", "summary": "invented",
                "evidence_refs": [{"source_type": "mrmem", "source_ref": "not-real"}]}])
        changed = dict(self.source.records[0])
        changed["summary"] = "Changed semantic statement"
        self.source.records[0] = changed
        with self.assertRaises(CompilationError):
            self.compile(batch)
        self.assertEqual(self.store.prepare_review("2026-10-01","2026-10-31")["compilation"]["compiled_items"],0)

    def test_revision_invalidates_existing_projections(self):
        batch = self.first_batch()
        self.compile(batch)
        record = dict(self.source.records[0])
        record["summary"] = "Source memory revised"
        self.source.records[0] = record
        context = self.store.prepare_review("2026-10-01","2026-10-31")
        self.assertEqual(context["compilation"]["compiled_items"],7)
        self.assertEqual(context["compilation"]["stale"],1)
        self.assertEqual(context["compilation"]["pending"],1)
        self.assertFalse(any(e["classification"] == "agent_compiled"
                             for e in context["domain_cards"][0]["evidence"]))
        new_batch = self.first_batch()
        self.assertEqual(new_batch["evidence"][0]["classification"],"pending")

    def test_confirmed_review_uses_compiled_domains_without_automatic_rating(self):
        batch = self.first_batch()
        self.compile(batch)
        review=self.store.save_review(period_start="2026-10-01",period_end="2026-10-31",
                                      domain_scores={"career":2},user_confirmed=True,
                                      evidence_refs=[{"source_type":"mrmem","source_ref":"change-job"}])
        self.assertEqual(review["evidence_refs"][0]["domain_ids"],["career","finance"])
        self.assertEqual(review["evidence_refs"][0]["classification"],"agent_compiled")
        self.assertEqual(set(review["domain_scores"]),{"career"})
        with self.assertRaises(ValidationError):
            self.store.save_review(period_start="2026-10-01",period_end="2026-10-31",
                domain_scores={"career":3},user_confirmed=False)

    def test_bad_annotations_fail_and_leave_projection_empty(self):
        batch=self.first_batch()
        rows=self.mapping(batch)
        rows[0]["domain_ids"]=["alien"]
        with self.assertRaises(CompilationError):
            self.store.compile_batch(period_start="2026-10-01",period_end="2026-10-31",
                offset=0,limit=20,batch_fingerprint=batch["batch_fingerprint"],annotations=rows)
        self.assertEqual(self.store.prepare_review("2026-10-01","2026-10-31")["compilation"]["compiled_items"],0)


if __name__ == "__main__":
    unittest.main()
