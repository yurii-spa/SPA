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

# ---------------------------------------------------------------------------
# След перехода В САМОЙ КАРТОЧКЕ (решение владельца 2026-08-23, вариант 1, ADR-129)
# ---------------------------------------------------------------------------
#
# Журнал выше живёт в ``data/`` и в git НЕ ПОПАДАЕТ (``.gitignore``: ``data/**/*.jsonl``),
# а карточки — попадают. Протокол §3.4 требует работать из ОТДЕЛЬНОГО дерева, поэтому
# законное закрытие вопроса владельца приезжает в прод-дерево БЕЗ записи о себе, и
# сторож ``tracker_status_sentinel`` называет его ``CRITICAL: неатрибутированный уход
# из needs-owner`` — теми самыми словами, которые означают «вопрос владельца закрыли
# без владельца». Это ложная тревога КАЖДЫЙ раз, а не иногда: ровно так сторожа глохнут.
#
# Владелец выбрал вариант 1: **везти след вместе с карточкой**. Компактная строка
# перехода пишется в тот же файл, что и сам ``status:`` (одной записью — иначе падение
# между двумя записями породило бы ровно того призрака, которого мы лечим), а журнал
# с pid/командой/деревом остаётся ЛОКАЛЬНЫМ для разбора.
#
# Чего след НЕ несёт и почему: pid, командной строки и путей хост-машины здесь нет —
# это было решением владельца («в репозиторий поедут pid, пути и командные строки» —
# явная причина отказа от варианта 2). Для сторожа этого и не нужно: ему достаточно
# отличить «переход сделал НАШ код» от «переход не объяснил никто».
#
# Честная граница: тот, кто правит ``status:`` руками, может дописать и след. Файловый
# сторож этого не различит НИКОГДА — доказательство и предмет лежат в одном файле.
# След закрывает ЛОЖНУЮ тревогу на законном пути; немого писателя без следа он ловит
# по-прежнему, и именно это проверено тестом в обе стороны.

#: Ключ frontmatter, под которым едет след. Список YAML: рендерится в Nimbalyst/Obsidian
#: как поле, в теле карточки владельцу не мешает.
TRAIL_KEY = "status_trail"

#: Сколько последних переходов держим. Карточка живёт месяцами и меняет статус десятки
#: раз; неограниченный след превратил бы frontmatter в журнал.
TRAIL_CAP = 12

#: Разделитель полей внутри строки следа.
TRAIL_SEP = " · "

_TRAIL_ITEM_RE = re.compile(r"^\s+-\s+(.*)$")
_TRAIL_LINE_RE = re.compile(r"^(?P<ts>\S+)\s+(?P<old>\S+)\s*->\s*(?P<new>\S+)$")


#: Как след называет «строки status: не было вовсе». Совпадает со словарём сторожа.
MISSING_STATUS = "(нет)"


def session_label() -> Optional[str]:
    """Ярлык сессии для следа — только если сессия себя назвала.

    Берётся из ``SPA_SESSION_ID`` (его выставляет обёртка цикла). Подставлять сюда pid
    «на всякий случай» нельзя: владелец отказался от варианта 2 именно из-за pid'ов в
    репозитории. Нет ярлыка — поля в следе просто нет; сторожу хватает ``source``.
    """
    value = (os.environ.get("SPA_SESSION_ID") or "").strip()
    return value or None


