"""`landing/src/lib/constitution.json` не смеет разойтись со своим источником (ADR-312).

Файл СГЕНЕРИРОВАН из `data/capital_config.json`. Копия, живущая рядом с источником и
не сверяемая с ним, — это тот же перепечатанный литерал, только в формате JSON: он
точно так же перестаёт быть правдой молча. Разойтись они не могут дольше одного
прогона CI, и это единственное, что делает «одно место» местом.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parents[2]
_TARGET = _REPO / "scripts" / "build_site_constitution.py"


def _load():
    spec = importlib.util.spec_from_file_location("spa_build_site_constitution", _TARGET)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Parity(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_the_generated_file_equals_what_the_generator_would_write_today(self):
        doc, why = self.m.build()
        self.assertEqual(why, "", f"источник не прочитан: {why}")
        live = json.loads(self.m.OUT.read_text(encoding="utf-8"))
        self.assertEqual(
            live, doc,
            "constitution.json разошёлся с data/capital_config.json — "
            "перегенерировать: python3 scripts/build_site_constitution.py")

    def test_every_declared_field_has_a_value(self):
        doc, why = self.m.build()
        self.assertEqual(why, "")
        missing = [k for k in self.m.FIELDS if doc.get(k) is None]
        self.assertEqual(missing, [], f"порог без значения: {missing}")

    def test_the_kill_switch_ladder_matches_governance_not_the_stale_config(self):
        """Порог стоп-крана берётся из governance-слоя, а НЕ из `capital_config`.

        Положительный контроль на настоящую ловушку: в конфиге лежит устаревшее
        одноступенчатое `max_drawdown_kill_pct: 5.0`, и напечатать его на сайте
        значило бы объявить ОДНУ ступень вместо двух (ADR-034/048: SOFT −5 %,
        HARD −10 %). Лестница обязана остаться двухступенчатой.
        """
        from spa_core.governance import kill_switch as ks
        doc, _ = self.m.build()
        ladder = doc["kill_switch"]
        self.assertEqual(ladder["soft_derisk_pct"], float(ks.SOFT_DERISK_THRESHOLD_PCT))
        self.assertEqual(ladder["hard_kill_pct"], float(ks.DRAWDOWN_THRESHOLD_PCT))
        # ...и это ПОВЕДЕНИЕ живого гейта, а не совпавшие числа: проверяется вызовом
        # на обеих границах, а не подстрокой в исходнике.
        self.assertEqual(ks.classify_drawdown_pct(ladder["soft_derisk_pct"] - 0.01)[0],
                         ks.TIER_NONE)
        self.assertEqual(ks.classify_drawdown_pct(ladder["soft_derisk_pct"])[0],
                         ks.TIER_SOFT_DERISK)
        self.assertEqual(ks.classify_drawdown_pct(ladder["hard_kill_pct"])[0],
                         ks.TIER_HARD_KILL)
        # две ступени, а не одна — именно это теряется, если взять число из конфига
        self.assertNotEqual(ladder["soft_derisk_pct"], ladder["hard_kill_pct"])

    def test_the_chain_caps_come_from_the_allocator_not_a_copy(self):
        """Потолки сети — из живого кода (ADR-345/ADR-025), а не переписаны в файл.

        Их нет в `capital_config.json` вовсе, и страница академии печатала
        «Base ≤ 20 %» литералом. Проверка сверяет записанное с КОНСТАНТАМИ класса:
        разойдись они — на сайте будет число, которого в аллокаторе больше нет.
        """
        from spa_core.allocator.allocator import StrategyAllocator

        doc, why = self.m.build()
        self.assertEqual(why, "")
        caps = doc["chain_caps"]
        self.assertAlmostEqual(caps["base_chain_pct"],
                               StrategyAllocator.BASE_CHAIN_CAP * 100.0, places=4)
        self.assertAlmostEqual(caps["l2_total_pct"],
                               StrategyAllocator.L2_TOTAL_CAP * 100.0, places=4)
        self.assertAlmostEqual(caps["single_chain_pct"],
                               StrategyAllocator.SINGLE_CHAIN_CAP * 100.0, places=4)
        self.assertIn("allocator.py", caps["_source"])

    def test_unreadable_chain_caps_refuse_the_whole_document(self):
        """Неполная конституция хуже отсутствующей: страница напечатала бы «нет данных»
        там, где порог ЕСТЬ, — поэтому отказ целиком, а не тихий пропуск поля."""
        from unittest import mock

        with mock.patch.object(self.m, "chain_caps", return_value=({}, "источник молчит")):
            doc, why = self.m.build()
        self.assertEqual(doc, {})
        self.assertIn("источник молчит", why)

    def test_an_unreadable_source_refuses_instead_of_writing_a_stale_copy(self):
        with TemporaryDirectory() as td:
            doc, why = self.m.build(Path(td) / "нет.json")
        self.assertEqual(doc, {})
        self.assertIn("не прочитан", why)

    def test_a_source_missing_a_field_refuses_wholesale(self):
        """fail-CLOSED: неполная конституция хуже отсутствующей."""
        with TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            p.write_text(json.dumps({"capital": {"starting_capital_usd": 1.0}}),
                         encoding="utf-8")
            doc, why = self.m.build(p)
        self.assertEqual(doc, {})
        self.assertIn("нет полей", why)

    def test_the_file_says_it_is_generated(self):
        """Файл, не говорящий о себе «сгенерирован», однажды поправят руками."""
        live = json.loads(self.m.OUT.read_text(encoding="utf-8"))
        self.assertIn("СГЕНЕРИРОВАН", live["note"])
        self.assertIn("capital_config.json", live["source"])


if __name__ == "__main__":
    unittest.main()
