#!/usr/bin/env python3
"""Единственный источник правды для статического гейта mypy (карточка
``agent-task-krasnyi-ci-lite-nevidim-geit-mypy-zhivet``, цикл #107).

**Зачем отдельный файл.** Раньше гейт жил ОДНОЙ inline-командой в шаге
``Type check — mypy on key modules`` файла ``.github/workflows/ci-lite.yml``.
Замер цикла #95: ``SPA CI-Lite`` простоял красным ~8.5 часов и этого никто не
увидел — четыре автономных цикла (#92–#95) сверяли «CI на main» по ``SPA Tests``
и ``SPA CI``, а третий workflow в эту формулировку не попадал. Плюс ``ci-lite``
запускается только по расписанию (раз в 6 часов) и вручную — то есть между
пушем и первым срабатыванием гейта проходили часы.

Список модулей и флаги вынесены сюда, чтобы гейт можно было позвать ИЗ ДВУХ
мест одним и тем же кодом: из workflow (``python3 scripts/mypy_gate.py``) и из
pytest (``tests/test_mypy_gate.py``), который крутится в том CI, который циклы
реально смотрят. Два места — один список; продублировать список значило бы
завести расхождение, которое никто не заметит (ровно класс «проверка
утверждает то, чего не измеряла»).

**Fail-CLOSED (инв. #2).** Отсутствие mypy — это НЕ «проверка пройдена» и не
повод для skip: ``run()`` возвращает ненулевой код и называет причину. Ср.
``scripts/type_check.sh`` — тот advisory-помощник глушит вывод через ``|| true``
и при отсутствии mypy уходит в эвристику, то есть НЕ МОЖЕТ упасть; он не гейт.

Только stdlib. Сети нет. Ничего не пишет в репозиторий (кэш mypy — в каталоге,
который задаёт вызывающий).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Ключевые модули money-path + общие типы. Список СУЖАТЬ нельзя молча:
# `tests/test_mypy_gate.py` пиннит и непустоту, и существование каждого файла.
MODULES: tuple[str, ...] = (
    "spa_core/paper_trading/cycle_runner.py",
    "spa_core/allocator/allocator.py",
    "spa_core/risk/policy.py",
    "spa_core/utils/type_utils.py",
)

FLAGS: tuple[str, ...] = (
    "--ignore-missing-imports",
    "--no-strict-optional",
    "--explicit-package-bases",
    "--follow-imports=silent",
)


def gate_argv(cache_dir: str | None = None) -> list[str]:
    """Полная командная строка гейта (без интерпретатора)."""
    argv = ["-m", "mypy", *MODULES, *FLAGS]
    if cache_dir:
        argv.append(f"--cache-dir={cache_dir}")
    return argv


def mypy_available() -> bool:
    """Установлен ли mypy в ТЕКУЩЕМ интерпретаторе."""
    proc = subprocess.run(
        [sys.executable, "-c", "import mypy"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return proc.returncode == 0


def run(cache_dir: str | None = None, timeout: float = 300.0) -> tuple[int, str]:
    """Прогнать гейт. Возвращает ``(returncode, вывод)``.

    Ненулевой код = гейт НЕ пройден. Отсутствие mypy тоже даёт ненулевой код —
    молчаливого «ну и ладно» здесь нет (инв. #2).
    """
    if not mypy_available():
        return 127, (
            "mypy НЕ УСТАНОВЛЕН в этом интерпретаторе "
            f"({sys.executable}) — гейт типов НЕ ВЫПОЛНЕН.\n"
            "Это КРАСНЫЙ, а не skip: пропущенная проверка, объявленная "
            "пройденной, — тот самый fail-OPEN, ради которого гейт и заводился.\n"
            "Установить: pip install mypy==2.1.0"
        )

    env = dict(os.environ)
    env.setdefault("SPA_ENV", "ci")
    env["MYPYPATH"] = str(REPO_ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, *gate_argv(cache_dir)],
            cwd=REPO_ROOT, capture_output=True, text=True,
            env=env, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"mypy не уложился в {timeout}с — гейт НЕ выполнен (fail-CLOSED)"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    print("=== Type check: mypy on key modules (scripts/mypy_gate.py) ===")
    for m in MODULES:
        print(f"  {m}")
    rc, out = run()
    print(out.rstrip())
    print("Type check PASSED" if rc == 0 else f"Type check FAILED (rc={rc})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
