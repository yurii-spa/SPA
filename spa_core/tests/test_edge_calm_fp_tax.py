# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_calm_fp_tax.py (registry ideas #32 CFPT and #33 RGVD).

These lock the properties the two verdicts depend on:
  • the phase glue is CUT, never crossed — the appended forward row (a different accounting
    series re-anchored at ~$100k) must not become a −31%/−84%/+105% "return"; that artifact
    is the whole reason the #32 numbers differ from the ones ideas #16/#17 published;
  • an unexplained same-block jump is REFUSED, not compounded (fail-CLOSED);
  • every signal family is CAUSAL: changing the return of day i can never change the
    exposure chosen for day i — this is exactly the look-ahead bias idea #28 documented,
    and #32's whole result would be an artifact if any family leaked it;
  • the FP/TP accounting prices the CUT fraction, so a fractional-Kelly path and a binary
    gate are measured on the same scale (otherwise continuous and binary families are not
    comparable and the leaderboard is meaningless);
  • Kelly sizing fails CLOSED on an unmeasurable variance (holds the baseline, never levers);
  • RGVD #33 fires only in calm and its control fires only in drawdown — the two halves of
    #32's mechanism split must not overlap, or the control proves nothing.

Everything runs on hand-checkable synthetic series — no repo data, no network.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "edge_calm_fp_tax", ROOT / "scripts" / "edge_calm_fp_tax.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)  # type: ignore[union-attr]


def _row(date: str, eq: float, phase: str = "backtest") -> dict:
    return {"date": date, "equity_usd": eq, "phase": phase}


# ── the phase glue: cut the boundary, never diff across it ───────────────────────────────────────
def test_backtest_block_drops_the_forward_reanchor():
    rows = [_row("2024-01-01", 100_000.0), _row("2024-01-02", 147_330.0),
            _row("2024-01-03", 101_079.0, phase="forward")]
    kept = mod.backtest_block(rows)
    assert [r["date"] for r in kept] == ["2024-01-01", "2024-01-02"]


def test_forward_reanchor_never_becomes_a_return():
    """The exact susde_dn shape: 147330 → 101079 across the phase boundary = −31%."""
    rows = [_row("2024-01-01", 100_000.0), _row("2024-01-02", 147_330.0),
            _row("2024-01-03", 101_079.0, phase="forward")]
    _, rets = mod._returns(mod.backtest_block(rows), "susde_dn")
    assert len(rets) == 1
    assert all(r > -0.30 for r in rets)          # the fabricated −31% is absent
    assert math.isclose(rets[0], 0.4733, abs_tol=1e-4)


def test_phase_blind_diff_would_have_produced_the_artifact():
    """Positive control: without the phase cut the same rows DO yield the −31% day."""
    rows = [_row("2024-01-01", 100_000.0), _row("2024-01-02", 147_330.0),
            _row("2024-01-03", 101_079.0, phase="forward")]
    eq = [r["equity_usd"] for r in rows]
    naive = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq))]
    assert min(naive) < -0.30


def test_unexplained_same_block_jump_is_refused():
    rows = [_row("2024-01-01", 100_000.0), _row("2024-01-02", 40_000.0)]   # −60% in-block
    with pytest.raises(ValueError, match="refusing"):
        mod._returns(rows, "book")


def test_jump_just_under_the_refusal_threshold_is_kept():
    rows = [_row("2024-01-01", 100_000.0), _row("2024-01-02", 51_000.0)]   # −49% < 50%
    _, rets = mod._returns(rows, "book")
    assert math.isclose(rets[0], -0.49, abs_tol=1e-9)


# ── causality: day i's own return can never move day i's exposure ────────────────────────────────
CAUSAL_FAMILIES = [
    ("dd#9", lambda r: mod._binary(mod.sig_dd(r, 0.02))),
    ("vol#1", lambda r: mod._binary(mod.sig_vol(r, 2.0))),
    ("kods#15-gate", lambda r: mod._binary(mod.sig_kods(r, 10))),
    ("kelly#15-frac", lambda r: mod.kelly_weights(r, 10, 1.0)),
    ("ecdr#23", lambda r: mod._binary(mod.sig_ecdr(r, 5, 20))),
    ("csd#28", lambda r: mod._binary(mod.sig_csd(r, 10, 0.0001))),
    ("rgvd#33", lambda r: mod._binary(mod.sig_rgvd(r, 2.0))),
    ("rgvd#33-control", lambda r: mod._binary(mod.sig_rgvd_inverse(r, 2.0))),
]


