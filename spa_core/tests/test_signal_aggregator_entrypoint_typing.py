"""
test_signal_aggregator_entrypoint_typing.py — «модуль сломан» ≠ «нам нечем его
вызвать». Проверка совместимости входа entrypoint'а (цикл #136, 2026-08-06).

Авария, которую воспроизводят эти тесты. `_ModuleAdapter._invoke` выбирал
entrypoint по `inspect.signature(fn).bind(...)`, а bind проверяет ТОЛЬКО
арность. Для `analyze(inp: BasisTradeInput)` привязка dict'а проходит, модуль
вызывается со словарём вместо своего доменного входа и падает::

    AttributeError: 'dict' object has no attribute 'spot_yield_annual'

Замер 06.08.2026 на Tier-C: 64 модуля числились `failed`, и множество этих 64
ПОИМЁННО совпадало с `_meta.module_status.not_ok.failed` живого прод-отчёта,
то есть отказы были настоящими, а не артефактом харнесса. Но у 62 из 64 первый
параметр entrypoint'а типизирован не-Mapping'ом (дата-классы, `List[...]`) —
ни один из этих модулей не сломан, агрегатору просто нечем построить их вход.
Ярлык `failed` читался как «код сломан, идите чинить 64 модуля»; карточка
`inbox-tier-c-171-iz-180-modulei-ne-otvechayut` так и предлагала — «самая
дешёвая группа, часть чинится тривиально».

Знакомый класс #29/#31/#35–#40: сторож честно отвечает на СВОЙ вопрос («было ли
исключение»), а читается как ответ на нужный («работает ли модуль»).

**Почему разделение делается ПОСЛЕ падения, а не вместо вызова.** Первая версия
починки отказывалась вызывать entrypoint с не-Mapping аннотацией — и погасила
`defi_liquidation_cascade_risk_analyzer`, РАБОТАЮЩИЙ модуль Tier-A (блокирующий
тир): он объявляет `analyze(positions: list[dict])`, но после массовой обвязки
protocol-контекстом принимает и контекст, а аннотацию ему никто не обновил.
Аннотация в этом коде — не гарантия. Поэтому вызываем как раньше, и лишь
УПАВШЕМУ модулю уточняем ярлык. Ни один модуль не перестаёт исполняться;
`test_wired_module_with_stale_annotation_still_runs` держит это навсегда.

Контроль в ОБЕ стороны — иначе «стало меньше failed» ничего не значит:
* модуль с не-Mapping входом → `unchecked` с НАЗВАННОЙ причиной (не молчание);
* модуль, который вход принимает и всё равно падает → по-прежнему `failed`.
  Починка не имеет права глушить настоящий отказ.
* текст исключения сохраняется в ОБОИХ случаях — тише не становится нигде.
"""
from __future__ import annotations

import inspect
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from spa_core.analytics import _module_registry as registry
from spa_core.analytics import signal_aggregator as sa


# ─── Образцы модулей ──────────────────────────────────────────────────────────

@dataclass
class BasisInput:
    spot_yield_annual: float
    perp_funding_annual: float


class TypedEntrypoint:
    """Точная форма реальной аварии: доменный дата-класс на входе."""

    def analyze(self, inp: BasisInput) -> Dict[str, Any]:
        # Ровно то, что падало в проде: dict не имеет атрибутов дата-класса.
        return {"risk_score": inp.spot_yield_annual}


