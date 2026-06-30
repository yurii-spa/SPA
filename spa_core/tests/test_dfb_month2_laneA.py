"""
test_dfb_month2_laneA.py — Month-2 Lane-A: the peg-grading fix + trends + breadth (0-bypass).

Covers, property + red-team + smoke:
  1. PEG FIX — an ETH-kind (LST/LRT) pool that fail-CLOSED to UNKNOWN now GRADES A/B/C/D once the live
     X/ETH peg series is injected (the desk's UnderlyingRiskFeed). Genuinely-absent peg feed → still
     UNKNOWN (honest). A TOXIC/depegged LRT still → class-D + REFUSE + tail_veto (peg feed does NOT
     soften toxicity, and cannot be sized around).
  2. TRENDS — 7d/30d APY/TVL deltas + refusal-state flips from the captured history; THIN-aware
     (<2 points → INSUFFICIENT_DATA, never extrapolated); deltas re-derivable from the raw series.
  3. BREADTH — behind SPA_DFB_BREADTH (default OFF); ON → wider keyless universe where EVERY pool goes
     through the SAME overlay (0 bypass — a thin/unknown breadth pool → UNKNOWN, never an ungraded
     "safe" passthrough); a toxic high-APY breadth pool still REFUSES.

PURE / no network (injected feeds + injected breadth rows) / no live-data mutation (tmp dirs).
"""
from __future__ import annotations

import datetime

import pytest

from spa_core.dfb import Pool, RiskClass
from spa_core.dfb import breadth_feed, pool_universe, risk_overlay, trends
from spa_core.dfb.risk_overlay import overlay
from spa_core.strategy_lab.rates_desk.feeds import UnderlyingRiskFeed

_AS_OF = "2026-06-29"


# ── hermetic peg feed (no network) ───────────────────────────────────────────────────────────────
def _dates(end: str, n: int):
    e = datetime.date.fromisoformat(end)
    return [(e - datetime.timedelta(days=i)).isoformat() for i in range(n)][::-1]


class _CleanPrice:
    """Tight-peg LST + a TOXIC depegged ezETH (drawdown from peak)."""
    def history_ratios(self, start_date=None, end_date=None, span=90):
        ds = _dates(end_date or _AS_OF, 60)
        return {
            "weeth": {d: 1.04 + 0.0001 * i for i, d in enumerate(ds)},   # clean, value-accruing
            "steth": {d: 1.0 for d in ds},
            "reth": {d: 1.10 for d in ds},
            "ezeth": {d: (1.05 if i < 30 else 1.05 - 0.0025 * (i - 30)) for i, d in enumerate(ds)},
        }


class _NoEthPrice:
    """A price feed with NO ETH-kind ratio history (the genuinely-unavailable case)."""
    def history_ratios(self, start_date=None, end_date=None, span=90):
        return {}


class _Funding:
    def history(self, start_date=None, end_date=None):
        return {d: 0.0001 for d in _dates(end_date or _AS_OF, 100)}   # benign positive funding


def _feed(price):
    return UnderlyingRiskFeed(price_feed=price, funding_feed=_Funding())


def _lst_pool(asset="eeth", kind="lst", apy=0.04, tvl=50_000_000.0):
    return Pool(pool_id=f"x__ethereum__{asset}", protocol="etherfi", chain="Ethereum", asset=asset,
                tier="T2", source="adapter_registry", apy_total=apy, tvl_usd=tvl,
                underlying_kind=kind, as_of=_AS_OF)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1) THE PEG-GRADING FIX
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_eth_kind_unknown_without_feed_but_grades_with_peg_feed():
    """BEFORE→AFTER: a clean LST pool is UNKNOWN with no peg feed, GRADES A/B/C/D with the live feed."""
    pool = _lst_pool()
    # no peg feed available → fail-CLOSED UNKNOWN (honest)
    before = overlay(pool, risk_feed=_feed(_NoEthPrice()))
    assert before.risk_class is RiskClass.UNKNOWN
    assert before.flag_reason == "insufficient_risk_surface"
    # live peg series injected → it now grades (no longer UNKNOWN)
    after = overlay(pool, risk_feed=_feed(_CleanPrice()))
    assert after.risk_class is not RiskClass.UNKNOWN
    assert after.risk_class in (RiskClass.A, RiskClass.B, RiskClass.C, RiskClass.D)
    assert after.refusal.verdict in ("SAFE", "REFUSE")
    assert after.structural_haircut is not None  # a real, non-fabricated haircut


