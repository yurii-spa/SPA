"""ADR-514 — критерий §49 `Marginal return` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Прибор предельной доходности (`spa_core/monitoring/marginal_apy_at_size.py`,
цикл #493) отвечает на вопрос владельца «Position size влияет на expected yield»
с сентября, и его артефакт свеж (замер 29.09 — 4,0 ч при объявленном пределе
7 ч). А сводный замер §49 (`scripts/cio_acceptance_rollup.py`) про этот критерий
отвечал

    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ —
     вердикт сегодня взять неоткуда»

потому что запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ и не
канонической формулировкой: конституция писала `§49 «Marginal return»`, то есть
форму `quoted`. Это ВТОРАЯ привязка цены `WORDING` (первая — `Costs`, ADR-513).

Находка цикла #731, из-за которой привязке предшествовала правка прибора
------------------------------------------------------------------------
Главный ответ прибора был **напечатанным предложением**: находка
`objective_is_linear_in_rate` добавлялась в отчёт БЕЗУСЛОВНО, с готовым текстом,
при любом снимке, — и прежний сторож требовал ровно этого («present regardless
of the snapshot»). Претензия верна и сегодня; проверял её код не разу. Перенести
такую находку в машинный вердикт значило бы перенести прозу — то есть сделать
ровно тот дефект, против которого вся эта работа и ведётся. Поэтому сперва
претензия стала ЗАМЕРОМ (`objective_size_sensitivity` спрашивает живой
доходностный член целевой функции дважды: при крошечной позиции и при
наибольшей разрешённой политикой), и только потом — привязкой.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `marginal_return_size_changes_expected_yield` красна на дефекте и зелена
  на контуре, где целевая функция на размер РЕАГИРУЕТ, — и второе достижимо
  только подменой самой целевой функции, а не фикстурой рядом;
* переносится поле `criterion.status` прибора, а НЕ его `overall`: `overall` —
  лестница ТЯЖЕСТИ, где третий исход стои́т выше `CRITICAL` намеренно
  (`test_unchecked_outranks_critical_in_overall`), и проба, перенёсшая его,
  спрятала бы измеренное красное за «не измерено» — инвариант #17 наизнанку;
* своего порога у пробы НЕТ ни одного: границы сцены задаёт `TunerConstraints`
  владельца (потолок концентрации, TVL-floor);
* прибор, не объявивший себя мерой `§49 Marginal return`, ⇒ `unmeasured`; якорь
  читается как НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный вердикт прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `data_dir` и `now` ДОХОДЯТ до прибора, и проверяется это по ИСХОДУ пробы;
  `repo_root` пробой НЕ объявлен намеренно — код целевой функции приходит
  импортом по `sys.path`, а не из дерева, и объявить его входом значило бы
  соврать о проводке (отдельный контроль ниже);
* проба НЕ ПИШЕТ артефакт прибора: `write=False` проверяется по ВЫЗОВУ.

Порядок контроля НЕ произволен: сначала доказывается, что сцена даёт ИМЕННО те
породы прибора (`TestSceneReproducesTheMeasuredKinds`), и только потом — что
проба на них отвечает. Без первого шага «красно на порванном звене»
тавтологично.

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348). Дат в
файле нет вовсе: у прибора нет ни одного суждения о свежести. Сеть не трогается,
живое `data/` не читается — материал пишется в одноразовый каталог.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import marginal_apy_at_size as M
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "marginal_return_size_changes_expected_yield"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Marginal return"

#: Живая книга 29.09 — пять ног, все с НАБЛЮДЁННЫМ TVL. Сцена не выдумана: это
#: те же ключи и те же порядки величин, на которых прибор даёт сегодняшний
#: вердикт, и именно поэтому «знаменатель наблюдён у всего капитала» здесь
#: достижимо, а не подогнано.
_BOOK = {"aave_v3": 5_000.0, "compound_v3": 40_000.0, "fluid_fusdc": 20_000.0,
         "maple": 20_000.0, "morpho_blue_base": 10_000.0}
_TVL = {"aave_v3": 190_524_954.0, "compound_v3": 36_394_816.0,
        "fluid_fusdc": 131_446_656.0, "maple": 2_902_334_467.0,
        "morpho_blue_base": 424_451_097.0}
_APY = {"aave_v3": 3.5749, "compound_v3": 4.7131, "fluid_fusdc": 4.47,
        "maple": 5.1442, "morpho_blue_base": 4.4477}


class _Objective:
    """Подставной модуль целевой функции: меняется РОВНО доходностный член.

    Потолки политики (`TunerConstraints`) берутся НАСТОЯЩИЕ и переносятся сюда
    как есть. Иначе подмена меняла бы разом две вещи — и вопрос «реагирует ли
    целевая функция на размер» подменился бы вопросом «прочитались ли пороги»,
    а контроль был бы тавтологичным.
    """

    def __init__(self, tuner_cls):
        from spa_core.tuner.allocation_tuner import TunerConstraints

        self.TunerConstraints = TunerConstraints
        self.AllocationTuner = tuner_cls


class _SizeAwareTuner:
    """Целевая функция, которая на размер РЕАГИРУЕТ.

    Единственный способ добраться до зелёного вердикта критерия — и это не
    удобство теста, а его предмет: зелёное состояние системы сегодня НЕ
    СУЩЕСТВУЕТ, а контроль, не умеющий его показать, не отличил бы работающую
    пробу от постоянно красной.
    """

    def _weighted_apy(self, weights, adapter_data):
        rates = {a["id"]: float(a.get("apy") or 0.0) for a in adapter_data}
        return sum(w * (rates.get(pid, 0.0) - w) for pid, w in weights.items())


class _TunerWithoutTheYieldTerm:
    """Доходностный член унесли или переименовали."""


class _Scene(unittest.TestCase):
    """Одноразовое дерево: материал в `data/`, живое `data/` не трогается."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        # Якорь считается ЗДЕСЬ, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        self.build()

    def build(self, *, book=None, live_for=None, capital=100_000.0) -> None:
        book = _BOOK if book is None else book
        live = set(_TVL) if live_for is None else live_for
        self._write(self.data_dir / "adapter_status.json", {"adapters": {
            key: {"tvl_usd": _TVL[key],
                  "tvl_source": "live" if key in live else "static",
                  "apy": _APY[key], "apy_base": _APY[key], "apy_reward": 0.0}
            for key in _TVL}})
        self._write(self.data_dir / "current_positions.json",
                    {"capital_usd": capital, "positions": dict(book)})

    @staticmethod
    def _write(path: Path, doc) -> None:
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def _swap_objective(self, module) -> None:
        saved = sys.modules.get(M.OBJECTIVE_MODULE)
        had = M.OBJECTIVE_MODULE in sys.modules
        sys.modules[M.OBJECTIVE_MODULE] = module

        def _restore():
            if had:
                sys.modules[M.OBJECTIVE_MODULE] = saved
            else:
                sys.modules.pop(M.OBJECTIVE_MODULE, None)

        self.addCleanup(_restore)

    def measure(self) -> dict:
        return M.run(root=str(self.root), write=False,
                     data_dir=str(self.data_dir), now=self.now)

    def probe(self, *, now=None, data_dir=None) -> tuple:
        """Проба зовётся ПО ИМЕНИ ИЗ РЕЕСТРА — иначе контроль проверял бы функцию,
        а не то, что реестр отдаёт именно её."""
        fn = ca.PROBES[PROBE_NAME]
        return fn(None, now=now or self.now,
                  data_dir=data_dir or str(self.data_dir))


