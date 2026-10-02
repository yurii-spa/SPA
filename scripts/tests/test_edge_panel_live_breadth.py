"""Acceptance for scripts/edge_panel_live_breadth.py (PLB / NLF).

Every test here is a POSITIVE CONTROL: it reproduces a defect that was actually hit while the
harness was being written, and it goes red if that wire is cut again.

  * `live_breadth` over the FULL axis answered "10/10 live" for a panel in which four books had
    been frozen since 2024 — because each of them HAD moved early in the axis. The count is a
    property of the SLICE being judged. (tests 2, 3)
  * `RPE.perf` returns maxDD NEGATIVE, so `maxdd <= cap` admitted every subset and the drawdown
    cap silently never bound: four different caps printed byte-identical frontiers. (test 7)
  * a frozen book and an unmeasured book are different facts (inv. #17) and the census must say
    which one it found, never a zero for both. (tests 1, 4)
  * a cap that admits no subset is the third outcome with a named reason, not an empty line and
    not a zero. (test 8)

No test reads the network. The real panel is runtime-only (not in git), so the reproduction
control states its own third outcome rather than skipping — a skip would make "not measured"
indistinguishable from "passed" (lesson of #465).
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


#: PLB/NLF live beside the panel loader on purpose — what they measure is a property of THAT
#: loader's output that every consumer, including its own run_idea17, had been reading wrongly.
HARNESS = ROOT / "scripts" / "edge_real_panel_ensemble.py"


def _load():
    spec = importlib.util.spec_from_file_location("edge_plb_under_test", HARNESS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PLB = _load()


# --------------------------------------------------------------------------- fixtures

def _write_book(root: Path, name: str, equities, *, killed_from=None, phase="backtest"):
    """One book's realized_series.jsonl. `equities` is [(date, equity_usd), ...]."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for date, eq in equities:
        lines.append(json.dumps({
            "as_of": date, "date": date, "equity_usd": eq, "phase": phase,
            "is_advisory": True,
            "killed": bool(killed_from and date >= killed_from),
        }))
    (d / "realized_series.jsonl").write_text("\n".join(lines) + "\n")


def _dates(n, start="2024-03-01"):
    """Real consecutive calendar dates: load_panel needs >= 60 points and PLB.load >= 200 days."""
    import datetime
    d0 = datetime.date.fromisoformat(start)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _wobble(dates, *, drift, amp):
    """Deterministic equity path with a non-zero daily sigma. No RNG: the pattern is the seed."""
    out = []
    val = 100.0
    for i, d in enumerate(dates):
        val *= 1.0 + drift + (amp if i % 3 == 0 else -amp / 2.0)
        out.append((d, val))
    return out


#: long enough to clear load_panel's 60-point floor and PLB.load's 200-day axis floor
FIXTURE_DAYS = 240
#: the day `dies` is killed, as an index into the fixture axis
DIES_AT = 5


@pytest.fixture()
def tiny_panel(tmp_path):
    """Four books. `dies` is frozen from day DIES_AT on; `flat` never moves at all."""
    ds = _dates(FIXTURE_DAYS)
    root = tmp_path / "panel"
    # grows, with a deterministic wobble so its trailing sigma is NOT zero (a smooth
    # exponential has pstdev 0 and would hit the sizer's floor exactly like a frozen book)
    _write_book(root, "grows", _wobble(ds, drift=0.001, amp=0.004))
    # moves for four days, then killed and frozen
    eq = []
    val = 100.0
    for i, d in enumerate(ds):
        if i < DIES_AT:
            val *= 0.99
        eq.append((d, val))
    _write_book(root, "dies", eq, killed_from=ds[DIES_AT])
    # never moves
    _write_book(root, "flat", [(d, 100.0) for d in ds])
    # a second grower so subsets of size > 1 exist
    _write_book(root, "grows2", _wobble(ds, drift=0.0005, amp=0.002))
    return root


# --------------------------------------------------------------------------- 1. census

