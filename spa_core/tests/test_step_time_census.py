"""Положительные контроли переписи времени шага тестов (ADR-534, заказ G87 п. 3).

Каждый тест ниже воспроизводит ОДНО названное порванное звено и краснеет на нём.
Батарея, никогда не видевшая настоящей поломки, есть украшение
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

**Времени-якоря в файле нет ПО ПОСТРОЕНИЮ.** Все отметки строятся от безразмерной
базы ``BASE_T`` и ВХОДЯТ в прибор аргументом — то есть приём №1 правила доставки,
а не литеральная дата. Личности процесса в файле нет вовсе; ``git init`` — тоже.

Инв. #16: ни один существующий тест не ослаблен и не сужен — файл только ДОБАВЛЯЕТ.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring.step_time_census import (
    AXE_NOT_NEEDED,
    AXE_REFUSED_EARLIER,
    AXE_REFUSED_NO_STAMP,
    AXE_REFUSED_UNREADABLE,
    AXE_USABLE,
    BIND_NO_THRESHOLD,
    BIND_OK,
    BIND_UNREADABLE,
    DEFAULT_BUCKETS_S,
    READ_ABSENT,
    READ_EMPTY,
    READ_NO_SESSION,
    READ_OK,
    NOISE_DECLARED_ABSENT,
    NOISE_DECLARED_AGREES,
    NOISE_DECLARED_DISAGREES,
    READ_UNREADABLE,
    at_or_beyond_limit,
    axe_stamp_verdict,
    by_file,
    census_from_events,
    census_from_path,
    concentration,
    format_census,
    parse_lines,
    parse_stamp,
    record_noise,
    threshold_binding,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Безразмерная база отметок. Это НЕ дата: прибор судит только о РАЗНИЦАХ, и
#: единственный его вход — сама запись, поэтому календарь на вердикт не влияет.
BASE_T = 1000.0

_FILE_A = "spa_core/tests/test_alpha.py"
_FILE_B = "spa_core/tests/test_beta.py"


def _session(t: float = BASE_T, args: list[str] | None = None) -> dict:
    return {"e": "session", "t": t, "iso": "-", "pid": 1,
            "args": args if args is not None else ["spa_core/tests/", "--timeout=180"]}


def _start(node: str, t: float) -> dict:
    return {"e": "start", "n": node, "t": t}


def _ok(node: str, t: float, d: float = 0.0) -> dict:
    return {"e": "ok", "n": node, "t": t, "d": d}


def _fail(node: str, t: float, when: str = "call", d: float = 0.0) -> dict:
    return {"e": "fail", "n": node, "t": t, "w": when, "d": d, "msg": "-"}


def _end(t: float, status: int = 0, started: int | None = None,
         finished: int | None = None) -> dict:
    """Строка `end`. Счётчики писателя ОПУСКАЮТСЯ, если их не назвали явно.

    Прежняя редакция ставила ``started=0, finished=0`` всегда, и сцена, ничего
    о себе не объявлявшая, выглядела объявившей НОЛЬ. Для оси 3 (заказ G109 п. 3)
    это разные исходы: «не объявлено» и «объявлено 0» (инв. #17). Ни одно
    утверждение существующих тестов этим не ослаблено — ни один из них счётчики
    не читал (проверено ввозом: их читателем был только писатель плагина).
    """
    event: dict = {"e": "end", "t": t, "status": status}
    if started is not None:
        event["started"] = started
    if finished is not None:
        event["finished"] = finished
    return event


def _scene_two_cases() -> list[dict]:
    """Сцена-эталон: сбор 10 с · случай A 5 с (исход на 3-й) · случай B 2 с · конец.

    Размах 1017 − 1000 = 17 с; раскладка 10 + (5 + 2) + 0.
    """
    return [
        _session(BASE_T),
        _start(f"{_FILE_A}::test_one", BASE_T + 10),
        _ok(f"{_FILE_A}::test_one", BASE_T + 13, d=0.5),
        _start(f"{_FILE_B}::test_two", BASE_T + 15),
        _ok(f"{_FILE_B}::test_two", BASE_T + 17, d=1.0),
        _end(BASE_T + 17),
    ]


# ---------------------------------------------------------------------------
# A. Тождество учёта: сумма корзин равна размаху
# ---------------------------------------------------------------------------
class AccountingIdentity(unittest.TestCase):

    def test_three_buckets_sum_to_the_span(self):
        c = census_from_events(_scene_two_cases())
        self.assertEqual(c.read, READ_OK, c.reason)
        self.assertAlmostEqual(c.span_s, 17.0, places=6)
        self.assertAlmostEqual(c.before_first_case_s, 10.0, places=6)
        self.assertAlmostEqual(c.inside_cases_s, 7.0, places=6)
        self.assertAlmostEqual(c.after_last_case_s, 0.0, places=6)
        self.assertTrue(c.identity_holds())

    def test_the_identity_is_able_to_break(self):
        """Обратная сторона: тождество не зелено ПО ПОСТРОЕНИЮ.

        Проверка, которая не умеет краснеть, ничего не проверяет (урок #722).
        """
        c = census_from_events(_scene_two_cases())
        broken = c._replace(inside_cases_s=c.inside_cases_s + 1.0)
        self.assertFalse(broken.identity_holds())

    def test_the_case_closes_at_the_next_start_not_at_its_own_outcome(self):
        """Разборка фикстур лежит В СЛУЧАЕ, а не в безымянном остатке.

        Закрой случай исходом — и 2 с между исходом A и стартом B выпали бы из
        суммы: «где уходит время» получило бы ответ с молчаливой дырой.
        """
        c = census_from_events(_scene_two_cases())
        case_a = c.cases[0]
        self.assertAlmostEqual(case_a.span, 5.0, places=6)
        self.assertAlmostEqual(case_a.to_outcome, 3.0, places=6)
        self.assertAlmostEqual(case_a.after_outcome, 2.0, places=6)
        self.assertAlmostEqual(c.unnamed_between_s, 2.0, places=6)

    def test_the_last_case_closes_at_the_last_event(self):
        events = _scene_two_cases()[:-1] + [_end(BASE_T + 20)]
        c = census_from_events(events)
        self.assertAlmostEqual(c.cases[-1].span, 5.0, places=6)
        self.assertAlmostEqual(c.span_s, 20.0, places=6)
        self.assertTrue(c.identity_holds())


# ---------------------------------------------------------------------------
# B. Третьи исходы — каждый НАЗВАН и ни один не выдан за ноль (инв. #17)
# ---------------------------------------------------------------------------
class ThirdOutcomes(unittest.TestCase):

    def test_absent_record_is_named_not_zeroed(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = census_from_path(Path(tmp) / "nope.jsonl")
        self.assertEqual(c.read, READ_ABSENT)
        self.assertIn("nope.jsonl", c.reason)
        self.assertEqual(c.span_s, 0.0)
        self.assertFalse(c.measured_budget)

    def test_no_path_at_all_is_also_named(self):
        c = census_from_path(None)
        self.assertEqual(c.read, READ_ABSENT)
        self.assertTrue(c.reason)

    def test_unreadable_record_is_a_separate_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = census_from_path(Path(tmp))          # каталог, а не файл
        self.assertEqual(c.read, READ_UNREADABLE)
        self.assertTrue(c.reason)

    def test_empty_record_is_not_a_clean_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            c = census_from_path(path)
        self.assertEqual(c.read, READ_EMPTY)

    def test_a_record_without_a_session_header_refuses(self):
        """Без строки `session` размах считался бы от первого попавшегося события."""
        c = census_from_events([_start(f"{_FILE_A}::t", BASE_T), _ok(f"{_FILE_A}::t", BASE_T + 1)])
        self.assertEqual(c.read, READ_NO_SESSION)
        self.assertIn("session", c.reason)

    def test_a_session_header_without_a_clock_refuses(self):
        head = _session()
        head.pop("t")
        c = census_from_events([head, _start(f"{_FILE_A}::t", BASE_T + 1)])
        self.assertEqual(c.read, READ_NO_SESSION)

    def test_a_torn_tail_is_counted_and_the_rest_is_still_measured(self):
        lines = [json.dumps(e) for e in _scene_two_cases()]
        lines.append('{"e":"start","n":"spa_core/tests/test_g.py::x","t":10')  # обрыв
        events, torn = parse_lines(lines)
        c = census_from_events(events, torn_lines=torn)
        self.assertEqual(c.torn_lines, 1)
        self.assertEqual(c.read, READ_OK)
        self.assertEqual(len(c.cases), 2)

    def test_a_line_that_is_json_but_not_an_event_is_torn_too(self):
        events, torn = parse_lines(['{"no_e": 1}', '[1,2,3]', '"a string"'])
        self.assertEqual(events, [])
        self.assertEqual(torn, 3)

    def test_a_case_without_an_outcome_is_counted_and_still_costs_its_wall(self):
        """На этом случае сессию и сняли: его секунды НЕ исчезают."""
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::test_one", BASE_T + 1),
            _ok(f"{_FILE_A}::test_one", BASE_T + 2),
            _start(f"{_FILE_B}::test_wedged", BASE_T + 3),
        ]
        c = census_from_events(events)
        self.assertEqual(c.cases_without_outcome, 1)
        self.assertIsNone(c.cases[-1].to_outcome)
        self.assertIsNone(c.cases[-1].outcome)
        self.assertAlmostEqual(c.cases[-1].span, 0.0, places=6)
        self.assertTrue(c.identity_holds())

    def test_a_truncated_session_is_a_lower_bound_and_says_so(self):
        events = _scene_two_cases()[:-1]              # без `end`
        c = census_from_events(events)
        self.assertFalse(c.ended)
        self.assertFalse(c.measured_budget)
        self.assertIn("НИЖНЯЯ ГРАНИЦА", format_census(c))
        self.assertIn("НЕ ИЗМЕРЕН", format_census(c))

    def test_a_finished_session_says_the_opposite(self):
        c = census_from_events(_scene_two_cases())
        self.assertTrue(c.ended)
        self.assertTrue(c.measured_budget)
        self.assertIn("ДОШЛА до конца", format_census(c))
        self.assertNotIn("НИЖНЯЯ ГРАНИЦА", format_census(c))

    def test_a_clock_that_went_backwards_is_counted_not_hidden(self):
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 10),
            _ok(f"{_FILE_A}::a", BASE_T + 5),          # назад
            _end(BASE_T + 20),
        ]
        c = census_from_events(events)
        self.assertEqual(c.backwards_clock, 1)

    def test_a_negative_interval_never_becomes_a_negative_span(self):
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 10),
            _ok(f"{_FILE_A}::a", BASE_T + 5),
            _end(BASE_T + 20),
        ]
        c = census_from_events(events)
        self.assertGreaterEqual(c.cases[0].span, 0.0)

    def test_a_session_with_no_cases_says_so_instead_of_printing_zero(self):
        c = census_from_events([_session(BASE_T), _end(BASE_T + 30)])
        self.assertEqual(c.read, READ_OK)
        self.assertEqual(c.cases, ())
        self.assertIn("ни одного случая", c.reason)
        self.assertAlmostEqual(c.before_first_case_s, 30.0, places=6)
        self.assertIn("ни одного случая", format_census(c))


# ---------------------------------------------------------------------------
# C. Несколько сессий в одном файле — писатель открывает его на ДОЗАПИСЬ
# ---------------------------------------------------------------------------
class SeveralSessionsInOneRecord(unittest.TestCase):

    def test_the_last_session_is_taken_and_the_count_is_printed(self):
        first = [_session(BASE_T), _start(f"{_FILE_A}::a", BASE_T + 1),
                 _ok(f"{_FILE_A}::a", BASE_T + 2), _end(BASE_T + 3)]
        second = [_session(BASE_T + 100), _start(f"{_FILE_B}::b", BASE_T + 101),
                  _ok(f"{_FILE_B}::b", BASE_T + 102), _end(BASE_T + 110)]
        c = census_from_events(first + second)
        self.assertEqual(c.sessions_in_record, 2)
        self.assertAlmostEqual(c.span_s, 10.0, places=6)      # только вторая
        self.assertEqual([case.nodeid for case in c.cases], [f"{_FILE_B}::b"])
        self.assertIn("сессий в записи 2", format_census(c))

    def test_one_session_reports_one(self):
        c = census_from_events(_scene_two_cases())
        self.assertEqual(c.sessions_in_record, 1)
        self.assertNotIn("сессий в записи", format_census(c))


# ---------------------------------------------------------------------------
# D. Порог `--timeout` ЧИТАЕТСЯ У ЗАПИСИ, а не берётся из текста воркфлоу
# ---------------------------------------------------------------------------
class TheLimitIsMeasuredNotRemembered(unittest.TestCase):

    def test_equals_form_is_read(self):
        c = census_from_events([_session(BASE_T, args=["--timeout=180"]), _end(BASE_T + 1)])
        self.assertEqual(c.timeout_s, 180.0)

    def test_separate_form_is_read(self):
        c = census_from_events([_session(BASE_T, args=["--timeout", "45"]), _end(BASE_T + 1)])
        self.assertEqual(c.timeout_s, 45.0)

    def test_an_absent_limit_is_none_and_never_one_hundred_eighty(self):
        """Подставить сюда 180 «как в воркфлоу» — ровно дефект site-numbers."""
        c = census_from_events([
            _session(BASE_T, args=["-q"]),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 2),
            _end(BASE_T + 2),
        ])
        self.assertIsNone(c.timeout_s)
        self.assertEqual(at_or_beyond_limit(c), (-1, -1))
        text = format_census(c)
        self.assertIn("порог `--timeout`: НЕ ИЗМЕРЕН", text)
        self.assertNotIn("180", text)

    def test_a_nonnumeric_limit_is_none_not_a_crash(self):
        c = census_from_events([_session(BASE_T, args=["--timeout=abc"]), _end(BASE_T + 1)])
        self.assertIsNone(c.timeout_s)

    def test_a_dangling_limit_flag_is_none(self):
        c = census_from_events([_session(BASE_T, args=["--timeout"]), _end(BASE_T + 1)])
        self.assertIsNone(c.timeout_s)

    def test_a_case_that_outlived_the_limit_twice_over_is_named_separately(self):
        """Клин, который порог НЕ взял, — свойство порога, а не медленного теста."""
        events = [
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::slow", BASE_T + 1),
            _ok(f"{_FILE_A}::slow", BASE_T + 13),       # ≥ порога, < вдвое
            _start(f"{_FILE_B}::wedged", BASE_T + 14),
            _ok(f"{_FILE_B}::wedged", BASE_T + 40),     # ≥ вдвое
            _end(BASE_T + 41),
        ]
        c = census_from_events(events)
        self.assertEqual(at_or_beyond_limit(c), (2, 1))

    def test_a_case_without_an_outcome_is_not_counted_against_the_limit(self):
        """У него наблюдённой фазы нет вовсе — считать его «на пороге» значило бы
        выдать отсутствие наблюдения за наблюдение (инв. #17)."""
        events = [
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::wedged", BASE_T + 1),
            _end(BASE_T + 500),
        ]
        c = census_from_events(events)
        self.assertEqual(at_or_beyond_limit(c), (0, 0))
        self.assertEqual(c.cases_without_outcome, 1)


# ---------------------------------------------------------------------------
# E. Поле `d` — ОТДЕЛЬНАЯ ось, а не подстановка вместо стены
# ---------------------------------------------------------------------------
class TheDeclaredDurationIsItsOwnAxis(unittest.TestCase):

    def test_the_field_is_not_substituted_for_the_observed_wall(self):
        """Заказ предполагал, что запись «несёт длительность каждого случая».
        Замер говорит другое: `d` — это фаза, а стена шире её."""
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 6, d=0.01),   # стена 5 с, поле 0.01 с
            _end(BASE_T + 6),
        ]
        c = census_from_events(events)
        self.assertAlmostEqual(c.observed_phases_s, 5.0, places=6)
        self.assertAlmostEqual(c.declared_d_s, 0.01, places=6)
        self.assertNotAlmostEqual(c.declared_d_s, c.observed_phases_s, places=3)

    def test_the_gap_between_the_field_and_the_wall_is_printed(self):
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 6, d=0.01),
            _end(BASE_T + 6),
        ]
        text = format_census(census_from_events(events))
        # Три числа, а не одно: что поле несёт · чего не несёт ВНУТРИ фаз ·
        # что лежит ПОСЛЕ исхода. Склейка потеряла бы, где именно время.
        self.assertIn("поле `d` несёт 0 с из 5 с наблюдённых фаз", text)
        self.assertIn("внутри фаз его не несёт 5 с (установка)", text)
        self.assertIn("после исхода — ещё 0 с", text)
        self.assertIn("итого вне поля 5 с", text)

    def test_an_outcome_without_d_contributes_nothing_and_does_not_crash(self):
        ev = _ok(f"{_FILE_A}::a", BASE_T + 6)
        ev.pop("d")
        c = census_from_events([_session(BASE_T), _start(f"{_FILE_A}::a", BASE_T + 1),
                                ev, _end(BASE_T + 6)])
        self.assertAlmostEqual(c.declared_d_s, 0.0, places=6)
        self.assertAlmostEqual(c.observed_phases_s, 5.0, places=6)

    def test_a_boolean_is_not_a_clock(self):
        """`True` есть `int` в Python — пустить его как отметку значило бы
        получить размах от 1 секунды и не заметить этого."""
        head = _session()
        head["t"] = True
        c = census_from_events([head, _end(BASE_T)])
        self.assertEqual(c.read, READ_NO_SESSION)


