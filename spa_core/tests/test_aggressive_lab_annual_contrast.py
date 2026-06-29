"""
spa_core/tests/test_aggressive_lab_annual_contrast.py — the Annual Contrast engine + one-pager.

Covers the build (per-strategy contrast over the fixture + a synthetic series), the dated drawdown
timeline (realized episodes AND the dated stress overlay), the contrast metrics, the stable-baseline
resolution, determinism/proof-hash, the one-pager, and the RED-TEAM honesty invariants:
  • the stable baseline is the REAL conservative book (not a flattering strawman) and its max-DD ~0,
  • realized drawdowns are REAL dated episodes from the series — a smooth series yields [] (no fake),
  • the dated stress overlay is clearly labelled modeled (never blended with realized),
  • INSUFFICIENT real history → INSUFFICIENT_DATA, never a fabricated year,
  • the Oct-2025 Ethena event is dated on the aggressive side and ABSENT on the stable side.

stdlib-only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("SPA_LAB_LIVE_RWA_FLOOR", "0")  # network-independent stable literal

from spa_core.strategy_lab.aggressive_lab import annual_contrast as ac
from spa_core.strategy_lab.aggressive_lab import fixtures as fx
from spa_core.strategy_lab.aggressive_lab import loader as ld

FIXED_NOW = "2026-06-30T00:00:00+00:00"


@pytest.fixture()
def fixture_dir(tmp_path) -> Path:
    d = tmp_path / "aggr"
    fx.materialize(d)
    return d


def _doc(fixture_dir, **kw):
    return ac.build_annual_contrast(
        data_dir=fixture_dir, stable_apy_pct=kw.pop("stable_apy_pct", 5.0),
        write=False, now_iso=FIXED_NOW, use_fixture_if_empty=False, **kw,
    )


# ── build / structure ─────────────────────────────────────────────────────────────────────────────
def test_builds_over_fixture(fixture_dir):
    doc = _doc(fixture_dir)
    assert doc["model"] == "aggressive_lab_annual_contrast"
    assert doc["n_strategies"] == len(fx.roster())
    # the deep-backtest fixtures produce a real year; thin_new (no backtest, 6 fwd days) is THIN.
    assert doc["n_with_data"] >= 5
    # guardrail stamps present
    for k in ("is_advisory", "outside_riskpolicy", "separate_from_golive_track"):
        assert doc[k] is True
    assert doc["llm_forbidden"] is True


def test_each_strategy_has_two_windows_kinds(fixture_dir):
    doc = _doc(fixture_dir)
    lrt = next(s for s in doc["strategies"] if s["strategy_id"] == "lrt_carry")
    wkinds = {w["window"] for w in lrt["windows"]}
    assert "trailing_12m" in wkinds
    assert any(w.startswith("cy_") for w in wkinds)  # calendar-year slices present


# ── the stable baseline (REAL conservative book, not a strawman) ────────────────────────────────────
def test_stable_baseline_is_real_and_flat(fixture_dir):
    doc = _doc(fixture_dir, stable_apy_pct=5.0)
    lrt = next(s for s in doc["strategies"] if s["strategy_id"] == "lrt_carry")
    yw = next(w for w in lrt["windows"] if w["window"] == "trailing_12m")
    stable = yw["stable"]
    # a steady ~5% book: positive return, max-DD ~0 (the HONEST contrast, not rigged)
    assert stable["total_return_pct"] > 0
    assert stable["max_drawdown_pct"] == 0.0
    assert stable["days_underwater"] == 0
    # Calmar of a zero-DD book is INSUFFICIENT (never +inf)
    assert stable["calmar"] == ac.INSUFFICIENT


def test_stable_apy_not_lowballed():
    """The stable rate must be the REAL conservative book — not understated below the RWA floor."""
    res = ac.resolve_stable_apy_pct(explicit=None, status_path=Path("/nonexistent"))
    # falls back to the committed conservative literal (the RWA/lending chassis floor ~3.4%)
    assert res["stable_apy_pct"] >= 3.0
    assert "literal" in res["stable_apy_source"]


def test_stable_apy_prefers_live_conservative_book(tmp_path):
    sp = tmp_path / "paper_trading_status.json"
    sp.write_text(json.dumps({"apy_today_pct": 4.6}), encoding="utf-8")
    res = ac.resolve_stable_apy_pct(explicit=None, status_path=sp)
    assert res["stable_apy_pct"] == 4.6
    assert "live_conservative_book" in res["stable_apy_source"]


def test_stable_apy_rejects_insane_live_value(tmp_path):
    """A corrupt/absurd live APY (e.g. 999) must NOT become the stable baseline — fail-closed."""
    sp = tmp_path / "paper_trading_status.json"
    sp.write_text(json.dumps({"apy_today_pct": 999.0}), encoding="utf-8")
    res = ac.resolve_stable_apy_pct(explicit=None, status_path=sp)
    assert res["stable_apy_pct"] < 12.0  # fell through to the conservative literal


# ── dated drawdown timeline — REAL episodes, never fabricated ───────────────────────────────────────
def test_realized_drawdowns_are_dated_and_real(fixture_dir):
    doc = _doc(fixture_dir)
    lrt = next(s for s in doc["strategies"] if s["strategy_id"] == "lrt_carry")
    realized = lrt["dated_drawdown_timeline"]["realized_drawdowns"]
    assert realized, "lrt_carry's deep backtest must show real drawdowns"
    # the catastrophic Apr-2026 rsETH depeg lands as a real, dated, deep episode
    apr = [d for d in realized if d["trough_date"].startswith("2026-04")]
    assert apr, "the Apr-2026 rsETH depeg must appear dated in the realized series"
    assert apr[0]["depth_pct"] < -10.0  # deep, signed-negative
    assert apr[0]["source"] == "realized_backtest_series"
    # every realized episode carries a peak date, trough date, depth, recovery field
    for d in realized:
        assert d["peak_date"] <= d["trough_date"]
        assert d["depth_pct"] < 0.0
        assert "time_to_recover_days" in d


def test_smooth_series_yields_no_fabricated_realized_dd(tmp_path):
    """RED-TEAM: a smoothly-accruing series must show ZERO realized drawdowns — never an invented one."""
    sdir = tmp_path / "smooth"
    sdir.mkdir(parents=True)
    eq = 100_000.0
    start = datetime.date(2025, 1, 1)
    lines = []
    for i in range(400):
        eq *= 1.0002  # pure monotone-up accrual
        d = (start + datetime.timedelta(days=i)).isoformat()
        lines.append(json.dumps({"date": d, "equity_usd": round(eq, 2), "phase": "backtest"}))
    (sdir / "realized_series.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (sdir / "meta.json").write_text(json.dumps(
        {"strategy_id": "smooth", "risk_class": "C", "risk_shape": "funding_flip",
         "headline_apy_pct": 12.0}), encoding="utf-8")
    s = ld.load_strategy("smooth", data_dir=tmp_path)
    contrast = ac.build_strategy_contrast(s, stable_apy_pct=5.0)
    assert contrast["status"] == "OK"
    assert contrast["dated_drawdown_timeline"]["realized_drawdowns"] == []  # NO fabricated DD
    # but the dated stress overlay still surfaces the tail by shape (not hidden)
    assert contrast["dated_drawdown_timeline"]["dated_stress_overlay"], \
        "the dated tail must still be surfaced via the labelled overlay"


def test_overlay_is_labelled_modeled_and_dated(fixture_dir):
    doc = _doc(fixture_dir)
    sd = next(s for s in doc["strategies"] if s["strategy_id"] == "susde_dn")
    overlay = sd["dated_drawdown_timeline"]["dated_stress_overlay"]
    assert overlay
    for o in overlay:
        assert o["source"] == "modeled_stress_overlay"  # never confused with realized
        assert o["depth_pct"] <= 0.0
        assert o["event_date"]  # dated
        assert "NOT a realized" in o["note"] or "NOT a realized series loss" in o["note"]


def test_oct_2025_dated_on_aggressive_absent_on_stable(fixture_dir):
    """SMOKE/RED-TEAM: the Oct-2025 Ethena unwind is dated on the aggressive side, absent on stable."""
    doc = _doc(fixture_dir)
    sd = next(s for s in doc["strategies"] if s["strategy_id"] == "susde_dn")
    overlay = sd["dated_drawdown_timeline"]["dated_stress_overlay"]
    oct_evt = [o for o in overlay if o["window_key"] == "usde_unwind_2025_10"]
    assert oct_evt, "the Oct-2025 USDe unwind must be on the aggressive side, dated"
    assert "2025-10" in oct_evt[0]["event_date"]
    assert oct_evt[0]["depth_pct"] < 0.0
    # the stable book takes ~0 in every window — the Oct-2025 cliff simply does not exist for it
    for w in sd["windows"]:
        assert w["stable"]["max_drawdown_pct"] == 0.0


# ── contrast metrics (the sellable numbers) ─────────────────────────────────────────────────────────
def test_contrast_metrics_complete(fixture_dir):
    doc = _doc(fixture_dir)
    lrt = next(s for s in doc["strategies"] if s["strategy_id"] == "lrt_carry")
    yw = next(w for w in lrt["windows"] if w["window"] == "trailing_12m")
    agg = yw["aggressive"]
    for k in ("total_return_pct", "cagr_pct", "max_drawdown_pct", "worst_month_pct",
              "days_underwater", "vol_pct", "calmar"):
        assert k in agg
    # cost of chasing = the extra max-DD the aggressive book takes vs the steady book
    assert yw["cost_of_chasing_dd_pct"] is not None
    assert yw["cost_of_chasing_dd_pct"] == pytest.approx(
        agg["max_drawdown_pct"] - yw["stable"]["max_drawdown_pct"], abs=1e-6)
    # an aggressive book with a real tail has a positive cost of chasing
    assert yw["cost_of_chasing_dd_pct"] > 0


# ── INSUFFICIENT_DATA honesty ───────────────────────────────────────────────────────────────────────
def test_insufficient_data_no_fake_year(tmp_path):
    sdir = tmp_path / "tiny"
    sdir.mkdir(parents=True)
    (sdir / "realized_series.jsonl").write_text(
        json.dumps({"date": "2026-06-29", "equity_usd": 100000.0, "phase": "forward"}) + "\n",
        encoding="utf-8")
    (sdir / "meta.json").write_text(json.dumps(
        {"strategy_id": "tiny", "risk_class": "C", "risk_shape": "funding_flip"}), encoding="utf-8")
    s = ld.load_strategy("tiny", data_dir=tmp_path)
    contrast = ac.build_strategy_contrast(s, stable_apy_pct=5.0)
    assert contrast["status"] == ac.INSUFFICIENT
    assert contrast["windows"] == []
    assert contrast["dated_drawdown_timeline"]["realized_drawdowns"] == []


# ── determinism + proof hash ────────────────────────────────────────────────────────────────────────
def test_deterministic_and_proof_hashed(fixture_dir):
    d1 = _doc(fixture_dir)
    d2 = _doc(fixture_dir)
    assert d1["proof_hash"] == d2["proof_hash"]
    assert len(d1["proof_hash"]) == 64
    # the hash excludes wall-clock — a different now_iso must not change it
    d3 = ac.build_annual_contrast(data_dir=fixture_dir, stable_apy_pct=5.0, write=False,
                                  now_iso="2030-01-01T00:00:00+00:00", use_fixture_if_empty=False)
    assert d3["proof_hash"] == d1["proof_hash"]


# ── the one-pager ───────────────────────────────────────────────────────────────────────────────────
def test_one_pager_renders_from_data(fixture_dir):
    doc = _doc(fixture_dir)
    md = ac.render_one_pager(doc)
    assert "The Cost of Chasing 15%" in md
    assert "2025-10" in md  # the dated Oct-2025 event surfaces
    assert "rsETH depeg" in md
    # the stable book max-DD ~0 framing must be present
    assert "max-drawdown ~0%" in md or "max-DD ~0" in md
    # the proof hash + source trace
    assert doc["proof_hash"][:16] in md
    assert doc["stable_apy_source"] in md


def test_one_pager_writes(fixture_dir, tmp_path):
    doc = _doc(fixture_dir)
    dest = tmp_path / "ANNUAL_CONTRAST.md"
    out = ac.write_one_pager(doc, doc_path=dest)
    assert out == dest
    assert dest.read_text(encoding="utf-8").startswith("# The Cost of Chasing 15%")


def test_write_artifact_atomic(fixture_dir, tmp_path):
    dest = tmp_path / "annual_contrast.json"
    doc = ac.build_annual_contrast(data_dir=fixture_dir, stable_apy_pct=5.0, write=True,
                                   now_iso=FIXED_NOW, use_fixture_if_empty=False, out_path=dest)
    on_disk = json.loads(dest.read_text(encoding="utf-8"))
    assert on_disk["proof_hash"] == doc["proof_hash"]
    assert on_disk["n_strategies"] == doc["n_strategies"]
