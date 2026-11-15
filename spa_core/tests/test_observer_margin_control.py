"""Приёмка ADR-1015: предел и наклад мерятся НА ПУТИ НАБЛЮДЕНИЯ, и предел СЛЕП к занятому модулю.

Заказ G1004 п. 1 (а) = [ADR-1014](../../docs/decisions/ADR-1014-margin-is-a-condition-of-each-slice.md)
§ 7 (а). ADR-1014 назвал свою границу числом: в клетке `aave_v3@0.01` самый медленный модуль снят
**0.012 с при пределе клетки 0.01 с** и получил статус `ok`, а население клетки совпало с
населением при 3.0 с ПОБАЙТОВО. Два чтения, и заказ прямо велел различить их СЦЕНОЙ, а не
рассуждением:

1. наблюдённая длительность есть ВЕРХНЯЯ граница настоящей — в неё входят накладные наблюдателя,
   и настоящая длительность ниже предела (так и объявлено в `MARGIN_KIND_LOWER_BOUND`);
2. предел на ЭТОМ пути не кусает вовсе — и тогда «ни один модуль не подошёл к пределу» всё время
   было свойством ПРИБОРА, а не системы.

Замер #1137 ОПРОВЕРГ ОБА и нашёл ТРЕТЬЕ, которого заказ не называл: предел кусает СПЯЩИЙ модуль
надёжно, наклад у НЕ СПЯЩЕГО модуля равен нулю — а **занятый вычислением модуль предел не ловит
вовсе**, и статус выходит `ok` при длительности в разы выше предела. Реестр аналитики населён
именно вычисляющими модулями.

Что держит эта батарея — по одному утверждению на класс:

* **контроль идёт ЕДИНСТВЕННОЙ дверью наблюдения** (`_observer_run`). Своя копия зова означала бы,
  что контроль доказывает поведение пути, которым перепись не мерит — ровно тот класс, против
  которого написан весь прибор (`timeout_knob_control` ADR-1011 закрыть его не мог ПО ПОСТРОЕНИЮ:
  он зовёт `_run_module` своим коротким сценарием, без трассировки и без корзин);
* **три исхода вердикта различимы** (инв. #17): предел кусает · предел МЁРТВ (находка о
  проводке) · НЕ ИЗМЕРЕНО с НАЗВАННОЙ причиной. Ни один не сливается с другим;
* **наклад НЕ ИЗМЕРЕН — тоже третий исход, а не нуль:** нуль читался бы как «наблюдатель
  бесплатен», то есть как утверждение о системе;
* **род занятости объявлен ЗНАЧЕНИЕМ** (`kind`), и неизвестный род — отказ, а не молчаливая
  подстановка сна. «Спит» и «считает» — разные вопросы к пределу, и ответ у них разный;
* **ответ о занятом модуле есть ДОЛЯ, а не одно наблюдение:** исход не детерминирован, и одна
  строка дала бы монетку вместо замера. Неполный ряд ⇒ НЕ ИЗМЕРЕНО, а не доля по остатку;
* **печать вырезает свой предмет по ЗАГОЛОВКУ строки**, а не подстрокой по всему тексту (урок
  #1136: мутант «печатать не то» выживает, потому что слова находятся в соседней строке).

Контроль у каждого утверждения — в ОБЕ стороны, и один прогон СКВОЗНОЙ: настоящий бегун
одноразового дерева, настоящий наблюдатель, настоящая гонка за GIL.
"""
from __future__ import annotations

import importlib.util
import shutil
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


rrwc = _load(CENSUS_PATH, "rrwc_observer_margin")

_BITES, _DEAD, _UNMEASURED = rrwc.OBSERVER_MARGIN_VERDICTS
_BZ_BITES, _BZ_BLIND, _BZ_UNMEASURED = rrwc.BUSY_LIMIT_VERDICTS

