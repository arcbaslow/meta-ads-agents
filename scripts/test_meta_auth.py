import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import meta_auth


class TestCredentialsFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.creds_path = os.path.join(self.tmpdir, "meta-ads-credentials.json")
        meta_auth.CREDENTIALS_PATH = self.creds_path

    def test_load_credentials_missing_file(self):
        result = meta_auth.load_credentials()
        self.assertIsNone(result)

    def test_save_and_load_credentials(self):
        creds = {
            "auth_method": "manual",
            "app_id": "123",
            "app_secret": "secret",
            "access_token": "token123",
            "token_expiry": "2026-06-05T00:00:00",
            "ad_accounts": [{"id": "act_111", "name": "Test", "currency": "USD"}],
        }
        meta_auth.save_credentials(creds)
        loaded = meta_auth.load_credentials()
        self.assertEqual(loaded["app_id"], "123")
        self.assertEqual(loaded["ad_accounts"][0]["id"], "act_111")

    def test_check_no_credentials(self):
        result = meta_auth.check_auth()
        self.assertEqual(result["status"], "error")
        self.assertIn("No credentials", result["message"])


class TestTokenValidation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.creds_path = os.path.join(self.tmpdir, "meta-ads-credentials.json")
        meta_auth.CREDENTIALS_PATH = self.creds_path

    @patch("meta_auth.validate_token_with_api")
    def test_check_valid_token(self, mock_validate):
        mock_validate.return_value = {
            "is_valid": True,
            "expires_at": 1749081600,
            "scopes": ["ads_read", "read_insights"],
        }
        creds = {
            "auth_method": "manual",
            "app_id": "123",
            "app_secret": "secret",
            "access_token": "valid_token",
            "token_expiry": "2026-06-05T00:00:00",
            "ad_accounts": [],
        }
        meta_auth.save_credentials(creds)
        result = meta_auth.check_auth()
        self.assertEqual(result["status"], "ok")

    @patch("meta_auth.validate_token_with_api")
    def test_check_expired_token(self, mock_validate):
        mock_validate.return_value = {"is_valid": False, "error": "Token expired"}
        creds = {
            "auth_method": "manual",
            "app_id": "123",
            "app_secret": "secret",
            "access_token": "expired_token",
            "token_expiry": "2024-01-01T00:00:00",
            "ad_accounts": [],
        }
        meta_auth.save_credentials(creds)
        result = meta_auth.check_auth()
        self.assertEqual(result["status"], "error")

    @patch("meta_auth.validate_token_with_api")
    def test_check_token_near_expiry_warning(self, mock_validate):
        """Token expiring within 7 days should include a warning."""
        mock_validate.return_value = {"is_valid": True, "expires_at": 0, "scopes": []}
        from datetime import datetime, timedelta, timezone
        near_expiry = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
        creds = {
            "auth_method": "oauth",
            "app_id": "123",
            "app_secret": "secret",
            "access_token": "almost_expired_token",
            "token_expiry": near_expiry,
            "ad_accounts": [],
        }
        meta_auth.save_credentials(creds)
        result = meta_auth.check_auth()
        self.assertEqual(result["status"], "ok")
        self.assertIn("expires_in_days", result)
        self.assertIn("warning", result)

    @patch("meta_auth.validate_token_with_api")
    def test_check_token_far_expiry_no_warning(self, mock_validate):
        """Token with >7 days left should NOT include a warning."""
        mock_validate.return_value = {"is_valid": True, "expires_at": 0, "scopes": []}
        from datetime import datetime, timedelta, timezone
        far_expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
        creds = {
            "auth_method": "oauth",
            "app_id": "123",
            "app_secret": "secret",
            "access_token": "good_token",
            "token_expiry": far_expiry,
            "ad_accounts": [],
        }
        meta_auth.save_credentials(creds)
        result = meta_auth.check_auth()
        self.assertEqual(result["status"], "ok")
        self.assertIn("expires_in_days", result)
        self.assertNotIn("warning", result)