class ListEntrypoint:
    """Форма `defi_leverage_looping_optimizer`: вход валидируется как список."""

    def analyze(self, pools: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(pools, list):
            raise TypeError("pools must be a list")
        return {"risk_score": float(len(pools))}   # pragma: no cover


class MappingEntrypointThatRaises:
    """Принимает Mapping и ВСЁ РАВНО падает — настоящий отказ."""

    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raise ValueError("Missing required keys: ['tvl_usd']")


class UnannotatedEntrypoint:
    """Аннотации нет — судить не по чему, поведение остаётся прежним."""

    def analyze(self, payload):  # noqa: ANN001 — намеренно без аннотации
        return {"risk_score": 42.0}


class StaleAnnotationButWired:
    """Форма `defi_liquidation_cascade_risk_analyzer` (Tier-A, блокирующий).

    Аннотация осталась от легаси-входа, а тело давно принимает контекст.
    Такой модуль обязан по-прежнему ИСПОЛНЯТЬСЯ.
    """

    def analyze(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(positions, dict) and "protocol" in positions:
            return {"risk_score": float(len(positions["protocol"]))}
        return {"risk_score": 0.0}   # pragma: no cover — легаси-ветка


class VarKwargsEntrypoint:
    """Контекст уезжает в **kwargs — аннотация к нему не относится."""

    def analyze(self, **kwargs: Any) -> Dict[str, Any]:
        return {"risk_score": 7.0}


def _run(cls) -> tuple:
    """Прогнать образец через настоящий адаптер, минуя импорт по имени."""
    adapter = sa._ModuleAdapter({"module": "sample", "class": cls.__name__})
    adapter._import_callable = lambda: cls()   # type: ignore[method-assign]
    return adapter.run("aave_v3", {"source": "test"})


# ─── Положительный контроль: реальная авария ─────────────────────────────────

class TypedEntrypointIsNotAFailure(unittest.TestCase):

    def test_old_arity_only_check_would_have_called_it(self):
        """Тест целится в НАСТОЯЩИЙ пробел, а не в соломенное чучело.

        Если bind перестанет принимать dict для `analyze(inp: BasisInput)`,
        то аварии, ради которой всё это написано, не существует — и тест ниже
        зеленел бы по неверной причине.
        """
        sig = inspect.signature(TypedEntrypoint().analyze)
        sig.bind({"source": "test", "protocol": "aave_v3"})   # НЕ бросает

    def test_typed_entrypoint_is_unchecked_not_failed(self):
        score, status, detail = _run(TypedEntrypoint)
        self.assertIsNone(score)
        self.assertEqual(status, "unchecked", f"должно быть unchecked, detail={detail}")
        self.assertNotEqual(status, "failed", "модуль не сломан — его нечем вызвать")

    def test_reason_names_the_required_type(self):
        """Причина ОБЯЗАНА быть названа: «unchecked» без неё — то же молчание."""
        _score, _status, detail = _run(TypedEntrypoint)
        self.assertIn("BasisInput", detail)
        self.assertIn("analyze", detail)
        self.assertIn("non-mapping", detail)

    def test_list_entrypoint_also_unchecked(self):
        _score, status, detail = _run(ListEntrypoint)
        self.assertEqual(status, "unchecked")
        self.assertIn("pools", detail)
        self.assertIn("pools must be a list", detail)   # диагноз сохранён

    def test_original_exception_is_kept_in_detail(self):
        """Ярлык уточнён, диагноз НЕ потерян — иначе это было бы приглушение."""
        _score, _status, detail = _run(TypedEntrypoint)
        self.assertIn("has no attribute", detail)
        self.assertIn("AttributeError", detail)


# ─── Контроль в обратную сторону: настоящий отказ обязан остаться failed ─────

class GenuineFailuresStayLoud(unittest.TestCase):

    def test_mapping_entrypoint_that_raises_is_still_failed(self):
        score, status, detail = _run(MappingEntrypointThatRaises)
        self.assertIsNone(score)
        self.assertEqual(status, "failed",
                         "починка не имеет права глушить настоящий отказ")
        self.assertIn("Missing required keys", detail)

    def test_unannotated_entrypoint_still_invoked(self):
        """Нет аннотации → вызываем, как и раньше. Fail-OPEN ровно здесь."""
        score, status, _detail = _run(UnannotatedEntrypoint)
        self.assertEqual(status, "ok")
        self.assertEqual(score, 42.0)

    def test_var_kwargs_entrypoint_still_invoked(self):
        score, status, _detail = _run(VarKwargsEntrypoint)
        self.assertEqual(status, "ok")
        self.assertEqual(score, 7.0)

    def test_wired_module_with_stale_annotation_still_runs(self):
        """Регрессия на реальную ошибку первой версии починки.

        Аннотация `List[Dict]` устарела, тело принимает контекст — модуль
        обязан ИСПОЛНЯТЬСЯ. Отказ по аннотации погасил бы блокирующий сигнал
        Tier-A (`defi_liquidation_cascade_risk_analyzer`).
        """
        score, status, detail = _run(StaleAnnotationButWired)
        self.assertEqual(status, "ok", f"работающий модуль погашен: {detail}")
        self.assertEqual(score, float(len("aave_v3")))


# ─── Таблица истинности проверки аннотации ───────────────────────────────────

class AnnotationAcceptsMapping(unittest.TestCase):

    def test_mapping_like_annotations_accepted(self):
        for ann in (dict, Dict[str, Any], Mapping[str, Any], Any, object,
                    Optional[dict], inspect.Parameter.empty):
            with self.subTest(ann=ann):
                self.assertTrue(sa._annotation_accepts_mapping(ann))

    def test_non_mapping_annotations_rejected(self):
        for ann in (BasisInput, List[Dict[str, Any]], list, str, int, float,
                    Optional[str], type(None)):
            with self.subTest(ann=ann):
                self.assertFalse(sa._annotation_accepts_mapping(ann))

    def test_string_annotations_both_directions(self):
        """`from __future__ import annotations` отдаёт аннотацию строкой."""
        for text in ("dict", "Dict[str, Any]", "Optional[dict]", "dict | None",
                     "typing.Mapping[str, Any]", "Any"):
            with self.subTest(text=text):
                self.assertTrue(sa._annotation_accepts_mapping(text))
        for text in ("BasisTradeInput", "List[ProtocolDebtInput]", "list[dict]",
                     "str", "Optional[str]"):
            with self.subTest(text=text):
                self.assertFalse(sa._annotation_accepts_mapping(text))


# ─── Регрессия на НАСТОЯЩИХ модулях Tier-C ───────────────────────────────────

class RealTierCModules(unittest.TestCase):
    """Образцы — это гипотеза; ниже проверяются те самые модули из аварии."""

    @staticmethod
    def _adapter(name: str):
        info = next((m for m in registry.get_tier_modules("C")
                     if m["module"] == name), None)
        if info is None:                      # pragma: no cover
            raise unittest.SkipTest(f"модуль {name} отсутствует в реестре Tier-C")
        return sa._ModuleAdapter(info)

    def test_basis_trade_analyzer_no_longer_counts_as_broken(self):
        """Тот самый модуль, чей AttributeError открыл находку."""
        _score, status, detail = self._adapter(
            "basis_trade_analyzer").run("aave_v3", {"source": "test"})
        self.assertEqual(status, "unchecked", f"detail={detail}")
        self.assertIn("BasisTradeInput", detail)

    def test_module_needing_real_data_stays_failed(self):
        """`protocol_adoption_scorer` принимает Dict и падает на нехватке
        данных — это НАСТОЯЩИЙ отказ, и он обязан остаться громким."""
        _score, status, detail = self._adapter(
            "protocol_adoption_scorer").run("aave_v3", {"source": "test"})
        self.assertEqual(status, "failed", f"detail={detail}")

    def test_working_modules_are_untouched(self):
        """Опубликованное число не должно шевельнуться.

        Девять ok-модулей Tier-C дают ту самую константу avg_score. Если бы
        починка задела их, менялся бы артефакт — а она обязана менять только
        ЯРЛЫК у тех, кого и так не вызывали.
        """
        ok = []
        for info in registry.get_tier_modules("C"):
            score, status, _d = sa._ModuleAdapter(info).run(
                "aave_v3", {"source": "test"})
            if status == "ok":
                ok.append((info["module"], score))
        self.assertEqual(len(ok), 9, f"ожидались те же 9 ok-модулей, получено {ok}")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
