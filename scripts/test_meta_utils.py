"""Tests for meta_utils shared utilities."""

import json
import os
import tempfile
import time
import unittest

import meta_utils


class TestCacheLayer(unittest.TestCase):
    """Tests for read_cache / write_cache with cross-platform path."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cache_dir = meta_utils.CACHE_DIR
        meta_utils.CACHE_DIR = self.tmpdir

    def tearDown(self):
        meta_utils.CACHE_DIR = self._orig_cache_dir

    def test_cache_write_and_read(self):
        data = {"campaigns": [{"id": "123", "name": "Test Campaign"}]}
        meta_utils.write_cache("act_111", "campaigns", data)
        loaded = meta_utils.read_cache("act_111", "campaigns", ttl_seconds=900)
        self.assertEqual(loaded["campaigns"][0]["id"], "123")

    def test_cache_miss_when_expired(self):
        data = {"campaigns": []}
        meta_utils.write_cache("act_111", "campaigns", data)
        loaded = meta_utils.read_cache("act_111", "campaigns", ttl_seconds=0)
        self.assertIsNone(loaded)

    def test_cache_miss_when_no_file(self):
        loaded = meta_utils.read_cache("act_999", "campaigns", ttl_seconds=900)
        self.assertIsNone(loaded)

    def test_cache_dir_is_cross_platform(self):
        """Cache dir should use tempfile, not hardcoded /tmp."""
        self.assertNotEqual(self._orig_cache_dir, "/tmp/claude-meta-ads")
        self.assertIn("claude-meta-ads", self._orig_cache_dir)

    def test_cache_read_invalid_json_returns_none(self):
        """Corrupt cache files should not crash — return None."""
        path = os.path.join(self.tmpdir, "act_111_broken.json")
        with open(path, "w") as f:
            f.write("{invalid json!!!")
        loaded = meta_utils.read_cache("act_111", "broken", ttl_seconds=900)
        self.assertIsNone(loaded)


class TestToPlain(unittest.TestCase):
    def test_dict_passthrough(self):
        self.assertEqual(meta_utils.to_plain({"a": 1}), {"a": 1})

    def test_nested_list(self):
        self.assertEqual(meta_utils.to_plain([{"a": [1, 2]}]), [{"a": [1, 2]}])

    def test_plain_types_passthrough(self):
        for val in [42, 3.14, "hello", True, None]:
            self.assertEqual(meta_utils.to_plain(val), val)

    def test_object_with_export_all_data(self):
        class FakeSDKObject:
            def export_all_data(self):
                return {"id": "123", "name": "Test"}
        result = meta_utils.to_plain(FakeSDKObject())
        self.assertEqual(result, {"id": "123", "name": "Test"})


class TestRetryLogic(unittest.TestCase):
    def test_succeeds_on_first_try(self):
        call_count = [0]
        def good_fn():
            call_count[0] += 1
            return "ok"
        result = meta_utils.api_call_with_retry(good_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 1)

    def test_raises_non_retryable_immediately(self):
        """Programming errors like KeyError should NOT be retried."""
        call_count = [0]
        def buggy_fn():
            call_count[0] += 1
            raise KeyError("missing key")
        with self.assertRaises(KeyError):
            meta_utils.api_call_with_retry(buggy_fn, max_retries=3, base_delay=0)
        # Should only be called once — no retries for programming errors
        self.assertEqual(call_count[0], 1)

    def test_raises_after_max_retries_on_connection_error(self):
        """Connection errors should be retried, then bubble up."""
        call_count = [0]
        def network_error():
            call_count[0] += 1
            raise ConnectionError("refused")
        with self.assertRaises(ConnectionError):
            meta_utils.api_call_with_retry(network_error, max_retries=2, base_delay=0)
        # 1 initial + 2 retries = 3 calls
        self.assertEqual(call_count[0], 3)

    def test_retries_on_timeout_then_succeeds(self):
        call_count = [0]
        def flaky_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise TimeoutError("timed out")
            return "ok"
        result = meta_utils.api_call_with_retry(flaky_fn, max_retries=3, base_delay=0)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)


if __name__ == "__main__":
    unittest.main()
