"""Приёмка ADR-1019: предел модуля судится ЧАСАМИ, а не ответом примитива.

Предмет — карточка `inbox-predel-modulya-analitiki-slep-k-vychisly` п. 3 и заказ
G1007 п. 1. Правка `_run_bounded` закрывает две ИЗМЕРЕННЫЕ (#1142, ADR-1017) дыры:

1. **исход судился вердиктом ожидания.** `lock.acquire(True, срок)` у занятого
   вычислением соседа возвращает «взял» многократно позже срока (худшее — 38.6×):
   примитив докладывает об успехе, не сверившись со своим сроком, и превышение
   предела в 50 раз выходило из функции как `ok` (замер #1137: `ok` 18 из 20);
2. **отсчёт начинался ПОСЛЕ `Thread.start()`**, а `start()` у занятого ребёнка
   держит главный поток почти всё время его работы (0.0054…0.0451 с при работе
   0.0500 с). Бюджет был `start() + timeout`, а не `timeout`.

ПОЧЕМУ примитив пересиживает срок — НЕ ИЗМЕРЕНО (ADR-1017), и батарея на это не
опирается НИ ОДНИМ утверждением.

─── Главное про форму этих контролей (урок ADR-1018) ───

Прошлая батарея того же предмета закрепила вердикт за ХОЗЯИНОМ: она утверждала
«настоящий бегун СЛЕП», и это было верно на Маке (3.13) и ложно на CI (3.11),
где примитив срок соблюдает. Красный по известной причине перестаёт быть
сигналом. Поэтому здесь **ложь примитива и цена `start()` сделаны ВХОДАМИ
СЦЕНЫ**, а не свойствами машины:

* `_LyingEvent` воспроизводит ИЗМЕРЕННОЕ поведение — «взял» после срока. Это не
  выдумка: ровно это снял прибор `bounded_countdown_probe.py` (ADR-1017);
* `_SlowStartThread` делает цену `start()` детерминированной;
* ребёнок в этих сценах НЕ ВЫЧИСЛЯЕТ: GIL из вопроса убран намеренно — его
  участие и есть то, что делало ответ свойством хозяина. Больше того, ни один
  исход не стои́т на длительности ребёнка: пересидка примитива задана СОБЫТИЕМ
  (он сидит до конца работы), а в сцене бюджета ребёнок МГНОВЕННЫЙ и различает
  исходы цена самого `start()`. Зазоров, зависящих от загрузки, здесь нет —
  первая редакция этой батареи их имела и давала 2 ложных падения из 24.

Благодаря этому каждое утверждение ниже одинаково на 3.11 и 3.13 ПО ПОСТРОЕНИЮ,
а не по совпадению. Отдельно (`TheRealDoorOnTheRealHost`) проверяется настоящая
дверь без шимов — но там утверждается только то, что верно на ЛЮБОМ хозяине:
модуль, превысивший предел, получает `timeout`.
"""
from __future__ import annotations

import threading
import time
import types
import unittest
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Dict

from spa_core.analytics import signal_aggregator as sa
from spa_core.monitoring import card_acceptance as ca

#: Величины сцен. `under < limit < work` и `work + start > limit > work` —
#: предпосылки, которые сцены проверяют сами, а не держат на вкусе автора.
LIMIT = 0.01
WORK = 0.05
PROBE_LIMIT = 0.001     # предел сцены ПРОБЫ: запас 50×, первая строка замера #1137
#: Потолок пересидки примитива. Это НЕ зазор сцены: `_LyingEvent` сидит до конца
#: работы ребёнка, а не фиксированный срок (см. его строку документации). Потолок
#: нужен ровно затем, чтобы сцена не висела вечно, если ребёнок не кончится.
OVERSIT_CAP = 10.0
#: Сцена БЮДЖЕТА (половина 2). Различает исходы цена САМОГО `start()`, а не
#: работа ребёнка: ребёнок здесь МГНОВЕННЫЙ, поэтому ни один зазор не зависит от
#: того, успеет ли он поспать под нагрузкой (замер #1144: сцена со спящим
#: ребёнком давала 'timeout' вместо 'ok' в 2 прогонах из 24 — то есть отвечала
#: о загрузке машины, а не о месте дедлайна).
START_COST = 0.50       # детерминированная цена самого `Thread.start()`
HALF2_LIMIT = 0.20      # предпосылки: work < limit < start + work
HALF2_WORK = 0.0        # мгновенный ребёнок: работа из вопроса убрана


