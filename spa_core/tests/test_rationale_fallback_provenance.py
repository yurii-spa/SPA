"""Запасная ветка провенанса судит по тому же правилу, что аллокатор.

Спящий дефект, найденный 2026-08-09 при разведке перед money-path.

`write_shadow_rationale` решает, у каких протоколов TVL «наблюдён». Основной путь
берёт карту провенанса от аллокатора. Если карты нет, включается запасная ветка —
и она засчитывала наблюдением **любой непустой `tvl_usd`**. Одиннадцать адаптеров
отдают захардкоженный литерал `TVL_USD`, то есть по этой ветке константа проходила
за наблюдение — прямое нарушение правила «`live` никогда не ставится на константу»
(`.claude/rules/risk-engine.md`, ADR-053).

Дефект **спал**: в живом цикле карта приходит (замерено 09.08 — 13 `live` / 5
`static`), и ветка не срабатывает. Проснулся бы он в тот день, когда провенанса нет
вовсе — то есть когда данных меньше всего, а осторожность нужнее всего. Ровно тот
класс, что уже закрывался в проекте: сторож, отвечающий уверенно там, где должен
отвечать «не знаю».

Соседний комментарий в коде обещает именно это: `tvl_known` отличает «посмотрели, и
там static» от «посмотреть не смогли», и второе обязано быть UNCHECKED. Запасная
ветка это обещание нарушала.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.paper_trading.allocation_rationale import write_shadow_rationale


def _orch(*rows: dict) -> dict:
    return {"adapters": list(rows)}


def _names(orch: dict) -> list:
    return [a["protocol"] for a in orch["adapters"]]


class TestFallbackBehaviour(unittest.TestCase):
    """Поведенческая проверка — долг, закрытый 2026-08-09 следующим витком.

    Имена протоколов НАСТОЯЩИЕ (`aave_v3`, `maple`) намеренно: с выдуманными
    fail-CLOSED срабатывал по причине `tier_unknown`, и тест зеленел бы, ничего
    не доказывая о провенансе TVL. Проверка обязана падать на своём предмете,
    а не на соседнем.

    Виток назад я объявил её невозможной: искал множество наблюдённых как отдельное
    поле документа, не нашёл и записал долг карточкой. Наблюдаемое поле всё это время
    было рядом — `decision_shadow.evidence.tvl_unevidenced_in_target`, тот самый
    список, которым пользуется соседний `test_allocation_rationale_shadow`.

    Вывод не про этот тест: «я не нашёл» было записано как «этого нет». Формулировка
    честнее — «не нашёл, где смотреть», и она бы не остановила работу.
    """

    def _doc(self, *rows: dict) -> dict:
        names = [r["protocol"] for r in rows]
        with TemporaryDirectory() as t:
            d = Path(t)
            (d / "adapter_orchestrator_status.json").write_text(
                json.dumps({"adapters": list(rows)}), encoding="utf-8")
            write_shadow_rationale(
                data_dir=d,
                current_positions={},
                target_positions={p: 10_000.0 for p in names},
                apy_pct={p: 4.0 for p in names},
                apy_sources={p: "live" for p in names},
                capital_usd=100_000.0,
                cycle_date="2026-08-09",
                run_ts="2026-08-09T12:00:00Z",
                tvl_sources=None,          # ← карты нет: работает запасная ветка
            )
            return json.loads((d / "allocation_rationale.json").read_text(encoding="utf-8"))

    def _unevidenced(self, *rows: dict) -> list:
        return self._doc(*rows)["decision_shadow"]["evidence"]["tvl_unevidenced_in_target"]

    def test_a_declared_live_tvl_counts_as_evidence(self):
        got = self._unevidenced(
            {"protocol": "aave_v3", "tvl_usd": 9_000_000.0, "tvl_source": "live"})
        self.assertNotIn("aave_v3", got,
                         "объявленный живой провенанс — настоящее наблюдение")

    # Проверок «снимок только из литералов» здесь НЕТ намеренно. При нулевом числе
    # наблюдений атрибуция уходит в fail-CLOSED целиком, и статус становится
    # `attribution_incomplete` — но по причине, которую этот файл не проверяет.
    # Тест, зеленеющий по соседнему поводу, доказывает не то, что заявляет; эта
    # ветка закреплена отдельно в `test_allocation_rationale_shadow`.

    def test_both_kinds_in_one_snapshot_are_separated(self):
        """Проверка не «пропускает всё» и не «режет всё»."""
        got = self._unevidenced(
            {"protocol": "aave_v3", "tvl_usd": 9_000_000.0, "tvl_source": "live"},
            {"protocol": "maple", "tvl_usd": 20_000_000.0, "tvl_source": "static"})
        self.assertNotIn("aave_v3", got)
        self.assertIn("maple", got)


class TestTheDefinitionMatchesTheAllocator(unittest.TestCase):
    """Одно определение на всех — иначе копии разойдутся при первой правке."""

    def test_the_fallback_requires_a_declared_live_source(self):
        src = Path(__file__).resolve().parents[1] / "paper_trading" / "allocation_rationale.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn('a.get("tvl_source") == "live"', text,
                      "запасная ветка обязана требовать объявленный провенанс")


if __name__ == "__main__":
    unittest.main()
