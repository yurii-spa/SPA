"""Controls for scripts/edge_msd_real_panel.py — registry #137 (MSDR), the order left by #133.

Every test is a POSITIVE CONTROL for a defect this class has actually produced:

  * #130's own engine reports a vanished denominator as `calmar = 999.99` — the largest number
    in its table. On the real panel EVERY points_farm row hits that branch. The whole value of
    this entry is that the figure is printed AND refused beside itself, so
    `test_the_engines_999_is_reported_but_never_adopted` goes red if the honest column is ever
    filled from the engine's.
  * #122/#126/#128/#129 each caught a rule funding `points_farm` because "lowest tail" there
    means NOT MEASURED. `test_crisis_premise_keeps_no_down_day_apart_from_measured` keeps the
    three outcomes apart at the exact place the fixture's spec constants meet observation.
  * a negative control quietly renamed stops being a control: the fixture's `lrt_carry` has no
    real book, so the substitution must be DECLARED in the data.
    `test_substitution_is_declared_in_the_row`.
  * #133's cliff must be the model it claims — yield gone, position held, nothing invented.
    `test_cliff_zeroes_only_after_the_date` and `test_cliff_none_is_bitwise_identity`.
  * a degenerate ratio refuses the RATIO, not the NUMERATOR: income stays judgeable, and it is
    the second half of #130's claim. `test_income_direction_*`.
  * three outcomes for the verdict, never two. `test_verdict_*` drives all three.

The panel is BUILT HERE, in tmp, and never read from data/: data/aggressive_lab is runtime-only
(gitignored), so a test that reached for it would be green on this Mac and "NOT MEASURED" in CI.
"""
# FROZEN-DATE-OK: cliff-dates-and-crisis-windows — the literal dates ARE the subject twice over:
# #133's five cliff dates are the population this entry re-runs, and the harness's crisis windows
# (2024-08, 2025-10, 2026-04) are named windows of real events, not a freshness horizon. Nothing
# here is judged against the calendar: `test_no_wall_clock_door_in_the_measured_path` in
# test_edge_static_guardian_perimeter.py asserts the shared measured path holds no wall-clock
# door, and the two doors this file adds (scripts/edge_msd_real_panel.py,
# scripts/edge_multi_strategy_diversification.py) are asserted below. Preference #3 of
# .claude/rules/deployment.md: the date is the subject.
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_msd_real_panel.py"
MSD_SCRIPT = ROOT / "scripts" / "edge_multi_strategy_diversification.py"