class TestSceneReproducesTheMeasuredKinds(_Scene):
    """СНАЧАЛА доказывается, что сцена даёт именно те породы прибора."""

    def test_the_live_objective_is_reproduced_as_a_FOUND_finding(self):
        rep = self.measure()
        self.assertEqual(rep["criterion"]["found"], ["objective_is_linear_in_rate"])
        self.assertEqual(rep["unchecked"], [])
        self.assertTrue(rep["objective_size_sensitivity"]["measured"])

    def test_a_size_aware_objective_empties_the_FOUND_axis(self):
        self._swap_objective(_Objective(_SizeAwareTuner))
        rep = self.measure()
        self.assertEqual(rep["criterion"]["found"], [])
        self.assertEqual(rep["criterion"]["compared"],
                         ["objective_reacts_to_our_size"])
        self.assertEqual(rep["criterion"]["status"], M.CRITERION_SATISFIED,
                         rep["criterion"]["reason"])

    def test_a_literal_denominator_is_reproduced_as_UNOBSERVED(self):
        self.build(live_for=set(_TVL) - {"maple"})
        rep = self.measure()
        self.assertIn("denominator_is_a_literal", rep["criterion"]["unobserved"])

    def test_an_unaskable_objective_is_reproduced_as_UNCHECKED(self):
        self._swap_objective(_Objective(_TunerWithoutTheYieldTerm))
        rep = self.measure()
        self.assertTrue(rep["unchecked"])
        self.assertEqual(rep["criterion"]["found"], [])


