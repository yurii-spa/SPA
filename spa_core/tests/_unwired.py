"""Кто из скриптов с точкой входа никем не вызывается.

Вынесено отдельно, чтобы храповик и его база считались ОДНИМ кодом: база,
построенная другой функцией, разойдётся с проверкой при первой же правке.
"""
from __future__ import annotations

import pathlib
from typing import List

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HAY_DIRS = ("launchd", "scripts", "spa_core", ".github")
_HAY_SUFFIXES = (".sh", ".plist", ".py", ".yml", ".yaml")


def entrypoint_scripts() -> List[pathlib.Path]:
    """Скрипты в `scripts/`, которые можно запустить как программу."""
    out = []
    for p in sorted((_ROOT / "scripts").glob("*.py")):
        try:
            if "__main__" in p.read_text(encoding="utf-8", errors="ignore"):
                out.append(p)
        except OSError:
            continue
    return out


def unwired_scripts() -> List[str]:
    """Имена скриптов, на которые нет НИ ОДНОЙ ссылки вне тестов.

    Ссылкой считается упоминание имени файла или импорта `scripts.<stem>` в
    plist, обёртке, модуле или workflow. Тесты не считаются: тест вызывает
    деталь, а вопрос здесь — включена ли она в проводку (урок цикла #144).
    """
    hay = []
    for d in _HAY_DIRS:
        base = _ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in _HAY_SUFFIXES and "/tests/" not in str(p):
                try:
                    hay.append((p, p.read_text(encoding="utf-8", errors="ignore")))
                except OSError:
                    continue
    orphans = []
    for m in entrypoint_scripts():
        needle_file, needle_mod = m.name, f"scripts.{m.stem}"
        if not any(p != m and (needle_file in t or needle_mod in t) for p, t in hay):
            orphans.append(m.stem)
    return sorted(orphans)
