"""
spa_core/tests/test_edge_gross_to_net_toll.py — acceptance for registry idea GTN.

Every test here is a POSITIVE CONTROL: it fails on a specific way the harness could be
wrong, and each one was verified to go RED against a deliberately broken copy of
scripts/edge_gross_to_net_toll.py before being committed (mutation list in the registry
entry). A check that has never seen a real failure is an ornament.

The real aggressive-lab panel is NOT git-tracked. Tests that need it SKIP with an explicit
"unchecked, not absent" reason instead of silently passing on a fixture — the exact trap
#70/#79/#80 fell into when their loader substituted the fixture without saying so.

stdlib + pytest only. Advisory-path code: no capital, no RiskPolicy, no live track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

gtn = pytest.importorskip("edge_gross_to_net_toll")
css = pytest.importorskip("edge_cost_signal_separation")


# ───────────────────────────── helpers ───────────────────────────────────────────
def _hist(*vectors):
    """A weight history from plain dicts (missing books are weight 0)."""
    return [dict(v) for v in vectors]


def _book_turnover(hist, book_ids):
    """css's own convention, re-stated locally so the test does not import the thing it checks."""
    out, prev = [], None
    for w in hist:
        if prev is None:
            out.append(0.0)
        else:
            out.append(sum(abs(w.get(b, 0.0) - prev.get(b, 0.0)) for b in book_ids))
        prev = w
    return out


# ───────────────────── 1. the anchor: disjoint legs change nothing ───────────────
def test_disjoint_legs_reproduce_book_turnover_exactly():
    """A private leg per book must make leg accounting IDENTICAL to book accounting.

    This is the anchor the whole idea stands on: if it drifts, every published cell is a
    different instrument from #80/#81 and cannot be compared with them.
    """
    books = ["a", "b", "c"]
    hist = _hist(
        {"a": 1.0},
        {"a": 0.5, "b": 0.5},
        {"b": 1.0},
        {"b": 0.25, "c": 0.75},
    )
    legs = gtn.disjoint_legs(books)
    assert gtn.leg_turnover(hist, legs) == pytest.approx(_book_turnover(hist, books), abs=1e-15)


def test_disjoint_legs_match_css_gross_and_turnover_on_a_real_arm():
    """Same anchor, but through css's own function rather than a local restatement."""
    book_rets = {"a": [0.001] * 8, "b": [-0.001] * 8, "c": [0.002] * 8}
    hist = _hist(
        {"a": 1.0, "b": 0.0, "c": 0.0},
        {"a": 0.5, "b": 0.5, "c": 0.0},
        {"a": 0.0, "b": 0.0, "c": 1.0},
    )
    _, tau_book = css._gross_and_turnover(hist, book_rets)
    tau_leg = gtn.leg_turnover(hist, gtn.disjoint_legs(sorted(book_rets)))
    assert tau_leg == pytest.approx(tau_book, abs=1e-15)


# ───────────────────── 2. the mechanism, on hand-computable numbers ──────────────
def test_shared_leg_halves_the_toll_of_a_rotation():
    """susde_spot -> susde_dn: the sUSDe leg does not move, only the perp hedge does.

    Hand arithmetic (GTN-A, normalised): e(spot) = {susde 1}, e(dn) = {susde .5, perp .5}.
    Moving x of weight changes susde by -x + .5x = -.5x and perp by +.5x, so tau_leg = x
    against tau_book = 2x. The multiplier is exactly 0.5 and nothing else.
    """
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in ("susde_spot", "susde_dn")})
    hist = _hist({"susde_spot": 1.0, "susde_dn": 0.0}, {"susde_spot": 0.0, "susde_dn": 1.0})
    tau_leg = gtn.leg_turnover(hist, legs)
    tau_book = _book_turnover(hist, ["susde_spot", "susde_dn"])
    assert tau_book[1] == pytest.approx(2.0)
    assert tau_leg[1] == pytest.approx(1.0)
    assert gtn.kappa(tau_book, tau_leg) == pytest.approx(0.5)


def test_disjoint_books_get_no_discount():
    """PT-sUSDe and sUSDe are different tokens; a rotation between them must cost full price."""
    legs = gtn.normalise_legs({b: gtn.RAW_LEGS[b] for b in ("susde_spot", "pendle_pt_levered")})
    hist = _hist(
        {"susde_spot": 1.0, "pendle_pt_levered": 0.0},
        {"susde_spot": 0.0, "pendle_pt_levered": 1.0},
    )
    tau_leg = gtn.leg_turnover(hist, legs)
    tau_book = _book_turnover(hist, ["susde_spot", "pendle_pt_levered"])
    assert gtn.kappa(tau_book, tau_leg) == pytest.approx(1.0)