#: Величины сцены. Все они — СЛЕДСТВИЯ объявлений прибора, а не литералы «на глаз»:
#: `under < sleep < over` есть предпосылка самой сцены, и прибор её проверяет первым делом.
SLEEP = 0.30
UNDER = 0.01
OVER = 2.00
BUSY = 0.05
#: Слово предела у ПОДСТАВНОГО бегуна сцены. Прибор читает его СТАТИЧЕСКИ (AST), поэтому дерево
#: сцены не исполняется ни разу и может быть минимальным.
TIMEOUT_WORD = "timeout"

#: Минимальный бегун, у которого `read_runner_timeout_status` обязан прочитать своё слово.
#: Он НЕ ИСПОЛНЯЕТСЯ: вопрос статический, и подставной бегун нужен ровно для этого ответа.
STATIC_RUNNER = '''
MODULE_TIMEOUT = 3.0

DEFAULT_PROTOCOLS = ["p_one"]


class FuturesTimeout(Exception):
    pass


class SignalAggregator:
    def __init__(self, data_dir=None, module_timeout=MODULE_TIMEOUT):
        self.data_dir = data_dir
        self.module_timeout = module_timeout
        self._log = []

    def _record(self, module, status, detail=""):
        self._log.append({"module": module, "status": status, "detail": detail})

    def _run_module(self, info, protocol, context):
        try:
            raise FuturesTimeout("scene")
        except FuturesTimeout:
            self._record(info["module"], "timeout")
            return None, False
'''

STATIC_REGISTRY = '''
TIER_A_MODULES = [{"module": "m_one", "tier": "A"}]
'''


def _static_tree(root: Path) -> Path:
    """Одноразовое дерево, которого хватает ТОЛЬКО на статический вопрос о слове предела."""
    pkg = root / "spa_core" / "analytics"
    pkg.mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "signal_aggregator.py").write_text(STATIC_RUNNER, encoding="utf-8")
    (pkg / "_module_registry.py").write_text(STATIC_REGISTRY, encoding="utf-8")
    return root


def _row(module: str, status: str, seconds: float, seconds_call=None) -> dict:
    return {"module": module, "status": status, "detail": "",
            "seconds": seconds,
            "seconds_call": seconds if seconds_call is None else seconds_call,
            "lines": [], "written": {}}


def _plan_sides(*, busy_ok=0, sleep_bites=True, over_status="ok", over_seconds=SLEEP + 0.02,
                over_mixed=0, idle_seconds=0.0, idle_spread=(), drop_busy=0):
    """Подставная дверь наблюдения: сторона узнаётся по СНУ семени и роду занятости, а статус
    РЕШАЕТ ПРЕДЕЛ, который дверь получила.

    Предел — не декорация плана: измерь прибор занятый модуль пределом `over`, и физика сцены
    обязана ответить `ok` ЗАКОННО (2.0 с > 0.05 с), то есть вердикт стал бы ложной находкой.
    Дверь, не смотрящая на предел, такую мутацию пропускает (мутант M02 выжил именно так).

    Дверь инъектируется, а не подменяется атрибутом модуля, по той же причине, по которой в
    этом проекте инъектируются часы и живость процесса: иначе сцена судила бы о живой машине.
    """
    def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None):
        s0 = (seed or [{}])[0]
        kind, sl = s0.get("kind", "sleep"), float(s0.get("sleep_s", SLEEP))
        names = [e["module"] for e in entries]
        if kind == "busy":
            kept = names[:len(names) - drop_busy]
            if timeout > BUSY:                 # предел ВЫШЕ занятости — `ok` законен у всех
                rows = [_row(n, "ok", BUSY) for n in kept]
            else:
                rows = [_row(n, "ok" if i < busy_ok else TIMEOUT_WORD, BUSY)
                        for i, n in enumerate(kept)]
        elif sl == 0.0:
            spread = list(idle_spread) or [idle_seconds] * len(names)
            rows = [_row(n, "ok", spread[i % len(spread)]) for i, n in enumerate(names)]
        elif timeout < sl:
            rows = [_row(n, TIMEOUT_WORD if sleep_bites else "ok", timeout) for n in names]
        else:
            # `over_mixed` строк отвечают СЛОВОМ ПРЕДЕЛА, остальные — `over_status`. Смешанный
            # ряд и есть различающая сцена для «сторона судится по ЛЮБОЙ строке, а не по всем».
            rows = [_row(n, TIMEOUT_WORD if i < over_mixed else over_status, over_seconds)
                    for i, n in enumerate(names)]
        return {"results": rows, "elsewhere": [], "observer_returncode": 0,
                "observer_stderr_tail": ""}
    return door