class _LyingEvent:
    """Примитив, ВОСПРОИЗВОДЯЩИЙ измеренную ложь: докладывает состояние ПОСЛЕ срока.

    Это и есть механизм ADR-1017 в виде входа сцены: зов ожидания возвращается
    многократно позже срока и отвечает «взял», потому что к моменту позднего
    возврата событие уже установлено. Со СРОКОМ примитив при этом не сверяется —
    `timeout` здесь не используется вовсе, и это дословно то, что было снято.

    **Пересидка задана СОБЫТИЕМ, а не длительностью** (правка #1144 по своему же
    замеру). Прежняя редакция спала фиксированные 0.08 с и надеялась, что ребёнок
    за это время успеет: при работе ребёнка 0.05 с зазор был 1.6×, и под нагрузкой
    он не выдерживал — 2 прогона из 24 давали `timeout` там, где сцена требовала
    `ok`, то есть контроль отвечал о загрузке хоста. Теперь примитив сидит ДО
    конца работы ребёнка и возвращается после — ровно то свойство, которое
    воспроизводится, и ни одного зазора. Потолок `OVERSIT_CAP` существует только
    затем, чтобы сцена не висела вечно: его срабатывание означает, что ребёнок не
    кончился, и тогда `is_set()` честно отдаст `False`.
    """

    def __init__(self, oversit_cap_s: float = OVERSIT_CAP) -> None:
        self._ev = threading.Event()
        self._cap = oversit_cap_s
        self.waits: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        self._ev.wait(self._cap)         # пересиживаем срок — ждём БЕЗ его учёта…
        return self._ev.is_set()         # …и докладываем состояние, не сверяясь с ним

    def set(self) -> None:
        self._ev.set()

    def is_set(self) -> bool:
        return self._ev.is_set()


class _SlowStartThread(threading.Thread):
    """`Thread`, у которого САМ `start()` стои́т известных денег."""

    def start(self) -> None:
        time.sleep(START_COST)
        super().start()


def _shim(*, event_factory=threading.Event, thread_cls=threading.Thread):
    """Накладка на ЕДИНСТВЕННУЮ дверь бегуна к потокам и событиям."""
    return types.SimpleNamespace(Thread=thread_cls, Event=event_factory)


class _patched_threading:
    """Подменяет `signal_aggregator.threading` на время сцены (и возвращает)."""

    def __init__(self, shim) -> None:
        self._shim = shim
        self._saved = None

    def __enter__(self):
        self._saved = sa.threading
        sa.threading = self._shim          # type: ignore[assignment]
        return self._shim

    def __exit__(self, *exc) -> None:
        sa.threading = self._saved         # type: ignore[assignment]


# ─── Редакции бегуна: ДО починки и каждая ПОЛОВИНА по отдельности ─────────────
#
# Все три берут потоки и события из `sa.threading`, то есть видят ту же накладку,
# что и настоящая дверь. Единственное, чем они отличаются от неё, — МЕСТО
# дедлайна и ЧЕМ судится исход; значит контроль сравнивает именно это.

def _runner_pre_fix(fn, timeout: float, label: str = ""):
    """ДОСЛОВНОЕ тело до ADR-1019: исход судится ВЕРДИКТОМ ожидания."""
    box: Dict[str, Any] = {}
    done = sa.threading.Event()

    def _runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc
        finally:
            done.set()

    sa.threading.Thread(target=_runner, name=f"pre-fix:{label}"[:60], daemon=True).start()
    if not done.wait(timeout):
        raise FuturesTimeout(f"module exceeded {timeout}s")
    exc = box.get("exc")
    if exc is not None:
        raise exc
    return box.get("value")


