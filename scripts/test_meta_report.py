import os
import tempfile
import unittest

import meta_report


SAMPLE_DATA = {
    "account_id": "act_123",
    "account_name": "Test Account",
    "date_range": "2026-03-07 to 2026-04-06",
    "summary": {
        "spend": 3104.23,
        "purchases": 11071,
        "revenue": 438338.0,
        "roas": 141.2,
        "cpa": 0.28,
        "reach": 869953,
    },
    "campaigns": [
        {"name": "Campaign A", "spend": 1069, "purchases": 5212, "revenue": 212835,
         "roas": 199.1, "cpa": 0.21, "ctr": 0.37, "cpm": 1.13},
        {"name": "Campaign B", "spend": 574, "purchases": 2000, "revenue": 73507,
         "roas": 128.0, "cpa": 0.29, "ctr": 0.59, "cpm": 1.14},
    ],
    "creatives": [
        {"name": "Ad 1", "format": "video", "spend": 165, "ctr": 5.97,
         "cpa": 0.027, "frequency": 1.29, "fatigue": "ok"},
        {"name": "Ad 2", "format": "image", "spend": 404, "ctr": 0.33,
         "cpa": 0.19, "frequency": 2.48, "fatigue": "monitor"},
    ],
    "placements": [
        {"name": "Instagram Feed", "spend": 1343, "purchases": 4602, "cpa": 0.292, "roas": 134},
        {"name": "Instagram Reels", "spend": 903, "purchases": 3395, "cpa": 0.266, "roas": 151},
    ],
    "age_breakdown": [
        {"age": "18-24", "spend": 258, "purchases": 1435, "cpa": 0.18, "roas": 242},
        {"age": "25-34", "spend": 1086, "purchases": 4024, "cpa": 0.27, "roas": 148},
    ],
    "gender_breakdown": [
        {"gender": "Male", "spend": 1653, "purchases": 6758, "cpa": 0.245, "roas": 158},
        {"gender": "Female", "spend": 1446, "purchases": 4283, "cpa": 0.338, "roas": 121},
    ],
    "tracking": {
        "pixel_status": "Active",
        "has_capi": False,
        "funnel_health": "Broken — purchases > add-to-carts",
    },
    "actions": [
        {"level": "critical", "text": "Implement CAPI"},
        {"level": "high", "text": "Scale top campaign"},
        {"level": "medium", "text": "Add CTA buttons"},
    ],
}


class TestMarkdownGeneration(unittest.TestCase):
    def test_generates_valid_markdown(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        self.assertIn("# Meta Ads Report", md)
        self.assertIn("Test Account", md)

    def test_contains_campaign_table(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        self.assertIn("Campaign A", md)
        self.assertIn("Campaign B", md)
        self.assertIn("|", md)

    def test_contains_creative_table(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        self.assertIn("Ad 1", md)
        self.assertIn("video", md)

    def test_contains_placement_table(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        self.assertIn("Instagram Feed", md)

    def test_contains_action_plan(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        self.assertIn("Implement CAPI", md)
        self.assertIn("CRITICAL", md.upper())

    def test_contains_tracking_section(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        self.assertIn("Active", md)


class TestPDFGeneration(unittest.TestCase):
    def test_generate_pdf_creates_file(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "test.pdf")
        meta_report.generate_pdf(md, path)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 100)

class TestHTMLGeneration(unittest.TestCase):
    def test_generate_html_contains_structure(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        html = meta_report.generate_html(md, SAMPLE_DATA)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<table>", html)
        self.assertIn("Test Account", html)

    def test_generate_html_contains_campaign_data(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        html = meta_report.generate_html(md, SAMPLE_DATA)
        self.assertIn("Campaign A", html)
        self.assertIn("Campaign B", html)

    def test_generate_html_contains_action_plan(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        html = meta_report.generate_html(md, SAMPLE_DATA)
        self.assertIn("Implement CAPI", html)

    def test_generate_html_has_dark_theme_styles(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        html = meta_report.generate_html(md, SAMPLE_DATA)
        self.assertIn("--bg:", html)
        self.assertIn("--accent:", html)

    def test_generate_html_writes_to_file(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        html = meta_report.generate_html(md, SAMPLE_DATA)
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "test.html")
        meta_report.write_file(path, html)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("<!DOCTYPE html>", content)


class TestFileWriting(unittest.TestCase):
    def test_write_markdown_file(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "report.md")
        meta_report.write_file(path, "# Test")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            self.assertIn("Test", f.read())


if __name__ == "__main__":
    unittest.main()
