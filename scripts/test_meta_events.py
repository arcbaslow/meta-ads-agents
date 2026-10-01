import contextlib
import io
import json
import sys
import unittest
from unittest import mock

import meta_events


class TestEventClassification(unittest.TestCase):
    def test_standard_event(self):
        self.assertEqual(meta_events.classify_event("Purchase"), "standard")
        self.assertEqual(meta_events.classify_event("Lead"), "standard")
        self.assertEqual(meta_events.classify_event("AddToCart"), "standard")

    def test_custom_event(self):
        self.assertEqual(meta_events.classify_event("my_custom_signup"), "custom")

    def test_pageview(self):
        self.assertEqual(meta_events.classify_event("PageView"), "standard")


class TestFunnelBuilder(unittest.TestCase):
    def test_build_funnel(self):
        events = {
            "PageView": 10000,
            "ViewContent": 5000,
            "AddToCart": 1000,
            "InitiateCheckout": 500,
            "Purchase": 100,
        }
        funnel = meta_events.build_funnel(events)
        self.assertEqual(len(funnel), 5)
        self.assertEqual(funnel[0]["event"], "PageView")
        self.assertEqual(funnel[0]["count"], 10000)
        self.assertAlmostEqual(funnel[1]["drop_off_pct"], 50.0)
        self.assertAlmostEqual(funnel[4]["conversion_rate"], 1.0)


class TestCAPIDetection(unittest.TestCase):
    def test_detect_capi_from_server_events(self):
        pixel_data = {"id": "123", "name": "Test"}
        server_events = [
            {"event_name": "Purchase", "source": "server"},
            {"event_name": "ViewContent", "source": "server"},
        ]
        result = meta_events.detect_capi_status(pixel_data, server_events)
        self.assertTrue(result["has_capi"])
        self.assertEqual(result["server_events"], ["Purchase", "ViewContent"])

    def test_no_capi_without_server_events(self):
        pixel_data = {"id": "123", "name": "Test"}
        result = meta_events.detect_capi_status(pixel_data, [])
        self.assertFalse(result["has_capi"])
        self.assertEqual(result["server_events"], [])


class TestWebsiteEventsFromInsights(unittest.TestCase):
    """Insights names actions offsite_conversion.fb_pixel_purchase, not
    Purchase, so every event was classed custom and the funnel had no order."""

    ACTIONS = [
        {"action_type": "link_click", "value": "900"},
        {"action_type": "post_engagement", "value": "1200"},
        {"action_type": "landing_page_view", "value": "700"},
        {"action_type": "omni_purchase", "value": "12"},
        {"action_type": "offsite_conversion.fb_pixel_view_content", "value": "400"},
        {"action_type": "offsite_conversion.fb_pixel_add_to_cart", "value": "80"},
        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "12"},
        {"action_type": "offsite_conversion.fb_pixel_custom", "value": "5"},
        {"action_type": "offsite_conversion.custom.1234567890", "value": "3"},
    ]

    def _fetch(self):
        class Account:
            def __init__(self, *args, **kwargs):
                pass

            def get_insights(self, fields=None, params=None):
                return [{
                    "actions": TestWebsiteEventsFromInsights.ACTIONS,
                    "action_values": [
                        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "480.5"},
                        {"action_type": "omni_purchase", "value": "480.5"},
                    ],
                }]

        with mock.patch("facebook_business.adobjects.adaccount.AdAccount", Account), \
                mock.patch("facebook_business.api.FacebookAdsApi.init", return_value=None):
            return meta_events.fetch_pixel_events("act_1", "unused")

    def test_pixel_actions_are_renamed_to_standard_events(self):
        counts, values = self._fetch()
        self.assertEqual(counts["ViewContent"], 400)
        self.assertEqual(counts["AddToCart"], 80)
        self.assertEqual(counts["Purchase"], 12)
        self.assertEqual(values, {"Purchase": 480.5})
        self.assertEqual(meta_events.classify_event("Purchase"), "standard")

    def test_engagement_actions_are_not_reported_as_pixel_events(self):
        counts, _ = self._fetch()
        for name in ("link_click", "post_engagement", "landing_page_view", "omni_purchase"):
            self.assertNotIn(name, counts)

    def test_custom_events_and_custom_conversions_are_kept(self):
        counts, _ = self._fetch()
        self.assertEqual(counts["offsite_conversion.fb_pixel_custom"], 5)
        self.assertEqual(counts["offsite_conversion.custom.1234567890"], 3)
        self.assertEqual(
            meta_events.classify_event("offsite_conversion.custom.1234567890"), "custom")

    def test_funnel_is_ordered_on_real_action_names(self):
        counts, _ = self._fetch()
        steps = [s["event"] for s in meta_events.build_funnel(counts)][:3]
        self.assertEqual(steps, ["ViewContent", "AddToCart", "Purchase"])


