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
# WS2: disable the public-API per-IP rate limiter in the test suite by default
# (see spa_core/tests/conftest.py for rationale — shared "testclient" IP would
# trip 429 across unrelated API tests). Production leaves it unset → ON.
# ---------------------------------------------------------------------------
os.environ.setdefault("SPA_RATE_LIMIT_ENABLED", "0")

# WS2: write/LLM auth gate OFF by default in the suite (legacy API tests post
# without a key). Production leaves it unset → ON. The security tests flip ON.
os.environ.setdefault("SPA_API_REQUIRE_AUTH", "0")

# ---------------------------------------------------------------------------
# Offline block: prevent any live network call in the full test suite.  Every
# HTTP/HTTPS attempt fails immediately with an OSError (no TCP wait); adapters
# catch it and fall back to their deterministic default APY values.  Individual
# tests that explicitly test network behaviour monkeypatch their own
# replacement via monkeypatch.setattr.
#
# It WRAPS, it does not assign (2026-08-17, card
# `inbox-storozh-telegram-dverei-vybivaet-storozh`).
#
# This used to be `_urllib_req.urlopen = _blocked_urlopen` — one line that
# threw away every layer the other root had installed.  Measured, in the order
# a repo-root run loads the two conftests:
#
#   spa_core conftest  ->  telegram_guard -> network_guard -> urlopen   (chain 3)
#   THIS LINE          ->  _blocked_urlopen                             (chain 1)
#   this file, later   ->  telegram_guard -> _blocked_urlopen  (network guard GONE)
#   first test         ->  autouse fixture repairs it and records a "clobber"
#
# so every combined run printed `network guard was RE-INSTALLED mid-run` and
# blamed whichever test ran first (reproduced verbatim with two files:
# `pytest spa_core/tests/test_doc_drift.py tests/test_adapter_registry.py`
# named `test_doc_drift.py::test_canonical_dr_doc_exists`, which does nothing
# of the sort).
#
# Nothing is relaxed.  The block is now a layer that publishes `__wrapped__`
# like its siblings, and the rule it enforced is split between the two layers
# that can each enforce their half without blinding the other:
#   * loopback / unparseable URLs   -> refused HERE (offline_block.OfflineError);
#   * every other address           -> refused by network_guard, which also
#                                      RECORDS the refusal (a block that
#                                      answered for it would leave that ledger
#                                      empty while three tests assert on it).
# Both are OSError, the contract every caller under test already takes.  A
# `pytest tests/` run gains network_guard's socket-level backstop, which this
# root never had.  Rationale: spa_core/tests/offline_block.py.
# ---------------------------------------------------------------------------
import pytest
import urllib.request as _urllib_req
import urllib.error as _urllib_err
import importlib.util as _ilu

# ONE module object per guard, shared with spa_core/tests/conftest.py — see the
# note there: two copies would mean two ledgers, one recording and the other
# reporting.  Loaded by absolute path from the single source of truth so the
# two roots can never drift apart.
_GUARD_DIR = _ROOT / "spa_core" / "tests"


def _shared_guard(module_name, filename):
    mod = sys.modules.get(module_name)
    if mod is None:
        _spec = _ilu.spec_from_file_location(module_name, _GUARD_DIR / filename)
        mod = _ilu.module_from_spec(_spec)          # type: ignore[arg-type]
        _spec.loader.exec_module(mod)               # type: ignore[union-attr]
        sys.modules[module_name] = mod
    return mod


# Installed BEFORE the offline block so the block WRAPS it and delegates the
# live network to it — and idempotent, so a run that already loaded
# spa_core/tests/conftest.py keeps that one instance untouched.
network_guard = _shared_guard("spa_network_guard", "network_guard.py")
network_guard.install()

offline_block = _shared_guard("spa_offline_block", "offline_block.py")
offline_block.install(network_guard)

#: Kept under its historical name for any reader who greps for it: the error a
#: refused LOCAL call raises in this root.  Non-loopback calls raise
#: network_guard.LiveNetworkAccessAttempted — also an OSError.
_OfflineError = offline_block.OfflineError

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


# ---------------------------------------------------------------------------
# WS4 — Structural test hermeticity.
#
# Two concerns, two mechanisms (both make the suite pass on a clean checkout
# with an EMPTY data/, the audit's flaky-test root cause):
#
#  (1) DEFAULT data-dir isolation — autouse fixture below points the runtime
#      data-dir env (SPA_DATA_DIR) at a per-test tmp dir so any code that
#      resolves its data dir via the standard mechanism never reads/writes the
#      live repo-root data/.  Tests that *intentionally* exercise the live
#      track opt OUT with @pytest.mark.live_data.
#
#  (2) LIVE-DATA CONSISTENCY guards — a small set of SSOT/consistency/presence
#      tests legitimately read the committed live data/ (doc-drift pins,
#      proof-chain reproduction, evidence/gate presence).  They are NOT unit
#      tests; redirecting them to an empty tmp would make them vacuous.  They
#      call ``require_live_data(path)`` (or are marked ``live_data``) so they
#      RUN when the artifact exists and SKIP cleanly when data/ is empty.
# ---------------------------------------------------------------------------
import pytest as _pytest

