# Roadmap

Written 2026-09-30 against v1.0.2 plus the `roadmap-work` branch. Marketing API facts were checked on that date against the pages listed under [Sources](#sources). Claims about the official Meta Ads MCP server are marked by how they were checked: [O] an official Meta page, [L] the live tool schemas of one connected session, [S] secondary coverage.

## Where this toolkit sits

Meta ships its own Ads MCP server at `mcp.facebook.com/ads`, in open beta since 2026-04-29 [O1]. It lists accounts and entities, runs insights queries from a closed field catalogue, reads the activity log, datasets and delivery errors, offers Meta-side benchmarks, anomaly and trend tools, and writes campaigns, ad sets, ads, creatives, audiences, catalogues and experiments [O2][L].

This toolkit does not rebuild any of that. It is the read-only analysis layer for the questions the server leaves to the person running the account:

- Why is this ad set not spending?
- What changed before this dropped?
- Which creatives are wearing out?
- How do conversions differ by attribution window?
- What goes into a report I can send or diff?

Its outputs are computed by code from fields the Marketing API returns, cached locally, and written as JSON, markdown, CSV, HTML or PDF. It writes nothing to an ad account. For changes, use Ads Manager or the official server.

## Coverage table

"Partial" means the raw inputs are available but the analysis is not done for you, or only part of the capability exists.

| Capability | Official Meta Ads MCP | This repo | Neither |
| --- | --- | --- | --- |
| Account, campaign, ad set, ad listing | Yes [O2] | Yes (`meta_campaigns.py`) | |
| Insights query | Partial: closed catalogue of 122 fields, no per-custom-conversion metrics, no quality rankings [L] | Partial: fixed field list (`meta_insights.py`) | Arbitrary fields |
| Breakdowns (age, gender, placement, device, country) | Partial: a `breakdowns` parameter exists, allowed values not documented [O3][S1] | Yes | |
| Daily time series | Yes (`time_increment`) [L] | Yes (`--daily`) | |
| Attribution window comparison | No: no window parameter [L][S2] | Yes (`--attribution`: `1d_click`, `7d_click`, `1d_view`) | |
| Period-over-period comparison | Partial: two calls, or trend direction [L] | Yes, in reports (`meta_report.py --compare`) | |
| Anomaly detection | Yes, no thresholds or lookback exposed [O3][L] | No (agent prompt only) | |
| Industry and auction benchmarks | Yes [O3] | No (a static reference file without sources) | |
| Opportunity score | Yes [O2] | No | |
| Creative fatigue scoring | No [L][S3] | Yes (`meta_creatives.py --fatigue`) | |
| Audience overlap between ad sets | Partial: auction overlap advice, no pairwise figure [L] | Partial: shared interests in targeting settings | Shared-user overlap |
| Audience size, delivery estimate | Partial: custom audience size only [O2] | No | Delivery estimate |
| Learning phase status | Yes, as a raw field [L] | Yes (`meta_delivery.py`) | |
| Stalled delivery diagnosis (cap against CPA, budget against event volume) | Partial: raw inputs; the errors tool excludes pacing and optimisation issues [L] | Yes (`meta_delivery.py`) | |
| Delivery errors | Yes [O4] | Partial: ad set `issues_info` in `meta_delivery.py` | |
| Ad rejection and policy review | Partial: status and log events, no rejection reasons [L] | No | Rejection reasons across an account |
| Activity log | Yes [O5] | Yes (`meta_changes.py`) | |
| Activity log correlated with performance | No: separate tools [L] | Yes (`meta_changes.py`) | |
| Pixel and dataset event volume | Yes, 28 days [O6] | Partial: 3 days, per event, browser and server | |
| Event match quality | Yes [O6] | No | |
| Pixel against Conversions API coverage | Partial: web-only and server-only volume [L] | Yes, per event (`event_sources`) | |
| Deduplication check | No [L] | No | Yes |
| Budget pacing, end-of-period forecast | No [L] | Partial: agent prompt, nothing computed | Forecast |
| Reconciliation with a tracker or CRM export | No [L] | No | Yes |
| Naming and UTM linting | No [L] | No (agent prompt only) | Yes |
| Multi-account rollup | Partial: one account per call [L][S4] | No | |
| Deterministic output for schedules and CI | No: conversational [S2] | Partial: delivery, change and fatigue output is sorted and stable; token from the environment; no single audit bundle | Audit bundle with exit codes |
| Report export (markdown, CSV, HTML, PDF) | No [L][S2] | Yes (`meta_report.py`) | |
| Local response cache | No: remote only [O1] | Yes, 15 minutes | |
| Creating and changing campaigns, ad sets, ads, creatives, audiences | Yes [O2] | No, by design | |
| A/B and lift tests, catalogue management, Ad Library search | Yes [O2][O7] | No | |

## Baseline

State of `master` at `145907a` before any change:

- `ruff check scripts/`: passed.
- `pytest scripts/ -q`: 124 passed. On the machine used for this work the default pytest temp root was not writable, so the suite was run with `--basetemp` pointing elsewhere. That is a local permission problem, not a repo defect.
- `.github/workflows/tests.yml` runs those two commands and nothing else.
- No test called a fetch function. Every API request path was untested, which is how the defects below survived.

## Now

Everything in this group is done on the `roadmap-work` branch. Effort is what it took: S is under a day, M is one to three days.

### Bugs and API version work

Each fix has a regression test. "Official MCP" does not apply to these: they are defects in this repo.

| # | What | Why it matters | Evidence | API fields or names | Effort | Risk | Commit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Retry set lacked 80000 (Ads Insights limit) and 613; network errors were never retried | The most common insights throttle ended a run. The SDK raises `requests` exceptions, which are not the builtin `ConnectionError` the wrapper checked | `meta_utils.py` retry set; confirmed by running `_is_retryable` on `requests.exceptions.ConnectionError`; codes from [M1][M2] | Error codes 4, 17, 613, 80000, 80003, 80004, 80014; `is_transient` | S | Low | `abab981` |
| 2 | Campaign, ad set and ad listings, ad set targeting, pixel health and `--attribution` skipped the retry wrapper | One throttled response ended the run, although the changelog said all calls retry | Read in `meta_campaigns.py`, `meta_audiences.py`, `meta_events.py`, `meta_insights.py` | None new | S | Low | `0fa5396` |
| 3 | Cache key collisions: `--daily` and `--attribution` shared the summary query's key; creatives ignored `--days`; events ignored `--funnel` | For 15 minutes the wrong data was returned with no warning. The budget and performance agents both hit this in one audit | Confirmed with a test that fails on the old code | None | S | Low | `755abbd` |
| 4 | `has_capi` was false for every pixel | The report told every account that the Conversions API was not configured. The code read a `source` key that the stats edge does not return | `AdsPixelStats` has `count`, `value`, `event`, `diagnostics_hourly_last_timestamp` (SDK 26.0.2); the edge filters with `event_source` [M3] | `AdsPixel/stats`: `aggregation=event`, `event_source=WEB_ONLY` or `SERVER_ONLY` | S | Medium: response shape taken from the SDK spec, not a live call | `e15f3c2` |
| 5 | `--health-check` never used the cache | One listing plus stats calls per pixel on every run, against the repo's own rule | Read in `meta_events.py` | None | S | Low | `24682df` |
| 6 | Account IDs were not normalised | The README said `123` and `act_123` both work. A bare number went to the API as a different node | README "Quick start"; no normaliser existed in `scripts/` | None | S | Low | `642b055` |
| 7 | `--compare` computed the comparison and left it out of the report | The README's comparison example wrote a report with no comparison in it | Confirmed by running the README command | None | S | Low | `b55ffdb` |
| 8 | `--with-metrics` requested `effective_object_story_spec` on the Ad node | The field exists on neither Ad nor AdCreative. The Graph API rejects unknown fields, so the quick-start command is expected to fail on a real account | Zero occurrences in SDK 19.0.0 and 26.0.2; absent from [M4][M5]. The name came from `docs/superpowers/plans/2026-04-06-high-priority-fixes.md` | `AdCreative.object_story_spec`, `AdCreative.object_type` | S | Low | `44bb7d0` |
| 9 | Events were compared by the wrong names | Insights returns `offsite_conversion.fb_pixel_purchase`; the code expected `Purchase`. Every event was labelled custom, the funnel had no order, and link clicks were listed as pixel events | Action type names from [M6] | `actions.action_type` | S | Low | `8f98d8e` |
| 10 | API failures ended in a traceback with empty stdout | An agent reading stdout got nothing to act on for an expired token or a throttle | Read in every adapter's `main`; token codes from [M7], usage header from [M2] | Error 190 and 102; `X-Business-Use-Case-Usage.estimated_time_to_regain_access` | S | Low | `650d0c7` |
| 11 | Token could only come from the credentials file | `CLAUDE.md` says tokens come from the environment. Nothing read it, so CI and scheduled runs needed a token on disk | `meta_auth.py` | None | S | Low | `4efd32f` |
| 12 | SDK crash reporter was on | On an unhandled SDK error the SDK posts the call stack to Meta. `SECURITY.md` says nothing is sent anywhere | `facebook_business/crashreporter.py`, enabled by `FacebookAdsApi.init(crash_log=True)` | None | S | Low | `05086c5` |
| 13 | API version floated; OAuth URLs hardcoded v21.0; dependency allowed dead SDKs | `facebook-business>=19.0.0` allowed releases whose default Marketing API version has expired. v24.0 expires 2026-10-06. v26.0 is current [M8][M9] | `pyproject.toml`, `meta_auth.py` | `API_VERSION = "v26.0"`; `facebook-business>=26.0.0,<27` | S | Medium: v26.0 behaviour was checked against the changelog and SDK field lists, not a live account | `74100d3` |
| 14 | Docs and agents had drifted from the code | `CLAUDE.md` and `SETUP.md` used the old project name; the rate limit reference listed tiers and an HTTP 429 that Meta does not use; two agents never called the queries their analysis needs | Rate limits from [M1][M2] | None | S | Low | `13ad940` |

A test added with item 8, `scripts/test_requested_fields.py`, runs every fetch function against a recording stand-in and fails when a requested field is missing from the installed SDK's field list for that object. It turns the "verify field names" rule in `CONTRIBUTING.md` into a check.

### Features

#### Stalled delivery diagnosis (`meta_delivery.py`, `/meta-ads delivery`)

- **What:** For each active ad set: issues Meta reports, zero delivery, underspend against the daily budget, a bid or cost cap below the account's cost per optimisation event, learning limited status, and a weekly budget that buys fewer events than the learning phase needs. Campaign budgets are checked once on the campaign. Checks that cannot run are listed as not evaluated with a reason.
- **Why:** A cap set below the real CPA stops delivery without any error. The account shows an active ad set that spends nothing, and the cause has to be worked out by comparing settings with results by hand.
- **Official MCP:** Partial. It returns `learning_stage_info`, bid and budget fields, and delivery errors. It has no tool that compares them, and its errors tool states that it does not cover pacing or optimisation issues [L].
- **Evidence:** Learning phase needs about 50 optimisation events in the 7 days after the last significant edit [H1][H2]. `learning_stage_info.status` values `LEARNING`, `SUCCESS`, `FAIL` [M10]. Whole-unit currencies [M11].
- **API fields:** AdSet `effective_status`, `bid_strategy`, `bid_amount`, `daily_budget`, `lifetime_budget`, `budget_remaining`, `optimization_goal`, `promoted_object`, `learning_stage_info`, `issues_info`, `start_time`, `end_time`; Campaign `daily_budget`, `lifetime_budget`, `budget_remaining`, `bid_strategy`, `start_time`, `stop_time`; AdAccount `currency`; insights `spend`, `impressions`, `actions` at ad set level.
- **Effort:** M. **Risk:** Medium. The reference CPA uses the API's default attribution. Optimisation events without an insights action type are not evaluated. Minimum ROAS bidding is not checked. No live account was used.
- **Commit:** `6a99403`.

#### Change history correlated with performance (`meta_changes.py`, `/meta-ads changes`)

- **What:** Reads the ad account activity log and daily insights. For every change to a campaign, ad set or ad it compares spend per day, CPM, CTR, and CPA when an action type is given, over the days before and after. Changes followed by a shift are listed largest first. Pauses and resumes are marked, and other changes to the same entity inside the window are counted.
- **Why:** "What changed before this dropped" is the first question after a bad day. Answering it means reading the history page and the reporting table side by side.
- **Official MCP:** No. The activity log and the insights query are separate tools and the agent has to join them in conversation [L].
- **Evidence:** Activity fields and the one-week default window [M12]. Borrowed from change-history tools in gomarble and the change-point idea in fortytwode [G1][G2].
- **API fields:** `AdAccount/activities`: `event_time`, `event_type`, `translated_event_type`, `object_id`, `object_name`, `object_type`, `actor_name`, `application_name`, `extra_data`, with `since` and `until`; insights `campaign_id`, `adset_id`, `ad_id`, `spend`, `impressions`, `clicks`, `actions` with `time_increment=1`.
- **Effort:** M. **Risk:** Medium. It is a before and after comparison and proves no cause. Log times are UTC and insights days are in the account time zone. How far back the log goes is not documented.
- **Commit:** `c32d682`.

#### Creative fatigue scored over time (`meta_creatives.py --fatigue`)

- **What:** Per ad: frequency for the period, CTR and CPM in the second half of the period against the first half, a 0 to 1 score, a status (`fatigued`, `near_fatigue`, `ok`) and a rotation recommendation. Ads with too few impressions in either half are listed as not scored.
- **Why:** The fatigue formula shipped in 1.0.0 but no command called it. The creative agent was told to derive CTR trends from raw daily rows, which gives a different answer each run.
- **Official MCP:** No. It returns frequency and CTR series and no score [L][S3].
- **Evidence:** `fatigue_score` in `meta_creatives.py` had no caller. Thresholds are the ones in `agents/meta-creative.md` since 1.0.0. The impression gate follows the spend-gate idea in [G3].
- **API fields:** insights at ad level: `ad_id`, `ad_name`, `adset_id`, `campaign_id`, `spend`, `impressions`, `clicks`, `reach`, `frequency`.
- **Effort:** S. **Risk:** Medium. The thresholds are practitioner rules, not Meta guidance. They are reported with the numbers behind them so the reader can disagree.
- **Commit:** `b9e3f94`.

## Next

Proposals. None of these is built.

### Ad rejection and policy review tracking

- **What:** One listing of every ad that is disapproved, has issues or is pending review, with the rejection reason, grouped by reason and by creative, plus the `ad_review_declined` and `ad_review_approved` entries from the activity log for timing.
- **Why:** Rejections arrive one notification at a time. Seeing that nine ads fell on the same policy line, or on the same landing page, is the useful view.
- **Official MCP:** Partial. `effective_status=DISAPPROVED` and the review events are readable; its errors tool states that it does not cover ad rejection [L].
- **Evidence:** Ad `effective_status` values and `ad_review_feedback`, `issues_info`, `failed_delivery_checks` [M4].
- **API fields:** Ad `effective_status`, `ad_review_feedback` (`global`, `placement_specific`), `issues_info`, `failed_delivery_checks`, `creative{id}`; activity `event_type`.
- **Effort:** S. **Risk:** Medium. The keys inside `ad_review_feedback` have to be confirmed on a real rejected ad before anything is grouped on them.

### Naming convention and UTM linting

- **What:** A rules file (pattern per level, delimiter, allowed `utm_source` and `utm_medium` values, required dynamic parameters) checked against campaign, ad set and ad names and each creative's URL parameters. Output is a sorted list of violations with a non-zero exit code on failure.
- **Why:** One ad with a missing or mistyped parameter splits its traffic into a separate row in the tracker and in analytics, and reconciliation fails from there on.
- **Official MCP:** No [L].
- **Evidence:** Rules-file linting with CI exit codes in [G4][G5]; URL tag extraction shape in [G6].
- **API fields:** AdCreative `url_tags`, `object_story_spec` (link in `link_data` or `video_data.call_to_action`), `asset_feed_spec`; Campaign, AdSet and Ad `name`.
- **Effort:** M. **Risk:** Low. No insights quota is used.

### Reconciliation with a tracker or CRM export

- **What:** Take a CSV with a date, an ad, ad set or campaign key, and a conversion count or revenue. Join it to Meta-reported conversions for the same period and report the gap per entity and per day.
- **Why:** Meta's numbers and the source of truth never match. The useful output is where the gap is concentrated.
- **Official MCP:** No [L].
- **Evidence:** Conversion action-type allowlist to avoid double counting in [G6].
- **API fields:** insights `ad_id`, `adset_id`, `campaign_id`, `actions`, `action_values`, `spend` with `time_increment=1`; the key mapping depends on the UTM template, so this follows the linting item.
- **Effort:** M. **Risk:** Medium. Attribution windows and time zones differ between the two sides and have to be stated in the output.

### Budget pacing and end-of-period forecast

- **What:** Month-to-date spend against budget per campaign and account, a run-rate forecast to the end of the period, and a flag when the forecast misses the budget or the account spend cap.
- **Why:** Pacing is currently an instruction to the budget agent with nothing computed.
- **Official MCP:** No. It returns `budget_remaining` and spend only [L].
- **Evidence:** Daily budgets may overspend by up to 75% on a day since v24.0, within seven times the daily budget per week; ad sets may share up to 20% of budget [M13][M14]. Alerts must allow for both.
- **API fields:** AdAccount `spend_cap`, `amount_spent`; Campaign and AdSet `daily_budget`, `lifetime_budget`, `budget_remaining`, `start_time`, `end_time`/`stop_time`; Campaign `is_adset_budget_sharing_enabled`; insights `spend` daily.
- **Effort:** M. **Risk:** Medium. A straight-line forecast is wrong for accounts with a strong weekday pattern; say which method was used.

### Deterministic audit bundle for schedules and CI

- **What:** One command that runs the code-computed checks (delivery, fatigue, change history, event sources, linting once built), writes a single JSON bundle with stable finding IDs, and exits non-zero on findings above a chosen severity. Each control reports pass, fail, unknown or not applicable, and coverage is reported separately from health.
- **Why:** A bundle that is identical for identical data can be diffed week to week and run unattended. "Could not read the pixel" stops being reported as "pixel broken".
- **Official MCP:** No. It is conversational; Meta's CLI is the scripted path [S2][O8].
- **Evidence:** Four-state controls and coverage in [G7]; JSON first, renderers second in [G2][G7].
- **API fields:** None new.
- **Effort:** M to L. **Risk:** This changes the shape of the project. The README states that the audit is an agent skill and not a command. It needs an owner decision.

### Attribution comparison, brought up to date

- **What:** Add `1d_ev` and `28d_click` to the windows, request `attribution_setting`, compute the per-window table and the click to view split in code, and note the March 2026 change in the output.
- **Why:** Since 2026-03-03 click-through attribution for website conversions counts link clicks only, and other interactions moved to engage-through [M15]. A `7d_click` series has a step there. `7d_view` and `28d_view` return nothing since 2026-01-12 [M16].
- **Official MCP:** No window parameter [L].
- **API fields:** `action_attribution_windows`: `1d_click`, `7d_click`, `28d_click`, `1d_view`, `1d_ev`; insights `attribution_setting`; AdSet `attribution_spec`, `is_incremental_attribution_enabled`.
- **Effort:** S. **Risk:** Low.

### Structure fields the adapters do not read yet

- **What:** Request `effective_status` on campaigns, ad sets and ads, `special_ad_categories`, `advantage_state_info`, `is_adset_budget_sharing_enabled` and `targeting_automation`. Identify Advantage+ campaigns from `advantage_state_info` and legacy ones from `smart_promotion_type`.
- **Why:** The account agent is asked about ad sets running disapproved ads and cannot answer, because ads are fetched without `effective_status` (`meta_campaigns.py:77`). With Advantage+ audience on, age, gender and interests in the targeting spec are suggestions, so targeting audits that read them as limits are wrong [M17][M18].
- **Official MCP:** Yes for the raw fields.
- **Effort:** S. **Risk:** Low.

### Audience adapter gaps

- **What:** Request audience size, surface flagged audiences, and extend the overlap check beyond interests.
- **Why:** `analyze_overlap` compares interest names only (`meta_audiences.py:99`), although its docstring says it also compares custom audiences and geography. Broad and Advantage+ ad sets have no interests, so it finds nothing for them. Audiences flagged for integrity reasons stop delivering and cannot seed lookalikes [M19].
- **API fields:** CustomAudience `approximate_count_lower_bound`, `approximate_count_upper_bound`, `operation_status` (code 471), `fields_violating_integrity_policy`; AdSet `targeting.custom_audiences`, `targeting.geo_locations`, `targeting_automation`.
- **Effort:** S to M. **Risk:** Low. The overlap stays a comparison of settings and must be labelled as that.

### Page size and large accounts

- **What:** Pass `limit` on the insights, creative and audience listings, and move breakdown and ad-level queries to asynchronous report runs with split-on-failure when a synchronous call returns "too much data".
- **Why:** `fetch_insights` (`meta_insights.py:131`), `fetch_creatives` (`meta_creatives.py:218`) and `fetch_custom_audiences` (`meta_audiences.py:68`) pass no `limit`, so each page holds the API default and a large account costs many calls. Campaign listings already pass 500.
- **Evidence:** Airbyte's async job manager [G8].
- **Effort:** S for `limit`, M to L for asynchronous jobs. **Risk:** Medium.

### Rate limit awareness before the limit

- **What:** Read `X-Business-Use-Case-Usage` and `X-FB-Ads-Insights-Throttle` on successful responses, pause when usage is high, and add a command that prints current usage without an API call.
- **Why:** Today the adapters only react after an error. On Limited access 60 read calls in five minutes block the account for 300 seconds [M1], and an audit can block the buyer's other tools.
- **Evidence:** Airbyte pauses at 85% and 95% and honours `estimated_time_to_regain_access` [G9].
- **Effort:** M. **Risk:** Low.

### Token introspection and smaller permissions

- **What:** Read the real expiry and scopes from `debug_token`, and request only `ads_read` at login.
- **Why:** `validate_token_with_api` returns a hardcoded scope list and no expiry (`meta_auth.py:83`), so a manually configured token is never reported as close to expiry. See also the open question on scopes.
- **Effort:** S. **Risk:** Medium. Changing scopes changes what existing users are asked to approve.

### Smaller items

- Report currency: `fmt_money` prints `$` for every account (`meta_report.py:10`). AdAccount `currency` is available.
- Minimum ROAS bidding in the delivery diagnosis: `bid_constraints.roas_average_floor` against `purchase_roas`.
- Pixel stats window: `fetch_event_sources` reads a fixed 3 days (`meta_events.py:189`) and ignores `--days`. The official server's stats tool reads up to 28 days [O6].
- Multi-account rollup: loop the code-computed checks over the accounts a token can see. Currency mixing has to be handled. The official server works one account per call [L].

## Later

- **Deduplication and event match quality through the Dataset Quality API.** Fields `event_match_quality.composite_score`, `dedupe_key_feedback`, `event_coverage`, `data_freshness` [M20]. It needs a system user token, which the OAuth flow here does not produce, and the official server already returns match quality [O6]. Worth doing only for the deduplication feedback.
- **Meta's own fatigue signal.** The ad account webhook has a `creative_fatigue` field [M21], and the SDK lists undocumented insights fields with that name. Test on a real account before building on either.
- **Figures in agent-written reports checked by code** against the JSON the adapters produced, before the report is shown [G10].
- **Explaining a CPA change by mix and efficiency** (shift-share between periods) [G2].
- **`appsecret_proof` on API calls.** The app secret is already stored at login.
- **Write features.** Not proposed. The official server creates and updates every entity this toolkit reads, under account-level rules an admin controls [O1]. A second write path here would duplicate it and add risk. If that changes, `CLAUDE.md` already sets the pattern: show the operation JSON, ask, then send.

## Considered and rejected

- **Rebuilding listing, generic insights, benchmarks, anomaly signals, opportunity score, Ad Library search, catalogue tools and experiments.** The official server covers them [O2][O3][O7].
- **Audience overlap as a percentage of shared users.** No documented endpoint returns it. The SDK carries an `AudienceOverlap` type and an `overlap_segment` breakdown with no documentation. Nothing is built on undocumented fields.
- **Fixed thresholds presented as verdicts, and a single health score from penalty points.** Frequency above 3.5, CTR under 0.5% and similar rules are practitioner reports, and the largest skill pack in this space now forbids them as platform-wide rules [G7]. Thresholds here are configurable defaults printed next to the numbers.
- **Conversion lag analysis.** The adapters have no time-to-convert data. The attribution agent now says so and compares `1d_click` with `7d_click` instead.
- **Incremental ROAS from zero-spend days.** Statistically weak and needs store data [G11].
- **Hosted connectors and token brokers.** A third party would hold the token, and the ones that exist have paid tiers.
- **Marketing mix modelling.** Out of scope.

## Open questions

Behaviour that may be intended. The code was left alone.

1. **Status filter.** `meta_campaigns.py:51`, `:68`, `:83` filter with `filtering` on the field `status`. The edges document an `effective_status` parameter. Whether `status` is accepted as a filtering field was not verified. `meta_delivery.py` uses `effective_status`.
2. **Date range includes today.** `compute_date_range` (`meta_insights.py:32`) returns `days + 1` dates ending today, and the tests assert it. Today is partial, so period totals and comparisons are low. The new modules use complete days ending yesterday.
3. **Summary labels.** `aggregate_metrics` sums `reach` across rows (`meta_insights.py:44`), which overstates unique reach, and reports the number of rows as `days` (`:58`).
4. **Funnel tail.** `build_funnel` appends events that are not funnel steps after Purchase, with drop-off figures (`meta_events.py:105`).
5. **OAuth scopes.** `meta_auth.py:23` requests `ads_management`, `read_insights` and `business_management`. The toolkit is read-only, and `read_insights` is a Pages permission. `ads_read` may be enough.
6. **App secret on the command line.** `--app-secret` (`meta_auth.py:335`) ends up in shell history, which `SECURITY.md` lists as in scope.
7. **Credentials file against environment.** `CLAUDE.md` says tokens come from the environment only. The file is still the default, and `META_ACCESS_TOKEN` now takes precedence. Should the file be deprecated?
8. **Benchmarks file.** `skills/meta-ads/references/benchmarks.md` lists CTR, CPC, CPM, CPA and ROAS by vertical with no source. The official server has a benchmark tool backed by Meta's data.
9. **Skill versions.** Every `SKILL.md` says `version: "1.0.0"` while the package is 1.0.2. Unknown whether skills are versioned separately.
10. **Old plan file.** `docs/superpowers/plans/2026-04-06-high-priority-fixes.md` is where the nonexistent `effective_object_story_spec` field came from. Keep as history or remove?
11. **Dead code.** `extract_conversions` (`meta_insights.py:62`) has no caller.
12. **Audit size.** The audit skill now starts seven core agents. The delivery agent makes four cached calls. Drop it from the audit if that is too much.
13. **Dependency cap.** `facebook-business>=26.0.0,<27` keeps the SDK and `API_VERSION` moving together in one deliberate commit. Dependabot will propose the next major when it ships.

## Could not verify

- Any live API behaviour. No call was made to the Meta API. That covers the error returned for the nonexistent field in item 8, whether `filtering` on `status` works, and the exact rows the pixel stats edge returns.
- How far back the activity log goes. The reference gives the one-week default only [M12].
- Whether the March 2026 click attribution change restated history, and whether it added an API value beyond `1d_ev` [M15].
- The values of `learning_stage_info.dynamic_lp_status` and when Meta returns the `dynamic_lp_*` fields.
- The official server's rate limits, data freshness, pricing after the beta, and the allowed `breakdowns` values. Meta's pages do not state them.
- The Marketing API versions table still stops at v25.0. v26.0 is confirmed by the Graph API changelog, the v26.0 changelog page and the SDK default [M8][M9].
- The 2026 out-of-cycle changes page after 2026-06-28.

## Sources

Official Meta Ads MCP and CLI:

- [O1] https://www.facebook.com/business/news/meta-ads-ai-connectors and https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-overview
- [O2] https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-tools-ad-creation-and-management.md
- [O3] https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-tools-comprehensive-reporting.md
- [O4] https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-tools-help-and-troubleshooting.md
- [O5] https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-tools-activity-logs.md
- [O6] https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-tools-signals-and-datasets.md
- [O7] https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-mcp-server/ads-mcp-server-tools-abtests-and-conversion-lift-studies.md
- [O8] https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/insights.md
- [L] Tool schemas and descriptions served by the connected server on 2026-09-30, including the 122-field catalogue from `ads_get_field_context`. First-party, not a public page.
- [S1] https://www.getpassionfruit.com/blog/meta-ads-claude-mcp-what-it-actually-does
- [S2] https://adsuploader.com/blog/meta-ads-mcp-vs-cli
- [S3] https://www.zentric.digital/insights/meta-ads-mcp-limitations
- [S4] https://insights.vaizle.com/how-to-connect-facebook-ads-to-claude-using-meta-ads-mcp/

Marketing API:

- [M1] https://developers.facebook.com/docs/marketing-api/overview/rate-limiting
- [M2] https://developers.facebook.com/docs/graph-api/overview/rate-limiting
- [M3] https://developers.facebook.com/docs/marketing-api/reference/ads-pixel/stats/
- [M4] https://developers.facebook.com/docs/marketing-api/reference/adgroup
- [M5] https://developers.facebook.com/docs/marketing-api/reference/ad-creative
- [M6] https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/
- [M7] https://developers.facebook.com/docs/graph-api/guides/error-handling
- [M8] https://developers.facebook.com/docs/graph-api/changelog/versions/
- [M9] https://developers.facebook.com/blog/post/2026/07/29/introducing-graph-api-v26-and-marketing-api-v26/ and https://pypi.org/pypi/facebook-business/json
- [M10] https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-learning-stage-info/
- [M11] https://developers.facebook.com/docs/marketing-api/currencies
- [M12] https://developers.facebook.com/docs/marketing-api/reference/ad-activity/
- [M13] https://developers.facebook.com/docs/marketing-api/marketing-api-changelog/version24.0
- [M14] https://developers.facebook.com/docs/marketing-api/out-of-cycle-changes/occ-2025
- [M15] https://www.facebook.com/business/news/click-attribution
- [M16] https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
- [M17] https://developers.facebook.com/docs/marketing-api/advantage-campaigns
- [M18] https://developers.facebook.com/docs/marketing-api/marketing-api-changelog/version23.0
- [M19] https://developers.facebook.com/docs/marketing-api/reference/custom-audience/
- [M20] https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api/
- [M21] https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-ad-accounts/
- [H1] https://www.facebook.com/business/help/112167992830700
- [H2] https://en-gb.facebook.com/business/help/269269737396981

Other open-source projects:

- [G1] https://github.com/gomarble-ai/facebook-ads-mcp-server
- [G2] https://github.com/fortytwode/meta-ads-account-audit
- [G3] https://github.com/retention-corp/meta-ads-triage-template
- [G4] https://github.com/VelkinaStudio/utm-lint
- [G5] https://github.com/dannybosie/utm-governor
- [G6] https://github.com/fivetran/dbt_facebook_ads
- [G7] https://github.com/AgriciDaniel/claude-ads (`ads/references/scoring-system.md`, `ads/references/meta-audit.md`)
- [G8] https://github.com/airbytehq/airbyte/blob/master/airbyte-integrations/connectors/source-facebook-marketing/source_facebook_marketing/streams/async_job_manager.py
- [G9] https://github.com/airbytehq/airbyte/blob/master/airbyte-integrations/connectors/source-facebook-marketing/source_facebook_marketing/api.py
- [G10] https://github.com/langchain-ai/paid-media-agent
- [G11] https://github.com/neoloong/ad-attribution-auditor
