"""Pytest fixtures for meta-ads-agents tests.

The adapters are flat modules that import each other by bare name
(`import meta_utils`), so the scripts directory has to be importable
regardless of where pytest was invoked from.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def tmp_cache_dir(monkeypatch, tmp_path):
    """Redirect cache and credentials to a temp dir for every test.

    Without this, a test that exercises a cache or auth path writes to
    the real `~/.claude/meta-ads-credentials.json` and the real system
    temp cache. The token environment variable is cleared for the same
    reason.
    """
    import meta_auth
    import meta_utils

    cache_dir = str(tmp_path / "claude-meta-ads")
    creds_path = str(tmp_path / "meta-ads-credentials.json")
    monkeypatch.setattr(meta_utils, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(meta_auth, "CREDENTIALS_PATH", creds_path)
    # A token exported in the developer's shell must not reach a test.
    monkeypatch.delenv(meta_auth.TOKEN_ENV_VAR, raising=False)
    return tmp_path
