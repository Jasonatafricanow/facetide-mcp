"""Nutrition MCP bounded report contract: synthetic response, no live NAS."""
import unittest

from facetide.adapters import NutritionMcpSource


class FakeNutrition(NutritionMcpSource):
    def __init__(self, report):
        super().__init__("https://private.example/mcp", member_id="adult_a")
        self.report = report
        self.asked_days = []

    async def _report(self, days):
        self.asked_days.append(days)
        return self.report


class NutritionAdapterTests(unittest.TestCase):
    def data(self):
        return {
            "ok": True, "fromDate": "2026-10-07", "toDate": "2026-11-05",
            "nutrition": {
                "daysWithMeals": 22, "estimatedItems": 2, "meanKcalOnLoggedDays": 1920
            },
            "health": {"sleepDays": 18, "averageSleepHours": 7.2,
                       "stepsDays": 16, "averageSteps": 7023}
        }

    def test_bounded_report_records_are_source_grounded(self):
        source = FakeNutrition(self.data())
        rows, warnings = source.query("2026-10-07", "2026-11-05", frozenset({"health"}))
        self.assertEqual(warnings, [])
        self.assertEqual(source.asked_days, [30])
        self.assertEqual(len(rows), 2)
        self.assertEqual([x["source_type"] for x in rows], ["nutrition-mcp"] * 2)
        self.assertTrue(all(x["occurred_at"] == "2026-11-05" for x in rows))
        self.assertTrue(all(x["domain_ids"] == ["health"] for x in rows))
        self.assertTrue(all(x["change"] is None for x in rows))

    def test_wrong_partial_period_returns_warning_not_fabricated_data(self):
        source = FakeNutrition({
            **self.data(), "fromDate": "2026-10-30"
        })
        rows, warnings = source.query("2026-11-01", "2026-11-05", frozenset({"health"}))
        self.assertEqual(source.asked_days, [7])
        self.assertEqual(rows, [])
        self.assertIn("No partial-window", warnings[0])

    def test_long_range_is_not_implicitly_covered(self):
        source = FakeNutrition(self.data())
        rows, warnings = source.query("2026-01-01", "2026-11-05", frozenset({"health"}))
        self.assertEqual(rows, [])
        self.assertTrue(warnings)
        self.assertEqual(source.asked_days, [])

    def test_invalid_or_insecure_mcp_url_rejected(self):
        for url in ("http://private.example/mcp", "https://private.example/login",
                    "https://user:secret@private.example/mcp",
                    "https://private.example/mcp?token=abc"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                NutritionMcpSource(url)
        NutritionMcpSource("http://127.0.0.1:3457/mcp")


if __name__ == "__main__":
    unittest.main()
