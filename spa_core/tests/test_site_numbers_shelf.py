#!/usr/bin/env python3
"""Витрина чисел сайта: один адрес чтения, недельный такт, годовые ставки.

Установка владельца 12.09 (ADR-357 п. 5): все числа сайта берутся из одного места,
обновление раз в неделю, форма — годовая в среднем. Причина, которую он назвал, важнее
настроек: «каждый раз вы у меня спрашиваете одно и то же» — повторяющийся вопрос был
следствием того, что у чисел не было одного адреса.

**Главное, что здесь сторожится, — что витрина НЕ СТАЛА ТРЕТЬИМ ИСТОЧНИКОМ.**
`.claude/rules/site-numbers.md` запрещает третье место для чисел, и запрет остаётся:
источников два (замер стареет за сутки, порог не стареет вовсе), а витрина — их
проекция. Проверяется это структурно: у КАЖДОГО числа витрины обязан быть `source`,
указывающий на один из двух источников. Число без источника и есть третье место.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_bsn", ROOT / "scripts" / "build_site_numbers.py")
bsn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bsn)

SNAP = {
    "as_of": "2026-09-13",
    "real_track_days": 82,
    "evidenced_anchor": "2026-06-22",
    "paper_apy_pct": 5.0092,
    "max_drawdown_pct": -0.0393,
    "nav_usd": 101256.44,
    "gates_passed": 29, "gates_total": 29,
    "go_live_state": "gate_passed_owner_decision_pending",
    "paper_tracks": {
        "conservative": {"status": "paper_test_running", "days_with_positions": 82,
                         "apy_pct": 5.01, "dd_pct": -0.0393, "nav_usd": 101256.44,
                         "evidence": "paper", "observed_accrual_since": "2026-06-22"},
        "balanced": {"status": "paper_test_running", "days_with_positions": 21,
                     "apy_pct": 2.8, "dd_pct": -0.31, "nav_usd": 100188.29,
                     "evidence": "paper", "observed_accrual_since": "2026-09-10"},
        "aggressive": {"status": "paper_test_running", "days_with_positions": 21,
                       "apy_pct": 7.62, "dd_pct": -0.15, "nav_usd": 100500.0,
                       "evidence": "paper", "observed_accrual_since": "2026-09-10"},
    },
}
CONST = {
    "kill_switch": {"soft_derisk_pct": 5.0, "hard_kill_pct": 10.0},
    "chain_caps": {"single_chain_pct": 90.0, "l2_total_pct": 50.0, "base_chain_pct": 20.0},
    "start_capital_usd": 100000.0, "min_cash_buffer_pct": 5.0,
    "max_per_protocol_t1_pct": 40.0, "max_per_protocol_t2_pct": 20.0,
    "max_t2_total_pct": 50.0, "tvl_floor_usd": 5000000, "apy_floor_pct": 1.0,
    "apy_ceiling_pct": 30.0, "min_paper_days_before_live": 30,
}


class _Scene(unittest.TestCase):
    """Источники подставляются во временный каталог: живой сайт не читается."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_shelf_"))
        self._snap, self._const = bsn.SNAPSHOT, bsn.CONSTITUTION
        bsn.SNAPSHOT = self.d / "track_snapshot.json"
        bsn.CONSTITUTION = self.d / "constitution.json"

    def tearDown(self):
        bsn.SNAPSHOT, bsn.CONSTITUTION = self._snap, self._const
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, snap=None, const=None):
        bsn.SNAPSHOT.write_text(json.dumps(SNAP if snap is None else snap), encoding="utf-8")
        bsn.CONSTITUTION.write_text(json.dumps(CONST if const is None else const), encoding="utf-8")


def _figures(doc) -> list:
    """Все числа витрины — то есть словари, у которых есть ключ `value`."""
    out = []
    def walk(o):
        if isinstance(o, dict):
            if "value" in o and "unit" in o:
                out.append(o)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(doc)
    return out


