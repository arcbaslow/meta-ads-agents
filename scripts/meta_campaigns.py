#!/usr/bin/env python3
"""Fetch Meta Ads campaign structure: campaigns, ad sets, and ads."""

import argparse
import json
import os
import sys
import time

import meta_auth

CACHE_DIR = "/tmp/claude-meta-ads"
CACHE_TTL = 900  # 15 minutes


def to_plain(obj):
    """Recursively convert Meta SDK objects to JSON-serializable dicts/lists."""
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    if hasattr(obj, 'export_all_data'):
        return to_plain(obj.export_all_data())
    if hasattr(obj, '_data'):
        return to_plain(dict(obj._data))
    return obj


def api_call_with_retry(fn, max_retries=3, base_delay=2):
    """Call fn() with exponential backoff on failure.

    Retries on any exception (typically Meta API rate limit error 80004).
    Delays: base_delay, base_delay*2, base_delay*4, ...
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            if delay > 0:
                time.sleep(delay)


def read_cache(account_id, key, ttl_seconds=CACHE_TTL):
    """Read cached JSON data if it exists and hasn't expired."""
    path = os.path.join(CACHE_DIR, f"{account_id}_{key}.json")
    if not os.path.exists(path):
        return None
    age = time.time() - os.path.getmtime(path)
    if age > ttl_seconds:
        return None
    with open(path, "r") as f:
        return json.load(f)


def write_cache(account_id, key, data):
    """Write JSON data to cache file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{account_id}_{key}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def fetch_campaigns(account_id, access_token, active_only=False):
    """Fetch all campaigns for an ad account."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    fields = [
        "id", "name", "status", "objective", "buying_type",
        "daily_budget", "lifetime_budget", "budget_remaining",
        "start_time", "stop_time", "created_time", "updated_time",
        "bid_strategy",
    ]
    params = {}
    if active_only:
        params["filtering"] = [{"field": "status", "operator": "IN", "value": ["ACTIVE"]}]

    campaigns = list(account.get_campaigns(fields=fields, params=params))
    return [to_plain(dict(c)) for c in campaigns]


def fetch_adsets(account_id, access_token, active_only=False):
    """Fetch all ad sets for an ad account."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    fields = [
        "id", "name", "campaign_id", "status", "targeting",
        "daily_budget", "lifetime_budget", "bid_amount", "bid_strategy",
        "billing_event", "optimization_goal", "start_time", "end_time",
        "attribution_spec",
    ]
    params = {}
    if active_only:
        params["filtering"] = [{"field": "status", "operator": "IN", "value": ["ACTIVE"]}]

    adsets = list(account.get_ad_sets(fields=fields, params=params))
    return [to_plain(dict(a)) for a in adsets]


def fetch_ads(account_id, access_token, active_only=False):
    """Fetch all ads for an ad account."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    fields = [
        "id", "name", "adset_id", "status", "creative",
        "created_time", "updated_time",
    ]
    params = {}
    if active_only:
        params["filtering"] = [{"field": "status", "operator": "IN", "value": ["ACTIVE"]}]

    ads = list(account.get_ads(fields=fields, params=params))
    return [to_plain(dict(a)) for a in ads]


def build_hierarchy(campaigns, adsets, ads):
    """Build a nested hierarchy: campaigns → ad sets → ads."""
    adset_map = {}
    for adset in adsets:
        cid = adset.get("campaign_id")
        if cid not in adset_map:
            adset_map[cid] = []
        adset_map[cid].append(adset)

    ad_map = {}
    for ad in ads:
        asid = ad.get("adset_id")
        if asid not in ad_map:
            ad_map[asid] = []
        ad_map[asid].append(ad)

    result = []
    for campaign in campaigns:
        cid = campaign["id"]
        campaign_adsets = adset_map.get(cid, [])
        for adset in campaign_adsets:
            adset["ads"] = ad_map.get(adset["id"], [])
        campaign["adsets"] = campaign_adsets
        result.append(campaign)

    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Ads campaign structure")
    parser.add_argument("--account", required=True, help="Ad account ID (e.g., act_123456)")
    parser.add_argument("--active-only", action="store_true", help="Only fetch active entities")
    parser.add_argument("--fetch-all", action="store_true", help="Fetch full hierarchy (campaigns + ad sets + ads)")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache, fetch fresh data")
    parser.add_argument("--json", action="store_true", default=True, help="Output as JSON")

    args = parser.parse_args()

    # Load credentials
    creds = meta_auth.load_credentials()
    if not creds:
        print(json.dumps({"status": "error", "message": "No credentials. Run meta_auth.py --oauth or --configure"}))
        sys.exit(1)

    token = creds["access_token"]
    account_id = args.account

    # Check cache
    cache_key = "hierarchy" if args.fetch_all else "campaigns"
    if not args.no_cache:
        cached = read_cache(account_id, cache_key)
        if cached:
            print(json.dumps(cached, indent=2))
            return

    # Fetch data
    campaigns = fetch_campaigns(account_id, token, args.active_only)

    if args.fetch_all:
        adsets = fetch_adsets(account_id, token, args.active_only)
        ads = fetch_ads(account_id, token, args.active_only)
        hierarchy = build_hierarchy(campaigns, adsets, ads)
        result = {
            "status": "ok",
            "account_id": account_id,
            "total_campaigns": len(campaigns),
            "total_adsets": len(adsets),
            "total_ads": len(ads),
            "hierarchy": hierarchy,
        }
    else:
        result = {
            "status": "ok",
            "account_id": account_id,
            "total_campaigns": len(campaigns),
            "campaigns": campaigns,
        }

    write_cache(account_id, cache_key, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