def _runner_half1_missing(fn, timeout: float, label: str = ""):
    """Дедлайн на месте (ДО `start()`), но исход судится СОСТОЯНИЕМ, не часами."""
    box: Dict[str, Any] = {}
    done = sa.threading.Event()

    def _runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc
        finally:
            done.set()

    deadline = time.monotonic() + timeout
    sa.threading.Thread(target=_runner, name=f"half1:{label}"[:60], daemon=True).start()
    remaining = deadline - time.monotonic()
    done.wait(remaining if remaining > 0.0 else 0.0)
    if not done.is_set():                 # ← часов тут нет: пересиженный срок пройдёт
        raise FuturesTimeout(f"module exceeded {timeout}s")
    exc = box.get("exc")
    if exc is not None:
        raise exc
    return box.get("value")


def _runner_half2_missing(fn, timeout: float, label: str = ""):
    """Исход судится часами, но дедлайн берётся ПОСЛЕ `start()` — бюджет раздут."""
    box: Dict[str, Any] = {}
    done = sa.threading.Event()

    def _runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc
        finally:
            done.set()

    sa.threading.Thread(target=_runner, name=f"half2:{label}"[:60], daemon=True).start()
    deadline = time.monotonic() + timeout          # ← цена `start()` НЕ списана
    remaining = deadline - time.monotonic()
    done.wait(remaining if remaining > 0.0 else 0.0)
    if not done.is_set() or time.monotonic() > deadline:
        raise FuturesTimeout(f"module exceeded {timeout}s")
    exc = box.get("exc")
    if exc is not None:
        raise exc
    return box.get("value")


def _outcome(call, fn, timeout: float) -> str:
    """`ok` · `timeout` · имя постороннего исключения. Третий исход не молчит."""
    try:
        call(fn, timeout, "scene")
        return "ok"
    except FuturesTimeout:
        return "timeout"
    except BaseException as exc:  # noqa: BLE001
        return f"{type(exc).__name__}"


class TheLyingPrimitiveIsAnInputNotAHostProperty(unittest.TestCase):
    """Нулевая проба: НАСТОЯЩАЯ авария, воспроизведённая её ИЗМЕРЕННЫМ механизмом."""

    def test_the_scene_premise_holds_the_primitive_really_oversits(self):
        """Предпосылка сцены ИЗМЕРЯЕТСЯ: пересидка обязана быть выше предела."""
        ev = _LyingEvent()
        started = time.monotonic()
        ev.wait(LIMIT)
        sat = time.monotonic() - started
        self.assertGreater(sat, LIMIT,
                           f"сцена не воспроизводит пересидку: {sat:.4f} с при пределе {LIMIT} с")
        self.assertEqual(ev.waits, [LIMIT], "срок до примитива не доехал — сцена не та")

    def test_the_pre_fix_runner_calls_an_over_the_deadline_module_ok(self):
        """Авария: модуль превысил предел в 5 раз и вышел как «уложился».

        Контроль НЕ ИСЧЕЗАЕТ при неудаче (урок #465) — он падает ГРОМКО: батарея,
        чья авария не воспроизводится, ничего не держит.
        """
        with _patched_threading(_shim(event_factory=_LyingEvent)):
            got = _outcome(_runner_pre_fix, lambda: time.sleep(WORK), LIMIT)
        self.assertEqual(got, "ok",
                         "авария НЕ воспроизвелась: редакция до починки обязана была "
                         f"выпустить превышение предела как «уложился», а дала {got!r}")

    def test_the_fixed_door_refuses_the_same_scene(self):
        """Та же сцена, та же ложь примитива — настоящая дверь отвечает `timeout`."""
        with _patched_threading(_shim(event_factory=_LyingEvent)):
            got = _outcome(sa._run_bounded, lambda: time.sleep(WORK), LIMIT)
        self.assertEqual(got, "timeout",
                         "дверь поверила примитиву: он доложил «взял» после срока, и "
                         f"превышение вышло как {got!r}")

    def test_the_two_editions_DISAGREE_on_this_scene(self):
        """Различающая сцена обязана заставить ОБЕ редакции утверждать (урок #1143 п. 27б)."""
        with _patched_threading(_shim(event_factory=_LyingEvent)):
            pre = _outcome(_runner_pre_fix, lambda: time.sleep(WORK), LIMIT)
            fixed = _outcome(sa._run_bounded, lambda: time.sleep(WORK), LIMIT)
        self.assertEqual((pre, fixed), ("ok", "timeout"),
                         f"сцена не различает редакции: до={pre!r}, после={fixed!r}")


