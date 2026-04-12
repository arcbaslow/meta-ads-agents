import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import meta_campaigns
import meta_utils


class TestCacheLayerBackwardCompat(unittest.TestCase):
    """Cache functions are now in meta_utils; verify aliases still work."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig = meta_utils.CACHE_DIR
        meta_utils.CACHE_DIR = self.tmpdir

    def tearDown(self):
        meta_utils.CACHE_DIR = self._orig

    def test_cache_write_and_read_via_campaigns(self):
        data = {"campaigns": [{"id": "123", "name": "Test Campaign"}]}
        meta_campaigns.write_cache("act_111", "campaigns", data)
        loaded = meta_campaigns.read_cache("act_111", "campaigns", ttl_seconds=900)
        self.assertEqual(loaded["campaigns"][0]["id"], "123")


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


class TestRetryBackwardCompat(unittest.TestCase):
    """Verify api_call_with_retry alias still works via meta_campaigns."""

    def test_succeeds_on_first_try(self):
        call_count = [0]
        def good_fn():
            call_count[0] += 1
            return "ok"
        result = meta_campaigns.api_call_with_retry(good_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 1)

    def test_raises_non_retryable_immediately(self):
        """Non-retryable errors should not be retried (new behavior)."""
        call_count = [0]
        def buggy_fn():
            call_count[0] += 1
            raise KeyError("bad key")
        with self.assertRaises(KeyError):
            meta_campaigns.api_call_with_retry(buggy_fn, max_retries=3, base_delay=0)
        self.assertEqual(call_count[0], 1)

    def test_retries_on_connection_error(self):
        call_count = [0]
        def flaky_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("refused")
            return "ok"
        result = meta_campaigns.api_call_with_retry(flaky_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)


if __name__ == "__main__":
    unittest.main()