# ---------------------------------------------------------------------------
# F. Производные переписи
# ---------------------------------------------------------------------------
class DerivedViews(unittest.TestCase):

    def test_by_file_sums_cases_of_the_same_file(self):
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 0),
            _ok(f"{_FILE_A}::a", BASE_T + 1),
            _start(f"{_FILE_A}::b", BASE_T + 2),
            _ok(f"{_FILE_A}::b", BASE_T + 3),
            _start(f"{_FILE_B}::c", BASE_T + 4),
            _ok(f"{_FILE_B}::c", BASE_T + 5),
            _end(BASE_T + 5),
        ]
        totals = by_file(census_from_events(events))
        self.assertAlmostEqual(totals[_FILE_A], 4.0, places=6)
        self.assertAlmostEqual(totals[_FILE_B], 1.0, places=6)

    def test_concentration_counts_only_cases_at_or_above_the_threshold(self):
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::big", BASE_T + 0),
            _ok(f"{_FILE_A}::big", BASE_T + 70),
            _start(f"{_FILE_B}::small", BASE_T + 70),
            _ok(f"{_FILE_B}::small", BASE_T + 70.5),
            _end(BASE_T + 70.5),
        ]
        rows = dict((t, (n, s)) for t, n, s in concentration(census_from_events(events)))
        self.assertEqual(rows[60.0][0], 1)
        self.assertAlmostEqual(rows[60.0][1], 70.0, places=6)
        self.assertEqual(rows[0.1][0], 2)

    def test_the_bucket_ladder_is_declared_and_descending(self):
        self.assertEqual(list(DEFAULT_BUCKETS_S), sorted(DEFAULT_BUCKETS_S, reverse=True))
        self.assertTrue(all(x > 0 for x in DEFAULT_BUCKETS_S))

    def test_a_wedged_case_is_marked_differently_in_the_digest(self):
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 2),
            _start(f"{_FILE_B}::wedged", BASE_T + 3),
        ]
        text = format_census(census_from_events(events))
        self.assertIn("⏳", text)
        self.assertIn("случаев без исхода 1", text)

    def test_the_digest_names_the_remainder_instead_of_truncating_silently(self):
        events = [_session(BASE_T)]
        t = BASE_T
        for i in range(5):
            events.append(_start(f"{_FILE_A}::t{i}", t))
            t += 1
            events.append(_ok(f"{_FILE_A}::t{i}", t))
        events.append(_end(t))
        text = format_census(census_from_events(events), shown=2)
        self.assertIn("и ещё 3 случа", text)


