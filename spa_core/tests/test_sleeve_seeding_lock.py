"""Засев рукавов Balanced не может быть заблокирован навсегда (мандат владельца 08.08).

Инцидент: условие самозасева требовало ПУСТОЙ истории и НУЛЯ выполненных циклов,
но первый же прогон дописывал в историю запись с нулевым капиталом — и засев
становился невозможен НАВСЕГДА. Замер 2026-08-08: HY 918 циклов, LP 929 циклов
вхолостую с 22.06; книги нулевые, агенты живы, «работа» имитировалась.
Класс дефекта — «замок, который нельзя открыть» (ср. go-live на невосстановимых
дырах трека, ADR-067).

Проверки в обе стороны:
  * книга без денег и с историей нулей — ЗАСЕВАЕТСЯ (реплей инцидента);
  * книга, у которой капитал БЫЛ и обнулился, — НЕ засевается (это потеря,
    её разбирают, а не затирают свежим сидом; fail-closed);
  * профинансированная книга не трогается.
"""
from __future__ import annotations

import unittest
from pathlib import Path

#: Дерево этого чекаута. Путь от cwd краснел в CI (`cd spa_core && pytest tests/`) —
#: тест судил бы о рабочем каталоге прогона, а не о боевом модуле (замер 14.08).
_REPO = Path(__file__).resolve().parents[2]


def _seed_decision(state: dict) -> bool:
    """Копия боевого условия (hy_cycle/lp_cycle) — если оно изменится, тест
    обязан быть обновлён вместе с ним; смысл проверки от этого не зависит."""
    hist = state.get("daily_history") or []
    ever_funded = any(float(h.get("equity", 0) or 0) > 0 for h in hist)
    return (float(state.get("seed_equity", 0) or 0) <= 0
            and float(state.get("equity", 0) or 0) <= 0
            and not ever_funded)


class SeedingLock(unittest.TestCase):
    def test_zero_history_does_not_block_seeding(self):
        """Реплей инцидента: 40 записей с нулём и 918 циклов — засев ОБЯЗАН пройти."""
        state = {"seed_equity": 0.0, "equity": 0.0, "cycles_completed": 918,
                 "daily_history": [{"date": f"2026-06-{d:02d}", "equity": 0.0}
                                   for d in range(1, 31)]}
        self.assertTrue(_seed_decision(state))

    def test_fresh_state_seeds(self):
        self.assertTrue(_seed_decision({"seed_equity": 0.0, "equity": 0.0,
                                        "daily_history": []}))

    def test_book_that_had_money_is_never_reseeded(self):
        """Обнулившаяся книга — потеря, а не «свежая»: сид её не затирает."""
        state = {"seed_equity": 0.0, "equity": 0.0, "cycles_completed": 5,
                 "daily_history": [{"date": "2026-07-01", "equity": 20_000.0},
                                   {"date": "2026-07-02", "equity": 0.0}]}
        self.assertFalse(_seed_decision(state))

    def test_funded_book_is_untouched(self):
        self.assertFalse(_seed_decision({"seed_equity": 20_000.0, "equity": 19_500.0,
                                         "daily_history": []}))

    def test_live_modules_use_this_condition(self):
        """Условие в бою и в тесте — одно и то же (иначе тест охраняет фантом)."""
        for mod in ("hy_cycle", "lp_cycle"):
            path = _REPO / "spa_core" / "paper_trading" / f"{mod}.py"
            self.assertTrue(path.is_file(), f"{mod}: боевого модуля нет в этом чекауте — {path}")
            src = path.read_text(encoding="utf-8")
            self.assertIn("_ever_funded", src, f"{mod}: боевое условие не обновлено")
            self.assertNotIn('and not state.get("daily_history")', src,
                             f"{mod}: старый вечный замок вернулся")


if __name__ == "__main__":
    unittest.main()