class EachHalfOfTheFixIsLoadBearing(unittest.TestCase):
    """Половина правки — половина починки. Контроль у КАЖДОЙ половины свой."""

    def test_half_one_without_the_clock_lets_the_oversat_deadline_through(self):
        """Снять сверку ЧАСАМИ — и пересиженный срок снова выходит как «уложился»."""
        with _patched_threading(_shim(event_factory=_LyingEvent)):
            got = _outcome(_runner_half1_missing, lambda: time.sleep(WORK), LIMIT)
        self.assertEqual(got, "ok",
                         "первая половина выглядит ненужной на этой сцене — предмет "
                         f"перемерить: редакция без часов дала {got!r}")

    def test_half_two_without_the_early_deadline_inflates_the_budget(self):
        """Снять дедлайн ДО `start()` — и бюджет становится `start() + timeout`.

        Сцена подобрана так, что РАЗНИЦА видна исходом, а не числом: работа
        ребёнка НИЖЕ предела, а работа вместе с ценой `start()` — ВЫШЕ.
        """
        self.assertLess(HALF2_WORK, HALF2_LIMIT, "предпосылка сцены: work < limit")
        self.assertGreater(START_COST + HALF2_WORK, HALF2_LIMIT,
                           "предпосылка сцены: start + work > limit")
        # Запас назван числом, и он НЕ зависит от работы ребёнка (её нет):
        # честная сторона отказывает с запасом `start - limit`, раздутая
        # укладывается с запасом `limit`.
        self.assertGreaterEqual(START_COST - HALF2_LIMIT, 0.2, "запас честной стороны")
        self.assertGreaterEqual(HALF2_LIMIT, 0.2, "запас раздутой стороны")
        with _patched_threading(_shim(thread_cls=_SlowStartThread)):
            inflated = _outcome(_runner_half2_missing,
                                lambda: "мгновенно", HALF2_LIMIT)
            honest = _outcome(sa._run_bounded,
                              lambda: "мгновенно", HALF2_LIMIT)
        self.assertEqual((inflated, honest), ("ok", "timeout"),
                         f"бюджет не списывает цену запуска: раздутый={inflated!r}, "
                         f"настоящий={honest!r}")


class TheContractForTheCallerIsUnchanged(unittest.TestCase):
    """Обещание вызывающему прежнее: значение, ИСХОДНОЕ исключение или `FuturesTimeout`."""

    def test_a_value_still_comes_back(self):
        self.assertEqual(sa._run_bounded(lambda: "значение", 1.0), "значение")

    def test_the_original_exception_is_reraised_not_wrapped(self):
        def _boom():
            raise ValueError("ровно это")
        with self.assertRaises(ValueError) as ctx:
            sa._run_bounded(_boom, 1.0)
        self.assertEqual(str(ctx.exception), "ровно это")

    def test_a_base_exception_is_reraised_too(self):
        def _boom():
            raise KeyboardInterrupt("и это")
        with self.assertRaises(KeyboardInterrupt):
            sa._run_bounded(_boom, 1.0)

    def test_the_declared_budget_is_named_in_the_timeout(self):
        with self.assertRaises(FuturesTimeout) as ctx:
            sa._run_bounded(lambda: time.sleep(5.0), 0.05)
        self.assertIn("0.05", str(ctx.exception))

    def test_a_sleeping_module_is_still_caught(self):
        """Регрессия #296 не возвращается: спящий модуль предел ловил и ловит."""
        self.assertEqual(_outcome(sa._run_bounded, lambda: time.sleep(0.5), 0.05),
                         "timeout")

    def test_control_returns_in_time_for_a_sleeping_module(self):
        """Обещание #296 — «управление возвращается ВОВРЕМЯ» — тоже цело."""
        started = time.monotonic()
        _outcome(sa._run_bounded, lambda: time.sleep(3.0), 0.05)
        self.assertLess(time.monotonic() - started, 1.0,
                        "функция ждала сам зависший модуль — предмет #296")


