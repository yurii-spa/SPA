"""Telegram notification for new ``needs-owner`` cards (ENV_SETUP_BRIEF_v3 §3.3).

Routes through the EXISTING bot (``spa_core.telegram.bot.TelegramBot`` — the
single-authority sender, flood-guarded, Keychain creds ``TELEGRAM_BOT_TOKEN_SPA`` /
``TELEGRAM_CHAT_ID_SPA``). We deliberately do NOT import the raw transport here
(single-authority guard). ``send_message`` is a stateless POST — it takes no
poller lock, so it never conflicts with the running bot. HTML parse-mode is used
so underscores / file paths don't 400 the way Markdown does.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from spa_core.owner_queue.queue import Card, first_instruction_line, load_card

log = logging.getLogger(__name__)


def build_message(card: Card) -> str:
    """Запасной вид уведомления: заголовок, первая строка задания, путь к карточке.

    Используется, когда варианты ответа из карточки разобрать не удалось (fail-CLOSED —
    выдумывать выбор владельцу нельзя). Основной, человеческий вид строит
    ``spa_core.telegram.owner_decisions``.
    """
    try:
        rel = card.path.resolve().relative_to(Path(__file__).resolve().parents[2])
        rel_str = str(rel)
    except Exception:
        rel_str = card.path.name
    title = html.escape(card.title or card.id)
    instr = html.escape(first_instruction_line(card))
    path = html.escape(rel_str)
    return (
        f"🟥 <b>Owner Decision — нужно решение</b>\n"
        f"<b>{title}</b>\n"
        f"➡️ {instr}\n"
        f"📄 <code>{path}</code>\n"
        f"Ответь: переведи карточку Needs Owner → Owner Done (в Nimbalyst или правкой status:)."
    )


def notify_needs_owner(path: str | Path, *, dry_run: bool = False,
                       owner_requested: bool = False) -> str:
    """Отправить владельцу карточку решения — с вариантами ответа и рекомендацией.

    Задание владельца 2026-08-08: решение должно приходить простым языком, с вариантами
    и пометкой «рекомендую», чтобы отвечать можно было прямо с телефона.

    Fail-CLOSED в две стороны, и обе намеренные:

    * варианты не разобрались ⇒ уходит СТАРЫЙ вид уведомления (кнопок нет, но владелец
      узнаёт о решении) — выдумывать варианты нельзя;
    * бот не умеет обработать нажатие (маячок ADR-069) ⇒ текст уходит без кнопок.

    ``dry_run=True`` собирает сообщение, но не отправляет (тесты / ``--check``).

    ``owner_requested=True`` — владелец САМ попросил прислать этот вопрос заново
    (решение 20.08, вариант 2). Только это снимает анти-шторм и дедуп, и только для
    одной отправки: оба заслона стоят против НАШЕЙ инициативы, а не против просьбы
    владельца — «спросил дважды, ответить обязаны дважды» (тот же принцип, что
    ``solicited`` у ``guard_outbound``). Заслоны при этом не ослаблены ни на строку:
    без явного флага поведение прежнее, байт в байт.
    """
    card = load_card(path)
    # Анти-шторм (инцидент 2026-08-20: 200+ копий одного решения за ночь): та же
    # карточка без ответа не уходит чаще окна и потолка попыток. Сухой прогон
    # (--check, тесты) гейт не трогает — он ничего не отправляет.
    if not dry_run and not owner_requested:
        try:
            from spa_core.telegram.owner_decisions import throttle_state

            allowed, why = throttle_state(Path(path).stem)
            if not allowed:
                log.warning("notify_needs_owner SUPPRESSED for %s: %s", path, why)
                return f"[anti-storm] отправка подавлена: {why}"
        except Exception as exc:  # noqa: BLE001 — защита не важнее уведомления
            log.warning("notify_needs_owner throttle check failed (%s) — шлю", exc)
    keyboard = None
    # `None` — сообщение собрать не удалось, регистрации нет, и отмечать исход не на чем.
    prep_pid: str | None = None
    try:
        from spa_core.telegram import owner_decisions

        # Сухой прогон НЕ регистрирует. Регистрация нужна кнопке (в момент нажатия надо
        # знать, что предлагалось), а при `--check` нажимать нечего: сообщение не ушло.
        # До #216 порядок был обратный — `register_push` стоял ДО `if dry_run`, и сухой
        # прогон оставлял в живом `data/telegram_owner_decisions.json` запись о карточке,
        # которую никто не отправлял (замер #183, дважды). Тот же класс, что «прогон
        # тестов ЗАГЛУШИЛ живой чат» (#180): сухая проверка меняет живое состояние.
        # ТЕКСТ при этом обязан остаться тем же самым — иначе сухой прогон показывал бы
        # не то, что уедет; за это отвечает общий `prepare_push`.
        prep = (owner_decisions.prepare_push(card.path, card.title or card.id, card.body)
                if dry_run else
                owner_decisions.register_push(card.path, card.title or card.id, card.body))
        # Берём подготовленный текст ВСЕГДА, а не только когда есть варианты.
        # Раньше при пустом списке уходил старый служебный вид — и многовыборная карточка
        # («можно взять несколько», вариантов намеренно ноль) теряла ЧЕСТНОЕ объяснение
        # «кнопок нет, ответь номерами», получая вместо него «переведи статус в Nimbalyst».
        # Запасной вид остаётся только на случай, когда подготовка вообще не удалась.
        msg = prep.text
        keyboard = prep.keyboard
        # Сухой прогон НЕ регистрировал запись — отмечать исход тоже не на чем.
        prep_pid = None if dry_run else prep.pid
    except Exception as exc:  # noqa: BLE001 — красивый вид не важнее самого уведомления
        log.warning("notify_needs_owner: rich build failed for %s: %s", path, exc)
        msg = build_message(card)

    if dry_run:
        return msg
    try:
        from spa_core.telegram.bot import TelegramBot

        bot = TelegramBot()
        # Лестница деградации, и порядок ступеней — это ПРИОРИТЕТ, а не стиль:
        #   кнопки + дедуп  →  дедуп  →  голая отправка.
        # `reply_markup` передаём ТОЛЬКО когда кнопки есть: путь без кнопок обязан остаться
        # байт-в-байт прежним. `dedup=True` — вопрос владельцу НЕ солиситирован, он его не
        # просил; побуквенно тот же вопрос в окне 30 минут не несёт ни одного нового факта,
        # а именно им владельца и заваливало (жалоба 09.08, повтор 13.08).
        # Но НИЖНЯЯ ступень намеренно без обоих: отправитель, который не знает новых
        # параметров, обязан всё равно доставить. Потерять оформление можно, потерять дедуп
        # можно (лишний повтор владелец переживёт), потерять само уведомление о решении —
        # нет. Ровно это проверяет `test_notification_reaches_a_sender_that_knows_nothing_
        # about_buttons`, и цикл #215 на нём и покраснел, добавив `dedup` в нижнюю ступень.
        def _send(**extra):
            return bot.send_message(msg, parse_mode="HTML", **extra)

        # Владелец попросил прислать вопрос заново ⇒ сообщение СОЛИЦИТИРОВАНО, и дедуп
        # (окно 30 мин, текст побуквенно тот же) обязан пропустить его — иначе исполнение
        # его же решения гасится нашей защитой от нас самих. Лимит потока НЕ снимается
        # ничем: он общий на всех отправителей и защищает канал, а не владельца от нас.
        dedup = not owner_requested
        try:
            ok = (_send(reply_markup=keyboard, dedup=dedup) if keyboard is not None
                  else _send(dedup=dedup))
        except TypeError as exc:
            log.warning("notify_needs_owner: sender rejected reply_markup (%s) — "
                        "отправляю без кнопок", exc)
            try:
                ok = _send(dedup=dedup)
            except TypeError as exc2:
                log.warning("notify_needs_owner: sender rejected dedup (%s) — шлю без "
                            "него; лишний повтор лучше потерянного вопроса", exc2)
                ok = _send()
        if not ok:
            log.warning("notify_needs_owner: send returned falsy for %s", path)
        # `ok` — это ПОЛНЫЙ ответ Telegram API, а в нём лежит `message_id`. Сжимать его
        # здесь до `bool` мы и перестаём: ровно на этой строке терялся адресат ответа
        # владельца (замер 20.08 — «Ответ 1» дважды отвергнут как «неоднозначно», хотя
        # Телеграм знал адресата точно). Отправку это не трогает ничем.
        _record_outcome(prep_pid, ok=bool(ok), result=ok)
    except Exception as exc:  # noqa: BLE001 — notification must never crash the orchestrator
        log.warning("notify_needs_owner: send failed for %s: %s", path, exc)
        _record_outcome(prep_pid, ok=False)
    return msg


def _record_outcome(pid: str | None, *, ok: bool, result=None) -> None:
    """Записать в журнал пушей, УЕХАЛО ли сообщение. Никогда не бросает.

    Без этого шага журнал знает только НАМЕРЕНИЕ: `register_push` ставит `buttons: true`
    ещё до отправки, а между ней и владельцем стоит `guard_outbound` (лимит 12/мин на всех
    отправителей + дедуп), который роняет сообщение молча и возвращает `None`. Запись при
    этом продолжает утверждать, что кнопки доставлены, и `heal_buttonless` такую запись не
    чинит НИКОГДА (он берёт только `buttons is False`).

    Это и есть механика жалобы владельца «кнопки решения так и не пришли»: массовая
    рассылка открытых вопросов упирается в лимит потока, часть сообщений гаснет, а все
    журналы показывают успех.
    """
    if not pid:
        return
    try:
        from spa_core.telegram import owner_decisions

        owner_decisions.mark_send_outcome(
            pid, ok=ok, message_id=owner_decisions.message_id_of(result))
    except Exception as exc:  # noqa: BLE001 — наблюдение не роняет уведомление
        log.warning("notify_needs_owner: outcome record failed for %s: %s", pid, exc)


WITHDRAWN_REASON = ("находка исчезла при следующем прогоне сторожа — "
                    "тревога оказалась ложной")


def build_withdrawn_message(card: Card, reason: str = WITHDRAWN_REASON) -> str:
    try:
        rel = str(card.path.resolve().relative_to(Path(__file__).resolve().parents[2]))
    except Exception:
        rel = card.path.name
    return (
        f"🟩 <b>Вопрос снят — отвечать не нужно</b>\n"
        f"<b>{html.escape(card.title or card.id)}</b>\n"
        f"➡️ {html.escape(reason)}\n"
        f"📄 <code>{html.escape(rel)}</code>\n"
        f"Карточка закрыта автоматически. Считаешь, что вопрос остался — верни ей статус."
    )


def notify_card_withdrawn(path: str | Path, *, reason: str = WITHDRAWN_REASON,
                          dry_run: bool = False) -> str:
    """Сообщить владельцу, что заданный ему вопрос отпал (цикл #172).

    Пара к :func:`notify_needs_owner`. Без неё авто-закрытие карточки означало бы,
    что в чате навсегда висит «нужно решение» по вопросу, которого больше нет:
    владелец видит требование, а карточка за ним уже `done`. Снять вопрос молча —
    отдельный дефект, а не экономия сообщения.

    Заодно гасим кнопки этой карточки: нажатие по старому сообщению не должно
    записывать «ответ владельца» в закрытую карточку (см. ``owner_decisions``).
    """
    card = load_card(path)
    msg = build_withdrawn_message(card, reason)
    if dry_run:
        return msg
    try:
        from spa_core.telegram import owner_decisions

        owner_decisions.mark_withdrawn(card.path)
    except Exception as exc:  # noqa: BLE001 — кнопки важны, но отзыв важнее
        log.warning("notify_card_withdrawn: mark_withdrawn failed for %s: %s", path, exc)
    try:
        from spa_core.telegram.bot import TelegramBot

        # dedup=True — отзыв карточки владелец тоже не просил (см. notify_needs_owner).
        if not TelegramBot().send_message(msg, parse_mode="HTML", dedup=True):
            log.warning("notify_card_withdrawn: send returned falsy for %s", path)
    except Exception as exc:  # noqa: BLE001 — уведомление не роняет оркестратор
        log.warning("notify_card_withdrawn: send failed for %s: %s", path, exc)
    return msg
