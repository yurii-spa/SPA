"""
Tests for the Strategy-as-Config change-control guard.

Hermetic: each test builds its own baseline against a tmp path or monkeypatches
``compute_current``; the real committed baseline is also asserted clean.

# LLM_FORBIDDEN — deterministic comparison tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load the guard module by path (lives in scripts/, not a package).
import importlib.util  # noqa: E402

_GUARD_PATH = _PROJECT_ROOT / "scripts" / "check_strategy_configs.py"
_spec = importlib.util.spec_from_file_location("check_strategy_configs", _GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(guard)


# ─── helpers ─────────────────────────────────────────────────────────────────────

def _snapshot(items):
    """Build a {id: {version, config_hash}} snapshot from tuples."""
    return {sid: {"version": ver, "config_hash": h} for sid, ver, h in items}


# ─── real-repo: committed baseline is clean ──────────────────────────────────────

def test_real_repo_guard_is_clean():
    """The committed baseline must match the live registry (exit 0)."""
    baseline = guard.load_baseline()
    current = guard.compute_current()
    result = guard.compare(current, baseline)
    assert result["silent_changes"] == []
    assert not guard.has_failures(result)


def test_main_clean_exit_zero(capsys):
    """CLI main() against the real committed baseline returns 0."""
    rc = guard.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "guard clean." in out


# ─── determinism ─────────────────────────────────────────────────────────────────

def test_compute_current_deterministic():
    a = guard.compute_current()
    b = guard.compute_current()
    assert a == b
    # ids sorted
    assert list(a.keys()) == sorted(a.keys())


# ─── clean comparison ────────────────────────────────────────────────────────────

def test_compare_clean_matches_baseline():
    current = guard.compute_current()
    baseline = dict(current)  # identical
    result = guard.compare(current, baseline)
    assert result["silent_changes"] == []
    assert result["versioned_changes"] == []
    assert result["new"] == []
    assert result["removed"] == []
    assert result["unchanged_count"] == len(current)
    assert not guard.has_failures(result)


# ─── silent change (hash changed, version same) → FAIL ───────────────────────────

def test_silent_change_flagged():
    baseline = _snapshot([("S1", "1.0", "aaa"), ("S2", "1.0", "bbb")])
    current = _snapshot([("S1", "1.0", "CHANGED"), ("S2", "1.0", "bbb")])
    result = guard.compare(current, baseline)
    assert [r["id"] for r in result["silent_changes"]] == ["S1"]
    assert result["versioned_changes"] == []
    assert guard.has_failures(result) is True


def test_silent_change_main_exit_one(monkeypatch, tmp_path, capsys):
    """Full CLI path: a silent change makes main() exit 1."""
    baseline_doc = {
        "schema_version": "1.1",
        "strategies": {"S1": {"version": "1.0", "config_hash": "ORIG"}},
    }
    bpath = tmp_path / "baseline.json"
    bpath.write_text(json.dumps(baseline_doc), encoding="utf-8")

    monkeypatch.setattr(
        guard,
        "compute_current",
        lambda: {"S1": {"version": "1.0", "config_hash": "DIFFERENT"}},
    )
    rc = guard.main(["--baseline", str(bpath)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "version did NOT" in err or "without a version bump" in err


# ─── versioned change (hash changed, version bumped) → OK ────────────────────────

def test_versioned_change_ok():
    baseline = _snapshot([("S1", "1.0", "aaa")])
    current = _snapshot([("S1", "1.1", "CHANGED")])
    result = guard.compare(current, baseline)
    assert result["silent_changes"] == []
    assert [r["id"] for r in result["versioned_changes"]] == ["S1"]
    assert result["versioned_changes"][0]["baseline_version"] == "1.0"
    assert result["versioned_changes"][0]["current_version"] == "1.1"
    assert guard.has_failures(result) is False


# ─── new / removed strategies ────────────────────────────────────────────────────

def test_new_strategy_reported_not_fail_by_default():
    baseline = _snapshot([("S1", "1.0", "aaa")])
    current = _snapshot([("S1", "1.0", "aaa"), ("S2", "1.0", "ccc")])
    result = guard.compare(current, baseline)
    assert result["new"] == ["S2"]
    assert guard.has_failures(result) is False
    # strict-new escalates it to a failure
    assert guard.has_failures(result, strict_new=True) is True


def test_removed_strategy_reported():
    baseline = _snapshot([("S1", "1.0", "aaa"), ("S2", "1.0", "bbb")])
    current = _snapshot([("S1", "1.0", "aaa")])
    result = guard.compare(current, baseline)
    assert result["removed"] == ["S2"]
    assert guard.has_failures(result) is False


# ─── update-baseline round-trips clean ───────────────────────────────────────────

def test_update_baseline_then_clean(tmp_path, capsys):
    bpath = tmp_path / "baseline.json"
    rc = guard.main(["--update-baseline", "--baseline", str(bpath)])
    assert rc == 0
    assert bpath.exists()
    doc = json.loads(bpath.read_text(encoding="utf-8"))
    assert doc["schema_version"] == guard.BASELINE_SCHEMA_VERSION
    assert len(doc["strategies"]) == len(guard.compute_current())

    capsys.readouterr()  # clear
    rc2 = guard.main(["--baseline", str(bpath)])
    assert rc2 == 0
    assert "guard clean." in capsys.readouterr().out


def test_missing_baseline_exit_one(tmp_path, capsys):
    rc = guard.main(["--baseline", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "baseline not found" in capsys.readouterr().err
