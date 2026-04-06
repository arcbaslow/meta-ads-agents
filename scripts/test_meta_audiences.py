import unittest

import meta_audiences


class TestAudienceTypeDetection(unittest.TestCase):
    def test_lookalike(self):
        audience = {"subtype": "LOOKALIKE", "name": "LAL - Purchasers 1%"}
        self.assertEqual(meta_audiences.classify_audience(audience), "lookalike")

    def test_custom(self):
        audience = {"subtype": "CUSTOM", "name": "Website Visitors 30d"}
        self.assertEqual(meta_audiences.classify_audience(audience), "custom")

    def test_saved(self):
        audience = {"subtype": "SAVED", "name": "Interest: Fitness"}
        self.assertEqual(meta_audiences.classify_audience(audience), "saved")


class TestTargetingSummary(unittest.TestCase):
    def test_extract_interests(self):
        targeting = {
            "flexible_spec": [{"interests": [{"id": "1", "name": "Fitness"}, {"id": "2", "name": "Yoga"}]}],
            "age_min": 25,
            "age_max": 45,
            "genders": [1],
            "geo_locations": {"countries": ["US"]},
        }
        summary = meta_audiences.summarize_targeting(targeting)
        self.assertIn("Fitness", summary["interests"])
        self.assertEqual(summary["age_range"], "25-45")
        self.assertEqual(summary["countries"], ["US"])


if __name__ == "__main__":
    unittest.main()
