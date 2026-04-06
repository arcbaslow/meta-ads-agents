import os
import tempfile
import unittest

import meta_report


class TestHTMLGeneration(unittest.TestCase):
    def test_generate_html_structure(self):
        report_data = {
            "account_id": "act_123",
            "account_name": "Test Account",
            "date_range": "2026-03-07 to 2026-04-06",
            "sections": [
                {
                    "title": "Executive Summary",
                    "content": "Account is performing well.",
                    "priority_items": [
                        {"level": "critical", "text": "Creative fatigue on 3 ads"},
                        {"level": "high", "text": "Budget underutilization on Campaign X"},
                    ],
                },
                {
                    "title": "Performance Overview",
                    "content": "Total spend: $5,000. ROAS: 3.2x.",
                    "metrics": {"spend": 5000, "roas": 3.2, "cpa": 15.6},
                },
            ],
        }
        html = meta_report.generate_html(report_data)
        self.assertIn("Test Account", html)
        self.assertIn("Executive Summary", html)
        self.assertIn("Creative fatigue", html)
        self.assertIn("$5,000", html)

    def test_write_html_file(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "report.html")
        html = "<html><body>Test</body></html>"
        meta_report.write_file(path, html)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            self.assertIn("Test", f.read())


if __name__ == "__main__":
    unittest.main()