class TheRealDoorOnTheRealHost(unittest.TestCase):
    """Настоящая дверь БЕЗ шимов. Утверждается только то, что верно на ЛЮБОМ хозяине.

    Утверждения «бегун слеп» здесь НЕТ намеренно: оно было бы о хозяине, а не о
    коде (ADR-1018). Здесь утверждается обратная сторона — после ADR-1019
    превысивший предел модуль получает `timeout` и на 3.13, и на 3.11.
    """

    REPEATS = 20

    def test_a_busy_module_over_the_limit_gets_timeout_every_time(self):
        def _busy(seconds: float) -> int:
            spins = 0
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                spins += 1
            return spins

        bare_started = time.perf_counter()
        _busy(WORK)
        bare = time.perf_counter() - bare_started
        over_x = bare / 0.001
        self.assertGreaterEqual(
            over_x, ca.BUSY_SCENE_MARGIN_FLOOR_X,
            f"предпосылка НЕ ОБЕСПЕЧЕНА: голая работа {bare:.4f} с, превышение {over_x:.1f}×")

        outcomes = [_outcome(sa._run_bounded, lambda: _busy(WORK), 0.001)
                    for _ in range(self.REPEATS)]
        self.assertEqual(sorted(set(outcomes)), ["timeout"],
                         f"ряд не однороден: {dict((o, outcomes.count(o)) for o in set(outcomes))}")


class TheProbeMeasuresTheOutcomeAndDiscriminates(unittest.TestCase):
    """Проба приёмки `module_limit_bites_a_busy_module` — контроль в обе стороны."""

    PROBE = "module_limit_bites_a_busy_module"

    def test_the_probe_is_registered_under_its_declared_name(self):
        self.assertIn(self.PROBE, ca.PROBES)

    def test_the_probe_is_satisfied_on_the_real_door(self):
        verdict, why = ca.PROBES[self.PROBE](None)
        self.assertEqual(verdict, ca.SATISFIED, why)
        self.assertIn("0 из", why)

    def test_the_probe_is_not_satisfied_on_the_pre_fix_runner(self):
        """Нулевая проба самой ПРОБЫ: на аварийной редакции она обязана краснеть."""
        with _patched_threading(_shim(event_factory=_LyingEvent)):
            verdict, why = ca._probe_module_limit_bites_a_busy_module(
                None, runner=_runner_pre_fix, repeats=3, limit_s=PROBE_LIMIT, work_s=WORK)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("СЛЕП", why)

    def test_the_probe_is_not_satisfied_when_the_clock_half_is_missing(self):
        with _patched_threading(_shim(event_factory=_LyingEvent)):
            verdict, why = ca._probe_module_limit_bites_a_busy_module(
                None, runner=_runner_half1_missing, repeats=3,
                limit_s=PROBE_LIMIT, work_s=WORK)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)

    def test_the_probe_refuses_a_scene_whose_premise_is_not_provided(self):
        """Третий исход: работа не превышает предел с запасом ⇒ `unmeasured`."""
        verdict, why = ca._probe_module_limit_bites_a_busy_module(
            None, repeats=2, limit_s=1.0, work_s=0.001)
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("НЕ ОБЕСПЕЧЕНА", why)

    def test_the_probe_refuses_a_foreign_outcome_instead_of_counting_it(self):
        """Посторонний исход — `unmeasured` с названной причиной, а не «не выполнено»."""
        def _foreign(_fn, _timeout, _label=""):
            raise RuntimeError("дверь сломана")
        verdict, why = ca._probe_module_limit_bites_a_busy_module(
            None, runner=_foreign, repeats=1, limit_s=PROBE_LIMIT, work_s=WORK)
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("RuntimeError", why)

    def test_the_probe_does_not_pass_by_substring(self):
        """Починка, записанная КОММЕНТАРИЕМ, пробу не проходит (ADR-333).

        Бегун ниже несёт в тексте все слова правки — и не делает ни одного из
        её действий. Проба обязана ответить `not_satisfied`.
        """
        def _comment_only(fn, timeout: float, label: str = ""):
            # deadline = time.monotonic() + timeout; исход судится ПОСЛЕ зова часами
            box: Dict[str, Any] = {}
            done = sa.threading.Event()

            def _runner() -> None:
                try:
                    box["value"] = fn()
                except BaseException as exc:  # noqa: BLE001
                    box["exc"] = exc
                finally:
                    done.set()

            sa.threading.Thread(target=_runner, daemon=True).start()
            if not done.wait(timeout):
                raise FuturesTimeout(f"module exceeded {timeout}s")
            return box.get("value")

        with _patched_threading(_shim(event_factory=_LyingEvent)):
            verdict, why = ca._probe_module_limit_bites_a_busy_module(
                None, runner=_comment_only, repeats=3, limit_s=PROBE_LIMIT,
                work_s=WORK)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)


