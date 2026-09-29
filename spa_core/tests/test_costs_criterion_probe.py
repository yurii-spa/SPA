"""ADR-513 — критерий §49 `Costs` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Прибор стоимости перекладки (`spa_core/monitoring/rebalance_cost_evidence.py`,
цикл #501, ADR-243) меряет критерий владельца «Gas, fees, slippage accounted for
in decision» с сентября, и его артефакт свеж (замер 29.09 — 2,1 ч при
объявленном пределе 7 ч). А сводный замер §49 (`scripts/cio_acceptance_rollup.py`)
про этот критерий отвечал

    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ —
     вердикт сегодня взять неоткуда»

потому что запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ, и притом
НЕ канонической формулировкой: конституция писала `§49 ТЗ «Portfolio CIO»
(Costs: …)`, то есть форму `paren`, и читателю оставалось угадывать. Это ПЕРВАЯ
привязка цены `WORDING` — по образцу пяти привязок цены `TRANSCRIPTION`
(ADR-507/508/510/511/512), тоже по одному и со своим контролем в обе стороны.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `costs_are_accounted_for_in_the_decision` зелена на целом контуре и
  красна на КАЖДОМ порванном звене — с названным звеном;
* переносится поле `criterion.status` прибора, а НЕ его `overall`. `overall` —
  лестница ТЯЖЕСТИ, и третий исход стои́т в ней выше `CRITICAL` намеренно
  (`test_unchecked_outranks_critical`): для здоровья артефакта это верно, а для
  вердикта критерия прятало бы ИЗМЕРЕННОЕ красное за «не измерено» — инвариант
  #17 наизнанку. Это предмет отдельного класса контроля
  (`TestTheProbeDoesNotInheritTheSeverityLadder`);
* своего порога у пробы НЕТ ни одного: срок годности наблюдения газа и срок
  годности записанного вердикта читаются прибором из манифеста, горизонт
  окупаемости — из `TriggerParams` владельца;
* прибор, не объявивший себя мерой `§49 Costs`, ⇒ `unmeasured`; якорь читается
  как НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный вердикт прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `data_dir`, `repo_root` и `now` ДОХОДЯТ и до пробы, и до прибора — ВСЕ двери, а
  не одна («половина инъекции», `.claude/rules/deployment.md`), и проверяется это
  по ИСХОДУ пробы, а не по наличию аргумента;
* проба НЕ ПИШЕТ артефакт прибора: она читает.

Порядок контроля НЕ произволен: сначала доказывается, что сцена даёт ИМЕННО те
породы прибора (`TestSceneReproducesTheMeasuredKinds`), и только потом — что
проба на них отвечает. Без первого шага «красно на порванном звене»
тавтологично.

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся
и в сцену, и в пробу. Литеральных дат в файле нет вовсе. Сеть не трогается,
живое `data/` не читается: материал пишется в одноразовый каталог.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import rebalance_cost_evidence as R
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "costs_are_accounted_for_in_the_decision"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Costs"

#: Ноги ЖИВОГО вердикта 06.09 — пять на ethereum, одна на base. Сцена не
#: выдумана: именно эта раскладка даёт $60.15 заряженного газа, из-за которых
#: прибор и написан.
_LEGS = [
    {"protocol": "aave_v3", "delta_usd": 28_157.89, "direction": "increase"},
    {"protocol": "compound_v3", "delta_usd": -2_105.26, "direction": "decrease"},
    {"protocol": "fluid_usdc", "delta_usd": -20_000.0, "direction": "decrease"},
    {"protocol": "maple", "delta_usd": -20_000.0, "direction": "decrease"},
    {"protocol": "morpho_blue_base", "delta_usd": -5_000.0, "direction": "decrease"},
    {"protocol": "pendle", "delta_usd": 18_947.37, "direction": "increase"},
]
_CHAINS = {"aave_v3": "ethereum", "compound_v3": "ethereum",
           "fluid_usdc": "ethereum", "maple": "ethereum",
           "morpho_blue_base": "base", "pendle": "ethereum"}
_TVL = {"aave_v3": 58_548_694.0, "compound_v3": 34_659_970.0,
        "fluid_usdc": 148_902_380.0, "maple": 2_725_025_302.0,
        "morpho_blue_base": 427_666_197.0, "pendle": 21_372_031.0}

#: Цена газа, при которой НАБЛЮДЁННОЕ сходится с ЗАРЯЖЕННЫМ ($12.00 за ногу на
#: ethereum): 19.2 gwei · 1e-9 · GAS_LIMIT_PER_LEG · $2500 = $12.00. Число не
#: подобрано на глаз — оно выведено из множителя САМОГО производителя.
_GWEI_THAT_MATCHES_THE_CHARGE = 12.0 / (1e-9 * R.GAS_LIMIT_PER_LEG * 2500.0)
#: Цена газа живого замера 06.09 — расхождение ×311, больше зазора гейта.
_GWEI_OF_THE_INCIDENT = 0.06


class _Scene(unittest.TestCase):
    """Одноразовое дерево: конституция в `architecture/`, материал в `data/`."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        (self.root / "architecture").mkdir()
        # Якорь считается ЗДЕСЬ, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        self.build()

    # ── сцена ───────────────────────────────────────────────────────────────

    def _ts(self, hours_ago: float) -> str:
        return (self.now - timedelta(hours=hours_ago)).isoformat()

    def build(self, *, gwei: float | None = None, verdict_age_h: float = 1.0,
              gas_age_h: float = 0.5, gas_slo: float | None = 1.5,
              verdict_slo: float | None = 26.0, payback: float | None = 23.11,
              tvl_for: set[str] | None = None,
              verdict_stamp: str | None = None) -> None:
        gwei = _GWEI_THAT_MATCHES_THE_CHARGE if gwei is None else gwei
        tvl_for = set(_TVL) if tvl_for is None else tvl_for

        produces = []
        if gas_slo is not None:
            produces.append({"artifact": R.GAS_ARTIFACT_REL, "slo_hours": gas_slo})
        agents = [{"label": "com.spa.gas_price_agent", "produces": produces}]
        if verdict_slo is not None:
            agents.append({"label": "com.spa.daily_cycle",
                           "produces": [{"artifact": R.VERDICT_ARTIFACT_REL,
                                         "slo_hours": verdict_slo}]})
        self._write(self.root / "architecture" / "manifest.json",
                    {"artifacts": [], "agents": agents})

        self._write(self.data_dir / "allocation_rationale.json", {
            "generated_at": (verdict_stamp if verdict_stamp is not None
                             else self._ts(verdict_age_h)),
            "capital_usd": 100_000.0,
            "decision_shadow": {
                "decision": "HOLD",
                "legs": [dict(l) for l in _LEGS],
                "turnover_usd": 47_105.26,
                "payback_days": payback,
                "gates": {"has_legs": True, "payback_within_horizon": True,
                          "gain_above_band": True},
            },
        })
        self._write(self.data_dir / "adapter_registry.json",
                    {"adapters": {k: {"chain": v} for k, v in _CHAINS.items()}})
        self._write(self.data_dir / "adapter_orchestrator_status.json",
                    {"adapters": [{"protocol": k, "tvl_usd": v,
                                   "tvl_source": "live"}
                                  for k, v in _TVL.items() if k in tvl_for]})
        self._write(self.data_dir / "gas_price_history.json", {
            "eth_usd": {"source": "live", "usd": 2500.0},
            "gas_limit_per_leg": R.GAS_LIMIT_PER_LEG,
            "history": {
                "ethereum": [{"ts": self._ts(gas_age_h), "source": "live",
                              "gwei": gwei, "sources_ok": 4}],
                "base": [{"ts": self._ts(gas_age_h), "source": "live",
                          "gwei": 0.006, "sources_ok": 2}],
            },
        })

    @staticmethod
    def _write(path: Path, doc) -> None:
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # ── прогон ──────────────────────────────────────────────────────────────

    def measure(self) -> dict:
        return R.run(root=str(self.root), write=False,
                     data_dir=str(self.data_dir), now=self.now)

    def probe(self, *, now=None, data_dir=None, repo_root=None) -> tuple:
        """Проба зовётся ПО ИМЕНИ ИЗ РЕЕСТРА — иначе контроль проверял бы функцию,
        а не то, что реестр отдаёт именно её. Часы идут прямым аргументом:
        `run_probe` их не принимает, и его проводка проверяется отдельно."""
        fn = ca.PROBES[PROBE_NAME]
        return fn(None, now=now or self.now,
                  data_dir=data_dir or str(self.data_dir),
                  repo_root=repo_root or str(self.root))


