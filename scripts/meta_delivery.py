#!/usr/bin/env python3
"""Diagnose stalled ad set delivery: caps below real CPA, learning status, thin budgets.

Reads ad set settings and ad set insights, then reports why an active ad
set is spending little or nothing. The checks are arithmetic on fields the
API returns. Nothing is changed in the account.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone

import meta_auth
import meta_campaigns
import meta_utils

# Currencies whose amounts the API returns in whole units. Every other
# currency is returned in hundredths (bid_amount 1250 is 12.50).
# https://developers.facebook.com/docs/marketing-api/currencies
WHOLE_UNIT_CURRENCIES = {
    "CLP", "COP", "CRC", "HUF", "ISK", "IDR", "JPY", "KRW", "PYG", "TWD", "VND",
}

# Meta's help centre: an ad set leaves the learning phase after about 50
# optimisation events in the 7 days after its last significant edit.
# https://www.facebook.com/business/help/112167992830700
# When learning_stage_info carries dynamic_lp_conversions_threshold, that
# per-ad-set number is used instead.
LEARNING_EVENTS = 50
LEARNING_DAYS = 7

CAPPED_STRATEGIES = {"COST_CAP", "LOWEST_COST_WITH_BID_CAP"}
# Paused entities are listed too: what they spent in the period still counts
# towards the account's reference CPA.
CAMPAIGN_STATUSES = ["ACTIVE", "WITH_ISSUES", "IN_PROCESS", "PAUSED"]
ADSET_STATUSES = CAMPAIGN_STATUSES + ["CAMPAIGN_PAUSED"]
DELIVERING_STATUSES = {"ACTIVE", "WITH_ISSUES"}
SEVERITY_ORDER = ["critical", "high", "medium", "info"]

ACCOUNT_FIELDS = ["id", "name", "currency", "timezone_name"]
CAMPAIGN_FIELDS = [
    "id", "name", "effective_status", "daily_budget", "lifetime_budget", "budget_remaining",
    "bid_strategy", "start_time", "stop_time",
]
ADSET_FIELDS = [
    "id", "name", "campaign_id", "effective_status", "bid_strategy", "bid_amount",
    "daily_budget", "lifetime_budget", "budget_remaining", "optimization_goal",
    "billing_event", "promoted_object", "learning_stage_info", "issues_info",
    "start_time", "end_time",
]
INSIGHT_FIELDS = ["adset_id", "campaign_id", "spend", "impressions", "actions"]

# The insights action type that counts each optimisation event. Names are
# from the AdsActionStats reference. Goals that are not listed have no
# cost-per-result to compare a cap with, and are reported as not evaluated.
# https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats/
GOAL_ACTION_TYPES = {
    "LINK_CLICKS": "link_click",
    "LANDING_PAGE_VIEWS": "landing_page_view",
    "LEAD_GENERATION": "onsite_conversion.lead_grouped",
    "QUALITY_LEAD": "onsite_conversion.lead_grouped",
    "APP_INSTALLS": "mobile_app_install",
    "POST_ENGAGEMENT": "post_engagement",
    "CONVERSATIONS": "onsite_conversion.messaging_conversation_started_7d",
}
PIXEL_EVENT_ACTION_TYPES = {
    "PURCHASE": "offsite_conversion.fb_pixel_purchase",
    "LEAD": "offsite_conversion.fb_pixel_lead",
    "COMPLETE_REGISTRATION": "offsite_conversion.fb_pixel_complete_registration",
    "ADD_TO_CART": "offsite_conversion.fb_pixel_add_to_cart",
    "INITIATED_CHECKOUT": "offsite_conversion.fb_pixel_initiate_checkout",
    "ADD_PAYMENT_INFO": "offsite_conversion.fb_pixel_add_payment_info",
    "CONTENT_VIEW": "offsite_conversion.fb_pixel_view_content",
    "SEARCH": "offsite_conversion.fb_pixel_search",
    "ADD_TO_WISHLIST": "offsite_conversion.fb_pixel_add_to_wishlist",
    "SUBSCRIBE": "subscribe_website",
    "START_TRIAL": "start_trial_website",
    "SUBMIT_APPLICATION": "submit_application_website",
    "CONTACT": "contact_website",
    "SCHEDULE": "schedule_website",
    "DONATE": "donate_website",
    "FIND_LOCATION": "find_location_website",
    "CUSTOMIZE_PRODUCT": "customize_product_website",
}


def to_major(amount, currency):
    """Convert an API money amount to the currency's main unit, or None."""
    if amount in (None, ""):
        return None
    divisor = 1 if (currency or "").upper() in WHOLE_UNIT_CURRENCIES else 100
    return int(amount) / divisor


