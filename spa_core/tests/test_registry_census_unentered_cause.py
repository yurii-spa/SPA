"""ADR-1009 — ПРИЧИНА НЕВХОДА: почему бегун ответил `unchecked` внутри предмета прибора.

ADR-1007 § 6б свернул 42 модуля предмета словами «`unchecked` 42 (бегун не входит — ось
ADR-999/1000)», ADR-1008 § 2 повторил формулировку, и заказ G998 п. 1 (а) назвал её премисой
работы. Премиса есть УТВЕРЖДЕНИЕ О МЕХАНИЗМЕ, а в бегуне к ОДНОМУ ярлыку `unchecked` ведут ДВА
РАЗНЫХ пути: сентинел `UNCHECKED` из `_invoke` (ни один вход не биндит контекст — бегун
действительно НЕ ВОШЁЛ) и ПАДЕНИЕ входа, который контекст принять МОГ, с диагнозом
`_foreign_input_entrypoint` (вход требует доменный тип) — а туда бегун ВОШЁЛ и исполнил его строки.
Замер ADR-1009 на живом дереве: премиса ВЕРНА у 0 из 42 и ЛОЖНА у 42.

Что держат эти тесты — по ИСХОДУ `unentered_causes`/`render`, а не по подстроке (ADR-333):

* **основание — ИСПОЛНЕННЫЕ строки ТЕЛА входа** (наблюдение), а не статический вердикт и не
  ярлык: контроль идёт в ОБЕ стороны — строка тела исполнена ⇒ `ENTERED_RAISED_FOREIGN`, ни одна
  не исполнена ⇒ `NO_ENTRY_BOUND`, и переключает вердикт РОВНО это;
* **вторая сторона — СЛОВА самого бегуна, читаемые ПАРИТЕТОМ С ОБЪЯВЛЕНИЕМ:** литералы берутся из
  AST бегуна СЦЕНЫ (`read_runner_unchecked_markers`), а не из копии текста в приборе; литерал,
  которого объявление не несёт, делает разбор НЕ ИЗМЕРЕННЫМ ЦЕЛИКОМ, а не раскладывается по двум
  известным именам (мерка, сверяющая свои константы сама с собой, уже была предметом — ADR-913);
* **расхождение сторон есть НАХОДКА** (`DISAGREED`), а не повод выбрать удобную — контроль в оба
  направления расхождения;
* **вопрос принадлежит статусу `unchecked`:** модуль со статусом `ok` в предмет НЕ входит (его
  вопрос — `SILENT_CAUSES`, ADR-1008), и наоборот;
* **паритет предмета со свёрткой статуса — третий исход**, при расхождении разбор не печатается;
* три исхода различимы всегда (инв. #17): причина НАЗВАНА · НЕ НАЗВАНА (`UNNAMED`/`DISAGREED` с
  основанием) · наблюдения НЕ БЫЛО (`unmeasured_reason`, предмет пуст);
* **предмет ПУСТ и «не мерили» — разные ответы**, и оба печатаются словами;
* **пояснение печатается только у НЕПУСТОЙ стороны:** фраза «там бегун вошёл» при нуле описывала бы
  население, которого замер не нашёл;
* **живой бегун сверяется с объявлением прибора** — дрейф его формулировок обязан покраснеть здесь,
  а не разойтись по двум старым именам на живом населении.

Прод-`data/` ни одна сцена не трогает: наблюдение здесь не запускается — оно подаётся сценой.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"
REAL_RUNNER = ROOT / "spa_core" / "analytics" / "signal_aggregator.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_unentered")

#: Бегун СЦЕНЫ объявляет оба пути к `unchecked` ровно теми же формами, что настоящий: голый
#: литерал и литерал с подстановкой. Текст берётся из ОБЪЯВЛЕНИЯ прибора, чтобы сцена не стала
#: третьим местом, где он живёт: разойдись объявление с бегуном — краснеет живой тест ниже.
_NO_ENTRY_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items() if v == "NO_ENTRY_BOUND"][0]
_FOREIGN_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items()
                 if v == "ENTERED_RAISED_FOREIGN"][0]

RUNNER_STUB = f'''
_ENTRY_METHODS = ("analyze", "score", "run")


class _ModuleAdapter:
    def run(self, protocol, context):
        raw = self._invoke(None, context)
        if raw is UNCHECKED:
            return None, "unchecked", "{_NO_ENTRY_TEXT}"
        try:
            return 1.0, "ok", ""
        except Exception as exc:
            return None, "unchecked", (
                "{_FOREIGN_TEXT} %s; raised %s" % ("x", exc))


class SignalAggregator:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
'''

#: Модуль с входом, объявившим ДОМЕННЫЙ тип: ровно форма 42 модулей живого замера.
MOD_FOREIGN_ENTRY = """
    import json


    def _log(result):
        with open("out.json", "w") as fh:
            json.dump(result, fh)


    def analyze(positions: list):
        head = positions[0]
        _log(head)
        return head
