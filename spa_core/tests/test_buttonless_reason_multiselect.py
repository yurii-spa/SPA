"""Многовыборная карточка — своё состояние, а не «мы не прочитали выбор».

КАЖДЫЙ тест — положительный контроль аварии **30.08.2026** (цикл #426):

    обязательный шаг 0-офис и `docs/SYSTEM_BRIEFING.md` каждый цикл печатали
    «2 вопроса владельцу ждут ответа БЕЗ КНОПОК» с причиной
    `unreadable_options_in_card` — «выбор в карточке написан, а разобрать его не
    вышло; **это наш дефект разбора, а не форма вопроса**» — и лекарством
    «научить `parse_options` этой форме».

    Обе карточки (`owner-decision-storozh-vspleskov-apy-nikto-ne-zovet-2026-08-29`,
    `owner-decision-knigu-perekladyvayut-22-raza-za-nedelyu-2026-08-29`) написаны
    безупречно по §2.4 — `**Вариант 1 — …**`, форму разбор знает с цикла #368.
    Пусто он отдаёт НАМЕРЕННО: тело говорит «Варианты не исключают друг друга»,
    то есть пункты берутся ВМЕСТЕ, и одна закрывающая кнопка такой ответ выразить
    не может.

    Цена диагноза была не в молчании, а в лекарстве: исполнить его значило собрать
    три ВЗАИМОИСКЛЮЧАЮЩИЕ кнопки под вопросом, который сам себя называет
    невзаимоисключающим, — выдумать владельцу выбор, которого карточка не
    предлагала (ADR-075), сломав работающий отказ.

Тот же класс, что `multi_question_card` (#359), на одно состояние в сторону:
`multi_question` для многовыборной карточки честно отдаёт ``None`` (разбор вышел
ДО подсчёта пунктов), и провал шёл дальше — в «мы не прочитали».

Фикстуры сверки — настоящие крошечные git-репозитории (без сети). Литеральных дат
нет: время — ВХОД.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.owner_queue import origin_view
from spa_core.telegram import buttonless_reason as br
from spa_core.telegram import owner_decisions as od

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
REF = "main"

#: Списано с ЖИВОЙ карточки `owner-decision-storozh-vspleskov-apy-nikto-ne-zovet-2026-08-29`:
#: безупречный перечень `**Вариант N — …**` ПЛЮС строка «варианты не исключают друг друга».
#: Ровно та форма, на которой сторож звал ломать верный отказ.
_MULTISELECT = (
    "## Что случилось и почему это важно\n\nСторож всплесков написан, но его никто не зовёт.\n\n"
    "## Что от тебя нужно\n\n"
    "**Вариант 1 — Строкой в дневном отчёте, без нового канала** *(рекомендую)*\n"
    "Дешевле и тише, чем заводить ещё один источник сообщений.\n\n"
    "**Вариант 2 — Подключить молча, без сообщений**\n"
    "Пишет находки в файл, ты смотришь, когда захочешь.\n\n"
    "**Вариант 3 — Сначала второй источник цен**\n"
    "Дольше, но именно это закрывает главную дыру.\n\n"
    "Варианты не исключают друг друга: 1 или 2 — сейчас, 3 — отдельной задачей.\n"
)

#: ДВА решения в одной карточке — соседнее состояние (#359). Отказ тоже верен, но
#: лечится ДЕЛЕНИЕМ карточки, и код у него свой.
_TWO_DECISIONS = (
    "## Что случилось и почему это важно\n\nВоронка ведёт в никуда.\n\n"
    "## Что от тебя нужно\n\n"
    "**Решение 1 — судьба чекапа.** Варианты:\n"
    "- **(а) Похоронить.** Признать продукт закрытым.\n"
    "- **(б) Воскресить.** Поднять сервис заново.\n\n"
    "**Решение 2 — канал заявок.** Варианты:\n"
    "- **(а) Телеграм.** Заявки идут в чат.\n"
    "- **(б) Почта.** Заявки идут письмом.\n"
)

#: Выбор НАПИСАН, а формы разбор не знает — единственное состояние, которое
#: действительно лечится кодом. Держит границу с другой стороны.
_UNREADABLE_OPTIONS = (
    "## Что случилось и почему это важно\n\nВоронка ведёт в никуда.\n\n"
    "## Что от тебя нужно\n\n"
    "Варианты:\n\n"
    "— похоронить чекап (рекомендую);\n"
    "— воскресить чекап.\n"
)

#: Выбора нет вовсе: слово «вариант» прозой, без перечня.
_WITHOUT_OPTIONS = (
    "## Что случилось и почему это важно\n\nВоронка ведёт в никуда.\n\n"
    "## Что от тебя нужно\n\n"
    "- Вариант тот же, что вчера — ничего не менять; подтверди словами.\n"
)


def _card_text(body: str, *, status: str = "needs-owner") -> str:
    return ("---\ntrackerStatus:\n  type: owner-decision\n"
            "title: \"Вопрос владельцу\"\n"
            f"status: {status}\n---\n\n{body}")


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с каталогом очереди и веткой-«origin». Сети не касается."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _write(root: Path, name: str, body: str) -> Path:
    p = root / origin_view.TRACKER_REL / f"{name}.md"
    p.write_text(_card_text(body), encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "c")
    return p


def _beacon(tmp_path: Path) -> Path:
    p = tmp_path / "beacon.json"
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": NOW.isoformat(), "pid": 1,
        "capabilities": ["alert_actions"],
    }), encoding="utf-8")
    return p


def _explain(path, tmp_path):
    return br.explain(path, now=NOW, beacon_path=_beacon(tmp_path), ref=REF)


# ===========================================================================
# ФИКСТУРА ВОСПРОИЗВОДИТ ЖИВОЕ СОСТОЯНИЕ, а не похожее на него
# ===========================================================================
def test_fixture_reproduces_the_measured_state_of_both_live_cards():
    """Три числа замера 30.08 на обеих живых карточках — здесь же.

    Без этой проверки положительный контроль ниже мог бы краснеть по ЛЮБОЙ причине
    (иная форма перечня, иной отказ) и выдавать себя за контроль той аварии. Здесь
    закреплено ровно то, что делает состояние собой: выбор РАЗБИРАЕМ по форме,
    вопросов ОДИН, а пусто отдаётся из-за «не исключают друг друга».
    """
    body = _MULTISELECT.split("---", 2)[-1]
    assert od.allows_multiple(body) is True
    assert od.multi_question(body) is None, "вопрос ОДИН — это не многовопросная карточка"
    assert od.parse_options(body) == [], "разбор отдаёт пусто НАМЕРЕННО"
    # Форма перечня разбору известна: убери строку «не исключают друг друга» —
    # и те же три варианта соберутся. Значит отказ вызван НЕ незнанием формы.
    without = body.replace(
        "Варианты не исключают друг друга: 1 или 2 — сейчас, 3 — отдельной задачей.\n", "")
    assert len(od.parse_options(without)) == 3, (
        "если и без строки многовыборности вариантов нет, фикстура проверяет не то")


# ===========================================================================
# ЯДРО АВАРИИ
# ===========================================================================
def test_multiselect_card_is_named_multiselect_not_a_parsing_defect(repo, tmp_path):
    """Положительный контроль аварии 30.08: было `unreadable_options_in_card`."""
    card = _write(repo, "owner-decision-storozh-vspleskov-apy", _MULTISELECT)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_MULTISELECT, reason.text
    assert reason.code != br.CODE_UNREADABLE_OPTIONS
    assert reason.measured


def test_multiselect_remedy_never_sends_anyone_to_teach_the_parser(repo, tmp_path):
    """Лекарство — не «научить `parse_options`»: оно и есть та самая поломка.

    Утверждение о ТЕКСТЕ, а не о коде, потому что вред нанесла именно прочитанная
    человеком строка: исполнив её, следующая сессия собрала бы взаимоисключающие
    кнопки под невзаимоисключающим вопросом (ADR-075).
    """
    card = _write(repo, "owner-decision-knigu-perekladyvayut", _MULTISELECT)

    reason = _explain(card, tmp_path)

    assert "parse_options" not in reason.remedy, reason.remedy
    assert "разбор НЕ трогать" in reason.remedy
    # И причина не выдаёт верный отказ за нашу неисправность.
    assert "дефект разбора" not in reason.text or "дефекта разбора здесь нет" in reason.text


def test_multiselect_is_measured_so_the_office_step_does_not_read_it_as_unknown(
        repo, tmp_path):
    """`measured` истинно: «не измерено» — отдельное состояние, и это не оно."""
    card = _write(repo, "owner-decision-multi", _MULTISELECT)

    assert _explain(card, tmp_path).measured is True


# ===========================================================================
# ОБРАТНЫЕ КОНТРОЛИ: соседние состояния не съедены новой веткой
# ===========================================================================
def test_two_decisions_card_still_reads_as_multi_question(repo, tmp_path):
    """Соседнее состояние #359 — своё имя и своё лекарство (деление карточки)."""
    card = _write(repo, "owner-decision-dva-resheniya", _TWO_DECISIONS)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_MULTI_QUESTION, reason.text
    assert reason.code != br.CODE_MULTISELECT


