"""Приёмка ADR-1016: население класса «дольше предела хотя бы ИНОГДА» мерится РЯДОМ проходов.

Заказ G1005 п. 1 = [ADR-1015](../../docs/decisions/ADR-1015-the-limit-is-blind-to-a-busy-module.md)
§ 7 (в). ADR-1015 нашёл замером, что `MODULE_TIMEOUT` **не ограничивает вычисляющий модуль**
(занятый 0.05 с при пределе 0.01 с получил `ok` у 10 из 10 повторов), и честно оставил открытым
главный вопрос: СКОЛЬКИХ из 302 записей реестра это задело. Прежний замер (#1136,
`0.008 … 0.016 с`) на него не отвечает ПО ПОСТРОЕНИЮ, и причин ровно две:

1. он снят ОДНИМ проходом, а предмет — «хотя бы ИНОГДА»: одно наблюдение отвечает про один
   момент времени, и модуль, выходящий за предел через раз, в нём безупречен;
2. он свёрнут в один ряд по ВСЕМ модулям («самый медленный — 0.016 с»), то есть отвечает про
   прогон, а население есть ответ ПОИМЁННЫЙ.

Что держит эта батарея — по одному утверждению на класс:

* **вердикт модуля считается по МАКСИМУМУ РЯДА**, а не по первой строке и не по среднему: мутант
  «читать только первый проход» умирает на ЧЕРЕДУЮЩЕМСЯ модуле, и ни одна другая сцена его не
  убивает (урок четырёх выживших мутантов #1137 — сцена, не РАЗЛИЧАЮЩАЯ мутацию, её оправдывает);
* **населений ДВА, и складывать их нельзя:** вычисляющее (бегун вошёл в ТЕЛО и вышел за предел) и
  стенное (любой род, включая `NOT_ENTERED`). Сцена различающая: модуль, в чьё тело бегун не вошёл
  ни разу, а стенная цена его ввоза выше предела, обязан попасть ВО ВТОРОЕ и не попасть в первое;
* **`NOT_ENTERED` — СВОЙ исход, а не «внутри предела» и не «не измерено»:** длительность у него
  как раз измерена, а вычисления не было вовсе. Сложи его с `UNDER_LIMIT` — и прибор объявил бы
  вычисляющим модуль, не исполнивший ни строки своего тела;
* **три исхода различимы** (инв. #17) у КАЖДОГО уровня: у модуля · у населения · у контроля оси.
  «Проходов 1» — НЕ ИЗМЕРЕНО с причиной, а не нуль; нуль по мере, не способной увидеть предмет,
  читался бы как утверждение о системе;
* **население печатается ТОЛЬКО над живым контролем оси** — тот же несущий порядок, что у
  `INVARIANT` (ADR-1011 § 4): «класс пуст» и «мера не видит класса» дают ОДНО наблюдение;
* **ряд собирает ЕДИНСТВЕННАЯ дверь наблюдения** (`_observer_run`), и слово «не вошёл» берётся у
  соседа (`UNENTERED_CAUSE_STATUS`), а не второй копией в этом же файле;
* **печать вырезает свой предмет по ЗАГОЛОВКУ строки**, а не подстрокой по всему тексту.

Один прогон СКВОЗНОЙ: настоящая дверь наблюдения, настоящий подпроцесс, настоящие сны и
настоящая гонка потока таймаута — на одноразовом НЕ-git дереве с миниатюрным бегуном.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
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


rrwc = _load(CENSUS_PATH, "rrwc_duration_population")

_OVER, _NEAR, _UNDER, _NOT_ENTERED, _UNMEASURED = rrwc.DURATION_VERDICTS
_SEPARATES, _BLIND, _CTL_UNMEASURED = rrwc.DURATION_CONTROL_VERDICTS

#: Слово предела у подставного бегуна сцены. Прибор читает его СТАТИЧЕСКИ (AST), поэтому
#: подставной бегун для статического вопроса не исполняется ни разу.
TIMEOUT_WORD = "timeout"
#: Предел сцен с подставной дверью. Литерал здесь безвреден: дверь не считает, а ОБЪЯВЛЯЕТ
#: длительности, и вопрос сцены — как прибор их СУДИТ.
LIMIT = 1.0
#: Пол запаса сцены — следствие объявления прибора, а не литерал «на глаз».
FLOOR = LIMIT / rrwc.MARGIN_FLOOR_X

#: Миниатюрный бегун для СКВОЗНОГО прогона. Он не копия боевого, и это сказано вслух: сцена
#: отвечает на вопрос «различает ли ПРИБОР ряд проходов», а не «как устроен боевой бегун» (на
#: второй отвечает ADR-1015 своей сценой). Нужное от бегуна здесь ровно три вещи — он зовёт
#: модуль, он ограничивает зов пределом и он записывает своё слово предела.
MINI_RUNNER = '''
import importlib, threading

MODULE_TIMEOUT = 3.0

DEFAULT_PROTOCOLS = ["p_one"]


class FuturesTimeout(Exception):
    pass


def _run_bounded(fn, timeout, label=""):
    box = {}
    done = threading.Event()

    def _runner():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["exc"] = exc
        finally:
            done.set()

    threading.Thread(target=_runner, daemon=True).start()
    if not done.wait(timeout):
        raise FuturesTimeout("module exceeded %ss" % timeout)
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


class SignalAggregator:
    def __init__(self, data_dir=None, module_timeout=MODULE_TIMEOUT):
        self.data_dir = data_dir
        self.module_timeout = module_timeout
        self._log = []

    def _record(self, module, status, detail=""):
        self._log.append({"module": module, "status": status, "detail": detail})

    def _run_module(self, info, protocol, context):
        mod = importlib.import_module("spa_core.analytics." + info["module"])
        fn = getattr(mod, "analyze", None)
        if fn is None:
            self._record(info["module"], "unchecked", "no context-accepting entrypoint")
            return None, False
        try:
            score = _run_bounded(lambda: fn(context), self.module_timeout, info["module"])
        except FuturesTimeout:
            self._record(info["module"], "timeout")
            return None, False
        except Exception as exc:
            self._record(info["module"], "failed", "%s: %s" % (type(exc).__name__, exc))
            return None, False
        self._record(info["module"], "ok")
        return score, True
'''

MINI_REGISTRY = '''
TIER_A_MODULES = [{"module": "m_one", "tier": "A"}]
'''


def _mini_tree(root: Path) -> Path:
    """Одноразовое НЕ-git дерево. `.git` в нём нет НАМЕРЕННО: дверь наблюдения отказывает в
    git-дереве и в прод-дереве, и это её собственный гейт, а не особенность сцены."""
    pkg = root / "spa_core" / "analytics"
    pkg.mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "signal_aggregator.py").write_text(MINI_RUNNER, encoding="utf-8")
    (pkg / "_module_registry.py").write_text(MINI_REGISTRY, encoding="utf-8")
    (root / "data").mkdir()
    return root


def _row(module: str, status: str, seconds: float, *, pass_i: int = 0, call=None) -> dict:
    return {"module": module, "status": status, "detail": "", "pass": pass_i,
            "seconds": seconds, "seconds_call": seconds if call is None else call,
            "lines": [], "written": {}}


def _door(rows_by_module, *, passes=2, series=None, reported_passes=None):
    """Подставная дверь наблюдения: ОБЪЯВЛЯЕТ ряд, который прибор обязан СУДИТЬ.

    Дверь инъектируется, а не подменяется атрибутом модуля, по той же причине, по которой в
    этом проекте инъектируются часы и живость процесса: иначе сцена судила бы о живой машине.
    Число зовов двери считается — без него «прибор не позвал наблюдателя» и «прибор позвал и
    отбросил ответ» неразличимы.
    """
    calls = []

    def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None,
             passes=passes):
        calls.append({"entries": [e.get("module") for e in entries], "timeout": timeout,
                      "passes": passes, "seed": seed})
        if series is not None:
            rows = list(series)
        else:
            rows = []
            for name, per_pass in rows_by_module.items():
                for i, (status, sec) in enumerate(per_pass):
                    rows.append(_row(name, status, sec, pass_i=i))
        return {"results": [r for r in rows if r.get("pass") == 0], "series": rows,
                "passes": passes if reported_passes is None else reported_passes,
                "elsewhere": [], "observer_returncode": 0, "observer_stderr_tail": ""}

    door.calls = calls
    return door


class _SceneBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rrwc_dur_")
        self.addCleanup(self._tmp.cleanup)
        self.root = _mini_tree(Path(self._tmp.name) / "tree")

    def _pop(self, door, *, passes=2, entries=None, **kw):
        return rrwc.duration_population(
            self.root, protocol="p_one", timeout=LIMIT, passes=passes,
            observe_door=door,
            entries=entries if entries is not None else [{"module": "m_one"}], **kw)


class TheVerdictIsTakenOverTheWholeSeries(_SceneBase):
    """«Хотя бы ИНОГДА» — то есть по МАКСИМУМУ ряда, а не по первой строке."""

    def test_a_module_over_the_limit_in_ONE_pass_of_two_is_the_subject(self):
        pop = self._pop(_door({"m_one": [("ok", 0.01), (TIMEOUT_WORD, LIMIT)]}))
        self.assertIsNone(pop["unmeasured_reason"], pop)
        self.assertEqual(pop["counts"][_OVER], 1, pop)
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _OVER)
        self.assertEqual(v["over_passes"], [1])
        # Слово предела означает, что модуль продолжает работать в своём потоке: наблюдённая
        # длительность есть НИЖНЯЯ граница настоящей, и род числа объявлен ЗНАЧЕНИЕМ.
        self.assertEqual(v["kind"], rrwc.MARGIN_KIND_LOWER_BOUND)

    def test_ONE_pass_would_have_called_the_SAME_module_clean(self):
        """Различающая сцена оси: тот же ряд, прочитанный первым проходом, даёт ДРУГОЙ вердикт.
        Мутант «судить по `series[0]`» выживает везде, кроме здесь."""
        pop = self._pop(_door({"m_one": [("ok", 0.01), (TIMEOUT_WORD, LIMIT)]}))
        self.assertEqual(pop["one_pass"]["m_one"], _UNDER, pop)
        self.assertEqual(pop["one_pass_disagrees"], 1)
        self.assertEqual(pop["disagreeing_modules"], ["m_one"])

    def test_over_the_limit_BY_DURATION_without_the_runners_word(self):
        """Вторая независимая половина «вышел за предел»: статус `ok`, а длительность выше
        предела. Убери сравнение чисел — и модуль, которого предел НЕ укусил (ровно дефект
        ADR-1015!), стал бы невидим."""
        pop = self._pop(_door({"m_one": [("ok", LIMIT + 0.5), ("ok", 0.01)]}))
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _OVER, pop)
        self.assertEqual(v["over_passes"], [0])
        self.assertIsNone(v["kind"], "слова предела не было — нижней границей это не является")

    def test_a_series_entirely_below_the_margin_floor_is_UNDER(self):
        pop = self._pop(_door({"m_one": [("ok", FLOOR / 2), ("ok", FLOOR / 3)]}))
        self.assertEqual(pop["per_module"][0]["verdict"], _UNDER, pop)
        self.assertEqual(pop["counts"][_NEAR], 0)
        self.assertEqual(pop["counts"][_OVER], 0)

    def test_EXACTLY_at_the_margin_floor_is_already_NEAR_not_under(self):
        """Пол запаса включающий: «запас РАВЕН полу» есть «запас не БОЛЬШЕ пола», и строгое
        сравнение пропустило бы ровно ту границу, ради которой пол объявлен."""
        pop = self._pop(_door({"m_one": [("ok", FLOOR), ("ok", 0.001)]}))
        self.assertEqual(pop["per_module"][0]["verdict"], _NEAR, pop)

    def test_between_the_floor_and_the_limit_is_NEAR_with_a_NAMED_reason(self):
        pop = self._pop(_door({"m_one": [("ok", FLOOR * 1.5), ("ok", 0.01)]}))
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _NEAR, pop)
        self.assertIn(str(rrwc.MARGIN_FLOOR_X).rstrip("0").rstrip("."), v["reason"])
        self.assertEqual(pop["near_population"], 1)
        self.assertEqual(pop["computing_population"], 0,
                         "у предела ≠ за пределом: сложить их значило бы назвать населением то, "
                         "чего замер не видел")


class NotEnteredIsItsOwnOutcome(_SceneBase):
    """`NOT_ENTERED` не сливается ни с «внутри предела», ни с «не измерено»."""

    def test_a_module_the_runner_never_entered_is_NOT_counted_as_computing(self):
        pop = self._pop(_door({"m_one": [(rrwc.DURATION_NOT_ENTERED_STATUS, LIMIT + 2.0),
                                         (rrwc.DURATION_NOT_ENTERED_STATUS, LIMIT + 2.0)]}))
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _NOT_ENTERED, pop)
        self.assertEqual(v["entered_n"], 0)
        self.assertEqual(pop["computing_population"], 0,
                         "вычисления не было — считать его вычисляющим значило бы ответить на "
                         "другой вопрос")
        # ...но стенную цену бегун заплатил, и она НЕ ТЕРЯЕТСЯ.
        self.assertEqual(pop["wall_over_limit_n"], 1, pop)
        self.assertEqual(pop["wall_over_limit"], ["m_one"])
        self.assertIsNotNone(v["wall_max_s"])

    def test_the_two_populations_are_DIFFERENT_numbers_on_the_same_run(self):
        """Различающая сцена для «сложить два населения»: один модуль вычисляет за пределом,
        второй за пределом только стенно, ТРЕТИЙ не выходит вовсе. Сложи первые два — и ответ
        «кого чинить» вырос бы вдвое; посчитай стенное население по ВСЕМУ ряду — и в него попал
        бы третий (мутант M07 выжил ровно на двухмодульной сцене, где «двое» и «все» совпадали)."""
        pop = self._pop(_door({
            "computing": [("ok", LIMIT + 0.2), ("ok", 0.01)],
            "importing": [(rrwc.DURATION_NOT_ENTERED_STATUS, LIMIT + 0.2),
                          (rrwc.DURATION_NOT_ENTERED_STATUS, LIMIT + 0.2)],
            "quiet": [("ok", 0.001), ("ok", 0.001)]}))
        self.assertEqual(pop["modules"], 3, pop)
        self.assertEqual(pop["computing_population"], 1, pop)
        self.assertEqual(pop["wall_over_limit_n"], 2, pop)
        self.assertEqual(pop["wall_over_limit"], ["computing", "importing"], pop)

    def test_a_MIXED_series_is_unmeasured_not_a_maximum_over_the_half(self):
        """Вошёл в одном проходе, не вошёл в другом ⇒ ряд разнороден. Максимума у него не
        бывает, а выбор удобной половины подделал бы род числа (инв. #17)."""
        pop = self._pop(_door({"m_one": [("ok", 0.01),
                                         (rrwc.DURATION_NOT_ENTERED_STATUS, 0.5)]}))
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _UNMEASURED, pop)
        self.assertIn("СМЕШАН", v["reason"])
        self.assertEqual(v["entered_n"], 1)
        self.assertEqual(len(pop["unmeasured_modules"]), 1)


