"""
spa_core/tests/test_aggressive_lab_producer.py — Lane 1 (PRODUCER) tests for the Aggressive Lab.

Covers the four contracts the build must hold:
  1. ROSTER          — every aggressive strategy is wrapped, declares its yield SOURCE + risk SHAPE
                       + risk_class, and accrues on REAL (injected) data.
  2. REAL DATA       — accrual uses the injected feed, NOT a hardcoded number; a STALE/MISSING feed
                       fails CLOSED (no fabricated accrual) rather than emitting a fake 12%.
  3. ISOLATION (red-team) — the lab CANNOT touch the go-live track or the live allocation:
                       protected files are byte-identical (md5) before/after a run, the IO guard
                       refuses a protected/escaping path, and verify_unchanged raises on a forced drift.
  4. BACKTEST + PROOF — a 2024-26-shaped replay produces a realized series with the stress window
                       visible, proof-chained + tamper-evident, consumable by the Lane 2 loader.

stdlib + pytest only; everything injected (no network); deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from spa_core.strategy_lab.aggressive_lab import (
    DEFAULT_NOTIONAL_USD,
    isolation,
    loader,
    proof,
    roster,
)
from spa_core.strategy_lab.aggressive_lab import _io
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds
from spa_core.strategy_lab.aggressive_lab.harness import PaperService, run_backtest, upsert_day


# ── shared fixture: a real-SHAPED injected history with a mid-window stress (no network) ──────────
def _stress_feeds(n: int = 20):
    base = datetime.date(2025, 10, 1)
    dates = [(base + datetime.timedelta(days=i)).isoformat() for i in range(n)]
    susde, pt, funding, eth = {}, {}, {}, {}
    rest = {"steth": {}, "eeth": {}}
    ratio = {"eeth": {}}
    for i, d in enumerate(dates):
        susde[d] = 0.11
        pt[d] = 0.12
        funding[d] = 0.0001 if i < 8 else -0.0005    # funding flips hostile mid-window
        eth[d] = 3000.0 if i < 8 else 2400.0          # 20% ETH crash mid-window
        rest["steth"][d] = 0.03
        rest["eeth"][d] = 0.032
        ratio["eeth"][d] = 1.03 if i < 8 else 0.92    # LRT depeg mid-window
    feeds = AggressiveFeeds(
        susde_apy_series=susde, pt_susde_series=pt, funding_series=funding,
        eth_price_series=eth, restaking_series=rest, lrt_ratio_series=ratio,
    )
    return feeds, dates


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 1. ROSTER
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_roster_complete_and_declares_source_and_shape():
    strats = roster.build_roster()
    ids = roster.roster_ids()
    # the real roster: sUSDe-DN, sUSDe-spot, Pendle-YT, Pendle-PT-levered, LRT-neutral,
    # ETH-directional, leverage-loop, points-farm.
    assert set(ids) == {
        "susde_dn", "susde_spot", "pendle_yt_susde", "pendle_pt_levered",
        "lrt_neutral", "eth_directional", "leverage_loop", "points_farm", "lp_eth_stable",
    }
    valid_shapes = {"funding_flip", "depeg", "liquidation", "il", "incentive_decay"}
    for sid, s in strats.items():
        assert s.is_advisory is True
        assert s.outside_riskpolicy is True
        assert s.risk_class in ("A", "B", "C", "D")
        assert s.risk_shape in valid_shapes
        assert s.yield_source and s.yield_source != "unspecified"
        # every entrant starts at the comparable notional, SEPARATE from the go-live track
        assert s.equity() == pytest.approx(DEFAULT_NOTIONAL_USD)


def test_eth_directional_flagged_beta_not_alpha():
    # the red-team "secretly pure ETH-beta" case must be class B (beta), never A (alpha).
    s = roster.build_roster()["eth_directional"]
    assert s.risk_class == "B"
    points = roster.build_roster()["points_farm"]
    assert points.risk_class == "D"  # incentive — decays, not a durable edge


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 2. REAL DATA — accrual tracks the feed; a stale/missing feed fails CLOSED (no fake number)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_accrual_uses_real_feed_not_hardcoded():
    """Two different injected sUSDe APYs must produce two different realized equities — proving the
    accrual reads the feed, not a hardcoded 11%/12%."""
    d = "2025-10-01"
    lo = AggressiveFeeds(susde_apy_series={d: 0.05}, pt_susde_series={d: 0.05},
                         funding_series={d: 0.0001})
    hi = AggressiveFeeds(susde_apy_series={d: 0.25}, pt_susde_series={d: 0.25},
                         funding_series={d: 0.0001})
    s_lo = roster.build_roster()["susde_spot"]
    s_hi = roster.build_roster()["susde_spot"]
    s_lo.step(lo.build_live_snapshot(d))
    s_hi.step(hi.build_live_snapshot(d))
    # higher real APY → strictly higher realized equity (not a constant fabricated number)
    assert s_hi.equity() > s_lo.equity()
    # and the magnitude matches the real feed value, not a hardcoded headline
    assert s_lo.equity() == pytest.approx(DEFAULT_NOTIONAL_USD * (1 + 0.05 / 365.0), abs=0.5)


def test_stale_missing_feed_fails_closed_no_fabricated_accrual(tmp_path):
    """A snapshot MISSING the required sUSDe feed must NOT accrue a fabricated number — the book
    fails closed and holds at its starting notional (honest gap, never a fake 11%)."""
    d = "2025-10-01"
    # feed with NO susde key (stale/missing) — only an unrelated field present
    empty = AggressiveFeeds(eth_price_series={d: 3000.0}, enable_points=False)
    snap = empty.build_live_snapshot(d)
    assert "susde" not in snap.defi_apy            # the required feed is genuinely absent
    s = roster.build_roster()["susde_spot"]
    s.step(snap)
    # fail-closed = SAFE-HOLD (owner decision 2026-07-06): a transient data gap must NOT fabricate a
    # number AND must NOT permanently kill — the book holds at its starting notional and RESUMES when
    # the feed returns (like the mark-gap path / rates_desk). The honesty invariant (no fabricated
    # accrual) is what matters and is preserved; the book stays alive (killed False), just paused.
    assert s.equity() == pytest.approx(DEFAULT_NOTIONAL_USD)  # no fabricated accrual (the real invariant)
    assert s.metrics().extra["killed"] is False              # safe-hold, not a permanent kill


def test_paper_service_global_feed_failure_records_gap_not_fake(tmp_path):
    """If the whole live snapshot build fails, the paper tick records a GAP and writes no
    fabricated realized point."""
    class Boom(AggressiveFeeds):
        def build_live_snapshot(self, as_of=None):
            raise RuntimeError("feed down")
    svc = PaperService(Boom(), state_dir=tmp_path, verify_isolation=True)
    st = svc.tick("2025-10-01")
    assert st["gap"] is True
    # no realized series file should have been created for any strategy
    for sid in roster.roster_ids():
        assert not (tmp_path / sid / "realized_series.jsonl").is_file()


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 3. ISOLATION (red-team) — cannot touch the go-live track / live allocation
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_io_guard_refuses_protected_filenames():
    for name in isolation.PROTECTED_FILES:
        with pytest.raises(isolation.IsolationViolation):
            _io.atomic_write_text(isolation.DATA_DIR / name, "x")


def test_io_guard_refuses_path_traversal_escape(tmp_path):
    # a path-traversal id that would escape the lab root into the live data dir is refused
    with pytest.raises(isolation.IsolationViolation):
        _io.atomic_write_text(tmp_path / ".." / "current_positions.json", "x", lab_root=tmp_path)


def test_backtest_leaves_golive_track_byte_identical(tmp_path):
    """RED-TEAM: a full backtest must leave every protected go-live/live-allocation file byte-
    identical (md5). verify_isolation=True asserts this internally; we also re-check here."""
    feeds, dates = _stress_feeds()
    before = isolation.snapshot_protected()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=True)
    after = isolation.snapshot_protected()
    assert before == after  # every protected file unchanged (or still absent)


def test_paper_tick_leaves_golive_track_byte_identical(tmp_path):
    feeds, dates = _stress_feeds()
    before = isolation.snapshot_protected()
    PaperService(feeds, state_dir=tmp_path, verify_isolation=True).tick(dates[0])
    assert isolation.snapshot_protected() == before


def test_verify_unchanged_raises_on_forced_drift():
    """The witness must actually FIRE if a protected file changed — proving the proof is real."""
    before = isolation.snapshot_protected()
    tampered = dict(before)
    # simulate a drift on one protected file
    first = isolation.PROTECTED_FILES[0]
    tampered[first] = "deadbeef" if tampered.get(first) != "deadbeef" else "feedface"
    with pytest.raises(isolation.IsolationViolation):
        isolation.verify_unchanged(tampered)


def test_writes_never_land_outside_lab_dir(tmp_path):
    """After a backtest, the ONLY files created are under the provided lab root — nothing in the
    real data/ dir and nothing with a protected name."""
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=True)
    written = [p.name for p in tmp_path.rglob("*") if p.is_file()]
    assert written, "backtest wrote nothing"
    for name in written:
        assert name not in isolation.PROTECTED_FILES


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 4. BACKTEST + PROOF-CHAIN — stress window visible, tamper-evident, loader-consumable
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_backtest_stress_window_visible(tmp_path):
    """The unhedged ETH-directional book must take a REAL hit through the mid-window ETH crash —
    the owner sees the −X% next to the headline."""
    feeds, dates = _stress_feeds()
    out = run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=True)
    direc = out["summary"]["eth_directional"]
    assert direc["net_return_pct"] < -5.0  # the 20% ETH crash bites the directional book
    # the kill machinery fired for the funding-flip + depeg books in-window
    assert out["summary"]["susde_dn"]["killed"] is True
    assert out["summary"]["lrt_neutral"]["killed"] is True


def test_backtest_series_proof_chained_and_tamper_evident(tmp_path):
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=True)
    series = _io.read_jsonl(tmp_path / "susde_spot" / "realized_series.jsonl")
    assert len(series) == len(dates)
    ok, reason = proof.verify_chain(series)
    assert ok, reason
    # tamper a past point's equity → the chain must break
    series[3]["equity_usd"] = 999999.0
    ok2, _ = proof.verify_chain(series)
    assert ok2 is False


def test_backtest_output_consumable_by_lane2_loader(tmp_path):
    """The realized_series.jsonl + meta.json we write must be exactly what Lane 2's loader reads."""
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=True)
    loaded = loader.load_all(data_dir=tmp_path)
    assert set(loaded.keys()) == set(roster.roster_ids())
    sd = loaded["susde_dn"]
    assert sd.backtest.n_points == len(dates)
    assert sd.risk_class in ("A", "B", "C", "D")
    assert sd.risk_shape in ("funding_flip", "depeg", "liquidation", "il", "incentive_decay")
    assert sd.n_malformed_lines == 0


