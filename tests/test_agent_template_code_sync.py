"""Обёртка агента синхронизирует код ПЕРЕД запуском, но никогда не падает из-за этого.

Решение владельца 2026-08-08, вариант 1 карточки
`owner-decision-chasovye-agenty-do-sutok-krutyat-staryi`.

**Замеренная авария.** Пуши уходят прямо на origin через API и не трогают рабочее дерево, а флот
исполняет именно его. Синхронизация шла раз в сутки. Для агента, просыпающегося раз в день, это
нормально; для ЧАСОВОГО — до суток работы на старом коде. Защиту от столкновения сессий выложили
07.08, а 08.08 она всё ещё не работала в проде: за эти сутки одна сессия удалила рабочий каталог
другой, вторая умерла, не доставив работу.

**Условие владельца, жёсткое и проверяемое здесь:** GitHub недоступен ⇒ агент СТАРТУЕТ НА СТАРОМ
КОДЕ и ГОВОРИТ об этом. Отказ синхронизации не имеет права стать отказом агента — иначе сеть
становится единой точкой отказа всего флота.

Отдельный тест закрывает класс «функция есть, вызова нет» (цикл #144): проверяется, что синк
реально запускается ПЕРЕД python, а не просто определён в файле.
"""
from __future__ import annotations

import os
import stat
import subprocess
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "scripts" / "agent_template.sh"