class TestTheProbeTransfersTheInstrumentsVerdict(_Scene):
    def test_the_live_objective_is_NOT_SATISFIED(self):
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("objective_is_linear_in_rate", detail)

    def test_a_size_aware_objective_is_SATISFIED(self):
        self._swap_objective(_Objective(_SizeAwareTuner))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_an_empty_book_is_UNMEASURED_not_green(self):
        """«Размер учитывается» про пустую книгу — тишина мёртвого дерева."""
        self._swap_objective(_Objective(_SizeAwareTuner))
        self.build(book={})
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("мёртвого дерева", detail)

    def test_a_literal_denominator_alone_is_UNMEASURED(self):
        self._swap_objective(_Objective(_SizeAwareTuner))
        self.build(live_for=set(_TVL) - {"maple"})
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("denominator_is_a_literal", detail)

    def test_an_unreadable_book_is_UNMEASURED(self):
        (self.data_dir / "current_positions.json").unlink()
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("книга не прочитана", detail)

    def test_an_unaskable_objective_is_UNMEASURED_not_the_old_default(self):
        """Порванное звено НЕ возвращает прежнее умолчание «функция линейна»."""
        self._swap_objective(_Objective(_TunerWithoutTheYieldTerm))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("НЕ СПРОСИЛИ", detail)
        self.assertIn(M.OBJECTIVE_YIELD_TERM, detail)

    def test_the_blind_spots_are_NAMED_in_every_verdict(self):
        """Критерий владельца шире сегодняшней меры, и это сказано вслух."""
        scenes = ("живая", "реагирующая", "пустая книга")
        for scene in scenes:
            with self.subTest(scene=scene):
                if scene == "реагирующая":
                    self._swap_objective(_Objective(_SizeAwareTuner))
                if scene == "пустая книга":
                    self.build(book={})
                _, detail = self.probe()
                self.assertIn("сцена замера синтетическая", detail)


class TestTheProbeDoesNotInheritTheSeverityLadder(_Scene):
    """Находка существования не тонет в «не измерено» — инвариант #17 наизнанку."""

    def test_a_found_finding_survives_an_unchecked_alongside(self):
        self.build(live_for=set())         # все знаменатели литеральны
        rep = self.measure()
        self.assertEqual(rep["overall"], "UNCHECKED",
                         "сцена не воспроизвела маскировку")
        self.assertTrue(rep["unchecked"])
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED,
                         f"находка спрятана за «не измерено»: {detail}")

    def test_the_probe_does_not_read_overall_at_all(self):
        """Прямой контроль проводки: `overall` подменён, вердикт не дрогнул."""
        real_run = M.run

        def _run_with_a_lying_overall(*a, **kw):
            rep = real_run(*a, **kw)
            rep["overall"] = "OK"
            return rep

        M.run = _run_with_a_lying_overall
        self.addCleanup(lambda: setattr(M, "run", real_run))
        verdict, _ = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED)


