#!/usr/bin/env python3
"""Решения владельца в Телеграме: разбор вариантов, кнопки, запись ответа.

Каждый тест — положительный контроль над КОНКРЕТНЫМ способом сломать владельцу отпуск:

* кнопка, которой нет в карточке (выдуманный вариант);
* «Вариант» из соседней секции, уехавший в выбор;
* кнопка, которую некому обработать (бот старый) — стирает сам вопрос;
* чужое нажатие, закрывающее карточку владельца (инвариант #14);
* «личность не подтвердили» ⇒ молча разрешили (fail-OPEN — наш родовой класс дефектов);
* двойное нажатие, выглядящее как два разных решения.

Живого Телеграма и сети здесь нет: проверяем ЧИСТЫЕ функции и запись в файл.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.owner_queue import queue as q
from spa_core.owner_queue.owner_answer import (
    ANSWER_HEADING,
    NotTheOwner,
    is_owner,
    record_owner_answer,
)
from spa_core.telegram import owner_decisions as od
from spa_core.tests._freshness import now_utc

# Время — ВХОД, а не окружение (`.claude/rules/deployment.md`, преференция №1): якорь берётся
# от часов один раз, все отметки строятся от него, и `now=` передаётся в каждый вызов. Ни одной
# литеральной даты — тест не может покраснеть оттого, что сдвинулся календарь.
NOW = now_utc()
OWNER = "123456789"
STRANGER = "987654321"

# Формат §2.4 — ровно так пишутся живые карточки решений.
CARD = """---
trackerStatus:
  type: owner-decision
title: "Деньги лежат в кэше"
status: needs-owner
---

## Что случилось и почему это важно

Каждый день система решает, куда разложить деньги. Страховка сработала правильно, но
освободившийся бюджет **никто не перекладывает** — он ложится в кэш и лежит.

## Что от тебя нужно

Это money-path, сам не трогаю. Выбери один вариант.

* **Вариант 1 (рекомендую) — перезаполнять освободившийся бюджет.** Ещё раз прогонять ту
  же раскладку по оставшимся пулам, строго внутри тех же потолков.
* **Вариант 2 — оставить как есть, но честно назвать.** Ничего не менять, просто писать
  в артефакте «столько-то заморожено».
* **Вариант 3 — снять причину заморозки.** Починить наблюдение за TVL.

## Как понять, что готово

`capital_cash_unexplained_pct` держится около нуля.

## Что будет после

Живые карточки ПЕРЕСКАЗЫВАЮТ варианты и после выбора — тем же оформлением, и заодно
описывают отвергнутые ходы, которых владельцу предлагать НЕЛЬЗЯ:

* **Вариант 1 — оформляю ADR и делаю через pre_cutover_gate.** С замером до/после.
* **Вариант 4 — распродать книгу и уйти в кэш.** Рассматривался и отвергнут: это не выбор,
  а описание того, что мы делать не будем.
"""

# Карточка, где ВЛОЖЕННЫЙ ключ называется так же, как верхнеуровневый. Правка обязана
# попасть в верхний уровень: иначе статус «needs-owner» останется, а решение уедет
# внутрь `trackerStatus:` — карточка навсегда зависнет в очереди владельца.
CARD_NESTED_COLLISION = """---
trackerStatus:
  type: owner-decision
  status: legacy-nested
title: "Столкновение имён"
status: needs-owner
---

## Что от тебя нужно

* **Вариант 1 (рекомендую) — сделать хорошо.** Текст.
"""


def _write_card(tmp_path: Path, name: str = "own-1.md", text: str = CARD) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _beacon(tmp_path: Path, *, age_s: int = 0, capability: str = "alert_actions") -> Path:
    p = tmp_path / "beacon.json"
    stamped = NOW - timedelta(seconds=age_s)
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": stamped.isoformat(), "pid": 1,
        "capabilities": [capability],
    }), encoding="utf-8")
    return p


# ── разбор вариантов ─────────────────────────────────────────────────────────


def test_parses_the_three_options_and_marks_the_recommended_one():
    """Живой формат §2.4 разбирается: 3 варианта, рекомендация — на первом."""
    opts = od.parse_options(CARD)
    assert [o.num for o in opts] == ["1", "2", "3"]
    assert [o.recommended for o in opts] == [True, False, False]
    assert opts[0].label == "перезаполнять освободившийся бюджет"


def test_variants_retold_in_a_later_section_are_not_offered_as_choices():
    """Положительный контроль: секция «Что будет после» пересказывает варианты ТЕМ ЖЕ
    оформлением и описывает ОТВЕРГНУТЫЙ ход («Вариант 4 — распродать книгу»). Без изоляции
    секции он стал бы четвёртой кнопкой — владелец одним нажатием с телефона заказал бы то,
    что карточка прямо называет несделаемым."""
    opts = od.parse_options(CARD)
    assert [o.num for o in opts] == ["1", "2", "3"]
    assert all("распродать" not in o.label for o in opts)


def test_card_without_options_yields_no_buttons(tmp_path):
    """Fail-CLOSED: вариантов нет ⇒ кнопок нет, но САМО уведомление уходит.

    Выдуманная кнопка хуже её отсутствия: владелец нажмёт то, чего в карточке не писали.
    """
    body = "## Что случилось и почему это важно\n\nВсё плохо.\n\n## Что от тебя нужно\n\nПозвони мне.\n"
    prep = od.prepare("Заголовок", body, "own-9", now=NOW, beacon_path=_beacon(tmp_path))
    assert prep.options == []
    assert prep.keyboard is None
    assert "Нужно твоё решение" in prep.text  # уведомление НЕ подавлено


def test_options_survive_letter_numbering_and_dash_variants():
    """«Вариант Б – …» с другим тире и буквой тоже разбирается: карточки пишут люди."""
    body = "## Что от тебя нужно\n\n* **Вариант Б – подождать неделю.** Текст.\n"
    opts = od.parse_options(body)
    assert len(opts) == 1 and opts[0].num == "Б"


# Живая карточка цикла #208 (`owner-decision-sbalansirovannyi-tir-na-saite-idet-paper`):
# жирный первого варианта перенесён по ширине строки — ровно так карточки и пишутся.
CARD_WRAPPED_BOLD = """---
trackerStatus:
  type: owner-decision
