"""Domain and persistence regression tests; runnable with stdlib unittest."""
import tempfile
import unittest
from pathlib import Path

from facetide.core import DOMAINS, GoalConflict, LifeStore, ValidationError


class LifeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "facetide.sqlite3"
        self.store = LifeStore(self.db_path)

    def goal(self, **overrides):
        data = {
            "title": "Recover a sustainable sleep routine",
            "enough_condition": "I feel adequately rested most mornings",
            "domain_ids": ["health", "leisure"],
            "user_confirmed": True,
        }
        data.update(overrides)
        return self.store.upsert_goal(**data)

    def test_empty_snapshot_and_seven_domains(self):
        snapshot = self.store.get_snapshot()
        self.assertEqual(len(snapshot["domains"]), 7)
        self.assertEqual({d["domain_id"] for d in snapshot["domains"]}, set(DOMAINS))
        self.assertTrue(all(d["score"] is None for d in snapshot["domains"]))
        self.assertEqual(snapshot["goals"], [])

    def test_goal_requires_confirmation(self):
        with self.assertRaises(ValidationError):
            self.goal(user_confirmed=False)
        self.assertEqual(self.store.get_snapshot()["goals"], [])

    def test_goal_domains_and_optimistic_version(self):
        created = self.goal(domain_ids=["leisure", "health", "health"])
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["domain_ids"], ["health", "leisure"])
        changed = self.goal(
            goal_id=created["goal_id"], expected_version=1,
            status="maintaining", enough_condition="Now sufficiently rested",
        )
        self.assertEqual(changed["version"], 2)
        self.assertEqual(changed["status"], "maintaining")
        with self.assertRaises(GoalConflict):
            self.goal(goal_id=created["goal_id"], expected_version=1)
        reopened = LifeStore(self.db_path)
        self.assertEqual(reopened.get_snapshot()["goals"][0]["version"], 2)

    def test_goal_validation(self):
        with self.assertRaises(ValidationError):
            self.goal(domain_ids=["unknown"])
        with self.assertRaises(ValidationError):
            self.goal(status="always_improve")
        with self.assertRaises(ValidationError):
            self.goal(indicators={"happiness": 99})
        with self.assertRaises(ValidationError):
            self.goal(indicators={"outcome": "not an array"})
        with self.assertRaises(ValidationError):
            self.goal(indicators={"driver": [""]})
        saved = self.goal(indicators={"outcome": ["rested most mornings"], "guardrail": ["work must remain sustainable"]})
        self.assertEqual(saved["indicators"]["outcome"], ["rested most mornings"])

    def test_review_is_user_rated_and_immutable(self):
        goal = self.goal()
        with self.assertRaises(ValidationError):
            self.store.save_review(period_start="2026-10-01", period_end="2026-10-31",
                                   domain_scores={"health": 3}, user_confirmed=False)
        review = self.store.save_review(
            period_start="2026-10-01", period_end="2026-10-31",
            domain_scores={"health": 3, "leisure": 2}, user_confirmed=True,
            personal_growth="Learned to set boundaries", change_band={"stable": ["Work routine"]},
        )
        self.assertEqual(review["goals_snapshot"][0]["version"], goal["version"])
        self.assertEqual(self.store.get_snapshot()["latest_review"]["review_id"], review["review_id"])
        self.goal(goal_id=goal["goal_id"], expected_version=1, status="reflecting")
        self.assertEqual(self.store.get_history()["reviews"][0]["goals_snapshot"][0]["status"], "building")
        self.assertEqual(len(self.store.get_history(domain_id="health")["reviews"]), 1)
        self.assertEqual(len(self.store.get_history(domain_id="finance")["reviews"]), 0)

    def test_score_validation_and_partial_scores(self):
        for bad in (True, 0, 6, 3.5, "4"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.store.save_review(period_start="2026-10-01", period_end="2026-10-31",
                                       domain_scores={"health": bad}, user_confirmed=True)
        review = self.store.save_review(period_start="2026-10-01", period_end="2026-10-31",
                                        domain_scores={"health": 4}, user_confirmed=True)
        self.assertNotIn("finance", review["domain_scores"])
        self.assertIsNone(next(d for d in self.store.get_snapshot()["domains"]
                               if d["domain_id"] == "finance")["score"])

    def test_previous_review_and_revision(self):
        first = self.store.save_review(period_start="2026-09-01", period_end="2026-09-30",
                                       domain_scores={"career": 2}, user_confirmed=True)
        previous = self.store.prepare_review("2026-10-01", "2026-10-31")["previous_review"]
        self.assertEqual(previous["review_id"], first["review_id"])
        correction = self.store.save_review(
            period_start="2026-09-01", period_end="2026-09-30",
            domain_scores={"career": 3}, revision_of=first["review_id"],
            user_confirmed=True,
        )
        self.assertEqual(correction["revision_of"], first["review_id"])
        self.assertEqual(self.store.get_history()["total"], 2)
        with self.assertRaises(ValidationError):
            self.store.save_review(period_start="2026-10-01", period_end="2026-10-31",
                                   domain_scores={"career": 3},
                                   revision_of=first["review_id"], user_confirmed=True)

    def test_invalid_dates_and_empty_review(self):
        with self.assertRaises(ValidationError):
            self.store.prepare_review("2026-10-31", "2026-10-01")
        with self.assertRaises(ValidationError):
            self.store.prepare_review("2026-02-30", "2026-03-01")
        with self.assertRaises(ValidationError):
            self.store.save_review(period_start="2026-10-01", period_end="2026-10-31",
                                   domain_scores={}, user_confirmed=True)
        with self.assertRaises(ValidationError):
            self.store.get_history(limit=0)


if __name__ == "__main__":
    unittest.main()