class _FakePixel:
    """Answers the stats edge the way the API does: hourly rows of
    {"value": event, "count": n}, filtered by the event_source param."""

    def __init__(self, web, server):
        self.rows = {"WEB_ONLY": web, "SERVER_ONLY": server}
        self.requested = []

    def get_stats(self, params=None):
        self.requested.append(params["event_source"])
        return self.rows[params["event_source"]]


def _hour(**counts):
    return {"aggregation": "event", "start_time": "2026-09-28T10:00:00+0000",
            "data": [{"value": name, "count": n} for name, n in counts.items()]}


class TestPixelHealth(unittest.TestCase):
    def test_server_events_are_detected_from_the_event_source_filter(self):
        """Stats rows have no source key; has_capi used to be False for everyone."""
        pixel = _FakePixel(
            web=[_hour(PageView=100, Purchase=4), _hour(PageView=50)],
            server=[_hour(Purchase=5)],
        )
        result = meta_events.pixel_health({"id": "1", "name": "Main"}, pixel)
        self.assertTrue(result["has_capi"])
        self.assertEqual(result["server_events"], ["Purchase"])
        self.assertEqual(result["event_sources"]["Purchase"], {"browser": 4, "server": 5})
        self.assertEqual(result["event_sources"]["PageView"], {"browser": 150, "server": 0})
        self.assertEqual(pixel.requested, ["WEB_ONLY", "SERVER_ONLY"])

    def test_browser_only_pixel_has_no_capi(self):
        pixel = _FakePixel(web=[_hour(PageView=10)], server=[])
        result = meta_events.pixel_health({"id": "1"}, pixel)
        self.assertFalse(result["has_capi"])
        self.assertEqual(result["server_events"], [])

    def test_failed_stats_call_reports_unknown_not_missing(self):
        class Broken:
            def get_stats(self, params=None):
                raise RuntimeError("no permission")

        result = meta_events.pixel_health({"id": "1"}, Broken())
        self.assertIsNone(result["has_capi"])
        self.assertIn("no permission", result["capi_check_error"])

    def test_failed_stats_call_does_not_put_the_token_in_the_output(self):
        """The result is printed and cached, and a network error quotes the URL."""
        class Unreachable:
            def get_stats(self, params=None):
                raise OSError("Max retries exceeded with url: "
                              "/v26.0/1/stats?access_token=PLACEHOLDER-TOKEN&aggregation=event")

        with self.assertLogs("meta_ads", level="WARNING") as logs:
            result = meta_events.pixel_health({"id": "1"}, Unreachable())
        self.assertNotIn("PLACEHOLDER-TOKEN", json.dumps(result) + " ".join(logs.output))
        self.assertIn("access_token=REDACTED", result["capi_check_error"])

    def test_sum_event_counts_adds_hourly_rows(self):
        totals = meta_events.sum_event_counts([_hour(Lead=2), _hour(Lead=3, PageView=1)])
        self.assertEqual(totals, {"Lead": 5, "PageView": 1})


class TestHealthCheckUsesTheCache(unittest.TestCase):
    """--health-check used to call the API on every run."""

    def _run(self, fetch, argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["meta_events.py"] + argv),                 mock.patch.object(meta_events.meta_auth, "load_credentials",
                                  return_value={"access_token": "placeholder"}),                 mock.patch.object(meta_events, "fetch_pixel_health", fetch),                 contextlib.redirect_stdout(out):
            meta_events.main()
        return json.loads(out.getvalue())

    def test_second_run_is_served_from_cache(self):
        fetch = mock.Mock(return_value=[{"id": "1", "has_capi": True}])
        argv = ["--account", "act_1", "--health-check"]
        first = self._run(fetch, argv)
        second = self._run(fetch, argv)
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 1)

    def test_no_cache_forces_a_fetch(self):
        fetch = mock.Mock(return_value=[])
        argv = ["--account", "act_1", "--health-check"]
        self._run(fetch, argv)
        self._run(fetch, argv + ["--no-cache"])
        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
