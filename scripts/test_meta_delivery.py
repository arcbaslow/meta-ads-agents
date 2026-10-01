"""Tests for the stalled-delivery diagnosis. All data here is synthetic."""

import contextlib
import io
import json
import random
import sys
from datetime import date
from unittest import mock

import meta_delivery
import meta_utils

TODAY = date(2026, 9, 30)
THRESHOLDS = {"underspend": 0.5, "learning_events": 50, "learning_days": 7}
ACCOUNT = {"id": "act_1", "currency": "USD"}
PURCHASE = "offsite_conversion.fb_pixel_purchase"


def adset(id, **overrides):
    base = {
        "id": id,
        "name": f"Ad set {id}",
        "campaign_id": "c1",
        "effective_status": "ACTIVE",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "daily_budget": "10000",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "promoted_object": {"pixel_id": "9", "custom_event_type": "PURCHASE"},
        "start_time": "2026-08-01T00:00:00+0000",
    }
    base.update(overrides)
    return base


def row(adset_id, spend, purchases=0, impressions=1000):
    actions = [{"action_type": "link_click", "value": "40"}]
    if purchases:
        actions.append({"action_type": PURCHASE, "value": str(purchases)})
    return {"adset_id": adset_id, "campaign_id": "c1", "spend": str(spend),
            "impressions": str(impressions), "actions": actions}


def run(adsets, insights, campaigns=(), account=ACCOUNT, thresholds=THRESHOLDS):
    return meta_delivery.diagnose(account, list(campaigns), adsets, insights, 7,
                                  thresholds, today=TODAY)


def checks(result, entity_id):
    return {f["check"]: f for f in result["findings"] if f["entity_id"] == entity_id}


# --- building blocks ---------------------------------------------------------

def test_amounts_are_converted_by_currency():
    assert meta_delivery.to_major("1250", "USD") == 12.5
    assert meta_delivery.to_major(1250, "JPY") == 1250
    assert meta_delivery.to_major(None, "USD") is None


def test_window_is_complete_days_ending_yesterday():
    assert meta_delivery.date_window(7, TODAY) == ("2026-09-23", "2026-09-29")


def test_optimisation_event_maps_to_an_insights_action_type():
    action = meta_delivery.optimization_action_type
    assert action(adset("1")) == PURCHASE
    assert action(adset("1", promoted_object={"custom_conversion_id": "77"})) == \
        "offsite_conversion.custom.77"
    assert action(adset("1", optimization_goal="LINK_CLICKS", promoted_object=None)) == "link_click"


def test_unmapped_optimisation_events_have_no_action_type():
    action = meta_delivery.optimization_action_type
    assert action(adset("1", promoted_object={"custom_event_type": "OTHER"})) is None
    assert action(adset("1", optimization_goal="REACH")) is None


def test_reference_cpa_pools_every_ad_set_with_the_same_event():
    adsets = [adset("1"), adset("2"), adset("3", optimization_goal="LINK_CLICKS")]
    rows = {"1": row("1", 300, purchases=10), "2": row("2", 100, purchases=10),
            "3": row("3", 80)}
    refs = meta_delivery.reference_cpas(adsets, rows)
    assert refs[PURCHASE] == {"spend": 400.0, "results": 20.0, "adsets": 2, "cpa": 20.0}
    assert refs["link_click"]["cpa"] == 2.0


# --- cap below CPA -----------------------------------------------------------

def test_cap_below_account_cpa_on_a_stalled_ad_set_is_high():
    capped = adset("2", bid_strategy="COST_CAP", bid_amount="600")
    result = run([adset("1"), capped], [row("1", 700, purchases=50)])
    found = checks(result, "2")
    assert found["cap_below_cpa"]["severity"] == "high"
    assert found["cap_below_cpa"]["evidence"] == {
        "bid_strategy": "COST_CAP", "cap": 6.0, "reference_cpa": 14.0,
        "reference_action_type": PURCHASE, "own_cpa": None, "cap_to_cpa_ratio": 0.43,
    }
    assert found["no_delivery"]["severity"] == "high"


