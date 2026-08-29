"""
spa_core/tests/test_edge_leg_aware_timing.py — acceptance for registry idea LAT.

Each test is a POSITIVE CONTROL, verified RED against a deliberately broken copy of
scripts/edge_leg_aware_timing.py before being committed (mutation list in the registry
entry). The central one is test_the_toll_is_heterogeneous_across_names: it is the ONLY
thing that separates LAT from #82 CIT, and if it can be made to pass with a flat toll then
the idea is a restatement, not an idea.

The real panel is NOT git-tracked; tests needing it SKIP with an explicit "unchecked, not
absent" reason rather than passing quietly on a fixture.

stdlib + pytest only. Advisory-path code: no capital, no RiskPolicy, no live track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

lat = pytest.importorskip("edge_leg_aware_timing")
gtn = pytest.importorskip("edge_gross_to_net_toll")
cit = pytest.importorskip("edge_cost_internalised_timing")
css = pytest.importorskip("edge_cost_signal_separation")
mh = pytest.importorskip("edge_mhfc_backtest")


# ───────────────────────────── synthetic panels ──────────────────────────────────
def _wave(n, period, amp, phase=0):
    return [amp * math.sin(2 * math.pi * (i + phase) / period) for i in range(n)]


def _panel(name_a, name_b, n=260):
    """Two books whose signals cross often, so any timing rule has decisions to make."""
    return {name_a: _wave(n, 30, 0.01), name_b: _wave(n, 30, 0.01, phase=15)}


def _dates(n):
    """n consecutive days ending today.

    The VALUES are never read: css._weight_history walks range(1, len(dates)) and the arm's
    rule is index-based, so only the LENGTH carries meaning. A literal start date here would
    be a time bomb with no upside — the calendar would eventually move under a test whose
    subject is not the calendar (the class .claude/rules/deployment.md names).
    """
    import datetime

    today = datetime.date.today()
    return [today - datetime.timedelta(days=n - 1 - i) for i in range(n)]


# ───────────────────── 1. the two published limits of lambda ─────────────────────
def test_lambda_infinite_is_todays_arm_cell_for_cell():
    """λ=inf must reproduce #80's arm exactly — otherwise LAT is a different instrument
    and none of its cells may be compared with a published one."""
    book_rets = _panel("susde_spot", "susde_dn")
    dates = _dates(len(next(iter(book_rets.values()))))
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in book_rets})
    hist, _ = lat.lat_history(book_rets, len(dates), "h20", float("inf"), 96.0, legs)
    assert hist == css._weight_history(book_rets, dates, "h20")


@pytest.mark.skipif(
    not (ROOT / "data" / "aggressive_lab").exists(),
    reason="real panel is not git-tracked: UNCHECKED here, not absent (run in the prod tree)",
)
def test_lambda_infinite_anchor_also_holds_where_a_MOVE_CAN_LOSE():
    """The two-book synthetic above is not enough on its own, and saying why is the point.

    With the roster's "hold every positive-signal book at equal weight" rule, a proposed move
    always shifts weight TOWARDS the books the signal likes, so its expected gain is positive
    and `lambda * gain > bar` is satisfied by any large lambda — the λ=inf branch is never the
    reason the move was taken, and a mutation deleting that branch survives. On the real panel
    a book in warm-up (signal None, credited 0) can be added to the basket while a
    positive-signal book is diluted, and THEN the gain is negative and only λ=inf takes it.
    """
    dates, book_rets = gtn.load_real_panel()
    legs = {b: lat.scoring_legs()[b] for b in sorted(book_rets)}
    hist, _ = lat.lat_history(book_rets, len(dates), "h20", float("inf"), 96.0, legs)
    assert hist == css._weight_history(book_rets, dates, "h20")


def test_switch_count_matches_the_moves_that_actually_happened():
    """A switch is a CHANGE of vector. Counting a no-op as a switch corrupts every control
    in section 2, because those controls are matched on the switch COUNT."""
    book_rets = _panel("susde_spot", "susde_dn")
    n = len(book_rets["susde_spot"])
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in book_rets})
    for lam in (1.0, 5.0, 20.0, float("inf")):
        hist, switches = lat.lat_history(book_rets, n, "h20", lam, 96.0, legs)
        moves = sum(1 for k in range(1, len(hist)) if hist[k] != hist[k - 1])
        assert switches == moves, f"λ={lam}: counted {switches} switches for {moves} moves"


def test_lambda_zero_freezes_the_first_vector_and_makes_no_switches():
    book_rets = _panel("susde_spot", "susde_dn")
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in book_rets})
    hist, switches = lat.lat_history(book_rets, len(book_rets["susde_spot"]), "h20", 0.0, 96.0, legs)
    assert switches == 0
    assert all(w == hist[0] for w in hist)


# ───────────────────── 2. THE claim: the toll is not flat ────────────────────────
def test_the_toll_is_heterogeneous_across_names():
    """The one test that separates LAT from #82.

    Two panels with BYTE-IDENTICAL returns; only the second book's NAME differs, and with it
    its composition: susde_dn shares the sUSDe leg with susde_spot (cheap to rotate into),
    pendle_pt_levered is a 3x loop on a different token (expensive). #82's flat rule cannot
    tell them apart and must switch the same number of times on both. LAT must not.
    """
    n = 260
    cheap = _panel("susde_spot", "susde_dn", n)
    dear = _panel("susde_spot", "pendle_pt_levered", n)
    table = lat.scoring_legs()   # the table the harness actually invoices on
    legs_cheap = {b: table[b] for b in cheap}
    legs_dear = {b: table[b] for b in dear}
    cost = 96.0

    # The rule only reveals itself where the bar bites: at a tiny lambda nothing switches and
    # at a huge one everything does, in both panels. So the claim is scanned over the
    # PUBLISHED lambda ladder rather than asserted at one hand-picked point.
    ladder = [x for x in lat.LAMBDA_GRID if not math.isinf(x) and x > 0]
    lat_pairs, cit_pairs = [], []
    for lam in ladder:
        lat_pairs.append((lat.lat_history(cheap, n, "h20", lam, cost, legs_cheap)[1],
                          lat.lat_history(dear, n, "h20", lam, cost, legs_dear)[1]))
        cit_pairs.append((cit.cit_history(cheap, n, "h20", lam, cost)[1],
                          cit.cit_history(dear, n, "h20", lam, cost)[1]))

    assert all(a == b for a, b in cit_pairs), (
        f"the flat rule must be blind to composition (that is its defect): {cit_pairs}"
    )
    assert any(a > b for a, b in lat_pairs), (
        f"LAT never distinguished a shared-leg pair from a 3x loop over the whole lambda "
        f"ladder {ladder}: {lat_pairs} — the mechanism is not wired"
    )
    assert all(a >= b for a, b in lat_pairs), (
        f"LAT declined MORE moves into the cheap pair than into the 3x loop: {lat_pairs}"
    )


def test_leg_tau_is_the_gtn_algebra_on_one_step():
    """Hand arithmetic: rotating fully out of spot sUSDe into the delta-neutral book moves
    the perp leg only, so one unit of weight costs one unit of flow, not two."""
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in ("susde_spot", "susde_dn")})
    tau = lat.leg_tau({"susde_dn": 1.0}, {"susde_spot": 1.0}, legs)
    assert tau == pytest.approx(1.0)
    raw = lat.leg_tau({"pendle_pt_levered": 1.0}, {"susde_spot": 1.0}, gtn.RAW_LEGS)
    assert raw == pytest.approx(6.0)   # 5 of loop legs built + 1 of sUSDe sold


def test_a_zero_size_move_is_never_charged_or_counted():
    legs = gtn.normalise_legs(gtn.RAW_LEGS)
    same = {"susde_spot": 0.5, "susde_dn": 0.5}
    assert lat.leg_tau(same, dict(same), legs) == pytest.approx(0.0)


# ───────────────────── 3. the flat-toll control ──────────────────────────────────
def test_flattened_legs_keep_the_size_and_destroy_the_structure():
    legs = lat.scoring_legs()
    flat = lat.flattened_legs(legs)
    avg = sum(sum(abs(v) for v in vec.values()) for vec in legs.values()) / len(legs)
    for book in legs:
        assert sum(flat[book].values()) == pytest.approx(avg)
        assert len(flat[book]) == 1
    # a private leg per book ⇒ nothing can net against anything
    assert len({next(iter(v)) for v in flat.values()}) == len(flat)


def test_flat_toll_cannot_distinguish_two_books():
    n = 260
    cheap = _panel("susde_spot", "susde_dn", n)
    dear = _panel("susde_spot", "pendle_pt_levered", n)
    flat_cheap = lat.flattened_legs(gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in cheap}))
    flat_dear = lat.flattened_legs(gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in dear}))
    _, a = lat.lat_history(cheap, n, "h20", 5.0, 96.0, flat_cheap)
    _, b = lat.lat_history(dear, n, "h20", 5.0, 96.0, flat_dear)
    assert a == b


# ───────────────────── 4. warm-up books are never credited ───────────────────────
def test_an_all_warmup_panel_never_switches():
    """fail-CLOSED, inherited from #82: a book that has shown nothing is credited nothing."""
    n = 40   # shorter than the h60 lookback ⇒ every signal is None
    book_rets = _panel("susde_spot", "susde_dn", n)
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in book_rets})
    _, switches = lat.lat_history(book_rets, n, "h60", 60.0, 96.0, legs)
    assert switches == 0


