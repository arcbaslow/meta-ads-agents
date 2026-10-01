"""Tests for the change-history correlation. All data here is synthetic."""

import contextlib
import io
import json
import random
import sys
from datetime import date, timedelta
from unittest import mock

import meta_changes
import meta_utils

TODAY = date(2026, 9, 30)
PURCHASE = "offsite_conversion.fb_pixel_purchase"


def day(n):
    """ISO date n days before TODAY."""
    return (TODAY - timedelta(days=n)).isoformat()


def rows(adset_id, spend_by_days_ago, campaign_id="c1", purchases=0, ad_id=None):
    """Daily insights rows: {days_ago: spend}. 1000 impressions and 20 clicks a day."""
    out = []
    for days_ago, spend in spend_by_days_ago.items():
        row = {"campaign_id": campaign_id, "adset_id": adset_id, "date_start": day(days_ago),
               "date_stop": day(days_ago), "spend": str(spend), "impressions": "1000",
               "clicks": "20", "actions": [{"action_type": "link_click", "value": "20"}]}
        if purchases:
            row["actions"].append({"action_type": PURCHASE, "value": str(purchases)})
        if ad_id:
            row["ad_id"] = ad_id
        out.append(row)
    return out


def event(object_id, days_ago, event_type="update_ad_set_budget", hour=10, **extra):
    base = {"event_time": f"{day(days_ago)}T{hour:02d}:00:00+0000", "event_type": event_type,
            "translated_event_type": event_type.replace("_", " "), "object_id": object_id,
            "object_name": f"Entity {object_id}", "actor_name": "Buyer"}
    base.update(extra)
    return base


def run(activities, insight_rows, **overrides):
    options = {"level": "adset", "days": 14, "window": 3, "threshold": 30.0,
               "action_type": None, "today": TODAY}
    options.update(overrides)
    return meta_changes.correlate(activities, insight_rows, **options)


def steady_then_half(adset_id="a1", change_days_ago=5):
    """100 a day before the change, 50 a day from the change on."""
    spend = {d: (100 if d > change_days_ago else 50) for d in range(1, 17)}
    return rows(adset_id, spend)


# --- grouping ----------------------------------------------------------------

def test_entries_for_one_object_on_one_day_become_one_change():
    groups = meta_changes.group_changes([
        event("a1", 5, "update_ad_set_budget", hour=11),
        event("a1", 5, "update_ad_set_bid_strategy", hour=9),
        event("a1", 4),
        event("a2", 5),
    ])
    assert [(g["date"], g["object_id"], len(g["events"])) for g in groups] == [
        (day(5), "a1", 2), (day(5), "a2", 1), (day(4), "a1", 1)]
    assert [e["event_type"] for e in groups[0]["events"]] == [
        "update_ad_set_bid_strategy", "update_ad_set_budget"]


def test_extra_data_json_is_parsed_and_other_text_is_kept():
    groups = meta_changes.group_changes([
        event("a1", 5, extra_data='{"old_value": 5000, "new_value": 2500}'),
        event("a1", 5, hour=12, extra_data="not json"),
    ])
    parsed = [e["extra_data"] for e in groups[0]["events"]]
    assert parsed == [{"old_value": 5000, "new_value": 2500}, "not json"]


def test_entries_without_an_object_or_time_are_ignored():
    assert meta_changes.group_changes([{"event_type": "x"}, {"object_id": "a1"}]) == []


# --- before and after --------------------------------------------------------

def test_change_day_is_in_neither_window():
    result = run([event("a1", 5)], steady_then_half())
    change = result["changes"][0]
    assert change["before"]["spend"] == 300.0
    assert change["before"]["days"] == 3
    assert change["after"]["spend"] == 150.0
    assert change["after"]["days"] == 3
    assert change["change_pct"]["spend_per_day"] == -50.0