def test_cap_below_cpa_on_an_ad_set_that_spends_is_informational():
    capped = adset("2", bid_strategy="LOWEST_COST_WITH_BID_CAP", bid_amount="1200")
    result = run([adset("1"), capped],
                 [row("1", 700, purchases=40), row("2", 650, purchases=50)])
    assert checks(result, "2")["cap_below_cpa"]["severity"] == "info"


def test_cap_above_cpa_is_not_flagged():
    capped = adset("2", bid_strategy="COST_CAP", bid_amount="3000")
    result = run([adset("1"), capped], [row("1", 700, purchases=50), row("2", 600, purchases=40)])
    assert "cap_below_cpa" not in checks(result, "2")


def test_cap_strategy_set_on_the_campaign_is_read():
    capped = adset("2", bid_strategy=None, bid_amount="600", daily_budget=None)
    campaign = {"id": "c1", "name": "C", "bid_strategy": "COST_CAP", "daily_budget": "20000"}
    result = run([adset("1", daily_budget=None), capped], [row("1", 700, purchases=50)],
                 campaigns=[campaign])
    assert checks(result, "2")["cap_below_cpa"]["severity"] == "high"


def test_cap_without_a_reference_is_reported_as_not_evaluated():
    capped = adset("2", bid_strategy="COST_CAP", bid_amount="600",
                   promoted_object={"custom_event_type": "OTHER"})
    result = run([capped], [row("2", 300)])
    assert "cap_below_cpa" not in checks(result, "2")
    assert {"entity_id": "2", "check": "cap_below_cpa",
            "reason": "optimisation event has no insights action type"} in result["not_evaluated"]


# --- delivery and spend ------------------------------------------------------

def test_stalled_ad_set_under_a_campaign_budget_is_medium():
    campaign = {"id": "c1", "name": "C", "daily_budget": "20000"}
    result = run([adset("1", daily_budget=None), adset("2", daily_budget=None)],
                 [row("1", 1300, purchases=60)], campaigns=[campaign])
    assert checks(result, "2")["no_delivery"]["severity"] == "medium"


def test_ad_set_that_started_after_the_window_is_not_stalled():
    result = run([adset("1", start_time="2026-09-30T08:00:00+0000")], [])
    assert "no_delivery" not in checks(result, "1")


def test_underspend_counts_only_days_the_ad_set_ran():
    late = adset("1", start_time="2026-09-28T00:00:00+0000")
    result = run([late], [row("1", 150, purchases=10)])
    assert "underspend" not in checks(result, "1")

    result = run([adset("1")], [row("1", 150, purchases=10)])
    evidence = checks(result, "1")["underspend"]["evidence"]
    assert evidence == {"spend": 150.0, "daily_budget": 100.0, "days": 7, "utilization": 0.21}


def test_campaign_budget_underspend_is_reported_once_on_the_campaign():
    campaign = {"id": "c1", "name": "C", "daily_budget": "20000"}
    adsets = [adset("1", daily_budget=None), adset("2", daily_budget=None)]
    result = run(adsets, [row("1", 200, purchases=10), row("2", 100, purchases=5)],
                 campaigns=[campaign])
    found = [f for f in result["findings"] if f["check"] == "underspend"]
    assert len(found) == 1
    assert found[0]["entity_type"] == "campaign"
    assert found[0]["evidence"]["utilization"] == 0.21


def test_delivery_issue_lists_what_meta_reports():
    broken = adset("1", effective_status="WITH_ISSUES", issues_info=[
        {"error_code": 1815869, "error_summary": "Ad set is off",
         "error_message": "Payment failed", "level": "AD_SET", "mid": "x"}])
    found = checks(run([broken], [row("1", 650, purchases=30)]), "1")["delivery_issue"]
    assert found["severity"] == "critical"
    assert found["evidence"]["issues"] == [{
        "error_code": 1815869, "error_summary": "Ad set is off",
        "error_message": "Payment failed", "level": "AD_SET"}]


# --- learning phase and budget ----------------------------------------------

def test_learning_limited_is_flagged_with_its_evidence():
    limited = adset("1", learning_stage_info={
        "status": "FAIL", "conversions": 12, "last_sig_edit_ts": 1790000000})
    found = checks(run([limited], [row("1", 650, purchases=30)]), "1")["learning_limited"]
    assert found["severity"] == "medium"
    assert found["evidence"] == {"status": "FAIL", "conversions": 12, "events_needed": 50,
                                 "last_significant_edit": "2026-09-21"}