# ---------------------------------------------------------------------------
# G. Совместимость с НАСТОЯЩИМ писателем — прибор не читает собственную выдумку
# ---------------------------------------------------------------------------
class TheRealWriterIsTheOneWeRead(unittest.TestCase):
    """Самый дорогой контроль батареи: запись делает живой плагин, а не фикстура.

    Прибор, проверенный только на придуманных мной событиях, зелен ПО ПОСТРОЕНИЮ:
    он читает мой формат, а не формат писателя. Поэтому здесь поднимается
    дочерний pytest с тем же `-p spa_core.ci.pytest_stream_record` и той же
    переменной окружения, что в воркфлоу.
    """

    def test_a_record_written_by_the_plugin_is_read_with_the_identity_holding(self):
        from spa_core.tests import _child_pytest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "test_sample_for_census.py"
            target.write_text(
                "import time\n"
                "def test_fast():\n"
                "    assert True\n"
                "def test_slower():\n"
                "    time.sleep(0.2)\n"
                "    assert True\n",
                encoding="utf-8",
            )
            record = root / "stream.jsonl"
            env = dict(os.environ)
            env["SPA_PYTEST_STREAM"] = str(record)
            env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            proc = _child_pytest.run_child_pytest(
                target, "-q", "-p", "spa_core.ci.pytest_stream_record",
                "--timeout=37",
                cwd=REPO_ROOT, env=env, timeout=120,
            )
            if not record.exists():
                self.fail(
                    "предпосылка НЕ ОБЕСПЕЧЕНА: писатель не создал запись "
                    f"(rc={proc.returncode})\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
                )
            c = census_from_path(record)

        self.assertEqual(c.read, READ_OK, c.reason)
        self.assertTrue(c.ended, "сессия дочернего прогона обязана дойти до конца")
        self.assertTrue(c.identity_holds())
        self.assertEqual(len(c.cases), 2)
        self.assertEqual(c.cases_without_outcome, 0)
        # Порог прочитан из args ЖИВОГО прогона, а не из моего словаря.
        self.assertEqual(c.timeout_s, 37.0)
        # Медленный случай дороже быстрого — иначе отметки берутся не оттуда.
        slower = [case for case in c.cases if case.nodeid.endswith("test_slower")][0]
        self.assertGreaterEqual(slower.span, 0.19)


