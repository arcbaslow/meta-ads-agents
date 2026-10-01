# Meta Marketing API Rate Limits

Checked against Meta's rate limiting pages on 2026-09-30:

- https://developers.facebook.com/docs/marketing-api/overview/rate-limiting
- https://developers.facebook.com/docs/graph-api/overview/rate-limiting

The numbers change. Re-read those pages before relying on them.

## Access tiers

Meta calls the two tiers Limited access (development) and Full access
(standard). An app moves to Full access after enough successful calls with a
low error rate.

## Business use case limits (per ad account, per hour)

| Use case | Limited access | Full access |
| --- | --- | --- |
| `ads_insights` | 600 + 400 x active ads | 190,000 + 400 x active ads |
| `ads_management` | 300 + 40 x active ads | 100,000 + 40 x active ads |
| `custom_audience` | 5,000 + 40 x active custom audiences | 190,000 + 40 x active custom audiences, capped at 700,000 |

Reads in this toolkit count against `ads_insights` (insights queries) and
`ads_management` (campaign, ad set, ad, creative and pixel listings).

## Ad account score limit

Each read call costs 1 point and each write call 3 points. Points decay over
300 seconds.

| Tier | Maximum score | Block when reached |
| --- | --- | --- |
| Limited access | 60 | 300 seconds |
| Full access | 9,000 | 60 seconds |

On Limited access, 60 read calls inside five minutes are enough to be
blocked. A full audit makes well over 20 calls, so keep the cache on.

## How throttling shows up

Meta does not answer with HTTP 429. It returns an error object with one of
these codes:

| Code | Meaning |
| --- | --- |
| 4 | Application request limit reached |
| 17 | User request limit reached |
| 613 | Calls to this API have exceeded the rate limit |
| 80000 | Business use case limit: ads insights |
| 80003 | Business use case limit: custom audience |
| 80004 | Business use case limit: ads management |
| 80014 | Business use case limit: catalog batch |

The adapters retry these with exponential backoff (2, 4 and 8 seconds) and
then stop with `"error_kind": "rate_limit"`.

## Usage headers

`X-Business-Use-Case-Usage` maps a business object ID to a list of entries:

```json
{
  "<business-object-id>": [
    {
      "type": "ads_insights",
      "call_count": 95,
      "total_cputime": 20,
      "total_time": 20,
      "estimated_time_to_regain_access": 19,
      "ads_api_access_tier": "standard_access"
    }
  ]
}
```

`call_count`, `total_cputime` and `total_time` are percentages of the limit.
`estimated_time_to_regain_access` is in minutes. When an adapter stops on a
rate limit error it reports that value as `retry_after_minutes`.

`X-FB-Ads-Insights-Throttle` carries `app_id_util_pct`, `acc_id_util_pct` and
`ads_api_access_tier` for the Insights API.

`X-Ad-Account-Usage` carries `acc_id_util_pct`, `reset_time_duration` and
`ads_api_access_tier`.

## What to do when rate limited

1. Read `retry_after_minutes` in the adapter's error output and wait that long.
2. Report the findings from the adapters that did complete.
3. Do not pass `--no-cache` on the retry. Cached responses cost nothing.

## Keeping call volume down

- Responses are cached for 15 minutes per account and query.
- Request account-level insights with a breakdown instead of one call per
  campaign or ad.
- Shorter `--days` and a higher `--level` return less data per call.
