---
name: meta-ads-delivery
description: "Stalled delivery diagnosis. Finds ad sets that spend little or nothing and explains why: bid or cost cap below the account's real CPA, learning limited, budget too small for the optimisation event, or an issue Meta reports. Use when user says 'not spending', 'not delivering', 'stalled', 'learning limited', 'cost cap', 'bid cap', 'why did delivery stop'."
user-invokable: true
argument-hint: "<account-id> [--days N]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads Delivery Diagnosis

**Invocation:** `/meta-ads delivery <account-id>` or "Why is this ad set not spending?"

## Process

1. Verify auth: `python scripts/meta_auth.py --check`
2. Spawn `meta-delivery` agent with the account ID
3. Agent runs `python scripts/meta_delivery.py --account <id> --days 7 --json` and explains the findings
4. Present blocked and stalled ad sets first, then caps, learning status and budgets
5. List the checks that could not be evaluated, with the reason

## Default Parameters
- Date range: last 7 complete days, ending yesterday
- `--underspend-threshold 0.5`: flag spend below half of the daily budget
- `--learning-events 50`: optimisation events per week needed to leave the learning phase. Replaced per ad set by the threshold Meta returns in `learning_stage_info`, when it returns one.

## What it does not do

It reads settings and insights. It does not change a bid, a budget or a status. To act on a finding, use Ads Manager or Meta's own Ads MCP server.
