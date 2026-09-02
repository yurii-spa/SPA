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
    OWNER_ACCEPTED_STATUS,
    OWNER_ONLY_STATUS,
    _parse_frontmatter,
    _split_frontmatter,
)
from spa_core.owner_queue.status_audit import record_status_write, stamp_trail
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


def _superseded_register(fm_lines: list[str]) -> dict:
    """Регистр вытеснения по ПРЕДЫДУЩЕМУ ответу владельца в этой карточке.

    Пусто ⇒ вытеснять нечего: карточка либо не отвечена вовсе, либо носит пустой скаляр
    (:data:`EMPTY_SCALARS`) — «ответа нет», а не «ответ пустой».

    **Почему регистр пишется, хотя ADR-163 сказал «автоматической записи нет».** Довод
    ADR-163 — «бот вытеснения не наблюдает, он видит только свой канал» — верен для
    МЕЖканального случая: ответ интерактивной сессии боту действительно не виден. Но
    ровно тот случай, который бот производит САМ, он наблюдает непосредственно: владелец
    жмёт вторую кнопку под той же карточкой, и старое значение у писателя в руках —
    строкой выше он читает его для проверки идемпотентности. Живой замер (прод-дерево,
    ``owner-decision-mandat-samostoyatelnoi-raboty-konchaetsy``, 19.08): вариант 1 в
    21:52:36.7, вариант 3 в 21:52:40.2 — 3.5 секунды, один канал, один бот. В машинном
    следе от первого ответа не осталось ничего.

    **Провенанс не выдумывается.** Отвеченная руками карточка может нести ``owner_choice``
    без ``owner_answered_at``/``owner_answer_via``; тогда регистр выходит НЕПОЛНЫМ, и это
    честно: сторож доставки читает неполное покрытие как «вытеснение расхождения не
    покрывает» и по-прежнему зовёт человека (fail-CLOSED). Дописать сюда сегодняшнюю
    отметку значило бы приписать вытесненному ответу момент, которого у него не было.
    """
    fm = _parse_frontmatter(fm_lines)
    register: dict = {}
    for field, reg_key in SUPERSEDED_FIELDS.items():
        value = fm.get(field)
        if not isinstance(value, str):
            # ``owner_choice: ""`` разбирается как начало вложенного блока (dict) —
            # это ОТСУТСТВИЕ значения, и попасть в регистр оно не должно.
            continue
        value = value.strip()
        if not value or value in EMPTY_SCALARS:
            continue
        register[reg_key] = value
    # Без самого вытесненного ВЫБОРА регистр бессмыслен: провенанс без решения не
    # называет вытесненный ответ, а сторож сверяет именно решение.
    if SUPERSEDED_FIELDS["owner_choice"] not in register:
        return {}
    return register


#: Ответ владельца — ВЫБОР варианта, вычитанного из карточки.
KIND_OPTION = "option"
#: Ответ владельца — ПОДТВЕРЖДЕНИЕ поручения: вариантов карточка не предлагала,
#: владелец сказал «принято» / «не надо». Разные вещи, и читателю карточки они
#: обязаны быть различимы: «владелец выбрал вариант 1» и «владелец согласился с
#: поручением» ведут к разной работе, а раньше выглядели бы одинаково.
KIND_ACK = "ack"

#: ЧТО именно подтвердил владелец. Один источник этих двух значений на весь проект:
#: `owner_decisions.ACK_ACCEPT` / `ACK_DECLINE` берутся отсюда, а не пишутся второй раз
#: (вторая копия имён — дефект #143–#145). Здесь они нужны потому, что от них зависит
#: СТАТУС карточки, а статус пишет этот модуль.
ACK_ACCEPT_CHOICE = "ack"    # «принято — беру в работу»: работа ещё впереди
ACK_DECLINE_CHOICE = "nack"  # «не надо — не делаем»: больше не ждут ничего


