"""Контроль пробы `catchup_cycle_fires_once_after_the_hour` (ADR-1052).

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом, где она
зелёная на целом контуре и КРАСНАЯ на каждом порванном звене — с названным звеном, — и
где она НЕ проходит подстрокой (ADR-333).

Звенья рвутся ПОДМЕНОЙ НАСТОЯЩЕГО МОДУЛЯ: исходник читается с диска, в нём меняется ровно
одна строка, мутант грузится под тем же именем, и проба зовётся та же. Поэтому контроль
меряет пробу, а не свою копию её условия.

Якорь подмены проверяется ЯВНО: не нашлась строка — тест падает ГРОМКО
(`AnchorMissing`), а не «мутация не применилась, зато зелено». Предпосылка, которую не
обеспечили, обязана быть слышна (`.claude/rules/deployment.md` § про pid).

# FROZEN-DATE-OK: injected-clock — даты 2026-09-16/17 суть ВХОД `now=` самой пробы
# (воспроизведение аварии 17.09): проба передаёт момент модулю параметром, а модуль
# сравнивает его со отметкой, которую сцена пишет в одноразовый каталог. Обе стороны
# сравнения закреплены сценой, стенных часов в пути нет ни у одной.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

import spa_core.monitoring as _mon
from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import catchup_cycle as real_cc
from spa_core.monitoring import self_heal as real_sh

PROBE = "catchup_cycle_fires_once_after_the_hour"
_CC_NAME = "spa_core.monitoring.catchup_cycle"
_SH_NAME = "spa_core.monitoring.self_heal"


class AnchorMissing(AssertionError):
    """Строка, которую мутация обязана заменить, в исходнике не найдена."""


def _mutate(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise AnchorMissing(
            f"якорь мутации встречается {source.count(old)} раз(а), а нужен ровно один: {old!r}")
    return source.replace(old, new, 1)


def _load(name: str, source: str, origin: Path):
    """Загрузить мутанта под именем ``name``, не записывая его в дерево."""
    spec = importlib.util.spec_from_loader(name, loader=None, origin=str(origin))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(origin)
    exec(compile(source, str(origin), "exec"), module.__dict__)
    return module


@contextmanager
def _swapped(**modules):
    """Подменить модули И атрибуты пакета: `from pkg import mod` читает ВТОРОЕ.

    Правка только `sys.modules` оставила бы на пакете старый атрибут, и проба получила
    бы НАСТОЯЩИЙ модуль — то есть контроль зеленел бы, ничего не подменив.
    """
    saved_sys = {n: sys.modules.get(n) for n in modules}
    saved_attr = {n: getattr(_mon, n.rsplit(".", 1)[1], None) for n in modules}
    try:
        for name, mod in modules.items():
            short = name.rsplit(".", 1)[1]
            if mod is None:
                sys.modules.pop(name, None)
                if hasattr(_mon, short):
                    delattr(_mon, short)
            else:
                sys.modules[name] = mod
                setattr(_mon, short, mod)
        yield
    finally:
        for name in modules:
            short = name.rsplit(".", 1)[1]
            if saved_sys[name] is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved_sys[name]
            if saved_attr[name] is None:
                if hasattr(_mon, short):
                    delattr(_mon, short)
            else:
                setattr(_mon, short, saved_attr[name])


def _cc_source() -> str:
    return Path(real_cc.__file__).read_text(encoding="utf-8")


def _sh_source() -> str:
    return Path(real_sh.__file__).read_text(encoding="utf-8")


def _probe():
    return ca.PROBES[PROBE](None)


@contextmanager
def _source_of(module, source: str):
    """Подменить ИСХОДНИК, который проба читает через `inspect.getsource`.

    Проба судит проводку по AST файла, а не по объекту модуля, поэтому порвать звено
    можно только здесь. Подмена адресная: про остальные объекты отвечает настоящий
    читатель — иначе контроль ослабил бы и соседние вопросы пробы.
    """
    original = ca.inspect.getsource

    def getsource(obj):
        return source if obj is module else original(obj)

    ca.inspect.getsource = getsource
    try:
        yield
    finally:
        ca.inspect.getsource = original


def _mutant_cc(old: str, new: str):
    return _load(_CC_NAME, _mutate(_cc_source(), old, new), Path(real_cc.__file__))


class TheProbeIsRegistered(unittest.TestCase):
    def test_the_probe_is_in_the_registry(self):
        self.assertIn(PROBE, ca.PROBES)

    def test_the_whole_contour_is_green(self):
        status, detail = _probe()
        self.assertEqual(status, ca.SATISFIED, detail)
        self.assertIn(real_cc.DAILY_CYCLE_LABEL, detail)


class EveryBrokenLinkIsRed(unittest.TestCase):
    """Каждое звено — своя мутация настоящего модуля, и имя звена обязано прозвучать."""

    def _assert_red(self, mutant, link: str):
        with _swapped(**{_CC_NAME: mutant}):
            status, detail = _probe()
        self.assertEqual(status, ca.NOT_SATISFIED, f"{link}: {detail}")
        self.assertIn(link, detail, detail)

    def test_no_launch_at_all_is_red(self):
        # Действие снято: решение верное, запуска нет — ровно 17.09 без догона.
        mutant = _mutant_cc(
            "    _record_attempt(root, verdict)      # попытка учтена ДО действия: не kickstart-петля\n"
            "    ok = (kickstart or _kickstart)(DAILY_CYCLE_LABEL)",
            "    _record_attempt(root, verdict)\n"
            "    ok = True")
        self._assert_red(mutant, "scene_17_09")

    def test_waking_another_service_is_red(self):
        mutant = _mutant_cc("(kickstart or _kickstart)(DAILY_CYCLE_LABEL)",
                            '(kickstart or _kickstart)("com.spa.self_heal")')
        self._assert_red(mutant, "scene_label")

    def test_a_second_launch_the_same_day_is_red(self):
        mutant = _mutant_cc('    if last_attempt_day == today:',
                            '    if False:')
        self._assert_red(mutant, "scene_repeat")

    def test_launching_over_a_finished_cycle_is_red(self):
        mutant = _mutant_cc("    if last_cycle_day >= today:",
                            "    if False:")
        self._assert_red(mutant, "scene_cycle_present")

    def test_ignoring_the_hour_is_red(self):
        mutant = _mutant_cc("    if moment.hour < CATCHUP_HOUR_UTC:",
                            "    if False:")
        self._assert_red(mutant, "scene_before_hour")

    def test_a_blind_launch_without_an_observation_is_red(self):
        # Наблюдения нет, а модуль подставляет день и идёт будить цикл — ровно тот
        # запуск вслепую, который владелец запретил рамкой карточки.
        mutant = _mutant_cc(
            "    if last_cycle_day is None:\n",
            '    last_cycle_day = last_cycle_day or "1970-01-01"\n'
            "    if last_cycle_day is None:\n")
        self._assert_red(mutant, "scene_unmeasured")

    def test_silence_instead_of_an_alarm_is_red(self):
        # «Не измерено» без тревоги — молчание, и владелец прямо назвал его негодным
        # наравне с запуском вслепую.
        mutant = _mutant_cc("        if write:\n            (alert or _alert)(",
                            "        if False:\n            (alert or _alert)(")
        self._assert_red(mutant, "scene_unmeasured")

    def test_an_instrument_without_a_live_caller_is_red(self):
        # Проба судит ИСХОДНИК сторожа (AST), поэтому подменяется ровно то, что она
        # читает: подмена объекта модуля её не обманет — `inspect.getsource` всё равно
        # прочитал бы файл с диска, и контроль зеленел бы, ничего не порвав.
        without = _mutate(_sh_source(),
                          "        catchup = catchup_cycle.run(write=not dry_run)",
                          "        catchup = None")
        with _source_of(real_sh, without):
            status, detail = _probe()
        self.assertEqual(status, ca.NOT_SATISFIED, detail)
        self.assertIn("live_caller", detail)

    def test_a_guard_without_the_function_is_red(self):
        renamed = _mutate(_sh_source(), "def run_self_heal(", "def run_self_heal_renamed(")
        with _source_of(real_sh, renamed):
            status, detail = _probe()
        self.assertEqual(status, ca.NOT_SATISFIED, detail)
        self.assertIn("live_caller", detail)

    def test_a_mention_outside_the_function_is_not_a_call(self):
        """«Упомянут» ≠ «приписан»: зов в СОСЕДНЕЙ функции проводкой не является."""
        moved = _mutate(
            _sh_source(),
            "        catchup = catchup_cycle.run(write=not dry_run)",
            "        catchup = None  # catchup_cycle.run(write=True) — только словами")
        moved += ("\n\ndef _elsewhere():\n    from spa_core.monitoring import catchup_cycle\n"
                  "    return catchup_cycle.run(write=False)\n")
        with _source_of(real_sh, moved):
            status, detail = _probe()
        self.assertEqual(status, ca.NOT_SATISFIED, detail)
        self.assertIn("live_caller", detail)


class TheProbeDoesNotPassOnWords(unittest.TestCase):
    """Приманка: все нужные слова и имена есть, поведения нет (ADR-333)."""

    DECOY = '''
"""Догоняющий дневной цикл: если к 10:00 UTC цикла за сегодня не было — ОДИН запуск
через ту же обёртку launchctl kickstart com.spa.daily_cycle. Три исхода различимы:
not_measured — тревога и ноль запусков; already_attempted — не чаще одного в сутки;
cycle_present — ничего не делать; not_due — порог не наступил. launched, launch_failed.
"""
CATCHUP_HOUR_UTC = 10
DAILY_CYCLE_LABEL = "com.spa.daily_cycle"
CYCLE_STATUS_NAME = "paper_trading_status.json"
CATCHUP_STATUS_NAME = "catchup_cycle_status.json"


def run(**kw):
    """Решение, порог, тревога, kickstart, одна попытка в сутки — всё названо словами."""
    return {"verdict": "cycle_present", "launch": False, "reason": "launched not_measured"}
'''

    def test_a_module_of_the_right_words_is_red(self):
        decoy = _load(_CC_NAME, self.DECOY, Path(real_cc.__file__))
        with _swapped(**{_CC_NAME: decoy}):
            status, detail = _probe()
        self.assertEqual(status, ca.NOT_SATISFIED, detail)
        self.assertIn("scene_17_09", detail)


class TheThreeOutcomesAreDistinguishable(unittest.TestCase):
    def test_an_absent_module_is_measured_as_not_built(self):
        """«Как было» этой карточки: модуля нет ⇒ предмет НЕ ПОСТРОЕН, и это ИЗМЕРЕНИЕ."""
        # `sys.modules[name] = None` — канонический способ сказать «такого модуля нет»:
        # `from pkg import mod` поднимает ImportError, как на чистом origin/main.
        saved = sys.modules.get(_CC_NAME)
        saved_attr = getattr(_mon, "catchup_cycle", None)
        try:
            sys.modules[_CC_NAME] = None       # type: ignore[assignment]
            if hasattr(_mon, "catchup_cycle"):
                delattr(_mon, "catchup_cycle")
            status, detail = _probe()
        finally:
            if saved is None:
                sys.modules.pop(_CC_NAME, None)
            else:
                sys.modules[_CC_NAME] = saved
            if saved_attr is not None:
                setattr(_mon, "catchup_cycle", saved_attr)
        self.assertEqual(status, ca.NOT_SATISFIED, detail)
        self.assertIn("НЕ ПОСТРОЕН", detail)

    def test_an_unreadable_guard_source_is_unmeasured(self):
        """Исходник сторожа не прочитан ⇒ третий исход, а не «зелено» и не «красно»."""
        real_getsource = ca.inspect.getsource

        def refuse(obj):
            if obj is real_sh:
                raise OSError("исходник недоступен")
            return real_getsource(obj)

        ca.inspect.getsource = refuse
        try:
            status, detail = _probe()
        finally:
            ca.inspect.getsource = real_getsource
        self.assertEqual(status, ca.UNMEASURED, detail)
        self.assertIn("НЕ ИЗМЕРЕНА", detail)


class TheMutationHarnessActuallySwaps(unittest.TestCase):
    """Положительный контроль самой оснастки: подмена обязана ДОХОДИТЬ до пробы."""

    def test_the_swap_reaches_the_probe(self):
        mutant = _mutant_cc("CATCHUP_HOUR_UTC = 10", "CATCHUP_HOUR_UTC = 11")
        with _swapped(**{_CC_NAME: mutant}):
            from spa_core.monitoring import catchup_cycle as seen
            self.assertEqual(seen.CATCHUP_HOUR_UTC, 11)
        from spa_core.monitoring import catchup_cycle as restored
        self.assertEqual(restored.CATCHUP_HOUR_UTC, real_cc.CATCHUP_HOUR_UTC)

    def test_a_missing_anchor_fails_loudly(self):
        with self.assertRaises(AnchorMissing):
            _mutate("abc", "такой строки тут нет", "x")


class TheCliDistinguishesItsOutcomes(unittest.TestCase):
    """Коды возврата — тоже исход, и склеивать их нельзя (инв. #17).

    Проба судит ПОВЕДЕНИЕ модуля; этот класс судит ДВЕРЬ, через которую его зовут руками
    и расписанием. Один вопрос — один читатель: без этого «НЕ ИЗМЕРЕНО» у CLI стало бы
    неотличимо от «делать нечего», как уже случалось у `pyflakes` и у шага 1д.
    """

    def _main(self, argv, data: dict | None, *, day: str | None = "2026-09-16"):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            if day is not None:
                (root / real_cc.CYCLE_STATUS_NAME).write_text(
                    json.dumps(data if data is not None
                               else {"last_cycle_ts": f"{day}T07:02:00Z"}),
                    encoding="utf-8")
            return real_cc.main([*argv, "--data-dir", str(root)])

    def test_an_unparsable_now_is_refused_not_replaced_by_the_wall_clock(self):
        self.assertEqual(real_cc.main(["--now", "вчера", "--dry-run"]), 2)

    def test_an_empty_now_is_refused(self):
        self.assertEqual(real_cc.main(["--now", "   ", "--dry-run"]), 2)

    def test_a_finished_cycle_is_code_zero(self):
        self.assertEqual(
            self._main(["--now", "2026-09-17T10:30:00Z", "--dry-run"], None,
                       day="2026-09-17"), 0)

    def test_before_the_hour_is_code_zero(self):
        self.assertEqual(
            self._main(["--now", "2026-09-17T09:30:00Z", "--dry-run"], None), 0)

    def test_a_due_catch_up_is_code_one(self):
        self.assertEqual(
            self._main(["--now", "2026-09-17T10:30:00Z", "--dry-run"], None), 1)

    def test_an_unreadable_state_is_code_two_not_zero(self):
        """«Не измерено» обязано отличаться от «делать нечего» КОДОМ, а не прозой."""
        self.assertEqual(
            self._main(["--now", "2026-09-17T10:30:00Z", "--dry-run"], None, day=None), 2)


if __name__ == "__main__":
    unittest.main()
