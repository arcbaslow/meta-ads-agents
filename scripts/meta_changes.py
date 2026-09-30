#!/usr/bin/env python3
"""Line up the account's change history with performance before and after each change.

Reads the ad account activity log and daily insights, then reports, for
every change to a campaign, ad set or ad, how that entity performed in
the days before and after. It answers "what changed before this dropped".
It shows what moved together. It does not prove that a change caused a
shift, and it changes nothing in the account.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone

import meta_auth
import meta_campaigns
import meta_utils

ACTIVITY_FIELDS = [
    "event_time", "event_type", "translated_event_type", "object_id", "object_name",
    "object_type", "actor_name", "application_name", "extra_data",
]
INSIGHT_FIELDS = ["campaign_id", "adset_id", "spend", "impressions", "clicks", "actions"]
# The metrics whose change can flag a shift. cpa is only present with --action-type.
SHIFT_METRICS = ["spend_per_day", "cpm", "ctr", "cpa"]


def parse_extra_data(raw):
    """extra_data is a JSON string. Return it parsed, or as given if it is not JSON."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def event_day(event_time):
    """The UTC date of a log entry as YYYY-MM-DD, or None if it cannot be read.

    The API returns an ISO 8601 string. A Unix timestamp is accepted too.
    """
    text = str(event_time or "")
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc).date().isoformat()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def group_changes(activities):
    """Merge the log entries for one object on one day into a single change.

    One edit in Ads Manager often writes several entries. Evaluating each
    would repeat the same before and after numbers.
    """
    groups = {}
    # Sorted first, so that the name a group takes and the order of its
    # events do not depend on the order the API returned the entries in.
    for entry in sorted(activities, key=lambda e: json.dumps(e, sort_keys=True, default=str)):
        object_id = entry.get("object_id")
        day = event_day(entry.get("event_time"))
        if not object_id or not day:
            continue
        event_time = str(entry["event_time"])
        key = (day, str(object_id))
        group = groups.setdefault(key, {
            "date": key[0],
            "object_id": key[1],
            "object_name": entry.get("object_name"),
            "object_type": entry.get("object_type"),
            "events": [],
        })
        group["events"].append({
            "event_time": event_time,
            "event_type": entry.get("event_type"),
            "description": entry.get("translated_event_type"),
            "actor": entry.get("actor_name"),
            "application": entry.get("application_name"),
            "extra_data": parse_extra_data(entry.get("extra_data")),
        })
    for group in groups.values():
        group["events"].sort(key=lambda e: (e["event_time"], e["event_type"] or ""))
    return [groups[key] for key in sorted(groups)]


def index_rows(rows):
    """Map each campaign, ad set and ad ID to its level and its daily rows."""
    series, levels = {}, {}
    for row in rows:
        for level, field in (("campaign", "campaign_id"), ("adset", "adset_id"), ("ad", "ad_id")):
            entity_id = row.get(field)
            if entity_id:
                series.setdefault(str(entity_id), []).append(row)
                levels[str(entity_id)] = level
    return series, levels


def window_metrics(rows, first, last, action_type=None):
    """Totals and rates for the rows dated first..last inclusive."""
    days = (last - first).days + 1
    spend = impressions = clicks = results = 0.0
    for row in rows:
        if not row.get("date_start"):
            continue
        day = date.fromisoformat(row["date_start"][:10])
        if not first <= day <= last:
            continue
        spend += float(row.get("spend", 0))
        impressions += float(row.get("impressions", 0))
        clicks += float(row.get("clicks", 0))
        if action_type:
            for action in row.get("actions") or []:
                if action.get("action_type") == action_type:
                    results += float(action.get("value", 0))

    metrics = {
        "days": days,
        "spend": round(spend, 2),
        "spend_per_day": round(spend / days, 2),
        "impressions": int(impressions),
        "cpm": round(spend / impressions * 1000, 2) if impressions else None,
        "ctr": round(clicks / impressions * 100, 3) if impressions else None,
    }
    if action_type:
        metrics["results"] = results
        metrics["cpa"] = round(spend / results, 2) if results else None
    return metrics


def percent_changes(before, after):
    """Percentage change per shift metric. None where either side is missing or zero."""
    changes = {}
    for metric in SHIFT_METRICS:
        if metric not in before:
            continue
        old, new = before[metric], after[metric]
        changes[metric] = round((new - old) / old * 100, 1) if old and new is not None else None
    return changes


def evaluate_change(group, rows, level, window, data_until, threshold, action_type=None):
    """Compare the `window` days before a change with the `window` days after it.

    The day of the change is in neither side. Returns the evaluated change,
    or None with a reason when there are no complete days after it yet.
    """
    changed_on = date.fromisoformat(group["date"])
    before = (changed_on - timedelta(days=window), changed_on - timedelta(days=1))
    after_last = min(changed_on + timedelta(days=window), data_until)
    if after_last <= changed_on:
        return None, "no complete day after the change yet"

    before_metrics = window_metrics(rows, before[0], before[1], action_type)
    after_metrics = window_metrics(rows, changed_on + timedelta(days=1), after_last, action_type)
    changes = percent_changes(before_metrics, after_metrics)
    moved = {m: pct for m, pct in changes.items() if pct is not None and abs(pct) >= threshold}
    largest = max(moved, key=lambda m: (abs(moved[m]), m)) if moved else None
    return {
        **group,
        "level": level,
        # Pausing or resuming moves spend by itself, so the reader should
        # not treat that shift as a finding.
        "status_changed": any("run_status" in (e["event_type"] or "") for e in group["events"]),
        "before": before_metrics,
        "after": after_metrics,
        "change_pct": changes,
        "shifted": bool(moved),
        "largest_shift": {"metric": largest, "change_pct": moved[largest]} if largest else None,
    }, None


