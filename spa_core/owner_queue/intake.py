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

import logging
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


def _notify(text: str) -> None:
    """Ответ владельцу через существующий бот (единая Telegram-власть, flood-guarded)."""
    try:
        from spa_core.telegram.bot import TelegramBot

        TelegramBot().send_message(text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001 — уведомление не должно ронять интейк
        log.warning("intake notify failed: %s", exc)


def _journal_history(dt: datetime, card, verdict: str, response: str) -> None:
    """Дописать результат проверки истории (Шаг 1a) в журнал недели (owner-directive)."""
    try:
        from spa_core.utils.atomic import atomic_save_text

        jdir = _REPO / "docs" / "journal"
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


def _declared_kind(card) -> str | None:
    """Маршрут, который владелец объявил сам (пульт), или None — тогда решает классификатор."""
    fields = getattr(card, "fields", None) or {}
    if str(fields.get("source") or "") not in _OWNER_LABELLED_SOURCES:
        return None
    return _DECLARED_ROUTE.get(str(fields.get("intake_kind") or ""))


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


def run_note_intake(now: datetime | None = None) -> dict:
    """Разобрать новые inbox-заметки/карточки.

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
    processed: list[str] = []
    unavailable: list[str] = []
    notices: list[str] = []
    urgent = False

    def _queue_notice(text: str) -> None:
        """Ответы владельцу копятся и отправляются в конце — по одному или сводкой.

        Штатно интейк разбирает 1–2 входящих, и владелец получает привычные отдельные
        ответы. Но прогон может застать очередь БОЛЬШОЙ — например, после починки
        аварии 11.08 в очередь честно вернулись 46 заданий, и прежний код отправил бы
        владельцу 46 сообщений подряд. Флуд — это не «много информации», это потеря
        сигнала: среди 46 «создал задачу» тревога о стоп-кране не будет прочитана.
        """
        notices.append(text)

    try:
        ingest_notes()  # свободные заметки Obsidian → inbox-карточки
    except Exception as exc:  # noqa: BLE001
        log.warning("intake ingest_notes failed: %s", exc)

    for card in list_cards(tracker_type="inbox", status="new"):
        if _already_accepted(card):
            continue                     # приём её уже принял: не переспрашивать и не слать повторно
        body = (card.body or card.title).strip()
        if "срочно" in body.lower():
            urgent = True

        # ── Шаг 1a — ПРОВЕРКА ИСТОРИИ (owner-directive 2026-07-16) ──────────────
        # Не дубль ли это? Уже сделано / в работе / осознанно отклонено → НЕ плодить
        # карточку, ответить человечески + журнал. PARTIAL → создать, но пометить.
        partial_note = ""
        try:
            from spa_core.owner_queue.history_check import history_check, is_duplicate

            hc = history_check(body)
            verdict = hc.get("verdict", "NEW")
            resp_h = hc.get("response", "")
            if is_duplicate(verdict):
                icon = {"DONE": "✅", "IN_PROGRESS": "🔧", "REJECTED": "🚫"}.get(verdict, "ℹ️")
                _queue_notice(f"{icon} {html.escape(resp_h or 'нашёл совпадение в памяти — дубль не создаю')}")
                _journal_history(dt, card, verdict, resp_h)
                set_status(card.path, "done", closed_by="owner_queue.intake/history_check",
                           evidence=f"duplicate of existing work (verdict {verdict}): {(resp_h or '')[:160]}")
                processed.append(card.id)
                continue
            if verdict == "PARTIAL" and resp_h:
                partial_note = resp_h
                _journal_history(dt, card, "PARTIAL", resp_h)
        except Exception as exc:  # noqa: BLE001 — history-check не должен ронять приём
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
                kind, resp = classify_and_answer(body)
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
                ideas = _REPO / "docs" / "ideas"
                ideas.mkdir(parents=True, exist_ok=True)
                fpath = ideas / f"{dt.strftime('%Y-%m-%d')}-{_slug(card.title)}.md"
                atomic_save_text(f"# {card.title}\n\n_Из Inbox {dt.strftime('%Y-%m-%d')} (source: {card.fields.get('source','')})._\n{partial_body}\n{body}\n", str(fpath))
                # Носитель гасится, НАЗЫВАЯ предмет, куда уехало содержимое (ADR-375).
                # Это и есть его приёмка: заметка существует — проверяемо.
                # Корень НАЗВАН: заметка лежит в `_REPO/docs/ideas`, и условие
                # освобождения обязано мерить от того же корня (ADR-501).
                set_status(card.path, "done", carried_to=fpath, repo_root=_REPO)
                _queue_notice(f"💡 Записал как идею: <b>{html.escape(card.title)}</b>{partial_tg}")
            elif kind == "unclear":
                q = resp or "Уточни: это вопрос или задача?"
                # Дословный текст пишется маркером, ОБЪЯВЛЕННЫМ в history_check: по нему
                # же следующий заход узнаёт точный повтор (цикл #446). Литерал здесь
                # означал бы формат в двух местах — он бы разошёлся молча.
                _owner_card = create_card(
                    "owner-decision",
                    f"Уточнение по заметке: {card.title}",
                    body=(f"## Что случилось и почему это важно\nПришло сообщение, непонятно — вопрос это или задача.\n\n"
                          f"{SOURCE_TEXT_OPEN}{body}{SOURCE_TEXT_CLOSE}{partial_body}\n\n## Что от тебя нужно\n{q}\n\n"
                          f"## Как понять, что готово\nТы уточнил.\n\n## Что будет после\nОбработаю по твоему ответу."),
                    status="needs-owner", source="intake",
                )
                # Тот же порядок: носитель гасится, назвав карточку владельцу.
                # `create_card` возвращает путь либо объект с `path` — берём оба вида,
                # потому что сверять приходится СУЩЕСТВОВАНИЕМ, а не типом.
                _target = getattr(_owner_card, "path", _owner_card)
                set_status(card.path, "done", carried_to=_target, repo_root=_REPO)
                _queue_notice(f"❓ Есть вопрос — смотри карточку: {html.escape(q)}{partial_tg}")
            else:  # task
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
                _queue_notice(f"📥 Создал задачу: <b>{html.escape(card.title)}</b>{partial_tg}")
            processed.append(card.id)
        except Exception as exc:  # noqa: BLE001 — карточка остаётся new → обычный цикл
            log.warning("intake route failed for %s: %s — leaving as new", card.id, exc)

    # Отправка ответов: до _MAX_INDIVIDUAL_NOTICES — как раньше, по одному; больше —
    # ОДНОЙ сводкой (см. _queue_notice: флуд глушит сигнал, а не добавляет его).
    if len(notices) <= _MAX_INDIVIDUAL_NOTICES:
        for text in notices:
            _notify(text)
    elif notices:
        head = "\n".join(f"• {_strip_tags(t)[:90]}" for t in notices[:_SUMMARY_HEAD])
        _notify(f"📥 Разобрал входящих за один прогон: <b>{len(notices)}</b>. "
                f"Шлю сводкой, чтобы не завалить чат:\n{head}\n"
                f"…и ещё {len(notices) - _SUMMARY_HEAD}. Все — в очереди карточек.")

    # ОДНО сообщение на прогон, а не по штуке на карточку: 11.08 недоступность классификатора
    # была молчаливой — владелец видел только её последствия (44 вопроса ниоткуда).
    if unavailable:
        _notify(f"⚠️ Классификатор недоступен — {len(unavailable)} входящих оставил как есть "
                f"(статус <b>new</b>), разберу обычным циклом. Вопросов из-за этого не создаю.")

    return {"processed": processed, "unavailable": unavailable,
            "notices": notices, "urgent": urgent}
