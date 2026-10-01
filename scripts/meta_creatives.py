#!/usr/bin/env python3
"""Fetch Meta Ads creative assets and detect creative fatigue."""

import argparse
import json
import sys

import meta_auth
import meta_campaigns
import meta_utils


def detect_format(creative):
    """Detect creative format: image, video, carousel, or unknown.

    Reads the creative's object_story_spec first, since it says what the ad
    is built from, then object_type, then the flat image and video fields.
    """
    # effective_object_story_spec is not an API field. It is still read so
    # that data assembled by earlier versions keeps classifying the same way.
    for key in ("object_story_spec", "effective_object_story_spec"):
        spec = creative.get(key) or {}
        if spec.get("video_data"):
            return "video"
        if (spec.get("link_data") or {}).get("child_attachments"):
            return "carousel"
        if spec.get("photo_data"):
            return "image"

    obj_type = (creative.get("object_type") or "").upper()
    if obj_type == "VIDEO":
        return "video"
    if obj_type == "PHOTO":
        return "image"

    if creative.get("video_id"):
        return "video"
    if creative.get("image_url") or creative.get("image_hash"):
        return "image"

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


FATIGUE_DAILY_FIELDS = ["ad_id", "ad_name", "adset_id", "campaign_id",
                        "spend", "impressions", "clicks"]
FATIGUE_TOTAL_FIELDS = ["ad_id", "impressions", "reach", "frequency", "spend"]

# The thresholds the creative agent has always documented: fatigued above
# frequency 3.0 with CTR down more than 20%, near fatigue above 2.5 with
# CTR down more than 10%.
FATIGUED = {"frequency": 3.0, "ctr_change": -0.20}
NEAR_FATIGUE = {"frequency": 2.5, "ctr_change": -0.10}

ROTATION_ADVICE = {
    "fatigued": "Rotate: replace this creative or pause it in favour of a fresh one.",
    "near_fatigue": "Prepare a replacement. Rotate if CTR keeps falling.",
    "ok": "Keep running.",
}


def fatigue_window(days, today=None):
    """The last `days` complete days and the date the second half starts on."""
    from datetime import date, timedelta

    today = today or date.today()
    since = today - timedelta(days=days)
    until = today - timedelta(days=1)
    second_half_start = since + timedelta(days=days // 2)
    return since.isoformat(), until.isoformat(), second_half_start.isoformat()


def _half_rates(rows):
    """CTR (percent) and CPM over a list of daily rows."""
    impressions = sum(int(r.get("impressions", 0)) for r in rows)
    clicks = sum(int(r.get("clicks", 0)) for r in rows)
    spend = sum(float(r.get("spend", 0)) for r in rows)
    if not impressions:
        return 0, None, None
    return impressions, clicks / impressions * 100, spend / impressions * 1000


def fatigue_status(frequency, ctr_change):
    """Classify an ad from its period frequency and its CTR change."""
    for status, limit in (("fatigued", FATIGUED), ("near_fatigue", NEAR_FATIGUE)):
        if frequency > limit["frequency"] and ctr_change < limit["ctr_change"]:
            return status
    return "ok"


def score_fatigue(daily_rows, total_rows, days, min_impressions=1000, today=None):
    """Score each ad's fatigue from its trend over the period.

    Splits the period in two halves and compares CTR and CPM between them.
    Frequency is the period figure from the API, because daily frequency
    does not add up. An ad needs min_impressions in each half to be scored;
    below that the CTR of a half is noise.
    """
    since, until, second_half_start = fatigue_window(days, today)
    totals = {row["ad_id"]: row for row in total_rows}
    by_ad = {}
    for row in daily_rows:
        by_ad.setdefault(row["ad_id"], []).append(row)

    ads, not_scored = [], []
    for ad_id in sorted(by_ad):
        rows = by_ad[ad_id]
        first = [r for r in rows if r["date_start"] < second_half_start]
        second = [r for r in rows if r["date_start"] >= second_half_start]
        imp_first, ctr_first, cpm_first = _half_rates(first)
        imp_second, ctr_second, cpm_second = _half_rates(second)
        identity = {
            "ad_id": ad_id,
            "ad_name": rows[0].get("ad_name"),
            "adset_id": rows[0].get("adset_id"),
            "campaign_id": rows[0].get("campaign_id"),
        }
        total = totals.get(ad_id)
        if min(imp_first, imp_second) < min_impressions:
            not_scored.append({**identity, "reason": "too few impressions in one half",
                               "impressions_first_half": imp_first,
                               "impressions_second_half": imp_second})
            continue
        if not total or not ctr_first:
            not_scored.append({**identity, "reason": "no period totals or no clicks to compare"})
            continue

        frequency = float(total.get("frequency", 0))
        ctr_change = (ctr_second - ctr_first) / ctr_first
        cpm_change = (cpm_second - cpm_first) / cpm_first if cpm_first else None
        status = fatigue_status(frequency, ctr_change)
        ads.append({
            **identity,
            "spend": round(float(total.get("spend", 0)), 2),
            "impressions": int(total.get("impressions", 0)),
            "reach": int(total.get("reach", 0)),
            "frequency": round(frequency, 2),
            "ctr_first_half": round(ctr_first, 3),
            "ctr_second_half": round(ctr_second, 3),
            "ctr_change": round(ctr_change, 3),
            "cpm_first_half": round(cpm_first, 2),
            "cpm_second_half": round(cpm_second, 2),
            "cpm_change": round(cpm_change, 3) if cpm_change is not None else None,
            "fatigue_score": fatigue_score(frequency, ctr_change),
            "status": status,
            "recommendation": ROTATION_ADVICE[status],
        })

    ads.sort(key=lambda a: (-a["fatigue_score"], a["ad_id"]))
    return {
        "window": {"since": since, "until": until, "days": days,
                   "second_half_starts": second_half_start},
        "min_impressions_per_half": min_impressions,
        "summary": {
            "scored": len(ads),
            "fatigued": sum(1 for a in ads if a["status"] == "fatigued"),
            "near_fatigue": sum(1 for a in ads if a["status"] == "near_fatigue"),
            "not_scored": len(not_scored),
        },
        "ads": ads,
        "not_scored": not_scored,
    }


def fetch_fatigue_inputs(account_id, access_token, days, no_cache=False):
    """Fetch daily and period ad insights for fatigue scoring, through the cache."""
    from facebook_business.adobjects.adaccount import AdAccount

    api = meta_utils.init_api(access_token)
    account = AdAccount(account_id, api=api)
    since, until, _ = fatigue_window(days)
    params = {"time_range": {"since": since, "until": until}, "level": "ad", "limit": 500}
    retry = meta_campaigns.api_call_with_retry
    plain = meta_campaigns.to_plain

    daily = meta_utils.cached(
        account_id, f"creatives_fatigue_daily_{days}d", no_cache=no_cache,
        fetch=lambda: retry(lambda: [
            plain(dict(r)) for r in account.get_insights(
                fields=FATIGUE_DAILY_FIELDS, params={**params, "time_increment": "1"})]))
    totals = meta_utils.cached(
        account_id, f"creatives_fatigue_totals_{days}d", no_cache=no_cache,
        fetch=lambda: retry(lambda: [
            plain(dict(r)) for r in account.get_insights(
                fields=FATIGUE_TOTAL_FIELDS, params=params)]))
    return daily, totals


def fetch_creatives(account_id, access_token):
    """Fetch all ad creatives for an account."""
    from facebook_business.adobjects.adaccount import AdAccount

    api = meta_utils.init_api(access_token)
    account = AdAccount(account_id, api=api)

    fields = [
        "id", "name", "title", "body", "image_url", "image_hash",
        "video_id", "thumbnail_url", "object_story_spec", "object_type",
        "call_to_action_type", "link_url", "status",
    ]
    creatives = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_ad_creatives(fields=fields))
    )
    return [meta_campaigns.to_plain(dict(c)) for c in creatives]


