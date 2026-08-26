#!/usr/bin/env python3
"""Карточка пишет варианты формой «**1 — подпись**» — читается ли это как выбор.

Авария, которую воспроизводят тесты ниже, — живая и датированная. 24.08 шаг 0-офис цикла
#368 напечатал: «1 вопрос владельцу ждёт ответа БЕЗ КНОПОК — ответить с телефона нельзя»,
и сам же назвал причину — `own_door_no_options`: «наша дверь, вариантов в журнале нет —
чинить РАЗБОР карточки». Карточка (`owner-decision-ezhednevnuyu-proverku-analitiki-nekomu-g`,
`needs-owner`, создана накануне циклом #367) предлагала владельцу три варианта, а замер
показывал расхождение сторожа и разбора:

    looks_like_a_choice  -> True     # выбор в карточке ЕСТЬ
    has_unparsed_options -> True     # сторож его видит
    parse_options        -> []       # разбор — нет

Каждый тест здесь — либо эта авария, либо граница, за которую разбору ходить нельзя
(ADR-075: выдумывать владельцу выбор запрещено). Время в тестах не участвует: предмет —
текст карточки, дат в нём нет.
"""
from __future__ import annotations

import pytest

from spa_core.telegram.owner_decisions import (
    build_keyboard,
    has_unparsed_options,
    multi_question,
    parse_options,
)


def _card(section: str) -> str:
    """Карточка формата §2.4 с подставленной секцией «Что от тебя нужно»."""
    return (
        "---\ntrackerStatus:\n  type: owner-decision\n"
        "title: Тестовая карточка\nstatus: needs-owner\n---\n\n"
        "## Что случилось и почему это важно\n\nНеважно.\n\n"
        "## Что от тебя нужно\n\n" + section + "\n\n"
        "## Как понять, что готово\n\nТы ответил номером.\n\n"
        "## Что будет после\n\nИсполняю.\n"
    )


# ── дословный кусок живой карточки (положительный контроль аварии) ───────────
#
# Скопирован из `nimbalyst-local/tracker/owner-decision-ezhednevnuyu-proverku-analitiki-
# nekomu-g.md` — включая перенос строк по ширине и пометку «(рекомендую)» ПОСЛЕ жирного,
# то есть ровно то, обо что разбор и споткнулся.
LIVE_SECTION = """Выбери, кто будет гонять эту проверку каждый день, и ответь номером:

**1 — завести отдельного агента** (рекомендую). Отдельная фоновая задача на Маке раз в сутки:
делает временную копию репозитория, гоняет проверку там, кладёт результат и уходит. Живое
состояние не трогает вообще. Минус: это новый постоянный процесс на машине (сейчас их 83), и
это ДЕПЛОЙ — без твоего слова я такое не делаю.

**2 — вписать шагом в протокол оркестратора.** Прогон проверки становится обязательным пунктом
цикла, как чтение офиса. Дешевле (нового процесса не появляется), но надёжность ниже: если
циклы не идут — не идёт и проверка, а именно это и случилось 07–20 августа.

**3 — оставить как есть.** Сторож будет честно краснеть, что проверка не ежедневная, а гонять
её будем «когда дойдут руки». Тогда красный станет постоянным фоном — а фон, как мы уже знаем,
перестают читать."""


class TestTheLiveAccident:
    """Та самая карточка, из-за которой владелец не мог ответить нажатием."""

    def test_all_three_options_are_read(self):
        opts = parse_options(_card(LIVE_SECTION))
        assert [o.num for o in opts] == ["1", "2", "3"]
        assert opts[0].label == "завести отдельного агента"
        assert opts[1].label == "вписать шагом в протокол оркестратора"
        assert opts[2].label == "оставить как есть"

    def test_the_star_goes_to_the_option_the_card_recommends(self):
        """Пометка стоит в хвосте ТОЙ ЖЕ строки, а не в продолжении абзаца.

        Обратный контроль тут же: звезда ровно одна и ровно у первого — подсказка в
        другую сторону дороже отсутствующей.
        """
        opts = parse_options(_card(LIVE_SECTION))
        assert [o.recommended for o in opts] == [True, False, False]

    def test_the_guard_and_the_parser_now_agree(self):
        """Расхождение сторожа с разбором и есть «варианты есть, кнопок нет»."""
        body = _card(LIVE_SECTION)
        assert parse_options(body)
        assert has_unparsed_options(body) is False

    def test_the_owner_gets_three_buttons(self):
        """Дальше по пути — клавиатура: разбор без кнопок владельцу ничего не даёт."""
        kb = build_keyboard("pid1", parse_options(_card(LIVE_SECTION)))
        flat = [b for row in kb["inline_keyboard"] for b in row]
        choices = [b["callback_data"] for b in flat]
        assert sum(c.endswith(":1") for c in choices) == 1
        assert sum(c.endswith(":2") for c in choices) == 1
        assert sum(c.endswith(":3") for c in choices) == 1
        assert any("⭐" in b["text"] for b in flat)