def test_shift_is_reported_with_its_largest_metric():
    result = run([event("a1", 5)], steady_then_half())
    assert result["summary"]["changes_followed_by_a_shift"] == 1
    shift = result["shifts"][0]
    assert shift["object_id"] == "a1"
    assert shift["metric"] in ("spend_per_day", "cpm")
    assert shift["change_pct"] == -50.0
    assert shift["events"] == ["update_ad_set_budget"]


def test_steady_performance_is_not_a_shift():
    result = run([event("a1", 5)], rows("a1", {d: 100 for d in range(1, 17)}))
    assert result["changes"][0]["shifted"] is False
    assert result["shifts"] == []


def test_threshold_is_configurable():
    spend = {d: (100 if d > 5 else 80) for d in range(1, 17)}
    assert run([event("a1", 5)], rows("a1", spend))["shifts"] == []
    assert len(run([event("a1", 5)], rows("a1", spend), threshold=15.0)["shifts"]) == 1


def test_recent_change_uses_the_complete_days_available():
    result = run([event("a1", 2)], rows("a1", {d: 100 for d in range(1, 17)}))
    assert result["changes"][0]["after"]["days"] == 1


def test_change_made_yesterday_has_no_after_window():
    result = run([event("a1", 1)], rows("a1", {d: 100 for d in range(1, 17)}))
    assert result["changes"] == []
    assert result["not_evaluated"] == [{
        "date": day(1), "object_id": "a1", "object_name": "Entity a1",
        "reason": "no complete day after the change yet"}]


def test_days_without_rows_count_as_zero_spend():
    spend = {d: 100 for d in range(6, 17)}
    result = run([event("a1", 5, "update_ad_set_run_status")], rows("a1", spend))
    change = result["changes"][0]
    assert change["after"]["spend_per_day"] == 0.0
    assert change["change_pct"]["spend_per_day"] == -100.0
    assert change["status_changed"] is True


def test_results_and_cpa_are_added_for_a_chosen_action_type():
    insight_rows = rows("a1", {d: 100 for d in range(6, 17)}, purchases=10) + \
        rows("a1", {d: 100 for d in range(1, 6)}, purchases=4)
    result = run([event("a1", 5)], insight_rows, action_type=PURCHASE)
    change = result["changes"][0]
    assert change["before"]["cpa"] == 10.0
    assert change["after"]["cpa"] == 25.0
    assert change["change_pct"]["cpa"] == 150.0
    assert result["shifts"][0]["metric"] == "cpa"


def test_cpa_is_absent_without_an_action_type():
    change = run([event("a1", 5)], steady_then_half())["changes"][0]
    assert "cpa" not in change["before"]
    assert "cpa" not in change["change_pct"]


# --- matching log entries to entities ---------------------------------------

def test_campaign_change_is_measured_on_all_its_ad_sets():
    insight_rows = steady_then_half("a1") + steady_then_half("a2")
    result = run([event("c1", 5, "update_campaign_budget")], insight_rows)
    change = result["changes"][0]
    assert change["level"] == "campaign"
    assert change["before"]["spend"] == 600.0
    assert change["after"]["spend"] == 300.0


def test_ad_change_needs_ad_level_rows():
    adset_rows = steady_then_half("a1")
    result = run([event("ad9", 5, "update_ad_creative")], adset_rows)
    assert result["changes"] == []
    assert result["unmatched_log_entries"][0]["object_id"] == "ad9"

    ad_rows = rows("a1", {d: (100 if d > 5 else 50) for d in range(1, 17)}, ad_id="ad9")
    result = run([event("ad9", 5, "update_ad_creative")], ad_rows, level="ad")
    assert result["changes"][0]["level"] == "ad"


def test_account_level_entries_are_listed_but_not_evaluated():
    result = run([event("act_1", 5, "ad_account_billing_charge")], steady_then_half())
    assert result["summary"]["unmatched_log_entries"] == 1
    assert result["changes"] == []


