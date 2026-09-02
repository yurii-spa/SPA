"""Две рекомендации в одном вопросе владельцу — и ни одну машина выбрать НЕ ВПРАВЕ.

КАЖДЫЙ тест — положительный контроль состояния, ИЗМЕРЕННОГО 2026-09-02 (цикл #461) на
живой `owner-decision-knigu-perekladyvayut-22-raza-za-nedelyu-2026-08-29` (`needs-owner`
с 29.08, четвёртый день без ответа, `priority: high`, блокирует честность 30-дневного
трека). В карточке ДВЕ рекомендации, и они противоречат друг другу:

* разметкой — `*(рекомендую)*` на «Варианте 1 — Сначала выяснить причину»;
* прозой — раздел «ПЕРЕСМОТР РЕКОМЕНДАЦИИ», который первую ДОСЛОВНО отменяет:
  «Посчитал — совет был осторожен не там… **Новая рекомендация: ставить ограничение
  сразу, а причину выяснять параллельно.**» (асимметрия 14 к 1 по деньгам).

И ровно этого раздела владелец НЕ ВИДИТ: бот шлёт из прод-дерева, где копия карточки
140 строк против 192 на `origin/main` — недостаёт 52 строки, все они и есть пересмотр.
Догнать автосинком нельзя по построению: `nimbalyst-local/` не возит НИКАКОЙ синк
(CLAUDE.md §1), то есть расхождение не «ещё не доехало», а не доедет.

**Чего здесь намеренно НЕТ — починки «подобрать номер» и починки «переписать копию».**
Новая рекомендация номера варианта не называет вовсе; подобрать его за автора значит
выдумать владельцу выбор (ADR-075). Переписать живую копию под origin значит подменить
вопрос задним числом, когда кнопки уже на руках (инвариант #14, авария 30–31.08).
Единственный честный исход — НАЗВАТЬ оба состояния словами, и закреплён именно он.

Обратные контроли обязательны и стоят рядом с каждым положительным: карточка с ОДНОЙ
рекомендацией, привязанной к номеру, лишней строки получить не должна — иначе оговорка
появится под каждым вопросом и обесценит сама себя.

Время и живость — входы; литеральных дат и литеральных pid здесь нет.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from spa_core.owner_queue import origin_view
from spa_core.telegram import owner_decisions as od

REF = "main"

#: Перечень ИЗ ЖИВОЙ карточки, дословно — вместе с последней строкой, из-за которой
#: `parse_options` возвращает НОЛЬ вариантов. Отказ там ВЕРНЫЙ: «варианты не исключают
#: друг друга» — кнопкой этого не выразить, одно нажатие закрыло бы карточку и молча
#: похоронило остальные пункты. Фикстура несёт эту строку не для красоты: без неё
#: варианты разбираются, премиса «вариантов нет НИГДЕ» исчезает, и часть 2 проверяла бы
#: не то состояние, которое измерено на живой карточке.
_LIVE_OPTIONS = (
    "## Что от тебя нужно\n\n"
    "**Вариант 1 — Сначала выяснить причину** *(рекомендую)*\n"
    "Замерить, сколько раз в сутки реально исполняется цикл.\n\n"
    "**Вариант 2 — Сразу поставить бюджет оборота на живой путь**\n"
    "Перенести потолок ADR-060 с теневого канала на настоящий.\n\n"
    "Варианты не исключают друг друга: 1 → потом 2 и/или 3.\n"
)
#: Раздел пересмотра — то, чего в прод-копии нет.
_REVISION = (
    "## ПЕРЕСМОТР РЕКОМЕНДАЦИИ (поздний вечер)\n\n"
    "Я советовал «сначала выясни причину, потом ограничивай». **Посчитал — совет был\n"
    "осторожен не там.**\n\n"
    "**Новая рекомендация: ставить ограничение сразу, а причину выяснять параллельно.**\n"
)
_HEAD = "## Что случилось и почему это важно\n\nКнигу перекладывают 22 раза за неделю.\n\n"

BODY_WITH_REVISION = _HEAD + _REVISION + "\n" + _LIVE_OPTIONS
BODY_STALE = _HEAD + _LIVE_OPTIONS


# ===========================================================================
# ЧАСТЬ 1 — рекомендация ПРОЗОЙ, не привязанная к номеру
# ===========================================================================
def test_prose_recommendation_without_a_number_is_named():
    """Ядро аварии: пересмотр есть, номера в нём нет — обязаны сказать словами."""
    found = od.unnumbered_recommendations(BODY_WITH_REVISION)

    assert len(found) == 1, found
    assert "ставить ограничение сразу" in found[0]


def test_the_named_recommendation_reaches_the_owner_message():
    """Проводка, а не только деталь: строка обязана дойти до ТЕКСТА, который уедет."""
    text = od.build_message("Книгу перекладывают", BODY_WITH_REVISION,
                            od.parse_options(BODY_WITH_REVISION),
                            has_buttons=False, card_name="own.md")

    assert "не привязанная к номеру варианта" in text
    assert "ставить ограничение сразу" in text
    # Номер за автора НЕ подобран — иначе это выдуманный владельцу выбор (ADR-075).
    assert "рекомендую вариант" not in text.lower()


def test_a_section_heading_alone_is_not_a_recommendation():
    """«## ПЕРЕСМОТР РЕКОМЕНДАЦИИ» — оглавление раздела: совета в нём не сказано."""
    only_heading = _HEAD + "## ПЕРЕСМОТР РЕКОМЕНДАЦИИ (поздний вечер)\n\nТекст.\n\n" + _LIVE_OPTIONS

    assert od.unnumbered_recommendations(only_heading) == []