class TestSeparatorForms:
    """Разделитель обязателен, но каким именно он написан — оформление."""

    @pytest.mark.parametrize("sep", ["—", "–", "-", ":", "."])
    def test_every_written_separator_is_accepted(self, sep):
        section = (f"**1{sep} Первый шаг**\n\nПояснение.\n\n"
                   f"**2{sep} Второй шаг**\n\nПояснение.")
        opts = parse_options(_card(section))
        assert [(o.num, o.label) for o in opts] == [("1", "Первый шаг"), ("2", "Второй шаг")]

    def test_a_bold_line_without_a_separator_is_not_an_option(self):
        """Голое «- **Текст**» по-прежнему НЕ вариант (ADR-075) — метки перечня нет."""
        section = ("Выбери, как поступаем:\n\n"
                   "- **Оставить как есть**\n"
                   "- **Переделать целиком**")
        assert parse_options(_card(section)) == []


class TestTheParserDoesNotInventAChoice:
    """Границы формы. Каждая — не придирка, а цена ложной кнопки."""

    def test_bold_prose_starting_with_a_number_range_is_not_an_option(self):
        """«**10 — 20 % годовых**» — это диапазон в прозе, а не вариант номер 10."""
        section = ("Реши, годится ли такая доходность.\n\n"
                   "**10 — 20 % годовых** — вот на что мы рассчитываем.")
        assert parse_options(_card(section)) == []

    def test_a_percent_after_the_number_breaks_the_marker(self):
        section = "**5 % — доля кэша** остаётся неизменной."
        assert parse_options(_card(section)) == []

    def test_a_year_is_not_a_marker(self):
        section = "**2026 — год перехода** на реальные деньги."
        assert parse_options(_card(section)) == []

    def test_the_templates_step_form_is_not_a_choice(self):
        """«**Шаг 1. …**» — ПОШАГОВАЯ инструкция §2.4, а не варианты.

        Это и есть граница между «предложили выбор» и «дали поручение»: у поручения
        кнопки другие («Принято» / «Не надо»), и подменить их кнопками «1/2/3» значило бы
        спросить владельца о выборе, которого карточка не предлагала. Метка формы —
        цифра СРАЗУ за `**`, поэтому слово «Шаг» её и разводит. Замер по обоим живым
        корпусам (156 карточек `origin/main` b83096bbc и 184 в прод-дереве): жирная
        метка-цифра встречается ровно в двух карточках, и обе — перечни, не шаги.
        """
        section = ("Сделай по шагам:\n\n"
                   "**Шаг 1. Прогнать приёмку.** Командой из правила.\n\n"
                   "**Шаг 2. Перезапустить агента.** И сверить коды выхода.")
        assert parse_options(_card(section)) == []

    def test_a_label_that_starts_with_a_digit_is_refused_not_guessed(self):
        """Осознанная цена ограничения: отказ, а не подмена.

        Отказ виден владельцу (`has_unparsed_options` скажет «варианты есть, кнопок
        собрать не смог»), выдуманная кнопка — нет.
        """
        section = ("Выбери срок:\n\n"
                   "**1 — 3 месяца подождать**\n\n"
                   "**2 — 6 месяцев подождать**")
        assert parse_options(_card(section)) == []


