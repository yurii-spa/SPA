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
    DEFAULT_BUCKETS_S,
    READ_ABSENT,
    READ_EMPTY,
    READ_NO_SESSION,
    READ_OK,
    READ_UNREADABLE,
    at_or_beyond_limit,
    by_file,
    census_from_events,
    census_from_path,
    concentration,
    format_census,
    parse_lines,
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


def _end(t: float, status: int = 0) -> dict:
    return {"e": "end", "t": t, "status": status, "started": 0, "finished": 0}


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
