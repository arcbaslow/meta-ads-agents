#!/usr/bin/env python3
"""Fetch Meta Ads insights: metrics with breakdowns and time series."""

import argparse
import json
import os
import sys
from datetime import date, timedelta

import meta_auth
import meta_campaigns

METRICS = [
    "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "ad_id", "ad_name",
    "spend", "impressions", "reach", "frequency", "clicks", "cpc", "cpm",
    "ctr", "actions", "action_values", "cost_per_action_type",
    "cost_per_unique_click", "unique_clicks", "unique_ctr",
]

BREAKDOWNS = {
    "age": ["age"],
    "gender": ["gender"],
    "placement": ["publisher_platform", "platform_position"],
    "device": ["device_platform"],
    "country": ["country"],
    "time": [],  # time_increment handled separately
}


def compute_date_range(days=30):
    """Compute start and end dates for the given number of days back from today."""
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def aggregate_metrics(daily_data):
    """Aggregate daily metrics into totals and averages."""
    total_spend = sum(float(d.get("spend", 0)) for d in daily_data)
    total_impressions = sum(int(d.get("impressions", 0)) for d in daily_data)
    total_clicks = sum(int(d.get("clicks", 0)) for d in daily_data)
    total_reach = sum(int(d.get("reach", 0)) for d in daily_data)

    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    avg_cpc = (total_spend / total_clicks) if total_clicks > 0 else 0
    avg_cpm = (total_spend / total_impressions * 1000) if total_impressions > 0 else 0

    return {
        "total_spend": total_spend,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_reach": total_reach,
        "avg_ctr": round(avg_ctr, 2),
        "avg_cpc": round(avg_cpc, 2),
        "avg_cpm": round(avg_cpm, 2),
        "days": len(daily_data),
    }


def extract_conversions(actions):
    """Extract purchase, lead, and other conversion actions from the actions list."""
    if not actions:
        return {}
    conversions = {}
    for action in actions:
        action_type = action.get("action_type", "")
        value = int(action.get("value", 0))
        if action_type in ("purchase", "lead", "complete_registration", "add_to_cart",
                           "initiate_checkout", "add_payment_info", "subscribe",
                           "offsite_conversion.fb_pixel_purchase",
                           "offsite_conversion.fb_pixel_lead"):
            conversions[action_type] = conversions.get(action_type, 0) + value
    return conversions


def build_attribution_params(days=30, level="campaign"):
    """Build API params for attribution window breakdown."""
    start_date, end_date = compute_date_range(days)
    return {
        "time_range": {"since": start_date, "until": end_date},
        "level": level,
        "action_breakdowns": ["action_type"],
        "action_attribution_windows": ["1d_click", "7d_click", "1d_view"],
    }


def fetch_insights(account_id, access_token, days=30, level="campaign",
                   breakdown=None, time_increment=None):
    """Fetch insights from Meta Marketing API."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    start_date, end_date = compute_date_range(days)

    params = {
        "time_range": {"since": start_date, "until": end_date},
        "level": level,
    }

    if time_increment:
        params["time_increment"] = time_increment  # "1" for daily, "7" for weekly
    elif breakdown == "time":
        params["time_increment"] = "1"

    breakdown_fields = []
    if breakdown and breakdown != "time" and breakdown in BREAKDOWNS:
        breakdown_fields = BREAKDOWNS[breakdown]
        params["breakdowns"] = breakdown_fields

    insights = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_insights(fields=METRICS, params=params))
    )
    return [meta_campaigns.to_plain(dict(i)) for i in insights]


def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Ads insights")
    parser.add_argument("--account", required=True, help="Ad account ID (e.g., act_123456)")
    parser.add_argument("--days", type=int, default=30, help="Number of days to look back (default: 30)")
    parser.add_argument("--level", choices=["account", "campaign", "adset", "ad"], default="campaign",
                        help="Reporting level (default: campaign)")
    parser.add_argument("--breakdown", choices=list(BREAKDOWNS.keys()), help="Breakdown dimension")
    parser.add_argument("--daily", action="store_true", help="Show daily time series")
    parser.add_argument("--attribution", action="store_true",
                        help="Break down conversions by attribution window (1d click, 7d click, 1d view)")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    parser.add_argument("--json", action="store_true", default=True, help="Output as JSON")

    args = parser.parse_args()
    account_id = args.account

    creds = meta_auth.load_credentials()
    if not creds:
        print(json.dumps({"status": "error", "message": "No credentials. Run meta_auth.py first"}))
        sys.exit(1)

    token = creds["access_token"]
    cache_key = f"insights_{args.level}_{args.days}d"
    if args.breakdown:
        cache_key += f"_{args.breakdown}"

    if not args.no_cache:
        cached = meta_campaigns.read_cache(args.account, cache_key)
        if cached:
            print(json.dumps(cached, indent=2))
            return

    time_increment = "1" if args.daily else None

    if args.attribution:
        cache_key = f"insights_{args.level}_{args.days}d_attribution"
        if not args.no_cache:
            cached = meta_campaigns.read_cache(args.account, cache_key)
            if cached:
                print(json.dumps(cached, indent=2))
                return

        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.adaccount import AdAccount
        api = FacebookAdsApi.init(access_token=token)
        account = AdAccount(account_id, api=api)

        params = build_attribution_params(args.days, args.level)
        raw = list(account.get_insights(fields=METRICS, params=params))
        raw = [meta_campaigns.to_plain(dict(r)) for r in raw]

        result = {
            "status": "ok",
            "account_id": account_id,
            "days": args.days,
            "level": args.level,
            "attribution_windows": ["1d_click", "7d_click", "1d_view"],
            "total_rows": len(raw),
            "data": raw,
        }
        meta_campaigns.write_cache(account_id, cache_key, result)
        print(json.dumps(result, indent=2))
        return

    raw = fetch_insights(args.account, token, args.days, args.level, args.breakdown, time_increment)

    result = {
        "status": "ok",
        "account_id": args.account,
        "days": args.days,
        "level": args.level,
        "breakdown": args.breakdown,
        "total_rows": len(raw),
        "data": raw,
    }

    if not args.breakdown and not args.daily:
        result["summary"] = aggregate_metrics(raw)

    meta_campaigns.write_cache(args.account, cache_key, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