# ---------------------------------------------------------------------------
# H. Проводка: у находки есть читатель, и читается она ПО ФОРМЕ ВЫЗОВА
# ---------------------------------------------------------------------------
class TheFindingHasAReader(unittest.TestCase):
    """ADR-526: произведённая находка без читателя — отдельный класс вреда.

    Читатель здесь `scripts/ci_verdict.py`: он единственный, у кого запись есть
    на руках в момент, когда она ещё существует. Проверяется ФОРМА ВЫЗОВА
    (ADR-414/427), а не наличие подстроки: подстрока переживает отрыв проводки.
    """

    @staticmethod
    def _tree() -> ast.Module:
        return ast.parse((REPO_ROOT / "scripts" / "ci_verdict.py").read_text(encoding="utf-8"))

    def test_ci_verdict_imports_the_census_by_name(self):
        wanted = {"census_from_path", "format_census"}
        found: set[str] = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom) and node.module == "spa_core.monitoring.step_time_census":
                found |= {alias.name for alias in node.names}
        self.assertTrue(wanted <= found, f"ввоз переписи оторван: {found}")

    def test_ci_verdict_calls_format_time_in_main(self):
        calls = [
            node for node in ast.walk(self._tree())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "format_time"
        ]
        self.assertTrue(calls, "вызова format_time в ci_verdict нет — читатель оторван")

    def test_the_workflow_hands_the_record_to_the_reader(self):
        """Читатель без входа есть тот же разрыв, что читатель без вызова."""
        text = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        verdict_lines = [ln for ln in text.splitlines() if "ci_verdict.py" in ln]
        self.assertTrue(verdict_lines, "в воркфлоу нет ни одного вызова ci_verdict.py")
        with_stream = [ln for ln in verdict_lines if "--stream" in ln]
        self.assertTrue(
            with_stream,
            "ни один вызов вердикта не получает --stream: перепись времени читать нечего",
        )

    def test_the_reader_prints_the_block_when_a_record_is_given(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_ci_verdict_under_test", REPO_ROOT / "scripts" / "ci_verdict.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "stream.jsonl"
            record.write_text(
                "\n".join(json.dumps(e) for e in _scene_two_cases()) + "\n",
                encoding="utf-8")
            text = module.format_time(record, label="spa_core/tests/")
        self.assertIn("размах сессии", text)
        self.assertIn("раскладка", text)

    def test_the_reader_stays_silent_when_no_record_was_asked_for(self):
        """Без `--stream` записи нет вовсе — печатать о ней нечего, и это НЕ
        молчание о вреде: сам `ci_verdict` уже называет отсутствие имён."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_ci_verdict_silent", REPO_ROOT / "scripts" / "ci_verdict.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.assertEqual(module.format_time(None, label="x"), "")

    def test_the_time_block_never_moves_the_return_code(self):
        """Вердикт о наборе берётся у ОДНОГО источника (ADR-474). Секунды его не трогают."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_ci_verdict_rc", REPO_ROOT / "scripts" / "ci_verdict.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "j.xml"
            junit.write_text(
                '<testsuite name="x" tests="2" failures="0" errors="0" skipped="0"/>',
                encoding="utf-8")
            record = Path(tmp) / "stream.jsonl"
            record.write_text(
                "\n".join(json.dumps(e) for e in _scene_two_cases()) + "\n",
                encoding="utf-8")
            rc_with = module.main([str(junit), "--stream", str(record)])
            rc_without = module.main([str(junit)])
        self.assertEqual(rc_with, rc_without)
        self.assertEqual(rc_with, module.RC_GREEN)


# ---------------------------------------------------------------------------
# I. Дыры, найденные МУТАЦИОННЫМ замером собственной батареи (ADR-534)
#    Каждый тест ниже написан ПО ИСХОДУ мутанта, который до него выживал.
# ---------------------------------------------------------------------------
class HolesFoundByMutatingMyOwnBattery(unittest.TestCase):

    def test_an_unreadable_census_is_zero_in_EVERY_number(self):
        """Мутант: любой ноль `_unreadable` → 1 выживал.

        Читатель, забывший проверить `read`, обязан получить ноль, а не выдуманное
        число: иначе «не измерено» снова станет неотличимо от измеренного.
        """
        c = census_from_path(None)
        for field in ("span_s", "before_first_case_s", "inside_cases_s",
                      "after_last_case_s", "observed_phases_s", "unnamed_between_s",
                      "declared_d_s"):
            self.assertEqual(getattr(c, field), 0.0, field)
        for field in ("torn_lines", "cases_without_outcome", "backwards_clock",
                      "sessions_in_record"):
            self.assertEqual(getattr(c, field), 0, field)
        self.assertEqual(c.cases, ())
        self.assertEqual(c.args, ())
        self.assertIsNone(c.timeout_s)
        self.assertFalse(c.ended)

    def test_a_clean_scene_reports_no_third_outcomes_at_all(self):
        """Мутант: умолчание `torn_lines: int = 0` → 1 выживало.

        Строка «третьи исходы: нет» и есть объявленный НОЛЬ (инв. #17); без неё
        прибор молчал бы о них одинаково и когда их нет, и когда их не спросили.
        """
        c = census_from_events(_scene_two_cases())
        self.assertEqual(c.torn_lines, 0)
        self.assertIn("третьи исходы: нет", format_census(c))

    def test_the_no_cases_branch_is_zero_in_every_number_too(self):
        c = census_from_events([_session(BASE_T), _end(BASE_T + 30)])
        self.assertEqual(c.inside_cases_s, 0.0)
        self.assertEqual(c.after_last_case_s, 0.0)
        self.assertEqual(c.observed_phases_s, 0.0)
        self.assertEqual(c.unnamed_between_s, 0.0)
        self.assertEqual(c.declared_d_s, 0.0)
        self.assertEqual(c.cases_without_outcome, 0)
        self.assertTrue(c.identity_holds())

    def test_a_subsecond_case_keeps_its_fraction(self):
        """Мутант: `max(0.0, …)` → `max(1.0, …)` выживал — все мои сцены были ≥ 1 с,
        и округление вверх до секунды прошло бы незамеченным на наборе, где
        108 тысяч случаев из 108 685 как раз короче секунды."""
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::quick", BASE_T + 1),
            _ok(f"{_FILE_A}::quick", BASE_T + 1.25),
            _end(BASE_T + 1.25),
        ]
        c = census_from_events(events)
        self.assertAlmostEqual(c.cases[0].to_outcome, 0.25, places=6)
        self.assertAlmostEqual(c.observed_phases_s, 0.25, places=6)

    def test_two_outcome_events_for_one_case_take_the_LAST_one(self):
        """Это не выдумка: на живой записи 3.11 таких событий 1 971 (субтесты).

        Взять первый исход значило бы обрезать случай на его первом упавшем
        субтесте и потерять остаток его стены.
        """
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::sub", BASE_T + 1),
            _fail(f"{_FILE_A}::sub", BASE_T + 2, when="call", d=0.1),
            _ok(f"{_FILE_A}::sub", BASE_T + 9, d=7.0),
            _end(BASE_T + 9),
        ]
        c = census_from_events(events)
        self.assertEqual(c.cases[0].outcome, "ok")
        self.assertAlmostEqual(c.cases[0].to_outcome, 8.0, places=6)
        self.assertAlmostEqual(c.cases[0].declared_d, 7.1, places=6)

    def test_an_outcome_outside_the_case_window_does_not_belong_to_it(self):
        """Исход с тем же именем, пришедший ПОСЛЕ закрытия случая, чужой."""
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _start(f"{_FILE_B}::b", BASE_T + 2),
            _ok(f"{_FILE_A}::a", BASE_T + 5),        # уже после закрытия случая A
            _ok(f"{_FILE_B}::b", BASE_T + 6),
            _end(BASE_T + 6),
        ]
        c = census_from_events(events)
        self.assertIsNone(c.cases[0].to_outcome)
        self.assertEqual(c.cases_without_outcome, 1)

    def test_a_case_exactly_at_the_bucket_threshold_is_counted(self):
        """Мутант: `>= threshold` → `> threshold` выживал — границы никто не трогал."""
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::exact", BASE_T + 0),
            _ok(f"{_FILE_A}::exact", BASE_T + 60),
            _end(BASE_T + 60),
        ]
        rows = dict((t, n) for t, n, _ in concentration(census_from_events(events)))
        self.assertEqual(rows[60.0], 1)

    def test_a_case_exactly_at_the_limit_counts_as_at_the_limit(self):
        """Мутант: оба `>=` в at_or_beyond_limit → `>` выживали."""
        events = [
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::exact", BASE_T + 0),
            _ok(f"{_FILE_A}::exact", BASE_T + 10),       # ровно порог
            _start(f"{_FILE_B}::double", BASE_T + 10),
            _ok(f"{_FILE_B}::double", BASE_T + 30),      # ровно вдвое
            _end(BASE_T + 30),
        ]
        self.assertEqual(at_or_beyond_limit(census_from_events(events)), (2, 1))

    def test_the_limit_line_is_printed_even_when_nobody_reached_it(self):
        """Мутант: `if at < 0` → `at <= 0` выживал, и прибор говорил бы
        «порог НЕ ИЗМЕРЕН» о прогоне, где порог измерен, а на нём просто никого нет.
        Ноль обязан быть ОБЪЯВЛЕН, а не выдан за отсутствие наблюдения (инв. #17)."""
        events = [
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::fast", BASE_T + 0),
            _ok(f"{_FILE_A}::fast", BASE_T + 1),
            _end(BASE_T + 1),
        ]
        text = format_census(census_from_events(events))
        self.assertIn("порог `--timeout` прочитан у записи: 10 с", text)
        self.assertIn("случаев на пороге или выше 0", text)
        self.assertNotIn("НЕ ИЗМЕРЕН", text)

    def test_exactly_as_many_cases_as_shown_leaves_no_remainder_line(self):
        """Мутант: `len(cases) > shown` → `>=` выживал."""
        events = [_session(BASE_T)]
        t = BASE_T
        for i in range(3):
            events.append(_start(f"{_FILE_A}::t{i}", t))
            t += 1
            events.append(_ok(f"{_FILE_A}::t{i}", t))
        events.append(_end(t))
        text = format_census(census_from_events(events), shown=3)
        self.assertNotIn("и ещё", text)

    def test_the_printed_minutes_and_percentages_are_the_measured_ones(self):
        """Мутанты `span / 60 → / 61` и `100.0 → 101.0` выживали: напечатанное
        число не проверял никто, а печать и есть весь выход прибора."""
        text = format_census(census_from_events(_scene_two_cases()))
        self.assertIn("размах сессии 0.3 мин (17 с)", text)
        # сбор 10 с из 17 = 58.8 %
        self.assertIn("58.8 %", text)

    def test_a_zero_span_prints_unmeasured_instead_of_dividing_by_it(self):
        """Мутант `span > 0` → `span >= 0` выживал, а на нулевом размахе он
        делит на ноль: «не измерено» обязано быть словом, а не исключением."""
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T),
            _ok(f"{_FILE_A}::a", BASE_T),
            _end(BASE_T),
        ]
        text = format_census(census_from_events(events))
        self.assertIn("НЕ ИЗМЕРЕНО", text)

    def test_the_entry_point_returns_two_when_the_record_is_absent(self):
        """Мутанты в `main()` выживали целиком: точку входа не звал ни один тест,
        а именно её зовёт человек с артефактом прогона на руках."""
        from spa_core.monitoring import step_time_census as mod

        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "stream.jsonl"
            record.write_text(
                "\n".join(json.dumps(e) for e in _scene_two_cases()) + "\n",
                encoding="utf-8")
            self.assertEqual(mod.main([str(record), "--top", "1"]), 0)
            self.assertEqual(mod.main([str(record), "--json", "--top", "1"]), 0)
            self.assertEqual(mod.main([str(record), "--by-file", "--top", "1"]), 0)
            self.assertEqual(mod.main([str(Path(tmp) / "nope.jsonl")]), 2)

    def test_the_declared_choices_are_pinned_not_incidental(self):
        """Мутанты лестницы и предела печати выживали: эти числа есть ВЫБОР, и
        выбор, который никто не закрепил, меняется молча. Закрепление здесь —
        не проверка поведения, а объявление: сдвинуть их можно только намеренно."""
        from spa_core.monitoring import step_time_census as mod

        self.assertEqual(tuple(mod.DEFAULT_BUCKETS_S), (60.0, 10.0, 1.0, 0.1))
        self.assertEqual(mod._NAMES_SHOWN, 10)

    def test_the_printed_minutes_are_seconds_divided_by_sixty(self):
        """Мутант `span / 60 → / 61` пережил сцену в 17 с: 17/60 и 17/61 округляются
        до одного и того же «0.3». Нужна сцена, на которой делитель ВИДЕН."""
        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::long", BASE_T + 0),
            _ok(f"{_FILE_A}::long", BASE_T + 1200),
            _end(BASE_T + 1200),
        ]
        text = format_census(census_from_events(events))
        self.assertIn("размах сессии 20.0 мин (1200 с)", text)

    def test_the_json_keeps_three_decimals(self):
        """Мутант `round(…, 3) → 4` выживал: машинный выход не читал ни один тест."""
        import contextlib
        import io

        from spa_core.monitoring import step_time_census as mod

        events = [
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 1.0000049),
            _end(BASE_T + 1.0000049),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "stream.jsonl"
            record.write_text("\n".join(json.dumps(e) for e in events) + "\n",
                              encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(mod.main([str(record), "--json", "--top", "1"]), 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["span_s"], 1.0)
        self.assertEqual(doc["top"][0]["to_outcome_s"], 0.0)

    def test_the_survivors_that_remain_are_equivalent_and_said_so_aloud(self):
        """Четыре мутанта второго круга РАВНОСИЛЬНЫ, и равносильность доказана
        предпосылкой, а не согласием (порядок ADR-529):

        * `split("::", 1)[0]` → `split("::", 2)[0]` — у элемента [0] maxsplit
          не меняет ничего ни при каком числе разделителей;
        * то же у `split("=", 1)[1]` для токена с ОДНИМ знаком равенства;
        * `<= tolerance` → `< tolerance` в тождестве учёта различимы только при
          разнице РОВНО 1e-6 — это проверка равенства плавающих, а не поведения;
        * `indent=2 → 3` меняет НАПИСАНИЕ документа, а не документ.

        Тест ниже доказывает первые два: они и есть те, что встречаются на живых
        данных (nodeid с двумя `::`, токен порога с одним `=`).
        """
        from spa_core.monitoring.step_time_census import _timeout_from_args

        nodeid = "spa_core/tests/test_x.py::Klass::test_method"
        self.assertEqual(nodeid.split("::", 1)[0], nodeid.split("::", 2)[0])
        self.assertEqual(_timeout_from_args(["--timeout=180"]), 180.0)
        self.assertEqual("--timeout=180".split("=", 1)[1], "--timeout=180".split("=", 2)[1])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ---------------------------------------------------------------------------
# J. ОСЬ 1 (заказ G109 п. 3): «связывает ли порог» — по ИСХОДУ, не по длительности
#
# Положительный контроль здесь — РЕАЛЬНЫЙ случай прогона 37769228666 (нога 3.12):
# `test_the_instrument_excludes_itself_by_naming_the_reason` шёл 504,7 с при пороге
# 180 с и завершился ИСХОДОМ `ok`, в junit — без элемента failure. Существующая ось
# считает его в «прожили ВДВОЕ дольше порога» и печатает «порог их не взял», что
# читается как улика клина; по ИСХОДУ же это случай, который порог и не связывал.
# Рядом — его противоположность, тоже реальная: восемь случаев ноги 3.11 с исходом
# `fail` на 180,7…182,7 с, у которых junit говорит дословно
# `Failed: Timeout (>180.0s) from pytest-timeout`.
# ---------------------------------------------------------------------------
class TheThresholdBindsOrItDoesNot(unittest.TestCase):

    def test_a_failure_at_the_threshold_counts_as_bound(self):
        """Порог СРАБОТАЛ: исход `fail` на пороге — это снятый случай."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::slow", BASE_T),
            _fail(f"{_FILE_A}::slow", BASE_T + 10, d=10.0),
            _end(BASE_T + 10),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.read, BIND_OK)
        self.assertEqual((bind.at_or_beyond, bind.bound, bind.unbound), (1, 1, 0))
        self.assertIs(bind.binds, True)

    def test_a_pass_above_the_threshold_counts_as_unbound(self):
        """Реальный случай 504,7 с с исходом `ok`: порог его НЕ связывал.

        Это ровно тот случай, которого существующая ось не различает: она считает
        его «пережившим порог», то есть уликой клина, — а он просто дошёл сам.
        """
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::long", BASE_T),
            _ok(f"{_FILE_A}::long", BASE_T + 30, d=30.0),
            _end(BASE_T + 30),
        ])
        bind = threshold_binding(c)
        self.assertEqual((bind.at_or_beyond, bind.bound, bind.unbound), (1, 0, 1))
        self.assertIs(bind.binds, False)
        # и существующая ось на той же сцене не различает его вовсе
        self.assertEqual(at_or_beyond_limit(c), (1, 1))

    def test_the_two_populations_are_never_merged(self):
        """Мутант `c.outcome == "fail"` → `is not None` слил бы их в одно число."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::killed", BASE_T),
            _fail(f"{_FILE_A}::killed", BASE_T + 11),
            _start(f"{_FILE_B}::survived", BASE_T + 11),
            _ok(f"{_FILE_B}::survived", BASE_T + 40),
            _end(BASE_T + 40),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.at_or_beyond, 2)
        self.assertEqual(bind.bound, 1)
        self.assertEqual(bind.unbound, 1)

    def test_a_skip_at_the_threshold_is_its_own_number(self):
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::skipped", BASE_T),
            {"e": "skip", "n": f"{_FILE_A}::skipped", "t": BASE_T + 12, "d": 12.0},
            _end(BASE_T + 12),
        ])
        bind = threshold_binding(c)
        self.assertEqual((bind.bound, bind.unbound, bind.skipped), (0, 0, 1))
        self.assertIs(bind.binds, False)

    def test_without_a_threshold_the_question_is_unmeasured_not_answered_no(self):
        """Порога нет ⇒ `binds is None`. Ответить «не связывал» значило бы выдать
        отсутствие наблюдения за наблюдение (инв. #17)."""
        c = census_from_events([
            _session(BASE_T, args=["-q"]),
            _start(f"{_FILE_A}::a", BASE_T),
            _ok(f"{_FILE_A}::a", BASE_T + 99),
            _end(BASE_T + 99),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.read, BIND_NO_THRESHOLD)
        self.assertIsNone(bind.binds)
        self.assertEqual((bind.bound, bind.unbound), (0, 0))

    def test_a_long_case_without_an_outcome_is_counted_apart(self):
        """У случая без исхода наблюдённой фазы нет — судить о пороге по нему
        нечем, но его существование обязано быть ВИДНО числом."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::hung", BASE_T),
            _start(f"{_FILE_B}::next", BASE_T + 50),
            _ok(f"{_FILE_B}::next", BASE_T + 51),
            _end(BASE_T + 51),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.unjudged_without_outcome, 1)
        self.assertEqual((bind.at_or_beyond, bind.bound, bind.unbound), (0, 0, 0))

    def test_twice_the_threshold_is_also_split_by_outcome(self):
        """Мутант, считавший «вдвое выше» без исхода, выживал: именно это число
        существующая ось печатает как «порог их не взял»."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::passed_far", BASE_T),
            _ok(f"{_FILE_A}::passed_far", BASE_T + 25),
            _start(f"{_FILE_B}::killed_far", BASE_T + 25),
            _fail(f"{_FILE_B}::killed_far", BASE_T + 55),
            _end(BASE_T + 55),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.beyond_twice, 2)
        self.assertEqual(bind.beyond_twice_unbound, 1)
        self.assertEqual(bind.beyond_twice_bound, 1)

    def test_an_unreadable_record_answers_none_not_false(self):
        bind = threshold_binding(census_from_path(None))
        self.assertEqual(bind.read, BIND_UNREADABLE)
        self.assertIsNone(bind.binds)

    def test_the_verdict_is_printed_in_both_directions(self):
        killed = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::k", BASE_T), _fail(f"{_FILE_A}::k", BASE_T + 11),
            _end(BASE_T + 11),
        ])
        self.assertIn("порог СВЯЗАЛ: ДА", format_census(killed))
        quiet = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::q", BASE_T), _ok(f"{_FILE_A}::q", BASE_T + 1),
            _end(BASE_T + 1),
        ])
        self.assertIn("порог СВЯЗАЛ: НЕТ", format_census(quiet))