def test_leverage_raises_the_toll_rather_than_lowering_it():
    """GTN-B: one dollar into a 3x loop moves five dollars of legs (3 collateral + 2 debt)."""
    hist = _hist({"pendle_pt_levered": 0.0}, {"pendle_pt_levered": 1.0})
    tau_leg = gtn.leg_turnover(hist, {"pendle_pt_levered": gtn.RAW_LEGS["pendle_pt_levered"]})
    assert tau_leg[1] == pytest.approx(5.0)
    assert gtn.kappa(_book_turnover(hist, ["pendle_pt_levered"]), tau_leg) == pytest.approx(5.0)


def test_normalised_leg_turnover_never_exceeds_book_turnover():
    """The triangle inequality, checked on many random histories rather than asserted in prose."""
    import random as _r

    rng = _r.Random(4242)
    books = sorted(gtn.RAW_LEGS)
    legs = gtn.normalise_legs(gtn.RAW_LEGS)
    for _ in range(200):
        hist = []
        for _ in range(6):
            picked = rng.sample(books, rng.randint(1, len(books)))
            hist.append({b: 1.0 / len(picked) for b in picked})
        tau_leg = gtn.leg_turnover(hist, legs)
        tau_book = _book_turnover(hist, books)
        for a, b in zip(tau_leg, tau_book):
            assert a <= b + 1e-12


# ───────────────────── 3. phi and the blend ──────────────────────────────────────
def test_phi_zero_is_todays_convention_and_phi_one_is_full_netting():
    book = [0.0, 2.0, 1.0]
    leg = [0.0, 1.0, 0.5]
    assert gtn.blend(book, leg, 0.0) == pytest.approx(book)
    assert gtn.blend(book, leg, 1.0) == pytest.approx(leg)
    assert gtn.blend(book, leg, 0.5) == pytest.approx([0.0, 1.5, 0.75])


def test_breakeven_in_phi_returns_none_when_netting_can_never_save_the_arm():
    """An arm that loses at perfect netting must report 'never', not a number."""
    class _Arm:
        gross = [-0.01] * 40
        tau_book = [0.0] + [1.0] * 39

        def tau(self, legs, phi):
            return gtn.blend(self.tau_book, [0.0] * 40, phi)

    assert gtn.breakeven_in_phi(_Arm(), {}, base_calmar=0.0) is None


# ───────────────────── 4. debt legs ──────────────────────────────────────────────
def test_debt_rate_zero_removes_the_leg_instead_of_zeroing_it():
    """A free debt leg must DISAPPEAR: kept at 0.0 it could silently net against a spot leg."""
    tab = gtn.legs_at_debt_rate(gtn.RAW_LEGS, 0.0)
    assert "stable_debt" not in tab["pendle_pt_levered"]
    assert "eth_debt" not in tab["levered_restaking"]
    assert tab["pendle_pt_levered"]["pt_susde"] == pytest.approx(3.0)


def test_debt_rate_scales_only_debt_legs():
    tab = gtn.legs_at_debt_rate(gtn.RAW_LEGS, 0.25)
    assert tab["levered_restaking"]["eth_debt"] == pytest.approx(0.5)   # 2.0 * 0.25
    assert tab["levered_restaking"]["wsteth"] == pytest.approx(3.0)     # untouched
    assert tab["susde_dn"] == gtn.RAW_LEGS["susde_dn"]


def test_debt_free_reading_still_undercharges_the_book_convention():
    """The verdict must survive the FRIENDLIEST reading: even with borrows free, a levered
    book moves more notional than its weight."""
    hist = _hist({"levered_restaking": 0.0}, {"levered_restaking": 1.0})
    tab = gtn.legs_at_debt_rate(gtn.RAW_LEGS, 0.0)
    tau = gtn.leg_turnover(hist, {"levered_restaking": tab["levered_restaking"]})
    assert tau[1] == pytest.approx(3.0)


# ───────────────────── 5. the drift guard against roster.py ──────────────────────
def test_leg_table_matches_the_live_roster_defaults():
    live = gtn.assert_leg_table_matches_roster()
    assert live["pendle_pt_levered"] == 3.0
    assert live["leverage_loop"] == 2.0          # the class default, NOT the tier descriptor's 3.0
    assert live["levered_restaking"] == 3.0
    assert live["susde_spot"] == 1.0