def _fake_root(root: Path, py_marker: Path, sync_marker: Path | None,
               sync_exit: int = 0) -> Path:
    """Минимальное дерево: spa_core, python-заглушка, опционально скрипт синка."""
    (root / "spa_core").mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("# fake\n")
    py = root / "python3"
    py.write_text(f'#!/bin/bash\necho "PY $@" >> "{py_marker}"\nexit 0\n')
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if sync_marker is not None:
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        s = root / "scripts" / "code_sync_from_origin.sh"
        s.write_text(f'#!/bin/bash\necho "SYNC" >> "{sync_marker}"\nexit {sync_exit}\n')
        s.chmod(s.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return py


def _run(root: Path, py: Path, name: str, stamp: Path, extra_env=None,
         template: Path | None = None):
    env = dict(os.environ)
    env.update({
        "SPA_AGENT_REPO_ROOT": str(root),
        "SPA_AGENT_PYTHON": str(py),
        "SPA_CODE_SYNC_STAMP": str(stamp),
    })
    env.update(extra_env or {})
    return subprocess.run(
        ["/bin/bash", str(template or TEMPLATE), name, "spa_core.fake"],
        capture_output=True, text=True, env=env, timeout=90,
    )


def _log_for(name: str) -> Path:
    return Path(f"/tmp/spa_{name}.log")


def _name() -> str:
    return f"synctest_{uuid.uuid4().hex[:8]}"


# ── синк действительно ВЫЗЫВАЕТСЯ (проводка, а не только функция) ────────────

def test_sync_runs_before_python(tmp_path):
    """Класс #144: функция без вызова оставила бы тесты зелёными, а фичу мёртвой."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    name = _name()
    r = _run(tmp_path / "root", py, name, tmp_path / "stamp")
    assert r.returncode == 0, r.stderr
    assert sync_m.exists(), "синк не вызван — код в проде остался бы старым"
    assert py_m.exists(), "python не запущен"
    assert sync_m.stat().st_mtime <= py_m.stat().st_mtime, "синк обязан идти ДО python"


def test_agent_starts_when_sync_fails(tmp_path):
    """УСЛОВИЕ ВЛАДЕЛЬЦА: origin недоступен ⇒ стартуем на старом коде, не падаем."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m, sync_exit=1)
    name = _name()
    r = _run(tmp_path / "root", py, name, tmp_path / "stamp")
    assert r.returncode == 0, f"агент упал из-за отказа синка: {r.stderr}"
    assert py_m.exists(), "агент обязан стартовать даже без свежего кода"


def test_failed_sync_says_so_in_the_log(tmp_path):
    """…и ГОВОРИТ об этом. Молчаливый старт на старом коде — это та же авария."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m, sync_exit=1)
    name = _name()
    _run(tmp_path / "root", py, name, tmp_path / "stamp")
    log = _log_for(name).read_text(encoding="utf-8", errors="replace")
    assert "CODE_SYNC_STALE" in log, log[-800:]
    assert "СТАРТУЮ НА СТАРОМ КОДЕ" in log, log[-800:]


def test_failed_sync_does_not_stamp(tmp_path):
    """Метка свежести не ставится при отказе — иначе следующий агент решит, что код свеж."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m, sync_exit=1)
    stamp = tmp_path / "stamp"
    _run(tmp_path / "root", py, _name(), stamp)
    assert not stamp.exists(), "отказавший синк пометил код как свежий"


# ── троттлинг: свежий код не пересинхронизируется ────────────────────────────

def test_fresh_stamp_skips_the_sync(tmp_path):
    """~56 агентов не должны гонять git checkout наперегонки за один индекс."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    stamp = tmp_path / "stamp"
    stamp.write_text("")                      # метка только что поставлена
    name = _name()
    r = _run(tmp_path / "root", py, name, stamp)
    assert r.returncode == 0
    assert not sync_m.exists(), "синк запустился, хотя код синхронизировали только что"
    log = _log_for(name).read_text(encoding="utf-8", errors="replace")
    assert "CODE_SYNC skip" in log


def test_stale_stamp_triggers_the_sync(tmp_path):
    """Зеркало: метка протухла ⇒ синк обязан пройти.

    Без этого теста «починка» вида «всегда пропускать» была бы зелёной, а
    часовые агенты по-прежнему крутили бы старый код.
    """
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    stamp = tmp_path / "stamp"
    stamp.write_text("")
    old = stamp.stat().st_mtime - 4000        # заметно старше окна по умолчанию
    os.utime(stamp, (old, old))
    r = _run(tmp_path / "root", py, _name(), stamp)
    assert r.returncode == 0
    assert sync_m.exists(), "протухшая метка не запустила синхронизацию"


def test_successful_sync_refreshes_the_stamp(tmp_path):
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    stamp = tmp_path / "stamp"
    _run(tmp_path / "root", py, _name(), stamp)
    assert stamp.exists() and sync_m.exists()


# ── дерево без скрипта синка (песочницы, чужие чекауты) ──────────────────────

def test_tree_without_sync_script_just_runs(tmp_path):
    """Нет скрипта — синхронизировать нечем; агент работает как раньше."""
    py_m = tmp_path / "py.txt"
    py = _fake_root(tmp_path / "root", py_m, None)
    r = _run(tmp_path / "root", py, _name(), tmp_path / "stamp")
    assert r.returncode == 0 and py_m.exists()


def test_skip_switch_disables_sync(tmp_path):
    """Ручной запуск на песочнице должен уметь выключить синк одной переменной."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    r = _run(tmp_path / "root", py, _name(), tmp_path / "stamp",
             extra_env={"SPA_AGENT_SKIP_SYNC": "1"})
    assert r.returncode == 0
    assert not sync_m.exists()
    assert py_m.exists()


# ── синк не смеет искажать код возврата агента ───────────────────────────────

