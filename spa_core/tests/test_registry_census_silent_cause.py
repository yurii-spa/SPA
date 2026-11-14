"""ADR-1008 — ПРИЧИНА тишины у «вошёл и промолчал» внутри предмета прибора «реестр → бегун».

ADR-1007 измерил, что предмет прибора (`default_reached_under_sandbox` 251) больше числа
наблюдённых записей на 190, и назвал четыре ОСНОВАНИЯ тишины по статусу бегуна: `unchecked` 42 ·
`failed` 5 · `dormant` 14 · **`ok` 129** — вошёл, отработал и не записал. Разбор этих 129 по
ПРИЧИНАМ (ADR-1007 § 6а, заказ G997 п. 1а) и есть вопрос «насколько предмет 251 — ложное
население»: причина решает, была бы починка двери каталога дверью с ЧИТАТЕЛЕМ или ложным усилением
класса ADR-940…944.

Что держат эти тесты — по ИСХОДУ `silent_causes`/`render`, а не по подстроке (ADR-333):

* **основание причины — НАБЛЮДЁННЫЕ исполненные строки** файла модуля под настоящим бегуном, а не
  догадка о взятой ветке: наблюдение без строк ⇒ `UNNAMED` со СВОЕЙ причиной, а не выбор ветки;
* **следствие не выдаётся за причину** — место, чьё условие бегун НЕ ВЫЧИСЛЯЛ, причиной не
  является (на живом населении первая редакция правила давала из-за этого `MIXED` у 80 из 129);
  контроль идёт в ОБЕ стороны: вычисленное и ложное условие причиной БЫТЬ ОБЯЗАНО;
* **`SELF_DISABLED` судит только АРГУМЕНТЫ вызова:** словарь-литерал в теле ОТВЕТА вызовом не
  является (первый замер на этом ошибся — `{"opportunities": []}` в пустой ветви читался как
  «модуль сам выключает запись»);
* **умолчание ключа читается В САМОМ УСЛОВИИ**, а не любым `.get` файла: чтение РЕЗУЛЬТАТА чужого
  вызова (`(analyze(...) or {}).get("opportunities")`) флагом не является;
* **предмет — ПЕРЕСЕЧЕНИЕ двух объявлений:** предмет оси И статус бегуна `ok`; `unchecked`,
  `dormant`, `failed` и писавшие в предмет не входят (у них молчание объясняется раньше пути —
  ADR-1007 § 6б/в);
* **паритет предмета со свёрткой тишины — третий исход** (`agrees False`), и при расхождении
  разбор НЕ печатается: мерка, спорящая сама с собой, вывода не производит;
* три исхода различимы всегда (инв. #17): причина НАЗВАНА · НЕ НАЗВАНА (`UNNAMED` с основанием) ·
  наблюдения НЕ БЫЛО (`unmeasured_reason`, предмет пуст) — и это не одно и то же число;
* граф причины — ТОТ ЖЕ, которым получен вердикт `WRITE_REACHABLE` (по имени, с избытком): вторая
  копия правила объясняла бы ДРУГОЙ граф, чем тот, что дал предмет.

Прод-`data/` ни одна сцена не трогает: наблюдение здесь не запускается — оно подаётся сценой.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_silent_cause")


class Scene:
    """Одноразовое дерево с ОДНИМ модулем аналитики: переписи целого репозитория здесь не нужно."""

    def __init__(self, source: str, *, module: str = "m_scene", entry: str = "analyze"):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_cause_")
        self.root = Path(self.tmp.name)
        pkg = self.root / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        self.module = module
        self.rel = f"spa_core/analytics/{module}.py"
        self.src = textwrap.dedent(source).lstrip("\n")
        (self.root / self.rel).write_text(self.src, encoding="utf-8")
        self.entry = entry

    def close(self):
        self.tmp.cleanup()

    def line_of(self, needle: str) -> int:
        for i, line in enumerate(self.src.splitlines(), 1):
            if needle in line:
                return i
        raise AssertionError(f"в сцене нет строки с `{needle}`")

    def verdict(self, write_needles, *, verdict: str = "WRITE_REACHABLE"):
        writes = [rrwc.WriteSite(func="?", line=self.line_of(n), form="json.dump")
                  for n in write_needles]
        return rrwc.ModuleVerdict(
            module=self.module, tier="B", path=self.rel, registry_class=None,
            runner_target="module", entry=self.entry, verdict=verdict, writes=writes)

    def census(self, mv, *, exposure=None):
        runner = rrwc.RunnerSide(entry_methods=("analyze",), passes_data_dir=False,
                                 runner_path="spa_core/analytics/signal_aggregator.py")
        if exposure is None:
            exposure = {"default_reached_under_sandbox":
                        1 if rrwc._exposed_under_sandbox(runner, mv) else 0}
        return rrwc.Census(root=str(self.root), runner=runner, modules=[mv],
                           counts={mv.verdict: 1}, exposure=exposure, blind_subset=None, code=1)

    def obs(self, executed_needles, *, status: str = "ok", written=None, lines="measured"):
        if lines == "measured":
            ln = sorted({self.line_of(n) for n in executed_needles})
        else:
            ln = lines
        rec = {"module": self.module, "status": status, "detail": "", "seconds": 0.0,
               "written": written or {"runner_dir": [], "tree_data": [], "cwd_data": []}}
        if ln is not None:
            rec["lines"] = ln
        return {"repo": str(self.root) + "_copy", "protocol": "aave_v3", "timeout": 3.0,
                "modules": 1, "statuses": {status: 1}, "baskets": {}, "writers": [],
                "per_module": [rec], "elsewhere_in_tree": [], "parity": {},
                "observer_returncode": 0, "observer_stderr_tail": ""}


FLAG_DEFAULT = """
    import json

    WRITE_LINE = "sentinel"


    def _log(result, path):
        with open(path, "w") as fh:
            json.dump(result, fh)


    def analyze(context, write_log=False):
        result = {"protocol": context["protocol"]}
        if write_log:
            _log(result, "default.json")
        return result