N_DAYS = 700
START = "2024-03-06"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("edge_msd_real_panel", SCRIPT)
    assert spec and spec.loader, f"cannot import {SCRIPT}"
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _dates(n: int = N_DAYS, start: str = START):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _write_book(root: Path, rets) -> None:
    root.mkdir(parents=True, exist_ok=True)
    dates = _dates(len(rets) + 1)
    eq = 100_000.0
    lines = []
    for i, d in enumerate(dates):
        if i:
            eq *= 1.0 + rets[i - 1]
        lines.append(json.dumps({
            "as_of": d, "date": d, "equity_usd": round(eq, 6), "phase": "backtest",
            "killed": False, "is_advisory": True, "outside_riskpolicy": True,
            "net_apy_pct": 0.0, "mtm_today_pct": 0.0,
        }))
    (root / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


@pytest.fixture(scope="module")
def panel(tmp_path_factory) -> Path:
    """The three books the order names, in the shapes the real panel actually has.

    susde_dn    — almost monotone with a couple of tiny down days (the real shape: maxDD 0.05 %).
    points_farm — monotone up, NOT ONE day below zero: the book whose "lowest tail" is an
                  absence of observation.
    lrt_neutral — two-sided with a real drawdown, the only one that can carry a denominator.
    """
    root = tmp_path_factory.mktemp("panel_msdr")
    n = N_DAYS - 1
    _write_book(root / "susde_dn", [(-0.0002 if i in (200, 640) else 0.0004) for i in range(n)])
    _write_book(root / "points_farm", [0.0003 + 0.0002 * ((i % 7) / 7.0) for i in range(n)])
    _write_book(root / "lrt_neutral", [(-0.02 if 150 <= i < 170 else 0.0035) for i in range(n)])
    _write_book(root / "filler_a", [(0.002 if i % 2 else -0.0016) for i in range(n)])
    return root


@pytest.fixture(scope="module")
def report(mod, panel):
    return mod.msdr_report(panel)


# ═══════════ the defect at the centre of this entry: 999.99 is not a Calmar ═══════════
def test_the_engines_999_is_reported_but_never_adopted(mod, report):
    """#130's engine prints 999.99 for a vanished denominator. The honest column must refuse it.

    If the two columns were ever filled from the same place, this entry would reproduce exactly
    the error it was written to measure, and it would look like a confirmation of #130.
    """
    rows = report["blends"]["test"]["rows"]
    hits = [r for r in rows if r["engine"]["calmar"] is not None
            and r["engine"]["calmar"] > 900.0]
    assert hits, ("the fixture produced no degenerate row at all — this test cannot see the "
                  "defect it exists for; the panel shape must be fixed, not the assertion")
    for r in hits:
        assert r["honest"]["calmar"] is None, (
            f"{r['label']}: honest Calmar {r['honest']['calmar']} printed over a denominator "
            f"the engine itself could not form")
        assert r["honest"]["calmar_degenerate"] or r["honest"]["status"].startswith("unmeasured")


def test_a_measurable_row_is_not_refused_wholesale(mod, report):
    """Control on the control: the refusal must be about the denominator, not about every row.

    A verdict function that refused everything would pass the test above while measuring
    nothing — the failure mode #129 named "NOT MEASURED dressed as a result".
    """
    rows = report["blends"]["full"]["rows"]
    measured = [r for r in rows if r["honest"]["calmar"] is not None]
    assert measured, ("every row of the full axis was refused — the honest verdict is not "
                      "discriminating, it is just saying no")


# ═════════════════════════ the premise, with three outcomes ═════════════════════════
def test_crisis_premise_keeps_no_down_day_apart_from_measured(mod, report):
    """`0.00 % because nothing fell` and `0.02 % measured` must never share a cell (inv. #17)."""
    pf = report["premise"]["points_farm"]
    assert pf, "no crisis window intersected the axis at all"
    statuses = {w["status"] for w in pf.values()}
    assert statuses <= {"no_down_day", "measured", "unmeasured_window_off_axis"}
    for name, w in pf.items():
        if w["status"] == "no_down_day":
            assert w["loss"] == 0.0 and w["down_days"] == 0, (
                f"{name}: a no-down-day window reported a loss")
    off = [w for w in pf.values() if w["status"] == "unmeasured_window_off_axis"]
    for w in off:
        assert w["loss"] is None, "a window off the axis handed back a number"

    # The branch above is only worth anything if the status it reads actually OCCURS here, and
    # if the OPPOSITE label cannot be worn by a window with nothing in it. Without these two
    # lines the whole test passes vacuously the moment the two statuses are merged — which is
    # exactly what the delta mutation run caught on the first version of this file.
    assert any(w["status"] == "no_down_day" for w in pf.values()), (
        "points_farm shows no `no_down_day` window at all — the status this entry turns on is "
        "not being produced, so nothing above was checked")
    for name, w in pf.items():
        # `.get`, not `[...]`: a window off the axis carries no down-day count at all, and that
        # third outcome must not be read as "zero down days".
        if w.get("down_days") == 0 and w["n_days"]:
            assert w["status"] == "no_down_day", (
                f"{name}: a covered window with zero down days is labelled {w['status']!r} — "
                f"`measured and equal to zero` has been merged with `measured`, and inv. #17's "
                f"two outcomes are again one cell")


# ═════════════════════════ the substitution, declared not silent ═════════════════════════
def test_substitution_is_declared_in_the_row(mod, report):
    """The fixture's `lrt_carry` has no real book; whatever stands in must say so, in the data."""
    rows = report["blends"]["full"]["rows"]
    subbed = [r for r in rows if r["alt"] in report["substitutions"]]
    assert subbed, "the negative control vanished from the grid"
    for r in subbed:
        assert r["substitution"], f"{r['label']} substitutes a book without declaring it"
        assert "*" in r["label"], f"{r['label']} is not marked as a substitution in its label"


def test_a_missing_book_is_a_loud_refusal(mod, tmp_path_factory):
    """A panel without the books the order names must refuse, never quietly pick a neighbour."""
    root = tmp_path_factory.mktemp("panel_missing")
    n = N_DAYS - 1
    for name in ("susde_dn", "filler_a", "filler_b"):
        _write_book(root / name, [(0.001 if i % 2 else -0.0008) for i in range(n)])
    with pytest.raises(RuntimeError, match="NOT MEASURED"):
        mod.msdr_report(root)


# ═════════════════════════ #133's cliff, as the model it claims ═════════════════════════
def test_cliff_zeroes_only_after_the_date(mod):
    series = {"2025-01-01": 0.01, "2025-06-30": 0.02, "2025-07-01": 0.03, "2025-12-31": 0.04}
    out = mod.apply_cliff(series, "2025-07-01")
    assert out["2025-01-01"] == 0.01 and out["2025-06-30"] == 0.02
    assert out["2025-07-01"] == 0.0 and out["2025-12-31"] == 0.0


def test_cliff_none_is_bitwise_identity(mod):
    series = {"2025-01-01": 0.01, "2025-07-01": -0.03}
    assert mod.apply_cliff(series, None) == series


def test_cliff_invents_no_losses(mod):
    """Yield gone, position held — the cliff may remove return, never add a loss."""
    series = {f"2025-07-{d:02d}": 0.01 for d in range(1, 20)}
    out = mod.apply_cliff(series, "2025-07-05")
    assert min(out.values()) == 0.0, "the cliff model invented a loss that was never observed"
    assert set(out) == set(series), "the cliff changed the axis"


# ═══════════════ the rebuilt portfolio is the engine's, not a second opinion ═══════════════
def test_portfolio_rebuild_matches_the_engine(mod, report, panel):
    """The honest verdict must be taken on the SAME path the engine scored, to four decimals.

    Two different paths under one label is how a table becomes unreadable while staying green.
    """
    H = mod.panel_mod()
    axis, rets, _books = H.plb_load(panel)
    comp = mod.as_date_map(axis, rets["susde_dn"])
    engine = mod.msd_mod()._run_kods_on_composite(comp, "probe")
    port = mod.kods_portfolio_series(comp)
    eq = 1.0
    for d in sorted(port):
        eq *= 1.0 + port[d]
    apy = (eq ** (365.0 / len(port)) - 1.0) * 100.0
    assert apy == pytest.approx(engine["apy_pct"], abs=1e-6), (
        f"rebuilt APY {apy} vs engine {engine['apy_pct']} — the two paths are not the same "
        f"portfolio, so the honest column describes something the engine never scored")


def test_rebuild_reads_the_engines_constants_not_its_own(mod):
    """Pin the import: moving #130's Kelly cap must move this file's rebuild with it."""
    M = mod.msd_mod()
    src = SCRIPT.read_text()
    for const in ("M.ALPHA", "M.MAX_RISKY", "M.LOOKBACK", "M.MIN_VAR", "M.RATES_DAILY",
                  "M.SAFE_DAILY"):
        assert const in src, f"{const} is not read off the imported engine — it was retyped"


# ═════════════════════════ income: the half that stays measurable ═════════════════════════
def test_income_direction_detects_monotone_down(mod):
    rows = [{"alt": "susde_dn", "w_alt": 0.0, "engine": {"apy_pct": 7.5}, "label": "susde_only"},
            {"alt": "points_farm", "w_alt": 0.2, "engine": {"apy_pct": 6.9}, "label": "80s_20p"},
            {"alt": "points_farm", "w_alt": 0.5, "engine": {"apy_pct": 6.1}, "label": "50s_50p"}]
    out = mod.income_direction(rows)
    assert out["status"] == "measured" and out["direction"] == "monotone_down"
    assert out["span_pp"] == pytest.approx(-1.4)


def test_income_direction_says_mixed_when_it_is_mixed(mod):
    """A direction function that always says `down` would make the finding unfalsifiable."""
    rows = [{"alt": "susde_dn", "w_alt": 0.0, "engine": {"apy_pct": 7.5}, "label": "a"},
            {"alt": "points_farm", "w_alt": 0.2, "engine": {"apy_pct": 8.9}, "label": "b"},
            {"alt": "points_farm", "w_alt": 0.5, "engine": {"apy_pct": 6.1}, "label": "c"}]
    assert mod.income_direction(rows)["direction"] == "mixed"


def test_income_direction_refuses_a_missing_apy(mod):
    rows = [{"alt": "susde_dn", "w_alt": 0.0, "engine": {"apy_pct": None}, "label": "a"},
            {"alt": "points_farm", "w_alt": 0.5, "engine": {"apy_pct": 6.1}, "label": "b"}]
    out = mod.income_direction(rows)
    assert out["status"] == "unmeasured" and out["reason"]


def test_income_is_measured_on_the_real_shaped_panel(mod, report):
    """The second half of #130's claim must come out as a direction, not as a refusal."""
    inc = report["verdict"]["income"]["test"]
    assert inc["status"] == "measured", inc
    assert inc["direction"] in ("monotone_down", "monotone_up", "mixed")


# ═════════════════════════ the verdict: three outcomes, never two ═════════════════════════
def _row(label, alt, calmar, degenerate, delta=None):
    return {"label": label, "alt": alt, "w_alt": 0.3,
            "honest": {"calmar": calmar, "calmar_degenerate": degenerate,
                       "status": "measured" if calmar is not None else "unmeasured_monotone"},
            "engine": {"apy_pct": 5.0},
            "delta_honest": ({"status": "measured", "delta_calmar": delta}
                             if delta is not None else {"status": "refused"})}


def test_verdict_unmeasurable_when_every_denominator_is_gone(mod):
    blends = {"test": {"rows": [_row("susde_only", "susde_dn", None, None),
                                _row("70s_30p", "points_farm", None, None)]}}
    v = mod.msdr_verdict(blends, {"test": []})
    assert v["verdict"] == "unmeasurable" and v["measured_rows"] == 0 and v["reason"]


def test_verdict_confirmed_when_a_measured_blend_wins(mod):
    blends = {"test": {"rows": [_row("susde_only", "susde_dn", 2.0, None),
                                _row("70s_30p", "points_farm", 3.0, None, delta=+1.0)]}}
    v = mod.msdr_verdict(blends, {"test": []})
    assert v["verdict"] == "confirmed" and v["winning_blends"] == ["70s_30p"]


def test_verdict_refuted_when_the_measured_blend_loses(mod):
    blends = {"test": {"rows": [_row("susde_only", "susde_dn", 3.0, None),
                                _row("70s_30p", "points_farm", 2.0, None, delta=-1.0)]}}
    v = mod.msdr_verdict(blends, {"test": []})
    assert v["verdict"] == "refuted" and not v["winning_blends"]


def test_verdict_does_not_count_a_degenerate_winner(mod):
    """A win on a denominator below the toll is the #129 defect and must not confirm anything."""
    blends = {"test": {"rows": [_row("susde_only", "susde_dn", 2.0, None),
                                _row("70s_30p", "points_farm", 500.0,
                                     "maxDD below the round-trip toll", delta=+498.0)]}}
    v = mod.msdr_verdict(blends, {"test": []})
    assert v["verdict"] == "refuted", (
        "a degenerate row was allowed to confirm the hypothesis — exactly #129's finding")


# ═════════════════════════ advisory, and no wall clock ═════════════════════════
def test_no_wall_clock_door_in_this_path():
    doors = ("datetime.now", "datetime.utcnow", "time.time", "date.today", "utcnow()")
    for path in (SCRIPT, MSD_SCRIPT):
        body = "\n".join(l for l in path.read_text().splitlines()
                         if not l.strip().startswith("#"))
        for d in doors:
            assert d not in body, f"{path.name} reads a wall clock ({d})"


def test_the_script_is_advisory_and_never_imports_execution():
    src = SCRIPT.read_text()
    assert "IS_ADVISORY = True" in src and "OUTSIDE_RISKPOLICY = True" in src
    assert "spa_core.execution" not in src
    assert "equity_curve_daily" not in src


def test_report_writes_nothing_to_disk(mod, panel):
    before = sorted(p.name for p in panel.iterdir())
    mod.msdr_report(panel)
    assert sorted(p.name for p in panel.iterdir()) == before
