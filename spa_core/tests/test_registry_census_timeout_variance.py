"""Приёмка ADR-1011: предел модуля — ВТОРОЙ вход наблюдения переписи «реестр → бегун».

Заказ G1000 п. 1 (г) = ADR-1010 § 7 (г). ADR-1010 закрыл первый вход (протокол) и НАЗВАЛ второй:
`--timeout` стоял `3 с` во всех замерах ADR-1002…1010, а зависимость населения
`dormant`/`failed`/`timeout` от него не измерял никто.

У этого входа дефект был ТОНЬШЕ, чем у протокола, и именно поэтому прожил девять решений:
перечня протоколов прибор у себя не держал вовсе, а предел держал — и держал ВЕРНЫЙ
(`default=3.0` при объявлении бегуна `MODULE_TIMEOUT = 3.0`). Верная копия опаснее неверной:
расхождения сегодня нет, назвать дефект нечем, кроме вопроса «а кто тут объявляет?», и молчит
она ровно до того дня, когда бегун поменяет своё число.

Что держит эта батарея — по одному утверждению на класс:

* **предел читается У БЕГУНА** (`read_runner_timeout`), и его исчезновение/переименование/
  невычислимость есть НЕ ИЗМЕРЕНО с причиной, а не подстановка `3.0`;
* **слово ответа на предел тоже читается У БЕГУНА** (`read_runner_timeout_status`): ожидание
  контроля есть утверждение О БЕГУНЕ, и вписать его в прибор значило бы снова свериться с собой —
  переименуй бегун статус, и контроль объявил бы ЖИВОЙ вход мёртвым;
* **`INVARIANT` обязан ЗАРАБОТАТЬ право быть напечатанным.** «Население не зависит от предела» и
  «предел ни на что не влияет» дают ОДНО И ТО ЖЕ наблюдение, а второе есть дефект проводки.
  Поэтому рядом стои́т положительный контроль входа (`timeout_knob_control`), и мёртвый либо
  неизмеренный контроль ЗАКРЫВАЕТ итог (fail-CLOSED) — это несущая половина решения;
* **различие в контроле не нуждается**: названное различие само и есть доказательство, что вход
  до решения доходит;
* **ядро сравнения ОДНО** на оба входа (`_compare_across_values`): своя копия у второго входа
  отвечала бы на свой вопрос, а имя, называющее один из входов, было бы обещанием, которого
  ядро не держит;
* **сравнение ПОИМЁННОЕ**, счёт — следствие (урок шестнадцати литералов «~3,3 %» при треке 5,3 %);
* **у прибора больше НЕТ умолчания-литерала предела** — сторож этого свойства читает AST самого
  прибора, иначе литерал вернулся бы молча первой же правкой;
* **матрица «предел × протокол» ОТКАЗЫВАЕТ, а не выбирает главный вход** — два входа в одном
  словаре наблюдений неразличимы по ключу, и молчаливый выбор снова мерил бы необъявленное.

Контроль у каждого утверждения — в ОБЕ стороны: сцена, где прибор обязан сказать «да», и сцена,
где он обязан сказать «нет» с НАЗВАННОЙ причиной. Живой бегун проверяется отдельно: исчезни у
него объявление предела или слово ответа — краснеет ЗДЕСЬ, а прибор честно скажет НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
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


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_timeouts")

#: Слова бегуна берутся из ОБЪЯВЛЕНИЯ прибора — сцена не имеет права стать третьим местом, где
#: они живут (тот же довод, что в батареях ADR-1009/1010).
_FOREIGN_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items()
                 if v == "ENTERED_RAISED_FOREIGN"][0]
_NO_ENTRY_TEXT = [k for k, v in rrwc.RUNNER_UNCHECKED_MARKERS.items()
                  if v == "NO_ENTRY_BOUND"][0]
_KB_LIVE, _KB_DEAD, _KB_UNMEASURED = rrwc.KNOB_VERDICTS
_INVARIANT, _VARIES, _UNMEASURED = rrwc.PROTOCOL_VERDICTS

SCENE_TIMEOUT = 2.5

#: Бегун сцены для СТАТИЧЕСКИХ вопросов (его не ввозят, только разбирают): объявление предела и
#: обработчик, отвечающий на него СВОИМ словом.
RUNNER_STUB = f'''
_ENTRY_METHODS = ("analyze", "score", "run")

MODULE_TIMEOUT = {SCENE_TIMEOUT}


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
    def __init__(self, data_dir=None, module_timeout=MODULE_TIMEOUT):
        self.data_dir = data_dir
        self.module_timeout = module_timeout

    def _run_module(self, module_info, protocol, context):
        try:
            return self._bounded(module_info, protocol, context)
        except FuturesTimeout:
            self._record(module_info["module"], "timeout")
            return None, False
        except Exception as exc:
            self._record(module_info["module"], "failed", str(exc))
            return None, False
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
    """Одноразовое дерево: бегун с ОБЪЯВЛЕННЫМ пределом + один модуль аналитики."""

    def __init__(self, *, module: str = "m_scene", runner_src: str = RUNNER_STUB,
                 source: str = MOD_FOREIGN_ENTRY):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_timeouts_")
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
        return rrwc.ModuleVerdict(
            module=module or self.module, tier="B", path=self.rel, registry_class=None,
            runner_target="module", entry=entry, verdict="WRITE_REACHABLE",
            writes=[rrwc.WriteSite(func="?", line=self.line_of("json.dump(result, fh)"),
                                   form="json.dump")],
            reads_context_data_dir=False, data_dir_door="NONE")

    def census(self, modules):
        runner = rrwc.RunnerSide(entry_methods=("analyze", "score", "run"), passes_data_dir=False,
                                 runner_path="spa_core/analytics/signal_aggregator.py")
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

    def obs(self, rows, *, timeout=SCENE_TIMEOUT, seconds=0.001):
        """Наблюдение сцены: rows = [(модуль, статус, detail, [исполненные строки])]."""
        per_module = []
        statuses = {}
        for module, status, detail, needles in rows:
            statuses[status] = statuses.get(status, 0) + 1
            per_module.append({
                "module": module, "status": status, "detail": detail, "seconds": seconds,
                "lines": sorted({self.line_of(n) for n in needles}),
                "written": {"runner_dir": [], "tree_data": [], "cwd_data": []}})
        return {"repo": str(self.root) + "_copy", "protocol": "p_one", "timeout": timeout,
                "modules": len(rows), "statuses": statuses, "baskets": {}, "writers": [],
                "per_module": per_module, "elsewhere_in_tree": [], "parity": {},
                "observer_returncode": 0, "observer_stderr_tail": ""}

    def ask(self, modules, by_timeout, knob=None):
        return rrwc.timeout_variance(self.root, self.census(modules), by_timeout, knob)


def _entered(module):
    return (module, "unchecked", _FOREIGN_TEXT + " a", ["head = positions[0]"])


def _not_entered(module):
    return (module, "unchecked", _NO_ENTRY_TEXT, ["import json"])


def _ok(module):
    return (module, "ok", "", ["head = positions[0]"])


def _side(res, name):
    assert name in res["sides"], sorted(res["sides"])
    return res["sides"][name]


def _knob(verdict, **kw):
    """Готовый ответ контроля — чтобы сцены сравнения не платили за подпроцесс."""
    base = {"verdict": verdict, "expected_status": "timeout", "sides": {}, "sleep_s": 0.3,
            "below_s": 0.05, "above_s": 2.0, "dead_reason": None, "unmeasured_reason": None}
    if verdict == _KB_LIVE:
        base["sides"] = {"below": {"timeout": 0.05, "status": "timeout", "seconds": 0.06},
                         "above": {"timeout": 2.0, "status": "ok", "seconds": 0.31}}
    elif verdict == _KB_DEAD:
        base["sides"] = {"below": {"timeout": 0.05, "status": "ok", "seconds": 0.31},
                         "above": {"timeout": 2.0, "status": "ok", "seconds": 0.31}}
        base["dead_reason"] = "предел на решение бегуна НЕ ВЛИЯЕТ так, как объявлено"
    else:
        base["unmeasured_reason"] = "сцена контроля не отдала результата"
    base.update(kw)
    return base


# ───────────── предел читается У БЕГУНА, а не копией в приборе ─────────────

class TestTimeoutComesFromTheRunner(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "s", None) is not None:
            self.s.close()

    def test_declared_timeout_is_read_from_the_runner_ast(self):
        self.s = Scene()
        self.assertEqual(rrwc.read_runner_timeout(self.s.root), SCENE_TIMEOUT)

    def test_a_runner_without_the_declaration_is_UNMEASURED(self):
        """Нет объявления ⇒ третий исход. Подставить `3.0` значило бы ответить о пределе,
        которого бегун не объявляет."""
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"MODULE_TIMEOUT = {SCENE_TIMEOUT}", "OTHER = 1"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout(self.s.root)
        self.assertIn(rrwc.RUNNER_TIMEOUT_NAME, str(cm.exception))

    def test_a_non_literal_declaration_is_UNMEASURED(self):
        """Вычисляемое объявление прибор не угадывает: он разбирает, а не исполняет."""
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"MODULE_TIMEOUT = {SCENE_TIMEOUT}", "MODULE_TIMEOUT = float(_cfg())"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout(self.s.root)
        self.assertIn("не литерал", str(cm.exception))

    def test_a_non_number_declaration_is_UNMEASURED(self):
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"MODULE_TIMEOUT = {SCENE_TIMEOUT}", 'MODULE_TIMEOUT = "3s"'))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout(self.s.root)
        self.assertIn("не число", str(cm.exception))

    def test_a_boolean_declaration_is_UNMEASURED(self):
        """`bool` — подкласс `int`, и `MODULE_TIMEOUT = True` пределом не является: без этой
        ветки прибор ответил бы «предел 1.0 с» о дереве, где предела нет."""
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"MODULE_TIMEOUT = {SCENE_TIMEOUT}", "MODULE_TIMEOUT = True"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout(self.s.root)
        self.assertIn("не число", str(cm.exception))

    def test_a_non_positive_declaration_is_UNMEASURED(self):
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            f"MODULE_TIMEOUT = {SCENE_TIMEOUT}", "MODULE_TIMEOUT = 0"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout(self.s.root)
        self.assertIn("не положителен", str(cm.exception))

    def test_a_missing_runner_is_UNMEASURED(self):
        self.s = Scene()
        (self.s.root / "spa_core" / "analytics" / "signal_aggregator.py").unlink()
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.read_runner_timeout(self.s.root)


# ───────────── слово ответа на предел — тоже У БЕГУНА ─────────────

class TestTimeoutStatusWordComesFromTheRunner(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "s", None) is not None:
            self.s.close()

    def test_word_is_read_from_the_handler(self):
        self.s = Scene()
        self.assertEqual(rrwc.read_runner_timeout_status(self.s.root), "timeout")

    def test_a_renamed_word_is_followed_not_overridden(self):
        """Переименуй бегун свой статус — прибор ЕДЕТ ЗА НИМ. Своя копия слова здесь объявила
        бы живой вход мёртвым, то есть соврала бы в сторону ЛОЖНОЙ находки."""
        self.s = Scene(runner_src=RUNNER_STUB.replace('"timeout")', '"overdue")'))
        self.assertEqual(rrwc.read_runner_timeout_status(self.s.root), "overdue")

    def test_a_runner_without_the_entry_is_UNMEASURED(self):
        self.s = Scene(runner_src=RUNNER_STUB.replace("def _run_module", "def _run_other"))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout_status(self.s.root)
        self.assertIn(rrwc.RUNNER_MODULE_CALL, str(cm.exception))

    def test_a_handler_that_records_nothing_is_UNMEASURED(self):
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            '            self._record(module_info["module"], "timeout")\n', ""))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout_status(self.s.root)
        self.assertIn(rrwc.RUNNER_RECORD, str(cm.exception))

    def test_two_different_words_are_UNMEASURED_not_a_pick(self):
        """Два ответа на предел ⇒ НЕ ИЗМЕРЕНО. Выбрать удобное значило бы раскладывать новый
        механизм по старым именам — дословно дефект, который нашёл ADR-1009."""
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            '            self._record(module_info["module"], "timeout")\n',
            '            self._record(module_info["module"], "timeout")\n'
            '            self._record(module_info["module"], "expired")\n'))
        with self.assertRaises(rrwc.NotMeasured) as cm:
            rrwc.read_runner_timeout_status(self.s.root)
        self.assertIn("РАЗНЫМИ словами", str(cm.exception))

    def test_a_non_timeout_handler_is_not_mistaken_for_one(self):
        """`except Exception` отвечает НЕ на предел, и его слово брать нельзя: иначе контроль
        ждал бы `failed` там, где бегун скажет `timeout`."""
        self.s = Scene(runner_src=RUNNER_STUB.replace(
            "        except FuturesTimeout:\n"
            '            self._record(module_info["module"], "timeout")\n'
            "            return None, False\n", ""))
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.read_runner_timeout_status(self.s.root)


# ───────────── положительный контроль ВХОДА: он и есть несущая половина ─────────────

KNOB_RUNNER_LIVE = '''
import importlib
import threading


class FuturesTimeout(Exception):
    pass


MODULE_TIMEOUT = 3.0


class SignalAggregator:
    def __init__(self, data_dir=None, module_timeout=MODULE_TIMEOUT):
        self.data_dir = data_dir
        self.module_timeout = module_timeout
        self._log = []

    def _record(self, module, status, detail=""):
        self._log.append({"module": module, "status": status, "detail": detail})

    def _call(self, info, context, box, done):
        mod = importlib.import_module("spa_core.analytics." + info["module"])
        box["r"] = mod.analyze(context)
        done.set()

    def _run_module(self, info, protocol, context):
        done, box = threading.Event(), {}
        threading.Thread(target=self._call, args=(info, context, box, done),
                         daemon=True).start()
        try:
            if not done.wait(self.module_timeout):
                raise FuturesTimeout("module exceeded")
        except FuturesTimeout:
            self._record(info["module"], "timeout")
            return None, False
        self._record(info["module"], "ok")
        return box.get("r"), True
'''

#: Мёртвый вход отличается от живого РОВНО ОДНОЙ строкой — тем единственным местом, где предел
#: попадает в решение. Слово ответа при этом объявлено, обработчик на месте, код «выглядит
#: проводкой»: именно эта форма и неотличима от инвариантности по наблюдению.
KNOB_RUNNER_DEAD = KNOB_RUNNER_LIVE.replace(
    "            if not done.wait(self.module_timeout):",
    "            if not done.wait():")


class KnobTree:
    """Ввозимое дерево: пакет `spa_core.analytics` с бегуном сцены (без модулей реестра)."""

    def __init__(self, runner_src: str):
        self.tmp = tempfile.TemporaryDirectory(prefix="rrwc_knob_tree_")
        self.root = Path(self.tmp.name)
        pkg = self.root / "spa_core" / "analytics"
        pkg.mkdir(parents=True)
        (self.root / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "signal_aggregator.py").write_text(textwrap.dedent(runner_src).lstrip("\n"),
                                                  encoding="utf-8")

    def close(self):
        self.tmp.cleanup()


class TestKnobControlSeesABrokenInput(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "t", None) is not None:
            self.t.close()

    def test_a_wired_input_is_KNOB_LIVE(self):
        """Положительный контроль самого контроля: предел доходит до решения ⇒ ответы сторон
        РАЗНЫЕ, и ответ «ниже сна» — то самое слово, которое объявил бегун."""
        self.t = KnobTree(KNOB_RUNNER_LIVE)
        res = rrwc.timeout_knob_control(self.t.root)
        self.assertEqual(res["verdict"], _KB_LIVE, res)
        self.assertEqual(res["expected_status"], "timeout")
        self.assertEqual(res["sides"]["below"]["status"], "timeout")
        self.assertNotEqual(res["sides"]["above"]["status"], "timeout")

    def test_a_dead_input_is_KNOB_DEAD_with_a_named_reason(self):
        """ОДНА строка разницы — и «инвариантность» стала бы описанием мёртвой проводки.
        Прибор обязан назвать это, а не промолчать зелёным."""
        self.t = KnobTree(KNOB_RUNNER_DEAD)
        res = rrwc.timeout_knob_control(self.t.root)
        self.assertEqual(res["verdict"], _KB_DEAD, res)
        self.assertEqual(res["sides"]["below"]["status"], res["sides"]["above"]["status"])
        self.assertIn("НЕ ВЛИЯЕТ", res["dead_reason"])

    def test_the_two_scenes_differ_by_exactly_one_line(self):
        """Предпосылка двух тестов выше: различие — РОВНО в месте, где предел входит в решение.
        Разойдись сцены шире, они мерили бы что угодно ещё."""
        live = KNOB_RUNNER_LIVE.splitlines()
        dead = KNOB_RUNNER_DEAD.splitlines()
        self.assertEqual(len(live), len(dead))
        diff = [i for i, (a, b) in enumerate(zip(live, dead)) if a != b]
        self.assertEqual(len(diff), 1, [live[i] for i in diff])
        self.assertIn("module_timeout", live[diff[0]])

    def test_a_tree_without_a_runner_is_UNMEASURED(self):
        """Бегуна нет вовсе ⇒ третий исход, и причина названа СВОЯ: читать слово не у кого."""
        self.t = KnobTree(KNOB_RUNNER_LIVE)
        (self.t.root / "spa_core" / "analytics" / "signal_aggregator.py").unlink()
        res = rrwc.timeout_knob_control(self.t.root)
        self.assertEqual(res["verdict"], _KB_UNMEASURED, res)
        self.assertIn("слово предела", res["unmeasured_reason"])

    def test_a_runner_that_cannot_be_imported_is_UNMEASURED_by_the_SCENE(self):
        """Слово ЧИТАЕТСЯ (разбор AST не исполняет модуль), а сцена не отрабатывает — это
        ТРЕТЬЕ состояние, и у него обязана быть своя причина: общий ярлык `UNMEASURED` слил бы
        «читать не у кого» с «бегун не ввозится», а лечатся они по-разному."""
        self.t = KnobTree(KNOB_RUNNER_LIVE + '\nraise RuntimeError("бегун сцены не ввозится")\n')
        self.assertEqual(rrwc.read_runner_timeout_status(self.t.root), "timeout")
        res = rrwc.timeout_knob_control(self.t.root)
        self.assertEqual(res["verdict"], _KB_UNMEASURED, res)
        self.assertIn("сцена контроля", res["unmeasured_reason"])

    def test_an_impossible_scene_is_UNMEASURED_before_any_subprocess(self):
        """Границы обязаны обнимать сон; не обнимают — сцена неисполнима, и это говорится
        вслух, а не решается в любую из двух сторон."""
        self.t = KnobTree(KNOB_RUNNER_LIVE)
        res = rrwc.timeout_knob_control(self.t.root, sleep_s=0.3, below=0.5, above=2.0)
        self.assertEqual(res["verdict"], _KB_UNMEASURED)
        self.assertIn("неисполнима", res["unmeasured_reason"])

    def test_a_runner_whose_word_is_unreadable_is_UNMEASURED(self):
        """Слово не прочитано ⇒ ждать от бегуна нечего, и контроль это НАЗЫВАЕТ."""
        self.t = KnobTree(KNOB_RUNNER_LIVE.replace(
            '            self._record(info["module"], "timeout")\n', ""))
        res = rrwc.timeout_knob_control(self.t.root)
        self.assertEqual(res["verdict"], _KB_UNMEASURED, res)
        self.assertIn("слово предела", res["unmeasured_reason"])


# ───────────── один предел на вопрос «различается ли» НЕ ОТВЕЧАЕТ ─────────────

class TestOneTimeoutIsNotAnAnswer(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def test_a_single_observation_is_UNMEASURED_not_invariant(self):
        mv = self.s.verdict()
        res = self.s.ask([mv], {rrwc.timeout_key(3.0): self.s.obs([_entered(mv.module)])},
                         _knob(_KB_LIVE))
        self.assertEqual(res["verdict"], _UNMEASURED)
        self.assertIn(str(rrwc.VARIANCE_MIN), res["unmeasured_reason"])
        self.assertEqual(res["sides"], {})

    def test_no_observation_at_all_has_its_own_reason(self):
        mv = self.s.verdict()
        res = self.s.ask([mv], None, _knob(_KB_LIVE))
        self.assertEqual(res["verdict"], _UNMEASURED)
        self.assertIn("--observe", res["unmeasured_reason"])

    def test_two_observations_do_answer(self):
        mv = self.s.verdict()
        res = self.s.ask([mv], {rrwc.timeout_key(1.0): self.s.obs([_entered(mv.module)]),
                                rrwc.timeout_key(9.0): self.s.obs([_entered(mv.module)])},
                         _knob(_KB_LIVE))
        self.assertEqual(res["verdict"], _INVARIANT)
        self.assertIsNone(res["unmeasured_reason"])

    def test_the_threshold_is_one_door_shared_with_the_protocol_input(self):
        """Порог принадлежит ВОПРОСУ «различается ли», а не входу: вторая копия числа была бы
        ровно тем дефектом, который этот прибор и ловит."""
        self.assertEqual(rrwc.VARIANCE_MIN, rrwc.PROTOCOL_VARIANCE_MIN)

    def test_keys_that_are_not_timeouts_are_UNMEASURED(self):
        """Ключ наблюдения делает ЕДИНСТВЕННАЯ дверь: иначе «наблюдений 2» получается из одного
        предела, записанного двумя способами, и различие сравнивалось бы с самим собой."""
        mv = self.s.verdict()
        res = self.s.ask([mv], {"aave_v3": self.s.obs([_entered(mv.module)]),
                                "maple": self.s.obs([_entered(mv.module)])}, _knob(_KB_LIVE))
        self.assertEqual(res["verdict"], _UNMEASURED)
        self.assertIn("timeout_key", res["unmeasured_reason"])


# ───────────── INVARIANT обязан стоять над ЖИВЫМ контролем (fail-CLOSED) ─────────────

class TestInvarianceMustEarnItsPrint(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.mv = self.s.verdict()
        self.same = {rrwc.timeout_key(1.0): self.s.obs([_entered(self.mv.module)]),
                     rrwc.timeout_key(9.0): self.s.obs([_entered(self.mv.module)])}

    def tearDown(self):
        self.s.close()

    def test_identical_sides_with_a_live_knob_are_INVARIANT(self):
        res = self.s.ask([self.mv], self.same, _knob(_KB_LIVE))
        self.assertEqual(res["verdict"], _INVARIANT)

    def test_identical_sides_with_a_DEAD_knob_are_UNMEASURED(self):
        """Та же сцена, те же наблюдения — меняется ТОЛЬКО контроль входа. Это и есть предмет
        ADR-1011: при мёртвом входе «инвариантно» описывает дефект проводки, а не систему."""
        res = self.s.ask([self.mv], self.same, _knob(_KB_DEAD))
        self.assertEqual(res["verdict"], _UNMEASURED)
        self.assertIn(_KB_DEAD, res["unmeasured_reason"])
        self.assertIn("НЕРАЗЛИЧИМЫ", res["unmeasured_reason"])

    def test_identical_sides_with_an_UNMEASURED_knob_are_UNMEASURED(self):
        res = self.s.ask([self.mv], self.same, _knob(_KB_UNMEASURED))
        self.assertEqual(res["verdict"], _UNMEASURED)
        self.assertIn(_KB_UNMEASURED, res["unmeasured_reason"])

    def test_no_knob_at_all_is_UNMEASURED_with_its_own_reason(self):
        """Контроль не запускался — это НЕ «вход мёртв» и НЕ «инвариантно»: третий исход."""
        res = self.s.ask([self.mv], self.same, None)
        self.assertEqual(res["verdict"], _UNMEASURED)
        self.assertIn("не запускался", res["knob"]["unmeasured_reason"])

    def test_a_named_difference_does_not_need_the_knob(self):
        """Различие само есть доказательство, что вход доходит до решения: требовать контроль
        ещё и здесь значило бы прятать НАХОДКУ за неизмеренной предпосылкой."""
        res = self.s.ask([self.mv],
                         {rrwc.timeout_key(1.0): self.s.obs([_entered(self.mv.module)]),
                          rrwc.timeout_key(9.0): self.s.obs([_not_entered(self.mv.module)])},
                         _knob(_KB_DEAD))
        self.assertEqual(res["verdict"], _VARIES)
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(side["counts"]["LABEL_DIFFERS"], 1)


# ───────────── сравнение ПОИМЁННОЕ: счёт — следствие, а не основание ─────────────

class TestNamesNotCounts(unittest.TestCase):
    def setUp(self):
        self.s = Scene()

    def tearDown(self):
        self.s.close()

    def test_equal_counts_with_different_modules_is_VARIES(self):
        """Счёта равны при обоих пределах (1 и 1), а модули РАЗНЫЕ — мера-по-числам назвала бы
        это инвариантностью. Дословно урок шестнадцати литералов «~3,3 %» при треке 5,3 %."""
        a, b = self.s.verdict(module="m_a"), self.s.verdict(module="m_b")
        res = self.s.ask([a, b], {
            rrwc.timeout_key(1.0): self.s.obs([_entered("m_a"), _ok("m_b")]),
            rrwc.timeout_key(9.0): self.s.obs([_ok("m_a"), _entered("m_b")])}, _knob(_KB_LIVE))
        side = _side(res, f"unentered:{rrwc.SILENT_CAUSE_AXIS}")
        self.assertEqual(set(side["subject"].values()), {1})
        self.assertEqual(side["verdict"], _VARIES)
        self.assertEqual(side["counts"]["SUBJECT_MOVED"], 2)
        self.assertEqual((side["union"], side["intersection"]), (2, 0))

    def test_the_runner_status_side_sees_a_move_as_a_label(self):
        """У стороны `runner_status` предмет — ВСЕ модули, поэтому тот же сдвиг есть ярлык.
        Два вида различия раздельны: свернуть их в одно имя было бы дефектом ADR-1009 выше."""
        a = self.s.verdict(module="m_a")
        res = self.s.ask([a], {rrwc.timeout_key(1.0): self.s.obs([_entered("m_a")]),
                               rrwc.timeout_key(9.0): self.s.obs([_ok("m_a")])}, _knob(_KB_LIVE))
        side = _side(res, "runner_status")
        self.assertEqual(side["counts"]["SUBJECT_MOVED"], 0)
        self.assertEqual(side["counts"]["LABEL_DIFFERS"], 1)
        self.assertEqual(side["differences"]["LABEL_DIFFERS"][0]["labels"],
                         {rrwc.timeout_key(1.0): "unchecked", rrwc.timeout_key(9.0): "ok"})


# ───────────── ЗАПАС: чем объясняется инвариантность, и когда он НЕ ИЗМЕРЕН ─────────────

class TestMarginIsNamedNotAssumed(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.mv = self.s.verdict()

    def tearDown(self):
        self.s.close()

    def test_margin_is_measured_against_the_declared_timeout(self):
        res = self.s.ask([self.mv],
                         {rrwc.timeout_key(1.0): self.s.obs([_entered(self.mv.module)],
                                                            seconds=0.01),
                          rrwc.timeout_key(9.0): self.s.obs([_entered(self.mv.module)],
                                                            seconds=0.005)}, _knob(_KB_LIVE))
        self.assertEqual(res["slowest"]["seconds"], 0.01)
        self.assertEqual(res["margin"], round(SCENE_TIMEOUT / 0.01, 1))

    def test_observations_without_durations_make_the_margin_UNMEASURED_not_zero(self):
        """«Запас не измерен» и «запаса нет» — разные утверждения, и второе читалось бы как
        находка (инв. #17)."""
        obs = self.s.obs([_entered(self.mv.module)])
        for row in obs["per_module"]:
            row.pop("seconds")
        res = self.s.ask([self.mv], {rrwc.timeout_key(1.0): obs,
                                     rrwc.timeout_key(9.0): self.s.obs(
                                         [_entered(self.mv.module)])}, _knob(_KB_LIVE))
        self.assertIsNone(res["slowest"])
        self.assertIsNone(res["margin"])
        self.assertIn("запас НЕ ИЗМЕРЕН", "\n".join(rrwc.render_timeout_variance(res)))

    def test_the_declared_timeout_outside_the_observed_set_is_said_aloud(self):
        """Ответ принадлежит НАБЛЮДЁННЫМ пределам. Нет среди них того, которым живёт бегун, —
        это печатается, а не остаётся свойством вызова."""
        res = self.s.ask([self.mv],
                         {rrwc.timeout_key(1.0): self.s.obs([_entered(self.mv.module)]),
                          rrwc.timeout_key(9.0): self.s.obs([_entered(self.mv.module)])},
                         _knob(_KB_LIVE))
        self.assertFalse(res["declared_observed"])
        self.assertIn("ЕГО НЕТ", "\n".join(rrwc.render_timeout_variance(res)))

    def test_the_declared_timeout_inside_the_observed_set_is_also_said_aloud(self):
        """«Измерено и равно» обязано быть ВИДНО, а не выводиться из молчания."""
        res = self.s.ask([self.mv],
                         {rrwc.timeout_key(SCENE_TIMEOUT): self.s.obs([_entered(self.mv.module)]),
                          rrwc.timeout_key(9.0): self.s.obs([_entered(self.mv.module)])},
                         _knob(_KB_LIVE))
        self.assertTrue(res["declared_observed"])
        self.assertIn("СРЕДИ наблюдённых", "\n".join(rrwc.render_timeout_variance(res)))

    def test_an_unreadable_runner_declaration_closes_the_verdict(self):
        """Без объявления нельзя сказать, входит ли в наблюдённые тот предел, которым бегун
        живёт, — поэтому fail-CLOSED, а не «инвариантно по наблюдённым»."""
        s = Scene(runner_src=RUNNER_STUB.replace(f"MODULE_TIMEOUT = {SCENE_TIMEOUT}", "OTHER = 1"))
        try:
            mv = s.verdict()
            res = s.ask([mv], {rrwc.timeout_key(1.0): s.obs([_entered(mv.module)]),
                               rrwc.timeout_key(9.0): s.obs([_entered(mv.module)])},
                        _knob(_KB_LIVE))
            self.assertEqual(res["verdict"], _UNMEASURED)
            self.assertIn(rrwc.RUNNER_TIMEOUT_NAME, res["unmeasured_reason"])
        finally:
            s.close()


# ───────────── ОДНА дверь: ядро сравнения у обоих входов общее ─────────────

class TestOneComparisonCore(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(CENSUS_PATH.read_text(encoding="utf-8"))

    def _calls_in(self, func_name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return {c.func.id for c in ast.walk(node)
                        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        raise AssertionError(f"в приборе нет функции `{func_name}`")

    def test_both_inputs_call_the_same_core(self):
        for owner in ("protocol_variance", "timeout_variance"):
            self.assertIn("_compare_across_values", self._calls_in(owner), owner)

    def test_there_is_no_second_comparison_core(self):
        """Вторая копия ядра отвечала бы на свой вопрос — тот самый класс, который прибор ловит
        у чужого кода. Сторож намеренно ГРУБЫЙ: ошибаться обязан в сторону находки."""
        names = [n.name for n in ast.walk(self.tree)
                 if isinstance(n, ast.FunctionDef) and "_compare_across" in n.name]
        self.assertEqual(names, ["_compare_across_values"], names)

    def test_the_sides_are_one_declaration_for_both_inputs(self):
        """Стороны объявлены ОДИН раз: разойдись они, ответ о пределе молчал бы о той оси,
        которую протокол уже умеет мерить."""
        src = CENSUS_PATH.read_text(encoding="utf-8")
        self.assertEqual(src.count("PROTOCOL_SIDES: Tuple"), 1)
        self.assertIn("for side in PROTOCOL_SIDES", src)


# ───────────── у прибора НЕТ своего умолчания предела ─────────────

class TestTheInstrumentHoldsNoTimeoutLiteral(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(CENSUS_PATH.read_text(encoding="utf-8"))

    def _argparse_default(self, option):
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"):
                continue
            if not any(isinstance(a, ast.Constant) and a.value == option for a in node.args):
                continue
            for kw in node.keywords:
                if kw.arg == "default":
                    return kw.value
            raise AssertionError(f"у `{option}` не объявлено умолчание")
        raise AssertionError(f"в приборе нет опции `{option}`")

    def test_the_timeout_option_has_no_literal_default(self):
        """Своё `3.0` СОВПАДАЛО с объявлением бегуна, и ровно совпадение делало дефект
        невидимым: прибор сверял свою константу сам с собой (класс ADR-913). Вернись литерал —
        краснеет здесь, а не через девять решений."""
        node = self._argparse_default("--timeout")
        self.assertIsInstance(node, ast.Constant)
        self.assertIsNone(node.value, ast.dump(node))

    def test_the_live_runner_still_declares_the_timeout_and_the_word(self):
        """Живой бегун сверяется с объявлением прибора: исчезни у него `MODULE_TIMEOUT` или
        слово ответа — краснеет ЗДЕСЬ, а прибор честно скажет НЕ ИЗМЕРЕНО."""
        self.assertTrue(REAL_RUNNER.is_file(), REAL_RUNNER)
        self.assertGreater(rrwc.read_runner_timeout(ROOT), 0.0)
        self.assertTrue(rrwc.read_runner_timeout_status(ROOT))


# ───────────── матрица двух входов ОТКАЗЫВАЕТ, а не выбирает главный ─────────────

class TestTwoInputsAtOnceAreNowTheMATRIX(unittest.TestCase):
    """ОСОЗНАННОЕ изменение этого класса (инв. #16: обоснование — здесь, запись — в журнале
    W46, цикл #1134, ADR-1012).

    Здесь стояли два утверждения о том, что смешанный зов `--protocols` + `--timeouts`
    ОТКАЗЫВАЕТ (ADR-1011 § 6). Отказ был верен — но верен ровно для словаря наблюдений с ОДНИМ
    ключом: два входа в нём неразличимы, и молчаливый выбор «главного» снова мерил бы
    необъявленное. ADR-1011 § 7 (а) сам назвал матрицу НЕ ИЗМЕРЕННОЙ и сказал, чем она
    закрывается: «отдельный ответ с ДВУМЯ ключами».

    ADR-1012 его и дал: ключ КЛЕТКИ несёт оба входа сразу (`cell_key`), поэтому выбирать нечего,
    а отказ стал бы отказом мерить ответ, который заказан. Проверка НЕ снята и НЕ ослаблена — она
    ПЕРЕВЁРНУТА и переехала: предмет «два входа сразу» держит теперь
    `spa_core/tests/test_registry_census_matrix_variance.py` (34 утверждения, включая сквозной
    живой зов). Что остаётся здесь — ровно то, что ADR-1012 НЕ отменил: неоднозначный ключ
    клетки по-прежнему ОТКАЗ, а не угаданный разбор.
    """

    def _run(self, *extra):
        """Код 2 сам по себе предметом НЕ является: пустое дерево наблюдения даёт его же.
        Поэтому читается ПРИЧИНА — иначе снятый отказ прошёл бы незамеченным."""
        buf = io.StringIO()
        with tempfile.TemporaryDirectory(prefix="rrwc_matrix_") as tmp:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                code = rrwc.main(["--repo-root", str(ROOT), "--observe", tmp, "--json", *extra])
        return code, json.loads(buf.getvalue())

    def test_the_old_refusal_is_GONE_and_the_tree_refuses_for_its_OWN_reason(self):
        """Пустое дерево наблюдения отказывает по-прежнему — но СВОЕЙ причиной (реестра нет), а
        не прежней «входы спрашиваются по одному». Читается именно причина: код 2 совпал бы."""
        code, doc = self._run("--protocols", "all", "--timeouts", "declared")
        self.assertEqual(code, 2)
        self.assertNotIn("вместе прибор не мерит", doc["unmeasured_reason"])
        self.assertNotIn("спрашиваются ПО", doc["unmeasured_reason"])

    def test_the_same_tree_refuses_identically_for_a_single_input(self):
        """Контроль предпосылки: на ТОМ ЖЕ дереве одиночный вход отказывает ТОЙ ЖЕ причиной —
        значит причина принадлежит дереву, а не смешанному зову."""
        code, doc = self._run("--timeouts", "declared,9")
        self.assertEqual(code, 2)
        mixed = self._run("--protocols", "all", "--timeouts", "declared")[1]
        # Путь одноразового дерева у двух зовов РАЗНЫЙ по построению, поэтому сверяется ПРИЧИНА
        # без него: равенство целых строк отвечало бы на вопрос «одна ли это папка».
        head = lambda r: r.split(":", 1)[0]
        self.assertEqual(head(doc["unmeasured_reason"]), head(mixed["unmeasured_reason"]))
        self.assertEqual(head(doc["unmeasured_reason"]), "реестра нет")

    def test_an_ambiguous_cell_key_is_STILL_a_refusal(self):
        """Единственное, что ADR-1012 НЕ отменил: неоднозначность ключа. Угадай прибор разбор —
        срез отвечал бы о ЧУЖОЙ клетке, то есть вернулся бы молчаливый выбор на уровень ниже."""
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.cell_key(f"aa{rrwc.MATRIX_CELL_SEP}ve", 3.0)


if __name__ == "__main__":
    unittest.main()
