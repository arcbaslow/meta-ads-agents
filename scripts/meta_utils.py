#!/usr/bin/env python3
"""Shared utilities for Meta Ads scripts: caching, retry, SDK helpers."""

import json
import logging
import os
import re
import sys
import tempfile
import time

logger = logging.getLogger("meta_ads")

# Cross-platform cache directory (fixes hardcoded /tmp on Windows)
CACHE_DIR = os.path.join(tempfile.gettempdir(), "claude-meta-ads")
CACHE_TTL = 900  # 15 minutes

# The one place the Graph / Marketing API version is set. Every SDK call and
# the OAuth URLs use it, so the version no longer follows whichever
# facebook-business release happens to be installed. Bump it in its own
# commit, together with the facebook-business range in pyproject.toml.
API_VERSION = "v26.0"


def init_api(access_token):
    """Create the SDK API object. Every adapter goes through here."""
    from facebook_business.api import FacebookAdsApi

    # crash_log=False: left on, the SDK installs an excepthook that posts the
    # call stack of any unhandled SDK error to Meta. The adapters report
    # errors themselves (see run_cli) and send nothing else anywhere.
    return FacebookAdsApi.init(access_token=access_token, api_version=API_VERSION,
                               crash_log=False)


def to_plain(obj):
    """Recursively convert Meta SDK objects to JSON-serializable dicts/lists."""
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    if hasattr(obj, 'export_all_data'):
        return to_plain(obj.export_all_data())
    if hasattr(obj, '_data'):
        return to_plain(dict(obj._data))
    return obj


# Meta API error codes that are safe to retry (rate limiting / transient).
# Rate-limit codes follow the Marketing API rate limiting page:
# https://developers.facebook.com/docs/marketing-api/overview/rate-limiting
_RETRYABLE_ERROR_CODES = {
    2,      # API Service: temporary issue, wait and retry
    4,      # Application request limit reached
    17,     # User request limit reached
    32,     # Page request limit reached
    613,    # Calls to this api have exceeded the rate limit
    80000,  # Business use case limit: ads insights
    80001,  # Business use case limit: pages
    80003,  # Business use case limit: custom audiences
    80004,  # Business use case limit: ads management
    80005,  # Business use case limit: lead generation
    80006,  # Business use case limit: messenger
    80014,  # Business use case limit: catalog batch
}


def _is_retryable(exc):
    """Check if an exception is a retryable Meta API error."""
    try:
        from facebook_business.exceptions import FacebookRequestError
        if isinstance(exc, FacebookRequestError):
            if exc.api_error_code() in _RETRYABLE_ERROR_CODES:
                return True
            # Meta marks some errors outside the list above as transient.
            return bool(exc.api_transient_error())
    except ImportError:
        pass
    # The SDK talks to the Graph API through requests, whose ConnectionError
    # and Timeout do not inherit from the builtins of the same name.
    try:
        import requests
        if isinstance(exc, (requests.exceptions.ConnectionError,
                            requests.exceptions.Timeout)):
            return True
    except ImportError:
        pass
    import urllib.error
    if isinstance(exc, (ConnectionError, TimeoutError, urllib.error.URLError)):
        return True
    return False


# A requests network error quotes the full request URL, and the SDK sends
# the token as a query parameter. Nothing that came from an exception is
# logged or printed without going through redact().
_SECRET_PARAM_RE = re.compile(
    r"(access_token|appsecret_proof|client_secret|fb_exchange_token)=[^&\s'\")]+")


def redact(text):
    """Blank out credentials that appear as URL parameters in a string."""
    return _SECRET_PARAM_RE.sub(r"\1=REDACTED", str(text))


def error_text(exc):
    """One safe line describing an exception, for logs and error output.

    For a Meta API error this is Meta's message and code, without the
    request dump. For anything else it is the class name and the redacted
    message.
    """
    message = getattr(exc, "api_error_message", None)
    if callable(message) and message():
        return f"{message()} (code {exc.api_error_code()})"
    return redact(f"{type(exc).__name__}: {exc}")


def api_call_with_retry(fn, max_retries=3, base_delay=2):
    """Call fn() with exponential backoff on retryable API errors.

    Only retries Meta API rate limit errors and transient connection issues.
    Programming errors (KeyError, TypeError, etc.) are raised immediately.
    Delays: base_delay, base_delay*2, base_delay*4, ...
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if not _is_retryable(exc) or attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "API call failed (attempt %d/%d), retrying in %ds: %s",
                attempt + 1, max_retries + 1, delay, error_text(exc),
            )
            if delay > 0:
                time.sleep(delay)


def read_cache(account_id, key, ttl_seconds=CACHE_TTL):
    """Read cached JSON data if it exists and hasn't expired.

    A ttl_seconds of zero or less always misses. That is how callers force
    a fresh fetch, so it has to be honoured before any mtime arithmetic.
    """
    if ttl_seconds <= 0:
        return None
    path = os.path.join(CACHE_DIR, f"{account_id}_{key}.json")
    if not os.path.exists(path):
        return None
    # Clamped: the filesystem can report an mtime a hair ahead of the wall
    # clock, which yields a negative age and makes an expired entry look
    # fresh. Seen on Windows under load.
    age = max(0.0, time.time() - os.path.getmtime(path))
    if age >= ttl_seconds:
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache read failed for %s/%s: %s", account_id, key, exc)
        return None


def write_cache(account_id, key, data):
    """Write JSON data to cache file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{account_id}_{key}.json")
    with open(path, "w") as f:
        json.dump(data, f)


