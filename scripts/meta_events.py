#!/usr/bin/env python3
"""Fetch Meta Pixel/CAPI event data and analyze conversion funnels."""

import argparse
import json
import sys

import meta_auth
import meta_campaigns

STANDARD_EVENTS = {
    "PageView", "ViewContent", "Search", "AddToCart", "AddToWishlist",
    "InitiateCheckout", "AddPaymentInfo", "Purchase", "Lead",
    "CompleteRegistration", "Contact", "CustomizeProduct",
    "Donate", "FindLocation", "Schedule", "StartTrial",
    "SubmitApplication", "Subscribe",
}

FUNNEL_ORDER = [
    "PageView", "ViewContent", "Search", "AddToCart",
    "InitiateCheckout", "AddPaymentInfo", "Purchase",
]


def classify_event(event_name):
    """Classify event as standard or custom."""
    if event_name in STANDARD_EVENTS:
        return "standard"
    return "custom"


def detect_capi_status(pixel_data, server_events):
    """Determine CAPI status from pixel data and server event list.

    Args:
        pixel_data: dict with pixel id/name
        server_events: list of dicts with event_name and source fields

    Returns:
        dict with has_capi bool, server_events list, and pixel info
    """
    server_event_names = [
        e.get("event_name") for e in server_events
        if e.get("source") == "server"
    ]
    return {
        **pixel_data,
        "has_capi": len(server_event_names) > 0,
        "server_events": server_event_names,
    }


def build_funnel(event_counts):
    """Build a conversion funnel from event counts.

    Args:
        event_counts: dict of event_name → count

    Returns:
        List of funnel steps with drop-off and conversion rates.
    """
    # Order events by funnel position
    ordered = []
    for event in FUNNEL_ORDER:
        if event in event_counts:
            ordered.append({"event": event, "count": event_counts[event]})

    # Add any non-funnel events at the end
    for event, count in event_counts.items():
        if event not in FUNNEL_ORDER:
            ordered.append({"event": event, "count": count})

    if not ordered:
        return []

    top_count = ordered[0]["count"]
    for i, step in enumerate(ordered):
        step["conversion_rate"] = round(step["count"] / top_count * 100, 1) if top_count > 0 else 0
        if i > 0:
            prev = ordered[i - 1]["count"]
            step["drop_off_pct"] = round((1 - step["count"] / prev) * 100, 1) if prev > 0 else 0
        else:
            step["drop_off_pct"] = 0

    return ordered


def fetch_pixel_events(account_id, access_token, days=7):
    """Fetch pixel event data for an ad account."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount
    from datetime import date, timedelta

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Fetch account-level insights with action breakdowns
    params = {
        "time_range": {"since": start_date.isoformat(), "until": end_date.isoformat()},
        "level": "account",
        "action_breakdowns": ["action_type"],
    }
    fields = ["actions", "action_values"]
    insights = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_insights(fields=fields, params=params))
    )

    event_counts = {}
    event_values = {}
    for insight in insights:
        for action in insight.get("actions", []):
            name = action.get("action_type", "")
            count = int(action.get("value", 0))
            event_counts[name] = event_counts.get(name, 0) + count
        for action in insight.get("action_values", []):
            name = action.get("action_type", "")
            value = float(action.get("value", 0))
            event_values[name] = event_values.get(name, 0) + value

    return event_counts, event_values


def fetch_pixel_health(account_id, access_token):
    """Check pixel configuration and health status, including CAPI detection."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    pixels = list(account.get_ads_pixels(fields=[
        "id", "name", "is_unavailable", "data_use_setting",
        "creation_time", "last_fired_time",
    ]))

    pixel_data = []
    for pixel in pixels:
        pixel_dict = meta_campaigns.to_plain(dict(pixel))

        # Try to detect CAPI by querying pixel stats for server events
        server_events = []
        try:
            from facebook_business.adobjects.adspixel import AdsPixel
            from datetime import date, timedelta
            px = AdsPixel(pixel_dict["id"], api=api)
            stats = list(px.get_stats(params={
                "aggregation": "event",
                "start_time": (date.today() - timedelta(days=3)).isoformat(),
                "end_time": date.today().isoformat(),
            }))
            for stat in stats:
                stat_dict = meta_campaigns.to_plain(dict(stat))
                for entry in stat_dict.get("data", []):
                    if entry.get("source") == "server" and entry.get("value", 0) > 0:
                        server_events.append({
                            "event_name": entry.get("event"),
                            "source": "server",
                        })
        except Exception:
            # pixel stats may require extra permissions or hit rate limits
            pass

        result = detect_capi_status(pixel_dict, server_events)
        pixel_data.append(result)

    return pixel_data


def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Pixel/CAPI event data")
    parser.add_argument("--account", required=True, help="Ad account ID")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--health-check", action="store_true", help="Quick pixel health status")
    parser.add_argument("--funnel", action="store_true", help="Build conversion funnel")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")

    args = parser.parse_args()

    creds = meta_auth.load_credentials()
    if not creds:
        print(json.dumps({"status": "error", "message": "No credentials"}))
        sys.exit(1)

    token = creds["access_token"]

    if args.health_check:
        pixels = fetch_pixel_health(args.account, token)
        result = {
            "status": "ok",
            "account_id": args.account,
            "pixels": pixels,
        }
    else:
        cache_key = f"events_{args.days}d"
        if not args.no_cache:
            cached = meta_campaigns.read_cache(args.account, cache_key)
            if cached:
                print(json.dumps(cached, indent=2))
                return

        event_counts, event_values = fetch_pixel_events(args.account, token, args.days)

        classified = {}
        for event, count in event_counts.items():
            classified[event] = {
                "count": count,
                "value": event_values.get(event, 0),
                "type": classify_event(event),
            }

        result = {
            "status": "ok",
            "account_id": args.account,
            "days": args.days,
            "total_event_types": len(classified),
            "events": classified,
        }

        if args.funnel:
            result["funnel"] = build_funnel(event_counts)

        meta_campaigns.write_cache(args.account, cache_key, result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