title: "Сбалансированный тир"
status: needs-owner
---

## Что от тебя нужно

Выбери, что делать с формулировкой на сайте.

* **Вариант 1 (рекомендую) — убрать «идёт paper-трек» из статуса Сбалансированного, пока в
  книге не появятся позиции.** Останется «ИССЛЕДОВАНИЕ · без live-аллокации».
* **Вариант 2 — оставить формулировку, но дописать честную оговорку.** Читателю видно ровно
  то, что есть.
* **Вариант 3 — оставить как есть.** Тогда запишу это решение в ADR.
"""


def test_option_whose_bold_wraps_to_the_next_line_is_not_lost():
    """Перенос строки внутри `**…**` съедал вариант МОЛЧА — и первым съел рекомендуемый.

    Замер 13.08 на живой карточке: три варианта в тексте, две кнопки владельцу, исчез
    именно тот, что помечен «рекомендую». Владелец увидел бы «Варианты: 2, 3» — и решил бы,
    что первого не предлагали. Перенос по ширине — норма письма, а не порча карточки.
    """
    opts = od.parse_options(CARD_WRAPPED_BOLD)
    assert [o.num for o in opts] == ["1", "2", "3"]
    assert [o.recommended for o in opts] == [True, False, False]
    assert opts[0].label.startswith("убрать")


def test_the_owner_sees_every_option_the_card_lists():
    """Сообщение владельцу и текст карточки обязаны предлагать ОДНО и то же."""
    msg = od.build_message("Сбалансированный тир", CARD_WRAPPED_BOLD,
                           od.parse_options(CARD_WRAPPED_BOLD), has_buttons=True)
    for num in ("1.", "2.", "3."):
        assert f"<b>{num}</b>" in msg
    assert "рекомендую" in msg


def test_an_unclosed_bold_does_not_swallow_the_whole_section():
    """Опечатка автора (жирный не закрыт НИГДЕ) не имеет права склеить секцию в один пункт."""
    body = ("## Что от тебя нужно\n\n"
            "* **Вариант 1 — забыл закрыть жирный.\n"
            "* **Вариант 2 — оставить как есть.** Текст.\n")
    opts = od.parse_options(body)
    assert [o.num for o in opts] == ["1"] or [o.num for o in opts] == ["1", "2"], \
        "склейка не должна терять оба варианта разом"


# ── callback_data ────────────────────────────────────────────────────────────


def test_callback_fits_telegram_limit_and_round_trips():
    """64 байта — жёсткий лимит Telegram; длинное имя карточки обязано в него влезать."""
    pid = od.make_pid("owner-decision-posle-strahovki-dengi-ostayutsya-sirotam-i-eshe-dlinnee")
    data = od.build_callback(pid, "1")
    assert len(data.encode("utf-8")) <= od.CALLBACK_MAX_BYTES
    assert od.parse_callback(data) == (pid, "1")


def test_callback_of_a_foreign_verb_is_not_ours():
    """Чужой callback (кнопка алертов) не должен разбираться как решение владельца."""
    assert od.parse_callback("act:aa:abcd1234:fix") is None
    assert od.parse_callback("nav:home") is None


def test_pid_is_stable_across_pushes():
    """Повторная отправка той же карточки даёт ТОТ ЖЕ pid.

    Иначе вчерашнее сообщение в переписке становится мёртвым: владелец жмёт кнопку
    старого пуша, а журнал такого pid уже не знает.
    """
    assert od.make_pid("own-1") == od.make_pid("own-1")


# ── интерлок «есть ли кому обработать нажатие» ───────────────────────────────


def test_no_buttons_when_the_bot_beacon_is_stale(tmp_path):
    """Положительный контроль аварии 2026-08-08: бот работал со старым кодом, маячка не
    было — и кнопка, попав на такого бота, СТЁРЛА БЫ текст тревоги панелью настроек."""
    stale = _beacon(tmp_path, age_s=10_000)
    prep = od.prepare("Заголовок", CARD, "own-1", now=NOW, beacon_path=stale)
    assert prep.options, "варианты обязаны разобраться — проверяем именно интерлок"
    assert prep.keyboard is None


def test_buttons_appear_when_a_live_bot_is_present(tmp_path):
    """Обратная сторона: маячок свежий ⇒ кнопки есть. Контроль в обе стороны."""
    prep = od.prepare("Заголовок", CARD, "own-1", now=NOW, beacon_path=_beacon(tmp_path))
    rows = prep.keyboard["inline_keyboard"]
    assert len(rows) == 4  # 3 варианта + «Подробнее»
    assert rows[0][0]["text"].startswith("⭐ 1.")


# ── запись ответа: инвариант #14 ─────────────────────────────────────────────


def test_stranger_cannot_close_the_owners_card(tmp_path):
    """ЧУЖОЕ нажатие не закрывает карточку владельца — и не меняет её ни на байт."""
    card = _write_card(tmp_path)
    before = card.read_text(encoding="utf-8")
    with pytest.raises(NotTheOwner):
        record_owner_answer(card, choice_num="1", choice_label="x",
                            actor_chat_id=STRANGER, owner_chat_id=OWNER, now=NOW)
    assert card.read_text(encoding="utf-8") == before


def test_unverifiable_identity_is_refused_not_allowed(tmp_path):
    """Fail-CLOSED против нашего родового дефекта: «не смогли проверить» ≠ «разрешено».

    chat_id владельца неизвестен (пусто в Keychain) — значит подтвердить некем, значит отказ.
    """
    card = _write_card(tmp_path)
    assert is_owner(STRANGER, "") is False
    assert is_owner("", "") is False
    with pytest.raises(NotTheOwner):
        record_owner_answer(card, choice_num="1", choice_label="x",
                            actor_chat_id=STRANGER, owner_chat_id="", now=NOW)
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


def test_owner_answer_closes_the_card_and_records_who_and_when(tmp_path):
    """Владелец решил: статус owner-done, выбор и авторство — в карточке (аудит)."""
    card = _write_card(tmp_path)
    res = record_owner_answer(card, choice_num="1",
                              choice_label="перезаполнять освободившийся бюджет",
                              actor_chat_id=OWNER, owner_chat_id=OWNER, now=NOW)
    assert res["already"] is False
    text = card.read_text(encoding="utf-8")
    assert "status: owner-done" in text
    assert "status: needs-owner" not in text
    assert "owner_choice: 1" in text
    assert f"owner_answered_by: {OWNER}" in text
    assert "owner_answer_via: telegram" in text
    assert ANSWER_HEADING in text
    assert "перезаполнять освободившийся бюджет" in text.split(ANSWER_HEADING)[1]


def test_nested_field_of_the_same_name_is_not_mistaken_for_the_top_level_one(tmp_path):
    """Положительный контроль: вложенный `trackerStatus.status` имеет отступ и НЕ должен
    перехватить правку. Иначе решение уедет внутрь блока, верхний `status:` останется
    `needs-owner`, и карточка навсегда зависнет в очереди владельца — молча."""
    card = _write_card(tmp_path, "own-nested.md", CARD_NESTED_COLLISION)
    record_owner_answer(card, choice_num="1", choice_label="сделать хорошо",
                        actor_chat_id=OWNER, owner_chat_id=OWNER, now=NOW)
    text = card.read_text(encoding="utf-8")
    assert "  status: legacy-nested" in text, "вложенный ключ обязан остаться нетронутым"
    loaded = q.load_card(card)
    assert loaded.tracker_type == "owner-decision"
    assert loaded.status == "owner-done"


def test_answer_keeps_the_card_type_intact(tmp_path):
    """Тип карточки после ответа не должен пострадать: `type:` тоже вложенный ключ."""
    card = _write_card(tmp_path)
    record_owner_answer(card, choice_num="2", choice_label="оставить как есть",
                        actor_chat_id=OWNER, owner_chat_id=OWNER, now=NOW)
    assert "  type: owner-decision" in card.read_text(encoding="utf-8")
    assert q.load_card(card).tracker_type == "owner-decision"


def test_second_identical_tap_does_not_write_a_second_decision(tmp_path):
    """Владелец может нажать дважды (из двух чатов, по плохой связи). Это ОДНО решение."""
    card = _write_card(tmp_path)
    record_owner_answer(card, choice_num="1", choice_label="x",
                        actor_chat_id=OWNER, owner_chat_id=OWNER, now=NOW)
    res2 = record_owner_answer(card, choice_num="1", choice_label="x",
                               actor_chat_id=OWNER, owner_chat_id=OWNER, now=NOW)
    assert res2["already"] is True
    assert card.read_text(encoding="utf-8").count(ANSWER_HEADING) == 1


def test_agent_path_to_owner_done_stays_forbidden(tmp_path):
    """Инвариант #14 НЕ ослаблен: агентский путь по-прежнему отказывает.

    Новый owner-путь добавлен РЯДОМ, а не вместо — если однажды кто-то «упростит»
    set_status, этот тест покраснеет.
    """
    card = _write_card(tmp_path)
    with pytest.raises(q.OwnerDoneForbidden):
        q.set_status(card, "owner-done")
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


# ── нажатие целиком (журнал + карточка) ──────────────────────────────────────


def test_tap_records_the_choice_end_to_end(tmp_path):
    """Полный путь: отправили → нажали → решение в карточке, выбор в журнале."""
    card = _write_card(tmp_path)
    state = tmp_path / "state.json"
    prep = od.register_push(card, "Деньги лежат в кэше", CARD, now=NOW,
                            state_path=state, beacon_path=_beacon(tmp_path))
    res = od.record_choice(prep.pid, "1", OWNER, owner_chat_id=OWNER, now=NOW,
                           state_path=state)
    assert res["ok"] is True
    assert res["label"] == "перезаполнять освободившийся бюджет"
    assert "status: owner-done" in card.read_text(encoding="utf-8")
    rec = od.find_push(prep.pid, state_path=state)
    assert rec["choice"] == "1"


def test_tap_after_the_question_was_withdrawn_records_nothing(tmp_path):
    """Цикл #172: мост научился закрывать ложную тревогу сам — значит появилась
    кнопка под вопросом, которого больше нет. Нажатие через три дня НЕ смеет
    записать «решение владельца» в закрытую карточку, и обязано это объяснить."""
    card = _write_card(tmp_path)
    state = tmp_path / "state.json"
    prep = od.register_push(card, "t", CARD, now=NOW, state_path=state,
                            beacon_path=_beacon(tmp_path))
    assert od.mark_withdrawn(card, now=NOW, state_path=state) is True
    res = od.record_choice(prep.pid, "1", OWNER, owner_chat_id=OWNER, now=NOW,
                           state_path=state)
    assert res == {"ok": False, "reason": "card_withdrawn", "card": str(card)}
    assert "owner_choice" not in card.read_text(encoding="utf-8")
    # Отказ — это ответ, а не молчание: у владельца должна быть внятная фраза.
    assert "снят" in od.confirmation_text(res)


def test_an_already_answered_question_cannot_be_withdrawn(tmp_path):
    """Обратный контроль: ответ владельца сильнее авто-закрытия. Если решение
    записано, снимать вопрос задним числом нельзя — это стёрло бы ответ."""
    card = _write_card(tmp_path)
    state = tmp_path / "state.json"
    prep = od.register_push(card, "t", CARD, now=NOW, state_path=state,
                            beacon_path=_beacon(tmp_path))
    od.record_choice(prep.pid, "1", OWNER, owner_chat_id=OWNER, now=NOW, state_path=state)
    assert od.mark_withdrawn(card, now=NOW, state_path=state) is False
    assert od.find_push(prep.pid, state_path=state)["choice"] == "1"


def test_withdrawal_message_says_the_question_is_gone_and_names_the_card(tmp_path):
    """Текст отзыва: владелец должен понять, что отвечать не нужно, и на что именно."""
    from spa_core.owner_queue.notify import notify_card_withdrawn

    card = _write_card(tmp_path)
    msg = notify_card_withdrawn(card, dry_run=True)   # dry_run: сети и записи нет
    assert "Вопрос снят" in msg and "отвечать не нужно" in msg
    assert "Деньги лежат в кэше" in msg
    assert "нужно решение" not in msg


def test_tap_on_an_option_that_was_never_offered_is_refused(tmp_path):
    """Кнопка «Вариант 7» из ниоткуда (подделанный callback) ничего не записывает."""
    card = _write_card(tmp_path)
    state = tmp_path / "state.json"
    prep = od.register_push(card, "t", CARD, now=NOW, state_path=state,
                            beacon_path=_beacon(tmp_path))
    res = od.record_choice(prep.pid, "7", OWNER, owner_chat_id=OWNER, now=NOW,
                           state_path=state)
    assert res == {"ok": False, "reason": "unknown_option", "card": str(card)}
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


def test_tap_on_an_unknown_card_answers_instead_of_crashing(tmp_path):
    """Нажатие по сообщению, которого журнал уже не помнит (кольцо переполнилось)."""
    res = od.record_choice("deadbeef", "1", OWNER, owner_chat_id=OWNER, now=NOW,
                           state_path=tmp_path / "state.json")
    assert res == {"ok": False, "reason": "unknown_card"}


def test_stranger_tap_is_refused_at_the_tap_level_too(tmp_path):
    """Тот же отказ, но через публичный путь нажатия — без исключения наружу."""
    card = _write_card(tmp_path)
    state = tmp_path / "state.json"
    prep = od.register_push(card, "t", CARD, now=NOW, state_path=state,
                            beacon_path=_beacon(tmp_path))
    res = od.record_choice(prep.pid, "1", STRANGER, owner_chat_id=OWNER, now=NOW,
                           state_path=state)
    assert res["ok"] is False and res["reason"] == "not_owner"
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


# ── человеческий вид сообщения ───────────────────────────────────────────────


def test_message_stays_within_telegram_length_limit():
    """Карточки бывают на 12 КБ. Сообщение длиннее 4096 Telegram просто НЕ доставит."""
    huge = CARD.replace("Каждый день система", "Очень длинный текст. " * 800)
    text = od.build_message("Заголовок", huge, od.parse_options(huge))
    assert len(text) < 4096


def test_summary_is_plain_russian_without_markdown_scaffolding():
    """Владельцу едет текст, а не разметка: звёздочек и обратных кавычек быть не должно."""
    s = od.summarize(CARD)
    assert "**" not in s and "`" not in s
    assert "никто не перекладывает" in s


# ── формы, которыми варианты пишут на самом деле ─────────────────────────────

# Замер по 76 живым карточкам: нумерованная форма — самая частая (69 строк в 23 карточках).
CARD_NUMBERED = """---
trackerStatus:
  type: owner-decision
