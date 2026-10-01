#!/usr/bin/env python3
"""Meta Ads authentication: OAuth flow, manual token config, and token validation."""

import argparse
import hmac
import json
import os
import secrets
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import meta_utils

CREDENTIALS_PATH = os.path.expanduser("~/.claude/meta-ads-credentials.json")
REDIRECT_URI = "http://localhost:8477/callback"
SCOPES = ["ads_read", "ads_management", "read_insights", "business_management"]

# A token in the environment wins over the credentials file. It is the way
# to run the adapters in CI or on a schedule, where nothing should be
# written to disk.
TOKEN_ENV_VAR = "META_ACCESS_TOKEN"
NO_TOKEN_MESSAGE = (
    f"No access token. Set {TOKEN_ENV_VAR}, or run meta_auth.py --oauth or --configure"
)


def load_credentials():
    """Load credentials from file. Returns None if file doesn't exist."""
    if not os.path.exists(CREDENTIALS_PATH):
        return None
    with open(CREDENTIALS_PATH, "r") as f:
        return json.load(f)


def get_access_token():
    """Return the access token to use, or None when there is none.

    Reads META_ACCESS_TOKEN first and falls back to the credentials file.
    """
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if token:
        return token
    creds = load_credentials()
    return (creds or {}).get("access_token") or None


def save_credentials(creds):
    """Save credentials to file, creating parent dirs if needed.

    On Unix, restricts the file to owner-read/write only (0600).
    """
    os.makedirs(os.path.dirname(CREDENTIALS_PATH), exist_ok=True)
    with open(CREDENTIALS_PATH, "w") as f:
        json.dump(creds, f, indent=2)
    # Restrict to owner-only on Unix systems
    if os.name != "nt":
        os.chmod(CREDENTIALS_PATH, stat.S_IRUSR | stat.S_IWUSR)


def validate_token_with_api(access_token):
    """Validate token against Meta's debug_token endpoint."""
    try:
        from facebook_business.adobjects.user import User

        api = meta_utils.init_api(access_token)
        me = User(fbid="me", api=api)
        me.api_get(fields=["id", "name"])
        return {"is_valid": True, "expires_at": 0, "scopes": SCOPES}
    except Exception as e:
        return {"is_valid": False, "error": meta_utils.error_text(e)}


def check_auth():
    """Check if current credentials are valid. Returns status JSON."""
    if os.environ.get(TOKEN_ENV_VAR, "").strip():
        result = validate_token_with_api(get_access_token())
        if not result.get("is_valid"):
            return {"status": "error",
                    "message": f"Token invalid: {result.get('error', 'unknown')}"}
        # Nothing is stored for an environment token, so there is no saved
        # expiry or account list to report. --accounts lists the accounts.
        return {"status": "ok", "auth_method": "env", "token_source": TOKEN_ENV_VAR}

    creds = load_credentials()
    if not creds:
        return {"status": "error", "message": "No credentials found. Run: meta_auth.py --oauth or --configure"}

    token = creds.get("access_token")
    if not token:
        return {"status": "error", "message": "No access token in credentials file"}

    result = validate_token_with_api(token)
    if result.get("is_valid"):
        response = {
            "status": "ok",
            "auth_method": creds.get("auth_method"),
            "ad_accounts": creds.get("ad_accounts", []),
            "token_expiry": creds.get("token_expiry"),
        }
        # Add expiry warning if token has a known expiry date
        expiry_str = creds.get("token_expiry")
        if expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str).replace(tzinfo=timezone.utc)
                days_left = (expiry - datetime.now(timezone.utc)).days
                response["expires_in_days"] = days_left
                if days_left < 0:
                    response["warning"] = "Token has expired. Re-authenticate with: meta_auth.py --oauth"
                elif days_left < 7:
                    response["warning"] = f"Token expires in {days_left} days. Re-authenticate soon."
            except (ValueError, TypeError):
                pass
        return response
    else:
        return {"status": "error", "message": f"Token invalid: {result.get('error', 'unknown')}"}



def list_ad_accounts(access_token):
    """Fetch all accessible ad accounts for the authenticated user."""
    from facebook_business.adobjects.user import User

    api = meta_utils.init_api(access_token)
    me = User(fbid="me", api=api)
    accounts = me.get_ad_accounts(fields=["id", "name", "currency", "account_status"])
    return [
        {
            "id": acc["id"],
            "name": acc.get("name", "Unnamed"),
            "currency": acc.get("currency", "USD"),
            "status": acc.get("account_status"),
        }
        for acc in accounts
    ]


