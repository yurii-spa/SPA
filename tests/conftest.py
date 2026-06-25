# tests/conftest.py — SPA-D003 (v1.9)
# sys.path setup for tests/ — merged from spa_core/tests/conftest.py (v1.7)
# plus path additions for scripts/ modules.
import sys
import os
from pathlib import Path

_ROOT = Path(__file__).parent.parent  # ~/Documents/SPA_Claude
_SCRIPTS = _ROOT / "scripts"
_SPA_CORE = _ROOT / "spa_core"

for _p in [str(_ROOT), str(_SCRIPTS), str(_SPA_CORE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Network guard: set DEFILLAMA_TIMEOUT to 1s so live-feed adapter calls
# fail fast and fall back to deterministic defaults in offline CI/sandbox.
# This does NOT affect production runtime (env var only applies to this process).
# ---------------------------------------------------------------------------
os.environ.setdefault("DEFILLAMA_TIMEOUT", "1")

# ---------------------------------------------------------------------------
# Offline autouse fixture: prevent any live network call in the full test
# suite. We patch urllib.request.urlopen at the stdlib level so that ALL
# HTTP/HTTPS attempts fail immediately with OSError (no TCP wait).
# Adapters catch this and fall back to their deterministic default APY values.
# Individual tests that explicitly test network behaviour must monkeypatch
# their own replacement via monkeypatch.setattr.
# ---------------------------------------------------------------------------
import pytest
import urllib.request as _urllib_req
import urllib.error as _urllib_err


class _OfflineError(OSError):
    """Raised instead of real network calls in the test suite."""
    reason = "offline — network disabled in test suite"


def _blocked_urlopen(url, *args, **kwargs):
    raise _OfflineError("offline — network disabled in test suite")


# Apply the patch at import time so it is active before any test module runs.
# We do NOT use monkeypatch here so we don't create fixture ordering issues.
_urllib_req.urlopen = _blocked_urlopen

# ---------------------------------------------------------------------------
# Kill retry backoff in spa_core/feeds/defi_llama_feed.py:
# That module uses MAX_RETRIES=3 + exponential time.sleep(1s,2s,4s) which
# makes every adapter call sleep 7s when the network is blocked.
# Setting MAX_RETRIES=1 + BACKOFF_BASE=0.0 makes failures instant: exactly one
# attempt is made (which fails fast against the blocked urlopen) with no sleep.
# NOTE: MAX_RETRIES must be >= 1 — range(0) makes ZERO attempts so the feed
# would never even try, which silently masks adapter fetch behaviour. The
# dedicated test_defi_llama_feed.py module restores the real values (3 / 1.0)
# via its own autouse fixture so its retry/backoff assertions are unaffected.
# ---------------------------------------------------------------------------
try:
    import spa_core.feeds.defi_llama_feed as _dlf
    _dlf.MAX_RETRIES = 1
    _dlf.BACKOFF_BASE = 0.0
except ImportError:
    pass
