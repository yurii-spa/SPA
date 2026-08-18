"""ADR-089 п.3 — одно определение APY на репозиторий (положительные контроли).

Что случилось. Аллокатор ранжировал книгу по одному числу, а дневной отчёт
показывал владельцу другое: `aave_v3` — 4.80 % против 2.36 %, `pendle` — 14.01 %
при полном отсутствии наблюдения на второй стороне. Причина не в единицах
(проверено численно в `docs/APY_DIVERGENCE_MEASUREMENT.md`, п. 4) и не в
арифметике: у двух путей были РАЗНЫЕ ПРАВИЛА того, что считать наблюдением.

* Аллокатор читал `adapters[*].live_apy` + окно свежести 36 ч — и протокол без
  наблюдения просто не брал.
* Отчёт читал соседнее поле `apy`, а оно при `live_apy: null` — эхо
  `fallback_apy` (`adapter_status_generator`: `apy_used = live_apy if live_apy is
  not None else fallback_pct`). Окна свежести у отчёта не было вовсе.

Замер 2026-08-18 на живом `data/adapter_status.json`: наблюдений НОЛЬ из 34,
а отчёт называл число для всех 34 — то есть печатал константу из реестра
как доходность позиции.

Каждый тест здесь — положительный контроль (`.claude/rules/deployment.md`):
проверено, что на коде ДО правки он краснеет. Сеть не трогается: фикстуры
рукописные, живой фид не опрашивается (`.claude/rules/adapters.md`).

Время — ВХОД: `now` передаётся параметром вместе с фиксированными отметками, так
что ни один тест не протухает от сдвига календаря.
"""
# FROZEN-DATE-OK: injected-clock — `_NOW` это ЯКОРЬ, который передаётся во все
# проверяемые функции параметром `now`, а каждая отметка `live_apy_as_of` строится
# от него же через `_ts(hours_ago=…)`. Обе стороны сравнения закреплены одним
# числом; сдвиг календаря на них не влияет вовсе. Ни одна литеральная дата в
# файле не сравнивается с настоящими часами.
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from spa_core.adapters import status_reader
from spa_core.allocator import allocator as alloc
from spa_core.reporting import daily_telegram_report as rep

# Один момент «сейчас» на весь файл. Литеральных дат в фикстурах нет — все
# отметки строятся ОТ него, поэтому файл бессмертен.
_NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_ago: float) -> str:
    return (_NOW - timedelta(hours=hours_ago)).isoformat()


def _block(live_apy, *, apy, fallback=None, as_of_hours_ago=1.0, **extra) -> dict:
    """Блок `adapters[<protocol>]` в схеме ADR-063."""
    row = {
        "display_name": "Aave V3",
        "apy": apy,
        "live_apy": live_apy,
        "live_apy_as_of": None if live_apy is None else _ts(as_of_hours_ago),
        "fallback_apy": apy if fallback is None else fallback,
        "tier": 1,
        "chain": "ethereum",
        "active": True,
    }
    row.update(extra)
    return row


def _doc(blocks: dict) -> dict:
    return {"generated_at": _ts(0.5), "adapters": blocks}