def test_a_heading_that_IS_a_declaration_is_still_caught():
    """Обратная сторона предыдущего — и причина, по которой отсев идёт НЕ по «#».

    Живая форма (`owner-decision-kritichnaya-nahodka-petli-*`, четыре карточки):
    «**Рекомендация: закрыть без действий**». Стой она заголовком — это по-прежнему
    совет, и ронять его молча значило бы завести ту же дыру с другой стороны.
    Первая редакция отсекала заголовки отдельным условием; мутация, снявшая его, не
    покрасила НИ ОДНОГО теста, а замер по 879 карточкам дал те же 10 попаданий —
    условие было мёртвым, и снято оно намеренно.
    """
    as_heading = _HEAD + "## Рекомендация: закрыть без действий\n\nТекст.\n\n" + _LIVE_OPTIONS

    assert od.unnumbered_recommendations(as_heading) == ["## Рекомендация: закрыть без действий"]


# ── Обратные контроли: молчание там, где сказать нечего ──────────────────────────
def test_a_single_recommendation_bound_to_a_number_says_nothing_extra():
    """Обычная карточка. Лишняя строка под КАЖДЫМ вопросом обесценила бы оговорку."""
    body = (_HEAD + "## Что от тебя нужно\n\n"
            "* **Вариант 1 (рекомендую) — сделать так.** Пояснение.\n"
            "* **Вариант 2 — не делать.** Пояснение.\n")

    assert od.unnumbered_recommendations(body) == []
    text = od.build_message("t", body, od.parse_options(body), card_name="c.md")
    assert "не привязанная к номеру" not in text


def test_prose_recommendation_that_does_name_its_option_is_left_to_the_other_hand():
    """«Рекомендация: вариант 2» — забота `_named_recommendation`, не наша.

    Иначе один и тот же совет предъявлялся бы владельцу дважды: звездой и оговоркой.
    """
    body = _HEAD + "**Рекомендация: вариант 2.**\n\n" + _LIVE_OPTIONS

    assert od.unnumbered_recommendations(body) == []


def test_letter_and_digit_references_in_prose_count_as_a_named_option():
    """Живая форма `agent-*`-карточек: «Рекомендация: (1) + (3)» — номера названы."""
    body = _HEAD + "**Рекомендация: (1) + (3)** — оба про один корень.\n\n" + _LIVE_OPTIONS

    assert od.unnumbered_recommendations(body) == []


def test_a_negated_recommendation_never_becomes_a_notice():
    """Отрицание сильнее — тот же приём, что в `_marks_recommendation` (fail-CLOSED).

    Строка несёт И декларацию, И отрицание: за такую поручиться нельзя, и молчание тут
    дешевле подсказки в неизвестную сторону. Первая редакция теста брала «Так я делать
    не рекомендую», где декларация не срабатывала ВООБЩЕ, — мутация, снявшая проверку
    отрицания, не покрасила его: тест проходил по постороннему поводу.
    """
    body = _HEAD + "**Рекомендация: закрыть.** Обратного я не рекомендую.\n\n" + _LIVE_OPTIONS

    assert od.unnumbered_recommendations(body) == []


def test_a_recommendation_inside_the_options_section_is_not_counted_twice():
    """Пометку внутри пункта читает `_marks_recommendation`. Вторая рука — дубль.

    Строка выбрана так, что ДЕКЛАРАЦИЯ в ней срабатывает: единственное, что её
    отсеивает, — принадлежность к перечню. Первая редакция брала «…** Рекомендую:
    дешевле.» одной строкой, где декларация не срабатывала вовсе, и мутация, снявшая
    исключение секции, проходила молча.
    """
    body = (_HEAD + "## Что от тебя нужно\n\n"
            "* **Вариант 1 — сделать так.**\n"
            "  Рекомендую: так дешевле.\n"
            "* **Вариант 2 — не делать.** Пояснение.\n")

    # Премиса: вне секции ровно эта строка НАШЛАСЬ БЫ — значит отсеивает её секция.
    assert od.unnumbered_recommendations(_HEAD + "  Рекомендую: так дешевле.\n")
    assert od.unnumbered_recommendations(body) == []


# ===========================================================================
# ЧАСТЬ 2 — тело живой копии расходится с origin, а вариантов нет ни там, ни тут
# ===========================================================================
def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card_text(body: str, *, status: str = "needs-owner", answer: bool = False) -> str:
    head = ["---", "trackerStatus:", "  type: owner-decision",
            'title: "Книгу перекладывают 22 раза за неделю"', f"status: {status}"]
    if answer:
        head += ["owner_choice: '1'", "owner_answered_at: '2030-01-01T00:00:00+00:00'",
                 "owner_answer_via: telegram", "owner_answered_by: owner"]
    return "\n".join(head) + "\n---\n\n" + body