class _SceneBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rrwc_obsm_")
        self.root = _static_tree(Path(self._tmp.name) / "tree")
        self.addCleanup(self._tmp.cleanup)

    def _ctl(self, door, **kw):
        kw.setdefault("sleep_s", SLEEP)
        kw.setdefault("under", UNDER)
        kw.setdefault("over", OVER)
        kw.setdefault("busy_s", BUSY)
        kw.setdefault("busy_repeats", 4)
        kw.setdefault("repeats", 3)
        return rrwc.observer_margin_control(self.root, observe_door=door, **kw)


class TheLimitBitesOnTheObservationPath(_SceneBase):
    """Чтение 2 ADR-1014 § 7а — и сцена, которая его различает."""

    def test_a_sleeping_module_above_the_limit_proves_the_limit_bites(self):
        ctl = self._ctl(_plan_sides())
        self.assertEqual(ctl["verdict"], _BITES, ctl)
        self.assertEqual(ctl["expected_status"], TIMEOUT_WORD)
        self.assertIsNone(ctl["dead_reason"])

    def test_the_SAME_scene_with_a_dead_limit_is_a_NAMED_finding_not_a_pass(self):
        """Положительный контроль в обратную сторону: ослабь проводку — и прибор обязан
        покраснеть НАЗВАННОЙ находкой, а не промолчать."""
        ctl = self._ctl(_plan_sides(sleep_bites=False))
        self.assertEqual(ctl["verdict"], _DEAD, ctl)
        self.assertIn(str(UNDER), ctl["dead_reason"])
        self.assertIn("не кусает", ctl["dead_reason"])
        self.assertIn("свойством ПРИБОРА", ctl["dead_reason"])

    def test_a_scene_that_does_not_DIFFER_is_unmeasured_not_a_verdict(self):
        """Обе стороны ответили словом предела ⇒ сцена различающей не стала. Это НЕ «предел
        кусает» и НЕ «предел мёртв»: третий исход с причиной (инв. #17)."""
        ctl = self._ctl(_plan_sides(over_status=TIMEOUT_WORD))
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("различающей", ctl["unmeasured_reason"])

    def test_ONE_timeout_row_on_the_over_side_already_breaks_the_scene(self):
        """Сторона судится по ЛЮБОЙ строке ряда, а не по всем: предел ВЫШЕ сна не должен
        звучать НИ РАЗУ, и «прозвучал у одной из трёх» есть неразличимая сцена, а не вердикт.
        Проверь прибор `all(...)` — и смешанный ряд прошёл бы как различающий (мутант M06)."""
        ctl = self._ctl(_plan_sides(over_mixed=1))
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("различающей", ctl["unmeasured_reason"])

    def test_the_busy_side_is_measured_AT_THE_LIMIT_BELOW_the_work(self):
        """Предел стороны занятости — `under`, и это утверждение о ПРОВОДКЕ: измерь прибор
        занятый модуль пределом `over`, и `ok` стал бы законным, а вердикт — ложной находкой."""
        ctl = self._ctl(_plan_sides())
        self.assertEqual(ctl["sides"]["busy_under_limit"]["timeout"], UNDER, ctl["sides"])
        self.assertGreater(ctl["busy_limit"]["over_x"], 1.0, ctl["busy_limit"])

    def test_the_scene_refuses_its_own_unplayable_premise(self):
        ctl = self._ctl(_plan_sides(), sleep_s=0.001)
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("неисполнима", ctl["unmeasured_reason"])

    def test_an_unread_limit_word_is_unmeasured_with_the_reason_named(self):
        """Дерево без слова предела: ответ НЕ ИЗМЕРЕН, и причина названа — не «предел мёртв»."""
        (self.root / "spa_core" / "analytics" / "signal_aggregator.py").write_text(
            "MODULE_TIMEOUT = 3.0\n", encoding="utf-8")
        ctl = self._ctl(_plan_sides())
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("слово предела", ctl["unmeasured_reason"])


