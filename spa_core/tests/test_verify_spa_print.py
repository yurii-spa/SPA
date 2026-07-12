"""Regression guard for verify_spa.py _print_human — the public DD verifier's human report.

Bug: `smuggled_markets` (an *underwriting* property) was mis-nested inside the *swarm* print
block, so `uw.get(...)` ran with uw=None whenever a proof set had swarm chains but no
underwriting section → AttributeError crashed the report mid-print (a funder running
`verify_spa.py data/` got a traceback instead of the proof output). Fixed by moving the check
into the `if uw is not None:` block. This test pins that: a report with swarm present and
underwriting ABSENT must print without raising.

Deterministic, stdlib-only, no network. verify_spa.py lives in scripts/ (not a package) so we
load it by path via importlib; importing is side-effect-free (main() is under __main__).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_VS_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_spa.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_spa_mod", _VS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # safe: main() is guarded by __main__
    return mod


def _base() -> dict:
    """Full report skeleton with every key _print_human reads directly. Optional sections are
    None (each is guarded by `if X is not None:`); the few printed unconditionally get literals."""
    return {
        "spec_version": "1.0",
        "canonical_json_rule": "sorted-keys, no-ws",
        "ok": True,
        "expected_head": None,
        "expected_surfaces": [],
        "files": {"data_dir": "data/"},
        "errors": [],
        "decision_chain": None,
        "decision_replay": None,
        "exit_nav": None,
        "nav_proof": None,
        "equity_track": None,
        "sleeves": None,
        "tournament": None,
        "snapshot_integrity": None,
        "anchors": None,
        "underwriting": None,
        "swarm": None,
        "fundability": None,
    }


def test_print_human_swarm_present_underwriting_absent_no_crash(capsys):
    vs = _load()
    # swarm present, NO 'underwriting' key → uw is None (the exact crash scenario).
    report = _base()
    report["swarm"] = {
        "valid": True,
        "n_chains": 1,
        "per_chain": [
            {"file": "swarm_book_proof.jsonl", "valid": True, "rows": 1,
             "broken_at": None, "head_hash": "deadbeef"},
        ],
    }
    # Must not raise AttributeError (or anything).
    vs._print_human(report)
    out = capsys.readouterr().out
    assert "swarm chains" in out


def test_print_human_underwriting_with_smuggled_markets(capsys):
    vs = _load()
    # underwriting present AND flags smuggled markets → the warning line must render in the uw block.
    report = _base()
    report["underwriting"] = {
        "valid": True, "length": 3, "broken_at": None, "refusal_consistent": True,
        "published": True, "head_hash": "abc123", "smuggled_markets": ["ezETH-PT"],
    }
    vs._print_human(report)
    out = capsys.readouterr().out
    assert "smuggled" in out.lower()
    assert "ezETH-PT" in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
