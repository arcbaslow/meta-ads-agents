# High-Priority Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 6 issues discovered during the first real audit of the Halyk Bank SK account — missing entity names in insights, broken creative format detection, unreliable CAPI check, no click/view attribution split, wall-of-text report, and no rate-limit handling.

**Architecture:** All changes are in `scripts/`. Each task modifies one Python file plus its test file. No new files except `scripts/meta_pdf.py` for PDF generation. The report overhaul replaces the current HTML-only approach with markdown-first + optional PDF via fpdf2.

**Tech Stack:** Python 3.14, facebook-business SDK, fpdf2 (new dep for PDF), unittest, existing venv at `.venv/`

---

### Task 1: Add entity names to insights output

**Files:**
- Modify: `scripts/meta_insights.py:13-17` (METRICS list)
- Modify: `scripts/test_meta_insights.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `scripts/test_meta_insights.py`:

```python
class TestInsightsFields(unittest.TestCase):
    def test_metrics_include_entity_names(self):
        for field in ["campaign_name", "adset_name", "ad_name", "adset_id", "campaign_id", "ad_id"]:
            self.assertIn(field, meta_insights.METRICS,
                          f"{field} missing from METRICS — agents need entity names in insights rows")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/claude-meta-ads/scripts && source ../.venv/bin/activate && python3 -m pytest test_meta_insights.py::TestInsightsFields -v`
Expected: FAIL — `campaign_name` not in METRICS

- [ ] **Step 3: Add entity name fields to METRICS**

In `scripts/meta_insights.py`, replace the METRICS list:

```python
METRICS = [
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "spend", "impressions", "reach", "frequency", "clicks", "cpc", "cpm",
    "ctr", "actions", "action_values", "cost_per_action_type",
    "cost_per_unique_click", "unique_clicks", "unique_ctr",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_insights.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/claude-meta-ads && git add scripts/meta_insights.py scripts/test_meta_insights.py
git commit -m "feat: add campaign/adset/ad names to insights output"
```

---

### Task 2: Fix creative format detection

**Files:**
- Modify: `scripts/meta_creatives.py:12-23` (detect_format function)
- Modify: `scripts/meta_creatives.py:50-55` (fetch_creatives fields)
- Modify: `scripts/meta_creatives.py:83-84` (fetch ads with effective_object_story_spec)
- Modify: `scripts/test_meta_creatives.py` (update tests)

- [ ] **Step 1: Write failing tests for improved format detection**

Replace the format detection tests in `scripts/test_meta_creatives.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failures**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_creatives.py::TestCreativeFormatDetection -v`
Expected: FAIL on `test_detect_video_from_effective_spec`, `test_detect_image_from_effective_spec`, `test_detect_video_from_object_type`

- [ ] **Step 3: Rewrite detect_format to check effective_object_story_spec first**

In `scripts/meta_creatives.py`, replace `detect_format`:

```python
def detect_format(creative):
    """Detect creative format: image, video, carousel, or unknown.

    Checks effective_object_story_spec first (most reliable from ads endpoint),
    then object_type, then legacy creative fields as fallback.
    """
    # Check effective_object_story_spec (from ads endpoint)
    ess = creative.get("effective_object_story_spec", {})
    if ess.get("video_data"):
        return "video"
    if ess.get("photo_data"):
        return "image"
    link_data = ess.get("link_data", {})
    if link_data.get("child_attachments"):
        return "carousel"

    # Check object_type field
    obj_type = creative.get("object_type", "").upper()
    if obj_type == "VIDEO":
        return "video"
    if obj_type == "PHOTO":
        return "image"

    # Legacy creative fields fallback
    if creative.get("video_id"):
        return "video"
    if creative.get("image_url"):
        return "image"

    # Check object_story_spec (old path)
    oss = creative.get("object_story_spec", {})
    if oss.get("video_data"):
        return "video"
    if oss.get("link_data", {}).get("child_attachments"):
        return "carousel"

    return "unknown"
```

- [ ] **Step 4: Update fetch to request effective_object_story_spec on ads**

In `scripts/meta_creatives.py`, in `fetch_creatives_with_metrics`, update the ads fetch (around line 83-84):

Replace:
```python
    ads = list(account.get_ads(fields=["id", "creative"]))
```

With:
```python
    ads = list(account.get_ads(fields=["id", "creative", "effective_object_story_spec"]))
```

And update the join logic to pass effective_object_story_spec into the entry:

Replace the loop body (lines 93-114) with:

```python
    ad_ess = {}
    for ad in ads:
        ad_dict = meta_campaigns.to_plain(dict(ad))
        cid = ad_dict.get("creative", {}).get("id")
        if cid:
            ad_to_creative[ad_dict["id"]] = cid
        ess = ad_dict.get("effective_object_story_spec", {})
        if ess:
            ad_ess[ad_dict["id"]] = ess

    # Join insights with creatives
    result = []
    for insight in insights:
        ad_id = insight.get("ad_id")
        creative_id = ad_to_creative.get(ad_id)
        creative = creative_map.get(creative_id, {})
        # Merge effective_object_story_spec from ad into creative for format detection
        merged = {**creative}
        if ad_id in ad_ess:
            merged["effective_object_story_spec"] = ad_ess[ad_id]
        entry = {
            "ad_id": ad_id,
            "ad_name": insight.get("ad_name"),
            "creative_id": creative_id,
            "format": detect_format(merged),
            "title": creative.get("title"),
            "body": creative.get("body"),
            "image_url": creative.get("image_url"),
            "thumbnail_url": creative.get("thumbnail_url"),
            "call_to_action": creative.get("call_to_action_type"),
            "spend": float(insight.get("spend", 0)),
            "impressions": int(insight.get("impressions", 0)),
            "clicks": int(insight.get("clicks", 0)),
            "ctr": float(insight.get("ctr", 0)),
            "frequency": float(insight.get("frequency", 0)),
        }
        result.append(entry)
```

Note: Remove the old `ad_to_creative` population loop — it's now inside the new loop above.

- [ ] **Step 5: Run all tests**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_creatives.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd ~/claude-meta-ads && git add scripts/meta_creatives.py scripts/test_meta_creatives.py
git commit -m "fix: detect creative format from effective_object_story_spec"
```

---

### Task 3: Add attribution window breakdown to insights

**Files:**
- Modify: `scripts/meta_insights.py` (add --attribution flag and fetch logic)
- Modify: `scripts/test_meta_insights.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `scripts/test_meta_insights.py`:

```python
class TestAttributionParams(unittest.TestCase):
    def test_build_attribution_params(self):
        params = meta_insights.build_attribution_params(days=30, level="campaign")
        self.assertIn("action_attribution_windows", params)
        self.assertEqual(params["action_attribution_windows"], ["1d_click", "7d_click", "1d_view"])
        self.assertEqual(params["action_breakdowns"], ["action_type"])
        self.assertEqual(params["level"], "campaign")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_insights.py::TestAttributionParams -v`
Expected: FAIL — `build_attribution_params` not defined

- [ ] **Step 3: Add build_attribution_params and --attribution CLI flag**

In `scripts/meta_insights.py`, add after `extract_conversions`:

```python
def build_attribution_params(days=30, level="campaign"):
    """Build API params for attribution window breakdown."""
    start_date, end_date = compute_date_range(days)
    return {
        "time_range": {"since": start_date, "until": end_date},
        "level": level,
        "action_breakdowns": ["action_type"],
        "action_attribution_windows": ["1d_click", "7d_click", "1d_view"],
    }
```

In the `main()` function, add a new argument after the `--daily` line:

```python
    parser.add_argument("--attribution", action="store_true",
                        help="Break down conversions by attribution window (1d click, 7d click, 1d view)")
```

And add handling before the existing fetch, after `time_increment = ...`:

```python
    if args.attribution:
        cache_key = f"insights_{args.level}_{args.days}d_attribution"
        if not args.no_cache:
            cached = meta_campaigns.read_cache(args.account, cache_key)
            if cached:
                print(json.dumps(cached, indent=2))
                return

        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.adaccount import AdAccount
        api = FacebookAdsApi.init(access_token=token)
        account = AdAccount(account_id, api=api)

        params = build_attribution_params(args.days, args.level)
        fields = METRICS
        raw = list(account.get_insights(fields=fields, params=params))
        raw = [meta_campaigns.to_plain(dict(r)) for r in raw]

        result = {
            "status": "ok",
            "account_id": account_id,
            "days": args.days,
            "level": args.level,
            "attribution_windows": ["1d_click", "7d_click", "1d_view"],
            "total_rows": len(raw),
            "data": raw,
        }
        meta_campaigns.write_cache(account_id, cache_key, result)
        print(json.dumps(result, indent=2))
        return
```

- [ ] **Step 4: Run all tests**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_insights.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd ~/claude-meta-ads && git add scripts/meta_insights.py scripts/test_meta_insights.py
git commit -m "feat: add attribution window breakdown to insights"
```

---

### Task 4: Improve CAPI detection in events script

**Files:**
- Modify: `scripts/meta_events.py:103-122` (fetch_pixel_health)
- Modify: `scripts/test_meta_events.py` (add CAPI detection test)

- [ ] **Step 1: Write the failing test**

Add to `scripts/test_meta_events.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_events.py::TestCAPIDetection -v`
Expected: FAIL — `detect_capi_status` not defined

- [ ] **Step 3: Add detect_capi_status function**

In `scripts/meta_events.py`, add after `classify_event`:

```python
def detect_capi_status(pixel_data, server_events):
    """Determine CAPI status from pixel data and server event list.

    Args:
        pixel_data: dict with pixel id/name
        server_events: list of dicts with event_name and source fields

    Returns:
        dict with has_capi bool, server_events list, and pixel info
    """
    server_event_names = [
        e.get("event_name") for e in server_events
        if e.get("source") == "server"
    ]
    return {
        **pixel_data,
        "has_capi": len(server_event_names) > 0,
        "server_events": server_event_names,
    }
```

- [ ] **Step 4: Update fetch_pixel_health to try server event detection**

Replace `fetch_pixel_health` in `scripts/meta_events.py`:

```python
def fetch_pixel_health(account_id, access_token):
    """Check pixel configuration and health status, including CAPI detection."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    pixels = list(account.get_ads_pixels(fields=[
        "id", "name", "is_unavailable", "data_use_setting",
        "creation_time", "last_fired_time",
    ]))

    pixel_data = []
    for pixel in pixels:
        pixel_dict = meta_campaigns.to_plain(dict(pixel))

        # Try to detect CAPI by querying pixel stats for server events
        server_events = []
        try:
            from facebook_business.adobjects.adspixel import AdsPixel
            from datetime import date, timedelta
            px = AdsPixel(pixel_dict["id"], api=api)
            stats = list(px.get_stats(params={
                "aggregation": "event",
                "start_time": (date.today() - timedelta(days=3)).isoformat(),
                "end_time": date.today().isoformat(),
            }))
            for stat in stats:
                stat_dict = meta_campaigns.to_plain(dict(stat))
                for entry in stat_dict.get("data", []):
                    if entry.get("source") == "server" and entry.get("value", 0) > 0:
                        server_events.append({
                            "event_name": entry.get("event"),
                            "source": "server",
                        })
        except Exception:
            # pixel stats may require extra permissions or hit rate limits
            pass

        result = detect_capi_status(pixel_dict, server_events)
        pixel_data.append(result)

    return pixel_data
```

- [ ] **Step 5: Run all tests**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_events.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd ~/claude-meta-ads && git add scripts/meta_events.py scripts/test_meta_events.py
git commit -m "feat: detect CAPI status from pixel server events"
```

---

### Task 5: Report overhaul — markdown + PDF

**Files:**
- Modify: `scripts/meta_report.py` (rewrite to generate markdown, add PDF via fpdf2)
- Create: `scripts/test_meta_report_new.py` (new tests, then rename)
- Modify: `scripts/requirements.txt` (add fpdf2, remove weasyprint)

- [ ] **Step 1: Install fpdf2 and remove weasyprint from requirements**

In `scripts/requirements.txt`, replace `weasyprint>=60.0` with `fpdf2>=2.8.1`:

```
facebook-business>=19.0.0
fpdf2>=2.8.1
matplotlib>=3.8
```

Run:
```bash
cd ~/claude-meta-ads && source .venv/bin/activate && pip3 install fpdf2 && pip3 uninstall weasyprint -y 2>/dev/null; echo "done"
```

- [ ] **Step 2: Write failing tests for markdown generation**

Replace `scripts/test_meta_report.py` entirely:

```python
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
        self.assertIn("|", md)  # pipe tables

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_report.py -v`
Expected: FAIL — `generate_markdown` not defined

- [ ] **Step 4: Rewrite meta_report.py**

Replace `scripts/meta_report.py` entirely:

```python
#!/usr/bin/env python3
"""Generate markdown and PDF reports from Meta Ads analysis data."""

import argparse
import json
import os
import sys
from datetime import date


def fmt_money(v):
    """Format a number as $X,XXX.XX."""
    return f"${v:,.2f}"


def fmt_num(v):
    """Format a number with commas."""
    if isinstance(v, float):
        return f"{v:,.2f}"
    return f"{v:,}"


def fmt_pct(v):
    """Format a number as percentage."""
    return f"{v:.2f}%"


def md_table(headers, rows):
    """Build a markdown pipe table from headers and row dicts/lists."""
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        if isinstance(row, dict):
            cells = [str(row.get(h, "")) for h in headers]
        else:
            cells = [str(c) for c in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def generate_markdown(report_data):
    """Generate a markdown report from structured report data."""
    name = report_data.get("account_name", report_data.get("account_id", "Unknown"))
    date_range = report_data.get("date_range", "")
    s = report_data.get("summary", {})

    lines = []
    lines.append(f"# Meta Ads Report — {name}")
    lines.append(f"**{date_range}**\n")

    # Account summary
    lines.append("## Account summary\n")
    summary_rows = []
    if s:
        summary_rows.append(["Spend", fmt_money(s.get("spend", 0))])
        summary_rows.append(["Purchases", fmt_num(s.get("purchases", 0))])
        summary_rows.append(["Revenue", fmt_money(s.get("revenue", 0))])
        summary_rows.append(["ROAS", f"{s.get('roas', 0):.1f}x"])
        summary_rows.append(["CPA", fmt_money(s.get("cpa", 0))])
        summary_rows.append(["Reach", fmt_num(s.get("reach", 0))])
    lines.append(md_table(["Metric", "Value"], summary_rows))
    lines.append("")

    # Campaign performance
    campaigns = report_data.get("campaigns", [])
    if campaigns:
        lines.append("## Campaign performance\n")
        headers = ["Campaign", "Spend", "Purchases", "Revenue", "ROAS", "CPA", "CTR", "CPM"]
        rows = []
        for c in campaigns:
            rows.append([
                c.get("name", ""),
                fmt_money(c.get("spend", 0)),
                fmt_num(c.get("purchases", 0)),
                fmt_money(c.get("revenue", 0)),
                f"{c.get('roas', 0):.1f}x",
                fmt_money(c.get("cpa", 0)),
                fmt_pct(c.get("ctr", 0)),
                fmt_money(c.get("cpm", 0)),
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Creative performance
    creatives = report_data.get("creatives", [])
    if creatives:
        lines.append("## Creative performance\n")
        headers = ["Ad", "Format", "Spend", "CTR", "CPA", "Frequency", "Fatigue"]
        rows = []
        for c in creatives:
            rows.append([
                c.get("name", ""),
                c.get("format", ""),
                fmt_money(c.get("spend", 0)),
                fmt_pct(c.get("ctr", 0)),
                fmt_money(c.get("cpa", 0)),
                f"{c.get('frequency', 0):.2f}",
                c.get("fatigue", ""),
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Placement breakdown
    placements = report_data.get("placements", [])
    if placements:
        lines.append("## Placement breakdown\n")
        headers = ["Placement", "Spend", "Purchases", "CPA", "ROAS"]
        rows = []
        for p in placements:
            rows.append([
                p.get("name", ""),
                fmt_money(p.get("spend", 0)),
                fmt_num(p.get("purchases", 0)),
                fmt_money(p.get("cpa", 0)),
                f"{p.get('roas', 0):.0f}x",
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Age breakdown
    age_data = report_data.get("age_breakdown", [])
    if age_data:
        lines.append("## Age breakdown\n")
        headers = ["Age", "Spend", "Purchases", "CPA", "ROAS"]
        rows = []
        for a in age_data:
            rows.append([
                a.get("age", ""),
                fmt_money(a.get("spend", 0)),
                fmt_num(a.get("purchases", 0)),
                fmt_money(a.get("cpa", 0)),
                f"{a.get('roas', 0):.0f}x",
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Gender breakdown
    gender_data = report_data.get("gender_breakdown", [])
    if gender_data:
        lines.append("## Gender breakdown\n")
        headers = ["Gender", "Spend", "Purchases", "CPA", "ROAS"]
        rows = []
        for g in gender_data:
            rows.append([
                g.get("gender", ""),
                fmt_money(g.get("spend", 0)),
                fmt_num(g.get("purchases", 0)),
                fmt_money(g.get("cpa", 0)),
                f"{g.get('roas', 0):.0f}x",
            ])
        lines.append(md_table(headers, rows))
        lines.append("")

    # Tracking health
    tracking = report_data.get("tracking", {})
    if tracking:
        lines.append("## Tracking health\n")
        lines.append(f"- Pixel: {tracking.get('pixel_status', 'Unknown')}")
        lines.append(f"- CAPI: {'Active' if tracking.get('has_capi') else 'Not configured'}")
        lines.append(f"- Funnel: {tracking.get('funnel_health', 'Unknown')}")
        lines.append("")

    # Action plan
    actions = report_data.get("actions", [])
    if actions:
        lines.append("## Action plan\n")
        for level in ["critical", "high", "medium", "low"]:
            level_actions = [a for a in actions if a.get("level") == level]
            if level_actions:
                lines.append(f"### {level.upper()}\n")
                for a in level_actions:
                    lines.append(f"- {a['text']}")
                lines.append("")

    return "\n".join(lines)


def generate_pdf(markdown_text, output_path):
    """Convert markdown text to PDF using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    for line in markdown_text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("# ") and not stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, stripped[2:], new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("## "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(0, 8, stripped[3:], new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, stripped[4:], new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("**") and stripped.endswith("**"):
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, stripped.strip("*"), new_x="LMARGIN", new_y="NEXT")
        elif stripped.startswith("|") and "---" not in stripped:
            # Table row
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            pdf.set_font("Helvetica", "", 8)
            col_w = (pdf.w - 20) / max(len(cells), 1)
            for cell in cells:
                pdf.cell(col_w, 5, cell, border=1)
            pdf.ln()
        elif stripped.startswith("- "):
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(5)
            pdf.cell(0, 6, stripped, new_x="LMARGIN", new_y="NEXT")
        elif stripped:
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 6, stripped, new_x="LMARGIN", new_y="NEXT")

    pdf.output(output_path)


def write_file(path, content):
    """Write content to a file, creating directories if needed."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="Generate Meta Ads report")
    parser.add_argument("--input", required=True, help="Path to JSON report data file")
    parser.add_argument("--format", choices=["pdf", "md", "both"], default="both",
                        help="Output format (default: both)")
    parser.add_argument("--output", help="Output file path (auto-generated if not set)")
    parser.add_argument("--json", action="store_true", default=True)

    args = parser.parse_args()

    with open(args.input, "r") as f:
        report_data = json.load(f)

    md = generate_markdown(report_data)
    account_id = report_data.get("account_id", "unknown")
    today = date.today().isoformat()
    base = args.output or f"meta-ads-report-{account_id}-{today}"

    outputs = {}

    if args.format in ("md", "both"):
        md_path = f"{base}.md" if not base.endswith(".md") else base
        write_file(md_path, md)
        outputs["md"] = os.path.abspath(md_path)

    if args.format in ("pdf", "both"):
        pdf_path = f"{base}.pdf" if not base.endswith(".pdf") else base
        generate_pdf(md, pdf_path)
        outputs["pdf"] = os.path.abspath(pdf_path)

    result = {"status": "ok", "format": args.format, "outputs": outputs}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run all tests**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_report.py -v`
Expected: All tests PASS

- [ ] **Step 6: Update the report skill to use new format flags**

In `skills/meta-ads-report/SKILL.md`, update the process step 5:

Replace:
```
5. Generate report: `python scripts/meta_report.py --input <data.json> --format pdf`
```
With:
```
5. Generate report: `python scripts/meta_report.py --input <data.json> --format both`
   This produces both .md and .pdf files. Use `--format md` for markdown only or `--format pdf` for PDF only.
```

- [ ] **Step 7: Commit**

```bash
cd ~/claude-meta-ads && git add scripts/meta_report.py scripts/test_meta_report.py scripts/requirements.txt skills/meta-ads-report/SKILL.md
git commit -m "feat: rewrite report as markdown + PDF via fpdf2, drop weasyprint"
```

---

### Task 6: Add rate-limit retry wrapper

**Files:**
- Modify: `scripts/meta_campaigns.py` (add api_call_with_retry)
- Modify: `scripts/test_meta_campaigns.py` (add retry test)
- Modify: `scripts/meta_insights.py` (use retry wrapper)
- Modify: `scripts/meta_events.py` (use retry wrapper)
- Modify: `scripts/meta_creatives.py` (use retry wrapper)
- Modify: `scripts/meta_audiences.py` (use retry wrapper)

- [ ] **Step 1: Write the failing test**

Read the current test file first, then add to `scripts/test_meta_campaigns.py`:

```python
class TestRetryWrapper(unittest.TestCase):
    def test_succeeds_on_first_try(self):
        call_count = [0]
        def good_fn():
            call_count[0] += 1
            return "ok"
        result = meta_campaigns.api_call_with_retry(good_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 1)

    def test_retries_on_rate_limit(self):
        call_count = [0]
        def flaky_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("too many calls")
            return "ok"
        result = meta_campaigns.api_call_with_retry(flaky_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)

    def test_raises_after_max_retries(self):
        def always_fails():
            raise Exception("rate limited")
        with self.assertRaises(Exception):
            meta_campaigns.api_call_with_retry(always_fails, max_retries=2, base_delay=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_campaigns.py::TestRetryWrapper -v`
Expected: FAIL — `api_call_with_retry` not defined

- [ ] **Step 3: Add the retry wrapper to meta_campaigns.py**

In `scripts/meta_campaigns.py`, add after `to_plain`:

```python
def api_call_with_retry(fn, max_retries=3, base_delay=2):
    """Call fn() with exponential backoff on failure.

    Retries on any exception (typically Meta API rate limit error 80004).
    Delays: base_delay, base_delay*2, base_delay*4, ...
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            if delay > 0:
                time.sleep(delay)
```

- [ ] **Step 4: Run all tests**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest test_meta_campaigns.py -v`
Expected: All tests PASS

- [ ] **Step 5: Apply retry wrapper to fetch functions in other scripts**

In `scripts/meta_insights.py`, wrap the API call in `fetch_insights`:

Replace:
```python
    insights = list(account.get_insights(fields=METRICS, params=params))
```
With:
```python
    insights = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_insights(fields=METRICS, params=params))
    )
```

In `scripts/meta_creatives.py`, wrap in `fetch_creatives`:

Replace:
```python
    creatives = list(account.get_ad_creatives(fields=fields))
```
With:
```python
    creatives = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_ad_creatives(fields=fields))
    )
```

In `scripts/meta_events.py`, wrap in `fetch_pixel_events`:

Replace:
```python
    insights = list(account.get_insights(fields=fields, params=params))
```
With:
```python
    insights = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_insights(fields=fields, params=params))
    )
```

In `scripts/meta_audiences.py`, wrap in the audience fetch (find the `get_custom_audiences` call):

Replace:
```python
    audiences = list(account.get_custom_audiences(fields=fields))
```
With:
```python
    audiences = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_custom_audiences(fields=fields))
    )
```

- [ ] **Step 6: Run all tests across all scripts**

Run: `cd ~/claude-meta-ads/scripts && python3 -m pytest -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
cd ~/claude-meta-ads && git add scripts/meta_campaigns.py scripts/test_meta_campaigns.py scripts/meta_insights.py scripts/meta_creatives.py scripts/meta_events.py scripts/meta_audiences.py
git commit -m "feat: add rate-limit retry wrapper, apply to all API calls"
```
