"""ADR-707 · писатели второго артефакта и литерал в опубликованном числе.

Предмет — пункт 1 карточки `inbox-tsikl-schitaet-pokrytie-fidov-100-zhivym`
(29.08): «кто и когда пишет запись `aave_arbitrum` в `adapter_status.json` —
константа в коде производителя или ручная правка». Ответ: КОНСТАНТА, и в
производителе.

Каждый тест здесь — положительный контроль на НАСТОЯЩУЮ поломку:

  * `TestShadowApy` / `TestGeneratorShadowBlock` — сам дефект: теневой блок брал
    число как ``entry.get("apy", 4.1)``, и литерал уезжал ровно в той ветке, где
    `adapter_registry.json` не прочитан, то есть когда система знает меньше всего;
  * `TestReadersOnHonestAbsence` — цена честного `None` у трёх читателей: два
    адаптера обязаны вернуть `None` (как и обещает докстринг `get_apy()` со
    ссылкой на решение владельца 2026-08-08), а `apy_aggregator` — не упасть
    `float(None)`, иначе честность стоила бы дороже выдумки;
  * `TestExecutionWriterIsAtomic` — инв. #5: `write_status_json` писал сырым
    `open(..., "w")`;
  * `TestCensusRegressions` — ТРИ ошибки самого прибора, найденные при его
    постройке. Без этих контролей прибор молчал бы о главном писателе и обвинял
    невиновных, оставаясь зелёным;
  * `TestProbe` — проба зелена на целом контуре и красна на КАЖДОМ порванном
    звене, причём «не измерено» съедает «не выполнено».

Литеральных дат в файле нет: предмет — дерево кода, а не свежесть артефакта,
поэтому часам здесь нечего инъектировать.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CENSUS_PATH = REPO_ROOT / "scripts" / "adapter_status_writer_census.py"


def _load_census(name: str = "_g851_census"):
    spec = importlib.util.spec_from_file_location(name, str(CENSUS_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stand_with_module(source: str, *, pkg: str = "spa_core",
                       fname: str = "w.py") -> str:
    """Одноразовое дерево с одним модулем — операнд для контролей прибора."""
    root = tempfile.mkdtemp(prefix="g851_stand_")
    d = os.path.join(root, pkg)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(source))
    return root


# ────────────────────────── 1. правило подстановки ──────────────────────────


class TestShadowApy(unittest.TestCase):
    """`_shadow_apy` — одна копия правила, ТРИ различимых исхода (инв. #17)."""

    def setUp(self) -> None:
        from spa_core.monitoring import adapter_status_generator as gen
        self.gen = gen

    def test_absent_record_yields_none_not_a_literal(self):
        """Записи нет ⇒ (None, None). ДО ADR-707 здесь уезжал литерал 4.1."""
        self.assertEqual(self.gen._shadow_apy({}), (None, None))
        self.assertEqual(self.gen._shadow_apy(None), (None, None))  # type: ignore[arg-type]

    def test_record_with_live_observation_is_live(self):
        got = self.gen._shadow_apy({"apy": 3.14, "live_apy": 3.14})
        self.assertEqual(got, (3.14, "live"))

    def test_record_without_live_observation_is_static(self):
        """Число есть, наблюдения нет — род `static`, а не `live`.

        ADR-053 дословно: «never stamp live on a constant».
        """
        got = self.gen._shadow_apy({"apy": 8.0, "live_apy": None})
        self.assertEqual(got, (8.0, "static"))

    def test_non_numeric_apy_is_absence_not_zero(self):
        for bad in ({"apy": None}, {"apy": "4.1"}, {"apy": True}):
            with self.subTest(bad=bad):
                self.assertEqual(self.gen._shadow_apy(bad), (None, None))

    def test_the_removed_literals_are_gone_from_the_producer(self):
        """Обратный контроль: три литерала из теневого блока ИСЧЕЗЛИ.

        Красен, если кто-нибудь вернёт `.get("apy", <число>)` в теневой блок.
        """
        src = (REPO_ROOT / "spa_core" / "monitoring"
               / "adapter_status_generator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get" or len(node.args) != 2:
                continue
            k, d = node.args
            if (isinstance(k, ast.Constant) and k.value == "apy"
                    and isinstance(d, ast.Constant)
                    and isinstance(d.value, (int, float))
                    and not isinstance(d.value, bool)):
                offenders.append((node.lineno, d.value))
        self.assertEqual(
            offenders, [],
            f"литерал вернулся в .get('apy', ...) производителя: {offenders}")


class TestGeneratorShadowBlock(unittest.TestCase):
    """Теневой блок документа: число и род, включая ветку «реестр не прочитан»."""

    def setUp(self) -> None:
        from spa_core.monitoring import adapter_status_generator as gen
        self.gen = gen
        self.stand = Path(tempfile.mkdtemp(prefix="g851_gen_"))
        self.registry = self.stand / "adapter_registry.json"
        self.out = self.stand / "adapter_status.json"
        self._real_feed = gen._fetch_defillama
        gen._fetch_defillama = lambda timeout=0: None   # сеть ОТКЛЮЧЕНА

    def tearDown(self) -> None:
        self.gen._fetch_defillama = self._real_feed

    def _doc(self, registry: dict | None):
        if registry is not None:
            self.registry.write_text(json.dumps(registry), encoding="utf-8")
            reg_path = str(self.registry)
        else:
            reg_path = str(self.stand / "НЕТ-ТАКОГО-ФАЙЛА.json")
        return self.gen.generate(registry_path=reg_path,
                                 output_path=str(self.out))

    def test_unreadable_registry_publishes_absence_not_constants(self):
        """САМ ДЕФЕКТ: реестр не прочитан ⇒ три блока несли 6.5 / 4.1 / 8.0."""
        doc = self._doc(None)
        self.assertEqual(doc["adapters"], {}, "предпосылка сцены: записей нет")
        for key in ("morpho_steakhouse", "aave_arbitrum", "pendle_pt"):
            with self.subTest(key=key):
                self.assertIsNone(doc[key]["apy"],
                                  f"{key}: литерал выдан за наблюдение")
                self.assertIsNone(doc[key]["apy_source"])

    def test_unreadable_registry_does_not_crash_on_bps_gain(self):
        """`bps_gain` считался арифметикой от числа — на `None` это TypeError."""
        doc = self._doc(None)
        self.assertIsNone(doc["morpho_steakhouse"]["bps_gain"])

    def test_readable_registry_copies_the_record_and_names_its_kind(self):
        doc = self._doc({"adapters": {
            "aave_arbitrum": {"protocol": "Aave V3 Arbitrum", "tier": 1,
                              "fallback_apy": 0.041},
        }})
        rec = doc["adapters"]["aave_arbitrum"]
        self.assertEqual(doc["aave_arbitrum"]["apy"], rec["apy"],
                         "теневой блок обязан быть ДУБЛЕМ, а не своим числом")
        # фида нет ⇒ наблюдения нет ⇒ род `static`, а не `live`
        self.assertEqual(doc["aave_arbitrum"]["apy_source"], "static")
        self.assertAlmostEqual(doc["aave_arbitrum"]["apy"], 4.1, places=4,
                               msg="число реестра (fallback_apy ×100) уцелело")

    def test_every_shadow_block_declares_its_kind(self):
        """Обратный контроль: ни один теневой блок не едет без рода."""
        doc = self._doc({"adapters": {}})
        for key in ("morpho_steakhouse", "aave_arbitrum", "pendle_pt"):
            with self.subTest(key=key):
                self.assertIn("apy_source", doc[key])


# ──────────────── 2. цена честного «наблюдения нет» у читателей ─────────────


class TestReadersOnHonestAbsence(unittest.TestCase):
    """Три читателя теневого блока на документе, где число отсутствует."""

    def setUp(self) -> None:
        self.stand = Path(tempfile.mkdtemp(prefix="g851_rd_"))
        (self.stand / "adapter_status.json").write_text(json.dumps({
            "schema_version": 2,
            "generated_by": "adapter_status_generator",
            "adapters": {},
            "morpho_steakhouse": {"apy": None, "apy_source": None,
                                  "bps_gain": None, "protocol_key": "morpho-blue",
                                  "tier": "T1", "tvl_usd": 0.0},
            "aave_arbitrum": {"apy": None, "apy_source": None, "tier": "T1",
                              "network": "arbitrum", "tvl_usd": 0.0},
            "pendle_pt": {"apy": None, "apy_source": None, "tier": "T2",
                          "chain": "ethereum", "protocol_key": "pendle-pt"},
        }), encoding="utf-8")

    def test_aave_arbitrum_adapter_returns_none_as_its_docstring_promises(self):
        """Решение владельца 2026-08-08: «наблюдения нет ⇒ None»."""
        from spa_core.adapters.aave_arbitrum_adapter import AaveArbitrumAdapter
        a = AaveArbitrumAdapter()
        a._data_dir = self.stand
        self.assertIsNone(a._load_apy_from_status())

    def test_morpho_steakhouse_adapter_returns_none(self):
        from spa_core.adapters.morpho_steakhouse_adapter import (
            MorphoSteakhouseAdapter,
        )
        m = MorphoSteakhouseAdapter()
        m._data_dir = self.stand
        self.assertIsNone(m._read_apy_from_status())

    def test_apy_aggregator_skips_the_row_instead_of_crashing(self):
        """`float(None)` уронил бы ВЕСЬ разбор рейтинга.

        Честное «числа нет» не имеет права стоить дороже тихой выдумки.
        """
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.stand)      # не должно бросить
        self.assertEqual(agg.snapshots(), [],
                         "ряд рейтинга без ставки — не ряд")

    def test_apy_aggregator_still_ranks_a_block_that_has_a_number(self):
        """Обратный контроль: число есть ⇒ строка ЕСТЬ (пропуск не огульный)."""
        (self.stand / "adapter_status.json").write_text(json.dumps({
            "schema_version": 2, "adapters": {},
            "aave_arbitrum": {"apy": 3.5, "apy_source": "live", "tier": "T1",
                              "network": "arbitrum", "tvl_usd": 1.0},
        }), encoding="utf-8")
        from spa_core.adapters.apy_aggregator import APYAggregator
        agg = APYAggregator.load(self.stand)
        self.assertEqual(len(agg.snapshots()), 1)
        self.assertAlmostEqual(agg.snapshots()[0].apy_pct, 3.5)


class TestExecutionWriterIsAtomic(unittest.TestCase):
    """Инв. #5: state-файл пишется tmp + os.replace, не сырым `open(..., "w")`."""

    def test_no_plain_open_write_remains_in_write_status_json(self):
        src = (REPO_ROOT / "spa_core" / "execution"
               / "adapter_status.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "write_status_json")
        bad = [n.lineno for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "open"]
        self.assertEqual(bad, [], f"сырой open(..., 'w') вернулся: стр. {bad}")
        self.assertTrue(
            any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "atomic_save"
                for n in ast.walk(fn)),
            "atomic_save в write_status_json не найден")

    def test_write_status_json_leaves_valid_json_and_no_temp_file(self):
        from spa_core.execution.adapter_status import write_status_json
        stand = Path(tempfile.mkdtemp(prefix="g851_exec_"))
        out = stand / "adapter_status.json"
        write_status_json(out)
        json.loads(out.read_text(encoding="utf-8"))          # не порван
        leftovers = [p.name for p in stand.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [], f"временный файл остался: {leftovers}")


# ──────────────────── 3. регрессии САМОГО прибора ───────────────────────────


class TestCensusRegressions(unittest.TestCase):
    """Три ошибки прибора, каждая однажды делала его зелёным и неправым."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.c = _load_census("_g851_census_reg")

    def test_method_form_open_is_detected(self):
        """`path.open("w")` — режим ПЕРВЫМ аргументом.

        Одна мерка на две формы искала его вторым, не находила и МОЛЧА
        пропускала запись: так `execution/adapter_status.py` не попадал в
        писатели вовсе, хотя нарушал инв. #5 — то есть прибор молчал ровно о том
        дефекте, за которым пришёл.
        """
        root = _stand_with_module('''
            from pathlib import Path
            _OUT = Path("data") / "adapter_status.json"
            def w(doc):
                with _OUT.open("w", encoding="utf-8") as fh:
                    fh.write(doc)
        ''')
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["writers"], 1, rep["counts"])
        self.assertEqual(rep["counts"]["non_atomic"], 1)

    def test_path_built_from_parts_resolves(self):
        """`ast.walk` обходит В ШИРИНУ — «последний литерал» давал `"data"`.

        Эта ошибка прятала ГЛАВНОГО писателя (`adapter_status_generator`).
        """
        root = _stand_with_module('''
            import os
            from pathlib import Path
            ROOT = Path("/x")
            _STATUS = ROOT / "data" / "adapter_status.json"
            def w(doc):
                import json
                open(str(_STATUS), "w").write(json.dumps(doc))
        ''')
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["writers"], 1,
                         f"путь из частей не раскрыт: {rep['counts']}")

    def test_os_replace_landing_counts_as_atomic(self):
        """`tmp + os.replace(tmp, dst)` — дословный рецепт инв. #5.

        Без этой формы прибор обвинил бы в неатомарности производителя, который
        пишет ПРАВИЛЬНО (своими руками, не через `atomic_save`).
        """
        root = _stand_with_module('''
            import os, tempfile, json
            from pathlib import Path
            _OUT = Path("data") / "adapter_status.json"
            def w(doc, output_path=_OUT):
                fd, tmp = tempfile.mkstemp(dir=".")
                with os.fdopen(fd, "w") as fh:
                    json.dump(doc, fh)
                os.replace(tmp, output_path)
        ''')
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["writers"], 1, rep["counts"])
        self.assertEqual(rep["counts"]["non_atomic"], 0,
                         "атомарная посадка названа неатомарной")

    def test_same_name_in_two_functions_does_not_cross_contaminate(self):
        """Плоский набор привязок читал `path` одной функции как `path` другой.

        Так прибор обвинил `card_acceptance.py`, который артефакт только ЧИТАЕТ.
        """
        root = _stand_with_module('''
            import os
            def reads():
                path = "data/adapter_status.json"
                return open(path, encoding="utf-8").read()
            def writes_something_else():
                path = os.path.join("data", "my_own_report.json")
                open(path, "w").write("{}")
        ''')
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["writers"], 0,
                         f"чужая привязка прочтена как своя: {rep['writers']}")

    def test_a_resolved_foreign_path_is_not_a_limit(self):
        """Раскрытый ЧУЖОЙ путь есть определённое «не наш писатель».

        Обратный порядок исходов объявлял границей меры 51 запись, почти все из
        которых пишут заведомо другие файлы.
        """
        root = _stand_with_module('''
            def w(doc, path="data/other_artifact.json"):
                open(path, "w").write(doc)
        ''')
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["writers"], 0)
        self.assertEqual(rep["counts"]["caller_supplied"], 0,
                         "чужой путь записан в границы меры")

    def test_literal_substitution_is_found_on_a_crafted_writer(self):
        """Положительный контроль оси L: литерал в опубликованном числе."""
        root = _stand_with_module('''
            from spa_core.utils.atomic import atomic_save
            def w(adapters):
                entry = adapters.get("aave_arbitrum", {})
                apy = entry.get("apy", 4.1)
                doc = {"generated_by": "x", "aave_arbitrum": {"apy": apy}}
                atomic_save(doc, "data/adapter_status.json")
        ''')
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["writers"], 1, rep["counts"])
        self.assertEqual(rep["counts"]["literal_substitution"], 1,
                         f"литерал не найден: {rep['substitutions']}")
        self.assertEqual(rep["substitutions"][0]["literal"], 4.1)

    def test_a_clean_writer_yields_zero_on_axis_l(self):
        """Обратный контроль: ось L не ловит подстрокой."""
        root = _stand_with_module('''
            from spa_core.utils.atomic import atomic_save
            def w(adapters):
                entry = adapters.get("aave_arbitrum", {})
                apy = entry.get("apy")
                doc = {"generated_by": "x",
                       "aave_arbitrum": {"apy": apy, "apy_source": None}}
                atomic_save(doc, "data/adapter_status.json")
        ''')
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["writers"], 1)
        self.assertEqual(rep["counts"]["literal_substitution"], 0)
        self.assertEqual(rep["counts"]["provenance_absent"], 0)

    def test_forbidden_domain_writer_is_named(self):
        root = _stand_with_module('''
            from spa_core.utils.atomic import atomic_save
            def w(doc):
                atomic_save(doc, "data/adapter_status.json")
        ''', pkg=os.path.join("spa_core", "adapters"))
        rep = self.c.measure(root)
        self.assertEqual(rep["counts"]["forbidden_domain"], 1, rep["counts"])

    def test_zero_writers_is_the_third_outcome_not_clean(self):
        """Ноль писателей — отказ меры: у артефакта есть `generated_by`."""
        root = _stand_with_module('x = 1\n')
        rep = self.c.measure(root)
        code, lines = self.c.verdict(rep)
        self.assertEqual(code, 2, lines)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in ln for ln in lines), lines)

    def test_traversal_limit_is_an_input_not_a_constant(self):
        """Предел распространения объявлен ВХОДОМ (урок ADR-703)."""
        self.assertIsInstance(self.c.DERIVE_ROUNDS, int)
        sig = __import__("inspect").signature(self.c._resolve_tails)
        self.assertIn("rounds", sig.parameters)

    def test_live_tree_is_green_at_its_declared_ceilings(self):
        """Прибор на СВОЁМ дереве: код 0 и все классы в потолках."""
        rep = self.c.measure()
        code, lines = self.c.verdict(rep)
        self.assertEqual(code, 0, f"{lines}\n{rep['counts']}")
        self.assertEqual(rep["counts"]["literal_substitution"], 0)

    def test_the_live_writer_declares_itself(self):
        """Один писатель из пяти объявляется — и это тот, кого зовёт цикл."""
        rep = self.c.measure()
        declaring = [w["file"] for w in rep["writers"]
                     if w["declares_generated_by"]]
        self.assertEqual(
            declaring,
            ["spa_core/monitoring/adapter_status_generator.py"],
            f"объявляющий писатель не тот: {declaring}")


# ───────────────────────────── 4. проба приёмки ─────────────────────────────


class TestProbe(unittest.TestCase):
    """Проба зелена на целом контуре и красна на КАЖДОМ порванном звене."""

    PROBE = "adapter_status_number_has_a_writer"

    def setUp(self) -> None:
        from spa_core.monitoring import card_acceptance as ca
        self.ca = ca
        self._saved = sys.modules.get(ca.WRITER_CENSUS_MODULE_NAME)

    def tearDown(self) -> None:
        name = self.ca.WRITER_CENSUS_MODULE_NAME
        if self._saved is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = self._saved

    def _run(self):
        return self.ca.PROBES[self.PROBE](None)

    def _fake(self, rep=None, raiser=None):
        """Подмена ПЕРЕПИСИ в `sys.modules` — доказывает, что проба читает её."""
        import types
        mod = types.ModuleType("fake_census")

        def measure(root_dir=None):
            if raiser is not None:
                raise raiser
            return rep

        mod.measure = measure           # type: ignore[attr-defined]
        sys.modules[self.ca.WRITER_CENSUS_MODULE_NAME] = mod

    def test_registered_by_equality_of_name(self):
        """Имя сверяется РАВЕНСТВОМ, не подстрокой (ADR-333)."""
        self.assertIn(self.PROBE, self.ca.PROBES)
        self.assertNotIn(self.PROBE + "_x", self.ca.PROBES)

    def test_green_on_the_whole_contour(self):
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.SATISFIED, detail)

    def test_probe_reads_the_instrument_not_its_own_copy(self):
        """Подменили перепись — вердикт изменился ⇒ проба читает ПРИБОР."""
        self._fake(rep={
            "counts": {"writers": 1, "literal_substitution": 7,
                       "provenance_absent": 0, "writer_unmeasured": 0,
                       "literal_unmeasured": 0, "caller_supplied": 0,
                       "undeclared": 0},
            "ceilings": {"literal_substitution": 0, "provenance_absent": 1,
                         "writer_unmeasured": 1, "literal_unmeasured": 0,
                         "caller_supplied": 26},
            "substitutions": [{"file": "f.py", "line": 1, "field": "apy",
                               "source_key": "apy", "literal": 4.1}],
        })
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("4.1", detail)

    def test_census_absent_is_unmeasured(self):
        self._fake(raiser=ImportError("нет модуля"))
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.UNMEASURED, detail)

    def test_census_crash_is_unmeasured_with_a_named_reason(self):
        self._fake(raiser=RuntimeError("перепись сломалась"))
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.UNMEASURED, detail)
        self.assertIn("перепись сломалась", detail)

    def test_zero_writers_is_unmeasured_not_satisfied(self):
        self._fake(rep={"counts": {"writers": 0}, "ceilings": {}})
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.UNMEASURED, detail)

    def test_provenance_absent_over_ceiling_is_not_satisfied(self):
        self._fake(rep={
            "counts": {"writers": 2, "literal_substitution": 0,
                       "provenance_absent": 5, "writer_unmeasured": 0,
                       "literal_unmeasured": 0, "caller_supplied": 0,
                       "undeclared": 0},
            "ceilings": {"literal_substitution": 0, "provenance_absent": 1,
                         "writer_unmeasured": 1, "literal_unmeasured": 0,
                         "caller_supplied": 26},
            "provenance_absent": [{"file": "f.py", "line": 9}],
        })
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)

    def test_unmeasured_eats_not_satisfied(self):
        """Третий исход судится ПЕРВЫМ: «не измерено» не выдаётся за ответ."""
        self._fake(rep={
            "counts": {"writers": 2, "literal_substitution": 9,
                       "provenance_absent": 9, "writer_unmeasured": 4,
                       "literal_unmeasured": 0, "caller_supplied": 0,
                       "undeclared": 0},
            "ceilings": {"literal_substitution": 0, "provenance_absent": 1,
                         "writer_unmeasured": 1, "literal_unmeasured": 0,
                         "caller_supplied": 26},
            "substitutions": [], "provenance_absent": [],
        })
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.UNMEASURED, detail)

    def test_undeclared_writers_do_not_gate_the_probe(self):
        """Класс ИЗМЕРЕН, но пробу не гейтит: радиус больше заказа, есть карточка."""
        self._fake(rep={
            "counts": {"writers": 5, "literal_substitution": 0,
                       "provenance_absent": 1, "writer_unmeasured": 1,
                       "literal_unmeasured": 0, "caller_supplied": 26,
                       "undeclared": 4},
            "ceilings": {"literal_substitution": 0, "provenance_absent": 1,
                         "writer_unmeasured": 1, "literal_unmeasured": 0,
                         "caller_supplied": 26},
        })
        verdict, detail = self._run()
        self.assertEqual(verdict, self.ca.SATISFIED, detail)


if __name__ == "__main__":
    unittest.main()
