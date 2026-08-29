"""Перепись модулей аналитики ВНЕ тиров — знаменатель метрики 90 %.

ЗАЧЕМ ЭТОТ ФАЙЛ. Метрика «% работающего слоя» (директива владельца 2026-08-03)
считалась от знаменателя 736 при реестре тиров в 671 модуль и 754 публичных файлах
на диске. Разница — 83 модуля, которые не измерял НИКТО: они не попадали ни в одну
корзину аудита и потому не могли ни улучшить метрику, ни ухудшить её. Знаменатель, в
котором часть корпуса просто отсутствует, — не строгая оценка, а незнание, выдающее
себя за оценку.

КАЖДЫЙ ТЕСТ НИЖЕ — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ настоящей ошибки, допущенной при постройке
переписи 2026-08-29, а не украшение:

1. `test_registry_key_is_package_qualified` — первый прогон сравнивал имя файла с
   именем реестра БЕЗ префикса подпакета и намерил 98 «внетировых» вместо 83:
   пятнадцать модулей `gross_of/` записаны в реестре как `gross_of.<имя>`, а на диске
   читались как `<имя>` и ложно объявлялись незарегистрированными.
2. `test_private_classes_are_not_candidates` — первый прогон зачислил в кандидаты САМ
   `signal_aggregator`: у него есть `_ModuleAdapter.run`, формально подходящий под
   критерий «класс с методом-входом». Адаптер — механизм ВЫЗОВА модулей, а не модуль;
   перепись предложила бы агрегатору звать самого себя.
3. `test_base_stub_is_not_called_dormant` — 21 модуль классифицировался как `dormant`
   («результат не приводится к score»), и ярлык уводил в сторону: измеренная причина
   у всех одна и другая — `analyze()` не реализован, наследуется заглушка
   `BaseAnalytics`, возвращающая пустой dict. `dormant` зовёт чинить данные,
   `inherits_base_stub` — писать реализацию.

Перепись read-only: ничего не исполняет в проде, `data/` не трогает, капитал не
двигает, реестр тиров не правит.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CENSUS_TOOL = REPO_ROOT / "scripts" / "audit_untiered_analytics.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("_census_tool_under_test", CENSUS_TOOL)
    assert spec and spec.loader, f"не загружается {CENSUS_TOOL}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_census_tool_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class CensusKeys(unittest.TestCase):
    """Ключ модуля строится ТОЧНО так же, как имя в реестре."""

    def test_registry_key_is_package_qualified(self):
        """Положительный контроль ошибки №1: `gross_of/x.py` → `gross_of.x`, не `x`.

        Наивный ключ (имя файла) разошёлся бы с реестром на пятнадцати модулях
        подпакета и раздул бы «вне тиров» с 83 до 98 — то есть придумал бы работу,
        которой нет, и исказил знаменатель метрики в другую сторону."""
        tool = _load_tool()
        on_disk = tool.modules_on_disk()
        sub = [k for k in on_disk if k.startswith("gross_of.")]
        self.assertTrue(sub, "в пакете нет ни одного модуля gross_of — тест ослеп")
        for key in sub:
            self.assertIn(".", key, f"ключ {key!r} потерял префикс подпакета")

        from spa_core.analytics import _module_registry as registry
        known = {m["module"] for m in registry.ALL_MODULES}
        registered_sub = {k for k in sub if k in known}
        self.assertTrue(
            registered_sub,
            "ни один модуль gross_of не совпал с реестром — значит ключ снова "
            "строится не так, как имя реестра (ровно ошибка первого прогона)")

    def test_untiered_is_disk_minus_registry_and_nothing_else(self):
        tool = _load_tool()
        from spa_core.analytics import _module_registry as registry
        known = {m["module"] for m in registry.ALL_MODULES}
        untiered = tool.untiered_modules()
        self.assertEqual(set(untiered) & known, set(),
                         "в «вне тиров» попал зарегистрированный модуль")
        for name, path in untiered.items():
            self.assertTrue((REPO_ROOT / path).exists(), f"{name}: файла {path} нет")

    def test_no_registered_module_lacks_a_file(self):
        """Обратная сторона: имя в реестре без файла на диске — тоже дыра знаменателя."""
        tool = _load_tool()
        from spa_core.analytics import _module_registry as registry
        known = {m["module"] for m in registry.ALL_MODULES}
        ghosts = sorted(known - set(tool.modules_on_disk()))
        self.assertEqual(ghosts, [], f"в реестре есть имена без файла: {ghosts}")


class CensusCandidates(unittest.TestCase):
    """Кто считается кандидатом в модули сигнала, а кто — механизмом."""

    def test_private_classes_are_not_candidates(self):
        """Положительный контроль ошибки №2: `signal_aggregator` — не кандидат.

        У него есть `_ModuleAdapter.run`. Единственный признак, отделивший механизм
        вызова от модуля сигнала без списка исключений из головы, — приватное имя."""
        tool = _load_tool()
        cls, entry, verdict, _reason = tool.find_entrypoint("signal_aggregator")
        self.assertEqual(verdict, "not_a_signal_module",
                         f"агрегатор зачислен кандидатом через {cls}.{entry} — "
                         f"он звал бы сам себя")

    def test_a_public_class_with_an_entrypoint_is_a_candidate(self):
        """Обратный контроль: критерий не «всё запрещать».

        Без этой стороны предыдущий тест проходил бы и у сломанного детектора,
        который не признаёт кандидатом вообще ничего."""
        tool = _load_tool()
        from spa_core.analytics import _module_registry as registry
        sample = next(m for m in registry.get_tier_modules("A") if m.get("class"))
        cls, entry, verdict, reason = tool.find_entrypoint(sample["module"])
        self.assertEqual(verdict, "callable",
                         f"{sample['module']} — рабочий модуль Tier-A, а детектор "
                         f"сказал {verdict!r} ({reason})")
        self.assertTrue(cls and entry)


class CensusStubDetection(unittest.TestCase):
    """`analyze()` не написан — это НЕ «модуль поспал»."""

    def test_base_stub_returns_empty_dict(self):
        """Опора остальных тестов: заглушка действительно пуста.

        Если базовый класс однажды начнёт возвращать что-то осмысленное, вся ветка
        `inherits_base_stub` станет неверной — и узнать об этом надо здесь."""
        from spa_core.base import BaseAnalytics

        class _Probe(BaseAnalytics):
            pass

        self.assertEqual(_Probe().analyze({"protocol": "aave_v3"}), {})

    def test_base_stub_is_not_called_dormant(self):
        """Положительный контроль ошибки №3 на РЕАЛЬНОМ модуле из переписи.

        `var_calculator.VaRCalculator` не реализует `analyze()`. Прогон даёт
        `dormant`; перепись обязана назвать точную причину, а не общий ярлык."""
        tool = _load_tool()
        implementor = tool.entrypoint_implementor(
            "var_calculator", "VaRCalculator", "analyze")
        self.assertEqual(
            implementor, "BaseAnalytics",
            "точка входа var_calculator больше не наследуется от базового класса — "
            "либо модуль починили (тогда обновить перепись), либо измеритель врёт")

    def test_the_census_labels_stub_inheritors_by_their_real_cause(self):
        """Уточнение ярлыка обязано доезжать до РАЗМЕТКИ, а не жить в измерителе.

        Мутация «убрать уточнение из `run_census`» оставила бы предыдущий тест
        зелёным: он спрашивает измеритель напрямую. Этот спрашивает результат —
        21 модуль обязан лежать в INHERITS_BASE_STUB, а не растворяться в кандидатах."""
        from spa_core.analytics import _untiered_census as census
        self.assertIn(
            "var_calculator", census.INHERITS_BASE_STUB,
            "модуль с ненаписанным входом не помечен в разметке — уточнение "
            "не доехало от измерителя до файла")
        self.assertNotIn("var_calculator", census.WIRABLE,
                         "ненаписанный вход числится кандидатом в реестр")

    def test_no_wirable_candidate_is_actually_a_stub(self):
        """Обратная сторона: в кандидатах не должно остаться ни одной заглушки."""
        tool = _load_tool()
        from spa_core.analytics import _untiered_census as census
        stubs = []
        for name, note in census.WIRABLE.items():
            cls = note.split("класс ", 1)[-1].split(".")[0] if "класс " in note else None
            entry = note.rsplit(".", 1)[-1] if "." in note else "analyze"
            if cls and tool.entrypoint_implementor(name, cls, entry) == "BaseAnalytics":
                stubs.append(name)
        self.assertEqual(stubs, [],
                         f"в кандидатах лежат модули с ненаписанным входом: {stubs}")

    def test_a_registry_entry_without_a_class_is_still_measurable(self):
        """Различие настоящего вызывающего и наивной выемки — на классах, которых НЕТ.

        У 158 записей реестра поля `class` нет вовсе: агрегатор передаёт исполнителю
        сам МОДУЛЬ и зовёт функции уровня модуля. Наивная выемка
        (`getattr(mod, class_name)`) на такой записи даже не формулируется —
        `class_name` равен None, — и молча возвращает «не знаю». Настоящий
        вызывающий отвечает `module-level`.

        Это ЕДИНСТВЕННОЕ поведенческое различие между двумя выемками, которое видно
        снаружи: там, где поле `class` есть, обе дают один ответ. Поэтому тест
        построен ровно на нём — числовой порог, который я написал сначала, обе
        выемки проходили одинаково, то есть не проверял ничего."""
        tool = _load_tool()
        from spa_core.analytics import _module_registry as registry

        classless = [m for m in registry.ALL_MODULES if not m.get("class")]
        self.assertTrue(
            classless,
            "в реестре не осталось записей без поля `class` — тест потерял предмет")

        answered = [m["module"] for m in classless[:12]
                    if tool.entrypoint_implementor(
                        m["module"], m.get("class"), "analyze") is not None]
        self.assertTrue(
            answered,
            "ни на одной записи без поля `class` измеритель не дал ответа — он "
            "вернулся к наивной выемке, которая такую запись сформулировать не может")


class CensusMarkupMatchesMeasurement(unittest.TestCase):
    """Разметка в пакете обязана совпадать с тем, что мерит инструмент."""

    def test_census_module_is_importable_and_named(self):
        from spa_core.analytics import _untiered_census as census
        self.assertTrue(census.AUDIT_GENERATED_AT)
        self.assertEqual(
            len(census.ALL_UNTIERED),
            len(census.OUT_OF_DENOMINATOR) + len(census.WIRABLE),
            "наборы переписи пересекаются — модуль попал в две корзины сразу")

    def test_every_censused_name_is_really_untiered(self):
        """Фантом в переписи = исключили из знаменателя то, чего там не было."""
        from spa_core.analytics import _untiered_census as census
        from spa_core.analytics import _module_registry as registry
        known = {m["module"] for m in registry.ALL_MODULES}
        wrong = sorted(set(census.ALL_UNTIERED) & known)
        self.assertEqual(wrong, [],
                         f"перепись называет внетировыми модули из реестра: {wrong}")

    def test_every_out_of_denominator_name_carries_a_reason(self):
        """Исключение из знаменателя без причины — это молчаливое списание."""
        from spa_core.analytics import _untiered_census as census
        for bucket in (census.DEPRECATED_TOMBSTONE, census.IMPORT_FAILED,
                       census.NOT_A_SIGNAL_MODULE, census.INHERITS_BASE_STUB):
            for name, reason in bucket.items():
                self.assertTrue(
                    reason and len(reason) > 10,
                    f"{name}: исключён из знаменателя без названной причины")

    def test_census_covers_every_untiered_module_on_disk(self):
        """Главное свойство: после переписи неизмеренных не остаётся.

        Ради этого всё и делалось. Модуль, которого нет ни в реестре тиров, ни в
        переписи, снова невидим для метрики — ровно исходный дефект."""
        tool = _load_tool()
        from spa_core.analytics import _untiered_census as census
        missed = sorted(set(tool.untiered_modules()) - set(census.ALL_UNTIERED))
        self.assertEqual(
            missed, [],
            f"{len(missed)} модул(ей) вне тиров И вне переписи — они снова невидимы "
            f"для метрики: {missed[:8]}")


if __name__ == "__main__":
    unittest.main()
