---
name: meta-ads-budget
description: "Budget and bid optimization analysis. Evaluates utilization, allocation, bid strategies, and scaling opportunities. Use when user says 'budget', 'scaling', 'bid strategy', 'spend', 'underspending'."
user-invokable: true
argument-hint: "<account-id> [--days N]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Budget Analysis

**Invocation:** `/meta-ads budget <account-id>` or "Should I increase my budget?"

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Spawn `meta-budget` agent with the account ID
3. Agent analyzes budget utilization, allocation, and scaling readiness
4. Present recommendations for budget optimization
