"""Тесты архива исходов и сопоставления постура×исход (цикл 3 ADR-067).

Ядро: (1) строка исхода — только из наблюдённого, день без evidenced-equity
дату НЕ занимает (иначе пустая строка навсегда закрыла бы день); (2) запись
идемпотентна по дате; (3) join ретро: RED-день с падением форвардной equity =
подтверждение, пар < 5 ⇒ UNCHECKED с динамической причиной — прогресс виден.
Все входы/часы инъектируются; живой data/ не трогается (tmp root).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import outcomes_archive as oa
from spa_core.monitoring.loop_retro import OUTCOME_MIN_PAIRS, analyze_outcomes

NOW = dt.datetime(2030, 7, 10, 9, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: часы инъектируются


def mkroot(td, day="2030-07-10", evidenced=True, with_positions=True):
    os.makedirs(os.path.join(td, "data", "investment_os"), exist_ok=True)
    bar = {"date": day, "close_equity": 100500.0, "daily_return_pct": 0.01}
    if not evidenced:
        bar["source"] = "backfill"
    with open(os.path.join(td, "data", "equity_curve_daily.json"), "w") as f:
        json.dump({"daily": [bar]}, f)
    if with_positions:
        with open(os.path.join(td, "data", "current_positions.json"), "w") as f:
            json.dump({"generated_at": f"{day}T06:00:00+00:00",
                       "positions": {"pendle": 20000.0}, "cash_usd": 15000.0}, f)
    with open(os.path.join(td, "data", "investment_os",
                           "chief_investment_verdicts.jsonl"), "w") as f:
        f.write(json.dumps({"date": day, "posture": "YELLOW"}) + "\n")
    return td


class Archive(unittest.TestCase):
    def test_appends_once_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            mkroot(td)
            r1 = oa.append_daily_outcome(root=td, now=NOW)
            self.assertTrue(r1["appended"])
            line = r1["line"]
            self.assertEqual(line["equity_close"], 100500.0)
            self.assertEqual(line["posture_office"], "YELLOW")
            self.assertEqual(line["positions"], {"pendle": 20000.0})
            r2 = oa.append_daily_outcome(root=td, now=NOW)
            self.assertFalse(r2["appended"])
            self.assertEqual(len(oa.load_outcomes(td)), 1)

    def test_day_without_evidenced_equity_does_not_claim_the_date(self):
        """Пустая строка навсегда заняла бы дату — не пишем, догоняем позже."""
        with tempfile.TemporaryDirectory() as td:
            mkroot(td, evidenced=False)
            r = oa.append_daily_outcome(root=td, now=NOW)
            self.assertFalse(r["appended"])
            self.assertIn("evidenced", r["reason"])
            self.assertEqual(oa.load_outcomes(td), [])

    def test_missing_fields_are_null_with_named_sources(self):
        with tempfile.TemporaryDirectory() as td:
            mkroot(td, with_positions=False)
            os.remove(os.path.join(td, "data", "investment_os",
                                   "chief_investment_verdicts.jsonl"))
            r = oa.append_daily_outcome(root=td, now=NOW)
            line = r["line"]
            self.assertIsNone(line["positions"])
            self.assertIsNone(line["posture_office"])
            self.assertTrue(line["sources"]["positions"])
            self.assertIn("отсутствует", line["sources"]["posture"])


def outcomes_seq(start_equity, returns, base=dt.date(2030, 7, 1)):
    eq, out = start_equity, []
    for i, r in enumerate(returns):
        eq *= (1 + r)
        out.append({"date": (base + dt.timedelta(days=i)).isoformat(),
                    "equity_close": round(eq, 2)})
    return out


class Join(unittest.TestCase):
    def test_red_followed_by_drop_is_confirmed(self):
        outc = outcomes_seq(100000.0, [0.0, -0.01, -0.01, 0.0, 0.0, 0.0, 0.0, 0.0])
        verdicts = [{"date": outc[0]["date"], "posture": "RED"}] + \
                   [{"date": o["date"], "posture": "GREEN"} for o in outc[1:6]]
        stats = analyze_outcomes(verdicts, outc, min_pairs=1)
        self.assertEqual(stats["red_pairs"], 1)
        self.assertEqual(stats["red_confirmed"], 1)
        self.assertEqual(stats["red_confirmation_rate"], 1.0)
        self.assertTrue(stats["measured"])

    def test_red_followed_by_growth_is_not_confirmed(self):
        outc = outcomes_seq(100000.0, [0.0, 0.01, 0.01, 0.0])
        verdicts = [{"date": outc[0]["date"], "posture": "RED"}]
        stats = analyze_outcomes(verdicts, outc, min_pairs=1)
        self.assertEqual(stats["red_confirmed"], 0)
        self.assertEqual(stats["red_confirmation_rate"], 0.0)

    def test_insufficient_pairs_is_unmeasured_with_progress(self):
        outc = outcomes_seq(100000.0, [0.0, 0.001])
        verdicts = [{"date": outc[0]["date"], "posture": "YELLOW"}]
        stats = analyze_outcomes(verdicts, outc)
        self.assertFalse(stats["measured"])
        self.assertIn(f"{OUTCOME_MIN_PAIRS}", stats["note"])
        self.assertEqual(stats["pairs_scored"], 1)

    def test_day_without_outcome_forms_no_pair_no_interpolation(self):
        outc = outcomes_seq(100000.0, [0.0, 0.001, 0.001])
        verdicts = [{"date": "2030-06-15", "posture": "RED"}]  # дня нет в исходах
        stats = analyze_outcomes(verdicts, outc, min_pairs=1)
        self.assertEqual(stats["pairs_scored"], 0)
        self.assertEqual(stats["red_pairs"], 0)


if __name__ == "__main__":
    unittest.main()
