"""Shared pytest fixtures for SPA tests.

Merged from tests/conftest.py (v1.7 consolidation — SPA-D003).
Includes both the original spa_core/tests fixtures and the richer
pool/position/risk-config fixtures previously living in tests/.
"""
import sys
import json
import time as _time
import pytest
import os
import socket as _socket
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# CI network backstop: under SPA_ENV=ci, bound EVERY socket op with a default
# timeout so no test can wedge the runner on a live network call. The SPA suite
# has many non-hermetic tests that reach live feeds transitively (adapters build
# a universe, cycles run monitors, etc.); on CI those stall indefinitely and hang
# the whole job for 30min+. A socket-level timeout catches ALL of them regardless
# of module or import style — the call fails fast and each adapter/monitor
# fail-closes to its documented non-live fallback. Belt-and-suspenders with the
# per-module SPA_ENV=ci guards. No-op locally (SPA_ENV != ci); production never
# imports this conftest.
if os.environ.get("SPA_ENV") == "ci":
    _socket.setdefaulttimeout(8)

# ---------------------------------------------------------------------------
# Skip test_family_fund_api if fastapi is not installed (stdlib-only env).
# Must be a collect_ignore at conftest level so pytest never tries to import
# the sub-conftest that has a bare `from fastapi...` import.
# ---------------------------------------------------------------------------
import importlib as _il
import importlib.util as _ilu
import glob as _glob
import os as _os
import ast as _ast
# ---------------------------------------------------------------------------
# stdlib-only CI installs ONLY pytest. Many spa_core/tests modules need non-stdlib
# deps (fastapi/requests/web3/numpy/pandas/argon2/eth-account/...) either directly OR
# transitively via the spa_core module under test (e.g. a test importing
# spa_core.api.server pulls in fastapi). Rather than list every file, statically read
# each test's imports and collect_ignore it if a DIRECT heavy dep is missing OR any
# spa_core.* module it imports fails to import (transitive missing dep). In a full deps
# venv nothing is missing -> nothing ignored -> every test runs. Generalizes the
# earlier test_family_fund_api skip. Only spa_core.* modules are import-probed (they are
# import-safe); test modules themselves are never executed here.
# ---------------------------------------------------------------------------
_HEAVY_DEPS = frozenset(("fastapi", "requests", "web3", "numpy", "pandas", "argon2",
                         "eth_account", "httpx", "uvicorn", "pydantic", "aiohttp", "jwt", "bcrypt"))
_ANY_MISSING = any(_ilu.find_spec(_d) is None for _d in _HEAVY_DEPS)
collect_ignore = []
collect_ignore_glob = ["test_family_fund_api/*"]  # family_fund runs in its own venv (needs python-multipart etc.); always excluded from the main CI suite
if _ANY_MISSING:
    _here = _os.path.dirname(__file__)
    _probe_cache = {}
    def _probe(_mod):
        if _mod not in _probe_cache:
            try:
                _il.import_module(_mod); _probe_cache[_mod] = True
            except ModuleNotFoundError:
                _probe_cache[_mod] = False
            except Exception:
                _probe_cache[_mod] = True  # non-dep import error -> let pytest report it
        return _probe_cache[_mod]
    for _f in _glob.glob(_os.path.join(_here, "test_*.py")):
        try:
            _tree = _ast.parse(open(_f, encoding="utf-8").read())
        except Exception:
            continue
        _skip = False
        for _n in _ast.walk(_tree):
            _names = []
            if isinstance(_n, _ast.Import):
                _names = [a.name for a in _n.names]
            elif isinstance(_n, _ast.ImportFrom) and _n.level == 0 and _n.module:
                _names = [_n.module]
            for _nm in _names:
                _top = _nm.split(".")[0]
                if _top in _HEAVY_DEPS and _ilu.find_spec(_top) is None:
                    _skip = True; break
                if _nm.startswith("spa_core") and not _probe(_nm):
                    _skip = True; break
            if _skip:
                break
        if _skip:
            collect_ignore.append(_os.path.basename(_f))
from unittest.mock import MagicMock, patch

# Make spa_core importable from this directory
_SPA_CORE = Path(__file__).parent.parent
_ROOT = _SPA_CORE.parent          # ~/Documents/SPA_Claude
_SCRIPTS = _ROOT / "scripts"

