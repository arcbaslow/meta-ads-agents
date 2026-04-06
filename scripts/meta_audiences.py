#!/usr/bin/env python3
"""Fetch Meta Ads audience data: custom audiences, targeting specs, demographics."""

import argparse
import json
import sys

import meta_auth
import meta_campaigns


def classify_audience(audience):
    """Classify audience type: custom, lookalike, or saved."""
    subtype = audience.get("subtype", "").upper()
    if "LOOKALIKE" in subtype:
        return "lookalike"
    if "CUSTOM" in subtype:
        return "custom"
    return "saved"


def summarize_targeting(targeting):
    """Extract a readable summary from a targeting spec."""
    interests = []
    for spec in targeting.get("flexible_spec", []):
        for interest in spec.get("interests", []):
            interests.append(interest.get("name", ""))

    age_min = targeting.get("age_min", 18)
    age_max = targeting.get("age_max", 65)
    genders = targeting.get("genders", [])
    gender_map = {1: "male", 2: "female"}
    gender_names = [gender_map.get(g, "all") for g in genders] or ["all"]

    geo = targeting.get("geo_locations", {})
    countries = geo.get("countries", [])
    cities = [c.get("name", "") for c in geo.get("cities", [])]
    regions = [r.get("name", "") for r in geo.get("regions", [])]

    return {
        "interests": interests,
        "age_range": f"{age_min}-{age_max}",
        "genders": gender_names,
        "countries": countries,
        "cities": cities,
        "regions": regions,
        "excluded_custom_audiences": [
            a.get("name", a.get("id"))
            for a in targeting.get("exclusions", {}).get("custom_audiences", [])
        ],
    }


def fetch_custom_audiences(account_id, access_token):
    """Fetch custom audiences for an account."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    fields = [
        "id", "name", "subtype",
        "data_source", "delivery_status", "operation_status",
        "retention_days", "time_created", "time_updated",
    ]
    audiences = meta_campaigns.api_call_with_retry(
        lambda: list(account.get_custom_audiences(fields=fields))
    )
    return [meta_campaigns.to_plain(dict(a)) for a in audiences]


def fetch_adset_targeting(account_id, access_token):
    """Fetch targeting specs from all ad sets."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.adaccount import AdAccount

    api = FacebookAdsApi.init(access_token=access_token)
    account = AdAccount(account_id, api=api)

    fields = ["id", "name", "campaign_id", "status", "targeting"]
    adsets = list(account.get_ad_sets(fields=fields))

    result = []
    for adset in adsets:
        targeting = adset.get("targeting", {})
        result.append({
            "adset_id": adset["id"],
            "adset_name": adset.get("name"),
            "campaign_id": adset.get("campaign_id"),
            "status": adset.get("status"),
            "targeting_summary": summarize_targeting(targeting),
            "raw_targeting": targeting,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch Meta Ads audience data")
    parser.add_argument("--account", required=True, help="Ad account ID")
    parser.add_argument("--overlap", action="store_true", help="Show audience overlap between ad sets")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    parser.add_argument("--json", action="store_true", default=True)

    args = parser.parse_args()

    creds = meta_auth.load_credentials()
    if not creds:
        print(json.dumps({"status": "error", "message": "No credentials"}))
        sys.exit(1)

    token = creds["access_token"]
    cache_key = "audiences"

    if not args.no_cache:
        cached = meta_campaigns.read_cache(args.account, cache_key)
        if cached:
            print(json.dumps(cached, indent=2))
            return

    custom_audiences = fetch_custom_audiences(args.account, token)
    adset_targeting = fetch_adset_targeting(args.account, token)

    # Classify audiences
    for aud in custom_audiences:
        aud["type"] = classify_audience(aud)

    result = {
        "status": "ok",
        "account_id": args.account,
        "total_custom_audiences": len(custom_audiences),
        "total_adsets_with_targeting": len(adset_targeting),
        "custom_audiences": custom_audiences,
        "adset_targeting": adset_targeting,
    }

    meta_campaigns.write_cache(args.account, cache_key, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
