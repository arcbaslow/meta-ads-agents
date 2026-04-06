---
name: meta-ads-audit
description: "Full Meta Ads account audit with parallel agent delegation. Analyzes performance, creatives, audiences, events, budget, structure, and attribution. Use when user says 'audit', 'full analysis', 'analyze my account', 'account health check'."
user-invokable: true
argument-hint: "<account-id> [--days N]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Full Meta Ads Account Audit

## Process

1. **Verify auth**: `python scripts/meta_auth.py --check`
2. **Fetch account structure**: `python scripts/meta_campaigns.py --account <id> --fetch-all --json`
3. **Detect conversion optimization**: Check if any campaigns use OUTCOME_SALES, OUTCOME_LEADS, or OUTCOME_APP_PROMOTION objectives
4. **Delegate to agents in parallel**:

   ALWAYS (6 core agents):
   - `meta-performance` — campaign/ad set/ad metrics, trends, anomalies
   - `meta-creative` — creative performance, fatigue detection, format analysis
   - `meta-audience` — targeting effectiveness, overlap, demographics, placements
   - `meta-events` — pixel health, CAPI coverage, conversion funnel
   - `meta-budget` — budget utilization, allocation, bid strategies, scaling
   - `meta-account` — account structure, naming, hygiene, consolidation

   CONDITIONAL:
   - `meta-attribution` — attribution windows, click vs view, cross-campaign overlap (spawn when conversion-optimized campaigns detected in step 3)

5. **Collect results** from all agents
6. **Generate unified recommendations** prioritized: Critical > High > Medium > Low
7. **Offer report**: "Generate a PDF/HTML report? Use `/meta-ads report <account-id>`"

## Agent Dispatch

Spawn all core agents in parallel using the Agent tool. Each agent independently fetches the data it needs via Python scripts and returns its analysis.

```
# Parallel dispatch (all at once):
Agent: meta-performance — "Analyze campaign performance for account <id>"
Agent: meta-creative — "Analyze creative performance for account <id>"
Agent: meta-audience — "Analyze audience targeting for account <id>"
Agent: meta-events — "Analyze pixel and event tracking for account <id>"
Agent: meta-budget — "Analyze budget utilization for account <id>"
Agent: meta-account — "Analyze account structure for account <id>"

# Conditional (if conversion objectives detected):
Agent: meta-attribution — "Analyze attribution settings for account <id>"
```

## Default Parameters
- Date range: 30 days (events: 7 days)
- Override with `--days N`

## Output

### Unified Report Structure

1. **Executive Summary**
   - Account overview (total spend, campaigns, ads)
   - Top 3 critical issues
   - Top 3 quick wins

2. **Performance** (from meta-performance agent)
3. **Creative** (from meta-creative agent)
4. **Audience** (from meta-audience agent)
5. **Events & Tracking** (from meta-events agent)
6. **Budget** (from meta-budget agent)
7. **Account Structure** (from meta-account agent)
8. **Attribution** (from meta-attribution agent, if applicable)

9. **Prioritized Action Plan**
   - **Critical**: Issues causing money waste or tracking failures (fix immediately)
   - **High**: Significant optimization opportunities (fix within 1 week)
   - **Medium**: Improvements worth testing (fix within 1 month)
   - **Low**: Nice to have (backlog)

## Error Handling

| Scenario | Action |
|----------|--------|
| Auth token expired | Report error, guide user to re-authenticate |
| Rate limited (429) | Back off, report partial results from completed agents |
| No active campaigns | Report account status, skip performance/creative/budget agents |
| No pixel configured | Skip events agent, flag as Critical recommendation |
| Agent timeout | Report findings from completed agents, note incomplete sections |