for _p in [str(_ROOT), str(_SCRIPTS), str(_SPA_CORE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# WS2: disable the public-API per-IP rate limiter in the test suite by default.
# All TestClient requests share the IP "testclient", so the production bucket
# would trip 429 after a few hundred requests and poison unrelated API tests.
# Tests that specifically exercise the limiter re-enable it locally (monkeypatch
# SPA_RATE_LIMIT_ENABLED=1). Production leaves the env unset → limiter ON.
# ---------------------------------------------------------------------------
os.environ.setdefault("SPA_RATE_LIMIT_ENABLED", "0")

# ---------------------------------------------------------------------------
# WS2: the public-API write/LLM auth gate defaults ON in production
# (SPA_API_REQUIRE_AUTH unset → enforced). Legacy API tests post to
# /api/chat & /api/agent/thought without a key and expect 200, so the suite
# runs with the gate OFF by default. The dedicated security tests
# (test_api_security_ws2.py) flip it ON explicitly to verify enforcement.
# ---------------------------------------------------------------------------
os.environ.setdefault("SPA_API_REQUIRE_AUTH", "0")


@pytest.fixture
def sample_portfolio():
    return {
        "total_capital_usd": 100000.0,
        "total_pnl_usd": 138.0,
        "total_pnl_pct": 0.138,
        "current_apy": 4.35,
        "cash_usd": 5000.0,
        "total_drawdown_pct": 0.0,
    }


@pytest.fixture
def sample_positions():
    return [
        {
            "protocol_key": "aave-v3-usdc-ethereum",
            "protocol": "Aave V3 USDC",
            "tier": "T1",
            "amount_usd": 40000,
            "current_apy": 4.23,
            "unrealized_pnl_usd": 4.63,
        },
        {
            "protocol_key": "compound-v3-usdc-ethereum",
            "protocol": "Compound",
            "tier": "T1",
            "amount_usd": 35000,
            "current_apy": 4.02,
            "unrealized_pnl_usd": 3.88,
        },
        {
            "protocol_key": "maple-usdc-ethereum",
            "protocol": "Maple Finance",
            "tier": "T2",
            "amount_usd": 20000,
            "current_apy": 4.80,
            "unrealized_pnl_usd": 2.63,
        },
    ]


@pytest.fixture
def temp_data_dir(tmp_path, sample_portfolio, sample_positions):
    """Creates a temp directory with minimal valid JSON data files."""
    data = {
        "portfolio.json": sample_portfolio,
        "positions.json": sample_positions,
        "risk_alerts.json": {
            "count": 0,
            "status": "OK",
            "alerts": [],
            "generated_at": "2026-05-21T16:00:00Z",
        },
        "backtest_results.json": {
            "metrics": {
                "sharpe_ratio": 24.76,
                "max_drawdown_pct": 0.0,
                "total_return_pct": 1.38,
            },
            "equity_curve": [],
            "generated_at": "2026-05-21T16:00:00Z",
        },
        "status.json": {
            "portfolio": sample_portfolio,
            "positions": sample_positions,
            "timestamp": "2026-05-21T16:00:00Z",
        },
    }
    for filename, content in data.items():
        (tmp_path / filename).write_text(json.dumps(content))
    return str(tmp_path)


# ── Pool / Protocol fixtures (merged from tests/conftest.py) ──────────────

@pytest.fixture
def mock_pool_t1_aave():
    """Aave V3 USDC — T1 whitelisted pool."""
    return {
        "pool": "aave-v3-usdc-mainnet",
        "project": "aave-v3",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 5.23,
        "tvlUsd": 850_000_000,
        "stablecoin": True,
        "ilRisk": "no",
        "exposure": "single",
    }


@pytest.fixture
def mock_pool_t1_compound():
    """Compound V3 USDT — T1 whitelisted pool."""
    return {
        "pool": "compound-v3-usdt-mainnet",
        "project": "compound-v3",
        "symbol": "USDT",
        "chain": "Ethereum",
        "apy": 4.87,
        "tvlUsd": 520_000_000,
        "stablecoin": True,
        "ilRisk": "no",
        "exposure": "single",
    }


@pytest.fixture
def mock_pool_t2_yearn():
    """Yearn V3 USDC — T2 whitelisted pool."""
    return {
        "pool": "yearn-v3-usdc-mainnet",
        "project": "yearn-v3",
        "symbol": "USDC",
        "chain": "Ethereum",
        "apy": 6.42,
        "tvlUsd": 120_000_000,
        "stablecoin": True,
        "ilRisk": "no",
        "exposure": "single",
    }


@pytest.fixture
def mock_pool_pendle():
    """Pendle PT stETH — T2 Pendle pool."""
    return {
        "pool": "pendle-pt-steth-2026-01-01",
        "project": "pendle-v2",
        "symbol": "PT-stETH-Jan26",
        "chain": "arbitrum",
        "apy": 8.15,
        "tvlUsd": 45_000_000,
        "stablecoin": False,
        "ilRisk": "no",
        "exposure": "single",
        "maturityDays": 60,
    }


@pytest.fixture
def mock_pool_list(mock_pool_t1_aave, mock_pool_t1_compound, mock_pool_t2_yearn, mock_pool_pendle):
    """Standard 4-pool test set covering T1 + T2 + Pendle."""
    return [mock_pool_t1_aave, mock_pool_t1_compound, mock_pool_t2_yearn, mock_pool_pendle]


# ── RiskConfig fixtures ───────────────────────────────────────────────────

@pytest.fixture
def default_risk_config():
    """Standard risk configuration matching production defaults."""
    from risk.policy import RiskConfig
    return RiskConfig(
        max_single_protocol=0.40,
        max_total_t2_allocation=0.35,
        min_cash_pct=0.03,
        min_tvl_usd=5_000_000,
        min_apy_for_new_position=3.0,
        max_apy_for_new_position=25.0,
    )


@pytest.fixture
def conservative_risk_config():
    """More conservative risk config for edge-case tests."""
    from risk.policy import RiskConfig
    return RiskConfig(
        max_concentration_t1=0.25,
        max_concentration_t2=0.15,
        max_single_protocol=0.25,
        max_total_t2_allocation=0.20,
        min_cash_pct=0.05,
        min_tvl_usd=10_000_000,
        min_apy_for_new_position=4.0,
        max_apy_for_new_position=15.0,
    )


# ── Portfolio / Position fixtures ─────────────────────────────────────────

@pytest.fixture
def mock_positions():
    """Realistic portfolio positions at 85% deployed."""
    return [
        {
            "protocol": "aave-v3",
            "symbol": "USDC",
            "allocation_usd": 30_000,
            "allocation_pct": 30.0,
            "target_pct": 30.0,
            "apy": 5.23,
            "tier": "T1",
        },
        {
            "protocol": "compound-v3",
            "symbol": "USDT",
            "allocation_usd": 25_000,
            "allocation_pct": 25.0,
            "target_pct": 25.0,
            "apy": 4.87,
            "tier": "T1",
        },
        {
            "protocol": "morpho",
            "symbol": "USDC",
            "allocation_usd": 15_000,
            "allocation_pct": 15.0,
            "target_pct": 15.0,
            "apy": 5.61,
            "tier": "T1",
        },
        {
            "protocol": "yearn-v3",
            "symbol": "USDC",
            "allocation_usd": 10_000,
            "allocation_pct": 10.0,
            "target_pct": 10.0,
            "apy": 6.42,
            "tier": "T2",
        },
        {
            "protocol": "pendle-v2",
            "symbol": "PT-stETH",
            "allocation_usd": 5_000,
            "allocation_pct": 5.0,
            "target_pct": 5.0,
            "apy": 8.15,
            "tier": "T2",
        },
    ]


@pytest.fixture
def mock_portfolio_status(mock_positions):
    """Full portfolio status dict as written to data/status.json."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "capital_usd": 100_000,
        "deployed_usd": 85_000,
        "cash_usd": 15_000,
        "total_pnl_usd": 847.23,
        "positions": mock_positions,
        "weighted_apy": 5.61,
        "paper_trading_day": 7,
    }


# ── PnL history fixture ───────────────────────────────────────────────────

@pytest.fixture
def mock_pnl_history():
    """14 days of synthetic PnL history entries (14d × 6 runs/day = 84 entries)."""
    entries = []
    value = 100_000.0
    base = datetime.now(timezone.utc) - timedelta(days=14)
    for i in range(14 * 6):  # 6 runs/day
        value *= (1 + 0.0002 + (i % 3 - 1) * 0.0001)
        entries.append({
            "timestamp": (base + timedelta(hours=i * 4)).isoformat(),
            "portfolio_value": round(value, 2),
            "pnl_usd": round(value - 100_000, 2),
            "daily_return_pct": 0.02,
        })
    return entries


# ── Temp data dir fixtures ─────────────────────────────────────────────────

@pytest.fixture
def data_dir(tmp_path):
    """Temporary data directory that mimics the production data/ layout."""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def populated_data_dir(data_dir, mock_portfolio_status, mock_pnl_history):
    """data_dir pre-populated with status.json, pnl_history.json, and risk_alerts.json."""
    (data_dir / "status.json").write_text(json.dumps(mock_portfolio_status))
    (data_dir / "pnl_history.json").write_text(json.dumps(mock_pnl_history))
    (data_dir / "risk_alerts.json").write_text(json.dumps({"alerts": []}))
    return data_dir


# ── HTTP mock helpers ─────────────────────────────────────────────────────

@pytest.fixture
def mock_defillama_response(mock_pool_list):
    """urllib response mock returning mock_pool_list as DeFiLlama /pools JSON."""
    body = json.dumps({"data": mock_pool_list}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


@pytest.fixture
def patch_defillama_http(mock_defillama_response):
    """Patches urllib.request.urlopen to return the DeFiLlama mock response."""
    with patch("urllib.request.urlopen", return_value=mock_defillama_response) as p:
        yield p


# ---------------------------------------------------------------------------
# No test may message the owner's real Telegram chat (2026-07-31).
#
# The owner was getting the production cycle-gap alert several times an hour
# while the production watchdog was healthy and silent — the sender was this
# suite (test_cycle_gap_monitor called run_cycle_gap_monitor with dry_run=False
# and no stubbed sender, so the call reached api.telegram.org for real).
# The guard intercepts urllib.request.urlopen for api.telegram.org only,
# delegates every other URL to the real one, and — because production senders
# are deliberately fail-safe and swallow exceptions — ALSO records the attempt
# so the autouse fixture below can fail the test from the outside.
# Rationale + design: spa_core/tests/telegram_guard.py.
# ---------------------------------------------------------------------------
import importlib.util as _ilu

# ONE module object, shared by both conftests.  A repo-root `pytest` run loads
# both of them; if each exec'd its own copy there would be two _ATTEMPTS lists
# and two urlopen wrappers — the outer one would record into ITS list while the
# other conftest's fixture checked the empty one, i.e. a guard that reports
# nothing.  That is the very failure class this guard exists to stop, so the
# module is looked up in sys.modules first and only exec'd if absent.
_GUARD_PATH = Path(__file__).resolve().parent / "telegram_guard.py"

# ---------------------------------------------------------------------------
# No test may reach the LIVE network at all (2026-08-03, cycle #93).
#
# telegram_guard delegates every NON-Telegram URL to the real transport, and
# this directory never had the blanket offline block that tests/conftest.py has
# carried since SPA-D003. Measured cost: spa_core/tests/ stopped completing on
# this machine — two runs stalled at the same 49% mark at ~5 tests/min and 6%
# CPU, and a stack dump taken during the stall showed ssl.read() under
# strategy_lab/data/_http.http_fetch (Hyperliquid funding feed) reached from
# spa_core/dfb/alerts.compute_alerts. Rationale + the full stack:
# spa_core/tests/network_guard.py.
#
# Installed BEFORE telegram_guard on purpose, so the Telegram guard ends up
# outermost and keeps reporting api.telegram.org with its own message.
# ---------------------------------------------------------------------------
_NET_GUARD_PATH = Path(__file__).resolve().parent / "network_guard.py"
network_guard = sys.modules.get("spa_network_guard")
if network_guard is None:
    _net_spec = _ilu.spec_from_file_location("spa_network_guard", _NET_GUARD_PATH)
    network_guard = _ilu.module_from_spec(_net_spec)         # type: ignore[arg-type]
    _net_spec.loader.exec_module(network_guard)              # type: ignore[union-attr]
    sys.modules["spa_network_guard"] = network_guard
network_guard.install()

telegram_guard = sys.modules.get("spa_telegram_guard")
if telegram_guard is None:
    _guard_spec = _ilu.spec_from_file_location("spa_telegram_guard", _GUARD_PATH)
    telegram_guard = _ilu.module_from_spec(_guard_spec)      # type: ignore[arg-type]
    _guard_spec.loader.exec_module(telegram_guard)           # type: ignore[union-attr]
    sys.modules["spa_telegram_guard"] = telegram_guard
telegram_guard.install()

# The shared live-feed doors (see live_feed_doors.py). Loaded by absolute path
# from a single source of truth so tests/conftest.py and this one can never
# drift apart — the same discipline the two guards above already use.
_DOORS_PATH = Path(__file__).resolve().parent / "live_feed_doors.py"
live_feed_doors = sys.modules.get("spa_live_feed_doors")
if live_feed_doors is None:
    _doors_spec = _ilu.spec_from_file_location("spa_live_feed_doors", _DOORS_PATH)
    live_feed_doors = _ilu.module_from_spec(_doors_spec)     # type: ignore[arg-type]
    _doors_spec.loader.exec_module(live_feed_doors)          # type: ignore[union-attr]
    sys.modules["spa_live_feed_doors"] = live_feed_doors

# ---------------------------------------------------------------------------
# The GATE (2026-08-18, card `agent-tests-reach-live-feed-222`).
#
# The guard REFUSES the call, the doors stop most tests from walking up to a
# feed, and the banner below REPORTS what is left — but the run still exits 0,
# so a brand-new test that reaches for a feed costs nobody anything and the
# number grows back. It already did once: "ноль отказов" was true of ONE test,
# was read as true of the suite, and the suite was measured at 1726 again.
# live_feed_gate.py turns that report into a failure, with the coverage it
# actually has written down instead of implied.
# ---------------------------------------------------------------------------
_GATE_PATH = Path(__file__).resolve().parent / "live_feed_gate.py"
live_feed_gate = sys.modules.get("spa_live_feed_gate")
if live_feed_gate is None:
    _gate_spec = _ilu.spec_from_file_location("spa_live_feed_gate", _GATE_PATH)
    live_feed_gate = _ilu.module_from_spec(_gate_spec)       # type: ignore[arg-type]
    _gate_spec.loader.exec_module(live_feed_gate)            # type: ignore[union-attr]
    sys.modules["spa_live_feed_gate"] = live_feed_gate


# ---------------------------------------------------------------------------
# The network guard's ledger belongs to ONE test (2026-08-04, cycle #115,
# cards `agent-network-guard-attempts-never-reset` /
# `agent-telegram-guard-outermost-fails-only-in-full-run`).
#
# telegram_guard has had a per-test reset since #55 (the fixture below);
# network_guard, added in #93, never got one, so its _ATTEMPTS grew for the
# whole session. The only assertion anywhere that reads the LIVE ledger —
# test_no_live_network_in_tests::test_telegram_guard_stays_outermost, claiming
# "the network guard did not swallow MY Telegram call" — was therefore
# comparing a session-wide cumulative list against []. It passed in isolation
# (15 passed, 0.13 s) and failed in every full run, and that single failure was
# the whole reason `SPA Tests` / `SPA CI` were red on main.
#
# Measured on origin/main d07714d07: baseline 2 failed / 91279 passed / 1 error;
# with this scoping (applied out-of-tree as a plugin, to measure before
# changing anything) 1 failed / 91280 passed / 0 errors — the remaining failure
# is unrelated (test_protocol_insurance_scorer, card
# `agent-insurance-scorer-fabricates-missing-tvl`).
#
# This does NOT hide anyone's network calls. Those 2745 refusals were already
# invisible — nothing consumed the ledger — and they are refusals, not leaks:
# the guard blocked every one. They are now attributed per test and printed at
# the end of the run by _report_network_refusals below, which is strictly more
# visibility than before.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _scope_network_guard_ledger(request):
    """Give every test its own network-refusal ledger, and gate what it found.

    Recording is unchanged. What is new (2026-08-18) is that the recording is
    now READ by `live_feed_gate` before the ledger is put away: a test that
    reached for a live feed fails here unless the baseline already knew about
    it. Scope is deliberately narrower than "every test" and is written down in
    live_feed_gate.py — the measured files are gated at their measured caps,
    every NEW test file is gated at zero, and older unmeasured files are still
    only reported. A gate that reddened 89 % of the suite for being unmeasured
    would be switched off within a day, which is the frozen-date-ratchet lesson
    in .claude/rules/deployment.md.
    """
    # Put the guard BACK if something knocked it out of the urlopen chain
    # (2026-08-08, cycle #163, card
    # `inbox-retsidiv-setevoi-strazh-snova-krasneet-t`).
    #
    # tests/conftest.py USED TO replace urlopen by plain assignment (line 58)
    # and then re-install ONLY telegram_guard, so in every run that collects
    # both roots the chain became `telegram_guard -> _blocked_urlopen` with
    # network_guard gone — before the first test ran, which is why the end-of-run
    # banner below blamed whichever test happened to be first. That block is now
    # a wrapper (spa_core/tests/offline_block.py, 2026-08-17, card
    # `inbox-storozh-telegram-dverei-vybivaet-storozh`) and no longer clobbers
    # anything. This repair stays: it is the backstop for the NEXT plain
    # assignment, and it is the thing that names it out loud. The network was
    # still
    # blocked (the sibling block is also fail-CLOSED), but THIS guard's ledger
    # stayed empty, and the three tests that read it went red only in a full
    # run: test_a_a_refused_call_lands_in_the_live_ledger,
    # test_c_the_previous_tests_refusal_was_archived_not_discarded,
    # test_http_fetch_cannot_reach_the_network. Reproduced with ONE neighbour:
    #   pytest spa_core/tests/test_network_guard_ledger_is_per_test.py \
    #          spa_core/tests/test_no_live_network_in_tests.py \
    #          tests/test_adapter_registry.py
    #
    # Repaired here rather than by relaxing those tests (invariant #16): they
    # were right — the guard really was absent. Restoring it is done LOUDLY,
    # via network_guard.clobbers(), reported by _report_network_refusals below.
    if network_guard.ensure_installed(request.node.nodeid):
        # Re-installing puts network_guard on top; telegram_guard must stay
        # OUTERMOST so api.telegram.org keeps its specific message and its own
        # ledger (pinned by test_telegram_guard_stays_outermost).
        telegram_guard.install()
    network_guard.reset()
    yield
    recorded = network_guard.archive(request.node.nodeid)
    if recorded:
        # Archived FIRST: whatever the gate decides, the refusals stay attributed
        # and printed. A gate that ate its own evidence would be the same
        # fail-OPEN shape this file keeps closing.
        problem = live_feed_gate.check(
            request.node.nodeid,
            recorded,
            marked=bool(request.node.get_closest_marker(live_feed_doors.MARKER)),
        )
        if problem:
            pytest.fail(problem, pytrace=False)


# ---------------------------------------------------------------------------
# The TIME half of the same card (2026-08-18): a test that quietly grows to eat
# the cycle is the same failure as one that quietly reaches for a feed — nobody
# looks until a run stops completing. `--durations` on the measured slice put
# 52 % of a 241 s run in THREE tests. This does not ban slow tests: @pytest.mark
# .slow declares one, a measured long-runner keeps its recorded cap, and only
# the UNDECLARED long-runner is refused. Same scope rule as the network gate.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _gate_the_time_budget(request):
    started = _time.monotonic()
    yield
    elapsed = _time.monotonic() - started
    problem = live_feed_gate.check_duration(
        request.node.nodeid,
        elapsed,
        marked_slow=bool(request.node.get_closest_marker("slow")),
    )
    if problem:
        pytest.fail(problem, pytrace=False)


# ---------------------------------------------------------------------------
# Shut the shared live-feed DOORS (2026-08-16, card
# `agent-tests-reach-live-feed-222`).
#
# network_guard answers "did anything reach the network" — no, it never did.
# This fixture answers the different question the card is about: "did a test
# that does not need a feed still walk up to one and get turned back".  Both
# doors are shut at a seam whose result is IDENTICAL to the refusal the guard
# already produced (rationale + the identity argument: live_feed_doors.py), so
# no assertion is weakened; the attempt simply stops being made.
#
# Ordered AFTER the ledger fixture so a test marked `live_feed_transport` still
# has its refusals recorded and attributed the same way.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _shut_the_shared_live_feed_doors(request):
    """Close DeFiLlama + the strategy-lab HTTP door for every test that did not
    ask for them, and put them back exactly as they were afterwards."""
    if request.node.get_closest_marker(live_feed_doors.MARKER):
        # The transport IS this test's subject — leave the doors open. The
        # network guard still refuses it; only the attempt is allowed.
        yield
        return
    previous = live_feed_doors.close()
    try:
        yield
    finally:
        live_feed_doors.restore(previous)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Name the tests whose code tried to reach the live network.

    Without this the refusals are recorded and never read by anyone — the
    "claims a check nobody looks at" shape (#29/#31/#35–#38, #40). Reporting is
    all it does: nothing here changes an exit status.
    """
    # Reported FIRST and independently of the refusal ledger: a clobber is the
    # more serious of the two findings, and it is precisely the state in which
    # the ledger is empty — so hanging this report off `archived` would hide it
    # exactly when it matters (cycle #163).
    knocked_out = network_guard.clobbers()
    if knocked_out:
        terminalreporter.write_sep("=", "network guard was RE-INSTALLED mid-run")
        terminalreporter.write_line(
            f"{len(knocked_out)} test(s) started with the guard knocked out of "
            f"the urlopen chain and had it restored. The suite was NOT "
            f"unguarded for them (the fixture repairs before the test body), "
            f"but something replaced urlopen by plain assignment instead of "
            f"wrapping it — find it and make it wrap."
        )
        for nodeid, what in knocked_out[:10]:
            terminalreporter.write_line(f"  missing[{what}]  {nodeid}")
        if len(knocked_out) > 10:
            # No silent caps: say what was left out.
            terminalreporter.write_line(
                f"  … {len(knocked_out) - 10} more test(s) not shown"
            )

    # The newness half of the gate needs git. If it could not run, SAY so —
    # a gate that silently went half-inert is worse than no gate, because the
    # green now means something different from what it says.
    trouble = live_feed_gate.git_trouble()
    if trouble:
        terminalreporter.write_sep("=", "live-feed gate ran HALF-INERT (no git)")
        terminalreporter.write_line(
            "The NEW-file half of the gate could not run — new test files were "
            "NOT gated in this run. The measured-file half still applied."
        )
        for reason in trouble[:5]:
            terminalreporter.write_line(f"  {reason}")

    archived = network_guard.archived()
    if not archived:
        return
    total = sum(len(items) for _, items in archived)
    terminalreporter.write_sep("=", "live-network refusals (guard held; no call went out)")
    terminalreporter.write_line(
        f"{total} refusal(s) from {len(archived)} test(s). Each one is production "
        f"code under test reaching for a live feed and getting a fail-CLOSED "
        f"OSError. Inject a fake feed instead (.claude/rules/adapters.md)."
    )
    # Never let this list be read as "and everything else is hermetic": say what
    # the gate actually covers, every time it prints.
    try:
        terminalreporter.write_line(live_feed_gate.coverage())
    except Exception as exc:  # noqa: BLE001 — a broken baseline must be LOUD
        terminalreporter.write_line(f"live-feed gate baseline UNREADABLE: {exc}")
    ranked = sorted(archived, key=lambda pair: -len(pair[1]))
    shown = ranked[:20]
    for nodeid, items in shown:
        terminalreporter.write_line(f"  {len(items):6d}  {nodeid}")
    if len(ranked) > len(shown):
        # No silent caps: say what was left out rather than implying this is all.
        terminalreporter.write_line(
            f"  … {len(ranked) - len(shown)} more test(s) not shown, "
            f"{sum(len(i) for _, i in ranked[len(shown):])} refusal(s) between them"
        )


@pytest.fixture(autouse=True)
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
# The #55 guard above stops a test from MESSAGING the owner. It does not stop a
# test from writing data/telegram/push_state.json — the edge-trigger state that
# decides whether the owner is ever messaged at all. push_policy resolves that
# path from its own __file__ (not from SPA_DATA_DIR), so the per-test data-dir
# isolation does not cover it, and ~19 production senders call push_critical()
# with no data_dir. A test that leaves `kill_switch: bad` there makes the next
# REAL firing take the "still bad → silent" branch. Rationale + measurements:
# spa_core/tests/push_state_guard.py.
# ---------------------------------------------------------------------------
_PUSH_GUARD_PATH = Path(__file__).resolve().parent / "push_state_guard.py"
push_state_guard = sys.modules.get("spa_push_state_guard")
if push_state_guard is None:
    _push_spec = _ilu.spec_from_file_location("spa_push_state_guard", _PUSH_GUARD_PATH)
    push_state_guard = _ilu.module_from_spec(_push_spec)     # type: ignore[arg-type]
    _push_spec.loader.exec_module(push_state_guard)          # type: ignore[union-attr]
    sys.modules["spa_push_state_guard"] = push_state_guard
push_state_guard.install()


@pytest.fixture(autouse=True)
def _no_live_push_state():
    """Sandbox push_policy's default state dir, fresh for every test.

    Not a mock: the whole policy (whitelist / edge-trigger / ceiling / digest)
    still runs — only the state's location changes. Clearing it per test also
    removes the order-dependence that made the live-Telegram guard fire in a
    file run but not in a single-test run.
    """
    push_state_guard.reset()
    yield


# ---------------------------------------------------------------------------
# No test may write the LIVE off-site backup of the track (2026-08-04, #113).
#
# The two guards above cover the owner's Telegram and the alert state. Neither
# covers the DR copy of the track itself: test_track_persistence calls the real
# _default_track_persister with no backup_dir, so run_backup resolves
# default_backup_dir() → iCloud SPA_backups on this host and writes the live
# off-site backup — then blocks forever in os.replace on the sync layer, which
# is why the full spa_core/tests/ run stopped completing on this machine.
# Redirection, not a mock: the whole backup path still executes, into a sandbox
# the suite owns. Rationale + measurements: spa_core/tests/backup_dir_guard.py.
# ---------------------------------------------------------------------------
_BACKUP_GUARD_PATH = Path(__file__).resolve().parent / "backup_dir_guard.py"
backup_dir_guard = sys.modules.get("spa_backup_dir_guard")
if backup_dir_guard is None:
    _bak_spec = _ilu.spec_from_file_location("spa_backup_dir_guard", _BACKUP_GUARD_PATH)
    backup_dir_guard = _ilu.module_from_spec(_bak_spec)      # type: ignore[arg-type]
    _bak_spec.loader.exec_module(backup_dir_guard)           # type: ignore[union-attr]
    sys.modules["spa_backup_dir_guard"] = backup_dir_guard
backup_dir_guard.install()


@pytest.fixture(autouse=True)
def _no_live_backup_dir():
    """Pin $SPA_BACKUP_DIR into a sandbox for every test, then restore it.

    Per-test rather than once per session: a test may set or delete the variable
    itself (tests/test_backup.py deletes it in a finally), and that must not
    leak into the next test's default resolution.
    """
    backup_dir_guard.install()
    yield
    backup_dir_guard.restore()


# ---------------------------------------------------------------------------
# No test may write the git-tracked SQLite file (2026-08-17, cycle #274,
# card `agent-test-run-dirties-tracked-fixtures`).
#
# The three guards above cover Telegram, the alert state and the off-site
# backup. None covers `spa_core/database/spa.db`, which db_url.py resolves from
# its own __file__ and which is git-tracked: five test_api.py tests reach
# sqlite3.connect on it through get_status → get_live_portfolio →
# init_database, and `git status` came back dirty after every run.
# Rationale + the measured call chain: spa_core/tests/tracked_db_guard.py.
# ---------------------------------------------------------------------------
_DB_GUARD_PATH = Path(__file__).resolve().parent / "tracked_db_guard.py"
tracked_db_guard = sys.modules.get("spa_tracked_db_guard")
if tracked_db_guard is None:
    _db_spec = _ilu.spec_from_file_location("spa_tracked_db_guard", _DB_GUARD_PATH)
    tracked_db_guard = _ilu.module_from_spec(_db_spec)       # type: ignore[arg-type]
    _db_spec.loader.exec_module(tracked_db_guard)            # type: ignore[union-attr]
    sys.modules["spa_tracked_db_guard"] = tracked_db_guard
tracked_db_guard.install()


@pytest.fixture(autouse=True)
def _no_live_tracked_db():
    """Pin $SPA_DATABASE_URL into a sandbox for every test, then restore it.

    Redirection, not a mock: schema creation and every query still run, against
    a file the suite owns. Per-test because test_db_url.py sets and deletes the
    variable itself, and that must not leak into the next test.
    """
    tracked_db_guard.install()
    yield
    tracked_db_guard.restore()