class TheLimitIsBlindToABusyModule(_SceneBase):
    """ТРЕТЬЕ чтение, которого заказ не называл, и его три исхода."""

    def test_a_busy_module_recorded_ok_above_the_limit_is_the_finding(self):
        ctl = self._ctl(_plan_sides(busy_ok=4))
        self.assertEqual(ctl["busy_limit"]["verdict"], _BZ_BLIND, ctl["busy_limit"])
        self.assertEqual(ctl["busy_limit"]["ok_n"], 4)
        self.assertEqual(ctl["busy_limit"]["total_n"], 4)
        self.assertEqual(ctl["busy_limit"]["over_x"], round(BUSY / UNDER, 1))

    def test_ONE_ok_out_of_many_is_already_blind_because_the_outcome_is_a_RACE(self):
        """Исход не детерминирован: «в большинстве поймал» ответом не является, иначе прибор
        отвечал бы на вопрос «как сегодня повезло с GIL»."""
        ctl = self._ctl(_plan_sides(busy_ok=1))
        self.assertEqual(ctl["busy_limit"]["verdict"], _BZ_BLIND, ctl["busy_limit"])
        self.assertEqual(ctl["busy_limit"]["ok_n"], 1)

    def test_a_busy_module_caught_EVERY_time_is_the_other_side_of_the_control(self):
        ctl = self._ctl(_plan_sides(busy_ok=0))
        self.assertEqual(ctl["busy_limit"]["verdict"], _BZ_BITES, ctl["busy_limit"])
        self.assertEqual(ctl["busy_limit"]["ok_n"], 0)
        self.assertIsNone(ctl["busy_limit"]["unmeasured_reason"])

    def test_an_incomplete_series_is_unmeasured_not_a_proportion_of_the_remainder(self):
        """Недостающие строки ловит ОДИН сторож — полнота стороны, и он НАЗЫВАЕТ имена. Второй
        ответ на тот же вопрос дал бы два разных «не измерено» об одной причине (класс ADR-220),
        поэтому вердикт занятости остаётся умолчанием, а причина приходит от сторожа полноты."""
        ctl = self._ctl(_plan_sides(busy_ok=2, drop_busy=2))
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("не отдал строк", ctl["unmeasured_reason"])
        self.assertIn("busy_under_limit", ctl["unmeasured_reason"])
        self.assertEqual(ctl["busy_limit"]["verdict"], _BZ_UNMEASURED, ctl["busy_limit"])

    def test_an_EMPTY_series_is_unmeasured_and_not_bites_by_zero_observations(self):
        """Положительный контроль на подделку нулём: `busy_repeats=0` прошёл бы равенством
        `0 == 0` и объявил бы «предел кусает», не наблюдав НИ ОДНОГО повтора."""
        ctl = self._ctl(_plan_sides(), busy_repeats=0)
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("busy_under_limit", ctl["unmeasured_reason"])
        self.assertIn("доли не бывает", ctl["unmeasured_reason"])
        self.assertEqual(ctl["busy_limit"]["verdict"], _BZ_UNMEASURED, ctl["busy_limit"])

    def test_the_busy_verdict_survives_a_dead_sleep_limit(self):
        """Два вопроса — два вердикта: находка о занятом модуле не теряется из-за того, что
        сосед ушёл в `OBS_LIMIT_DEAD`. Иначе одна находка глотала бы другую."""
        ctl = self._ctl(_plan_sides(sleep_bites=False, busy_ok=4))
        self.assertEqual(ctl["verdict"], _DEAD)
        self.assertEqual(ctl["busy_limit"]["verdict"], _BZ_BLIND, ctl["busy_limit"])