class TestSceneReproducesTheMeasuredKinds(_Scene):
    """СНАЧАЛА доказывается, что сцена даёт именно те породы прибора.

    Без этого шага «проба красна на порванном звене» тавтологично: красной её
    могло бы сделать что угодно, а не тот дефект, ради которого она написана.
    """

    def test_the_whole_contour_is_green_for_the_instrument(self):
        rep = self.measure()
        self.assertEqual(rep["criterion"]["found"], [], rep["criterion"]["reason"])
        self.assertEqual(rep["unchecked"], [])
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_SATISFIED,
                         rep["criterion"]["reason"])

    def test_the_incident_of_06_09_is_reproduced_as_a_FOUND_divergence(self):
        self.build(gwei=_GWEI_OF_THE_INCIDENT)
        rep = self.measure()
        self.assertIn("cost_error_exceeds_the_deciding_margin",
                      rep["criterion"]["found"])
        self.assertEqual(rep["criterion"]["status"], R.CRITERION_NOT_SATISFIED)

    def test_a_stale_observation_is_reproduced_as_UNOBSERVED(self):
        self.build(gas_age_h=48.0)
        rep = self.measure()
        self.assertIn("observed_gas_is_stale", rep["criterion"]["unobserved"])

    def test_an_unmodelled_slippage_is_reproduced_as_UNCHECKED(self):
        self.build(tvl_for=set(_TVL) - {"pendle"})
        rep = self.measure()
        self.assertTrue(rep["unchecked"])


