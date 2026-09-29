"""Единственный источник правды (в Python) для интерпретатора ФЛОТА.

Агентов запускает `scripts/agent_template.sh` строкой
``PYTHON="${SPA_AGENT_PYTHON:-/Users/yuriikulieshov/miniconda3/bin/python3}"``.
Любой Python-код, которому нужен ТОТ ЖЕ интерпретатор — пробы приёмки
(`deployment_acceptance`), самолечение (`self_heal`), запуск агентской цели, —
обязан спрашивать ЗДЕСЬ, а не хардкодить путь у себя: иначе «питон флота»
получает несколько независимых определений, и они молча расходятся (ровно тот
класс дефекта, что `ADAPTER_REGISTRY`-тройка в `.claude/rules/adapters.md`).

Одно имя переменной и один дефолт намеренно ЗЕРКАЛЯТ bash-канон
`agent_template.sh` (два языка — две записи; общий JSON-конфиг ради одной строки
был бы избыточной инфраструктурой). `SPA_AGENT_PYTHON` — тот же override, что
использует флот.
"""
from __future__ import annotations

import os
import sys

#: Тот же override, что читает agent_template.sh.
FLEET_PYTHON_ENV = "SPA_AGENT_PYTHON"

#: Канонический интерпретатор флота — дефолт, зеркалящий agent_template.sh.
#: ЕДИНСТВЕННОЕ место в Python-коде, где этот путь записан.
MINICONDA_DEFAULT = "/Users/yuriikulieshov/miniconda3/bin/python3"


def fleet_python() -> str:
    """Путь к интерпретатору флота.

    Порядок: ``SPA_AGENT_PYTHON`` → канонический miniconda (если он ЕСТЬ на этой
    машине) → ``sys.executable``. Откат к ``sys.executable`` держит вопрос
    осмысленным в CI (ubuntu, miniconda нет): там «флот» — тот же интерпретатор,
    что гонит код, и он несёт ``spa_core``.
    """
    env = os.environ.get(FLEET_PYTHON_ENV)
    if env:
        return env
    if os.path.isfile(MINICONDA_DEFAULT):
        return MINICONDA_DEFAULT
    return sys.executable
