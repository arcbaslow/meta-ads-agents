# meta-ads-agents

[![tests](https://github.com/arcbaslow/meta-ads-agents/actions/workflows/tests.yml/badge.svg)](https://github.com/arcbaslow/meta-ads-agents/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![version](https://img.shields.io/badge/version-1.0.1-blue.svg)](CHANGELOG.md)

A multi-agent toolkit for Meta (Facebook / Instagram) Ads. Talks to the
Meta Marketing API for campaign, ad set, ad, creative, audience, and
Pixel/CAPI event data, then runs specialist agents over the result —
one for performance, one for creative fatigue, one for audiences, one
for event health, one for budget pacing.

Designed to work with agentic runtimes side by side:

- **Claude Code** — full skill and subagent integration via `skills/` and `agents/`
- **Codex / other AGENTS.md runtimes** — driven by `AGENTS.md` and the universal Python CLI

The Python adapters under `scripts/` are the source of truth and work
the same everywhere. Read-only by default.

## What it does

- **Campaign performance**: spend, ROAS, CPA, CTR, frequency and
  impression trends across campaign, ad set, and ad level.
- **Creative fatigue**: scores each creative on frequency, CTR decay,
  and recency so you know which ads are burning budget on an audience
  that has already seen them.
- **Audience breakdowns**: performance split by age, gender, placement,
  device, and country.
- **Event health**: Pixel and Conversions API event coverage,
  deduplication signals, and conversion-funnel mapping.
- **Budget pacing**: underspend, budget saturation, and bid-strategy
  problems.
- **Full audit**: one command that fans the specialist agents out in
  parallel and merges the findings into a single report.
- **Reports**: markdown, HTML, or PDF export.

## Requirements

- Python 3.10 or newer
- A Meta App with `ads_read` and `ads_management` permissions
- Access to the ad accounts you want to analyze

The full app-setup walkthrough is in [docs/SETUP.md](docs/SETUP.md).

## Install

From inside the project directory.

### Recommended: `uv`

```
uv venv
uv pip install -r scripts/requirements.txt
uv run python scripts/meta_auth.py --check
```

[`uv`](https://github.com/astral-sh/uv) is a single-binary Python installer
and runner. One install of `uv` replaces the venv + pip dance and is
faster on cold-start.

### Optional extras

- `pip install -e ".[dev]"` — adds pytest + ruff for contributors.

### Plain venv (works everywhere)

```
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r scripts/requirements.txt
```

## Authenticate

Two paths. OAuth is the default; a manually pasted long-lived token is
the fallback for environments where the browser callback can't reach
`localhost:8477`.

```
# OAuth: opens a browser, captures the callback, exchanges for a
# long-lived (60-day) token
python scripts/meta_auth.py --oauth --app-id <id> --app-secret <secret>

# Manual: paste a token you already have
python scripts/meta_auth.py --configure --app-id <id> --app-secret <secret> --access-token <token>
```

Then verify and list what you can reach:

```
python scripts/meta_auth.py --check
python scripts/meta_auth.py --accounts
```

Credentials are written to `~/.claude/meta-ads-credentials.json`
(mode `0600` on POSIX). Requested scopes: `ads_read`, `ads_management`,
`read_insights`, `business_management`.

## Use it

### Claude Code

After authentication, slash commands work directly:

```
/meta-ads audit act_123456789
/meta-ads performance act_123456789
/meta-ads creative act_123456789
```

The full list lives in `skills/meta-ads/SKILL.md`.

### Plain Python

Every feature is exposed as a Python CLI under `scripts/`. The runtimes
above are conveniences — anything they can do, you can do manually.

```
python scripts/meta_insights.py --account act_123456789 --days 30
python scripts/meta_insights.py --account act_123456789 --level adset --breakdown age
python scripts/meta_creatives.py --account act_123456789 --with-metrics
python scripts/meta_events.py --account act_123456789 --health-check
```

Every adapter prints JSON to stdout. Pass `--no-cache` to bypass the
15-minute response cache.

## Commands

```
/meta-ads audit <account-id>         full audit, agents in parallel
/meta-ads performance <account-id>   spend, ROAS, CPA, CTR trends
/meta-ads creative <account-id>      creative fatigue detection
/meta-ads audience <account-id>      demographic and placement breakdown
/meta-ads events <account-id>        Pixel / CAPI health check
/meta-ads budget <account-id>        utilization and scaling opportunities
/meta-ads report <account-id>        PDF / HTML export
/meta-ads accounts                   list accessible ad accounts
/meta-ads auth                       set up or re-check authentication
```

Default lookback is 30 days for everything except `events`, which uses
7. Override with `--days N`.

## Account ID format

Meta ad account IDs are prefixed with `act_`. The scripts accept either
form:

- `123456789`      → normalised to `act_123456789`
- `act_123456789`  → used as-is

## How it works

The toolkit has three layers.

1. **Python adapters** (`scripts/`) call the Marketing API, cache
   responses, and return structured JSON. One module per domain:
   `meta_auth`, `meta_campaigns`, `meta_insights`, `meta_creatives`,
   `meta_audiences`, `meta_events`, `meta_report`.
2. **Agents** (`agents/`) are markdown specialist definitions the
   runtime spawns as subagents. Each reads the relevant adapter output
   and produces analysis for its domain.
3. **Skills** (`skills/`) provide the `/meta-ads ...` routing surface
   and, for audits, fan out to all agents in parallel and merge the
   results.

## Caching and rate limits

Adapter responses are cached as JSON under the OS temp directory
(`claude-meta-ads/`) with a 15-minute TTL, keyed by account and query.
Repeated analysis inside that window costs no API quota.

Retryable Meta error codes (17, 4, 32, 80001, 80003–80006 — all rate
limit families) plus transient connection errors are retried with
exponential backoff. Non-retryable errors surface immediately rather
than being swallowed.

Rate-limit tiers and the backoff strategy are documented in
`skills/meta-ads/references/meta-api-limits.md`.

## Project structure

```
meta-ads-agents/
  .claude-plugin/        plugin manifest and marketplace config
  agents/                7 specialist agent definitions
  docs/                  setup guide
  hooks/                 pre/post-tool guards
  scripts/               Python adapters and tests (the universal CLI)
  skills/
    meta-ads/            top-level router skill + reference docs
    meta-ads-audit/      parallel audit orchestrator
    meta-ads-performance/
    meta-ads-creative/
    meta-ads-audience/
    meta-ads-events/
    meta-ads-budget/
    meta-ads-report/
  AGENTS.md              instructions for AGENTS.md-standard runtimes
  CLAUDE.md              Claude Code instructions
```

## Benchmarks

`skills/meta-ads/references/benchmarks.md` ships industry-average CTR,
CPA, and ROAS by vertical. `campaign-objectives.md` maps ODAX
objectives to their valid optimization events — useful for catching
campaigns optimizing for the wrong thing.

## Tests

```
pytest scripts/ -q
```

Every adapter is mocked. The suite never hits the Meta API and needs no
credentials. CI runs it on Python 3.10 / 3.11 / 3.12 / 3.13.

## Status

v1.0.0 — all read paths shipped and unit-tested. No write paths yet;
when they land they will follow the same confirm-before-mutate pattern
as [google-ads-agents](https://github.com/arcbaslow/google-ads-agents).

Meta versions the Marketing API roughly twice a year. Auth endpoints
currently target `v21.0`. Field and edge names are verified against the
official docs on each bump, not from memory.

## License

MIT. See [LICENSE](LICENSE).

## Related

Part of a set of marketing-measurement agent toolkits:

- [google-ads-agents](https://github.com/arcbaslow/google-ads-agents)
- [google-analytics-agent](https://github.com/arcbaslow/google-analytics-agent)
- [google-search-console-agent](https://github.com/arcbaslow/google-search-console-agent)
- [gtm-diff](https://github.com/arcbaslow/gtm-diff)
- [figma-taxonomy-gen](https://github.com/arcbaslow/figma-taxonomy-gen)

Built and maintained by [Good Labs](https://goodlabs.kz).