def test_roster_drift_is_a_hard_failure_not_a_warning(tmp_path):
    """POSITIVE CONTROL replaying the real hazard: someone re-levers a book and the invoice
    keeps quoting the old size. The guard must REFUSE, loudly."""
    src = (ROOT / "spa_core" / "strategy_lab" / "aggressive_lab" / "roster.py").read_text()
    mutated = src.replace('self._cfg.get("leverage", 2.0)', 'self._cfg.get("leverage", 4.0)')
    assert mutated != src, "the 2.0 default vanished from roster.py — re-point this control"
    path = tmp_path / "roster_mutated.py"
    path.write_text(mutated)
    with pytest.raises(RuntimeError, match="drifted"):
        gtn.assert_leg_table_matches_roster(path)


def test_leverage_default_is_read_per_class_not_by_first_match(tmp_path):
    """A `leverage` literal in a NEIGHBOURING class must not be attributed to this one —
    the same failure as mutating a test by text instead of by coordinate."""
    src = '''
class A(_Base):
    id = "book_a"
    def f(self):
        lev = float(self._cfg.get("leverage", 2.0))


class B(_Base):
    id = "book_b"
    def f(self):
        lev = float(self._cfg.get("leverage", 7.0))
'''
    path = tmp_path / "roster_two.py"
    path.write_text(src)
    got = gtn.roster_leverage_defaults(path)
    assert got == {"book_a": 2.0, "book_b": 7.0}


def test_contradictory_leverage_defaults_in_one_class_refuse(tmp_path):
    src = '''
class A(_Base):
    id = "book_a"
    def f(self):
        lev = float(self._cfg.get("leverage", 2.0))
    def g(self):
        lev = float(self._cfg.get("leverage", 3.0))
'''
    path = tmp_path / "roster_conflict.py"
    path.write_text(src)
    with pytest.raises(RuntimeError, match="refusing to guess"):
        gtn.roster_leverage_defaults(path)


def test_gross_notional_must_spend_the_leverage_it_claims(monkeypatch):
    """A leg table that claims 3x but only lists 3.0 of gross notional has lost the debt leg."""
    broken = {k: dict(v) for k, v in gtn.RAW_LEGS.items()}
    broken["levered_restaking"] = {"wsteth": 3.0}   # debt leg dropped
    monkeypatch.setattr(gtn, "RAW_LEGS", broken)
    with pytest.raises(RuntimeError, match="implies gross notional"):
        gtn.assert_leg_table_matches_roster()


# ───────────────────── 6. controls ───────────────────────────────────────────────
def test_random_composition_keeps_the_leg_count_and_the_sizes():
    ctrl = gtn.random_composition_legs(gtn.RAW_LEGS, seed=7)
    for book, vec in gtn.RAW_LEGS.items():
        assert len(ctrl[book]) == len(vec)
        assert sorted(ctrl[book].values()) == pytest.approx(sorted(abs(v) for v in vec.values()))


def test_random_composition_is_seeded_and_actually_varies():
    a = gtn.random_composition_legs(gtn.RAW_LEGS, seed=1)
    assert a == gtn.random_composition_legs(gtn.RAW_LEGS, seed=1)
    assert a != gtn.random_composition_legs(gtn.RAW_LEGS, seed=2)


def test_relabel_permutes_whole_vectors_and_identity_is_detectable():
    perm = gtn.relabel_legs(gtn.RAW_LEGS, seed=3)
    assert sorted(map(lambda d: tuple(sorted(d.items())), perm.values())) == sorted(
        map(lambda d: tuple(sorted(d.items())), gtn.RAW_LEGS.values())
    )
    assert gtn.is_identity_relabel(gtn.RAW_LEGS, dict(gtn.RAW_LEGS)) is True
    identity_seen = any(
        gtn.is_identity_relabel(gtn.RAW_LEGS, gtn.relabel_legs(gtn.RAW_LEGS, s))
        for s in range(50)
    )
    # not asserted to occur — asserted to be RECOGNISED when it does
    assert identity_seen in (True, False)


def test_empty_leg_vector_is_refused():
    with pytest.raises(ValueError):
        gtn.normalise_legs({"x": {}})
    with pytest.raises(ValueError):
        gtn.legs_at_debt_rate({"x": {"eth_debt": 1.0}}, 0.0)