def test_learning_uses_the_per_ad_set_threshold_when_meta_returns_one():
    learning = adset("1", learning_stage_info={
        "status": "LEARNING", "conversions": 4, "dynamic_lp_conversions_threshold": 10})
    found = checks(run([learning], [row("1", 650, purchases=30)]), "1")["learning"]
    assert found["severity"] == "info"
    assert found["evidence"]["events_needed"] == 10


def test_ad_set_that_left_learning_is_not_flagged():
    done = adset("1", learning_stage_info={"status": "SUCCESS", "conversions": 0})
    found = checks(run([done], [row("1", 650, purchases=30)]), "1")
    assert "learning" not in found and "learning_limited" not in found


def test_budget_too_small_for_the_learning_phase():
    small = adset("1", daily_budget="2000")
    found = checks(run([small], [row("1", 140, purchases=7)]), "1")
    assert found["budget_below_learning_volume"]["evidence"] == {
        "weekly_budget": 140.0, "reference_cpa": 20.0, "events_needed": 50,
        "events_affordable": 7.0, "weekly_budget_needed": 1000.0}


def test_budget_that_covers_the_learning_phase_is_not_flagged():
    found = checks(run([adset("1", daily_budget="20000")], [row("1", 1400, purchases=70)]), "1")
    assert "budget_below_learning_volume" not in found


def test_lifetime_budget_is_spread_over_the_days_left():
    lifetime = adset("1", daily_budget=None, lifetime_budget="100000",
                     budget_remaining="28000", end_time="2026-10-14T00:00:00+0000")
    found = checks(run([lifetime], [row("1", 700, purchases=35)]), "1")
    assert found["budget_below_learning_volume"]["evidence"]["weekly_budget"] == 140.0


def test_campaign_budget_is_checked_once_against_its_cheapest_event():
    campaign = {"id": "c1", "name": "C", "daily_budget": "3000"}
    adsets = [adset("1", daily_budget=None), adset("2", daily_budget=None)]
    result = run(adsets, [row("1", 105, purchases=5), row("2", 105, purchases=5)],
                 campaigns=[campaign])
    found = [f for f in result["findings"] if f["check"] == "budget_below_learning_volume"]
    assert [(f["entity_type"], f["entity_id"]) for f in found] == [("campaign", "c1")]
    assert found[0]["evidence"]["events_affordable"] == 10.0


def test_budget_check_without_a_reference_cpa_is_not_evaluated():
    result = run([adset("1")], [row("1", 650)])
    assert {"entity_id": "1", "check": "budget_below_learning_volume",
            "reason": "no reference CPA for the optimisation event"} in result["not_evaluated"]


# --- whole-report behaviour --------------------------------------------------

def test_paused_ad_sets_feed_the_reference_but_are_not_checked():
    paused = adset("1", effective_status="PAUSED")
    capped = adset("2", bid_strategy="COST_CAP", bid_amount="600")
    result = run([paused, capped], [row("1", 700, purchases=50)])
    assert result["summary"]["adsets_checked"] == 1
    assert result["reference_cpa"][PURCHASE]["cpa"] == 14.0
    assert checks(result, "1") == {}


def test_whole_unit_currency_is_not_divided_by_100():
    capped = adset("2", bid_strategy="COST_CAP", bid_amount="600", daily_budget="100000")
    result = run([adset("1", daily_budget="100000"), capped], [row("1", 70000, purchases=50)],
                 account={"id": "act_1", "currency": "JPY"})
    assert checks(result, "2")["cap_below_cpa"]["evidence"]["cap"] == 600


def test_output_does_not_depend_on_input_order():
    adsets = [adset(str(i), bid_strategy="COST_CAP", bid_amount="600") for i in range(1, 7)]
    rows = [row("1", 700, purchases=50), row("2", 90, purchases=3), row("3", 650, purchases=20)]
    expected = json.dumps(run(adsets, rows), sort_keys=True)
    for seed in range(5):
        shuffled_adsets, shuffled_rows = adsets[:], rows[:]
        random.Random(seed).shuffle(shuffled_adsets)
        random.Random(seed).shuffle(shuffled_rows)
        assert json.dumps(run(shuffled_adsets, shuffled_rows), sort_keys=True) == expected


