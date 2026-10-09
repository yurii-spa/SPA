# LLM_FORBIDDEN
"""Контроли на `scripts/ci_verdict.py` — три исхода шага тестов (ADR-474).

Каждый тест ниже — положительный контроль на РЕАЛЬНУЮ аварию, а не украшение
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»):

* обрыв сессии (прогон 36119204905: лог кончается штампом `+++ Timeout +++`, сводки
  pytest нет ни одной) ⇒ записи прогона НЕТ ⇒ «НЕ ИЗМЕРЕНО»;
* таймаут в `setUpClass` приходит junit-ом как **error**, а не failure — прибор,
  считающий одни `failures`, назвал бы ту самую аварию ЗЕЛЁНОЙ;
* ноль собранных тестов проходит любую проверку на провалы ⇒ «НЕ ИЗМЕРЕНО», не «чисто».

Разбор сверяется не только с рукописным XML, но и с тем, что пишет ЖИВОЙ pytest:
рукописная фикстура доказывает поведение прибора, живая — что он читает настоящую форму.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ci_verdict.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_ci_verdict_under_test", _SCRIPT)
    assert spec and spec.loader, f"не загрузился {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cv = _load_module()


def _write(tmp_path: Path, body: str, name: str = "junit.xml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).strip(), encoding="utf-8")
    return path


# ── ИЗМЕРЕНО ──────────────────────────────────────────────────────────────────

def test_green_when_the_run_recorded_itself_with_no_failures(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        <testsuite name="pytest" tests="5" failures="0" errors="0" skipped="1"/>
    """)
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_GREEN
    assert verdict.measured
    assert verdict.tests == 5