class TheOverheadIsMeasuredNotDeclared(_SceneBase):
    """`MARGIN_KIND_LOWER_BOUND` объявлял наклад; здесь у него появляется ЧИСЛО."""

    def test_the_overhead_is_the_observed_minus_the_known_duration(self):
        ctl = self._ctl(_plan_sides(over_seconds=SLEEP + 0.05))
        self.assertEqual(ctl["verdict"], _BITES, ctl)
        self.assertAlmostEqual(ctl["overhead_s"], 0.05, places=3)
        self.assertEqual(ctl["overhead_kind"], rrwc.MARGIN_KIND_LOWER_BOUND)

    def test_a_negative_overhead_is_unmeasured_not_a_number(self):
        """Наблюдённое КОРОЧЕ заданного сна ⇒ сцена не обеспечила предпосылку. Отрицательный
        наклад был бы выдуманным числом, а нуль — утверждением «наблюдатель бесплатен»."""
        ctl = self._ctl(_plan_sides(over_seconds=SLEEP - 0.05))
        self.assertIsNone(ctl["overhead_s"])
        self.assertIn("КОРОЧЕ", ctl["overhead_kind"])

    def test_the_overhead_splits_into_the_call_and_the_bookkeeping(self):
        """Два слагаемых названы РАЗДЕЛЬНО: «модуль подорожал» и «наблюдатель подорожал» —
        разные находки, а причиной вердикта запаса объявлена первая."""
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None):
            s0 = (seed or [{}])[0]
            kind, sl = s0.get("kind", "sleep"), float(s0.get("sleep_s", SLEEP))
            names = [e["module"] for e in entries]
            if kind == "busy":
                rows = [_row(n, TIMEOUT_WORD, BUSY) for n in names]
            elif sl == 0.0:
                rows = [_row(n, "ok", 0.0) for n in names]
            elif timeout < sl:
                rows = [_row(n, TIMEOUT_WORD, timeout) for n in names]
            else:                      # наблюдено 0.40, из них зов 0.37, бухгалтерия 0.03
                rows = [_row(n, "ok", 0.40, seconds_call=0.37) for n in names]
            return {"results": rows, "elsewhere": [], "observer_returncode": 0,
                    "observer_stderr_tail": ""}
        ctl = self._ctl(door)
        sp = ctl["overhead_split"]
        self.assertAlmostEqual(sp["call_s"], 0.07, places=3)
        self.assertAlmostEqual(sp["bookkeeping_s"], 0.03, places=3)
        self.assertIsNone(sp["unmeasured_reason"])

    def test_the_overhead_of_a_NOT_SLEEPING_module_is_its_own_number(self):
        """Несущее число §7а: `ok` при длительности выше предела вправе объясняться накладом,
        снятым у НЕ СПЯЩЕГО модуля, — и только им. Наклад спящего относится к другому роду."""
        ctl = self._ctl(_plan_sides(idle_spread=(0.001, 0.004, 0.002)))
        # МАКСИМУМ, а не минимум: вопрос «сколько наблюдатель МОГ приписать модулю». Минимум
        # преуменьшил бы его вклад и тем самым подтвердил бы `ok` щедрее, чем позволяет замер.
        self.assertAlmostEqual(ctl["overhead_split"]["idle_s"], 0.004, places=4)
        self.assertEqual(ctl["overhead_split"]["idle_n"], 3)

    def test_a_missing_series_leaves_the_split_unmeasured_not_zero(self):
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None):
            s0 = (seed or [{}])[0]
            kind, sl = s0.get("kind", "sleep"), float(s0.get("sleep_s", SLEEP))
            names = [e["module"] for e in entries]
            if kind == "busy":
                rows = [_row(n, TIMEOUT_WORD, BUSY) for n in names]
            elif sl == 0.0:
                rows = [{**_row(n, "ok", 0.0), "seconds_call": None} for n in names]
            elif timeout < sl:
                rows = [_row(n, TIMEOUT_WORD, timeout) for n in names]
            else:
                rows = [_row(n, "ok", SLEEP + 0.02) for n in names]
            return {"results": rows, "elsewhere": [], "observer_returncode": 0,
                    "observer_stderr_tail": ""}
        ctl = self._ctl(door)
        self.assertIsNone(ctl["overhead_split"]["idle_s"])
        self.assertIn("НЕ ИЗМЕРЕНА", ctl["overhead_split"]["unmeasured_reason"])


