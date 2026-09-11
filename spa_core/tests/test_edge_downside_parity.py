"""
spa_core/tests/test_edge_downside_parity.py

Structural tests for registry ideas #105 (DSP — Downside-Semideviation Parity) and
#106 (TDC — Tail-Coincidence Discount), `scripts/edge_downside_parity.py`.

EVERY test here replays a defect that this module actually had during the cycle that wrote it,
or a control the verdict rests on. None of them asserts a published APY/Calmar number: the
aggressive_lab books are regenerated, so a golden number would be a time bomb of exactly the
kind `.claude/rules/deployment.md` describes. The registry entry carries the numbers and names
the panel snapshot they belong to; these tests carry the properties.

  1.  The degeneracy is in the DOWNSIDE denominator, not in volatility. The first version of
      control C3 looked for a zero-VOLATILITY book, found none (points_farm's daily sd is
      2.7e-08, not 0.0), and declared its own exclusion rule untested. The measure that IS
      exactly zero on that book is the semideviation.
  2.  Universe selection excludes by a NAMED clause, and each clause is exercised.
  3.  WARM-UP ALIGNMENT — the load-bearing one. Without a pinned warm-up, a 20-day scheme was
      scored over 40 more days than a 60-day scheme, and the extra days read as skill: the
      unaligned run reported DSP at +4.23 pp over equal weight, the aligned one at +0.54 pp.
      Four fifths of the headline was the misalignment.
  4.  Causality: the same-bar mutation must MOVE the result, or "strictly causal" is a claim
      no control can falsify.
  5.  The placebo's identity permutation must reproduce the unpermuted run EXACTLY, or the
      null it builds is not a null of the thing measured.
  6.  apply_cap reaches a fixed point, respects the cap, and conserves the budget.
  7.  Selection never ranks on an infinite Calmar (no drawdown is not a score).
  8.  #106's estimator resolution is k+1 values, and at the default grid point that is THREE.
  9.  DSP and IVOL are not the same function on data where the semidev/vol ratio varies —
      the twin #30 found on its synthetic fixture must not be assumed here.
 10.  Controls that cannot be measured REFUSE; they never share an exit with "measured, fine".

IS_ADVISORY=True. OUTSIDE_RISKPOLICY=True. LLM_FORBIDDEN. stdlib-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.edge_downside_parity import (  # noqa: E402
    CAP_GRID,
    LOOKBACK_GRID,
    RISK_FLOOR,
    WARMUP,
    apply_cap,
    coincidence,
    make_tail_coincidence,
    metrics,
    rankable,
    run_scheme,
    section0_controls,
    section1_universe,
    semideviation,
    stdev,
    w_downside_parity,
    w_equal,
    w_inverse_vol,
)


# ── a deterministic synthetic panel; no live data/, no network, no clock ──────────────────
def _panel():
    """Four books with deliberately different shapes, and one with no downside at all.

    `drifter` never falls — it is the points_farm/lp_eth_stable shape, the one that makes an
    inverse-downside weight a statement about the floor rather than about the book.
    """
    n = 240
    books = {}
    books["choppy"] = [0.004 if i % 2 else -0.003 for i in range(n)]
    books["upvol"] = [0.02 if i % 7 == 0 else (-0.001 if i % 5 == 0 else 0.0009)
                      for i in range(n)]
    books["quiet"] = [(-0.0004 if i % 31 == 0 else 0.0006) for i in range(n)]
    # MOVES but never falls: stdev > 0 while semideviation ≡ 0. A constant series would make
    # the two measures agree, and a control that confuses them would survive the battery.
    books["drifter"] = [0.0002 if i % 3 else 0.0006 for i in range(n)]
    return books


def _marked_books():
    p = _panel()
    return p, ["choppy", "upvol", "quiet"]


def _fake_panel_dict(books):
    """{book: {date: ret}} in the shape section1_universe expects."""
    dates = [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(len(next(iter(books.values()))))]
    return {b: dict(zip(dates, r)) for b, r in books.items()}, dates


# ── 1. the degeneracy lives in the downside denominator ───────────────────────────────────
def test_downside_denominator_is_exactly_zero_where_volatility_is_not():
    books = _panel()
    assert semideviation(books["drifter"]) == 0.0
    assert stdev(books["drifter"]) > 0.0           # it moves; it just never falls
    assert stdev([0.0002] * 10) == 0.0             # only a CONSTANT series is zero-vol
    never_falls = [0.001, 0.003, 0.0005, 0.002, 0.0001]
    assert semideviation(never_falls) == 0.0
    assert stdev(never_falls) > 0.0, (
        "the first C3 asked for zero VOLATILITY and therefore found nothing on the real panel; "
        "the measure that is exactly zero for a book with no losing day is the semideviation"
    )


def test_zero_downside_book_would_be_handed_the_portfolio_by_the_floor():
    books, marked = _marked_books()
    all_books = marked + ["drifter"]
    w = w_downside_parity({b: books[b] for b in all_books}, all_books)
    assert w["drifter"] == max(w.values())
    assert w["drifter"] > 0.5, (
        "floored rather than excluded, a book with no downside takes the portfolio — which is "
        "why the universe rule excludes it by a clause instead of relying on the floor"
    )


# ── 2. universe clauses are named, and each one is exercised ──────────────────────────────
def test_universe_excludes_by_a_named_clause():
    books = _panel()
    books["frozen"] = [0.0] * len(books["quiet"])          # clause (a): no daily mark
    panel, dates = _fake_panel_dict(books)
    universe, census = section1_universe(panel, dates)
    assert census["frozen"]["excluded_because"] == "no daily mark"
    assert census["drifter"]["excluded_because"] == "no downside at all"
    assert set(universe) == {"choppy", "upvol", "quiet"}
    for book in universe:
        assert census[book]["excluded_because"] == ""


# ── 3. warm-up alignment — the defect that was four fifths of the first headline ──────────
def test_equal_weight_is_identical_across_lookbacks_when_warmup_is_pinned():
    books, marked = _marked_books()
    scored = {lkb: metrics(run_scheme(books, marked, w_equal, lkb, 1.0, 15.0,
                                      warmup=WARMUP)["rets"])["apy"]
              for lkb in LOOKBACK_GRID}
    assert len(set(round(v, 12) for v in scored.values())) == 1, (
        "equal weight does not depend on a lookback; if its number moves with one, the columns "
        "of every comparison are different samples"
    )


def test_without_a_pinned_warmup_the_same_scheme_reports_different_numbers():
    """The positive control: the bug has to be reproducible, or the fix guards nothing."""
    books, marked = _marked_books()
    unaligned = {lkb: metrics(run_scheme(books, marked, w_equal, lkb, 1.0, 15.0,
                                         warmup=0)["rets"])["apy"]
                 for lkb in LOOKBACK_GRID}
    assert len(set(round(v, 12) for v in unaligned.values())) > 1, (
        "this panel must be able to EXHIBIT the misalignment, otherwise the aligned test above "
        "passes for free and guards nothing"
    )


# ── 4. causality is falsifiable, not decorative ───────────────────────────────────────────
def test_same_bar_mutation_moves_the_result():
    books, marked = _marked_books()
    for scheme in (w_downside_parity, w_inverse_vol):
        causal = run_scheme(books, marked, scheme, 20, 0.6, 0.0, warmup=WARMUP)["rets"]
        peeking = run_scheme(books, marked, scheme, 20, 0.6, 0.0, warmup=WARMUP,
                             same_bar=True)["rets"]
        assert len(causal) == len(peeking)
        assert any(abs(a - b) > 1e-15 for a, b in zip(causal, peeking)), (
            f"{scheme.__name__}: letting the window end on the day it weights changes nothing, "
            "so the claim 'strictly causal' is true by construction and tested by nothing"
        )


def test_the_causal_window_never_contains_the_day_it_weights():
    """Directly: a spike placed on day t must not reach the weight used ON day t."""
    books, marked = _marked_books()
    spiked = {b: list(v) for b, v in books.items()}
    t = WARMUP + 5
    spiked["quiet"][t] = -0.5                      # a catastrophe on exactly one day
    base = run_scheme(books, marked, w_downside_parity, 20, 1.0, 0.0, warmup=WARMUP)
    hit = run_scheme(spiked, marked, w_downside_parity, 20, 1.0, 0.0, warmup=WARMUP)
    i = t - WARMUP
    assert base["weights"][i] == hit["weights"][i], (
        "the weight used on day t moved when day t's own return changed — that is a same-bar "
        "look-ahead, the defect #94 (GSB) was written about"
    )
    assert base["weights"][i + 1] != hit["weights"][i + 1], (
        "the spike must reach the NEXT day's weight, or the signal reads nothing at all"
    )


# ── 5. the placebo's null is a null of the measured thing ─────────────────────────────────
def test_identity_permutation_reproduces_the_unpermuted_run_exactly():
    books, marked = _marked_books()
    plain = run_scheme(books, marked, w_downside_parity, 20, 0.6, 15.0, warmup=WARMUP)["rets"]
    ident = run_scheme(books, marked, w_downside_parity, 20, 0.6, 15.0, warmup=WARMUP,
                       permute={b: b for b in marked})["rets"]
    assert plain == ident


def test_a_non_identity_permutation_changes_the_result():
    books, marked = _marked_books()
    plain = run_scheme(books, marked, w_downside_parity, 20, 0.6, 15.0, warmup=WARMUP)["rets"]
    swapped = run_scheme(books, marked, w_downside_parity, 20, 0.6, 15.0, warmup=WARMUP,
                         permute={"choppy": "quiet", "quiet": "choppy", "upvol": "upvol"})["rets"]
    assert plain != swapped, "a placebo that cannot move the number is not a placebo"


# ── 6. the cap is a fixed point, not one pass ─────────────────────────────────────────────
def test_apply_cap_respects_the_cap_and_conserves_the_budget():
    # Chosen so that ONE pass overshoots: capping `a` at 0.40 spills 0.40 onto {b, c} pro rata,
    # and b's share (0.19/0.20) lifts it to 0.57 — over the cap it was supposed to enforce.
    raw = {"a": 0.80, "b": 0.19, "c": 0.01}
    for cap in CAP_GRID:
        w = apply_cap(raw, cap)
        assert abs(sum(w.values()) - 1.0) < 1e-12
        assert max(w.values()) <= cap + 1e-9, (
            f"cap {cap}: one pass of spilling can push a previously-uncapped book over the cap; "
            "the cap has to be iterated to a fixed point"
        )


def test_apply_cap_is_a_noop_above_one():
    raw = {"a": 0.5, "b": 0.3, "c": 0.2}
    assert apply_cap(raw, 1.0) == raw


# ── 7. an infinite Calmar is not a score ──────────────────────────────────────────────────
def test_selection_refuses_to_rank_a_configuration_that_never_fell():
    assert rankable({"calmar": 2.5}) is True
    assert rankable({"calmar": float("inf")}) is False
    assert rankable({"calmar": float("nan")}) is False, (
        "selecting on ∞ would make 'did not fall in the training half' beat every real "
        "trade-off on the grid"
    )


# ── 8. #106's estimator has a resolution, and the default is three values ─────────────────
def test_coincidence_is_bounded_and_reaches_both_ends():
    window = {"always": [-0.01] * 20, "never": [0.01] * 20,
              "mixed": [(-0.01 if i % 2 else 0.01) for i in range(20)]}
    assert coincidence(window, "always") == 1.0
    assert coincidence(window, "never") == 0.0
    assert 0.0 <= coincidence(window, "mixed") <= 1.0


def test_coincidence_resolution_is_k_plus_one_values():
    """At the default (20 days × 0.10) the 'discount' can only be 0, 1/2 or 1."""
    n, tail = 20, 0.10
    k = max(1, int(round(n * tail)))
    assert k == 2
    seen = set()
    for pattern in range(2 ** 6):
        window = {
            "probe": [(-0.01 if (pattern >> (i % 6)) & 1 else 0.01) for i in range(n)],
            "other": [(-0.02 if i < n // 2 else 0.02) for i in range(n)],
        }
        seen.add(round(coincidence(window, "probe", tail), 6))
    assert seen <= {0.0, 0.5, 1.0}
    assert len(seen) >= 2, "the probe must actually exercise more than one value"


def test_a_wider_tail_fraction_gives_the_discount_more_values():
    books, marked = _marked_books()
    coarse = run_scheme(books, marked, make_tail_coincidence(0.10), 20, 0.6, 15.0,
                        warmup=WARMUP)["rets"]
    fine = run_scheme(books, marked, make_tail_coincidence(0.50), 20, 0.6, 15.0,
                      warmup=WARMUP)["rets"]
    assert coarse != fine, (
        "if the tail fraction changed nothing, rejecting #106 at k=2 would be rejecting the "
        "estimator rather than the idea, and the resolution grid in §7 would be empty ceremony"
    )


# ── 9. DSP is not the structural twin #30 found on its synthetic fixture ──────────────────
def test_downside_parity_is_not_inverse_volatility_when_the_ratio_varies():
    books, marked = _marked_books()
    win = {b: books[b][:60] for b in marked}
    ratios = [semideviation(win[b]) / stdev(win[b]) for b in marked if stdev(win[b]) > 0]
    assert max(ratios) / min(ratios) > 1.5, "this panel must have room for the two to differ"
    wv, ws = w_inverse_vol(win, marked), w_downside_parity(win, marked)
    assert any(abs(wv[b] - ws[b]) > 1e-6 for b in marked), (
        "#30 measured a difference of exactly zero on a fixture where semivariance and variance "
        "are proportional by construction; a panel where the ratio varies must not repeat that"
    )


def test_the_two_denominators_can_disagree_on_the_ORDER_not_only_the_size():
    """A scheme that never re-orders is a concentration dial, not a selection criterion."""
    win = {
        "a": [0.05, -0.001, 0.04, -0.001, 0.05],    # big upside vol, tiny downside
        "b": [0.002, -0.02, 0.003, -0.02, 0.002],   # small total vol, all of it downside
    }
    books = ["a", "b"]
    wv, ws = w_inverse_vol(win, books), w_downside_parity(win, books)
    assert (wv["a"] > wv["b"]) != (ws["a"] > ws["b"]), (
        "on this window the two denominators must rank the books in OPPOSITE order — that is "
        "the whole claim of #105, and if it cannot happen the idea is arithmetic, not a signal"
    )


# ── 10. an unmeasurable control refuses ───────────────────────────────────────────────────
def test_controls_refuse_when_the_degeneracy_rule_is_unexercised():
    """A panel with no zero-downside book cannot TEST the exclusion rule the run relies on."""
    books = {b: v for b, v in _panel().items() if b != "drifter"}
    panel, dates = _fake_panel_dict(books)
    out = section0_controls(panel, dates)
    assert any("C3" in f for f in out["failures"]), (
        "'could not check' and 'checked and fine' must not share an exit: with no zero-downside "
        "book on the panel the exclusion rule is unexercised, and that is a refusal"
    )


def test_controls_accept_a_panel_that_does_exercise_the_degeneracy_rule():
    """The other direction of C3: the rule must FIRE on a book that moves but never falls.

    A control that looks for zero VOLATILITY instead of zero DOWNSIDE passes the refusal test
    above for the wrong reason — it finds nothing either way. Only this direction separates them.
    """
    panel, dates = _fake_panel_dict(_panel())
    out = section0_controls(panel, dates)
    assert "drifter" in out["c3_degenerate"], (
        "`drifter` moves (stdev > 0) and never falls (semideviation == 0); a C3 that asks about "
        "volatility cannot see it, and then the exclusion rule the run depends on is untested"
    )
    assert not any("C3" in f for f in out["failures"])


def test_c1_actually_compares_and_fails_on_a_wrong_published_number(monkeypatch):
    """C1 pins the data path to a published table. A tolerance that always passes pins nothing."""
    import scripts.edge_downside_parity as mod

    books = _panel()
    panel, dates = _fake_panel_dict(books)
    truth = mod.ens.perf([panel["quiet"][d] for d in dates])
    monkeypatch.setattr(mod, "PUBLISHED_17",
                        {"quiet": (round(truth["apy"] * 100, 2), round(truth["maxdd"] * 100, 2))})
    ok = mod.section0_controls(panel, dates)
    assert not any("C1" in f for f in ok["failures"]), "C1 must accept the number it measured"

    monkeypatch.setattr(mod, "PUBLISHED_17",
                        {"quiet": (round(truth["apy"] * 100 + 5.0, 2),
                                   round(truth["maxdd"] * 100, 2))})
    bad = mod.section0_controls(panel, dates)
    assert any("C1" in f for f in bad["failures"]), (
        "a published APY 5 pp away from the measured one must FAIL C1; if it does not, C1 is a "
        "table printed next to numbers it never compared"
    )


def test_controls_refuse_when_the_published_replay_is_absent():
    """C1 pins the data path to the table #17 published; a panel without those books refuses."""
    panel, dates = _fake_panel_dict(_panel())
    out = section0_controls(panel, dates)
    assert any("C1" in f and "absent" in f for f in out["failures"])


