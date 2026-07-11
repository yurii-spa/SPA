"""Tests for spa_core/strategy_lab/swarm/guardian_forward.py (Swarm block 1 — L2 guardians).

The trace-equivalence test is the contract that keeps `vol_guardian_trace` from ever silently
diverging from the canonical OOS-validated overlay `aggressive_lab.guardian.apply_guardian_vol`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol
from spa_core.strategy_lab.swarm import guardian_forward as gf


def _series(seed: int, n: int, spike_at: int | None = None) -> list[float]:
    """Deterministic pseudo-random equity series (no random module state leakage)."""
    eq = [100_000.0]
    x = seed
    for i in range(n):
        x = (x * 1103515245 + 12345) % (2 ** 31)
        r = ((x / 2 ** 31) - 0.5) * 0.004  # ±0.2%/day base noise
        if spike_at is not None and spike_at <= i < spike_at + 6:
            x = (x * 69069 + 1) % (2 ** 31)
            r += ((x / 2 ** 31) - 0.7) * 0.06  # violent, mostly-down spike window
        eq.append(eq[-1] * (1.0 + r))
    return eq


# ── trace must equal the canonical overlay ─────────────────────────────────────────────────────
@pytest.mark.parametrize("seed,n,spike", [(7, 120, 60), (42, 300, 150), (3, 40, None), (9, 5, None)])
def test_trace_matches_canonical_overlay(seed, n, spike):
    eq = _series(seed, n, spike)
    for cost in (0.0, 0.0015):
        canonical = apply_guardian_vol(eq, roundtrip_cost=cost)
        traced, exposures, events = gf.vol_guardian_trace(eq, roundtrip_cost=cost)
        assert traced == pytest.approx(canonical)
        if len(eq) >= 2:
            assert len(exposures) == len(eq) - 1


def test_trace_derisk_only_exposures():
    eq = _series(11, 200, 90)
    _, exposures, events = gf.vol_guardian_trace(eq)
    assert set(exposures) <= {gf.GUARDIAN_PARAMS["derisk_frac"], 1.0}  # de-risk-only, never levered
    actions = [a for _, a in events]
    assert "DERISK" in actions  # the spike must trigger at least one de-risk


# ── book-level guard on a synthetic aggressive_lab layout ──────────────────────────────────────
def _write_book(root: Path, name: str, bt_eq: list[float], fwd_eq: list[float]) -> Path:
    book = root / name
    book.mkdir(parents=True)
    (book / "meta.json").write_text(json.dumps(
        {"risk_class": "C", "risk_shape": "funding_flip", "headline_apy_pct": 11.0}))
    with (book / "realized_series.jsonl").open("w") as fh:
        day = 1
        for phase, series in (("backtest", bt_eq), ("forward", fwd_eq)):
            for v in series:
                fh.write(json.dumps({"date": f"2026-{(day // 28) + 1:02d}-{(day % 28) + 1:02d}",
                                     "phase": phase, "equity_usd": round(v, 2)}) + "\n")
                day += 1
    return book


def test_guard_book_spike_derisks_and_cuts_dd(tmp_path):
    bt = _series(5, 80)  # calm backtest tail → clean baseline
    fwd = _series(21, 60, spike_at=25)  # forward window contains a violent vol spike
    book = _write_book(tmp_path, "spiky", bt, fwd)
    view = gf._guard_book(book)
    assert view["state"] in ("ARMED", "DERISKED")
    assert view["forward_days"] == len(fwd)
    assert any(e["action"] == "DERISK" for e in view["derisk_events_forward"])
    # The guardian's whole point: guarded forward drawdown strictly better than raw.
    assert view["guarded"]["max_dd_pct"] > view["raw"]["max_dd_pct"]
    assert view["warmup_source"] == "backtest_tail_normalized"
    assert view["signal"] is not None and view["signal"]["derisk_threshold"] == 2.0


def test_guard_book_calm_book_untouched(tmp_path):
    """No vol spike → guardian must not whipsaw a clean book (registry: points_farm behavior)."""
    book = _write_book(tmp_path, "calm", _series(5, 80), _series(23, 60, spike_at=None))
    view = gf._guard_book(book)
    assert view["derisk_events_forward"] == []
    assert view["guarded"]["max_dd_pct"] == pytest.approx(view["raw"]["max_dd_pct"])


def test_guard_book_no_forward_fails_closed(tmp_path):
    book = _write_book(tmp_path, "young", _series(5, 80), [])
    view = gf._guard_book(book)
    assert view["state"] == "NO_FORWARD"
    assert "raw" not in view  # no invented numbers


# ── full run: status doc + hash-chained daily proof ────────────────────────────────────────────
def test_run_forward_guardian_writes_status_and_chained_proof(tmp_path):
    agg = tmp_path / "aggressive_lab"
    _write_book(agg, "spiky", _series(5, 80), _series(21, 60, spike_at=25))
    _write_book(agg, "calm", _series(6, 80), _series(23, 40))
    out = tmp_path / "swarm"

    doc = gf.run_forward_guardian(agg_dir=agg, out_dir=out)
    assert doc["is_advisory"] and doc["outside_riskpolicy"]
    assert set(doc["books"]) == {"spiky", "calm"}
    assert doc["summary"]["books"] == 2
    assert doc["proof_appended"] is True

    saved = json.loads((out / gf.STATUS_NAME).read_text())
    assert saved["books"]["spiky"]["forward_days"] == 61  # _series(n=60) yields 61 points

    # Second run same UTC day: status refreshes, proof does NOT duplicate; chain stays valid.
    doc2 = gf.run_forward_guardian(agg_dir=agg, out_dir=out)
    assert doc2["proof_appended"] is False
    lines = [json.loads(l) for l in (out / gf.PROOF_NAME).read_text().splitlines()]
    assert len(lines) == 1
    rec = lines[0]
    assert rec["prev_hash"] == gf.GENESIS_HASH
    check = dict(rec)
    expect = check.pop("hash")
    import hashlib
    assert hashlib.sha256((rec["prev_hash"] + json.dumps(check, sort_keys=True)).encode()
                          ).hexdigest() == expect


def test_run_forward_guardian_empty_dir_fail_closed(tmp_path):
    doc = gf.run_forward_guardian(agg_dir=tmp_path / "missing", out_dir=tmp_path / "swarm")
    assert doc["books"] == {} and doc["summary"]["books"] == 0
