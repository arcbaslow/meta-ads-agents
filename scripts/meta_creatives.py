#!/usr/bin/env python3
"""Fetch Meta Ads creative assets and detect creative fatigue."""

import argparse
import json
import sys

import meta_auth
import meta_campaigns


def detect_format(creative):
    """Detect creative format: image, video, carousel, or unknown.

    Checks effective_object_story_spec first (most reliable from ads endpoint),
    then object_type, then legacy creative fields as fallback.
    """
    # Check effective_object_story_spec (from ads endpoint)
    ess = creative.get("effective_object_story_spec", {})
    if ess.get("video_data"):
        return "video"
    if ess.get("photo_data"):
        return "image"
    link_data = ess.get("link_data", {})
    if link_data.get("child_attachments"):
        return "carousel"

    # Check object_type field
    obj_type = creative.get("object_type", "").upper()
    if obj_type == "VIDEO":
        return "video"
    if obj_type == "PHOTO":
        return "image"

    # Legacy creative fields fallback
    if creative.get("video_id"):
        return "video"
    if creative.get("image_url"):
        return "image"

    # Check object_story_spec (old path)
    oss = creative.get("object_story_spec", {})
    if oss.get("video_data"):
        return "video"
    if oss.get("link_data", {}).get("child_attachments"):
        return "carousel"

    return "unknown"


def fatigue_score(frequency, ctr_trend):
    """Calculate creative fatigue score (0.0 = fresh, 1.0 = exhausted).

    Args:
        frequency: Average frequency of the ad
        ctr_trend: CTR change as a decimal (e.g., -0.3 means 30% decline)
    """
    # Frequency component: starts contributing after frequency > 2
    freq_score = min(max((frequency - 2) / 5, 0), 1.0)

    # CTR decline component: negative trend increases fatigue
    ctr_score = min(max(abs(ctr_trend) / 0.5, 0), 1.0) if ctr_trend < 0 else 0

    # Weighted combination
    return round(freq_score * 0.4 + ctr_score * 0.6, 2)


def fetch_creatives(account_id, access_token):
    """Fetch all ad creatives for an account."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    fields = [
        "id", "name", "title", "body", "image_url", "image_hash",
        "video_id", "thumbnail_url", "object_story_spec",
        "call_to_action_type", "link_url", "status",
    ]
    creatives = list(account.get_ad_creatives(fields=fields))
    return [meta_campaigns.to_plain(dict(c)) for c in creatives]


def fetch_creatives_with_metrics(account_id, access_token, days=30):
    """Fetch creatives joined with per-ad performance metrics."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount
    from datetime import date, timedelta

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Fetch ad-level insights
    params = {
        "time_range": {"since": start_date.isoformat(), "until": end_date.isoformat()},
        "level": "ad",
    }
    fields = ["ad_id", "ad_name", "spend", "impressions", "clicks", "ctr", "frequency", "actions"]
    insights = list(account.get_insights(fields=fields, params=params))

    # Fetch creatives
    creatives = fetch_creatives(account_id, access_token)
    creative_map = {c["id"]: c for c in creatives}

    # Fetch ads to link creative IDs
    ads = list(account.get_ads(fields=["id", "creative", "effective_object_story_spec"]))
    ad_to_creative = {}
    ad_ess = {}
    for ad in ads:
        ad_dict = meta_campaigns.to_plain(dict(ad))
        cid = ad_dict.get("creative", {}).get("id")
        if cid:
            ad_to_creative[ad_dict["id"]] = cid
        ess = ad_dict.get("effective_object_story_spec", {})
        if ess:
            ad_ess[ad_dict["id"]] = ess

    # Join insights with creatives
    result = []
    for insight in insights:
        ad_id = insight.get("ad_id")
        creative_id = ad_to_creative.get(ad_id)
        creative = creative_map.get(creative_id, {})
        # Merge effective_object_story_spec from ad into creative for format detection
        merged = {**creative}
        if ad_id in ad_ess:
            merged["effective_object_story_spec"] = ad_ess[ad_id]
        entry = {
            "ad_id": ad_id,
            "ad_name": insight.get("ad_name"),
            "creative_id": creative_id,
            "format": detect_format(merged),
            "title": creative.get("title"),
            "body": creative.get("body"),
            "image_url": creative.get("image_url"),
            "thumbnail_url": creative.get("thumbnail_url"),
            "call_to_action": creative.get("call_to_action_type"),
            "spend": float(insight.get("spend", 0)),
            "impressions": int(insight.get("impressions", 0)),
            "clicks": int(insight.get("clicks", 0)),
            "ctr": float(insight.get("ctr", 0)),
            "frequency": float(insight.get("frequency", 0)),
        }
        result.append(entry)

    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Ads creatives")
    parser.add_argument("--account", required=True, help="Ad account ID")
    parser.add_argument("--with-metrics", action="store_true", help="Include performance metrics")
    parser.add_argument("--days", type=int, default=30, help="Days to look back for metrics")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    parser.add_argument("--json", action="store_true", default=True)

    args = parser.parse_args()

    creds = meta_auth.load_credentials()
    if not creds:
        print(json.dumps({"status": "error", "message": "No credentials"}))
        sys.exit(1)

    token = creds["access_token"]
    cache_key = f"creatives_{'metrics' if args.with_metrics else 'basic'}"

    if not args.no_cache:
        cached = meta_campaigns.read_cache(args.account, cache_key)
        if cached:
            print(json.dumps(cached, indent=2))
            return

    if args.with_metrics:
        data = fetch_creatives_with_metrics(args.account, token, args.days)
    else:
        data = fetch_creatives(args.account, token)

    result = {
        "status": "ok",
        "account_id": args.account,
        "total_creatives": len(data),
        "creatives": data,
    }

    meta_campaigns.write_cache(args.account, cache_key, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
