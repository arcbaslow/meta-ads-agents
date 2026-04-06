import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

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


if __name__ == "__main__":
    unittest.main()
