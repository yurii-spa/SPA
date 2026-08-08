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
