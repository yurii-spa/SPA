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
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.owner_queue.queue import (
    OWNER_ONLY_STATUS,
    _parse_frontmatter,
    _split_frontmatter,
)
from spa_core.owner_queue.status_audit import record_status_write
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

    # Статус ДО ответа: закрытие карточки владельцем — тоже запись `status:`, и в
    # журнале переходов она обязана стоять рядом с остальными, иначе сторож назовёт
    # законный ответ владельца неатрибутированным.
    old_status = _parse_frontmatter(fm_lines).get("status")
    old_status = str(old_status).strip() if isinstance(old_status, str) else None

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
    record_status_write(p, old=old_status, new=OWNER_ONLY_STATUS,
                        source="owner_answer.record_owner_answer", now=now)
    return {"path": str(p), "choice": choice_num, "already": False, "answered_at": stamp}


# ── перенос следа решения владельца в ту копию карточки, которая уедет в git ──
#
# **Зачем.** Ответ владельца рождается и умирает в ОДНОМ дереве. Маршрут (замер #178,
# карточка `inbox-otvet-vladeltsa-zhivet-tolko-v-host-dereve`):
#
#   1. владелец жмёт кнопку в Телеграме;
#   2. бот вызывает ``record_owner_answer`` и пишет ``owner_choice`` / ``owner_answered_at``
#      / ``owner_answer_via`` / ``owner_answered_by`` в ХОСТ-дерево — единственное, которое
#      он знает (он в нём и запущен);
#   3. решение разбирает цикл — в ИЗОЛИРОВАННОМ worktree от ``origin/main``, где этих полей
#      нет ВООБЩЕ, и пушит оттуда ``status: ingested``;
#   4. хост-копию не обновляет никто.
#
# Итог, измеренный на двух живых карточках (``own-rnd-duty-is-concentration-adr055``,
# ``owner-decision-morfo-40-knigi-…``): на origin у обеих НЕТ ни ``owner_choice``, ни
# ``owner_answered_at`` — инжестирующая сессия переписывает раздел своей прозой. Машинно
# проверяемый след «что именно выбрал владелец и когда» существует ТОЛЬКО в рабочей копии
# одной машины, вне git. Один ``git checkout`` — и аудита решения нет.
#
# **Что делает перенос.** Перед тем как поставить ``ingested``, поля ответа копируются в ту
# копию карточки, которая уедет в git. Ничего не решает и не исполняет: переносится ФАКТ
# ответа, а не его трактовка.
#
# **Чего он НЕ делает.** Не трогает тело карточки: блок «## Решение владельца» пишет бот, а
# прозу инжеста — сессия, и склеивать их значило бы плодить два рассказа об одном решении.
# Не перезаписывает уже записанный ответ: расхождение полей — это ДВА разных ответа
# владельца, и выбирать между ними молча запрещено (``AnswerConflict``, fail-CLOSED).

#: Поля, которыми ``record_owner_answer`` метит ответ владельца. Один список на весь
#: модуль: вторая копия имён — ровно тот дефект, за который проект платил в #143–#145.
OWNER_ANSWER_FIELDS = (
    "owner_choice",
    "owner_answered_at",
    "owner_answer_via",
    "owner_answered_by",
)

#: Поля, по которым ОТЛИЧАЮТСЯ два разных ответа владельца (выбор и момент). ``via`` /
#: ``by`` — про канал и отправителя: они могут дополниться позже и конфликтом не являются.
_IDENTITY_FIELDS = ("owner_choice", "owner_answered_at")

CARRY_ALREADY_PRESENT = "already_present"      # след уже в этой копии — переносить нечего
CARRY_CARRIED = "carried"                      # перенесён из другой копии
CARRY_NO_ANSWER = "no_answer_recorded"         # следа нет НИГДЕ (владелец ответил руками)
CARRY_CONFLICT = "conflict"                    # две копии дают РАЗНЫЙ ответ — не выбираем
CARRY_UNMEASURED = "unmeasured"                # искать было нечем — это не «ок»


class AnswerConflict(RuntimeError):
    """Две копии карточки несут РАЗНЫЙ ответ владельца. Выбрать сторону молча нельзя."""


def read_answer_fields(text: str) -> dict:
    """Поля ответа владельца из ТЕКСТА карточки (пусто — если их нет).

    Разбор — общим парсером frontmatter, а не своим регэкспом: вложенное ``type:`` внутри
    ``trackerStatus:`` не имеет права попасть в верхний уровень, и это правило уже написано
    один раз.
    """
    fm = _parse_frontmatter(_split_frontmatter(text)[0])
    return {k: str(fm[k]) for k in OWNER_ANSWER_FIELDS
            if isinstance(fm.get(k), str) and str(fm[k]).strip()}


