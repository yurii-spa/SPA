"""
spa_core/tests/test_edge_single_book_turnover_cap.py — acceptance for SBTC and CVX.

Each test is a POSITIVE CONTROL, verified RED against a deliberately broken copy of
scripts/edge_single_book_turnover_cap.py before being committed (mutation list in the
registry entry). Two of them are the entry itself:

  * test_the_cap_is_a_PATH_not_a_filter — a cap read against the TARGET's yesterday instead
    of the REALISED yesterday is a different instrument that happens to print similar
    aggregates; if that mutation stays green the whole ladder is unreadable;
  * test_the_ordered_book_leads_at_BOTH_debt_rates_and_only_delta_one_reaches_88s_band —
    the correction this entry publishes. #88 quoted the share from the δ=1 column while
    paying the δ=0 bill, and nothing in the family noticed.

The real panel is NOT git-tracked; tests needing it SKIP with an explicit "unchecked, not
absent" reason rather than passing quietly on a fixture.

stdlib + pytest only. Advisory-path code: no capital, no RiskPolicy, no live track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import datetime
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

sbtc = pytest.importorskip("edge_single_book_turnover_cap")
gtn = pytest.importorskip("edge_gross_to_net_toll")
css = pytest.importorskip("edge_cost_signal_separation")
mh = pytest.importorskip("edge_mhfc_backtest")

PANEL = ROOT / "data" / "aggressive_lab"
NEEDS_PANEL = pytest.mark.skipif(
    not PANEL.exists(),
    reason="real panel is not git-tracked: UNCHECKED here, not absent (run in the prod tree)",
)


# ───────────────────────────── synthetic panels ──────────────────────────────────
def _wave(n, period, amp, phase=0):
    return [amp * math.sin(2 * math.pi * (i + phase) / period) for i in range(n)]


def _panel(*names, n=260):
    """Books whose signals cross often, so a cap has decisions to bind on.

    The LAST name is given a constant positive drift on purpose: it is always included by
    the arm, so the free side of the vector is never empty and the fail-CLOSED refusal
    branch never fires. That keeps refusals out of tests whose subject is the CAP, and
    leaves refusal to the one test that is about refusal.
    """
    out = {}
    for k, name in enumerate(names[:-1]):
        out[name] = _wave(n, 30, 0.01, phase=k * 30 // max(1, len(names) - 1))
    out[names[-1]] = [0.001] * n
    return out


def _dates(n):
    """n consecutive days ending today.

    The VALUES are never read — the arm's rule is index-based and only the LENGTH carries
    meaning. A literal start date here would be a time bomb with no upside: the calendar
    would eventually move under a test whose subject is not the calendar
    (the class .claude/rules/deployment.md names).
    """
    today = datetime.date.today()
    return [today - datetime.timedelta(days=n - 1 - i) for i in range(n)]


def _legs(book_rets):
    return gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in book_rets})


# ─────────────────────── 1. the two published limits of kappa ────────────────────
def test_kappa_infinite_is_todays_arm_cell_for_cell():
    """κ=inf must reproduce #80's arm exactly, or no cell here may be compared to a
    published one."""
    br = _panel("susde_spot", "susde_dn", "points_farm")
    dates = _dates(len(next(iter(br.values()))))
    hist, bound, refused = sbtc.capped_history(br, dates, "h20", ["susde_dn"], float("inf"))
    assert hist == css._weight_history(br, dates, "h20")
    assert (bound, refused) == (0, 0)


def test_kappa_zero_freezes_the_capped_book_and_leaves_the_others_trading():
    """κ=0 is the other published limit: that ONE name never moves again, and the other
    nine keep trading. A cap that froze the whole vector would be #50's band, not SBTC."""
    br = _panel("susde_spot", "susde_dn", "points_farm")
    dates = _dates(len(next(iter(br.values()))))
    hist, bound, refused = sbtc.capped_history(br, dates, "h20", ["susde_dn"], 0.0)
    assert refused == 0
    frozen = {round(day["susde_dn"], 12) for day in hist}
    assert len(frozen) == 1, f"capped book moved: {sorted(frozen)}"
    assert frozen == {round(hist[0]["susde_dn"], 12)}
    others = {round(day["susde_spot"], 12) for day in hist}
    assert len(others) > 1, "the free books stopped trading too — this is a global freeze"
    assert bound > 0, "κ=0 never bound: the panel gives the cap nothing to do"