def test_genuinely_unreadable_options_still_read_as_a_parsing_defect(repo, tmp_path):
    """Ветка не проглотила состояние, которое ДЕЙСТВИТЕЛЬНО лечится кодом.

    Иначе починка одного ложного диагноза сделала бы ложным другой — и настоящий
    дефект разбора перестал бы звать себя починить.
    """
    card = _write(repo, "owner-decision-nechitaemye", _UNREADABLE_OPTIONS)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_UNREADABLE_OPTIONS, reason.text
    assert "parse_options" in reason.remedy


def test_card_without_any_choice_still_reads_as_no_options(repo, tmp_path):
    """Выбора нет вовсе — по-прежнему `no_options_in_card` (ADR-075)."""
    card = _write(repo, "owner-decision-bez-vybora", _WITHOUT_OPTIONS)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_NO_OPTIONS, reason.text


def test_ordinary_exclusive_options_never_reach_this_branch_at_all(repo, tmp_path):
    """Карточка с обычным взаимоисключающим перечнем кнопки ПОЛУЧАЕТ.

    Контроль в обе стороны: новая ветка не должна отбирать кнопки у здоровых
    карточек — она живёт ниже по течению, там, где кнопок нет и без неё.
    """
    body = (
        "## Что случилось и почему это важно\n\nЦикл идёт 52 раза в сутки.\n\n"
        "## Что от тебя нужно\n\n"
        "- **Вариант 1 (⭐ рекомендую) — разрешить метку.** Две строки в настройку.\n"
        "- **Вариант 2 — ничего не менять.** Источник запусков останется неизвестным.\n"
    )
    card = _write(repo, "owner-decision-obychnaya", body)

    reason = _explain(card, tmp_path)

    assert reason.code not in (br.CODE_MULTISELECT, br.CODE_UNREADABLE_OPTIONS,
                               br.CODE_NO_OPTIONS), reason.text