class ThirdOutcomeAtEveryLevel(_SceneBase):
    """НЕ ИЗМЕРЕНО с НАЗВАННОЙ причиной — у модуля, у населения и у входа."""

    def test_one_pass_is_unmeasured_and_the_observer_is_NOT_called_at_all(self):
        door = _door({"m_one": [("ok", 0.01)]})
        pop = self._pop(door, passes=1)
        self.assertIsNotNone(pop["unmeasured_reason"])
        self.assertIn(str(rrwc.DURATION_MIN_PASSES), pop["unmeasured_reason"])
        self.assertIsNone(pop["computing_population"],
                          "нуль здесь читался бы как «класс пуст», то есть как ответ")
        self.assertEqual(door.calls, [], "проверка проходов обязана стоять ДО наблюдателя: "
                                         "платить за ряд, который не будет судим, незачем")

    def test_a_missing_pass_row_is_unmeasured_naming_WHICH_pass(self):
        rows = [_row("m_one", "ok", 0.01, pass_i=0)]
        pop = self._pop(_door({}, series=rows))
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _UNMEASURED, pop)
        self.assertIn("[1]", v["reason"])

    def test_a_non_numeric_stopwatch_is_unmeasured_not_zero(self):
        rows = [_row("m_one", "ok", 0.01, pass_i=0),
                _row("m_one", "ok", 0.01, pass_i=1, call=None)]
        rows[1]["seconds_call"] = "н/д"
        pop = self._pop(_door({}, series=rows))
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _UNMEASURED, pop)
        self.assertIn("нуля", v["reason"], "подстановка нуля сделала бы модуль бесплатным")

    def test_an_observer_crash_is_unmeasured_not_a_duration(self):
        pop = self._pop(_door({"m_one": [("ok", 0.01),
                                         (rrwc.OBSERVER_ERROR_STATUS, 0.0)]}))
        v = pop["per_module"][0]
        self.assertEqual(v["verdict"], _UNMEASURED, pop)
        self.assertIn("наблюдатель упал", v["reason"])

    def test_no_series_from_the_observer_is_unmeasured_not_a_read_of_results(self):
        def door(repo, entries, **kw):
            return {"results": [_row("m_one", "ok", 0.01)], "series": None, "passes": None,
                    "elsewhere": [], "observer_returncode": 0, "observer_stderr_tail": ""}
        pop = self._pop(door)
        self.assertIn("РЯДА", pop["unmeasured_reason"] or "", pop)

    def test_a_series_of_the_WRONG_length_is_unmeasured(self):
        pop = self._pop(_door({"m_one": [("ok", 0.01), ("ok", 0.02)]}, reported_passes=5))
        self.assertIn("заказано", pop["unmeasured_reason"] or "", pop)

    def test_an_empty_registry_is_unmeasured_not_an_empty_population(self):
        pop = self._pop(_door({}), entries=[])
        self.assertIn("ноль записей", pop["unmeasured_reason"] or "", pop)
        self.assertIsNone(pop["computing_population"])

    def test_counts_account_for_EVERY_module_in_the_series(self):
        pop = self._pop(_door({
            "a": [("ok", LIMIT + 1), ("ok", 0.01)],
            "b": [("ok", FLOOR * 2), ("ok", 0.01)],
            "c": [("ok", 0.001), ("ok", 0.001)],
            "d": [(rrwc.DURATION_NOT_ENTERED_STATUS, 0.01),
                  (rrwc.DURATION_NOT_ENTERED_STATUS, 0.01)],
            "e": [("ok", 0.01), (rrwc.DURATION_NOT_ENTERED_STATUS, 0.01)]}))
        self.assertEqual(sum(pop["counts"].values()), pop["modules"], pop)
        self.assertEqual(pop["modules"], 5)
        self.assertEqual([pop["counts"][k] for k in rrwc.DURATION_VERDICTS], [1, 1, 1, 1, 1])