def date_window(days, today=None):
    """The last `days` complete days. Today is left out because it is partial."""
    today = today or date.today()
    return (today - timedelta(days=days)).isoformat(), (today - timedelta(days=1)).isoformat()


def optimization_action_type(adset):
    """The insights action type that counts this ad set's optimisation event."""
    goal = adset.get("optimization_goal")
    promoted = adset.get("promoted_object") or {}
    if goal in ("OFFSITE_CONVERSIONS", "VALUE"):
        if promoted.get("custom_conversion_id"):
            return f"offsite_conversion.custom.{promoted['custom_conversion_id']}"
        return PIXEL_EVENT_ACTION_TYPES.get(promoted.get("custom_event_type"))
    return GOAL_ACTION_TYPES.get(goal)


def action_count(row, action_type):
    """How many times action_type occurred in an insights row."""
    for action in (row or {}).get("actions") or []:
        if action.get("action_type") == action_type:
            return float(action.get("value", 0))
    return 0.0


def reference_cpas(adsets, rows_by_adset):
    """Account-wide cost per optimisation event over the window.

    For each action type: the spend of every ad set optimising for it,
    divided by the events those ad sets got. This is the "real CPA" a cap
    is compared with. cpa is None when there were no events.
    """
    totals = {}
    for adset in adsets:
        action_type = optimization_action_type(adset)
        row = rows_by_adset.get(adset["id"])
        if not action_type or not row:
            continue
        entry = totals.setdefault(action_type, {"spend": 0.0, "results": 0.0, "adsets": 0})
        entry["spend"] += float(row.get("spend", 0))
        entry["results"] += action_count(row, action_type)
        entry["adsets"] += 1
    for entry in totals.values():
        entry["spend"] = round(entry["spend"], 2)
        entry["cpa"] = round(entry["spend"] / entry["results"], 2) if entry["results"] else None
    return totals


def active_days(entity, since, until):
    """Days of the window on which the ad set or campaign was scheduled to run."""
    start = max((entity.get("start_time") or since)[:10], since)
    scheduled_end = entity.get("end_time") or entity.get("stop_time") or until
    end = min(scheduled_end[:10], until)
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return max(span, 0)


def weekly_budget(entity, currency, today):
    """What an ad set or campaign can spend in a week, or None if it has no budget."""
    daily = to_major(entity.get("daily_budget"), currency)
    if daily:
        return daily * 7
    remaining = to_major(entity.get("budget_remaining"), currency)
    end = entity.get("end_time") or entity.get("stop_time")
    if remaining and end:
        days_left = max((date.fromisoformat(end[:10]) - today).days, 1)
        return remaining / days_left * 7
    return None


def _finding(check, severity, entity, evidence, note, entity_type="adset"):
    return {
        "check": check,
        "severity": severity,
        "entity_type": entity_type,
        "entity_id": entity["id"],
        "entity_name": entity.get("name"),
        "campaign_id": entity.get("campaign_id", entity["id"]),
        "evidence": evidence,
        "note": note,
    }


def _skip(entity, check, reason):
    return {"entity_id": entity["id"], "check": check, "reason": reason}


def _budget_finding(entity, entity_type, budget, reference_cpa, target_events):
    """Flag a weekly budget that cannot buy the events the learning phase needs."""
    if budget >= target_events * reference_cpa:
        return None
    return _finding(
        "budget_below_learning_volume", "medium", entity,
        {"weekly_budget": round(budget, 2), "reference_cpa": reference_cpa,
         "events_needed": target_events,
         "events_affordable": round(budget / reference_cpa, 1),
         "weekly_budget_needed": round(target_events * reference_cpa, 2)},
        f"A week of budget buys fewer than {target_events} optimisation events "
        "at the account's CPA.",
        entity_type=entity_type,
    )