# ---------------------------------------------------------------------------
# K. ОСЬ 2 (заказ G109 п. 3): ОТКАЗ от негодной отметки топора
#
# Положительный контроль воспроизводит ИЗМЕРЕННУЮ аварию, причём дважды и на
# разных прогонах: ADR-534 дополнение 3 — отметка раннера на 285,9 с РАНЬШЕ
# последней активности записи; прогон 37769228666 нога 3.11 — на 183,3 с раньше.
# Отметка, которая раньше наблюдённой активности, не является даже ВЕРХНЕЙ
# границей, и подстановка её вместо неизмеренного бюджета УМЕНЬШИЛА бы измеренное.
#
# Смещения ниже — безразмерные сдвиги от ``BASE_T``, а не даты: предметом здесь
# является ПОРЯДОК двух событий, и календарь на него не влияет.
# ---------------------------------------------------------------------------
_GAP_ADR534 = 285.9      # дополнение 3 ADR-534
_GAP_RUN_3_11 = 183.3    # прогон 37769228666, нога 3.11


def _unended_scene(last_at: float) -> list[dict]:
    """Сессия БЕЗ строки `end`: бюджет шага не измерен, соблазн подставить топор."""
    return [
        _session(BASE_T, args=["--timeout=180"]),
        _start(f"{_FILE_A}::a", BASE_T + 1),
        _ok(f"{_FILE_A}::a", last_at),
    ]


