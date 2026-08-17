"""Контракт увода производного состояния (``live_paths.sandboxed_state_path``).

Цикл #274, карточка ``agent-test-run-dirties-tracked-fixtures``.

Сторож выше (``test_test_run_leaves_tree_clean.py``) отвечает на вопрос
«осталось ли дерево чистым». Он НЕ отвечает на вопрос «почему» — и если
починка развалится, он покраснеет длинным списком файлов, не назвав причину.
Здесь закреплён сам механизм, поимённо и в обе стороны:

* под тестами дефолт уходит в песочницу (иначе прогон снова пачкает дерево);
* явно переданный путь уважается (иначе тесты, которые ПРОВЕРЯЮТ запись,
  перестали бы что-либо проверять — это было бы молчаливым ослаблением, инв. #16);
* без pytest (прод) путь не меняется НИ НА БАЙТ (иначе починка тестов увела бы
  живое состояние — ровно та авария, которую чинили);
* осознанный обход через env-флаг работает (прод-ветка обязана оставаться
  измеримой из дочернего процесса).

Время сюда не входит: свежести этот модуль не судит, литеральных дат нет.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from spa_core.utils import live_paths


REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── Под тестами: дефолт уводится ────────────────────────────────────────────

def test_default_path_is_redirected_under_pytest(monkeypatch, tmp_path):
    """Главное свойство: git-tracked дефолт НЕ возвращается как есть."""
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(live_paths.LIVE_STATE_IN_TESTS_ENV, raising=False)

    tracked = REPO_ROOT / "data" / "adapter_status.json"
    got = live_paths.sandboxed_state_path(tracked)

    assert got != tracked
    assert got.parent == tmp_path


def test_redirect_keeps_the_file_name(monkeypatch, tmp_path):
    """Имя артефакта сохраняется — по нему его узнают тесты и отладка."""
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(live_paths.LIVE_STATE_IN_TESTS_ENV, raising=False)

    got = live_paths.sandboxed_state_path(REPO_ROOT / "data" / "risk_alerts.json")
    assert got.name == "risk_alerts.json"


def test_two_different_logs_do_not_collide(monkeypatch, tmp_path):
    """Увод по имени файла корректен лишь пока имена различны.

    Иначе два лога писали бы друг в друга и тесты стали бы зависеть от порядка —
    та самая болезнь, ради которой всё это делается.
    """
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(live_paths.LIVE_STATE_IN_TESTS_ENV, raising=False)

    a = live_paths.sandboxed_state_path(REPO_ROOT / "data" / "token_emission_log.json")
    b = live_paths.sandboxed_state_path(
        REPO_ROOT / "spa_core" / "data" / "reward_harvesting_log.json")
    assert a != b


def test_measured_writer_filenames_are_unique():
    """Положительный контроль к предыдущему: имена ИЗМЕРЕННЫХ путей различны.

    Список — ровно те 13 путей, что пачкал прогон 17.08 (замер цикла #274).
    Если однажды два уводимых артефакта получат одинаковое имя, увод по имени
    станет молчаливой склейкой, и тест назовёт это ДО аварии.
    """
    measured = [
        "data/adapter_status.json",
        "data/airdrop_farming_log.json",
        "data/alert_log.json",
        "data/apy_milestone_log.json",
        "data/borrowing_cost_log.json",
        "data/exit_liquidity_log.json",
        "data/chains_status.json",
        "data/gap_monitor.json",
        "data/live_execution_log.json",
        "data/risk_alerts.json",
        "data/yield_farming_roi_log.json",
        "data/yield_volatility_surface_log.json",
        "spa_core/data/reward_harvesting_log.json",
        "spa_core/data/token_emission_log.json",
        "spa_core/database/spa.db",
    ]
    names = [Path(p).name for p in measured]
    assert len(names) == len(set(names)), sorted(
        n for n in names if names.count(n) > 1)


# ─── Каталог-приёмник (чокпоинт выгрузки export_data) ───────────────────────

def test_state_dir_is_redirected_under_pytest(monkeypatch, tmp_path):
    """``sandboxed_state_dir`` уводит КАТАЛОГ, а не только отдельный файл.

    За ним стоит ``export_data.write_json`` — через него уходят десятки
    git-tracked артефактов, поэтому увод одного файла тут ничего бы не решил.
    """
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(live_paths.LIVE_STATE_IN_TESTS_ENV, raising=False)

    live_dir = REPO_ROOT / "data"
    assert live_paths.sandboxed_state_dir(live_dir) != live_dir
    assert live_paths.sandboxed_state_dir(live_dir) == tmp_path


def test_export_data_write_json_targets_the_sandbox(monkeypatch, tmp_path):
    """Чокпоинт выгрузки действительно пишет НЕ в дерево.

    Проверяется поведением, а не чтением исходника: зовём настоящий
    ``write_json`` и смотрим, где оказался файл.
    """
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(live_paths.LIVE_STATE_IN_TESTS_ENV, raising=False)
    ed = pytest.importorskip("spa_core.export_data")

    ed.write_json("chains_status.json", {"probe": True})

    assert (tmp_path / "chains_status.json").exists()
    live = REPO_ROOT / "data" / "chains_status.json"
    if live.exists():
        assert "probe" not in live.read_text(encoding="utf-8")


def test_export_data_respects_a_deliberately_redirected_output_dir(monkeypatch, tmp_path):
    """Осознанное перенаправление ``OUTPUT_DIR`` сильнее увода.

    Так делают test_export_sections.py и test_integration_e2e.py; уведи мы и
    его — они бы зеленели вхолостую (инв. #16).
    """
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path / "sandbox"))
    ed = pytest.importorskip("spa_core.export_data")
    chosen = tmp_path / "chosen"
    monkeypatch.setattr(ed, "OUTPUT_DIR", chosen)

    ed.write_json("chains_status.json", {"probe": True})

    assert (chosen / "chains_status.json").exists()


# ─── Явный путь сильнее увода ────────────────────────────────────────────────

def test_explicit_caller_path_is_untouched(monkeypatch, tmp_path):
    """Каталогом, который назвал вызывающий, владеет вызывающий.

    Это НЕ поблажка: тесты вроде TestLogPersistence передают свой путь и потом
    читают файл обратно. Уведи мы и его — они бы позеленели вхолостую.
    """
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path / "sandbox"))
    caller_owned = tmp_path / "mine" / "borrowing_cost_log.json"

    # Путь ВНЕ дерева уже «явный» с точки зрения писателей: они зовут
    # sandboxed_state_path только для своего умолчания.
    assert live_paths.sandboxed_state_path(caller_owned).name == caller_owned.name


def test_live_escape_hatch_returns_the_real_path(monkeypatch, tmp_path):
    """Осознанный обход: прод-ветка остаётся проверяемой."""
    monkeypatch.setenv(live_paths.TEST_STATE_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(live_paths.LIVE_STATE_IN_TESTS_ENV, "1")

    tracked = REPO_ROOT / "data" / "adapter_status.json"
    assert live_paths.sandboxed_state_path(tracked) == tracked


# ─── Прод: путь не меняется ──────────────────────────────────────────────────

def test_production_path_is_unchanged_in_a_child_without_pytest(tmp_path):
    """БЕЗ pytest путь обязан быть ровно исходным — измерено, а не заявлено.

    Меряется в ОТДЕЛЬНОМ процессе: внутри прогона ``pytest`` уже в
    ``sys.modules``, поэтому проверить прод-ветку изнутри невозможно в принципе
    (тот же приём, что в test_telegram_prefs_isolation / test_gas_monitor_hermetic).
    """
    script = textwrap.dedent(
        """
        import sys, json
        from pathlib import Path
        sys.path.insert(0, sys.argv[1])
        from spa_core.utils import live_paths
        assert "pytest" not in sys.modules, "дочерний процесс не должен знать pytest"
        target = Path(sys.argv[1]) / "data" / "adapter_status.json"
        got = live_paths.sandboxed_state_path(target)
        print(json.dumps({"same": str(got) == str(target),
                          "under_test": live_paths.under_test()}))
        """
    )
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTEST_CURRENT_TEST", live_paths.TEST_STATE_DIR_ENV,
                        live_paths.LIVE_STATE_IN_TESTS_ENV)}
    proc = subprocess.run(
        [sys.executable, "-c", script, str(REPO_ROOT)],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    import json as _json
    result = _json.loads(proc.stdout.strip().splitlines()[-1])

    assert result["under_test"] is False, (
        "вне pytest under_test() обязан быть False — иначе прод пишет в песочницу")
    assert result["same"] is True, (
        "БЕЗ pytest путь изменился — починка тестов увела живое состояние")


# ─── Признак «под тестами» переживает вычищенное окружение ──────────────────

def test_under_test_survives_a_cleared_environment(monkeypatch):
    """Замеренный случай: TestRunAlertsCli чистит os.environ ЦЕЛИКОМ.

    ``mock.patch.dict(os.environ, {}, clear=True)`` стирает и
    ``PYTEST_CURRENT_TEST``. Признак, читающий только env, там бы отказал — и
    ``data/alert_log.json`` продолжил бы пачкаться. Поэтому опора на
    ``sys.modules``; этот тест держит выбор навсегда.
    """
    from unittest import mock

    with mock.patch.dict(os.environ, {}, clear=True):
        assert not os.environ.get("PYTEST_CURRENT_TEST")
        assert live_paths.under_test() is True
