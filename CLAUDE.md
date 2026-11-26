# CLAUDE.md

Notes for Claude Code working in `meta-ads-agents`.

## Status

Shipped: v1.1.0 (test count in docs/VERIFICATION.md). The read-only adapters are in maintenance
mode: bugfixes, Meta API version bumps, and doc fixes only. On 2026-11-26 the owner decided the
repo gets a write path: `scripts/meta_mcp.py`, used through an MCP host. See docs/WRITES.md.

## Working rules

- Meta Marketing API versions twice a year. Verify field and edge names
  against current official docs before touching request code - not from
  memory.
- Respect the local JSON cache (15-min TTL). Don't add calls that bypass it.
  The exception is `meta_mcp.py`: a plan and its apply must read live state.
- The CLI adapters only read. Writes go through `meta_mcp.py` only: a plan
  sends `validate_only` requests and returns a diff and a single-use token;
  the one write a plan makes is uploading new media to the account's media
  library, after the host's `gate(profile)` allows it. Only `apply_changes`
  with that token, after the gate, sends the change once. Every create is
  PAUSED and nothing is activated. Show the diff to the user before
  confirming.
- Adapter tokens via env or `meta-ads-credentials.json`; MCP write tokens
  only from `~/.claude/meta-credentials.json`, written by the owner. Never in
  code, fixtures, logs, URLs or test data.
- Tests use fixtures, not live API calls.

## Style

- Commits: short imperative sentence. No conventional-commits prefixes,
  no Co-Authored-By / generated-with trailers, no emoji.
- Plain factual writing. No marketing copy.