def diagnose_adset(adset, campaign, row, references, currency, window, thresholds, today):
    """Run every check on one ad set. Returns (findings, not_evaluated)."""
    findings, skipped = [], []
    since, until = window
    spend = float((row or {}).get("spend", 0))
    impressions = int((row or {}).get("impressions", 0))
    days = active_days(adset, since, until)
    action_type = optimization_action_type(adset)
    reference = references.get(action_type) if action_type else None
    reference_cpa = reference["cpa"] if reference else None
    own_results = action_count(row, action_type) if action_type else 0.0
    own_cpa = round(spend / own_results, 2) if own_results else None

    issues = adset.get("issues_info") or []
    if adset.get("effective_status") == "WITH_ISSUES" or issues:
        findings.append(_finding(
            "delivery_issue", "critical", adset,
            {"issues": [
                {k: issue.get(k) for k in
                 ("error_code", "error_summary", "error_message", "level")}
                for issue in issues
            ]},
            "Meta reports an issue that blocks or limits delivery.",
        ))

    budget_daily = to_major(adset.get("daily_budget"), currency)
    budget = weekly_budget(adset, currency, today)
    stalled = days > 0 and impressions == 0
    if stalled and budget is not None:
        findings.append(_finding(
            "no_delivery", "high", adset,
            {"impressions": 0, "spend": 0.0, "days": days, "budget_scope": "adset"},
            "Active with its own budget but served no impressions.",
        ))
    elif stalled:
        findings.append(_finding(
            "no_delivery", "medium", adset,
            {"impressions": 0, "spend": 0.0, "days": days, "budget_scope": "campaign"},
            "Active but served no impressions. The campaign budget went to other ad sets.",
        ))

    underspending = False
    if budget_daily and days > 0 and not stalled:
        utilization = spend / (budget_daily * days)
        if utilization < thresholds["underspend"]:
            underspending = True
            findings.append(_finding(
                "underspend", "medium", adset,
                {"spend": round(spend, 2), "daily_budget": budget_daily, "days": days,
                 "utilization": round(utilization, 2)},
                "Spent less than the set share of its daily budget.",
            ))

    strategy = adset.get("bid_strategy") or (campaign or {}).get("bid_strategy")
    cap = to_major(adset.get("bid_amount"), currency)
    if strategy in CAPPED_STRATEGIES and cap:
        if reference_cpa is None:
            skipped.append(_skip(
                adset, "cap_below_cpa",
                "no results for the optimisation event in the period" if action_type
                else "optimisation event has no insights action type"))
        elif cap < reference_cpa:
            if stalled or underspending:
                severity = "high"
            elif budget_daily:
                # Spending its budget despite the low cap: worth knowing, not a stall.
                severity = "info"
            else:
                severity = "medium"
            findings.append(_finding(
                "cap_below_cpa", severity, adset,
                {"bid_strategy": strategy, "cap": cap, "reference_cpa": reference_cpa,
                 "reference_action_type": action_type, "own_cpa": own_cpa,
                 "cap_to_cpa_ratio": round(cap / reference_cpa, 2)},
                "The cap is below what this event costs across the account.",
            ))

    learning = adset.get("learning_stage_info") or {}
    status = learning.get("status")
    target_events = learning.get("dynamic_lp_conversions_threshold") or thresholds["learning_events"]
    if status in ("FAIL", "LEARNING"):
        evidence = {"status": status, "conversions": learning.get("conversions"),
                    "events_needed": target_events}
        if learning.get("last_sig_edit_ts"):
            edited = datetime.fromtimestamp(int(learning["last_sig_edit_ts"]), tz=timezone.utc)
            evidence["last_significant_edit"] = edited.date().isoformat()
        if status == "FAIL":
            findings.append(_finding(
                "learning_limited", "medium", adset, evidence,
                "Learning limited: too few optimisation events to leave the learning phase.",
            ))
        else:
            findings.append(_finding(
                "learning", "info", adset, evidence,
                "Still in the learning phase. Results are less stable until it ends.",
            ))

    # An ad set funded by a campaign budget is checked once per campaign, in
    # campaign_findings.
    if budget is not None:
        if reference_cpa is None:
            skipped.append(_skip(adset, "budget_below_learning_volume",
                                 "no reference CPA for the optimisation event"))
        else:
            finding = _budget_finding(adset, "adset", budget, reference_cpa, target_events)
            if finding:
                findings.append(finding)

    return findings, skipped


def campaign_findings(campaign, adsets, rows_by_adset, references, currency, window,
                      thresholds, today):
    """Budget checks for a campaign that funds its ad sets from one budget."""
    findings, skipped = [], []
    since, until = window
    members = [a for a in adsets
               if a.get("effective_status") in DELIVERING_STATUSES
               and weekly_budget(a, currency, today) is None]
    budget = weekly_budget(campaign, currency, today)
    if not members or budget is None:
        return findings, skipped

    daily = to_major(campaign.get("daily_budget"), currency)
    days = active_days(campaign, since, until)
    spend = sum(float(rows_by_adset.get(a["id"], {}).get("spend", 0)) for a in adsets)
    if daily and days > 0:
        utilization = spend / (daily * days)
        if utilization < thresholds["underspend"]:
            findings.append(_finding(
                "underspend", "medium", campaign,
                {"spend": round(spend, 2), "daily_budget": daily, "days": days,
                 "utilization": round(utilization, 2)},
                "The campaign spent less than the set share of its daily budget.",
                entity_type="campaign",
            ))

    # The cheapest optimisation event among the ad sets is the most lenient
    # test: if the budget cannot fund that one, it cannot fund any of them.
    cpas = [references[t]["cpa"] for t in map(optimization_action_type, members)
            if t in references and references[t]["cpa"] is not None]
    if not cpas:
        skipped.append(_skip(campaign, "budget_below_learning_volume",
                             "no reference CPA for the optimisation event"))
        return findings, skipped
    finding = _budget_finding(campaign, "campaign", budget, min(cpas),
                              thresholds["learning_events"])
    if finding:
        findings.append(finding)
    return findings, skipped


