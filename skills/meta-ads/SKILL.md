---
name: meta-ads
description: "Meta Ads analysis for Facebook and Instagram campaigns. Full account audits, campaign performance, creative fatigue detection, audience insights, Pixel/CAPI tracking health, budget optimization, attribution modeling, and PDF/HTML reporting. Multi-account support. Triggers on: meta ads, facebook ads, instagram ads, campaign analysis, ad performance, ROAS, creative fatigue, pixel, CAPI."
user-invokable: true
argument-hint: "[command] [account-id] [options]"
license: MIT
metadata:
  author: arcbaslow
  version: "1.0.0"
  category: meta-ads
---

# Meta Ads: Campaign Analysis Skill

**Invocation:** `/meta-ads $1 $2` where `$1` is the command and `$2` is the account ID or argument.

**Scripts:** Located at the plugin root `scripts/` directory.

Multi-agent Meta Ads analysis covering campaign performance, creative fatigue,
audience targeting, Pixel/CAPI events, budget optimization, and attribution modeling.
Supports multiple ad accounts.

## Quick Reference

| Command | What it does |
|---------|-------------|
| `/meta-ads audit <account-id>` | Full account audit with parallel agent delegation |
| `/meta-ads performance <account-id>` | Campaign performance analysis (spend, ROAS, CPA, CTR) |
| `/meta-ads creative <account-id>` | Creative analysis with fatigue detection |
| `/meta-ads audience <account-id>` | Audience targeting and demographic insights |
| `/meta-ads events <account-id>` | Pixel/CAPI health and conversion funnel |
| `/meta-ads budget <account-id>` | Budget utilization and scaling opportunities |
| `/meta-ads report <account-id>` | Generate PDF/HTML report |
| `/meta-ads auth` | Set up authentication (OAuth or manual token) |
| `/meta-ads accounts` | List accessible ad accounts |

## Command Routing

When the user invokes `/meta-ads`:

| Input | Route to |
|-------|----------|
| `audit <id>` | meta-ads-audit skill |
| `performance <id>` | meta-ads-performance skill |
| `creative <id>` | meta-ads-creative skill |
| `audience <id>` | meta-ads-audience skill |
| `events <id>` | meta-ads-events skill |
| `budget <id>` | meta-ads-budget skill |
| `report <id>` | meta-ads-report skill |
| `auth` | Run `python scripts/meta_auth.py --oauth` or `--configure` |
| `accounts` | Run `python scripts/meta_auth.py --accounts` |

## Natural Language Routing

For ad-hoc queries without explicit commands:
- "How are my campaigns doing?" → meta-ads-performance
- "Which creatives are fatigued?" → meta-ads-creative
- "Best performing audiences?" → meta-ads-audience
- "Is my pixel working?" → meta-ads-events
- "Should I increase my budget?" → meta-ads-budget
- "Run a full analysis" → meta-ads-audit

## Authentication

Before any analysis command, verify auth:
```bash
python scripts/meta_auth.py --check
```

If auth fails, guide user through setup:
1. `python scripts/meta_auth.py --oauth --app-id <id> --app-secret <secret>` (recommended)
2. `python scripts/meta_auth.py --configure --app-id <id> --app-secret <secret> --access-token <token>` (manual)

## Multi-Account

If user has multiple accounts configured, prompt which account to analyze.
Show: `python scripts/meta_auth.py --accounts`

## Reference Files

Load on-demand as needed (do NOT load all at startup):
- `references/meta-api-limits.md`: Rate limit tiers and backoff strategy
- `references/benchmarks.md`: Industry average CTR, CPA, ROAS by vertical
- `references/campaign-objectives.md`: ODAX objectives and optimization events

## Date Ranges

Default date ranges per analysis type:
- Performance, creative, audience, budget, account: **30 days**
- Events/tracking: **7 days**
- Override with `--days N` on any command

## After Analysis

After any analysis command completes, offer:
- "Generate a PDF report? Use `/meta-ads report <account-id>`"
- "Run a full audit? Use `/meta-ads audit <account-id>`"
