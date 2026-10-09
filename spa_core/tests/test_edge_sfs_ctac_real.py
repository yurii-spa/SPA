"""Controls for scripts/edge_sigma_floor_ctac_real.py — registry ideas #128 (SFS), #129 (CTAC-REAL).

Every test here is a POSITIVE CONTROL for a defect the registry actually measured, not a
restatement of what the code does:

  * #126 measured a sizer that put 86.11 % of the book in ONE name with sigma = 0.00000 % and
    0 down days out of 852, breaching the 20 %/name ceiling by 4.3x. `test_cap_waterfill_*` and
    `test_sfs_refuses_*` fail if either half of the fix is removed.
  * #126 also had to REFUSE to print a Calmar of ~1283 because its denominator was a rounding
    artefact. `test_calmar_degenerate_*` and `test_drawdown_verdict_*` fail if that refusal turns
    back into a float.
  * #122 measured that on this panel "moved least" means "not measured", not "safe".
    `test_crisis_loss_distinguishes_*` keeps the two apart (inv. #17).
  * #127's acceptance criterion was met on the real panel by exactly that degeneracy.
    `test_acceptance_separates_letter_from_meaning` fails if the meaning checks are dropped and
    only the literal pass survives.

The panel is BUILT HERE, in tmp, and never read from data/: data/aggressive_lab is runtime-only
(gitignored), so a test that reached for it would be green on this Mac and "not measured" in CI
— the exact substitution the rules forbid. The synthetic panel is shaped to carry each defect.
"""
# FROZEN-DATE-OK: crisis-window-geometry — the literal dates here ARE the subject, and the
# claim was verified rather than asserted: neither scripts/edge_sigma_floor_ctac_real.py nor the
# path of scripts/edge_real_panel_ensemble.py it calls contains a single wall-clock door (no
# datetime.now / utcnow / time.time / today), so nothing in this file is judged against the
# calendar and nothing here can rot as the calendar moves. What the dates DO carry is geometry:
# the harness's own CRISIS_WINDOWS are literals (eth_crash_2024_08 = 2024-08-01..2024-08-20), so
# a synthetic panel that wants crisis 1 to land inside its axis has to start before it and run
# past it — exactly as the real panel does. Relative stamps (preference #2) cannot express that,
# and injecting a clock (preference #1) would inject something no reader of this code consults.
# This is preference #3 of .claude/rules/deployment.md: the date is the subject.
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_sigma_floor_ctac_real.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("edge_sfs_ctac_real", SCRIPT)
    assert spec and spec.loader, f"cannot import {SCRIPT}"
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ───────────────────────────── the synthetic panel ─────────────────────────────
#: the axis is long enough for plb_load's own refusal (>= 200 common days) plus a lookback.
N_DAYS = 300
#: crisis 1 of the harness is 2024-08-01..2024-08-20; the axis below starts 2024-03-06 so that
#: window lands inside it, the way it does on the real panel.
START = "2024-03-06"