# Canonical live data dir (repo-root/data).  Single source of truth for the
# helpers below so individual tests don't re-derive parents[N] paths.
LIVE_DATA_DIR = _ROOT / "data"


def require_live_data(*relpaths, allow_empty=False):
    """Skip the calling test unless every given live-data artifact is present.

    ``relpaths`` are relative to repo-root/data (e.g. "golive_status.json" or
    "rates_desk/decision_log.jsonl") OR absolute/Path objects.  Returns the
    resolved list of Paths so callers can use them directly.  On a clean
    checkout with an empty data/ this raises pytest.skip → suite stays green.
    """
    resolved = []
    for rp in relpaths:
        p = Path(rp)
        if not p.is_absolute():
            p = LIVE_DATA_DIR / rp
        if not p.exists():
            _pytest.skip(f"live-data artifact absent (clean checkout): {p}")
        if not allow_empty and p.is_file() and p.stat().st_size == 0:
            _pytest.skip(f"live-data artifact empty (clean checkout): {p}")
        resolved.append(p)
    return resolved


# NOTE: the live_data / slow / evidence markers are registered canonically in
# pytest.ini ([pytest] markers=...), so no pytest_configure hook is needed here.


@_pytest.fixture(autouse=True)
def _isolate_data_dir(request, tmp_path, monkeypatch):
    """Default-isolate the runtime data dir to a per-test tmp dir.

    Any module resolving its data dir from the SPA_DATA_DIR env (the canonical
    runtime hook) gets a throwaway dir, so a stray dev/CI run can never read or
    mutate the live go-live track.  Tests marked ``live_data`` opt out and keep
    the real environment (they guard their own reads with require_live_data).
    """
    if request.node.get_closest_marker("live_data"):
        return
    # Use a DEDICATED subdir name (NOT "data") so we never collide with tests
    # that create their own ``tmp_path / "data"`` via .mkdir() (without
    # exist_ok) — a collision there would raise FileExistsError and break them.
    d = tmp_path / "_spa_isolated_data"
    d.mkdir(exist_ok=True)
    monkeypatch.setenv("SPA_DATA_DIR", str(d))


# ---------------------------------------------------------------------------
# No test may message the owner's real Telegram chat (2026-07-31).
#
# Same guard as spa_core/tests/conftest.py — the two test roots are collected
# separately by CI (`pytest tests/` runs after `cd spa_core` in one workflow),
# so the guard has to be installed from BOTH or one root stays unprotected.
# The implementation is loaded by absolute path from a single source of truth
# (spa_core/tests/telegram_guard.py) rather than duplicated, so the two roots
# can never drift apart. Rationale: that module's docstring.
# ---------------------------------------------------------------------------
import importlib.util as _ilu

# ONE module object, shared with spa_core/tests/conftest.py — see the note
# there: two copies would mean two _ATTEMPTS lists and a guard that records in
# one and reports from the other.
_TG_GUARD_PATH = _ROOT / "spa_core" / "tests" / "telegram_guard.py"
telegram_guard = sys.modules.get("spa_telegram_guard")
if telegram_guard is None:
    _tg_spec = _ilu.spec_from_file_location("spa_telegram_guard", _TG_GUARD_PATH)
    telegram_guard = _ilu.module_from_spec(_tg_spec)         # type: ignore[arg-type]
    _tg_spec.loader.exec_module(telegram_guard)              # type: ignore[union-attr]
    sys.modules["spa_telegram_guard"] = telegram_guard
telegram_guard.install()


@_pytest.fixture(autouse=True)
def _no_live_telegram(request):
    """Fail any test that tried to reach the live Telegram Bot API.

    Fail-CLOSED and non-swallowable: the check runs AFTER the test body, so an
    attempt is reported even when the exception raised at the call site was
    caught by the fail-safe production sender under test.
    """
    telegram_guard.reset()
    yield
    telegram_guard.assert_no_live_telegram(request.node.nodeid)


# ---------------------------------------------------------------------------
# No test may write the owner's LIVE alert state (2026-07-31, cycle #58).
#
# Same guard as spa_core/tests/conftest.py, installed from BOTH roots for the
# same reason the Telegram guard is: CI collects them separately. Loaded by
# absolute path from the single source of truth so the roots cannot drift.
# What it protects: push_policy resolves data/telegram/ from its own __file__,
# so the _isolate_data_dir fixture above (SPA_DATA_DIR) does NOT cover it, and a
# test driving any of ~19 senders writes the owner's real edge-trigger state.
# ---------------------------------------------------------------------------
_PUSH_GUARD_PATH = _ROOT / "spa_core" / "tests" / "push_state_guard.py"
push_state_guard = sys.modules.get("spa_push_state_guard")
if push_state_guard is None:
    _push_spec = _ilu.spec_from_file_location("spa_push_state_guard", _PUSH_GUARD_PATH)
    push_state_guard = _ilu.module_from_spec(_push_spec)     # type: ignore[arg-type]
    _push_spec.loader.exec_module(push_state_guard)          # type: ignore[union-attr]
    sys.modules["spa_push_state_guard"] = push_state_guard
