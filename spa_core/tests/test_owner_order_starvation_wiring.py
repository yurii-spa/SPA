"""Шаг 0a-голод обязан ДОЙТИ ДО СЕССИИ, а не только существовать.

Дефект-класс (замер цикла #391): `scripts/check_owner_order_starvation.py` доставлен
26.08 вместе с шагом протокола, покрыт 19 зелёными тестами — и **не вызывался ниоткуда**.
Протокол его называл, но `docs/` проводкой намеренно не считается
(`spa_core/tests/_unwired.py`), и храповик неподключённых скриптов красил `main`
именно этим именем. Ровно тот класс, ради которого храповик и заведён: код написан,
доставлен, зелёный — и мёртв.

Проверять здесь надо ПРОВОДКУ, а не деталь: у самого сторожа тесты есть, а падение было
в том, что его никто не звал ([[mutate-the-wiring-not-just-the-parts]] — одна удалённая
точка вызова оставила 1364 теста зелёными). Поэтому измерение — прогон САМОЙ обёртки в
дочернем процессе с подменёнными путями: вердикт сторожа обязан оказаться в промпте,
который обёртка отдаёт сессии. Строка в логе этого не делает — цикл в лог не смотрит.

Обёртка НЕ запускается против живого дерева: копия правится sed'ом (REPO_ROOT, PYTHON,
CLAUDE_BIN, суффикс лога), замок цикла в песочнице отсутствует и обёртка честно идёт
«без защиты», а вместо Claude стоит скрипт, который просто выкладывает свой промпт.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO / "scripts" / "agent_orchestrator.sh"
_GUARD = _REPO / "scripts" / "check_owner_order_starvation.py"


def _sandbox(tmp_path: Path, guard_body: str | None) -> tuple[Path, Path]:
    """Копия обёртки, указывающая на песочницу; возвращает (обёртка, файл промпта)."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    prompt_file = tmp_path / "prompt.txt"

    fake_claude = tmp_path / "fake_claude.sh"
    fake_claude.write_text(
        "#!/bin/bash\n"
        "# -p <prompt> ... — выкладываем ровно то, что обёртка отдала сессии\n"
        f"printf '%s' \"$2\" > {prompt_file}\n"
        "exit 0\n"
    )
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IEXEC)

    if guard_body is not None:
        guard = root / "scripts" / "check_owner_order_starvation.py"
        guard.write_text(guard_body)
        guard.chmod(guard.stat().st_mode | stat.S_IEXEC)

    src = _WRAPPER.read_text()
    src = re.sub(r'^REPO_ROOT=.*$', f'REPO_ROOT="{root}"', src, count=1, flags=re.M)
    src = re.sub(r'^PYTHON=.*$', f'PYTHON="{sys.executable}"', src, count=1, flags=re.M)
    src = re.sub(r'^CLAUDE_BIN=.*$', f'CLAUDE_BIN="{fake_claude}"', src, count=1, flags=re.M)
    dst = tmp_path / "wrapper.sh"
    dst.write_text(src)
    dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
    return dst, prompt_file


def _run(wrapper: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["SPA_ORCHESTRATOR_ARMED"] = "1"
    # Свой лог: без этого тест писал бы в /tmp/spa_orchestrator.log живого агента.
    env["SPA_ORCHESTRATOR_LOG_SUFFIX"] = "_test_" + tmp_path.name
    return subprocess.run(["/bin/bash", str(wrapper)], env=env,
                          capture_output=True, text=True, timeout=120)


_FINDING = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "print('\\U0001F6A8 ГОЛОДАЮЩИЙ ПРИКАЗ ВЛАДЕЛЬЦА: inbox-proba (проба цикла #391)')\n"
    "sys.exit(1)\n"
)
_CLEAN = (
    "#!/usr/bin/env python3\n"
    "print('\\u2705 голодающих critical-приказов владельца (>24ч) не найдено')\n"
)
_BROKEN = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "print('Traceback: сторож сам сломался', file=sys.stderr)\n"
    "sys.exit(7)\n"
)