def _dates(n: int = N_DAYS, start: str = START):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _write_book(root: Path, rets, *, killed_on=None) -> None:
    """One realized_series.jsonl in the producer's own format, phase='backtest' throughout."""
    root.mkdir(parents=True, exist_ok=True)
    dates = _dates(len(rets) + 1)
    eq = 100_000.0
    lines = []
    for i, d in enumerate(dates):
        if i:
            eq *= 1.0 + rets[i - 1]
        lines.append(json.dumps({
            "as_of": d, "date": d, "equity_usd": round(eq, 6), "phase": "backtest",
            "killed": bool(killed_on and d >= killed_on), "is_advisory": True,
            "outside_riskpolicy": True, "net_apy_pct": 0.0, "mtm_today_pct": 0.0,
        }))
    (root / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


@pytest.fixture(scope="module")
def panel(tmp_path_factory) -> Path:
    """A panel carrying every shape the registry found on the real one.

    quiet       — strictly monotone up, NOT ONE day below zero over the whole axis. This is the
                  points_farm shape: sigma = 0, down_days = 0, and the book that 1/sigma loads
                  to 86 % while calling it low risk.
    frozen      — one move, then dead. The lp_eth_stable shape: cash wearing a book's name.
    noisy_a..c  — real two-sided books, each with a fall inside the crisis-1 window.
    """
    root = tmp_path_factory.mktemp("panel")
    n = N_DAYS - 1
    dates = _dates()[1:]

    def in_c1(i):
        return "2024-08-01" <= dates[i] <= "2024-08-20"

    _write_book(root / "quiet", [0.0004] * n)
    _write_book(root / "frozen", [0.01] + [0.0] * (n - 1), killed_on=dates[3])
    _write_book(root / "noisy_a",
                [(-0.02 if in_c1(i) else (0.004 if i % 3 else -0.002)) for i in range(n)])
    _write_book(root / "noisy_b",
                [(-0.01 if in_c1(i) else (0.003 if i % 4 else -0.0015)) for i in range(n)])
    _write_book(root / "noisy_c",
                [(-0.005 if in_c1(i) else (0.0025 if i % 5 else -0.0008)) for i in range(n)])
    return root


@pytest.fixture(scope="module")
def loaded(mod, panel):
    H = mod.load_harness()
    axis, rets, books = H.plb_load(panel)
    return H, axis, rets, books


# ───────────────── drawdown_verdict: three outcomes stay distinguishable (inv. #17) ─────────────
def test_drawdown_verdict_refuses_an_empty_series(mod):
    v = mod.drawdown_verdict([])
    assert v["status"] == "unmeasured_empty"
    assert v["maxdd"] is None and v["calmar"] is None
    assert v["reason"]


def test_drawdown_verdict_refuses_a_monotone_series_instead_of_returning_zero(mod):
    """The #126 defect: a monotone ledger whose 0.0 maxDD becomes an infinite Calmar."""
    v = mod.drawdown_verdict([0.001] * 100)
    assert v["status"] == "unmeasured_monotone"
    assert v["maxdd"] is None, "a non-decreasing curve has no measured drawdown"
    assert v["calmar"] is None, "no ratio may be formed from an unmeasured denominator"
    assert v["down_days"] == 0
    assert v["apy"] is not None, "the RETURN is still measured — only the drawdown is not"


def test_drawdown_verdict_measures_a_series_with_a_down_day(mod):
    v = mod.drawdown_verdict([0.01, -0.03, 0.01, 0.01])
    assert v["status"] == "measured"
    assert v["maxdd"] is not None and v["maxdd"] > 0
    assert v["calmar"] is not None and math.isfinite(v["calmar"])
    assert v["down_days"] == 1


def test_drawdown_verdict_never_returns_an_infinite_calmar(mod):
    """Control in the other direction: no input may produce the inf that #122 found."""
    for series in ([], [0.0] * 50, [0.001] * 50, [0.0, 0.0, 0.001], [-0.01, 0.02]):
        v = mod.drawdown_verdict(series)
        assert v["calmar"] is None or math.isfinite(v["calmar"]), series


# ───────────────── calmar_degenerate: the refusal threshold is NAMED, not invented ──────────────
def test_calmar_degenerate_refuses_an_unmeasured_drawdown(mod):
    assert "not measured" in mod.calmar_degenerate(None)


def test_calmar_degenerate_refuses_a_denominator_below_the_toll(mod):
    reason = mod.calmar_degenerate(0.0002)
    assert reason and "0.96" in reason, "the reason must name the toll it compared against"


def test_calmar_degenerate_accepts_a_drawdown_above_the_toll(mod):
    assert mod.calmar_degenerate(0.05) is None


def test_calmar_degeneracy_threshold_is_the_roundtrip_constant_not_a_literal(mod):
    """Control on provenance: the boundary must MOVE with the toll it claims to be."""
    assert mod.calmar_degenerate(0.005, floor=0.0096) is not None
    assert mod.calmar_degenerate(0.005, floor=0.001) is None
    assert mod.calmar_degenerate(mod.ROUNDTRIP * 1.01) is None
    assert mod.calmar_degenerate(mod.ROUNDTRIP * 0.99) is not None


# ───────────────── cap_waterfill: #126's 86.11 % breach cannot happen again ─────────────────
def test_cap_waterfill_leaves_admissible_shares_untouched(mod):
    shares = {"a": 0.2, "b": 0.2, "c": 0.2, "d": 0.2, "e": 0.2}
    out = mod.cap_waterfill(shares, cap=0.20)
    assert out["weights"] == pytest.approx(shares)
    assert out["cap_binds"] == 0 and out["degenerate"] is None


def test_cap_waterfill_pins_an_over_cap_name_and_keeps_the_book_full(mod):
    """The direct positive control on #126: 86 % in one name must come back as exactly 20 %."""
    shares = {"hog": 0.8611, "a": 0.05, "b": 0.04, "c": 0.03, "d": 0.0189, "e": 0.0}
    out = mod.cap_waterfill(shares, cap=0.20)
    w = out["weights"]
    assert w["hog"] == pytest.approx(0.20), "the ceiling must bind on the heaviest name"
    assert max(w.values()) <= 0.20 + 1e-12
    assert sum(w.values()) == pytest.approx(1.0), "the excess is redistributed, not discarded"
    assert out["cap_binds"] >= 1


def test_cap_waterfill_preserves_the_order_of_the_names_it_does_not_pin(mod):
    """The ceiling must not destroy the sizer's information where it does not bind."""
    shares = {"hog": 0.60, "a": 0.20, "b": 0.12, "c": 0.05, "d": 0.02, "e": 0.01}
    w = mod.cap_waterfill(shares, cap=0.20)["weights"]
    free = ["b", "c", "d", "e"]
    assert [w[k] for k in free] == sorted((w[k] for k in free), reverse=True)


def test_cap_waterfill_goes_to_cash_when_the_cap_cannot_be_met(mod):
    """Fail-CLOSED: 3 names x 20 % cannot fill a book, so the residual is cash, not a breach."""
    out = mod.cap_waterfill({"a": 0.7, "b": 0.2, "c": 0.1}, cap=0.20)
    assert out["weights"] == pytest.approx({"a": 0.2, "b": 0.2, "c": 0.2})
    assert out["deployed"] == pytest.approx(0.6)
    assert out["cash"] == pytest.approx(0.4)
    assert out["degenerate"], "the state in which the denominator is inert must be NAMED"


def test_cap_waterfill_refuses_a_non_positive_cap(mod):
    with pytest.raises(ValueError):
        mod.cap_waterfill({"a": 1.0}, cap=0.0)


# ───────────────── sfs_weights: the refusal, and which ingredient does the work ─────────────
def test_sfs_refuses_a_book_with_no_down_day_in_the_window(mod, loaded):
    """Acceptance criterion 1 of #126 order 2, as a property rather than a measurement."""
    H, axis, rets, books = loaded
    d = mod.sfs_weights(rets, books, end=200, lookback=30, refuse_no_down_days=True, cap=None)
    assert "quiet" in d["refused"]
    assert d["weights"]["quiet"] == 0.0, "zero BY CONSTRUCTION, not by rounding"
    assert "frozen" in d["refused"], "a frozen book has no down day either"


def test_the_refusal_and_not_the_floor_is_what_zeroes_the_quiet_book(mod, loaded):
    """Control in the other direction: with the refusal off, the quiet book is funded again."""
    H, axis, rets, books = loaded
    off = mod.sfs_weights(rets, books, end=200, lookback=30, refuse_no_down_days=False, cap=None)
    assert off["weights"]["quiet"] > 0.0
    assert "quiet" not in off["refused"]


def test_the_quiet_book_is_the_one_1_over_sigma_loads_up(mod, loaded):
    """The defect being fixed, reproduced: without the refusal the sizer picks the quiet book."""
    H, axis, rets, books = loaded
    off = mod.sfs_weights(rets, books, end=200, lookback=30, sigma_floor=1e-5,
                          refuse_no_down_days=False, cap=None)
    heaviest = max(off["weights"], key=lambda b: off["weights"][b])
    assert heaviest in {"quiet", "frozen"}, (
        "on this panel 1/sigma must concentrate in a book with no measured risk — if it does "
        "not, the fixture no longer carries the defect the fix is for")
    assert off["weights"][heaviest] > mod.POLICY_CAP


def test_sfs_weights_are_causal(mod, loaded):
    """Positive control on look-ahead: mutating the future must not move today's weights."""
    H, axis, rets, books = loaded
    end = 150
    before = mod.sfs_weights(rets, books, end=end, lookback=30, cap=None)["weights"]
    future = {b: list(v) for b, v in rets.items()}
    for b in future:
        for i in range(end, len(future[b])):
            future[b][i] = -0.5 if i % 2 else 0.5
    after = mod.sfs_weights(future, books, end=end, lookback=30, cap=None)["weights"]
    assert before == pytest.approx(after)


def test_sfs_weights_refuse_a_window_too_short_to_be_an_estimate(mod, loaded):
    H, axis, rets, books = loaded
    with pytest.raises(ValueError):
        mod.sfs_weights(rets, books, end=3, lookback=30)


def test_sfs_goes_all_cash_when_no_book_is_eligible(mod):
    """Fail-CLOSED, and it must not raise: 'nothing qualifies' is an answer, not a crash."""
    rets = {"a": [0.001] * 60, "b": [0.002] * 60}
    d = mod.sfs_weights(rets, ["a", "b"], end=50, lookback=30, refuse_no_down_days=True)
    assert d["eligible"] == []
    assert d["cash"] == pytest.approx(1.0)
    assert sum(d["weights"].values()) == 0.0
    assert d["degenerate"]


def test_raising_the_sigma_floor_moves_the_uncapped_weights(mod, loaded):
    """The floor is a live parameter — the premise the degeneracy claim is measured against."""
    H, axis, rets, books = loaded
    lo = mod.sfs_weights(rets, books, end=200, lookback=30, sigma_floor=1e-5, cap=None)["weights"]
    hi = mod.sfs_weights(rets, books, end=200, lookback=30, sigma_floor=5e-2, cap=None)["weights"]
    assert lo != pytest.approx(hi)


def test_the_cap_makes_the_sigma_floor_inert_when_few_names_are_eligible(mod, loaded):
    """#128's central finding, as a property: with k*cap < 1 every eligible name sits AT the cap,
    so the denominator cannot express anything and the floor is unobservable."""
    H, axis, rets, books = loaded
    a = mod.sfs_weights(rets, books, end=200, lookback=30, sigma_floor=1e-5,
                        cap=mod.POLICY_CAP)
    b = mod.sfs_weights(rets, books, end=200, lookback=30, sigma_floor=5e-2,
                        cap=mod.POLICY_CAP)
    assert a["degenerate"], "the fixture must reach the state the finding is about"
    assert a["weights"] == pytest.approx(b["weights"])


# ───────────────── run_sizer: acceptance criteria 2 and 3 ─────────────────
def test_run_sizer_never_breaches_the_policy_cap(mod, loaded):
    H, axis, rets, books = loaded
    r = mod.run_sizer(rets, books, lo=30, hi=len(axis), cap=mod.POLICY_CAP)
    assert r["cap_violation_days"] == 0
    assert r["days_over_policy_cap"] == 0
    assert r["max_name_weight"] <= mod.POLICY_CAP + 1e-12


def test_an_unimposed_cap_is_reported_as_unimposed_not_as_zero_breaches(mod, loaded):
    """inv. #17 on the ceiling column: 'never applied' must not read as 'applied and held'."""
    H, axis, rets, books = loaded
    uncapped = mod.run_sizer(rets, books, lo=30, hi=len(axis), cap=None,
                             refuse_no_down_days=False, sigma_floor=1e-5)
    assert uncapped["cap_violation_days"] is None, "no ceiling was imposed — there is no count"
    assert uncapped["days_over_policy_cap"] > 0, (
        "but the MEASUREMENT 'would these weights have breached 20 %' is always available, and "
        "on this panel 1/sigma does breach it")


def test_run_sizer_refuses_to_start_inside_its_first_window(mod, loaded):
    H, axis, rets, books = loaded
    with pytest.raises(ValueError):
        mod.run_sizer(rets, books, lo=5, hi=len(axis), lookback=30)
    with pytest.raises(ValueError):
        mod.run_sizer(rets, books, lo=30, hi=30, lookback=30)


def test_the_toll_is_charged_on_turnover_and_only_on_turnover(mod, loaded):
    H, axis, rets, books = loaded
    free = mod.run_sizer(rets, books, lo=30, hi=len(axis), roundtrip=0.0)
    paid = mod.run_sizer(rets, books, lo=30, hi=len(axis), roundtrip=mod.ROUNDTRIP)
    assert free["apy_net"] == pytest.approx(free["apy_gross"]), "no toll, no gap"
    assert paid["apy_net"] < paid["apy_gross"], "a daily rebalancer must pay for its churn"
    assert paid["turnover_per_day"] > 0


def test_the_drawdown_is_judged_on_the_gross_series_not_on_our_own_fee(mod):
    """The #125/#126 convention, as a control: a monotone book plus a toll must not report a
    'measured' drawdown that is only the fee read back to us."""
    rets = {"a": [0.001] * 120, "b": [0.0012] * 120}
    r = mod.run_sizer(rets, ["a", "b"], lo=30, hi=120, lookback=30,
                      refuse_no_down_days=False, cap=None, roundtrip=mod.ROUNDTRIP)
    assert r["dd_status"] == "unmeasured_monotone", "the market never took anything"
    assert r["maxdd"] is None and r["calmar"] is None
    assert r["maxdd_incl_toll"] is not None, (
        "the contaminated figure stays VISIBLE rather than being dropped")


# ───────────────── crisis_loss: a measured zero is not a missing one (inv. #17) ─────────────
def test_crisis_loss_refuses_a_window_off_the_axis(mod, loaded):
    H, axis, rets, books = loaded
    e = mod.crisis_loss(rets, axis, "noisy_a", "2019-01-01", "2019-01-10")
    assert e["loss"] is None
    assert e["status"] == "unmeasured_window_off_axis"
    assert e["reason"]


def test_crisis_loss_distinguishes_a_measured_zero_from_a_missing_one(mod, loaded):
    """The #122 lesson: 'covered the window and lost nothing' and 'never looked' differ."""
    H, axis, rets, books = loaded
    quiet = mod.crisis_loss(rets, axis, "quiet", "2024-08-01", "2024-08-20")
    assert quiet["loss"] == 0.0, "an observed zero IS a number"
    assert quiet["status"] == "no_down_day", "and it carries its own status"
    off = mod.crisis_loss(rets, axis, "quiet", "2019-01-01", "2019-01-10")
    assert off["loss"] is None and off["status"] != quiet["status"]


def test_crisis_loss_measures_a_real_fall(mod, loaded):
    H, axis, rets, books = loaded
    e = mod.crisis_loss(rets, axis, "noisy_a", "2024-08-01", "2024-08-20")
    assert e["status"] == "measured"
    assert e["loss"] > 0.1, "noisy_a falls 2 %/day for 20 days inside the window"
    assert e["down_days"] >= 15


# ───────────────── ctac_weights: its premise, and its free number ─────────────────
def test_ctac_funds_the_book_that_lost_nothing(mod):
    """CTAC's own premise, made explicit — and on this panel it is also the known pathology."""
    w = mod.ctac_weights({"quiet": 0.0, "hurt": 0.25, "mild": 0.02})
    assert max(w, key=lambda b: w[b]) == "quiet"
    assert sum(w.values()) == pytest.approx(1.0)


def test_anti_ctac_inverts_the_order(mod):
    losses = {"quiet": 0.0, "hurt": 0.25, "mild": 0.02}
    c = mod.ctac_weights(losses, kind="ctac")
    a = mod.ctac_weights(losses, kind="anti")
    assert sorted(c, key=lambda b: c[b]) == sorted(a, key=lambda b: a[b])[::-1]


def test_ctac_eps_is_a_live_parameter(mod):
    """If eps did not move the answer, the eps sweep in the report would prove nothing."""
    losses = {"quiet": 0.0, "hurt": 0.25, "mild": 0.02}
    assert mod.ctac_weights(losses, eps=1e-5) != pytest.approx(
        mod.ctac_weights(losses, eps=5e-2))


def test_ctac_weights_refuse_an_empty_universe_and_an_unknown_kind(mod):
    with pytest.raises(ValueError):
        mod.ctac_weights({})
    with pytest.raises(ValueError):
        mod.ctac_weights({"a": 0.1}, kind="nonsense")


# ───────────────── bootstrap: the null is a relabelling, and it is deterministic ─────────────
def test_the_permutation_preserves_the_loss_multiset(mod, loaded):
    """The null must destroy the book-to-tail LINK and nothing else: same losses, new owners."""
    H, axis, rets, books = loaded
    losses = {b: mod.crisis_loss(rets, axis, b, "2024-08-01", "2024-08-20")["loss"]
              for b in books}
    import random
    rng = random.Random(mod.BOOTSTRAP_SEED)
    names, vals = sorted(losses), [losses[b] for b in sorted(losses)]
    shuffled = list(vals)
    rng.shuffle(shuffled)
    assert sorted(shuffled) == sorted(vals)
    assert shuffled != vals, "a null that never relabels anything tests nothing"
    assert set(names) == set(losses)


NOISY = ["noisy_a", "noisy_b", "noisy_c"]


def test_the_bootstrap_is_deterministic_under_its_seed(mod, loaded):
    # Asked of the noisy books only, and that choice is the point: over the FULL panel CTAC loads
    # `quiet`+`frozen`, the resulting curve never falls, and the bootstrap correctly refuses
    # (covered by test_the_bootstrap_refuses_... below). Determinism can only be checked where a
    # number exists to be reproduced.
    H, axis, rets, books = loaded
    books = NOISY
    losses = {b: mod.crisis_loss(rets, axis, b, "2024-08-01", "2024-08-20")["loss"]
              for b in books}
    kw = dict(lo=120, hi=len(axis), n=20)
    a = mod.ctac_bootstrap(rets, books, losses, **kw)
    b = mod.ctac_bootstrap(rets, books, losses, **kw)
    assert a["p_value"] == b["p_value"]
    c = mod.ctac_bootstrap(rets, books, losses, seed=mod.BOOTSTRAP_SEED + 1, **kw)
    assert c["status"] == "measured"


def test_the_bootstrap_refuses_rather_than_returns_a_number_when_the_actual_is_unmeasured(mod):
    """Third outcome (inv. #17): no measurable drawdown means no p-value, not p = 1.0."""
    rets = {"a": [0.001] * 200, "b": [0.002] * 200}
    out = mod.ctac_bootstrap(rets, ["a", "b"], {"a": 0.0, "b": 0.0}, lo=0, hi=200, n=5)
    assert out["p_value"] is None
    assert out["status"] == "unmeasured_actual"
    assert out["reason"]
    measured = mod.ctac_bootstrap(
        {"a": [0.01, -0.03] * 100, "b": [0.005, -0.01] * 100}, ["a", "b"],
        {"a": 0.05, "b": 0.01}, lo=0, hi=200, n=5, ew_calmar=1.0)
    assert set(out) == set(measured), (
        "the refusal must carry the SAME keys as a measurement — a caller that reads a missing "
        "key as a zero is the defect inv. #17 is about")


def test_the_bootstrap_counts_draws_against_the_baseline_only_when_given_one(mod, loaded):
    H, axis, rets, books = loaded
    books = NOISY
    losses = {b: mod.crisis_loss(rets, axis, b, "2024-08-01", "2024-08-20")["loss"]
              for b in books}
    blind = mod.ctac_bootstrap(rets, books, losses, lo=120, hi=len(axis), n=10)
    assert blind["draws_beating_ew"] is None, "not asked, so not answered with a zero"
    seeing = mod.ctac_bootstrap(rets, books, losses, lo=120, hi=len(axis), n=10, ew_calmar=0.0)
    assert isinstance(seeing["draws_beating_ew"], int)


# ───────────────── the reports, end to end on the synthetic panel ─────────────────
def test_sfs_report_meets_the_three_acceptance_criteria_of_the_order(mod, panel):
    rep = mod.sfs_report(panel)
    for k, ok in rep["acceptance"].items():
        assert ok is True, f"{k} failed on the synthetic panel"
    assert rep["variants"]["sfs_full"]["always_refused"], (
        "the refusal must have bitten on at least one book, or the criterion is vacuous")


def test_the_capped_variant_is_identical_across_the_whole_floor_sweep(mod, panel):
    """#128's finding as a test: with the ceiling on, sigma_floor cannot change the answer."""
    rep = mod.sfs_report(panel)
    capped = {(v["capped_apy_net"], v["capped_maxdd"], v["capped_calmar"], v["capped_max_name"])
              for v in rep["floor_sweep"].values()}
    assert len(capped) == 1, f"the capped answer moved with the floor: {capped}"
    uncapped = {v["uncapped_apy_net"] for v in rep["floor_sweep"].values()}
    assert len(uncapped) > 1, (
        "control in the other direction: without the ceiling the floor MUST move the answer, "
        "else the identity above would be a property of the panel and not of the ceiling")


def test_ctac_real_report_separates_the_letter_of_the_order_from_its_meaning(mod, panel):
    rep = mod.ctac_real_report(panel)
    assert rep["status"] == "measured"
    acc = rep["acceptance"]
    for k in ("calmar_beats_ew", "p_below_0_05", "literal_pass", "calmar_degenerate",
              "cap_violated", "apy_beats_ew", "null_median_beats_ew", "passed"):
        assert k in acc, f"{k} missing — the meaning checks are the finding of #129"
    assert acc["passed"] is False or (
        acc["calmar_degenerate"] is None and not acc["cap_violated"]), (
        "`passed` may only be True when the Calmar is non-degenerate AND the ceiling held")


def test_ctac_real_report_refuses_a_panel_whose_crisis_window_is_off_axis(mod, tmp_path):
    """Fail-CLOSED: a panel that never saw crisis 1 yields 'not measured', not a sized portfolio."""
    root = tmp_path / "late"
    n = N_DAYS - 1
    for name, r in (("a", 0.001), ("b", -0.0005), ("c", 0.002)):
        _write_book_at(root / name, [r if i % 3 else -r for i in range(n)], start="2030-01-01")
    rep = mod.ctac_real_report(root)
    assert rep["status"] == "unmeasured"
    assert rep["reason"]


def _write_book_at(root: Path, rets, *, start: str) -> None:
    import datetime as dt
    root.mkdir(parents=True, exist_ok=True)
    d0 = dt.date.fromisoformat(start)
    eq = 100_000.0
    lines = []
    for i in range(len(rets) + 1):
        if i:
            eq *= 1.0 + rets[i - 1]
        d = (d0 + dt.timedelta(days=i)).isoformat()
        lines.append(json.dumps({"as_of": d, "date": d, "equity_usd": round(eq, 6),
                                 "phase": "backtest", "killed": False, "is_advisory": True,
                                 "outside_riskpolicy": True}))
    (root / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


def test_the_script_runs_end_to_end_on_a_panel_it_was_handed(mod, panel):
    assert mod.main(["--panel-dir", str(panel), "--section", "both"]) == 0


def test_the_script_declares_itself_advisory_and_outside_riskpolicy(mod):
    """Железный инвариант директивы: nothing here may be read as a money-path module."""
    assert mod.IS_ADVISORY is True
    assert mod.OUTSIDE_RISKPOLICY is True
    # Asked of the CODE, not of the file's bytes: this script's own docstring names the track it
    # promises not to open, so a grep over the source answers a different question and answers it
    # wrongly. Docstrings are excluded by walking the AST and skipping the first statement of
    # every module/class/function body.
    import ast
    tree = ast.parse(SCRIPT.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    live = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]
    for forbidden in ("equity_curve_daily", "cycle_runner", "data/paper_state"):
        assert not any(forbidden in v for v in live), (
            f"{forbidden!r} appears in live code — the go-live track must never be opened here")