class TestOneDefinitionOfAnObservation(unittest.TestCase):
    """Наблюдение и литерал обязаны остаться различимыми."""

    def test_literal_echo_is_not_reported_as_a_yield(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — авария в виде теста.

        `live_apy: null`, `apy: 3.5` (= `fallback_apy`). До правки отчёт печатал
        «3.5% APY» рядом с позицией; аллокатор в той же ситуации протокол не брал.
        """
        meta = rep._adapter_meta(_doc({"aave_v3": _block(None, apy=3.5)}), _NOW)
        row = meta["aave_v3"]
        self.assertIsNone(row["apy"], "литерал fallback_apy выдан за наблюдение")
        self.assertEqual(row["apy_reason"], status_reader.APY_NOT_OBSERVED)
        self.assertNotIn("3.5", rep._apy_suffix(row))

    def test_a_real_observation_still_gets_printed(self):
        """Обратная сторона: ужесточение не обязано обнулять честный замер."""
        meta = rep._adapter_meta(_doc({"aave_v3": _block(2.36, apy=2.36)}), _NOW)
        row = meta["aave_v3"]
        self.assertAlmostEqual(row["apy"], 2.36)
        self.assertEqual(row["apy_reason"], status_reader.APY_OBSERVED)
        self.assertIn("2.4% APY", rep._apy_suffix(row))

    def test_absence_is_named_not_silent(self):
        """Пустая строка и «нет наблюдения» читаются по-разному — это и есть смысл."""
        row = rep._adapter_meta(_doc({"aave_v3": _block(None, apy=3.5)}), _NOW)["aave_v3"]
        self.assertTrue(rep._apy_suffix(row).strip(),
                        "отсутствие наблюдения не должно быть молчаливым пропуском")

    def test_stale_observation_is_refused_and_says_why(self):
        """Окно свежести у отчёта раньше отсутствовало вовсе (ось 3 замера)."""
        old = status_reader.EVIDENCE_MAX_AGE_H + 1.0
        row = rep._adapter_meta(
            _doc({"aave_v3": _block(2.36, apy=2.36, as_of_hours_ago=old)}), _NOW
        )["aave_v3"]
        self.assertIsNone(row["apy"])
        self.assertEqual(row["apy_reason"], status_reader.APY_STALE)

    def test_observation_without_a_timestamp_is_not_evidence(self):
        """Неизвестный возраст — не свидетельство (fail-CLOSED, инвариант 2)."""
        blk = _block(2.36, apy=2.36)
        blk["live_apy_as_of"] = None
        row = rep._adapter_meta(_doc({"aave_v3": blk}), _NOW)["aave_v3"]
        self.assertIsNone(row["apy"])
        self.assertEqual(row["apy_reason"], status_reader.APY_UNKNOWN_AGE)


class TestTwoPathsOneNumber(unittest.TestCase):
    """На ОДНИХ входах аллокатор и отчёт обязаны называть ОДНО число."""

    #: Ровно та пара, из-за которой заведена карточка: наблюдение 2.36 %
    #: у одного протокола и никакого наблюдения у второго.
    _BLOCKS = {
        "aave_v3": _block(2.36, apy=2.36),
        "pendle": _block(None, apy=8.0),
    }

    def _paths(self, tmpdir):
        import json
        from pathlib import Path

        d = Path(tmpdir)
        st = d / "adapter_status.json"
        st.write_text(json.dumps(_doc(self._BLOCKS)), encoding="utf-8")
        orch = d / "adapter_orchestrator_status.json"
        orch.write_text(json.dumps({"generated_at": _ts(2.0), "adapters": []}),
                        encoding="utf-8")
        # Путь А — аллокатор: decimal.
        a = {k: v[0] * 100.0
             for k, v in alloc._load_evidenced_apy(orch, st, now=_NOW).items()}
        # Путь Б — отчёт: проценты.
        b = {k: v["apy"]
             for k, v in rep._adapter_meta(_doc(self._BLOCKS), _NOW).items()
             if v["apy"] is not None}
        return a, b

    def test_both_paths_agree_on_the_same_inputs(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — краснеет, если пути снова разъедутся.

        До правки путь Б возвращал ещё и `pendle: 8.0` (эхо `fallback_apy`),
        которого в пути А не было никогда: наборы ключей не совпадали.
        """
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            a, b = self._paths(td)
        self.assertEqual(set(a), set(b),
                         "пути видят РАЗНЫЕ наборы протоколов")
        for k in a:
            self.assertAlmostEqual(
                a[k], b[k], places=6,
                msg=f"{k}: аллокатор {a[k]} % против отчёта {b[k]} %",
            )

    def test_a_hundredfold_unit_slip_is_caught(self):
        """Храповик единиц: decimal×100 обязан совпасть с процентами отчёта."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            a, b = self._paths(td)
        self.assertTrue(a, "фикстура обязана содержать хотя бы одно наблюдение")
        for k in a:
            self.assertLess(abs(a[k] - b[k]), 1e-6)
            self.assertGreater(a[k], 1.0, "проценты выродились в decimal")


class TestTheDefinitionHasExactlyOneHome(unittest.TestCase):
    """Третьей копии правила завестись не должно."""

    def test_freshness_window_does_not_drift_between_copies(self):
        """Аллокатор (money-path, править нельзя) держит приватную копию окна.

        Пока она существует, копии обязаны совпадать — иначе «одно определение»
        живёт только на бумаге. Правильный конец: аллокатор импортирует
        `status_reader.EVIDENCE_MAX_AGE_H` и своей константы не имеет
        (money-path ⇒ решение владельца, карточка `own-2026-08-18-...`).
        """
        self.assertEqual(
            alloc._EVIDENCE_MAX_AGE_H, status_reader.EVIDENCE_MAX_AGE_H,
            "окно свежести разъехалось между аллокатором и status_reader",
        )

    def test_report_does_not_re_derive_the_rule_from_apy(self):
        """Отчёт обязан спрашивать `status_reader`, а не читать `apy` сам."""
        for fn in (rep._adapter_meta, rep._live_apy):
            self.assertIn(
                "observed_apy_pct_fresh", fn.__code__.co_names,
                f"{fn.__name__} снова выводит правило сам, "
                f"вместо единственного определения в status_reader",
            )
            self.assertNotIn(
                "apy_fallback", fn.__code__.co_names,
                f"{fn.__name__} снова подставляет литерал",
            )

    def test_base_registry_literal_is_not_an_input_anymore(self):
        """`apy_fallback` из `_BASE_ADAPTERS_REGISTRY` больше не подставляется.

        ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: до правки пустой `adapter_status.json` давал
        «Aave V3 Base: 4.5% APY (monitoring)» — литерал, зашитый в модуль отчёта.
        """
        rows = rep._collect_base_chain({"adapters": {}}, rep._DEFAULT_DATA_DIR, _NOW)
        for row in rows["adapters"]:
            if row.get("suspended"):
                continue
            self.assertIsNone(
                row["apy"],
                f"{row['label']}: литерал реестра подставлен как наблюдение",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
