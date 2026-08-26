#!/usr/bin/env python3
"""Сообщение предложило владельцу выбор — и уехало БЕЗ КНОПОК. Кто это измеряет.

Жалоба владельца 14.08 (09:37Z, карточка `inbox-a-zadacha-pochinit-vse-taki-esche-raz-so`),
дословно: *«сообщение, которым мне пишет "нужно твоё решение", пишет варианты ответов —
кнопок нету»*. Цикл #228 закрыл первую половину той же жалобы (спам из облака); вторая
половина — эта.

Почему на неё нельзя было ответить (замер цикла #229)
------------------------------------------------------------------------------
Журналов канала два, и ни один не отвечает на вопрос владельца:

* ``data/telegram_owner_decisions.json`` — знает про кнопки (`buttons`), но ТОЛЬКО про
  свой путь (`owner_decisions.register_push`). Любой другой отправитель для него не
  существует. По нему после 10.08 всё чисто — и это правда ровно про один путь.
* ``data/alert_history.json`` — знает про ВСЕ отправки (с #215/#218 обе двери пишут), но
  хранит `preview` длиной 80 символов и НЕ хранит, была ли клавиатура. Блок «Варианты:»
  в 80 символов не помещается по построению: у нашего же текста первые 80 символов — это
  «🧑‍⚖️ Нужно твоё решение» + заголовок карточки.

То есть класс жалобы был неизмерим ПО ПОСТРОЕНИЮ, а не «не найден». Поэтому мерим там,
где оба факта ещё есть — **в дверях, в момент отправки**: полный текст и клавиатура видны
только там. Скан по журналу после этого становится тривиальным и честным.

Что здесь есть
------------------------------------------------------------------------------
``offers_choice(text)``  — предлагает ли сообщение выбор ВАРИАНТА (детерминированно, по
                           формам, которые наш же билдер и печатает).
``scan(entries)``        — какие ДОСТАВЛЕННЫЕ сообщения предлагали выбор без кнопок.
                           Записи без поля `buttons` — «не измерено», отдельной строкой:
                           старый журнал не имеет права выглядеть чистым (fail-CLOSED).
                           Починенные штатным ремонтом — на СВОЕЙ полке (`healed`), см. ниже.

Почему у починенного случая своя полка (замер #370)
------------------------------------------------------------------------------
24.08 в 11:21:37Z вопрос владельцу («Ежедневную проверку аналитики некому гонять»,
сообщение 9048) уехал без кнопок; в 13:16:47Z штатный ремонт (`heal_buttonless`) дослал
их вторым сообщением, и в 13:28 владелец нажал. Ремонт отработал ровно как задуман.

А шаг 0-офис до сих пор печатал этот случай как ОТКРЫТЫЙ дефект с призывом «чинить путь
между сборкой клавиатуры и отправкой» — и печатал бы его ВЕЧНО: сообщение в канале кнопок
задним числом не отращивает, а `buttons_fixed_at` в той же записи журнала не читал никто.
Вечная находка глушит соседние настоящие (в том же отчёте их три, `unmatchable`).

Вычеркнуть починенное было бы ровно тем fail-OPEN, ради которого класс и заводили, —
поэтому не вычёркиваем, а НАЗЫВАЕМ: код причины ``healed_by_followup``, отдельный
счётчик, и число, которого не мерил никто, — **сколько владелец просидел с вопросом,
на который нечем ответить** (в том случае 1.92 ч).

stdlib, детерминированно, **LLM запрещён** (инвариант #3 — это monitoring-путь).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# ── формы, по которым узнаём предложение выбора ──────────────────────────────
#
# Каждая привязана к РЕАЛЬНОМУ тексту, который печатает `owner_decisions.build_message`
# (и его честные ветки), а не к воображению автора:
#
#   * `<b>Варианты:</b>` + строки `<b>1.</b> …`      — обычный вид с кнопками;
#   * «⚠️ Кнопки сейчас недоступны …»                 — маячок протух (ADR-069);
#   * «Ответь номером варианта в чат»                — тот же случай, хвост;
#   * «Ответь номерами в чат»                        — многовыборная карточка;
#   * «Варианты в карточке есть, но я не смог …»      — разбор не собрал кнопки;
#   * «не варианты одного решения, а N отдельных …»   — многовопросная карточка (#359).
#
# Последнюю форму ловим НАМЕРЕННО, хотя кнопок у неё не будет никогда: у сообщения есть
# что выбрать, и владелец не может ответить нажатием — это настоящая цена, а не
# оформление. Не узнать её значило бы погасить сторожа переписыванием текста, то есть
# сделать отчёт зеленее, ничего не починив.
#
# Сознательно НЕ ловим: «Вариантов в карточке не нашёл» (выбора не предлагали — кнопкам
# неоткуда взяться, это fail-CLOSED, а не дефект) и любые «1)» внутри отчётов: дневной
# дайджест перечисляет позиции цифрами и выбора не предлагает.
_CHOICE_PATTERNS = (
    re.compile(r"<b>\s*Вариант(?:ы)?\s*:?\s*</b>", re.IGNORECASE),
    re.compile(r"^\s*Вариант(?:ы)?\s*:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"Кнопки\s+сейчас\s+недоступны", re.IGNORECASE),
    re.compile(r"Ответь\s+номер(?:ом|ами)", re.IGNORECASE),
    re.compile(r"Варианты\s+в\s+карточке\s+есть", re.IGNORECASE),
    re.compile(r"не\s+варианты\s+одного\s+решения", re.IGNORECASE),
)


def offers_choice(text: str) -> bool:
    """Предлагает ли сообщение владельцу выбрать вариант. Никогда не бросает.

    Fail-CLOSED в сторону молчания: не узнали форму — ``False``. Ложная находка тут
    дороже пропуска (владельцу нельзя носить выдуманные дефекты), а настоящие формы
    печатает наш же билдер, и они закреплены тестами в обе стороны.
    """
    t = text or ""
    if not t:
        return False
    return any(p.search(t) for p in _CHOICE_PATTERNS)


def history_fields(text: str, buttons: Optional[bool]) -> Dict[str, Any]:
    """Поля отправки для журнала канала: ``offers_choice`` всегда, ``buttons`` — если измерено.

    ``buttons is None`` означает «дверь не сказала», и записи не будет вовсе: «не
    измерено» обязано отличаться от «кнопок не было». Ровно на этом различии стоит
    весь скан ниже.
    """
    out: Dict[str, Any] = {"offers_choice": bool(offers_choice(text))}
    if buttons is not None:
        out["buttons"] = bool(buttons)
    return out


# ── ЧЕМ послано и ПОЧЕМУ без кнопок ─────────────────────────────────────────
#
# Замер #350 на живом отчёте. Шаг 0-офис напечатал «⚠️ КНОПОК НЕТ у 2 доставленных
# сообщений с вариантами» — и всё. Чтобы понять, надо ли что-то чинить, сессии
# пришлось руками поднять `data/telegram_owner_decisions.json`, найти обе карточки по
# кускам текста и сверить времена: полчаса ровно на тот вопрос, который у соседней
# находки (H3, `buttons_reason`) печатается прямо в строке. Находка без причины —
# это приглашение к раскопкам, а не сигнал: одинаковые с виду строки лечатся
# по-разному, и «сообщение уехало ДРУГОЙ дверью» с «наш разбор не собрал вариантов»
# ведут к противоположной работе.
#
# Сопоставляем ТОЛЬКО по ``message_id`` — точному, измеренному ключу. Сведение по
# близости времени было бы гаданием: в очереди рядом стоят карточки одной минуты, и
# ложная атрибуция здесь дороже отсутствия (прецедент «нечёткое совпадение отдаёт APY
# чужого пула»). Не сошлось — так и говорим, с причиной.

#: Наша дверь, а вариантов в журнале нет: кнопкам неоткуда взяться — чинить РАЗБОР.
JOIN_OWN_NO_OPTIONS = "own_door_no_options"
#: Наша дверь и журнал говорит «кнопки были», а канал — «не было». Расхождение двух
#: наших же записей: чинить не разбор, а путь между сборкой клавиатуры и отправкой.
JOIN_OWN_CONTRADICTS = "own_door_says_buttons"
#: Наша дверь, кнопок в этом сообщении не было — и штатный ремонт их ДОСЛАЛ вторым
#: сообщением (`buttons_fixed_at` пишет только `mark_buttons_delivered`, и только после
#: удавшейся отправки). Владелец кнопки получил; чинить путь отправки по этой записи
#: больше нечего — а вот СКОЛЬКО он ждал без них, до сих пор не мерил никто.
JOIN_HEALED = "healed_by_followup"
#: Сообщение послано НЕ дверью решений владельца: у нашей message_id пишется всегда.
JOIN_OTHER_SENDER = "other_sender"
#: Сопоставить нечем — и это НЕ «другая дверь». Разница принципиальная: объявить
#: чужим отправителем сообщение, чью запись мы просто не пометили id, значит закрыть
#: СВОЙ дефект чужим именем.
JOIN_UNMATCHABLE = "unmatchable"
#: Журнала отправок не дали вовсе.
JOIN_NO_JOURNAL = "no_journal"

_JOIN_TEXT = {
    JOIN_OWN_NO_OPTIONS: "наша дверь, вариантов в журнале нет — чинить РАЗБОР карточки",
    JOIN_OWN_CONTRADICTS: "наша дверь, журнал говорит «кнопки были» — чинить путь "
                          "между сборкой клавиатуры и отправкой",
    JOIN_HEALED: "кнопки досланы вдогонку вторым сообщением — владелец их получил, "
                 "путь отправки по этой записи чинить нечего",
    JOIN_OTHER_SENDER: "послано НЕ дверью решений владельца — у нашей message_id "
                       "пишется всегда; искать отправителя, а не разбор",
    JOIN_UNMATCHABLE: "сопоставить нечем, отправитель НЕ ИЗМЕРЕН",
    JOIN_NO_JOURNAL: "журнал отправок не передан — отправитель НЕ ИЗМЕРЕН",
}


def _push_index(pushes) -> tuple[dict, int]:
    """(message_id → запись, сколько записей БЕЗ message_ids).

    Второе число — не украшение: пока в журнале есть записи без id, «не нашли по id»
    не имеет права читаться как «другая дверь».
    """
    by_id: Dict[int, Dict[str, Any]] = {}
    idless = 0
    for rec in pushes or []:
        if not isinstance(rec, dict):
            continue
        ids = rec.get("message_ids")
        clean = []
        for v in (ids if isinstance(ids, list) else []):
            try:
                clean.append(int(v))
            except (TypeError, ValueError):
                continue
        if not clean:
            idless += 1
            continue
        for mid in clean:
            by_id.setdefault(mid, rec)
    return by_id, idless


def attribute_send(entry: Dict[str, Any], by_id: dict, idless: int,
                   *, have_journal: bool) -> Dict[str, Any]:
    """Чем послано это сообщение и почему без кнопок. Никогда не бросает.

    Fail-CLOSED: любое сомнение → ``unmatchable`` с названной причиной, а не догадка.
    """
    if not have_journal:
        return {"code": JOIN_NO_JOURNAL, "text": _JOIN_TEXT[JOIN_NO_JOURNAL]}
    mid = entry.get("message_id")
    try:
        mid = int(mid)
    except (TypeError, ValueError):
        return {"code": JOIN_UNMATCHABLE,
                "text": f"{_JOIN_TEXT[JOIN_UNMATCHABLE]}: у записи канала нет message_id"}
    rec = by_id.get(mid)
    if rec is None:
        if idless:
            return {"code": JOIN_UNMATCHABLE,
                    "text": (f"{_JOIN_TEXT[JOIN_UNMATCHABLE]}: записи с id {mid} в журнале "
                             f"нет, но и сам журнал неполон — {idless} отправк(а/и) без "
                             f"message_ids, и «чужая дверь» от «наша без отметки id» "
                             f"неотличимы")}
        return {"code": JOIN_OTHER_SENDER, "text": _JOIN_TEXT[JOIN_OTHER_SENDER],
                "card_id": None}
    fixed_at = rec.get("buttons_fixed_at")
    if isinstance(fixed_at, str) and fixed_at.strip():
        # Ремонт СОСТОЯЛСЯ: `buttons_fixed_at` ставит только `mark_buttons_delivered`,
        # и только когда досылка уехала. Это единственная запись в обоих журналах,
        # которая отличает «владелец остался без кнопок» от «кнопки приехали вторым
        # сообщением», — и до этой правки её не читал никто.
        out: Dict[str, Any] = {"code": JOIN_HEALED, "text": _JOIN_TEXT[JOIN_HEALED],
                               "card_id": rec.get("card_id"),
                               "fixed_at": fixed_at.strip()}
        out["healed_by"] = _healing_message_id(rec, mid)
        out["waited_h"] = _waited_hours(entry.get("ts"), fixed_at)
        return out
    code = JOIN_OWN_CONTRADICTS if rec.get("buttons") else JOIN_OWN_NO_OPTIONS
    return {"code": code, "text": _JOIN_TEXT[code],
            "card_id": rec.get("card_id")}


def _healing_message_id(rec: Dict[str, Any], sent_mid: int) -> Optional[int]:
    """Каким сообщением приехали кнопки. ``None`` — досылка id не оставила.

    ``None`` здесь означает «не измерено», а не «не было»: отправитель мог вернуть
    ответ без ``message_id``, и ремонт всё равно состоялся (отметку без успеха не
    ставят). Врать номером мы не будем ни в ту, ни в другую сторону.
    """
    later = None
    for v in (rec.get("message_ids") if isinstance(rec.get("message_ids"), list) else []):
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if v != sent_mid:
            later = v
    return later


def _waited_hours(sent_iso, fixed_iso) -> Optional[float]:
    """Сколько владелец просидел с вопросом, на который нечем ответить. Не бросает.

    ``None`` — не измерено (отметку не разобрать). Отрицательную разницу тоже отдаём
    как «не измерено»: ремонт РАНЬШЕ отправки означает, что часы одной из сторон врут,
    а зажатый в ноль возраст уже стоил нам находки (#291) — второй раз не повторяем.
    """
    from datetime import datetime

    def _parse(v):
        if not isinstance(v, str) or not v.strip():
            return None
        try:
            return datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None

    a, b = _parse(sent_iso), _parse(fixed_iso)
    if a is None or b is None or a.tzinfo is None or b.tzinfo is None:
        return None
    delta = (b - a).total_seconds() / 3600.0
    return round(delta, 2) if delta >= 0 else None


# ── скан журнала ─────────────────────────────────────────────────────────────


def scan(entries: Iterable[Dict[str, Any]], *, limit: int = 20,
         pushes: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Доставленные сообщения, предложившие выбор без кнопок + честный «не измерено».

    Судим ТОЛЬКО про ``ok=True``: подавленное заслоном сообщение в чат не приезжало, и
    кнопки ему не нужны. Запись без поля ``buttons`` — не находка и не чистота, а
    отдельный счётчик: журнал до цикла #229 этого не знал ни про одну отправку.

    ``pushes`` — журнал отправок решений владельца. С ним у каждой находки появляется
    ПРИЧИНА (:func:`attribute_send`), без него — честное «отправитель НЕ ИЗМЕРЕН».
    Необязателен намеренно: скан не имеет права зависеть от второго файла (#350).
    """
    have_journal = pushes is not None
    by_id, idless = _push_index(pushes)
    confirmed: List[Dict[str, Any]] = []
    unmeasured = 0
    unscanned = 0
    total_choice = 0
    for rec in entries or []:
        if not isinstance(rec, dict):
            continue
        if not rec.get("ok"):
            continue
        if "offers_choice" not in rec:
            # Запись СТАРОГО образца: поле появилось в цикле #229, и про неё нельзя
            # сказать ни «предлагала выбор», ни «не предлагала». Считаем отдельно —
            # иначе «0 сообщений с вариантами» читалось бы как «всё в порядке», хотя
            # это ровно тот fail-OPEN, ради которого затевалось измерение.
            unscanned += 1
            continue
        if not rec.get("offers_choice"):
            continue
        total_choice += 1
        if "buttons" not in rec:
            unmeasured += 1
            continue
        if rec.get("buttons"):
            continue
        found = {
            "ts": rec.get("ts"),
            "preview": rec.get("preview"),
            "message_id": rec.get("message_id"),
            "solicited": bool(rec.get("solicited")),
        }
        found["cause"] = attribute_send(found, by_id, idless,
                                        have_journal=have_journal)
        confirmed.append(found)
    confirmed.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    # Починенное НЕ исчезает — оно получает свою полку. Разница принципиальная:
    # сообщение в канале кнопок задним числом не отращивает, поэтому в общей куче
    # починенный случай кричал бы ВЕЧНО и звал чинить путь, у которого ремонт уже
    # отработал, — а вечный крик глушит соседние настоящие находки. Но и вычеркнуть
    # его нельзя: это ровно тот fail-OPEN, из-за которого класс и заводили. Отсюда
    # два счётчика и две полки.
    healed = [r for r in confirmed
              if (r.get("cause") or {}).get("code") == JOIN_HEALED]
    open_ = [r for r in confirmed
             if (r.get("cause") or {}).get("code") != JOIN_HEALED]
    return {
        "with_choice": total_choice,
        "buttonless": open_[:limit],
        "buttonless_count": len(open_),
        "healed": healed[:limit],
        "healed_count": len(healed),
        "unmeasured_count": unmeasured,
        "unscanned_count": unscanned,
    }


def _healed_tail(report: Dict[str, Any]) -> str:
    """Хвост строки про досланные вдогонку кнопки. Пусто — если таких не было.

    Печатается ВСЕГДА, когда такие записи есть, в том числе рядом с «незакрытых нет»:
    ремонт сработал — это не то же самое, что «отправили правильно с первого раза», и
    единственное число, которым эти два состояния различимы для читателя, — сколько
    владелец просидел с вопросом, на который нечем ответить.
    """
    m = int(report.get("healed_count") or 0)
    if not m:
        return ""
    waits = [w for w in ((r.get("cause") or {}).get("waited_h")
                         for r in (report.get("healed") or []))
             if isinstance(w, (int, float))]
    if waits:
        worst = f"владелец ждал до {max(waits):.2f} ч"
    else:
        worst = "сколько ждал владелец — НЕ ИЗМЕРЕНО"
    return f" · кнопки досланы вдогонку: {m} ({worst})"


def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для читателя (шаг 0-офис). «Не измерено» называется вслух."""
    if not isinstance(report, dict):
        return "канал: кнопки НЕ ИЗМЕРЕНЫ (нет блока)"
    n = int(report.get("buttonless_count") or 0)
    u = int(report.get("unmeasured_count") or 0)
    healed_tail = _healed_tail(report)
    if n:
        first = (report.get("buttonless") or [{}])[0]
        # Причина стоит РЯДОМ с находкой, а не в json: без неё эта строка стоила
        # сессии #350 получаса раскопок по двум журналам (см. шапку модуля).
        cause = first.get("cause") if isinstance(first.get("cause"), dict) else None
        why = (cause or {}).get("text") or "причина НЕ ИЗМЕРЕНА (отчёт старого образца)"
        card = (cause or {}).get("card_id")
        card_tail = f", карточка {card}" if card else ""
        return (f"⚠️ КНОПОК НЕТ у {n} доставленн(ого/ых) сообщени(я/й) с вариантами; "
                f"свежайшее {first.get('ts')}: {str(first.get('preview') or '')[:80]} "
                f"[{why}{card_tail}]{healed_tail}")
    if u:
        return (f"сообщений с вариантами без измеренных кнопок: {u} "
                f"(старые записи журнала — «не измерено», не «чисто»){healed_tail}")
    choice = int(report.get("with_choice") or 0)
    old = int(report.get("unscanned_count") or 0)
    if healed_tail:
        # Незакрытых нет — но «все с кнопками» было бы неправдой: у этих кнопок не было
        # в момент отправки, и владелец ждал их измеренное время. Говорим ровно это.
        return (f"сообщения с вариантами: {choice}, незакрытых без кнопок нет"
                f"{healed_tail}")
    if not choice and old:
        # «Ноль сообщений с вариантами» из журнала, где ни одна запись не измерена, —
        # это НЕ чистота. Пока кольцевой буфер не сменится на записи нового образца,
        # честный ответ ровно один: не измерено (fail-CLOSED).
        return (f"кнопки в канале ещё НЕ ИЗМЕРЕНЫ: {old} доставленн(ых) запис(ей) "
                f"старого образца, поля `offers_choice` у них нет (появилось в #229)")
    tail = f" · записей старого образца: {old}" if old else ""
    return f"сообщения с вариантами: {choice}, все с кнопками{tail}"