def test_turnover_is_actually_charged():
    """A scheme that trades must be POORER at 96 bps than at 0 bps, monotonically."""
    books, marked = _marked_books()
    apys = []
    for bps in (0.0, 15.0, 96.0):
        res = run_scheme(books, marked, w_downside_parity, 20, 0.6, bps, warmup=WARMUP)
        assert sum(res["turnover"]) > 0.0, "this scheme must trade, or the test charges nothing"
        apys.append(metrics(res["rets"])["apy"])
    assert apys[0] > apys[1] > apys[2], (
        f"APY did not fall as the roundtrip price rose ({apys}) — the turnover term is not "
        "reaching the portfolio return, and every cost-conditional verdict would be free"
    )


def test_equal_weight_still_pays_for_its_own_drift():
    """#49 (RDT) measured that holding a constant weight IS a trade. It must not be free here."""
    books, marked = _marked_books()
    res = run_scheme(books, marked, w_equal, 20, 1.0, 0.0, warmup=WARMUP)
    assert sum(res["turnover"]) > 0.0, (
        "equal weight rebalanced daily has turnover; scoring it as costless would hand the "
        "baseline an advantage no real book has"
    )


# ── determinism ───────────────────────────────────────────────────────────────────────────
def test_runs_are_deterministic():
    books, marked = _marked_books()
    a = run_scheme(books, marked, w_downside_parity, 20, 0.6, 15.0, warmup=WARMUP)
    b = run_scheme(books, marked, w_downside_parity, 20, 0.6, 15.0, warmup=WARMUP)
    assert a["rets"] == b["rets"] and a["weights"] == b["weights"]


def test_weights_always_sum_to_one_and_never_go_negative():
    books, marked = _marked_books()
    for scheme in (w_equal, w_inverse_vol, w_downside_parity, make_tail_coincidence(0.25)):
        res = run_scheme(books, marked, scheme, 20, 0.6, 15.0, warmup=WARMUP)
        for w in res["weights"]:
            assert abs(sum(w.values()) - 1.0) < 1e-9
            assert min(w.values()) >= -1e-15


def test_risk_floor_is_below_every_denominator_it_must_not_bind_on():
    """The floor was first set at 1e-04 and bound on a BOOK (susde_dn, 1.9e-05). It is a knob;
    a knob that binds on the data is the knob deciding, not the data."""
    assert RISK_FLOOR <= 1e-6