def diagnose(account, campaigns, adsets, insights, days, thresholds, today=None):
    """Build the delivery diagnosis from fetched data. Pure: no API calls."""
    today = today or date.today()
    window = date_window(days, today)
    currency = account.get("currency")
    campaign_map = {c["id"]: c for c in campaigns}
    rows_by_adset = {row["adset_id"]: row for row in insights}
    references = reference_cpas(adsets, rows_by_adset)

    findings, skipped, checked = [], [], 0
    for adset in adsets:
        if adset.get("effective_status") not in DELIVERING_STATUSES:
            continue
        checked += 1
        found, not_evaluated = diagnose_adset(
            adset, campaign_map.get(adset.get("campaign_id")), rows_by_adset.get(adset["id"]),
            references, currency, window, thresholds, today)
        findings += found
        skipped += not_evaluated

    for campaign in campaigns:
        members = [a for a in adsets if a.get("campaign_id") == campaign["id"]]
        found, not_evaluated = campaign_findings(
            campaign, members, rows_by_adset, references, currency, window, thresholds, today)
        findings += found
        skipped += not_evaluated

    findings.sort(key=lambda f: (SEVERITY_ORDER.index(f["severity"]), f["entity_id"], f["check"]))
    skipped.sort(key=lambda s: (s["entity_id"], s["check"]))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER}
    return {
        "status": "ok",
        "account_id": account.get("id"),
        "currency": currency,
        "window": {"since": window[0], "until": window[1], "days": days},
        "thresholds": thresholds,
        "summary": {"adsets_checked": checked, "findings": counts,
                    "not_evaluated": len(skipped)},
        "reference_cpa": {k: references[k] for k in sorted(references)},
        "findings": findings,
        "not_evaluated": skipped,
    }


def fetch_inputs(account_id, access_token, days, no_cache=False):
    """Fetch the four inputs, each through the response cache."""
    from facebook_business.adobjects.adaccount import AdAccount

    api = meta_utils.init_api(access_token)
    account = AdAccount(account_id, api=api)
    since, until = date_window(days)
    retry = meta_campaigns.api_call_with_retry
    plain = meta_campaigns.to_plain
    campaign_params = {"effective_status": CAMPAIGN_STATUSES, "limit": 500}
    adset_params = {"effective_status": ADSET_STATUSES, "limit": 500}
    insight_params = {"time_range": {"since": since, "until": until}, "level": "adset"}

    def cached(key, fetch):
        return meta_utils.cached(account_id, key, lambda: retry(fetch), no_cache=no_cache)

    return (
        cached("delivery_account",
               lambda: plain(dict(account.api_get(fields=ACCOUNT_FIELDS)))),
        cached("delivery_campaigns",
               lambda: [plain(dict(c)) for c in
                        account.get_campaigns(fields=CAMPAIGN_FIELDS, params=campaign_params)]),
        cached("delivery_adsets",
               lambda: [plain(dict(a)) for a in
                        account.get_ad_sets(fields=ADSET_FIELDS, params=adset_params)]),
        cached(f"delivery_insights_{days}d",
               lambda: [plain(dict(r)) for r in
                        account.get_insights(fields=INSIGHT_FIELDS, params=insight_params)]),
    )


def main():
    parser = argparse.ArgumentParser(description="Diagnose stalled Meta Ads delivery")
    parser.add_argument("--account", required=True, type=meta_utils.account_id_arg,
                        help="Ad account ID (e.g., act_123456)")
    parser.add_argument("--days", type=int, default=7,
                        help="Complete days to look back, ending yesterday (default: 7)")
    parser.add_argument("--underspend-threshold", type=float, default=0.5,
                        help="Flag spend below this share of the daily budget (default: 0.5)")
    parser.add_argument("--learning-events", type=int, default=LEARNING_EVENTS,
                        help="Optimisation events per week needed to leave learning (default: 50)")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache, fetch fresh data")
    parser.add_argument("--json", action="store_true",
                        help="No-op; output is always JSON. Accepted for consistency.")
    args = parser.parse_args()

    token = meta_auth.get_access_token()
    if not token:
        print(json.dumps({"status": "error", "message": meta_auth.NO_TOKEN_MESSAGE}))
        sys.exit(1)

    account, campaigns, adsets, insights = fetch_inputs(
        args.account, token, args.days, args.no_cache)
    thresholds = {"underspend": args.underspend_threshold,
                  "learning_events": args.learning_events,
                  "learning_days": LEARNING_DAYS}
    result = diagnose(account, campaigns, adsets, insights, args.days, thresholds)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    meta_utils.run_cli(main)