class TestPartialListIsRefusedWholesale:
    """Взяли не все написанные пункты ⇒ не берём ни одного.

    Форма — дословно из живой `own-21-agent-cleanup-decisions` («реши по каждому»,
    четыре НЕЗАВИСИМЫХ вопроса). Подпись второго начинается с обратной кавычки, три
    остальных — с буквы: без этого правила владелец получил бы ТРИ кнопки на ЧЕТЫРЕ
    вопроса, нажал бы одну — и карточка закрылась бы, похоронив остальные.
    """

    SECTION = ("(реши по каждому)\n\n"
               "**1. Три RETIRED-агента загружены вопреки статусу** — `digest_weekly`.\n"
               "→ Рекомендую: **выгрузить**.\n\n"
               "**2. `novel-edge-rnd`** — автономная Claude-R&D-задача.\n"
               "→ Рекомендую: **переподчинить новому протоколу**.\n\n"
               "**3. Автономный roadmap-loop** — остановлен.\n"
               "→ Рекомендую: **не возобновлять как есть**.\n\n"
               "**4. Агенты «НЕПОНЯТНО»** — нужна твоя ясность.\n"
               "→ Рекомендую: по каждому скажи «важен» / «в утиль».")

    def test_a_partially_readable_list_gives_no_buttons_at_all(self):
        assert parse_options(_card(self.SECTION)) == []

    def test_and_the_owner_is_told_the_options_are_there(self):
        """Отказ обязан быть НАЗВАН: «выбора не предлагали» здесь было бы враньём."""
        assert has_unparsed_options(_card(self.SECTION)) is True

    def test_the_refusal_is_not_dressed_up_as_several_questions(self):
        """«Разобрал не всё» и «вопросов несколько» — разные диагнозы.

        Подменить первый вторым значит назвать владельцу не ту причину и отправить
        сессию чинить не то.
        """
        assert multi_question(_card(self.SECTION)) is None

    def test_the_same_list_read_whole_does_give_buttons(self):
        """Обратный контроль: правило ловит НЕПОЛНОТУ, а не саму форму."""
        section = self.SECTION.replace("**2. `novel-edge-rnd`**",
                                       "**2. Автономная R&D-задача**")
        assert [o.num for o in parse_options(_card(section))] == ["1", "2", "3", "4"]


class TestStepsInsideAnOptionAreNotOptions:
    """Диалект ЯВНЫЙ — значит голые «1.»/«2.» внутри абзаца остаются шагами.

    Без этого разбор поймал бы дубль номера, объявил «вопросов несколько» и потерял
    кнопки у ВСЕЙ карточки — авария цикла #338, только другим входом.
    """

    def test_a_numbered_recipe_inside_the_first_option_changes_nothing(self):
        section = ("Выбери:\n\n"
                   "**1 — починить сейчас**. Порядок такой:\n"
                   "1. прогнать приёмку;\n"
                   "2. переустановить агента.\n\n"
                   "**2 — отложить до следующего цикла**.")
        opts = parse_options(_card(section))
        assert [(o.num, o.label) for o in opts] == [
            ("1", "починить сейчас"), ("2", "отложить до следующего цикла")]


class TestRecommendationInTheSameLineTail:
    """Пометка живёт за жирной головкой — и знак у неё бывает обратный."""

    def test_a_negated_mark_gives_no_star_to_anyone(self):
        section = ("Выбери:\n\n"
                   "**1 — снести панель** (не рекомендую). Данные пропадут.\n\n"
                   "**2 — оставить панель**. Ничего не меняется.")
        opts = parse_options(_card(section))
        assert [o.recommended for o in opts] == [False, False]

    def test_the_mark_belongs_to_its_own_option_only(self):
        section = ("Выбери:\n\n"
                   "**1 — снести панель**. Данные пропадут.\n\n"
                   "**2 — оставить панель** (рекомендую). Ничего не меняется.")
        opts = parse_options(_card(section))
        assert [o.recommended for o in opts] == [False, True]


class TestTheSectionStillBounds:
    """Секция «Что будет после» вариантов не даёт — правило старое, не ослаблено."""

    def test_bold_numeric_lines_outside_the_need_section_are_ignored(self):
        body = (
            "---\ntrackerStatus:\n  type: owner-decision\n"
            "title: Тест\nstatus: needs-owner\n---\n\n"
            "## Что от тебя нужно\n\nОтветь словами, вариантов нет.\n\n"
            "## Что будет после\n\n"
            "**1 — готовлю агента** по обычному порядку.\n\n"
            "**2 — вписываю шаг в протокол**.\n"
        )
        assert parse_options(body) == []