def test_clean_lst_grades_safe_with_peg_feed():
    after = overlay(_lst_pool(asset="eeth", kind="lst"), risk_feed=_feed(_CleanPrice()))
    assert after.refusal.verdict == "SAFE"
    assert after.risk_class in (RiskClass.A, RiskClass.B)
    assert not after.refusal.tail_veto


def test_genuinely_absent_peg_feed_still_unknown():
    """fail-CLOSED honesty: if the peg feed is genuinely unavailable, the ETH-kind pool stays UNKNOWN
    (we never fabricate peg=0 to manufacture a benign grade)."""
    ov = overlay(_lst_pool(), risk_feed=_feed(_NoEthPrice()))
    assert ov.risk_class is RiskClass.UNKNOWN
    assert ov.flagged is True
    assert ov.structural_haircut is None


@pytest.mark.parametrize("size", ["100000000", "10000000", "1000000", "1000"])
def test_toxic_lrt_still_class_d_refuse_with_peg_feed(size):
    """The peg feed does NOT soften toxicity: a DEPEGGED LRT, fed its REAL peg drawdown, is class D +
    REFUSE + tail_veto at ANY size (the size-down exploit stays closed even with the live feed)."""
    from decimal import Decimal
    pool = _lst_pool(asset="ezeth", kind="lrt", apy=0.22, tvl=15_000_000.0)
    ov = overlay(pool, risk_feed=_feed(_CleanPrice()), probe_size_usd=Decimal(size),
                 exit_liquidity_usd=3_000_000.0)
    assert ov.refusal.verdict == "REFUSE", f"toxic LRT not refused at {size}"
    assert ov.risk_class is RiskClass.D, f"toxic LRT not class D at {size}"
    assert ov.refusal.tail_veto is True, f"toxic veto not size-independent at {size}"
    assert ov.structural_haircut is not None and ov.structural_haircut > 0.06


def test_peg_overlay_deterministic_with_feed():
    a = overlay(_lst_pool(), risk_feed=_feed(_CleanPrice())).to_dict()
    b = overlay(_lst_pool(), risk_feed=_feed(_CleanPrice())).to_dict()
    assert a == b


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2) TRENDS (THIN-aware)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _hist_record(date, apy, tvl, verdict="SAFE", rclass="A"):
    return {"capture_date": date, "apy_total": apy, "tvl_usd": tvl,
            "refusal_verdict": verdict, "risk_class": rclass}


def test_trend_thin_one_point_is_insufficient_not_extrapolated():
    recs = [_hist_record("2026-06-29", 0.08, 40e6)]
    t = trends.compute_trend("p", records=recs)
    assert t["thin"] is True
    assert t["n_points"] == 1
    for w in ("7d", "30d"):
        assert t["deltas"][w]["status"] == "INSUFFICIENT_DATA"
        assert t["deltas"][w]["apy_delta"] is None
    # sparkline still carries the one real point (no fabricated second point)
    assert len(t["series"]["apy_total"]) == 1


def test_trend_deltas_match_recompute_from_raw():
    recs = [
        _hist_record("2026-05-29", 0.06, 30e6, "SAFE", "A"),   # 31 days before latest
        _hist_record("2026-06-22", 0.07, 35e6, "SAFE", "A"),   # 7 days before latest
        _hist_record("2026-06-29", 0.09, 40e6, "REFUSE", "C"),  # latest
    ]
    t = trends.compute_trend("p", records=recs)
    assert t["thin"] is False
    # 7d window anchors on 2026-06-22 (<= latest-7d): apy 0.09-0.07 = 0.02
    d7 = t["deltas"]["7d"]
    assert d7["status"] == "ok"
    assert abs(d7["apy_delta"] - 0.02) < 1e-9
    assert abs(d7["tvl_delta"] - 5e6) < 1e-3
    # 30d window anchors on 2026-05-29: apy 0.09-0.06 = 0.03
    d30 = t["deltas"]["30d"]
    assert abs(d30["apy_delta"] - 0.03) < 1e-9
    # refusal-state flip (SAFE/A → REFUSE/C) detected once
    assert t["n_refusal_state_changes"] == 1
    assert t["refusal_state_changes"][0]["to_verdict"] == "REFUSE"


