"""ADR-706 — ось APY получает контракт провенанса, который у оси TVL был с ADR-053.

Почему этот файл существует
---------------------------
Правило `.claude/rules/risk-engine.md` запрещает штамповать «live» на постоянной
дословно — и до этого решения запрет был выполним ТОЛЬКО на оси TVL: у `YieldInfo`
было поле `tvl_source`, а поля для провенанса СТАВКИ не было вовсе. Поэтому «живость»
ставки назначалась догадкой на трёх дверях подряд:

1. `adapter_orchestrator._run_one_adapter` — `live_data=True` по одному факту
   «вернулось число»;
2. `allocator._load_adapters` на пути снимка — `"apy_source": "live"` БЕЗУСЛОВНО
   («live by construction» в комментарии);
3. приёмка владельца `scripts/capital_observability_census.py` (ADR-364) считает
   наблюдением объявленный провенанс — то есть читает по оси APY ровно тот штамп,
   который поставлен догадкой. Её «100 %» по этой оси не могло упасть НИКОГДА.

Замер 12.10, который и есть предмет: все пять протоколов, держащих капитал ($95 000),
приходят в аллокатор путём СНИМКА — тем самым, где провенанс не спрашивают; а из
одиннадцати опрашиваемых адаптеров один — `fluid_fusdc`, $20 000 книги — по построению
подставляет вместо наблюдения классовую постоянную `SPIKE_NORM_PCT = 9.0`, и постоянная
эта лежит внутри полосы допуска RiskPolicy (1…30 %), поэтому гейт её пропускает.

Что закреплено, и в ОБЕ стороны
-------------------------------
* перепись `scripts/apy_provenance_census.py` краснеет на адаптере, который МОЖЕТ
  подставить постоянную и провенанс не объявляет, — и зеленеет, как только объявление
  появилось (не «как только постоянную убрали»: поведение защиты от spike остаётся);
* **две измеренные ЛОЖНЫЕ находки первой редакции прибора — положительные контроли:**
  делитель `/ 100.0` (перевод процентов в доли) и точность `round(x, 8)` подстановкой
  не являются, и обвинять их прибор больше не вправе;
* нечитаемый исходник ⇒ `unmeasured` с названной причиной, НИКОГДА не «чисто»
  (инв. #17), и у предела шагов разрешения свой третий исход;
* найденная постоянная ПЕРЕВЕШИВАЕТ неразобранную соседнюю ветвь — «не смог разобрать
  Б» не делает ветвь А менее постоянной (ровно этот обратный порядок прятал
  `fluid_fusdc` в «НЕ ИЗМЕРЕНО» в первой редакции);
* `fluid_fusdc` отдаёт ТО ЖЕ ЧИСЛО, что и до правки, во всех трёх случаях —
  поведение не менялось, менялось представление;
* запись оркестратора несёт `apy_source` ВСЕГДА, включая отказные пути, и
  незаявленный провенанс остаётся `None` («не объявлен» ≠ «объявлен постоянной»);
* незнакомое слово в объявлении (`"hint"`) читается как НЕ объявлено (fail-CLOSED);
* `feed_coverage` несёт объявление отдельным ключом, и `apy_sources` при этом НЕ
  меняется: это два разных вопроса (путь добычи против происхождения), и слияние их
  было бы той же подменой, только в другую сторону.

Сеть не трогается: адаптеры подменяются фикстурами, живой фид не зовётся. Литеральных
дат нет; где нужен момент — он вход (`now_fn`).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.fluid_fusdc_adapter import FluidFUSDCAdapter
from spa_core.orchestrator.adapter_orchestrator import run_orchestrator
from spa_core.tests._freshness import ts

_CENSUS_PATH = Path(__file__).resolve().parents[2] / "scripts" / "apy_provenance_census.py"


def _load_census():
    """Загрузить прибор по пути (скрипты не пакет)."""
    spec = importlib.util.spec_from_file_location("apy_provenance_census", _CENSUS_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Регистрируем ДО exec_module: иначе относительные ссылки модуля на себя рвутся.
    sys.modules["apy_provenance_census"] = mod
    spec.loader.exec_module(mod)
    return mod


CENSUS = _load_census()


# ── сцена: одноразовый модуль-адаптер ────────────────────────────────────────

_HEAD = '''
from typing import Optional


class YieldInfo:
    def __init__(self, **kw):
        self.kw = kw


class Scene:
    SPIKE_NORM_PCT: float = 9.0
    SPIKE_THRESHOLD_PCT: float = 15.0

    def _fetch(self) -> Optional[dict]:
        return {"apy": 4.2}
'''

#: Подставляет классовую постоянную и провенанс НЕ объявляет — авария ADR-706.
SCENE_SUBSTITUTES = _HEAD + '''
    def get_apy(self):
        raw = self._fetch()["apy"]
        if raw > self.SPIKE_THRESHOLD_PCT:
            return self.SPIKE_NORM_PCT
        return raw

    def get_yield_info(self):
        return YieldInfo(apy=self.get_apy())
'''

#: То же самое, но провенанс ОБЪЯВЛЕН. Постоянная на месте — лечится объявление.
SCENE_DECLARES = _HEAD + '''
    def apy_with_provenance(self):
        raw = self._fetch()["apy"]
        if raw > self.SPIKE_THRESHOLD_PCT:
            return self.SPIKE_NORM_PCT, "static"
        return raw, "live"

    def get_yield_info(self):
        value, source = self.apy_with_provenance()
        return YieldInfo(apy=value, apy_source=source)
'''

#: Постоянной до поля доехать не может — честное «только живое».
SCENE_LIVE_ONLY = _HEAD + '''
    def get_yield_info(self):
        data = self._fetch()
        return YieldInfo(apy=data.get("apy"))
'''

#: ЛОЖНЫЕ НАХОДКИ первой редакции прибора, дословно: делитель перевода единиц и
#: точность округления. Ни то, ни другое не есть источник значения.
SCENE_UNIT_SCALE = _HEAD + '''
    def get_yield_info(self):
        data = self._fetch()
        apy_pct = float(data.get("apy")) if data is not None else None
        return YieldInfo(apy=round(apy_pct / 100.0, 8) if apy_pct is not None else None)
'''


def _measure_scene(source: str, class_name: str = "Scene", **kw) -> dict:
    with TemporaryDirectory() as td:
        path = Path(td) / "scene_adapter.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return CENSUS.measure_adapter(path, class_name, **kw)


class TestCensusBothDirections(unittest.TestCase):
    def test_substituted_class_constant_without_declaration_is_a_finding(self):
        row = _measure_scene(SCENE_SUBSTITUTES)
        self.assertEqual(row["verdict"], "can_substitute", row)
        self.assertTrue(any("SPIKE_NORM_PCT" in n for n in row["notes"]),
                        "постоянная обязана быть НАЗВАНА: {}".format(row["notes"]))

    def test_the_same_constant_with_a_declaration_is_not_a_finding(self):
        row = _measure_scene(SCENE_DECLARES)
        self.assertEqual(row["verdict"], "declared", row)

    def test_value_that_only_comes_from_a_call_is_live_only(self):
        row = _measure_scene(SCENE_LIVE_ONLY)
        self.assertEqual(row["verdict"], "live_only", row)

    def test_unit_divisor_and_round_precision_are_not_substitutions(self):
        # Обе формы прибор обвинял в первой редакции (3 ложных из 3 и 1 из 1).
        row = _measure_scene(SCENE_UNIT_SCALE)
        self.assertEqual(row["verdict"], "live_only", row)

    def test_unreadable_source_is_the_third_outcome_with_a_named_reason(self):
        row = _measure_scene("def broken(:\n")
        self.assertEqual(row["verdict"], "unmeasured", row)
        self.assertTrue(row["notes"] and "не разобран" in row["notes"][0], row["notes"])

    def test_missing_class_is_the_third_outcome_not_clean(self):
        row = _measure_scene(SCENE_LIVE_ONLY, class_name="NoSuchClass")
        self.assertEqual(row["verdict"], "unmeasured", row)

    def test_step_limit_is_an_input_and_its_exhaustion_is_the_third_outcome(self):
        # Предел 0 шагов: до постоянной дойти нельзя, и это НЕ «постоянной нет».
        row = _measure_scene(SCENE_SUBSTITUTES, max_steps=0)
        self.assertEqual(row["verdict"], "unmeasured", row)
        self.assertTrue(any("предел шагов" in n for n in row["notes"]), row["notes"])

    def test_a_proven_constant_outranks_an_unresolved_neighbour(self):
        # Ветвь А — постоянная; ветвь Б — вызов помощника ЧУЖОГО модуля на пределе.
        scene = _HEAD + '''
    def get_apy(self):
        raw = _outside_helper()
        if raw > self.SPIKE_THRESHOLD_PCT:
            return self.SPIKE_NORM_PCT
        return raw

    def get_yield_info(self):
        return YieldInfo(apy=self.get_apy())
'''
        row = _measure_scene(scene, max_steps=2)
        self.assertEqual(row["verdict"], "can_substitute", row)


class TestLiveDoorAndSurface(unittest.TestCase):
    """Замер на ЖИВОМ дереве: дверь зелена, справочная поверхность под потолком."""

    def test_door_has_no_substitution_without_declaration(self):
        rep = CENSUS.measure()
        self.assertIsNone(rep["door_refused"], rep["door_refused"])
        self.assertEqual(rep["door"]["can_substitute"], 0, [
            r for r in rep["door_rows"] if r["verdict"] == "can_substitute"])
        self.assertEqual(rep["door"]["unmeasured"], 0, [
            r for r in rep["door_rows"] if r["verdict"] == "unmeasured"])
        self.assertGreaterEqual(rep["door"]["declared"], 1,
                                "fluid_fusdc обязан объявлять провенанс")

    def test_observed_surface_stays_under_the_ceiling(self):
        rep = CENSUS.measure()
        self.assertLessEqual(
            rep["observed"]["can_substitute"], CENSUS.OBSERVED_SURFACE_CEILING,
            "потолок может только убывать (инв. #16): {}".format(
                [r["class"] for r in rep["observed_rows"]
                 if r["verdict"] == "can_substitute"]))


class TestFluidDeclaresWithoutChangingBehaviour(unittest.TestCase):
    """Число то же, ярлык честный — три исхода различимы."""

    def _adapter(self, raw):
        a = FluidFUSDCAdapter()
        return a, patch.object(FluidFUSDCAdapter, "get_raw_apy", lambda _self: raw)

    def test_observed_rate_is_live(self):
        a, p = self._adapter(11.38)
        with p:
            self.assertEqual(a.apy_with_provenance(), (11.38, "live"))
            self.assertEqual(a.get_apy(), 11.38)
            self.assertEqual(a.get_yield_info().apy_source, "live")

    def test_spike_substitution_is_static_and_the_number_is_unchanged(self):
        a, p = self._adapter(22.0)
        with p:
            value, source = a.apy_with_provenance()
            self.assertEqual(value, FluidFUSDCAdapter.SPIKE_NORM_PCT)
            self.assertEqual(source, "static")
            # ПОВЕДЕНИЕ не изменилось: наружу уходит та же нормализованная 9.0.
            self.assertEqual(a.get_apy(), FluidFUSDCAdapter.SPIKE_NORM_PCT)
            info = a.get_yield_info()
            self.assertEqual(info.apy_source, "static")
            self.assertAlmostEqual(info.apy or 0.0, 0.09, places=6)

    def test_no_observation_is_neither_live_nor_static(self):
        a, p = self._adapter(None)
        with p:
            self.assertEqual(a.apy_with_provenance(), (None, None))
            info = a.get_yield_info()
            self.assertIsNone(info.apy)
            self.assertIsNone(info.apy_source)


# ── оркестратор: поле есть ВСЕГДА ────────────────────────────────────────────


def _fake_adapter(protocol, apy, apy_source="__absent__", raises=None):
    class _Fake:
        PROTOCOL = protocol

        def get_yield_info(self):
            if raises is not None:
                raise raises
            kw = {}
            if apy_source != "__absent__":
                kw["apy_source"] = apy_source
            return YieldInfo(protocol=protocol, asset="USDC", apy=apy,
                             tvl_usd=9_000_000.0, tier="T2", risk_score=0.3, **kw)

    _Fake.__name__ = "Fake_" + protocol
    return _Fake


class TestOrchestratorCarriesTheDeclaration(unittest.TestCase):
    def _run(self, reg):
        res = run_orchestrator(registry=reg, write=False)
        return {a["protocol"]: a for a in res.adapters}

    def test_declared_live_static_and_undeclared_are_three_outcomes(self):
        rows = self._run([
            ("live_one", "T2", _fake_adapter("live_one", 0.05, "live")),
            ("static_one", "T2", _fake_adapter("static_one", 0.09, "static")),
            ("silent_one", "T2", _fake_adapter("silent_one", 0.04)),
        ])
        self.assertEqual(rows["live_one"]["apy_source"], "live")
        self.assertEqual(rows["static_one"]["apy_source"], "static")
        self.assertIsNone(rows["silent_one"]["apy_source"])
        # Поведение не изменилось: все три по-прежнему «живые данные».
        for key in ("live_one", "static_one", "silent_one"):
            self.assertTrue(rows[key]["live_data"], key)
            self.assertEqual(rows[key]["status"], "ok", key)

    def test_unknown_word_in_the_declaration_reads_as_undeclared(self):
        rows = self._run([("hinty", "T2", _fake_adapter("hinty", 0.05, "hint"))])
        self.assertIsNone(rows["hinty"]["apy_source"],
                          "незнакомое слово — не объявление (fail-CLOSED)")

    def test_the_field_is_present_on_refusal_paths_too(self):
        rows = self._run([
            ("boom", "T2", _fake_adapter("boom", None, raises=RuntimeError("net down"))),
            ("empty", "T2", _fake_adapter("empty", None, "live")),
        ])
        for key in ("boom", "empty"):
            self.assertIn("apy_source", rows[key], key)
        self.assertIsNone(rows["boom"]["apy_source"])


# ── аллокатор: объявление рядом с путём, а не вместо него ────────────────────


class TestAllocatorRecordsTheDeclaration(unittest.TestCase):
    def _coverage(self, snapshot_rows, live_apy_provider=None):
        from spa_core.allocator.allocator import StrategyAllocator
        with TemporaryDirectory() as td:
            data = Path(td)
            (data / "adapter_orchestrator_status.json").write_text(
                json.dumps({"adapters": snapshot_rows}), encoding="utf-8")
            (data / "adapter_status.json").write_text(
                json.dumps({"adapters": {}}), encoding="utf-8")
            (data / "adapter_registry.json").write_text(
                json.dumps({"adapters": {}}), encoding="utf-8")
            kw = {} if live_apy_provider is None else {
                "live_apy_provider": live_apy_provider}
            alloc = StrategyAllocator(
                status_path=data / "adapter_orchestrator_status.json",
                registry_path=data / "adapter_registry.json",
                adapter_status_path=data / "adapter_status.json",
                **kw,
            )
            alloc._load_adapters()
            return alloc._build_feed_coverage()

    @staticmethod
    def _row(protocol, apy_pct, apy_source="__absent__"):
        row = {"protocol": protocol, "status": "ok", "apy_pct": apy_pct,
               "tvl_usd": 90_000_000.0, "tvl_source": "live", "tier": "T2",
               # Отметка ОТНОСИТЕЛЬНАЯ (`_freshness.ts`), а не литеральная дата:
               # литерал здесь — бомба замедленного действия из
               # `.claude/rules/deployment.md`, и предметом она не является.
               "last_updated": ts(hours_ago=0.5)}
        if apy_source != "__absent__":
            row["apy_source"] = apy_source
        return row

    def test_declaration_is_recorded_without_touching_apy_sources(self):
        cov = self._coverage([
            self._row("declared_live", 4.2, "live"),
            self._row("declared_static", 9.0, "static"),
            self._row("silent", 3.1),
        ])
        self.assertEqual(cov["apy_declared"]["declared_live"], "live")
        self.assertEqual(cov["apy_declared"]["declared_static"], "static")
        self.assertIsNone(cov["apy_declared"]["silent"])
        self.assertEqual(cov["apy_declared_live"], 1)
        self.assertEqual(cov["apy_declared_static"], 1)
        self.assertEqual(cov["apy_undeclared"], 1)
        # ДРУГОЙ вопрос — и ответ на него не изменился: путь добычи у всех трёх
        # по-прежнему «снимок», и рационале с взводом ADR-060 читают именно его.
        self.assertEqual(
            {v for v in cov["apy_sources"].values()}, {"live"})

    def test_an_evidenced_observation_outranks_the_adapters_own_label(self):
        """Ранжируют НЕ на числе адаптера ⇒ и ярлык берётся у того, на чём ранжируют.

        ADR-061: наблюдение из `adapter_status.live_apy` перебивает число снимка. Если бы
        объявление осталось от адаптера, измеренное наблюдение уехало бы «статикой» —
        промах в сторону занижения, но всё равно ложь о происхождении числа.
        """
        # Наблюдения подаются ИНЪЕКЦИЕЙ: по контракту аллокатора явный
        # `live_apy_provider` И ЕСТЬ карта наблюдений, а под pytest чтение файлов
        # не делается вовсе (тест не вправе ранжировать на живом `data/`).
        cov = self._coverage(
            [self._row("declared_static", 9.0, "static"),
             self._row("b", 4.0), self._row("c", 5.0)],
            live_apy_provider=lambda: {"declared_static": 0.09, "b": 0.04, "c": 0.05},
        )
        self.assertEqual(cov["apy_declared"]["declared_static"], "live", cov["apy_declared"])

    def test_the_orchestrators_own_live_data_flag_is_not_an_independent_witness(self):
        """`orchestrator_live` — тот же флаг «вернулось число», и за наблюдение не идёт.

        Иначе догадка вернулась бы через вторую дверь: каждая строка живого снимка
        несёт `live_data: True`, и `apy_declared` стал бы «live» у всех безусловно —
        ровно то, что ADR-706 убирает.
        """
        from spa_core.allocator import allocator as A
        rows = [dict(self._row("declared_static", 9.0, "static"), live_data=True),
                dict(self._row("b", 4.0), live_data=True),
                dict(self._row("c", 5.0), live_data=True)]
        # Ветвь чтения наблюдений из файлов закрыта под pytest намеренно (тест не
        # вправе ранжировать на живом `data/`), поэтому заслон снимается — и ВМЕСТЕ
        # с ним затыкается дверь в сеть: иначе производственный код полез бы за
        # живым фидом (`.claude/rules/adapters.md` — фид в тестах подменяют).
        with patch.object(A, "_load_evidenced_apy", lambda *a, **k: {
                "declared_static": (0.09, "orchestrator_live"),
                "b": (0.04, "orchestrator_live"), "c": (0.05, "orchestrator_live")}), \
                patch.object(A.StrategyAllocator, "_get_live_apy_map",
                             lambda _self: {}), \
                patch.dict("os.environ", {}, clear=False) as _env:
            _env.pop("PYTEST_CURRENT_TEST", None)
            cov = self._coverage(rows)
        self.assertEqual(cov["apy_declared"]["declared_static"], "static", cov["apy_declared"])
        self.assertIsNone(cov["apy_declared"]["b"], cov["apy_declared"])

    def test_a_snapshot_where_nobody_declares_is_not_reported_as_observed(self):
        cov = self._coverage([self._row("silent_a", 4.0), self._row("silent_b", 5.0)])
        self.assertEqual(cov["apy_declared_live"], 0,
                         "ни одного объявления ⇒ наблюдением по оси APY не считается")
        self.assertEqual(cov["apy_undeclared"], 2)


if __name__ == "__main__":
    unittest.main()


# ── проба приёмки: зелена на целом контуре, красна на КАЖДОМ порванном звене ──


class _FakeCensus:
    """Подставная перепись: доказывает, что проба читает ПРИБОР, а не свою копию."""

    class _Boom(Exception):
        pass

    def __init__(self, report=None, raises=None):
        self._report = report
        self._raises = raises

    def measure(self, *a, **kw):
        if self._raises is not None:
            raise self._raises
        return self._report


def _report(population=11, declared=1, live_only=10, can_substitute=0, unmeasured=0,
            rows=None, refused=None):
    return {
        "max_steps": 3,
        "door_refused": refused,
        "door": {"population": population, "declared": declared, "live_only": live_only,
                 "can_substitute": can_substitute, "unmeasured": unmeasured,
                 "literal_defaults": 2},
        "door_rows": rows or [],
        "observed": {"population": 40, "declared": 1, "live_only": 36,
                     "can_substitute": 2, "unmeasured": 1, "literal_defaults": 7},
        "observed_rows": [],
    }


class TestAcceptanceProbeEveryLink(unittest.TestCase):
    """ADR-333: имя пробы сверяется РАВЕНСТВОМ, и каждое звено имеет свой контроль."""

    PROBE_NAME = "apy_provenance_declared_in_the_door"

    def setUp(self):
        from spa_core.monitoring import card_acceptance as ca
        self.ca = ca
        self.probe = ca.PROBES[self.PROBE_NAME]   # равенство имени, не подстрока

    def _with_census(self, fake):
        return patch.dict(sys.modules, {self.ca.APY_PROVENANCE_MODULE_NAME: fake})

    def test_the_probe_is_registered_under_exactly_this_name(self):
        self.assertIn(self.PROBE_NAME, self.ca.PROBES)
        # Подстрочное совпадение именем НЕ является (ADR-333).
        self.assertNotIn(self.PROBE_NAME + "_extra", self.ca.PROBES)

    def test_whole_circuit_on_the_live_tree_is_satisfied(self):
        verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.SATISFIED, detail)
        self.assertIn("11", detail)

    def test_link_census_unloadable_is_unmeasured(self):
        with patch.object(self.ca, "_apy_provenance_module",
                          side_effect=ImportError("нет файла переписи")):
            verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("перепись не загружена", detail)

    def test_link_census_raises_is_unmeasured(self):
        with self._with_census(_FakeCensus(raises=RuntimeError("разбор рухнул"))):
            verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("перепись упала", detail)

    def test_link_door_refused_is_unmeasured(self):
        with self._with_census(_FakeCensus(_report(refused="POLLED_ADAPTERS не прочитан"))):
            verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("дверь не прочитана", detail)

    def test_link_empty_door_is_unmeasured_not_satisfied(self):
        with self._with_census(_FakeCensus(_report(population=0, declared=0, live_only=0))):
            verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.UNMEASURED, detail)
        self.assertIn("НИ ОДНОГО", detail)

    def test_link_unresolved_expression_is_unmeasured_with_names(self):
        rows = [{"class": "FluidFUSDCAdapter", "verdict": "unmeasured",
                 "notes": ["предел шагов 3 достигнут"], "literal_defaults": []}]
        with self._with_census(_FakeCensus(_report(unmeasured=1, live_only=9, rows=rows))):
            verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.UNMEASURED)
        self.assertIn("FluidFUSDCAdapter", detail)
        self.assertIn("НЕ РАЗОБРАНО", detail)

    def test_link_silent_substitution_is_not_satisfied_with_names(self):
        rows = [{"class": "FluidFUSDCAdapter", "verdict": "can_substitute",
                 "notes": ["self.SPIKE_NORM_PCT"], "literal_defaults": []}]
        with self._with_census(_FakeCensus(
                _report(declared=0, live_only=10, can_substitute=1, rows=rows))):
            verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("SPIKE_NORM_PCT", detail)

    def test_unmeasured_outranks_a_substitution_in_the_same_report(self):
        # Порядок исходов: «не измерено» съедает «не выполнено» — нельзя судить
        # о двери, часть которой не разобрана.
        rows = [
            {"class": "A", "verdict": "unmeasured", "notes": ["форма не разобрана"],
             "literal_defaults": []},
            {"class": "B", "verdict": "can_substitute", "notes": ["self.X"],
             "literal_defaults": []},
        ]
        with self._with_census(_FakeCensus(
                _report(unmeasured=1, can_substitute=1, live_only=9, rows=rows))):
            verdict, _ = self.probe(None)
        self.assertEqual(verdict, self.ca.UNMEASURED)