def test_agent_exit_code_comes_from_python_not_from_sync(tmp_path):
    """Код возврата обязан оставаться кодом модуля — launchd судит по нему."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    root = tmp_path / "root"
    _fake_root(root, py_m, sync_m, sync_exit=1)
    py = root / "python3"
    py.write_text(f'#!/bin/bash\necho "PY $@" >> "{py_m}"\nexit 42\n')
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    r = _run(root, py, _name(), tmp_path / "stamp")
    assert r.returncode == 42, "код возврата подменён синхронизацией"


# ── `stat` не переносим: авария CI 2026-08-13 (цикл #221) ────────────────────
#
# Что произошло на самом деле. `SPA Tests` краснел на этом файле 12 прогонов
# подряд, ровно на двух тестах — тех, где метка синка СУЩЕСТВУЕТ. Причина не в
# тестах: `stat -f %m` — форма BSD, а у GNU-coreutils `-f` означает «статус
# файловой системы» и формата не берёт, поэтому `%m` уезжает как ИМЯ ФАЙЛА и на
# stdout приходит текстовый блок вместо числа. Защита `|| echo 0` этого не ловит:
# для существующего файла блок печатается. Мусор попадал в `$(( ))`, арифметика
# падала, `age` оставался неприсвоенным — и `set -u` убивал ОБЁРТКУ: на bash 5
# (CI) кодом 1, на bash 3.2 (наш прод) МОЛЧА и кодом 0. То есть launchd записал бы
# успех агента, который не стартовал и не оставил лога.
#
# Прод сегодня спасает только то, что в его PATH резолвится BSD-`stat`. Первый же
# GNU-`stat`, появившийся в /Users/…/miniconda3/bin (ПЕРВЫЙ каталог PATH обёртки),
# погасил бы весь флот тихо. Тесты ниже гоняют ИМЕННО этот сценарий с macOS.

_GNU_STAT_SHIM = """#!/bin/bash
# Поведение GNU-coreutils `stat`: -f = статус ФАЙЛОВОЙ СИСТЕМЫ, формата не берёт.
if [ "$1" = "-f" ]; then
  shift; rc=0
  for f in "$@"; do
    if [ ! -e "$f" ]; then echo "stat: cannot read file system information for '$f'" >&2; rc=1; continue; fi
    echo "  File: \\"$f\\""
    echo "    ID: 1234abcd Namelen: 255     Type: ext2/ext3"
  done
  exit $rc
fi
if [ "$1" = "-c" ] && [ "$2" = "%Y" ]; then
  # Настоящий mtime — обеими формами: заглушка обязана работать И на Маке, И на
  # ubuntu-раннере. Первая редакция звала здесь только BSD-форму, и тест честно
  # покраснел в CI (`троттлинг мёртв`): на Linux /usr/bin/stat — это GNU.
  /usr/bin/stat -c %Y "$3" 2>/dev/null || /usr/bin/stat -f %m "$3"
  exit $?