def _worktree_dirs(start: Path) -> list[Path]:
    """Рабочие деревья репозитория, ПЕРВЫМ — главное. Пусто ⇒ измерить было нечем.

    Главное дерево идёт первым не по вкусу, а по устройству маршрута: бот запущен в
    прод-дереве и пишет ответ туда. ``git worktree list --porcelain`` печатает главное
    дерево первым — это его контракт, а не наше предположение.
    """
    try:
        res = subprocess.run(
            ["git", "-C", str(start), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0:
        return []
    return [Path(ln[len("worktree "):].strip())
            for ln in res.stdout.splitlines() if ln.startswith("worktree ")]


def find_answer_copies(card_path: str | Path,
                       extra_dirs: tuple | list = ()) -> list[tuple[Path, dict]]:
    """Копии ЭТОЙ карточки в других деревьях, у которых есть след ответа владельца.

    Порядок значим: сначала явно указанные каталоги, затем главное рабочее дерево (куда
    пишет бот), затем остальные. Сама целевая карточка в список не попадает — переносить
    из себя в себя нечего.
    """
    target = Path(card_path).resolve()
    name = target.name
    candidates: list[Path] = [Path(d) / name for d in extra_dirs]
    for wt in _worktree_dirs(target.parent):
        candidates.append(wt / "nimbalyst-local" / "tracker" / name)

    out: list[tuple[Path, dict]] = []
    seen: set[Path] = {target}
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            fields = read_answer_fields(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue  # нечитаемая копия — не находка и не источник
        if fields:
            out.append((resolved, fields))
    return out


def _answer_identity(fields: dict) -> tuple:
    return tuple(fields.get(k, "") for k in _IDENTITY_FIELDS)


def carry_owner_answer(card_path: str | Path,
                       extra_dirs: tuple | list = ()) -> dict:
    """Перенести след решения владельца в ``card_path`` — ПЕРЕД тем, как его закроют.

    Возвращает вердикт (``verdict`` + подробности). Пишет только недостающие поля и только
    когда источник ровно один по смыслу; во всём остальном отказывается и говорит почему.

    :raises AnswerConflict: копии несут разные ответы владельца — выбирать нельзя.
    """
    p = Path(card_path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"verdict": CARRY_UNMEASURED, "detail": f"карточка не прочитана: {exc}",
                "path": str(p), "fields": {}}

    mine = read_answer_fields(text)
    copies = find_answer_copies(p, extra_dirs)

    # Разные ответы среди источников — стоп до любой записи.
    identities = {_answer_identity(f) for _, f in copies}
    if mine:
        identities.add(_answer_identity(mine))
    if len(identities) > 1:
        where = ", ".join(str(src) for src, _ in copies) or "—"
        raise AnswerConflict(
            f"{p.name}: копии карточки несут РАЗНЫЕ ответы владельца "
            f"({sorted(identities)}); источники: {where}. "
            f"Выбрать сторону молча нельзя — сверьте руками."
        )

    if all(mine.get(k) for k in _IDENTITY_FIELDS):
        return {"verdict": CARRY_ALREADY_PRESENT, "path": str(p), "fields": mine,
                "detail": "след решения уже в этой копии"}
    if not copies:
        return {"verdict": CARRY_NO_ANSWER, "path": str(p), "fields": mine,
                "detail": "следа ответа нет ни в одной копии карточки "
                          "(владелец мог ответить правкой статуса руками)"}

    source, fields = copies[0]
    merged = dict(fields)
    merged.update(mine)  # уже записанное здесь главнее: свой файл не переписываем
    added = {k: v for k, v in merged.items() if mine.get(k) != v}
    if not added:
        return {"verdict": CARRY_ALREADY_PRESENT, "path": str(p), "fields": mine,
                "detail": "след решения уже в этой копии"}

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
        return {"verdict": CARRY_UNMEASURED, "path": str(p), "fields": mine,
                "detail": "во frontmatter карточки некуда писать след решения"}

    for key in OWNER_ANSWER_FIELDS:      # порядок полей — стабильный, не словарный
        if key in added:
            end = _set_frontmatter_field(lines, start, end, key, added[key])
    atomic_save_text("".join(lines), str(p))
    return {"verdict": CARRY_CARRIED, "path": str(p), "fields": merged,
            "added": added, "source": str(source),
            "detail": f"след решения перенесён из {source}"}
