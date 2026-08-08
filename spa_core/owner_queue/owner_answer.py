#!/usr/bin/env python3
"""Ответ ВЛАДЕЛЬЦА на карточку решения — единственный путь к ``owner-done``.

Зачем отдельный модуль, а не флажок в ``queue.set_status``
------------------------------------------------------------------------------
Инвариант #14: «Агентам ЗАПРЕЩЕНО переводить карточку решения в ``owner-done``. Только
владелец.» ``queue.set_status`` этот переход ОТКАЗЫВАЕТ, и здесь он не ослаблен ни на
строку — тесты на отказ продолжают проходить без единой правки.

Решение владельца 2026-08-08 (перед отъездом на 10 дней): нажатие кнопки в Телеграме — это
его собственное решение, и карточка закрывается сразу. Значит нужен путь, у которого
владелец — не «ещё один вызывающий», а **условие работы**. Отсюда три правила:

1. **Проверка личности живёт ВНУТРИ писателя.** Не на стороне вызова. Появится второе место
   вызова — оно унаследует проверку, а не забудет её. Это ровно тот класс ошибки, на котором
   мы уже горели: страж честно отвечал на свой вопрос, а нужный никто не задавал.
2. **Не можем проверить — отказываем.** Не знаем chat_id владельца (нет в Keychain, пустой) —
   ``NotTheOwner``. Fail-CLOSED: «проверить не удалось» никогда не значит «разрешено».
3. **Пишем, КТО и КОГДА решил.** ``owner_answered_by`` / ``owner_answered_at`` /
   ``owner_answer_via`` — чтобы через месяц было видно, что карточку закрыл владелец с
   телефона, а не агент от его имени.

Модуль ничего не исполняет и не двигает капитал: он только записывает выбор в карточку.
Работу по решению делает обычный цикл под обычными правилами.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.owner_queue.queue import OWNER_ONLY_STATUS, _split_frontmatter
from spa_core.utils.atomic import atomic_save_text


class NotTheOwner(PermissionError):
    """Ответ пришёл не от владельца (или личность не удалось подтвердить)."""


ANSWER_HEADING = "## Решение владельца"


def _owner_chat_id(explicit: Optional[str]) -> str:
    """chat_id владельца. Пусто ⇒ подтвердить личность нечем ⇒ вызывающий получит отказ."""
    if explicit not in (None, ""):
        return str(explicit).strip()
    try:
        from spa_core.telegram.bot import get_chat_id

        return str(get_chat_id() or "").strip()
    except Exception:  # noqa: BLE001 — недоступность Keychain = «не подтвердили» = отказ
        return ""


def is_owner(actor_chat_id, owner_chat_id: Optional[str] = None) -> bool:
    """Тот ли это человек. Сомнение (пустое значение с любой стороны) → False."""
    owner = _owner_chat_id(owner_chat_id)
    actor = str(actor_chat_id or "").strip()
    if not owner or not actor:
        return False
    return actor == owner


def _set_frontmatter_field(lines: list[str], start: int, end: int,
                           key: str, value: str) -> int:
    """Заменить/добавить верхнеуровневое поле frontmatter. Возвращает новый ``end``.

    Верхнеуровневое — значит без отступа: ``type:`` внутри ``trackerStatus:`` имеет отступ
    и совпасть не должен, иначе правка ушла бы во вложенный блок.
    """
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith(f"{key}:") and not lines[i][:1].isspace():
            newline = "\n" if lines[i].endswith("\n") else ""
            lines[i] = f"{key}: {value}{newline}"
            return end
    lines.insert(end, f"{key}: {value}\n")
    return end + 1


def record_owner_answer(
    path: str | Path,
    *,
    choice_num: str,
    choice_label: str,
    actor_chat_id,
    owner_chat_id: Optional[str] = None,
    via: str = "telegram",
    now: Optional[datetime] = None,
) -> dict:
    """Записать решение владельца в карточку и закрыть её как ``owner-done``.

    Идемпотентно: повторный тот же выбор ничего не переписывает и не плодит вторую
    секцию «Решение владельца» — владелец может нажать дважды из двух чатов, и это
    не должно выглядеть как два разных решения.

    :raises NotTheOwner: ответ не от владельца либо личность не подтверждена.
    """
    if not is_owner(actor_chat_id, owner_chat_id):
        raise NotTheOwner(
            "owner-done может поставить только владелец (инвариант #14): "
            "chat_id отправителя не совпал с chat_id владельца или не подтверждён"
        )

    p = Path(path)
    text = p.read_text(encoding="utf-8")
    fm_lines, _body = _split_frontmatter(text)
    if not fm_lines:
        raise ValueError(f"{p}: no frontmatter to update")

    stamp = (now or datetime.now(timezone.utc)).isoformat()

    # Уже отвечено тем же вариантом — выходим, ничего не трогая.
    already = re.search(r"^owner_choice:\s*(.+)$", text, re.MULTILINE)
    if already and already.group(1).strip().strip('"') == str(choice_num):
        return {"path": str(p), "choice": choice_num, "already": True}

    lines = text.splitlines(keepends=True)
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
    if start is None or end is None:
        raise ValueError(f"{p}: could not locate frontmatter bounds")

    end = _set_frontmatter_field(lines, start, end, "status", OWNER_ONLY_STATUS)
    end = _set_frontmatter_field(lines, start, end, "owner_choice", str(choice_num))
    end = _set_frontmatter_field(lines, start, end, "owner_answered_at", stamp)
    end = _set_frontmatter_field(lines, start, end, "owner_answer_via", via)
    end = _set_frontmatter_field(
        lines, start, end, "owner_answered_by", str(actor_chat_id)
    )

    body_addition = (
        f"\n\n---\n\n{ANSWER_HEADING}\n\n"
        f"**Вариант {choice_num}** — {choice_label}\n\n"
        f"_Ответ владельца получен {stamp} ({via}). "
        f"Карточка закрыта самим владельцем, не агентом (инвариант #14)._\n"
    )
    out = "".join(lines).rstrip("\n") + body_addition
    atomic_save_text(out, str(p))
    return {"path": str(p), "choice": choice_num, "already": False, "answered_at": stamp}