class TestTheProbeTransfersTheInstrumentsVerdict(_Scene):
    def test_the_whole_contour_is_SATISFIED(self):
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_a_found_divergence_is_NOT_SATISFIED(self):
        self.build(gwei=_GWEI_OF_THE_INCIDENT)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("cost_error_exceeds_the_deciding_margin", detail)

    def test_a_stale_gas_observation_is_UNMEASURED(self):
        self.build(gas_age_h=48.0)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("observed_gas_is_stale", detail)

    def test_an_unreadable_verdict_is_UNMEASURED(self):
        (self.data_dir / "allocation_rationale.json").unlink()
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("записанный вердикт не прочитан", detail)

    def test_a_STALE_recorded_verdict_is_UNMEASURED_not_green(self):
        """«Расхождений нет» про вердикт трёхнедельной давности — тишина дерева."""
        self.build(verdict_age_h=24.0 * 21)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("протух", detail)

    def test_a_threshold_without_a_home_is_UNMEASURED_not_invented(self):
        self.build(verdict_slo=None)
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("дом срока годности", detail)

    def test_the_blind_spots_are_NAMED_in_every_verdict(self):
        """Критерий владельца шире сегодняшней меры, и это сказано вслух."""
        for build in ({}, {"gwei": _GWEI_OF_THE_INCIDENT}, {"gas_age_h": 48.0}):
            with self.subTest(build=build):
                self.build(**build)
                _, detail = self.probe()
                self.assertIn("ОДНА компонента стоимости из трёх", detail)


