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

    # Классификатор вердикта — НАСТОЯЩИЙ, не подставной: песочница подменяет сторожа, чтобы
    # задать (код, вывод), а решение по этой паре обязан принимать доставляемый код.
    # Без копии обёртка уходит в ветку «библиотеки нет» и печатает «НЕ ИЗМЕРЕНО» ВСЕГДА —
    # и тогда три теста ниже зеленеют ВАКУУМНО: они ищут в промпте подстроку, которая есть
    # и в эхо-выводе сторожа. Замерено при доставке ADR-347: без этих трёх строк
    # `test_finding_reaches_the_prompt` проходит на обёртке, не классифицирующей ничего.
    (root / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(_REPO / "scripts" / "lib" / "starvation_verdict.sh",
                 root / "scripts" / "lib" / "starvation_verdict.sh")

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
    # Находка — ТРОЙКА. Единица отдана интерпретатору: см. _CRASHED_REALLY ниже.
    "sys.exit(3)\n"
)
_CLEAN = (
    "#!/usr/bin/env python3\n"
    "print('\\u2705 голодающих critical-приказов владельца (>24ч) не найдено')\n"
)
#: Поломка, ВЫДУМАННАЯ автором первой редакции теста: код 7. Оставлена намеренно — она
#: проверяет ветку «любой прочий код», и она же — вещественное доказательство того, почему
#: одного такого контроля мало: кода 7 у падающего python-скрипта не бывает НИКОГДА.
_BROKEN_EXOTIC_CODE = (
    "#!/usr/bin/env python3\n"
    "import sys\n"
    "print('Traceback: сторож сам сломался', file=sys.stderr)\n"
    "sys.exit(7)\n"
)
#: Поломка, СЛУЧИВШАЯСЯ 12.09: сторож умер на собственном импорте `spa_core`, потому что
#: бутстрап `sys.path` стоял НИЖЕ импорта, а обёртка зовёт файл ПО ПУТИ. Интерпретатор вышел
#: с кодом 1 — тем самым, который до ADR-347 означал «НАХОДКА». Трассировка уехала в промпт
#: цикла словами «возьми ЭТУ карточку первой».
#: На прежней обёртке этот тест КРАСНЕЕТ: в промпте будет «НАХОДКА», а не «НЕ ИЗМЕРЕНО».
_CRASHED_REALLY = (
    "#!/usr/bin/env python3\n"
    "from spa_core.utils.observation import observed  # noqa: F401\n"
    "print('до этой строки дело не доходит')\n"
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
    # Без этой строки тест зеленеет вакуумно: «ГОЛОДАЮЩИЙ ПРИКАЗ» попадает в промпт и через
    # ветку «НЕ ИЗМЕРЕНО», которая просто повторяет вывод сторожа. Проверять надо ВЕРДИКТ.
    assert "НЕ ИЗМЕРЕН" not in prompt.split("Ты — оркестратор")[0], (
        "находка подана как «не измерено» — классификатор не отработал: "
        + repr(prompt[:300]))


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
    """Сторож упал экзотическим кодом ⇒ «НЕ ИЗМЕРЕНО» в промпте, а не тишина.

    Тишина читалась бы как «приказ владельца не голодает» — ровно тот fail-OPEN, из-за
    которого critical-приказ простоял четверо суток при 40+ прошедших циклах.
    """
    wrapper, prompt_file = _sandbox(tmp_path, _BROKEN_EXOTIC_CODE)
    proc = _run(wrapper, tmp_path)
    assert prompt_file.exists(), f"обёртка не дошла до Claude: rc={proc.returncode}\n{proc.stderr[-1500:]}"
    prompt = prompt_file.read_text()
    assert "НЕ ИЗМЕРЕН" in prompt, (
        f"падение сторожа прошло молча — промпт: {prompt[:300]!r}")
    assert "7" in prompt.split("Ты — оркестратор")[0], "код возврата сторожа не назван"


def test_a_guard_that_dies_on_its_own_import_is_not_a_finding(tmp_path):
    """Настоящая авария 12.09: крах сторожа предъявлен сессии как ЕГО ВЕРДИКТ.

    Сторож умер на `import spa_core` и вышел с кодом 1 — кодом, который прежний контракт
    считал НАХОДКОЙ. Обёртка вклеила трассировку в начало промпта словами «ШАГ 0a-ГОЛОД —
    НАХОДКА, возьми ЭТУ карточку первой». Это ровно тот класс, ради которого написан
    инвариант #17: три исхода — измерено · измерено и пусто · НЕ измерено — обязаны быть
    различимы, а здесь «не измерено» было склеено с самым громким из измеренных.

    Тест — положительный контроль: на обёртке до ADR-347 он КРАСНЕЕТ (проверено: в промпте
    стоит «НАХОДКА»). Соседний `_BROKEN_EXOTIC_CODE` его НЕ заменяет — тот выходит кодом 7,
    которого у падающего python-скрипта не бывает, поэтому он зеленел всё это время.
    """
    wrapper, prompt_file = _sandbox(tmp_path, _CRASHED_REALLY)
    proc = _run(wrapper, tmp_path)
    assert prompt_file.exists(), f"обёртка не дошла до Claude: rc={proc.returncode}\n{proc.stderr[-1500:]}"
    prompt = prompt_file.read_text()
    head = prompt.split("Ты — оркестратор")[0]
    assert "НЕ ИЗМЕРЕН" in head, (
        "крах сторожа не назван «не измерено» — промпт: " + repr(prompt[:300]))
    assert "НАХОДКА" not in head, (
        "крах сторожа предъявлен сессии как НАХОДКА — это авария 12.09 дословно. "
        "Промпт: " + repr(prompt[:400]))
    # Строго ModuleNotFoundError, а не «или Traceback»: мягкая форма зеленела бы и в том
    # случае, если бы подставной сторож упал по какой-то ДРУГОЙ причине, и контроль
    # перестал бы воспроизводить именно ту аварию, ради которой написан.
    assert "ModuleNotFoundError" in head, (
        "воспроизведена НЕ та авария (или причина потеряна по дороге): " + repr(head[:400]))


def test_the_real_guard_reaches_a_verdict_when_launched_the_way_the_wrapper_launches_it(tmp_path):
    """НАСТОЯЩИЙ сторож, запущенный ТОЧНО как его зовёт обёртка, доходит до вердикта.

    Обёртка исполняет `"$PYTHON" "$STARVE_PY"` — файл ПО ПУТИ, а не модуль через `-m`.
    Тогда `sys.path[0]` — каталог `scripts/`, и корень репозитория в пути не появляется
    сам ни при каком рабочем каталоге. Именно это и убивало сторожа: бутстрап `sys.path`
    стоял НИЖЕ `from spa_core.utils.observation import …`.

    Тесты выше проверяют ВЕТКИ обёртки на подставных сторожах и об этом молчат по
    построению — поэтому вопрос «а настоящий-то запускается?» задаётся здесь отдельно.
    `PYTHONPATH` снимается намеренно: у обёртки его нет, и держать зелёный тест на
    переменной окружения запускающего значило бы мерить не то.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["SPA_DATA_DIR"] = str(tmp_path / "data")  # живое data/ не трогаем
    proc = subprocess.run(
        [sys.executable, str(_GUARD), "--no-write", "--ref", ""],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=180)
    assert proc.returncode != 1, (
        "сторож НЕ ДОШЁЛ до вердикта при запуске по пути — ровно авария 12.09.\n"
        f"stderr: {proc.stderr[-2000:]}")
    assert proc.returncode in (0, 3), (
        f"неожиданный код {proc.returncode}; stdout={proc.stdout[-800:]!r} "
        f"stderr={proc.stderr[-800:]!r}")
    assert "ГОЛОДА" in proc.stdout.upper() or "ГОЛОДАЮЩ" in proc.stdout, proc.stdout[:300]


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