class TheShelfIsAProjectionNotASource(_Scene):
    def test_every_number_names_the_source_it_came_from(self):
        """Число без источника и есть ТРЕТЬЕ место — то, что правило запрещает."""
        self.write()
        figs = _figures(bsn.build(published_at="2026-09-13"))
        self.assertGreater(len(figs), 10, "витрина подозрительно пуста")
        for f in figs:
            self.assertTrue(f.get("source"), f"число без источника: {f}")
            self.assertTrue(
                "track_snapshot.json" in f["source"] or "constitution.json" in f["source"],
                f"источник не из двух объявленных: {f['source']}")

    def test_every_number_declares_its_kind(self):
        """Замер или решение — третьего рода не бывает (правило site-numbers)."""
        self.write()
        for f in _figures(bsn.build(published_at="2026-09-13")):
            self.assertIn(f.get("kind"), (bsn.MEASUREMENT, bsn.DECISION), f)


class RatesAreAnnualisedAndSayHow(_Scene):
    def test_every_rate_is_marked_annualised_with_a_named_method(self):
        """«Годовая» без метода — намерение, а не число."""
        self.write()
        doc = bsn.build(published_at="2026-09-13")
        for path in (doc["headline"]["apy"], doc["books"]["conservative"]["apy"],
                     doc["books"]["balanced"]["apy"], doc["books"]["aggressive"]["apy"]):
            self.assertTrue(path.get("annualised"), path)
            self.assertIn("365", path.get("annualisation", ""), "метод не назван")

    def test_a_threshold_is_never_marked_annualised(self):
        """Порог не ставка: пометить его годовым значило бы соврать о роде."""
        self.write()
        for f in bsn.build(published_at="2026-09-13")["thresholds"].values():
            self.assertNotIn("annualised", f, f)


class TheTailTravelsWithTheRate(_Scene):
    def test_every_book_carries_its_drawdown_beside_its_rate(self):
        """Инв. #8: доходность без хвоста на этом сайте не публикуется."""
        self.write()
        for book in bsn.build(published_at="2026-09-13")["books"].values():
            self.assertIn("apy", book)
            self.assertIn("drawdown", book)


class TheLiteralDaysAreNamedBesideTheNumber(_Scene):
    """Обязательство ADR-357 п. 4 — идёт вместе с решением, решением не является."""

    def test_a_book_accrued_partly_on_literals_says_so(self):
        self.write()
        split = bsn.build(published_at="2026-09-13")["books"]["aggressive"]["evidence_split"]
        self.assertEqual((split["literal_days"], split["observed_days"]), (17, 4))
        self.assertIn("17 из 21", split["caveat"])

    def test_a_fully_observed_book_carries_no_caveat(self):
        """Обратная сторона: оговорка не вешается на книгу, которой она не нужна."""
        self.write()
        split = bsn.build(published_at="2026-09-13")["books"]["conservative"]["evidence_split"]
        self.assertEqual(split["literal_days"], 0)
        self.assertIsNone(split["caveat"])

    def test_an_unmeasured_switch_date_is_not_zero_literal_days(self):
        """Инв. #17: «не знаем долю» и «доля равна нулю» — разные факты."""
        snap = json.loads(json.dumps(SNAP))
        snap["paper_tracks"]["aggressive"].pop("observed_accrual_since")
        self.write(snap=snap)
        split = bsn.build(published_at="2026-09-13")["books"]["aggressive"]["evidence_split"]
        self.assertIsNone(split["literal_days"])
        self.assertIn("НЕ ИЗВЕСТНА", split["unmeasured_reason"])


class TwoDatesNotOne(_Scene):
    def test_the_measurement_date_and_the_publication_date_are_both_present(self):
        """Наблюдение ежедневное, публикация недельная — смешать их значит соврать."""
        self.write()
        doc = bsn.build(published_at="2026-09-20")
        self.assertEqual(doc["measured_at"], "2026-09-13")
        self.assertEqual(doc["published_at"], "2026-09-20")
        self.assertEqual(doc["next_publication"], "2026-09-27")
        self.assertEqual(doc["cadence"], "weekly")