"""

SELF_DISABLED = """
    import json


    def _log(result, path):
        with open(path, "w") as fh:
            json.dump(result, fh)


    def analyze(context, config=None):
        cfg = config or {}
        if is_ctx(context):
            return analyze([context], config={"write_log": False})
        write_log = cfg.get("write_log", True)
        if write_log:
            _log({"ok": 1}, "default.json")
        return {"ok": 1}


    def is_ctx(obj):
        return isinstance(obj, dict)
"""


class SilentCauseIsEarnedFromExecutedLines(unittest.TestCase):
    """Причина названа только тем, что бегун ДЕЙСТВИТЕЛЬНО исполнил."""

    def _run(self, scene, mv, obs):
        return rrwc.silent_causes(scene.root, scene.census(mv), obs)

    def test_falsy_parameter_default_is_named_flag_default_falsy(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = self._run(s, mv, s.obs(["if write_log:", "result = {", "return result"]))
        self.assertEqual(got["subject"], 1)
        self.assertEqual(got["per_module"][0]["cause"], "FLAG_DEFAULT_FALSY")
        self.assertEqual(got["causes"]["FLAG_DEFAULT_FALSY"], 1)

    def test_truthy_default_is_not_the_flag_cause(self):
        """Контроль в ОБРАТНУЮ сторону: правдивое умолчание этой причиной быть не может."""
        s = Scene(FLAG_DEFAULT.replace("write_log=False", "write_log=True"))
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = self._run(s, mv, s.obs(["if write_log:", "result = {", "return result"]))
        self.assertNotEqual(got["per_module"][0]["cause"], "FLAG_DEFAULT_FALSY")

    def test_module_passing_a_falsy_argument_is_named_self_disabled(self):
        s = Scene(SELF_DISABLED)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        obs = s.obs(["cfg = config or {}", "if is_ctx(context):", "write_log = cfg.get",
                     "if write_log:", "return {\"ok\": 1}"])
        got = self._run(s, mv, obs)
        self.assertEqual(got["per_module"][0]["cause"], "SELF_DISABLED")

    def test_a_key_read_in_the_guard_and_passed_falsy_is_self_disabled(self):
        """Условие читает КЛЮЧ прямо в себе, а модуль передаёт его ложным — порядок причин значим.

        Сцена добавлена мутацией M05, пережившей первый прогон: разбора «ключ связан присваиванием»
        для этой формы нет (присваивания нет вовсе), и работает ровно запасная ветвь порядка. На
        живом населении форма не редкость — `(config or {}).get("write_log", True)` у пяти модулей.
        """
        src = """
            import json


            def _log(result, path):
                with open(path, "w") as fh:
                    json.dump(result, fh)


            def analyze(context, config=None):
                if is_ctx(context):
                    return analyze([context], config={"write_log": False})
                if (config or {}).get("write_log", True):
                    _log({"ok": 1}, "default.json")
                return {"ok": 1}


            def is_ctx(obj):
                return isinstance(obj, dict)
        """
        s = Scene(src)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv), s.obs(
            ["if is_ctx(context):", "if (config or {}).get(", "return {\"ok\": 1}"]))
        self.assertEqual(got["per_module"][0]["cause"], "SELF_DISABLED")

    def test_a_dict_literal_in_the_answer_body_is_not_an_argument(self):
        """Дефект ПЕРВОГО замера: `{"k": False}` в теле ОТВЕТА читался как «модуль сам выключает»."""
        src = SELF_DISABLED.replace(
            'return analyze([context], config={"write_log": False})',
            'return {"write_log": False, "protocol": context["protocol"]}')
        s = Scene(src)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        obs = s.obs(["cfg = config or {}", "if is_ctx(context):", "write_log = cfg.get",
                     "if write_log:", "return {\"ok\": 1}"])
        got = self._run(s, mv, obs)
        self.assertNotEqual(got["per_module"][0]["cause"], "SELF_DISABLED")

    def test_a_get_elsewhere_in_the_file_is_not_the_guards_default(self):
        """Второй дефект первого замера: `.get(key)` чужого РЕЗУЛЬТАТА читался как ложное умолчание."""
        src = """
            import json


            def _log(rows, path):
                with open(path, "w") as fh:
                    json.dump(rows, fh)


            def analyze(rows, config=None):
                if is_ctx(rows):
                    borrowed = (analyze([rows]) or {}).get("rows")
                    return {"rows": borrowed}
                if rows:
                    _log(rows, "default.json")
                return {"rows": rows}


            def is_ctx(obj):
                return isinstance(obj, dict)
        """
        s = Scene(src)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(rows, fh)"])
        got = self._run(s, mv, s.obs(["if is_ctx(rows):", "if rows:", "return {\"rows\": rows}"]))
        self.assertEqual(got["per_module"][0]["cause"], "DATA_CONDITION")

    def test_a_guard_about_the_input_is_named_data_condition(self):
        src = """
            import json


            def _log(rows, path):
                with open(path, "w") as fh:
                    json.dump(rows, fh)


            def analyze(rows):
                if len(rows) > 5:
                    _log(rows, "default.json")
                return {"n": len(rows)}
        """
        s = Scene(src)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(rows, fh)"])
        got = self._run(s, mv, s.obs(["if len(rows) > 5:", "return {\"n\": len(rows)}"]))
        self.assertEqual(got["per_module"][0]["cause"], "DATA_CONDITION")

    def test_an_executed_return_before_the_call_is_named(self):
        src = """
            import json


            def _log(rows, path):
                with open(path, "w") as fh:
                    json.dump(rows, fh)


            def analyze(rows):
                if is_ctx(rows):
                    return {"protocol": rows["protocol"]}
                _log(rows, "default.json")
                return {"n": 1}


            def is_ctx(obj):
                return isinstance(obj, dict)
        """
        s = Scene(src)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(rows, fh)"])
        obs = s.obs(["if is_ctx(rows):", "return {\"protocol\": rows["])
        got = self._run(s, mv, obs)
        self.assertEqual(got["per_module"][0]["cause"], "RETURNED_BEFORE_WRITE")


NESTED = """
    import json


    def _log(rows, path):
        with open(path, "w") as fh:
            json.dump(rows, fh)


    def analyze(rows, write_log=False):
        if is_ctx(rows):
            return {"protocol": rows["protocol"]}
        if write_log:
            if rows:
                _log(rows, "default.json")
        return {"n": 1}


    def is_ctx(obj):
        return isinstance(obj, dict)