class TheControlOfThePassAxis(_SceneBase):
    """Население печатается только над ЖИВЫМ контролем: сцена обязана различать то, чего один
    проход не различает."""

    def test_the_REAL_door_separates_a_series_from_a_single_pass(self):
        """СКВОЗНОЙ прогон: настоящая дверь наблюдения, настоящий подпроцесс, настоящие сны."""
        ctl = rrwc.duration_population_control(self.root, timeout=0.5)
        self.assertEqual(ctl["verdict"], _SEPARATES, ctl)
        self.assertEqual(ctl["sides"]["over"]["verdict"], _OVER, ctl)
        self.assertEqual(ctl["sides"]["near"]["verdict"], _NEAR, ctl)
        self.assertEqual(ctl["sides"]["under"]["verdict"], _UNDER, ctl)
        self.assertEqual(ctl["sides"]["alternate"]["verdict"], _OVER, ctl)
        self.assertEqual(ctl["alternate_one_pass"], _UNDER, ctl)

    def test_a_control_whose_alternate_does_NOT_alternate_is_a_NAMED_finding(self):
        """Обратная сторона: ряд собран, а отличия от одного прохода нет ⇒ ось декоративна.
        Это НЕ «контроль прошёл» и НЕ «не измерено» — своя находка о ПРОВОДКЕ."""
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None,
                 passes=2):
            rows = []
            for e in entries:
                name = e["module"]
                if name.endswith("_over") or name.endswith("_alternate"):
                    per = [(TIMEOUT_WORD, timeout)] * passes      # «чередующийся» не чередуется
                elif name.endswith("_near"):
                    per = [("ok", timeout * rrwc.DUR_CTL_NEAR_X)] * passes
                else:
                    per = [("ok", timeout * rrwc.DUR_CTL_UNDER_X)] * passes
                for i, (st, sec) in enumerate(per):
                    rows.append(_row(name, st, sec, pass_i=i))
            return {"results": [r for r in rows if r["pass"] == 0], "series": rows,
                    "passes": passes, "elsewhere": [], "observer_returncode": 0,
                    "observer_stderr_tail": ""}
        ctl = rrwc.duration_population_control(self.root, timeout=LIMIT, observe_door=door)
        self.assertEqual(ctl["verdict"], _BLIND, ctl)
        self.assertIn("ничего не различает", ctl["blind_reason"])

    def test_a_side_that_does_not_reproduce_itself_makes_the_control_unmeasured(self):
        """Пока сцена не различает заведомо разные длительности, её ответ о населении ничего не
        стои́т: это третий исход с НАЗВАННОЙ стороной, а не вердикт."""
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None,
                 passes=2):
            rows = []
            for e in entries:                       # ВСЕ стороны отвечают одинаково
                for i in range(passes):
                    rows.append(_row(e["module"], "ok", timeout * rrwc.DUR_CTL_UNDER_X, pass_i=i))
            return {"results": [r for r in rows if r["pass"] == 0], "series": rows,
                    "passes": passes, "elsewhere": [], "observer_returncode": 0,
                    "observer_stderr_tail": ""}
        ctl = rrwc.duration_population_control(self.root, timeout=LIMIT, observe_door=door)
        self.assertEqual(ctl["verdict"], _CTL_UNMEASURED, ctl)
        self.assertIn("не воспроизвела", ctl["unmeasured_reason"])
        self.assertIn("`over`", ctl["unmeasured_reason"])

    def test_a_control_missing_a_side_is_unmeasured_not_a_verdict_over_the_rest(self):
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None,
                 passes=2):
            rows = []
            for e in entries[:-1]:                  # последней стороны в ответе нет вовсе
                for i in range(passes):
                    rows.append(_row(e["module"], "ok", 0.001, pass_i=i))
            return {"results": [r for r in rows if r["pass"] == 0], "series": rows,
                    "passes": passes, "elsewhere": [], "observer_returncode": 0,
                    "observer_stderr_tail": ""}
        ctl = rrwc.duration_population_control(self.root, timeout=LIMIT, observe_door=door)
        self.assertEqual(ctl["verdict"], _CTL_UNMEASURED, ctl)
        self.assertTrue(ctl["unmeasured_reason"])

    def test_the_declared_sides_are_ORDERED_by_construction(self):
        """Предпосылка сцены — объявление, а не удача: `under` ниже пола запаса, `near` между
        полом и пределом, `over` выше предела. Разъедься они — сцена перестала бы различать."""
        self.assertLess(rrwc.DUR_CTL_UNDER_X, 1.0 / rrwc.MARGIN_FLOOR_X)
        self.assertLessEqual(1.0 / rrwc.MARGIN_FLOOR_X, rrwc.DUR_CTL_NEAR_X)
        self.assertLess(rrwc.DUR_CTL_NEAR_X, 1.0)
        self.assertLess(1.0, rrwc.DUR_CTL_OVER_X)
        self.assertEqual(rrwc.DUR_CTL_PASSES, len(rrwc.DUR_CTL_ALTERNATE_X))
        self.assertGreaterEqual(rrwc.DUR_CTL_PASSES, rrwc.DURATION_MIN_PASSES)
        self.assertEqual(rrwc.DUR_CTL_ALTERNATE_X[0], rrwc.DUR_CTL_UNDER_X,
                         "первый проход чередующейся стороны обязан быть КОРОТКИМ: иначе один "
                         "проход ответил бы верно, и сцена перестала бы различать меру")

    def test_the_declared_default_timeout_leaves_room_for_the_observers_overhead(self):
        """Предел сцены не произволен: сторона `near` обязана остаться НИЖЕ предела даже с
        накладом СПЯЩЕГО модуля (0.129…0.149 с, замер ADR-1015), иначе сцена честно ответит
        «не измерено» — дороже и ни о чём."""
        overhead_s = 0.15
        t = rrwc.DUR_CTL_TIMEOUT_S
        self.assertLess(rrwc.DUR_CTL_NEAR_X * t + overhead_s, t)
        self.assertGreater(rrwc.DUR_CTL_NEAR_X * t, t / rrwc.MARGIN_FLOOR_X)

    def test_every_side_of_the_scene_is_BUSY_not_sleeping(self):
        """Замер #1141: брошенный поток спящей стороны, укушенной пределом, задерживает зов
        СЛЕДУЮЩЕЙ стороны (`near` со сном 0.1 с наблюдена 0.248 с — ровно до конца чужого сна).
        Вычисляющая сторона следа не оставляет: предел её не кусает, она дорабатывает сама."""
        self.assertEqual(rrwc.DUR_CTL_OCCUPANCY, "busy")