title: "Морфо подставляет выдуманные проценты"
status: needs-owner
---

## Что от тебя нужно

Выбрать один из трёх вариантов:

1. **Довести правило до конца (рекомендую).** Убрать подстановку — нет данных означает «не знаю».
   *Почему рекомендую:* это ровно то правило, которое ты уже одобрил.
2. **Оставить как есть**, но тогда честно записать в ADR-063, что это заявленное исключение.
3. **Оставить подстановку, но пометить её как «не наблюдение».** Число остаётся ради расчётов.
"""

# Живая карточка own-31: ДВА НЕЗАВИСИМЫХ вопроса, у каждого своя рекомендация «да».
CARD_TWO_QUESTIONS = """---
trackerStatus:
  type: owner-decision
title: "Десять агентов в реестре без флота"
status: needs-owner
---

## Что от тебя нужно

Два решения:

1. **Ставить ли четыре готовых?** Рекомендация: да. Код есть, программы на месте.
2. **Выводить ли шесть из реестра?** Рекомендация: да. Пять описывают несуществующее.
"""


def test_numbered_form_is_parsed_it_is_the_most_common_one():
    """Положительный контроль замера: большинство карточек пишет варианты нумерованным
    списком без слова «Вариант». Разбирая только «* **Вариант N — …**», мы оставили бы
    без кнопок 23 карточки из 76 — ровно те, на которые владелец рассчитывает."""
    opts = od.parse_options(CARD_NUMBERED)
    assert [o.num for o in opts] == ["1", "2", "3"]
    assert [o.recommended for o in opts] == [True, False, False]
    # «(рекомендую)» — пометка, а не суть: на кнопке её заменяет ⭐.
    assert opts[0].label == "Довести правило до конца"
    # Жирное выделение может кончаться посреди предложения — берём выделенное.
    assert opts[1].label == "Оставить как есть"


def test_a_card_asking_two_independent_questions_gets_no_buttons(tmp_path):
    """Положительный контроль по живой карточке own-31: «Два решения: 1. Ставить ли…?
    2. Выводить ли…?» — это НЕ выбор одного варианта. Кнопки сделали бы вопросы
    взаимоисключающими: нажатие на «1» закрыло бы карточку, а второй вопрос владельца
    умер бы молча. Fail-CLOSED: кнопок нет, уведомление уходит текстом."""
    assert od.parse_options(CARD_TWO_QUESTIONS) == []
    prep = od.prepare("Десять агентов", CARD_TWO_QUESTIONS, "own-31", now=NOW,
                      beacon_path=_beacon(tmp_path))
    assert prep.keyboard is None
    assert "Нужно твоё решение" in prep.text


# Третья живая форма: в жирном стоит ТОЛЬКО пометка, суть — сразу за ним.
CARD_LABEL_AFTER_BOLD = """---
trackerStatus:
  type: owner-decision