def trail_line(*, old: Optional[str], new: str, source: str,
               now: Optional[datetime] = None,
               session: Optional[str] = None) -> str:
    """Одна строка следа: ``<ts> <old> -> <new> · <source>[ · <session>]``."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    parts = [f"{stamp} {old or MISSING_STATUS} -> {new}", source]
    label = session if session is not None else session_label()
    if label:
        parts.append(label)
    return TRAIL_SEP.join(parts)


def _frontmatter_bounds(lines: list[str]) -> tuple[Optional[int], Optional[int]]:
    """Индексы открывающего и закрывающего ``---``. ``(None, None)`` — frontmatter нет."""
    start = end = None
    seen = 0
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            seen += 1
            if seen == 1:
                start = i
            elif seen == 2:
                end = i
                break
    return start, end


def read_trail(text: str) -> list[dict]:
    """След переходов из ТЕКСТА карточки, в порядке записи.

    Нечитаемая строка следа отбрасывается, а не выдаётся за переход: выдумывать
    переход из мусора значило бы оправдывать чужую правку.
    """
    lines = text.splitlines()
    start, end = _frontmatter_bounds(lines)
    if start is None or end is None:
        return []
    out: list[dict] = []
    inside = False
    for ln in lines[start + 1:end]:
        if not ln[:1].isspace():
            inside = ln.split(":", 1)[0].strip() == TRAIL_KEY if ":" in ln else False
            continue
        if not inside:
            continue
        m = _TRAIL_ITEM_RE.match(ln)
        if not m:
            continue
        raw = _unquote_trail(m.group(1).strip())
        parts = [p.strip() for p in raw.split(TRAIL_SEP)]
        head = _TRAIL_LINE_RE.match(parts[0]) if parts else None
        if not head:
            continue
        out.append({
            "ts": head.group("ts"),
            "old": head.group("old"),
            "new": head.group("new"),
            "source": parts[1] if len(parts) > 1 else "",
            "session": parts[2] if len(parts) > 2 else "",
            "raw": raw,
        })
    return out


def _unquote_trail(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def stamp_trail(text: str, *, old: Optional[str], new: str, source: str,
                now: Optional[datetime] = None,
                session: Optional[str] = None) -> str:
    """Текст карточки с дописанным следом перехода.

    Ничего не бросает и НИКОГДА не роняет запись статуса: у карточки без frontmatter
    след писать некуда — возвращаем текст как есть (переход тогда останется
    неатрибутированным, и это честный исход, а не потеря работы).
    """
    lines = text.splitlines(keepends=True)
    start, end = _frontmatter_bounds(lines)
    if start is None or end is None:
        return text

    existing = [item["raw"] for item in read_trail(text)]
    existing.append(trail_line(old=old, new=new, source=source, now=now,
                               session=session))
    kept = existing[-TRAIL_CAP:]

    # Выбрасываем старый блок целиком: ключ и его отступные строки.
    rebuilt: list[str] = []
    inside = False
    for i, ln in enumerate(lines):
        if start < i < end:
            if not ln[:1].isspace():
                inside = (ln.split(":", 1)[0].strip() == TRAIL_KEY) if ":" in ln else False
                if inside:
                    continue
            elif inside:
                continue
        rebuilt.append(ln)

    start, end = _frontmatter_bounds(rebuilt)
    if start is None or end is None:                    # недостижимо: границы были
        return text
    block = [f"{TRAIL_KEY}:\n"] + [f"  - \"{line}\"\n" for line in kept]
    rebuilt[end:end] = block
    return "".join(rebuilt)


def trail_explains(text: str, old: str, new: str) -> Optional[dict]:
    """Объясняет ли след КАРТОЧКИ переход ``old -> new``. ``None`` — не объясняет.

    Цепочка читается с конца: последняя запись обязана приводить в ``new``, а начало
    непрерывного хвоста — совпадать с ``old``. Так же, как в журнале: одна запись не
    выдаёт индульгенцию всем последующим.

    Времени тут НЕ проверяем осознанно. Журнальное окно существует, чтобы старая
    запись не оправдала новый переход в ОДНОМ дереве; след же едет вместе с карточкой
    и попадает в прод-дерево с задержкой доставки — от часов до дней. Требовать окна
    значило бы объявлять КАЖДУЮ доставленную карточку неатрибутированной, то есть
    вернуть ровно ту ложную тревогу, ради которой след и заведён. Возраст записи
    возвращается вызывающему и печатается в отчёте — он назван, а не спрятан.
    """
    entries = read_trail(text)
    if not entries:
        return None
    if entries[-1]["new"] != new:
        return None
    chain_start = len(entries) - 1
    while chain_start > 0 and entries[chain_start - 1]["new"] == entries[chain_start]["old"]:
        chain_start -= 1
        if entries[chain_start]["old"] == old:
            break
    if entries[chain_start]["old"] != old:
        return None
    last = entries[-1]
    return {
        "ts": last["ts"],
        "source": last["source"],
        "session": last["session"],
        "records": entries[chain_start:],
    }


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


#: Поля frontmatter, чья отметка тоже означает «с карточкой что-то произошло».
#: След пишет НАШ код; ``owner_answered_at`` пишет бот в прод-дерево, и он может быть
#: НОВЕЕ любого следа: поздний `ack` открывает карточку, закрытую агентом (карточка
#: ``inbox-pozdnii-prinyato-voskreshaet-kartochku-z``). Читать один только след значило бы
#: объявить такую карточку устаревшей копией и увести ЖИВОЙ ответ владельца из очереди.
CHANGE_STAMP_FIELDS = ("owner_answered_at",)


def _parse_stamp(value) -> Optional[datetime]:
    """ISO-отметка → datetime в UTC. Непарсимое — ``None``, а не «эпоха»."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def frontmatter_value(text: str, key: str) -> Optional[str]:
    """Скалярное поле верхнего уровня из frontmatter карточки. Нет поля ⇒ ``None``."""
    lines = text.splitlines()
    start, end = _frontmatter_bounds(lines)
    if start is None or end is None:
        return None
    for ln in lines[start + 1:end]:
        if ln[:1].isspace() or ":" not in ln:
            continue
        name, _, value = ln.partition(":")
        if name.strip() == key:
            return _unquote_trail(value.strip()) or None
    return None


def latest_change_at(text: str) -> Optional[datetime]:
    """Самая поздняя отметка «с этой карточкой что-то произошло» — по её ТЕКСТУ.

    Функция принимает ТЕКСТ, а не путь, ровно затем, чтобы одна и та же мерка
    прикладывалась к обеим копиям карточки — к файлу в дереве и к версии на
    ``origin/main``. Копия мерки для второй стороны разъехалась бы с первой молча
    (урок ADR-220: у общего решения параметр, а не второй экземпляр).

    Отметок две породы, и обе обязательны:

    * след переходов (``status_trail``) — его пишет наш код при каждом ``set_status``;
    * :data:`CHANGE_STAMP_FIELDS` — ответ владельца, который пишет бот прямо в
      прод-дерево, минуя git.

    ``None`` означает «никаких свидетельств о движении карточки в тексте нет» — это
    ФАКТ (карточка не двигалась с рождения), а не сбой разбора: непарсимая отметка
    отбрасывается по отдельности, и если хоть одна разобралась, вернётся она.
    """
    stamps = [_parse_stamp(item.get("ts")) for item in read_trail(text)]
    stamps.extend(_parse_stamp(frontmatter_value(text, key))
                  for key in CHANGE_STAMP_FIELDS)
    measured = [s for s in stamps if s is not None]
    return max(measured) if measured else None
