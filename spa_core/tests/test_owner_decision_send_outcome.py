"""Журнал решений владельца обязан знать, УЕХАЛО ли сообщение, а не только что мы его собрали.

Задание владельца 2026-08-19 21:39Z (карточка `inbox-knopki-resheniya-tak-i-ne-prishli-prishl`),
дословно: «Кнопки решения так и не пришли – пришли заново все открытые вопросы с кнопками».
Третий повтор одной жалобы (#215 · #228 · #229).

Что измерено в цикле #309 и что здесь закрепляется
------------------------------------------------------------------------------
``register_push`` пишет ``buttons: true`` ДО отправки: там измеряется, СОБРАЛАСЬ ли
клавиатура. Между этой записью и владельцем стоит ``guard_outbound`` — лимит потока
(``MAX_MSGS_PER_MIN = 12`` на ВСЕХ отправителей) и дедуп. Он роняет сообщение молча,
возвращая ``None``.

Отсюда авария, которую воспроизводит каждый тест ниже: разослать 13 открытых вопросов
подряд — значит упереться в лимит, потерять часть молча и получить журнал, в котором ВСЁ
успешно. Хуже того, ``heal_buttonless`` чинит только записи с ``buttons is False``, поэтому
решение, чьё сообщение не ушло ВООБЩЕ, было для починки невидимо навсегда.

Каждый тест — положительный контроль: на неисправленном коде он краснеет.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.owner_queue import notify as notify_mod
from spa_core.telegram import owner_decisions as od

CARD = """---
trackerStatus:
  type: owner-decision
status: needs-owner
---

# Тестовый вопрос владельцу

## Что от тебя нужно

**Вариант 1.** Сделать так. (⭐ рекомендация агента)
**Вариант 2.** Сделать иначе.
"""


@pytest.fixture()
def card(tmp_path: Path) -> Path:
    d = tmp_path / "nimbalyst-local" / "tracker"
    d.mkdir(parents=True)
    p = d / "owner-decision-probe-send-outcome.md"
    p.write_text(CARD, encoding="utf-8")
    return p


@pytest.fixture()
def state(tmp_path: Path) -> Path:
    return tmp_path / "telegram_owner_decisions.json"


@pytest.fixture(autouse=True)
def handler_alive(monkeypatch: pytest.MonkeyPatch):
    """Обработчик нажатий ЖИВ — иначе кнопок не будет по другой причине (ADR-069).

    Маячок подменяется, а не берётся с машины: на Linux-раннере живого бота нет вовсе,
    и тест молча мерил бы не то, что заявляет (`buttons` уже `False` до всякой отправки).
    """
    from spa_core.telegram import alert_actions

    monkeypatch.setattr(alert_actions, "handler_available", lambda **kw: True)


def _records(state: Path):
    return json.loads(state.read_text())["pushes"]


def _register(card: Path, state: Path):
    """Отправка, как её видит журнал ДО ответа сети: кнопки собраны, исход неизвестен."""
    return od.register_push(card, "Тестовый вопрос владельцу", card.read_text(),
                            state_path=state, live_root=card.parents[2])


# ── сам исход ────────────────────────────────────────────────────────────────


def test_dropped_send_is_not_recorded_as_delivered(card: Path, state: Path):
    """АВАРИЯ 19.08: заслон уронил сообщение, а журнал утверждал «кнопки доставлены»."""
    prep = _register(card, state)
    assert _records(state)[0]["buttons"] is True, "предусловие: запись намерения"

    od.mark_send_outcome(prep.pid, ok=False, state_path=state)

    rec = _records(state)[0]
    assert rec["delivered"] is False
    # Ключевое утверждение: запись больше НЕ утверждает, что владелец видел кнопки.
    assert rec["buttons"] is False


def test_successful_send_is_recorded_as_delivered(card: Path, state: Path):
    """Обратный контроль: удачная отправка не должна гасить кнопки."""
    prep = _register(card, state)

    od.mark_send_outcome(prep.pid, ok=True, state_path=state)

    rec = _records(state)[0]
    assert rec["delivered"] is True
    assert rec["buttons"] is True


def test_dropped_send_becomes_visible_to_the_healer(card: Path, state: Path):
    """Главный тест: недоехавшее решение обязано попасть в штатный ремонт.

    До починки `heal_buttonless` брал только `buttons is False`, а недоехавшее сообщение
    несло `buttons: true` ⇒ ремонт не видел его НИКОГДА.
    """
    prep = _register(card, state)
    assert od.buttonless_pushes(state_path=state) == [], "предусловие: ремонт молчит"

    od.mark_send_outcome(prep.pid, ok=False, state_path=state)

    heals = od.buttonless_pushes(state_path=state)
    assert [h.pid for h in heals] == [prep.pid]


def test_marking_is_idempotent_and_survives_unknown_pid(card: Path, state: Path):
    prep = _register(card, state)
    assert od.mark_send_outcome(prep.pid, ok=False, state_path=state) is True
    assert od.mark_send_outcome(prep.pid, ok=False, state_path=state) is True
    assert len(_records(state)) == 1
    # Чужой pid — не находка и не авария: просто нечего отмечать.
    assert od.mark_send_outcome("no-such-pid", ok=True, state_path=state) is False


def test_marking_never_raises_on_a_broken_journal(tmp_path: Path):
    broken = tmp_path / "broken.json"
    broken.write_text("{ это не json", encoding="utf-8")
    assert od.mark_send_outcome("any", ok=True, state_path=broken) is False


# ── проводка: исход обязан записываться САМ, а не по памяти вызывающего ───────


def test_notify_records_the_outcome_when_the_guard_drops_the_message(
        card: Path, state: Path, monkeypatch: pytest.MonkeyPatch):
    """Сквозной положительный контроль ровно той аварии, что дала жалобу владельца.

    Мутируй проводку (сними вызов `_record_outcome` в `notify_needs_owner`) — покраснеет
    именно этот тест: журнал снова начнёт утверждать доставку того, что заслон уронил.
    """
    sent: list = []

    class _DroppingBot:
        """Заслон потока: сообщение НЕ уходит, ошибки нет, возвращается None."""

        def send_message(self, text, **kw):
            sent.append(text)
            return None

    monkeypatch.setattr(od, "_state_path", lambda override=None: state)
    monkeypatch.setattr("spa_core.telegram.bot.TelegramBot", _DroppingBot)
    monkeypatch.setattr(od, "_live_tracker_dir", lambda override=None: card.parent)

    notify_mod.notify_needs_owner(card)

    assert sent, "предусловие: отправку пытались сделать"
    rec = _records(state)[0]
    assert rec["delivered"] is False, "исход отправки не записан"
    assert rec["buttons"] is False, "журнал всё ещё утверждает доставленные кнопки"


def test_dry_run_records_no_outcome_at_all(card: Path, state: Path,
                                           monkeypatch: pytest.MonkeyPatch):
    """Обратный контроль: сухой прогон не пишет в живое состояние (#183, #216)."""
    monkeypatch.setattr(od, "_state_path", lambda override=None: state)

    notify_mod.notify_needs_owner(card, dry_run=True)

    assert not state.exists() or _records(state) == []
