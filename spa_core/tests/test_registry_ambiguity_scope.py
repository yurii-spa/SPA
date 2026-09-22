"""Доля многозначных хвостов у КАЖДОГО документа реестра (заказ G73 п. 2).

Каждый тест — положительный контроль: сцена, в которой порвано ровно одно
звено прибора, и прибор обязан на ней покраснеть. Тест, никогда не видевший
настоящей поломки, есть украшение (`.claude/rules/deployment.md`).

Время сюда не входит вовсе: прибор не судит о свежести, и литеральной даты в
файле нет ни одной — поэтому и пометки `FROZEN-DATE-OK` ему не нужно.
"""
from __future__ import annotations

import ast
import json
import sys
import textwrap
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.monitoring import rule_second_copy_census as C  # noqa: E402


# --- сцена -----------------------------------------------------------------

#: Документ сцены. Подобран так, чтобы в нём ЖИЛИ все три класса цены:
#: `status` однозначен, `rows` многозначен (`rows` и `counts.rows`) и
#: читается формой, у которой путь не разбирается, `verdict` многозначен
#: (`verdict` и `counts.verdict`) и читается формой, у которой путь разобран.
SCENE_DOC = {
    "status": "CLEAN",
    "verdict": "ok",
    "rows": [{"verdict": "ok"}],
    "counts": {"rows": 1, "verdict": 1},
}

SCENE_PRODUCER_SRC = textwrap.dedent('''
    OUTPUT_FILENAME = "scene_census.json"


    def measure(root):
        return {"status": "CLEAN"}


    def run(root):
        return {"doc": measure(root)}


    def report(doc):
        print(doc["status"])
''')

SCENE_READER_SRC = textwrap.dedent('''
    from spa_core.monitoring import scene_census

    KEY = "verdict"


    def test_unambiguous_tail():
        doc = scene_census.measure(".")
        assert doc["status"] == "CLEAN"


    def test_ambiguous_tail_unresolved_path():
        doc = scene_census.measure(".")
        row = doc["rows"][0]
        assert row["verdict"] == "ok"


    def test_ambiguous_tail_resolved_path():
        doc = scene_census.measure(".")
        assert doc["counts"]["verdict"] == 1
''')

CONTROL = C.FILTER_CONTROL_CENSUS