def fetch_creatives_with_metrics(account_id, access_token, days=30):
    """Fetch creatives joined with per-ad performance metrics."""
    from datetime import date, timedelta

    from facebook_business.adobjects.adaccount import AdAccount

    api = meta_utils.init_api(access_token)
    account = AdAccount(account_id, api=api)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Fetch ad-level insights
    params = {
        "time_range": {"since": start_date.isoformat(), "until": end_date.isoformat()},
        "level": "ad",
    }
    fields = ["ad_id", "ad_name", "spend", "impressions", "clicks", "ctr", "frequency", "actions"]
    insights = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_insights(fields=fields, params=params))
    )

    # Fetch creatives
    creatives = fetch_creatives(account_id, access_token)
    creative_map = {c["id"]: c for c in creatives}

    # Fetch ads to link creative IDs
    ads = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_ads(fields=["id", "creative"]))
    )
    ad_to_creative = {}
    for ad in ads:
        ad_dict = meta_campaigns.to_plain(dict(ad))
        cid = ad_dict.get("creative", {}).get("id")
        if cid:
            ad_to_creative[ad_dict["id"]] = cid

    # Join insights with creatives
    result = []
    for insight in insights:
        ad_id = insight.get("ad_id")
        creative_id = ad_to_creative.get(ad_id)
        creative = creative_map.get(creative_id, {})
        entry = {
            "ad_id": ad_id,
            "ad_name": insight.get("ad_name"),
            "creative_id": creative_id,
            "format": detect_format(creative),
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
    parser.add_argument("--account", required=True, type=meta_utils.account_id_arg,
                        help="Ad account ID")
    parser.add_argument("--with-metrics", action="store_true", help="Include performance metrics")
    parser.add_argument("--fatigue", action="store_true",
                        help="Score creative fatigue per ad from the trend over the period")
    parser.add_argument("--days", type=int,
                        help="Days to look back (default: 30, or 14 with --fatigue)")
    parser.add_argument("--min-impressions", type=int, default=1000,
                        help="With --fatigue: impressions an ad needs in each half of the "
                             "period to be scored (default: 1000)")
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

    if args.fatigue:
        days = args.days or 14
        daily, totals = fetch_fatigue_inputs(args.account, token, days, args.no_cache)
        result = {"status": "ok", "account_id": args.account,
                  **score_fatigue(daily, totals, days, args.min_impressions)}
        print(json.dumps(result, indent=2))
        return

    args.days = args.days or 30

    # The metrics depend on the lookback, so --days is part of that key.
    cache_key =f"creatives_metrics_{args.days}d" if args.with_metrics else "creatives_basic"

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
    meta_utils.run_cli(main)