# ───────────────── 2. the mechanism: a path, and a constraint that is paid ────────
def test_the_cap_is_a_PATH_not_a_filter(monkeypatch):
    """The cap is measured against the REALISED weight, never the target's own yesterday.

    A filter (clamp target_t against target_{t-1}) prints a similar-looking ladder and is a
    completely different instrument: it lets a book teleport as long as its TARGET moved
    smoothly. Asserted on exact numbers, not on "they differ".
    """
    a, b, c = "susde_dn", "susde_spot", "points_farm"
    third = 1.0 / 3.0
    crafted = [
        {a: third, b: third, c: third},
        {a: 0.9, b: 0.05, c: 0.05},
        {a: 0.9, b: 0.05, c: 0.05},
        {a: third, b: third, c: third},
    ]
    monkeypatch.setattr(sbtc, "target_history", lambda br, d, m: crafted)
    br = {a: [0.0] * 4, b: [0.0] * 4, c: [0.0] * 4}
    hist, bound, refused = sbtc.capped_history(br, _dates(4), "h20", [a], 0.1)
    assert refused == 0
    got = [round(day[a], 6) for day in hist]
    assert got == [round(third, 6), round(third + 0.1, 6), round(third + 0.2, 6),
                   round(third + 0.1, 6)], got
    # the filter reading would have let it land on 0.9 as soon as the target stopped moving
    assert max(got) < 0.9


def test_the_free_books_absorb_the_residual_so_the_vector_still_sums_to_one():
    """The cap is not free: gross exposure is unchanged, so the other names must pay for it
    in their own turnover. A vector that stopped summing to 1 would be a hidden cash sleeve
    and would flatter every drawdown number in the entry."""
    br = _panel("susde_spot", "susde_dn", "points_farm", "lrt_neutral")
    dates = _dates(len(next(iter(br.values()))))
    for kappa in (0.0, 0.02, 0.1):
        hist, _, refused = sbtc.capped_history(br, dates, "h20", ["susde_dn"], kappa)
        assert refused == 0
        for day in hist:
            assert abs(sum(day.values()) - 1.0) < 1e-9


def test_the_free_books_keep_the_arms_proportions_among_themselves(monkeypatch):
    """The residual is spread PROPORTIONALLY to the arm's own targets — it does not invent a
    new opinion about which free book to favour. Two free books whose targets are 1:3 stay
    1:3 after absorbing."""
    a, b, c = "susde_dn", "susde_spot", "points_farm"
    crafted = [{a: 0.5, b: 0.125, c: 0.375}, {a: 0.9, b: 0.025, c: 0.075}]
    monkeypatch.setattr(sbtc, "target_history", lambda br, d, m: crafted)
    br = {a: [0.0] * 2, b: [0.0] * 2, c: [0.0] * 2}
    hist, _, _ = sbtc.capped_history(br, _dates(2), "h20", [a], 0.1)
    day = hist[1]
    assert abs(day[a] - 0.6) < 1e-12
    assert abs(day[c] / day[b] - 3.0) < 1e-9
    assert abs(day[b] + day[c] - 0.4) < 1e-12


def test_an_infeasible_day_is_REFUSED_not_quietly_relaxed(monkeypatch):
    """When the free books carry no weight to absorb the residual, the cap cannot be honoured
    without changing gross exposure. fail-CLOSED: hold yesterday. The tempting alternative —
    relax the cap for one day — turns an unaffordable constraint into a licence to trade."""
    a, b = "susde_dn", "susde_spot"
    crafted = [{a: 0.5, b: 0.5}, {a: 1.0, b: 0.0}]
    monkeypatch.setattr(sbtc, "target_history", lambda br, d, m: crafted)
    br = {a: [0.0] * 2, b: [0.0] * 2}
    hist, _, refused = sbtc.capped_history(br, _dates(2), "h20", [a], 0.1)
    assert refused == 1
    assert hist[1] == hist[0], "the infeasible day traded anyway"


