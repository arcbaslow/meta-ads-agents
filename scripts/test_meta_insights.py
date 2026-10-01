import contextlib
import io
import json
import sys
import unittest
from datetime import date, timedelta
from unittest import mock

import meta_campaigns
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

    def test_aggregate_empty_list(self):
        result = meta_insights.aggregate_metrics([])
        self.assertEqual(result["total_spend"], 0)
        self.assertEqual(result["total_impressions"], 0)
        self.assertEqual(result["total_clicks"], 0)
        self.assertEqual(result["avg_ctr"], 0)
        self.assertEqual(result["avg_cpc"], 0)
        self.assertEqual(result["avg_cpm"], 0)
        self.assertEqual(result["days"], 0)

    def test_aggregate_all_zeros(self):
        daily_data = [{"spend": "0", "impressions": "0", "clicks": "0"}]
        result = meta_insights.aggregate_metrics(daily_data)
        self.assertEqual(result["avg_ctr"], 0)
        self.assertEqual(result["avg_cpc"], 0)
        self.assertEqual(result["avg_cpm"], 0)

    def test_aggregate_missing_fields(self):
        """Fields missing from rows should default to 0, not crash."""
        daily_data = [{"date_start": "2026-03-01"}]
        result = meta_insights.aggregate_metrics(daily_data)
        self.assertEqual(result["total_spend"], 0)
        self.assertEqual(result["total_impressions"], 0)


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


class TestCacheKeys(unittest.TestCase):
    def test_daily_query_has_its_own_key(self):
        plain = meta_insights.cache_key_for("campaign", 30)
        daily = meta_insights.cache_key_for("campaign", 30, daily=True)
        self.assertNotEqual(plain, daily)

    def test_attribution_query_has_its_own_key(self):
        plain = meta_insights.cache_key_for("campaign", 30)
        attribution = meta_insights.cache_key_for("campaign", 30, attribution=True)
        self.assertNotEqual(plain, attribution)

    def test_breakdown_and_daily_combine(self):
        keys = {
            meta_insights.cache_key_for("ad", 14, breakdown="age"),
            meta_insights.cache_key_for("ad", 14, breakdown="age", daily=True),
            meta_insights.cache_key_for("ad", 14, daily=True),
        }
        self.assertEqual(len(keys), 3)


class TestMainDoesNotServeTheWrongCache(unittest.TestCase):
    """A cached summary query used to be returned for --daily and --attribution."""

    def _run(self, argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["meta_insights.py"] + argv),                 mock.patch.object(meta_insights.meta_auth, "load_credentials",
                                  return_value={"access_token": "placeholder"}),                 mock.patch.object(meta_insights, "fetch_insights",
                                  return_value=[{"date_start": "2026-09-01", "spend": "1"}]),                 contextlib.redirect_stdout(out):
            meta_insights.main()
        return json.loads(out.getvalue())

    def test_daily_after_summary_fetches_daily_rows(self):
        meta_campaigns.write_cache("act_1", meta_insights.cache_key_for("campaign", 30),
                                   {"status": "ok", "summary": {"total_spend": 99}, "data": []})
        result = self._run(["--account", "act_1", "--daily"])
        self.assertNotIn("summary", result)
        self.assertEqual(result["total_rows"], 1)

    def test_summary_after_daily_is_not_the_daily_rows(self):
        self._run(["--account", "act_1", "--daily"])
        result = self._run(["--account", "act_1"])
        self.assertIn("summary", result)


if __name__ == "__main__":
    unittest.main()