@pytest.fixture()
def repo(tmp_path):
    """Настоящий крошечный git-репозиторий: проверяем ЭФФЕКТ на git, не заглушку."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _diverged(repo: Path, *, live_status="needs-owner", live_answer=False,
              live_body=BODY_STALE) -> Path:
    """Ровно состояние живой карточки: на ref тело ДЛИННЕЕ, вариантов нет НИГДЕ."""
    card = repo / origin_view.TRACKER_REL / "own-churn.md"
    card.write_text(_card_text(BODY_WITH_REVISION), encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "c")
    card.write_text(_card_text(live_body, status=live_status, answer=live_answer),
                    encoding="utf-8")
    return card


def test_body_divergence_is_not_reported_as_nothing_to_update(repo):
    """Ядро: вариантов ноль и там и тут, а тело на ref длиннее — прежний вердикт ЛГАЛ.

    До починки здесь стоял `not_stale` с текстом «ref не богаче, обновлять нечего» —
    утверждение о состоянии, которое сторож сам же и измерил, и оно было ложным.
    """
    card = _diverged(repo)
    # Премиса, ради которой фикстура и списана с живой карточки дословно: вариантов
    # НЕТ НИ ЗДЕСЬ, НИ НА REF — единственное состояние, в котором старый прокси
    # (число разобранных вариантов) объявлял «обновлять нечего».
    assert od.parse_options(card.read_text(encoding="utf-8")) == []
    assert od.parse_options(_card_text(BODY_WITH_REVISION)) == []

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_BODY_DIVERGED, rep
    assert rep["measured"] is True
    assert rep["lines_only_on_ref"] > 0, rep
    assert "обновлять нечего" not in rep["detail"]


def test_the_diverged_copy_is_never_rewritten(repo):
    """Назвать — да, переписать — нет: кнопки у владельца означают ПРЕЖНИЙ текст."""
    card = _diverged(repo)
    before = card.read_text(encoding="utf-8")

    od.refresh_live_copy_from_ref(card, ref=REF)

    assert card.read_text(encoding="utf-8") == before


def test_a_live_copy_that_is_AHEAD_of_the_ref_is_never_called_stale(repo):
    """Обратный контроль, найденный уже существующим тестом при первой редакции.

    Первая редакция сравнивала тела на «различаются ли», и живая копия, ДОПИСАННАЯ в
    дереве (сессия ещё не запушила), получала оговорку «передо мной не самая свежая
    редакция» — ложь в другую сторону, да ещё и с числом 0 строк. Право на оговорку
    даёт только усечение: на ref есть строки, которых тут нет, а своих нет ни одной.
    """
    card = _diverged(repo, live_body=BODY_WITH_REVISION + "\nДописано в дереве.\n")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_NOT_STALE, rep
    assert "lines_only_on_ref" not in rep


def test_a_live_copy_that_is_a_REWRITE_is_not_called_stale(repo):
    """Не усечение, а другая редакция: строки есть с обеих сторон — судить нам нечем."""
    card = _diverged(repo, live_body=_HEAD + "Совсем другой текст вопроса.\n")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_NOT_STALE, rep


def test_identical_bodies_stay_not_stale(repo):
    """Обратный контроль: копии совпадают ⇒ прежний вердикт и ни слова владельцу."""
    card = _diverged(repo, live_body=BODY_WITH_REVISION)

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_NOT_STALE, rep
    assert "lines_only_on_ref" not in rep


def test_an_owner_answer_still_outranks_the_divergence(repo):
    """Защита #178 не ослаблена ни на строку: след ответа сильнее любого расхождения."""
    card = _diverged(repo, live_answer=True)

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_OWNER_ANSWER, rep


def test_a_closed_question_is_not_reopened_by_the_divergence(repo):
    """Тоже обратный контроль: вопрос уже не на владельце ⇒ сверять нечего."""
    card = _diverged(repo, live_status="ingested")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_STATUS, rep


def test_the_divergence_reaches_the_message_the_owner_would_get(repo, monkeypatch):
    """Проводка до КОНЦА: сухой прогон уведомления обязан нести строку о расхождении.

    Сухой прогон намеренно: он собирает ровно тот текст, что уедет, и не пишет ни в
    живое состояние, ни в чат.
    """
    from spa_core.owner_queue import notify as nf

    card = _diverged(repo)
    real = od.refresh_live_copy_from_ref
    monkeypatch.setattr(od, "refresh_live_copy_from_ref",
                        lambda p, **kw: real(p, ref=REF))

    text = nf.notify_needs_owner(card, dry_run=True)

    assert "НЕ самая свежая редакция" in text
    assert "origin/main" in text
    # И вторая оговорка тоже на месте — прод-копия пересмотра не содержит, но перечень
    # в ней есть, а значит владелец должен узнать, что читать надо не только сообщение.
    assert "Прочитай карточку" in text
