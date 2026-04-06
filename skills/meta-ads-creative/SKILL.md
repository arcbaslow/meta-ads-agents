---
name: meta-ads-creative
description: "Creative analysis with fatigue detection. Identifies winning patterns and recommends refreshes. Use when user says 'creative', 'fatigue', 'which ads work best', 'creative refresh'."
user-invokable: true
argument-hint: "<account-id> [--days N]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Creative Analysis

**Invocation:** `/meta-ads creative <account-id>` or "Which creatives are fatigued?"

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Spawn `meta-creative` agent with the account ID
3. Agent analyzes creative performance and fatigue signals
4. Present top/bottom performers, fatigue alerts, format insights
5. Offer report generation

## Default Parameters
- Date range: last 30 days for performance, last 14 days for fatigue detection
- Override with `--days N`
