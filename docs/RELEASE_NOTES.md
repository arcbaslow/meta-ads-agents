# Meta Ads Agents v1.1.0

Release date: 2026-10-01

This release fixes defects in the adapters, moves to Marketing API v26.0, and adds three read-only analyses that Meta's official Ads MCP server does not provide. The [changelog](../CHANGELOG.md) has every entry. The [roadmap](ROADMAP.md) has the evidence for each and what is proposed next.

## Added

- `meta_delivery.py` and `/meta-ads delivery`: diagnosis of stalled delivery. It flags ad sets with issues Meta reports, no impressions or underspend, and checks whether a bid or cost cap is below the account's cost per optimisation event, whether the ad set is learning limited, and whether a week of budget buys fewer events than the learning phase needs.
- `meta_changes.py` and `/meta-ads changes`: the ad account activity log lined up with each entity's metrics before and after every change.
- `meta_creatives.py --fatigue`: per-ad fatigue score, status and rotation recommendation from frequency, CTR change and CPM drift over the period.
- `META_ACCESS_TOKEN`: the adapters run from an environment token with nothing stored on disk.
- `docs/ROADMAP.md`.

## Changed

- Marketing API v26.0, set in `meta_utils.API_VERSION`. The dependency is `facebook-business>=26.0.0,<27`. Earlier ranges allowed SDK releases whose default API version has expired.
- The SDK crash reporter is off.
- The full audit starts seven core agents. The delivery agent is the seventh.

## Fixed

- `--health-check` reported no Conversions API for every pixel. Fixed, and it now lists browser and server counts per event.
- `--with-metrics` requested a field the Ad node does not have.
- `--daily` and `--attribution` could return each other's cached data.
- `--compare` left the comparison out of the report it wrote.
- Event classification and the funnel used names that never matched the API's.
- Error 80000, error 613 and network errors were not retried, and several calls skipped the retry wrapper.
- API and network errors print a JSON error object. A network error no longer exposes the access token.
- Bare account numbers are accepted, as the README said.

## Upgrading

Reinstall so that the SDK matches the pinned API version:

```bash
python -m pip install -e ".[dev]"
```

Output changes to be aware of:

- `meta_events.py` event lists contain website pixel events only, under their standard names. Link clicks and other engagement actions are no longer listed.
- `has_capi` can be `null` when the pixel stats call fails.
- A failed API call exits 1 with a JSON error on stdout instead of a traceback.

## Validation

271 tests passed. Ruff passed.

Local validation used Windows and Python 3.12.10. The [verification record](VERIFICATION.md) lists the checks and their scope. The repository's CI matrix covers Python 3.10 to 3.13. Tests use mocks and fixtures. No live ad account was used, so the new analyses and the Conversions API fix are verified against the SDK's field lists and Meta's documentation, not against live responses.

## Downloads

Use the source archive for the complete toolkit, including scripts, skills, configuration, documentation and demo fixtures. `SHA256SUMS.txt` records the attached artifact hashes. GitHub's automatically generated source downloads are also available.

Package-registry publishing is separate from this GitHub release and remains controlled by the existing opt-in repository settings. No claim is made that this version is published on PyPI or npm.