def test_findings_are_ordered_by_severity():
    broken = adset("9", effective_status="WITH_ISSUES", issues_info=[{"error_code": 1}])
    result = run([adset("1", daily_budget="2000"), broken], [row("1", 140, purchases=7)])
    severities = [f["severity"] for f in result["findings"]]
    order = meta_delivery.SEVERITY_ORDER
    assert severities == sorted(severities, key=order.index)
    assert result["summary"]["findings"]["critical"] == 1


# --- names checked against the SDK -------------------------------------------

def _values(enum_class):
    return {v for k, v in vars(enum_class).items() if not k.startswith("_")}


def test_status_filters_use_values_each_edge_accepts():
    from facebook_business.adobjects.adset import AdSet
    from facebook_business.adobjects.campaign import Campaign

    assert set(meta_delivery.CAMPAIGN_STATUSES) <= _values(Campaign.EffectiveStatus)
    assert set(meta_delivery.ADSET_STATUSES) <= _values(AdSet.EffectiveStatus)
    assert meta_delivery.DELIVERING_STATUSES <= _values(AdSet.EffectiveStatus)


def test_goal_and_event_names_exist_in_the_sdk():
    from facebook_business.adobjects.adpromotedobject import AdPromotedObject
    from facebook_business.adobjects.adset import AdSet

    goals = _values(AdSet.OptimizationGoal)
    assert set(meta_delivery.GOAL_ACTION_TYPES) <= goals
    assert {"OFFSITE_CONVERSIONS", "VALUE"} <= goals
    assert set(meta_delivery.PIXEL_EVENT_ACTION_TYPES) <= _values(AdPromotedObject.CustomEventType)
    assert meta_delivery.CAPPED_STRATEGIES <= _values(AdSet.BidStrategy)


# --- fetching ----------------------------------------------------------------

class FakeAccount:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def api_get(self, fields=None, params=None):
        FakeAccount.calls.append("account")
        return {"id": "act_1", "currency": "USD"}

    def get_campaigns(self, fields=None, params=None):
        FakeAccount.calls.append("campaigns")
        return []

    def get_ad_sets(self, fields=None, params=None):
        FakeAccount.calls.append("adsets")
        return [adset("2", bid_strategy="COST_CAP", bid_amount="600"), adset("1")]

    def get_insights(self, fields=None, params=None):
        FakeAccount.calls.append(("insights", params["time_range"], params["level"]))
        return [row("1", 700, purchases=50)]


def run_main(argv):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["meta_delivery.py"] + argv), \
            mock.patch.dict("os.environ", {"META_ACCESS_TOKEN": "placeholder"}), \
            mock.patch("facebook_business.adobjects.adaccount.AdAccount", FakeAccount), \
            mock.patch.object(meta_utils, "init_api", return_value=None), \
            contextlib.redirect_stdout(out):
        meta_delivery.main()
    return json.loads(out.getvalue())


def test_main_reports_the_capped_ad_set():
    FakeAccount.calls = []
    result = run_main(["--account", "1"])
    assert result["status"] == "ok"
    assert result["account_id"] == "act_1"
    assert [f["check"] for f in result["findings"] if f["entity_id"] == "2"] == \
        ["cap_below_cpa", "no_delivery"]
    insights_call = [c for c in FakeAccount.calls if isinstance(c, tuple)][0]
    assert insights_call[2] == "adset"
    assert insights_call[1]["until"] < date.today().isoformat()


def test_every_call_goes_through_the_cache():
    FakeAccount.calls = []
    first = run_main(["--account", "act_1"])
    assert len(FakeAccount.calls) == 4
    second = run_main(["--account", "act_1"])
    assert len(FakeAccount.calls) == 4
    assert first == second


def test_no_cache_fetches_again():
    FakeAccount.calls = []
    run_main(["--account", "act_1"])
    run_main(["--account", "act_1", "--no-cache"])
    assert len(FakeAccount.calls) == 8


def test_missing_token_is_a_json_error():
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["meta_delivery.py", "--account", "act_1"]), \
            contextlib.redirect_stdout(out):
        try:
            meta_delivery.main()
        except SystemExit as exc:
            assert exc.code == 1
    assert json.loads(out.getvalue())["status"] == "error"
