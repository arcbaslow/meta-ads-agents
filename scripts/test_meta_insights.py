import unittest
from datetime import date, timedelta

import meta_insights


class TestDateRange(unittest.TestCase):
    def test_default_30_days(self):
        start, end = meta_insights.compute_date_range(days=30)
        self.assertEqual((date.today() - timedelta(days=30)).isoformat(), start)
        self.assertEqual(date.today().isoformat(), end)

    def test_custom_days(self):
        start, end = meta_insights.compute_date_range(days=7)
        self.assertEqual((date.today() - timedelta(days=7)).isoformat(), start)


class TestMetricAggregation(unittest.TestCase):
    def test_aggregate_daily_metrics(self):
        daily_data = [
            {"date_start": "2026-03-01", "spend": "50.00", "impressions": "1000", "clicks": "50"},
            {"date_start": "2026-03-02", "spend": "60.00", "impressions": "1200", "clicks": "48"},
        ]
        result = meta_insights.aggregate_metrics(daily_data)
        self.assertAlmostEqual(result["total_spend"], 110.0)
        self.assertEqual(result["total_impressions"], 2200)
        self.assertEqual(result["total_clicks"], 98)
        self.assertAlmostEqual(result["avg_ctr"], 98 / 2200 * 100, places=2)


class TestInsightsFields(unittest.TestCase):
    def test_metrics_include_entity_names(self):
        for field in ["campaign_name", "adset_name", "ad_name", "adset_id", "campaign_id", "ad_id"]:
            self.assertIn(field, meta_insights.METRICS,
                          f"{field} missing from METRICS — agents need entity names in insights rows")


class TestAttributionParams(unittest.TestCase):
    def test_build_attribution_params(self):
        params = meta_insights.build_attribution_params(days=30, level="campaign")
        self.assertIn("action_attribution_windows", params)
        self.assertEqual(params["action_attribution_windows"], ["1d_click", "7d_click", "1d_view"])
        self.assertEqual(params["action_breakdowns"], ["action_type"])
        self.assertEqual(params["level"], "campaign")


if __name__ == "__main__":
    unittest.main()