class TheAxeStampIsRefusedWhenItIsUnusable(unittest.TestCase):

    def test_a_stamp_earlier_than_the_record_is_refused(self):
        """Авария ADR-534 дополнение 3 и её независимое повторение на 3.11."""
        for gap in (_GAP_ADR534, _GAP_RUN_3_11):
            with self.subTest(gap=gap):
                last = BASE_T + 1000
                c = census_from_events(_unended_scene(last))
                axe = axe_stamp_verdict(c, last - gap)
                self.assertEqual(axe.kind, AXE_REFUSED_EARLIER)
                self.assertFalse(axe.usable)
                self.assertIsNone(axe.upper_bound_s)
                self.assertAlmostEqual(axe.gap_s, -gap, places=3)
                self.assertIn(f"{gap:.1f} с", axe.reason)

    def test_a_stamp_after_the_last_activity_bounds_the_budget_from_above(self):
        last = BASE_T + 1000
        c = census_from_events(_unended_scene(last))
        axe = axe_stamp_verdict(c, last + 60)
        self.assertEqual(axe.kind, AXE_USABLE)
        self.assertTrue(axe.usable)
        self.assertAlmostEqual(axe.lower_bound_s, last - BASE_T, places=3)
        self.assertAlmostEqual(axe.upper_bound_s, last + 60 - BASE_T, places=3)

    def test_when_the_record_reached_its_end_the_stamp_is_not_needed(self):
        """Бюджет измерен самой записью ⇒ отметка не нужна, но согласие с ней
        НАЗЫВАЕТСЯ числом (на реальной 3.12 оно 73,2 с)."""
        c = census_from_events(_scene_two_cases())
        axe = axe_stamp_verdict(c, BASE_T + 20)
        self.assertEqual(axe.kind, AXE_NOT_NEEDED)
        self.assertTrue(axe.usable)
        self.assertAlmostEqual(axe.gap_s, 3.0, places=3)

    def test_a_missing_stamp_is_a_named_refusal_not_a_zero(self):
        """Мутант `stamp_t is None` → `stamp_t == 0` подставил бы ноль и объявил
        шаг завершившимся до собственного начала."""
        c = census_from_events(_unended_scene(BASE_T + 1000))
        axe = axe_stamp_verdict(c, None)
        self.assertEqual(axe.kind, AXE_REFUSED_NO_STAMP)
        self.assertFalse(axe.usable)
        self.assertIsNone(axe.gap_s)
        self.assertIsNone(axe.upper_bound_s)

    def test_an_unreadable_record_refuses_the_stamp_too(self):
        axe = axe_stamp_verdict(census_from_path(None), BASE_T)
        self.assertEqual(axe.kind, AXE_REFUSED_UNREADABLE)
        self.assertFalse(axe.usable)

    def test_the_boundary_is_not_off_by_one_second(self):
        """Мутант `gap < 0` → `gap <= 0` объявлял бы отказ на РОВНО совпавшей
        отметке, то есть отказывал годной."""
        last = BASE_T + 1000
        c = census_from_events(_unended_scene(last))
        self.assertEqual(axe_stamp_verdict(c, last).kind, AXE_USABLE)

    def test_the_refusal_and_the_brackets_are_printed(self):
        last = BASE_T + 1000
        c = census_from_events(_unended_scene(last))
        refused = format_census(c, axe_stamp=last - _GAP_RUN_3_11)
        self.assertIn("отметка топора: ОТКАЗ", refused)
        self.assertNotIn("между границами", refused)
        usable = format_census(c, axe_stamp=last + 60)
        self.assertIn("отметка топора: ГОДНА", usable)
        self.assertIn("между границами", usable)

    def test_no_stamp_means_no_axe_line_at_all(self):
        """Прибор не вправе выдумывать отметку: в записи её нет по построению."""
        self.assertNotIn("отметка топора",
                         format_census(census_from_events(_scene_two_cases())))

    def test_a_stamp_is_read_as_iso_or_epoch_and_junk_is_none(self):
        self.assertEqual(parse_stamp("1000"), 1000.0)
        self.assertIsNone(parse_stamp(None))
        self.assertIsNone(parse_stamp(""))
        self.assertIsNone(parse_stamp("не отметка"))
        # ISO разбирается и даёт РАЗНИЦУ в секундах, равную названной
        a = parse_stamp("2026-10-08T15:28:29Z")
        b = parse_stamp("2026-10-08T15:16:09Z")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertAlmostEqual(a - b, 12 * 60 + 20, places=3)