title: "Куда записать находку"
status: needs-owner
---

## Что от тебя нужно

Выбрать, куда это записать.

- **Вариант 1 (рекомендую).** НЕ заводить третий paper-трек и НЕ создавать нового агента.
  Вместо этого добавить ранжирование второй рукой внутрь уже одобренного модуля.
  *Почему рекомендую:* ноль дополнительной нагрузки на флот при максимуме информации.
- **Вариант 2.** Отдать находку кураторам тиров как правило распределения.
"""


def test_option_label_may_live_right_after_the_bold_marker():
    """Положительный контроль по живой карточке own-rnd-xvd: «- **Вариант 1 (рекомендую).**
    НЕ заводить третий paper-трек…» — точка вместо тире, суть ЗА жирным. Не разбирая эту
    форму, мы отдавали владельцу карточку без кнопок, хотя варианты в ней есть."""
    opts = od.parse_options(CARD_LABEL_AFTER_BOLD)
    assert [o.num for o in opts] == ["1", "2"]
    assert opts[0].recommended is True
    assert opts[0].label == "НЕ заводить третий paper-трек и НЕ создавать нового агента"
    # Обоснование «Почему рекомендую…» на кнопку не едет — только первое предложение.
    assert "Почему рекомендую" not in opts[0].label


# ── текст не имеет права обещать несуществующую кнопку ───────────────────────


def test_message_never_promises_a_button_that_will_not_be_there(tmp_path):
    """Положительный контроль замеренной аварии: владельцу пришло решение с фразой
    «Нажми кнопку — запишу решение» и БЕЗ единой кнопки.

    Причина: текст строился ДО решения о клавиатуре и всегда обещал кнопку. Обещать
    несуществующее хуже, чем не обещать: владелец решает, что сломан бот, и перестаёт
    верить всему каналу. Текст и клавиатура обязаны говорить одно.
    """
    stale = _beacon(tmp_path, age_s=10_000)  # обработчика нет ⇒ кнопок не будет
    prep = od.prepare("Заголовок", CARD, "own-1", now=NOW, beacon_path=stale)
    assert prep.keyboard is None
    assert prep.options, "варианты обязаны разобраться — проверяем именно согласованность"
    assert "Нажми кнопку" not in prep.text
    assert "Ответь номером варианта" in prep.text


def test_message_does_promise_the_button_when_it_is_really_there(tmp_path):
    """Контроль в обратную сторону: кнопки есть — зовём нажимать."""
    prep = od.prepare("Заголовок", CARD, "own-1", now=NOW, beacon_path=_beacon(tmp_path))
    assert prep.keyboard is not None
    assert "Нажми кнопку" in prep.text


# ── формы, найденные на живой карточке про табличку честности ────────────────

CARD_PLAIN_AND_INLINE_STAR = """---
trackerStatus:
  type: owner-decision