def test_multiselect_code_is_distinct_from_every_other_code():
    """Новый код не совпал с существующим — иначе состояния снова слиплись бы."""
    others = {br.CODE_MULTI_QUESTION, br.CODE_UNREADABLE_OPTIONS, br.CODE_NO_OPTIONS,
              br.CODE_STALE_VS_ORIGIN, br.CODE_HANDLER_UNAVAILABLE, br.CODE_HEAL_PENDING,
              br.CODE_CARD_GONE, br.CODE_UNMEASURED}
    assert br.CODE_MULTISELECT not in others


def test_multiselect_shadows_multi_question_by_construction_not_by_luck():
    """Порядок двух веток в `_explain_no_options` держится НЕ на порядке, а на структуре.

    Замер цикла #430 (подъём осиротевшей работы #426): перенос ветки `allows_multiple`
    НИЖЕ `multi_question` оставляет все 21 тест ЗЕЛЁНЫМИ — то есть комментарий «ветка
    стоит ВЫШЕ» ничем не закреплён и закрепить его нельзя: `_parse_options_measured`
    возвращает ``[], None`` сразу по `allows_multiple`, поэтому `multi_question` в этой
    точке `None` ВСЕГДА, при любом теле. Мутация по координате не красится по построению
    (класс «условие, которое нечем окрасить»).

    Красить надо не порядок, а факт, на который порядок опирается. Если ранний возврат
    из `_parse_options_measured` однажды снимут, две ветки станут пересекаться — и
    многовыборная карточка снова начнёт получать чужой диагноз, а на ЭТО уже никто не
    смотрит. Тест — положительный контроль ровно того ранненго возврата: снимите его, и
    здесь станет красно.
    """
    from spa_core.telegram.owner_decisions import allows_multiple, multi_question

    bodies = [
        # многовыборная И с метками РАЗНЫХ семей — единственная форма, которой
        # `multi_question` отвечает непусто, когда раннего возврата нет
        "## Что от тебя нужно\n\nВарианты не исключают друг друга.\n\n"
        "**Вариант А1 — раз**\n**Вариант А2 — два**\n"
        "**Вариант Б1 — три**\n**Вариант Б2 — четыре**\n",
        # многовыборная с ДУБЛЕМ номера — вторая форма, дающая непустой `multi_question`
        "## Что от тебя нужно\n\nМожно выбрать несколько пунктов.\n\n"
        "**Вариант 1 — раз**\n**Вариант 2 — два**\n**Вариант 2 — снова два**\n",
    ]
    for body in bodies:
        assert allows_multiple(body) is True, body
        assert multi_question(body) is None, (
            "ранний возврат по `allows_multiple` снят: две ветки "
            "`_explain_no_options` стали пересекаться, и теперь их ПОРЯДОК "
            "решает исход — закрепите порядок тестом или верните возврат"
        )