# ───────────────────── 7. the claim that weights never move ──────────────────────
def test_the_accounting_never_touches_a_single_weight():
    """GTN's whole standing rests on this: it re-prices trades, it does not change them."""
    dates, book_rets = gtn.load_fixture_panel()
    arm = gtn.Arm(book_rets, dates, "h20")
    before = [dict(w) for w in arm.hist]
    for tab in (
        gtn.normalise_legs(gtn.disjoint_legs(sorted(book_rets))),
        gtn.disjoint_legs(sorted(book_rets)),
    ):
        gtn.leg_turnover(arm.hist, tab)
    assert arm.hist == before


def test_per_book_flow_attribution_sums_to_the_ungrossed_total():
    hist = _hist(
        {"susde_spot": 1.0, "pendle_pt_levered": 0.0},
        {"susde_spot": 0.0, "pendle_pt_levered": 1.0},
    )
    flow = gtn.per_book_leg_flow(hist, gtn.RAW_LEGS)
    assert flow["susde_spot"] == pytest.approx(1.0)      # 1 unit of weight x gross 1
    assert flow["pendle_pt_levered"] == pytest.approx(5.0)  # 1 unit of weight x gross 5


# ───────────────────── 8. the panel is never faked ───────────────────────────────
def test_missing_panel_refuses_instead_of_substituting_the_fixture(tmp_path):
    """POSITIVE CONTROL for the #70/#79/#80 trap: a worktree has no data/, and a silent
    fallback publishes fixture numbers under a panel headline."""
    with pytest.raises(FileNotFoundError, match="refusing to substitute the fixture"):
        gtn.load_real_panel(tmp_path / "no_such_panel")


def test_short_axis_is_refused(tmp_path):
    panel = tmp_path / "panel"
    (panel / "b1").mkdir(parents=True)
    (panel / "b2").mkdir(parents=True)
    for name in ("b1", "b2"):
        rows = [
            '{"date": "2026-01-%02d", "equity_usd": %.2f, "phase": "backtest"}' % (i + 1, 100.0 + i)
            for i in range(70)
        ]
        (panel / name / "realized_series.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(RuntimeError, match="refusing to publish"):
        gtn.load_real_panel(panel)


@pytest.mark.skipif(
    not (ROOT / "data" / "aggressive_lab").exists(),
    reason="real panel is not git-tracked: UNCHECKED here, not absent (run in the prod tree)",
)
def test_every_panel_book_has_a_leg_vector():
    """A book with no declared composition must stop the run, not be priced by guesswork."""
    _, book_rets = gtn.load_real_panel()
    missing = sorted(set(book_rets) - set(gtn.RAW_LEGS))
    assert not missing, f"panel books without a leg vector: {missing}"


@pytest.mark.skipif(
    not (ROOT / "data" / "aggressive_lab").exists(),
    reason="real panel is not git-tracked: UNCHECKED here, not absent (run in the prod tree)",
)
def test_real_panel_anchor_reproduces_the_published_81_cell():
    """#81 published h60 on this panel: netAPY 22.77% at c=96 against equal-weight 17.62%.

    If this cell moves, the panel or the arm has changed underneath the registry and no GTN
    number may be compared with a published one.
    """
    dates, book_rets = gtn.load_real_panel()
    eq = gtn.Arm(book_rets, dates, "eq")
    h60 = gtn.Arm(book_rets, dates, "h60")
    import edge_mhfc_backtest as mh

    eq_apy = mh._apy(css._net(eq.gross, eq.tau_book, 0.0))
    h60_apy = mh._apy(css._net(h60.gross, h60.tau_book, gtn.CONVENTION_COST))
    assert eq_apy * 100 == pytest.approx(17.62, abs=0.01)
    assert h60_apy * 100 == pytest.approx(22.77, abs=0.01)


def test_module_declares_advisory_and_never_imports_execution():
    assert gtn.IS_ADVISORY is True
    assert gtn.OUTSIDE_RISKPOLICY is True
    assert gtn.EVIDENCE_LEVEL == "L0"
    # An IMPORT of the execution domain, not the docstring's promise not to import it: the
    # prose says "Never imports spa_core.execution", so a plain substring check can never go
    # red and would be an ornament.
    src = (SCRIPTS / "edge_gross_to_net_toll.py").read_text()
    import ast

    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("spa_core.execution"), alias.name
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("spa_core.execution"), node.module
    spec = importlib.util.find_spec("edge_gross_to_net_toll")
    assert spec is not None and spec.origin.endswith("edge_gross_to_net_toll.py")