# ---------------------------------------------------------------------------
# L. ОСЬ 3 (заказ G109 п. 3): СЧЁТ шума и сверка объявления записи
#
# Положительный контроль сверки — авария ADR-534 дополнение 2: собственный тест
# плагина выключал писателя посреди сессии, и запись несла 416 стартов против 588
# тестов своего же junit. Внутри записи этот вред неотличим от снятого топором
# шага; то, что внутри записи ИЗМЕРИМО, — спор её собственного объявления
# (`started`/`finished` в строке `end`) с независимой реконструкцией. На реальной
# ноге 3.12 объявление СОШЛОСЬ до единицы (115 980 / 118 019), и это единственная
# форма, в которой у объявления вообще появился читатель.
# ---------------------------------------------------------------------------
class TheNoiseOfTheRecordIsCountedNotAssumed(unittest.TestCase):

    def test_a_clean_record_says_clean_as_a_measurement(self):
        noise = record_noise(census_from_events(_scene_two_cases()))
        self.assertIs(noise.clean, True)
        self.assertEqual(
            (noise.torn_lines, noise.cases_without_outcome,
             noise.backwards_clock, noise.extra_sessions), (0, 0, 0, 0))
        self.assertIn("шум записи: ЧИСТО",
                      format_census(census_from_events(_scene_two_cases())))

    def test_a_torn_line_flips_the_verdict_and_is_counted(self):
        events, torn = parse_lines(
            [json.dumps(e) for e in _scene_two_cases()] + ["{оборвано"])
        noise = record_noise(census_from_events(events, torn_lines=torn))
        self.assertEqual(noise.torn_lines, 1)
        self.assertIs(noise.clean, False)

    def test_a_case_without_an_outcome_flips_the_verdict(self):
        c = census_from_events([
            _session(BASE_T),
            _start(f"{_FILE_A}::hung", BASE_T + 1),
            _start(f"{_FILE_B}::next", BASE_T + 5),
            _ok(f"{_FILE_B}::next", BASE_T + 6),
            _end(BASE_T + 6),
        ])
        noise = record_noise(c)
        self.assertEqual(noise.cases_without_outcome, 1)
        self.assertIs(noise.clean, False)

    def test_a_backwards_clock_flips_the_verdict(self):
        c = census_from_events([
            _session(BASE_T + 100),
            _start(f"{_FILE_A}::a", BASE_T + 101),
            _ok(f"{_FILE_A}::a", BASE_T + 50),
            _end(BASE_T + 102),
        ])
        self.assertGreaterEqual(record_noise(c).backwards_clock, 1)
        self.assertIs(record_noise(c).clean, False)

    def test_an_extra_session_in_the_record_is_counted_as_noise(self):
        c = census_from_events(
            [_session(BASE_T), _start(f"{_FILE_A}::a", BASE_T + 1),
             _ok(f"{_FILE_A}::a", BASE_T + 2), _end(BASE_T + 3)]
            + [_session(BASE_T + 100), _start(f"{_FILE_B}::b", BASE_T + 101),
               _ok(f"{_FILE_B}::b", BASE_T + 102), _end(BASE_T + 103)])
        noise = record_noise(c)
        self.assertEqual(noise.extra_sessions, 1)
        self.assertIs(noise.clean, False)

    def test_a_declaration_that_agrees_is_said_to_agree(self):
        """Реальная 3.12: объявлено 115 980 / 118 019 и столько же восстановлено."""
        c = census_from_events([
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 2),
            _end(BASE_T + 3, started=1, finished=1),
        ])
        noise = record_noise(c)
        self.assertEqual(noise.declared_check, NOISE_DECLARED_AGREES)
        self.assertEqual((noise.rebuilt_started, noise.rebuilt_finished), (1, 1))
        self.assertIn("СОШЛОСЬ", format_census(c))

    def test_a_declaration_that_disagrees_is_named_with_both_pairs(self):
        """Авария дополнения 2 ADR-534 в измеримой внутри записи форме: писатель
        выключен посреди сессии ⇒ объявление и реконструкция расходятся."""
        c = census_from_events([
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 2),
            _end(BASE_T + 3, started=588, finished=588),
        ])
        noise = record_noise(c)
        self.assertEqual(noise.declared_check, NOISE_DECLARED_DISAGREES)
        self.assertEqual(noise.declared_started, 588)
        self.assertEqual(noise.rebuilt_started, 1)
        text = format_census(c)
        self.assertIn("СПОРИТ", text)
        self.assertIn("588", text)

    def test_a_record_without_an_end_line_leaves_the_declaration_unjudged(self):
        """Третий исход: «не объявлено» не есть ни согласие, ни спор."""
        c = census_from_events(_unended_scene(BASE_T + 100))
        noise = record_noise(c)
        self.assertEqual(noise.declared_check, NOISE_DECLARED_ABSENT)
        self.assertIsNone(noise.declared_started)

    def test_declaring_zero_is_not_the_same_as_declaring_nothing(self):
        """Мутант, читавший `started` через `or`, слил бы 0 и отсутствие."""
        zero = census_from_events([
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 2),
            _end(BASE_T + 3, started=0, finished=0),
        ])
        self.assertEqual(record_noise(zero).declared_check, NOISE_DECLARED_DISAGREES)
        self.assertEqual(record_noise(zero).declared_started, 0)
        silent = census_from_events(_scene_two_cases())
        self.assertEqual(record_noise(silent).declared_check, NOISE_DECLARED_ABSENT)

    def test_several_outcome_events_on_one_case_are_structure_not_noise(self):
        """На реальной 3.12 таких случаев 277 (лишних событий 2 039) — это ФАЗЫ.
        Записать их в шум значило бы объявить дефектом устройство pytest-а."""
        c = census_from_events([
            _session(BASE_T),
            _start(f"{_FILE_A}::two_phases", BASE_T + 1),
            _ok(f"{_FILE_A}::two_phases", BASE_T + 2, d=1.0),
            _ok(f"{_FILE_A}::two_phases", BASE_T + 3, d=1.0),
            _end(BASE_T + 3, started=1, finished=2),
        ])
        noise = record_noise(c)
        self.assertEqual(noise.cases_with_many_outcomes, 1)
        self.assertEqual(noise.extra_outcome_events, 1)
        self.assertIs(noise.clean, True)
        self.assertEqual(noise.declared_check, NOISE_DECLARED_AGREES)
        self.assertIn("это ФАЗЫ, а не порча", format_census(c))

    def test_an_unreadable_record_does_not_claim_to_be_clean(self):
        self.assertIsNone(record_noise(census_from_path(None)).clean)


# ---------------------------------------------------------------------------
# M. Три оси обязаны быть ВИДНЫ потребителю, а не только существовать
# ---------------------------------------------------------------------------
class ThePortedAxesHaveAReader(unittest.TestCase):

    def test_the_json_output_carries_all_three_axes(self):
        """Прибор зовут и машинно; ось, которой нет в `--json`, для машины
        не перенесена (ADR-526: читатель без входа есть тот же разрыв)."""
        from spa_core.monitoring import step_time_census as mod

        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "stream.jsonl"
            record.write_text(
                "\n".join(json.dumps(e) for e in _scene_two_cases()) + "\n",
                encoding="utf-8")
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = mod.main([str(record), "--json",
                                 "--axe-stamp", str(BASE_T + 20)])
        self.assertEqual(code, 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["threshold_binding"]["read"], BIND_OK)
        self.assertIs(doc["record_noise"]["clean"], True)
        self.assertEqual(doc["axe_stamp"]["kind"], AXE_NOT_NEEDED)

    def test_an_unparsed_stamp_is_refused_out_loud_by_the_entry_point(self):
        """Негодная отметка не становится молча `None`: цикл обязан увидеть отказ."""
        from spa_core.monitoring import step_time_census as mod

        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "stream.jsonl"
            record.write_text(
                "\n".join(json.dumps(e) for e in _scene_two_cases()) + "\n",
                encoding="utf-8")
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.main([str(record), "--axe-stamp", "вчера"])
        out = buf.getvalue()
        self.assertIn("отметка топора: ОТКАЗ", out)
        self.assertIn("не разобрана", out)


