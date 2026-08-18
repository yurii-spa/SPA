"""Сторож для инструмента, который отличает ПЛАТО набора от ПОМЕХИ.

Каждый тест ниже — воспроизведение настоящей аварии 14–18.08, а не украшение.

Авария: цикл #226 замерил прирост лога у двух прогонов приёмки, идущих рядом, и
получил «~2 байта за 15 минут» против «18 332 байта за 60 с» у одиночного. Вывод
записали в карточку: прогоны сериализует общий ресурс вне worktree, приёмку гонять
по очереди. Цикл #289 перемерил: те две цифры сняты в РАЗНЫХ МЕСТАХ набора, а не в
двух условиях. Одиночный прогон БЕЗ СОСЕДЕЙ встаёт на том же месте на те же ~150 с
(`spa_core/tests/test_cycle_nav_determinism.py` — шесть тестов, 151.26 с соло).
Настоящая цена соседства на одной и той же цели — ×1.5 (227 с против 151 с), то есть
два прогона рядом дешевле двух по очереди, и правило «по очереди» было бы вредным.

Поэтому проверяется ПОВЕДЕНИЕ вердикта на тех самых числах, а не текст правила.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "spa_core" / "tests" / "acceptance_plateau_baseline.json"
SCRIPT = ROOT / "spa_core" / "monitoring" / "stalled_run_diagnosis.py"

# Числа настоящего замера 18.08 (цикл #289) — не выдуманная фикстура.
STALL_FILE = "spa_core/tests/test_cycle_nav_determinism.py"
STALL_AFTER = 9577          # тестов завершено в момент остановки
STALL_SECONDS = 150.0       # столько прогон стоял, соседей не было
SOLO_SECONDS = 151.0        # `6 passed in 151.26s` на чистом origin/main


def _load():
    spec = importlib.util.spec_from_file_location("_stalled_run_diagnosis", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _load()


@pytest.fixture(scope="module")
def live_baseline(tool):
    return tool.load_baseline(json.loads(BASELINE_PATH.read_text(encoding="utf-8")))


def _progress(n_done: int) -> str:
    """stdout `pytest -q` после n завершённых тестов — как его печатает pytest."""
    lines, left = [], n_done
    while left >= 72:
        lines.append("." * 72 + f" [ {min(99, 100 * (n_done - left + 72) // max(n_done, 1))}%]")
        left -= 72
    if left:
        lines.append("." * left)
    return "\n".join(lines) + "\n"


def _collected(n_before: int, stall_file: str = STALL_FILE) -> str:
    """Список собранных тестов, где тест номер n_before+1 лежит в `stall_file`."""
    head = [f"spa_core/tests/test_filler.py::test_{i}" for i in range(n_before)]
    tail = [f"{stall_file}::test_nav_conservation_property",
            f"{stall_file}::test_kill_switch_case_is_all_cash_and_conserves",
            "spa_core/tests/test_after.py::test_z"]
    return "\n".join(head + tail) + "\n\n3 tests collected in 0.5s\n"


# --------------------------------------------------------------------------
# 1. Сама авария: остановка на плато называется исправностью
# --------------------------------------------------------------------------

def test_the_real_stall_of_18_08_is_named_a_plateau(tool, live_baseline):
    """Ровно тот вход, на котором 14.08 был дан неверный ответ «помеха»."""
    out = tool.diagnose(_progress(STALL_AFTER), _collected(STALL_AFTER),
                        STALL_SECONDS, live_baseline)
    assert out["verdict"] == tool.PLATEAU, out
    assert out["current"].startswith(STALL_FILE)
    assert out["completed"] == STALL_AFTER


def test_positive_control_without_the_measurement_the_wrong_answer_returns(tool):
    """Снимаем базу — и инструмент выдаёт РОВНО прежний неверный вывод «ищи помеху».

    Это обратный конец проверки: если бы вердикт не зависел от замера, тест был бы
    зелёным и на неисправленном поведении.
    """
    out = tool.diagnose(_progress(STALL_AFTER), _collected(STALL_AFTER),
                        STALL_SECONDS, {})
    assert out["verdict"] == tool.CONTENTION, out
    assert STALL_FILE in out["reason"]


def test_plateau_does_not_blind_the_tool_beyond_its_budget(tool, live_baseline):
    """Плато объясняет 150 с, но не полчаса: за бюджетом снова «ищи помеху»."""
    budget = live_baseline[STALL_FILE]["budget_seconds"]
    out = tool.diagnose(_progress(STALL_AFTER), _collected(STALL_AFTER),
                        budget + 1, live_baseline)
    assert out["verdict"] == tool.CONTENTION, out


def test_exactly_at_the_budget_is_still_a_plateau(tool, live_baseline):
    budget = live_baseline[STALL_FILE]["budget_seconds"]
    out = tool.diagnose(_progress(STALL_AFTER), _collected(STALL_AFTER),
                        budget, live_baseline)
    assert out["verdict"] == tool.PLATEAU, out


def test_a_file_outside_the_baseline_is_a_contention_candidate(tool, live_baseline):
    out = tool.diagnose(_progress(STALL_AFTER),
                        _collected(STALL_AFTER, "spa_core/tests/test_unknown.py"),
                        STALL_SECONDS, live_baseline)
    assert out["verdict"] == tool.CONTENTION, out


# --------------------------------------------------------------------------
# 2. Fail-CLOSED: «не измерено» никогда не выдаёт себя за «всё хорошо»
# --------------------------------------------------------------------------

def test_empty_collect_list_is_unmeasured_not_a_plateau(tool, live_baseline):
    out = tool.diagnose(_progress(STALL_AFTER), "", STALL_SECONDS, live_baseline)
    assert out["verdict"] == tool.UNMEASURED, out


def test_progress_longer_than_the_collect_list_is_unmeasured(tool, live_baseline):
    """Прогресс и список от разных прогонов — угадывать нечего."""
    out = tool.diagnose(_progress(50), _collected(2), STALL_SECONDS, live_baseline)
    assert out["verdict"] == tool.UNMEASURED, out


def test_negative_stall_is_unmeasured(tool, live_baseline):
    out = tool.diagnose(_progress(STALL_AFTER), _collected(STALL_AFTER), -1.0, live_baseline)
    assert out["verdict"] == tool.UNMEASURED, out


# --------------------------------------------------------------------------
# 3. Счёт завершённых тестов: сводка и предупреждения — не тесты
# --------------------------------------------------------------------------

def test_summary_and_warnings_are_not_counted_as_tests(tool):
    clean = _progress(144)
    noisy = (clean
             + "=========== warnings summary ===========\n"
             + "spa_core/tests/x.py::test_y: DeprecationWarning: ...\n"
             + "6 passed in 151.26s (0:02:31)\n")
    assert tool.completed_tests(noisy) == tool.completed_tests(clean) == 144


def test_percent_marker_is_stripped_not_counted(tool):
    assert tool.completed_tests("..... [100%]\n") == 5


def test_non_dot_outcomes_count_as_finished_tests(tool):
    """`s`/`x`/`F`/`E` — тоже завершённые тесты; иначе позиция уедет на пропусках."""
    assert tool.completed_tests(".sxF.E [ 12%]\n") == 6


def test_empty_progress_means_the_first_test_is_running(tool, live_baseline):
    out = tool.diagnose("", _collected(0), 1.0, live_baseline)
    assert out["completed"] == 0
    assert out["current"].startswith(STALL_FILE)


# --------------------------------------------------------------------------
# 4. База плато: объявление без замера — это и есть тот дефект
# --------------------------------------------------------------------------

@pytest.mark.parametrize("broken, why", [
    ({"plateaus": {"a.py": {"solo_seconds": 10, "budget_seconds": 20}}}, "нет evidence"),
    ({"plateaus": {"a.py": {"solo_seconds": 10, "budget_seconds": 20, "evidence": "  "}}},
     "пустой evidence"),
    ({"plateaus": {"a.py": {"budget_seconds": 20, "evidence": "x"}}}, "нет solo_seconds"),
    ({"plateaus": {"a.py": {"solo_seconds": 0, "budget_seconds": 20, "evidence": "x"}}},
     "нулевой замер"),
    ({"plateaus": {"a.py": {"solo_seconds": 30, "budget_seconds": 10, "evidence": "x"}}},
     "бюджет меньше замера"),
    ({"plateaus": "нет"}, "plateaus не объект"),
    ({}, "нет plateaus"),
])
def test_baseline_refuses_a_plateau_claimed_without_a_measurement(tool, broken, why):
    with pytest.raises(ValueError):
        tool.load_baseline(broken)


def test_live_baseline_parses_and_every_named_file_exists(tool, live_baseline):
    """Плато, названное несуществующим файлом, оправдывало бы что угодно и ничего."""
    assert live_baseline, "живая база пуста — плато 18.08 замерено, оно обязано быть в ней"
    for path in live_baseline:
        assert (ROOT / path).is_file(), f"база плато называет несуществующий файл: {path}"


def test_live_baseline_budget_covers_the_measured_parallel_cost(tool, live_baseline):
    """Бюджет обязан покрывать ИЗМЕРЕННУЮ цену соседства (×1.9 худшая), иначе
    исправный параллельный прогон будет объявлен помехой."""
    entry = live_baseline[STALL_FILE]
    assert entry["solo_seconds"] == pytest.approx(SOLO_SECONDS, abs=1.0)
    assert entry["budget_seconds"] >= entry["solo_seconds"] * 1.9


# --------------------------------------------------------------------------
# 5. CLI: коды возврата — единственный канал для вызывающего
# --------------------------------------------------------------------------

def _cli(tmp_path, progress, collected, stalled, baseline_obj=None):
    p = tmp_path / "progress.log"; p.write_text(progress, encoding="utf-8")
    c = tmp_path / "collected.txt"; c.write_text(collected, encoding="utf-8")
    argv = ["--progress", str(p), "--collected", str(c), "--stalled-for", str(stalled)]
    if baseline_obj is not None:
        b = tmp_path / "baseline.json"
        b.write_text(json.dumps(baseline_obj, ensure_ascii=False), encoding="utf-8")
        argv += ["--baseline", str(b)]
    return subprocess.run([sys.executable, str(SCRIPT), *argv],
                          capture_output=True, text=True)


def test_cli_returns_zero_on_a_plateau(tmp_path):
    r = _cli(tmp_path, _progress(STALL_AFTER), _collected(STALL_AFTER), STALL_SECONDS)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PLATEAU" in r.stdout


def test_cli_returns_one_when_the_plateau_does_not_explain_it(tmp_path):
    r = _cli(tmp_path, _progress(STALL_AFTER),
             _collected(STALL_AFTER, "spa_core/tests/test_unknown.py"), STALL_SECONDS)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CONTENTION_CANDIDATE" in r.stdout


def test_cli_returns_two_when_the_baseline_is_unreadable(tmp_path):
    r = _cli(tmp_path, _progress(STALL_AFTER), _collected(STALL_AFTER), STALL_SECONDS,
             baseline_obj={"plateaus": {"a.py": {"solo_seconds": 1}}})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "UNMEASURED" in r.stdout
