"""External MCP host projections: allowlist, provenance, revisions and revocation."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from facetide.core import LifeStore, ValidationError


class HostBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            "FACETIDE_BRIDGE_ALLOWED_SOURCES": "calendar,github",
            "FACETIDE_MRMEM_DIR": "",
            "FACETIDE_MRMEM_USER_ID": "",
            "FACETIDE_NUTRITION_MCP_URL": "",
            "FACETIDE_EVIDENCE_FILE": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.path = Path(self.temp.name) / "bridge.sqlite3"
        self.store = LifeStore(self.path)

    def event(self, **kwargs):
        row = {
            "provider": "calendar",
            "source_ref": "provider-event-id-1",
            "occurred_at": "2026-10-12",
            "known_at": "2026-10-12T10:30:00+00:00",
            "domain_ids": ["career", "social"],
            "summary": "A user-approved summary of an existing calendar event",
        }
        row.update(kwargs)
        return row

    def test_publish_from_other_mcp_into_common_seven_domain_pipeline(self):
        result = self.store.publish_source_bundle([self.event()])
        self.assertEqual(result["verification"], "host_attested_only")
        context = self.store.prepare_review("2026-10-01","2026-10-31")
        self.assertEqual(context["compilation"]["source_items"], 1)
        item = context["evidence"][0]
        self.assertEqual(item["source_type"],"bridge:calendar")
        self.assertEqual(item["evidence_kind"],"inference")
        self.assertEqual(item["known_at"],"2026-10-12T10:30:00+00:00")
        cards = {c["domain_id"]:c for c in context["domain_cards"]}
        self.assertEqual(cards["career"]["total_evidence"],1)
        self.assertEqual(cards["social"]["total_evidence"],1)
        self.assertEqual(cards["finance"]["total_evidence"],0)
        self.assertTrue(any("host" in x.lower() for x in context["warnings"]))
        self.assertTrue(all(x["score"] is None for x in self.store.get_snapshot()["domains"]))

    def test_revision_and_revocation_invalidate_projection(self):
        self.store.publish_source_bundle([self.event()])
        batch=self.store.get_compilation_batch("2026-10-01","2026-10-31")
        self.store.compile_batch(
            period_start="2026-10-01", period_end="2026-10-31",
            offset=0, limit=25, batch_fingerprint=batch["batch_fingerprint"],
            annotations=[{
                "source_type":"bridge:calendar", "source_ref":"provider-event-id-1",
                "domain_ids":["career"], "axis_ids":[], "change":"unknown",
                "observation":"User reviewed a professional meeting", "reason":"Calendar item",
                "confidence":"low",
            }],
        )
        self.assertEqual(self.store.prepare_review("2026-10-01","2026-10-31")["compilation"]["compiled_items"],1)
        self.store.publish_source_bundle([self.event(summary="The host source revision changed")])
        self.assertEqual(self.store.prepare_review("2026-10-01","2026-10-31")["compilation"]["stale"],1)
        self.store.publish_source_bundle([self.event(resolution_status="retracted")])
        context=self.store.prepare_review("2026-10-01","2026-10-31")
        self.assertEqual(context["compilation"]["active_items"],0)
        self.assertTrue(all(c["total_evidence"]==0 for c in context["domain_cards"]))

    def test_unapproved_provider_and_invalid_batch_fail_atomically(self):
        with self.assertRaises(ValidationError):
            self.store.publish_source_bundle([self.event(provider="bank")])
        with self.assertRaises(ValidationError):
            self.store.publish_source_bundle([self.event(),self.event(provider="bank")])
        self.assertEqual(self.store.prepare_review("2026-10-01","2026-10-31")["evidence"],[])

    def test_narrowing_allowlist_hides_other_providers(self):
        self.store.publish_source_bundle([
            self.event(provider="calendar"),
            self.event(provider="github", source_ref="issue-02"),
        ])
        with patch.dict(os.environ, {"FACETIDE_BRIDGE_ALLOWED_SOURCES": "github"}):
            narrowed = LifeStore(self.path)
            items = narrowed.prepare_review("2026-10-01", "2026-10-31")["evidence"]
            self.assertEqual([x["source_type"] for x in items], ["bridge:github"])

    def test_explicit_opt_in_required_even_for_existing_data(self):
        self.store.publish_source_bundle([self.event()])
        with patch.dict(os.environ, {"FACETIDE_BRIDGE_ALLOWED_SOURCES": ""}):
            other = LifeStore(self.path)
            self.assertEqual(other.prepare_review("2026-10-01","2026-10-31")["evidence"],[])
            with self.assertRaises(ValidationError):
                other.publish_source_bundle([self.event()])


if __name__=="__main__":
    unittest.main()
