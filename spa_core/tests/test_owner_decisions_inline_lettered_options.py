"""Буквенный перечень ВНУТРИ одного абзаца — «(а) …, (б) …, (в) …» — C5, ADR-580.

Авария (A5_owner_control.md, замер 2026-10-05): живая `owner-decision-disk-mac-mini-
zabit-pod-nol-odin-zhurnal` (`needs-owner` с 2026-09-26) ушла владельцу `buttons:
false` 2026-10-01 и не исцелена. Её «Шаг 2» несёт три буквенных варианта ВНУТРИ
ОДНОГО предложения («Варианты: (а) …, (б) …, (в) …»), а не каждый своим пунктом
списка, — ни один из построчных диалектов разбора их не видел.

Карточка скопирована READ-ONLY из прод-трекера (`~/Documents/SPA_Claude/
nimbalyst-local/tracker/owner-decision-disk-mac-mini-zabit-pod-nol-odin-zhurnal.md`)
— байт в байт, текст не редактировался для теста.

# CHANGED (integration review F5, 2026-10-05 — journal 2026-W40): the ШЕСТОЙ
# диалект introduced here originally built THREE BUTTONS from the disk card's
# «Шаг 2» letter list — correctly isolating it from the SURROUNDING prose, but
# missing that the SAME SECTION carries «Шаг 1» (an owner action) and «Шаг 3» (a
# separate yes/no consent) as independent asks. Pressing one letter would have
# recorded an answer for the whole card and left Шаг 1/Шаг 3 unanswered — a wrong
# button is a wrong owner decision. The fix (`_STEP_BLOCK_RE` + the check in
# `_parse_options_measured`) fails CLOSED with a new `MultiQuestion` reason
# (`MQ_MULTI_STEP`) whenever a section carries more than one `**Шаг N**` block,
# even when only one of them holds the lettered list. This tightens the tests
# below to the corrected, honest behaviour (buttonless + a NAMED reason, not
# three options) — it does not relax any check. A second real fixture (the depeg
# card, where the lettered sub-question and a letterless mandatory step are
# MERGED into one paragraph by the paragraph-splitter itself, since the source
# has no blank line between the two bullet items) is added below per the review's
# request for both real cards as fixtures.
"""
from __future__ import annotations

from spa_core.telegram import owner_decisions as od

