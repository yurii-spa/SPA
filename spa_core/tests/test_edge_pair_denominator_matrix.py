"""Controls for scripts/edge_pair_denominator_matrix.py — registry #140 (PDM) and #141 (TUB).

Every test is a POSITIVE CONTROL for a defect this class has already produced on this panel:

  * #122/#126/#128/#129/#131/#137 each caught a rule funding a book whose "lowest tail" is an
    ABSENCE OF OBSERVATION. §1 must keep the three outcomes apart, and it must keep the TWO
    refusal gates apart from each other: "no fall was seen" and "the fall seen is shallower than
    the fee" are different facts, and #137 is the entry that paid for confusing them.
    -> test_first_gate_*, test_second_gate_*, test_two_gates_are_distinguishable
  * #137 printed `calmar = apy/maxdd if max_dd > 1e-9 else 999.99`, i.e. a vanished denominator
    as the LARGEST number of its table. Nothing here may publish a ratio over a refused
    denominator. -> test_refused_denominator_never_becomes_a_number
  * #129 made "the rule is worse" and "there is nothing to measure" mandatory to distinguish.
    The matrix therefore has THREE cell verdicts, and a panel with no surviving pair must REFUSE
    with a named reason rather than print an empty table as a clean pass.
    -> test_matrix_refuses_with_a_reason_when_no_pair_survives, test_cell_blames_the_right_gate
  * a rank correlation computed over a column with a hole is #465's defect exactly: not measured,
    dressed as a number. -> test_transfer_refuses_over_a_refused_cell
  * look-ahead is the standing failure of every sizer in this series: the day being sized must
    never be inside the window that sizes it. -> test_tub_bounds_are_causal
  * #141's own denominator must not be able to vanish, and where it HAS no input it must be None
    rather than 0.0 (inv. #17) -- a bound of 0.0 is an infinite weight.
    -> test_bound_is_none_not_zero_when_no_magnitude_exists, test_empty_window_bound_is_none
  * a new loop that silently disagrees with the loop whose numbers are published is how a
    "better" result gets manufactured. #141's loop must reproduce
    edge_admitted_set_guardian_zero.run_sizer_rule BITWISE on the two rules they share.
    -> test_equivalence_with_the_published_loop_*
  * "panel absent" is a third outcome with a named reason and a non-zero exit, never a clean
    pass. -> test_missing_panel_is_not_measured, test_main_exits_nonzero_without_a_panel

The panel is BUILT HERE, in tmp, and never read from data/: data/aggressive_lab is runtime-only
(gitignored), so a test that reached for it would be green on this Mac and "NOT MEASURED" in CI.
The real-panel numbers of #140/#141 live in the registry entry, which names the command that
produced them.
"""
# FROZEN-DATE-OK: panel-axis-and-oos-seam — the literal dates ARE the subject, preference #3 of
# .claude/rules/deployment.md. #140's entire question is measurability on either side of the
# harness's OOS seam, so the panel's axis (START) has to straddle a FIXED seam; a relative axis
# would move the seam under the question. The seam itself is never retyped here -- it is read off
# the harness (`TRAIN_END`), asserted by test_seam_is_read_from_the_harness_not_retyped. There is
# no freshness horizon and no wall clock anywhere in the measured path: nothing is judged against
# today, which is why the `injected-clock` reason would be a false claim rather than a stronger
# one (cycle #477: a note is not an injection).
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import statistics
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_pair_denominator_matrix.py"
GZ_SCRIPT = ROOT / "scripts" / "edge_admitted_set_guardian_zero.py"

N_DAYS = 700
START = "2024-03-06"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot import {path}"
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def mod():
    return _load(SCRIPT, "edge_pair_denominator_matrix")


@pytest.fixture(scope="module")
def gz():
    return _load(GZ_SCRIPT, "edge_admitted_set_guardian_zero")