def test_other_changes_near_the_same_entity_are_counted():
    result = run([event("a1", 5), event("a1", 4, "update_ad_set_target_spec"), event("a1", 12)],
                 steady_then_half())
    by_date = {c["date"]: c["other_changes_in_window"] for c in result["changes"]}
    assert by_date == {day(5): 1, day(4): 1, day(12): 0}


# --- determinism -------------------------------------------------------------

def test_output_does_not_depend_on_input_order():
    activities = [event("a1", 5), event("a2", 6, "update_ad_set_bidding"),
                  event("a1", 9, "update_ad_set_target_spec"), event("c1", 5)]
    insight_rows = steady_then_half("a1") + steady_then_half("a2", change_days_ago=6)
    expected = json.dumps(run(activities, insight_rows), sort_keys=True)
    for seed in range(5):
        shuffled_a, shuffled_r = activities[:], insight_rows[:]
        random.Random(seed).shuffle(shuffled_a)
        random.Random(seed).shuffle(shuffled_r)
        assert json.dumps(run(shuffled_a, shuffled_r), sort_keys=True) == expected


def test_shifts_are_sorted_by_size():
    insight_rows = steady_then_half("a1") + \
        rows("a2", {d: (100 if d > 5 else 10) for d in range(1, 17)})
    result = run([event("a1", 5), event("a2", 5)], insight_rows)
    assert [s["object_id"] for s in result["shifts"]] == ["a2", "a1"]


# --- fetching ----------------------------------------------------------------

class FakeAccount:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def get_activities(self, fields=None, params=None):
        FakeAccount.calls.append(("activities", params))
        return [event("a1", 5)]

    def get_insights(self, fields=None, params=None):
        FakeAccount.calls.append(("insights", params, fields))
        first = date.today() - timedelta(days=5)
        return [{"campaign_id": "c1", "adset_id": "a1",
                 "date_start": (first + timedelta(days=offset)).isoformat(),
                 "spend": "50", "impressions": "1000", "clicks": "20"}
                for offset in range(-12, 5)]


def run_main(argv):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["meta_changes.py"] + argv), \
            mock.patch.dict("os.environ", {"META_ACCESS_TOKEN": "placeholder"}), \
            mock.patch("facebook_business.adobjects.adaccount.AdAccount", FakeAccount), \
            mock.patch.object(meta_utils, "init_api", return_value=None), \
            contextlib.redirect_stdout(out):
        meta_changes.main()
    return json.loads(out.getvalue())


def test_insights_reach_back_one_window_before_the_log():
    FakeAccount.calls = []
    run_main(["--account", "act_1", "--days", "14", "--window", "3"])
    activities = [c for c in FakeAccount.calls if c[0] == "activities"][0][1]
    insights = [c for c in FakeAccount.calls if c[0] == "insights"][0][1]
    today = date.today()
    assert activities["since"] == (today - timedelta(days=14)).isoformat()
    assert insights["time_range"]["since"] == (today - timedelta(days=17)).isoformat()
    assert insights["time_range"]["until"] == (today - timedelta(days=1)).isoformat()
    assert insights["time_increment"] == "1"


def test_ad_level_requests_the_ad_id():
    FakeAccount.calls = []
    run_main(["--account", "act_1", "--level", "ad"])
    fields = [c for c in FakeAccount.calls if c[0] == "insights"][0][2]
    assert "ad_id" in fields


def test_every_call_goes_through_the_cache():
    FakeAccount.calls = []
    first = run_main(["--account", "act_1"])
    second = run_main(["--account", "act_1"])
    assert len(FakeAccount.calls) == 2
    assert first == second
    assert first["account_id"] == "act_1"
    assert first["summary"]["changes"] == 1
    run_main(["--account", "act_1", "--no-cache"])
    assert len(FakeAccount.calls) == 4


def test_requested_activity_fields_exist_in_the_sdk():
    from facebook_business.adobjects.adactivity import AdActivity

    known = {v for k, v in vars(AdActivity.Field).items() if not k.startswith("_")}
    assert set(meta_changes.ACTIVITY_FIELDS) <= known