"""


class ConsequenceIsNotACause(unittest.TestCase):
    """Место, чьё условие бегун НЕ ВЫЧИСЛЯЛ, причиной не является — и обратный контроль к этому."""

    def _cause(self, scene, executed):
        mv = scene.verdict(["json.dump(rows, fh)"])
        got = rrwc.silent_causes(scene.root, scene.census(mv), scene.obs(executed))
        return got["per_module"][0]

    def test_inner_guard_never_evaluated_is_not_reported(self):
        s = Scene(NESTED)
        self.addCleanup(s.close)
        row = self._cause(s, ["if is_ctx(rows):", "if write_log:", "return {\"n\": 1}"])
        self.assertEqual(row["cause"], "FLAG_DEFAULT_FALSY")
        self.assertEqual([x["cause"] for x in row["sites"]], ["FLAG_DEFAULT_FALSY"])

    def test_inner_guard_evaluated_and_false_is_the_cause(self):
        """Обратная сторона: вычисленное и ложное ВНУТРЕННЕЕ условие ОБЯЗАНО стать причиной."""
        s = Scene(NESTED)
        self.addCleanup(s.close)
        row = self._cause(s, ["if is_ctx(rows):", "if write_log:", "if rows:", "return {\"n\": 1}"])
        self.assertEqual(row["cause"], "DATA_CONDITION")

    def test_a_taken_branch_is_not_a_false_guard(self):
        """Ветвь ВЗЯТА, а вызов всё равно не исполнился (пустой цикл) — условие ложным НЕ было.

        Цикл в словарь причин не входит намеренно, и честный ответ здесь `UNNAMED` с основанием, а
        не ближайший флаг: назвать флаг значило бы объявить ложным условие, которое было ИСТИННЫМ.
        """
        src = """
            import json


            def _log(row, path):
                with open(path, "w") as fh:
                    json.dump(row, fh)


            def analyze(rows, write_log=False):
                if write_log:
                    for row in rows:
                        _log(row, "default.json")
                return {"n": 1}
        """
        s = Scene(src)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(row, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv),
                                 s.obs(["if write_log:", "for row in rows:", "return {\"n\": 1}"]))
        row = got["per_module"][0]
        self.assertEqual(row["cause"], "UNNAMED")
        self.assertNotIn("FLAG_DEFAULT_FALSY", [x["cause"] for x in row["sites"]])

    def test_two_evaluated_false_guards_with_different_causes_are_mixed(self):
        src = """
            import json


            def _log(rows, path):
                with open(path, "w") as fh:
                    json.dump(rows, fh)


            def analyze(rows, save=False):
                if not rows:
                    _log([], "default.json")
                    return {"n": 0}
                if save:
                    _log(rows, "default.json")
                return {"n": len(rows)}
        """
        s = Scene(src)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(rows, fh)"])   # обе площадки зовут ОДНОГО писателя
        got = rrwc.silent_causes(s.root, s.census(mv),
                                 s.obs(["if not rows:", "if save:", "return {\"n\": len(rows)}"]))
        row = got["per_module"][0]
        self.assertEqual(row["cause"], "MIXED")
        self.assertEqual({x["cause"] for x in row["sites"]}, {"DATA_CONDITION", "FLAG_DEFAULT_FALSY"})


class ThirdOutcomesAreDistinguishable(unittest.TestCase):
    """«Не названа» и «не мерили» — разные ответы, и ни один не ноль (инв. #17)."""

    def test_without_observation_the_subject_is_unmeasured_not_zero(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv), None)
        self.assertIsNotNone(got["unmeasured_reason"])
        self.assertEqual(got["subject"], 0)
        self.assertEqual(got["causes"], {})
        self.assertIsNone(got["parity"]["agrees"])

    def test_observation_without_executed_lines_is_unnamed_with_its_own_reason(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv), s.obs([], lines=None))
        row = got["per_module"][0]
        self.assertEqual(row["cause"], "UNNAMED")
        self.assertIn("исполненных строк", row["detail"])
        self.assertIsNone(got["unmeasured_reason"])  # наблюдение БЫЛО — не то же самое

    def test_unparsable_module_is_unnamed_with_the_parser_reason(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        obs = s.obs(["if write_log:"])
        (s.root / s.rel).write_text("def analyze(ctx:\n", encoding="utf-8")
        got = rrwc.silent_causes(s.root, s.census(mv), obs)
        self.assertEqual(got["per_module"][0]["cause"], "UNNAMED")
        self.assertIn("не разобран", got["per_module"][0]["detail"])

    def test_missing_entry_in_the_file_is_unnamed_not_a_guessed_cause(self):
        s = Scene(FLAG_DEFAULT, entry="no_such_entry")
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv), s.obs(["if write_log:"]))
        self.assertEqual(got["per_module"][0]["cause"], "UNNAMED")

    def test_executed_write_line_with_an_empty_basket_is_its_own_cause(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv),
                                 s.obs(["if write_log:", "json.dump(result, fh)"]))
        self.assertEqual(got["per_module"][0]["cause"], "WRITE_LINE_EXECUTED")