title: "Табличка честности не доезжает"
status: needs-owner
---

## Что от тебя нужно

Выбери, как поступаем:

1. **Дать правилу честности ту же дорогу, что и доставке**, и разрешить проходить owner-gate.
   Табличка начнёт доезжать. ⭐ **Рекомендация агента:** правило честности должно уметь
   исполняться — сейчас оно не работает вовсе.
2. **Смягчить сам порог сравнения** — сравнивать среднее за сутки.
3. Оставить как есть — но тогда надо понимать, что правило сейчас декоративное.
"""

CARD_MULTISELECT = CARD_PLAIN_AND_INLINE_STAR.replace(
    "Выбери, как поступаем:", "Выбери, как поступаем — можно взять несколько:")


def test_a_numbered_option_without_bold_is_still_an_option():
    """Положительный контроль живой карточки: пункт «3. Оставить как есть — …» написан БЕЗ
    жирного и молча пропадал.

    Спрятать существующий выбор ХУЖЕ, чем не показать кнопок: владелец видел бы две кнопки
    там, где карточка предлагает три, и не узнал бы о третьей.
    """
    opts = od.parse_options(CARD_PLAIN_AND_INLINE_STAR)
    assert [o.num for o in opts] == ["1", "2", "3"]
    assert opts[2].label.startswith("Оставить как есть")


def test_recommendation_inside_the_option_paragraph_is_found():
    """Звёздочка стоит в ПРОДОЛЖЕНИИ абзаца («⭐ Рекомендация агента:»), а не в заголовке.

    Смотреть только на заголовок — значит потерять рекомендацию там, где автор её поставил,
    и лишить владельца главного, ради чего он просил кнопки.
    """
    opts = od.parse_options(CARD_PLAIN_AND_INLINE_STAR)
    assert [o.recommended for o in opts] == [True, False, False]


def test_a_card_allowing_several_answers_gets_no_single_choice_buttons(tmp_path):
    """«можно взять несколько» — одна закрывающая кнопка исказила бы вопрос: владелец выбрал
    бы один пункт, остальные молча отпали бы. Кнопок нет, и текст называет ПРИЧИНУ."""
    assert od.allows_multiple(CARD_MULTISELECT) is True
    assert od.parse_options(CARD_MULTISELECT) == []
    prep = od.prepare("Табличка", CARD_MULTISELECT, "own-x", now=NOW,
                      beacon_path=_beacon(tmp_path))
    assert prep.keyboard is None
    assert "НЕСКОЛЬКО пунктов" in prep.text
    assert "Вариантов в карточке не нашёл" not in prep.text


def test_single_choice_card_is_not_mistaken_for_multiselect():
    """Контроль в обратную сторону: обычная карточка кнопки получает."""
    assert od.allows_multiple(CARD_PLAIN_AND_INLINE_STAR) is False
    assert len(od.parse_options(CARD_PLAIN_AND_INLINE_STAR)) == 3


# ── авария 10.08: десять карточек уехали владельцу БЕЗ КНОПОК ────────────────
#
# Замер по журналу отправок `data/telegram_owner_decisions.json` (21 карточка): десять ушли
# с `options: []`, и НИ НА ОДНУ из этих десяти владелец не ответил — при том что среди
# карточек с кнопками отвеченные есть. Владелец в отъезде и отвечает именно кнопкой.
# Две из десяти — не «карточка без выбора», а наш непрочитанный выбор. Каждый тест ниже
# воспроизводит КОНКРЕТНУЮ живую карточку того дня.

# Живая карточка `owner-decision-sistema-ostanovlena-avariinym-vyklyuchat`: суть отделена
# ДВОЕТОЧИЕМ, а не тире. Ею система стояла остановленной, пока владелец не мог ответить.
CARD_COLON_SEPARATOR = """---
trackerStatus:
  type: owner-decision