class EachSideMustBeWholeAndNamed(_SceneBase):
    def test_a_side_missing_its_rows_is_unmeasured_with_the_names_printed(self):
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None):
            return {"results": [], "elsewhere": [], "observer_returncode": 3,
                    "observer_stderr_tail": "boom"}
        ctl = self._ctl(door)
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("не отдал строк", ctl["unmeasured_reason"])

    def test_a_non_numeric_stopwatch_is_unmeasured_not_zero(self):
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None):
            rows = [{**_row(n, "ok", 0.0), "seconds": None} for n in (e["module"] for e in entries)]
            return {"results": rows, "elsewhere": [], "observer_returncode": 0,
                    "observer_stderr_tail": ""}
        ctl = self._ctl(door)
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("бесплатным", ctl["unmeasured_reason"])

    def test_a_refusing_door_is_unmeasured_with_the_side_named(self):
        def door(repo, entries, *, protocol, timeout, python=None, seed=None, run_timeout=None):
            raise rrwc.NotMeasured("дерево под наблюдателем не годится")
        ctl = self._ctl(door)
        self.assertEqual(ctl["verdict"], _UNMEASURED, ctl)
        self.assertIn("limit_under_sleep", ctl["unmeasured_reason"])


class ThePrintCutsItsSubjectByTheLineHeader(_SceneBase):
    """Урок #1136: утверждение, ищущее подстроку по ВСЕЙ печати, отдаёт подтверждение даром."""

    @staticmethod
    def _line(lines, head):
        hits = [ln for ln in lines if ln.strip().startswith(head)]
        assert len(hits) == 1, f"строк с заголовком {head!r}: {len(hits)}"
        return hits[0]

    def test_every_declared_fact_has_its_own_line_header(self):
        lines = rrwc.render_observer_margin(self._ctl(_plan_sides(busy_ok=4, idle_seconds=0.004)))
        for head in ("укус предела:", "наклад наблюдателя:", "расклад наклада:",
                     "тёплый наклад:", "предел у ЗАНЯТОГО модуля:",
                     "наклад у НЕ СПЯЩЕГО модуля:"):
            self._line(lines, head)

    def test_the_busy_line_carries_the_finding_and_not_its_neighbour(self):
        blind = self._line(rrwc.render_observer_margin(
            self._ctl(_plan_sides(busy_ok=4))), "предел у ЗАНЯТОГО модуля:")
        bites = self._line(rrwc.render_observer_margin(
            self._ctl(_plan_sides(busy_ok=0))), "предел у ЗАНЯТОГО модуля:")
        self.assertIn(_BZ_BLIND, blind)
        self.assertIn(_BZ_BITES, bites)
        self.assertNotEqual(blind, bites)

    def test_no_scene_at_all_prints_UNMEASURED_on_every_line_not_zeros(self):
        lines = rrwc.render_observer_margin(None)
        self.assertTrue(all("НЕ ИЗМЕР" in ln for ln in lines[1:]), lines)


