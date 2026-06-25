"""
spa_core/tests/test_rates_desk.py — Rates-Desk de-risk: scorer + fair-value unit tests.

Pure synthetic, no network. Verifies the deterministic contracts the de-risk relies on:
  - tail score is HIGHER for a depegging/decaying series than a stable one
  - tail score is deterministic (same input → same output)
  - fair-value REFUSEs when the high yield is tail-comp, CARRYs when a genuine spread exists
  - fail-CLOSED behaviour (missing data → max-risk score / REFUSE)
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.strategy_lab.rates_desk import config as C
from spa_core.strategy_lab.rates_desk.fair_value import fair_value
from spa_core.strategy_lab.rates_desk.risk_score import (
    funding_flip_prob,
    score_on_date,
    score_underlying_series,
    trailing_median,
)


def _dates(n: int, start_ord: int = 739000):
    import datetime
    base = datetime.date.fromordinal(start_ord)
    return [(base + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _stable_series(n: int = 120):
    """A tight-peg LST: ratio hugs ~1.0 with tiny symmetric noise."""
    ds = _dates(n)
    return {ds[i]: 1.0 + (0.0005 if i % 2 else -0.0005) for i in range(n)}


def _depegging_series(n: int = 120):
    """A toxic LRT: starts ~1.03 then grinds DOWN ~0.25%/day (sustained one-sided decay)."""
    ds = _dates(n)
    out = {}
    r = 1.03
    for i in range(n):
        r *= (1.0 - 0.0025)  # one-sided downside drift
        out[ds[i]] = r
    return out


# ── tail-score discrimination ─────────────────────────────────────────────────────────────────
def test_tail_score_higher_for_depegging_than_stable():
    stable = score_underlying_series("stable", _stable_series())
    toxic = score_underlying_series("toxic", _depegging_series())
    # compare the typical (last-date, fully-warmed) score
    last_stable = stable[max(stable)].score
    last_toxic = toxic[max(toxic)].score
    assert last_toxic > last_stable
    assert last_toxic >= 0.45      # a sustained depeg breaches the refuse threshold
    assert last_stable < 0.30      # a tight peg stays in the safe band


def test_tail_score_deterministic():
    s1 = score_underlying_series("x", _depegging_series())
    s2 = score_underlying_series("x", _depegging_series())
    assert [s1[d].score for d in sorted(s1)] == [s2[d].score for d in sorted(s2)]


def test_depeg_drawdown_drives_score():
    """A series that drops sharply from a peak scores higher at the bottom than at the peak."""
    ds = _dates(80)
    ser = {ds[i]: 1.05 for i in range(40)}
    for i in range(40, 80):
        ser[ds[i]] = 1.05 - 0.02 * (i - 39)  # steady drawdown
    scores = score_underlying_series("dd", ser)
    assert scores[ds[39]].score < scores[ds[60]].score


def test_failclosed_empty_date():
    """A date with no history is failed-CLOSED at max score (1.0)."""
    ts = score_on_date("y", {}, "2026-01-01")
    assert ts.failed_closed is True
    assert ts.score == 1.0


def test_trailing_median_dampens_spike():
    """A lone 1-day spike is rejected by the trailing median (the false-depeg remedy)."""
    vals = [1.0, 1.0, 1.0, 1.5, 1.0, 1.0]   # one outlier at idx 3
    sm = trailing_median(vals, 3)
    assert sm[3] == 1.0     # median of [1.0,1.0,1.5] = 1.0 — the spike is rejected


def test_funding_flip_prob_counts_negatives():
    f = {"2026-01-01": -0.001, "2026-01-02": 0.001, "2026-01-03": -0.002, "2026-01-04": 0.0}
    p = funding_flip_prob(f, "2026-01-04", window=4)
    assert abs(p - 0.5) < 1e-9   # 2 of 4 negative
    assert funding_flip_prob({}, "2026-01-04", window=4) is None  # no history → None (surfaced)


# ── fair value: CARRY vs REFUSE ─────────────────────────────────────────────────────────────────
def test_fair_value_refuses_tail_comp():
    """High quoted yield but HIGH tail score → the yield is tail-comp → REFUSE."""
    v = fair_value("toxic", "2026-01-01", quoted_implied=0.20, baseline_yield=0.05,
                   tail_score=0.80)
    assert v.classification == "REFUSE"
    assert v.refuse_reason == "tail"


def test_fair_value_carries_genuine_spread():
    """Quoted yield comfortably above fair, LOW tail score → genuine carry → CARRY."""
    v = fair_value("clean", "2026-01-01", quoted_implied=0.08, baseline_yield=0.04,
                   tail_score=0.05)
    assert v.classification == "CARRY"
    assert v.spread_vs_fair > C.COST_BUFFER_APY


def test_fair_value_refuses_no_spread():
    """Low tail and quoted BELOW fair (no harvestable edge after cost) → REFUSE(no_spread).

    With tail≈0 the haircut≈0 so fair≈baseline; a quoted yield at/under baseline leaves no
    spread to harvest. (quoted 0.040, baseline 0.044, tail 0.0 → fair 0.044, spread -0.004.)"""
    v = fair_value("flat", "2026-01-01", quoted_implied=0.040, baseline_yield=0.044,
                   tail_score=0.0)
    assert v.spread_vs_fair <= C.COST_BUFFER_APY
    assert v.classification == "REFUSE"
    assert v.refuse_reason == "no_spread"


def test_fair_value_failclosed_bad_tail():
    """A malformed (out-of-range) tail score is treated as MAX risk → REFUSE."""
    v = fair_value("bad", "2026-01-01", quoted_implied=0.20, baseline_yield=0.05,
                   tail_score=5.0)
    assert v.tail_score == 1.0
    assert v.classification == "REFUSE"


def test_fair_value_deterministic():
    a = fair_value("d", "2026-01-01", 0.10, 0.04, 0.3)
    b = fair_value("d", "2026-01-01", 0.10, 0.04, 0.3)
    assert a == b
