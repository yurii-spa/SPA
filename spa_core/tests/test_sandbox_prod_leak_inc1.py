"""C8 (ADR-580) — положительный контроль, реплей INC-1.

Прод-агент ``com.spa.decision_loop`` зовёт G97-зонд (``artifact_stamp_clock_doors.py``)
в одноразовом дереве; зонд выставляет свои ``SPA_STAMP_*``, но НЕ
``SPA_DATA_DIR``/``SPA_LIVE_ROOT``, и производитель, резолвящий путь через
``spa_core.utils.live_paths`` без СВОЕГО параметра, уводил запись в прод:
``data/owner_decision_pending.json`` получил ``generated_at: 2041-11-23T19:53:29Z`` —
якорь инъекции зонда (``docs/rm_truth/REVIEW_1.md``, п. 1). Содержание перезаписал
следующий же цикл `agent_health`, но тридцать три минуты запись была в проде.

Этот набор реплеит аварию ЧЕСТНО: реальный ``owner_decision_pending.run()`` (тот же
вызов, что упал 05.10) зовётся ВНУКОВЫМ процессом с ``HOME``, подменённым на
временную «домашнюю» директорию — ``live_paths.DEFAULT_LIVE_ROOT`` считается от
``Path.home()``, поэтому фальшивый ``HOME`` даёт фальшивый «прод» без единой правки
кода и без риска для настоящего прод-дерева.

Три контроля:

* :func:`test_harness_without_sandbox_vars_refuses_instead_of_leaking` — форма АВАРИИ:
  маркер песочницы есть (как у зонда), а ``SPA_DATA_DIR``/``SPA_LIVE_ROOT`` харнесс
  забыл (ровно то, что произошло 05.10). ОЖИДАНИЕ: процесс падает с
  ``SandboxLeakError``, «прод»-файл НЕ меняется.
* :func:`test_correctly_wired_harness_writes_into_its_own_sandbox` — форма ПОЧИНКИ
  (b): харнесс выставил все три переменные. ОЖИДАНИЕ: запись уходит в песочницу,
  «прод»-файл НЕ меняется (и это уже не отказ, а успешная работа).
* :func:`test_without_the_destination_guard_the_scene_would_have_leaked` — контроль
  «метка нашла бы АВАРИЮ, если бы проверки не было»: та же сцена, но проверка (a)
  симулированно отключена ПАРАМЕТРОМ (``monkeypatch`` на внутреннюю функцию, а не
  правка исходника) — и путь действительно разрешается в фальшивый прод. Без этого
  контроля первый тест мог бы быть зелёным просто потому, что фальшивый прод не
  существует вовсе; так — доказано, что именно ПРОВЕРКА останавливает запись, а не
  случайность сцены.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.utils import live_paths as LP

# FROZEN-DATE-OK: sentinel-content — the only literal date in this file
# ("2020-01-01T00:00:00+00:00" in `_fake_prod`) is pre-existing FILE CONTENT the
# test writes to the fake "prod" path and then compares BYTE-FOR-BYTE
# (`target.read_bytes() == before`) to prove the leak guard left it untouched.
# No code under test ever reads it as a timestamp or compares it to any clock —
# it is a sentinel value, not a freshness measurement, so the calendar cannot
# move it into or out of staleness. The INC-1 anchor itself
# ("2041-11-23T19:53:29Z", the G97-probe stamp that actually leaked) lives only
# in this docstring as prose, never as code the detector would match.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_prod(tmp_path: Path, name: str) -> tuple[Path, Path, bytes]:
    """Фальшивый «прод»: ``<home>/Documents/SPA_Claude/data/owner_decision_pending.json``
    с заведомым содержимым — чтобы неизменность было чем доказать."""
    fake_home = tmp_path / name
    fake_prod = fake_home / "Documents" / "SPA_Claude"
    (fake_prod / "data").mkdir(parents=True)
    pre_existing = {"generated_at": "2020-01-01T00:00:00+00:00",
                    "sentinel": "untouched-by-sandbox"}
    target = fake_prod / "data" / "owner_decision_pending.json"
    target.write_text(json.dumps(pre_existing), encoding="utf-8")
    return fake_home, fake_prod, target.read_bytes()


def _run_owner_decision_pending(env: dict, *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c",
         "from spa_core.monitoring.owner_decision_pending import run; run()"],
        env=env, capture_output=True, text=True, timeout=timeout)


def test_harness_without_sandbox_vars_refuses_instead_of_leaking(tmp_path):
    """Реплей аварии: маркер есть, ``SPA_DATA_DIR``/``SPA_LIVE_ROOT`` харнесс не
    выставил (ровно форма INC-1) — отказ, а НЕ тихая запись в прод."""
    fake_home, fake_prod, before = _fake_prod(tmp_path, "home_leak")
    target = fake_prod / "data" / "owner_decision_pending.json"
    before_mtime = target.stat().st_mtime

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    # Маркер зонда — БЕЗ SPA_DATA_DIR/SPA_LIVE_ROOT. Это и есть упущение,
    # из-за которого 05.10 запись ушла в настоящий прод.
    env[LP.PROBE_TREE_ENV] = str(tmp_path / "sandbox_tree_unused")
    env.pop(LP.DATA_DIR_ENV, None)
    env.pop(LP.LIVE_ROOT_ENV, None)

    proc = _run_owner_decision_pending(env)

    assert proc.returncode != 0, (
        "харнесс без SPA_DATA_DIR/SPA_LIVE_ROOT обязан падать, а не тихо писать")
    assert "SandboxLeakError" in proc.stderr, proc.stderr[-500:]
    assert target.read_bytes() == before, "«прод»-файл изменился — защита не сработала"
    assert target.stat().st_mtime == before_mtime, "mtime сдвинулся — файл трогали"


def test_correctly_wired_harness_writes_into_its_own_sandbox(tmp_path):
    """Форма починки C8(b): харнесс выставил все три переменные — запись уходит
    в песочницу, прод не трогается, процесс завершается успехом."""
    fake_home, fake_prod, before = _fake_prod(tmp_path, "home_fixed")
    target = fake_prod / "data" / "owner_decision_pending.json"

    sandbox_tree = tmp_path / "sandbox_tree"
    (sandbox_tree / "data").mkdir(parents=True)

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    env[LP.SANDBOX_ENV] = "1"
    env[LP.LIVE_ROOT_ENV] = str(sandbox_tree)
    env[LP.DATA_DIR_ENV] = str(sandbox_tree / "data")

    proc = _run_owner_decision_pending(env)

    assert proc.returncode == 0, proc.stderr[-1000:]
    assert (sandbox_tree / "data" / "owner_decision_pending.json").is_file(), (
        "правильно сконфигурированный харнесс обязан писать В СЕБЯ")
    assert target.read_bytes() == before, "«прод»-файл не должен трогаться вообще"


def test_without_the_destination_guard_the_scene_would_have_leaked(monkeypatch, tmp_path):
    """Контроль на саму сцену: без проверки (a) путь ДЕЙСТВИТЕЛЬНО уводит в прод.

    Снимаем ТОЛЬКО проверку маркера (параметром — `monkeypatch`, без правки
    исходника), оставляя всё остальное как в первом тесте. Если бы этот контроль
    был зелёным просто потому, что фальшивого прода нет, первый тест прошёл бы
    по случайности сцены, а не по работе защиты. Он не зелёный: путь РАВЕН
    фальшивому проду.
    """
    fake_home, fake_prod, _ = _fake_prod(tmp_path, "home_control")
    monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
    monkeypatch.setenv(LP.PROBE_TREE_ENV, str(tmp_path / "sandbox_tree_unused"))
    monkeypatch.delenv(LP.DATA_DIR_ENV, raising=False)
    monkeypatch.delenv(LP.LIVE_ROOT_ENV, raising=False)
    # Откат (a): маркер видят все, но функция, которая на него смотрит,
    # притворяется, что его нет.
    monkeypatch.setattr(LP, "_sandbox_marker_active", lambda: False)

    leaked_to = LP.live_data_dir(tmp_path / "caller")

    assert leaked_to == fake_prod / "data", (
        "без проверки (a) умолчание ОБЯЗАНО попасть в прод-путь — если здесь не "
        "прод, сцена не воспроизводит аварию, и первый тест ничего не доказывает")
