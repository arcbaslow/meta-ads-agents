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


if __name__ == "__main__":
    unittest.main()
