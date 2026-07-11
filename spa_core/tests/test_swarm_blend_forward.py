"""Tests for spa_core/strategy_lab/swarm/blend_forward.py (Swarm block 2 — cross-desk blend forward)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.strategy_lab.swarm import blend_forward as bf


# ── fixtures: synthetic three-leg layout ───────────────────────────────────────────────────────
def _dates(n: int, start_day: int = 1) -> list[str]:
    return [f"2026-06-{d:02d}" if d <= 30 else f"2026-07-{d - 30:02d}"
            for d in range(start_day, start_day + n)]


def _write_susde(path: Path, rows: list[tuple[str, float, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for date, eq, phase in rows:
            fh.write(json.dumps({"date": date, "equity_usd": eq, "phase": phase}) + "\n")


def _write_series(path: Path, rows: list[tuple[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"id": path.stem, "series": [{"date": d, "equity_usd": e} for d, e in rows]}))


def _sources(tmp_path: Path) -> dict:
    return {
        "susde": {"path": tmp_path / "susde.jsonl", "desc": "susde test leg"},
        "rates": {"path": tmp_path / "rates.json", "desc": "rates test leg"},
        "rwa": {"path": tmp_path / "rwa.json", "desc": "rwa test leg"},
    }


def _build_legs(tmp_path: Path, n: int = 10, susde_crash_at: int | None = None) -> dict:
    ds = _dates(n)
    srcs = _sources(tmp_path)
    susde = []
    eq = 100_000.0
    for i, d in enumerate(ds):
        r = -0.08 if (susde_crash_at is not None and i == susde_crash_at) else 0.001
        eq *= (1.0 + r) if i else 1.0
        susde.append((d, round(eq, 2), "forward"))
    # a backtest bar BEFORE the forward window must be ignored by the loader
    susde.insert(0, ("2026-05-01", 90_000.0, "backtest"))
    _write_susde(srcs["susde"]["path"], susde)
    _write_series(srcs["rates"]["path"], [(d, round(100_000 * (1 + 0.000124 * i), 2))
                                          for i, d in enumerate(ds)])
    _write_series(srcs["rwa"]["path"], [(d, round(100_000 * (1 + 0.00009 * i), 2))
                                        for i, d in enumerate(ds)])
    return srcs


# ── leg loading ────────────────────────────────────────────────────────────────────────────────
def test_susde_loader_forward_phase_only(tmp_path):
    srcs = _build_legs(tmp_path)
    legs = bf.load_legs(srcs)
    assert "2026-05-01" not in legs["susde"]  # backtest bar excluded
    assert len(legs["susde"]) == 10
    assert len(legs["rates"]) == len(legs["rwa"]) == 10


def test_missing_leg_degraded_fail_closed(tmp_path):
    srcs = _sources(tmp_path)  # nothing written at all
    doc = bf.run_forward_blend(sources=srcs, out_dir=tmp_path / "swarm")
    assert doc["state"] == "DEGRADED"
    assert "susde" in doc["reason"] and doc["common_days"] == 0
    assert "blend" not in doc  # no invented numbers


def test_single_common_day_is_warmup(tmp_path):
    srcs = _sources(tmp_path)
    _write_susde(srcs["susde"]["path"], [("2026-06-01", 100_000.0, "forward")])
    _write_series(srcs["rates"]["path"], [("2026-06-01", 100_000.0), ("2026-06-02", 100_010.0)])
    _write_series(srcs["rwa"]["path"], [("2026-06-01", 100_000.0), ("2026-06-02", 100_009.0)])
    doc = bf.run_forward_blend(sources=srcs, out_dir=tmp_path / "swarm")
    assert doc["state"] == "WARMUP" and doc["common_days"] == 1
    assert "blend" not in doc


# ── the blend cushions the aggressive leg's crash (idea #3's whole point) ──────────────────────
def test_blend_cushions_susde_crash(tmp_path):
    srcs = _build_legs(tmp_path, n=12, susde_crash_at=6)
    doc = bf.run_forward_blend(sources=srcs, out_dir=tmp_path / "swarm")
    assert doc["state"] == "TRACKING"
    susde_dd = doc["legs"]["susde"]["max_dd_pct"]
    blend_dd = doc["blend"]["max_dd_pct"]
    assert susde_dd == pytest.approx(-8.0, abs=0.3)
    # 25% weight → the blend's drawdown must be ~a quarter of the lone-leg crash
    assert blend_dd > susde_dd * 0.35  # i.e. much shallower (dd values are negative)
    assert blend_dd < 0.0


def test_blend_math_daily_rebalanced_exact(tmp_path):
    """Two flat legs + one moving leg: blend return must equal weight × leg return each day."""
    srcs = _sources(tmp_path)
    ds = _dates(3)
    _write_susde(srcs["susde"]["path"], [(d, 100_000.0 * (1.02 ** i), "forward")
                                         for i, d in enumerate(ds)])
    _write_series(srcs["rates"]["path"], [(d, 100_000.0) for d in ds])
    _write_series(srcs["rwa"]["path"], [(d, 100_000.0) for d in ds])
    doc = bf.run_forward_blend(sources=srcs, out_dir=tmp_path / "swarm")
    expected = 100_000.0 * (1 + 0.25 * 0.02) ** 2
    assert doc["blend"]["equity_usd"] == pytest.approx(expected, rel=1e-9)


# ── risk-parity research column ────────────────────────────────────────────────────────────────
def test_risk_parity_needs_history_then_downweights_volatile_leg(tmp_path):
    srcs = _build_legs(tmp_path, n=10)
    doc = bf.run_forward_blend(sources=srcs, out_dir=tmp_path / "swarm")
    assert doc["risk_parity_research"]["weights"] is None  # 10 < lookback+1

    srcs = _build_legs(tmp_path, n=bf.RISK_PARITY_LOOKBACK + 5, susde_crash_at=15)
    doc = bf.run_forward_blend(sources=srcs, out_dir=tmp_path / "swarm")
    rp = doc["risk_parity_research"]["weights"]
    assert rp is not None and abs(sum(rp.values()) - 1.0) < 0.01
    assert rp["susde"] < rp["rates"] and rp["susde"] < rp["rwa"]  # volatile leg downweighted


# ── status + proof chain ───────────────────────────────────────────────────────────────────────
def test_status_written_and_proof_idempotent_per_day(tmp_path):
    srcs = _build_legs(tmp_path)
    out = tmp_path / "swarm"
    doc = bf.run_forward_blend(sources=srcs, out_dir=out)
    assert doc["proof_appended"] is True
    saved = json.loads((out / bf.STATUS_NAME).read_text())
    assert saved["is_advisory"] and saved["outside_riskpolicy"]
    assert saved["weights_default"] == {"susde": 0.25, "rates": 0.50, "rwa": 0.25}

    doc2 = bf.run_forward_blend(sources=srcs, out_dir=out)
    assert doc2["proof_appended"] is False
    lines = (out / bf.PROOF_NAME).read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["state"] == "TRACKING" and rec["prev_hash"] == "0" * 64 and "hash" in rec