push_state_guard.install()


@_pytest.fixture(autouse=True)
def _no_live_push_state():
    """Sandbox push_policy's default state dir, fresh for every test.

    Not a mock: the whole policy (whitelist / edge-trigger / ceiling / digest)
    still runs — only the state's location changes.
    """
    push_state_guard.reset()
    yield


# ---------------------------------------------------------------------------
# No test may write the LIVE off-site backup of the track (2026-08-04, #113).
#
# Same guard as spa_core/tests/conftest.py, installed from BOTH roots for the
# same reason the two above are, and loaded by absolute path from the single
# source of truth so the roots cannot drift. What it protects: run_backup with
# no backup_dir resolves default_backup_dir() → the real iCloud SPA_backups on
# this host, which is both the DR copy of the live track and (measured) a
# directory that blocks os.replace forever. Rationale:
# spa_core/tests/backup_dir_guard.py.
# ---------------------------------------------------------------------------
_BACKUP_GUARD_PATH = _ROOT / "spa_core" / "tests" / "backup_dir_guard.py"
backup_dir_guard = sys.modules.get("spa_backup_dir_guard")
if backup_dir_guard is None:
    _bak_spec = _ilu.spec_from_file_location("spa_backup_dir_guard", _BACKUP_GUARD_PATH)
    backup_dir_guard = _ilu.module_from_spec(_bak_spec)      # type: ignore[arg-type]
    _bak_spec.loader.exec_module(backup_dir_guard)           # type: ignore[union-attr]
    sys.modules["spa_backup_dir_guard"] = backup_dir_guard
backup_dir_guard.install()


@_pytest.fixture(autouse=True)
def _no_live_backup_dir():
    """Pin $SPA_BACKUP_DIR into a sandbox for every test, then restore it."""
    backup_dir_guard.install()
    yield
    backup_dir_guard.restore()


# ---------------------------------------------------------------------------
# Shut the shared live-feed DOORS (2026-08-16, card
# `agent-tests-reach-live-feed-222`).
#
# Same doors as spa_core/tests/conftest.py, installed from BOTH roots for the
# same reason the three guards above are, and loaded by absolute path from the
# single source of truth so the roots cannot drift. Rationale + the argument
# that this changes no observable result: spa_core/tests/live_feed_doors.py.
# ---------------------------------------------------------------------------
_DOORS_PATH = _ROOT / "spa_core" / "tests" / "live_feed_doors.py"
live_feed_doors = sys.modules.get("spa_live_feed_doors")
if live_feed_doors is None:
    _doors_spec = _ilu.spec_from_file_location("spa_live_feed_doors", _DOORS_PATH)
    live_feed_doors = _ilu.module_from_spec(_doors_spec)     # type: ignore[arg-type]
    _doors_spec.loader.exec_module(live_feed_doors)          # type: ignore[union-attr]
    sys.modules["spa_live_feed_doors"] = live_feed_doors


@_pytest.fixture(autouse=True)
def _shut_the_shared_live_feed_doors(request):
    """Close DeFiLlama + the strategy-lab HTTP door for every test that did not
    ask for them, and put them back exactly as they were afterwards."""
    if request.node.get_closest_marker(live_feed_doors.MARKER):
        yield
        return
    previous = live_feed_doors.close()
    try:
        yield
    finally:
        live_feed_doors.restore(previous)
# No test may write the git-tracked SQLite file (2026-08-17, cycle #274).
#
# Same guard as spa_core/tests/conftest.py, installed from BOTH roots for the
# same reason the three above are, and loaded by absolute path from the single
# source of truth so the roots cannot drift. What it protects:
# spa_core/database/spa.db, resolved by db_url.py from its own __file__ and
# therefore NOT covered by the _isolate_data_dir fixture above.
# Rationale: spa_core/tests/tracked_db_guard.py.
# ---------------------------------------------------------------------------
_DB_GUARD_PATH = _ROOT / "spa_core" / "tests" / "tracked_db_guard.py"
tracked_db_guard = sys.modules.get("spa_tracked_db_guard")
if tracked_db_guard is None:
    _db_spec = _ilu.spec_from_file_location("spa_tracked_db_guard", _DB_GUARD_PATH)
    tracked_db_guard = _ilu.module_from_spec(_db_spec)       # type: ignore[arg-type]
    _db_spec.loader.exec_module(tracked_db_guard)            # type: ignore[union-attr]
    sys.modules["spa_tracked_db_guard"] = tracked_db_guard
tracked_db_guard.install()


@_pytest.fixture(autouse=True)
def _no_live_tracked_db():
    """Pin $SPA_DATABASE_URL into a sandbox for every test, then restore it."""
    tracked_db_guard.install()
    yield
    tracked_db_guard.restore()
