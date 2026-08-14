#!/usr/bin/env python3
"""Fetch Meta Ads campaign structure: campaigns, ad sets, and ads."""

import argparse
import json
import sys

import meta_auth
import meta_utils

# Backward-compatible aliases — other scripts import these from meta_campaigns
to_plain = meta_utils.to_plain
api_call_with_retry = meta_utils.api_call_with_retry
read_cache = meta_utils.read_cache
write_cache = meta_utils.write_cache
CACHE_DIR = meta_utils.CACHE_DIR
CACHE_TTL = meta_utils.CACHE_TTL

def _init_account(account_id, access_token):
    """Initialize a Meta API AdAccount object."""
    from facebook_business.adobjects.adaccount import AdAccount
    from facebook_business.api import FacebookAdsApi

    api = FacebookAdsApi.init(access_token=access_token)
    return AdAccount(account_id, api=api)


def _paginated_fetch(cursor, page_size=500):
    """Iterate through a Meta SDK Cursor and collect all pages as plain dicts.

    The SDK Cursor auto-paginates, but we process in chunks to avoid
    loading everything into memory at once for large accounts.
    """
    results = []
    for obj in cursor:
        results.append(to_plain(dict(obj)))
    return results


def fetch_campaigns(account_id, access_token, active_only=False):
    """Fetch all campaigns for an ad account with automatic pagination."""
    account = _init_account(account_id, access_token)

    fields = [
        "id", "name", "status", "objective", "buying_type",
        "daily_budget", "lifetime_budget", "budget_remaining",
        "start_time", "stop_time", "created_time", "updated_time",
        "bid_strategy",
    ]
    params = {"limit": 500}
    if active_only:
        params["filtering"] = [{"field": "status", "operator": "IN", "value": ["ACTIVE"]}]

    cursor = account.get_campaigns(fields=fields, params=params)
    return _paginated_fetch(cursor)


def fetch_adsets(account_id, access_token, active_only=False):
    """Fetch all ad sets for an ad account with automatic pagination."""
    account = _init_account(account_id, access_token)

    fields = [
        "id", "name", "campaign_id", "status", "targeting",
        "daily_budget", "lifetime_budget", "bid_amount", "bid_strategy",
        "billing_event", "optimization_goal", "start_time", "end_time",
        "attribution_spec",
    ]
    params = {"limit": 500}
    if active_only:
        params["filtering"] = [{"field": "status", "operator": "IN", "value": ["ACTIVE"]}]

    cursor = account.get_ad_sets(fields=fields, params=params)
    return _paginated_fetch(cursor)


def fetch_ads(account_id, access_token, active_only=False):
    """Fetch all ads for an ad account with automatic pagination."""
    account = _init_account(account_id, access_token)

    fields = [
        "id", "name", "adset_id", "status", "creative",
        "created_time", "updated_time",
    ]
    params = {"limit": 500}
    if active_only:
        params["filtering"] = [{"field": "status", "operator": "IN", "value": ["ACTIVE"]}]

    cursor = account.get_ads(fields=fields, params=params)
    return _paginated_fetch(cursor)


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

    args = parser.parse_args()

    # Load credentials
    creds = meta_auth.load_credentials()
    if not creds:
        print(json.dumps({"status": "error", "message": "No credentials. Run meta_auth.py --oauth or --configure"}))
        sys.exit(1)

    token = creds["access_token"]
    account_id = args.account

    # Check cache (include active_only in key to avoid collisions)
    active_suffix = "_active" if args.active_only else ""
    cache_key = ("hierarchy" if args.fetch_all else "campaigns") + active_suffix
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