def test_red_when_failures_are_named(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        <testsuite name="pytest" tests="5" failures="2" errors="0" skipped="0"/>
    """)
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_RED
    assert verdict.measured


def test_red_when_only_errors_are_present_setupclass_timeout_shape(tmp_path: Path) -> None:
    """Контроль НА САМУЮ аварию: таймаут `setUpClass` — это error, не failure.

    Прибор, читающий только `failures`, назвал бы прогон 36119204905 ЗЕЛЁНЫМ.
    """
    path = _write(tmp_path, """
        <testsuite name="pytest" tests="106810" failures="0" errors="3" skipped="0"/>
    """)
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_RED, "errors без failures обязаны читаться как КРАСНО"
    assert verdict.errors == 3


def test_testsuites_wrapper_is_parsed_not_called_unmeasured(tmp_path: Path) -> None:
    """pytest пишет и одиночный `<testsuite>`, и обёртку `<testsuites>` — обе законны.

    Прибор, знающий одну форму, объявил бы «НЕ ИЗМЕРЕНО» на исправной записи: это
    fail-CLOSED в верную сторону, но по НЕВЕРНОЙ причине, и вердикт был бы ложным.
    """
    path = _write(tmp_path, """
        <testsuites>
          <testsuite name="a" tests="3" failures="1" errors="0" skipped="0"/>
          <testsuite name="b" tests="4" failures="0" errors="0" skipped="2"/>
        </testsuites>
    """)
    verdict = cv.read_verdict(path)
    assert verdict.measured
    assert (verdict.tests, verdict.failures, verdict.skipped) == (7, 1, 2)
    assert verdict.rc == cv.RC_RED


# ── НЕ ИЗМЕРЕНО — три разные причины, и каждая названа ────────────────────────

def test_missing_record_is_unmeasured_and_names_the_path(tmp_path: Path) -> None:
    """Сессия, убитая `os._exit` или снятая по `timeout-minutes`, записи не пишет."""
    verdict = cv.read_verdict(tmp_path / "nope.xml")
    assert verdict.rc == cv.RC_UNMEASURED
    assert not verdict.measured
    assert "nope.xml" in verdict.reason
    assert verdict.tests is None, "числа при «не измерено» обязаны быть None, а не 0"


def test_truncated_record_is_unmeasured_not_green(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_text('<testsuite name="pytest" tests="5" failures="0"', encoding="utf-8")
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_UNMEASURED
    assert verdict.reason


def test_record_without_any_testsuite_is_unmeasured(tmp_path: Path) -> None:
    path = _write(tmp_path, "<something-else/>")
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_UNMEASURED
    assert "testsuite" in verdict.reason


def test_zero_collected_is_unmeasured_not_a_clean_pass(tmp_path: Path) -> None:
    """Пустой набор проходит любую проверку на провалы — это fail-OPEN, не «чисто»."""
    path = _write(tmp_path, """
        <testsuite name="pytest" tests="0" failures="0" errors="0" skipped="0"/>
    """)
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_UNMEASURED
    assert "0 тестов" in verdict.reason


def test_absent_counter_is_unmeasured_not_zero(tmp_path: Path) -> None:
    """Найдено МУТАЦИЕЙ собственной батареи (цикл #694): дефект был в приборе.

    `_int_attr` читал отсутствие атрибута нулём, поэтому запись с `tests="50"` и
    без `failures` объявлялась ЗЕЛЁНОЙ — прибор против инварианта #17 нарушал его
    сам. Отсутствие наблюдения обязано быть отдельным значением, а не нулём.
    """
    path = _write(tmp_path, '<testsuite name="p" tests="50" errors="0" skipped="0"/>')
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_UNMEASURED, "нет счётчика failures ⇒ не измерено, не зелено"
    assert "failures" in verdict.reason


@pytest.mark.parametrize("missing", ["tests", "failures", "errors", "skipped"])
def test_each_required_counter_is_named_when_absent(tmp_path: Path, missing: str) -> None:
    attrs = {"tests": "7", "failures": "0", "errors": "0", "skipped": "0"}
    del attrs[missing]
    body = "<testsuite name=\"p\" " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>"
    verdict = cv.read_verdict(_write(tmp_path, body))
    assert verdict.rc == cv.RC_UNMEASURED
    assert missing in verdict.reason, "причина обязана НАЗВАТЬ пропавший счётчик"


def test_absent_counter_in_one_suite_of_many_still_unmeasured(tmp_path: Path) -> None:
    """Сумма по набору не вправе «доложить» отсутствующее слагаемое нулём."""
    path = _write(tmp_path, """
        <testsuites>
          <testsuite name="a" tests="3" failures="0" errors="0" skipped="0"/>
          <testsuite name="b" tests="4" errors="0" skipped="0"/>
        </testsuites>
    """)
    assert cv.read_verdict(path).rc == cv.RC_UNMEASURED


def test_nonnumeric_attribute_does_not_crash_the_reader(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        <testsuite name="pytest" tests="ошибка" failures="0" errors="0" skipped="0"/>
    """)
    verdict = cv.read_verdict(path)
    assert verdict.rc == cv.RC_UNMEASURED, "нечитаемое число тестов = не измерено"


# ── вывод и коды возврата — контракт для воркфлоу ─────────────────────────────

def test_unmeasured_output_names_the_reason_out_loud(tmp_path: Path) -> None:
    verdict = cv.read_verdict(tmp_path / "gone.xml")
    text = cv.format_verdict(verdict, label="spa_core/tests/")
    assert "НЕ ИЗМЕРЕНО" in text
    assert "причина:" in text


def test_measured_output_never_says_unmeasured(tmp_path: Path) -> None:
    path = _write(tmp_path, '<testsuite name="p" tests="2" failures="0" errors="0" skipped="0"/>')
    text = cv.format_verdict(cv.read_verdict(path), label="x")
    assert "НЕ ИЗМЕРЕНО" not in text
    assert "ИЗМЕРЕНО" in text


@pytest.mark.parametrize(
    "body,expected_rc",
    [
        ('<testsuite name="p" tests="2" failures="0" errors="0" skipped="0"/>', cv.RC_GREEN),
        ('<testsuite name="p" tests="2" failures="1" errors="0" skipped="0"/>', cv.RC_RED),
        ('<testsuite name="p" tests="0" failures="0" errors="0" skipped="0"/>', cv.RC_UNMEASURED),
    ],
)
def test_main_returns_the_contracted_exit_code(tmp_path: Path, body: str, expected_rc: int) -> None:
    path = _write(tmp_path, body)
    assert cv.main([str(path), "--label", "проба"]) == expected_rc


def test_three_codes_are_three_distinct_values() -> None:
    """Инв. #17: если два исхода делят код возврата, третьего исхода нет."""
    assert len({cv.RC_GREEN, cv.RC_RED, cv.RC_UNMEASURED}) == 3


# ── живой pytest: прибор читает НАСТОЯЩУЮ форму, а не нашу гипотезу о ней ─────

def _run_pytest_writing_junit(tmp_path: Path, source: str) -> Path:
    (tmp_path / "test_sample.py").write_text(textwrap.dedent(source), encoding="utf-8")
    junit = tmp_path / "out.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "no:randomly",
         f"--junitxml={junit}", "-p", "no:cacheprovider"],
        cwd=tmp_path, capture_output=True, text=True, timeout=300,
    )
    return junit


def test_reads_the_xml_a_real_pytest_actually_writes_green(tmp_path: Path) -> None:
    junit = _run_pytest_writing_junit(tmp_path, """
        def test_ok(): assert True
        def test_ok_two(): assert True
    """)
    verdict = cv.read_verdict(junit)
    assert verdict.rc == cv.RC_GREEN, f"живой pytest + чистый набор ⇒ зелено, а не {verdict}"
    assert verdict.tests == 2