def test_trend_window_with_no_anchor_is_insufficient():
    """Two recent points but none old enough for the 30d window → that window is INSUFFICIENT_DATA."""
    recs = [_hist_record("2026-06-28", 0.08, 40e6), _hist_record("2026-06-29", 0.09, 41e6)]
    t = trends.compute_trend("p", records=recs)
    assert t["deltas"]["30d"]["status"] == "INSUFFICIENT_DATA"


def test_trend_reads_from_history_file(tmp_path):
    """Smoke: compute_trend reads the captured JSONL via history.read_history."""
    from spa_core.dfb import history as dfb_history
    pools = pool_universe.build_universe(surface={"as_of": _AS_OF, "quotes": [
        {"market_id": "pt-susde-1", "underlying": "susde", "protocol": "pendle", "venue": "pendle_pt",
         "kind": "stable_synth", "quoted_rate": "0.085", "tvl_usd": "40000000",
         "exit_liquidity_usd": "8000000", "as_of": _AS_OF, "chain": "Ethereum"}]})
    ovs = risk_overlay.build_overlays(pools)
    dfb_history.capture_all(ovs, capture_date="2026-06-28", data_dir=tmp_path)
    dfb_history.capture_all(ovs, capture_date="2026-06-29", data_dir=tmp_path)
    pid = ovs[0].pool_id
    t = trends.compute_trend(pid, data_dir=tmp_path)
    assert t["n_points"] == 2 and t["thin"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3) BREADTH (flagged, 0-bypass)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
_BREADTH_ROWS = [
    {"project": "aave-v3", "chain": "Ethereum", "symbol": "USDC", "apy": 5.2, "apyBase": 5.2,
     "apyReward": 0.0, "tvlUsd": 900_000_000, "ilRisk": "no", "exposure": "single"},
    {"project": "somefarm", "chain": "Base", "symbol": "WTF-USDC", "apy": 180.0, "apyBase": 2.0,
     "apyReward": 178.0, "tvlUsd": 5_000_000, "ilRisk": "yes", "exposure": "multi"},  # toxic, unknown kind
    {"project": "pendle", "chain": "Ethereum", "symbol": "sUSDe", "apy": 9.5, "apyBase": 9.5,
     "apyReward": 0.0, "tvlUsd": 40_000_000, "ilRisk": "no", "exposure": "single"},
    {"project": "spam", "chain": "Ethereum", "symbol": "JUNK", "apy": 9.0, "tvlUsd": 100},  # sub-floor
    {"project": "bad", "chain": "Ethereum", "symbol": "NEG", "apy": -3.0, "tvlUsd": 10_000_000},  # neg APY
]


def test_breadth_flag_default_off():
    assert pool_universe.breadth_enabled() is False
    pools = pool_universe.build_universe(surface={"as_of": _AS_OF, "quotes": []},
                                        breadth_rows=_BREADTH_ROWS)  # flag resolves OFF → no breadth
    assert not any(p.pool_id.startswith("breadth-") for p in pools)


def test_breadth_flag_on_widens_universe():
    pools = pool_universe.build_universe(surface={"as_of": _AS_OF, "quotes": []},
                                        include_breadth=True, breadth_rows=_BREADTH_ROWS)
    breadth = [p for p in pools if p.pool_id.startswith("breadth-")]
    # sub-floor TVL + negative APY rows are DROPPED (fail-CLOSED) → 3 admitted
    assert len(breadth) == 3
    assert all(p.apy_total is not None and p.apy_total >= 0 for p in breadth)


