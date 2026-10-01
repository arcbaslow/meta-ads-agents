"""Tests for meta_utils shared utilities."""

import contextlib
import io
import json
import os
import tempfile
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


def _request_error(code, transient=False, subcode=None, headers=None, message="x"):
    """Build the SDK's request error the way a failed Graph API call does."""
    from facebook_business.exceptions import FacebookRequestError
    error = {"code": code, "message": message, "is_transient": transient}
    if subcode:
        error["error_subcode"] = subcode
    context = {"method": "GET", "path": "/act_1/insights", "params": {"level": "ad"}}
    return FacebookRequestError("x", context, 400, headers or {}, json.dumps({"error": error}))


def _network_error():
    """What requests raises when the API is unreachable: the message quotes
    the request URL, query string included."""
    import requests
    return requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='graph.facebook.com', port=443): Max retries exceeded "
        "with url: /v26.0/act_1/insights?access_token=PLACEHOLDER-TOKEN&level=ad"
        "&appsecret_proof=PLACEHOLDER-PROOF (Caused by NewConnectionError())")


class TestTokenNeverLeavesInAnError(unittest.TestCase):
    def test_redact_blanks_credential_parameters(self):
        text = meta_utils.redact(str(_network_error()))
        self.assertNotIn("PLACEHOLDER-TOKEN", text)
        self.assertNotIn("PLACEHOLDER-PROOF", text)
        self.assertIn("access_token=REDACTED", text)
        self.assertIn("level=ad", text)

    def test_retry_warning_does_not_log_the_token(self):
        def unreachable():
            raise _network_error()

        with self.assertLogs("meta_ads", level="WARNING") as logs, \
                self.assertRaises(Exception):
            meta_utils.api_call_with_retry(unreachable, max_retries=1, base_delay=0)
        self.assertTrue(logs.output)
        self.assertNotIn("PLACEHOLDER-TOKEN", " ".join(logs.output))

    def test_network_error_is_reported_as_json_without_the_token(self):
        def main():
            raise _network_error()

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit) as raised:
            meta_utils.run_cli(main)
        self.assertEqual(raised.exception.code, 1)
        result = json.loads(out.getvalue())
        self.assertEqual(result["error_kind"], "network")
        self.assertNotIn("PLACEHOLDER-TOKEN", out.getvalue() + err.getvalue())

    def test_api_error_text_is_metas_message_only(self):
        text = meta_utils.error_text(_request_error(190, message="Session has expired"))
        self.assertEqual(text, "Session has expired (code 190)")


