"""Сторож роя знает ВСЕ законные состояния книги сторожа — из словаря производителя.

Тревога после перезагрузки 15.10 (карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere`):
`com.spa.swarm_health` выходил с кодом 1 — `guardian_forward unknown guardian states:
[eth_directional, leverage_loop, …, susde_spot]`. Разбор: у девяти книг стояло
`NOTHING_TO_PROTECT` — законное состояние порога применимости (ADR-206, решение владельца
01.09: на ровной книге сторож не срабатывает и честно пишет это). Плохим был не производитель,
а СЛОВАРЬ сторожа — своя копия из четырёх слов, отставшая от ADR-206.

Починка — словарь ОДИН и живёт у производителя (`guardian_forward.GUARDIAN_BOOK_STATES`).
Положительные контроли: живая форма 16.10 и настоящий вывод `_guard_book` на фикстуре
01.09 — красные на origin 8f913113, зелёные после; обратный контроль — выдуманное
состояние по-прежнему ловится.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.strategy_lab.swarm import guardian_forward as gf
from spa_core.strategy_lab.swarm import swarm_health as sh
from spa_core.tests.test_guardian_forward_applicability import FIXTURE, _book_dir

#: Дословный набор состояний `data/swarm/guardian_forward.json` на 2026-10-16T02:21Z.
LIVE_2026_10_16 = {
    "eth_directional": "NOTHING_TO_PROTECT", "leverage_loop": "NOTHING_TO_PROTECT",
    "levered_restaking": "NOTHING_TO_PROTECT", "lp_eth_stable": "NOTHING_TO_PROTECT",
    "lrt_neutral": "ARMED", "pendle_pt_levered": "NOTHING_TO_PROTECT",
    "pendle_yt_susde": "NOTHING_TO_PROTECT", "points_farm": "NOTHING_TO_PROTECT",
    "susde_dn": "NOTHING_TO_PROTECT", "susde_spot": "NOTHING_TO_PROTECT",
}


def _doc(states: dict) -> dict:
    return {"books": {n: {"state": s} for n, s in states.items()}}


class GuardianVocabulary(unittest.TestCase):
    def test_live_shape_of_16_10_passes_the_contract(self):
        ok, why = sh._contract_check("guardian_forward", _doc(LIVE_2026_10_16))
        self.assertTrue(ok, why)
        self.assertEqual(why, "10 books, states valid")

    def test_real_producer_output_passes_the_contract(self):
        raw = json.loads(FIXTURE.read_text())
        books = {}
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("leverage_loop", "lrt_neutral"):
                books[name] = gf._guard_book(_book_dir(Path(tmp), name, raw[name]))
        self.assertEqual(books["leverage_loop"]["state"], gf.NOTHING_TO_PROTECT)
        ok, why = sh._contract_check("guardian_forward", {"books": books})
        self.assertTrue(ok, why)

    def test_an_invented_state_is_still_caught(self):
        ok, why = sh._contract_check("guardian_forward",
                                     _doc({"susde_dn": "ARMED", "x": "BOGUS"}))
        self.assertFalse(ok)
        self.assertEqual(why, "unknown guardian states: ['x']")

    def test_vocabulary_has_one_home(self):
        self.assertIs(sh.GUARDIAN_BOOK_STATES, gf.GUARDIAN_BOOK_STATES)
        self.assertIn(gf.NOTHING_TO_PROTECT, gf.GUARDIAN_BOOK_STATES)


if __name__ == "__main__":
    unittest.main()