def test_clamp_move_travels_exactly_kappa_in_both_directions_and_no_further():
    up = sbtc.clamp_move(target=0.9, prev=0.2, kappa=0.1)
    down = sbtc.clamp_move(target=0.0, prev=0.2, kappa=0.1)
    assert abs(up - 0.3) < 1e-12 and abs(down - 0.1) < 1e-12
    # a move smaller than the cap passes through untouched — a cap is not a rate limiter
    assert sbtc.clamp_move(target=0.25, prev=0.2, kappa=0.1) == 0.25
    assert sbtc.clamp_move(target=0.9, prev=0.2, kappa=float("inf")) == 0.9
    assert sbtc.clamp_move(target=0.9, prev=0.2, kappa=0.0) == 0.2


def test_capping_a_book_that_is_not_on_the_panel_refuses_loudly():
    br = _panel("susde_spot", "susde_dn")
    with pytest.raises(ValueError):
        sbtc.capped_history(br, _dates(260), "h20", ["a_book_that_does_not_exist"], 0.1)


def test_capping_different_books_produces_different_histories():
    """The identity control must not be nine copies of the same run. Comparing two rows that
    are the same object by construction is the blindest test there is."""
    br = _panel("susde_spot", "susde_dn", "points_farm")
    dates = _dates(len(next(iter(br.values()))))
    h_a, _, _ = sbtc.capped_history(br, dates, "h20", ["susde_dn"], 0.0)
    h_b, _, _ = sbtc.capped_history(br, dates, "h20", ["susde_spot"], 0.0)
    assert h_a != h_b


# ───────────────────────── 3. CVX: the convex invoice ────────────────────────────
def test_convex_net_at_gamma_zero_is_the_familys_linear_net_exactly():
    """γ=0 must reproduce every published number of #79-#88 cell for cell, or the CVX row
    labelled γ=0 is not the family's model and the whole comparison is void."""
    gross = [0.001, -0.002, 0.0005, 0.0]
    turns = [0.0, 0.4, 1.3, 0.05]
    assert sbtc.convex_net(gross, turns, 96.0, 0.0) == css._net(gross, turns, 96.0)


def test_the_impact_term_is_superlinear_so_one_big_trade_costs_more_than_two_halves():
    """The whole point of a convex invoice: flow is punished more than proportionally.
    A linear term would make this equality, and the CVX section would measure nothing."""
    one_big = sbtc.convex_net([0.0], [1.0], 0.0, 96.0)[0]
    two_halves = sum(sbtc.convex_net([0.0, 0.0], [0.5, 0.5], 0.0, 96.0))
    assert one_big < two_halves - 1e-9


def test_a_book_that_does_not_trade_pays_no_impact_at_any_gamma():
    """The claim printed above the CVX table. Equal-weight does not trade, so every column of
    that table is the ACTIVE arm's own bill and nothing else."""
    gross = [0.001] * 5
    turns = [0.0] * 5
    for gamma in sbtc.GAMMA_GRID:
        assert sbtc.convex_net(gross, turns, 96.0, gamma) == gross


# ─────────────────── 4. the controls must actually be controls ───────────────────
def test_the_turnover_match_really_minimises_the_gap_over_the_whole_grid():
    """A control that is 'matched' by assertion rather than by search is decoration. Verified
    by recomputing every point of the grid independently here."""
    br = _panel("susde_spot", "susde_dn", "points_farm")
    dates = _dates(len(next(iter(br.values()))))
    legs = _legs(br)
    n_days = len(dates) - 1
    target = 3.0
    k, flow = sbtc.match_kappa_to_flow(br, dates, "h20", ["susde_dn"], target, legs, n_days)
    brute = []
    for kk in sbtc.KAPPA_SEARCH:
        h, _, _ = sbtc.capped_history(br, dates, "h20", ["susde_dn"], kk)
        f = sum(gtn.leg_turnover(h, legs)) / (n_days / 365.0)
        brute.append((abs(f - target), kk, f))
    best_err = min(b[0] for b in brute)
    assert abs(flow - target) <= best_err + 1e-9
    assert abs(k - max(b[1] for b in brute if b[0] <= best_err + 1e-9)) < 1e-12