def exchange_for_long_lived_token(app_id, app_secret, short_token):
    """Exchange short-lived token for a long-lived one (60 days).

    Raises:
        RuntimeError: If the Meta API returns an HTTP error.
    """
    params = urllib.parse.urlencode({
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    })
    url = f"https://graph.facebook.com/{meta_utils.API_VERSION}/oauth/access_token?{params}"
    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            error_body = json.loads(e.read().decode())
            msg = error_body.get("error", {}).get("message", str(e))
        except (json.JSONDecodeError, AttributeError):
            msg = str(e)
        raise RuntimeError(f"Token exchange failed: {msg}") from e
    return data["access_token"], data.get("expires_in", 5184000)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth redirect."""

    auth_code = None
    expected_state = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            # Reject a callback that doesn't carry the state we generated.
            # Without this, any local page can drive this listener into
            # exchanging an attacker-supplied code while it is open.
            got_state = params.get("state", [""])[0]
            if not hmac.compare_digest(got_state, OAuthCallbackHandler.expected_state or ""):
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h2>Error: state mismatch</h2>"
                                 b"<p>This callback did not originate from the login "
                                 b"that started here. Nothing was saved.</p></body></html>")
                return
            OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authentication successful!</h2><p>You can close this window.</p></body></html>")
        else:
            error = params.get("error_description", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>Error: {error}</h2></body></html>".encode())

    def log_message(self, format, *args):
        pass


def run_oauth_flow(app_id, app_secret):
    """Run the full OAuth flow: open browser, capture callback, exchange token."""
    state = secrets.token_urlsafe(32)
    OAuthCallbackHandler.auth_code = None
    OAuthCallbackHandler.expected_state = state

    auth_url = f"https://www.facebook.com/{meta_utils.API_VERSION}/dialog/oauth?" + urlencode({
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "state": state,
    })

    print("Opening browser for Facebook Login...")
    print(f"If browser doesn't open, visit: {auth_url}")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8477), OAuthCallbackHandler)
    server.timeout = 10  # per-request timeout, checked in loop
    deadline = time.time() + 120
    print("Waiting for authorization (timeout: 2 minutes)...")

    while OAuthCallbackHandler.auth_code is None:
        if time.time() > deadline:
            server.server_close()
            return {"status": "error", "message": "OAuth timed out after 2 minutes. Try again."}
        server.handle_request()

    code = OAuthCallbackHandler.auth_code
    server.server_close()

    params = urllib.parse.urlencode({
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    })
    url = f"https://graph.facebook.com/{meta_utils.API_VERSION}/oauth/access_token?{params}"
    try:
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            error_body = json.loads(e.read().decode())
            msg = error_body.get("error", {}).get("message", str(e))
        except (json.JSONDecodeError, AttributeError):
            msg = str(e)
        return {"status": "error", "message": f"OAuth code exchange failed: {msg}"}
    short_token = data["access_token"]

    long_token, expires_in = exchange_for_long_lived_token(app_id, app_secret, short_token)
    expiry_ts = time.time() + expires_in
    expiry_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(expiry_ts))

    accounts = list_ad_accounts(long_token)

    creds = {
        "auth_method": "oauth",
        "app_id": app_id,
        "app_secret": app_secret,
        "access_token": long_token,
        "token_expiry": expiry_str,
        "ad_accounts": accounts,
    }
    save_credentials(creds)
    return {"status": "ok", "ad_accounts": accounts, "token_expiry": expiry_str}


def run_manual_config(app_id, app_secret, access_token):
    """Configure with a manually provided system user token."""
    result = validate_token_with_api(access_token)
    if not result.get("is_valid"):
        return {"status": "error", "message": f"Token validation failed: {result.get('error')}"}

    accounts = list_ad_accounts(access_token)

    creds = {
        "auth_method": "manual",
        "app_id": app_id,
        "app_secret": app_secret,
        "access_token": access_token,
        "token_expiry": None,
        "ad_accounts": accounts,
    }
    save_credentials(creds)
    return {"status": "ok", "ad_accounts": accounts}


def accounts_result():
    """Ad accounts for --accounts.

    With a token in the environment the list comes from the API through the
    response cache. Otherwise it is the list saved at login.
    """
    if os.environ.get(TOKEN_ENV_VAR, "").strip():
        accounts = meta_utils.read_cache("me", "ad_accounts")
        if accounts is None:
            accounts = meta_utils.api_call_with_retry(
                lambda: list_ad_accounts(get_access_token())
            )
            meta_utils.write_cache("me", "ad_accounts", accounts)
        return {"status": "ok", "ad_accounts": accounts}

    creds = load_credentials()
    if not creds:
        return {"status": "error", "message": "No credentials found"}
    return {"status": "ok", "ad_accounts": creds.get("ad_accounts", [])}


def main():
    parser = argparse.ArgumentParser(description="Meta Ads authentication")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--oauth", action="store_true", help="Run OAuth flow")
    group.add_argument("--configure", action="store_true", help="Manual token configuration")
    group.add_argument("--check", action="store_true", help="Check current auth status")
    group.add_argument("--accounts", action="store_true", help="List accessible ad accounts")

    parser.add_argument("--app-id", help="Meta App ID")
    parser.add_argument("--app-secret", help="Meta App Secret")
    parser.add_argument("--access-token", help="Access token (for --configure)")

    args = parser.parse_args()

    if args.check:
        result = check_auth()
    elif args.accounts:
        result = accounts_result()
    elif args.oauth:
        if not args.app_id or not args.app_secret:
            result = {"status": "error", "message": "--app-id and --app-secret required for OAuth"}
        else:
            result = run_oauth_flow(args.app_id, args.app_secret)
    elif args.configure:
        if not args.app_id or not args.app_secret or not args.access_token:
            result = {"status": "error", "message": "--app-id, --app-secret, and --access-token required"}
        else:
            result = run_manual_config(args.app_id, args.app_secret, args.access_token)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    meta_utils.run_cli(main)
