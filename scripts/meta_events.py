#!/usr/bin/env python3
"""Fetch Meta Pixel/CAPI event data and analyze conversion funnels."""

import argparse
import json
import logging
import sys

import meta_auth
import meta_campaigns
import meta_utils

logger = logging.getLogger("meta_ads")

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


# Insights reports website pixel events as offsite_conversion.fb_pixel_<event>.
# Names from the AdsActionStats reference:
# https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/
_PIXEL_ACTION_PREFIX = "offsite_conversion.fb_pixel_"
_PIXEL_ACTION_EVENTS = {
    "view_content": "ViewContent",
    "search": "Search",
    "add_to_cart": "AddToCart",
    "add_to_wishlist": "AddToWishlist",
    "initiate_checkout": "InitiateCheckout",
    "add_payment_info": "AddPaymentInfo",
    "purchase": "Purchase",
    "lead": "Lead",
    "complete_registration": "CompleteRegistration",
}


def website_event_name(action_type):
    """Map an insights action type to the pixel event it counts.

    Returns the standard event name for offsite_conversion.fb_pixel_<event>,
    the action type itself for custom pixel events and custom conversions,
    and None for anything that is not a website event (link clicks, post
    engagement, the omni_ and on-Facebook groupings).
    """
    if not action_type.startswith("offsite_conversion."):
        return None
    if action_type.startswith(_PIXEL_ACTION_PREFIX):
        suffix = action_type[len(_PIXEL_ACTION_PREFIX):]
        return _PIXEL_ACTION_EVENTS.get(suffix, action_type)
    return action_type


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
    """Fetch the website events attributed to the account's ads.

    These are insights actions, so they count events credited to an ad
    within the attribution window, not everything the pixel received.
    PageView is never among them. Raw pixel volumes are in the health
    check's event_sources.
    """
    from datetime import date, timedelta

    from facebook_business.adobjects.adaccount import AdAccount

    api = meta_utils.init_api(access_token)
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
            name = website_event_name(action.get("action_type", ""))
            if name is None:
                continue
            count = int(float(action.get("value", 0)))
            event_counts[name] = event_counts.get(name, 0) + count
        for action in insight.get("action_values", []):
            name = website_event_name(action.get("action_type", ""))
            if name is None:
                continue
            value = float(action.get("value", 0))
            event_values[name] = event_values.get(name, 0) + value

    return event_counts, event_values


def sum_event_counts(stats):
    """Total the per-event counts in a pixel stats response.

    The stats edge returns one row per hour. With aggregation=event each
    row's data list holds {"value": <event name>, "count": <n>} entries.
    """
    totals = {}
    for row in stats:
        for entry in row.get("data", []):
            name = entry.get("value") or entry.get("event")
            if not name:
                continue
            totals[name] = totals.get(name, 0) + int(entry.get("count", 0) or 0)
    return totals


def fetch_event_sources(pixel, days=3):
    """Count a pixel's events separately for the browser and the server.

    The stats rows carry no source field, so the split comes from the
    edge's event_source filter: WEB_ONLY for the browser pixel and
    SERVER_ONLY for the Conversions API.

    Returns a dict of event name -> {"browser": n, "server": n}.
    """
    from datetime import date, timedelta

    sources = {}
    for label, event_source in (("browser", "WEB_ONLY"), ("server", "SERVER_ONLY")):
        params = {
            "aggregation": "event",
            "event_source": event_source,
            "start_time": (date.today() - timedelta(days=days)).isoformat(),
            "end_time": date.today().isoformat(),
        }
        stats = meta_campaigns.api_call_with_retry(
            lambda: [meta_campaigns.to_plain(dict(s)) for s in pixel.get_stats(params=params)]
        )
        for name, count in sum_event_counts(stats).items():
            sources.setdefault(name, {"browser": 0, "server": 0})[label] = count
    return sources


def fetch_pixel_health(account_id, access_token):
    """Check pixel configuration and health status, including CAPI detection."""
    from facebook_business.adobjects.adaccount import AdAccount
    from facebook_business.adobjects.adspixel import AdsPixel

    api = meta_utils.init_api(access_token)
    account = AdAccount(account_id, api=api)

    pixel_fields = [
        "id", "name", "is_unavailable", "data_use_setting",
        "creation_time", "last_fired_time",
    ]
    pixels = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_ads_pixels(fields=pixel_fields))
    )

    pixel_data = []
    for pixel in pixels:
        pixel_dict = meta_campaigns.to_plain(dict(pixel))
        pixel_data.append(pixel_health(pixel_dict, AdsPixel(pixel_dict["id"], api=api)))

    return pixel_data


def pixel_health(pixel_dict, pixel):
    """Add CAPI status and the browser/server event split to one pixel."""
    try:
        sources = fetch_event_sources(pixel)
    except Exception as e:
        # Unknown is not the same as absent. Reporting has_capi False here
        # would tell the reader to set up something they may already have.
        reason = meta_utils.error_text(e)
        logger.warning("CAPI detection failed for pixel %s: %s", pixel_dict.get("id"), reason)
        return {
            **pixel_dict,
            "has_capi": None,
            "server_events": [],
            "event_sources": {},
            "capi_check_error": reason,
        }

    server_events = [
        {"event_name": name, "source": "server"}
        for name, counts in sorted(sources.items()) if counts["server"] > 0
    ]
    result = detect_capi_status(pixel_dict, server_events)
    result["event_sources"] = sources
    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Pixel/CAPI event data")
    parser.add_argument("--account", required=True, type=meta_utils.account_id_arg,
                        help="Ad account ID")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--health-check", action="store_true", help="Quick pixel health status")
    parser.add_argument("--funnel", action="store_true", help="Build conversion funnel")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    # Accepted as a no-op: every adapter already prints JSON to stdout.
    # All seven agent definitions and the audit skill pass --json, matching
    # the gsc/ga4/gads convention, and without this each one exits 2 on its
    # first command.
    parser.add_argument("--json", action="store_true",
                        help="No-op; output is always JSON. Accepted for consistency.")

    args = parser.parse_args()

    token = meta_auth.get_access_token()
    if not token:
        print(json.dumps({"status": "error", "message": meta_auth.NO_TOKEN_MESSAGE}))
        sys.exit(1)

    if args.health_check:
        cache_key = "pixel_health"
        if not args.no_cache:
            cached = meta_campaigns.read_cache(args.account, cache_key)
            if cached:
                print(json.dumps(cached, indent=2))
                return

        pixels = fetch_pixel_health(args.account, token)
        result = {
            "status": "ok",
            "account_id": args.account,
            "pixels": pixels,
        }
        meta_campaigns.write_cache(args.account, cache_key, result)
    else:
        cache_key = f"events_{args.days}d" + ("_funnel" if args.funnel else "")
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
    meta_utils.run_cli(main)
