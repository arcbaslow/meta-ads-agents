---
name: meta-ads-performance
description: "Campaign performance analysis. Spend, ROAS, CPA, CTR trends with anomaly detection. Use when user says 'how are my campaigns doing', 'performance', 'metrics', 'ROAS', 'CPA'."
user-invokable: true
argument-hint: "<account-id> [--days N]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Performance Analysis

**Invocation:** `/meta-ads performance <account-id>` or natural language like "How are my campaigns doing?"

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Spawn `meta-performance` agent with the account ID
3. Agent fetches insights and analyzes trends
4. Present findings with prioritized recommendations
5. Offer report: "Generate a PDF report? Use `/meta-ads report <account-id>`"

## Default Parameters
- Date range: last 30 days
- Level: campaign (with drill-down to ad set and ad)
- Override with `--days N`

Load `references/benchmarks.md` for industry context.