def correlate(activities, rows, level, days, window, threshold, action_type=None, today=None):
    """Build the change report from fetched data. Pure: no API calls."""
    today = today or date.today()
    data_until = today - timedelta(days=1)
    # Float sums depend on the order of their terms, so the rows are put in
    # a fixed order before anything is added up.
    rows = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    series, levels = index_rows(rows)

    changes, account_events, skipped = [], [], []
    for group in group_changes(activities):
        object_id = group["object_id"]
        if object_id not in series:
            account_events.append(group)
            continue
        change, reason = evaluate_change(group, series[object_id], levels[object_id], window,
                                         data_until, threshold, action_type)
        if change is None:
            skipped.append({"date": group["date"], "object_id": object_id,
                            "object_name": group["object_name"], "reason": reason})
        else:
            changes.append(change)

    # How many other changes touched the same entity close by. A shift next
    # to several changes cannot be pinned on one of them.
    for change in changes:
        day = date.fromisoformat(change["date"])
        change["other_changes_in_window"] = sum(
            1 for other in changes
            if other is not change and other["object_id"] == change["object_id"]
            and abs((date.fromisoformat(other["date"]) - day).days) <= window)

    changes.sort(key=lambda c: (c["date"], c["object_id"]), reverse=True)
    shifted = sorted(
        (c for c in changes if c["shifted"]),
        key=lambda c: (-abs(c["largest_shift"]["change_pct"]), c["date"], c["object_id"]))
    return {
        "status": "ok",
        "period": {"since": (today - timedelta(days=days)).isoformat(),
                   "until": data_until.isoformat(), "days": days},
        "level": level,
        "comparison_window_days": window,
        "shift_threshold_pct": threshold,
        "action_type": action_type,
        "summary": {
            "changes": len(changes),
            "changes_followed_by_a_shift": len(shifted),
            "not_evaluated": len(skipped),
            "unmatched_log_entries": len(account_events),
        },
        "shifts": [
            {"date": c["date"], "object_id": c["object_id"], "object_name": c["object_name"],
             "level": c["level"], "events": [e["event_type"] for e in c["events"]],
             **c["largest_shift"], "status_changed": c["status_changed"],
             "other_changes_in_window": c["other_changes_in_window"]}
            for c in shifted
        ],
        "changes": changes,
        "not_evaluated": skipped,
        # Entries for objects with no insights rows at this level: the
        # account itself, audiences, entities that did not deliver in the
        # period, and ads when --level is adset.
        "unmatched_log_entries": account_events,
    }


def fetch_inputs(account_id, access_token, days, window, level, no_cache=False):
    """Fetch the activity log and the daily insights, both through the cache."""
    from facebook_business.adobjects.adaccount import AdAccount

    api = meta_utils.init_api(access_token)
    account = AdAccount(account_id, api=api)
    today = date.today()
    retry = meta_campaigns.api_call_with_retry
    plain = meta_campaigns.to_plain

    activity_params = {
        "since": (today - timedelta(days=days)).isoformat(),
        "until": today.isoformat(),
        "limit": 500,
    }
    # The insights reach further back than the log so that the earliest
    # change still has a full "before" window.
    insight_params = {
        "time_range": {"since": (today - timedelta(days=days + window)).isoformat(),
                       "until": (today - timedelta(days=1)).isoformat()},
        "level": level,
        "time_increment": "1",
        "limit": 500,
    }
    insight_fields = INSIGHT_FIELDS + (["ad_id"] if level == "ad" else [])

    activities = meta_utils.cached(
        account_id, f"changes_activities_{days}d", no_cache=no_cache,
        fetch=lambda: retry(lambda: [
            plain(dict(a))
            for a in account.get_activities(fields=ACTIVITY_FIELDS, params=activity_params)]))
    rows = meta_utils.cached(
        account_id, f"changes_insights_{level}_{days}d_{window}w", no_cache=no_cache,
        fetch=lambda: retry(lambda: [
            plain(dict(r))
            for r in account.get_insights(fields=insight_fields, params=insight_params)]))
    return activities, rows


def main():
    parser = argparse.ArgumentParser(
        description="Correlate the Meta Ads activity log with performance shifts")
    parser.add_argument("--account", required=True, type=meta_utils.account_id_arg,
                        help="Ad account ID (e.g., act_123456)")
    parser.add_argument("--days", type=int, default=14,
                        help="Days of change history to read (default: 14)")
    parser.add_argument("--window", type=int, default=3,
                        help="Days compared before and after each change (default: 3)")
    parser.add_argument("--level", choices=["adset", "ad"], default="adset",
                        help="Lowest level to evaluate. 'ad' also covers changes to ads "
                             "and returns more rows (default: adset)")
    parser.add_argument("--threshold", type=float, default=30.0,
                        help="Percent change that counts as a shift (default: 30)")
    parser.add_argument("--action-type",
                        help="Insights action type to count as the result, for example "
                             "offsite_conversion.fb_pixel_purchase. Adds results and CPA.")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache, fetch fresh data")
    parser.add_argument("--json", action="store_true",
                        help="No-op; output is always JSON. Accepted for consistency.")
    args = parser.parse_args()

    token = meta_auth.get_access_token()
    if not token:
        print(json.dumps({"status": "error", "message": meta_auth.NO_TOKEN_MESSAGE}))
        sys.exit(1)

    activities, rows = fetch_inputs(args.account, token, args.days, args.window, args.level,
                                    args.no_cache)
    result = correlate(activities, rows, args.level, args.days, args.window, args.threshold,
                       args.action_type)
    result["account_id"] = args.account
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    meta_utils.run_cli(main)
