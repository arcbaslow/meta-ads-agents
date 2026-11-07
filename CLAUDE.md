# CLAUDE.md

Notes for Claude Code working in `meta-ads-agents`.

## Status

Shipped: v1.1.0 (test count in docs/VERIFICATION.md). **Maintenance mode** - bugfixes, Meta API version
bumps, and doc fixes only.

## Working rules

- Meta Marketing API versions twice a year. Verify field and edge names
  against current official docs before touching request code - not from
  memory.
- Respect the local JSON cache (15-min TTL). Don't add calls that bypass it.
- Read paths only by default. Any future write path follows the same
  confirm-before-mutate pattern as google-ads-agents: show the operation
  JSON, ask y/N, then send.
- Tokens via env only. Never in code, fixtures, logs, or test data.
- Tests use fixtures, not live API calls.

## Style

- Commits: short imperative sentence. No conventional-commits prefixes,
  no Co-Authored-By / generated-with trailers, no emoji.
- Plain factual writing. No marketing copy.