@pytest.mark.parametrize("name,fn", CAUSAL_FAMILIES, ids=[n for n, _ in CAUSAL_FAMILIES])
def test_family_is_causal_on_the_acted_day(name, fn):
    """Detonate day 60 by −40% and the exposure CHOSEN for day 60 must not move."""
    base = [0.001] * 120
    hit = list(base)
    hit[60] = -0.40
    assert fn(base)[60] == fn(hit)[60], f"{name} leaks day-i information into day-i sizing"


def _noisy_base(n: int = 200) -> list:
    """A calm-but-noisy series: small alternating moves, so trailing vol is small yet > 0.

    A constant series cannot exercise the vol families at all (their causal baseline is the
    expanding median of trailing vol, which stays 0), so the controls below need this.
    """
    return [0.002 if i % 2 == 0 else -0.0015 for i in range(n)]


@pytest.mark.parametrize("name,fn", CAUSAL_FAMILIES, ids=[n for n, _ in CAUSAL_FAMILIES])
def test_family_reacts_on_the_day_after(name, fn):
    """Negative control for the causality test: the shock must still be SEEN, one day later.

    Without this, a family that ignores its input entirely would pass the causality test.

    Two shocks, because the families key off different states: a +40% day spikes volatility
    while leaving the book at a new peak (the only thing a calm-gated family such as RGVD #33
    can ever fire on), a −40% day digs the drawdown the dd-gated families need.
    """
    base = _noisy_base()
    hit = list(base)
    hit[60] = 0.40
    hit[90] = -0.40
    assert fn(base)[61:] != fn(hit)[61:], f"{name} never reacts to the shock at all"


def test_exposure_is_bounded_to_zero_one():
    rets = [0.02, -0.03, 0.01, 0.05, -0.02] * 30
    for _, fn in CAUSAL_FAMILIES:
        assert all(0.0 <= w <= 1.0 for w in fn(rets))


# ── trailing state excludes today ────────────────────────────────────────────────────────────────
def test_trailing_drawdown_excludes_today():
    dd = mod.trailing_drawdown([-0.5, 0.0])
    assert dd[0] == 0.0                       # nothing has happened yet on day 0
    assert math.isclose(dd[1], -0.5, abs_tol=1e-12)


def test_trailing_vol_and_mean_exclude_today():
    r = [0.0, 0.0, 0.0, 1.0, 0.0]
    assert mod.trailing_vol(r, 3)[3] == 0.0   # the 1.0 on day 3 is not in day 3's window
    assert mod.trailing_vol(r, 3)[4] > 0.0
    assert mod.trailing_mean(r, 3)[3] == 0.0


def test_expanding_median_is_causal_and_warms_up():
    vals = [1.0, 2.0, 3.0, 4.0]
    med = mod.expanding_median(vals, warmup=2)
    assert med[0] == 0.0 and med[1] == 0.0    # refuses to speak before warmup
    assert med[2] == 1.5                      # median of [1, 2] — day 2 excluded


# ── Kelly sizing ─────────────────────────────────────────────────────────────────────────────────
def test_kelly_fails_closed_on_zero_variance():
    """σ² = 0 is unmeasurable, not infinitely attractive: hold the baseline, never lever."""
    flat = [0.001] * 60
    w = mod.kelly_weights(flat, 10, 1.0, w_max=1.0)
    assert all(x == 1.0 for x in w)


def test_kelly_cuts_exposure_when_trailing_mean_is_below_rf():
    rets = [0.004, -0.006] * 40                # noisy, mean ≈ −0.001/day, well under r_f
    w = mod.kelly_weights(rets, 10, 1.0)
    assert w[50] == 0.0


def test_kelly_alpha_scales_exposure_on_real_variance():
    """The knob #15 could not test on the fixture: with σ² > 0, α must actually matter."""
    rets = [0.01, 0.02, -0.005, 0.015, -0.01] * 24
    lo = mod.kelly_weights(rets, 10, 0.001)
    hi = mod.kelly_weights(rets, 10, 1.0)
    assert sum(lo) < sum(hi)


# ── FP/TP accounting ─────────────────────────────────────────────────────────────────────────────
def test_evaluate_labels_a_derisk_day_by_what_actually_followed():
    #        day    0     1     2      3      4     5     6     7
    rets = [0.01, 0.01, 0.01, -0.05, -0.05, 0.01, 0.01, 0.01]
    # day 2 sits in front of the crash: (1.01 × 0.95) − 1 = −4.05% ⇒ TRUE positive
    assert mod.forward_return(rets, 2, 2) < 0
    m_tp = mod.evaluate(rets, mod._binary([i == 2 for i in range(8)]), horizon=2)
    assert (m_tp["tp"], m_tp["fp"]) == (1.0, 0.0)
    assert math.isclose(m_tp["avoided_bp_yr"], -rets[2] * (365.0 / 8) * mod.BP, rel_tol=1e-9)

    # day 0 sits in front of two up-days ⇒ FALSE positive, and its carry is the tax
    assert mod.forward_return(rets, 0, 2) > 0
    m_fp = mod.evaluate(rets, mod._binary([i == 0 for i in range(8)]), horizon=2)
    assert (m_fp["tp"], m_fp["fp"]) == (0.0, 1.0)
    assert math.isclose(m_fp["tax_bp_yr"], rets[0] * (365.0 / 8) * mod.BP, rel_tol=1e-9)
    assert m_fp["precision"] == 0.0


