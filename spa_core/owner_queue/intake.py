"""Событийный ЛЁГКИЙ интейк Inbox (owner-approved 2026-07-15).

Триггерится по событию (WatchPaths на inbox/ → agent_inbox_intake.sh). Делает ТОЛЬКО:
  1. `ingest_notes()` — свободные заметки Obsidian из inbox/ → inbox-карточки;
  2. для каждой НОВОЙ inbox-карточки — классификация через `ask_router` (Claude): задача/идея/непонятно;
     - **задача** → вписать критерий + статус `in-progress` (детальную работу делает ПОЛНЫЙ цикл);
     - **идея** → сохранить в `docs/ideas/<дата>-<slug>.md`, карточку → `done` (идея ≠ инструкция);
     - **непонятно** → карточка `own-*` `needs-owner` с уточняющим вопросом, исходную → `done`;
  3. короткий ответ владельцу в Telegram.

ЖЁСТКО ОГРАНИЧЕН: детерминированный Python — умеет ТОЛЬКО карточки + уведомления. НИКАКОГО кода,
git/push, деплоя, исполнения задач, правок тестов (это физически недоступно — модуль их не вызывает).
Claude запускается лишь для классификации (ask_router). Fail-safe: любая ошибка по карточке —
карточка остаётся `new` и её подхватит обычный цикл, ничего не теряется.

**Этот fail-safe два месяца был НЕДОСТИЖИМ (починено 12.08.2026).** Он ловил исключение из
`classify_and_answer`, а тот глотал падение `claude` и возвращал обычный на вид вердикт
`("unclear", …)` — исключения не было ⇒ `except` ниже не срабатывал НИ РАЗУ. 11.08, пока
классификатор лежал, интейк выпустил **44 карточки-вопроса владельцу** (все 44 из 44 с
дословным fallback-текстом, настоящих вопросов ноль) и закрыл 44 исходных задания как `done` —
28 из них на `origin` до сих пор `new`, то есть в проде реальный бэклог выглядел сделанным.
Теперь недоступность приходит отдельным видом `ask_router.UNAVAILABLE` и обрабатывается ЯВНО:
карточка остаётся `new`, вопрос владельцу НЕ создаётся, исходник НЕ закрывается.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]

#: Сколько ответов владельцу шлём поштучно, прежде чем перейти на сводку.
#: Штатный прогон — 1–2 входящих; всё, что заметно больше, это разбор накопившейся
#: очереди, и владельцу нужен ОДИН итог, а не лента.
_MAX_INDIVIDUAL_NOTICES = 3
#: Сколько строк показать в сводке (остальные — счётчиком).
_SUMMARY_HEAD = 5


def _strip_tags(text: str) -> str:
    """HTML-разметку из отдельного ответа в сводке не показываем."""
    import re as _re

    return _re.sub(r"<[^>]+>", "", text).strip()


def _notify(text: str) -> bool:
    """Ответ владельцу через существующий бот (единая Telegram-власть, flood-guarded).

    Возвращает, ушло ли сообщение: ``False`` (сбой сети, заслон потока, нет chat_id) оставляет
    уведомление в исходящих (:func:`_outbox_load`) — его повторит следующий прогон."""
    try:
        from spa_core.telegram.bot import TelegramBot

        return bool(TelegramBot().send_message(text, parse_mode="HTML"))
    except Exception as exc:  # noqa: BLE001 — уведомление не должно ронять интейк
        log.warning("intake notify failed: %s", exc)
        return False


# ── Исходящие уведомления — ДОЛГОВЕЧНО, до отметки приёма (16.10) ───────────────────────────────────
# Отметка приёма (``intake_seen`` / закрытие носителя) значит только «приём закончен», никогда «задача
# сделана». Раньше ответы владельцу копились в памяти и уходили в конце прогона, а отметка ставилась
# раньше: падение между ними теряло уведомление НАВСЕГДА (следующий прогон карточку пропускает).
# Теперь порядок по карточке: связанная работа (идемпотентна) → запись уведомления в этот файл
# (atomic, fsync) → отметка. В конце прогона файл отправляется и чистится по мере доставки; остаток
# (упали / Telegram не принял) уходит следующим прогоном. Доставка — НЕ МЕНЕЕ ОДНОГО раза: падение
# между отправкой и вычёркиванием повторит сообщение; повторный разбор той же карточки дубля не даёт
# (ключ — имя карточки, запись заменяется, а не добавляется).
_OUTBOX_NAME = "intake_outbox.json"


def _outbox_path() -> Path:
    return _REPO / "data" / _OUTBOX_NAME


def _outbox_load(path: Path | None = None) -> list[dict]:
    p = Path(path) if path is not None else _outbox_path()
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        items = doc.get("pending") if isinstance(doc, dict) else None
        if not isinstance(items, list):
            raise ValueError("no 'pending' list")
        return [i for i in items if isinstance(i, dict) and isinstance(i.get("key"), str)
                and isinstance(i.get("text"), str)]
    except (OSError, ValueError) as exc:
        # Нечитаемый файл НЕ выдаётся за пустой и не затирается: откладываем в сторону с именем.
        aside = p.with_name(f"{p.name}.unreadable-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        try:
            os.replace(p, aside)
        except OSError:
            pass
        log.warning("intake outbox unreadable (%s) — moved aside to %s", exc, aside.name)
        return []


def _outbox_save(items: list[dict], path: Path | None = None) -> None:
    from spa_core.utils.atomic import atomic_save_text
    target = Path(path) if path is not None else _outbox_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_save_text(json.dumps({"schema": 1, "pending": items}, ensure_ascii=False, indent=1),
                     str(target))


def _outbox_put(key: str, text: str, at: datetime, path: Path | None = None) -> None:
    """Долговечно передать уведомление по ключу ``key``; повторная передача заменяет запись.

    Ключ приёма — имя карточки; ключи сквозного пути пульта (``cockpit_loop``) — «карточка#событие»,
    поэтому «принято» и «сделано и проверено» по одной карточке друг друга не вытесняют."""
    items = [i for i in _outbox_load(path) if i.get("key") != key]
    items.append({"key": key, "text": text, "queued_at": at.strftime("%Y-%m-%dT%H:%M:%SZ")})
    _outbox_save(items, path)


def _outbox_drop(keys, path: Path | None = None) -> None:
    keys = set(keys)
    items = _outbox_load(path)
    left = [i for i in items if i.get("key") not in keys]
    if len(left) != len(items):
        _outbox_save(left, path)


def flush_outbox(*, notify=None, path: Path | None = None) -> list[str]:
    """Отправить ВСЁ, что лежит в исходящих; доставленное вычёркивается сразу. Возврат — тексты,
    которые были в очереди на отправку (не «доставленные»: вернувший ``False`` отправитель оставляет
    запись до следующего прогона).

    Семантика доставки — НЕ МЕНЕЕ ОДНОГО РАЗА, не «ровно один раз»: падение между отправкой и
    вычёркиванием, или отправка, о которой Telegram не успел ответить, повторит сообщение следующим
    прогоном. Дубль по одной карточке и одному событию невозможен только В ИСХОДЯЩИХ (ключ заменяет
    запись), а не в чате владельца.

    До ``_MAX_INDIVIDUAL_NOTICES`` — по одному; больше — ОДНОЙ сводкой (флуд глушит сигнал)."""
    send = notify if notify is not None else _notify
    pending = _outbox_load(path)
    notices = [i["text"] for i in pending]
    if len(pending) <= _MAX_INDIVIDUAL_NOTICES:
        for item in pending:
            if send(item["text"]) is not False:
                _outbox_drop([item["key"]], path)
    else:
        head = "\n".join(f"• {_strip_tags(t)[:90]}" for t in notices[:_SUMMARY_HEAD])
        ok = send(f"📥 Разобрал входящих за один прогон: <b>{len(notices)}</b>. "
                  f"Шлю сводкой, чтобы не завалить чат:\n{head}\n"
                  f"…и ещё {len(notices) - _SUMMARY_HEAD}. Все — в очереди карточек.")
        if ok is not False:
            _outbox_drop([i["key"] for i in pending], path)
    return notices


def _journal_history(dt: datetime, card, verdict: str, response: str, root: Path | None = None) -> None:
    """Дописать результат проверки истории (Шаг 1a) в журнал недели (owner-directive)."""
    try:
        from spa_core.utils.atomic import atomic_save_text

        jdir = (root if root is not None else _REPO) / "docs" / "journal"
        jdir.mkdir(parents=True, exist_ok=True)
        iso = dt.isocalendar()
        jf = jdir / f"{iso[0]}-W{iso[1]:02d}.md"
        prev = jf.read_text(encoding="utf-8") if jf.exists() else f"# Journal · {iso[0]}-W{iso[1]:02d}\n"
        entry = (f"\n- **История-чек [{verdict}]** для «{card.title}» "
                 f"(source: {card.fields.get('source','')}): {response[:300]}")
        atomic_save_text(prev.rstrip() + entry + "\n", str(jf))
    except Exception as exc:  # noqa: BLE001
        log.warning("_journal_history failed: %s", exc)


#: Источники, чья пометка ``intake_kind`` — слово самого владельца (ADR-760, пульт).
_OWNER_LABELLED_SOURCES = ("cockpit", "cockpit-voice")
#: Пометка владельца → маршрут приёма. «note» (замечание) маршрута не задаёт.
_DECLARED_ROUTE = {"idea": "idea", "task": "task"}


#: Провенанс записи пульта: пометка ``intake_kind`` — слово ВЛАДЕЛЬЦА только при ``author: owner``.
#: Запись агента или с неустановленным автором (и старая карточка без поля) несёт пометку как
#: ПОДСКАЗКУ: маршрут решает тот же классификатор, что и для всех прочих входящих.
_AUTHOR_OWNER = "owner"
_KIND_HINT_RU = {"idea": "идея", "task": "задача", "note": "замечание"}


def _cockpit_kind(card) -> str | None:
    fields = getattr(card, "fields", None) or {}
    if str(fields.get("source") or "") not in _OWNER_LABELLED_SOURCES:
        return None
    return str(fields.get("intake_kind") or "") or None


def _declared_kind(card) -> str | None:
    """Маршрут, который ВЛАДЕЛЕЦ объявил сам (пульт, ``author: owner``), или None — решает классификатор."""
    fields = getattr(card, "fields", None) or {}
    if str(fields.get("author") or "").strip() != _AUTHOR_OWNER:
        return None
    return _DECLARED_ROUTE.get(_cockpit_kind(card) or "")


def _kind_hint(card) -> str:
    """Пометка записи пульта, не подтверждённая как слово владельца, — подсказка классификатору."""
    if _declared_kind(card) is not None:
        return ""
    kind = _cockpit_kind(card)
    ru = _KIND_HINT_RU.get(kind or "")
    return (f"\n\n(Пометка записи — «{ru}»; автор не подтверждён как владелец, это подсказка, "
            f"а не решение.)") if ru else ""


#: Собственная отметка приёма в теле задачи (её вписывает ветка «task» ниже) и поле frontmatter,
#: которым приём отмечает уже принятую задачу. Замер 16.10 (ARB): задача остаётся `new` (ADR-375),
#: поэтому КАЖДЫЙ запуск приёма брал её заново — два прогона после перезагрузки 15.10 (23:37 и
#: 01:40 CEST) переработали одни и те же 28 карточек, отправили по 44–45 уведомлений и повторно
#: дописали владельцу вопрос «то же самое или новое?». Принятая задача приёмом больше не трогается.
_INTAKE_CRITERION_STAMP = "## Как понять, что готово\nЗадача выполнена и проверена (детали — обычный цикл).\n"
_INTAKE_SEEN_FIELD = "intake_seen"


def _already_accepted(card) -> bool:
    fields = getattr(card, "fields", None) or {}
    if str(fields.get(_INTAKE_SEEN_FIELD) or "").strip():
        return True
    try:
        text = card.path.read_text(encoding="utf-8")
    except (OSError, AttributeError):
        return False
    return _INTAKE_CRITERION_STAMP in text


def _stamp_seen(path, at: datetime) -> None:
    """Вписать ``intake_seen: <UTC>`` во frontmatter (тело и прочие поля не меняются)."""
    from spa_core.utils.atomic import atomic_save_text
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    marks = [i for i, ln in enumerate(lines) if ln.strip() == "---"][:2]
    if len(marks) < 2 or marks[0] != 0:
        return
    stamp = f"{_INTAKE_SEEN_FIELD}: {at.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
    for i in range(1, marks[1]):
        if lines[i].startswith(_INTAKE_SEEN_FIELD + ":"):
            lines[i] = stamp
            break
    else:
        lines.insert(marks[1], stamp)
    atomic_save_text("".join(lines), str(path))


def _existing_idea_note(ideas: Path, card) -> Path | None:
    """Заметка-идея, уже записанная по ЭТОЙ карточке (её имя стоит в строке происхождения)."""
    needle = f"card: {card.path.name})"
    try:
        for p in sorted(ideas.glob("*.md")):
            try:
                if needle in p.read_text(encoding="utf-8", errors="ignore")[:2000]:
                    return p
            except OSError:
                continue
    except OSError:
        return None
    return None


#: Поле карточки-вопроса владельцу: из какой inbox-заметки он родился (идемпотентность повтора).
_SOURCE_CARD_FIELD = "intake_source_card"


def _existing_owner_question(card, tracker_dir=None) -> Path | None:
    """Карточка-вопрос владельцу, уже заведённая приёмом по ЭТОЙ заметке (любой статус)."""
    from spa_core.owner_queue import queue as _q
    try:
        for p in sorted(Path(tracker_dir if tracker_dir is not None else _q.TRACKER_DIR).glob("owner-decision-*.md")):
            try:
                if str(_q.load_card(p).fields.get(_SOURCE_CARD_FIELD) or "") == card.path.name:
                    return p
            except Exception:  # noqa: BLE001 — битую карточку пропускаем
                continue
    except OSError:
        return None
    return None


def _forget(keys: list[str], path: Path | None = None) -> None:
    """Снять уведомления, переданные в этом прогоне по карточке, приём которой не закончился."""
    if not keys:
        return
    try:
        _outbox_drop(keys, path)
    except Exception as exc:  # noqa: BLE001 — лишнее уведомление лучше потерянной карточки
        log.warning("intake outbox drop failed for %s: %s", keys, exc)
    keys.clear()


def run_note_intake(now: datetime | None = None, *, tracker_dir=None, repo_root=None,
                    notify=None, history=None, ingest: bool = True, classify=None) -> dict:
    """Разобрать новые inbox-заметки/карточки.

    Объявленные ШВЫ (по умолчанию — боевое поведение, байт в байт): ``tracker_dir`` — каталог
    карточек; ``repo_root`` — корень, от которого лежат ``docs/ideas``, журнал и исходящие
    (``data/intake_outbox.json``); ``notify`` — отправитель (Telegram); ``history`` — проверка
    истории (``history_check``, за ней локальный ``claude``); ``classify`` — классификатор маршрута
    (по умолчанию ``ask_router.classify_and_answer``); ``ingest=False`` — не сканировать
    заметки Obsidian. Нужны одноразовой сцене пробы ``cockpit_voice_loop_closed``: живой трекер,
    живые исходящие и Telegram она не трогает.

    Returns ``{'processed': [...], 'unavailable': [...], 'notices': [...], 'urgent': bool}``:
    ``unavailable`` — карточки, по которым классификатор НЕ ОТВЕТИЛ (оставлены `new`,
    вердикта по ним не выносилось); ``notices`` — что ушло владельцу.
    """
    import html

    from spa_core.owner_queue.queue import (
        _slug,  # каноническая версия с Cyrillic→Latin транслитом (DRY — не дублировать)
        create_card,
        ingest_notes,
        list_cards,
        set_status,
    )
    from spa_core.owner_queue.history_check import SOURCE_TEXT_CLOSE, SOURCE_TEXT_OPEN
    from spa_core.telegram import ask_router
    from spa_core.telegram.ask_router import classify_and_answer
    from spa_core.utils.atomic import atomic_save_text

    dt = now or datetime.now(timezone.utc)
    root = Path(repo_root) if repo_root is not None else _REPO
    obox = (root / "data" / _OUTBOX_NAME) if repo_root is not None else None
    processed: list[str] = []
    unavailable: list[str] = []
    notices: list[str] = []
    urgent = False

    def _queue_notice(card, text: str) -> None:
        """Ответы владельцу копятся (в долговечных исходящих, до отметки приёма карточки)
        и отправляются в конце — по одному или сводкой.

        Штатно интейк разбирает 1–2 входящих, и владелец получает привычные отдельные
        ответы. Но прогон может застать очередь БОЛЬШОЙ — например, после починки
        аварии 11.08 в очередь честно вернулись 46 заданий, и прежний код отправил бы
        владельцу 46 сообщений подряд. Флуд — это не «много информации», это потеря
        сигнала: среди 46 «создал задачу» тревога о стоп-кране не будет прочитана.
        """
        _outbox_put(card.path.name, text, dt, obox)
        handed_off.append(card.path.name)

    if ingest:
        try:
            ingest_notes()  # свободные заметки Obsidian → inbox-карточки
        except Exception as exc:  # noqa: BLE001
            log.warning("intake ingest_notes failed: %s", exc)

    for card in list_cards(tracker_type="inbox", status="new", tracker_dir=tracker_dir):
        if _already_accepted(card):
            continue                     # приём её уже принял: не переспрашивать и не слать повторно
        body = (card.body or card.title).strip()
        handed_off: list[str] = []
        if "срочно" in body.lower():
            urgent = True

        # ── Шаг 1a — ПРОВЕРКА ИСТОРИИ (owner-directive 2026-07-16) ──────────────
        # Не дубль ли это? Уже сделано / в работе / осознанно отклонено → НЕ плодить
        # карточку, ответить человечески + журнал. PARTIAL → создать, но пометить.
        partial_note = ""
        try:
            from spa_core.owner_queue.history_check import history_check, is_duplicate

            hc = (history or history_check)(body)
            verdict = hc.get("verdict", "NEW")
            resp_h = hc.get("response", "")
            if is_duplicate(verdict):
                icon = {"DONE": "✅", "IN_PROGRESS": "🔧", "REJECTED": "🚫"}.get(verdict, "ℹ️")
                _journal_history(dt, card, verdict, resp_h, root)
                _queue_notice(card, f"{icon} {html.escape(resp_h or 'нашёл совпадение в памяти — дубль не создаю')}")
                set_status(card.path, "done", closed_by="owner_queue.intake/history_check",
                           evidence=f"duplicate of existing work (verdict {verdict}): {(resp_h or '')[:160]}")
                processed.append(card.id)
                continue
            if verdict == "PARTIAL" and resp_h:
                partial_note = resp_h
                _journal_history(dt, card, "PARTIAL", resp_h, root)
        except Exception as exc:  # noqa: BLE001 — history-check не должен ронять приём
            _forget(handed_off, obox)
            log.warning("intake history_check failed for %s: %s — продолжаю как NEW", card.id, exc)

        # PARTIAL (§1a): карточку СОЗДАТЬ, но пометить «похоже на …, проверь» — и в
        # ТЕЛЕ карточки (её увидит полный цикл), и в Telegram-ответе владельцу.
        # ARB 16.10, решение №4: вопрос «это то же самое или новое?» владельцу НЕ задаётся —
        # сверку по истории, живому трекеру и origin делает агент, который возьмёт карточку.
        # Подсказка остаётся сведением (в теле карточки и в ответе), а не вопросом.
        partial_body = (f"\n\n> ⚠️ Проверка истории: похоже на уже существующее — {partial_note}\n"
                        f"> Сверку «то же самое или новое» делает агент, который возьмёт карточку "
                        f"(история, трекер, origin); владельцу этот вопрос не задаётся.\n"
                        if partial_note else "")
        partial_tg = (f"\nℹ️ Похоже на уже существующее — агент сверит сам, отвечать не нужно: "
                      f"{html.escape(partial_note)}" if partial_note else "")

        # ADR-760: запись из пульта уже несёт пометку владельца (идея/задача) — её не
        # переспрашиваем у классификатора: владелец сам сказал, что это. «Замечание» и всё
        # прочее классифицируется как раньше. Классификатор при этом не вызывается вовсе.
        declared = _declared_kind(card)
        if declared is not None:
            kind, resp = declared, ""
        else:
            try:
                kind, resp = (classify or classify_and_answer)(body + _kind_hint(card))
            except Exception as exc:  # noqa: BLE001 — карточка ждёт обычного цикла
                log.warning("intake classify failed for %s: %s — leaving as new", card.id, exc)
                continue

        # Классификатор НЕ ВЫНОСИЛ вердикта (упал / ненулевой выход / пустота). Это НЕ
        # «непонятно»: спросить было не у кого. Единственное честное действие — не решать:
        # карточка остаётся `new`, вопрос владельцу не создаётся, исходник не закрывается.
        # Ровно этого не хватило 11.08 (44 фантома + 44 закрытых задания, см. docstring).
        if kind == ask_router.UNAVAILABLE:
            log.warning("intake: классификатор недоступен для %s — оставляю new", card.id)
            unavailable.append(card.id)
            continue

        try:
            if kind == "idea":
                ideas = root / "docs" / "ideas"
                ideas.mkdir(parents=True, exist_ok=True)
                # Повторный разбор после падения не пишет вторую заметку: та же карточка уже
                # записана (её имя стоит в заметке) — берём ту, что есть.
                fpath = _existing_idea_note(ideas, card)
                if fpath is None:
                    stem = f"{dt.strftime('%Y-%m-%d')}-{_slug(card.title)}"
                    fpath, n = ideas / f"{stem}.md", 2
                    while fpath.exists():        # чужая заметка с тем же именем не затирается
                        fpath, n = ideas / f"{stem}-{n}.md", n + 1
                    atomic_save_text(f"# {card.title}\n\n_Из Inbox {dt.strftime('%Y-%m-%d')} (source: {card.fields.get('source','')}; card: {card.path.name})._\n{partial_body}\n{body}\n", str(fpath))
                _queue_notice(card, f"💡 Записал как идею: <b>{html.escape(card.title)}</b>{partial_tg}")
                # Носитель гасится, НАЗЫВАЯ предмет, куда уехало содержимое (ADR-375).
                # Это и есть его приёмка: заметка существует — проверяемо.
                # Корень НАЗВАН: заметка лежит в `_REPO/docs/ideas`, и условие
                # освобождения обязано мерить от того же корня (ADR-501).
                set_status(card.path, "done", carried_to=fpath, repo_root=root)
            elif kind == "unclear":
                q = resp or "Уточни: это вопрос или задача?"
                # Дословный текст пишется маркером, ОБЪЯВЛЕННЫМ в history_check: по нему
                # же следующий заход узнаёт точный повтор (цикл #446). Литерал здесь
                # означал бы формат в двух местах — он бы разошёлся молча.
                # Повтор после падения не заводит второй вопрос: вопрос по ЭТОЙ заметке уже есть
                # (поле intake_source_card) — берём его, даже если классификатор сформулировал
                # уточнение иначе (открытый близнец create_card сравнивает тело дословно).
                _owner_card = _existing_owner_question(card, tracker_dir) or create_card(
                    "owner-decision",
                    f"Уточнение по заметке: {card.title}",
                    body=(f"## Что случилось и почему это важно\nПришло сообщение, непонятно — вопрос это или задача.\n\n"
                          f"{SOURCE_TEXT_OPEN}{body}{SOURCE_TEXT_CLOSE}{partial_body}\n\n## Что от тебя нужно\n{q}\n\n"
                          f"## Как понять, что готово\nТы уточнил.\n\n## Что будет после\nОбработаю по твоему ответу."),
                    status="needs-owner", source="intake",
                    extra_fields={_SOURCE_CARD_FIELD: card.path.name},
                    **({"tracker_dir": tracker_dir} if tracker_dir is not None else {}),
                )
                # Тот же порядок: носитель гасится, назвав карточку владельцу.
                # `create_card` возвращает путь либо объект с `path` — берём оба вида,
                # потому что сверять приходится СУЩЕСТВОВАНИЕМ, а не типом.
                _target = getattr(_owner_card, "path", _owner_card)
                # Уведомление передаётся до закрытия носителя.
                _queue_notice(card, f"❓ Есть вопрос — смотри карточку: {html.escape(q)}{partial_tg}")
                set_status(card.path, "done", carried_to=_target, repo_root=root)
            else:  # task
                # Уведомление передаётся ДО правки тела: вписанный критерий сам по себе
                # читается как «уже принята» (_already_accepted, старые карточки), и падение
                # после него без переданного уведомления теряло бы ответ владельцу.
                _queue_notice(card, f"📥 Создал задачу: <b>{html.escape(card.title)}</b>{partial_tg}")
                # вписать критерий (полную декомпозицию делает обычный цикл), статус in-progress
                append = ""
                if "Как понять, что готово" not in body:
                    append += "\n\n" + _INTAKE_CRITERION_STAMP
                current = card.path.read_text(encoding="utf-8")
                if "Проверка истории:" not in current:
                    append += partial_body  # PARTIAL-пометку увидит полный цикл в теле карточки
                if append:
                    atomic_save_text(current.rstrip() + append, str(card.path))
                _stamp_seen(card.path, dt)
                # ИЗМЕНЕНО 14.09 (ADR-375): приём БОЛЬШЕ НЕ БЕРЁТ задачу в работу.
                #
                # Здесь стояло `set_status(card.path, "in-progress")`. С правилом машинной
                # приёмки (`.claude/rules/acceptance.md`) это стало прямым нарушением: из
                # приёма карточка уходит только с объявленной пробой, а приём пробы знать
                # не может — задача пришла текстом от владельца минуту назад. Попытка
                # отказывала, карточка молча оставалась `new`, и СЕМЬ тестов краснели.
                #
                # Правильный ответ не «освободить приём», а признать, что он и не берёт
                # работу: он её ПРИНИМАЕТ. Карточка остаётся `new` — «ещё ничья», — и
                # мерку объявляет тот, кто возьмёт её в работу. Ровно этого правило и хочет.
            processed.append(card.id)
        except Exception as exc:  # noqa: BLE001 — карточка остаётся new → обычный цикл
            _forget(handed_off, obox)   # приём не закончен — уведомлять не о чем, следующий прогон повторит
            log.warning("intake route failed for %s: %s — leaving as new", card.id, exc)

    # Сквозной путь пульта (STUDIO-OS-NEXT-01): уведомление «сделано и проверено», потерянное
    # падением между закрытием карточки пробой и передачей в исходящие, дочищается здесь —
    # приём запускается на каждое событие, поэтому окно потери ограничено следующим событием.
    try:
        from spa_core.owner_queue import cockpit_loop as _cl
        _cl.sweep_notices(tracker_dir=tracker_dir, outbox_path=obox, now=dt)
    except Exception as exc:  # noqa: BLE001 — дочистка не должна ронять приём
        log.warning("intake cockpit sweep failed: %s", exc)

    # Отправка ответов: до _MAX_INDIVIDUAL_NOTICES — как раньше, по одному; больше —
    # ОДНОЙ сводкой (см. _queue_notice: флуд глушит сигнал, а не добавляет его). Отправляется ВСЁ,
    # что лежит в исходящих, — и остаток прошлого прогона; доставленное вычёркивается сразу.
    # ``_notify`` вернул ``False`` ⇒ запись остаётся до следующего прогона (не менее одного раза).
    notices = flush_outbox(notify=notify, path=obox)

    # ОДНО сообщение на прогон, а не по штуке на карточку: 11.08 недоступность классификатора
    # была молчаливой — владелец видел только её последствия (44 вопроса ниоткуда).
    if unavailable:
        (notify if notify is not None else _notify)(f"⚠️ Классификатор недоступен — {len(unavailable)} входящих оставил как есть "
                f"(статус <b>new</b>), разберу обычным циклом. Вопросов из-за этого не создаю.")

    return {"processed": processed, "unavailable": unavailable,
            "notices": notices, "urgent": urgent}