class OneDoorForEveryRule(_SceneBase):
    """Второе место для правила — тот же класс, против которого написан прибор."""

    def test_the_word_for_not_entered_is_taken_from_the_NEIGHBOUR_not_copied(self):
        self.assertEqual(rrwc.DURATION_NOT_ENTERED_STATUS, rrwc.UNENTERED_CAUSE_STATUS)

    def test_the_observers_own_error_word_is_in_PARITY_with_the_scene(self):
        """Слово `observer_error` живёт внутри `_OBSERVER`, а прибор судит по своей копии.
        Разъедься они — прибор перестал бы отличать «наблюдатель упал» от «модуль ответил»."""
        self.assertIn(f'"{rrwc.OBSERVER_ERROR_STATUS}"', rrwc._OBSERVER)

    def test_the_observer_unpacks_exactly_as_many_argv_as_the_door_passes(self):
        """Проходы уехали в наблюдателя ВОСЬМЫМ аргументом. Разъедься число аргументов с
        распаковкой — наблюдатель падал бы на `ValueError`, а причина читалась бы как «дерево
        не отдало результата»."""
        head = rrwc._OBSERVER.splitlines()
        unpack = [ln for ln in head if "sys.argv[" in ln]
        self.assertEqual(len(unpack), 1, unpack)
        self.assertIn("sys.argv[1:9]", unpack[0])
        self.assertEqual(len(unpack[0].split("=")[0].split(",")), 8, unpack[0])

    def test_results_keep_their_pre_ADR_1016_shape(self):
        """`results` читают соседние разборы (ADR-1006…1012) по имени модуля. Смена формы под
        ними означала бы, что перепись отвечает на чужие вопросы по-новому без спроса."""
        entries = [{"module": "_census_duration_population_control_under", "class": None,
                    "weight": 0.0, "category": "scene"}]
        seed = [{"module": entries[0]["module"], "sleep_s": 0.001, "kind": "sleep"}]
        ran = rrwc._observer_run(self.root, entries, protocol="p_one", timeout=1.0,
                                 seed=seed, passes=3, run_timeout=120.0)
        self.assertEqual(len(ran["results"]), 1, ran)
        self.assertNotIn("pass", ran["results"][0])
        self.assertEqual(ran["passes"], 3)
        self.assertEqual(len(ran["series"]), 3)
        self.assertEqual(sorted(r["pass"] for r in ran["series"]), [0, 1, 2])

    def test_an_unknown_seed_kind_is_REFUSED_by_the_observer(self):
        """Род занятости объявлен ЗНАЧЕНИЕМ (ADR-1015), и `alternate` его не ослабил."""
        entries = [{"module": "m_seed", "class": None, "weight": 0.0, "category": "scene"}]
        seed = [{"module": "m_seed", "sleep_s": 0.001, "kind": "нет-такого-рода"}]
        with self.assertRaises(rrwc.NotMeasured) as caught:
            rrwc._observer_run(self.root, entries, protocol="p_one", timeout=1.0,
                               seed=seed, passes=2, run_timeout=120.0)
        self.assertIn("не отдал результата", str(caught.exception))

    def test_an_alternate_seed_without_durations_is_REFUSED(self):
        entries = [{"module": "m_alt", "class": None, "weight": 0.0, "category": "scene"}]
        seed = [{"module": "m_alt", "kind": "alternate", "durations": [0.001]}]
        with self.assertRaises(rrwc.NotMeasured):
            rrwc._observer_run(self.root, entries, protocol="p_one", timeout=1.0,
                               seed=seed, passes=2, run_timeout=120.0)

    def test_an_alternate_seed_without_an_OCCUPANCY_is_REFUSED(self):
        """У `sleep` и `busy` ответ предела РАЗНЫЙ (ADR-1015 § 4), поэтому умолчания у рода
        занятости нет: подставить сон молча значило бы выбрать ответ за сцену."""
        entries = [{"module": "m_alt", "class": None, "weight": 0.0, "category": "scene"}]
        seed = [{"module": "m_alt", "kind": "alternate", "durations": [0.001, 0.002]}]
        with self.assertRaises(rrwc.NotMeasured):
            rrwc._observer_run(self.root, entries, protocol="p_one", timeout=1.0,
                               seed=seed, passes=2, run_timeout=120.0)