# ── реальная карточка, скопированная из прод-трекера ────────────────────────────
DISK_CARD_BODY = """## Что случилось и почему это важно

Диск Mac Mini, на котором живёт вся система, **заполнился до конца**: свободного места
осталось **108 мегабайт из 471 гигабайта** (0,02 %). В таком состоянии машина не может
записать ни одного байта — ни один агент, ни дневной цикл, ни даже команда `touch`. Проверено
запуском: `touch` отказал и в `/tmp`, и в домашнем каталоге.

Прямую причину переполнения я нашёл и убрал: журнал одного агента
(`/tmp/spa_decision_loop.log`, поток вывода `com.spa.decision_loop`) **вырос до 7,1 гигабайта**
без какого-либо усечения — его никто не подрезает. Я его удалил, и свободного места стало
6,9 ГБ; запись снова работает. Журнал лежал в `/tmp` — это предписанное место для логов агентов
(инвариант #12), оно чистится при перезагрузке, поэтому потерян только вывод за последние дни,
а не какие-либо данные трека.

**Но это лечение симптома, а не болезни.** Остаток — **434 ГБ из 471** — занят чем-то другим,
и что это, решать тебе: там твои файлы, и удалять их без тебя я не буду (необратимое действие,
предмет №3 границы ADR-285). Запас 6,9 ГБ на машине, которая крутит 56 агентов и пишет
состояние каждые полчаса, — это дни, а не недели.

Что я проверил и что НЕ пострадало: `data/current_positions.json` и
`data/equity_curve_daily.json` записаны сегодня в 08:00, то есть дневной цикл отработал и трек
не потерян. Я НЕ проверял, сколько агентов молча отказали в записи за время, пока места не
было, — это отдельный замер, и выдавать «не проверял» за «всё хорошо» я не стану.

## Что от тебя нужно

**Шаг 1.** Посмотри, чем занято 434 ГБ (Finder → «Об этом Mac» → «Хранилище», либо скажи мне —
я приложу машинный разбор по каталогам, он сейчас считается). Освободи хотя бы 50 ГБ, чтобы
запас был неделями, а не днями.

**Шаг 2.** Реши по временным деревьям в `/tmp`: там **около 40 копий репозитория** циклов
#665–#701, примерно **12 ГБ**. Это рабочие деревья прошлых сессий; по правилу их снимает
уборщик деревьев, и без тебя я их не трогаю — в них может лежать недоставленная работа.
Варианты: (а) разрешить мне удалять деревья циклов старше 7 дней, чья работа уже на `origin`
(проверяемо машинно), (б) оставить как есть и чистить руками, (в) починить уборщика, чтобы он
делал это сам.
**Рекомендация — (а) с проверкой «работа на origin».** Она измерима, а не на глаз.

**Шаг 3.** Отдельная задача-починка, её я сделаю сам, если скажешь «да»: у журналов агентов в
`/tmp` **нет ни усечения, ни предела размера**. Один вырос до 7,1 ГБ и в одиночку остановил
запись на всей машине. Правильно — предел на файл и подрезка, иначе это повторится.

## Как понять, что готово

`df -h /` показывает не меньше 50 ГБ свободно, и ни один журнал агента в `/tmp` не больше
500 МБ.

## Что будет после

По шагу 2 (вариант «а») — напишу проверку «работа этого дерева есть на origin» и буду снимать
только подтверждённые, называя каждое снятое дерево в журнале. По шагу 3 — поставлю предел
размера и подрезку журналам агентов, с положительным контролем (тест, который воспроизводит
именно этот случай: журнал растёт, предел срабатывает, запись продолжается). Заводить сторожа
свободного места тоже имеет смысл — сейчас о переполнении не сказал ни один: все 97 артефактов
офиса были «прочитаны», а машина при этом не могла записать байт.
"""


# ── F5: the real disk card fails CLOSED (multi-step section), not 3 buttons ──────
#
# CHANGED (F5, 2026-10-05): this card's section has THREE «Шаг N» blocks (Шаг 1 —
# an owner action, Шаг 2 — the lettered choice, Шаг 3 — a separate yes/no consent).
# Building buttons from Шаг 2's letters alone would have answered only Шаг 2 and
# silently buried Шаг 1/Шаг 3 under a single closing press — a wrong button is a
# wrong owner decision (review F5). The correct, honest outcome is buttonless with
# a NAMED multi-step reason, surfaced to the owner via `has_unparsed_options`
# (which stays True: a choice IS visibly written in the text, we are refusing to
# turn it into a button, not claiming there is no choice).


def test_the_real_disk_card_refuses_buttons_for_a_multi_step_section():
    """Регрессия A5_owner_control.md / F5: before this fix, pressing one letter
    would have recorded an answer for the WHOLE card (3 steps, 1 lettered)."""
    assert od.parse_options(DISK_CARD_BODY) == []


def test_the_real_disk_card_names_the_multi_step_reason():
    mq = od.multi_question(DISK_CARD_BODY)
    assert mq is not None
    assert mq.code == od.MQ_MULTI_STEP
    assert "Шаг" in mq.text or "шаг" in mq.text


def test_the_card_still_tells_the_owner_a_choice_was_written_but_unbuttoned():
    """`has_unparsed_options` must stay True: a letter list IS visibly written in
    the section — we are refusing to button it (wrong question), not claiming
    there was no choice to begin with."""
    assert od.has_unparsed_options(DISK_CARD_BODY) is True


# ── positive control: the SAME lettered mechanism still works for a card with
#    exactly ONE step block (the gate is additive, it does not break the dialect) ──

