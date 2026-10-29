"""Дошёл ли ОТВЕТ на задание владельца до его канала (ADR-863, цикл #980).

Предмет этого модуля — НЕ «сделана ли работа» и не «закрыта ли карточка». Он один:
**узнал ли владелец ответ на СВОЮ просьбу**. Это два разных вопроса, и до ADR-863 на
второй не отвечал никто.

Замер 2026-10-29, из-за которого модуль понадобился. Владелец сказал «проверь дашборд»
**семь раз** (15.10 · 15.10 · 16.10 · 16.10 · 17.10 · 24.10 · 29.10 — последний раз прямо
во время цикла, который на эту просьбу отвечал). Проверка была сделана дважды (#966, #977),
числа сошлись, и оба ответа легли **в тело карточки в файле git**. С его стороны семь
просьб выглядели как семь проигнорированных.

Канал к владельцу при этом СУЩЕСТВОВАЛ и работал — долговечные исходящие
``data/intake_outbox.json`` → Telegram (``intake.flush_outbox``, доставка не менее одного
раза). У него просто не было писателя для этого случая: ``cockpit_loop._ensure_done_notice``
закрыт ДВУМЯ гейтами, и оба мимо задания из голоса —

* ``is_cockpit(fm)`` — ``source`` обязан быть из ``COCKPIT_SOURCES`` (``cockpit`` /
  ``cockpit-voice``), а голосовое задание владельца рождается с ``source: voice`` либо
  ``source: telegram``;
* ``verified_by_probe`` — его ставит только ``close_verified``, то есть путь пульта.

Население на 29.10: карточек ``voice``/``telegram`` — **80**, закрытых ``done`` — **72**,
несущих ЛЮБУЮ запись об уведомлении (``owner_notice``) — **0**. Ни одно задание владельца
за всю историю очереди не оставило следа о том, что ответ до него дошёл.

## Что здесь сделано, а что намеренно НЕ сделано

**Одна дверь.** Второго писателя понятия «уведомить владельца» не заводится (ADR-220):
записи кладутся в те же исходящие приёма тем же ``intake._outbox_put``, что и уведомления
пульта. Этот модуль добавляет к каналу ПИСАТЕЛЯ и ЧИТАТЕЛЯ, а не канал.

**Историческое население НЕ рассылается.** 72 карточки закрыты до появления канала;
отправить владельцу 72 (или даже 5) сообщения о работе, законченной недели назад, —
не исполнение просьбы, а шум. Поэтому они получают ТРЕТИЙ исход — «не измерено» с
названной причиной, — и это ЗАМЕР, а не умолчание.

**Границу рисует ПОЛЕ, а не дата.** Соблазн был отсечь историю календарём
(«уведомлять закрытые после 29.10»), и это ровно бомба из
``.claude/rules/deployment.md`` § «Время в тестах»: литеральная дата начинает врать от
того, что сдвинулся календарь, а не от того, что изменилось поведение. Здесь граница —
наличие метки ``owner_notice``, которую ставит сам путь закрытия. Карточка без метки
закрыта тем кодом, который метку ставить не умел; это проверяемо и не зависит от часов.

## Три исхода различимы (инв. #17)

Вопрос «дошёл ли ответ» имеет ровно три ответа, и они требуют разных действий:

* ``True``  — ответ ОТДАН каналу: метка ``answer-sent`` стои́т, и в исходящих записи
  больше нет, то есть ``flush_outbox`` её принял;
* ``False`` — ответ ЕЩЁ НЕ отдан: метка ``answer-pending`` (закрыли, уведомление не
  положено) либо ``answer-sent`` при записи, ВСЁ ЕЩЁ лежащей в исходящих (Telegram не
  принял — сеть, заслон потока, нет chat_id);
* ``None``  — **НЕ ИЗМЕРЕНО**: метки нет вовсе. Карточка закрыта до появления канала,
  либо ответа в ней не записано ничем. Молчание не имеет права читаться как «дошло».

Сильнее ``True`` этот модуль не утверждает НАМЕРЕННО. «Отдано каналу» — не «прочитано
владельцем» и даже не «Telegram подтвердил доставку конкретного сообщения»: за
``message_ids`` отвечает журнал отправок карточек решения
(``notify.delivery_verdict``), у исходящих приёма такой записи нет по построению.
Назвать здесь «доставлено» значило бы повторить ровно тот дефект, который чинил замер
цикла #385: ответ на СВОЙ вопрос («мы положили в очередь») выдаётся за ответ на нужный
(«владелец получил»).

# LLM_FORBIDDEN — детерминированный учёт, никакого суждения модели (инв. #3).
"""
from __future__ import annotations