class TestTheDeclarationIsCheckedByAnchorNotBySubstring(_Scene):
    def _with_module(self, stub):
        saved = sys.modules.get(ca.MARGINAL_RETURN_MODULE)
        sys.modules[ca.MARGINAL_RETURN_MODULE] = stub
        self.addCleanup(
            lambda: sys.modules.__setitem__(ca.MARGINAL_RETURN_MODULE, saved)
            if saved is not None
            else sys.modules.pop(ca.MARGINAL_RETURN_MODULE, None))

    def test_an_instrument_that_declares_nothing_is_UNMEASURED(self):
        class _Stub:
            CRITERION = ""
        self._with_module(_Stub())
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_a_MENTION_of_Marginal_return_is_not_a_declaration(self):
        class _Stub:
            CRITERION = "заметка про Marginal return где-то в середине строки"
        self._with_module(_Stub())
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_anchor_must_START_the_declaration_not_merely_occur_in_it(self):
        """Ровно та мутация, которую «есть ли подстрока» пропускает."""
        class _Stub:
            CRITERION = "подробности про §49 Marginal return смотри в соседнем ADR"
        self._with_module(_Stub())
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_real_instrument_declares_the_anchor(self):
        self.assertTrue(M.CRITERION.startswith("§49 Marginal return"))


class TestFailClosedOnAnythingUnknown(_Scene):
    def _stub(self, block):
        outer = self

        class _Stub:
            CRITERION = M.CRITERION
            CRITERION_SATISFIED = M.CRITERION_SATISFIED
            CRITERION_NOT_SATISFIED = M.CRITERION_NOT_SATISFIED
            CRITERION_UNMEASURED = M.CRITERION_UNMEASURED

            @staticmethod
            def run(**kw):
                doc = dict(outer.measure())
                if block is None:
                    doc.pop("criterion", None)
                else:
                    doc["criterion"] = block
                return doc

        saved = sys.modules.get(ca.MARGINAL_RETURN_MODULE)
        sys.modules[ca.MARGINAL_RETURN_MODULE] = _Stub()
        self.addCleanup(
            lambda: sys.modules.__setitem__(ca.MARGINAL_RETURN_MODULE, saved)
            if saved is not None
            else sys.modules.pop(ca.MARGINAL_RETURN_MODULE, None))

    def test_an_unknown_criterion_status_is_UNMEASURED_not_satisfied(self):
        self._stub({"status": "ЧТО-ТО НОВОЕ", "reason": "…"})
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не переносится", detail)

    def test_a_missing_criterion_block_is_UNMEASURED(self):
        self._stub(None)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не вынес вердикта", detail)

    def test_an_instrument_that_falls_over_is_UNMEASURED(self):
        class _Stub:
            CRITERION = M.CRITERION

            @staticmethod
            def run(**kw):
                raise RuntimeError("прибор упал")

        saved = sys.modules.get(ca.MARGINAL_RETURN_MODULE)
        sys.modules[ca.MARGINAL_RETURN_MODULE] = _Stub()
        self.addCleanup(
            lambda: sys.modules.__setitem__(ca.MARGINAL_RETURN_MODULE, saved)
            if saved is not None
            else sys.modules.pop(ca.MARGINAL_RETURN_MODULE, None))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("прибор упал", detail)

    def test_an_unimportable_instrument_is_UNMEASURED(self):
        saved = sys.modules.get(ca.MARGINAL_RETURN_MODULE)
        sys.modules[ca.MARGINAL_RETURN_MODULE] = None      # importlib ⇒ ImportError
        self.addCleanup(
            lambda: sys.modules.__setitem__(ca.MARGINAL_RETURN_MODULE, saved)
            if saved is not None
            else sys.modules.pop(ca.MARGINAL_RETURN_MODULE, None))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не загружен", detail)