#: Шаг 2 of the real disk card, ISOLATED (Шаг 1 / Шаг 3 removed) — same letters,
#: same recommendation sentence, same realistic markdown. A single `**Шаг 2.**`
#: marker does not trip the new multi-step gate (only >1 DISTINCT markers do).
DISK_STEP2_ONLY_BODY = """## Что от тебя нужно

**Шаг 2.** Реши по временным деревьям в `/tmp`: там **около 40 копий репозитория** циклов
#665–#701, примерно **12 ГБ**. Это рабочие деревья прошлых сессий; по правилу их снимает
уборщик деревьев, и без тебя я их не трогаю — в них может лежать недоставленная работа.
Варианты: (а) разрешить мне удалять деревья циклов старше 7 дней, чья работа уже на `origin`
(проверяемо машинно), (б) оставить как есть и чистить руками, (в) починить уборщика, чтобы он
делал это сам.
**Рекомендация — (а) с проверкой «работа на origin».** Она измерима, а не на глаз.

## Как понять, что готово
"""


def test_a_single_step_section_still_parses_three_options():
    opts = od.parse_options(DISK_STEP2_ONLY_BODY)
    assert [o.num for o in opts] == ["а", "б", "в"]


def test_the_recommended_option_is_marked_by_the_separate_sentence():
    """«Рекомендация — (а) с проверкой…» — отдельное предложение ПОСЛЕ перечня,
    физически лежащее в хвосте варианта (в) — звезда обязана остаться на (а)."""
    opts = od.parse_options(DISK_STEP2_ONLY_BODY)
    assert [o.recommended for o in opts] == [True, False, False]


def test_option_labels_do_not_bleed_into_the_recommendation_sentence():
    """Подпись варианта (в) не должна унести «Рекомендация — (а) …» в свой текст —
    предложение о рекомендации относится к (а), а не к (в)."""
    opts = od.parse_options(DISK_STEP2_ONLY_BODY)
    assert "Рекомендация" not in opts[2].label
    assert "починить уборщика" in opts[2].label.lower()


def test_the_single_step_card_has_no_unparsed_options():
    assert od.has_unparsed_options(DISK_STEP2_ONLY_BODY) is False


def test_buttons_build_with_markdown_stripped_and_cut_at_a_word_boundary():
    """Подписи кнопок не несут ни `` ` `` / `**`, ни заезда ссылкой, и обрыв — по
    границе слова с многоточием, а не посреди слова."""
    opts = od.parse_options(DISK_STEP2_ONLY_BODY)
    kb = od.build_keyboard("abc12345", opts)
    labels = [row[0]["text"] for row in kb["inline_keyboard"][:-1]]  # без «Подробнее»
    assert len(labels) == 3
    for label in labels:
        assert "`" not in label
        assert "**" not in label
        assert "[" not in label and "](" not in label
        if label.endswith("…"):
            # Многоточие — после ПРОБЕЛА (граница слова), не посреди слова.
            assert not label[:-1].rstrip()[-1:].isalnum() or " " in label


def test_full_option_text_survives_in_the_message_body_even_when_the_button_is_cut():
    """Короткая подпись кнопки — не единственная копия варианта: полный текст едет
    в текст сообщения (§2.4), кнопка — только навигация."""
    opts = od.parse_options(DISK_STEP2_ONLY_BODY)
    text = od.build_message("Диск забит", DISK_STEP2_ONLY_BODY, opts,
                            card_name="owner-decision-disk")
    assert "удалять деревья циклов старше 7 дней" in text


# ── F5: the real depeg card (ingested) — a letterless mandatory step and the
#    lettered sub-question get MERGED into one paragraph by `_paragraphs` itself
#    (no blank line between the two bullet items in the source), so `len(inline_
#    hits) == 1` alone cannot see the second ask; the raw-line step-marker count
#    must. Copied READ-ONLY from the prod tracker (`~/Documents/SPA_Claude/
#    nimbalyst-local/tracker/owner-decision-monitor-depega-steiblov-slep-net-
#    istochn.md`), body text only, byte-for-byte. ──────────────────────────────

