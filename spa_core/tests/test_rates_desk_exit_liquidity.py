"""
spa_core/tests/test_rates_desk_exit_liquidity.py — the §9 exit-liquidity VALIDATION tests.

Proves the brief §9 ask ("validate the proxy against what actually filled during Oct-2025") on the
exit_liquidity_validation module, BOTH on a small in-memory deep dataset (hermetic, always runs) AND
— when the real deep file is present with the per-day TVL series — on the real Oct-2025 stress data.

Three properties, per the brief:
  (1) the exit_liquidity proxy SHRINKS when the contemporaneous pool TVL shrinks (Oct-2025 replay);
  (2) the sizing discipline (max_size_frac_of_exit + the hold-side kills) keeps the desk out of an
      illiquid bag through the collapse — no position is ever STUCK below exit without a kill firing;
  (3) the EXIT_CAPACITY collapse kill fires when a position exceeds contemporaneous exit capacity.

PURE / deterministic / no network (the validation reads the cached deep dataset; the in-memory tests
inject a synthetic one). LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal

import pytest

from spa_core.strategy_lab.rates_desk import exit_liquidity_validation as elv
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams


# ── a hermetic Oct-2025-shaped deep dataset (TVL collapses through the window) ─────────────────────
def _oct2025_deep():
    """Two affected synth-dollar PT markets whose contemporaneous TVL collapses across the window —
    the shape of the real Oct-2025 USDe leverage unwind (USDe $14B→$5.6B drained the PT pools)."""
    def series(peak_tvl, trough_tvl):
        # peak on 2025-10-01, steady decline to a trough on 2025-11-15 (monotone for a clean test)
        days = ["2025-09-20", "2025-10-01", "2025-10-15", "2025-11-01", "2025-11-15"]
        tvls = [peak_tvl * 0.9, peak_tvl, peak_tvl * 0.8, trough_tvl * 1.1, trough_tvl]
        return [{"date": d, "implied_yield": 0.10, "underlying_yield": 0.09,
                 "tvl_usd": round(t, 2), "pt_price": None} for d, t in zip(days, tvls)]
    return {
        "generated_at": "2026-01-01T00:00:00+00:00", "method": "test",
        "underlyings": ["sUSDe", "USDe"], "window": {"start": "2025-09-20", "end": "2025-11-15"},
        "markets": {
            "PT-sUSDE-27NOV2025": {
                "underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-27NOV2025",
                "market_address": "0xA", "pt_address": "0xPA", "maturity": "2025-11-27",
                "method": "direct_api_implied", "series": series(142_000_000, 88_000_000),
            },
            "PT-USDe-27NOV2025": {
                "underlying": "USDe", "kind": "stable_synth", "symbol": "PT-USDe-27NOV2025",
                "market_address": "0xB", "pt_address": "0xPB", "maturity": "2025-11-27",
                "method": "direct_api_implied", "series": series(30_000_000, 13_000_000),
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# Hermetic (always-runs) — synthetic Oct-2025-shaped deep dataset
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def test_proxy_shrinks_with_real_tvl_hermetic():
    out = elv.proxy_shrinks(_oct2025_deep())
    assert out["VERDICT_proxy_shrinks_with_real_tvl"] is True
    assert out["n_markets"] == 2
    for m in out["per_market"]:
        assert m["proxy_shrank"] is True
        # exit drawdown tracks TVL drawdown exactly (exit is linear in depth)
        assert abs(m["exit_liquidity_drawdown_pct"] - m["tvl_drawdown_pct"]) < 0.01
        assert m["tvl_drawdown_pct"] > 30.0  # a real, material collapse


def test_sizing_protected_book_hermetic():
    out = elv.sizing_protects(_oct2025_deep())
    assert out["VERDICT_sizing_protected_book"] is True
    assert out["n_markets"] == 2
    # no market was ever a stuck illiquid bag (held below exit WITHOUT the kill firing)
    for m in out["per_market"]:
        assert m["stuck_illiquid_bag_without_kill"] is False
        # the desk DID derisk during the window (a kill fired) — the discipline engaged
        assert m["first_kill_reason"] in ("concentration", "exit_capacity")


def test_collapse_kill_fires_hermetic():
    out = elv.collapse_kill_fires(_oct2025_deep())
    assert out["VERDICT_exit_capacity_kill_fires"] is True
    for m in out["per_market"]:
        assert m["kill_reason"] == "exit_capacity"
        assert m["killed_state"] is True


def test_run_overall_verdict_hermetic():
    out = elv.run(deep=_oct2025_deep())
    assert out["VERDICT_exit_liquidity_validated"] is True
    assert out["proxy_shrinks"]["VERDICT_proxy_shrinks_with_real_tvl"] is True
    assert out["sizing_protects"]["VERDICT_sizing_protected_book"] is True
    assert out["collapse_kill"]["VERDICT_exit_capacity_kill_fires"] is True


def test_proxy_does_not_shrink_on_stale_constant_dataset():
    """HONESTY guard: an OLD deep file (no per-day tvl_usd) cannot shrink — every day degrades to the
    SAME documented constant. The validation must report that FAIL, never a fabricated pass."""
    stale = _oct2025_deep()
    for m in stale["markets"].values():
        for pt in m["series"]:
            pt.pop("tvl_usd", None)  # strip the TVL series → the pre-fix stale-constant behavior
    out = elv.proxy_shrinks(stale)
    assert out["VERDICT_proxy_shrinks_with_real_tvl"] is False  # honest fail — no shrink possible
    for m in out["per_market"]:
        assert m["exit_liquidity_drawdown_pct"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# Real Oct-2025 data — runs only when the deep file is present WITH the per-day TVL series
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _real_deep_with_tvl():
    try:
        deep = pph.load()
    except (FileNotFoundError, ValueError):
        return None
    # require at least one affected market carrying a real per-day tvl_usd inside the window
    lo, hi = elv.OCT2025_WINDOW
    for m in deep.get("markets", {}).values():
        if str(m.get("underlying", "")).lower() in elv._AFFECTED_UNDERLYINGS:
            if any(lo <= pt.get("date", "") <= hi and isinstance(pt.get("tvl_usd"), (int, float))
                   for pt in m.get("series", [])):
                return deep
    return None


def test_real_oct2025_proxy_shrinks():
    deep = _real_deep_with_tvl()
    if deep is None:
        pytest.skip("deep PT history with per-day TVL not present — run pendle_pt_history first")
    out = elv.proxy_shrinks(deep)
    assert out["VERDICT_proxy_shrinks_with_real_tvl"] is True
    assert out["n_markets"] >= 1
    # the real Oct-2025 unwind drained these pools materially (the brief's specific quantification)
    assert any(m["tvl_drawdown_pct"] >= 25.0 for m in out["per_market"])


def test_real_oct2025_sizing_protected():
    deep = _real_deep_with_tvl()
    if deep is None:
        pytest.skip("deep PT history with per-day TVL not present")
    out = elv.sizing_protects(deep)
    assert out["VERDICT_sizing_protected_book"] is True


def test_real_oct2025_collapse_kill():
    deep = _real_deep_with_tvl()
    if deep is None:
        pytest.skip("deep PT history with per-day TVL not present")
    out = elv.collapse_kill_fires(deep)
    assert out["VERDICT_exit_capacity_kill_fires"] is True


def test_real_oct2025_deterministic():
    deep = _real_deep_with_tvl()
    if deep is None:
        pytest.skip("deep PT history with per-day TVL not present")
    a = elv.run(deep=deep)
    b = elv.run(deep=deep)
    assert a == b  # same data → identical verdict (PURE / deterministic)


# ── doc-writer: idempotent + atomic ────────────────────────────────────────────────────────────────
def test_doc_section_idempotent_and_atomic(tmp_path):
    out = elv.run(deep=_oct2025_deep())
    doc = tmp_path / "RATES_DESK_VALIDATION.md"
    doc.write_text("# pre-existing\n\nsome other content\n", encoding="utf-8")
    elv.write_doc_section(out, doc_path=doc)
    body1 = doc.read_text(encoding="utf-8")
    assert "## §9 Exit-liquidity validation" in body1
    assert "some other content" in body1            # other content preserved
    assert elv._DOC_BEGIN in body1 and elv._DOC_END in body1
    # writing again is idempotent (single marker block, no duplication)
    elv.write_doc_section(out, doc_path=doc)
    body2 = doc.read_text(encoding="utf-8")
    assert body2.count(elv._DOC_BEGIN) == 1
    assert body2.count(elv._DOC_END) == 1
    assert not list(tmp_path.glob(".*tmp"))          # atomic — no leftover temp files
