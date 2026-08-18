# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_score_proportional.py — registry ideas #62 SPW / #63 SXD.

Hand-built series only; nothing here reads data/aggressive_lab/ (gitignored, regenerated nightly,
absent in CI). Every pin below is a positive control for one load-bearing claim of the entries:

  • **λ=0 is an IDENTITY, not a lookalike.** `spw_weights` at λ=0 must be the equal-weight panel
    cell for cell, for every form and every cap ≥ 1/N. This is the anchor of the whole λ axis: if
    it drifts, "λ measures the departure from the registry's baseline" stops being true and every
    row of #62 is comparing two different portfolios. Pinned with a mutation control that reddens
    the moment λ moves off zero.

  • **`rank` is magnitude-BLIND and `linear` is not.** #62's entire verdict rests on this pair
    being a controlled comparison, so both halves are asserted: a strictly monotone re-scaling of
    the scores must leave the `rank` weights EXACTLY unchanged and must move the `linear` ones.
    A test that checked only the first would pass on a module that ignored its scores.

  • **The causal side never reads a future return.** Mutating tomorrow's score may not move today's
    weight; mutating today's must. Both halves, for the same reason.

  • **The cap is a cap, capital that will not fit becomes CASH, and nothing is ever negative.**
    A weight map that silently breaches 20 % would put a number in the registry that RiskPolicy
    v1.0 forbids, even in an advisory backtest.

  • **Fail-CLOSED where a cross-section is undefined**: fewer than two rankable books, or a day on
    which every book scores identically, ⇒ equal weight, never a tilt on floating-point dust, and
    never cash (refusing to rank is not a reason to leave a panel we already hold).

  • **#63's two decompositions are IDENTITIES.** excess ≡ share×spread + cov and excess ≡ tilt +
    timing, to floating point, on adversarial inputs — including a rule that goes to cash, one with
    a negative excess, and one that is flat. An identity is the one kind of claim that must never
    hold "approximately".

  • **The bridge to #61 closes exactly.** For the UNCAPPED binary rule the #63 excess over the
    active days must equal `rank_agreement`'s h=1 spread × k/N. This is what makes #61's h=20 zero
    and this family's positive portfolio rows the same measurement rather than a contradiction, and
    it is pinned against the real #61 function, not against a re-implementation of it.

  • **cov is identically zero for the DAILY binary form, and NOT for the published sticky one.**
    This pair is the correction the test-suite forced on the entry before it was written down: the
    tidy claim "every binary rule of this family has share k/N, so cov is structurally zero" is
    true only at M=1. At M=20 a demotion outlives the day that caused it, more than k books are out
    on many days, and the published rule therefore carries a sizing term nobody chose — negative,
    on the live panel. Both halves are asserted, because only the pair distinguishes a structural
    zero from a rule that happens to be flat on this fixture.

  • **Read-only.** The module must contain no write path at all, and no execution import.

