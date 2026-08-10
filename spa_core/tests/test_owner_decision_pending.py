"""Сторож «у остановки должен быть ЖИВОЙ вопрос владельцу» (цикл #195).

КАЖДЫЙ тест — положительный контроль реальной аварии **10.08.2026**:

    00:52 UTC  прод встал (`data/kill_switch_active.json`, threat_reactor: HALT);
    12:23 UTC  владельцу ушёл вопрос, которым остановку можно снять;
    13:30 UTC  книга всё ещё в кэше, deployed 0 %, а разрыв в 11.5 часов не
               измерял НИ ОДИН сторож.

Время здесь — ВХОД (`now=`), и отметки в фикстурах тоже фиксированные: обе стороны
закреплены, тест не протухнет от движения календаря (`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spa_core.monitoring.owner_decision_pending import (
    CRITICAL,
    OK,
    PENDING_CRITICAL_H,
    WARNING,
    check_pending_owner_decisions,
    run,
)

# FROZEN-DATE-OK: injected-clock — `now=` передаётся в КАЖДОМ вызове, и все
# отметки фикстур взяты из той же хронологии 10.08: обе стороны закреплены,
# движение календаря на вердикт не влияет вовсе (предпочтение №1
# `.claude/rules/deployment.md`). Сама дата здесь к тому же и предмет — это
# дословная хронология аварии, ради которой сторож написан.

# --- Хронология аварии 10.08 ------------------------------------------------
HALT_AT = "2026-08-10T00:52:40.835853+00:00"
PUSHED_AT = "2026-08-10T12:23:04.287867+00:00"
NOW_1330 = dt.datetime(2026, 8, 10, 13, 30, tzinfo=dt.timezone.utc)
NOW_0100 = dt.datetime(2026, 8, 10, 1, 0, tzinfo=dt.timezone.utc)

CARD_ID = "owner-decision-sistema-ostanovlena-avariinym-vyklyuchat"


@pytest.fixture()
def tree(tmp_path: Path):
    """Дерево-песочница: data/ и трекер рядом, как в настоящем репозитории."""
    data = tmp_path / "data"
    tracker = tmp_path / "nimbalyst-local" / "tracker"
    data.mkdir()
    tracker.mkdir(parents=True)
    return data, tracker


def _halt(data: Path, at: str = HALT_AT) -> None:
    (data / "kill_switch_active.json").write_text(json.dumps({
        "activated_at": at,
        "reason": "threat_reactor: emergency breaker: HALT",
        "source": "kill_switch_checker",
    }), encoding="utf-8")


def _journal(data: Path, pushes: list) -> None:
    (data / "telegram_owner_decisions.json").write_text(
        json.dumps({"schema_version": 1, "pushes": pushes}), encoding="utf-8")


def _card(tracker: Path, card_id: str = CARD_ID, status: str = "needs-owner") -> None:
    (tracker / f"{card_id}.md").write_text(
        "---\n"
        "trackerStatus:\n"
        "  type: owner-decision\n"
        f'title: "Система остановлена аварийным выключателем"\n'
        f"status: {status}\n"
        "---\n\n## Что от тебя нужно\n\n**Вариант 1 (рекомендую)** — снять.\n",
        encoding="utf-8")


def _push(*, card_id: str = CARD_ID, pushed_at: str = PUSHED_AT,
          buttons: bool = True, choice=None) -> dict:
    return {"pid": "8aeaeddb", "card_id": card_id, "card": f"/x/{card_id}.md",
            "title": "Система остановлена аварийным выключателем",
            "pushed_at": pushed_at, "buttons": buttons, "choice": choice}


# ===========================================================================
# H1 — ТУПИК: остановка есть, вопроса нет (00:52 → 01:00 живой аварии)
# ===========================================================================
def test_halt_without_any_question_is_a_dead_end(tree):
    data, tracker = tree
    _halt(data)
    _journal(data, [])

    doc = check_pending_owner_decisions(now=NOW_0100, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert doc["halted"] is True
    assert doc["pending_count"] == 0
    assert "ТУПИК" in doc["issues"][0]
    assert "пути вверх нет" in doc["issues"][0]
    # Возраст простоя назван числом, а не «недавно».
    assert "0.1ч" in doc["issues"][0]


def test_dead_end_is_not_declared_when_the_queue_could_not_be_measured(tree):
    """«Не измерено» и «нет вопроса» — РАЗНЫЕ факты, и путать их нельзя.

    Тревога обязана быть, но поклёпа «вопроса не задано» — нет: журнал просто
    нечитаем. Это ровно та развилка, на которой fail-CLOSED вырождается в ложь.
    """
    data, tracker = tree
    _halt(data)
    (data / "telegram_owner_decisions.json").write_text("{не json", encoding="utf-8")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert "НЕ ИЗМЕРЕНО" in doc["issues"][0]
    assert "ТУПИК" not in doc["issues"][0]
    assert doc["unchecked"] and doc["unchecked"][0]["check"] == "push_journal"


# ===========================================================================
# H2 — остановка ждёт ЧЕЛОВЕКА (авария 10.08 целиком)
# ===========================================================================
def test_halt_with_a_pending_question_names_the_wait_10_08(tree):
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 1
    assert doc["halt_age_h"] == pytest.approx(12.62, abs=0.02)
    assert doc["oldest_pending_age_h"] == pytest.approx(1.12, abs=0.02)
    line = doc["issues"][0]
    assert "ОСТАНОВЛЕНА" in line and "ждёт ЧЕЛОВЕКА" in line
    # Оба срока в одной строке: простой И возраст вопроса — это разные величины,
    # и 10.08 они разошлись на 11.5 часа.
    assert "12.6ч" in line and "1.1ч" in line
    # Часы считает ПРОСТОЙ: вопрос свежий (1.1ч), но система стоит 12.6ч ⇒ CRITICAL.
    assert doc["status"] == CRITICAL


def test_a_fresh_halt_with_a_pending_question_is_only_a_warning(tree):
    """Контроль в обратную сторону: полтора часа простоя — ещё не тревога."""
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push(pushed_at="2026-08-10T01:00:00+00:00")])

    doc = check_pending_owner_decisions(
        now=dt.datetime(2026, 8, 10, 2, 22, tzinfo=dt.timezone.utc),
        data_dir=data, tracker_dir=tracker)

    assert doc["status"] == WARNING
    assert doc["halt_age_h"] < PENDING_CRITICAL_H


def test_the_clock_is_the_standstill_not_the_freshness_of_the_question(tree):
    """Вопрос, заданный минуту назад, НЕ делает суточный простой свежим.

    Мутация, которую тест ловит: считать возраст по `oldest_pending_age_h`.
    Тогда достаточно переспросить владельца — и тревога гаснет, а книга стоит.
    """
    data, tracker = tree
    _halt(data, at="2026-08-09T00:52:40+00:00")          # простой ~36ч
    _card(tracker)
    _journal(data, [_push(pushed_at="2026-08-10T13:00:00+00:00")])  # вопрос 0.5ч

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["oldest_pending_age_h"] < PENDING_CRITICAL_H
    assert doc["halt_age_h"] > PENDING_CRITICAL_H
    assert doc["status"] == CRITICAL


# ===========================================================================
# Что НЕ является находкой (контроль в обратную сторону)
# ===========================================================================
def test_answered_question_is_not_pending(tree):
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push(choice="1")])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    # Ответ получен ⇒ ждущих вопросов нет ⇒ это ТУПИК, а не «ждёт человека»:
    # выключатель всё ещё активен, а спросить больше нечего.
    assert "ТУПИК" in doc["issues"][0]


def test_card_closed_outside_the_button_is_not_pending(tree):
    """Владелец мог ответить и в карточке — статус карточки главнее журнала."""
    data, tracker = tree
    _card(tracker, status="owner-done")
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    assert doc["status"] == OK


def test_pending_questions_without_a_halt_are_fields_not_an_alarm(tree):
    """Владелец в отъезде — WARN, который не может погаснуть 9 дней, это шум.

    Тревога поднимается там, где ожидание СТОИТ трека, то есть при остановке.
    """
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["halted"] is False
    assert doc["pending_count"] == 1
    assert doc["status"] == OK
    assert doc["issues"] == []


# ===========================================================================
# H3 — вопрос, на который владелец физически не может ответить
# ===========================================================================
def test_a_pending_question_without_buttons_is_named(tree):
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push(buttons=False)])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["buttonless_count"] == 1
    assert doc["status"] == WARNING
    assert "БЕЗ КНОПОК" in doc["issues"][0]


def test_halt_line_comes_first_even_when_buttons_are_missing_too(tree):
    """`reason` отчёта — это issues[0]; первой строкой обязана быть ОСТАНОВКА."""
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push(buttons=False)])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert "ОСТАНОВЛЕНА" in doc["reason"]
    assert any("БЕЗ КНОПОК" in line for line in doc["issues"])


# ===========================================================================
# Fail-CLOSED на карточке, которой нет в живом дереве (авария #194)
# ===========================================================================
def test_a_push_whose_card_is_missing_is_unchecked_not_silently_dropped(tree):
    """Нажатие по такой карточке отвечает «карточка исчезла» — молчать нельзя."""
    data, tracker = tree
    _journal(data, [_push()])          # карточки в трекере НЕТ

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    assert doc["unchecked"] and doc["unchecked"][0]["check"] == f"card_missing:{CARD_ID}"
    assert doc["status"] == WARNING    # без остановки — предупреждение
    # А во время остановки та же неизмеримость обязана быть CRITICAL.
    _halt(data)
    doc2 = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert doc2["status"] == CRITICAL


def test_an_unreadable_card_is_unchecked_not_treated_as_closed(tree):
    """Пустой статус сравнился бы с `needs-owner` как «не равно» — и вопрос молча
    выпал бы из очереди. Это fail-OPEN ровно того вида, ради которого модуль и писан.
    """
    data, tracker = tree
    _halt(data)
    (tracker / f"{CARD_ID}.md").write_text("вообще не карточка", encoding="utf-8")
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    assert any(u["check"] == f"card_unreadable:{CARD_ID}" for u in doc["unchecked"])
    assert doc["status"] == CRITICAL
    assert "НЕ ИЗМЕРЕНО" in doc["issues"][0] and "ТУПИК" not in doc["issues"][0]


def test_an_absent_journal_is_not_a_finding_but_a_corrupt_one_is(tree):
    """«Файла нет» ≠ «файл испорчен».

    Чистое дерево (CI, песочница) журнала отправок не имеет — там владельцу просто
    ничего не отправляли, и предупреждение здесь было бы шумом, который учат
    пролистывать. А ВОТ испорченный журнал делает очередь вопросов неизмеримой.
    """
    data, tracker = tree

    absent = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert absent["status"] == OK
    assert absent["journal_present"] is False
    assert absent["unchecked"] == []

    (data / "telegram_owner_decisions.json").write_text("{не json", encoding="utf-8")
    corrupt = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert corrupt["status"] == WARNING
    assert corrupt["unchecked"][0]["check"] == "push_journal"


def test_a_halt_with_no_journal_at_all_is_still_a_dead_end(tree):
    """Отсутствие журнала гасит шум, но НЕ гасит тревогу об остановке.

    Мутация, которую тест ловит: «нет журнала ⇒ молчим» целиком. Тогда самая
    страшная конфигурация — стоим и никого не спросили — стала бы тихой.
    """
    data, tracker = tree
    _halt(data)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert "ТУПИК" in doc["issues"][0]


# ===========================================================================
# Артефакт: без файла обязательного читателя (шаг 0-офис) не существует
# ===========================================================================
def test_run_writes_the_artifact_next_to_the_data_dir(tree):
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push()])

    doc, path = run(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert path == data / "owner_decision_pending.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["status"] == doc["status"] == CRITICAL
    assert written["generated_at"] == NOW_1330.isoformat()


# ===========================================================================
# Проводка: пульс флота обязан НЕСТИ эту находку, а не только модуль
# ===========================================================================
def test_agent_health_carries_the_finding(tree, monkeypatch):
    """Мутация «снять проводку» обязана краснить: без неё модуль — сирота.

    Именно так умирал класс #144: правка детали при мёртвой проводке зелена и
    бесполезна.
    """
    from spa_core.monitoring import agent_health_monitor as ahm

    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push()])

    checks, status, issues = ahm.check_system(data, NOW_1330)

    assert checks["owner_pending_count"] == 1
    assert checks["owner_pending_oldest_h"] == pytest.approx(1.12, abs=0.02)
    assert status == ahm.CRITICAL
    assert any("ждёт ЧЕЛОВЕКА" in line for line in issues)


def test_agent_health_reports_unchecked_when_the_probe_itself_fails(tree, monkeypatch):
    """Упавшая проверка — это НЕ «путь вверх есть» (fail-CLOSED на самой себе)."""
    from spa_core.monitoring import agent_health_monitor as ahm
    from spa_core.monitoring import owner_decision_pending as odp

    data, _tracker = tree

    def _boom(**_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(odp, "check_pending_owner_decisions", _boom)
    _checks, status, issues = ahm.check_system(data, NOW_1330)

    assert status in (ahm.WARNING, ahm.CRITICAL)
    assert any("owner_decision_pending UNCHECKED" in line for line in issues)