class AbsenceIsNeverAStaleLiteral(_Scene):
    def test_a_missing_value_is_null_with_a_named_reason(self):
        snap = json.loads(json.dumps(SNAP))
        snap["paper_apy_pct"] = None
        self.write(snap=snap)
        apy = bsn.build(published_at="2026-09-13")["headline"]["apy"]
        self.assertIsNone(apy["value"])
        self.assertTrue(apy["unavailable_reason"])

    def test_a_boolean_is_not_a_number(self):
        """`True` прошло бы как 1.0 — то же семейство, что `observed_number`."""
        self.assertIsNone(bsn._num(True))
        self.assertIsNone(bsn._num(None))
        self.assertEqual(bsn._num("5.2"), 5.2)


class TheShelfRefusesWholesale(_Scene):
    """Половинчатая витрина хуже отсутствующей: часть чисел свежая, часть прошлая."""

    def test_a_missing_source_refuses(self):
        bsn.CONSTITUTION.write_text(json.dumps(CONST), encoding="utf-8")
        with self.assertRaises(bsn.NotMeasured) as ctx:
            bsn.build()
        self.assertIn("track_snapshot", str(ctx.exception))

    def test_an_unparsable_source_refuses(self):
        bsn.SNAPSHOT.write_text("{не json", encoding="utf-8")
        bsn.CONSTITUTION.write_text(json.dumps(CONST), encoding="utf-8")
        with self.assertRaises(bsn.NotMeasured) as ctx:
            bsn.build()
        self.assertIn("не разобран", str(ctx.exception))

    def test_a_snapshot_without_required_fields_refuses(self):
        snap = json.loads(json.dumps(SNAP))
        snap.pop("evidenced_anchor")
        self.write(snap=snap)
        with self.assertRaises(bsn.NotMeasured) as ctx:
            bsn.build()
        self.assertIn("evidenced_anchor", str(ctx.exception))

    def test_the_cli_returns_two_for_not_measured(self):
        """Код возврата разделяет исходы: 2 — не измерено, а не «пусто, но ок»."""
        self.assertEqual(bsn.main(["--published-at", "2026-09-13"]), 2)


if __name__ == "__main__":
    unittest.main()


class TheWeeklyCadenceLivesInTheFileNotTheSchedule(_Scene):
    """Такт недельный ПО РЕШЕНИЮ владельца, а не по частоте запуска агента.

    Если бы срок решало расписание, он менялся бы вместе с ним — и «раз в неделю»
    держалось бы на том, что никто не трогал cron. Срок решает файл.
    """

    def setUp(self):
        super().setUp()
        self._out = bsn.OUT
        bsn.OUT = self.d / "site_numbers.json"

    def tearDown(self):
        bsn.OUT = self._out
        super().tearDown()

    def test_no_shelf_at_all_means_publish(self):
        due, why = bsn.publication_due(today="2026-09-13")
        self.assertTrue(due)
        self.assertIn("первая публикация", why)

    def test_six_days_is_not_due_and_seven_is(self):
        bsn.OUT.write_text(json.dumps({"published_at": "2026-09-13"}), encoding="utf-8")
        self.assertFalse(bsn.publication_due(today="2026-09-19")[0])
        self.assertTrue(bsn.publication_due(today="2026-09-20")[0])

    def test_an_unreadable_date_publishes_rather_than_assuming_freshness(self):
        """«Не прочитали, когда публиковали» ≠ «публиковали недавно» (инв. #17)."""
        bsn.OUT.write_text(json.dumps({"published_at": "позавчера"}), encoding="utf-8")
        due, why = bsn.publication_due(today="2026-09-13")
        self.assertTrue(due, "неразобранная дата молча выдана за свежую")
        self.assertIn("не прочитана", why)

    def test_if_due_does_not_rewrite_within_the_week(self):
        self.write()
        bsn.OUT.write_text(json.dumps({"published_at": "2026-09-13"}), encoding="utf-8")
        before = bsn.OUT.read_text(encoding="utf-8")
        self.assertEqual(bsn.main(["--if-due", "--published-at", "2026-09-15"]), 0)
        self.assertEqual(bsn.OUT.read_text(encoding="utf-8"), before,
                         "витрина переписана раньше срока — такт держится не файлом")
