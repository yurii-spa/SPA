"""Прогон тестов НЕ ИМЕЕТ ПРАВА пачкать git-tracked файлы.

Цикл #274 (2026-08-17), карточка ``agent-test-run-dirties-tracked-fixtures``.

Зачем этот сторож
=================
До починки прогон ``pytest spa_core/tests/`` оставлял ``git status`` с
ТРИНАДЦАТЬЮ изменёнными git-tracked файлами (``data/adapter_status.json``,
``data/risk_alerts.json``, ``spa_core/data/token_emission_log.json``,
``spa_core/database/spa.db`` и другими). Следствия, ради которых это чинится:

1. **«Чистое дерево» переставало быть сигналом.** Именно им цикл отделяет свои
   правки от чужих перед пушем — а после любого прогона оно заведомо грязное.
2. **Опубликованная фикстура тихо сдвигает ожидания других тестов** — набор
   становится зависимым от порядка.

Починка (увод дефолтных путей в песочницу: ``live_paths.sandboxed_state_path``
и ``tracked_db_guard``) держится ровно до тех пор, пока её кто-нибудь
не обойдёт новым писателем. Поэтому здесь стоит сторож, а не запись в журнале.

Чем этот сторож отличается от «украшения»
=========================================
Он МЕРЯЕТ, а не пересказывает: поднимает НАСТОЯЩИЙ дочерний ``pytest`` на
канареечном срезе (те самые файлы, что были измерены как писатели), и сверяет
байты трекаемых артефактов до и после. Положительный контроль —
``test_positive_control_*``: он воспроизводит исходную аварию (запись в
трекаемый путь) и требует, чтобы детектор её УВИДЕЛ; детектор, никогда не
видевший настоящей поломки, ничего не гарантирует.

Дочерний процесс, а не текущий: наблюдать «чисто ли дерево после прогона»
изнутри того же прогона нельзя — соседние тесты ещё не отработали, и результат
зависел бы от порядка сборки. Дочерний процесс даёт замкнутый, воспроизводимый
интервал наблюдения.

Если что-то всё же записалось, сторож **возвращает байты на место** и только
потом краснеет: диагностика не имеет права оставлять дерево хуже, чем нашла.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Каталоги, где живут трекаемые артефакты состояния. Именно их пачкал прогон.
_WATCHED_DIRS = ("data", "spa_core/data", "spa_core/database")

#: Канареечный срез: файлы, ИЗМЕРЕННЫЕ как писатели 13 трекаемых путей
#: (инструментированный прогон, обёртки вокруг open/os.replace/sqlite3.connect).
#: Один только test_cash_attribution_policy_refusals пачкал девять путей.
_CANARY = (
    "spa_core/tests/test_cash_attribution_policy_refusals.py",
    "spa_core/tests/test_borrowing_cost_optimizer.py",
    "spa_core/tests/test_airdrop_farming_value_estimator.py",
    "spa_core/tests/test_alerts.py",
    "spa_core/tests/test_api.py",
    # Найден уже ЭТИМ сторожем, а не первым замером: инструментированный прогон
    # был прерван на 9 %, и писателя ``data/live_execution_log.json`` он не
    # успел увидеть. Честная запись о границах замера — и повод, по которому
    # канареечный срез обязан расти вместе с находками.
    "spa_core/tests/test_engine_bridge.py",
    # Семейство ``spa_core/analytics/*`` — 59+ путей ``data/<анализатор>_log.json``,
    # которые всплывали только за 20 %-й отметкой полного прогона и потому не
    # попали ни в карточку, ни в первый замер. Здесь — по одному представителю
    # каждой формы писателя, измеренной при уводе (цикл #275):
    "spa_core/tests/test_bridge_risk_assessor.py",        # Path-писатель, тип пути
    "spa_core/tests/test_defi_impermanent_loss_hedging_analyzer.py",  # monkeypatch константы
    "spa_core/tests/test_protocol_insider_activity_monitor.py",       # ``log_file=None``
    "spa_core/tests/test_defi_protocol_depositor_concentration_analyzer.py",  # cfg-словарь
)


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(_REPO_ROOT)) + args,
        capture_output=True, text=True, check=True,
    ).stdout


def _tracked_state_files() -> list[Path]:
    """Git-tracked файлы в наблюдаемых каталогах (пути от корня репозитория)."""
    out = _git("ls-files", "-z", *_WATCHED_DIRS)
    return [_REPO_ROOT / rel for rel in out.split("\0") if rel]


def _snapshot(paths) -> dict[Path, bytes | None]:
    """Байты каждого файла (None — файла нет). Байты, а не mtime: mtime меняется
    и от безобидного touch, а нас интересует именно СОДЕРЖИМОЕ."""
    snap: dict[Path, bytes | None] = {}
    for p in paths:
        try:
            snap[p] = p.read_bytes()
        except FileNotFoundError:
            snap[p] = None
    return snap


def _diff(before: dict[Path, bytes | None], after: dict[Path, bytes | None]) -> list[str]:
    """Имена файлов, чьё содержимое изменилось (относительно корня репо)."""
    changed = []
    for p, was in before.items():
        now = after.get(p)
        if was != now:
            changed.append(str(p.relative_to(_REPO_ROOT)))
    return sorted(changed)


def _restore(before: dict[Path, bytes | None], changed: list[str]) -> None:
    """Вернуть изменённые файлы к исходным байтам (сторож не мусорит)."""
    for rel in changed:
        p = _REPO_ROOT / rel
        was = before.get(p)
        if was is None:
            try:
                p.unlink()
            except OSError:
                pass
        else:
            p.write_bytes(was)


@pytest.fixture(scope="module")
def tracked_state_files():
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("не git-чекаут — сверять с индексом нечего")
    try:
        files = _tracked_state_files()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("git недоступен в этом окружении")
    if not files:
        pytest.skip("в наблюдаемых каталогах нет трекаемых файлов (пустой чекаут)")
    return files


# ─── Сам сторож ──────────────────────────────────────────────────────────────

def test_canary_pytest_run_leaves_tracked_state_untouched(tracked_state_files):
    """Дочерний прогон писателей НЕ меняет ни одного трекаемого файла.

    Краснеет, когда появляется новый писатель: ему достаточно попасть в
    канареечный срез или в тот же веер (``run_cycle`` тянет за собой всю
    аналитику через ``signal_aggregator``), и байты разойдутся.
    """
    before = _snapshot(tracked_state_files)

    env = dict(os.environ)
    # Дочерний прогон обязан быть таким же, как обычный: никаких послаблений,
    # иначе сторож проверял бы не ту конфигурацию, что гоняет CI.
    env["PYTHONHASHSEED"] = "0"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *_CANARY],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, env=env,
    )

    after = _snapshot(tracked_state_files)
    changed = _diff(before, after)
    _restore(before, changed)

    assert proc.returncode == 0, (
        "канареечный срез сам по себе красный — сначала почини его:\n"
        + proc.stdout[-3000:] + proc.stderr[-2000:]
    )
    assert not changed, (
        "прогон тестов ИЗМЕНИЛ git-tracked файлы — «чистое дерево» перестало "
        "быть сигналом перед пушем:\n  " + "\n  ".join(changed)
        + "\n\nПочини ПИСАТЕЛЯ, а не этот сторож: путь по умолчанию должен "
          "уводиться в песочницу (spa_core/utils/live_paths.sandboxed_state_path), "
          "а явно переданный путь — уважаться. Байты уже возвращены на место."
    )


# ─── Положительный контроль: детектор действительно детектирует ──────────────

def test_positive_control_detector_sees_a_tracked_write(tracked_state_files):
    """Воспроизводит АВАРИЮ: запись в трекаемый файл обязана быть замечена.

    Без этого теста сторож выше — украшение: он зелен и когда всё хорошо, и
    когда сравнение сломано (например, снимок пуст и сравнивать нечего).
    Здесь мы портим файл своими руками и требуем, чтобы ``_diff`` его назвал,
    а ``_restore`` вернул байты обратно.
    """
    victim = tracked_state_files[0]
    before = _snapshot(tracked_state_files)

    original = before[victim]
    victim.write_bytes((original or b"") + "\n# положительный контроль\n".encode())

    after = _snapshot(tracked_state_files)
    changed = _diff(before, after)

    rel = str(victim.relative_to(_REPO_ROOT))
    try:
        assert rel in changed, (
            "детектор НЕ увидел запись в трекаемый файл — сторож выше ничего "
            "не гарантирует"
        )
    finally:
        _restore(before, changed)

    # И обратная сторона: восстановление действительно вернуло байты.
    assert victim.read_bytes() == original, (
        "_restore не вернул исходные байты — сторож оставляет дерево грязным"
    )
    assert not _diff(before, _snapshot(tracked_state_files)), (
        "после восстановления расхождений быть не должно"
    )


def test_positive_control_detector_is_quiet_when_nothing_changes(tracked_state_files):
    """Контроль в ОБРАТНУЮ сторону: без записи детектор молчит.

    Иначе «краснеет всегда» неотличимо от «краснеет по делу», и первый же
    ложный прогон научит всех его отключать.
    """
    before = _snapshot(tracked_state_files)
    assert _diff(before, _snapshot(tracked_state_files)) == []