def _scene_tree(tmp: Path, *, doc=None, producer=True, reader=True,
                artifact_name="scene_census.json", artifact_text=None) -> Path:
    """Одноразовое дерево с производителем, читателем и артефактом."""
    root = tmp
    (root / "spa_core" / "monitoring").mkdir(parents=True, exist_ok=True)
    (root / "spa_core" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    if producer:
        (root / "spa_core" / "monitoring" / "scene_census.py").write_text(
            SCENE_PRODUCER_SRC, encoding="utf-8")
    # Производитель, которого НЕ читает никто: на нём стои́т объявленный
    # контроль пред-фильтра, и оба обхода обязаны дать по нулю читателей.
    (root / "spa_core" / "monitoring" / "scene_control.py").write_text(
        SCENE_PRODUCER_SRC.replace("scene_census.json", "scene_control.json"),
        encoding="utf-8")
    (root / "data" / "scene_control.json").write_text(
        json.dumps({"status": "CLEAN"}), encoding="utf-8")
    if reader:
        (root / "spa_core" / "tests" / "test_scene_reader.py").write_text(
            SCENE_READER_SRC, encoding="utf-8")
    payload = SCENE_DOC if doc is None else doc
    text = (artifact_text if artifact_text is not None
            else json.dumps(payload, ensure_ascii=False))
    (root / "data" / artifact_name).write_text(text, encoding="utf-8")
    return root


def _fake_bridge(registry: dict) -> types.ModuleType:
    mod = types.ModuleType(C.REGISTRY_OWNER)
    setattr(mod, C.REGISTRY_ATTR, registry)
    return mod


class _Stubbed:
    """Подменяет реестр в `sys.modules` на время сцены и возвращает как было."""

    def __init__(self, registry):
        self.registry = registry
        self.saved = None
        self.had = False

    def __enter__(self):
        self.had = C.REGISTRY_OWNER in sys.modules
        self.saved = sys.modules.get(C.REGISTRY_OWNER)
        if self.registry is None:
            sys.modules[C.REGISTRY_OWNER] = types.ModuleType(C.REGISTRY_OWNER)
        else:
            sys.modules[C.REGISTRY_OWNER] = _fake_bridge(self.registry)
        return self

    def __exit__(self, *exc):
        if self.had:
            sys.modules[C.REGISTRY_OWNER] = self.saved
        else:
            sys.modules.pop(C.REGISTRY_OWNER, None)
        return False


def _scene_registry(artifact="data/scene_census.json"):
    """Реестр сцены ОБЯЗАН нести объявленный контроль фильтра.

    Иначе прибор отказывает — и это не помеха тесту, а предмет отдельного
    контроля ниже: замер без проверенного фильтра не имеет основания.
    """
    return {
        "scene_census": {"module": "spa_core/monitoring/scene_census.py",
                         "artifact": artifact},
        CONTROL: {"module": "spa_core/monitoring/scene_control.py",
                  "artifact": "data/scene_control.json"},
    }


def _measure(tmp: Path, registry=None, **kw):
    with _Stubbed(_scene_registry() if registry is None else registry):
        return C.registry_ambiguity_scope(tmp, data_dir=tmp / "data", **kw)


# --- хвост как ИМЯ поля -----------------------------------------------------

class NameTailTests(unittest.TestCase):

    def test_index_is_not_a_field_name(self):
        """`findings[0]` читателю по имени недоступен, `findings` — доступен."""
        self.assertEqual(C._name_tail("findings[0]"), "findings")
        self.assertEqual(C._name_tail("a.findings[0].file"), "file")
        self.assertEqual(C._name_tail("a.b[0][1]"), "b")

    def test_tail_owners_group_paths_by_name(self):
        owners = C._tail_owners({"rows": "[]", "counts.rows": "1",
                                 "status": "'CLEAN'"})
        self.assertEqual(sorted(owners["rows"]), ["counts.rows", "rows"])
        self.assertEqual(owners["status"], ["status"])


# --- медиана ----------------------------------------------------------------

class MedianTests(unittest.TestCase):

    def test_empty_population_is_none_not_zero(self):
        """Пустому набору — «не измерено», а не ноль (инв. #17)."""
        self.assertIsNone(C._median([]))

    def test_odd_and_even(self):
        self.assertEqual(C._median([1.0, 5.0, 3.0]), 3.0)
        self.assertEqual(C._median([1.0, 3.0]), 2.0)


# --- где лежит артефакт -----------------------------------------------------

class ArtifactPathTests(unittest.TestCase):

    def test_data_prefix_is_replaced_by_the_given_dir(self):
        p = C._artifact_path(Path("/tree"), "data/x.json", Path("/live/data"))
        self.assertEqual(p, Path("/live/data/x.json"))

    def test_subdirectory_under_data_survives(self):
        """`data/investment_os/outcomes.jsonl` обязан сохранить подкаталог.

        Срезка до имени файла отправила бы прибор искать `outcomes.jsonl` в
        корне `data/` и объявила бы «артефакта нет» про существующий файл.
        """
        p = C._artifact_path(Path("/tree"), "data/investment_os/o.jsonl",
                             Path("/live/data"))
        self.assertEqual(p, Path("/live/data/investment_os/o.jsonl"))

    def test_without_data_dir_the_path_is_tree_relative(self):
        p = C._artifact_path(Path("/tree"), "data/x.json", None)
        self.assertEqual(p, Path("/tree/data/x.json"))

    def test_path_outside_data_is_not_truncated(self):
        p = C._artifact_path(Path("/tree"), "var/x.json", Path("/live/data"))
        self.assertEqual(p, Path("/live/data/var/x.json"))


# --- хвосты ОДНОГО документа ------------------------------------------------

class DocumentAmbiguityTests(unittest.TestCase):

    def test_shallow_rule_does_not_expand_lists(self):
        """Счёт проверен рукой: пути `counts.rows counts.verdict rows status
        verdict` дают ТРИ хвоста (`status`, `verdict`, `rows`), из них
        многозначны два — `verdict` и `rows`."""
        got = C._document_ambiguity(SCENE_DOC)
        self.assertEqual(got["tails_shallow"], 3)
        self.assertEqual(got["ambiguous_shallow"], 2)
        self.assertEqual(got["ambiguous_share_shallow_pct"], 66.67)

    def test_deep_rule_sees_tails_that_live_only_inside_lists(self):
        """`file` и `line` живут ТОЛЬКО внутри элемента списка."""
        got = C._document_ambiguity({"rows": [{"file": "a", "line": 1}],
                                     "n": 1})
        self.assertEqual((got["tails_shallow"], got["tails_deep"]), (2, 3))

    def test_deep_rule_also_LOSES_the_name_of_the_list_itself(self):
        """Цена глубокого правила — не ноль, и молчать о ней нельзя.

        Развернув список, оно перестаёт называть сам список: `rows` исчезает.
        Выдать «точнее» за «строго больше» значило бы соврать в ту сторону,
        которую цикл #674 и измерил как ОБРАТНУЮ.
        """
        got = C._document_ambiguity({"rows": [{"file": "a"}], "file": "b"})
        self.assertEqual((got["tails_shallow"], got["tails_deep"]), (2, 1))

    def test_ambiguity_born_only_of_expansion_is_a_property_of_the_rule(self):
        got = C._document_ambiguity({"rows": [{"file": "a"}, {"file": "b"}],
                                     "n": 1})
        self.assertEqual(got["ambiguous_shallow"], 0)
        self.assertEqual(got["ambiguous_deep"], 1)
        self.assertEqual(got["verdict"], C.FLATTEN_RULE_DEPENDENT)

    def test_document_without_lists_gets_its_own_third_verdict(self):
        """Ноль расхождения при отсутствии списков есть пустота ПО ПОСТРОЕНИЮ.

        Выдать его за «свойство документа» значило бы сказать, что правило
        уплощения ничего не стоит, — не измерив этого ни разу.
        """
        got = C._document_ambiguity({"a": 1, "b": {"a": 2}})
        self.assertEqual(got["lists_in_doc"], 0)
        self.assertEqual(got["verdict"], C.FLATTEN_NO_LISTS)

    def test_lists_without_new_ambiguity_are_a_property_of_the_document(self):
        """Список есть, а новой многозначности он не родил — вердикт третий.

        Второй элемент сделал бы `rows` многозначным у глубокого правила
        (`rows[0]`, `rows[1]`) и перевёл бы вердикт в «свойство правила»:
        разница между двумя вердиктами тут ровно в одном элементе списка.
        """
        got = C._document_ambiguity({"rows": [1], "n": 1})
        self.assertGreater(got["lists_in_doc"], 0)
        self.assertEqual(got["verdict"], C.FLATTEN_DOC_PROPERTY)
        self.assertEqual(
            C._document_ambiguity({"rows": [1, 2], "n": 1})["verdict"],
            C.FLATTEN_RULE_DEPENDENT)

    def test_share_of_an_empty_document_is_none_not_zero(self):
        got = C._document_ambiguity({})
        self.assertIsNone(got["ambiguous_share_shallow_pct"])

    def test_depth_limit_is_counted_and_not_dissolved_into_the_map(self):
        deep = cur = {}
        for _ in range(C.DEEP_FLATTEN_MAX_DEPTH + 5):
            cur["n"] = {}
            cur = cur["n"]
        got = C._document_ambiguity(deep)
        self.assertGreater(got["paths_depth_capped"], 0)


# --- чего многозначность стоит ЧИТАТЕЛЮ -------------------------------------

def _touch(field, path, form=None):
    return {"form": C.TOUCH_DECIDES if form is None else form,
            "field": field, "field_path": path, "line": 1,
            "field_path_outcome": "scene"}


class CostedTouchTests(unittest.TestCase):

    owners = {"rows": ["rows", "counts.rows"], "status": ["status"]}
    ambiguous = {"rows"}

    def _run(self, touches):
        return C._costed_touches([{"file": "f.py", "touches": touches}],
                                 self.owners, self.ambiguous)

    def test_unambiguous_tail_costs_nothing(self):
        _, counts = self._run([_touch("status", "status")])
        self.assertEqual(counts[C.COST_TAIL_UNAMBIGUOUS], 1)
        self.assertEqual(counts[C.COST_DECIDES_AMBIGUOUS], 0)

    def test_resolved_path_makes_an_ambiguous_tail_free(self):
        """Читатель, назвавший ПОЛНЫЙ путь, назвал координату однозначно.

        Считать его ценой значило бы завысить ответ на порядок: на живом
        дереве таких чтений 344 против 38 настоящих.
        """
        costed, counts = self._run([_touch("rows", "counts.rows")])
        self.assertEqual(counts[C.COST_PATH_RESOLVES], 1)
        self.assertEqual(counts[C.COST_DECIDES_AMBIGUOUS], 0)
        self.assertEqual(costed, [])

    def test_ambiguous_tail_with_unresolved_path_is_the_cost(self):
        costed, counts = self._run([_touch("rows", None)])
        self.assertEqual(counts[C.COST_DECIDES_AMBIGUOUS], 1)
        self.assertEqual(len(costed), 1)
        self.assertEqual(costed[0]["paths"], 2)
        self.assertEqual(costed[0]["sample"], ["counts.rows", "rows"])

    def test_unmeasured_field_is_its_own_outcome_not_a_cost(self):
        """«Поле решения не разобрано» — третий исход, а не «стоит»/«не стоит»."""
        costed, counts = self._run([_touch(None, None)])
        self.assertEqual(counts[C.COST_FIELD_UNMEASURED], 1)
        self.assertEqual(counts[C.COST_DECIDES_AMBIGUOUS], 0)
        self.assertEqual(costed, [])

    def test_printing_touch_is_not_a_decision(self):
        _, counts = self._run([_touch("rows", None, form=C.TOUCH_PRINTS)])
        self.assertEqual(sum(counts.values()), 0)


# --- шаг целиком на одноразовом дереве --------------------------------------

class ScopeSceneTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_scene_measures_the_document_and_finds_the_reader(self):
        _scene_tree(self.tmp)
        got = _measure(self.tmp)
        self.assertEqual(got["status"], "MEASURED", got.get("reason"))
        self.assertEqual(got["documents_measured"], 2)
        row = next(r for r in got["rows"] if r["census"] == "scene_census")
        self.assertGreaterEqual(row["readers"], 1)

    def test_the_answer_names_the_reader_the_ambiguity_costs(self):
        """Ровно то, что спросил заказ: есть ли документ, у кого она СТОИТ."""
        _scene_tree(self.tmp)
        got = _measure(self.tmp)
        self.assertEqual(got["verdict"], C.REGISTRY_COSTS_READER)
        row = next(r for r in got["rows"] if r["census"] == "scene_census")
        self.assertTrue(row["costs_a_reader"])
        fields = {t["field"] for t in row["costed_sample"]}
        self.assertIn("rows", fields)
        self.assertNotIn("status", fields)

    def test_all_three_cost_classes_are_populated_by_one_real_reader(self):
        """Классы не выдуманы: одна настоящая сцена населяет все три."""
        _scene_tree(self.tmp)
        got = _measure(self.tmp)
        row = next(r for r in got["rows"] if r["census"] == "scene_census")
        counts = row["cost_counts"]
        self.assertGreaterEqual(counts[C.COST_TAIL_UNAMBIGUOUS], 1)
        self.assertGreaterEqual(counts[C.COST_PATH_RESOLVES], 1)
        self.assertGreaterEqual(counts[C.COST_DECIDES_AMBIGUOUS], 1)

    def test_a_document_nobody_decides_on_costs_nobody(self):
        _scene_tree(self.tmp, reader=False)
        got = _measure(self.tmp)
        self.assertEqual(got["verdict"], C.REGISTRY_COSTS_NOBODY)
        self.assertEqual(got["documents_costing_a_reader"], 0)


# --- ТРЕТИЙ ИСХОД у каждого документа (инв. #17) ----------------------------

class UnmeasuredDocumentTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _outcome_for(self, registry):
        got = _measure(self.tmp, registry=registry)
        self.assertEqual(got["status"], "MEASURED", got.get("reason"))
        rows = [i for i in got["unmeasured"] if i["census"] == "scene_census"]
        self.assertEqual(len(rows), 1, got["unmeasured"])
        return got, rows[0]

    def test_absent_artifact_is_named_not_counted_as_clean(self):
        _scene_tree(self.tmp)
        reg = _scene_registry()
        reg["scene_census"]["artifact"] = "data/nowhere.json"
        got, row = self._outcome_for(reg)
        self.assertEqual(row["outcome"], C.DOC_ABSENT)
        self.assertNotIn("scene_census", [r["census"] for r in got["rows"]])

    def test_non_json_artifact_is_its_own_outcome(self):
        """`.jsonl` — не «многозначности нет», а «уплощать нечего».

        Ровно этот случай живой: `outcomes` реестра есть `outcomes.jsonl`.
        """
        _scene_tree(self.tmp, artifact_name="scene_census.jsonl")
        reg = _scene_registry(artifact="data/scene_census.jsonl")
        got = _measure(self.tmp, registry=reg)
        row = next(i for i in got["unmeasured"]
                   if i["census"] == "scene_census")
        self.assertEqual(row["outcome"], C.DOC_NOT_JSON)
        self.assertIn(".jsonl", row["reason"])
        self.assertNotIn("scene_census", [r["census"] for r in got["rows"]])

    def test_unreadable_json_is_named_with_its_error(self):
        _scene_tree(self.tmp, artifact_text="{ не json")
        got = _measure(self.tmp)
        row = next(i for i in got["unmeasured"]
                   if i["census"] == "scene_census")
        self.assertEqual(row["outcome"], C.DOC_UNREADABLE)
        self.assertIn("Error", row["reason"])

    def test_document_that_is_not_a_mapping_is_named(self):
        """Перечень обязан быть НЕПУСТ: `all([])` зелено при молчании.

        Ровно эта форма и есть вырожденный сторож, которого ищет сосед
        `vacuous_guard_census`: осмотрено ноль, и об этом не сказано ничего.
        """
        _scene_tree(self.tmp, artifact_text=json.dumps([1, 2]))
        got = _measure(self.tmp)
        row = next(i for i in got["unmeasured"]
                   if i["census"] == "scene_census")
        self.assertEqual(row["outcome"], C.DOC_NOT_A_MAPPING)
        self.assertIn("list", row["reason"])

    def test_unreadable_producer_is_named_not_silently_skipped(self):
        _scene_tree(self.tmp, producer=False)
        got = _measure(self.tmp, registry=_scene_registry())
        row = next(i for i in got["unmeasured"]
                   if i["census"] == "scene_census")
        self.assertEqual(row["outcome"], C.DOC_PRODUCER_UNREADABLE)
        self.assertIn("scene_census.py", row["reason"])

    def test_unmeasured_documents_stay_out_of_the_shares(self):
        """Неизмеренный документ не имеет права подпирать медиану."""
        _scene_tree(self.tmp)
        reg = _scene_registry()
        reg["absent"] = {"module": "spa_core/monitoring/scene_census.py",
                         "artifact": "data/nowhere.json"}
        got = _measure(self.tmp, registry=reg)
        self.assertEqual(got["documents_declared"], 3)
        self.assertEqual(got["documents_measured"], 2)
        self.assertEqual(got["documents_unmeasured"], 1)
        self.assertEqual(len(got["unmeasured"]), got["documents_unmeasured"])


# --- ОТКАЗ шага целиком (fail-CLOSED) ---------------------------------------

class StepRefusalTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_registry_without_the_declared_control_refuses(self):
        """Замер без ПРОВЕРЕННОГО фильтра не имеет основания и не выдаётся."""
        _scene_tree(self.tmp)
        reg = {"scene_census": {"module": "spa_core/monitoring/scene_census.py",
                                "artifact": "data/scene_census.json"}}
        got = _measure(self.tmp, registry=reg)
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn(CONTROL, got["reason"])

    def test_filter_that_loses_a_reader_refuses_the_whole_step(self):
        """Пред-фильтр перестал быть надмножеством ⇒ числа НЕ публикуются.

        Сцена рвёт ровно фильтр и ничего больше: контроль ставится на
        производителя, у которого читатель ЕСТЬ, но ни имя переписи в
        реестре, ни имя артефакта, ни точечное имя модуля в тексте читателя
        не встречаются — `from spa_core.monitoring import scene_census`
        не содержит строки `spa_core.monitoring.scene_census` целиком.
        Полный обход читателя находит, фильтрованный — нет.
        """
        _scene_tree(self.tmp)
        reg = {CONTROL: {"module": "spa_core/monitoring/scene_census.py",
                         "artifact": "data/unrelated_name.json"}}
        (self.tmp / "data" / "unrelated_name.json").write_text(
            json.dumps(SCENE_DOC), encoding="utf-8")
        got = _measure(self.tmp, registry=reg)
        self.assertEqual(got["status"], "UNMEASURED", got.get("verdict"))
        self.assertIn("ПОТЕРЯЛ читателей", got["reason"])
        self.assertIn("test_scene_reader.py",
                      " ".join(got["filter_control"]["lost_by_filter"]))

    def test_the_sound_filter_is_proven_sound_and_not_assumed(self):
        """Обратная сторона того же контроля: на целой сцене он ЗЕЛЁН.

        Без этой стороны предыдущий тест краснел бы всегда — и доказывал бы
        не надмножественность фильтра, а лишь то, что шаг умеет отказывать.
        """
        _scene_tree(self.tmp)
        got = _measure(self.tmp)
        self.assertEqual(got["status"], "MEASURED", got.get("reason"))
        self.assertTrue(got["filter_control"]["sound"])
        self.assertEqual(got["filter_control"]["lost_by_filter"], [])
        self.assertEqual(got["filter_control"]["census"], CONTROL)

    def test_empty_registry_refuses(self):
        _scene_tree(self.tmp)
        got = _measure(self.tmp, registry={})
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn(C.REGISTRY_ATTR, got["reason"])

    def test_registry_without_the_attribute_refuses(self):
        _scene_tree(self.tmp)
        with _Stubbed(None):
            got = C.registry_ambiguity_scope(self.tmp,
                                             data_dir=self.tmp / "data")
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn(C.REGISTRY_ATTR, got["reason"])

    def test_empty_code_dirs_of_the_neighbour_refuse_the_step(self):
        """Сосед объявил ПУСТОЙ `_CODE_DIRS` ⇒ обходить нечего.

        Выдать это за «читателей нет» значило бы объявить ноль там, где не
        было сделано ни одного наблюдения (инв. #17).
        """
        import importlib
        _scene_tree(self.tmp)
        neighbour = importlib.import_module(C.NEIGHBOUR_CENSUS)
        saved = neighbour._CODE_DIRS
        neighbour._CODE_DIRS = ()
        try:
            got = _measure(self.tmp)
        finally:
            neighbour._CODE_DIRS = saved
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn("ПУСТОЙ", got["reason"])
        self.assertEqual(neighbour._CODE_DIRS, saved)

    def test_tree_without_code_refuses_instead_of_saying_no_readers(self):
        """«Обходить не в чем» и «читателей нет» — разные утверждения."""
        (self.tmp / "data").mkdir(parents=True, exist_ok=True)
        got = _measure(self.tmp)
        self.assertEqual(got["status"], "UNMEASURED")
        self.assertIn("НЕ «читателей нет»", got["reason"])


# --- ПРОВОДКА: замер обязан доезжать до документа и отчёта -------------------

class WiringTests(unittest.TestCase):

    def test_step_is_called_from_measure(self):
        """Прибор, не позванный из `measure`, есть замер, которого нет."""
        src = (ROOT / "spa_core" / "monitoring"
               / "rule_second_copy_census.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "measure")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("registry_ambiguity_scope", called)

    def test_measure_passes_the_data_dir_through(self):
        """Каталог данных обязан доезжать до шага АРГУМЕНТОМ.

        Оставь его окружением — и шаг из рабочего дерева ответил бы
        «артефакта нет» про каждый документ, выдав свойство дерева за
        свойство реестра.
        """
        src = (ROOT / "spa_core" / "monitoring"
               / "rule_second_copy_census.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "measure")
        self.assertIn("data_dir", [a.arg for a in fn.args.kwonlyargs])
        call = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "registry_ambiguity_scope")
        # Наличие ключа проводкой НЕ является: `data_dir=None` есть тот же
        # ключ и та же слепота. Спрашивается ЗНАЧЕНИЕ — имя параметра
        # `measure`, а не литерал.
        bound = next(kw for kw in call.keywords if kw.arg == "data_dir")
        self.assertIsInstance(bound.value, ast.Name)
        self.assertEqual(bound.value.id, "data_dir")

    def test_run_gives_measure_a_data_dir(self):
        src = (ROOT / "spa_core" / "monitoring"
               / "rule_second_copy_census.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "run")
        call = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "measure")
        self.assertIn("data_dir", [kw.arg for kw in call.keywords])

    def test_report_prints_the_answer_and_says_unmeasured_out_loud(self):
        measured = {"registry_ambiguity_scope": {
            "status": "MEASURED", "verdict": C.REGISTRY_COSTS_READER,
            "documents_declared": 77, "documents_measured": 76,
            "documents_unmeasured": 1, "unmeasured": [],
            "share_shallow_min_pct": 0.0, "share_shallow_median_pct": 9.54,
            "share_shallow_max_pct": 59.38, "share_deep_median_pct": 42.27,
            "neighbour_census": "census_consumer_census",
            "neighbour_share_shallow_pct": 0.87, "neighbour_rank_by_share": 68,
            "documents_costing_a_reader": 13, "cost_totals": {}, "rows": [],
            "filter_control": {"census": CONTROL, "readers_filtered": 24,
                               "readers_full_scan": 24, "lost_by_filter": [],
                               "sound": True},
            "blind": []},
            "status": "CLEAN", "counts": {}, "remedy_counts": {}}
        lines = "\n".join(C.report(measured, max_rows=3))
        self.assertIn("МНОГОЗНАЧНОСТЬ РЕЕСТРА", lines)
        self.assertIn("9.54", lines)
        self.assertIn(C.REGISTRY_COSTS_READER, lines)

        absent = {"status": "CLEAN", "counts": {}, "remedy_counts": {}}
        lines = "\n".join(C.report(absent, max_rows=3))
        self.assertIn("[МНОГОЗНАЧНОСТЬ РЕЕСТРА] НЕ ИЗМЕРЕНА", lines)

    def test_report_refuses_to_substitute_an_empty_list_for_a_missing_key(self):
        """Инв. #17 в СОБСТВЕННОМ отчёте: `or []` на перечень запрещена.

        Документ без ключа `rows` и без ключа `unmeasured` обязан читаться как
        «не измерено», а не как «стоящих читателю документов нет» и «все
        документы измерены». Это ровно тот класс, который заказ G73 п. 3
        называет у соседней печати, и заводить его второй экземпляр здесь
        значило бы чинить в базе то, что чинится в коде.
        """
        doc = {"registry_ambiguity_scope": {
            "status": "MEASURED", "verdict": C.REGISTRY_COSTS_NOBODY,
            "documents_declared": 1, "documents_measured": 1,
            "documents_unmeasured": 0, "cost_totals": {},
            "filter_control": {"census": CONTROL, "readers_filtered": 0,
                               "readers_full_scan": 0, "lost_by_filter": [],
                               "sound": True}},
            "status": "CLEAN", "counts": {}, "remedy_counts": {}}
        lines = "\n".join(C.report(doc, max_rows=3))
        self.assertIn("ЦЕНА] НЕ ИЗМЕРЕНА", lines)
        self.assertIn("НЕ ИЗМЕРЕНО] перечня нет", lines)

    def test_report_says_the_filter_control_is_unmeasured_out_loud(self):
        doc = {"registry_ambiguity_scope": {
            "status": "MEASURED", "verdict": C.REGISTRY_COSTS_NOBODY,
            "documents_declared": 1, "documents_measured": 1,
            "documents_unmeasured": 0, "unmeasured": [], "rows": [],
            "cost_totals": {}},
            "status": "CLEAN", "counts": {}, "remedy_counts": {}}
        lines = "\n".join(C.report(doc, max_rows=3))
        self.assertIn("КОНТРОЛЬ] НЕ ИЗМЕРЕН", lines)

    def test_report_of_a_refused_step_names_the_reason(self):
        doc = {"registry_ambiguity_scope": {"status": "UNMEASURED",
                                            "reason": "реестр не ввезён"},
               "status": "CLEAN", "counts": {}, "remedy_counts": {}}
        lines = "\n".join(C.report(doc, max_rows=3))
        self.assertIn("НЕ ИЗМЕРЕНА: реестр не ввезён", lines)


# --- реестр не копируется, а СПРАШИВАЕТСЯ -----------------------------------

class NoSecondCopyTests(unittest.TestCase):

    def test_registry_is_imported_not_relisted(self):
        """Второй список переписей и есть дефект, который перепись ищет."""
        src = (ROOT / "spa_core" / "monitoring"
               / "rule_second_copy_census.py").read_text(encoding="utf-8")
        self.assertIn(C.REGISTRY_OWNER, src)
        self.assertNotIn('"vacuous_guard_census": {', src)

    def test_code_dirs_are_asked_of_the_neighbour(self):
        """Второй список «где живёт код» тоже был бы копией правила."""
        fn_src = _function_source("registry_ambiguity_scope")
        self.assertIn("_CODE_DIRS", fn_src)
        self.assertNotIn('("spa_core", "scripts", "tests", "research")', fn_src)


def _function_source(name: str) -> str:
    src = (ROOT / "spa_core" / "monitoring"
           / "rule_second_copy_census.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, fn) or ""


if __name__ == "__main__":
    unittest.main()
