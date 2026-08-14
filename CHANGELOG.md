# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [semantic](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-08-14
### Fixed

- The OAuth callback listener on `localhost:8477` accepted any `code`
  it was handed. There was no `state` parameter, so while the listener
  was open any local page could drive it into exchanging an
  attacker-supplied code and bind the toolkit to someone else's ad
  account. The flow now generates a 32-byte state, sends it, and
  rejects a callback whose state doesn't match under `hmac.compare_digest`.
- `read_cache` used `age > ttl_seconds`, so `ttl_seconds=0` — the way
  callers force a fresh fetch — could still return a cache hit when the
  entry was written in the same clock tick, or when the filesystem
  reported an mtime marginally ahead of the wall clock. Non-positive
  TTLs now short-circuit to a miss and age is clamped at zero. This was
  reproducible as an intermittent test failure roughly one run in three.

### Changed

- Package, plugin, and marketplace names aligned to `meta-ads-agents`.
  They previously read `claude-meta-ads`, which pointed the plugin
  homepage and repository URLs at a repo that does not exist.
- README rewritten: badges, accurate CLI examples verified against the
  adapters' argparse definitions, caching and rate-limit behaviour
  documented.

### Added

- MIT `LICENSE` file. The license was declared in metadata but the file
  was missing.
- CI on Python 3.10 / 3.11 / 3.12 / 3.13 running ruff and pytest.
- `CONTRIBUTING.md`, `SECURITY.md`, issue and pull-request templates,
  Dependabot config.
- Ruff and pytest configuration in `pyproject.toml`, plus trove
  classifiers and project URLs. The lint rule set is selected
  explicitly rather than inherited from ruff's implicit default, which
  changes between releases and would otherwise turn a ruff upgrade into
  a red CI run.
- `scripts/conftest.py`, which makes the adapters importable no matter
  where pytest is invoked from and redirects the credentials path and
  response cache to a temp directory for every test.
- Release workflow with a tag-versus-`pyproject` version guard, sdist
  and wheel build, and a `twine check` gate.

## [1.0.0] - 2026-04-12

### Added

- Meta Marketing API adapters under `scripts/`: auth, campaigns,
  insights, creatives, audiences, events, reporting.
- Seven specialist agent definitions covering account, performance,
  creative, audience, events, budget, and attribution.
- Skill routing surface `/meta-ads` with a parallel audit orchestrator.
- OAuth flow with long-lived token exchange, plus manual token
  configuration for environments without a browser callback.
- Local JSON response cache with a 15-minute TTL, keyed by account.
- Exponential backoff on retryable Meta API error codes.
- Creative fatigue scoring on frequency, CTR decay, and recency.
- Pixel and Conversions API event health checks with funnel mapping.
- Markdown, HTML, and PDF report rendering.
- Reference tables for API rate-limit tiers, vertical benchmarks, and
  ODAX campaign objectives.

[Unreleased]: https://github.com/arcbaslow/meta-ads-agents/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/arcbaslow/meta-ads-agents/releases/tag/v1.0.0