class TestEveryDeclaredDoorIsInjected(_Scene):
    """Не «есть ли параметр», а доходит ли он ДО ИСХОДА пробы."""

    def test_data_dir_reaches_the_instrument(self):
        empty = self.root / "empty"
        empty.mkdir()
        verdict, detail = self.probe(data_dir=str(empty))
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("книга не прочитана", detail)

    def test_the_clock_reaches_the_instrument(self):
        """Часы доходят до прибора — проверено по ИСХОДУ вызова, не по подписи.

        У прибора нет ни одного суждения о свежести, поэтому вердикт от часов не
        зависит НИ НА ОДНОЙ сцене — и «часы дошли» здесь нельзя доказать сменой
        вердикта. Доказывается тем единственным способом, каким это вообще
        измеримо: отметка `generated_at` отчёта равна поданным часам.
        """
        captured = {}
        real_run = M.run

        def _capture(*a, **kw):
            captured.update(kw)
            return real_run(*a, **kw)

        M.run = _capture
        self.addCleanup(lambda: setattr(M, "run", real_run))
        self.probe(now=self.now)
        self.assertEqual(captured.get("now"), self.now)

    def test_repo_root_is_NOT_declared_and_that_is_the_honest_answer(self):
        """Вход, который не может изменить исход, входом объявлять НЕЛЬЗЯ.

        Код целевой функции приходит импортом по `sys.path`, а не из дерева;
        `root` прибор тратит только на запись артефакта, а она здесь выключена.
        Объявив `repo_root`, проба заставила бы сводный замер напечатать «дерево
        замера дошло» про дерево, которого она не видела.
        """
        self.assertEqual(("data_dir",), ca.probe_tree_inputs(PROBE_NAME))


class TestTheProbeOnlyReads(_Scene):
    def test_the_probe_calls_the_instrument_with_write_false(self):
        captured = {}
        real_run = M.run

        def _capture(*a, **kw):
            captured.update(kw)
            return real_run(*a, **kw)

        M.run = _capture
        self.addCleanup(lambda: setattr(M, "run", real_run))
        self.probe()
        self.assertIs(captured.get("write"), False,
                      "проба зовёт прибор на запись — она уже не только читает")

    def test_nothing_is_written_into_the_disposable_tree(self):
        self.probe()
        self.assertFalse((self.root / M.REPORT_REL).exists())


class TestTheRegistryWiringIsReal(_Scene):
    def test_run_probe_by_name_reaches_the_same_verdict(self):
        (self.data_dir / "current_positions.json").unlink()
        verdict, detail = ca.run_probe(PROBE_NAME, data_dir=str(self.data_dir))
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("книга не прочитана", detail)


class TestTheProbeIsRegisteredAndDeclared(unittest.TestCase):
    def test_it_is_in_the_registry_under_this_exact_name(self):
        self.assertIn(PROBE_NAME, ca.PROBES)

    def test_it_declares_THIS_criterion(self):
        self.assertEqual(
            CRITERION,
            ca._probe_marginal_return_size_changes_expected_yield.s49_criterion)
        self.assertEqual([PROBE_NAME],
                         ca.probes_by_s49_criterion().get(CRITERION))

    def test_the_declaration_points_INTO_the_population_of_the_live_order(self):
        """Объявление, указывающее мимо §49, есть находка, а не тихий ноль."""
        rollup = _load_rollup()
        card = Path(ca.REPO_ROOT) / rollup.CARD_REL
        if not card.exists():                       # pragma: no cover
            self.skipTest(f"карточка приказа не найдена: {card}")
        names = rollup.parse_s49_criteria(card.read_text(encoding="utf-8"))
        self.assertIn(CRITERION, names)


def _load_rollup():
    import importlib.util
    path = Path(ca.REPO_ROOT) / "scripts" / "cio_acceptance_rollup.py"
    spec = importlib.util.spec_from_file_location("_cio_rollup_for_marginal", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
