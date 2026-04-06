#!/usr/bin/env python3
"""Meta Ads authentication: OAuth flow, manual token config, and token validation."""

import argparse
import json
import os
import sys
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

CREDENTIALS_PATH = os.path.expanduser("~/.claude/meta-ads-credentials.json")
REDIRECT_URI = "http://localhost:8477/callback"
SCOPES = ["ads_read", "ads_management", "read_insights", "business_management"]


def load_credentials():
    """Load credentials from file. Returns None if file doesn't exist."""
    if not os.path.exists(CREDENTIALS_PATH):
        return None
    with open(CREDENTIALS_PATH, "r") as f:
        return json.load(f)


def save_credentials(creds):
    """Save credentials to file, creating parent dirs if needed."""
    os.makedirs(os.path.dirname(CREDENTIALS_PATH), exist_ok=True)
    with open(CREDENTIALS_PATH, "w") as f:
        json.dump(creds, f, indent=2)


def validate_token_with_api(access_token):
    """Validate token against Meta's debug_token endpoint."""
    try:
        from facebook_business.api import FacebookAdsApi
        from facebook_business.adobjects.user import User

        api = FacebookAdsApi.init(access_token=access_token)
        me = User(fbid="me", api=api)
        me.api_get(fields=["id", "name"])
        return {"is_valid": True, "expires_at": 0, "scopes": SCOPES}
    except Exception as e:
        return {"is_valid": False, "error": str(e)}


def check_auth():
    """Check if current credentials are valid. Returns status JSON."""
    creds = load_credentials()
    if not creds:
        return {"status": "error", "message": "No credentials found. Run: meta_auth.py --oauth or --configure"}

    token = creds.get("access_token")
    if not token:
        return {"status": "error", "message": "No access token in credentials file"}

    result = validate_token_with_api(token)
    if result.get("is_valid"):
        return {
            "status": "ok",
            "auth_method": creds.get("auth_method"),
            "ad_accounts": creds.get("ad_accounts", []),
            "token_expiry": creds.get("token_expiry"),
        }
    else:
        return {"status": "error", "message": f"Token invalid: {result.get('error', 'unknown')}"}


def list_ad_accounts(access_token):
    """Fetch all accessible ad accounts for the authenticated user."""
    from facebook_business.api import FacebookAdsApi
    from facebook_business.adobjects.user import User

    api = FacebookAdsApi.init(access_token=access_token)
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
    """Exchange short-lived token for a long-lived one (60 days)."""
    import urllib.request
    import urllib.parse

    params = urllib.parse.urlencode({
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    })
    url = f"https://graph.facebook.com/v21.0/oauth/access_token?{params}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    return data["access_token"], data.get("expires_in", 5184000)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth redirect."""

    auth_code = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
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
    auth_url = "https://www.facebook.com/v21.0/dialog/oauth?" + urlencode({
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "scope": ",".join(SCOPES),
        "response_type": "code",
    })

    print(f"Opening browser for Facebook Login...")
    print(f"If browser doesn't open, visit: {auth_url}")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8477), OAuthCallbackHandler)
    server.timeout = 120
    print("Waiting for authorization (timeout: 2 minutes)...")

    while OAuthCallbackHandler.auth_code is None:
        server.handle_request()

    code = OAuthCallbackHandler.auth_code
    server.server_close()

    import urllib.request
    import urllib.parse

    params = urllib.parse.urlencode({
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    })
    url = f"https://graph.facebook.com/v21.0/oauth/access_token?{params}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
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
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.check:
        result = check_auth()
    elif args.accounts:
        creds = load_credentials()
        if not creds:
            result = {"status": "error", "message": "No credentials found"}
        else:
            result = {"status": "ok", "ad_accounts": creds.get("ad_accounts", [])}
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
    main()