def test_forward_return_is_none_past_the_end():
    assert mod.forward_return([0.01, 0.01], 1, 5) is None
    assert math.isclose(mod.forward_return([0.1, 0.1], 0, 2), 0.21, abs_tol=1e-12)


def test_evaluate_prices_the_cut_fraction_for_continuous_weights():
    """Half-cut exposure must hand back exactly half the carry a full cut would."""
    rets = [0.01] * 40
    full = mod.evaluate(rets, [0.0] * 40, horizon=5)
    half = mod.evaluate(rets, [0.5] * 40, horizon=5)
    assert math.isclose(half["tax_bp_yr"], full["tax_bp_yr"] / 2.0, rel_tol=1e-9)


def test_evaluate_overlay_matches_weighted_returns():
    rets = [0.01, -0.02, 0.03, 0.00, 0.01] * 20
    w = [0.0 if i % 3 == 0 else 1.0 for i in range(len(rets))]
    m = mod.evaluate(rets, w, horizon=5)
    expect = mod.perf([w[i] * rets[i] for i in range(len(rets))])
    assert math.isclose(m["ov_calmar"], expect["calmar"], rel_tol=1e-12)


def test_full_exposure_is_a_no_op():
    rets = [0.01, -0.02, 0.03] * 30
    m = mod.evaluate(rets, [1.0] * len(rets), horizon=5)
    assert m["duty"] == 0.0
    assert m["tax_bp_yr"] == 0.0 and m["avoided_bp_yr"] == 0.0
    assert math.isclose(m["ov_calmar"], m["raw_calmar"], rel_tol=1e-12)


def test_calm_tax_counts_only_calm_days():
    """A signal that fires only deep inside a drawdown contributes ZERO calm tax."""
    rets = [-0.05] * 10 + [0.01] * 30
    w = mod._binary(mod.sig_dd(rets, 0.02))
    m = mod.evaluate(rets, w, horizon=5)
    assert m["duty"] > 0.0
    assert m["calm_tax_bp_yr"] == 0.0


# ── idea #33: the two halves must not overlap ────────────────────────────────────────────────────
def test_rgvd_fires_only_in_calm_and_its_control_only_in_drawdown():
    # calm-but-noisy for 120 days, then a sustained vol spike that also digs a drawdown
    rets = _noisy_base(120) + [0.05, -0.07, 0.04, -0.06] * 20
    dd = mod.trailing_drawdown(rets)
    calm_only = mod.sig_rgvd(rets, 1.5)
    dd_only = mod.sig_rgvd_inverse(rets, 1.5)
    assert any(calm_only) and any(dd_only)
    for i in range(len(rets)):
        assert not (calm_only[i] and dd_only[i])            # disjoint by construction
        if calm_only[i]:
            assert dd[i] > -mod.CALM_DD
        if dd_only[i]:
            assert dd[i] <= -mod.CALM_DD


def test_rgvd_halves_reconstruct_the_plain_vol_signal():
    """calm-half ∪ drawdown-half == plain vol#1 — the split loses no firing day."""
    # calm-but-noisy for 120 days, then a sustained vol spike that also digs a drawdown
    rets = _noisy_base(120) + [0.05, -0.07, 0.04, -0.06] * 20
    plain = mod.sig_vol(rets, 1.5)
    union = [a or b for a, b in zip(mod.sig_rgvd(rets, 1.5), mod.sig_rgvd_inverse(rets, 1.5))]
    assert plain == union


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────
def test_max_drawdown_and_calmar():
    eq = mod.equity_path([0.0, -0.20, 0.10])
    assert math.isclose(mod.max_drawdown(eq), -0.20, abs_tol=1e-12)
    p = mod.perf([0.001] * 365)
    assert p["maxdd"] == 0.0 and p["calmar"] == float("inf")


def test_perf_annualises_on_days():
    p = mod.perf([0.0] * 365)
    assert math.isclose(p["apy"], 0.0, abs_tol=1e-12)
    p2 = mod.perf([0.01] * 365)
    assert math.isclose(p2["apy"], 1.01 ** 365 - 1, rel_tol=1e-9)
