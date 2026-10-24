import copy
import csv
import html
import os
import tempfile
import unittest
from unittest import mock

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
        "period_reach": 869953,
        "rows": 2,
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

    def test_summary_uses_period_reach_without_row_counts(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        self.assertIn("| Period reach | 869,953 |", md)
        self.assertNotIn("| Rows |", md)

    def test_missing_reach_is_explained_without_a_zero(self):
        data = copy.deepcopy(SAMPLE_DATA)
        del data["summary"]["period_reach"]
        note = "Reach is not additive across entities or days; account-level period reach was not fetched."
        data["summary"]["reach_note"] = note
        md = meta_report.generate_markdown(data)
        self.assertNotIn("| Period reach |", md)
        self.assertIn(note, meta_report.generate_html(md, data))


class TestPDFGeneration(unittest.TestCase):
    def test_pdf_consumes_escaped_html(self):
        payload = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        with tempfile.TemporaryDirectory() as tmpdir, \
                mock.patch("fpdf.FPDF.write_html", autospec=True) as write_html:
            meta_report.generate_pdf("# " + payload, os.path.join(tmpdir, "test.pdf"))
        rendered = write_html.call_args.args[1]
        self.assertIn(html.escape(payload, quote=True), rendered)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<img", rendered)

    def test_generate_pdf_creates_file(self):
        md = meta_report.generate_markdown(SAMPLE_DATA)
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "test.pdf")
        meta_report.generate_pdf(md, path)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 100)

class TestHTMLGeneration(unittest.TestCase):
    def test_account_and_campaign_names_are_escaped(self):
        payload = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        data = copy.deepcopy(SAMPLE_DATA)
        data["account_name"] = payload
        data["campaigns"][0]["name"] = payload
        rendered = meta_report.generate_html(meta_report.generate_markdown(data), data)
        escaped = html.escape(payload, quote=True)
        self.assertIn(f"<td>{escaped}</td>", rendered)
        self.assertIn(f"{escaped}</title>", rendered)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<img", rendered)

    def test_all_text_nodes_are_escaped_and_bold_still_works(self):
        payload = '<img src=x onerror="alert(1)"> & text'
        escaped = html.escape(payload, quote=True)
        md = "\n".join([f"# {payload}", f"## {payload}", f"### {payload}",
                        f"**{payload}**", f"- {payload}", payload,
                        f"| {payload} |", "| --- |", f"| {payload} |"])
        rendered = meta_report.generate_html(md)
        for tag in ("h1", "h2", "h3", "strong", "li", "p", "th", "td"):
            self.assertIn(f"<{tag}>{escaped}</{tag}>", rendered)
        self.assertNotIn("<img", rendered)

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
    def test_formula_prefixes_are_neutralized_in_every_string_cell(self):
        for prefix in ("=", "+", "-", "@", "\t", "\r"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as tmpdir:
                data = copy.deepcopy(SAMPLE_DATA)
                for section in ("campaigns", "creatives", "placements"):
                    for row in data[section]:
                        for key in row:
                            row[key] = prefix + "1+1"
                        row["spend"] = -12.5
                files = meta_report.generate_csv(data, tmpdir)
                for path in files.values():
                    with open(path, newline="", encoding="utf-8") as f:
                        for row in csv.DictReader(f):
                            self.assertEqual(row.pop("spend"), "-12.5")
                            self.assertTrue(all(value == "'" + prefix + "1+1" for value in row.values()))

    def test_safe_strings_and_empty_strings_are_preserved(self):
        data = {"creatives": [{"name": "Ordinary name", "format": "", "fatigue": "ok"}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = meta_report.generate_csv(data, tmpdir)["creatives"]
            with open(path, newline="", encoding="utf-8") as f:
                row = next(csv.DictReader(f))
        self.assertEqual(row["name"], "Ordinary name")
        self.assertEqual(row["format"], "")
        self.assertEqual(row["fatigue"], "ok")

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
        "period_reach": 750000,
    },
    "campaigns": [
        {"name": "Campaign A", "spend": 900, "purchases": 4000, "revenue": 180000,
         "roas": 200.0, "cpa": 0.23, "ctr": 0.35, "cpm": 1.10},
        {"name": "Campaign C", "spend": 300, "purchases": 1000, "revenue": 40000,
         "roas": 133.0, "cpa": 0.30, "ctr": 0.40, "cpm": 1.00},
    ],
}


class TestComparison(unittest.TestCase):
    def test_legacy_reach_is_explained_in_summary_and_comparison(self):
        legacy = copy.deepcopy(SAMPLE_DATA)
        del legacy["summary"]["period_reach"]
        legacy["summary"]["reach"] = 654321
        note = "Older summed reach is not shown because reach is not additive."
        md = meta_report.generate_markdown(legacy)
        self.assertEqual(md.count(note), 1)
        self.assertNotIn("| Period reach |", md)
        self.assertNotIn("654,321", md)
        self.assertIn(note, meta_report.generate_html(md, legacy))
        for current, previous in ((SAMPLE_DATA, legacy), (legacy, SAMPLE_DATA), (legacy, legacy)):
            with self.subTest(current=current, previous=previous):
                comparison = meta_report.generate_comparison(current, previous)
                self.assertEqual(comparison["reach_note"], note)
                self.assertNotIn("period_reach", comparison["metrics"])
                self.assertNotIn("reach", comparison["metrics"])
                rendered = "\n".join(meta_report.comparison_markdown(comparison))
                self.assertIn(note, rendered)
                self.assertNotIn("| Period reach |", rendered)

    def test_comparison_uses_period_reach(self):
        comparison = meta_report.generate_comparison(SAMPLE_DATA, PREVIOUS_DATA)
        self.assertEqual(comparison["metrics"]["period_reach"]["change"], 119953)
        self.assertIn("| Period reach | 869,953 | 750,000 | +16.0% |",
                      "\n".join(meta_report.comparison_markdown(comparison)))

    def test_comparison_omits_unavailable_reach(self):
        previous = copy.deepcopy(PREVIOUS_DATA)
        del previous["summary"]["period_reach"]
        previous["summary"]["reach_note"] = "Period reach was not fetched."
        for current, prior in ((SAMPLE_DATA, previous), (previous, SAMPLE_DATA)):
            with self.subTest(current=current, previous=prior):
                comparison = meta_report.generate_comparison(current, prior)
                self.assertEqual(
                    comparison["reach_note"],
                    "Period reach is not compared because it was not fetched for one of the periods.",
                )
                self.assertNotIn("period_reach", comparison["metrics"])
                self.assertNotIn("reach", comparison["metrics"])
                rendered = "\n".join(meta_report.comparison_markdown(comparison))
                self.assertEqual(rendered.count(comparison["reach_note"]), 1)
                self.assertNotIn("| Period reach |", rendered)

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
