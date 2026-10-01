# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [semantic](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- README: a section on where the toolkit sits next to Meta's official Ads MCP
  server, the API version and error output under "Caching and API behavior",
  and an updated list of what the tests cover.

## [1.1.0] - 2026-10-01

### Added

- `docs/ROADMAP.md`: a coverage table against Meta's official Ads MCP server,
  what was fixed and built in this release with evidence, proposals for what
  comes next, rejected ideas, and open questions.
- `meta_creatives.py --fatigue`: fatigue scored over time, per ad. The
  fatigue formula existed since 1.0.0 but no command called it, so the
  creative agent had to work out CTR trends by hand from raw rows. The new
  mode compares CTR and CPM between the two halves of the period, reads the
  period frequency, and returns a score, a status and a rotation
  recommendation for each ad. Ads with too few impressions to compare are
  listed as not scored. Both API calls go through the response cache.
- `meta_changes.py` and the `/meta-ads changes` skill with a `meta-changes`
  agent. It reads the ad account activity log and daily insights and compares
  each campaign, ad set or ad before and after every change to it, to answer
  "what changed before this dropped". Changes followed by a shift are listed
  largest first, pauses and resumes are marked, and other changes to the same
  entity inside the window are counted. Both API calls go through the
  response cache.
- `meta_delivery.py` and the `/meta-ads delivery` skill with a `meta-delivery`
  agent: a read-only diagnosis of stalled delivery. It flags ad sets with
  issues Meta reports, no impressions or underspend, and checks whether a bid
  or cost cap sits below the account's cost per optimisation event, whether
  the ad set is learning limited, and whether a week of budget buys fewer
  events than the learning phase needs. Output is sorted and deterministic.
  All four API calls go through the response cache.
- `META_ACCESS_TOKEN`: when set, every adapter uses it and does not read the
  credentials file. This lets the adapters run in CI or on a schedule without
  a token on disk. `meta_auth.py --check` reports `auth_method: "env"`, and
  `--accounts` lists the token's ad accounts through the response cache.

### Changed

- Marketing API version set to v26.0 in one place, `meta_utils.API_VERSION`.
  Before, SDK calls used whatever version the installed `facebook-business`
  defaulted to, and the dependency range `>=19.0.0` allowed releases whose
  default Marketing API version has expired (v19 to v23) or expires on
  2026-10-06 (v24). The OAuth URLs had their own hardcoded v21.0. The
  dependency is now `facebook-business>=26.0.0,<27`.
- The SDK's crash reporter is switched off. It was on by default and, on an
  unhandled SDK error, posted the Python call stack to Meta. The adapters
  now create the API object in one place, `meta_utils.init_api`.
- Documentation brought back in line with the code: `CLAUDE.md` and
  `docs/SETUP.md` still used the old `claude-meta-ads` name and paths, the
  rate limit reference listed tiers and an HTTP 429 response that Meta does
  not use, and the attribution and audience agents did not call the
  `--attribution` and `--overlap` queries their analysis depends on.

### Fixed

- The retry wrapper did not retry error 80000, the Ads Insights business use
  case limit, or 613. It also missed network failures entirely: the SDK raises
  `requests` exceptions, which do not inherit from the builtin
  `ConnectionError` and `TimeoutError` the wrapper checked for. Both are now
  retried, along with any error Meta flags as transient.
- Campaign, ad set and ad listings, ad set targeting, the pixel health check
  and the `--attribution` insights query called the API without the retry
  wrapper, so one throttled response ended the run. They now retry like the
  other calls.
- `meta_insights.py --daily` and `--attribution` shared a cache key with the
  plain summary query, so whichever ran first was returned for the other two
  for 15 minutes. `meta_creatives.py --with-metrics` ignored `--days` in its
  key, and `meta_events.py --funnel` could return a cached result without the
  funnel. Each variant now has its own key.
- `meta_events.py --health-check` reported `has_capi: false` for every pixel.
  It looked for a `source` key that the pixel stats edge does not return. The
  browser and server split now comes from the edge's `event_source` filter
  (`WEB_ONLY`, `SERVER_ONLY`), and each pixel lists per-event counts for both
  under `event_sources`. When the stats call fails, `has_capi` is `null` with
  the reason in `capi_check_error` instead of a false "not configured".
- `meta_events.py --health-check` never read or wrote the response cache, so
  every run cost one pixel listing plus stats calls for each pixel. It now
  follows the same 15-minute cache and `--no-cache` flag as the other queries.
- The README said a bare account number is accepted and normalised to
  `act_<id>`, but no adapter did that and a bare number went to the API as a
  different node. `--account` now accepts both forms and rejects anything
  else before a request is made.
- `meta_report.py --compare` computed the period comparison and printed it to
  stdout but never put it in the report it wrote. Markdown, HTML and PDF
  output now carry a "Period comparison" section with account-level and
  per-campaign changes.
- `meta_creatives.py --with-metrics` asked the Ad node for
  `effective_object_story_spec`, which is not a field of Ad or AdCreative in
  the Marketing API. Format detection now reads the creative's
  `object_story_spec` and `object_type`, and a carousel is no longer
  classified as an image when it also has an `image_url`.
- `meta_events.py` compared insights action types such as
  `offsite_conversion.fb_pixel_purchase` with pixel event names such as
  `Purchase`. Nothing matched, so every event was labelled custom, the funnel
  was unordered, and link clicks and post engagement were listed as pixel
  events. Website pixel actions are now renamed to their standard event and
  other action types are left out.
- A network error from the SDK quotes the request URL, and the SDK sends the
  access token as a URL parameter. An unreachable API therefore printed the
  token in the traceback. Network errors are now reported as an error object
  with `"error_kind": "network"`, and every exception message that is logged,
  printed or cached has `access_token`, `appsecret_proof`, `client_secret`
  and `fb_exchange_token` values removed first.
- A failed API call ended the adapter with a Python traceback and an empty
  stdout. Adapters now print an error object with Meta's message, the error
  code and subcode, and an `error_kind` of `auth`, `rate_limit`,
  `too_much_data` or `api`. An expired or revoked token says how to
  re-authenticate. A throttled call reports `retry_after_minutes` from the
  `X-Business-Use-Case-Usage` header when Meta sends it.

## [1.0.2] - 2026-09-08

### Added

- Distinct SVG banner and project icon, linked CI/release badges, and a screenshot of real output generated from synthetic fixtures.
- Reproducible offline examples, release notes, maintainer release instructions and a verification record.

### Changed

- Included the eight adapter modules in built distributions; previous wheels contained only metadata.
- Reorganized README around installation, first run, example output, supported capabilities and the actual CI checks.
- Corrected installation and capability claims, with explicit distinctions between agent workflows, direct CLI operations and optional integrations.

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

[Unreleased]: https://github.com/arcbaslow/meta-ads-agents/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/arcbaslow/meta-ads-agents/releases/tag/v1.1.0
[1.0.2]: https://github.com/arcbaslow/meta-ads-agents/releases/tag/v1.0.2
[1.0.1]: https://github.com/arcbaslow/meta-ads-agents/releases/tag/v1.0.1
[1.0.0]: https://github.com/arcbaslow/meta-ads-agents/releases/tag/v1.0.0
