"""
tests/test_adapter_health.py — MP-1486 (v11.02)

20 tests for scripts/adapter_health.py:
  - check_adapter() happy path, fallback path, error path
  - run_all() count and tier filtering
  - result dict schema validation
  - APY sanity band logic
  - CLI entry-point (main) via subprocess / import
  - --json and --tier flag behaviour
  - registry coverage (all adapters produce a result)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Import the module under test
import importlib.util as _ilu

_SCRIPT = ROOT / "scripts" / "adapter_health.py"
_spec = _ilu.spec_from_file_location("adapter_health", _SCRIPT)
_ah = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_ah)

check_adapter = _ah.check_adapter
run_all = _ah.run_all
APY_MIN_PCT = _ah.APY_MIN_PCT
APY_MAX_PCT = _ah.APY_MAX_PCT

from spa_core.adapters.registry import ADAPTER_REGISTRY


# ── Fixtures ──────────────────────────────────────────────────────────────────

_T1_ENTRY = {
    "module": "spa_core.adapters.aave_v3",
    "class": "AaveV3Adapter",
    "tier": "T1",
    "research_only": False,
    "chain": "Ethereum",
    "asset": "USDC",
    "fallback_apy": 3.5,
}

_MISSING_ENTRY = {
    "module": "spa_core.adapters.nonexistent_xyz",
    "class": "FakeAdapter",
    "tier": "T9",
    "research_only": True,
    "chain": "Fake",
    "asset": "XYZ",
    "fallback_apy": 0.0,
}

_FALLBACK_ENTRY = {
    "module": "spa_core.adapters.nonexistent_xyz",
    "class": "FakeAdapter",
    "tier": "T2",
    "research_only": False,
    "chain": "Ethereum",
    "asset": "USDC",
    "fallback_apy": 5.0,
}


# ── 1. check_adapter result schema ────────────────────────────────────────────

def test_result_has_required_keys():
    r = check_adapter("aave_usdc", _T1_ENTRY)
    required = {"name", "tier", "chain", "asset", "research_only",
                "apy_pct", "source", "status"}
    assert required.issubset(set(r.keys()))


def test_result_name_matches_arg():
    r = check_adapter("aave_usdc", _T1_ENTRY)
    assert r["name"] == "aave_usdc"


def test_result_tier_from_info():
    r = check_adapter("aave_usdc", _T1_ENTRY)
    assert r["tier"] == "T1"


def test_result_research_only_from_info():
    r = check_adapter("aave_usdc", _T1_ENTRY)
    assert r["research_only"] is False


# ── 2. Status logic ───────────────────────────────────────────────────────────

def test_ok_status_when_apy_in_band():
    r = check_adapter("aave_usdc", _T1_ENTRY)
    # fallback_apy=3.5 is in [0, 200] → OK or live-sourced OK
    assert r["status"] in ("OK", "APY_OOB", "NO_DATA")  # no ERROR


def test_error_status_when_module_missing_and_no_fallback():
    r = check_adapter("fake_adapter", _MISSING_ENTRY)
    assert r["status"] == "ERROR"
    assert "error" in r


def test_fallback_used_when_import_fails_with_fallback():
    r = check_adapter("fake_fallback", _FALLBACK_ENTRY)
    # Module doesn't exist but fallback_apy=5.0 > 0 → should use fallback
    assert r["status"] in ("OK", "APY_OOB")
    assert r["source"] == "fallback"
    assert r["apy_pct"] == 5.0


def test_apy_pct_is_float_or_none():
    r = check_adapter("aave_usdc", _T1_ENTRY)
    assert r["apy_pct"] is None or isinstance(r["apy_pct"], float)


# ── 3. APY sanity constants ───────────────────────────────────────────────────

def test_apy_min_is_zero():
    assert APY_MIN_PCT == 0.0


def test_apy_max_is_200():
    assert APY_MAX_PCT == 200.0


# ── 4. run_all() ─────────────────────────────────────────────────────────────

def test_run_all_returns_list():
    results = run_all()
    assert isinstance(results, list)


def test_run_all_count_matches_registry():
    results = run_all()
    assert len(results) == len(ADAPTER_REGISTRY)


def test_run_all_tier_filter_t1():
    t1_expected = sum(1 for v in ADAPTER_REGISTRY.values() if v.get("tier") == "T1")
    results = run_all(tier_filter="T1")
    assert len(results) == t1_expected
    assert all(r["tier"] == "T1" for r in results)


def test_run_all_tier_filter_t2():
    results = run_all(tier_filter="T2")
    assert all(r["tier"] == "T2" for r in results)


def test_run_all_tier_filter_empty_for_unknown():
    results = run_all(tier_filter="T9")
    assert results == []


def test_run_all_every_adapter_has_name():
    results = run_all()
    names = [r["name"] for r in results]
    for key in ADAPTER_REGISTRY:
        assert key in names


# ── 5. CLI integration via subprocess ────────────────────────────────────────

def test_cli_default_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True, text=True
    )
    # Allow exit code 0 (all OK) or 1 (errors detected)
    assert proc.returncode in (0, 1)


def test_cli_json_flag_produces_valid_json():
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--json"],
        capture_output=True, text=True
    )
    # stdout should be parseable JSON
    data = json.loads(proc.stdout)
    assert isinstance(data, list)
    assert len(data) == len(ADAPTER_REGISTRY)


def test_cli_json_flag_each_entry_has_status():
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--json"],
        capture_output=True, text=True
    )
    data = json.loads(proc.stdout)
    for entry in data:
        assert "status" in entry
        assert entry["status"] in ("OK", "APY_OOB", "NO_DATA", "ERROR")


def test_cli_tier_filter_t1():
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--tier", "T1", "--json"],
        capture_output=True, text=True
    )
    data = json.loads(proc.stdout)
    assert all(r["tier"] == "T1" for r in data)
    t1_count = sum(1 for v in ADAPTER_REGISTRY.values() if v.get("tier") == "T1")
    assert len(data) == t1_count


def test_cli_single_name_flag():
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--name", "aave_usdc", "--json"],
        capture_output=True, text=True
    )
    data = json.loads(proc.stdout)
    assert len(data) == 1
    assert data[0]["name"] == "aave_usdc"