class TheControlGoesThroughTheONEObservationDoor(unittest.TestCase):
    """Своя копия зова наблюдателя означала бы контроль пути, которым никто не мерит."""

    def test_the_census_and_the_control_call_the_same_door(self):
        src = CENSUS_PATH.read_text(encoding="utf-8")
        import ast
        tree = ast.parse(src)
        calls = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            if fn.name not in ("observe", "observer_margin_control"):
                continue
            names = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    if isinstance(f, ast.Name):
                        names.add(f.id)
                    elif isinstance(f, ast.BoolOp):          # (observe_door or _observer_run)(…)
                        names.update(v.id for v in f.values if isinstance(v, ast.Name))
            calls[fn.name] = names
        self.assertIn("_observer_run", calls["observe"], calls)
        self.assertIn("_observer_run", calls["observer_margin_control"], calls)

    def test_the_observer_script_declares_the_kind_and_refuses_an_unknown_one(self):
        src = rrwc._OBSERVER
        self.assertIn('_MAKERS = {"sleep": _mk_sleep, "busy": _mk_busy}', src)
        self.assertIn("род занятости семени не объявлен", src)

    def test_the_observer_stops_its_stopwatch_twice_and_names_both(self):
        src = rrwc._OBSERVER
        self.assertIn('"seconds_call": t_call', src)
        self.assertLess(src.index("t_call = round"), src.index("after = {k: snap(v)"),
                        "`seconds_call` обязан быть снят ДО бухгалтерии наблюдателя")


class TheLiveRunnerIsAskedTheSameQuestion(unittest.TestCase):
    """СКВОЗНОЙ прогон: настоящий `spa_core` одноразового дерева, настоящий наблюдатель.

    Этот один прогон и есть положительный контроль всего решения: он единственный видел
    настоящую гонку за GIL, и именно он нашёл `BUSY_LIMIT_BLIND`. Проверка, никогда не видевшая
    настоящей поломки, — украшение (`.claude/rules/deployment.md`).
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="rrwc_obsm_live_")
        cls.root = Path(cls._tmp.name) / "tree"
        cls.root.mkdir()
        # Дерево БЕЗ `.git` и БЕЗ `data/` — иначе `_observer_run` откажет сам, и это верно.
        for rel in ("spa_core", "scripts"):
            shutil.copytree(ROOT / rel, cls.root / rel,
                            ignore=shutil.ignore_patterns("__pycache__", "data", ".git",
                                                          "*.pyc", "tests"))
        cls.reason = None
        try:
            cls.ctl = rrwc.observer_margin_control(
                cls.root, sleep_s=0.20, under=0.005, over=1.0, busy_s=0.05,
                busy_repeats=3, repeats=2)
        except Exception as exc:                                    # noqa: BLE001
            cls.ctl, cls.reason = None, f"{type(exc).__name__}: {exc}"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        if self.ctl is None:
            # Предпосылка не обеспечена — падать ГРОМКО, а не скипать: скип сделал бы
            # «не измерено» неотличимым от «прошло» (урок #465).
            self.fail(f"сквозная сцена не отработала: {self.reason}")

    def test_the_limit_bites_a_sleeping_module_on_the_REAL_path(self):
        self.assertEqual(self.ctl["verdict"], _BITES, self.ctl)

    def test_the_observer_costs_nothing_at_a_module_that_does_not_sleep(self):
        """Чтение 1 ADR-1014 § 7а ОПРОВЕРГНУТО замером: накладу, которым объясняли `ok` при
        0.012 с против предела 0.01 с, взяться НЕГДЕ."""
        split = self.ctl["overhead_split"]
        idle = split["idle_s"]
        self.assertIsNotNone(idle, split)
        self.assertLess(float(idle), 0.005, split)

    def test_the_bookkeeping_is_NOT_what_inflates_the_observed_duration(self):
        """Вторая опровергнутая догадка: снимок дерева ПОСЛЕ зова почти бесплатен."""
        self.assertLess(self.ctl["overhead_split"]["bookkeeping_s"], 0.02, self.ctl)

    def test_the_REAL_runner_is_blind_to_a_busy_module(self):
        """Находка, о которой заказ не спрашивал, и она про ПРОД-бегуна, а не про прибор."""
        bz = self.ctl["busy_limit"]
        self.assertEqual(bz["verdict"], _BZ_BLIND, bz)
        self.assertGreater(bz["ok_n"], 0, bz)
        self.assertGreaterEqual(bz["over_x"], 10.0, bz)


if __name__ == "__main__":
    unittest.main(verbosity=2)