import html
import re
from pathlib import Path

#: Источники карточек пульта — ОДНА копия, у пульта (ADR-760).
from spa_core.studio_os.mission_intake import COCKPIT_SOURCES

#: Каналы, которыми рождается задание САМОГО владельца. Пульт — часть населения, а не
#: отдельный случай: `cockpit_loop` остаётся единственным писателем своих событий, но
#: предмет «ответ дошёл до владельца» у всех четырёх каналов ОДИН.
#:
#: `nimbalyst` сюда НЕ входит и это замер, а не осторожность: карточки с этим источником
#: заводят агенты и сторожа (209 из 891 на 29.10), и уведомлять владельца о закрытии
#: находки сторожа значило бы завалить чат работой, которую он не просил.
OWNER_TASK_SOURCES = tuple(COCKPIT_SOURCES) + ("voice", "telegram")

#: Состояния метки `owner_notice`, принадлежащие ЭТОМУ предмету. Значения пульта
#: (`done-verified`, `not-accepted:*`) здесь не перечислены и не трогаются: поле одно,
#: знание о том, что владельцу сказали последним, тоже одно, а состояния не пересекаются.
ANSWER_PENDING = "answer-pending"
ANSWER_SENT = "answer-sent"

#: Ключ события в исходящих: «<карточка>#<событие>». Отличен от событий пульта, поэтому
#: «принято», «сделано и проверено» и «вот ответ» друг друга в очереди не вытесняют.
EVENT_ANSWER = "answer"

#: Метки, КАЖДАЯ из которых утверждает «владельцу назван результат его задания», и ключ
#: события, по которому эту запись надо искать в исходящих.
#:
#: Путь пульта (`done-verified`) входит сюда НЕ из вежливости: он кладёт запись в ТЕ ЖЕ
#: исходящие и владелец получает тот же Telegram, то есть по предмету этого модуля он
#: отвечает ДА. Назвать его «не измерено» значило бы объявить слепым работающий канал —
#: ровно та ошибка, против которой написан инв. #17 (три исхода РАЗЛИЧИМЫ, а не «всё, что
#: не моё, — неизвестно»).
#:
#: `not-accepted:*` сюда НЕ входит: он говорит «в работе, ещё не принята», то есть про
#: ответ не утверждает ничего.
_ANSWERING_EVENTS = {
    ANSWER_SENT: EVENT_ANSWER,
    "done-verified": "done-verified",
}

#: Статусы, на которых задание считается ЗАКРЫТЫМ. Та же пара, что у следа закрытия
#: (`queue.EVIDENCED_CLOSING_STATUSES`) — своей редакции здесь нет намеренно.
CLOSED_STATUSES = frozenset({"done", "owner-done"})

#: Род записанного ответа. Порядок — порядок предпочтения при печати.
EV_PROBE = "probe"
EV_CARRIED = "carried_to"
EV_SECTION = "answer_section"