title: "Система остановлена аварийным выключателем"
status: needs-owner
---

## Что от тебя нужно

Что сделать с остановкой прямо сейчас.

- **Вариант А (⭐ рекомендую): снять выключатель вручную и дать циклу идти.**
  Основание: ни одно расхождение не является аварией фида.
- **Вариант Б: оставить остановку до починки EB-02.** Честнее «по букве», но каждый день
  стоит дня трека.
"""

# Живая карточка `owner-decision-reshenie-adr-070-p-6-ispolnit-nelzya-odi`: вариант написан
# отдельным АБЗАЦЕМ, без `- ` в начале строки. Ждёт владельца с того же дня.
CARD_BOLD_WITHOUT_BULLET = """---
trackerStatus:
  type: owner-decision
title: "Решение ADR-070 п.6 исполнить нельзя"
status: needs-owner
---

## Что от тебя нужно

Выбрать тир.

**Вариант A (рекомендую) — перевести `morpho_steakhouse` в T2, оценка 0.30.**

**Вариант B — оставить `morpho_steakhouse` в T1 и дать ему собственную оценку ниже 0.25.**

**Вариант C — признать `morpho_blue` дублем и вывести его из книги.**
"""

# Та же карточка про остановку в ИСХОДНОМ виде: ДВА решения, и в каждом свой «Вариант А».
CARD_TWO_DECISIONS_SAME_NUMBERS = """---
trackerStatus:
  type: owner-decision
title: "Два решения в одной карточке"
status: needs-owner
---

## Что от тебя нужно

Два разных решения — их лучше не смешивать.

**Решение 1 — что сделать с остановкой ПРЯМО СЕЙЧАС:**

- **Вариант А (⭐ рекомендую): снять выключатель вручную.** Основание такое-то.
- **Вариант Б: оставить остановку до починки.** Честнее по букве.

**Решение 2 — что делать с самим EB-02:**

- **Вариант А (⭐ рекомендую): сравнивать живое с живым.** Базой брать историю протокола.
- **Вариант Б: обновить константы сегодняшними числами.** Дёшево, но повторится.
- **Вариант В: поднять порог и кворум.** Не рекомендую — глушит сторожа.
"""

# Карточка-поручение: выбора не предлагает вовсе. Контроль в обратную сторону.
CARD_NO_CHOICE_AT_ALL = """---
trackerStatus:
  type: owner-decision
title: "Добавить ключ на сервер"
status: needs-owner
---

## Что от тебя нужно

