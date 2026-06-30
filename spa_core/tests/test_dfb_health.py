"""test_dfb_health.py — the d_dfb health domain in system_health_monitor (Lane-2 WS-3.5).

The d_dfb domain makes the STANDING DFB pipeline observable + fail-CLOSED. Three verifications:

  • PROPERTY  — a fresh, valid, low-UNKNOWN snapshot grades every data-derived check OK; the
                domain is registered in the monitor's collect() roll-up.
  • RED-TEAM  — a STALE snapshot (capture agent down) → WARNING (never silent-OK); a missing
                snapshot → WARNING; a broken proof chain → WARNING; a feed-outage UNKNOWN spike
                → WARNING. Every degraded condition is surfaced, none silently passes.
  • SMOKE     — check_d_dfb_defi_board() runs end-to-end against a sandbox data dir and returns
                exactly the four expected sub-checks.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in (str(_SPA_CORE), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spa_core.monitoring.system_health_monitor import (  # noqa: E402
    OK,
    WARNING,
    SystemHealthMonitor,
)

_D = "d_dfb_defi_board"


def _fresh_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _write_snapshot(tmp: Path, doc: dict) -> None:
    d = tmp / "dfb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pools.json").write_text(json.dumps(doc), encoding="utf-8")


def _mon(tmp: Path) -> SystemHealthMonitor:
    m = SystemHealthMonitor(data_dir=tmp)
    m._dfb_cache = "unset"  # ensure a clean per-test load
    return m


# ── PROPERTY ─────────────────────────────────────────────────────────────────
def test_d_dfb_healthy_snapshot_all_data_checks_ok(tmp_path):
    _write_snapshot(tmp_path, {"generated_at": _fresh_ts(), "n_pools": 38,
                               "n_unknown": 8, "chain_valid": True})
    m = _mon(tmp_path)
    assert m._check_dfb_snapshot(_D).status == OK
    assert m._check_dfb_chain(_D).status == OK
    assert m._check_dfb_unknown_canary(_D).status == OK


def test_d_dfb_registered_in_collect():
    """The d_dfb domain must appear in the monitor's roll-up (not just be definable)."""
    import inspect
    src = inspect.getsource(SystemHealthMonitor.collect)
    assert "check_d_dfb_defi_board" in src
    assert "d_dfb_defi_board" in src


def test_d_dfb_returns_four_subchecks(tmp_path):
    """SMOKE: the domain returns exactly its four sub-checks, each tagged to the domain."""
    _write_snapshot(tmp_path, {"generated_at": _fresh_ts(), "n_pools": 10,
                               "n_unknown": 1, "chain_valid": True})
    m = _mon(tmp_path)
    res = m.check_d_dfb_defi_board()
    ids = {r.id for r in res}
    assert ids == {"d_dfb.snapshot.fresh", "d_dfb.chain.valid",
                   "d_dfb.unknown.canary", "d_dfb.capture.heartbeat"}
    assert all(r.domain == _D for r in res)


# ── RED-TEAM (fail-CLOSED: every degraded condition WARNs, none silent-OK) ─────
def test_d_dfb_missing_snapshot_warns_not_silent_ok(tmp_path):
    m = _mon(tmp_path)  # empty data dir — no dfb/pools.json at all
    assert m._check_dfb_snapshot(_D).status == WARNING
    assert m._check_dfb_chain(_D).status == WARNING
    assert m._check_dfb_unknown_canary(_D).status == WARNING


def test_d_dfb_stale_snapshot_warns(tmp_path):
    _write_snapshot(tmp_path, {"generated_at": "2020-01-01T00:00:00Z", "n_pools": 10,
                               "n_unknown": 1, "chain_valid": True})
    assert _mon(tmp_path)._check_dfb_snapshot(_D).status == WARNING


def test_d_dfb_no_generated_at_warns(tmp_path):
    _write_snapshot(tmp_path, {"n_pools": 10, "n_unknown": 1, "chain_valid": True})
    assert _mon(tmp_path)._check_dfb_snapshot(_D).status == WARNING


def test_d_dfb_broken_chain_warns(tmp_path):
    _write_snapshot(tmp_path, {"generated_at": _fresh_ts(), "n_pools": 10,
                               "n_unknown": 1, "chain_valid": False})
    assert _mon(tmp_path)._check_dfb_chain(_D).status == WARNING


def test_d_dfb_feed_outage_unknown_spike_warns(tmp_path):
    _write_snapshot(tmp_path, {"generated_at": _fresh_ts(), "n_pools": 10,
                               "n_unknown": 9, "chain_valid": True})
    assert _mon(tmp_path)._check_dfb_unknown_canary(_D).status == WARNING


def test_d_dfb_empty_universe_canary_warns(tmp_path):
    _write_snapshot(tmp_path, {"generated_at": _fresh_ts(), "n_pools": 0,
                               "n_unknown": 0, "chain_valid": True})
    assert _mon(tmp_path)._check_dfb_unknown_canary(_D).status == WARNING


def test_d_dfb_low_unknown_ratio_ok(tmp_path):
    _write_snapshot(tmp_path, {"generated_at": _fresh_ts(), "n_pools": 100,
                               "n_unknown": 20, "chain_valid": True})
    assert _mon(tmp_path)._check_dfb_unknown_canary(_D).status == OK