#: Заголовок в теле, которым цикл помечает ответ на просьбу. Ищется ОДНИМ выражением:
#: второй редакции этого знания быть не должно, иначе «ответ есть» начнёт зависеть от
#: того, какой читатель спросил.
_ANSWER_HEADING = re.compile(
    r"(?mi)^\#{2,}\s*(?:[^\n]*\b)?(ОТВЕТ|ОТВЕЧАЮ|ЗАМЕР|РЕЗУЛЬТАТ|РАЗОБРАНО)\b")


def is_owner_task(fm: dict | None) -> bool:
    """Задание ли это САМОГО владельца — по объявленному каналу прихода."""
    return str((fm or {}).get("source") or "") in OWNER_TASK_SOURCES


def is_closed(fm: dict | None) -> bool:
    return str((fm or {}).get("status") or "").strip() in CLOSED_STATUSES


def answer_evidence(fm: dict | None, body: str | None) -> tuple[str, str] | None:
    """ЧТО именно записано как ответ. ``None`` — ответа не записано ничем.

    Порядок спроса — от самого сильного основания к самому слабому, и слабейшее
    («в теле есть раздел с ответом») всё-таки сильнее пустоты: именно в этой форме
    лежали оба ответа про дашборд.

    ``None`` НЕ означает «работа не сделана» — только «в карточке нет ничего, что можно
    назвать владельцу ответом». Уведомление в этом случае не кладётся: сказать «готово»,
    не умея сказать ЧТО, — обещание, а не ответ.
    """
    fm = fm or {}
    probe = str(fm.get("verified_by_probe") or "").strip()
    if probe:
        return EV_PROBE, probe
    carried = str(fm.get("carried_to") or "").strip()
    if carried:
        return EV_CARRIED, carried
    if body and _ANSWER_HEADING.search(body):
        return EV_SECTION, ""
    return None


def answer_notice_text(title: str, kind: str, detail: str, card_name: str = "") -> str:
    """Текст владельцу: простыми словами, с ОСНОВАНИЕМ и адресом ответа (§2.4, инв. #15).

    Основание названо честно: «проверено пробой» там, где проба есть, и «ответ в теле
    карточки» там, где его нет. Подставлять первое вместо второго значило бы выдумать
    проверку, которой не было.
    """
    t = html.escape(str(title or card_name or "задание"))
    where = html.escape(str(card_name or ""))
    if kind == EV_PROBE:
        why = f"проверено пробой <code>{html.escape(detail)}</code>"
    elif kind == EV_CARRIED:
        why = f"ответ здесь: <code>{html.escape(detail)}</code>"
    else:
        why = "ответ записан в теле карточки"
    tail = f"\n📄 <code>{where}</code>" if where else ""
    return f"💬 Твоя просьба «{t}» — ответ есть: {why}.{tail}"


def _outbox_keys(outbox_path=None) -> set[str] | None:
    """Ключи, ЛЕЖАЩИЕ в исходящих сейчас. ``None`` — исходящие НЕ ПРОЧИТАНЫ.

    Читаемость спрашивается ОТДЕЛЬНЫМ вопросом, и это не перестраховка, а урок
    ``pyflakes`` из ``.claude/rules/deployment.md``: у ``intake._outbox_load`` свой,
    совершенно законный контракт — нечитаемый файл он отодвигает в сторону и отдаёт
    ПУСТОЙ список, чтобы приём не встал. Для нашего вопроса пустой список означает
    «записи в очереди нет», то есть «канал её принял», — и первая редакция этой функции
    ровно так и ответила: нечитаемые исходящие она объявила ДОСТАВКОЙ. Fail-OPEN тише
    красного теста, поэтому опаснее; нашла его обратная сцена
    ``test_unreadable_outbox_is_unmeasured_not_delivered``.

    Поэтому порядок такой: сперва «файл вообще разбирается?», и только потом — содержимое
    у ``_outbox_load`` (единственного читателя смысла записей; второго знания о формате
    здесь не заводится, спрашивается лишь разбор). Побочно это делает вердикт
    безвредным: отказавшись ДО ``_outbox_load``, он не отодвигает файл в сторону —
    читатель не вправе менять то, о чём судит.

    Файла нет вовсе ⇒ пустое множество, а не «не измерено»: ``flush_outbox`` оставляет
    после себя именно отсутствие ожидающих записей, и отличить «ещё не создавали» от
    «всё отдано» здесь не нужно — в обоих случаях этой записи в очереди НЕТ.
    """
    from spa_core.owner_queue import intake
    import json

    p = Path(outbox_path) if outbox_path is not None else intake._outbox_path()
    if p.exists():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict) or not isinstance(doc.get("pending"), list):
            return None
    try:
        items = intake._outbox_load(outbox_path)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(items, list):
        return None
    return {str(i.get("key")) for i in items if isinstance(i, dict)}


