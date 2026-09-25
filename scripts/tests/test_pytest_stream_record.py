# LLM_FORBIDDEN
"""Контроли на потоковую запись прогона (цикл #697) — имя теста ДО того, как он побежал.

Авария, которую воспроизводит каждый тест ниже, случилась 2026-09-25 на прогоне
**36174140955**. Шаг `Run spa_core unit tests` шёл 120 минут ровно (18:41:49 → 20:42:01),
дошёл до `[ 80%]`, напечатал `FFF F..F....F.F..F` — не меньше тринадцати упавших — и был
снят внешней границей `timeout-minutes`. В логе после этого:

    ❌ НЕ ИЗМЕРЕНО — spa_core/tests/
       причина: записи прогона нет (reports/junit-spa_core.xml)

Третий исход назван честно (ADR-474), и он же прячет имена: и сводка pytest, и junit-запись
пишутся В КОНЦЕ сессии. Вдобавок между 20:35:41 и 20:42:01 шаг не напечатал ни знака —
шесть минут тишины при пороге `--timeout=180`, то есть блокировка в C-коде, которую SIGALRM
не прерывает. Ни одного имени ни у провалов, ни у зависа.

Батарея проверяет ровно это и в обе стороны:

1. убитая сессия ОСТАВЛЯЕТ запись, и в ней НАЗВАНЫ упавший и тот, кто исполнялся в момент
   топора (сцена выше, воспроизведённая `kill -9` на живом pytest);
2. потоковая запись НЕ МОЖЕТ сделать оборванную сессию измеренной — код возврата 2 остаётся
   (иначе «успели 80 тысяч, все зелёные» стало бы вердиктом о наборе, инв. #17);
3. отсутствие записи — НАЗВАННЫЙ исход, а не «упавших нет»;
4. проводка: шаг воркфлоу грузит плагин, объявляет переменную окружения и отдаёт вердикту
   ТОТ ЖЕ путь — мутация любого из трёх звеньев обязана покраснеть.
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ci_verdict.py"
_PLUGIN = _REPO_ROOT / "spa_core" / "ci" / "pytest_stream_record.py"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "test.yml"
_PLUGIN_ARG = "spa_core.ci.pytest_stream_record"


def _load_verdict_module():
    spec = importlib.util.spec_from_file_location("_ci_verdict_stream_under_test", _SCRIPT)
    assert spec and spec.loader, f"не загрузился {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cv = _load_verdict_module()


def _import_plugin():
    import importlib
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    return importlib.import_module(_PLUGIN_ARG)


class _FakeConfig:
    """Минимум, который читает `pytest_configure`: только `invocation_params`."""

    invocation_params = None


def _events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _scene(tmp_path: Path, source: str) -> Path:
    (tmp_path / "test_scene.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


# ── 1. Живой pytest пишет запись, и она переживает СМЕРТЬ процесса ────────────

def test_a_killed_session_still_names_the_failure_and_the_test_it_died_on(
    tmp_path: Path,
) -> None:
    """Сцена 25.09 дословно: `.F` в логе, а в записи — имя упавшего И имя зависшего.

    Это положительный контроль на саму аварию: без потоковой записи оба имени не
    существуют нигде, потому что pytest пишет и сводку, и junit В КОНЦЕ сессии, а
    конца здесь нет — процесс снят `kill -9`, как джобу снимает `timeout-minutes`.
    """
    scene = _scene(tmp_path, """
        import time
        def test_a_passes(): assert True
        def test_b_fails(): assert False, "named failure"
        def test_c_blocks_and_never_returns(): time.sleep(600)
        def test_d_never_reached(): assert True
    """)
    stream = tmp_path / "stream.jsonl"
    env = {**os.environ, "SPA_PYTEST_STREAM": str(stream), "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", str(scene), "-q", "-p", "no:randomly",
         "-p", _PLUGIN_ARG, "-p", "no:cacheprovider"],
        cwd=str(scene), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    # Ждём, пока запись доедет до блокирующего теста, — предпосылку обеспечиваем
    # НАБЛЮДЕНИЕМ, а не сном наугад: не дождались ⇒ падаем ГРОМКО, а не судим о
    # недописанной записи как о полной.
    deadline = time.time() + 60
    while time.time() < deadline:
        if stream.exists() and any(
            e.get("e") == "start" and "test_c_blocks" in str(e.get("n"))
            for e in _events(stream)
        ):
            break
        time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("предпосылка НЕ обеспечена: запись не дошла до блокирующего теста "
                    "за 60 с — судить о ней нельзя")
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=30)

    assert stream.exists(), "запись не пережила смерть процесса — весь смысл модуля в этом"
    read = cv.read_stream(stream)
    assert read.read, read.reason
    assert not read.ended, "сессия убита, а запись докладывает, что дошла до конца"
    failed = [node for node, _when, _msg in read.failed]
    assert any("test_b_fails" in node for node in failed), (
        f"упавший НЕ НАЗВАН, а это и есть авария 25.09: {failed}")
    assert any("test_c_blocks" in node for node in read.running), (
        f"исполнявшийся в момент топора НЕ НАЗВАН: {read.running}")
    assert not any("test_d_never_reached" in node for node in read.running), (
        "не начинавшийся тест назван исполнявшимся — запись выдумывает")


def test_a_session_that_reaches_the_end_says_so(tmp_path: Path) -> None:
    """Контроль В ОБРАТНУЮ СТОРОНУ: у дошедшей сессии `ended` и незавершённых нет."""
    scene = _scene(tmp_path, """
        def test_one(): assert True
        def test_two(): assert False
        def test_three(): import pytest; pytest.skip("причина")
    """)
    stream = tmp_path / "stream.jsonl"
    subprocess.run(
        [sys.executable, "-m", "pytest", str(scene), "-q", "-p", "no:randomly",
         "-p", _PLUGIN_ARG, "-p", "no:cacheprovider"],
        cwd=str(scene), env={**os.environ, "SPA_PYTEST_STREAM": str(stream),
                             "PYTHONPATH": str(_REPO_ROOT)},
        capture_output=True, text=True, timeout=300,
    )
    read = cv.read_stream(stream)
    assert read.read and read.ended, "дошедшая сессия обязана оставить строку `end`"
    assert read.running == [], f"у дошедшей сессии незавершённых быть не может: {read.running}"
    assert read.started == 3 and read.finished == 3, (read.started, read.finished)
    assert len(read.failed) == 1


def test_without_the_env_var_the_plugin_writes_nothing_at_all(tmp_path: Path) -> None:
    """Инертность — НАЗВАННОЕ умолчание: загруженный плагин без переменной не стоит ничего."""
    scene = _scene(tmp_path, "def test_one(): assert True\n")
    stream = tmp_path / "must-not-appear.jsonl"
    env = {k: v for k, v in os.environ.items() if k != "SPA_PYTEST_STREAM"}
    env["PYTHONPATH"] = str(_REPO_ROOT)
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(scene), "-q", "-p", "no:randomly",
         "-p", _PLUGIN_ARG, "-p", "no:cacheprovider"],
        cwd=str(scene), env=env, capture_output=True, text=True, timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert not stream.exists(), "плагин писал без переменной окружения"


def test_without_the_env_var_no_writer_is_created_at_all(monkeypatch) -> None:
    """Контроль НА КОНТРОЛЬ (мутация M03 пережила проверку выше).

    Тест над ним смотрит на ОДИН путь и поэтому доказывает лишь «не писал СЮДА»:
    плагин, подставляющий себе любой другой путь, проходил его молча. Инертность —
    это отсутствие ПИСАТЕЛЯ, и спрашивать надо у писателя.
    """
    plugin = _import_plugin()
    monkeypatch.delenv(plugin.STREAM_ENV, raising=False)
    plugin.pytest_configure(_FakeConfig())
    assert plugin._RECORDER is None, (                                   # noqa: SLF001
        "без переменной окружения писатель всё равно создан — плагин не инертен")


def test_a_teardown_failure_keeps_the_plugin_counters_balanced(tmp_path: Path) -> None:
    """Контроль НА КОНТРОЛЬ (мутация M05 пережила проверку ниже).

    Соседний тест мерит СЧЁТЧИКИ ЧИТАТЕЛЯ по рукописной записи; счётчики САМОГО
    плагина — другое число, и оно уезжает в строку `end`. Разойдись они, сверка двух
    источников начнёт печатать расхождение на исправном прогоне, то есть врать
    ровно там, где её и завели. Падение в `teardown` — единственная форма, где один
    тест приносит ДВА отчёта о провале.
    """
    scene = _scene(tmp_path, """
        import pytest

        @pytest.fixture
        def breaks_on_the_way_out():
            yield
            raise RuntimeError("teardown падает")

        def test_passes_then_teardown_breaks(breaks_on_the_way_out): assert True
        def test_plain(): assert True
    """)
    stream = tmp_path / "stream.jsonl"
    subprocess.run(
        [sys.executable, "-m", "pytest", str(scene), "-q", "-p", "no:randomly",
         "-p", _PLUGIN_ARG, "-p", "no:cacheprovider"],
        cwd=str(scene), env={**os.environ, "SPA_PYTEST_STREAM": str(stream),
                             "PYTHONPATH": str(_REPO_ROOT)},
        capture_output=True, text=True, timeout=300,
    )
    end = [e for e in _events(stream) if e.get("e") == "end"]
    assert end, "сессия дошла до конца, а строки `end` нет"
    assert end[0]["started"] == 2, end[0]
    assert end[0]["finished"] == end[0]["started"], (
        f"падение в teardown посчитано вторым завершением: {end[0]}")


# ── 2. Запись НЕ выносит вердикт ──────────────────────────────────────────────

def test_stream_cannot_turn_an_aborted_session_into_a_measured_one(tmp_path: Path) -> None:
    """Главный запрет: 80 тысяч зелёных строк — не вердикт о наборе (инв. #17).

    Без него прибор против инварианта, который он же и стережёт, сам бы его и нарушил.
    """
    stream = tmp_path / "stream.jsonl"
    stream.write_text("\n".join(json.dumps(e) for e in [
        {"e": "session", "t": 1},
        *[{"e": "start", "n": f"t.py::test_{i}"} for i in range(80)],
        *[{"e": "ok", "n": f"t.py::test_{i}", "d": 0.1} for i in range(80)],
    ]) + "\n", encoding="utf-8")
    rc = cv.main([str(tmp_path / "absent.xml"), "--label", "spa_core/tests/",
                  "--stream", str(stream)])
    assert rc == cv.RC_UNMEASURED, (
        "оборванная сессия с зелёной потоковой записью объявлена измеренной — "
        "это ровно подделка доказательства, а не слабое доказательство")


@pytest.mark.parametrize("body,expected_rc", [
    ('<testsuite tests="2" failures="0" errors="0" skipped="0"/>', 0),
    ('<testsuite tests="2" failures="1" errors="0" skipped="0"/>', 1),
])
def test_stream_does_not_move_the_code_of_a_measured_step(
    tmp_path: Path, body: str, expected_rc: int,
) -> None:
    """И в обратную сторону: имена печатаются, а код возврата берётся у junit."""
    junit = tmp_path / "junit.xml"
    junit.write_text(body, encoding="utf-8")
    stream = tmp_path / "stream.jsonl"
    stream.write_text(json.dumps({"e": "fail", "n": "t.py::test_x", "w": "call"}) + "\n",
                      encoding="utf-8")
    assert cv.main([str(junit), "--stream", str(stream)]) == expected_rc


# ── 3. Отсутствие имён — исход, а не «упавших нет» ────────────────────────────

def test_absent_record_is_a_named_outcome_not_an_empty_list(tmp_path: Path) -> None:
    read = cv.read_stream(tmp_path / "nope.jsonl")
    assert not read.read and read.reason, "молчание вместо причины"
    assert "nope.jsonl" in read.reason, read.reason
    printed = cv.format_stream(read, measured=False)
    assert "имена" in printed and "nope.jsonl" in printed, printed


def test_stream_not_requested_is_also_a_named_outcome() -> None:
    read = cv.read_stream(None)
    assert not read.read and "--stream" in read.reason, read.reason


def test_a_torn_tail_line_is_counted_not_silently_dropped(tmp_path: Path) -> None:
    """Процесс убивают ПОСРЕДИ записи — недописанный хвост обязан быть назван числом."""
    stream = tmp_path / "stream.jsonl"
    stream.write_text(
        json.dumps({"e": "start", "n": "t.py::test_a"}) + "\n"
        + json.dumps({"e": "ok", "n": "t.py::test_a", "d": 0.1}) + "\n"
        + '{"e": "start", "n": "t.py::test_b"',                      # оборван
        encoding="utf-8",
    )
    read = cv.read_stream(stream)
    assert read.torn == 1, f"оборванный хвост проглочен молча: {read}"
    assert "1" in cv.format_stream(read, measured=False)


def test_a_record_with_neither_failures_nor_hangs_says_so_out_loud(tmp_path: Path) -> None:
    """Пустой перечень имён обязан быть ФРАЗОЙ, а не отсутствием строк."""
    stream = tmp_path / "stream.jsonl"
    stream.write_text(json.dumps({"e": "session", "t": 1}) + "\n"
                      + json.dumps({"e": "start", "n": "t.py::a"}) + "\n"
                      + json.dumps({"e": "ok", "n": "t.py::a", "d": 0.0}) + "\n",
                      encoding="utf-8")
    printed = cv.format_stream(cv.read_stream(stream), measured=False)
    assert "нечего" in printed, printed


def test_teardown_failure_does_not_double_count_a_finished_test(tmp_path: Path) -> None:
    """Счёт завершённых обязан сходиться со счётом стартов, иначе сверка источников врёт."""
    stream = tmp_path / "stream.jsonl"
    stream.write_text("\n".join(json.dumps(e) for e in [
        {"e": "start", "n": "t.py::a"},
        {"e": "ok", "n": "t.py::a", "d": 0.1},
        {"e": "fail", "n": "t.py::a", "w": "teardown"},
    ]) + "\n", encoding="utf-8")
    read = cv.read_stream(stream)
    assert read.started == 1 and read.finished == 1, (read.started, read.finished)


# ── 4. Сверка двух источников — вопрос, а не второй вердикт ───────────────────

def test_diverging_population_is_named_but_changes_no_code(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuite tests="9" failures="0" errors="0" skipped="0"/>',
                     encoding="utf-8")
    stream = tmp_path / "stream.jsonl"
    stream.write_text(json.dumps({"e": "start", "n": "t.py::a"}) + "\n"
                      + json.dumps({"e": "ok", "n": "t.py::a", "d": 0.0}) + "\n",
                      encoding="utf-8")
    verdict = cv.read_verdict(junit)
    note = cv.cross_check(verdict, cv.read_stream(stream))
    assert note and "9" in note and "1" in note, note
    assert cv.main([str(junit), "--stream", str(stream)]) == cv.RC_GREEN


def test_agreeing_population_says_nothing(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
                     encoding="utf-8")
    stream = tmp_path / "stream.jsonl"
    stream.write_text(json.dumps({"e": "start", "n": "t.py::a"}) + "\n"
                      + json.dumps({"e": "ok", "n": "t.py::a", "d": 0.0}) + "\n",
                      encoding="utf-8")
    assert cv.cross_check(cv.read_verdict(junit), cv.read_stream(stream)) == ""


def test_cross_check_stays_silent_when_there_is_nothing_to_compare(tmp_path: Path) -> None:
    """Нет junit-записи ⇒ сверять не с чем; вопрос без второго операнда не задаётся."""
    assert cv.cross_check(cv.read_verdict(tmp_path / "absent.xml"),
                          cv.read_stream(None)) == ""


# ── 5. ПРОВОДКА: три звена, и каждое обязано краснеть от мутации ──────────────

def _workflow_text() -> str:
    assert _WORKFLOW.exists(), f"воркфлоу не найден: {_WORKFLOW}"
    return _WORKFLOW.read_text(encoding="utf-8")


def _step_block(text: str, name: str) -> str:
    """Тело шага воркфлоу от его `- name:` до следующего `- name:` того же уровня."""
    marker = f"- name: {name}"
    start = text.find(marker)
    assert start != -1, f"шага «{name}» в воркфлоу нет"
    rest = text.find("\n      - name:", start + len(marker))
    return text[start:] if rest == -1 else text[start:rest]


@pytest.mark.parametrize("step,verdict_step", [
    ("Run spa_core unit tests", "Verdict — spa_core/tests/"),
    ("Run scripts/ gate tests + colocated suites", "Verdict — scripts/tests/ + colocated"),
])
def test_the_step_loads_the_plugin_and_hands_the_same_path_to_the_verdict(
    step: str, verdict_step: str,
) -> None:
    """Звено за звеном: плагин загружен · путь объявлен · вердикту отдан ТОТ ЖЕ путь.

    Разорви любое — и шаг вернётся к безымянному обрыву 25.09, ничего при этом не
    сломав: запись просто не появится, а «упавших не названо» прочтётся как «их нет».
    Поэтому проверяется проводка, а не наличие файла плагина.
    """
    text = _workflow_text()
    run_block = _step_block(text, step)
    verdict_block = _step_block(text, verdict_step)

    assert f"-p {_PLUGIN_ARG}" in run_block, (
        f"шаг «{step}» не грузит плагин потоковой записи")
    assert "SPA_PYTEST_STREAM:" in run_block, (
        f"шаг «{step}» не объявляет путь записи")
    declared = run_block.split("SPA_PYTEST_STREAM:")[1].splitlines()[0].strip()
    assert declared, f"шаг «{step}» объявил пустой путь записи"
    assert f"--stream {declared}" in verdict_block, (
        f"шаг вердикта «{verdict_step}» читает НЕ ТОТ путь: объявлено {declared!r}, "
        f"а в вердикте его нет — запись есть, а имён всё равно не будет")


def test_the_plugin_module_is_importable_by_the_name_the_workflow_uses() -> None:
    """`-p <имя>` — это ИМПОРТ: имя, которого не импортировать, валит шаг целиком."""
    assert _PLUGIN.exists(), f"плагина нет: {_PLUGIN}"
    done = subprocess.run(
        [sys.executable, "-c", f"import {_PLUGIN_ARG} as m; print(m.STREAM_ENV)"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip() == "SPA_PYTEST_STREAM", done.stdout


def test_the_env_name_in_the_workflow_is_the_one_the_plugin_reads() -> None:
    """Имя переменной — контракт двух файлов; разойдись они, запись молча не появится."""
    import importlib
    sys.path.insert(0, str(_REPO_ROOT))
    try:
        plugin = importlib.import_module(_PLUGIN_ARG)
    finally:
        sys.path.remove(str(_REPO_ROOT))
    assert f"{plugin.STREAM_ENV}:" in _workflow_text(), (
        f"воркфлоу объявляет не ту переменную, которую читает плагин ({plugin.STREAM_ENV})")