def test_paper_idempotent_per_utc_day(tmp_path):
    """Re-ticking the same UTC day must NOT double-accrue (the realized series stays one point/day)."""
    feeds, dates = _stress_feeds()
    svc = PaperService(feeds, state_dir=tmp_path, verify_isolation=True)
    svc.tick(dates[0])
    eq1 = svc._strats["susde_spot"].equity()
    svc.tick(dates[0])  # same day again
    eq2 = svc._strats["susde_spot"].equity()
    assert eq1 == pytest.approx(eq2)  # no double accrual
    series = _io.read_jsonl(tmp_path / "susde_spot" / "realized_series.jsonl")
    assert len([p for p in series if p["date"] == dates[0]]) == 1


def test_paper_restart_survival(tmp_path):
    """A fresh PaperService restores the prior book state from disk (does not zero it)."""
    feeds, dates = _stress_feeds()
    svc = PaperService(feeds, state_dir=tmp_path, verify_isolation=True)
    svc.tick(dates[0])
    eq = svc._strats["susde_spot"].equity()
    # a brand-new service over the same state dir continues the book
    svc2 = PaperService(feeds, state_dir=tmp_path, verify_isolation=True)
    assert svc2._strats["susde_spot"].equity() == pytest.approx(eq)


def test_artifacts_carry_outside_riskpolicy_domain_stamp(tmp_path):
    feeds, dates = _stress_feeds()
    run_backtest(feeds, dates[0], dates[-1], state_dir=tmp_path, verify_isolation=True)
    summary = json.loads((tmp_path / "backtest_summary.json").read_text())
    assert summary["domain"] == "aggressive_lab"
    assert summary["outside_riskpolicy"] is True
    assert summary["is_advisory"] is True
    meta = json.loads((tmp_path / "susde_dn" / "meta.json").read_text())
    assert meta["outside_riskpolicy"] is True and meta["is_advisory"] is True
