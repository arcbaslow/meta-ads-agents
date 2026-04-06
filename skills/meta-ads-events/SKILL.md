---
name: meta-ads-events
description: "Pixel and CAPI event analysis. Checks tracking health, event configuration, and conversion funnel. Use when user says 'pixel', 'CAPI', 'events', 'tracking', 'funnel', 'conversions'."
user-invokable: true
argument-hint: "<account-id> [--days N]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Event & Tracking Analysis

**Invocation:** `/meta-ads events <account-id>` or "Is my pixel working?"

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Spawn `meta-events` agent with the account ID
3. Agent checks pixel health, CAPI coverage, and funnel integrity
4. Present tracking status with issues and fixes

## Default Parameters
- Date range: last 7 days (recent data most relevant for tracking health)
- Override with `--days N`
