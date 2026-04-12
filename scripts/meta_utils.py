#!/usr/bin/env python3
"""Shared utilities for Meta Ads scripts: caching, retry, SDK helpers."""

import json
import logging
import os
import sys
import tempfile
import time

logger = logging.getLogger("meta_ads")

# Cross-platform cache directory (fixes hardcoded /tmp on Windows)
CACHE_DIR = os.path.join(tempfile.gettempdir(), "claude-meta-ads")
CACHE_TTL = 900  # 15 minutes


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


# Meta API error codes that are safe to retry (rate limiting / transient)
_RETRYABLE_ERROR_CODES = {
    17,     # API Too Many Calls
    4,      # Application request limit reached
    32,     # Page request limit reached
    80001,  # There have been too many calls
    80003,  # There have been too many calls to this account
    80004,  # There have been too many calls from this ad-account
    80005,  # Too many calls to the Insights API
    80006,  # Too many calls to the Custom Audiences API
}


def _is_retryable(exc):
    """Check if an exception is a retryable Meta API error."""
    try:
        from facebook_business.exceptions import FacebookRequestError
        if isinstance(exc, FacebookRequestError):
            return exc.api_error_code() in _RETRYABLE_ERROR_CODES
    except ImportError:
        pass
    # Also retry on transient connection errors
    import urllib.error
    if isinstance(exc, (ConnectionError, TimeoutError, urllib.error.URLError)):
        return True
    return False


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
                attempt + 1, max_retries + 1, delay, exc,
            )
            if delay > 0:
                time.sleep(delay)


def read_cache(account_id, key, ttl_seconds=CACHE_TTL):
    """Read cached JSON data if it exists and hasn't expired."""
    path = os.path.join(CACHE_DIR, f"{account_id}_{key}.json")
    if not os.path.exists(path):
        return None
    age = time.time() - os.path.getmtime(path)
    if age > ttl_seconds:
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


def exit_error(message, code=1):
    """Print error JSON and exit with non-zero code."""
    print(json.dumps({"status": "error", "message": message}))
    sys.exit(code)
