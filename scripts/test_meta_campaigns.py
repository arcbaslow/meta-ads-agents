import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import meta_campaigns


class TestCacheLayer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        meta_campaigns.CACHE_DIR = self.tmpdir

    def test_cache_write_and_read(self):
        data = {"campaigns": [{"id": "123", "name": "Test Campaign"}]}
        meta_campaigns.write_cache("act_111", "campaigns", data)
        loaded = meta_campaigns.read_cache("act_111", "campaigns", ttl_seconds=900)
        self.assertEqual(loaded["campaigns"][0]["id"], "123")

    def test_cache_miss_when_expired(self):
        data = {"campaigns": []}
        meta_campaigns.write_cache("act_111", "campaigns", data)
        loaded = meta_campaigns.read_cache("act_111", "campaigns", ttl_seconds=0)
        self.assertIsNone(loaded)

    def test_cache_miss_when_no_file(self):
        loaded = meta_campaigns.read_cache("act_999", "campaigns", ttl_seconds=900)
        self.assertIsNone(loaded)


class TestOutputFormat(unittest.TestCase):
    def test_format_campaign_hierarchy(self):
        campaigns = [
            {"id": "1", "name": "Campaign A", "status": "ACTIVE", "objective": "OUTCOME_SALES"},
        ]
        adsets = [
            {"id": "10", "campaign_id": "1", "name": "AdSet A1", "status": "ACTIVE"},
        ]
        ads = [
            {"id": "100", "adset_id": "10", "name": "Ad A1a", "status": "ACTIVE"},
        ]
        result = meta_campaigns.build_hierarchy(campaigns, adsets, ads)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "1")
        self.assertEqual(len(result[0]["adsets"]), 1)
        self.assertEqual(len(result[0]["adsets"][0]["ads"]), 1)


class TestRetryWrapper(unittest.TestCase):
    def test_succeeds_on_first_try(self):
        call_count = [0]
        def good_fn():
            call_count[0] += 1
            return "ok"
        result = meta_campaigns.api_call_with_retry(good_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 1)

    def test_retries_on_rate_limit(self):
        call_count = [0]
        def flaky_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("too many calls")
            return "ok"
        result = meta_campaigns.api_call_with_retry(flaky_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)

    def test_raises_after_max_retries(self):
        def always_fails():
            raise Exception("rate limited")
        with self.assertRaises(Exception):
            meta_campaigns.api_call_with_retry(always_fails, max_retries=2, base_delay=0)


if __name__ == "__main__":
    unittest.main()