def status_for_answer(kind: str, choice_num: str) -> str:
    """Каким статусом закрывается карточка этим ответом владельца.

    Единственное место, где живёт правило «что значит ответ для очереди».

    * ВЫБОР варианта (:data:`KIND_OPTION`) → ``owner-done``. Ответ И ЕСТЬ результат,
      закрытие нажатием решено осознанно (ADR-075, решение владельца 08.08).
    * «Не надо» (:data:`ACK_DECLINE_CHOICE`) → ``owner-done``. Отказ тоже полон:
      после него не ждут ни действия, ни проверки.
    * «Принято — беру в работу» (:data:`ACK_ACCEPT_CHOICE`) → ``owner-accepted``,
      НЕтерминальный. Это обещание совершить действие, а не действие. Замер #350:
      единственное на тот день ack-закрытие (`owner-decision-snyat-mertvyi-adres-\
      checkup-earn-defi-co`, 22.08 20:29Z) стало терминальным при НЕвыполненном
      критерии приёмки той же карточки (замер 20:47Z — всё ещё 404), и обещанную
      перепроверку делать стало некому.

    Незнакомый ``kind`` ведёт себя как выбор — прежнее поведение: новый вид ответа
    не имеет права молча получить НЕтерминальный статус и зависнуть в очереди.
    """
    if str(kind) == KIND_ACK and str(choice_num).lower() == ACK_ACCEPT_CHOICE:
        return OWNER_ACCEPTED_STATUS
    return OWNER_ONLY_STATUS