def _dates(n: int, start: str = START):
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _write_book(root: Path, rets) -> None:
    """One book in the producer's own accounting shape: equity, phase=backtest."""
    root.mkdir(parents=True, exist_ok=True)
    dates = _dates(len(rets) + 1)
    eq = 100_000.0
    lines = []
    for i, d in enumerate(dates):
        if i:
            eq *= 1.0 + rets[i - 1]
        lines.append(json.dumps({
            "as_of": d, "date": d, "equity_usd": round(eq, 8), "phase": "backtest",
            "killed": False, "is_advisory": True, "outside_riskpolicy": True,
            "net_apy_pct": 0.0, "mtm_today_pct": 0.0,
        }))
    (root / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


N = N_DAYS - 1


def _two_sided_a(n: int = N):
    """Carry with a REAL drawdown in both halves, deeper than the 0.96 % toll."""
    out = []
    for i in range(n):
        if 100 <= i < 120 or 550 <= i < 570:
            out.append(-0.004)
        else:
            out.append(0.0012)
    return out


def _two_sided_b(n: int = N):
    """A second carrier with a real two-sided shape, falling on DIFFERENT days."""
    out = []
    for i in range(n):
        if 300 <= i < 325 or 600 <= i < 615:
            out.append(-0.005)
        else:
            out.append(0.0010)
    return out


def _thin_tail(n: int = N):
    """Down days ARE observed, but the deepest fall is shallower than the entry fee.

    This is the shape the SECOND gate exists for, and the real panel has two of them
    (`susde_dn` 0.01 %/0.05 %, `pendle_yt_susde` 0.23 %/0.89 %).
    """
    return [(-0.00002 if i in (150, 400, 600) else 0.0003) for i in range(n)]


def _monotone(n: int = N):
    """Not one day below zero: the book whose tail is an absence of observation."""
    return [0.0003 + 0.0002 * ((i % 7) / 7.0) for i in range(n)]


def _train_only(n: int = N):
    """Falls in TRAIN, never in TEST — a book that survives exactly one half."""
    return [(-0.01 if 200 <= i < 230 else (0.002 if i < 460 else 0.0)) for i in range(n)]


@pytest.fixture(scope="module")
def panel(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("panel_pdm")
    _write_book(root / "carry_tail_a", _two_sided_a())
    _write_book(root / "carry_tail_b", _two_sided_b())
    _write_book(root / "thin_tail", _thin_tail())
    _write_book(root / "monotone_up", _monotone())
    _write_book(root / "train_only", _train_only())
    return root


@pytest.fixture(scope="module")
def report(mod, panel):
    return mod.pdm_report(panel, lookback=30)


@pytest.fixture(scope="module")
def loaded(mod, panel):
    return mod.load_axis(panel)


# ═════════════════════ §1 · the two gates, and telling them apart ═════════════════════
def test_first_gate_refuses_a_book_that_never_fell(report):
    """A monotone book has NOT drawn down 0.0 — it has not been observed drawing down."""
    h = report["legs"]["rows"]["monotone_up"]["halves"]
    for half in ("TRAIN", "TEST"):
        assert h[half]["status"] == "unmeasured_monotone", half
        assert h[half]["maxdd"] is None, "a refused drawdown must be None, never 0.0"
        assert h[half]["survives"] is False
    assert "monotone_up" not in report["legs"]["survivors"]


def test_second_gate_refuses_a_fall_shallower_than_the_fee(report):
    """Down days observed, but maxDD < toll: the ratio would be an artefact of division."""
    h = report["legs"]["rows"]["thin_tail"]["halves"]
    for half in ("TRAIN", "TEST"):
        assert h[half]["status"] == "measured", f"{half}: the fixture must OBSERVE falls here"
        assert h[half]["down_days"] >= 1
        assert h[half]["degenerate"] is not None, f"{half}: gate 2 must fire"
        assert "round-trip toll" in h[half]["degenerate"]
        assert h[half]["survives"] is False
    assert "thin_tail" not in report["legs"]["survivors"]


def test_two_gates_are_distinguishable(report):
    """#137 paid for confusing "not seen falling" with "fell less than the fee"."""
    mono = report["legs"]["rows"]["monotone_up"]["halves"]["TEST"]
    thin = report["legs"]["rows"]["thin_tail"]["halves"]["TEST"]
    assert mono["status"] != thin["status"]
    assert mono["degenerate"] is not None and mono["maxdd"] is None
    assert thin["degenerate"] is not None and thin["maxdd"] is not None, (
        "the thin-tail book DID produce a measured drawdown; erasing it would merge the two "
        "gates and hide which one refused")


def test_a_book_can_survive_one_half_and_not_the_other(report):
    h = report["legs"]["rows"]["train_only"]["halves"]
    assert h["TRAIN"]["survives"] is True
    assert h["TEST"]["survives"] is False
    assert report["legs"]["rows"]["train_only"]["survives_both"] is False


def test_both_carriers_survive_both_halves(report):
    assert report["legs"]["survivors"] == ["carry_tail_a", "carry_tail_b"], (
        "the fixture must produce exactly the pair the matrix is then expected to find; "
        "otherwise the matrix tests below cannot see the defect they exist for")


def test_refused_denominator_never_becomes_a_number(report):
    """No row anywhere in the report may carry a Calmar over a refused denominator."""
    for b, row in report["legs"]["rows"].items():
        for half, h in row["halves"].items():
            if h["maxdd"] is None:
                assert h["degenerate"] is not None, (b, half)
    for comp in report["composition"]:
        for half in comp["rows"]:
            for cell in comp["rows"][half]:
                if cell["degenerate"] is not None and cell["calmar"] is not None:
                    assert cell["status"] == "measured"
                if cell["maxdd"] is None:
                    assert cell["calmar"] is None, "ratio printed over a missing denominator"
    for r in report["tub"]["table"]:
        if r["maxdd"] is None:
            assert r["calmar"] is None


# ═════════════════════════════ §2 · the matrix ═════════════════════════════
def test_matrix_is_square_and_covers_every_pair(report, loaded):
    books = loaded["books"]
    cells = report["matrix"]["cells"]
    assert set(cells) == set(books)
    for a in books:
        assert set(cells[a]) == set(books) - {a}, a
    assert report["matrix"]["n_pairs_total"] == len(books) * (len(books) - 1) // 2


def test_matrix_finds_exactly_the_surviving_pair(mod, report):
    assert report["matrix"]["surviving_pairs"] == [("carry_tail_a", "carry_tail_b")]
    assert report["matrix"]["n_pairs_surviving"] == 1
    assert report["matrix"]["refusal_reason"] is None
    assert (report["matrix"]["cells"]["carry_tail_a"]["carry_tail_b"]["verdict"]
            == mod.CELL_OK)


def test_cell_blames_the_right_gate(mod, report):
    """A pair refused by a LEG and a pair refused by ITSELF are different findings."""
    cell = report["matrix"]["cells"]["carry_tail_a"]["monotone_up"]
    assert cell["verdict"] == mod.CELL_LEGS
    assert cell["blocked_by"] == ["monotone_up"], (
        "the cell must name WHICH leg refused, not just that one did")


def test_pair_refused_by_itself_is_a_separate_verdict(mod, panel, tmp_path):
    """Both legs fall deeper than the fee, yet their 50/50 never falls at all.

    This is the cell verdict the real panel does not happen to contain, so it is BUILT: two
    mirror-image legs whose average is monotone. Without this control `pair_refused` would be
    an unreachable branch, and an unreachable branch is not a measurement.
    """
    root = tmp_path / "mirror"
    a = [(0.04 if i % 2 == 0 else -0.02) for i in range(N)]
    b = [(-0.02 if i % 2 == 0 else 0.04) for i in range(N)]
    _write_book(root / "mirror_a", a)
    _write_book(root / "mirror_b", b)
    _write_book(root / "monotone_up", _monotone())
    L = mod.load_axis(root)
    legs = mod.legs_report(L["rets"], L["books"], L["halves"])
    assert set(legs["survivors"]) == {"mirror_a", "mirror_b"}, legs["survivors"]
    cell = mod.pair_cell(L["rets"], "mirror_a", "mirror_b", L["halves"], legs)
    assert cell["verdict"] == mod.CELL_PAIR, cell
    assert "both legs judgeable" in cell["reason"]


def test_matrix_refuses_with_a_reason_when_no_pair_survives(mod, tmp_path):
    """An empty table is NOT a clean pass — the acceptance criterion of order #137 allows a
    refusal only WITH a named reason."""
    root = tmp_path / "nopairs"
    _write_book(root / "monotone_up", _monotone())
    _write_book(root / "monotone_two", [0.0002] * N)
    _write_book(root / "thin_tail", _thin_tail())
    L = mod.load_axis(root)
    legs = mod.legs_report(L["rets"], L["books"], L["halves"])
    m = mod.pair_matrix(L["rets"], L["books"], L["halves"], legs)
    assert m["n_pairs_surviving"] == 0
    assert m["surviving_pairs"] == []
    assert m["refusal_reason"], "a zero count without a reason is NOT MEASURED dressed as clean"


# ═════════════════════════ §3 · composition and its transfer ═════════════════════════
def test_composition_is_measured_only_on_survivors(report):
    assert [c["pair"] for c in report["composition"]] == [["carry_tail_a", "carry_tail_b"]]


def test_blend_grid_includes_both_pure_legs(mod, report):
    ws = [c["w_a"] for c in report["composition"][0]["rows"]["TRAIN"]]
    assert ws[0] == 0.0 and ws[-1] == 1.0
    assert len(ws) == len(mod.BLEND_GRID)


def test_transfer_names_the_corner_or_the_interior(report):
    t = report["composition"][0]["transfer"]
    assert t["status"] == "measured"
    assert -1.0 <= t["spearman"] <= 1.0
    assert isinstance(t["train_interior_optimum"], bool)
    assert 1 <= t["argmax_train_rank_on_test"] <= t["n_cells"]


def test_transfer_refuses_over_a_refused_cell(mod, tmp_path):
    """A spearman over a column with a hole is a number about nothing (#465)."""
    root = tmp_path / "holey"
    _write_book(root / "mirror_a", [(0.04 if i % 2 == 0 else -0.02) for i in range(N)])
    _write_book(root / "mirror_b", [(-0.02 if i % 2 == 0 else 0.04) for i in range(N)])
    _write_book(root / "pad", _two_sided_a())
    L = mod.load_axis(root)
    comp = mod.blend_sweep(L["rets"], "mirror_a", "mirror_b", L["halves"])
    refused = [c for h in comp["rows"] for c in comp["rows"][h] if c["degenerate"] is not None]
    assert refused, "the fixture produced no refused blend cell — this test sees nothing"
    assert comp["transfer"]["status"] == "unmeasured"
    assert comp["transfer"]["spearman"] is None
    assert "hole" in comp["transfer"]["reason"]


def test_blend_reports_its_own_cap_violation(report):
    """Every interior cell of a two-name blend breaks the 20 %/name ceiling by construction;
    §3 answers measurability, not deployability, and must say so in the data."""
    rows = report["composition"][0]["rows"]["TEST"]
    assert any(c["cap_violation"] for c in rows), (
        "a two-book blend that reports no cap violation is hiding that it is not deployable")


# ═════════════════════════ §4 · TUB: the bound and its honesty ═════════════════════════
def test_rule_of_three_closed_form(mod):
    """d == 0 must be the EXACT closed form, not a bisection approximation."""
    for n in (30, 90, 365, 852):
        assert mod.cp_upper(n, 0, 0.05) == pytest.approx(1.0 - 0.05 ** (1.0 / n), rel=1e-15)
    assert mod.cp_upper(100, 0, 0.05) == pytest.approx(0.02951, abs=1e-5)


def test_bound_decreases_with_evidence_and_with_confidence(mod):
    """More days seen without a fall ⇒ a tighter bound. More confidence demanded ⇒ a looser one."""
    bounds = [mod.cp_upper(n, 0, 0.05) for n in (30, 90, 180, 365, 852)]
    assert bounds == sorted(bounds, reverse=True)
    alphas = [mod.cp_upper(365, 0, a) for a in (0.32, 0.10, 0.05, 0.01, 1e-8)]
    assert alphas == sorted(alphas)


def test_clopper_pearson_matches_its_definition(mod):
    """The bisected branch must satisfy P(X <= d | n, p_hi) == alpha."""
    for n, d in ((50, 5), (120, 40), (482, 175)):
        p = mod.cp_upper(n, d, 0.05)
        assert mod.binom_tail_le(n, d, p) == pytest.approx(0.05, abs=1e-6), (n, d)
        assert d / n < p < 1.0


def test_binomial_tail_survives_a_window_that_overflows_naive_arithmetic(mod):
    """math.comb(482, 175) * p**175 overflows in float; log space must not."""
    v = mod.binom_tail_le(482, 175, 0.4)
    assert 0.0 <= v <= 1.0 and v == v  # not NaN
    assert mod.binom_tail_le(10, 10, 0.5) == pytest.approx(1.0)
    assert mod.binom_tail_le(10, 0, 0.5) == pytest.approx(0.5 ** 10)


def test_empty_window_bound_is_none(mod):
    """A bound over no observations is NOT MEASURED — handing back a float would let a sizer
    weight a book it has never seen (inv. #17)."""
    assert mod.cp_upper(0, 0, 0.05) is None
    with pytest.raises(ValueError):
        mod.cp_upper(100, 0, 0.0)


def test_tub_bounds_are_causal(mod, loaded):
    """The day being sized must never be inside the window that sizes it."""
    rets = {b: list(v) for b, v in loaded["rets"].items()}
    before = mod.tub_bounds(rets, loaded["books"], end=400, lookback=30)
    rets["carry_tail_a"][400] = -0.95
    rets["carry_tail_a"][450] = -0.95
    after = mod.tub_bounds(rets, loaded["books"], end=400, lookback=30)
    assert before["books"] == after["books"], (
        "a future day changed today's bound — this is look-ahead")


def test_magnitude_kind_is_labelled_measured_or_modelled(mod, loaded):
    """The label follows the WINDOW, not the book: `carry_tail_a` falls at days 100-120 and
    550-570, so over [0, 200) its magnitude is observed and over [200, 400) it is not. A label
    attached to the book rather than to the window would be a claim about the series, not a
    statement about what this window saw."""
    early = mod.tub_bounds(loaded["rets"], loaded["books"], end=200, lookback=200)["books"]
    assert early["carry_tail_a"]["kind"] == "measured_magnitude"
    assert early["carry_tail_a"]["down"] > 0
    assert early["carry_tail_b"]["kind"] == "modelled_magnitude", (
        "carry_tail_b does not fall until day 300 — in this window it has NOT been seen falling")
    assert early["monotone_up"]["kind"] == "modelled_magnitude", (
        "a book with no observed fall has no observed magnitude; borrowing the panel's must be "
        "declared, never passed off as measurement (ADR-580 C2)")
    assert early["monotone_up"]["down"] == 0 and early["monotone_up"]["bound"] > 0.0
    late = mod.tub_bounds(loaded["rets"], loaded["books"], end=400, lookback=200)["books"]
    assert late["carry_tail_a"]["kind"] == "modelled_magnitude", (
        "the same book over a window with no fall must flip to modelled, or the label is about "
        "the book and not about the evidence")


def test_bound_is_none_not_zero_when_no_magnitude_exists(mod, tmp_path):
    """If NOT ONE book fell anywhere in the window there is no magnitude to borrow. A bound of
    0.0 there would be an infinite weight; the honest answer is None."""
    root = tmp_path / "allup"
    _write_book(root / "up_a", _monotone())
    _write_book(root / "up_b", [0.0002] * N)
    _write_book(root / "up_c", [0.0004] * N)
    L = mod.load_axis(root)
    out = mod.tub_bounds(L["rets"], L["books"], end=300, lookback=30)
    assert out["panel_magnitude"] is None
    for b, row in out["books"].items():
        assert row["bound"] is None, b
        assert row["kind"] == "unmeasured_no_panel_magnitude", b
        assert row["p_hi"] is not None, "the PROBABILITY is still boundable — only m is missing"


def test_a_day_with_no_admitted_name_is_refused_not_equal_weighted(mod, tmp_path):
    root = tmp_path / "allup2"
    _write_book(root / "up_a", _monotone())
    _write_book(root / "up_b", [0.0002] * N)
    L = mod.load_axis(root)
    r = mod.run_tub(L["rets"], L["books"], lo=30, hi=200, kind="tub", lookback=30)
    assert r["refused_days"] == 170, (
        "with no magnitude anywhere, every day must be REFUSED; silently falling back to equal "
        "weight is the fail-OPEN this series keeps finding")
    assert r["mean_deployed"] == 0.0


def test_tub_never_breaks_the_policy_ceiling(report):
    S = _load(ROOT / "scripts" / "edge_sigma_floor_ctac_real.py", "sfs")
    for r in report["tub"]["table"]:
        assert r["max_name_weight"] <= S.POLICY_CAP + 1e-12, r["label"]
        assert r["cap_violation_days"] == 0, r["label"]


def test_p1_is_recorded_as_a_verdict_in_both_directions(report):
    """P1 was registered before the run and must be judged, not quietly dropped."""
    p1 = report["tub"]["p1"]
    assert p1["never_fallen"] == ["monotone_up"]
    for half in ("TRAIN", "TEST"):
        d = p1["halves"][half]
        assert isinstance(d["p1_holds"], bool)
        assert d["delta"] == pytest.approx(d["tub_mass"] - d["inv_sigma_mass"])


def test_breakeven_reports_unreachable_rather_than_a_fake_alpha(mod, loaded):
    be = mod.breakeven_alpha(loaded["rets"], loaded["books"])
    assert be["status"] == "measured"
    for b, row in be["rows"].items():
        if row["needed_p_hi"] >= 1.0:
            assert row["status"] == "unreachable" and row["alpha"] is None, b
        else:
            assert row["status"] == "measured" and 0.0 < row["alpha"] <= 1.0, b


def test_breakeven_refuses_a_panel_where_nothing_fell(mod, tmp_path):
    root = tmp_path / "allup3"
    _write_book(root / "up_a", _monotone())
    _write_book(root / "up_b", [0.0002] * N)
    L = mod.load_axis(root)
    be = mod.breakeven_alpha(L["rets"], L["books"])
    assert be["status"] == "unmeasured" and be["panel_magnitude"] is None
    assert "no magnitude" in be["reason"]


def test_unknown_denominator_is_refused(mod, loaded):
    with pytest.raises(ValueError, match="unknown denominator"):
        mod.run_tub(loaded["rets"], loaded["books"], lo=30, hi=100, kind="inv_maxdd",
                    lookback=30)


def test_sizer_refuses_a_start_inside_its_first_window(mod, loaded):
    with pytest.raises(ValueError, match="inside the first"):
        mod.run_tub(loaded["rets"], loaded["books"], lo=10, hi=100, kind="tub", lookback=30)


# ═══════════════ the new loop must not disagree with the published one ═══════════════
def test_equivalence_with_the_published_loop_equal_weight(mod, gz, loaded):
    """#141's loop and `run_sizer_rule` must agree BITWISE where the rule is the same."""
    rets, books = loaded["rets"], loaded["books"]
    mine = mod.run_tub(rets, books, lo=30, hi=400, kind="ew", lookback=30)
    theirs = gz.run_sizer_rule(rets, books, lo=30, hi=400, rule=gz.rule_admit_all,
                               lookback=30, sizer="ew")
    assert mine["apy_net"] == theirs["apy_net"]
    assert mine["maxdd"] == theirs["maxdd"]
    assert mine["turnover_per_day"] == theirs["turnover_per_day"]
    assert mine["mean_weight"] == theirs["mean_weight"]


def test_equivalence_with_the_published_loop_inverse_sigma(mod, gz, loaded):
    rets, books = loaded["rets"], loaded["books"]
    mine = mod.run_tub(rets, books, lo=30, hi=400, kind="inv_sigma", lookback=30)
    theirs = gz.run_sizer_rule(rets, books, lo=30, hi=400,
                               rule=gz.rule_sigma_positive(30), lookback=30,
                               sizer="inv_sigma")
    assert mine["apy_net"] == theirs["apy_net"]
    assert mine["maxdd"] == theirs["maxdd"]
    assert mine["mean_weight"] == theirs["mean_weight"]


def test_thresholds_are_imported_not_retyped(mod):
    """A toll or ceiling copied into this file could drift from the one the series judges by."""
    S = mod.sfs_mod()
    src = SCRIPT.read_text()
    assert "0.0096" not in src, "the round-trip toll must be read from #128's module"
    assert "0.20" not in src.replace("0.20 %", ""), "the ceiling must be imported"
    assert S.ROUNDTRIP == 0.0096 and S.POLICY_CAP == 0.20


def test_seam_is_read_from_the_harness_not_retyped(mod, loaded):
    H = mod.panel_mod()
    assert loaded["seam"] == H.TRAIN_END
    assert "2025-06-30" not in SCRIPT.read_text(), (
        "a retyped seam can drift from the one #137 was measured against")


# ═════════════════════ panel absent is a third outcome, not a pass ═════════════════════
def test_missing_panel_is_not_measured(mod, tmp_path):
    with pytest.raises(RuntimeError, match="NOT MEASURED"):
        mod.load_axis(tmp_path / "does_not_exist")


def test_main_exits_nonzero_without_a_panel(mod, tmp_path, capsys):
    rc = mod.main(["--panel-dir", str(tmp_path / "nope")])
    assert rc == 2, "an unmeasurable run must not exit 0"
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_seam_must_split_the_axis(mod, tmp_path):
    """A panel entirely on one side of the seam cannot answer a transfer question."""
    root = tmp_path / "early"
    short = 300
    for name in ("a", "b"):
        _write_book(root / f"book_{name}", [0.001] * short)
    L_dates = _dates(short + 1)
    assert L_dates[-1] < "2025-06-30", "fixture precondition: the axis ends before the seam"
    with pytest.raises(RuntimeError, match="does not split"):
        mod.load_axis(root)


def test_report_is_pure_and_writes_nothing(mod, panel):
    before = sorted(p.relative_to(panel).as_posix() for p in panel.rglob("*"))
    mod.pdm_report(panel, lookback=30)
    after = sorted(p.relative_to(panel).as_posix() for p in panel.rglob("*"))
    assert before == after, "an advisory report must not write to the panel"


def test_module_declares_advisory_and_outside_riskpolicy(mod):
    assert mod.IS_ADVISORY is True
    assert mod.OUTSIDE_RISKPOLICY is True


def test_printer_never_prints_a_number_for_a_refused_ratio(mod, report, capsys):
    mod.print_report(report)
    out = capsys.readouterr().out
    assert "ОТКАЗАН" in out or "НЕ ИЗМЕРЕН" in out
    assert "999" not in out, "#137's instrument printed a vanished denominator as 999.99"


# ════════════ closing the six mutants that survived the first delta run ════════════
#
# Every test below was written because `scripts/delta_mutation_run.py --spec
# docs/mutations/PDM-140-2026-10-23.json` reported the corresponding mutation as ВЫЖИЛ on the
# first pass. Four were real holes in the tests above, one is a provably EQUIVALENT mutant and is
# documented as such rather than chased, and one needed a window size the sweeps do not reach.
# None of them was closed by weakening the specification (inv. #16).

def test_an_unmeasured_drawdown_is_refused_by_the_toll_gate_too(mod):
    """Why mutant 1 ("ok = degen is None") is EQUIVALENT and not a hole.

    Dropping the `status == "measured"` half of §1's conjunction changes NO behaviour, because
    `calmar_degenerate(None)` already refuses: a ratio cannot be formed over a denominator that
    was never observed. The conjunction is kept as defence in depth, and this test pins the
    property the equivalence rests on -- if `calmar_degenerate` ever started returning None for
    a missing maxDD, the two gates really would come apart and §1 would pass monotone books.
    """
    S = mod.sfs_mod()
    assert S.calmar_degenerate(None) is not None
    assert "not measured" in S.calmar_degenerate(None)


def test_binomial_tail_is_exact_where_naive_arithmetic_dies(mod):
    """Mutant 4 survived because no swept window is large enough to break naive arithmetic.

    `binom_tail_le` is a general function and nothing stops a later caller passing a longer
    window, so its contract must hold beyond LOOKBACK_SWEEP. At n = 5000 the naive form
    (`math.comb(n, k) * p**k * (1-p)**(n-k)`) raises OverflowError converting a 1500-digit
    integer to float, while log space returns the right answer.
    """
    v = mod.binom_tail_le(5000, 2500, 0.5)
    assert v == pytest.approx(0.5056, abs=1e-3), v
    with pytest.raises(OverflowError):
        total = 0.0
        for k in range(2501):
            total += math_comb(5000, k) * (0.5 ** k) * (0.5 ** (5000 - k))


def math_comb(n: int, k: int) -> int:
    import math
    return math.comb(n, k)


def test_pair_surviving_only_one_half_is_refused(mod, tmp_path):
    """Mutant 2: `ok = good` keeps only the LAST half iterated, so a pair measurable on TEST
    alone would be reported measurable. The order #137 says "обеих половинах" and that is the
    whole point of the matrix -- a one-sided answer is the question #137 was written to replace.

    Built: two mirror-image legs in TRAIN (each falls deeper than the fee, their 50/50 never
    falls) that become aligned in TEST (both fall together, so the 50/50 falls too).
    """
    root = tmp_path / "half_only"
    a = [(0.04 if i % 2 == 0 else -0.02) if i < 460
         else (-0.03 if 500 <= i < 510 else 0.003) for i in range(N)]
    b = [(-0.02 if i % 2 == 0 else 0.04) if i < 460
         else (-0.03 if 500 <= i < 510 else 0.003) for i in range(N)]
    _write_book(root / "half_a", a)
    _write_book(root / "half_b", b)
    _write_book(root / "pad", _two_sided_a())
    L = mod.load_axis(root)
    legs = mod.legs_report(L["rets"], L["books"], L["halves"])
    assert {"half_a", "half_b"} <= set(legs["survivors"]), legs["survivors"]
    cell = mod.pair_cell(L["rets"], "half_a", "half_b", L["halves"], legs)
    assert cell["halves"]["TEST"]["survives"] is True, "fixture precondition: TEST is measurable"
    assert cell["halves"]["TRAIN"]["survives"] is False, "fixture precondition: TRAIN is not"
    assert cell["verdict"] == mod.CELL_PAIR, (
        "a pair measurable in only ONE half must be refused: the matrix answers a question "
        "about both sides of the seam")


def test_interior_optimum_requires_beating_BOTH_legs(mod, tmp_path):
    """Mutant 3: `min(legs)` instead of `max(legs)` -- "diversification helps" would then be
    claimed whenever a blend beats the WORSE leg, which every blend of a good and a bad leg does
    trivially. Built: two perfectly co-falling legs with different carry, so Calmar is monotone
    in the weight and no blend beats the better leg.
    """
    root = tmp_path / "monotone_frontier"
    crisis = lambda i: (100 <= i < 120 or 550 <= i < 570)  # noqa: E731
    _write_book(root / "leg_good", [(-0.004 if crisis(i) else 0.0020) for i in range(N)])
    _write_book(root / "leg_bad", [(-0.004 if crisis(i) else 0.0002) for i in range(N)])
    _write_book(root / "pad", _two_sided_b())
    L = mod.load_axis(root)
    legs = mod.legs_report(L["rets"], L["books"], L["halves"])
    assert {"leg_good", "leg_bad"} <= set(legs["survivors"])
    comp = mod.blend_sweep(L["rets"], "leg_good", "leg_bad", L["halves"])
    te = [c["calmar"] for c in comp["rows"]["TEST"]]
    assert all(v is not None for v in te), "fixture precondition: every cell is judgeable"
    assert any(te[i] > min(te[0], te[-1]) for i in range(1, len(te) - 1)), (
        "fixture precondition: interior cells DO beat the worse leg, which is what makes the "
        "min/max confusion invisible without this control")
    assert comp["transfer"]["test_blend_beats_both_legs"] is False
    assert comp["transfer"]["test_best_interior_gain"] is None


def test_p1_is_refuted_when_the_bound_funds_the_never_fallen_book(mod, tmp_path):
    """Mutant 5: `p1_holds: True` -- the registered prediction must be judgeable in BOTH
    directions, and the fixture above happens to confirm it, so a hard-coded True survived there.

    This fixture reproduces the real panel's mechanism: a book that moves a lot but never falls
    has a LARGE sigma (so 1/sigma gives it little) and a SMALL ignorance bound (so TUB gives it
    the ceiling). Eight books, so the 20 % cap does not bind every name -- a flat vector would
    make both sizers coincide and the comparison would express nothing (#128/#131).
    """
    root = tmp_path / "p1_refuted"
    _write_book(root / "up_volatile", [(0.03 if i % 2 == 0 else 0.001) for i in range(N)])
    for name, up, dn in (("down_a", 0.010, -0.010), ("down_b", 0.012, -0.008),
                         ("down_c", 0.009, -0.011), ("down_d", 0.010, -0.009),
                         ("down_e", 0.011, -0.010), ("down_f", 0.008, -0.012),
                         ("down_g", 0.010, -0.011)):
        _write_book(root / name, [(dn if i % 2 == 0 else up) for i in range(N)])
    L = mod.load_axis(root)
    nf = mod.never_fallen(L["rets"], L["books"])
    assert nf == ["up_volatile"]
    sig = mod.run_tub(L["rets"], L["books"], lo=30, hi=400, kind="inv_sigma", lookback=30)
    assert not all(abs(v - 0.20) < 1e-9 for v in sig["mean_weight"].values()), (
        "fixture precondition: the ceiling must NOT bind every name, or both sizers coincide "
        "and P1 is decided by a tie rather than by the mechanism")
    # The verdict is read through `pdm_report`, where the P1 line actually lives. Comparing the
    # two masses by hand here would leave the reported verdict untested -- the first delta run
    # caught exactly that: a hard-coded `p1_holds: True` survived a test that recomputed the
    # masses itself and never looked at what the report said.
    rep = mod.pdm_report(root, lookback=30)
    p1 = rep["tub"]["p1"]
    assert p1["never_fallen"] == ["up_volatile"]
    for half in ("TRAIN", "TEST"):
        d = p1["halves"][half]
        assert d["tub_mass"] > d["inv_sigma_mass"], (half, d)
        assert d["p1_holds"] is False, (
            f"{half}: TUB funds the never-fallen book MORE than 1/sigma does, so the registered "
            f"prediction must read REFUTED here")


def test_breakeven_marks_an_unreachable_row_rather_than_printing_alpha(mod, tmp_path):
    """Mutant 6: alpha printed unconditionally. Where a measured book's own bound EXCEEDS the
    panel's median loss magnitude, no confidence level makes a never-fallen book rank riskier
    than it -- p_hi is capped at 1. The real panel has exactly one such row
    (`eth_directional`, 110.45 bp against a 71.7 bp median), so the branch is not hypothetical.
    """
    root = tmp_path / "unreachable"
    _write_book(root / "huge", [(-0.30 if i % 3 == 0 else 0.20) for i in range(N)])
    _write_book(root / "tiny_a", [(-0.00002 if i % 2 == 0 else 0.00003) for i in range(N)])
    _write_book(root / "tiny_b", [(-0.00001 if i % 2 == 0 else 0.00002) for i in range(N)])
    L = mod.load_axis(root)
    be = mod.breakeven_alpha(L["rets"], L["books"])
    assert be["status"] == "measured"
    assert be["rows"]["huge"]["needed_p_hi"] > 1.0, "fixture precondition"
    assert be["rows"]["huge"]["status"] == "unreachable"
    assert be["rows"]["huge"]["alpha"] is None, (
        "an alpha printed here would be a confidence level that does not exist")
    for name in ("tiny_a", "tiny_b"):
        assert be["rows"][name]["status"] == "measured"
        assert 0.0 < be["rows"][name]["alpha"] <= 1.0
