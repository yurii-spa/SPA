"""Tests for spa_core/strategy_lab/swarm/swarm_book.py (block A — the exercised swarm portfolio)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.strategy_lab.swarm import swarm_book as sb

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _write_book(agg: Path, name: str, bars: list[tuple[str, float]], backtest_tail=True) -> None:
    d = agg / name
    d.mkdir(parents=True, exist_ok=True)
    with (d / "realized_series.jsonl").open("w") as fh:
        if backtest_tail:  # a seam bar that must be ignored (re-base, not a return)
            fh.write(json.dumps({"date": "2026-06-01", "phase": "backtest",
                                 "equity_usd": 163_000.0}) + "\n")
        for date, eq in bars:
            fh.write(json.dumps({"date": date, "phase": "forward", "equity_usd": eq}) + "\n")


def _artifacts(swarm: Path, recos: dict, g_states: dict | None = None,
               systemic: str = "NORMAL", age_h: float = 0.5,
               rtmr_exo: set | None = None) -> None:
    swarm.mkdir(parents=True, exist_ok=True)
    ts = (NOW - timedelta(hours=age_h)).isoformat()
    (swarm / "leverage_brain.json").write_text(json.dumps({
        "as_of_utc": ts,
        "books": {n: {"leverage_reco": r} for n, r in recos.items()}}))
    g_states = g_states or {}
    (swarm / "guardian_forward.json").write_text(json.dumps({
        "as_of_utc": ts,
        "systemic": {"state": systemic},
        "books": {n: {"state": g_states.get(n, "ARMED"),
                      "rtmr": {"exogenous_derisk": n in (rtmr_exo or set())}}
                  for n in recos}}))


# ── decide_weights ─────────────────────────────────────────────────────────────────────────────
def test_weights_normalized_and_capped(tmp_path):
    _artifacts(tmp_path, {"a": 2.0, "b": 1.5, "c": 1.5})
    w, reasons = sb.decide_weights(json.loads((tmp_path / "leverage_brain.json").read_text()),
                                   json.loads((tmp_path / "guardian_forward.json").read_text()), NOW)
    assert all(v <= sb.MAX_BOOK_WEIGHT + 1e-9 for v in w.values())
    assert sum(w.values()) <= 1.0
    assert w["a"] == sb.MAX_BOOK_WEIGHT  # 2/5 = 0.4 → capped at 0.25


def test_stale_brain_all_cash(tmp_path):
    _artifacts(tmp_path, {"a": 1.5}, age_h=sb.ARTIFACT_MAX_AGE_H + 1)
    w, reasons = sb.decide_weights(json.loads((tmp_path / "leverage_brain.json").read_text()),
                                   json.loads((tmp_path / "guardian_forward.json").read_text()), NOW)
    assert w == {} and any("fail-closed" in r for r in reasons)


def test_systemic_all_cash(tmp_path):
    _artifacts(tmp_path, {"a": 1.5, "b": 1.5}, systemic="SYSTEMIC")
    w, reasons = sb.decide_weights(json.loads((tmp_path / "leverage_brain.json").read_text()),
                                   json.loads((tmp_path / "guardian_forward.json").read_text()), NOW)
    assert w == {} and any("SYSTEMIC" in r for r in reasons)


def test_derisked_and_rtmr_books_zeroed(tmp_path):
    _artifacts(tmp_path, {"a": 1.5, "b": 1.5, "c": 1.5},
               g_states={"b": "DERISKED"}, rtmr_exo={"c"})
    w, _ = sb.decide_weights(json.loads((tmp_path / "leverage_brain.json").read_text()),
                             json.loads((tmp_path / "guardian_forward.json").read_text()), NOW)
    assert "b" not in w and "c" not in w and "a" in w


# ── the causality contract ─────────────────────────────────────────────────────────────────────
def test_init_never_retro_applies(tmp_path):
    agg, swarm = tmp_path / "agg", tmp_path / "swarm"
    _write_book(agg, "a", [("2026-07-08", 100000.0), ("2026-07-09", 105000.0)])
    _artifacts(swarm, {"a": 1.5})
    doc = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW)
    assert doc["equity"] == sb.NOTIONAL_USD          # +5% bar existed BEFORE init → not applied
    assert doc["days_tracked"] == 0
    assert doc["last_applied_date"] == "2026-07-09"
    assert doc["weights"] == {"a": 0.25}             # decision recorded for FUTURE bars


def test_applies_new_bar_with_prior_weights(tmp_path):
    agg, swarm = tmp_path / "agg", tmp_path / "swarm"
    _write_book(agg, "a", [("2026-07-09", 100000.0)])
    _artifacts(swarm, {"a": 1.5})
    sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW)          # init: w={a:0.25}

    _write_book(agg, "a", [("2026-07-09", 100000.0), ("2026-07-10", 102000.0)])  # +2% next day
    doc = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW + timedelta(hours=1))
    assert doc["days_tracked"] == 1
    assert doc["equity"] == pytest.approx(100_000 * (1 + 0.25 * 0.02))  # 0.25 weight × +2%
    row = doc["history"][0]
    assert row["date"] == "2026-07-10" and row["weights_used"] == {"a": 0.25}


def test_gap_book_contributes_zero_and_flagged(tmp_path):
    agg, swarm = tmp_path / "agg", tmp_path / "swarm"
    _write_book(agg, "a", [("2026-07-09", 100000.0)])
    _write_book(agg, "b", [("2026-07-09", 100000.0)])
    _artifacts(swarm, {"a": 1.5, "b": 1.5})
    sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW)
    # only book a prints the next bar; b is silent that day
    _write_book(agg, "a", [("2026-07-09", 100000.0), ("2026-07-10", 104000.0)])
    doc = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW + timedelta(hours=1))
    row = doc["history"][0]
    assert row["gap_books"] == ["b"]
    assert doc["equity"] == pytest.approx(100_000 * (1 + 0.25 * 0.04))


def test_history_append_only_across_restarts(tmp_path):
    agg, swarm = tmp_path / "agg", tmp_path / "swarm"
    _write_book(agg, "a", [("2026-07-09", 100000.0)])
    _artifacts(swarm, {"a": 1.5})
    sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW)
    _write_book(agg, "a", [("2026-07-09", 100000.0), ("2026-07-10", 102000.0)])
    d1 = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW + timedelta(hours=1))
    d2 = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW + timedelta(hours=2))
    assert d2["history"] == d1["history"]            # idempotent: same bars never re-applied
    assert d2["equity"] == d1["equity"]


def test_seam_backtest_bar_ignored(tmp_path):
    agg, swarm = tmp_path / "agg", tmp_path / "swarm"
    _write_book(agg, "a", [("2026-07-09", 100000.0)], backtest_tail=True)
    _artifacts(swarm, {"a": 1.5})
    doc = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW)
    assert doc["last_applied_date"] == "2026-07-09"  # backtest 2026-06-01 bar invisible


def test_proof_chain_daily_idempotent(tmp_path):
    agg, swarm = tmp_path / "agg", tmp_path / "swarm"
    _write_book(agg, "a", [("2026-07-09", 100000.0)])
    _artifacts(swarm, {"a": 1.5})
    doc = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW)
    assert doc["proof_appended"] is True
    doc2 = sb.run_swarm_book(agg_dir=agg, swarm_dir=swarm, now=NOW + timedelta(hours=1))
    assert doc2["proof_appended"] is False
    assert len((swarm / sb.PROOF_NAME).read_text().splitlines()) == 1
