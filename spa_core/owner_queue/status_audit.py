#!/usr/bin/env python3
"""Аудит записей ``status:`` в карточках трекера — «кто это сделал».

Зачем
------------------------------------------------------------------------------
Цикл #171 (карточка ``inbox-statusy-kartochek-vladeltsa-perepisalis``): три карточки
owner-gate сайта одновременно сменили ``status:`` сами. **Вопрос владельцу закрылся
без ответа владельца**, а уже разобранный ответ снова встал в очередь. Тела карточек
не пострадали — переписаны ровно строки ``status:``. Ни один сторож не сказал ни слова.

Опасна не автоматика, а её немота: закрытие вопроса владельца не оставляло НИ ОДНОЙ
записи нигде, и увидеть его можно было только перечитав файл глазами.

Этот модуль отвечает на первый вопрос карточки — «кто писатель»: каждая запись
``status:``, сделанная НАШИМ кодом, оставляет строку с pid, командой, деревом и
переходом. Второй вопрос — «а если писатель НЕ наш» — закрывает сторож
``spa_core.monitoring.tracker_status_sentinel``: переход без записи здесь он называет
НЕАТРИБУТИРОВАННЫМ вслух. Два механизма нужны оба: журнал знает имя, но только для
своих; сторож видит всех, но имени не знает.

Почему сбой аудита НЕ отменяет запись статуса
------------------------------------------------------------------------------
Уронить перевод карточки из-за того, что не записался журнал, значит поменять потерю
следа на потерю работы. Поэтому здесь: громкая жалоба в stderr (с ``flush=True`` —
непрожатый ``print`` в демоне не существует, урок #84) и возврат ``None``. Молчания
это не создаёт: пропущенная запись превращает переход в неатрибутированный, а такой
переход сторож ловит по построению.

Только stdlib. LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

#: Журнал живёт в ТОМ дереве, где лежит карточка: сторож читает трекер и журнал одного
#: и того же дерева, иначе он сверял бы записи одной машины с карточками другой.
AUDIT_REL = os.path.join("data", "tracker_status_audit.jsonl")

#: Сколько символов командной строки сохраняем. Полный ``argv`` бывает в килобайты
#: (pytest с сотней путей), а для опознания писателя хватает начала.
ARGV_CAP = 400

_STATUS_RE = re.compile(r"^status:[ \t]*(.*)$")


def repo_root_for(path: str | Path) -> Optional[Path]:
    """Корень рабочего дерева, которому принадлежит файл (по ``.git`` вверх).

    Без ``subprocess``: аудит зовётся на КАЖДУЮ запись статуса, и запуск git на
    каждую из них — это цена, которую платить незачем. ``.git`` бывает каталогом
    (главное дерево) и файлом (worktree) — оба считаются корнем.
    """
    try:
        p = Path(path).resolve()
    except OSError:
        return None
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def audit_path_for(card_path: str | Path) -> Optional[Path]:
    """Путь журнала для дерева этой карточки. ``None`` — дерево не опознано."""
    root = repo_root_for(card_path)
    return None if root is None else root / AUDIT_REL


def status_of_text(text: str) -> Optional[str]:
    """Верхнеуровневый ``status:`` из ТЕКСТА карточки. ``None`` — такой строки нет.

    Ищем только внутри frontmatter и только без отступа: ``status:`` с отступом
    принадлежит вложенному блоку (``trackerStatus:``), а строка из ТЕЛА карточки —
    просто текст, и принять её за статус значило бы выдумать переход.
    """
    lines = text.splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            if start is None:
                start = i
            else:
                end = i
                break
    if start is None or end is None:
        return None
    for ln in lines[start + 1:end]:
        if ln[:1].isspace():
            continue
        m = _STATUS_RE.match(ln)
        if m:
            return m.group(1).strip()
    return None


def read_status(card_path: str | Path) -> Optional[str]:
    """Верхнеуровневый ``status:`` карточки. ``None`` — файла нет / строки нет."""
    try:
        text = Path(card_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return status_of_text(text)


def _process_facts() -> dict:
    """Кто именно пишет: pid, родитель, команда, интерпретатор, каталог запуска."""
    argv = " ".join(sys.argv)
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "argv": argv[:ARGV_CAP],
        "argv_truncated": len(argv) > ARGV_CAP,
        "executable": sys.executable,
        "cwd": os.getcwd(),
    }


def record_status_write(card_path: str | Path, *, old: Optional[str],
                        new: str, source: str,
                        now: Optional[datetime] = None) -> Optional[dict]:
    """Записать факт перевода карточки. Возвращает записанную строку либо ``None``.

    ``source`` — имя точки записи (``queue.set_status``, ``owner_answer`` …), чтобы
    в журнале было видно не только КТО процесс, но и КАКОЙ путь кода сработал.

    Ничего не бросает: см. модульную docstring («почему сбой аудита не отменяет запись»).
    """
    p = Path(card_path)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    root = repo_root_for(p)
    entry = {
        "ts": stamp,
        "card": p.name,
        "path": str(p),
        "tree": str(root) if root else None,
        "old": old,
        "new": new,
        "source": source,
        **_process_facts(),
    }
    target = None if root is None else root / AUDIT_REL
    if target is None:
        print(f"[status_audit] дерево карточки не опознано ({p}) — запись перехода "
              f"{old!r} -> {new!r} НЕ сохранена", file=sys.stderr, flush=True)
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        # O_APPEND + одна write(): параллельные писатели не рвут строки друг друга.
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        print(f"[status_audit] журнал не записан ({target}): {exc}; переход "
              f"{p.name} {old!r} -> {new!r} останется НЕАТРИБУТИРОВАННЫМ",
              file=sys.stderr, flush=True)
        return None
    return entry


def read_audit(root: str | Path) -> tuple[list[dict], list[str]]:
    """Записи журнала дерева и список нечитаемых строк.

    Битая строка НЕ отбрасывается молча: она возвращается второй половиной ответа,
    чтобы сторож мог сказать «часть журнала не прочитана», а не выдать это за пустоту.
    """
    path = Path(root) / AUDIT_REL
    if not path.is_file():
        return [], []
    entries: list[dict] = []
    broken: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], [f"журнал не прочитан: {exc}"]
    for num, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            broken.append(f"строка {num}")
            continue
        if isinstance(obj, dict):
            entries.append(obj)
        else:
            broken.append(f"строка {num}")
    return entries, broken
