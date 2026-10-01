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

class TestCSVExport(unittest.TestCase):
    def test_csv_creates_campaign_file(self):
        tmpdir = tempfile.mkdtemp()
        files = meta_report.generate_csv(SAMPLE_DATA, tmpdir)
        self.assertIn("campaigns", files)
        self.assertTrue(os.path.exists(files["campaigns"]))

    def test_csv_campaign_file_has_headers(self):
        tmpdir = tempfile.mkdtemp()
        meta_report.generate_csv(SAMPLE_DATA, tmpdir)
        with open(os.path.join(tmpdir, "campaigns.csv")) as f:
            header = f.readline()
        self.assertIn("name", header)
        self.assertIn("spend", header)

    def test_csv_creates_creatives_and_placements(self):
        tmpdir = tempfile.mkdtemp()
        files = meta_report.generate_csv(SAMPLE_DATA, tmpdir)
        self.assertIn("creatives", files)
        self.assertIn("placements", files)

    def test_csv_empty_data(self):
        tmpdir = tempfile.mkdtemp()
        files = meta_report.generate_csv({"account_id": "act_123"}, tmpdir)
        self.assertEqual(files, {})


PREVIOUS_DATA = {
    "account_id": "act_123",
    "date_range": "2026-02-05 to 2026-03-07",
    "summary": {
        "spend": 2800.0,
        "purchases": 9000,
        "revenue": 350000.0,
        "roas": 125.0,
        "cpa": 0.31,
        "reach": 750000,
    },
    "campaigns": [
        {"name": "Campaign A", "spend": 900, "purchases": 4000, "revenue": 180000,
         "roas": 200.0, "cpa": 0.23, "ctr": 0.35, "cpm": 1.10},
        {"name": "Campaign C", "spend": 300, "purchases": 1000, "revenue": 40000,
         "roas": 133.0, "cpa": 0.30, "ctr": 0.40, "cpm": 1.00},
    ],
}


class TestComparison(unittest.TestCase):
    def test_comparison_has_metric_deltas(self):
        result = meta_report.generate_comparison(SAMPLE_DATA, PREVIOUS_DATA)
        self.assertIn("metrics", result)
        spend = result["metrics"]["spend"]
        self.assertAlmostEqual(spend["change"], 3104.23 - 2800.0, places=1)
        self.assertIn("change_pct", spend)

    def test_comparison_detects_new_campaign(self):
        result = meta_report.generate_comparison(SAMPLE_DATA, PREVIOUS_DATA)
        campaigns = {c["name"]: c for c in result["campaigns"]}
        self.assertEqual(campaigns["Campaign B"]["status"], "new")

    def test_comparison_detects_removed_campaign(self):
        result = meta_report.generate_comparison(SAMPLE_DATA, PREVIOUS_DATA)
        campaigns = {c["name"]: c for c in result["campaigns"]}
        self.assertEqual(campaigns["Campaign C"]["status"], "removed")

    def test_comparison_active_campaign(self):
        result = meta_report.generate_comparison(SAMPLE_DATA, PREVIOUS_DATA)
        campaigns = {c["name"]: c for c in result["campaigns"]}
        self.assertEqual(campaigns["Campaign A"]["status"], "active")

    def test_comparison_is_rendered_in_the_report(self):
        """--compare used to compute the comparison and then leave it out of
        the markdown, HTML and PDF it wrote."""
        data = dict(SAMPLE_DATA)
        data["comparison"] = meta_report.generate_comparison(SAMPLE_DATA, PREVIOUS_DATA)
        md = meta_report.generate_markdown(data)
        self.assertIn("## Period comparison", md)
        self.assertIn(PREVIOUS_DATA["date_range"], md)
        self.assertIn("| Spend | $3,104.23 | $2,800.00 | +10.9% |", md)
        self.assertIn("| Campaign B | new |", md)
        self.assertIn("| Campaign C | removed |", md)

    def test_new_campaign_has_no_percentage_change(self):
        data = dict(SAMPLE_DATA)
        data["comparison"] = meta_report.generate_comparison(SAMPLE_DATA, PREVIOUS_DATA)
        row = [line for line in meta_report.generate_markdown(data).splitlines()
               if line.startswith("| Campaign B |")][0]
        self.assertIn("n/a", row)

    def test_report_without_comparison_has_no_comparison_section(self):
        self.assertNotIn("Period comparison", meta_report.generate_markdown(SAMPLE_DATA))


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
