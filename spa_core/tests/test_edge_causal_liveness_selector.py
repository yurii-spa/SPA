# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_causal_liveness_selector.py — registry idea #69 CLS.

Hand-built series only; nothing here reads data/aggressive_lab/ (gitignored, regenerated nightly,
absent in CI). Every pin below is a positive control for one load-bearing claim of the entry — and
wherever a claim could pass for the wrong reason, its refuting half stands beside it.

  • **THE CENSUS IS THE REGISTRY'S OWN, AND THE ONLY DIFFERENCE IS THE WINDOW.** Run over the whole
    sample, `causal_live_books` must equal `ets.live_books` book for book — that identity is what
    makes the audit in (A) a comparison of like with like instead of two different definitions
    disagreeing. Pinned with its refuting half: run over a strict prefix it must be allowed to
    differ, or the window is decorative.

  • **THE CENSUS NEVER READS THE DAYS IT IS USED ON — AND THAT IS A LIMIT, NOT A FEATURE.** A book
    that dies strictly AFTER the fit window is still called LIVE, and the test says so out loud.
    A causal census cannot see a death that has not happened; publishing it as if it could is how
    a hindsight universe gets called honest.

  • **THE DEFLATION IS A FACT ABOUT THE PANEL, NOT ABOUT THIS CODE.** `identity_k` must return a k
    when the dark books sit at the bottom of the mean ranking, and must return None when one of
    them does not. Without the second half, "#69 is #68 at k=6" could be an artifact of the search
    always succeeding — which would make the entry's central claim unfalsifiable.

  • **FAIL-CLOSED ON THE LIVE COUNT, NOT THE BOOK COUNT.** k at or above the number of LIVE books
    is refused even when it is far below the number of books — freezing every investable name is
    an all-cash request wearing a selector's name, and a holed panel makes that easy to reach.

  • **A CENSUS OVER NOTHING IS REFUSED, NOT ANSWERED.** Empty or reversed windows raise; the
    expanding census refuses to reach a verdict before its warm-up, because a share over three
    days is a statement about the calendar and not about the feed.

  • **THE CAP IS A CAP** on every allocation this file produces. A row in the registry that
    silently breached 20 % would be a number RiskPolicy v1.0 forbids, even in an advisory backtest.

  • **THE FLAGS NEVER MOVE.** #69 is a frozen list like #68; if any book's flag changed mid-sample
    the entry would be measuring a state machine and calling it a constant.

  • **DENSITY IS BLIND TO A CONSTANT BOOK** — the sibling degeneracy of #54's dark ones. Pinned
    because the entry rests on it: a literal constant scores maximum liveness.

  • **Read-only, advisory.** No write path at all, no execution import, no re-tuned constants.