class ThePrintingCutsItsSubjectByTheHeader(_SceneBase):
    """Урок #1136: утверждение о печати обязано вырезать предмет ЗАГОЛОВКОМ строки, иначе
    мутант «печатать не то» выживает, потому что слова находятся в соседней строке."""

    @staticmethod
    def _line(lines, head):
        found = [ln for ln in lines if ln.strip().startswith(head)]
        assert len(found) == 1, (head, lines)
        return found[0]

    def test_population_is_WITHHELD_while_the_control_is_not_live(self):
        pop = self._pop(_door({"m_one": [("ok", 0.01), ("ok", 0.01)]}))
        lines = rrwc.render_duration_population(
            pop, {"verdict": _BLIND, "blind_reason": "ось декоративна", "sides": {}})
        self.assertIn("НЕ ИЗМЕРЕНО", self._line(lines, "население:"))
        self.assertIn("НЕ ИЗМЕРЕНО", self._line(lines, "стенное население:"))
        self.assertIn(_BLIND, self._line(lines, "контроль оси проходов:"))

    def test_both_populations_are_printed_over_a_live_control(self):
        pop = self._pop(_door({
            "a": [("ok", LIMIT + 1), ("ok", 0.01)],
            "d": [(rrwc.DURATION_NOT_ENTERED_STATUS, LIMIT + 1),
                  (rrwc.DURATION_NOT_ENTERED_STATUS, LIMIT + 1)]}))
        ctl = {"verdict": _SEPARATES, "alternate_one_pass": _UNDER,
               "sides": {"alternate": {"verdict": _OVER}}}
        lines = rrwc.render_duration_population(pop, ctl)
        self.assertIn("1 из 2", self._line(lines, "вычисляющее население"))
        self.assertIn("2", self._line(lines, "стенное население"))
        self.assertIn("ADVISORY", "\n".join(lines))

    def test_no_series_prints_a_NAMED_third_outcome_not_zeroes(self):
        lines = rrwc.render_duration_population(None, None)
        self.assertIn("НЕ ИЗМЕРЕНО", self._line(lines, "население:"))
        self.assertIn("НЕ ИЗМЕРЕН", self._line(lines, "контроль оси проходов:"))

    def test_the_count_a_single_pass_would_have_missed_is_printed(self):
        pop = self._pop(_door({"m_one": [("ok", 0.01), (TIMEOUT_WORD, LIMIT)]}))
        ctl = {"verdict": _SEPARATES, "alternate_one_pass": _UNDER,
               "sides": {"alternate": {"verdict": _OVER}}}
        lines = rrwc.render_duration_population(pop, ctl)
        self.assertIn("1 модулей", self._line(lines, "ОДИН проход сказал бы иначе"))


if __name__ == "__main__":
    unittest.main()