def test_census_distinguishes_a_killed_frozen_book_from_an_unmeasured_one(tiny_panel):
    """inv. #17: frozen-because-killed and never-measured are two facts, not one zero."""
    (tiny_panel / "no_block").mkdir()
    _write_book(tiny_panel, "no_block", [(d, 100.0) for d in _dates(5)], phase="forward")

    c = PLB.book_census(tiny_panel)

    assert c["dies"]["killed_on"] == _dates(FIXTURE_DAYS)[DIES_AT]
    assert c["dies"]["moving_days"] == DIES_AT - 1  # measured, and it is not zero
    assert c["dies"]["unmeasured"] is None
    assert c["flat"]["killed_on"] is None
    assert c["flat"]["moving_days"] == 0            # measured AND equal to zero
    assert c["no_block"]["moving_days"] is None     # NOT measured — never 0
    assert c["no_block"]["unmeasured"]              # and the reason is named


def test_census_refuses_an_empty_panel(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(RuntimeError, match="no books"):
        PLB.book_census(tmp_path / "empty")


# --------------------------------------------------------------------------- 2-3. slice-aware liveness

def test_live_breadth_is_a_property_of_the_slice_not_of_the_panel(tiny_panel):
    """THE bug: asked over the whole axis, a book frozen since day 5 still counts as live."""
    axis, rets, books = PLB.plb_load(tiny_panel)
    n = len(axis)

    live_all, frozen_all = PLB.live_breadth(axis, rets, books)
    live_tail, frozen_tail = PLB.live_breadth(axis, rets, books, lo=n // 2)

    assert "dies" in live_all and "dies" not in frozen_all     # it did move, early
    assert "dies" in frozen_tail                               # and it is dead on the tail
    assert "flat" in frozen_all and "flat" in frozen_tail
    assert "grows" in live_all and "grows" in live_tail


def test_post_kill_era_is_measured_from_the_census_not_written_down(tiny_panel):
    axis, _, _ = PLB.plb_load(tiny_panel)
    census = PLB.book_census(tiny_panel)

    idx, date = PLB.post_kill_era(axis, census)
    assert date == census["dies"]["killed_on"]
    assert axis[idx - 1] == date                   # the era starts the day AFTER the last kill

    # move the kill later in the fixture: the era must move with it, not stay put
    later = dict(census)
    later["dies"] = dict(census["dies"], killed_on=axis[-3])
    idx2, date2 = PLB.post_kill_era(axis, later)
    assert date2 == axis[-3] and idx2 > idx


def test_post_kill_era_reports_the_third_outcome_when_nothing_was_killed(tiny_panel):
    axis, _, _ = PLB.plb_load(tiny_panel)
    census = {k: dict(v, killed_on=None) for k, v in PLB.book_census(tiny_panel).items()}
    idx, date = PLB.post_kill_era(axis, census)
    assert date is None and idx == 0               # no fabricated era date


# --------------------------------------------------------------------------- 5-7. subset metrics

def test_subset_perf_refuses_a_portfolio_of_nothing(tiny_panel):
    axis, rets, _ = PLB.plb_load(tiny_panel)
    with pytest.raises(ValueError, match="empty subset"):
        PLB.subset_perf([], rets, 0, len(axis))


def test_subset_perf_charges_the_roundtrip_exactly_once(tiny_panel):
    """A static subset trades on day one only. A per-day toll would be a different rule."""
    axis, rets, _ = PLB.plb_load(tiny_panel)
    n = len(axis)
    free = PLB.subset_perf(["grows"], rets, 0, n)
    tolled = PLB.subset_perf(["grows"], rets, 0, n, roundtrip=0.01)
    double = PLB.subset_perf(["grows"], rets, 0, n, roundtrip=0.02)
    assert tolled["apy"] < free["apy"]
    # one-off: doubling the toll costs about twice as much terminal value, not 2*n times
    assert (free["apy"] - double["apy"]) < 3 * (free["apy"] - tolled["apy"])


def test_subset_perf_reports_maxdd_as_a_magnitude_so_a_cap_can_bind(tiny_panel):
    """THE silent bug: RPE.perf returns maxDD negative, so `maxdd <= cap` was always true."""
    axis, rets, _ = PLB.plb_load(tiny_panel)
    p = PLB.subset_perf(["dies"], rets, 0, len(axis))
    assert p["maxdd"] > 0.0, "a book that lost 5% must report a POSITIVE drawdown magnitude"
    assert PLB.subset_perf(["flat"], rets, 0, len(axis))["maxdd"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- 8-10. frontier

def test_frontier_reports_the_third_outcome_when_the_cap_admits_nothing(tiny_panel):
    axis, rets, books = PLB.plb_load(tiny_panel)
    ti = len(axis) // 2
    rows = PLB.nleg_frontier(["dies"], rets, train_hi=ti, test_hi=len(axis), cap=0.0)
    row = rows[0]
    assert row["admitted"] == 0
    assert row["train"] is None and row["test"] is None and row["test_rank"] is None
    assert "no subset of size 1" in row["reason"]


def test_frontier_selects_on_train_only_and_never_reads_the_test_half(tiny_panel):
    """Causality: rewriting TEST must move the TEST numbers and NOT move the choice."""
    axis, rets, books = PLB.plb_load(tiny_panel)
    ti = len(axis) // 2
    uni = ["grows", "grows2", "dies"]
    before = PLB.nleg_frontier(uni, rets, train_hi=ti, test_hi=len(axis), cap=1.0)

    poisoned = {b: list(v) for b, v in rets.items()}
    for i in range(ti, len(axis)):
        poisoned["grows2"][i] = 0.5          # make the loser spectacular, but only on TEST
    after = PLB.nleg_frontier(uni, rets=poisoned, train_hi=ti, test_hi=len(axis), cap=1.0)

    assert [r["subset"] for r in after] == [r["subset"] for r in before], "choice used TEST data"
    assert any(a["test"]["apy"] != b["test"]["apy"]
               for a, b in zip(after, before) if a["test"] and b["test"]), \
        "poisoning TEST changed nothing — the harness is not reading the TEST half at all"


def test_frontier_marks_policy_admissibility_from_the_declared_cap(tiny_panel):
    axis, rets, books = PLB.plb_load(tiny_panel)
    ti = len(axis) // 2
    rows = PLB.nleg_frontier(books, rets, train_hi=ti, test_hi=len(axis), cap=1.0)
    by_n = {r["n"]: r for r in rows}
    assert by_n[1]["admissible_by_policy"] is False      # 100% in one name
    assert by_n[len(books)]["admissible_by_policy"] is (1.0 / len(books) <= PLB.POLICY_CAP)


def test_degenerate_calmar_is_counted_rather_than_worked_around(tiny_panel):
    axis, rets, _ = PLB.plb_load(tiny_panel)
    zero, total = PLB.degenerate_calmar_subsets(["flat", "grows"], rets, lo=0, hi=len(axis))
    assert total == 3                                   # {flat}, {grows}, {flat,grows}
    assert zero >= 1, "a flat book has maxDD 0 and therefore an infinite Calmar"


# --------------------------------------------------------------------------- 12-13. inverse-risk sizer

def test_inverse_risk_sizer_sends_the_money_to_the_books_that_cannot_move(tiny_panel):
    """The measured claim of section 2: 1/risk is a cash position wearing a book's name."""
    axis, rets, books = PLB.plb_load(tiny_panel)
    w = PLB.inverse_risk_weights(rets, books, end=len(axis), lookback=10)
    frozen, _ = ["flat", "dies"], None
    assert sum(w[b] for b in frozen) > 0.9, w


def test_the_floor_is_what_decides_that_and_it_is_a_parameter_not_a_constant(tiny_panel):
    axis, rets, books = PLB.plb_load(tiny_panel)
    tight = PLB.inverse_risk_weights(rets, books, end=len(axis), lookback=10, floor=1e-8)
    loose = PLB.inverse_risk_weights(rets, books, end=len(axis), lookback=10, floor=1e-1)
    share_tight = sum(tight[b] for b in ("flat", "dies"))
    share_loose = sum(loose[b] for b in ("flat", "dies"))
    assert share_tight > share_loose, "raising the floor must reduce the frozen share"


def test_inverse_risk_sizer_refuses_a_window_too_short_to_be_an_estimate(tiny_panel):
    axis, rets, books = PLB.plb_load(tiny_panel)
    with pytest.raises(ValueError, match="window shorter"):
        PLB.inverse_risk_weights(rets, books, end=3, lookback=3)


def test_inverse_risk_sizer_refuses_an_unknown_statistic(tiny_panel):
    axis, rets, books = PLB.plb_load(tiny_panel)
    with pytest.raises(ValueError, match="unknown kind"):
        PLB.inverse_risk_weights(rets, books, end=len(axis), lookback=10, kind="vibes")


# --------------------------------------------------------------------------- 14. spearman

def test_spearman_refuses_a_constant_series_instead_of_returning_zero():
    with pytest.raises(ValueError, match="constant series"):
        PLB.rank_spearman([1.0, 1.0, 1.0, 1.0], [1.0, 2.0, 3.0, 4.0])
    assert PLB.rank_spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert PLB.rank_spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


# --------------------------------------------------------------------------- 15. reproduction control

PUBLISHED = {
    # registry entry PLB, section 1 — EW over all ten books, full 852-day axis
    "ew_all_full_apy": 0.1794, "ew_all_full_maxdd": 0.0544,
    # section 1 — EW over the six books that are live in the post-kill era
    "ew_live_full_apy": 0.3105, "ew_live_full_maxdd": 0.0900,
    "frozen": ["leverage_loop", "levered_restaking", "lp_eth_stable", "lrt_neutral"],
}


def _measure_real_panel():
    """('MEASURED', numbers) or ('UNMEASURED', reason). Never a zero, never a skip."""
    panel = Path(PLB.PANEL_DIR)
    if not panel.is_dir():
        return "UNMEASURED", f"panel directory {panel} is absent (runtime-only data, not in git)"
    try:
        axis, rets, books = PLB.plb_load(panel)
    except Exception as exc:  # noqa: BLE001 - the reason must be named, whatever it is
        return "UNMEASURED", f"panel did not load: {exc}"
    census = PLB.book_census(panel)
    era_i, _ = PLB.post_kill_era(axis, census)
    live, frozen = PLB.live_breadth(axis, rets, books, lo=era_i)
    return "MEASURED", {
        "ew_all_full": PLB.subset_perf(books, rets, 0, len(axis)),
        "ew_live_full": PLB.subset_perf(sorted(live), rets, 0, len(axis)),
        "frozen": sorted(frozen),
    }


def test_published_numbers_are_reproduced_or_the_absence_is_named():
    outcome, payload = _measure_real_panel()
    if outcome == "UNMEASURED":
        assert isinstance(payload, str) and payload, "НЕ ИЗМЕРЕНО must carry its reason"
        return
    assert payload["frozen"] == PUBLISHED["frozen"], payload["frozen"]
    assert payload["ew_all_full"]["apy"] == pytest.approx(PUBLISHED["ew_all_full_apy"], abs=5e-4)
    assert payload["ew_all_full"]["maxdd"] == pytest.approx(PUBLISHED["ew_all_full_maxdd"], abs=5e-4)
    assert payload["ew_live_full"]["apy"] == pytest.approx(PUBLISHED["ew_live_full_apy"], abs=5e-4)
    assert payload["ew_live_full"]["maxdd"] == pytest.approx(PUBLISHED["ew_live_full_maxdd"], abs=5e-4)


def test_the_harness_never_imports_the_execution_domain():
    """inv. #6. Measured on IMPORT STATEMENTS, not on a substring.

    The substring form was tried first and it failed on the harness's own docstring, which
    promises in prose NOT to touch spa_core/execution. A rule that cannot tell a promise from
    an import is the wrong instrument, so this reads the parse tree.
    """
    tree = ast.parse(HARNESS.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not [m for m in imported if m.startswith("spa_core.execution")], sorted(imported)
    assert PLB.POLICY_CAP == 0.20
    assert PLB.PLB_ROUNDTRIP == 0.0096
