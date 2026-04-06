import unittest

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


if __name__ == "__main__":
    unittest.main()