stdlib + pytest only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_causal_liveness_selector.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="edge_causal_liveness_selector.py absent")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("edge_causal_liveness_selector_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cls = _load()
ets = cls.ets
stt = cls.stt
ecr = cls.ecr

TOL = 1e-12
K = 2


def panel_of(rets: Dict[str, List[float]]):
    """Axis labels are deliberately NOT dates — nothing under test parses them, and a literal date
    would grow the frozen-date class (.claude/rules/deployment.md) for pure decoration."""
    n = len(next(iter(rets.values())))
    assert all(len(v) == n for v in rets.values()), "ragged fixture"
    return ets.SynthPanel([f"d{i:05d}" for i in range(n)], rets)


def alive(n: int, level: float = 0.001) -> List[float]:
    """A book that prints every day. Values wobble so it is not also a constant book."""
    return [level * (1.0 + 0.1 * (i % 5)) for i in range(n)]


def dies_at(n: int, i_last: int, level: float = 0.001) -> List[float]:
    """Prints every day up to and including `i_last`, then a literal 0.0 for ever after."""
    return [level * (1.0 + 0.1 * (i % 5)) if i <= i_last else 0.0 for i in range(n)]


# ═══════════════════ the census: same definition, different window ═══════════════════
def test_causal_census_over_the_whole_sample_is_the_registry_census():
    """(A) is a like-for-like audit only if the two censuses ARE the same definition."""
    p = panel_of({"a": alive(200), "b": dies_at(200, 40), "c": alive(200), "d": dies_at(200, 150)})
    assert cls.causal_live_books(p, 0, p.n) == ets.live_books(p)


def test_causal_census_over_a_prefix_may_differ_and_here_it_does():
    """The refuting half: if the window changed nothing, the whole idea would be decoration."""
    p = panel_of({"a": alive(200), "b": dies_at(200, 60), "c": alive(200)})
    assert "b" in cls.causal_live_books(p, 0, 100)      # 61 prints / 100 days → still live
    assert "b" not in cls.causal_live_books(p, 0, p.n)  # 61 / 200 → dead over the whole sample
    assert cls.causal_live_books(p, 0, 100) != cls.causal_live_books(p, 0, p.n)


def test_the_census_cannot_see_a_death_that_has_not_happened_yet():
    """The honest LIMIT of (A), pinned rather than hidden: causality is not clairvoyance.

    A book that prints through the whole fit window and dies the day after is LIVE to every
    causal census that exists. Any claim that a causal universe is free of survivorship is a
    claim about the books' death dates, never about the census.
    """
    p = panel_of({"a": alive(200), "b": dies_at(200, 99), "c": alive(200)})
    assert "b" in cls.causal_live_books(p, 0, 100)
    assert "b" not in cls.causal_live_books(p, 100, 200)


def test_density_refuses_an_empty_or_reversed_window_and_an_unknown_book():
    p = panel_of({"a": alive(50), "b": alive(50)})
    with pytest.raises(ValueError):
        cls.density(p, "a", 10, 10)
    with pytest.raises(ValueError):
        cls.density(p, "a", 30, 10)
    with pytest.raises(ValueError):
        cls.density(p, "a", 0, 51)
    with pytest.raises(KeyError):
        cls.density(p, "nobody", 0, 10)


def test_causal_census_refuses_a_threshold_that_is_not_a_share():
    p = panel_of({"a": alive(50), "b": alive(50)})
    with pytest.raises(ValueError):
        cls.causal_live_books(p, 0, 50, min_density=1.5)


# ═══════════════════ census lag: the delay is the definition's, not the book's ═══════════════════
def test_census_lag_measures_the_delay_after_the_last_print():
    """A book that prints daily for 100 days then goes dark is not "dead" on day 101: its
    accumulated share only decays through 0.5 on day 200. The 99-day gap is the number a curator
    would actually live with, and the entry quotes it, so it is pinned."""
    p = panel_of({"a": alive(400), "b": dies_at(400, 99)})
    lag = cls.census_lag(p, min_window=10)
    assert lag["b"]["last_print_i"] == 99
    assert lag["b"]["first_dead_i"] == 200          # 100 prints / 201 days < 0.5, first time
    assert lag["b"]["lag_days"] == 101
    assert lag["a"]["first_dead_i"] is None         # never dead ⇒ no verdict, not a zero
    assert lag["a"]["lag_days"] is None


def test_census_lag_can_be_negative_for_a_book_that_only_ever_trickles():
    """The other branch, and it is not a bug: a book that never clears the threshold is called
    dead while it is still printing. Suppressing that would hide the case the panel actually has."""
    n = 300
    trickle = [0.001 if i % 4 == 0 else 0.0 for i in range(n)]   # density 0.25, prints to the end
    p = panel_of({"a": alive(n), "b": trickle})
    lag = cls.census_lag(p, min_window=10)
    assert lag["b"]["last_print_i"] == n - 4
    assert lag["b"]["first_dead_i"] is not None
    assert lag["b"]["lag_days"] < 0


def test_census_lag_refuses_to_answer_before_its_warm_up():
    """A book that prints once and never again is "dead" on day three to a census with no floor —
    a verdict reached on three days of evidence. The floor does not change WHETHER the verdict
    comes, it changes when it is allowed to count; the pin is that it moves the date."""
    n = 120
    once = [0.001] + [0.0] * (n - 1)
    p = panel_of({"a": alive(n), "b": once})
    assert cls.census_lag(p, min_window=1)["b"]["first_dead_i"] == 2
    assert cls.census_lag(p, min_window=60)["b"]["first_dead_i"] == 59
    with pytest.raises(ValueError):
        cls.census_lag(p, min_window=0)


# ═══════════════════ the selector: #54's gate composed with #68's ranking ═══════════════════
def _holed():
    """Four live books and two dark ones. The dark pair is placed at the TOP of the mean ranking
    on purpose in the second fixture below; here they sit wherever their zeros put them."""
    n = 240
    return panel_of({
        "live_best": [0.0030] * n,
        "live_mid": [0.0020] * n,
        "live_bad": [0.0005] * n,
        "live_worst": [-0.0010] * n,
        "dark_a": dies_at(n, 20, level=0.0010),
        "dark_b": dies_at(n, 30, level=0.0010),
    })


def test_lff_freezes_the_dark_books_plus_the_bottom_k_of_the_live_ones():
    p = _holed()
    assert cls.lff_freeze_set(p, 0, p.n, 2) == {"dark_a", "dark_b", "live_worst", "live_bad"}


def test_lff_halves_can_be_read_apart():
    """`gate_dark=False` keeps the dark books invested — the row that stops #69 being credited
    with #54's gate; `invert` takes the best live books and must be disjoint from the worst."""
    p = _holed()
    assert cls.lff_freeze_set(p, 0, p.n, 2, gate_dark=False) == {"live_worst", "live_bad"}
    top = cls.lff_freeze_set(p, 0, p.n, 2, invert=True)
    assert top == {"dark_a", "dark_b", "live_best", "live_mid"}
    assert not (top - {"dark_a", "dark_b"}) & (cls.lff_freeze_set(p, 0, p.n, 2) - {"dark_a", "dark_b"})


def test_k_zero_is_the_dark_gate_alone_and_nothing_else():
    p = _holed()
    assert cls.lff_freeze_set(p, 0, p.n, 0) == {"dark_a", "dark_b"}


def test_k_is_bounded_by_the_LIVE_count_not_the_book_count():
    """The holed-panel trap: k=4 is comfortably below the six books and would still freeze every
    investable name. Fail-CLOSED, and the pin is that k=3 (one live book left) still passes."""
    p = _holed()
    cls.lff_freeze_set(p, 0, p.n, 3)
    with pytest.raises(ValueError):
        cls.lff_freeze_set(p, 0, p.n, 4)
    with pytest.raises(ValueError):
        cls.lff_freeze_set(p, 0, p.n, -1)


def test_a_fully_dark_panel_is_refused_rather_than_ranked():
    n = 200
    p = panel_of({"x": dies_at(n, 5), "y": dies_at(n, 7)})
    with pytest.raises(ValueError):
        cls.lff_freeze_set(p, 0, n, 1)


def test_flags_from_refuses_a_book_that_is_not_on_the_panel():
    p = _holed()
    with pytest.raises(KeyError):
        cls.flags_from(p, {"ghost"}, p.n)


def test_the_freeze_list_never_moves():
    """#69 is a frozen list like #68. A flag that changed mid-sample would make every "zero
    decisions" claim in the entry false."""
    p = _holed()
    flags = cls.flags_from(p, cls.lff_freeze_set(p, 0, p.n, 2), p.n)
    for b, col in flags.items():
        assert len(set(col)) == 1, f"{b} changed its flag mid-sample"


# ═══════════════════ the deflation: #69's set vs #68's dial ═══════════════════
def test_identity_k_finds_the_dial_when_the_dark_books_sit_at_the_bottom():
    """The shape of the real panel: every dark book ranks below every live book that matters, so
    #69's set is exactly #68's bottom-(dark+k). This is the arithmetic behind the entry's verdict."""
    n = 240
    p = panel_of({
        "live_best": [0.0030] * n,
        "live_mid": [0.0020] * n,
        "live_bad": [0.0005] * n,
        "live_worst": [-0.0010] * n,
        "dark_a": dies_at(n, 20, level=-0.0050),     # dark AND deeply negative on the fit window
        "dark_b": dies_at(n, 30, level=-0.0050),
    })
    assert cls.identity_k(p, 0, p.n, 2) == 4
    assert cls.ffb_freeze_set(p, 0, p.n, 4) == cls.lff_freeze_set(p, 0, p.n, 2)


def test_identity_k_returns_None_when_a_dark_book_ranks_high():
    """THE REFUTING HALF, and the entry stands or falls on it: if the search always succeeded,
    "#69 is #68 at k=6" would be a property of this function rather than of the panel. Here one
    dark book earns well before it dies, so no bottom-k of #68 can ever contain it together with
    the worst live books — and the census selects something the dial cannot reach."""
    n = 240
    p = panel_of({
        "live_best": [0.0030] * n,
        "live_mid": [0.0020] * n,
        "live_bad": [0.0005] * n,
        "live_worst": [-0.0010] * n,
        "dark_rich": dies_at(n, 20, level=0.0500),   # dark, but the richest mean on the panel
        "dark_b": dies_at(n, 30, level=-0.0050),
    })
    assert "dark_rich" in cls.lff_freeze_set(p, 0, p.n, 2)
    assert cls.identity_k(p, 0, p.n, 2) is None


def test_on_an_all_live_panel_LFF_collapses_onto_FFB_weight_for_weight():
    """The arithmetic self-check that the live-only column of the report is (and is only) a
    self-check: with no dark books the gate is empty and the two rules are one rule."""
    n = 200
    p = panel_of({"a": [0.003] * n, "b": [0.002] * n, "c": [0.001] * n,
                  "d": [0.0005] * n, "e": [-0.001] * n, "f": [-0.002] * n})
    assert cls.identity_k(p, 0, n, 2) == 2
    lff = cls.lff_weights(p, 0, n, 2, n)
    ffb = stt.ffb_weights(p, 0, n, 2, n)
    for b in p.books:
        for i in range(n):
            assert abs(lff[b][i] - ffb[b][i]) < TOL


# ═══════════════════ the allocation itself ═══════════════════
def test_every_allocation_respects_the_concentration_cap():
    p = _holed()
    for w in (cls.lff_weights(p, 0, p.n, 2, p.n),
              cls.lff_weights(p, 0, p.n, 2, p.n, invert=True),
              cls.lff_weights(p, 0, p.n, 2, p.n, gate_dark=False),
              cls.dark_only_weights(p, 0, p.n, p.n)):
        nb = len(p.books)
        for b, col in w.items():
            for x in col:
                # `alloc_recycle` works in units where 1.0 is the neutral share of ONE book;
                # the cap is a share of the BOOK, i.e. cap*nb in those units (ecr's convention).
                assert x <= cls.CONC_CAP * nb + 1e-9, f"{b} breached the cap: {x}"


def test_frozen_books_hold_exactly_zero_and_survivors_hold_the_rest():
    p = _holed()
    frozen = cls.lff_freeze_set(p, 0, p.n, 2)
    w = cls.lff_weights(p, 0, p.n, 2, p.n)
    for b in frozen:
        assert all(abs(x) < TOL for x in w[b]), f"{b} was frozen but still carries weight"
    assert any(w[b][0] > 0 for b in p.books if b not in frozen)


# ═══════════════════ the degeneracy density cannot see ═══════════════════
def test_density_scores_a_literal_constant_book_as_maximally_alive():
    """#54 named dark books; this is their sibling. A book that accrues a constant prints every
    day, so the census calls it live, while it carries no risk at all — and a mean-based selector
    spends its k on it. Named by the diagnostic, never ruled on by a threshold."""
    n = 200
    p = panel_of({"a": alive(n), "constant": [0.0002] * n})
    assert "constant" in cls.causal_live_books(p, 0, n)
    d = cls.dispersion_census(p, 0, n)
    assert d["constant"]["density"] == 1.0
    assert d["constant"]["stdev_bp"] < TOL
    assert d["constant"]["distinct"] == 1
    assert d["a"]["stdev_bp"] > d["constant"]["stdev_bp"]


def test_dispersion_census_refuses_a_bad_window():
    p = panel_of({"a": alive(50), "b": alive(50)})
    with pytest.raises(ValueError):
        cls.dispersion_census(p, 20, 20)


# ═══════════════════ scope ═══════════════════
def test_the_module_is_advisory_and_has_no_write_path():
    assert cls.IS_ADVISORY is True
    assert cls.OUTSIDE_RISKPOLICY is True
    src = SCRIPT.read_text(encoding="utf-8")
    assert "LLM_FORBIDDEN" in src
    for forbidden in ('open(', 'atomic_save', 'spa_core.execution', 'os.replace'):
        assert forbidden not in src, f"{forbidden} has no business in a read-only R&D script"


def test_inherited_constants_are_not_re_tuned_here():
    """The entry's comparability with #67/#68 rests on these being the SAME numbers, not similar
    ones. A silent re-tune would make every side-by-side row in the registry a different program."""
    assert cls.REF_K == stt.REF_K
    assert cls.REF_M == stt.REF_M
    assert cls.LOOKBACK == stt.LOOKBACK
    assert cls.CONC_CAP == stt.CONC_CAP
    assert cls.SPLITS == stt.SPLITS
    assert cls.MIN_DENSITY == 0.5           # #54's own threshold