def record_owner_answer(
    path: str | Path,
    *,
    choice_num: str,
    choice_label: str,
    actor_chat_id,
    owner_chat_id: Optional[str] = None,
    via: str = "telegram",
    kind: str = KIND_OPTION,
    now: Optional[datetime] = None,
) -> dict:
    """Записать решение владельца в карточку и перевести её в статус ЕГО ответа.

    Куда именно — решает :func:`status_for_answer`: выбор варианта и «не надо»
    закрывают карточку (``owner-done``), «принято — беру в работу» переводит её в
    НЕтерминальный ``owner-accepted``, потому что работа после этого только
    начинается (#350).

    Идемпотентно: повторный тот же выбор ничего не переписывает и не плодит вторую
    секцию «Решение владельца» — владелец может нажать дважды из двух чатов, и это
    не должно выглядеть как два разных решения.

    ``kind`` — ЧЕМ был ответ: :data:`KIND_OPTION` (выбран вариант карточки) или
    :data:`KIND_ACK` (карточка вариантов не предлагала, владелец подтвердил
    поручение). Личность проверяется одинаково: инвариант #14 не знает разницы
    между кнопкой «Вариант 1» и кнопкой «Принято» — обе нажимает владелец.

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

    # Вытесняемый ответ — ДО перезаписи: строкой ниже его значения перестанут
    # существовать где бы то ни было, кроме прозы тела (ADR-180).
    superseded = _superseded_register(fm_lines)

    new_status = status_for_answer(kind, choice_num)
    end = _set_frontmatter_field(lines, start, end, "status", new_status)
    for reg_key, reg_value in superseded.items():   # порядок — объявленный, не словарный
        end = _set_frontmatter_field(lines, start, end, reg_key, reg_value)
    end = _set_frontmatter_field(lines, start, end, "owner_choice", str(choice_num))
    end = _set_frontmatter_field(lines, start, end, "owner_answered_at", stamp)
    end = _set_frontmatter_field(lines, start, end, "owner_answer_via", via)
    end = _set_frontmatter_field(
        lines, start, end, "owner_answered_by", str(actor_chat_id)
    )

    end = _set_frontmatter_field(lines, start, end, "owner_answer_kind", str(kind))

    headline = (f"**{choice_label}**" if kind == KIND_ACK
                else f"**Вариант {choice_num}** — {choice_label}")
    # Приписка про закрытие обязана быть ПРАВДОЙ: «принято» карточку не закрывает,
    # и читатель карточки (человек, не только фильтр) должен узнать это здесь же.
    verdict = (
        "Карточка закрыта самим владельцем, не агентом (инвариант #14)."
        if new_status == OWNER_ONLY_STATUS else
        "Поручение ПРИНЯТО владельцем — карточка остаётся открытой "
        "(`owner-accepted`), пока агент не выполнит её критерий приёмки и не "
        "отчитается. Закрыть её в `ingested` может только этот отчёт."
    )
    body_addition = (
        f"\n\n---\n\n{ANSWER_HEADING}\n\n"
        f"{headline}\n\n"
        f"_Ответ владельца получен {stamp} ({via}). {verdict}_\n"
    )
    out = "".join(lines).rstrip("\n") + body_addition
    # След перехода — в саму карточку, вместе со статусом (ADR-129, вариант 1
    # владельца): ответ владельца тоже переезжает между деревьями, и без следа
    # он приезжает немым ровно так же, как закрытие агентом.
    out = stamp_trail(out, old=old_status, new=new_status,
                      source="owner_answer.record_owner_answer", now=now)
    atomic_save_text(out, str(p))
    record_status_write(p, old=old_status, new=new_status,
                        source="owner_answer.record_owner_answer", now=now)
    return {"path": str(p), "choice": choice_num, "already": False,
            "answered_at": stamp, "status": new_status,
            "superseded": superseded}


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

#: Написания ПУСТОГО YAML-скаляра. Пустое значение — это ОТСУТСТВИЕ ответа, а не ответ
#: со значением «пусто»: штатная карточка владельца рождается со строкой ``owner_choice: ""``
#: и носит её, пока владелец не ответил.
#:
#: **Живёт здесь, а не у сторожа (ADR-180).** До #435 список был объявлен в
#: ``monitoring.owner_answer_delivery`` — там, где след ЧИТАЮТ. Теперь его же вопрос
#: («это ответ или его отсутствие?») задаёт и ПИСАТЕЛЬ, решая, есть ли что вытеснять.
#: Две копии списка разошлись бы молча и в разные стороны: писатель счёл бы ``~`` ответом
#: и записал бы вытеснение пустоты, читатель — нет. Сторож импортирует отсюда.
EMPTY_SCALARS = ('""', "''", "~", "null", "Null", "NULL")

#: Регистр вытеснения (ADR-163): поле следа → поле, в котором ДОСЛОВНО назван вытесненный
#: им ответ. Сторож доставки читает его, чтобы отличить разобранное расхождение от спора.
#:
#: **Живёт здесь, а не у сторожа (ADR-180)** — по той же причине, по какой здесь живёт
#: :data:`OWNER_ANSWER_FIELDS`: с #435 регистр не только читают, но и ПИШУТ (см.
#: :func:`record_owner_answer`), а ADR-163 прямо предупреждает: «Другое имя = сторож снова
#: слеп». Одно имя в двух модулях достигается импортом, а не второй записью.
SUPERSEDED_FIELDS = {
    "owner_choice": "owner_choice_superseded",
    "owner_answered_at": "owner_choice_superseded_at",
    "owner_answer_via": "owner_choice_superseded_via",
}

#: Поля, которыми ``record_owner_answer`` метит ответ владельца. Один список на весь
#: модуль: вторая копия имён — ровно тот дефект, за который проект платил в #143–#145.
OWNER_ANSWER_FIELDS = (
    "owner_choice",
    "owner_answered_at",
    "owner_answer_via",
    "owner_answered_by",
)

#: Поля, по которым доказывается, что две копии несут ОДИН И ТОТ ЖЕ записанный ответ
#: (выбор И момент). Регистр отвечает на вопрос «это та же самая запись?» — им пользуется
#: доказательство разобранности (`orchestrator_queue._same_owner_answer`), и там строгость
#: намеренная: совпасть должно и то, и другое, иначе «доказано» станет догадкой.
#: **Это НЕ регистр спора** — см. ``_DISPUTE_FIELDS`` ниже (ADR-179).
_IDENTITY_FIELDS = ("owner_choice", "owner_answered_at")

#: ЧЕМ определяется СПОР о решении владельца — и только им (ADR-179, продолжение ADR-175).
#: Один и тот же кортеж ``_IDENTITY_FIELDS`` отвечал на ДВА разных вопроса: «та же запись?»
#: и «спорят ли копии о решении?». На первый ответ «нужны оба поля» верен, на второй —
#: нет: момент записи говорит, КАК ответ попал в файл, а не КАКОЙ он.
_DISPUTE_FIELDS = ("owner_choice",)

#: Провенанс: как и через что ответ попал в файл. Расхождение здесь — не спор о решении,
#: но и не пустяк: выбрать одну отметку значит затереть другую, поэтому провенанс
#: НЕ переносится никуда и называется вслух отдельным исходом.
_PROVENANCE_FIELDS = tuple(f for f in OWNER_ANSWER_FIELDS if f not in _DISPUTE_FIELDS)

CARRY_ALREADY_PRESENT = "already_present"      # след уже в этой копии — переносить нечего
CARRY_CARRIED = "carried"                      # перенесён из другой копии
CARRY_NO_ANSWER = "no_answer_recorded"         # следа нет НИГДЕ (владелец ответил руками)
CARRY_CONFLICT = "conflict"                    # две копии дают РАЗНЫЙ ответ — не выбираем
CARRY_PROVENANCE = "provenance"                # решение ОДНО, разошлись отметка/канал
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
    out: list[tuple[Path, dict]] = []
    for resolved, text in _answer_copy_texts(card_path, extra_dirs):
        fields = read_answer_fields(text)
        if fields:
            out.append((resolved, fields))
    return out


def _answer_copy_texts(card_path: str | Path,
                       extra_dirs: tuple | list = ()) -> list[tuple[Path, str]]:
    """Пути копий этой карточки и их текст. ОДИН обход на всех читателей.

    Вынесено затем, что читателей у одного набора копий стало двое — сам ответ и
    регистр вытеснения. Второй обход разошёлся бы с первым по составу источников, и
    спор считался бы по одному множеству копий, а разрешался по другому.
    """
    target = Path(card_path).resolve()
    name = target.name
    candidates: list[Path] = [Path(d) / name for d in extra_dirs]
    for wt in _worktree_dirs(target.parent):
        candidates.append(wt / "nimbalyst-local" / "tracker" / name)

    out: list[tuple[Path, str]] = []
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
            out.append((resolved, resolved.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue  # нечитаемая копия — не находка и не источник
    return out


def read_superseded_values(text: str) -> dict:
    """``{поле спора: значение, ОБЪЯВЛЕННОЕ вытесненным}`` — из ТЕКСТА одной копии.

    Регистр объявлен ровно один раз (:data:`SUPERSEDED_FIELDS`) и читается отсюда же:
    второй список полей разошёлся бы с первым — это и есть класс, которым уже болели
    два сторожа одного дома.
    """
    fm = _parse_frontmatter(_split_frontmatter(text)[0])
    out: dict = {}
    for field, reg_key in SUPERSEDED_FIELDS.items():
        value = fm.get(reg_key)
        if isinstance(value, str) and value.strip() and value.strip() not in EMPTY_SCALARS:
            out[field] = value.strip()
    return out


def retired_answer_values(card_path: str | Path,
                          extra_dirs: tuple | list = ()) -> dict:
    """``{поле: {значения, объявленные вытесненными}}`` по ВСЕМ копиям карточки.

    Вытеснение — ОБЪЯВЛЕНИЕ, а не вывод: значение попадает сюда, только если какая-то
    копия прямо назвала его вытесненным в своём регистре. Ничего не объявлено ⇒ словарь
    пуст ⇒ прежний отказ остаётся дословно (fail-CLOSED сохранён).
    """
    retired: dict = {}
    for _, text in _answer_copy_texts(card_path, extra_dirs):
        for field, value in read_superseded_values(text).items():
            retired.setdefault(field, set()).add(value)
    try:
        own = read_superseded_values(Path(card_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        own = {}
    for field, value in own.items():
        retired.setdefault(field, set()).add(value)
    return retired


def answer_disagreements(copies, retired: dict | None = None) -> dict:
    """``{поле: [различающиеся НАЗВАННЫЕ значения]}`` — по чему копии спорят на самом деле.

    ``copies`` — последовательность словарей полей (своя копия и найденные чужие).

    **Отсутствие поля не спорит ни с чем.** До цикла #428 сравнивались КОРТЕЖИ
    (``_answer_identity``, снята), где недостающее поле подставлялось пустой строкой и дальше
    участвовало как ЗНАЧЕНИЕ. Копия, где записан вариант 1 и не записан момент, и копия, где
    записаны вариант 1 И момент, давали ``('1', '')`` против ``('1', '<отметка>')`` — разные
    кортежи, то есть, по букве этого кода, «два разных ответа владельца».

    Замер 30.08 (цикл #428) на живом прод-дереве: шаг 2 протокола (инжест ответов владельца)
    отказал по ЧЕТЫРЁМ карточкам из семи, и по двум из них — ``owner-decision-AI1-approach``
    и ``owner-decision-urovni-dokazatelnosti`` — ответ владельца во ВСЕХ копиях был один и тот
    же, вариант 1; расходилось ровно то, что в части копий отметки времени просто нет.
    Цена выше, чем у шумной строки в отчёте: ``set-status … ingested`` возвращал 2 и карточка
    не закрывалась, то есть разобранное решение владельца оставалось в очереди как
    неразобранное — и следующая сессия разбирала его заново.

    Тот же корень, что у пустого скаляра ``owner_choice: ""`` (цикл #427) и у сравнения
    ``1`` против ``"1"`` в сторожe доставки (цикл #428): **сторож принимает «не сказано» за
    сказанное.** Третье место, третья форма записи — поэтому чинится правилом, а не случаем.

    Fail-CLOSED там, где спор настоящий: если поле НАЗВАНО больше чем в одной копии и
    значения разные, оно попадает в результат и закрывать карточку по-прежнему нельзя.
    **Сужение до `owner_choice` (30.08, цикл #434, ADR-179).** До него спором считалось и
    расхождение `owner_answered_at`. Замер по ВСЕЙ популяции карточек решений прод-дерева:
    расхождение было у пяти карточек, спор о решении — у трёх; у `aave-na-arbitrum` и
    `tret-flota-nelzya-proverit` владелец ответил ОДИНАКОВО (вариант 1) и разошлась одна
    отметка — пачечная `20:30:00Z` текстовой сессии против посекундной телеграмной. Эти две
    висели в прод-дереве `owner-done` и не могли быть закрыты НИ ОДНИМ агентом никогда:
    каждый цикл шаг 2 предъявлял их как неразобранный ответ владельца, и следующая сессия
    разбирала их заново. Соседний сторож (`monitoring/owner_answer_delivery`) то же правило
    получил решением ADR-175 — здесь оно доезжает до второго.
    """
    return _named_divergences(copies, _DISPUTE_FIELDS, retired)


def answer_provenance_divergences(copies) -> dict:
    """``{поле: [различающиеся НАЗВАННЫЕ значения]}`` — по чему копии расходятся в ПРОВЕНАНСЕ.

    Провенанс (`owner_answered_at`, `owner_answer_via`, `owner_answered_by`) отвечает на
    вопрос «как ответ попал в файл», а не «какой он». Расхождение здесь человека не зовёт
    (ADR-175/ADR-179), но и не молчит: поле НЕ переносится ни в какую сторону — выбрать одну
    отметку значит затереть другую, а чужой провенанс не наша собственность.
    """
    return _named_divergences(copies, _PROVENANCE_FIELDS)


def _named_divergences(copies, keys, retired: dict | None = None) -> dict:
    """Общая единица правила: НАЗВАННЫЕ значения ``keys``, различающиеся между копиями.

    Одна реализация на оба регистра: вторая копия этой логики разошлась бы с первой ровно
    так же, как разошлись два сторожа одного дома (#434).
    """
    retired = retired or {}
    named: dict = {}
    for fields in copies:
        for key in keys:
            value = str(fields.get(key, "")).strip()
            if value and value not in retired.get(key, ()):
                named.setdefault(key, set()).add(value)
    return {k: sorted(v) for k, v in sorted(named.items()) if len(v) > 1}


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
                "path": str(p), "fields": {}, "provenance": {}}

    mine = read_answer_fields(text)
    copies = find_answer_copies(p, extra_dirs)

    # Разные ответы среди источников — стоп до любой записи. Спор считается по
    # НАЗВАННЫМ значениям: копия, где поля нет, молчит о нём, а не возражает.
    # Регистр вытеснения спрашивается ДО того, как расхождение будет названо спором:
    # значение, которое карточка сама объявила вытесненным, не возражает — владелец уже
    # выбрал сторону (ADR-163). Соседний сторож доставки это правило знал, а эта дверь —
    # нет, и шаг 2 звал человека на РАЗОБРАННЫЙ спор (ADR-210). Fail-CLOSED цел: ничего
    # не объявлено ⇒ `retired` пуст ⇒ отказ прежний дословно.
    retired = retired_answer_values(p, extra_dirs)
    disagreements = answer_disagreements([f for _, f in copies] + ([mine] if mine else []),
                                         retired)
    if disagreements:
        where = ", ".join(str(src) for src, _ in copies) or "—"
        named = "; ".join(f"{k}: {v}" for k, v in disagreements.items())
        raise AnswerConflict(
            f"{p.name}: копии карточки несут РАЗНЫЕ ответы владельца "
            f"({named}); источники: {where}. "
            f"Выбрать сторону молча нельзя — сверьте руками."
        )

    # Решение ОДНО, а записано по-разному: провенанс не спор (ADR-179), человека не зовём —
    # но и не переносим, потому что выбрать одну отметку значит затереть другую.
    provenance = answer_provenance_divergences(
        [f for _, f in copies] + ([mine] if mine else []))
    prov_named = "; ".join(f"{k}: {v}" for k, v in provenance.items())

    if all(mine.get(k) for k in _IDENTITY_FIELDS):
        if provenance:
            return {"verdict": CARRY_PROVENANCE, "path": str(p), "fields": mine,
                    "provenance": provenance, "added": {},
                    "detail": f"решение ОДНО, разошёлся лишь провенанс ({prov_named}) — "
                              f"переносить нечего"}
        return {"verdict": CARRY_ALREADY_PRESENT, "path": str(p), "fields": mine,
                "provenance": {}, "detail": "след решения уже в этой копии"}
    if not copies:
        return {"verdict": CARRY_NO_ANSWER, "path": str(p), "fields": mine,
                "provenance": {}, "detail": "следа ответа нет ни в одной копии карточки "
                                            "(владелец мог ответить правкой статуса руками)"}

    source, fields = copies[0]
    # Спорное поле провенанса не переносится НИКУДА: у нас нет основания предпочесть одну
    # его запись другой, а запись затирает.
    merged = {k: v for k, v in fields.items() if k not in provenance}
    merged.update(mine)  # уже записанное здесь главнее: свой файл не переписываем
    added = {k: v for k, v in merged.items() if mine.get(k) != v}
    if not added:
        if provenance:
            return {"verdict": CARRY_PROVENANCE, "path": str(p), "fields": mine,
                    "provenance": provenance, "added": {},
                    "detail": f"решение ОДНО, разошёлся лишь провенанс ({prov_named}) — "
                              f"переносить нечего"}
        return {"verdict": CARRY_ALREADY_PRESENT, "path": str(p), "fields": mine,
                "provenance": {}, "detail": "след решения уже в этой копии"}

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
                "provenance": provenance,
                "detail": "во frontmatter карточки некуда писать след решения"}

    for key in OWNER_ANSWER_FIELDS:      # порядок полей — стабильный, не словарный
        if key in added:
            end = _set_frontmatter_field(lines, start, end, key, added[key])
    atomic_save_text("".join(lines), str(p))
    if provenance:
        return {"verdict": CARRY_PROVENANCE, "path": str(p), "fields": merged,
                "added": added, "source": str(source), "provenance": provenance,
                "detail": f"перенесено: {', '.join(sorted(added))}; спорный провенанс "
                          f"({prov_named}) НЕ перенесён — источник {source}"}
    return {"verdict": CARRY_CARRIED, "path": str(p), "fields": merged,
            "added": added, "source": str(source), "provenance": {},
            "detail": f"след решения перенесён из {source}"}


# ── ВИДИМОСТЬ ответа владельца из ЛЮБОГО дерева (шаг 2 протокола) ────────────
#
# **Авария 14.08, замеренная целиком.** Владелец ответил на карточку
# `owner-decision-stranitsa-treka-chetvertyi-den-pryachet` в 12:26:56Z (Телеграм, вариант 1);
# след записан честно — `data/tracker_status_audit.jsonl` строка 155, писатель
# `spa_core/telegram/bot.py`. Шаг 2 протокола, ДОСЛОВНО предписанный работать из
# изолированного worktree (§3.4), вернул оттуда **пустой список**: бот пишет ответ в
# ПРОД-дерево, а на `origin/main` он не уезжает ничем — мост доставки везёт только то, что
# создал или закрыл сам за прогон (`IDLE`, ADR-081), а ответа владельца он не создавал.
# Два прогона цикла #230 (16:15Z и 17:01Z) прошли мимо живого решения.
#
# **Почему это опаснее уже закрытого зеркала.** `inbox-otvet-vladeltsa-zhivet-tolko-v-host-dereve`
# (#182) — про ЛОЖНОЕ «есть решение»: оно стоит времени сессии. Здесь ЛОЖНОЕ «решений нет»:
# оно теряет РЕШЕНИЕ ВЛАДЕЛЬЦА, и заметить нечем — пустой список выглядит ровно как честная
# пустая очередь. `carry_owner_answer` тут не помогает по построению: он переносит след,
# когда сессия УЖЕ разбирает карточку, а сюда сессия не доходит вовсе.
#
# **Почему опрашивается ТОЛЬКО главное дерево, а не все 37.** Ответ владельца пишет бот, а бот
# запущен в прод-дереве — это маршрут, а не предположение (тот же довод, что у `_worktree_dirs`).
# Опрос всех рабочих деревьев дал бы `owner-done` из десятков брошенных `/tmp`-worktree, где
# решение давно разобрано и доставлено, — то есть ровно ту находку-пустышку, которая приучает
# пролистывать раздел целиком (урок #243: девять десятых раздела учили не читать его).
#
# **Инвариант #14 не ослаблен ни на строку.** Здесь ничего не записывается: модуль только
# ЧИТАЕТ чужую копию и НАЗЫВАЕТ её. `owner-done` по-прежнему ставит только владелец внутри
# `record_owner_answer` со сверкой личности.

#: Вердикты сверки «а нет ли ответа владельца в другом дереве».
CROSS_SAME_TREE = "same_tree"          # читаем прод-дерево — вопроса о втором дереве нет
CROSS_AGREES = "agrees"                # главное дерево опрошено, невидимых ответов нет
CROSS_FOUND = "owner_answer_only_in_main_tree"
CROSS_UNMEASURED = "unmeasured"        # опросить не удалось — это НЕ «ок»

#: Статусы, из которых следует, что ответ по этой карточке в ЧИТАЕМОМ дереве уже разобран.
#: Такая карточка находкой не считается — граница осознанная: если владелец ответил ПОВТОРНО
#: уже после инжеста, доказать это здесь нечем, и доказательство живёт там, где ему место —
#: в сверке следа (`_same_owner_answer` + `carry_owner_answer`, вердикт `answer_ingested_proven`).
#: `owner-accepted` здесь тоже «ответ виден»: владелец ответил, и читаемое дерево это
#: показывает. Работа при этом ещё впереди — но вопрос раздела ровно один: «есть ли
#: ответ владельца, невидимый читателю», и на него ответ «есть, виден» (#350).
_LOCAL_HANDLED = frozenset({OWNER_ONLY_STATUS, OWNER_ACCEPTED_STATUS,
                            "ingested", "done", "owner-done-archived"})

#: Статусы, в которых карточка ГЛАВНОГО дерева несёт ответ владельца. Пропустить здесь
#: `owner-accepted` значило бы вернуть дефект #231: ответ владельца, невидимый шагу 2
#: из worktree, — только теперь молча и для целого КЛАССА ответов («принято»).
_ANSWERED_IN_MAIN = frozenset({OWNER_ONLY_STATUS, OWNER_ACCEPTED_STATUS})


class ForeignOwnerAnswer:
    """Ответ владельца, лежащий в ГЛАВНОМ дереве и невидимый читаемому."""

    __slots__ = ("card_id", "path", "tree", "title", "local_status", "local_path",
                 "answer_fields", "age_hours")

    def __init__(self, card_id, path, tree, title, local_status, local_path,
                 answer_fields, age_hours):
        self.card_id = card_id
        self.path = path                  # копия в главном дереве (её и читаем)
        self.tree = tree                  # корень главного дерева
        self.title = title
        self.local_status = local_status  # "" — файла в читаемом дереве нет вовсе
        self.local_path = local_path
        self.answer_fields = answer_fields
        self.age_hours = age_hours        # None — момент ответа не записан/не разобран

    def as_dict(self) -> dict:
        return {
            "id": self.card_id,
            "source_tree": str(self.tree),
            "source_path": str(self.path),
            "local_status": self.local_status or "(файла нет)",
            "local_path": str(self.local_path),
            "owner_answer": dict(self.answer_fields),
            "age_hours": self.age_hours,
        }


def _age_hours(fields: dict, now: datetime) -> Optional[float]:
    """Сколько часов ответ владельца лежит без разбора. None — момент не разобран.

    Время — ВХОД (`now`), а не окружение: фикстура с литеральной датой начинает падать от
    одного сдвига календаря по причине, не имеющей отношения к проверяемому поведению
    (`.claude/rules/deployment.md`).
    """
    stamp = str(fields.get("owner_answered_at", "") or "").strip()
    if not stamp:
        return None
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((now - dt).total_seconds() / 3600.0, 2)


def scan_owner_answers_elsewhere(tracker_dir, *, now: datetime | None = None):
    """(вердикт, находки, причина-если-не-измерено) для трекера ``tracker_dir``.

    Отвечает ровно на один вопрос: **есть ли в ГЛАВНОМ рабочем дереве карточка со статусом
    ``owner-done``, которой читаемое дерево не покажет.** Ничего не пишет и не «синхронизирует»:
    массовый перенос стёр бы карточки, живущие только в одном дереве (тот же довод, что у
    `check_tracker_drift`).

    Fail-CLOSED: не удалось определить деревья / читаемый трекер не внутри рабочего дерева ⇒
    ``CROSS_UNMEASURED`` с причиной. Молчаливого «всё в порядке» здесь нет.
    """
    now = now or datetime.now(timezone.utc)
    try:
        d = Path(tracker_dir).resolve()
    except OSError as exc:                                    # noqa: BLE001
        return CROSS_UNMEASURED, [], f"путь трекера не разрешился: {exc}"
    if not d.is_dir():
        return CROSS_UNMEASURED, [], f"каталога трекера нет: {d}"

    trees = _worktree_dirs(d)
    if not trees:
        return (CROSS_UNMEASURED, [],
                "`git worktree list` не назвал ни одного дерева — какое дерево главное, "
                "здесь НЕ измерено; путь не выдумываю")
    try:
        main_tree = trees[0].resolve()
    except OSError as exc:                                    # noqa: BLE001
        return CROSS_UNMEASURED, [], f"главное дерево не разрешилось: {exc}"

    # Какому дереву принадлежит ЧИТАЕМЫЙ трекер. Определяем по вложенности, а не по cwd:
    # cwd на выбор трекера не влияет (измерено #140), а трекер могли указать флагом.
    own_tree = None
    for wt in trees:
        try:
            wt_r = wt.resolve()
        except OSError:                                       # noqa: BLE001
            continue
        if d == wt_r or wt_r in d.parents:
            # Самое ГЛУБОКОЕ совпадение: главное дерево может быть родителем линкованного
            # (`.claude/worktrees/...` лежит внутри прод-дерева), и первое же совпадение
            # объявило бы своим чужое дерево.
            if own_tree is None or len(wt_r.parts) > len(own_tree.parts):
                own_tree = wt_r
    if own_tree is None:
        return (CROSS_UNMEASURED, [],
                f"трекер {d} не лежит ни в одном рабочем дереве этого репозитория")
    if own_tree == main_tree:
        # Читаем прод-дерево — то самое, куда пишет бот. Второго дерева спрашивать не о чем,
        # и печатать здесь находку значило бы будить сессию на верном действии.
        return CROSS_SAME_TREE, [], None

    try:
        rel = d.relative_to(own_tree)
    except ValueError as exc:                                 # noqa: BLE001
        return CROSS_UNMEASURED, [], f"трекер вне своего дерева: {exc}"
    foreign_dir = main_tree / rel
    if not foreign_dir.is_dir():
        return (CROSS_UNMEASURED, [],
                f"в главном дереве нет каталога трекера {foreign_dir} — ответ владельца "
                f"мог быть записан туда, и проверить это нечем")

    findings: list[ForeignOwnerAnswer] = []
    try:
        candidates = sorted(foreign_dir.glob("*.md"))
    except OSError as exc:                                    # noqa: BLE001
        return CROSS_UNMEASURED, [], f"каталог главного дерева нечитаем: {exc}"

    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue          # битая копия — не находка и не доказательство (fail-open по файлу)
        fm = _parse_frontmatter(_split_frontmatter(text)[0])
        if str(fm.get("status", "") or "").strip() not in _ANSWERED_IN_MAIN:
            continue
        local = d / p.name
        local_status = ""
        if local.is_file():
            try:
                local_fm = _parse_frontmatter(_split_frontmatter(
                    local.read_text(encoding="utf-8"))[0])
                local_status = str(local_fm.get("status", "") or "").strip()
            except (OSError, UnicodeDecodeError):
                local_status = ""
        if local_status in _LOCAL_HANDLED:
            continue          # здесь ответ уже виден или уже разобран — не находка
        fields = read_answer_fields(text)
        findings.append(ForeignOwnerAnswer(
            card_id=p.stem, path=p, tree=main_tree,
            title=str(fm.get("title", "") or "").strip() or p.stem,
            local_status=local_status, local_path=local,
            answer_fields=fields, age_hours=_age_hours(fields, now),
        ))
    return (CROSS_FOUND if findings else CROSS_AGREES), findings, None
