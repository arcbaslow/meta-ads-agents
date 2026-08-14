# Contributing

Patches welcome. Keep changes small and focused.

## Setup

```
git clone https://github.com/arcbaslow/meta-ads-agents
cd meta-ads-agents
uv venv && uv pip install -e ".[dev]"
# or: python -m venv .venv && pip install -e ".[dev]"
```

## Before you push

```
ruff check scripts/
pytest scripts/ -q
```

Both must pass. CI runs them on every PR across Python 3.10 / 3.11 /
3.12 / 3.13.

## Commit style

Plain imperative sentence, sentence-case acceptable. No Conventional
Commits prefixes (`feat:`, `fix:`, `chore:`). No `Co-Authored-By:`
trailers, no `Generated with...` footers, no emoji.

Examples of the desired tone:

- `reject OAuth callbacks that don't carry our state`
- `retry on Meta error code 80005`
- `fix frequency weighting in the creative fatigue score`
- `bump Marketing API to v22.0`

PR refs `(#NNN)` only when one exists.

## Meta API versioning

The Marketing API ships a new version roughly twice a year and
deprecates old ones on a fixed schedule. Two rules:

1. **Verify field and edge names against the current official docs
   before touching request code.** Not from memory, not from an older
   answer. Meta renames and removes fields between versions and the SDK
   will happily send a field that no longer exists.
2. **Version bumps are their own PR.** Bump the version string, run the
   suite, and note the change in `CHANGELOG.md`. Don't bundle a version
   bump with a feature.

## What I'll accept

- Bug fixes with a regression test
- New analysis dimensions backed by fields the Marketing API actually
  returns
- Better fatigue / pacing heuristics, if you can show why the current
  one is wrong
- Marketing API version bumps
- Documentation fixes
- CI improvements

## What I'll push back on

- Write paths that mutate campaigns without the confirm-before-mutate
  pattern (show the operation JSON, ask `y/N`, then send)
- Anything that bypasses the response cache and burns API quota
- Adding paid SaaS dependencies
- Big rewrites without a discussion first — open an issue describing the
  shape before the work

## Local-only files

- `~/.claude/meta-ads-credentials.json` — your access token and app
  secret. Never commit this, never paste it into an issue.
- `<system temp>/claude-meta-ads/` — cached API responses. Contains real
  ad account data.

If you accidentally stage either, `git restore --staged <file>` before
committing.

## Tests

Every adapter is mocked. CI never hits the Meta Marketing API and needs
no credentials. Keep it that way: any test that touches the network
must be guarded behind an env var and skipped by default.

`scripts/conftest.py` redirects the credentials path and the response
cache to a temp directory for every test. Don't write a test that
depends on real user state.

## License

By contributing you agree your changes are released under the MIT
license, same as the rest of the repo.
