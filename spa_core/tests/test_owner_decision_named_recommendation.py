"""Звезда рекомендации обязана стоять на том варианте, который автор НАЗВАЛ.

Авария 2026-08-08 (цикл #168, замерена на живой карточке
``owner-decision-geit-i-allokator-schitayut-zhivoi-tvl-po``): рекомендация написана
ОТДЕЛЬНЫМ абзацем после перечня — «**Рекомендация агента — вариант 1.**». Физически такой
абзац лежит в хвосте ПОСЛЕДНЕГО варианта, а звезда ставилась по расположению абзаца ⇒
владельцу уходило «⭐ рекомендую» на варианте **3**, то есть ровно на том, который автор
не советовал.

Почему это не косметика: с ADR-075 владелец отвечает КНОПКОЙ, и здесь кнопка двигает
money-path (вход гейта RiskPolicy). Перевёрнутая подсказка — это не «съехало оформление»,
а совет в обратную сторону, выданный от имени агента.

Каждый тест ниже — положительный контроль: на коде до починки краснеет.
Контроль в обратную сторону обязателен и он здесь есть: звезда, честно стоящая внутри
своего абзаца, и карточка вообще без рекомендации ведут себя по-прежнему.
"""
from __future__ import annotations

from spa_core.telegram.owner_decisions import parse_options


def _card(need: str) -> str:
    return (
        "## Что случилось и почему это важно\n\nНеважно.\n\n"
        "## Что от тебя нужно\n\n" + need + "\n\n"
        "## Как понять, что готово\n\nОдна строка.\n\n"
        "## Что будет после\n\nЧто-нибудь.\n"
    )


LIVE_08_08 = _card(
    "Выбрать, каким становится ЕДИНОЕ определение. Варианты:\n\n"
    "1. **Гейт узнаёт про закреплённые наблюдения** — то, что аллокатор уже умеет.\n"
    "2. **Аллокатор перестаёт повышать TVL по наблюдению** — определение тоже одно.\n"
    "3. **Оставить как есть, но перестать врать в отчёте** — код не трогаем.\n"
    "   Самое дешёвое и безопасное, но настоящая причина простоя останется.\n\n"
    "**Рекомендация агента — вариант 1.** Он единственный, который и убирает противоречие,\n"
    "и работает в сторону цели «деньги не должны стоять»."
)


def _stars(body: str):
    return {o.num for o in parse_options(body) if o.recommended}


def test_live_card_0808_stars_the_named_option_not_the_last_paragraph():
    """Замер аварии дословно: звезда обязана быть на 1, а не на 3."""
    opts = parse_options(LIVE_08_08)
    assert [o.num for o in opts] == ["1", "2", "3"], opts
    assert _stars(LIVE_08_08) == {"1"}


def test_the_wrongly_starred_option_is_not_starred_anymore():
    """Отдельно и прямо: вариант 3 (тот, что уезжал владельцу) звезды НЕ несёт."""
    assert all(not o.recommended for o in parse_options(LIVE_08_08) if o.num == "3")


def test_named_recommendation_wins_over_paragraph_position():
    """Даже когда советующая фраза стоит в абзаце ДРУГОГО варианта — решает НОМЕР."""
    body = _card(
        "1. **Сделать А** — быстро.\n"
        "2. **Сделать Б** — долго.\n"
        "   Здесь длинный разбор. Рекомендую вариант 1, потому что дешевле.\n"
    )
    assert _stars(body) == {"1"}


def test_reverse_order_phrasing_is_understood():
    body = _card(
        "1. **Сделать А** — быстро.\n"
        "2. **Сделать Б** — долго.\n\n"
        "Вариант 2 — рекомендую: он единственный закрывает причину.\n"
    )
    assert _stars(body) == {"2"}


def test_two_different_numbers_named_leave_nobody_starred():
    """Спорная формулировка ⇒ подсказки нет. Кнопки при этом остаются — выбор за владельцем."""
    body = _card(
        "1. **Сделать А**.\n"
        "2. **Сделать Б**.\n\n"
        "Рекомендую вариант 1. Хотя по деньгам рекомендую вариант 2.\n"
    )
    opts = parse_options(body)
    assert [o.num for o in opts] == ["1", "2"]
    assert _stars(body) == set()


def test_negated_recommendation_never_becomes_a_star():
    """«Не рекомендую вариант 2» — совет ПРОТИВ. Прочитать его как «за» было бы худшим
    из возможных исходов, поэтому звезды нет ни у кого (fail-CLOSED)."""
    body = _card(
        "1. **Сделать А**.\n"
        "2. **Сделать Б**.\n\n"
        "Не рекомендую вариант 2 — он отменяет уже принятое решение.\n"
    )
    assert [o.num for o in parse_options(body)] == ["1", "2"]
    assert _stars(body) == set()


def test_named_number_absent_from_the_list_leaves_nobody_starred():
    body = _card(
        "1. **Сделать А**.\n"
        "2. **Сделать Б**.\n\n"
        "Рекомендую вариант 5.\n"
    )
    assert _stars(body) == set()


# ── контроль в обратную сторону: прежнее поведение не тронуто ────────────────


def test_star_inside_its_own_paragraph_still_works():
    """Ничего не названо номером — звезда по-прежнему берётся из абзаца варианта."""
    body = _card(
        "1. **Сделать А** — быстро.\n"
        "2. **Сделать Б** — долго.\n"
        "   ⭐ Рекомендация агента: так честнее.\n"
    )
    assert _stars(body) == {"2"}


def test_marker_in_the_option_header_still_works():
    body = _card(
        "1. **Сделать А (рекомендую)** — быстро.\n"
        "2. **Сделать Б** — долго.\n"
    )
    assert _stars(body) == {"1"}


def test_card_without_any_recommendation_stays_without_a_star():
    body = _card("1. **Сделать А**.\n2. **Сделать Б**.\n")
    assert [o.num for o in parse_options(body)] == ["1", "2"]
    assert _stars(body) == set()


def test_the_live_card_on_disk_is_the_one_that_was_measured():
    """Проводка, а не только разбор строки: берём НАСТОЯЩИЙ файл карточки из трекера.

    Если карточку однажды перепишут так, что рекомендация перестанет называть номер,
    этот тест скажет об этом вслух, а не промолчит.
    """
    from pathlib import Path

    p = (Path(__file__).resolve().parents[2] / "nimbalyst-local" / "tracker"
         / "owner-decision-geit-i-allokator-schitayut-zhivoi-tvl-po.md")
    if not p.exists():   # карточка живёт своей жизнью (могла быть отвечена и уехать)
        return
    body = p.read_text(encoding="utf-8")
    opts = parse_options(body)
    assert opts, "у живой карточки перестали читаться варианты"
    assert {o.num for o in opts if o.recommended} == {"1"}, [
        (o.num, o.recommended) for o in opts]