class TestTheProbeDoesNotInheritTheSeverityLadder(_Scene):
    """Находка существования не тонет в «не измерено» — инвариант #17 наизнанку.

    `overall` у прибора ставит третий исход ВЫШЕ `CRITICAL` намеренно. Проба,
    перенёсшая `overall`, объявила бы измеренное расхождение «не измеренным» —
    и красное владельца исчезло бы из сводки тише, чем от любой правки.
    """

    def test_a_found_divergence_survives_an_unchecked_alongside(self):
        self.build(gwei=_GWEI_OF_THE_INCIDENT,
                   tvl_for=set(_TVL) - {"pendle"})
        rep = self.measure()
        self.assertEqual(rep["overall"], "UNCHECKED",
                         "сцена не воспроизвела маскировку")
        self.assertTrue(rep["unchecked"])
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED,
                         f"находка спрятана за «не измерено»: {detail}")

    def test_the_probe_does_not_read_overall_at_all(self):
        """Прямой контроль проводки: `overall` подменён, вердикт не дрогнул."""
        real_run = R.run

        def _run_with_a_lying_overall(*a, **kw):
            rep = real_run(*a, **kw)
            rep["overall"] = "OK"
            return rep

        R.run = _run_with_a_lying_overall
        self.addCleanup(lambda: setattr(R, "run", real_run))
        self.build(gwei=_GWEI_OF_THE_INCIDENT)
        verdict, _ = self.probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED)


class TestTheDeclarationIsCheckedByAnchorNotBySubstring(_Scene):
    def _with_module(self, stub):
        saved = sys.modules.get(ca.COST_EVIDENCE_MODULE)
        sys.modules[ca.COST_EVIDENCE_MODULE] = stub
        self.addCleanup(
            lambda: sys.modules.__setitem__(ca.COST_EVIDENCE_MODULE, saved)
            if saved is not None else sys.modules.pop(ca.COST_EVIDENCE_MODULE, None))

    def test_an_instrument_that_declares_nothing_is_UNMEASURED(self):
        class _Stub:
            CRITERION = ""
        self._with_module(_Stub())
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_a_MENTION_of_Costs_is_not_a_declaration(self):
        """Подстрока «Costs» совпала бы с любой заметкой о стоимости (ADR-333)."""
        class _Stub:
            CRITERION = "заметка про Costs где-то в середине строки"
        self._with_module(_Stub())
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_anchor_must_START_the_declaration_not_merely_occur_in_it(self):
        """Ровно та мутация, которую «есть ли подстрока» пропускает.

        Заметка, где `§49 Costs` стои́т В СЕРЕДИНЕ, ссылается на критерий, а не
        объявляет себя его мерой. Проверка вхождением приняла бы её за
        объявление — и мерой критерия стал бы прибор, который этого не говорил.
        """
        class _Stub:
            CRITERION = "подробности про §49 Costs смотри в соседнем ADR"
        self._with_module(_Stub())
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_real_instrument_declares_the_anchor(self):
        self.assertTrue(R.CRITERION.startswith("§49 Costs"))


class TestFailClosedOnAnythingUnknown(_Scene):
    def _stub(self, block):
        outer = self

        class _Stub:
            CRITERION = R.CRITERION
            CRITERION_SATISFIED = R.CRITERION_SATISFIED
            CRITERION_NOT_SATISFIED = R.CRITERION_NOT_SATISFIED
            CRITERION_UNMEASURED = R.CRITERION_UNMEASURED

            @staticmethod
            def run(**kw):
                doc = dict(outer.measure())
                if block is None:
                    doc.pop("criterion", None)
                else:
                    doc["criterion"] = block
                return doc

        saved = sys.modules.get(ca.COST_EVIDENCE_MODULE)
        sys.modules[ca.COST_EVIDENCE_MODULE] = _Stub()
        self.addCleanup(
            lambda: sys.modules.__setitem__(ca.COST_EVIDENCE_MODULE, saved)
            if saved is not None else sys.modules.pop(ca.COST_EVIDENCE_MODULE, None))

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
            CRITERION = R.CRITERION

            @staticmethod
            def run(**kw):
                raise RuntimeError("прибор упал")

        saved = sys.modules.get(ca.COST_EVIDENCE_MODULE)
        sys.modules[ca.COST_EVIDENCE_MODULE] = _Stub()
        self.addCleanup(
            lambda: sys.modules.__setitem__(ca.COST_EVIDENCE_MODULE, saved)
            if saved is not None else sys.modules.pop(ca.COST_EVIDENCE_MODULE, None))
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("прибор упал", detail)