def test_the_grids_are_fixed_constants_not_something_tuned_after_the_fact():
    """The ladder, the search grid, the split and the cost are declared in the module and
    stated in the entry. Pinning them here is what makes 'no parameter was chosen on TEST'
    a checkable claim instead of a promise."""
    assert sbtc.KAPPA_LADDER == (0.0, 0.01, 0.02, 0.05, 0.10, 0.20, float("inf"))
    assert sbtc.GAMMA_GRID == (0.0, 48.0, 96.0, 192.0, 384.0, 768.0)
    assert sbtc.KAPPA_SEARCH[0] == 0.0 and sbtc.KAPPA_SEARCH[-1] == 0.5
    assert len(sbtc.KAPPA_SEARCH) == 101
    assert sbtc.SPLIT_DATE == "2025-06-30"
    assert sbtc.CONVENTION_COST == 96
    assert sbtc.DEBT_RATE == 0.0
    assert sbtc.ORDERED_BOOK == "pendle_pt_levered"


# ───────────────────────── 5. against the real panel ─────────────────────────────
@NEEDS_PANEL
def test_the_ordered_book_leads_at_BOTH_debt_rates_and_only_delta_one_reaches_88s_band():
    """THE CORRECTION THIS ENTRY PUBLISHES.

    #88 headlined 'pendle_pt_levered generates 43-48 % of all leg flow' and SCORED at δ=0.
    Those are two different columns. At δ=1 the share does land in 43-48 %; at the δ=0
    invoice #88 actually paid it does not. The ADDRESS survives — the book still leads by
    more than a factor of two — but the number was quoted from the other column, and this
    test fails the day either half of that stops being true.
    """
    dates, br = gtn.load_real_panel()
    for delta, in_88_band in ((1.0, True), (0.0, False)):
        legs = gtn.legs_at_debt_rate(gtn.RAW_LEGS, delta)
        legs = {b: legs[b] for b in sorted(br)}
        for mode, _ in css.ARMS:
            hist = sbtc.target_history(br, dates, mode)
            flow = gtn.per_book_leg_flow(hist, legs)
            total = sum(flow.values())
            ranked = sorted(flow.items(), key=lambda kv: -kv[1])
            assert ranked[0][0] == sbtc.ORDERED_BOOK, (delta, mode, ranked[:2])
            share = flow[sbtc.ORDERED_BOOK] / total
            assert share > 2.0 * ranked[1][1] / total, (delta, mode, share)
            # #88 rounded its own column to "43-48 %"; measured it is 42.8-47.8 % at δ=1.
            # The two readings are DISJOINT bands, which is the whole correction.
            assert (0.42 <= share <= 0.48) is in_88_band, (delta, mode, share)
            assert (0.30 <= share <= 0.40) is not in_88_band, (delta, mode, share)


@NEEDS_PANEL
def test_the_future_cannot_change_the_past():
    """Truncating the panel must not move a single earlier weight. The cheapest way for a
    look-ahead to enter a path-dependent rule is a cap tuned on the whole series."""
    dates, br = gtn.load_real_panel()
    cut = 400
    short_dates = dates[:cut]
    short_br = {b: v[:cut] for b, v in br.items()}
    long_hist, _, _ = sbtc.capped_history(br, dates, "h60", [sbtc.ORDERED_BOOK], 0.02)
    short_hist, _, _ = sbtc.capped_history(
        short_br, short_dates, "h60", [sbtc.ORDERED_BOOK], 0.02
    )
    assert len(short_hist) == cut - 1
    for i, day in enumerate(short_hist):
        assert day == long_hist[i], f"day {i} changed when later days were removed"


@NEEDS_PANEL
def test_scoring_uses_the_leg_invoice_and_prices_borrowings_free_by_declaration():
    legs = sbtc.scoring_legs()
    assert all(leg not in gtn.DEBT_LEGS for vec in legs.values() for leg in vec)
    assert "stable_debt" not in legs["pendle_pt_levered"]
    assert abs(sum(abs(v) for v in legs["pendle_pt_levered"].values()) - 3.0) < 1e-12


def test_missing_panel_refuses_instead_of_substituting_the_fixture(tmp_path):
    with pytest.raises(FileNotFoundError):
        gtn.load_real_panel(tmp_path / "nope")