Зайти в панель Railway и добавить переменную `ETHERSCAN_API_KEY`. Без неё не работает
проверка кошельков.
"""


def test_option_separated_by_a_colon_is_read():
    """Положительный контроль аварии 10.08: `**Вариант А (⭐ рекомендую): снять…**`.

    Разбор ждал только тире, и карточка, которой система стояла ОСТАНОВЛЕННОЙ, уехала
    владельцу без кнопок. Разделитель — оформление; выбор владельца от него не зависит.
    """
    opts = od.parse_options(CARD_COLON_SEPARATOR)
    assert [o.num for o in opts] == ["А", "Б"]
    assert opts[0].label.startswith("снять выключатель")
    assert [o.recommended for o in opts] == [True, False]


def test_option_written_as_a_plain_paragraph_is_read():
    """Второй положительный контроль того же дня: вариант БЕЗ маркера списка.

    `**Вариант A (рекомендую) — перевести…**` отдельным абзацем. Якорь `^\\s*[*\\-+]\\s+`
    такую строку не видел, и карточка про тир `morpho_steakhouse` тоже ушла без кнопок.
    """
    opts = od.parse_options(CARD_BOLD_WITHOUT_BULLET)
    assert [o.num for o in opts] == ["A", "B", "C"]
    assert opts[0].label.startswith("перевести")
    assert [o.recommended for o in opts] == [True, False, False]


def test_two_decisions_in_one_card_get_no_buttons_instead_of_a_mixture(tmp_path):
    """Дубль номера значит, что карточка задаёт НЕ ОДИН вопрос.

    Раньше здесь молча брался первый «Вариант А», а НЕсовпавший номер второго перечня
    («Вариант В») попадал в кнопки наравне с первым: владелец получал ряд из ДВУХ РАЗНЫХ
    вопросов и увидеть этого не мог. Смешать два вопроса хуже, чем не показать кнопок.
    """
    opts = od.parse_options(CARD_TWO_DECISIONS_SAME_NUMBERS)
    assert opts == []
    prep = od.prepare("Два решения", CARD_TWO_DECISIONS_SAME_NUMBERS, "own-2d", now=NOW,
                      beacon_path=_beacon(tmp_path))
    assert prep.keyboard is None
    # Ровно тот вариант, который протекал из ВТОРОГО перечня в кнопки первого:
    # «В» не дублировал ни «А», ни «Б», поэтому молчаливый пропуск дублей его не ловил.
    assert [o.num.lower() for o in prep.options] == []


def test_a_card_with_unreadable_options_says_so_instead_of_denying_them(tmp_path):
    """Кнопок нет по РАЗНЫМ причинам, и владельцу они звучали одинаково.

    «Вариантов в карточке не нашёл» верно для карточки-поручения и ЛОЖНО для карточки, где
    вариантов пять. Владелец читает второе как «выбора и не предлагали» — и не отвечает.
    Это ровно то молчание, которым система простояла остановленной.
    """
    assert od.has_unparsed_options(CARD_TWO_DECISIONS_SAME_NUMBERS) is True
    prep = od.prepare("Два решения", CARD_TWO_DECISIONS_SAME_NUMBERS, "own-2d", now=NOW,
                      beacon_path=_beacon(tmp_path))
    assert "Варианты в карточке есть" in prep.text
    assert "Вариантов в карточке не нашёл" not in prep.text


def test_a_card_that_really_offers_no_choice_keeps_the_old_honest_wording(tmp_path):
    """Контроль в обратную сторону: поручение без выбора НЕ должно выглядеть неполадкой."""
    assert od.parse_options(CARD_NO_CHOICE_AT_ALL) == []
    assert od.has_unparsed_options(CARD_NO_CHOICE_AT_ALL) is False
    prep = od.prepare("Ключ", CARD_NO_CHOICE_AT_ALL, "own-key", now=NOW,
                      beacon_path=_beacon(tmp_path))
    assert "Вариантов в карточке не нашёл" in prep.text
    assert "Варианты в карточке есть" not in prep.text


def test_multiselect_card_keeps_its_own_reason_not_the_defect_wording(tmp_path):
    """У «можно взять несколько» причина СВОЯ и она не неполадка — порядок веток важен."""
    prep = od.prepare("Табличка", CARD_MULTISELECT, "own-x", now=NOW,
                      beacon_path=_beacon(tmp_path))
    assert "НЕСКОЛЬКО пунктов" in prep.text
    assert "Варианты в карточке есть" not in prep.text


# ── Слепое пятно, ОБЩЕЕ у разбора и у его же сторожа (замер цикла #197, 10.08) ──────────
#
# Живая карточка `own-rnd-killswitch-rearm-policy-missing` — единственный вопрос, ждавший
# владельца, — провисела 12,5 часа БЕЗ КНОПОК, и владелец прочёл под ней «Вариантов в
# карточке не нашёл», хотя вариантов пять. Причина: варианты помечены буквой И цифрой
# («Вариант А1», «Вариант Б2»), а номер в ОБОИХ выражениях описан как ОДИН знак — после
# «А» стоит «1», границы слова там нет.
#
# Молчание разбора здесь по замыслу (двумя решениями в одной карточке кнопки не выразить),
# а вот сторож честности заведён СПЕЦИАЛЬНО ради фразы «владелец прочёл „вариантов не
# нашёл“ под карточкой, где их пять» — и промолчал тоже, подтвердив разбору его же слепое
# пятно. Сторож, делящий слепое пятно с тем, кого сторожит, не сторож.
CARD_LETTER_DIGIT_TWO_DECISIONS = """---
type: owner-decision
status: needs-owner
---

# Аварийный тормоз ни разу не срабатывал

## Что от тебя нужно

Два решения. Ни одно из них агент не имеет права принять сам — это риск-контур и go-live.

**Решение А — политика возврата после жёсткой остановки (сейчас её нет вообще).**
- **Вариант А1 (рекомендация агента).** Оставить снятие за владельцем, но добавить срок.
- **Вариант А2.** Автоматический возврат через N дней. Агент это **не рекомендует**.
- **Вариант А3.** Ничего не менять, оставить как есть.