def test_the_warmup_credit_is_zero_and_is_MEASURED_to_be_inert_on_this_panel(monkeypatch):
    """The credit rule, and the honest size of what testing it can prove.

    The rule itself is asserted directly: an unmeasured book is credited 0.0.

    The interesting half is what a positive control CANNOT show here, and it was measured
    rather than assumed. Substituting an optimistic credit (+1.0 for every None) changes the
    arm's decisions by sum over the warm-up set of dw_b. With a single lookback horizon every
    book leaves warm-up on the same day, so that set is either all books — where weights
    summing to 1 make the term exactly 0 — or none. MHFC decides None per book and could in
    principle break the tie; on THIS panel it does not, because warm-up is over before the
    first move. So the substitution is inert, end to end, and this test pins that as the
    measured state instead of dressing an unfalsifiable rule up as a guard. If a future panel
    or a shorter axis makes the sets differ, this assertion flips and the credit becomes
    testable — which is exactly when someone should look at it again.
    """
    assert lat.signal_credit(None) == 0.0
    assert lat.signal_credit(-0.3) == pytest.approx(-0.3)
    assert lat.signal_credit(0.0) == 0.0

    if not (ROOT / "data" / "aggressive_lab").exists():
        pytest.skip("real panel is not git-tracked: UNCHECKED here, not absent")
    dates, book_rets = gtn.load_real_panel()
    legs = {b: lat.scoring_legs()[b] for b in sorted(book_rets)}
    honest, sw_honest = lat.lat_history(book_rets, len(dates), "mhfc", 20.0, 96.0, legs)
    monkeypatch.setattr(lat, "signal_credit", lambda v: 1.0 if v is None else float(v))
    optimistic, sw_opt = lat.lat_history(book_rets, len(dates), "mhfc", 20.0, 96.0, legs)
    assert (honest, sw_honest) == (optimistic, sw_opt), (
        "an optimistic warm-up credit now CHANGES the arm — the rule has become testable on "
        "this panel, so replace this measurement with a real positive control"
    )