class TestTokenFromEnvironment(unittest.TestCase):
    """META_ACCESS_TOKEN lets the adapters run with nothing stored on disk."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        meta_auth.CREDENTIALS_PATH = os.path.join(self.tmpdir, "meta-ads-credentials.json")

    def test_no_token_anywhere(self):
        self.assertIsNone(meta_auth.get_access_token())

    def test_file_token_is_used_when_the_variable_is_unset(self):
        meta_auth.save_credentials({"access_token": "from-file"})
        self.assertEqual(meta_auth.get_access_token(), "from-file")

    def test_environment_wins_over_the_file(self):
        meta_auth.save_credentials({"access_token": "from-file"})
        with patch.dict(os.environ, {meta_auth.TOKEN_ENV_VAR: "from-env"}):
            self.assertEqual(meta_auth.get_access_token(), "from-env")

    def test_blank_variable_is_ignored(self):
        meta_auth.save_credentials({"access_token": "from-file"})
        with patch.dict(os.environ, {meta_auth.TOKEN_ENV_VAR: "  "}):
            self.assertEqual(meta_auth.get_access_token(), "from-file")

    @patch("meta_auth.validate_token_with_api", return_value={"is_valid": True})
    def test_check_with_environment_token_needs_no_file(self, _validate):
        with patch.dict(os.environ, {meta_auth.TOKEN_ENV_VAR: "from-env"}):
            result = meta_auth.check_auth()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["auth_method"], "env")
        self.assertNotIn("from-env", str(result))
        self.assertFalse(os.path.exists(meta_auth.CREDENTIALS_PATH))

    @patch("meta_auth.list_ad_accounts", return_value=[{"id": "act_1", "name": "A"}])
    def test_accounts_with_environment_token_go_through_the_cache(self, list_accounts):
        with patch.dict(os.environ, {meta_auth.TOKEN_ENV_VAR: "from-env"}):
            first = meta_auth.accounts_result()
            second = meta_auth.accounts_result()
        self.assertEqual(first, second)
        self.assertEqual(first["ad_accounts"][0]["id"], "act_1")
        self.assertEqual(list_accounts.call_count, 1)

    def test_adapter_reports_missing_token_as_json(self):
        import contextlib
        import io
        import json
        import sys

        import meta_insights

        out = io.StringIO()
        with patch.object(sys, "argv", ["meta_insights.py", "--account", "act_1"]), \
                contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            meta_insights.main()
        result = json.loads(out.getvalue())
        self.assertEqual(result["status"], "error")
        self.assertIn(meta_auth.TOKEN_ENV_VAR, result["message"])


class TestOAuthCallbackState(unittest.TestCase):
    """The callback listener must reject a code that doesn't carry our state."""

    def _dispatch(self, path, expected_state):
        handler = meta_auth.OAuthCallbackHandler.__new__(meta_auth.OAuthCallbackHandler)
        handler.path = path
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        meta_auth.OAuthCallbackHandler.auth_code = None
        meta_auth.OAuthCallbackHandler.expected_state = expected_state
        handler.do_GET()
        return handler

    def tearDown(self):
        meta_auth.OAuthCallbackHandler.auth_code = None
        meta_auth.OAuthCallbackHandler.expected_state = None

    def test_matching_state_accepts_code(self):
        handler = self._dispatch("/callback?code=good_code&state=s3cr3t", "s3cr3t")
        self.assertEqual(meta_auth.OAuthCallbackHandler.auth_code, "good_code")
        handler.send_response.assert_called_once_with(200)

    def test_mismatched_state_rejects_code(self):
        handler = self._dispatch("/callback?code=evil_code&state=wrong", "s3cr3t")
        self.assertIsNone(meta_auth.OAuthCallbackHandler.auth_code)
        handler.send_response.assert_called_once_with(400)

    def test_missing_state_rejects_code(self):
        handler = self._dispatch("/callback?code=evil_code", "s3cr3t")
        self.assertIsNone(meta_auth.OAuthCallbackHandler.auth_code)
        handler.send_response.assert_called_once_with(400)


if __name__ == "__main__":
    unittest.main()
