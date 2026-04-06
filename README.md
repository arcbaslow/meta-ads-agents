# claude-meta-ads

A Claude Code plugin that pulls data from the Meta Marketing API and analyzes your Facebook/Instagram ad accounts. It uses multiple specialist agents — one for campaign metrics, one for creative fatigue, one for audiences, etc. — and can run them in parallel for a full account audit.

## What it does

- Fetches campaign, ad set, and ad data with local JSON caching (15-min TTL)
- Scores creative fatigue based on frequency, CTR trends, and recency
- Breaks down audience performance by age, gender, placement, device, country
- Checks Pixel and CAPI event health, maps conversion funnels
- Flags underspending, budget saturation, and bid strategy issues
- Generates HTML or PDF reports

## Setup

You need a Meta App with `ads_read` and `ads_management` permissions. The full walkthrough is in [docs/SETUP.md](docs/SETUP.md).

Install Python dependencies in a venv:

```bash
cd claude-meta-ads
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

Then authenticate:

```
/meta-ads auth
```

This stores credentials in `~/.claude/meta-ads-credentials.json`.

## Usage

```
/meta-ads audit act_123456789       # full audit, all agents in parallel
/meta-ads performance act_123456789 # spend, ROAS, CPA, CTR trends
/meta-ads creative act_123456789    # creative fatigue detection
/meta-ads audience act_123456789    # targeting and demographic breakdown
/meta-ads events act_123456789      # pixel/CAPI health check
/meta-ads budget act_123456789      # utilization and scaling opportunities
/meta-ads report act_123456789      # PDF/HTML export
/meta-ads accounts                  # list accessible ad accounts
```

## How it works

The plugin has three layers:

1. **Python scripts** (`scripts/`) talk to the Meta API, cache responses, and return structured JSON. Each script handles one domain: auth, campaigns, insights, creatives, audiences, events, reporting.

2. **Agents** (`agents/`) are specialist markdown definitions that Claude Code spawns as subagents. Each one reads the relevant script output and produces analysis for its domain.

3. **Skills** (`skills/`) route user commands to the right agent or, for audits, fan out to all agents in parallel and merge the results.

## Project structure

```
claude-meta-ads/
  .claude-plugin/       # plugin manifest and marketplace config
  agents/               # 7 specialist agent definitions
  docs/                 # setup guide
  scripts/              # Python scripts + tests
  skills/
    meta-ads/           # main routing skill + reference docs
    meta-ads-audit/     # parallel audit orchestrator
    meta-ads-*/         # individual analysis skills
```

## Running tests

```bash
source .venv/bin/activate
cd scripts
python3 -m pytest -v
```

All tests use mocked API responses, no Meta credentials needed.

## License

MIT
