---
name: meta-ads-audience
description: "Audience and targeting analysis. Evaluates audience effectiveness, overlap, demographics, and expansion opportunities. Use when user says 'audience', 'targeting', 'demographics', 'overlap'."
user-invokable: true
argument-hint: "<account-id> [--days N]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Audience Analysis

**Invocation:** `/meta-ads audience <account-id>` or "Which audiences convert best?"

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Spawn `meta-audience` agent with the account ID
3. Agent analyzes targeting, demographics, placements, and overlap
4. Present audience insights with optimization recommendations
5. Offer report generation