class TestEveryDoorIsInjected(_Scene):
    """Не «есть ли параметр», а доходит ли он ДО ИСХОДА пробы.

    «Половина инъекции» — та же бомба, что её отсутствие
    (`.claude/rules/deployment.md`, замер #453).
    """

    def test_the_clock_reaches_the_instrument(self):
        """Тот же материал при сдвинутых часах даёт ДРУГОЙ вердикт.

        Проверяется ИСХОД, а не наличие аргумента: материал не тронут ни на
        байт, менялись только часы. Первым же о сдвиге говорит свежесть
        наблюдения газа (предел 1,5 ч), и этого довольно — вопрос здесь «дошли
        ли часы», а не «какой из двух сроков годности ответит первым».
        """
        self.assertEqual(self.probe()[0], ca.SATISFIED)
        later = self.now + timedelta(days=30)
        verdict, detail = self.probe(now=later)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("observed_gas_is_stale", detail)

    def test_data_dir_reaches_the_instrument(self):
        """Пустой каталог материала — вердикт обязан это ЗАМЕТИТЬ."""
        empty = self.root / "empty"
        empty.mkdir()
        verdict, detail = self.probe(data_dir=str(empty))
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("записанный вердикт не прочитан", detail)

    def test_repo_root_reaches_the_instrument(self):
        """Конституция живёт в `repo_root`: без неё порог теряет дом."""
        (self.root / "architecture" / "manifest.json").unlink()
        verdict, detail = self.probe()
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("манифест не прочитан", detail)


class TestTheProbeOnlyReads(_Scene):
    def test_the_probe_does_not_write_the_instruments_artifact(self):
        """`write=False`: проба не переписывает даже артефакт своего прибора."""
        self.probe()
        self.assertFalse((self.root / R.REPORT_REL).exists(),
                         "проба записала артефакт — она уже не только читает")


class TestTheRegistryWiringIsReal(_Scene):
    def test_run_probe_by_name_reaches_the_same_verdict(self):
        """Реестр обязан отдавать ИМЕННО эту пробу и проводить оба дерева.

        Часы `run_probe` не принимает — и это не пробел: карточку он меряет
        сегодняшними часами. Здесь проверяется ОСТАЛЬНАЯ проводка: имя, дерево
        кода и каталог материала. Вердикт берётся на сцене, чей ответ от
        сегодняшних часов не зависит (порванное звено, а не срок годности).
        """
        (self.data_dir / "allocation_rationale.json").unlink()
        verdict, detail = ca.run_probe(PROBE_NAME, repo_root=str(self.root),
                                       data_dir=str(self.data_dir))
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("записанный вердикт не прочитан", detail)

    def test_both_tree_inputs_are_DECLARED_by_the_probe(self):
        """Вход, не объявленный пробой, `run_probe` ей не передаёт вовсе."""
        self.assertEqual({"repo_root", "data_dir"},
                         set(ca.probe_tree_inputs(PROBE_NAME)))


class TestTheProbeIsRegisteredAndDeclared(unittest.TestCase):
    def test_it_is_in_the_registry_under_this_exact_name(self):
        self.assertIn(PROBE_NAME, ca.PROBES)

    def test_it_declares_THIS_criterion(self):
        self.assertEqual(
            CRITERION,
            ca._probe_costs_are_accounted_for_in_the_decision.s49_criterion)
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
    spec = importlib.util.spec_from_file_location("_cio_rollup_for_costs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
