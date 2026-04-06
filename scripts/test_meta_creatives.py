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


if __name__ == "__main__":
    unittest.main()