# ───────────────────── 5. no look-ahead ──────────────────────────────────────────
def test_the_future_cannot_change_the_past():
    n = 200
    base = _panel("susde_spot", "susde_dn", n)
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in base})
    hist_a, _ = lat.lat_history(base, n, "h20", 20.0, 96.0, legs)
    perturbed = {b: list(v) for b, v in base.items()}
    for b in perturbed:
        for i in range(n - 20, n):
            perturbed[b][i] = 0.9   # a wild future
    hist_b, _ = lat.lat_history(perturbed, n, "h20", 20.0, 96.0, legs)
    cut = n - 25
    assert hist_a[:cut] == hist_b[:cut]


# ───────────────────── 6. the invoice the scorer uses ────────────────────────────
def test_scoring_uses_the_leg_invoice_not_the_book_one():
    n = 260
    book_rets = _panel("susde_spot", "pendle_pt_levered", n)
    dates = _dates(n)
    legs = {b: gtn.RAW_LEGS[b] for b in book_rets}
    hist = css._weight_history(book_rets, dates, "h20")
    gross, tau_book = css._gross_and_turnover(hist, book_rets)
    tau_leg = gtn.leg_turnover(hist, legs)
    assert sum(tau_leg) > sum(tau_book) * 1.5, "a 3x loop must cost more, not the same"
    apy_leg = lat._score(hist, book_rets, legs, 0.0, 96.0)[0]
    apy_book = mh._apy(css._net(gross, tau_book, 96.0))
    assert apy_leg < apy_book


def test_scoring_legs_price_borrowings_free_by_declaration():
    legs = lat.scoring_legs()
    assert lat.DEBT_RATE == 0.0
    assert "stable_debt" not in legs["pendle_pt_levered"]
    assert legs["pendle_pt_levered"]["pt_susde"] == pytest.approx(3.0)


# ───────────────────── 7. the panel is never faked ───────────────────────────────
def test_missing_panel_refuses_instead_of_substituting_the_fixture(tmp_path):
    with pytest.raises(FileNotFoundError, match="refusing to substitute the fixture"):
        gtn.load_real_panel(tmp_path / "nope")


@pytest.mark.skipif(
    not (ROOT / "data" / "aggressive_lab").exists(),
    reason="real panel is not git-tracked: UNCHECKED here, not absent (run in the prod tree)",
)
def test_todays_arm_loses_under_the_corrected_invoice_on_the_real_panel():
    """The published GTN finding, pinned from LAT's side: λ=inf (today's arm) does NOT beat
    equal weight once the toll is charged on legs. If this ever flips, the registry entry is
    stale and must be re-read before anyone acts on it."""
    dates, book_rets = gtn.load_real_panel()
    legs = {b: lat.scoring_legs()[b] for b in sorted(book_rets)}
    eq_hist = css._weight_history(book_rets, dates, "eq")
    eq_gross, _ = css._gross_and_turnover(eq_hist, book_rets)
    eq_cal = mh._calmar(css._net(eq_gross, gtn.leg_turnover(eq_hist, legs), 96.0))
    hist, _ = lat.lat_history(book_rets, len(dates), "h60", float("inf"), 96.0, legs)
    assert lat._score(hist, book_rets, legs, eq_cal, 96.0)[3] < 0.0


def test_module_declares_advisory_and_never_imports_execution():
    assert lat.IS_ADVISORY is True
    assert lat.OUTSIDE_RISKPOLICY is True
    assert lat.EVIDENCE_LEVEL == "L0"
    src = (SCRIPTS / "edge_leg_aware_timing.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("spa_core.execution"), alias.name
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("spa_core.execution"), node.module