class SubjectIsTheIntersectionOfTwoDeclarations(unittest.TestCase):
    """Предмет — предмет ОСИ И статус `ok`; остальное принадлежит другим осям."""

    def _subject(self, status, *, written=None):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv),
                                 s.obs(["if write_log:"], status=status, written=written))
        return got

    def test_only_status_ok_is_asked_for_a_cause(self):
        self.assertEqual(self._subject("ok")["subject"], 1)
        for other in ("unchecked", "dormant", "failed", "timeout"):
            with self.subTest(status=other):
                self.assertEqual(self._subject(other)["subject"], 0)

    def test_a_writer_is_not_in_the_subject(self):
        got = self._subject("ok", written={"tree_data": ["x.json"]})
        self.assertEqual(got["subject"], 0)

    def test_a_module_outside_the_axis_subject_is_not_asked(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"], verdict="NO_WRITE_REACHED")
        got = rrwc.silent_causes(s.root, s.census(mv), s.obs(["if write_log:"]))
        self.assertEqual(got["subject"], 0)
        self.assertIsNone(got["unmeasured_reason"])

    def test_a_module_absent_from_the_census_gets_its_own_reason(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        c = s.census(mv)
        obs = s.obs(["if write_log:"])
        c.modules.append(rrwc.ModuleVerdict(
            module="другой", tier="B", path="spa_core/analytics/другой.py", registry_class=None,
            runner_target="module", entry="analyze", verdict="NO_ENTRY"))
        got = rrwc.silent_causes(s.root, c, obs)
        self.assertEqual(got["subject"], 1)


class ParityAndRenderRefuseToBrag(unittest.TestCase):
    """Расхождение мерок — третий исход, и разбор при нём НЕ печатается."""

    def _scene(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        return s, mv

    def test_parity_agrees_on_the_live_rule(self):
        s, mv = self._scene()
        got = rrwc.silent_causes(s.root, s.census(mv), s.obs(["if write_log:"]))
        self.assertTrue(got["parity"]["agrees"])
        self.assertEqual(got["parity"]["silent_ok"], got["parity"]["subject"])

    def test_render_does_not_print_the_breakdown_when_the_count_disagrees(self):
        s, mv = self._scene()
        c = s.census(mv, exposure={"default_reached_under_sandbox": 9})
        text = rrwc.render(c, s.obs(["if write_log:"]))
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("FLAG_DEFAULT_FALSY", text)

    def test_render_names_the_cause_and_the_unnamed_count(self):
        s, mv = self._scene()
        text = rrwc.render(s.census(mv), s.obs(["if write_log:"]))
        self.assertIn("FLAG_DEFAULT_FALSY", text)
        self.assertIn("причина НАЗВАНА у 1 из 1", text)

    def test_render_without_observation_says_not_measured(self):
        s, mv = self._scene()
        text = rrwc.render(s.census(mv), None)
        self.assertIn("ПРИЧИНЫ тишины", text)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("FLAG_DEFAULT_FALSY", text)


class TheGraphIsTheSameOneThatProducedTheSubject(unittest.TestCase):
    """Вторая копия правила обхода объясняла бы ДРУГОЙ граф, чем тот, что дал `WRITE_REACHABLE`."""

    def test_name_match_across_classes_is_kept_as_in_measure_module(self):
        src = """
            import json


            class A:
                def analyze(self, ctx):
                    self._log(ctx)
                    return {"ok": 1}


            class B:
                def _log(self, rows):
                    with open("default.json", "w") as fh:
                        json.dump(rows, fh)
        """
        s = Scene(src, entry="A.analyze")
        self.addCleanup(s.close)
        tree = rrwc._read_tree(s.root / s.rel)
        funcs = rrwc._func_index(tree)
        edges = rrwc._call_edges(funcs)
        holders = rrwc._write_holders(funcs, {s.line_of("json.dump(rows, fh)")})
        self.assertIn(("m", "B", "_log"), holders)
        self.assertTrue(rrwc._leads_to_write(("m", "A", "analyze"), edges, holders))

    def test_declared_vocabulary_covers_every_reported_cause(self):
        s = Scene(FLAG_DEFAULT)
        self.addCleanup(s.close)
        mv = s.verdict(["json.dump(result, fh)"])
        got = rrwc.silent_causes(s.root, s.census(mv), s.obs(["if write_log:"]))
        self.assertEqual(set(got["causes"]), set(rrwc.SILENT_CAUSES))
        self.assertIn(got["per_module"][0]["cause"], rrwc.SILENT_CAUSES)


class TheObserverCarriesExecutedLines(unittest.TestCase):
    """Без строк наблюдения причина не выводима — поэтому наблюдатель обязан их НЕСТИ."""

    def test_observer_source_installs_both_trace_doors(self):
        src = rrwc._OBSERVER
        self.assertIn("threading.settrace(_trace)", src)
        self.assertIn("sys.settrace(_trace)", src)
        self.assertIn('"lines": lines', src)

    def test_observer_restores_the_trace_doors(self):
        """Трассировка, оставленная включённой, меняла бы наблюдение СЛЕДУЮЩИХ модулей."""
        src = rrwc._OBSERVER
        self.assertIn("sys.settrace(None)", src)
        self.assertIn("threading.settrace(None)", src)


class LiveTreeAnswersWithoutObservation(unittest.TestCase):
    """Живое дерево: без наблюдения ответ — НЕ ИЗМЕРЕНО, и `--json` несёт его всегда."""

    def test_live_census_has_the_axis_and_reports_unmeasured(self):
        c = rrwc.measure(ROOT)
        got = rrwc.silent_causes(ROOT, c, None)
        self.assertEqual(got["axis"], rrwc.SILENT_CAUSE_AXIS)
        self.assertEqual(got["status"], rrwc.SILENT_CAUSE_STATUS)
        self.assertIsNotNone(got["unmeasured_reason"])

    def test_json_output_carries_silent_causes_without_observation(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(CENSUS_PATH), "--repo-root", str(ROOT), "--json"],
            capture_output=True, text=True)
        doc = json.loads(proc.stdout)
        self.assertIn("silent_causes", doc)
        self.assertIsNotNone(doc["silent_causes"]["unmeasured_reason"])


if __name__ == "__main__":
    unittest.main()
