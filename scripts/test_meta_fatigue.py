"""Tests for fatigue scoring over time (meta_creatives.py --fatigue). Synthetic data."""

import contextlib
import io
import json
import random
import sys
from datetime import date, timedelta
from unittest import mock

import meta_creatives
import meta_utils

TODAY = date(2026, 9, 30)


def daily(ad_id, first_half, second_half, days=14, spend=10.0):
    """Daily rows for an ad: (impressions, clicks) per day in each half."""
    rows = []
    start = TODAY - timedelta(days=days)
    for offset in range(days):
        impressions, clicks = first_half if offset < days // 2 else second_half
        rows.append({
            "ad_id": ad_id, "ad_name": f"Ad {ad_id}", "adset_id": "s1", "campaign_id": "c1",
            "date_start": (start + timedelta(days=offset)).isoformat(),
            "impressions": str(impressions), "clicks": str(clicks), "spend": str(spend),
        })
    return rows


def total(ad_id, frequency, impressions=14000, reach=4000, spend=140.0):
    return {"ad_id": ad_id, "frequency": str(frequency), "impressions": str(impressions),
            "reach": str(reach), "spend": str(spend)}


def score(daily_rows, total_rows, **overrides):
    options = {"days": 14, "min_impressions": 1000, "today": TODAY}
    options.update(overrides)
    return meta_creatives.score_fatigue(daily_rows, total_rows, **options)


def test_window_is_complete_days_split_in_two():
    assert meta_creatives.fatigue_window(14, TODAY) == ("2026-09-16", "2026-09-29", "2026-09-23")
    assert meta_creatives.fatigue_window(7, TODAY) == ("2026-09-23", "2026-09-29", "2026-09-26")


def test_high_frequency_with_falling_ctr_is_fatigued():
    result = score(daily("1", (1000, 20), (1000, 12)), [total("1", 4.2)])
    ad = result["ads"][0]
    assert ad["status"] == "fatigued"
    assert ad["ctr_first_half"] == 2.0
    assert ad["ctr_second_half"] == 1.2
    assert ad["ctr_change"] == -0.4
    assert ad["frequency"] == 4.2
    assert ad["fatigue_score"] == meta_creatives.fatigue_score(4.2, -0.4)
    assert ad["recommendation"].startswith("Rotate")
    assert result["summary"] == {"scored": 1, "fatigued": 1, "near_fatigue": 0, "not_scored": 0}


def test_moderate_frequency_with_a_smaller_decline_is_near_fatigue():
    ad = score(daily("1", (1000, 20), (1000, 17)), [total("1", 2.8)])["ads"][0]
    assert ad["status"] == "near_fatigue"


def test_falling_ctr_at_low_frequency_is_not_fatigue():
    ad = score(daily("1", (1000, 20), (1000, 10)), [total("1", 1.4)])["ads"][0]
    assert ad["status"] == "ok"
    assert ad["recommendation"] == "Keep running."


def test_high_frequency_with_stable_ctr_is_not_fatigue():
    ad = score(daily("1", (1000, 20), (1000, 20)), [total("1", 6.0)])["ads"][0]
    assert ad["status"] == "ok"
    assert ad["ctr_change"] == 0.0


def test_cpm_drift_is_reported():
    rows = daily("1", (1000, 20), (1000, 20))
    for row in rows[7:]:
        row["spend"] = "15.0"
    ad = score(rows, [total("1", 3.5)])["ads"][0]
    assert ad["cpm_first_half"] == 10.0
    assert ad["cpm_second_half"] == 15.0
    assert ad["cpm_change"] == 0.5


def test_ad_with_too_few_impressions_in_a_half_is_not_scored():
    result = score(daily("1", (1000, 20), (100, 1)), [total("1", 4.0)])
    assert result["ads"] == []
    assert result["not_scored"] == [{
        "ad_id": "1", "ad_name": "Ad 1", "adset_id": "s1", "campaign_id": "c1",
        "reason": "too few impressions in one half",
        "impressions_first_half": 7000, "impressions_second_half": 700}]


def test_minimum_impressions_is_configurable():
    result = score(daily("1", (1000, 20), (100, 1)), [total("1", 4.0)], min_impressions=500)
    assert len(result["ads"]) == 1


def test_ad_that_started_mid_period_is_not_scored():
    rows = daily("1", (1000, 20), (1000, 12))[7:]
    result = score(rows, [total("1", 4.0)])
    assert result["not_scored"][0]["impressions_first_half"] == 0


def test_ad_without_clicks_in_the_first_half_is_not_scored():
    result = score(daily("1", (1000, 0), (1000, 5)), [total("1", 4.0)])
    assert result["not_scored"][0]["reason"] == "no period totals or no clicks to compare"


def test_ads_are_sorted_by_score_and_output_ignores_input_order():
    rows = daily("1", (1000, 20), (1000, 19)) + daily("2", (1000, 20), (1000, 8)) + \
        daily("3", (1000, 20), (1000, 14))
    totals = [total("1", 2.0), total("2", 5.0), total("3", 3.4)]
    expected = score(rows, totals)
    assert [a["ad_id"] for a in expected["ads"]] == ["2", "3", "1"]
    for seed in range(5):
        shuffled_rows, shuffled_totals = rows[:], totals[:]
        random.Random(seed).shuffle(shuffled_rows)
        random.Random(seed).shuffle(shuffled_totals)
        assert score(shuffled_rows, shuffled_totals) == expected


class FakeAccount:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def get_insights(self, fields=None, params=None):
        FakeAccount.calls.append(params)
        if params.get("time_increment") == "1":
            start = date.today() - timedelta(days=14)
            rows = daily("1", (1000, 20), (1000, 12))
            for offset, row in enumerate(rows):
                row["date_start"] = (start + timedelta(days=offset)).isoformat()
            return rows
        return [total("1", 4.2)]


def run_main(argv):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["meta_creatives.py"] + argv), \
            mock.patch.dict("os.environ", {"META_ACCESS_TOKEN": "placeholder"}), \
            mock.patch("facebook_business.adobjects.adaccount.AdAccount", FakeAccount), \
            mock.patch.object(meta_utils, "init_api", return_value=None), \
            contextlib.redirect_stdout(out):
        meta_creatives.main()
    return json.loads(out.getvalue())


def test_fatigue_flag_scores_ads_over_14_complete_days():
    FakeAccount.calls = []
    result = run_main(["--account", "act_1", "--fatigue"])
    assert result["status"] == "ok"
    assert result["window"]["days"] == 14
    assert result["ads"][0]["status"] == "fatigued"
    today = date.today()
    for params in FakeAccount.calls:
        assert params["level"] == "ad"
        assert params["time_range"] == {"since": (today - timedelta(days=14)).isoformat(),
                                        "until": (today - timedelta(days=1)).isoformat()}


def test_fatigue_calls_go_through_the_cache():
    FakeAccount.calls = []
    first = run_main(["--account", "act_1", "--fatigue"])
    second = run_main(["--account", "act_1", "--fatigue"])
    assert len(FakeAccount.calls) == 2
    assert first == second
    run_main(["--account", "act_1", "--fatigue", "--days", "7"])
    assert len(FakeAccount.calls) == 4


def test_fatigue_fields_exist_in_the_sdk():
    from facebook_business.adobjects.adsinsights import AdsInsights

    known = {v for k, v in vars(AdsInsights.Field).items() if not k.startswith("_")}
    assert set(meta_creatives.FATIGUE_DAILY_FIELDS) <= known
    assert set(meta_creatives.FATIGUE_TOTAL_FIELDS) <= known