def test_reads_the_xml_a_real_pytest_actually_writes_red(tmp_path: Path) -> None:
    junit = _run_pytest_writing_junit(tmp_path, """
        def test_ok(): assert True
        def test_broken(): assert False
    """)
    verdict = cv.read_verdict(junit)
    assert verdict.rc == cv.RC_RED, f"живой pytest + падение ⇒ красно, а не {verdict}"
    assert verdict.failures == 1

# ── ПРИЧИНЫ: третий вопрос к той же записи (ADR-675, заказ G108 п. 1) ──────────
#
# Порванное звено: перепись причин не позвана. Тогда «провалов 80» уезжает в лог
# одиноким числом, и множитель между провалами и ДЕФЕКТАМИ снова живёт в голове
# читателя — то самое состояние, которое заказ G108 п. 1 велел закрыть (у фазы
# установки тот же прогон давал 19 провалов на ЧЕТЫРЁХ дефектах).

_CAUSE_TB = "spa_core/tests/test_x.py:1: in t\nE   KeyError: 'identity'\n"


def _junit_with_two_keyerrors(tmp_path: Path) -> Path:
    cases = "".join(
        f'<testcase classname="m" name="t{i}" time="0.1">'
        f'<failure message="KeyError: &apos;{key}&apos;">{_CAUSE_TB}</failure></testcase>'
        for i, key in enumerate(("identity", "verdict")))
    path = tmp_path / "junit-causes.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites><testsuite name="pytest" tests="2" failures="2" errors="0" '
        f'skipped="0">{cases}</testsuite></testsuites>', encoding="utf-8")
    return path


def test_the_fork_of_defects_reaches_the_log_of_the_step(tmp_path: Path) -> None:
    out = cv.format_causes(_junit_with_two_keyerrors(tmp_path), None)
    assert "ВИЛКА ДЕФЕКТОВ" in out
    assert "НЕ МЕНЬШЕ 1" in out        # грубый ключ склеил имя ключа
    assert "НЕ БОЛЬШЕ 2" in out        # точный ключ его различил


def test_the_causes_are_printed_by_the_entry_point_not_only_available(
        tmp_path: Path, capsys) -> None:
    """Проводка мерится ВЫЗОВОМ: функция, которую никто не зовёт, — не читатель."""
    rc = cv.main([str(_junit_with_two_keyerrors(tmp_path)), "--label", "стенд"])
    out = capsys.readouterr().out
    assert rc == cv.RC_RED
    assert "ВИЛКА ДЕФЕКТОВ" in out


def test_an_absent_record_says_NOT_MEASURED_and_claims_no_zero(tmp_path: Path) -> None:
    out = cv.format_causes(tmp_path / "нет-такого.xml", None)
    assert "НЕ ИЗМЕРЕНО" in out
    assert "провалов 0" not in out


# ── ADR-676 (заказ G108 п. 2): дверь срока печатается ТЕМ ЖЕ логом ────────────
# Шаг, у которого один случай съел срок и не вернул его, и шаг, не влезший в
# бюджет, дают один и тот же лог Actions — а лечатся они по-разному. Поэтому
# четвёртый вопрос стои́т рядом с раскладкой времени, а не в отдельном приборе,
# который никто не зовёт.

def _stream_with_a_case_that_never_returned(tmp_path: Path) -> Path:
    rows = [
        {"e": "session", "args": ["--timeout=180", "--timeout-method=signal"],
         "t": 0.0},
        {"e": "start", "n": "spa_core/tests/t.py::fast", "t": 1.0},
        {"e": "ok", "n": "spa_core/tests/t.py::fast", "t": 1.5, "d": 0.5},
        {"e": "start", "n": "spa_core/tests/t.py::hung", "t": 2.0},
    ]
    path = tmp_path / "stream-doors.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_the_door_of_the_deadline_is_printed_by_the_entry_point(
        tmp_path: Path, capsys) -> None:
    """Проводка мерится ВЫЗОВОМ, а не ввозом: ввезённая и не позванная перепись
    числа в лог не кладёт, и шаг молчит ровно о том, ради чего она написана."""
    cv.main([str(_junit_with_two_keyerrors(tmp_path)), "--label", "стенд",
             "--stream", str(_stream_with_a_case_that_never_returned(tmp_path))])
    out = capsys.readouterr().out
    assert "не вернулись 1" in out
    assert "t.py::hung" in out


def test_without_a_stream_the_door_is_NOT_MEASURED_rather_than_zero(
        tmp_path: Path) -> None:
    out = cv.format_doors(None)
    assert "НЕ ИЗМЕРЕНА" in out
    assert "не вернулись 0" not in out