def test_finding_reaches_the_prompt(tmp_path):
    """Главное: находка ОБЯЗАНА оказаться в промпте, и первой.

    На необёрнутом (доставленном 26.08) файле этот тест краснеет: промпт начинается
    словами «Ты — оркестратор SPA», сторожа в нём нет вовсе.
    """
    wrapper, prompt_file = _sandbox(tmp_path, _FINDING)
    proc = _run(wrapper, tmp_path)
    assert prompt_file.exists(), f"обёртка не дошла до Claude: rc={proc.returncode}\n{proc.stderr[-1500:]}"
    prompt = prompt_file.read_text()
    assert "ГОЛОДАЮЩИЙ ПРИКАЗ ВЛАДЕЛЬЦА" in prompt, (
        "вердикт сторожа голодания не доехал до сессии — он существует, но не читается "
        f"тем, кто выбирает задачу. Промпт начинается так: {prompt[:200]!r}")
    assert "inbox-proba" in prompt, "имя голодающей карточки потеряно по дороге"
    assert prompt.index("ГОЛОДАЮЩИЙ") < prompt.index("Ты — оркестратор SPA"), (
        "находка стоит ПОСЛЕ протокола — шаг 0a-голод по определению идёт до шага 0a")


def test_clean_verdict_does_not_pollute_the_prompt(tmp_path):
    """Контроль в обратную сторону: без голода промпт не меняется.

    Иначе «сторож сработал» было бы неотличимо от «сторож всегда что-то дописывает»,
    и находка перестала бы быть сигналом.
    """
    wrapper, prompt_file = _sandbox(tmp_path, _CLEAN)
    proc = _run(wrapper, tmp_path)
    assert prompt_file.exists(), f"обёртка не дошла до Claude: rc={proc.returncode}\n{proc.stderr[-1500:]}"
    prompt = prompt_file.read_text()
    assert prompt.startswith("Ты — оркестратор SPA"), prompt[:200]
    assert "ГОЛОД" not in prompt.upper()


def test_broken_guard_is_not_measured_not_silence(tmp_path):
    """Сторож упал ⇒ «НЕ ИЗМЕРЕНО» в промпте, а не тишина.

    Тишина читалась бы как «приказ владельца не голодает» — ровно тот fail-OPEN, из-за
    которого critical-приказ простоял четверо суток при 40+ прошедших циклах.
    """
    wrapper, prompt_file = _sandbox(tmp_path, _BROKEN)
    proc = _run(wrapper, tmp_path)
    assert prompt_file.exists(), f"обёртка не дошла до Claude: rc={proc.returncode}\n{proc.stderr[-1500:]}"
    prompt = prompt_file.read_text()
    assert "НЕ ИЗМЕРЕН" in prompt, (
        f"падение сторожа прошло молча — промпт: {prompt[:300]!r}")
    assert "7" in prompt.split("Ты — оркестратор")[0], "код возврата сторожа не назван"


def test_missing_guard_in_a_stale_tree_is_also_not_measured(tmp_path):
    """Прод-дерево отстало от origin ⇒ скрипта нет ⇒ тоже «НЕ ИЗМЕРЕНО».

    Это не гипотеза: обёртка уже несёт такую же ветку для замка цикла и для
    deliver-new — прод синкается отдельным шагом и регулярно отстаёт.
    """
    wrapper, prompt_file = _sandbox(tmp_path, None)
    proc = _run(wrapper, tmp_path)
    assert prompt_file.exists(), f"обёртка не дошла до Claude: rc={proc.returncode}\n{proc.stderr[-1500:]}"
    prompt = prompt_file.read_text()
    assert "НЕ ИЗМЕРЕН" in prompt


def test_the_real_guard_exists_where_the_wrapper_looks_for_it():
    """Песочница подменяет пути — значит, реальный путь надо закрепить отдельно.

    Без этого все четыре теста выше остались бы зелёными, даже если бы обёртка звала
    несуществующее имя: они проверяют ПОВЕДЕНИЕ ветки, а не адрес.
    """
    assert _GUARD.exists(), f"обёртка зовёт {_GUARD}, а его нет"
    src = _WRAPPER.read_text()
    assert "scripts/check_owner_order_starvation.py" in src
    assert "${STARVE_PREFIX}" in src, (
        "вердикт сторожа никуда не вклеивается — вызов без потребителя это тот же "
        "мёртвый код, только на шаг дальше")