def delivery_verdict(path, *, outbox_path=None) -> tuple[bool | None, str]:
    """Дошёл ли ответ по карточке ``path`` до канала владельца.

    Возврат — ``(True | False | None, причина словами)``; смысл трёх исходов и граница
    утверждения ``True`` объявлены в docstring модуля. Пара к
    ``notify.delivery_verdict`` (та — про карточку РЕШЕНИЯ и про ``message_ids``).
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"карточка не прочитана ({exc.__class__.__name__}) — НЕ ИЗМЕРЕНО"
    fm, body = split_frontmatter(text)
    if not is_owner_task(fm):
        return None, (f"источник «{fm.get('source') or '(нет)'}» не из каналов владельца "
                      f"{OWNER_TASK_SOURCES} — предмета нет")
    mark = str(fm.get("owner_notice") or "").strip()
    if not mark:
        ev = answer_evidence(fm, body)
        if ev is None:
            return None, ("метки уведомления нет и ответа в карточке не записано ничем — "
                          "НЕ ИЗМЕРЕНО")
        return None, ("метки уведомления нет: карточка закрыта путём, который метку ставить "
                      "не умел (до ADR-863) — НЕ ИЗМЕРЕНО, а не «дошло»")
    if mark == ANSWER_PENDING:
        return False, ("уведомление ещё не положено в исходящие — закрытие записано, "
                       "дочистка (`cockpit_loop.sweep_notices`) его положит")
    event = _ANSWERING_EVENTS.get(mark)
    if event is not None:
        keys = _outbox_keys(outbox_path)
        if keys is None:
            return None, "исходящие приёма не прочитаны — НЕ ИЗМЕРЕНО"
        if f"{p.name}#{event}" in keys:
            return False, ("запись ВСЁ ЕЩЁ лежит в исходящих — канал её не принял "
                           "(сеть, заслон потока или нет chat_id); повторит следующий прогон")
        return True, (f"ответ отдан каналу владельца событием «{mark}»: "
                      f"исходящие запись приняли")
    return None, (f"метка «{mark}» не утверждает, что владельцу назван ОТВЕТ "
                  f"(это другое событие пути пульта) — НЕ ИЗМЕРЕНО")


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Плоский разбор frontmatter + тело. Одна копия на модуль, только stdlib.

    Нарочно НЕ полный YAML: читаются только скалярные поля верхнего уровня, а именно они
    и нужны (`source`, `status`, `owner_notice`, `carried_to`, `verified_by_probe`).
    Вложенный `trackerStatus` сюда не попадает и не требуется.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out, text[end + 4:]


# ── перепись: сколько ответов владельцу дошло, сколько нет, сколько НЕ ИЗМЕРЕНО ────────
DELIVERED, PENDING, UNMEASURED, NO_ANSWER = "delivered", "pending", "unmeasured", "no_answer"


def measure(tracker_dir, *, outbox_path=None) -> dict:
    """Перепись закрытых заданий владельца по исходу доставки ОТВЕТА.

    Отвечает на один вопрос — «про сколько закрытых просьб владельца мы не можем сказать,
    узнал ли он ответ». Число отсутствия (`unmeasured`) публикуется ЗНАЧЕНИЕМ и читается
    вердиктом (урок ADR-851/856: третий исход, который не доезжает до вердикта, не
    существует).
    """
    d = Path(tracker_dir)
    counts = {DELIVERED: 0, PENDING: 0, UNMEASURED: 0, NO_ANSWER: 0}
    rows: list[dict] = []
    if not d.is_dir():
        return {"tracker_dir": str(d), "closed_owner_tasks": None, "counts": counts,
                "rows": rows, "unmeasured_reason": f"каталога трекера нет: {d}"}
    for p in sorted(d.glob("inbox-*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = split_frontmatter(text)
        if not (is_owner_task(fm) and is_closed(fm)):
            continue
        ev = answer_evidence(fm, body)
        ok, why = delivery_verdict(p, outbox_path=outbox_path)
        if ev is None:
            kind = NO_ANSWER
        elif ok is True:
            kind = DELIVERED
        elif ok is False:
            kind = PENDING
        else:
            kind = UNMEASURED
        counts[kind] += 1
        rows.append({"card": p.name, "outcome": kind, "evidence": ev[0] if ev else None,
                     "reason": why})
    return {"tracker_dir": str(d), "closed_owner_tasks": sum(counts.values()),
            "counts": counts, "rows": rows, "unmeasured_reason": None}


# ── эталон класса: две сцены, отличающиеся РОВНО меткой ───────────────────────────────
DRIVE_CONFLATES, DRIVE_UNMEASURED, DRIVE_DISTINGUISHES = (
    "conflates", "unmeasured", "distinguishes")


def drive_exemplar() -> dict:
    """Поднять НАСТОЯЩИЙ :func:`delivery_verdict` на трёх сценах одной карточки.

    Сцены отличаются РОВНО одним: меткой ``owner_notice``. Всё остальное — источник,
    статус, тело, основание ответа — побайтно одно и то же, поэтому разный исход
    приписать нечему, кроме предмета.

    Нужен, чтобы проба приёмки мерила ПОВЕДЕНИЕ живой двери, а не наличие модуля:
    дверь, отвечающая одно и то же на «закрыто до появления канала» и на «ответ отдан
    каналу», и есть дословная авария 29.10.
    """
    import tempfile

    base = ("---\n"
            "trackerStatus:\n  type: inbox\n"
            "title: проверь дашборд\n"
            "status: done\n"
            "source: voice\n"
            "carried_to: nimbalyst-local/tracker/inbox-anchor.md\n"
            "{mark}"
            "---\n\n## ОТВЕТ\n\nдашборд проверен\n")
    scenes = {"scene_no_mark": "",
              "scene_pending": f"owner_notice: {ANSWER_PENDING}\n",
              "scene_sent": f"owner_notice: {ANSWER_SENT}\n"}
    out: dict = {}
    try:
        with tempfile.TemporaryDirectory() as td:
            ob = Path(td) / "outbox.json"
            ob.write_text('{"schema": 1, "pending": []}', encoding="utf-8")
            for name, mark in scenes.items():
                c = Path(td) / f"inbox-{name}.md"
                c.write_text(base.format(mark=mark), encoding="utf-8")
                ok, why = delivery_verdict(c, outbox_path=ob)
                out[name] = {"verdict": ok, "reason": why}
    except Exception as exc:  # noqa: BLE001
        return {"kind": DRIVE_UNMEASURED,
                "reason": f"сцену не удалось собрать: {type(exc).__name__}: {exc}"}
    got = tuple(out[k]["verdict"] for k in ("scene_no_mark", "scene_pending", "scene_sent"))
    if len(set(map(repr, got))) < 3:
        return {"kind": DRIVE_CONFLATES, "scenes": out, "verdicts": got}
    out["kind"] = DRIVE_DISTINGUISHES if got == (None, False, True) else DRIVE_CONFLATES
    out["verdicts"] = got
    return out