"""

#: Модуль, чей вход требует ДВА позиционных параметра: ровно форма 5 модулей оси `door_unresolved`
#: (`analyze(self, protocols, config)`) — контекст не биндится ни одной формой.
MOD_TWO_REQUIRED = """
    import json

    SETUP = "module level"


    class Analyzer:
        def __init__(self):
            self.ready = True

        def _log(self, result):
            with open("out.json", "w") as fh:
                json.dump(result, fh)

        def analyze(self, protocols, config):
            out = {"n": len(protocols)}
            self._log(out)
            return out
"""

#: Ни одного входа с объявленным бегуном ИМЕНЕМ: входить было некуда, и это НЕ «не вошёл».
MOD_NO_CANDIDATE = """
    import json


    def compute(a, b):
        with open("out.json", "w") as fh:
            json.dump({"s": a + b}, fh)
        return a + b
"""


class Scene:
    """Одноразовое дерево: бегун + ОДИН модуль аналитики. Переписи репозитория здесь не нужно."""

    def __init__(self, source: str, *, module: str = "m_scene", entry: str = "analyze",
                 runner_src: str = RUNNER_STUB):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_unentered_")
        self.root = Path(self.tmp.name)
        pkg = self.root / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        (pkg / "signal_aggregator.py").write_text(textwrap.dedent(runner_src).lstrip("\n"),
                                                  encoding="utf-8")
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

    def verdict(self, write_needles, *, verdict: str = "WRITE_REACHABLE", entry=None,
                door: str = "NONE"):
        writes = [rrwc.WriteSite(func="?", line=self.line_of(n), form="json.dump")
                  for n in write_needles]
        return rrwc.ModuleVerdict(
            module=self.module, tier="B", path=self.rel, registry_class=None,
            runner_target="module", entry=self.entry if entry is None else entry,
            verdict=verdict, writes=writes, reads_context_data_dir=door != "NONE",
            data_dir_door=door)

    def census(self, mv, *, exposure=None, entry_methods=("analyze", "score", "run")):
        runner = rrwc.RunnerSide(entry_methods=entry_methods, passes_data_dir=False,
                                 runner_path="spa_core/analytics/signal_aggregator.py")
        if exposure is None:
            exposure = {"default_reached_under_sandbox":
                        1 if rrwc._exposed_under_sandbox(runner, mv) else 0}
        return rrwc.Census(root=str(self.root), runner=runner, modules=[mv],
                           counts={mv.verdict: 1}, exposure=exposure, blind_subset=None, code=1)

    def obs(self, executed_needles, *, status="unchecked", detail="", lines="measured"):
        ln = sorted({self.line_of(n) for n in executed_needles}) if lines == "measured" else lines
        rec = {"module": self.module, "status": status, "detail": detail, "seconds": 0.0,
               "written": {"runner_dir": [], "tree_data": [], "cwd_data": []}}
        if ln is not None:
            rec["lines"] = ln
        return {"repo": str(self.root) + "_copy", "protocol": "aave_v3", "timeout": 3.0,
                "modules": 1, "statuses": {status: 1}, "baskets": {}, "writers": [],
                "per_module": [rec], "elsewhere_in_tree": [], "parity": {},
                "observer_returncode": 0, "observer_stderr_tail": ""}

    def ask(self, mv, obs, *, exposure=None, axis=rrwc.SILENT_CAUSE_AXIS):
        c = self.census(mv, exposure=exposure)
        return rrwc.unentered_causes(self.root, c, obs, axis)


def _one(res):
    assert res["unmeasured_reason"] is None, res["unmeasured_reason"]
    assert len(res["per_module"]) == 1, res["per_module"]
    return res["per_module"][0]


# ─────────── основание: ИСПОЛНЕННЫЕ строки тела входа, контроль в ОБЕ стороны ───────────

class TestExecutedLinesDecide(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_executed_entry_body_line_makes_it_ENTERED_not_the_premise(self):
        """Строка ТЕЛА входа исполнена ⇒ бегун ВОШЁЛ: премиса «не входит» здесь ЛОЖНА."""
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        row = _one(self.s.ask(mv, self.s.obs(["head = positions[0]"], detail=_FOREIGN_TEXT + " a")))
        self.assertEqual(row["cause"], "ENTERED_RAISED_FOREIGN")
        self.assertEqual(row["entered_entries"], ["analyze"])

    def test_no_entry_body_line_executed_makes_it_NO_ENTRY_BOUND(self):
        """Исполнены только строки МОДУЛЬНОГО уровня ⇒ вход не позван: премиса ВЕРНА."""
        self.s = Scene(MOD_TWO_REQUIRED, entry=None)
        mv = self.s.verdict(["json.dump(result, fh)"], verdict="NO_ENTRY", door="UNRESOLVED")
        row = _one(self.s.ask(mv, self.s.obs(["SETUP = "], detail=_NO_ENTRY_TEXT),
                              exposure={"door_unresolved": 1}, axis="door_unresolved"))
        self.assertEqual(row["cause"], "NO_ENTRY_BOUND")
        self.assertEqual(row["entered_entries"], [])

    def test_the_same_scene_flips_the_verdict_on_the_lines_alone(self):
        """ОДНА сцена, ОДИН вердикт статики: меняются ТОЛЬКО исполненные строки и слова бегуна.

        Положительный контроль на то, что ответ даёт НАБЛЮДЕНИЕ, а не статический вердикт:
        если бы причина выводилась из `entry`/`verdict`, оба прогона дали бы одно и то же.
        """
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        entered = _one(self.s.ask(mv, self.s.obs(["head = positions[0]"],
                                                 detail=_FOREIGN_TEXT + " a")))
        not_entered = _one(self.s.ask(mv, self.s.obs(["import json"], detail=_NO_ENTRY_TEXT)))
        self.assertEqual((entered["cause"], not_entered["cause"]),
                         ("ENTERED_RAISED_FOREIGN", "NO_ENTRY_BOUND"))

    def test_the_def_line_itself_is_not_a_body_line(self):
        """Строка `def` исполняется при ИМПОРТЕ у каждого метода — входом она не является.

        Отрицательный контроль: считай прибор `def` телом, и «не вошёл» стало бы «вошёл» у
        КАЖДОГО импортированного модуля, то есть премиса оказалась бы ложной всегда и ни о чём.
        """
        self.s = Scene(MOD_TWO_REQUIRED, entry=None)
        mv = self.s.verdict(["json.dump(result, fh)"], verdict="NO_ENTRY", door="UNRESOLVED")
        row = _one(self.s.ask(mv, self.s.obs(["def analyze(self, protocols, config):"],
                                             detail=_NO_ENTRY_TEXT),
                              exposure={"door_unresolved": 1}, axis="door_unresolved"))
        self.assertEqual(row["cause"], "NO_ENTRY_BOUND")


# ─────────── вторая сторона: слова бегуна ПАРИТЕТОМ с объявлением ───────────

class TestRunnerWordsByParity(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_markers_are_read_from_the_scene_runner_ast(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        found = rrwc.read_runner_unchecked_markers(self.s.root)
        heads = {rrwc._marker_head(v) for v in found.values()}
        self.assertEqual(heads, set(rrwc.RUNNER_UNCHECKED_MARKERS))

    def test_an_unknown_runner_wording_makes_the_whole_analysis_unmeasured(self):
        """Третий путь бегуна обязан СТАТЬ ВИДИМЫМ, а не разойтись по двум старым именам."""
        self.s = Scene(MOD_FOREIGN_ENTRY, runner_src=RUNNER_STUB.replace(
            f'"{_NO_ENTRY_TEXT}"', '"entrypoint vanished in a brand new way"'))
        mv = self.s.verdict(["json.dump(result, fh)"])
        res = self.s.ask(mv, self.s.obs(["head = positions[0]"], detail=_FOREIGN_TEXT + " a"))
        self.assertIsNotNone(res["unmeasured_reason"])
        self.assertIn("brand new way", res["unmeasured_reason"])
        self.assertEqual(res["subject"], 0)
        self.assertEqual(res["causes"], {})

    def test_a_runner_without_any_unchecked_explanation_is_NotMeasured(self):
        self.s = Scene(MOD_FOREIGN_ENTRY, runner_src='_ENTRY_METHODS = ("analyze",)\n')
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.read_runner_unchecked_markers(self.s.root)

    def test_a_non_literal_explanation_is_NotMeasured_not_a_guess(self):
        """Объяснение, собранное выражением, прибор не разбирает — и говорит это ВСЛУХ."""
        self.s = Scene(MOD_FOREIGN_ENTRY, runner_src=RUNNER_STUB.replace(
            f'return None, "unchecked", "{_NO_ENTRY_TEXT}"',
            'return None, "unchecked", _reason_for(obj)'))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_unchecked_markers(self.s.root)
        self.assertIn("не литералом", str(cm.exception))

    def test_a_missing_runner_is_NotMeasured(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        (self.s.root / "spa_core" / "analytics" / "signal_aggregator.py").unlink()
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.read_runner_unchecked_markers(self.s.root)

    def test_detail_outside_the_declaration_is_UNNAMED_for_that_module(self):
        """Бегун объявлен верно, а СКАЗАЛ про этот модуль иное ⇒ UNNAMED с основанием, не догадка."""
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        row = _one(self.s.ask(mv, self.s.obs(["head = positions[0]"], detail="ModuleNotFoundError")))
        self.assertEqual(row["cause"], "UNNAMED")
        self.assertIsNone(row["runner_said"])


# ─────────── расхождение сторон — НАХОДКА, в оба направления ───────────

class TestDisagreementIsAFinding(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_lines_say_entered_runner_says_no_entry(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        row = _one(self.s.ask(mv, self.s.obs(["head = positions[0]"], detail=_NO_ENTRY_TEXT)))
        self.assertEqual(row["cause"], "DISAGREED")
        self.assertEqual(row["runner_said"], "NO_ENTRY_BOUND")
        self.assertEqual(row["entered_entries"], ["analyze"])

    def test_lines_say_not_entered_runner_says_foreign(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        row = _one(self.s.ask(mv, self.s.obs(["import json"], detail=_FOREIGN_TEXT + " a")))
        self.assertEqual(row["cause"], "DISAGREED")
        self.assertEqual(row["runner_said"], "ENTERED_RAISED_FOREIGN")
        self.assertEqual(row["entered_entries"], [])


# ─────────── третий исход (инв. #17) ───────────

class TestThreeOutcomes(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_no_observation_is_unmeasured_not_zeros(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        res = rrwc.unentered_causes(self.s.root, self.s.census(mv), None)
        self.assertIsNotNone(res["unmeasured_reason"])
        self.assertEqual(res["subject"], 0)
        self.assertEqual(res["causes"], {})

    def test_observation_without_lines_is_UNNAMED_with_its_basis(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        row = _one(self.s.ask(mv, self.s.obs([], detail=_FOREIGN_TEXT + " a", lines=None)))
        self.assertEqual(row["cause"], "UNNAMED")
        self.assertIn("исполненных строк", row["detail"])

    def test_no_candidate_entry_in_the_file_is_UNNAMED_not_NO_ENTRY_BOUND(self):
        """«Входить было некуда» и «вход есть, но не биндится» — разные ответы, и путать их нельзя."""
        self.s = Scene(MOD_NO_CANDIDATE, entry=None)
        mv = self.s.verdict(["json.dump({\"s\": a + b}, fh)"], verdict="NO_ENTRY",
                            door="UNRESOLVED")
        row = _one(self.s.ask(mv, self.s.obs(["import json"], detail=_NO_ENTRY_TEXT),
                              exposure={"door_unresolved": 1}, axis="door_unresolved"))
        self.assertEqual(row["cause"], "UNNAMED")
        self.assertIn("некуда", row["detail"])

    def test_unparsable_module_is_UNNAMED_with_the_reason(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        (self.s.root / self.s.rel).write_text("def analyze(\n", encoding="utf-8")
        row = _one(self.s.ask(mv, self.s.obs([], detail=_NO_ENTRY_TEXT, lines=[1])))
        self.assertEqual(row["cause"], "UNNAMED")
        self.assertIn("не разобран", row["detail"])

    def test_axis_disagreeing_with_its_own_count_blocks_the_analysis(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        res = self.s.ask(mv, self.s.obs(["head = positions[0]"], detail=_FOREIGN_TEXT + " a"),
                         exposure={"default_reached_under_sandbox": 7})
        self.assertIsNotNone(res["unmeasured_reason"])
        self.assertEqual(res["subject"], 0)

    def test_an_empty_subject_is_not_the_same_answer_as_unmeasured(self):
        """Предмет ПУСТ (измерено и равно нулю) ⇔ «не мерили»: оба говорятся словами, но разными."""
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        empty = self.s.ask(mv, self.s.obs(["head = positions[0]"], status="ok",
                                          detail=_FOREIGN_TEXT + " a"))
        self.assertIsNone(empty["unmeasured_reason"])
        self.assertEqual(empty["subject"], 0)
        self.assertEqual(empty["causes"], {k: 0 for k in rrwc.UNENTERED_CAUSES})


# ─────────── вопрос принадлежит статусу `unchecked` ───────────

class TestSubjectIsTheIntersection(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_an_ok_module_is_not_in_the_subject_its_question_is_ADR_1008(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        res = self.s.ask(mv, self.s.obs(["head = positions[0]"], status="ok"))
        self.assertEqual(res["subject"], 0)

    def test_a_module_outside_the_axis_subject_is_not_asked(self):
        """Модуль, которого в предмете оси нет, не спрашивается — и это НЕ «не измерено»."""
        self.s = Scene(MOD_NO_CANDIDATE, entry=None)
        mv = self.s.verdict([], verdict="NO_WRITE_REACHED")
        res = self.s.ask(mv, self.s.obs(["import json"], detail=_NO_ENTRY_TEXT),
                         exposure={"default_reached_under_sandbox": 0})
        self.assertIsNone(res["unmeasured_reason"])
        self.assertEqual(res["subject"], 0)
        # Сворачивать нечего: ни одного `unchecked` в предмете нет, поэтому паритет — `None`
        # («не измерено»), и это ОТЛИЧИМО от расхождения (`False`), которое блокирует разбор.
        self.assertEqual(res["parity"], {"unchecked": None, "subject": 0, "agrees": None})

    def test_parity_of_the_subject_with_the_status_fold_is_reported(self):
        self.s = Scene(MOD_FOREIGN_ENTRY)
        mv = self.s.verdict(["json.dump(result, fh)"])
        res = self.s.ask(mv, self.s.obs(["head = positions[0]"], detail=_FOREIGN_TEXT + " a"))
        self.assertEqual(res["parity"], {"unchecked": 1, "subject": 1, "agrees": True})


# ─────────── объявление осей и печать ───────────

class TestDeclaredAxesAndRender(unittest.TestCase):
    def test_the_axis_list_follows_the_declaration_not_the_order_wording(self):
        """Спроси прибор РОВНО то, что названо вслух, — и `unchecked` третьей оси остались бы без меры.

        Заказ назвал две оси; `OBSERVED_AXES` несёт три, и у третьей (`door_foreign_param`) под
        бегуном тоже есть `unchecked` (4 замером #1131). Перечень берётся у ОБЪЯВЛЕНИЯ.
        """
        self.assertEqual(set(rrwc.UNENTERED_AXES), set(rrwc.OBSERVED_AXES))
        self.assertIn("door_unresolved", rrwc.UNENTERED_AXES)
        self.assertIn(rrwc.SILENT_CAUSE_AXIS, rrwc.UNENTERED_AXES)

    def test_by_axis_answers_for_every_declared_axis(self):
        s = Scene(MOD_FOREIGN_ENTRY)
        try:
            mv = s.verdict(["json.dump(result, fh)"])
            out = rrwc.unentered_causes_by_axis(s.root, s.census(mv), None)
            self.assertEqual(set(out), set(rrwc.UNENTERED_AXES))
        finally:
            s.close()

    def test_render_prints_both_sides_of_the_premise_and_only_the_nonempty_clause(self):
        """Пояснение «там бегун вошёл» при нуле описывало бы ненайденное население."""
        s = Scene(MOD_FOREIGN_ENTRY)
        try:
            mv = s.verdict(["json.dump(result, fh)"])
            c = s.census(mv)
            obs = s.obs(["head = positions[0]"], detail=_FOREIGN_TEXT + " a")
            text = rrwc.render(c, obs)
            line = [ln for ln in text.splitlines() if "премиса" in ln]
            self.assertTrue(line, text)
            self.assertIn("ВЕРНА у 0 из 1", line[0])
            self.assertIn("ЛОЖНА у 1", line[0])
            self.assertIn("ФОРМА контекста", line[0])
            self.assertNotIn("НЕ СУЩЕСТВУЕТ", line[0])
        finally:
            s.close()

    def test_render_says_unmeasured_without_observation(self):
        s = Scene(MOD_FOREIGN_ENTRY)
        try:
            mv = s.verdict(["json.dump(result, fh)"])
            text = rrwc.render(s.census(mv), None)
            self.assertIn("НЕ ИЗМЕРЕНО", [ln for ln in text.splitlines()
                                          if "ПРИЧИНЫ статуса" in ln][0])
        finally:
            s.close()


# ─────────── живой бегун: дрейф его слов обязан покраснеть ЗДЕСЬ ───────────

class TestLiveRunnerParity(unittest.TestCase):
    def test_the_live_runner_explains_unchecked_exactly_as_declared(self):
        """Объявление прибора и формулировки НАСТОЯЩЕГО бегуна — одно и то же, или красный тест.

        Без этого теста дрейф текста в бегуне делал бы разбор `unmeasured` МОЛЧА на живом
        населении: прибор ответил бы честно, но об этом узнал бы только тот, кто прочитал вывод.
        """
        found = rrwc.read_runner_unchecked_markers(ROOT)
        heads = {rrwc._marker_head(v) for v in found.values()}
        self.assertEqual(heads, set(rrwc.RUNNER_UNCHECKED_MARKERS),
                         f"бегун {REAL_RUNNER} объясняет `unchecked` иначе, чем объявлено")

    def test_every_declared_cause_has_a_place_in_the_vocabulary(self):
        self.assertEqual(set(rrwc.RUNNER_UNCHECKED_MARKERS.values()),
                         {"NO_ENTRY_BOUND", "ENTERED_RAISED_FOREIGN"})
        for cause in rrwc.RUNNER_UNCHECKED_MARKERS.values():
            self.assertIn(cause, rrwc.UNENTERED_CAUSES)
        self.assertIn("UNNAMED", rrwc.UNENTERED_CAUSES)
        self.assertIn("DISAGREED", rrwc.UNENTERED_CAUSES)


if __name__ == "__main__":
    unittest.main()
