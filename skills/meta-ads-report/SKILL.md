---
name: meta-ads-report
description: "Generate PDF or HTML reports from Meta Ads analysis. Use when user says 'report', 'PDF', 'export', 'client report'."
user-invokable: true
argument-hint: "<account-id> [--html] [--days N] [--compare]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Report Generation

**Invocation:** `/meta-ads report <account-id>`

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Collect data from all analysis scripts (or use cached data from recent audit)
3. Spawn relevant agents to generate analysis sections
4. Compile report data into JSON structure
5. Generate report: `python scripts/meta_report.py --input <data.json> --format both`
   This produces both .md and .pdf files. Use `--format md` for markdown only or `--format pdf` for PDF only.

## Report Sections

1. Executive Summary — key metrics, top recommendations
2. Performance Overview — spend, ROAS, CPA, CTR trends with charts
3. Campaign Breakdown — all campaigns with metrics table
4. Creative Analysis — top/bottom performers, fatigue alerts
5. Audience Insights — best audiences, overlap, demographics
6. Event & Tracking Health — pixel status, CAPI, funnel
7. Budget Efficiency — utilization, reallocation recommendations
8. Prioritized Action Plan — Critical > High > Medium > Low

## Options

- `--html`: Generate HTML instead of PDF
- `--days N`: Custom date range (default: 30)
- `--compare`: Include period-over-period comparison (current vs previous period)

## Output

Report saved to current directory as `meta-ads-report-<account-id>-<date>.pdf` (or `.html`).