def test_breadth_apy_normalized_from_percent():
    pools = pool_universe.build_universe(surface={"as_of": _AS_OF, "quotes": []},
                                        include_breadth=True, breadth_rows=_BREADTH_ROWS)
    usdc = next(p for p in pools if p.pool_id == "breadth-aave-v3__ethereum__usdc")
    assert abs(usdc.apy_total - 0.052) < 1e-9  # 5.2% → 0.052 decimal


def test_breadth_zero_bypass_every_pool_graded():
    """THE invariant: every breadth pool passes through the IDENTICAL overlay — each has a verdict
    object (A/B/C/D or fail-CLOSED UNKNOWN), NEVER an ungraded passthrough."""
    pools = pool_universe.build_universe(surface={"as_of": _AS_OF, "quotes": []},
                                        include_breadth=True, breadth_rows=_BREADTH_ROWS)
    breadth = [p for p in pools if p.pool_id.startswith("breadth-")]
    ovs = risk_overlay.build_overlays(breadth)
    assert len(ovs) == len(breadth)
    for ov in ovs:
        assert ov.refusal is not None and ov.refusal.verdict in ("SAFE", "REFUSE", "UNKNOWN")
        assert ov.risk_class in (RiskClass.A, RiskClass.B, RiskClass.C, RiskClass.D, RiskClass.UNKNOWN)


def test_breadth_toxic_unknown_kind_fails_closed_not_safe():
    """A high-APY breadth pool whose kind the engine can't resolve must be UNKNOWN (fail-CLOSED),
    NEVER a watered-down 'safe' passthrough — breadth never relaxes the risk truth."""
    pools = pool_universe.build_universe(surface={"as_of": _AS_OF, "quotes": []},
                                        include_breadth=True, breadth_rows=_BREADTH_ROWS)
    wtf = next(p for p in pools if "wtf-usdc" in p.pool_id)
    ov = overlay(wtf)
    assert ov.risk_class is RiskClass.UNKNOWN
    assert ov.refusal.verdict == "UNKNOWN"
    assert ov.flagged is True
    assert ov.structural_haircut is None  # never a fabricated grade


def test_breadth_known_kind_pool_grades():
    """A breadth pool whose symbol maps to a known kind grades normally through the overlay."""
    pools = pool_universe.build_universe(surface={"as_of": _AS_OF, "quotes": []},
                                        include_breadth=True, breadth_rows=_BREADTH_ROWS)
    susde = next(p for p in pools if "susde" in p.pool_id and p.pool_id.startswith("breadth-"))
    ov = overlay(susde)
    assert ov.risk_class in (RiskClass.A, RiskClass.B, RiskClass.C, RiskClass.D)
    assert ov.risk_class is not RiskClass.UNKNOWN


def test_breadth_env_flag_resolves(monkeypatch):
    monkeypatch.setenv(breadth_feed.BREADTH_FLAG_ENV, "1")
    assert breadth_feed.breadth_enabled() is True
    monkeypatch.setenv(breadth_feed.BREADTH_FLAG_ENV, "off")
    assert breadth_feed.breadth_enabled() is False
    monkeypatch.delenv(breadth_feed.BREADTH_FLAG_ENV, raising=False)
    assert breadth_feed.breadth_enabled() is False


def test_breadth_build_and_write_metadata(tmp_path):
    """Smoke: the writer records the breadth flag + count + n_unknown (breadth OFF → no network)."""
    res = risk_overlay.build_and_write(
        write=True, data_dir=tmp_path, surface={"as_of": _AS_OF, "quotes": [
            {"market_id": "pt-susde-1", "underlying": "susde", "protocol": "pendle",
             "venue": "pendle_pt", "kind": "stable_synth", "quoted_rate": "0.085",
             "tvl_usd": "40000000", "exit_liquidity_usd": "8000000", "as_of": _AS_OF,
             "chain": "Ethereum"}]},
        include_breadth=False)
    assert "breadth" in res and "n_breadth" in res and "n_unknown" in res
    assert res["breadth"] is False
    assert res["chain_valid"] is True
