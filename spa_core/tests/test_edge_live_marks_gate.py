"""Controls for registry #152 LMG — the #149 live-marks gate, read in three units.

Every test is a positive control: it pins one invariant of the instrument, or breaks ONE
named wire and confirms the instrument notices. None asserts on a printed substring
(ADR-333) — each calls the real internal functions of `scripts/edge_live_marks_gate.py` on a
deterministic synthetic panel built in a tmpdir.

THE CLAIM UNDER TEST, stated so a reader can see what would falsify it: the gate's three
units are INDEPENDENT. `test_unit1_open_while_unit3_shut_is_the_whole_finding` builds a panel
that satisfies the prohibition's stated number (90 calendar days) and cannot satisfy its
purpose (a measurable drawdown), and requires the instrument to report BOTH facts rather than
collapsing them into one "gate open".

The real panel (`data/aggressive_lab/`) is gitignored and exists only on the owner's Mac, so a
test that read it would answer "is the owner's disk present". Nothing is written outside the
tmpdir: no test here touches git-tracked `data/` (ADR-903).

# FROZEN-DATE-OK: synthetic-axis — every date on these scenes is a literal anchor of the
# scene itself (_DAY0 below), and NO module on this path reads a clock: there is no `.now()`,
# `.today()`, `.utcnow()`, `time.time()` or `time.monotonic()` in
# `scripts/edge_live_marks_gate.py`, in `scripts/edge_real_panel_ensemble.py`, or here. The
# instrument takes no `now` argument because it has nothing to pass one to — GATE_DAYS is
# counted in ROWS of a file, never in distance from today — so no verdict can change because
# the calendar moved.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_live_marks_gate.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("lmg_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lmg_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


LMG = _load()

#: the scene's own epoch. A literal anchor, not a clock read (see FROZEN-DATE-OK above).
_DAY0 = datetime.date(2026, 8, 5)


def _book(panel: Path, name: str, rets, *, marks=None, phase: str = "forward",
          mark_source: str = "realized_backtest_series") -> None:
    """One book's forward series. `marks` is the per-row mtm_today_pct (None ⇒ all zero)."""
    d = panel / name
    d.mkdir(parents=True, exist_ok=True)
    eq = 100_000.0
    rows = [{"date": _DAY0.isoformat(), "as_of": _DAY0.isoformat(), "equity_usd": eq,
             "phase": phase, "mtm_source": mark_source,
             "mtm_today_pct": (marks[0] if marks else 0.0)}]
    for i, r in enumerate(rets, start=1):
        eq *= (1.0 + r)
        day = (_DAY0 + datetime.timedelta(days=i)).isoformat()
        rows.append({"date": day, "as_of": day, "equity_usd": eq, "phase": phase,
                     "mtm_source": mark_source,
                     "mtm_today_pct": (marks[i] if marks and i < len(marks) else 0.0)})
    (d / "realized_series.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n")


def _accrual(n: int, daily: float = 0.0003):
    """A monotone accrual path: rises every day, so its drawdown is 0 BY CONSTRUCTION."""
    return [daily] * n


def _with_loss(n: int, loss: float, at: int, daily: float = 0.0003):
    out = [daily] * n
    out[at] = loss
    return out


class TestForwardBlockIsDefinedByExclusion(unittest.TestCase):
    def test_unknown_future_phase_label_still_counts_as_forward(self):
        """A label this code has never heard of must land INSIDE the judged block."""
        rows = [{"date": "2026-08-05", "phase": "backtest", "equity_usd": 1.0},
                {"date": "2026-08-06", "phase": "live", "equity_usd": 1.0},
                {"date": "2026-08-07", "phase": "paper2", "equity_usd": 1.0},
                {"date": "2026-08-08", "equity_usd": 1.0}]
        fwd = LMG.forward_block(rows)
        self.assertEqual([r["date"] for r in fwd],
                         ["2026-08-06", "2026-08-07", "2026-08-08"])

    def test_backtest_rows_are_never_counted_as_live_marks(self):
        rows = [{"date": f"2026-08-{d:02d}", "phase": "backtest", "equity_usd": 1.0}
                for d in range(5, 20)]
        self.assertEqual(LMG.forward_block(rows), [])

    def test_block_is_returned_in_date_order(self):
        rows = [{"date": "2026-08-09", "phase": "forward", "equity_usd": 1.0},
                {"date": "2026-08-06", "phase": "forward", "equity_usd": 1.0}]
        self.assertEqual([r["date"] for r in LMG.forward_block(rows)],
                         ["2026-08-06", "2026-08-09"])