# ───────────────────────────── 6. domain hygiene ─────────────────────────────────
def _code_only(src: str) -> str:
    """Source with every string literal and comment removed.

    A guard that greps raw source cannot tell the difference between USING
    `equity_curve_daily` and PROMISING not to touch it — and this module's own docstring
    makes exactly that promise. Scanning prose as if it were code is how a guard ends up
    reddening on the sentence that documents its own subject.
    """
    import io
    import tokenize

    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def test_module_declares_advisory_and_never_imports_execution():
    src = (SCRIPTS / "edge_single_book_turnover_cap.py").read_text()
    assert sbtc.IS_ADVISORY is True and sbtc.OUTSIDE_RISKPOLICY is True
    assert sbtc.EVIDENCE_LEVEL == "L0"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            mod = getattr(node, "module", None) or ""
            assert "execution" not in mod and not any("execution" in n for n in names)
    code = _code_only(src)
    for forbidden in ("equity_curve_daily", "atomic_save", "RiskPolicy", "execution"):
        assert forbidden not in code, f"{forbidden} is USED, not merely mentioned"
    # and the promises really are made, in the prose, where a reader will find them
    assert "equity_curve_daily" in src and "OUTSIDE_RISKPOLICY" in src


# ───────────── 7. the claims this entry publishes, locked to numbers ─────────────
def test_spearman_is_a_rank_correlation_and_not_a_shape_test():
    """Known inputs. A monotone but non-linear relation must read +1, because the frequency
    question is about ORDER — 'does more flow removed mean a better score' — not about a
    straight line."""
    assert abs(sbtc.spearman([1, 2, 3, 4], [1, 4, 9, 16]) - 1.0) < 1e-12
    assert abs(sbtc.spearman([1, 2, 3, 4], [16, 9, 4, 1]) + 1.0) < 1e-12
    assert abs(sbtc.spearman([1, 1, 1], [3, 2, 1])) < 1e-12  # no spread -> no correlation
    assert abs(sbtc.spearman([1, 2, 2, 3], [1, 2, 2, 3]) - 1.0) < 1e-12  # ties averaged


def _real_frozen_table(mode):
    dates, br = gtn.load_real_panel()
    legs = sbtc.scoring_legs()
    legs = {b: legs[b] for b in sorted(br)}
    n_days = len(dates) - 1
    eq = css._weight_history(br, dates, "eq")
    eq_gross, _ = css._gross_and_turnover(eq, br)
    eq_tau = gtn.leg_turnover(eq, legs)
    eq_calmar = mh._calmar(css._net(eq_gross, eq_tau, sbtc.CONVENTION_COST))
    rows = {}
    for b in sorted(br):
        h, _, _ = sbtc.capped_history(br, dates, mode, [b], 0.0)
        rows[b] = sbtc.score(h, br, legs, eq_calmar, sbtc.CONVENTION_COST, n_days)
    return rows, eq_calmar


@NEEDS_PANEL
def test_the_deciding_control_is_IMPOSSIBLE_because_the_ordered_book_has_the_lowest_floor():
    """The central caveat of the entry, locked to the data.

    A matched-flow comparison cannot be built: freezing the ordered book removes MORE flow
    than freezing any other name can, even at that name's own limit. The moment some other
    book's floor drops below it, the match becomes possible and this test must be re-read —
    which is exactly when the entry's headline caveat stops being true.
    """
    for mode, _ in css.ARMS:
        rows, _ = _real_frozen_table(mode)
        floors = sorted((r.leg_to_yr, b) for b, r in rows.items())
        assert floors[0][1] == sbtc.ORDERED_BOOK, (mode, floors[:2])


@NEEDS_PANEL
def test_the_frequency_law_explains_the_ranking_which_is_why_this_is_NOT_an_edge():
    """The verdict of #89, stated as a number rather than as a mood.

    Across the ten single-book freezes, flow removed and score are strongly rank-correlated
    on every arm. That is #50 for the fifth time, and it is the reason the ordered book's
    1/10 rank is NOT evidence that the NAME carries information.
    """
    for mode, _ in css.ARMS:
        rows, _ = _real_frozen_table(mode)
        books = sorted(rows)
        rho = sbtc.spearman([rows[b].leg_to_yr for b in books],
                            [rows[b].dcalmar for b in books])
        assert rho < -0.6, (mode, rho)