def cached(account_id, key, fetch, no_cache=False):
    """Return the cached response for key, or call fetch() and cache the result.

    New API calls go through this so that none can skip the cache by
    accident. no_cache skips the read and still stores the fresh result.
    """
    if not no_cache:
        hit = read_cache(account_id, key)
        if hit is not None:
            return hit
    data = fetch()
    write_cache(account_id, key, data)
    return data


def normalize_account_id(value):
    """Return an ad account ID in the act_<digits> form the API expects.

    Accepts the bare number shown in Ads Manager as well as the prefixed
    form. Raises ValueError for anything else, so a typo fails here and
    not as a confusing Graph API error.
    """
    text = str(value).strip()
    digits = text[4:] if text.lower().startswith("act_") else text
    if not digits.isdigit():
        raise ValueError(f"not an ad account ID: {value!r}")
    return f"act_{digits}"


def account_id_arg(value):
    """argparse type for --account."""
    import argparse
    try:
        return normalize_account_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def exit_error(message, code=1):
    """Print error JSON and exit with non-zero code."""
    print(json.dumps({"status": "error", "message": message}))
    sys.exit(code)


# Token errors, from the Graph API error handling guide:
# https://developers.facebook.com/docs/graph-api/guides/error-handling
_TOKEN_ERROR_CODES = {102, 190}
_RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613} | {
    c for c in _RETRYABLE_ERROR_CODES if 80000 <= c < 90000
}
# Code 100 with this subcode means the query asked for too much data at once.
_TOO_MUCH_DATA = (100, 1487534)


def minutes_to_regain_access(headers):
    """Longest wait, in minutes, reported by the X-Business-Use-Case-Usage header.

    The header maps a business object ID to a list of usage entries, each
    with estimated_time_to_regain_access. Returns None when the header is
    missing or unreadable.
    """
    raw = None
    for key, value in (headers or {}).items():
        if str(key).lower() == "x-business-use-case-usage":
            raw = value
    if not raw:
        return None
    try:
        usage = json.loads(raw)
        waits = [
            entry.get("estimated_time_to_regain_access", 0)
            for entries in usage.values() for entry in entries
        ]
    except (ValueError, TypeError, AttributeError):
        return None
    return max(waits) if waits and max(waits) > 0 else None


def describe_api_error(exc):
    """Turn an SDK request error into the error JSON the adapters print.

    Uses Meta's own message and codes. The request context is left out.
    """
    code = exc.api_error_code()
    subcode = exc.api_error_subcode()
    result = {
        "status": "error",
        "message": exc.api_error_message() or "Meta API request failed",
        "error_code": code,
        "error_subcode": subcode,
    }
    if code in _TOKEN_ERROR_CODES:
        result["error_kind"] = "auth"
        result["action"] = ("The access token has expired or was revoked. "
                            "Run meta_auth.py --oauth, or --configure with a new token.")
    elif code in _RATE_LIMIT_ERROR_CODES:
        result["error_kind"] = "rate_limit"
        wait = minutes_to_regain_access(exc.http_headers())
        if wait:
            result["retry_after_minutes"] = wait
            result["action"] = f"Rate limited. Meta estimates access returns in {wait} minutes."
        else:
            result["action"] = "Rate limited. Wait before retrying and keep the cache on."
    elif (code, subcode) == _TOO_MUCH_DATA:
        result["error_kind"] = "too_much_data"
        result["action"] = "The query is too large. Use fewer --days or a higher --level."
    else:
        result["error_kind"] = "api"
    return result


def run_cli(main):
    """Run an adapter's main() and report a Meta API or network error as JSON.

    Without this an expired token or a throttled call ends in a Python
    traceback on stderr and nothing on stdout, which the agents reading the
    output cannot act on. A network error must not reach the default
    traceback at all: its message quotes the request URL with the token.
    """
    try:
        import requests
        from facebook_business.exceptions import FacebookRequestError
    except ImportError:
        main()
        return
    try:
        main()
    except FacebookRequestError as exc:
        print(json.dumps(describe_api_error(exc), indent=2))
        sys.exit(1)
    except requests.exceptions.RequestException as exc:
        print(json.dumps({
            "status": "error",
            "error_kind": "network",
            "message": error_text(exc),
            "action": "Could not reach the Meta API. Check the connection and retry.",
        }, indent=2))
        sys.exit(1)