stdlib + pytest only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_score_proportional.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="edge_score_proportional.py absent")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("edge_score_proportional_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = _load()
ecr = sp.ecr
xsd = sp.xsd
ets = sp.ets
edh = sp.edh

TOL = 1e-12


def panel_of(rets: Dict[str, List[float]]):
    """Axis labels are deliberately NOT dates — nothing under test parses them, and a literal date
    would grow the frozen-date class (.claude/rules/deployment.md) for pure decoration."""
    n = len(next(iter(rets.values())))
    return ets.SynthPanel([f"d{i:05d}" for i in range(n)], rets)


REGIMES = (29, 37, 53, 71, 83, 97)
NEUTRAL = 1.0 / len(REGIMES)


def wobbly(n: int = 240) -> Dict[str, List[float]]:
    """Six books that take turns leading, in coprime REGIMES rather than day-to-day flicker.

    Regimes are coprime so the cross-sectional order genuinely rotates and every book spends time
    at both ends of the field. A panel with a standing order would let a static tilt masquerade as
    a working rule — which is the very confusion #62 exists to resolve.

    SIX books, not four, and the count is load-bearing: with four the neutral share 0.25 already
    breaches the project's 0.20 cap, so every weight would be pinned at the cap and half these
    tests would pass while measuring nothing. The real panels have 10 and 6 books against that same
    cap, so six is also the honest narrow case. (The first draft of this file used four and the
    λ=0 identity "failed" — the fixture was wrong, and the module gained a real fix from it: the
    neutral fallback is now clipped at the cap instead of breaching it.)
    """
    jit = [0.0001 * (i % 7) for i in range(n)]
    return {chr(ord("a") + j): [0.001 * float((i // p) % 4) + jit[i] for i in range(n)]
            for j, p in enumerate(REGIMES)}


def scores_from(rets: Dict[str, List[float]],
                warmup: int = 0) -> Dict[str, List[Optional[float]]]:
    """A trailing-shaped score object: the book's own return, with a `None` warm-up head."""
    return {b: [None if i < warmup else v[i] for i in range(len(v))] for b, v in rets.items()}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 1. THE ANCHOR — λ = 0 is the equal-weight panel, cell for cell
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("form", ["linear", "rank", "softmax"])
@pytest.mark.parametrize("cap", [None, 0.20, 0.5])
def test_lambda_zero_is_the_equal_weight_panel_exactly(form, cap):
    rets = wobbly()
    p = panel_of(rets)
    w = sp.spw_weights(p, scores_from(rets), 0.0, form, cap)
    for b in p.books:
        for i in range(p.n):
            assert abs(w[b][i] - NEUTRAL) < TOL


@pytest.mark.parametrize("form", ["linear", "rank", "softmax"])
def test_a_cap_tighter_than_equal_weight_puts_the_residue_in_cash_not_in_a_breach(form):
    """The fail-CLOSED path is the one taken when the rule knows least, so it is the last place
    that may print a weight above the project's own concentration limit."""
    rets = wobbly()
    p = panel_of(rets)
    tight = NEUTRAL / 2.0
    w = sp.spw_weights(p, scores_from(rets), 0.0, form, tight)
    for b in p.books:
        for i in range(p.n):
            assert abs(w[b][i] - tight) < TOL
    assert abs(sum(w[b][0] for b in p.books) - 0.5) < TOL


@pytest.mark.parametrize("lam", [0.25, 1.0, -1.0])
def test_moving_lambda_off_zero_breaks_the_identity(lam):
    """POSITIVE CONTROL: the identity above must be capable of failing."""
    rets = wobbly()
    p = panel_of(rets)
    w = sp.spw_weights(p, scores_from(rets), lam, "linear", 0.20)
    assert any(abs(w[b][i] - NEUTRAL) > 1e-6 for b in p.books for i in range(p.n))


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 2. THE CONTROLLED COMPARISON — `rank` sees order only, `linear` sees magnitude
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_rank_form_is_blind_to_magnitude_and_linear_is_not():
    """The pair that #62's verdict rests on, asserted in BOTH directions.

    A strictly increasing, order-preserving distortion of the scores changes every magnitude and no
    ordering. `rank` must be bit-identical afterwards; `linear` must not be. If only the first held,
    "rank is the magnitude-blind twin" would be a comment rather than a property.
    """
    rets = wobbly()
    p = panel_of(rets)
    s = scores_from(rets)
    stretched = {b: [None if v is None else (v ** 3) * 1000.0 + v for v in col]
                 for b, col in s.items()}

    r0 = sp.spw_weights(p, s, 1.0, "rank", 0.20)
    r1 = sp.spw_weights(p, stretched, 1.0, "rank", 0.20)
    assert r0 == r1

    l0 = sp.spw_weights(p, s, 1.0, "linear", 0.20)
    l1 = sp.spw_weights(p, stretched, 1.0, "linear", 0.20)
    assert l0 != l1


def test_the_rank_form_displaces_the_same_capital_every_day():
    """#63's structural claim about `rank`: its share is a constant, so its cov term is exactly 0.

    This is why the entry reads `rank` as "a binary rule with more levels" rather than as sizing on
    conviction — and it is measured here rather than argued.
    """
    rets = wobbly()
    p = panel_of(rets)
    w = sp.spw_weights(p, scores_from(rets), 1.0, "rank", None)
    d = sp.decompose(p, w)
    assert abs(d["share_sd"]) < 1e-9
    assert abs(d["cov_share_spread"]) < 1e-15


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 3. CAUSALITY — tomorrow may not move today
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_tomorrow_cannot_change_today_but_today_can():
    rets = wobbly()
    p = panel_of(rets)
    s = scores_from(rets)
    base = sp.spw_weights(p, s, 1.0, "linear", 0.20)

    later = {b: list(col) for b, col in s.items()}
    later["a"][150] = 99.0
    after = sp.spw_weights(p, later, 1.0, "linear", 0.20)
    assert [after[b][100] for b in p.books] == [base[b][100] for b in p.books]

    now = {b: list(col) for b, col in s.items()}
    now["a"][100] = 99.0
    changed = sp.spw_weights(p, now, 1.0, "linear", 0.20)
    assert [changed[b][100] for b in p.books] != [base[b][100] for b in p.books]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 4. THE CAP, THE FLOOR AND THE CASH
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("lam", [0.5, 1.0, 2.0, 4.0, 16.0])
@pytest.mark.parametrize("form", ["linear", "rank", "softmax"])
def test_no_weight_ever_breaches_the_cap_or_goes_negative(lam, form):
    rets = wobbly()
    p = panel_of(rets)
    w = sp.spw_weights(p, scores_from(rets), lam, form, 0.20)
    for b in p.books:
        for i in range(p.n):
            assert -TOL <= w[b][i] <= 0.20 + 1e-9


@pytest.mark.parametrize("form", ["linear", "rank", "softmax"])
@pytest.mark.parametrize("z", [-6.0, -2.5, -1.0, 0.0, 3.0])
def test_the_shape_function_itself_is_never_negative(form, z):
    """The floor is asserted on φ DIRECTLY, and this test exists because of a surviving mutation.

    Deleting `max(0, ·)` from the shape reddened nothing at the weight level: `_cap_fill` only ever
    considers names with φ > 0, so a negative φ is silently indistinguishable from a zero one. The
    invariant is real and is enforced in two places, so it is pinned where it is STATED — otherwise
    the second line of defence quietly becomes the only one, and nobody finds out until the day the
    filter is refactored.
    """
    assert sp._shape(z, 4.0, form) >= 0.0
    assert sp._shape(z, -4.0, form) >= 0.0


@pytest.mark.parametrize("lam", [0.0, 1.0, 4.0])
def test_the_book_never_sums_above_one(lam):
    rets = wobbly()
    p = panel_of(rets)
    w = sp.spw_weights(p, scores_from(rets), lam, "linear", 0.20)
    for i in range(p.n):
        assert sum(w[b][i] for b in p.books) <= 1.0 + 1e-9


def test_capital_that_will_not_fit_inside_the_cap_becomes_cash():
    """A tight cap must leave the residue UNINVESTED, never redistributed into a silent breach."""
    rets = wobbly()
    p = panel_of(rets)
    w = sp.spw_weights(p, scores_from(rets), 4.0, "linear", 0.15)
    deployed = [sum(w[b][i] for b in p.books) for i in range(p.n)]
    assert min(deployed) < 1.0 - 1e-9
    assert max(deployed) <= 1.0 + 1e-9


def test_phi_equal_to_one_reproduces_the_registry_waterfill_exactly():
    """`_cap_fill` generalises `ecr._waterfill` from equal shares to proportional ones — so with a
    flat φ the two must agree cell for cell, or the generalisation has changed the baseline."""
    phi = {b: 1.0 for b in ("a", "b", "c", "d")}
    mine = sp._cap_fill(phi, 1.0, 0.30)
    theirs = ecr._waterfill(sorted(phi), 0.30)
    assert sorted(mine) == sorted(theirs)
    for b in theirs:
        assert abs(mine[b] - theirs[b]) < TOL


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 5. FAIL-CLOSED WHERE THERE IS NO CROSS-SECTION
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_a_day_with_no_dispersion_is_held_at_equal_weight():
    rets = {b: [0.001] * 60 for b in ("a", "b", "c")}
    p = panel_of(rets)
    flat = {b: [0.5] * 60 for b in p.books}          # every book identical, every day
    w = sp.spw_weights(p, flat, 3.0, "linear", 0.40)
    for b in p.books:
        for i in range(p.n):
            assert abs(w[b][i] - 1.0 / 3.0) < TOL


def test_fewer_than_two_rankable_books_is_held_at_equal_weight():
    rets = {b: [0.001] * 40 for b in ("a", "b", "c")}
    p = panel_of(rets)
    s: Dict[str, List[Optional[float]]] = {"a": [1.0] * 40, "b": [None] * 40, "c": [None] * 40}
    w = sp.spw_weights(p, s, 3.0, "linear", 0.40)
    for b in p.books:
        for i in range(p.n):
            assert abs(w[b][i] - 1.0 / 3.0) < TOL


def test_an_unmeasured_book_keeps_the_neutral_share_and_is_not_demoted_for_being_unmeasured():
    """#40's rule, kept: an unmeasured drift is not a low drift. The warm-up must therefore look
    exactly like the equal-weight panel — otherwise SPW and the binary rows are not comparable on
    the first L days and every table silently mixes two different warm-ups."""
    rets = wobbly(120)
    p = panel_of(rets)
    s = scores_from(rets, warmup=60)
    w = sp.spw_weights(p, s, 2.0, "linear", 0.40)
    for b in p.books:
        for i in range(60):
            assert abs(w[b][i] - NEUTRAL) < TOL
    assert any(abs(w[b][100] - NEUTRAL) > 1e-6 for b in p.books)


@pytest.mark.parametrize("kwargs", [
    {"lam": float("inf"), "form": "linear"},
    {"lam": float("nan"), "form": "linear"},
    {"lam": 1.0, "form": "sigmoid"},
])
def test_meaningless_settings_are_refused(kwargs):
    rets = wobbly(60)
    p = panel_of(rets)
    with pytest.raises(ValueError):
        sp.spw_weights(p, scores_from(rets), kwargs["lam"], kwargs["form"], 0.20)


def test_a_zero_cap_is_refused():
    rets = wobbly(60)
    p = panel_of(rets)
    with pytest.raises(ValueError):
        sp.spw_weights(p, scores_from(rets), 1.0, "linear", 0.0)


def test_the_anti_rule_really_inverts_the_tilt():
    """λ<0 is a CONTROL and must actually be the mirror: the book the rule overweights must be the
    one the anti-rule underweights. A control that quietly agreed with the rule would make every
    'the ranking carries information' row unfalsifiable."""
    rets = wobbly()
    p = panel_of(rets)
    s = scores_from(rets)
    pro = sp.spw_weights(p, s, 1.0, "linear", None)
    anti = sp.spw_weights(p, s, -1.0, "linear", None)
    i = 100
    best = max(p.books, key=lambda b: s[b][i])
    worst = min(p.books, key=lambda b: s[b][i])
    assert pro[best][i] > pro[worst][i]
    assert anti[best][i] < anti[worst][i]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 6. #63 — THE IDENTITIES
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _adversarial_weight_maps(p):
    """Weight maps chosen to break a decomposition that only works on well-behaved input."""
    s = scores_from({b: p.rets[b] for b in p.books})
    return {
        "equal (flat, zero excess)": {b: [NEUTRAL] * p.n for b in p.books},
        "spw linear": sp.spw_weights(p, s, 1.0, "linear", 0.20),
        "spw anti (negative excess)": sp.spw_weights(p, s, -1.0, "linear", 0.20),
        "binary uncapped": sp.binary_weights(p, s, 1, 20, None),
        "binary capped to cash": sp.binary_weights(p, s, 1, 20, 0.20),
        "half in cash": {b: [NEUTRAL / 2.0] * p.n for b in p.books},
    }


@pytest.mark.parametrize("name", list(_adversarial_weight_maps(panel_of(wobbly()))))
def test_both_decompositions_are_exact_identities(name):
    p = panel_of(wobbly())
    w = _adversarial_weight_maps(p)[name]
    d = sp.decompose(p, w)
    assert abs(d["resid_1"]) < 1e-15
    assert abs(d["resid_2"]) < 1e-15


def test_the_excess_is_the_portfolio_minus_equal_weight_and_nothing_else():
    """The quantity being decomposed is pinned against a direct computation, so a future change to
    `excess_path` cannot quietly redefine what the three terms add up to."""
    p = panel_of(wobbly())
    w = sp.spw_weights(p, scores_from({b: p.rets[b] for b in p.books}), 1.0, "linear", 0.20)
    direct = []
    for i in range(p.n):
        pf = sum(w[b][i] * p.rets[b][i] for b in p.books)
        eq = sum(p.rets[b][i] for b in p.books) / len(p.books)
        direct.append(pf - eq)
    got = sp.excess_path(p, w)
    for x, y in zip(direct, got):
        assert abs(x - y) < 1e-15


def test_a_flat_allocation_has_zero_excess_zero_share_and_no_undefined_spread():
    """The degenerate case that a ratio decomposition can only get wrong once: share = 0 everywhere.
    The spread must not be reported as 0 (it is undefined), and the identity must still close."""
    p = panel_of(wobbly())
    d = sp.decompose(p, {b: [NEUTRAL] * p.n for b in p.books})
    assert abs(d["excess_mean"]) < 1e-15
    assert d["active_days"] == 0.0
    assert abs(d["resid_1"]) < 1e-15


def test_cov_is_identically_zero_for_the_daily_binary_form():
    """#63's claim about the DAILY binary form: exactly k books are out every day, so the share is
    the constant k/N and the sizing term is structurally absent."""
    p = panel_of(wobbly())
    s = scores_from({b: p.rets[b] for b in p.books})
    d = sp.decompose(p, sp.binary_weights(p, s, 1, 1, None))
    assert abs(d["share_mean"] - 1.0 / len(p.books)) < 1e-12
    assert abs(d["share_sd"]) < 1e-12
    assert abs(d["cov_share_spread"]) < 1e-15


def test_the_published_sticky_form_does_NOT_have_a_constant_share():
    """The correction this test-suite forced on the entry before it was written down.

    With M>1 a demotion outlives the day that caused it, so on many days MORE than k books are out
    and the share is not k/N at all. The published rule therefore carries a sizing term nobody
    chose — and #63 measures it as negative on the live panel. Had this test not existed, the entry
    would have shipped the tidier and false claim "cov is identically zero for every binary rule of
    this family".
    """
    p = panel_of(wobbly())
    s = scores_from({b: p.rets[b] for b in p.books})
    d = sp.decompose(p, sp.binary_weights(p, s, 1, 20, None))
    assert d["share_sd"] > 1e-6
    assert abs(d["cov_share_spread"]) > 1e-12


def test_the_bridge_to_61_is_an_identity_at_h_equals_one():
    """The load-bearing result of #63: for the UNCAPPED binary rule the portfolio excess over the
    active days IS #61's h=1 forward spread × k/N.

    Pinned against `edge_decision_hold.rank_agreement` itself — the actual #61 function — because a
    re-implementation of the null would make this a test of my own arithmetic instead of a bridge
    between two entries.
    """
    rets = wobbly(300)
    p = panel_of(rets)
    k = 1
    s = xsd.drift_scores(p.rets, lookback=20)
    w = ecr.alloc_recycle(p.books, xsd.rank_demotion_flags(s, k, 1), p.n, cap=None)
    d = sp.decompose(p, w)
    ra = edh.rank_agreement(p, k, 20, 1, "drift")
    predicted = ra["spread_bp"] * 1e-4 * k / len(p.books)
    assert abs(d["excess_live_mean"] - predicted) < 1e-12


def test_the_bridge_does_not_close_at_a_horizon_the_portfolio_never_consumes():
    """POSITIVE CONTROL for the test above: the identity is about h=1 SPECIFICALLY.

    Without this, "the bridge closes" could be true of a module that returned the same number for
    every horizon, and the entry's whole reading of #61's h=20 zero would rest on nothing.
    """
    rets = wobbly(300)
    p = panel_of(rets)
    k = 1
    s = xsd.drift_scores(p.rets, lookback=20)
    w = ecr.alloc_recycle(p.books, xsd.rank_demotion_flags(s, k, 1), p.n, cap=None)
    d = sp.decompose(p, w)
    far = edh.rank_agreement(p, k, 20, 20, "drift")
    assert abs(d["excess_live_mean"] - far["spread_bp"] * 1e-4 * k / len(p.books)) > 1e-9


def test_the_static_twin_of_a_weight_map_has_no_timing_left():
    """`tilt` is what the twin holds; a twin's own timing term must therefore be exactly zero."""
    p = panel_of(wobbly())
    w = sp.spw_weights(p, scores_from({b: p.rets[b] for b in p.books}), 1.0, "linear", 0.20)
    twin = ecr.alloc_static_matched(w)
    d_twin = sp.decompose(p, twin)
    d_real = sp.decompose(p, w)
    assert abs(d_twin["timing_mean"]) < 1e-15
    assert abs(d_twin["tilt_mean"] - d_real["tilt_mean"]) < 1e-15


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 7. THE CONTROLS ARE CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_permutation_preserves_deployment_and_turnover_and_destroys_book_identity():
    p = panel_of(wobbly())
    w = sp.spw_weights(p, scores_from({b: p.rets[b] for b in p.books}), 1.0, "linear", 0.20)
    perm = sp.permuted_weights(w, p.books, seed=3)
    real_m = ecr.portfolio_metrics(p, w)
    perm_m = ecr.portfolio_metrics(p, perm)
    assert abs(real_m["turnover_yr"] - perm_m["turnover_yr"]) < 1e-9
    assert abs(real_m["deployed"] - perm_m["deployed"]) < 1e-12
    assert any(perm[b] != w[b] for b in p.books)


def test_rotation_preserves_every_path_as_a_multiset_and_only_moves_it_in_time():
    p = panel_of(wobbly())
    w = sp.spw_weights(p, scores_from({b: p.rets[b] for b in p.books}), 1.0, "linear", 0.20)
    sh = sp.shifted_weights(w, p.books, 30)
    for b in p.books:
        assert sorted(sh[b]) == sorted(w[b])
        assert sh[b] != w[b]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 8. SCOPE — advisory, read-only, no execution import
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_module_declares_itself_advisory_and_outside_riskpolicy():
    assert sp.IS_ADVISORY is True
    assert sp.OUTSIDE_RISKPOLICY is True


def test_the_file_contains_no_write_path_at_all():
    src = SCRIPT.read_text()
    for forbidden in ("open(", "write_text", "os.replace", "atomic_save", "mkdir", "json.dump"):
        assert forbidden not in src, f"{forbidden} — this file must stay read-only"


def test_it_imports_no_execution_code():
    src = SCRIPT.read_text()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "execution" not in stripped, f"execution import: {stripped}"


def test_the_look_ahead_rows_are_declared_as_look_ahead():
    """The only harm a read-only research file can do is to be quoted wrongly, so the label that
    prevents it is part of the artefact and is pinned like any other behaviour."""
    src = SCRIPT.read_text()
    assert src.count("[LOOK-AHEAD]") >= 3
    assert "never a rule" in src or "never rules" in src
