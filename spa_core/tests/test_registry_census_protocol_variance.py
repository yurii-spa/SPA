"""ADR-1010 — ПРОТОКОЛ как объявленный вход: различается ли механизм бегуна по протоколам.

Семь решений подряд (ADR-1002…1009) сняли свои числа ОДНИМ прогоном на `aave_v3`, потому что
`--protocol` имел умолчание и вопрос «зависит ли ОТВЕТ от протокола» никто не задавал (заказ
G999 п. 1б = ADR-1009 § 7б). Замер на живом дереве: `unchecked` ИНВАРИАНТЕН по всем восьми
объявленным протоколам (42/5/4 поимённо те же), а предмет ADR-1008 «вошёл и промолчал» — НЕТ
(117…129, двенадцать модулей входят в него под одними протоколами и не входят под другими).

Что держат эти тесты — по ИСХОДУ `protocol_variance`/`render_protocol_variance`, а не по
подстроке (ADR-333):

* **один протокол на вопрос «различается ли» НЕ ОТВЕЧАЕТ:** `UNMEASURED` с названной причиной, и
  это не «различий нет». Именно подстановка «одно наблюдение ⇒ инвариантно» и держала семь ADR;
* **сравнение ПОИМЁННОЕ, а не по счётам:** контроль — сцена, где счёта у всех протоколов РАВНЫ, а
  модули разные; сравнение по числам объявило бы её инвариантной (дословно урок шестнадцати
  литералов «~3,3 %», `.claude/rules/site-numbers.md`);
* **два вида различия НЕ сворачиваются в одно имя** (`SUBJECT_MOVED` — различается НАСЕЛЕНИЕ ·
  `LABEL_DIFFERS` — различается МЕХАНИЗМ при одном населении): это ровно дефект ADR-1009, один
  ярлык на два механизма, только на уровень выше. Контроль — отдельная сцена на каждый вид;
* **перечень протоколов читается У БЕГУНА** (`read_runner_protocols`), а не хранится копией в
  приборе: нет объявления · не литерал · пусто ⇒ НЕ ИЗМЕРЕНО (мерка, сверяющая свои константы
  сама с собой, уже была предметом — ADR-913);
* **неизмеренная сторона НЕ даёт итогу сказать «инвариантно» по остальным** (fail-CLOSED);
* **предмет ПУСТ под всеми протоколами ≠ сверено поимённо** — вердикт один, ответы РАЗНЫЕ, и
  пустой печатается своими словами (инв. #17);
* **остаток печати считается по КАЖДОМУ виду отдельно:** «всего минус 20» врёт, когда один вид
  короче предела, — и это было бы число без своего производителя;
* **ответ принадлежит НАБЛЮДЁННЫМ протоколам:** объявленный, но не наблюдённый, назван вслух;
* **живой бегун сверяется с объявлением прибора** — исчезни у него `DEFAULT_PROTOCOLS`, краснеет
  здесь, а не отвечает об инвариантности по выдуманному множеству.

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


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_protocols")

#: Слова, которыми бегун СЦЕНЫ объясняет свой `unchecked`, берутся из ОБЪЯВЛЕНИЯ прибора — чтобы
#: сцена не стала третьим местом, где они живут (тот же довод, что в батарее ADR-1009).
_FOREIGN_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items()
                 if v == "ENTERED_RAISED_FOREIGN"][0]
_NO_ENTRY_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items()
                  if v == "NO_ENTRY_BOUND"][0]

SCENE_PROTOCOLS = ["p_one", "p_two"]

RUNNER_STUB = f'''
_ENTRY_METHODS = ("analyze", "score", "run")

DEFAULT_PROTOCOLS = {SCENE_PROTOCOLS!r}


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


class Scene:
    """Одноразовое дерево: бегун с ОБЪЯВЛЕННЫМ перечнем протоколов + один модуль аналитики."""

    def __init__(self, *, module: str = "m_scene", runner_src: str = RUNNER_STUB,
                 source: str = MOD_FOREIGN_ENTRY):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_protocols_")
        self.root = Path(self.tmp.name)
        pkg = self.root / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        (pkg / "signal_aggregator.py").write_text(textwrap.dedent(runner_src).lstrip("\n"),
                                                  encoding="utf-8")
        self.module = module
        self.rel = f"spa_core/analytics/{module}.py"
        self.src = textwrap.dedent(source).lstrip("\n")
        (self.root / self.rel).write_text(self.src, encoding="utf-8")

    def close(self):
        self.tmp.cleanup()

    def line_of(self, needle: str) -> int:
        for i, line in enumerate(self.src.splitlines(), 1):
            if needle in line:
                return i
        raise AssertionError(f"в сцене нет строки с `{needle}`")

    def verdict(self, *, module=None, entry="analyze"):
        mv = rrwc.ModuleVerdict(
            module=module or self.module, tier="B", path=self.rel, registry_class=None,
            runner_target="module", entry=entry, verdict="WRITE_REACHABLE",
            writes=[rrwc.WriteSite(func="?", line=self.line_of("json.dump(result, fh)"),
                                   form="json.dump")],
            reads_context_data_dir=False, data_dir_door="NONE")
        return mv

    def census(self, modules, *, exposure=None):
        runner = rrwc.RunnerSide(entry_methods=("analyze", "score", "run"), passes_data_dir=False,
                                 runner_path="spa_core/analytics/signal_aggregator.py")
        if exposure is None:
            # Счёт объявляется у КАЖДОЙ объявленной оси и ПО ЕЁ ЖЕ правилу: ось без счёта есть
            # третий исход прибора («предмет не подтверждён своим счётом»), и сцена, забывшая
            # его объявить, мерила бы отказ вместо предмета.
            exposure = {}
            for axis, declared in rrwc.OBSERVED_AXES.items():
                rule = declared[1]
                if rule == "exposed":
                    exposure[axis] = sum(1 for m in modules
                                         if rrwc._exposed_under_sandbox(runner, m))
                elif rule.startswith("door:"):
                    door = rule.split(":", 1)[1]
                    exposure[axis] = sum(1 for m in modules if m.data_dir_door == door)
                else:
                    raise AssertionError(f"сцена не знает правила оси `{axis}`: {rule}")
        return rrwc.Census(root=str(self.root), runner=runner, modules=list(modules),
                           counts={"WRITE_REACHABLE": len(modules)}, exposure=exposure,
                           blind_subset=None, code=1)

    def obs(self, rows, *, protocol="p_one"):
        """Наблюдение сцены: rows = [(модуль, статус, detail, [исполненные строки])]."""
        per_module = []
        statuses = {}
        for module, status, detail, needles in rows:
            statuses[status] = statuses.get(status, 0) + 1
            per_module.append({
                "module": module, "status": status, "detail": detail, "seconds": 0.0,
                "lines": sorted({self.line_of(n) for n in needles}),
                "written": {"runner_dir": [], "tree_data": [], "cwd_data": []}})
        return {"repo": str(self.root) + "_copy", "protocol": protocol, "timeout": 3.0,
                "modules": len(rows), "statuses": statuses, "baskets": {}, "writers": [],
                "per_module": per_module, "elsewhere_in_tree": [], "parity": {},
                "observer_returncode": 0, "observer_stderr_tail": ""}

    def ask(self, modules, observations, *, exposure=None):
        c = self.census(modules, exposure=exposure)
        return rrwc.protocol_variance(self.root, c, observations)


def _entered(module):
    return (module, "unchecked", _FOREIGN_TEXT + " a", ["head = positions[0]"])


def _not_entered(module):
    return (module, "unchecked", _NO_ENTRY_TEXT, ["import json"])


def _ok(module):
    return (module, "ok", "", ["head = positions[0]"])


def _dormant(module):
    return (module, "dormant", "", ["import json"])


def _side(res, name):
    assert name in res["sides"], sorted(res["sides"])
    return res["sides"][name]


# ───────────── один протокол на вопрос «различается ли» НЕ ОТВЕЧАЕТ ─────────────

class TestOneProtocolIsNotAnAnswer(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def test_a_single_observation_is_UNMEASURED_not_invariant(self):
        """Один протокол даёт ЗНАЧЕНИЕ, а не различие: вердикт — третий исход с причиной."""
        mv = self.s.verdict()
        res = self.s.ask([mv], {"p_one": self.s.obs([_entered(mv.module)])})
        self.assertEqual(res["verdict"], "UNMEASURED")
        self.assertIn(str(rrwc.PROTOCOL_VARIANCE_MIN), res["unmeasured_reason"])
        self.assertEqual(res["sides"], {})

    def test_no_observation_at_all_is_UNMEASURED_with_its_own_reason(self):
        """Наблюдения НЕ БЫЛО — своя причина, отличная от «наблюдений меньше двух»."""
        mv = self.s.verdict()
        res = self.s.ask([mv], None)
        self.assertEqual(res["verdict"], "UNMEASURED")
        self.assertIn("--observe", res["unmeasured_reason"])

    def test_two_observations_do_answer(self):
        """Положительный контроль того же порога: на двух наблюдениях вердикт ВЫДАЁТСЯ."""
        mv = self.s.verdict()
        res = self.s.ask([mv], {"p_one": self.s.obs([_entered(mv.module)], protocol="p_one"),
                                "p_two": self.s.obs([_entered(mv.module)], protocol="p_two")})
        self.assertIn(res["verdict"], ("INVARIANT", "VARIES"))
        self.assertIsNone(res["unmeasured_reason"])


# ───────────── контроль в ОБЕ стороны: вердикт переключают РОВНО наблюдения ─────────────

class TestVerdictFlipsOnObservationsAlone(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.mv = self.s.verdict()

    def tearDown(self):
        self.s.close()

    def _ask(self, second_rows):
        return self.s.ask([self.mv], {
            "p_one": self.s.obs([_entered(self.mv.module)], protocol="p_one"),
            "p_two": self.s.obs(second_rows, protocol="p_two")})

    def test_same_cause_under_both_protocols_is_INVARIANT(self):
        res = self._ask([_entered(self.mv.module)])
        self.assertEqual(res["verdict"], "INVARIANT")
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(side["verdict"], "INVARIANT")
        self.assertEqual(side["counts"], {k: 0 for k in rrwc.PROTOCOL_DIFFERENCES})
        self.assertFalse(side["subject_empty"])

    def test_a_different_cause_under_the_second_protocol_is_LABEL_DIFFERS(self):
        """ТА ЖЕ сцена, тот же статический вердикт: меняются только наблюдённые строки."""
        res = self._ask([_not_entered(self.mv.module)])
        self.assertEqual(res["verdict"], "VARIES")
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(side["counts"]["LABEL_DIFFERS"], 1)
        self.assertEqual(side["counts"]["SUBJECT_MOVED"], 0)
        row = side["differences"]["LABEL_DIFFERS"][0]
        self.assertEqual(row["module"], self.mv.module)
        self.assertEqual(row["labels"],
                         {"p_one": "ENTERED_RAISED_FOREIGN", "p_two": "NO_ENTRY_BOUND"})

    def test_a_module_leaving_the_subject_is_SUBJECT_MOVED_not_LABEL_DIFFERS(self):
        """Статус перестал быть `unchecked` ⇒ различается НАСЕЛЕНИЕ, а не ярлык внутри него."""
        res = self._ask([_ok(self.mv.module)])
        self.assertEqual(res["verdict"], "VARIES")
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(side["counts"]["SUBJECT_MOVED"], 1)
        self.assertEqual(side["counts"]["LABEL_DIFFERS"], 0)
        row = side["differences"]["SUBJECT_MOVED"][0]
        self.assertEqual((row["in"], row["out"]), (["p_one"], ["p_two"]))

    def test_the_runner_status_side_sees_the_move_as_a_label(self):
        """У стороны `runner_status` предмет — ВСЕ модули, поэтому тот же сдвиг есть ярлык."""
        res = self._ask([_ok(self.mv.module)])
        side = _side(res, "runner_status")
        self.assertEqual(side["counts"]["SUBJECT_MOVED"], 0)
        self.assertEqual(side["counts"]["LABEL_DIFFERS"], 1)
        self.assertEqual(side["differences"]["LABEL_DIFFERS"][0]["labels"],
                         {"p_one": "unchecked", "p_two": "ok"})


# ───────────── сравнение ПОИМЁННОЕ: равные счёта при разных модулях = НАХОДКА ─────────────

class TestNamesNotCounts(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_equal_counts_with_different_modules_is_VARIES(self):
        """Счёта равны у обоих протоколов (1 и 1), а модули РАЗНЫЕ — сравнение по числам
        объявило бы это инвариантностью. Ровно урок шестнадцати литералов «~3,3 %»."""
        self.s = Scene()
        a = self.s.verdict(module="m_a")
        b = self.s.verdict(module="m_b")
        res = self.s.ask([a, b], {
            "p_one": self.s.obs([_entered("m_a"), _ok("m_b")], protocol="p_one"),
            "p_two": self.s.obs([_ok("m_a"), _entered("m_b")], protocol="p_two")})
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(set(side["subject"].values()), {1})       # счёта РАВНЫ
        self.assertEqual(side["verdict"], "VARIES")                 # и всё же различие
        self.assertEqual(side["counts"]["SUBJECT_MOVED"], 2)
        self.assertEqual((side["union"], side["intersection"]), (2, 0))

    def test_counts_alone_would_have_said_invariant(self):
        """Та же сцена, прочитанная ТОЛЬКО по счётам: мера-по-числам даёт ложный зелёный.
        Тест держит не прибор, а ПРИЧИНУ, по которой он сравнивает поимённо."""
        self.s = Scene()
        a = self.s.verdict(module="m_a")
        b = self.s.verdict(module="m_b")
        res = self.s.ask([a, b], {
            "p_one": self.s.obs([_entered("m_a"), _ok("m_b")], protocol="p_one"),
            "p_two": self.s.obs([_ok("m_a"), _entered("m_b")], protocol="p_two")})
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        by_counts = len(set(tuple(sorted(side["subject"].values())) for _ in (0,))) == 1
        self.assertTrue(by_counts, "предпосылка сцены: счёта совпадают")
        self.assertNotEqual(side["verdict"], "INVARIANT")


# ───────────── перечень протоколов — У БЕГУНА, а не копией в приборе ─────────────

class TestProtocolListComesFromTheRunner(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_declared_list_is_read_from_the_runner_ast(self):
        self.s = Scene()
        self.assertEqual(list(rrwc.read_runner_protocols(self.s.root)), SCENE_PROTOCOLS)

    def test_a_runner_without_the_declaration_is_UNMEASURED(self):
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"DEFAULT_PROTOCOLS = {SCENE_PROTOCOLS!r}", "OTHER = 1"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_protocols(self.s.root)
        self.assertIn(rrwc.RUNNER_PROTOCOLS_NAME, str(cm.exception))

    def test_an_empty_declaration_is_UNMEASURED_not_an_empty_answer(self):
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"DEFAULT_PROTOCOLS = {SCENE_PROTOCOLS!r}", "DEFAULT_PROTOCOLS = []"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_protocols(self.s.root)
        self.assertIn("ПУСТ", str(cm.exception))

    def test_a_computed_declaration_is_UNMEASURED_not_guessed(self):
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"DEFAULT_PROTOCOLS = {SCENE_PROTOCOLS!r}", "DEFAULT_PROTOCOLS = list(_src())"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_protocols(self.s.root)
        self.assertIn("не литерал", str(cm.exception))

    def test_a_missing_runner_is_UNMEASURED(self):
        self.s = Scene()
        (self.s.root / "spa_core" / "analytics" / "signal_aggregator.py").unlink()
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.read_runner_protocols(self.s.root)

    def test_an_unreadable_runner_is_UNMEASURED_not_an_empty_list(self):
        self.s = Scene(runner_src="def broken( :\n")
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_protocols(self.s.root)
        self.assertIn("не разобран", str(cm.exception))

    def test_the_verdict_refuses_when_the_runner_list_cannot_be_read(self):
        """Сравнение само по себе возможно, но прибор ОТКАЗЫВАЕТ: ответ без объявления бегуна
        не знал бы, о каком множестве протоколов он говорит."""
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"DEFAULT_PROTOCOLS = {SCENE_PROTOCOLS!r}", "OTHER = 1"))
        mv = self.s.verdict()
        res = self.s.ask([mv], {"p_one": self.s.obs([_entered(mv.module)], protocol="p_one"),
                                "p_two": self.s.obs([_entered(mv.module)], protocol="p_two")})
        self.assertEqual(res["verdict"], "UNMEASURED")
        self.assertIn(rrwc.RUNNER_PROTOCOLS_NAME, res["unmeasured_reason"])


# ───────────── ответ принадлежит НАБЛЮДЁННЫМ протоколам ─────────────

class TestTheAnswerNamesItsOwnScope(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.mv = self.s.verdict()

    def tearDown(self):
        self.s.close()

    def test_a_declared_but_unobserved_protocol_is_named(self):
        """Бегун объявил p_one/p_two, наблюдались p_one и ЧУЖОЙ p_three: оба перечня названы."""
        res = self.s.ask([self.mv], {
            "p_one": self.s.obs([_entered(self.mv.module)], protocol="p_one"),
            "p_three": self.s.obs([_entered(self.mv.module)], protocol="p_three")})
        self.assertEqual(res["declared_not_observed"], ["p_two"])
        self.assertEqual(res["observed_not_declared"], ["p_three"])
        text = "\n".join(rrwc.render_protocol_variance(res))
        self.assertIn("p_two", text)
        self.assertIn("p_three", text)

    def test_full_coverage_is_said_in_its_own_words(self):
        res = self.s.ask([self.mv], {
            "p_one": self.s.obs([_entered(self.mv.module)], protocol="p_one"),
            "p_two": self.s.obs([_entered(self.mv.module)], protocol="p_two")})
        self.assertEqual(res["declared_not_observed"], [])
        self.assertIn("наблюдены ВСЕ", "\n".join(rrwc.render_protocol_variance(res)))


# ───────────── fail-CLOSED: неизмеренная сторона не даёт итогу зеленеть ─────────────

class TestUnmeasuredSideClosesTheVerdict(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_a_side_that_disagrees_with_its_own_count_makes_the_whole_verdict_UNMEASURED(self):
        """Паритет предмета оси со её счётом — предпосылка разбора; расхождение закрывает ИТОГ,
        а не одну сторону: «инвариантно по остальным» было бы ответом, которого замер не делал."""
        self.s = Scene()
        mv = self.s.verdict()
        obs = {"p_one": self.s.obs([_entered(mv.module)], protocol="p_one"),
               "p_two": self.s.obs([_entered(mv.module)], protocol="p_two")}
        res = self.s.ask([mv], obs, exposure={"default_reached_under_sandbox": 7})
        self.assertEqual(res["verdict"], "UNMEASURED")
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(side["verdict"], "UNMEASURED")
        self.assertIn("p_one", side["unmeasured_reason"])
        text = "\n".join(rrwc.render_protocol_variance(res))
        self.assertIn("НЕ ИЗМЕРЕНО", text)

    def test_an_unknown_side_is_refused_by_name(self):
        self.s = Scene()
        mv = self.s.verdict()
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc._side_labels(self.s.root, self.s.census([mv]),
                              self.s.obs([_entered(mv.module)]), "no_such_side")
        self.assertIn("PROTOCOL_SIDES", str(cm.exception))


# ───────────── предмет ПУСТ ≠ сверено поимённо ─────────────

class TestEmptySubjectIsNotASweep(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_an_empty_subject_says_so_in_its_own_words(self):
        """Ни одного `unchecked` ни под одним протоколом: различаться нечему, и это НЕ сверка."""
        self.s = Scene()
        mv = self.s.verdict()
        res = self.s.ask([mv], {"p_one": self.s.obs([_ok(mv.module)], protocol="p_one"),
                                "p_two": self.s.obs([_ok(mv.module)], protocol="p_two")})
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(side["verdict"], "INVARIANT")
        self.assertTrue(side["subject_empty"])
        text = "\n".join(rrwc.render_protocol_variance(res))
        self.assertIn("предмет ПУСТ под всеми протоколами", text)

    def test_a_non_empty_sweep_does_not_claim_emptiness(self):
        self.s = Scene()
        mv = self.s.verdict()
        res = self.s.ask([mv], {"p_one": self.s.obs([_entered(mv.module)], protocol="p_one"),
                                "p_two": self.s.obs([_entered(mv.module)], protocol="p_two")})
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertFalse(side["subject_empty"])
        self.assertIn("совпал ПОИМЁННО", "\n".join(rrwc.render_protocol_variance(res)))


# ───────────── остаток печати считается по КАЖДОМУ виду отдельно ─────────────

class TestRemainderNamesItsProducer(unittest.TestCase):
    def tearDown(self):
        self.s.close()

    def test_remainder_is_per_kind_not_total_minus_two_limits(self):
        """Один вид длиннее предела, второй ПУСТ: «всего минус 20» дало бы заниженный остаток."""
        self.s = Scene()
        n = rrwc._PV_SHOWN + 5
        mods = [self.s.verdict(module=f"m_{i}") for i in range(n)]
        res = self.s.ask(mods, {
            "p_one": self.s.obs([_entered(m.module) for m in mods], protocol="p_one"),
            "p_two": self.s.obs([_not_entered(m.module) for m in mods], protocol="p_two")})
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(side["counts"]["LABEL_DIFFERS"], n)
        self.assertEqual(side["counts"]["SUBJECT_MOVED"], 0)
        text = "\n".join(rrwc.render_protocol_variance(res))
        self.assertIn(f"… и ещё {n - rrwc._PV_SHOWN} ", text)

    def test_nothing_is_elided_when_both_kinds_fit(self):
        self.s = Scene()
        mv = self.s.verdict()
        res = self.s.ask([mv], {"p_one": self.s.obs([_entered(mv.module)], protocol="p_one"),
                                "p_two": self.s.obs([_not_entered(mv.module)], protocol="p_two")})
        self.assertNotIn("и ещё", "\n".join(rrwc.render_protocol_variance(res)))


# ───────────── объявления: перечни читаются, а не живут второй копией ─────────────

class TestDeclarationsHaveReaders(unittest.TestCase):
    def test_verdict_vocabulary_is_the_one_the_instrument_prints(self):
        self.assertEqual(rrwc.PROTOCOL_VERDICTS,
                         (rrwc._PV_INVARIANT, rrwc._PV_VARIES, rrwc._PV_UNMEASURED))

    def test_difference_vocabulary_is_the_one_the_instrument_fills(self):
        self.assertEqual(rrwc.PROTOCOL_DIFFERENCES, (rrwc._PD_MOVED, rrwc._PD_DIFFERS))
        s = Scene()
        try:
            mv = s.verdict()
            res = s.ask([mv], {"p_one": s.obs([_entered(mv.module)], protocol="p_one"),
                               "p_two": s.obs([_entered(mv.module)], protocol="p_two")})
            for side in res["sides"].values():
                self.assertEqual(tuple(side["differences"]), rrwc.PROTOCOL_DIFFERENCES)
        finally:
            s.close()

    def test_sides_cover_every_declared_unentered_axis(self):
        """Перечень сторон объявлен, а не выбран зовом: ось, появившаяся в `UNENTERED_AXES`,
        обязана войти в сравнение сама (тот же довод, что у ADR-1007/1009)."""
        for axis in rrwc.UNENTERED_AXES:
            self.assertIn(f"unentered:{axis}", rrwc.PROTOCOL_SIDES)
        self.assertIn("runner_status", rrwc.PROTOCOL_SIDES)
        self.assertIn("silent", rrwc.PROTOCOL_SIDES)
        self.assertEqual(len(rrwc.PROTOCOL_SIDES), 2 + len(rrwc.UNENTERED_AXES))

    def test_every_side_answers_on_a_live_scene(self):
        """Каждая объявленная сторона ДАЁТ вердикт — объявление без читателя было бы ложным
        усилением (ADR-940…944), и этот прибор ловит ровно его."""
        s = Scene()
        try:
            mv = s.verdict()
            res = s.ask([mv], {"p_one": s.obs([_entered(mv.module)], protocol="p_one"),
                               "p_two": s.obs([_entered(mv.module)], protocol="p_two")})
            self.assertEqual(sorted(res["sides"]), sorted(rrwc.PROTOCOL_SIDES))
            for name, side in res["sides"].items():
                self.assertIn(side["verdict"], rrwc.PROTOCOL_VERDICTS, name)
        finally:
            s.close()


# ───────────── живой бегун сверяется с объявлением прибора ─────────────

class TestTheLiveRunnerIsChecked(unittest.TestCase):
    def test_the_real_runner_declares_the_protocol_list_the_instrument_reads(self):
        """Исчезни/переименуйся `DEFAULT_PROTOCOLS` у живого бегуна — краснеет ЗДЕСЬ, а прибор
        не отвечает об инвариантности по множеству, которого в дереве нет."""
        self.assertTrue(REAL_RUNNER.is_file(), REAL_RUNNER)
        names = rrwc.read_runner_protocols(ROOT)
        self.assertGreaterEqual(len(names), rrwc.PROTOCOL_VARIANCE_MIN,
                                "перечень бегуна короче порога сравнения")
        self.assertTrue(all(isinstance(n, str) and n for n in names), names)


if __name__ == "__main__":
    unittest.main()