@NEEDS_PANEL
def test_the_one_cell_where_the_frequency_law_FAILS_is_the_only_thing_left_to_chase():
    """h60 / eth_directional: freezing it removes 28 % of the arm's flow and makes Calmar
    WORSE than not capping at all. Under a pure frequency law that cell cannot exist. It is
    one cell — an order for the next test, not an edge — and the entry says so."""
    rows, _ = _real_frozen_table("h60")
    raw = -1.23  # h60 uncapped dCalmar, the published cell of #88
    assert rows["eth_directional"].leg_to_yr < 0.75 * 14.38
    assert rows["eth_directional"].dcalmar < raw, rows["eth_directional"].dcalmar


@NEEDS_PANEL
def test_kappa_infinite_reproduces_88s_published_cells_on_the_real_panel():
    """Anchor to numbers that are already in the registry. If these two cells drift, either
    this harness or #88's table is wrong, and the branch cannot be read as one series."""
    dates, br = gtn.load_real_panel()
    legs = sbtc.scoring_legs()
    legs = {b: legs[b] for b in sorted(br)}
    n_days = len(dates) - 1
    eq = css._weight_history(br, dates, "eq")
    eq_gross, _ = css._gross_and_turnover(eq, br)
    eq_tau = gtn.leg_turnover(eq, legs)
    eq_calmar = mh._calmar(css._net(eq_gross, eq_tau, sbtc.CONVENTION_COST))
    assert abs(eq_calmar - 3.24) < 0.01
    for mode, apy_88, dcal_88 in (("h5", -0.6250, -3.93), ("h60", 0.1761, -1.23)):
        h, _, _ = sbtc.capped_history(br, dates, mode, [sbtc.ORDERED_BOOK], float("inf"))
        r = sbtc.score(h, br, legs, eq_calmar, sbtc.CONVENTION_COST, n_days)
        assert abs(r.apy - apy_88) < 0.0005, (mode, r.apy)
        assert abs(r.dcalmar - dcal_88) < 0.01, (mode, r.dcalmar)


@NEEDS_PANEL
def test_a_global_cap_degenerates_into_refusals_and_is_labelled_as_such():
    """Section 4 calls itself switch suppression rather than 'the same slowing spread over
    everyone'. That label is only honest if refusals really do dominate — checked here."""
    dates, br = gtn.load_real_panel()
    books = sorted(br)
    _, bound, refused = sbtc.capped_history(br, dates, "h5", books, 0.17)
    assert refused > bound, (bound, refused)
    # and the limits still behave: kappa=0 freezes the first vector with no refusal at all
    hist0, _, refused0 = sbtc.capped_history(br, dates, "h5", books, 0.0)
    assert refused0 == 0 and all(day == hist0[0] for day in hist0)


@NEEDS_PANEL
def test_a_small_impact_charge_costs_more_than_every_measured_effect_of_the_branch():
    """THE CVX VERDICT. gamma=48 bps on tau**1.5 takes more Calmar off h60 than the largest
    effect #79-#88 ever measured (+0.73, and that one failed its own control). A branch whose
    findings are smaller than its unmeasured cost-model uncertainty is not fundable yet."""
    dates, br = gtn.load_real_panel()
    legs = sbtc.scoring_legs()
    legs = {b: legs[b] for b in sorted(br)}
    eq = css._weight_history(br, dates, "eq")
    eq_gross, _ = css._gross_and_turnover(eq, br)
    eq_tau = gtn.leg_turnover(eq, legs)
    h, _, _ = sbtc.capped_history(br, dates, "h60", [sbtc.ORDERED_BOOK], float("inf"))
    gross, _ = css._gross_and_turnover(h, br)
    tau = gtn.leg_turnover(h, legs)
    d = {}
    for gamma in (0.0, 48.0):
        base = mh._calmar(sbtc.convex_net(eq_gross, eq_tau, sbtc.CONVENTION_COST, gamma))
        d[gamma] = mh._calmar(sbtc.convex_net(gross, tau, sbtc.CONVENTION_COST, gamma)) - base
    assert d[0.0] - d[48.0] > 0.73, d
    # equal-weight itself is untouched by gamma: it does not trade, so the whole gap is the
    # active arm's own bill and none of it is a moving baseline
    a = mh._calmar(sbtc.convex_net(eq_gross, eq_tau, sbtc.CONVENTION_COST, 0.0))
    b = mh._calmar(sbtc.convex_net(eq_gross, eq_tau, sbtc.CONVENTION_COST, 768.0))
    assert abs(a - b) < 1e-12
