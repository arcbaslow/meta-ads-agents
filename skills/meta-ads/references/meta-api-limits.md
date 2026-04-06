# Meta Marketing API Rate Limits

## Rate Limit Tiers

| Tier | Call Limit | Who |
|------|-----------|-----|
| Development | 200 calls/hour | Unreviewed apps |
| Standard | 60 + 40 * active_ad_count calls/hour | Reviewed apps |
| Advanced | Higher limits | Large partners |

## Throttling Behavior

- API returns HTTP 429 when rate limited
- Check `x-business-use-case-usage` header for per-account usage
- Header format: `{"account_id": {"call_count": N, "total_cputime": N, "total_time": N, "type": "ads_management"}}`

## Backoff Strategy

1. On 429: wait 60 seconds, retry
2. On second 429: wait 120 seconds
3. On third 429: abort and report partial results

## Batch Requests

- Max 50 requests per batch call
- Each batch request counts as one API call
- Use batch for fetching multiple objects by ID

## Best Practices

- Cache responses (15-minute TTL for insights, 1-hour for structure)
- Use fields parameter to request only needed data
- Use pagination (limit + after cursor) for large result sets
- Prefer account-level insights with breakdowns over per-entity calls