class TestMonotoneIsStuckNotWaiting(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.panel = Path(self.td.name) / "panel"
        _book(self.panel, "accrual_only", _accrual(89))
        _book(self.panel, "real_loss", _with_loss(89, -0.05, 40))
        _book(self.panel, "sub_toll_loss", _with_loss(89, -0.002, 40))
        _book(self.panel, "frozen", [0.0] * 89)
        self.g = LMG.panel_gate(self.panel)

    def tearDown(self):
        self.td.cleanup()

    def test_accrual_path_is_monotone_and_can_never_be_measurable(self):
        d = self.g["books"]["accrual_only"]
        self.assertTrue(d["monotone"])
        self.assertEqual(d["down_days"], 0)
        self.assertAlmostEqual(d["maxdd"], 0.0, places=12)
        self.assertFalse(d["measurable"])

    def test_a_real_loss_is_measurable(self):
        d = self.g["books"]["real_loss"]
        self.assertFalse(d["monotone"])
        self.assertGreater(d["maxdd"], LMG.toll())
        self.assertTrue(d["measurable"])

    def test_a_sub_toll_loss_moves_but_is_not_measurable(self):
        """Measured and equal to (near) zero — the middle outcome of inv. #17."""
        d = self.g["books"]["sub_toll_loss"]
        self.assertFalse(d["monotone"])
        self.assertEqual(d["down_days"], 1)
        self.assertGreater(d["maxdd"], 0.0)
        self.assertLess(d["maxdd"], LMG.toll())
        self.assertFalse(d["measurable"])

    def test_frozen_is_distinguished_from_monotone(self):
        """Both have maxDD 0; only one of them ever moved."""
        frozen, accrual = self.g["books"]["frozen"], self.g["books"]["accrual_only"]
        self.assertAlmostEqual(frozen["maxdd"], accrual["maxdd"], places=12)
        self.assertTrue(frozen["frozen"])
        self.assertFalse(accrual["frozen"])
        self.assertEqual(frozen["moves"], 0)
        self.assertGreater(accrual["moves"], 0)

    def test_counts_match_the_per_book_rows(self):
        self.assertEqual(self.g["n_measurable"], 1)
        self.assertEqual(self.g["measurable_books"], ["real_loss"])
        self.assertEqual(self.g["n_monotone"], 2)      # accrual_only + frozen
        self.assertEqual(self.g["n_frozen"], 1)


class TestMarksAreNotBookkeeping(unittest.TestCase):
    def test_a_book_with_no_nonzero_mark_has_zero_marked_days(self):
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            _book(panel, "unmarked", _accrual(89))                       # marks default to 0.0
            _book(panel, "marked", _accrual(89), marks=[0.02] * 90)
            g = LMG.panel_gate(panel)
        self.assertEqual(g["books"]["unmarked"]["marked_days"], 0)
        self.assertEqual(g["books"]["marked"]["marked_days"], 90)
        self.assertEqual(g["n_unmarked_books"], 1)

    def test_absent_mark_field_is_not_read_as_a_mark(self):
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel" / "nomark"
            panel.mkdir(parents=True)
            rows = [{"date": (_DAY0 + datetime.timedelta(days=i)).isoformat(),
                     "equity_usd": 100.0 + i, "phase": "forward"} for i in range(90)]
            (panel / "realized_series.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n")
            d = LMG.book_forward(panel / "realized_series.jsonl", t=LMG.toll())
        self.assertEqual(d["marked_days"], 0)
        self.assertIsNone(d["unmeasured"])

    def test_marked_book_days_is_the_sum_over_judged_books(self):
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            _book(panel, "a", _accrual(89), marks=[0.01] * 90)
            _book(panel, "b", _accrual(89), marks=([0.01] * 10) + ([0.0] * 80))
            _book(panel, "c", _accrual(89))
            g = LMG.panel_gate(panel)
        self.assertEqual(g["marked_book_days"], 90 + 10)
        self.assertEqual(g["total_book_days"], 270)


class TestThreeUnitsAreIndependent(unittest.TestCase):
    def test_unit1_open_while_unit3_shut_is_the_whole_finding(self):
        """The panel satisfies the prohibition's NUMBER and cannot satisfy its PURPOSE."""
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            for i in range(10):
                _book(panel, f"accrual_{i}", _accrual(LMG.GATE_DAYS - 1))
            g = LMG.panel_gate(panel)
        self.assertEqual(g["min_days"], LMG.GATE_DAYS)
        self.assertTrue(g["unit1_open"])                       # unit 1: reached
        self.assertEqual(g["marked_book_days"], 0)             # unit 2: nothing marked
        self.assertEqual(g["n_measurable"], 0)                 # unit 3: purpose unmet
        self.assertEqual(g["n_monotone"], 10)                  # and it CANNOT be met

    def test_unit1_shut_while_unit3_open_is_the_opposite_case(self):
        """A short block with a real loss: purpose met, number not. The units do not agree."""
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            _book(panel, "short_loud", _with_loss(20, -0.08, 10), marks=[0.5] * 21)
            g = LMG.panel_gate(panel)
        self.assertLess(g["min_days"], LMG.GATE_DAYS)
        self.assertFalse(g["unit1_open"])
        self.assertEqual(g["n_measurable"], 1)

    def test_gate_days_is_counted_in_rows_never_in_distance_from_today(self):
        """Pins the property the FROZEN-DATE-OK claim rests on: no clock on this path."""
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            _book(panel, "a", _accrual(LMG.GATE_DAYS - 1))
            g = LMG.panel_gate(panel)
        self.assertEqual(g["books"]["a"]["days"], LMG.GATE_DAYS)
        self.assertEqual(g["gate_days"], 90)
        src = SCRIPT.read_text()
        for door in (".now(", ".today(", ".utcnow(", "time.time(", "time.monotonic("):
            self.assertNotIn(door, src, f"{door} is a wall-clock door on this path")


class TestFailsClosed(unittest.TestCase):
    def test_missing_panel_dir_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(LMG.GateUnmeasured):
                LMG.panel_gate(Path(td) / "absent")

    def test_panel_with_no_books_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "panel").mkdir()
            with self.assertRaises(LMG.GateUnmeasured):
                LMG.panel_gate(Path(td) / "panel")

    def test_unreadable_book_is_named_not_counted_as_a_quiet_book(self):
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            _book(panel, "good", _with_loss(89, -0.05, 40))
            bad = panel / "corrupt"
            bad.mkdir(parents=True)
            (bad / "realized_series.jsonl").write_text("{not json\n")
            g = LMG.panel_gate(panel)
        self.assertIsNotNone(g["books"]["corrupt"]["unmeasured"])
        self.assertEqual(g["n_unmeasured"], 1)
        self.assertEqual(g["n_judged"], 1)
        # the corrupt book must NOT inflate any of the three units
        self.assertEqual(g["n_measurable"], 1)
        self.assertEqual(g["total_book_days"], 90)

    def test_book_with_no_forward_rows_is_unmeasured_not_zero_days_of_calm(self):
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            _book(panel, "all_backtest", _accrual(89), phase="backtest")
            _book(panel, "good", _accrual(89))
            g = LMG.panel_gate(panel)
        self.assertEqual(g["books"]["all_backtest"]["unmeasured"], "no forward rows")
        self.assertEqual(g["n_judged"], 1)

    def test_every_book_unreadable_refuses_rather_than_reporting_a_clean_gate(self):
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            for name in ("a", "b"):
                d = panel / name
                d.mkdir(parents=True)
                (d / "realized_series.jsonl").write_text("{broken\n")
            with self.assertRaises(LMG.GateUnmeasured):
                LMG.panel_gate(panel)

    def test_cli_returns_2_when_the_gate_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as td:
            rc = LMG.main(["--panel-dir", str(Path(td) / "absent"),
                           "--data-dir", td])
        self.assertEqual(rc, 2)

    def test_cli_returns_0_and_prints_on_a_readable_gate(self):
        with tempfile.TemporaryDirectory() as td:
            panel = Path(td) / "panel"
            _book(panel, "a", _accrual(89))
            _book(panel, "b", _with_loss(89, -0.05, 40))
            rc = LMG.main(["--panel-dir", str(panel), "--data-dir", td])
        self.assertEqual(rc, 0)


