# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_real_panel_ensemble.py (registry ideas #16 + #17).

These lock the properties the honest verdicts depend on:
  • the panel loader is fail-CLOSED (never fabricates a book);
  • perf() metrics are correct on hand-checkable series;
  • the causal signals (trailing drawdown / vol / breadth) use NO same-day / future info;
  • apply_overlay parks in cash exactly on de-risk days;
  • the lead-lag detector actually finds a planted lead and reports lag 0 for a coincident signal;
  • the duty-cap logic exposes (not hides) the degenerate stay-in-cash optimum.

Everything runs on tiny synthetic panels written to tmp — no real data, no network.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "edge_real_panel_ensemble", ROOT / "scripts" / "edge_real_panel_ensemble.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)  # type: ignore[union-attr]


# ── loader ──────────────────────────────────────────────────────────────
# DELIBERATE FIXTURE CHANGE (2026-08-02, card agent-idea16-17-phase-glue-contamination,
# invariant #16 — declared, not silent): _write_book used to emit rows WITHOUT a `phase`
# field, which the real producer never writes (aggressive_lab/fixtures.py stamps
# phase="backtest"/"forward" on every row, and the schema in aggressive_lab/__init__.py
# lists it as load-bearing). The fixture is brought to the producer's live form — STRICTER,
# not weaker. No assertion below is changed; `_write_book` gains an optional forward tail so
# the seam this card is about can be reproduced at all.
def _write_book(d: Path, name: str, start_eq: float, dailies, forward=None, phase="backtest"):
    """Write a book. `forward`, if given, appends phase="forward" rows RE-ANCHORED at $100k —
    the real file layout: one accounting series glued after another in the same file.
    `phase=None` omits the field entirely (a legacy row the producer no longer writes)."""
    sub = d / name
    sub.mkdir(parents=True, exist_ok=True)
    eq = start_eq
    lines = []
    import datetime as _dt
    day = _dt.date(2024, 1, 1)
    tag = "" if phase is None else f', "phase": "{phase}"'
    for i, r in enumerate([0.0] + list(dailies)):
        eq = eq * (1.0 + r) if i else eq
        lines.append(f'{{"date": "{day.isoformat()}", "equity_usd": {eq:.6f}{tag}}}')
        day += _dt.timedelta(days=1)
    for fwd_eq in list(forward or []):
        lines.append(
            f'{{"date": "{day.isoformat()}", "equity_usd": {float(fwd_eq):.6f}, "phase": "forward"}}'
        )
        day += _dt.timedelta(days=1)
    (sub / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


def test_loader_failclosed_drops_short_books(tmp_path):
    _write_book(tmp_path, "good", 100.0, [0.001] * 100)
    _write_book(tmp_path, "tooshort", 100.0, [0.001] * 5)
    panel = mod.load_panel(tmp_path)
    assert "good" in panel
    assert "tooshort" not in panel  # < 60 points → dropped, not fabricated


def test_loader_empty_raises(tmp_path):
    with pytest.raises(RuntimeError):
        mod.load_panel(tmp_path)


def test_common_axis_is_intersection(tmp_path):
    _write_book(tmp_path, "a", 100.0, [0.001] * 80)
    _write_book(tmp_path, "b", 100.0, [0.001] * 80)
    panel = mod.load_panel(tmp_path)
    axis = mod.common_axis(panel)
    assert len(axis) == 80  # 81 equity points → 80 returns, shared


# ── phase discipline (card agent-idea16-17-phase-glue-contamination) ────
# The file glues two accounting series: a phase="backtest" block compounding from $100k, then
# phase="forward" rows of the live paper book RE-ANCHORED at ~$100k. A loader that diffs
# equity_usd without looking at `phase` turns that re-anchor into a one-day return of −31%
# (susde_dn) … +105% (eth_directional). These lock the boundary as CUT, never crossed.
def test_forward_row_is_not_diffed_against_the_backtest_block(tmp_path):
    """The exact shape of the real files: 100 backtest days grown to ~$147k, then ONE forward
    row back at $100k. Phase-blind, the seam reads as ≈−32%; the loader must not see it."""
    _write_book(tmp_path, "susde_like", 100_000.0, [0.004] * 100, forward=[100_000.0])
    panel = mod.load_panel(tmp_path)
    rets = panel["susde_like"]
    assert len(rets) == 100                      # 101 backtest points → 100 returns
    assert min(rets.values()) > 0.0              # every day is the real +0.4%, none is the seam
    assert max(abs(r) for r in rets.values()) < 0.01


def test_glued_loader_really_does_produce_the_artifact(tmp_path):
    """POSITIVE CONTROL — without this the test above could pass on a file with no seam at all.
    The retained phase-blind loader must still read the same seam as a huge one-day move."""
    _write_book(tmp_path, "susde_like", 100_000.0, [0.004] * 100, forward=[100_000.0])
    glued = mod.load_glued_panel(tmp_path)["susde_like"]
    assert min(glued.values()) < -0.30           # the fabricated crash the registry published
    assert len(glued) == 101                     # one MORE return than the clean panel


def test_book_without_phase_field_is_not_assumed_to_be_backtest(tmp_path):
    """Canonical semantics of the producer's own reader (aggressive_lab/loader.py): a missing or
    unknown phase means "forward". Fail-CLOSED — such a book is dropped, never silently used."""
    _write_book(tmp_path, "legacy", 100.0, [0.001] * 100, phase=None)   # no `phase` field at all
    _write_book(tmp_path, "good", 100.0, [0.001] * 100)
    panel = mod.load_panel(tmp_path)
    assert "legacy" not in panel
    assert "good" in panel


def test_empty_after_phase_filter_raises_instead_of_fabricating(tmp_path):
    """A whole panel of forward-only books must refuse, not return an empty/invented panel."""
    _write_book(tmp_path, "fwd_only", 100.0, [0.001] * 100, phase="forward")
    with pytest.raises(RuntimeError):
        mod.load_panel(tmp_path)


def test_unexplained_jump_inside_one_phase_block_is_refused(tmp_path):
    """Residual discontinuity INSIDE the backtest block (a re-base the phase field did not
    mark) is refused, not compounded — fail-CLOSED beyond the phase filter itself."""
    dailies = [0.001] * 60 + [-0.80] + [0.001] * 60
    _write_book(tmp_path, "rebased", 100.0, dailies)
    with pytest.raises(ValueError, match="accounting discontinuity"):
        mod.load_panel(tmp_path)


def test_a_real_but_large_move_below_the_threshold_is_kept(tmp_path):
    """POSITIVE CONTROL for the refusal above: a violent but genuine −40% day must survive, so
    the guard cannot be read as 'clip anything big'."""
    dailies = [0.001] * 60 + [-0.40] + [0.001] * 60
    _write_book(tmp_path, "crashy", 100.0, dailies)
    panel = mod.load_panel(tmp_path)
    # tolerance is the fixture's own %.6f equity rounding, not slack in the guard
    assert min(panel["crashy"].values()) == pytest.approx(-0.40, abs=1e-6)


def test_glue_artifact_reports_both_panels_for_the_same_book(tmp_path):
    """The size of the correction is reported, not asserted — section 0 of the report."""
    _write_book(tmp_path, "susde_like", 100_000.0, [0.004] * 100, forward=[100_000.0])
    art = mod.glue_artifact(tmp_path)["susde_like"]
    assert art["seam_ret"] < -0.30                      # what the old loader read
    assert art["apy_clean"] > art["apy_glued"]          # the artifact suppressed the real APY
    assert art["maxdd_clean"] == pytest.approx(0.0)     # the only "drawdown" WAS the seam
    assert art["maxdd_glued"] < -0.30


# ── metrics ─────────────────────────────────────────────────────────────
def test_perf_flat_zero_returns():
    p = mod.perf([0.0] * 50)
    assert abs(p["apy"]) < 1e-9
    assert p["maxdd"] == 0.0
    assert p["vol"] == 0.0


def test_perf_maxdrawdown_matches_hand_calc():
    # +10%, then -50% (peak 1.1 → 0.55 = -50% dd), then flat
    rets = [0.10, -0.50, 0.0]
    p = mod.perf(rets)
    assert p["maxdd"] == pytest.approx(-0.5, abs=1e-9)


def test_max_drawdown_monotone_up_is_zero():
    eq = mod._equity([0.01] * 30)
    assert mod._max_drawdown(eq) == 0.0


# ── causality (NO look-ahead) ───────────────────────────────────────────
def test_trailing_drawdown_is_causal():
    # dd[i] must reflect returns[:i] only. A crash on day k must NOT show in dd[k].
    rets = [0.0, 0.0, -0.5, 0.0, 0.0]
    dd = mod._trailing_drawdown(rets)
    assert dd[2] == 0.0          # the -50% day itself not yet reflected
    assert dd[3] == pytest.approx(-0.5, abs=1e-9)  # reflected the NEXT day


def test_trailing_vol_is_causal_and_zero_at_start():
    rets = [0.0, 0.0, 0.3, 0.0]
    v = mod._trailing_vol(rets, lookback=10)
    assert v[0] == 0.0 and v[1] == 0.0   # < 2 points of history
    # v[2] uses returns[:2] = [0,0] → zero; the 0.3 spike only affects v[3]
    assert v[2] == 0.0
    assert v[3] > 0.0


def test_breadth_signal_range_and_causal():
    # others take a -40% return at index 2; a causal trailing-DD reflects it at index 3.
    panel = {
        "x": [0.0] * 6,
        "a": [0.0, 0.0, -0.4, 0.0, 0.0, 0.0],
        "b": [0.0, 0.0, -0.4, 0.0, 0.0, 0.0],
    }
    br = mod.breadth_signal(panel, "x", theta_book=0.1)
    assert all(0.0 <= v <= 1.0 for v in br)
    assert br[2] == 0.0            # crash-return day itself not yet in others' trailing dd
    assert br[3] == pytest.approx(1.0, abs=1e-9)  # reflected the NEXT day → both down > 10%


# ── overlay ─────────────────────────────────────────────────────────────
def test_apply_overlay_parks_cash_on_derisk_days():
    rets = [0.05, -0.05, 0.05]
    derisk = [False, True, False]
    out = mod.apply_overlay(rets, derisk, safe_daily=0.0)
    assert out == [0.05, 0.0, 0.05]


def test_apply_overlay_safe_daily_used():
    out = mod.apply_overlay([0.1, 0.1], [True, True], safe_daily=0.0002)
    assert out == [0.0002, 0.0002]


# ── lead-lag detector ───────────────────────────────────────────────────
def test_leadlag_finds_planted_lead():
    # signal that is the drawdown severity shifted EARLIER by 3 days → should report lag≈3
    import random

    rng = random.Random(7)
    sev = [max(0.0, rng.gauss(0, 1)) for _ in range(200)]
    lead = 3
    signal = sev[lead:] + [0.0] * lead   # signal[t] == sev[t+lead] → leads by `lead`
    lag, corr = mod._lead_lag(signal, sev, max_lag=6)
    assert lag == lead
    assert corr > 0.9


def test_leadlag_coincident_reports_zero():
    import random

    rng = random.Random(11)
    sev = [max(0.0, rng.gauss(0, 1)) for _ in range(200)]
    lag, corr = mod._lead_lag(list(sev), sev, max_lag=6)
    assert lag == 0
    assert corr > 0.99


# ── duty-cap degeneracy exposure (the honesty guard) ────────────────────
def test_idea16_exposes_degenerate_stay_in_cash_optimum(tmp_path):
    # Build a target with one big crash + otherwise positive carry, and 9 helper books that
    # are ALWAYS in drawdown → any breadth threshold fires every day (duty→1.0, degenerate).
    _write_book(tmp_path, "susde_dn", 100.0, ([0.001] * 80 + [-0.4] + [0.001] * 80))
    for i in range(9):
        _write_book(tmp_path, f"h{i}", 100.0, [-0.02] + [0.0] * 160)  # perpetual drawdown
    panel = mod.load_panel(tmp_path)
    axis = mod.common_axis(panel)
    res = mod.run_idea16(panel, axis, target="susde_dn", verbose=False)
    br = res["breadth"]
    # the protective (duty-capped) pick must NOT be the ~always-cash optimum
    assert br["duty"] <= 0.50
    # ...and the degenerate uncapped optimum must be recorded with a high duty, so the
    # verdict can honestly flag it rather than pass it off as an edge.
    deg = br["degenerate_uncapped"]
    assert deg["duty"] > 0.50


def test_idea17_runs_and_reports_all_portfolios(tmp_path):
    for nm, base in (("a", 0.0005), ("b", 0.0003), ("c", -0.0001)):
        _write_book(tmp_path, nm, 100.0, [base + (0.01 if i % 40 == 0 else 0.0) for i in range(120)])
    panel = mod.load_panel(tmp_path)
    axis = mod.common_axis(panel)
    res = mod.run_idea17(panel, axis, verbose=False)
    for key in ("equal_weight", "inverse_vol", "inverse_vol_floor", "best_single"):
        assert key in res["oos"]
    assert -1.0 <= res["avg_corr"] <= 1.0


def test_main_smoke_on_real_panel_if_present():
    # If the real panel exists in the repo, main() must run end-to-end and return 0.
    if not (mod.PANEL_DIR).exists() or not list(mod.PANEL_DIR.glob("*/realized_series.jsonl")):
        pytest.skip("real aggressive_lab panel not present in this checkout")
    assert mod.main([]) == 0
