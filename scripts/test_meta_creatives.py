import unittest

import meta_creatives


class TestCreativeFormatDetection(unittest.TestCase):
    def test_detect_video_from_effective_spec(self):
        creative = {"effective_object_story_spec": {"video_data": {"video_id": "123"}}}
        self.assertEqual(meta_creatives.detect_format(creative), "video")

    def test_detect_image_from_effective_spec(self):
        creative = {"effective_object_story_spec": {"photo_data": {"image_hash": "abc"}}}
        self.assertEqual(meta_creatives.detect_format(creative), "image")

    def test_detect_carousel_from_effective_spec(self):
        creative = {"effective_object_story_spec": {"link_data": {"child_attachments": [{}]}}}
        self.assertEqual(meta_creatives.detect_format(creative), "carousel")

    def test_detect_video_from_object_type(self):
        creative = {"object_type": "VIDEO"}
        self.assertEqual(meta_creatives.detect_format(creative), "video")

    def test_detect_image_from_legacy_fields(self):
        creative = {"image_url": "https://example.com/img.jpg"}
        self.assertEqual(meta_creatives.detect_format(creative), "image")

    def test_detect_video_from_legacy_fields(self):
        creative = {"video_id": "12345"}
        self.assertEqual(meta_creatives.detect_format(creative), "video")

    def test_detect_video_from_object_story_spec(self):
        creative = {"object_story_spec": {"video_data": {"video_id": "123"}}}
        self.assertEqual(meta_creatives.detect_format(creative), "video")

    def test_detect_image_from_object_story_spec(self):
        creative = {"object_story_spec": {"photo_data": {"image_hash": "abc"}}}
        self.assertEqual(meta_creatives.detect_format(creative), "image")

    def test_carousel_wins_over_a_cover_image(self):
        """A carousel creative can also carry an image_url for its first card."""
        creative = {
            "image_url": "https://example.com/card1.jpg",
            "object_story_spec": {"link_data": {"child_attachments": [{}, {}]}},
        }
        self.assertEqual(meta_creatives.detect_format(creative), "carousel")

    def test_detect_image_from_image_hash(self):
        self.assertEqual(meta_creatives.detect_format({"image_hash": "abc"}), "image")

    def test_null_object_type_does_not_crash(self):
        self.assertEqual(meta_creatives.detect_format({"object_type": None}), "unknown")

    def test_detect_unknown(self):
        creative = {}
        self.assertEqual(meta_creatives.detect_format(creative), "unknown")


class TestFatigueScore(unittest.TestCase):
    def test_high_frequency_declining_ctr(self):
        # Frequency > 3 and CTR dropped by > 30%
        score = meta_creatives.fatigue_score(frequency=5.2, ctr_trend=-0.45)
        self.assertGreaterEqual(score, 0.7)

    def test_low_frequency_stable_ctr(self):
        score = meta_creatives.fatigue_score(frequency=1.2, ctr_trend=-0.05)
        self.assertLessEqual(score, 0.3)

    def test_fresh_creative_zero_inputs(self):
        """Brand new creative with no frequency and no CTR change should be 0."""
        score = meta_creatives.fatigue_score(frequency=0, ctr_trend=0)
        self.assertEqual(score, 0.0)

    def test_saturated_creative_maxes_at_one(self):
        """Extreme values should cap the score at 1.0, not exceed it."""
        score = meta_creatives.fatigue_score(frequency=100, ctr_trend=-1.0)
        self.assertLessEqual(score, 1.0)
        self.assertGreaterEqual(score, 0.9)

    def test_improving_ctr_no_fatigue_contribution(self):
        """Positive CTR trend (improving creative) should not add to fatigue."""
        score = meta_creatives.fatigue_score(frequency=1.0, ctr_trend=0.3)
        self.assertEqual(score, 0.0)

    def test_high_frequency_but_stable_ctr(self):
        """High frequency alone contributes 40% weight max."""
        score = meta_creatives.fatigue_score(frequency=7.0, ctr_trend=0)
        self.assertAlmostEqual(score, 0.4)  # freq component = 1.0, 1.0 * 0.4 = 0.4


if __name__ == "__main__":
    unittest.main()