class TestExitNavAndNeighbours(unittest.TestCase):
    def test_exit_nav_presence_is_reported_per_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "rates_desk").mkdir()
            (data / "rates_desk" / "exit_nav.json").write_text("{}")
            rows = LMG.exit_nav_presence(data)
        by_path = {r["path"]: r["present"] for r in rows}
        self.assertTrue(by_path["rates_desk/exit_nav.json"])
        self.assertFalse(by_path["exit_nav.json"])
        self.assertFalse(by_path["aggressive_lab/exit_nav.json"])
        self.assertEqual(len(rows), len(LMG.EXIT_NAV_CANDIDATES))

    def test_neighbour_sources_report_their_refusal_rather_than_a_zero(self):
        """#148 §2 is IMPORTED, never re-implemented; an empty data root is a named reason."""
        with tempfile.TemporaryDirectory() as td:
            out = LMG.neighbour_sources(Path(td))
        self.assertIsNotNone(out.get("unmeasured"))


class TestDeclaredConstants(unittest.TestCase):
    def test_gate_number_and_toll_come_from_their_canon(self):
        self.assertEqual(LMG.GATE_DAYS, 90)
        self.assertAlmostEqual(LMG.toll(), LMG.ens().PLB_ROUNDTRIP, places=12)
        self.assertEqual(LMG.BACKTEST_PHASE, "backtest")

    def test_advisory_flags_are_set(self):
        self.assertTrue(LMG.IS_ADVISORY)
        self.assertTrue(LMG.OUTSIDE_RISKPOLICY)


if __name__ == "__main__":
    unittest.main()
