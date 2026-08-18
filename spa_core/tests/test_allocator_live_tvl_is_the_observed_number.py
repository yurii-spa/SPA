"""Метка «живое» и ЧИСЛО обязаны ехать вместе (ADR-095 п.3, решение владельца 18.08).

Дефект, ради которого файл написан. В ветке снимка оркестратора
(``StrategyAllocator._load_adapters``) живое наблюдение из закреплённого пула читалось в
``tvl_evidence``, ставило ``tvl_source="live"`` — и **выбрасывалось**: в строку кандидата
уезжал литерал адаптера. Лог при этом обещал «replaces the adapter literal», чего не
происходило.

Цена измерена, а не предположена: пул с наблюдённым размером **$2.6M проходил floor $5M по
константе $800M** и НЕ попадал в ``_tvl_floor_unverified`` — сторож молчал именно потому,
что метка врала. Прямое нарушение `.claude/rules/risk-engine.md`: «Never stamp `live` on a
constant», и тот же класс, что moonwell-190×: ``_filter_by_tvl`` судит по ЧИСЛУ, а доверие к
числу — по МЕТКЕ.

Соседний registry-путь того же метода написан правильно с самого начала — там наблюдение
попадает И в число, И в метку. Дефект асимметричный, ровно один из двух путей, поэтому
проверка стоит на ПОВЕДЕНИИ, а не на чтении кода.

Почему тест снимает пайтест-охрану `tvl_evidence`. Под pytest карта наблюдений намеренно
пуста (`_load_adapters` не читает живой `data/`), то есть саму чинимую ветку иначе не
исполнить. Здесь охрана снимается ТОЧЕЧНО и вместе с ней подставляется фикстура — живой
`data/` не читается ни разу, что и было целью охраны.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.allocator import allocator as A
from spa_core.allocator.allocator import StrategyAllocator
from spa_core.tests._freshness import ts as _ts

#: Наблюдение из закреплённого пула — НИЖЕ порога $5M.
OBSERVED_SMALL = 2_600_000.0
#: Литерал адаптера — на два порядка выше, порог проходит.
ADAPTER_LITERAL = 800_000_000.0

_PROTO = "morpho_steakhouse"


def _rows(evidence: dict[str, tuple[float, str]]) -> list[dict]:
    """Строки кандидатов из ветки снимка при заданной карте наблюдений TVL."""
    snapshot = {"adapters": [{
        "protocol": _PROTO,
        "status": "ok",
        "apy_pct": 3.25,
        "tvl_usd": ADAPTER_LITERAL,
        "tvl_source": "static",
        "tier": "T1",
        # ОТНОСИТЕЛЬНАЯ отметка: литеральная дата рядом с понятием свежести —
        # бомба замедленного действия, и храповик дат честно на ней покраснел
        # (моя же правка, поймана сверкой через час). Предмет теста —
        # ЧИСЛО TVL рядом с меткой, а не дата, поэтому шаблон 2 из `_freshness`.
        "last_updated": _ts(hours_ago=1),
    }]}
    with TemporaryDirectory() as td:
        status = Path(td) / "adapter_status.json"
        status.write_text(json.dumps(snapshot), encoding="utf-8")
        alloc = StrategyAllocator(
            status_path=status,
            registry_path=Path(td) / "no_registry.json",   # реестровый мёрдж выключен
            live_apy_provider={_PROTO: 0.0325},            # APY инъектирован, сети нет
            strategy_loop_enabled=False,
        )
        # Точечно: охрана `PYTEST_CURRENT_TEST` иначе оставит карту пустой и ветку
        # неисполнимой. Живой `data/` при этом не читается — вместо него фикстура.
        with mock.patch.dict(A.os.environ, {}, clear=False) as env:
            env.pop("PYTEST_CURRENT_TEST", None)
            with mock.patch.object(A, "_load_evidenced_tvl", return_value=evidence), \
                 mock.patch.object(A, "_load_evidenced_apy", return_value={}):
                return [r for r in alloc._load_adapters() if r["protocol"] == _PROTO]


class TestObservationReachesTheRow(unittest.TestCase):
    """Живое наблюдение обязано попасть В СТРОКУ, а не только в метку."""

    def test_row_carries_the_observed_number_not_the_literal(self):
        rows = _rows({_PROTO: (OBSERVED_SMALL, "931ea9be-5f4d-428e")})
        self.assertTrue(rows, "кандидат исчез — проверять нечего")
        row = rows[0]
        self.assertEqual(row["tvl_source"], "live")
        self.assertEqual(
            float(row["tvl_usd"]), OBSERVED_SMALL,
            "метка сказала «живое», а число осталось литералом адаптера — ровно тот "
            "дефект, из-за которого $2.6M проходили порог $5M",
        )

    def test_without_an_observation_the_literal_stays_static(self):
        """Обратный контроль: нет наблюдения — нет и метки «живое»."""
        rows = _rows({})
        self.assertTrue(rows)
        self.assertEqual(rows[0]["tvl_source"], "static")
        self.assertEqual(float(rows[0]["tvl_usd"]), ADAPTER_LITERAL)


class TestFloorJudgesTheNumberItWasGiven(unittest.TestCase):
    """Приёмочный критерий владельца: порог судится по наблюдению, не по константе."""

    def _alloc(self):
        alloc = StrategyAllocator.__new__(StrategyAllocator)
        alloc._tvl_floor_unverified = []
        return alloc

    def test_observed_below_floor_is_rejected(self):
        """Рядом стоит законный кандидат — иначе сработает fail-safe фильтра.

        `_filter_by_tvl` при отсеве ВСЕХ кандидатов возвращает исходный список
        («книга не становится all-cash из-за сломанного источника»). Это
        существующее и намеренное поведение, поэтому проверять отсев на одиноком
        кандидате нельзя — первая версия теста именно на этом и покраснела, и
        права была она, а не код.
        """
        alloc = self._alloc()
        ok, rejected = alloc._filter_by_tvl([
            {"protocol": _PROTO, "tvl_usd": OBSERVED_SMALL, "tvl_source": "live"},
            {"protocol": "susde", "tvl_usd": 1_560_000_000.0, "tvl_source": "live"},
        ])
        self.assertEqual([r["protocol"] for r in ok], ["susde"])
        self.assertEqual(rejected, [_PROTO])

    def test_observed_above_floor_passes_and_is_not_called_unverified(self):
        alloc = self._alloc()
        ok, rejected = alloc._filter_by_tvl(
            [{"protocol": _PROTO, "tvl_usd": 106_500_000.0, "tvl_source": "live"}])
        self.assertEqual([r["protocol"] for r in ok], [_PROTO])
        self.assertEqual(rejected, [])
        self.assertEqual(alloc._tvl_floor_unverified, [])

    def test_a_constant_never_verifies_the_floor(self):
        """Главное сужение: починка не разрешает константам судить порог."""
        alloc = self._alloc()
        ok, _rejected = alloc._filter_by_tvl(
            [{"protocol": "aave_v3", "tvl_usd": 12_000_000_000.0,
              "tvl_source": "static"}])
        self.assertEqual([r["protocol"] for r in ok], ["aave_v3"])
        self.assertEqual(
            alloc._tvl_floor_unverified, ["aave_v3"],
            "константа выше порога исчезла из списка неверифицированных — "
            "это «never stamp live on a constant» наоборот",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
