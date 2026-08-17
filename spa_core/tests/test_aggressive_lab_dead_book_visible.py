#!/usr/bin/env python3
"""A DEAD book must be visible to whoever reads the metrics.

THE MEASURED DEFECT (docs/AGGRESSIVE_PANEL_FEEDS.md §5): loader.py and scorecard.py contained not
one mention of ``killed``. The harness writes the flag on every point (harness.py), but nothing
downstream read it. A liquidated book therefore hands the ranking layer a perfectly flat equity
line: zero volatility, zero drawdown, an infinite-looking Calmar — and it beats the LIVE books.
31.7% of the panel was effectively cash pretending to be a strategy.

What these tests DO NOT ask for: a change to the selection rule. The dead book still appears in
every sort order, exactly where the arithmetic puts it. What changes is that the fact stops being
hidden — the consumer can now tell "flat because it died" from "flat because the market was calm",
and can see how much of the panel's capital is dead.

Time is an INPUT (``now_iso`` injected). No network, no live data dir.

Run:  python3 -m pytest spa_core/tests/test_aggressive_lab_dead_book_visible.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategy_lab.aggressive_lab import loader as ld
from spa_core.strategy_lab.aggressive_lab import scorecard as sc

NOW = "2026-06-30T00:00:00+00:00"


def _day(n: int) -> str:
    import datetime
    return (datetime.date(2026, 1, 1) + datetime.timedelta(days=n)).isoformat()


def _write(root: Path, sid: str, points, meta=None) -> None:
    d = root / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / ld.REALIZED_SERIES_NAME).write_text(
        "\n".join(json.dumps(p, sort_keys=True) for p in points) + "\n", encoding="utf-8")
    if meta:
        (d / ld.META_NAME).write_text(json.dumps(meta), encoding="utf-8")


def _pt(i, equity, killed=False, phase="backtest"):
    return {"date": _day(i), "equity_usd": equity, "phase": phase, "killed": killed}


def _panel() -> Path:
    """Three books, 20 backtest points each.

      dead_book  — drops 40%, is KILLED on day 8, then a dead-flat line to the end.
      calm_book  — never killed, flat by nature (a genuinely quiet carry book).
      live_book  — never killed, wobbles.

    dead_book and calm_book end up with an IDENTICAL flat tail. That collision is the point:
    without the killed flag no metric on earth separates them.
    """
    root = Path(tempfile.mkdtemp(prefix="aggr_dead_"))
    dead = []
    eq = 100_000.0
    for i in range(20):
        if i < 8:
            eq *= 0.938  # the liquidation slide
        dead.append(_pt(i, round(eq, 2), killed=(i >= 8)))
    _write(root, "dead_book", dead, meta={"risk_class": "C", "risk_shape": "liquidation"})

    calm = [_pt(i, 100_000.0) for i in range(20)]
    _write(root, "calm_book", calm, meta={"risk_class": "C", "risk_shape": "funding_flip"})

    live = [_pt(i, round(100_000.0 * (1.0 + 0.004 * i + (0.003 if i % 3 else -0.002)), 2))
            for i in range(20)]
    _write(root, "live_book", live, meta={"risk_class": "A", "risk_shape": "funding_flip"})
    return root


class TestLoaderReadsTheKillFlag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _panel()

    def test_loader_reports_the_kill(self):
        s = ld.load_strategy("dead_book", data_dir=self.root)
        self.assertTrue(s.killed)
        self.assertEqual(s.killed_since, _day(8))
        self.assertEqual(s.backtest.n_killed_points, 12)

    def test_loader_reports_a_live_book_as_live(self):
        s = ld.load_strategy("live_book", data_dir=self.root)
        self.assertFalse(s.killed)
        self.assertIsNone(s.killed_since)
        self.assertEqual(s.backtest.n_killed_points, 0)

    def test_a_point_without_the_flag_is_not_evidence_of_death(self):
        """fail-CLOSED cuts the other way here: an OLD point written before the flag existed must
        not be read as 'alive-unknown ⇒ dead'. Absent flag = not killed, and the panel-level
        summary is what tells you nobody in the panel reported a kill."""
        root = Path(tempfile.mkdtemp(prefix="aggr_noflag_"))
        _write(root, "legacy", [{"date": _day(i), "equity_usd": 100.0, "phase": "backtest"}
                                for i in range(5)])
        s = ld.load_strategy("legacy", data_dir=root)
        self.assertFalse(s.killed)


class TestScorecardSurfacesTheKill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _panel()
        cls.doc = sc.build_scorecard(data_dir=cls.root, use_fixture_if_empty=False,
                                     write=False, now_iso=NOW)
        cls.by_id = {e["strategy_id"]: e for e in cls.doc["strategies"]}

    def test_entry_carries_liveness(self):
        dead = self.by_id["dead_book"]
        self.assertFalse(dead["is_alive"])
        self.assertTrue(dead["liveness"]["killed"])
        self.assertEqual(dead["liveness"]["killed_since"], _day(8))

    def test_live_entry_is_alive(self):
        self.assertTrue(self.by_id["live_book"]["is_alive"])
        self.assertFalse(self.by_id["live_book"]["liveness"]["killed"])

    def test_flat_because_dead_is_distinguishable_from_flat_because_calm(self):
        """THE test. Both tails are flat to the last decimal; only the reason differs, and the
        scorecard must now say which."""
        dead = self.by_id["dead_book"]["liveness"]
        calm = self.by_id["calm_book"]["liveness"]
        self.assertEqual(dead["flatline_reason"], "killed")
        self.assertEqual(calm["flatline_reason"], "calm_market")
        self.assertTrue(dead["flat_because_killed"])
        self.assertFalse(calm["flat_because_killed"])

    def test_panel_reports_the_dead_capital_share(self):
        ls = self.doc["liveness_summary"]
        self.assertEqual(ls["n_killed"], 1)
        self.assertEqual(ls["killed_ids"], ["dead_book"])
        self.assertGreater(ls["dead_capital_frac"], 0.0)
        self.assertLess(ls["dead_capital_frac"], 1.0)
        # dead_book's final equity is ~$60k of a ~$280k panel
        self.assertAlmostEqual(
            ls["dead_capital_frac"],
            ls["dead_capital_usd"] / (ls["dead_capital_usd"] + ls["live_capital_usd"]),
            places=9)

    def test_selection_rule_is_unchanged_only_the_fact_is_surfaced(self):
        """We refused to quietly re-rank. The dead book is still in every order, at whatever place
        the arithmetic gives it — the honesty fix is disclosure, not a hidden filter."""
        so = self.doc["sort_orders"]
        self.assertEqual(set(so), {"by_return_desc", "by_sharpe_desc", "by_tail_asc"})
        for order in so.values():
            self.assertIn("dead_book", order)
        self.assertEqual(self.doc["n_strategies"], 3)

    def test_render_table_shows_liveness_to_a_human(self):
        txt = sc.render_table(self.doc)
        self.assertIn("alive", txt.lower())
        self.assertIn("dead capital", txt.lower())


if __name__ == "__main__":
    unittest.main()