DEPEG_CARD_BODY = """## Что от тебя нужно
Реши, разрешаешь ли починку (я не двигаю risk-логику без твоего «да»). Два шага:

- **Шаг 1 (обязательный, безопасный):** перестать выдумывать $1.00. Нет цены → статус `UNKNOWN`
  («цена неизвестна», честно показываем «не проверено»), но БЕЗ ложной тревоги — `UNKNOWN` НЕ
  считается «CRITICAL», значит стоп-кран от него НЕ сработает. Просто перестаём врать, что всё ок.
- **Шаг 2 (чтобы монитор реально работал):** подключить настоящий источник цены стейблов. Варианты:
  (а) он-чейн оракул (Chainlink) — самый надёжный; (б) DeFiLlama/CoinGecko цена стейбла — проще,
  но менее строго. **Рекомендация:** сделать Шаг 1 сейчас (честный `UNKNOWN`, ложных сработок нет),
  а как источник — начать с DeFiLlama (у нас уже есть его фид), позже усилить до он-чейн-оракула.

Ответь: «делай оба шага, источник DeFiLlama» — или укажи свой источник / отложи.

## Как понять, что готово
"""


def test_the_real_depeg_card_refuses_buttons_even_when_steps_merge_into_one_paragraph():
    """Before this fix, Шаг 1 and Шаг 2 (no blank line between the two bullets)
    merged into ONE paragraph, `len(inline_hits) == 1`, and the (а)/(б) source
    choice became the WHOLE card's buttons — Шаг 1 (and the overall yes/no
    consent) would have been answered by the same press."""
    assert od.parse_options(DEPEG_CARD_BODY) == []
    mq = od.multi_question(DEPEG_CARD_BODY)
    assert mq is not None
    assert mq.code == od.MQ_MULTI_STEP


# ── контроль: перенос строки редактором не рвёт перечень ─────────────────────────
def test_the_inline_dialect_survives_a_line_wrap_inside_the_marker_group():
    """Авария ровно в этом: «(а)» на одной физической строке, «(б)(в)» — на
    следующей (так лежит текст живой карточки на диске)."""
    body = (
        "## Что от тебя нужно\n\n"
        "Варианты: (а) первый вариант текста,\n"
        "(б) второй вариант текста, (в) третий вариант текста.\n"
    )
    opts = od.parse_options(body)
    assert [o.num for o in opts] == ["а", "б", "в"]
    assert opts[0].label == "первый вариант текста"


def test_two_separate_inline_lettered_paragraphs_are_a_multi_question_refusal():
    """Перечень «(а)(б)» встречается в ДВУХ разных абзацах — два независимых
    решения, кнопки смешали бы ответы (fail-CLOSED, как у дубля номера).

    Причина уходит через `multi_question`, а не `has_unparsed_options`: последний
    устроен ПОСТРОЧНО и не обязан узнавать комма-разделённый перечень ВНУТРИ
    предложения как «след перечисленного выбора» — это отдельная, более узкая мера,
    которую `multi_question` не делит (см. докстринг `_parse_options_measured`)."""
    body = (
        "## Что от тебя нужно\n\n"
        "Решение 1: (а) первое, (б) второе.\n\n"
        "Решение 2: (а) третье, (б) четвёртое.\n"
    )
    assert od.parse_options(body) == []
    mq = od.multi_question(body)
    assert mq is not None
    assert "абзац" in mq.text


def test_a_lone_paren_letter_in_prose_is_not_mistaken_for_a_list():
    """Одиночная «(а)» без продолжения алфавита — ссылка на пункт договора, не
    перечень (нужно хотя бы два ПОДРЯД, начиная с (а))."""
    body = "## Что от тебя нужно\n\nСм. пункт (а) договора и реши, продлевать ли его.\n"
    assert od.parse_options(body) == []


def test_letters_must_start_at_a_to_count_as_a_list():
    """«(б) …, (в) …» без (а) впереди — не перечень: решётка начинается с первой
    буквы алфавита, иначе порядок объявления не доказан."""
    body = "## Что от тебя нужно\n\nВарианты: (б) один, (в) другой.\n"
    assert od.parse_options(body) == []