fi
exec /usr/bin/stat "$@"
"""

_DEAD_STAT_SHIM = '#!/bin/bash\necho "не число"\nexit 1\n'


def _shim(tmp_path: Path, body: str, name: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def test_gnu_stat_does_not_kill_the_agent_and_still_skips(tmp_path):
    """Положительный контроль аварии 13.08: на GNU-`stat` агент обязан СТАРТОВАТЬ.

    И именно пропустить синк — иначе «починка» вида «при сомнении всегда
    синхронизировать» прошла бы зелёной, а троттлинг ~56 агентов был бы мёртв.
    """
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    stamp = tmp_path / "stamp"
    stamp.write_text("")                      # метка только что поставлена
    name = _name()
    r = _run(tmp_path / "root", py, name, stamp,
             extra_env={"SPA_AGENT_STAT": str(_shim(tmp_path, _GNU_STAT_SHIM, "gnu_stat"))})
    assert r.returncode == 0, f"обёртка умерла на GNU-`stat`: rc={r.returncode} {r.stderr}"
    assert py_m.exists(), "агент НЕ СТАРТОВАЛ — ровно авария 2026-08-13"
    assert not sync_m.exists(), "возраст метки не прочитан GNU-формой — троттлинг мёртв"
    assert "CODE_SYNC skip" in _log_for(name).read_text(encoding="utf-8", errors="replace")


def test_gnu_stat_stale_stamp_still_triggers_the_sync(tmp_path):
    """Зеркало: на GNU-`stat` протухшая метка обязана запустить синк."""
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    stamp = tmp_path / "stamp"
    stamp.write_text("")
    old = stamp.stat().st_mtime - 4000
    os.utime(stamp, (old, old))
    r = _run(tmp_path / "root", py, _name(), stamp,
             extra_env={"SPA_AGENT_STAT": str(_shim(tmp_path, _GNU_STAT_SHIM, "gnu_stat"))})
    assert r.returncode == 0, r.stderr
    assert py_m.exists(), "агент не стартовал"
    assert sync_m.exists(), "протухшая метка не запустила синхронизацию на GNU-`stat`"


def test_unreadable_stamp_age_is_named_and_syncs_instead_of_dying(tmp_path):
    """`stat` сломан насмерть ⇒ агент стартует, синк идёт, причина НАЗВАНА.

    «Возраст неизвестен» ближе к «код мог протухнуть», чем к «код свежий», —
    поэтому fail-safe здесь означает синхронизацию, а не пропуск. И не молча.
    """
    py_m, sync_m = tmp_path / "py.txt", tmp_path / "sync.txt"
    py = _fake_root(tmp_path / "root", py_m, sync_m)
    stamp = tmp_path / "stamp"
    stamp.write_text("")
    name = _name()
    r = _run(tmp_path / "root", py, name, stamp,
             extra_env={"SPA_AGENT_STAT": str(_shim(tmp_path, _DEAD_STAT_SHIM, "dead_stat"))})
    assert r.returncode == 0, r.stderr
    assert py_m.exists(), "агент не стартовал из-за нечитаемого возраста метки"
    assert sync_m.exists(), "неизвестный возраст обязан вести к синку, а не к пропуску"
    log = _log_for(name).read_text(encoding="utf-8", errors="replace")
    assert "stamp_age_unknown" in log, log[-800:]


def test_a_crash_inside_the_sync_section_cannot_kill_the_agent(tmp_path):
    """Структурная страховка: обрыв ВНУТРИ секции синка не уносит агента.

    Условие владельца («отказ синхронизации не имеет права стать отказом агента»)
    до 13.08 держалось на дисциплине автора, а не на устройстве файла: одной
    арифметической ошибки хватило, чтобы `set -u` убил весь запуск. Здесь дефект
    ВНОСИТСЯ нарочно — старой строкой, которая и упала в CI, — и проверяется,
    что подоболочка его удерживает.

    Контроль в обратную сторону идёт ниже, в том же тесте: та же мутация БЕЗ
    подоболочки обязана воспроизвести аварию, иначе тест ничего не доказывает.
    """
    src = TEMPLATE.read_text(encoding="utf-8")
    buggy_line = '        age=$(( now - $("$STAT_BIN" -f %m "$SYNC_STAMP" 2>/dev/null || echo 0) ))\n'
    start = src.index('        local now="" mtime="" age=""')
    end = src.index('        if [ -n "$age" ]', start)
    mutated = src[:start] + '        local now="" age=""\n        now=$(date +%s)\n' + buggy_line + src[end:]
    assert "( maybe_sync_code ) || true" in mutated, "проводка вызова изменилась — тест пересобрать"

    shim = _shim(tmp_path, _GNU_STAT_SHIM, "gnu_stat")

    def run_variant(text: str, tag: str):
        tpl = tmp_path / f"tpl_{tag}.sh"
        tpl.write_text(text)
        root = tmp_path / f"root_{tag}"
        py_m, sync_m = tmp_path / f"py_{tag}.txt", tmp_path / f"sync_{tag}.txt"
        py = _fake_root(root, py_m, sync_m)
        stamp = tmp_path / f"stamp_{tag}"
        stamp.write_text("")
        r = _run(root, py, _name(), stamp,
                 extra_env={"SPA_AGENT_STAT": str(shim)}, template=tpl)
        return r, py_m

    r_guarded, py_guarded = run_variant(mutated, "guarded")
    assert py_guarded.exists(), (
        "подоболочка не удержала обрыв внутри синка — агент не стартовал")

    r_bare, py_bare = run_variant(
        mutated.replace("( maybe_sync_code ) || true", "maybe_sync_code"), "bare")
    assert not py_bare.exists(), (
        "мутация без подоболочки НЕ воспроизвела аварию 2026-08-13 — "
        "значит и защита ничего не доказывает")