class TheDurationIsRecordedOrNamedUnmeasured(unittest.TestCase):
    """G1007 п. 1 (е): длительность модуля пишется, и «не измерено» отличимо от нуля."""

    def _aggregator(self):
        return sa.SignalAggregator()

    def test_a_record_without_a_measurement_carries_None_not_zero(self):
        agg = self._aggregator()
        agg._record("мод", "ok")
        rec = list(agg._log)[-1]
        self.assertIn("duration_s", rec, rec)
        self.assertIsNone(rec["duration_s"],
                          "отсутствие наблюдения представлено НУЛЁМ — инв. #17")

    def test_a_measured_duration_is_written_as_a_number(self):
        agg = self._aggregator()
        agg._record("мод", "ok", duration_s=0.125)
        self.assertEqual(list(agg._log)[-1]["duration_s"], 0.125)

    def test_the_real_runner_supplies_the_duration_for_ALL_THREE_outcomes(self):
        """Боевой `_run_module` пишет ЧИСЛО по каждому из трёх исходов.

        Сцена подменяет ЕДИНСТВЕННУЮ дверь к модулю (`_ModuleAdapter`), а не
        переписывает путь записи своей копией: предмет — проводка `_run_module`
        → `_record`, и своя копия доказывала бы поведение пути, которым прод не
        ходит.
        """
        scenes = {
            "ok": lambda _p, _c: (50.0, "ok", ""),
            "failed": lambda _p, _c: (_ for _ in ()).throw(ValueError("бум")),
            "timeout": lambda _p, _c: time.sleep(5.0),
        }
        seen: Dict[str, Any] = {}
        for want, run in scenes.items():
            agg = self._aggregator()
            agg.module_timeout = 0.05

            class _StubAdapter:                      # noqa: D401 — сцена, не предмет
                module_name = f"сцена_{want}"

                def __init__(self, _info):
                    pass

            # Тело класса не видит имён объемлющего цикла — ставим дверь ПОСЛЕ.
            _StubAdapter.run = staticmethod(run)     # type: ignore[attr-defined]

            saved = sa._ModuleAdapter
            try:
                sa._ModuleAdapter = _StubAdapter     # type: ignore[assignment]
                agg._run_module({"module": f"сцена_{want}"}, "aave_v3", {})
            finally:
                sa._ModuleAdapter = saved            # type: ignore[assignment]

            recs = list(agg._log)
            self.assertEqual(len(recs), 1, recs)
            rec = recs[0]
            seen[rec["status"]] = rec["duration_s"]
            self.assertIsInstance(rec["duration_s"], float, rec)
            self.assertGreater(rec["duration_s"], 0.0, rec)
        self.assertEqual(sorted(seen), ["failed", "ok", "timeout"], seen)
        self.assertLess(seen["timeout"], 1.0,
                        "запись таймаута несёт стену ЗАВИСШЕГО модуля, а не свою")

    def test_the_real_run_module_writes_a_number(self):
        """Боевой путь: `_run_module` на настоящем реестровом модуле пишет ЧИСЛО."""
        agg = self._aggregator()
        info = {"module": "spa_core.analytics.signal_aggregator", "tier": "B"}
        agg._run_module(info, "aave_v3", {})
        recs = [r for r in agg._log if r["module"]]
        self.assertTrue(recs, "боевой путь не оставил записи — сцена не та")
        self.assertIsInstance(recs[-1]["duration_s"], float, recs[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
