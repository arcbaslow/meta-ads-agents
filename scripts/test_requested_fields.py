"""Every field an adapter requests must exist on that object in the SDK.

The Graph API rejects a request that names a field the node does not have,
and nothing in the mocked suite would notice: `meta_creatives.py
--with-metrics` asked the Ad node for `effective_object_story_spec`, which
is not a field of Ad or of AdCreative, and the tests stayed green.

This runs each fetch function against a recording stand-in for the ad
account and compares what it asked for with the field lists the SDK
generates from Meta's API spec. It checks names against the installed SDK
version, so it also flags a field that a version bump removes.
"""

from unittest import mock

import meta_audiences
import meta_campaigns
import meta_changes
import meta_creatives
import meta_delivery
import meta_events
import meta_insights
import pytest
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adactivity import AdActivity
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.adsinsights import AdsInsights
from facebook_business.adobjects.adspixel import AdsPixel
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.customaudience import CustomAudience

EDGE_OBJECTS = {
    "api_get": AdAccount,
    "get_activities": AdActivity,
    "get_campaigns": Campaign,
    "get_ad_sets": AdSet,
    "get_ads": Ad,
    "get_ad_creatives": AdCreative,
    "get_custom_audiences": CustomAudience,
    "get_ads_pixels": AdsPixel,
    "get_insights": AdsInsights,
}


def names(enum_class):
    return {v for k, v in vars(enum_class).items() if not k.startswith("_")}


class RecordingAccount:
    """Stands in for AdAccount and records the fields and params of each call."""

    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, edge):
        if edge not in EDGE_OBJECTS:
            raise AttributeError(edge)

        def call(fields=None, params=None):
            RecordingAccount.calls.append((edge, list(fields or []), dict(params or {})))
            return []

        return call


@pytest.fixture
def recorded():
    RecordingAccount.calls = []
    with mock.patch("facebook_business.adobjects.adaccount.AdAccount", RecordingAccount), \
            mock.patch("facebook_business.api.FacebookAdsApi.init", return_value=None):
        yield RecordingAccount.calls


FETCHES = [
    lambda: meta_campaigns.fetch_campaigns("act_1", "unused"),
    lambda: meta_campaigns.fetch_adsets("act_1", "unused", active_only=True),
    lambda: meta_campaigns.fetch_ads("act_1", "unused"),
    lambda: meta_insights.fetch_insights("act_1", "unused", breakdown="placement"),
    lambda: meta_insights.fetch_insights("act_1", "unused", breakdown="age", time_increment="1"),
    lambda: meta_creatives.fetch_creatives("act_1", "unused"),
    lambda: meta_creatives.fetch_creatives_with_metrics("act_1", "unused"),
    lambda: meta_audiences.fetch_custom_audiences("act_1", "unused"),
    lambda: meta_audiences.fetch_adset_targeting("act_1", "unused"),
    lambda: meta_events.fetch_pixel_events("act_1", "unused"),
    lambda: meta_events.fetch_pixel_health("act_1", "unused"),
    lambda: meta_creatives.fetch_fatigue_inputs("act_1", "unused", 14, no_cache=True),
    lambda: meta_delivery.fetch_inputs("act_1", "unused", 7, no_cache=True),
    lambda: meta_changes.fetch_inputs("act_1", "unused", 14, 3, "ad", no_cache=True),
]


def unknown_fields(calls):
    """Requested fields that the SDK does not define for the edge's object."""
    unknown = []
    for edge, fields, _params in calls:
        known = names(EDGE_OBJECTS[edge].Field)
        unknown += [f"{edge}: {field}" for field in fields if field not in known]
    return unknown


def test_requested_fields_exist_in_the_sdk(recorded):
    for fetch in FETCHES:
        fetch()
    assert len(recorded) >= len(FETCHES)
    assert not unknown_fields(recorded)


def test_requested_breakdowns_and_windows_exist_in_the_sdk():
    breakdowns = names(AdsInsights.Breakdowns)
    for requested in meta_insights.BREAKDOWNS.values():
        assert set(requested) <= breakdowns, requested

    params = meta_insights.build_attribution_params()
    windows = names(AdsInsights.ActionAttributionWindows)
    assert set(params["action_attribution_windows"]) <= windows
    assert set(params["action_breakdowns"]) <= names(AdsInsights.ActionBreakdowns)


def test_ads_are_not_asked_for_a_field_they_do_not_have(recorded):
    """Regression: effective_object_story_spec was requested on the Ad node."""
    meta_creatives.fetch_creatives_with_metrics("act_1", "unused")
    requested = {field for _edge, fields, _params in recorded for field in fields}
    assert "effective_object_story_spec" not in requested