**Решение Б — что должна означать мягкая ступень (5%).**
- **Вариант Б1 (рекомендация агента).** Оставить формулировку «не увеличивать» как есть.
- **Вариант Б2.** Сделать её реальным снижением экспозиции. Агент **не рекомендует**.
"""


def test_letter_digit_options_are_seen_by_the_honesty_guard():
    """Положительный контроль живой карточки 10.08: пять вариантов, ноль кнопок, ложная причина.

    Сторож честности обязан быть ШИРЕ разбора — в этом весь его смысл. Пока он описывает
    номер варианта тем же выражением, что и разбор, «кнопок нет» превращается в «выбора и
    не предлагали», и владелец не отвечает: он ведь прочёл, что отвечать нечего.
    """
    assert od.has_unparsed_options(CARD_LETTER_DIGIT_TWO_DECISIONS) is True


def test_letter_digit_card_tells_the_owner_the_truth_about_missing_buttons(tmp_path):
    """Эффект, а не внутренность: что владелец ЧИТАЕТ под карточкой с пятью вариантами."""
    prep = od.prepare("Аварийный тормоз", CARD_LETTER_DIGIT_TWO_DECISIONS, "own-rearm",
                      now=NOW, beacon_path=_beacon(tmp_path))
    assert prep.keyboard is None, "два решения в одной карточке кнопками не выразить"
    assert "Варианты в карточке есть" in prep.text
    assert "Вариантов в карточке не нашёл" not in prep.text


def test_two_decisions_by_letter_prefix_still_get_no_mixed_buttons():
    """Контроль в обратную сторону: УВИДЕТЬ варианты ≠ смешать два вопроса в один ряд кнопок.

    Дубля номера здесь НЕТ (А1/А2/А3/Б1/Б2 — пять разных), поэтому прежнее правило «дубль
    ⇒ fail-CLOSED» этот случай не ловит. Одно нажатие закрывает карточку целиком: смешав
    «политику возврата» с «смыслом мягкой ступени», мы похоронили бы второй вопрос молча.
    """
    assert od.parse_options(CARD_LETTER_DIGIT_TWO_DECISIONS) == []


def test_single_decision_with_letter_digit_numbers_gets_real_buttons():
    """Обратный контроль ширины: ОДНО решение с номерами А1/А2 — нормальный выбор.

    Составная метка сама по себе не порок — пороком её делает ВТОРАЯ буква рядом. Пока
    буква одна, вопрос один, и владелец обязан получить кнопки, а не приглашение отвечать
    словами: увидеть варианты и не предложить их — половина починки, а владелец в отъезде
    отвечает только кнопкой.
    """
    body = (
        "## Что от тебя нужно\n\n"
        "- **Вариант А1 (⭐ рекомендую): снять выключатель.** Основание такое-то.\n"
        "- **Вариант А2: оставить остановку до починки.** Честнее по букве.\n"
    )
    opts = od.parse_options(body)
    assert [o.num for o in opts] == ["А1", "А2"]
    assert [o.recommended for o in opts] == [True, False]
    assert od.has_unparsed_options(body) is False


def test_the_wider_guard_does_not_drag_in_a_card_that_offers_no_choice():
    """Расширение сторожа не имеет права красить карточку-поручение как неполадку."""
    assert od.has_unparsed_options(CARD_NO_CHOICE_AT_ALL) is False


def test_the_wider_guard_does_not_read_an_ordinary_phrase_as_an_option():
    """И не имеет права звать дефектом обычную фразу, начинающуюся словом «вариант».

    Ложь в другую сторону дороже, чем кажется: владельцу предлагается завести
    несуществующий дефект, а следующая настоящая находка тонет в этом шуме.
    """
    body = "## Что от тебя нужно\n\n- Вариант тот же, что вчера — ничего не делать.\n"
    assert od.has_unparsed_options(body) is False


# ── Отрицательная рекомендация стирала звезду у ВСЕХ (замер #197 по 8 живым карточкам) ──
#
# «Спорно ⇒ звезды нет ни у кого» задумано против ПЕРЕВЁРНУТОЙ подсказки, но било по
# другому: любое честное предупреждение о соседнем варианте («агент это не рекомендует»)
# гасило рекомендацию во всей карточке. Замер 10.08: ВОСЕМЬ открытых карточек владельца,
# и в каждой автор пометил рекомендованный вариант, а владелец получил перечень без единой
# звезды. Чем аккуратнее написана карточка, тем вернее пропадала подсказка.
CARD_STAR_PLUS_HONEST_WARNING = """---
type: owner-decision
status: needs-owner
---

## Что от тебя нужно

- **Вариант 1 (⭐ рекомендую) — сравнивать живое с ЖИВЫМ.** Базой брать наблюдаемое.
- **Вариант 2 — обновить константы сегодняшними числами.** Дёшево, но это бомба.
- **Вариант 3 — поднять порог.** Не рекомендую: это глушит сторожа, не чиня причину.
"""


def test_honest_warning_about_another_option_does_not_erase_the_star():
    """Положительный контроль восьми живых карточек: звезда обязана остаться на своём варианте."""
    opts = od.parse_options(CARD_STAR_PLUS_HONEST_WARNING)
    assert [o.num for o in opts] == ["1", "2", "3"]
    assert [o.recommended for o in opts] == [True, False, False]


def test_the_option_the_card_advises_against_never_gets_the_star():
    """Ради чего гашение и заводили: «(не рекомендую)» в заголовке — это НЕ рекомендация.

    Строка содержит подстроку «рекоменд», и голый поиск по ней ставит звезду ровно тому
    варианту, от которого автор отговаривает. Подсказка наоборот хуже отсутствующей:
    владелец отвечает кнопкой и не перечитывает карточку.
    """
    body = (
        "## Что от тебя нужно\n\n"
        "- **Вариант 1 (не рекомендую) — распродать книгу.** Дорого и необратимо.\n"
        "- **Вариант 2 — оставить как есть.** Ничего не меняем.\n"
    )
    assert [o.recommended for o in od.parse_options(body)] == [False, False]


def test_a_warning_in_the_option_paragraph_does_not_star_that_option():
    """То же самое в ХВОСТЕ абзаца — путь, по которому звезда ищется вторым заходом.

    Формулировка взята с живой карточки `agent-dolgozhivuschie-agenty-krutyat-staryi-kod`
    («*Не рекомендую* — это возвращает нас ровно к 8 августа») и выбрана НАМЕРЕННО: она,
    в отличие от «агент это не рекомендует», проходит через `_RECOMMEND_INLINE_RE`, то
    есть действительно доходит до этой ветки. Первая редакция теста была написана с
    формулировкой, которую эта регулярка не видит вовсе, — тест был зелёным и на
    неисправленном коде, то есть проверял пустоту. Мутация это и показала.
    """
    body = (
        "## Что от тебя нужно\n\n"
        "- **Вариант 1 — оставить как есть.** Ничего не меняем.\n"
        "- **Вариант 2 — автоматический возврат.**\n"
        "  *Не рекомендую* — хвост становится хуже, чем вообще без тормоза.\n"
    )
    assert [o.recommended for o in od.parse_options(body)] == [False, False]


def test_a_recommendation_naming_a_number_still_wins_over_paragraph_position():
    """Контроль неизменности: названный номер по-прежнему сильнее расположения абзаца."""
    body = (
        "## Что от тебя нужно\n\n"
        "- **Вариант 1 — оживить фиды.** Долго, но честно.\n"
        "- **Вариант 2 — пересмотреть лимит.** Быстро.\n"
        "\n"
        "**Рекомендация агента — вариант 1.**\n"
    )
    assert [o.recommended for o in od.parse_options(body)] == [True, False]