class TestApiErrorReporting(unittest.TestCase):
    """An API failure used to end in a traceback and an empty stdout."""

    def _run(self, exc):
        def main():
            raise exc

        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            meta_utils.run_cli(main)
        self.assertEqual(raised.exception.code, 1)
        return json.loads(out.getvalue())

    def test_expired_token_is_reported_with_a_next_step(self):
        result = self._run(_request_error(190, subcode=463, message="Session has expired"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_kind"], "auth")
        self.assertEqual(result["error_code"], 190)
        self.assertEqual(result["error_subcode"], 463)
        self.assertIn("meta_auth.py", result["action"])

    def test_throttle_reports_the_wait_from_the_usage_header(self):
        usage = {"123": [{"type": "ads_insights", "call_count": 100,
                          "estimated_time_to_regain_access": 19}]}
        headers = {"X-Business-Use-Case-Usage": json.dumps(usage)}
        result = self._run(_request_error(80000, headers=headers))
        self.assertEqual(result["error_kind"], "rate_limit")
        self.assertEqual(result["retry_after_minutes"], 19)

    def test_throttle_without_header_still_explains_itself(self):
        result = self._run(_request_error(17))
        self.assertEqual(result["error_kind"], "rate_limit")
        self.assertNotIn("retry_after_minutes", result)

    def test_too_much_data_suggests_a_smaller_query(self):
        result = self._run(_request_error(100, subcode=1487534))
        self.assertEqual(result["error_kind"], "too_much_data")

    def test_other_api_errors_keep_metas_message(self):
        result = self._run(_request_error(100, message="Invalid parameter"))
        self.assertEqual(result["error_kind"], "api")
        self.assertEqual(result["message"], "Invalid parameter")

    def test_request_context_is_not_echoed(self):
        result = self._run(_request_error(100))
        self.assertNotIn("/act_1/insights", json.dumps(result))

    def test_programming_errors_are_not_swallowed(self):
        def main():
            raise KeyError("bug")

        with self.assertRaises(KeyError):
            meta_utils.run_cli(main)

    def test_unreadable_usage_header_is_ignored(self):
        self.assertIsNone(meta_utils.minutes_to_regain_access(
            {"x-business-use-case-usage": "not json"}))
        self.assertIsNone(meta_utils.minutes_to_regain_access({}))


class TestRetryableErrors(unittest.TestCase):
    def test_insights_throttle_code_is_retried(self):
        """80000 is the ads insights business use case limit."""
        self.assertTrue(meta_utils._is_retryable(_request_error(80000)))

    def test_rate_limit_code_613_is_retried(self):
        self.assertTrue(meta_utils._is_retryable(_request_error(613)))

    def test_transient_flag_is_retried(self):
        self.assertTrue(meta_utils._is_retryable(_request_error(99999, transient=True)))

    def test_invalid_parameter_is_not_retried(self):
        self.assertFalse(meta_utils._is_retryable(_request_error(100)))

    def test_expired_token_is_not_retried(self):
        self.assertFalse(meta_utils._is_retryable(_request_error(190)))

    def test_requests_connection_error_is_retried(self):
        """The SDK raises requests' own ConnectionError, not the builtin."""
        import requests
        self.assertTrue(meta_utils._is_retryable(requests.exceptions.ConnectionError("reset")))

    def test_requests_timeout_is_retried(self):
        import requests
        self.assertTrue(meta_utils._is_retryable(requests.exceptions.ReadTimeout("slow")))


class TestApiVersion(unittest.TestCase):
    def test_sdk_calls_use_the_pinned_version(self):
        api = meta_utils.init_api("placeholder")
        self.assertEqual(api._api_version, meta_utils.API_VERSION)

    def test_oauth_urls_use_the_pinned_version(self):
        """The OAuth URLs carried a hardcoded v21.0 of their own."""
        import inspect

        import meta_auth

        source = inspect.getsource(meta_auth)
        self.assertNotRegex(source, r"facebook\.com/v\d+\.\d+/")
        self.assertEqual(source.count("{meta_utils.API_VERSION}"), 3)

    def test_dependency_range_matches_the_pinned_version(self):
        """The SDK's field lists are generated per API version, so the
        installed major has to be the one the adapters call."""
        import re
        from pathlib import Path

        major = meta_utils.API_VERSION.lstrip("v").split(".")[0]
        root = Path(__file__).resolve().parent.parent
        for path in (root / "pyproject.toml", root / "scripts" / "requirements.txt"):
            match = re.search(r"facebook-business>=(\d+)\.[\d.]+,<(\d+)", path.read_text())
            self.assertIsNotNone(match, path)
            self.assertEqual(match.group(1), major, path)
            self.assertEqual(int(match.group(2)), int(major) + 1, path)


class TestApiInit(unittest.TestCase):
    def test_crash_reporter_is_not_installed(self):
        """The SDK's crash reporter posts call stacks to Meta when enabled."""
        import sys

        from facebook_business.crashreporter import CrashReporter

        hook = sys.excepthook
        api = meta_utils.init_api("placeholder")
        self.assertIsNotNone(api)
        self.assertIsNone(CrashReporter.reporter_instance)
        self.assertIs(sys.excepthook, hook)


class TestAccountIdNormalization(unittest.TestCase):
    """The README promises that 123 and act_123 both work."""

    def test_bare_number_gets_the_prefix(self):
        self.assertEqual(meta_utils.normalize_account_id("123456789"), "act_123456789")

    def test_prefixed_id_is_unchanged(self):
        self.assertEqual(meta_utils.normalize_account_id("act_123456789"), "act_123456789")

    def test_whitespace_and_prefix_case_are_tolerated(self):
        self.assertEqual(meta_utils.normalize_account_id(" ACT_42 "), "act_42")

    def test_garbage_is_rejected(self):
        for bad in ["", "act_", "act_12x", "my account"]:
            with self.assertRaises(ValueError):
                meta_utils.normalize_account_id(bad)

    def test_every_adapter_normalizes_its_account_argument(self):
        import argparse
        import sys
        from unittest import mock

        import meta_audiences
        import meta_campaigns
        import meta_creatives
        import meta_events
        import meta_insights

        for module in (meta_campaigns, meta_insights, meta_creatives,
                       meta_audiences, meta_events):
            seen = {}

            def capture(self, args=None, namespace=None, _seen=seen):
                _seen["args"] = _real(self, args, namespace)
                raise SystemExit(0)

            _real = argparse.ArgumentParser.parse_args
            with mock.patch.object(sys, "argv", ["x", "--account", "123456789"]),                     mock.patch.object(argparse.ArgumentParser, "parse_args", capture):
                with self.assertRaises(SystemExit):
                    module.main()
            self.assertEqual(seen["args"].account, "act_123456789", module.__name__)


if __name__ == "__main__":
    unittest.main()