# ---------------------------------------------------------------------------
# N. ДЫРЫ СЦЕН, найденные мутационным замером САМИХ новых осей
#
# Замер: 56 мутантов по пяти новым функциям, убито 34, выжило 22 — и все 22
# оказались дырами СЦЕН, а не дефектами прибора (урок #752–#754). Каждый тест
# ниже закрывает названный мутант и краснеет на нём.
#
# Среди них — ровно та ловушка, которой учит замер ADR-581: РАВНЫЕ счёты двух
# исходов делают подмену ИМЕНИ ключа невидимой. На сцене «один fail и один ok»
# мутант `outcome == "fail"` → `!=` даёт то же число 1, и сцена его не видит;
# различимость появляется только при НЕРАВНЫХ счётах.
# ---------------------------------------------------------------------------
class HolesFoundByMutatingTheNewAxes(unittest.TestCase):

    def test_an_unmeasured_binding_is_zero_in_EVERY_field(self):
        """Мутанты `const 0->1` в `_no_binding` выживали шестью штуками: сцена
        читала только `bound`/`unbound`, а полей там десять."""
        bind = threshold_binding(census_from_events(
            [_session(BASE_T, args=["-q"]), _end(BASE_T + 1)]))
        self.assertEqual(bind.read, BIND_NO_THRESHOLD)
        self.assertIsNone(bind.threshold_s)
        self.assertEqual(
            (bind.at_or_beyond, bind.bound, bind.unbound, bind.skipped,
             bind.unjudged_without_outcome, bind.beyond_twice,
             bind.beyond_twice_bound, bind.beyond_twice_unbound),
            (0, 0, 0, 0, 0, 0, 0, 0))

    def test_a_case_EXACTLY_at_the_threshold_is_counted(self):
        """Мутант `>= порог` → `> порог` выживал: ни одна сцена не стояла РОВНО
        на пороге, а реальные снятые случаи стоя́т именно там (180,005 с)."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::exact", BASE_T),
            _fail(f"{_FILE_A}::exact", BASE_T + 10),
            _end(BASE_T + 10),
        ])
        self.assertEqual(threshold_binding(c).at_or_beyond, 1)

    def test_a_case_EXACTLY_at_twice_the_threshold_is_counted(self):
        """Мутант `>= 2 * порог` → `> 2 * порог` выживал по той же причине."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::exact2", BASE_T),
            _fail(f"{_FILE_A}::exact2", BASE_T + 20),
            _end(BASE_T + 20),
        ])
        self.assertEqual(threshold_binding(c).beyond_twice, 1)

    def test_the_outcome_name_is_read_and_not_merely_present(self):
        """Мутанты `outcome == "fail"` → `!=` и `== "skip"` → `!=` выживали на
        симметричной сцене. Счёты здесь НЕРАВНЫЕ (1 fail · 2 ok · 1 skip),
        поэтому подмена имени меняет число и видна."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::killed", BASE_T),
            _fail(f"{_FILE_A}::killed", BASE_T + 11),
            _start(f"{_FILE_A}::ok1", BASE_T + 11),
            _ok(f"{_FILE_A}::ok1", BASE_T + 22),
            _start(f"{_FILE_A}::ok2", BASE_T + 22),
            _ok(f"{_FILE_A}::ok2", BASE_T + 33),
            _start(f"{_FILE_B}::skipped", BASE_T + 33),
            {"e": "skip", "n": f"{_FILE_B}::skipped", "t": BASE_T + 44},
            _end(BASE_T + 44),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.at_or_beyond, 4)
        self.assertEqual(bind.bound, 1)      # при `!=` стало бы 3
        self.assertEqual(bind.unbound, 2)    # при `!=` стало бы 2 — поэтому и fail, и skip
        self.assertEqual(bind.skipped, 1)    # при `!=` стало бы 3

    def test_a_case_WITH_an_outcome_is_never_counted_as_unjudged(self):
        """Мутант `to_outcome is None and span >= порог` → `or` выживал: в сцене
        не было случая, у которого исход ЕСТЬ и размах при этом больше порога."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::long_but_judged", BASE_T),
            _ok(f"{_FILE_A}::long_but_judged", BASE_T + 50),
            _end(BASE_T + 50),
        ])
        self.assertEqual(threshold_binding(c).unjudged_without_outcome, 0)

    def test_a_record_with_only_one_absolute_clock_refuses_the_stamp(self):
        """Мутант `last_event_t is None or session_t is None` → `and` выживал:
        через запись оба поля ставятся вместе, поэтому сцена строится прямо."""
        from spa_core.monitoring.step_time_census import AXE_REFUSED_NO_CLOCK

        base = census_from_events(_scene_two_cases())
        for broken in (base._replace(session_t=None),
                       base._replace(last_event_t=None)):
            with self.subTest(missing=broken):
                axe = axe_stamp_verdict(broken, BASE_T + 20)
                self.assertEqual(axe.kind, AXE_REFUSED_NO_CLOCK)
                self.assertFalse(axe.usable)

    def test_an_unreadable_noise_ledger_is_zero_in_EVERY_field(self):
        """Мутанты `const 0->1` в ветви нечитаемой записи выживали семью штуками."""
        noise = record_noise(census_from_path(None))
        self.assertIsNone(noise.clean)
        self.assertEqual(
            (noise.cases_without_outcome, noise.backwards_clock,
             noise.extra_sessions, noise.cases_with_many_outcomes,
             noise.extra_outcome_events, noise.rebuilt_started,
             noise.rebuilt_finished), (0, 0, 0, 0, 0, 0, 0))
        self.assertIsNone(noise.declared_started)
        self.assertIsNone(noise.declared_finished)

    def test_half_a_declaration_is_not_silence(self):
        """Мутант `started is None and finished is None` → `or` выживал: сцены с
        ОДНИМ объявленным счётчиком не было. Объявлена половина ⇒ это уже
        объявление, и сверять его надо, а не звать молчанием."""
        c = census_from_events([
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 2),
            _end(BASE_T + 3, started=1),
        ])
        self.assertEqual(record_noise(c).declared_check, NOISE_DECLARED_DISAGREES)
        self.assertEqual(record_noise(c).declared_started, 1)
        self.assertIsNone(record_noise(c).declared_finished)

    def test_one_matching_counter_out_of_two_is_still_a_disagreement(self):
        """Мутант `started == rebuilt and finished == rebuilt` → `or` выживал:
        сцены, где сходится РОВНО ОДИН счётчик, не было."""
        c = census_from_events([
            _session(BASE_T),
            _start(f"{_FILE_A}::a", BASE_T + 1),
            _ok(f"{_FILE_A}::a", BASE_T + 2),
            _end(BASE_T + 3, started=1, finished=999),
        ])
        self.assertEqual(record_noise(c).declared_check, NOISE_DECLARED_DISAGREES)


    def test_a_case_EXACTLY_at_the_threshold_without_an_outcome_is_unjudged(self):
        """Мутант `c.span >= limit` → `>` в счёте неподсудных выживал: сцены с
        размахом РОВНО в порог у случая без исхода не было."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::hung_exact", BASE_T),
            _start(f"{_FILE_B}::next", BASE_T + 10),
            _ok(f"{_FILE_B}::next", BASE_T + 11),
            _end(BASE_T + 11),
        ])
        self.assertEqual(threshold_binding(c).unjudged_without_outcome, 1)

    def test_beyond_twice_is_a_SUBSET_of_at_the_threshold(self):
        """Мутант, снявший фильтр «вдвое выше», давал twice == at и выживал,
        пока в сцене эти два числа были РАВНЫ."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::at_only", BASE_T),
            _fail(f"{_FILE_A}::at_only", BASE_T + 11),
            _start(f"{_FILE_B}::far", BASE_T + 11),
            _fail(f"{_FILE_B}::far", BASE_T + 42),
            _end(BASE_T + 42),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.at_or_beyond, 2)
        self.assertEqual(bind.beyond_twice, 1)

    def test_the_outcome_name_is_read_INSIDE_the_twice_population_too(self):
        """Мутанты `== "fail"` / `== "ok"` в счёте «вдвое выше» выживали: там
        счёты были РАВНЫ (1 и 1). Здесь они НЕРАВНЫ — 1 fail против 2 ok."""
        c = census_from_events([
            _session(BASE_T, args=["--timeout=10"]),
            _start(f"{_FILE_A}::far_killed", BASE_T),
            _fail(f"{_FILE_A}::far_killed", BASE_T + 25),
            _start(f"{_FILE_A}::far_ok1", BASE_T + 25),
            _ok(f"{_FILE_A}::far_ok1", BASE_T + 55),
            _start(f"{_FILE_B}::far_ok2", BASE_T + 55),
            _ok(f"{_FILE_B}::far_ok2", BASE_T + 90),
            _end(BASE_T + 90),
        ])
        bind = threshold_binding(c)
        self.assertEqual(bind.beyond_twice, 3)
        self.assertEqual(bind.beyond_twice_bound, 1)     # при `!=` стало бы 2
        self.assertEqual(bind.beyond_twice_unbound, 2)   # при `!=` стало бы 1
