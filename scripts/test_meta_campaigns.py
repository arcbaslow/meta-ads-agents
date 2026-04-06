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


if __name__ == "__main__":
    unittest.main()
