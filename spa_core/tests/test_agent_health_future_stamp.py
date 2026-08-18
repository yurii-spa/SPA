"""Отметка из БУДУЩЕГО не смеет читаться как «только что» (цикл #291).

Карточка `inbox-otmetka-iz-buduschego-chitaetsya-kak-tol`, находка цикла #290.

`agent_health_monitor._hours_since` зажимал возраст в ноль (``max(0.0, …)``).
Значит отметка, опередившая наши часы — испорченные часы, чужой часовой пояс,
выдуманная дата — приходила к четырём проверкам как «самая свежая на свете
правда», и КАЖДАЯ из них честно отвечала «несвежести не нашёл». Это наш родовой
fail-OPEN: зелёный ответ на свой вопрос читается как ответ на нужный.

**Каждый тест ниже — положительный контроль**: на модуле с `origin/main`
(зажим на месте) он краснеет, потому что проверяет ПОВЕДЕНИЕ — вердикт и текст
находки, а не наличие строчки в исходнике.

Обратные контроли идут рядом и столь же обязательны: починка, которая красит
на любой отметке впереди часов, — это не починка, а новый ложный сигнал.
Отметка в пределах допуска (`CLOCK_SKEW_H`) обязана оставаться «свежей», а
формулировки ветвей «протухло» — побайтно прежними: их дедупит `should_alert`,
и тихая смена текста расклеила бы дедуп тревог владельцу.

Время здесь — ВХОД: `now` инъектируется в проверку, а все отметки считаются от
ТОГО ЖЕ мгновения. Обе стороны сравнения закреплены друг за друга, поэтому тест
бессмертен по календарю (правило `.claude/rules/deployment.md`, порядок
предпочтения п.1). Литеральной даты нет намеренно — она здесь не предмет, и
храповик `test_frozen_date_ratchet.py` справедливо не пустил бы её в набор про
свежесть.
"""
import json
from datetime import timedelta

import pytest

from spa_core.tests._freshness import now_utc

from spa_core.monitoring.agent_health_monitor import (
    CLOCK_SKEW_H,
    CRITICAL,
    CYCLE_STALE_H,
    EQUITY_STALE_H,
    FLEET_PARITY_STALE_H,
    OK,
    REFUSAL_PROTECTED,
    REFUSAL_UNCHECKED,
    RESILIENCE_STALE_H,
    WARNING,
    _hours_since,
    _is_future,
    check_system,
    judge_lock_refusal,
)

#: Мгновение «сейчас» снимается ОДИН раз и дальше служит обеим сторонам: и как
#: инъектированный `now`, и как точка отсчёта каждой отметки. Календарь может
#: ехать сколько угодно — расстояния между ними не меняются.
NOW = now_utc()
_NONE_LOG = "/nonexistent/autopush.log"  # → file_age_minutes None → проверка пропускается

# Насколько «в будущее» уводим отметку в положительных контролях: заведомо за
# допуском, но по-человечески правдоподобно (сдвиг на час часового пояса).
_AHEAD_H = 3.0


def _stamp(hours_old):
    """ISO-отметка возрастом `hours_old` часов; отрицательное = ВПЕРЕДИ часов."""
    return (NOW - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(tmp_path, name, payload):
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")


# ── помощник: зажим снят, знак наружу выходит ───────────────────────────────

def test_hours_since_returns_negative_for_a_future_stamp():
    """Сердце находки: раньше здесь было ровно 0.0 — «только что»."""
    h = _hours_since(_stamp(-_AHEAD_H), NOW)
    assert h is not None
    assert h == pytest.approx(-_AHEAD_H, abs=0.01), (
        "отметка из будущего обязана давать ОТРИЦАТЕЛЬНЫЙ возраст; "
        "зажим в 0.0 делает испорченные часы неотличимыми от свежести"
    )


def test_hours_since_still_positive_and_unclamped_for_the_past():
    """Обратный контроль: обычный прошлый возраст не тронут."""
    assert _hours_since(_stamp(5.0), NOW) == pytest.approx(5.0, abs=0.01)


def test_hours_since_still_none_when_unreadable():
    """Обратный контроль: «не прочитано» осталось отдельным исходом."""
    assert _hours_since("не отметка вовсе", NOW) is None
    assert _hours_since(None, NOW) is None


def test_is_future_respects_the_tolerance_in_both_directions():
    """Допуск — порог, а не украшение: по обе стороны от него ответы разные."""
    assert _is_future(-(CLOCK_SKEW_H + 0.1)) is True
    assert _is_future(-(CLOCK_SKEW_H - 0.1)) is False
    assert _is_future(0.0) is False
    assert _is_future(10.0) is False
    assert _is_future(None) is False  # «не прочитано» ≠ «из будущего»


# ── читатель 1: свежесть трека (CRITICAL) ───────────────────────────────────

def test_equity_stamp_from_the_future_is_critical_not_silence(tmp_path):
    _write(tmp_path, "equity_curve_daily.json", {"generated_at": _stamp(-_AHEAD_H)})
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == CRITICAL, "отметка трека из будущего гасила CRITICAL о протухшем треке"
    assert any("equity_curve" in i and "FUTURE" in i for i in issues)
    assert any("NOT MEASURED" in i for i in issues), "незнание обязано быть НАЗВАНО"
    assert checks["equity_last_update_h"] == pytest.approx(-_AHEAD_H, abs=0.01)


def test_equity_within_clock_skew_stays_fresh(tmp_path):
    """Обратный контроль: минуты рассинхрона часов — не находка."""
    _write(tmp_path, "equity_curve_daily.json",
           {"generated_at": _stamp(-(CLOCK_SKEW_H - 0.2))})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert not any("equity_curve" in i for i in issues)


def test_equity_stale_branch_keeps_its_exact_wording(tmp_path):
    """Обратный контроль: текст ветви «протухло» не менялся (его дедупит should_alert)."""
    _write(tmp_path, "equity_curve_daily.json",
           {"generated_at": _stamp(EQUITY_STALE_H + 5.0)})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == CRITICAL
    assert any(i.startswith("equity_curve stale ") and "h (>" in i for i in issues)


# ── читатель 2: свежесть дневного цикла (CRITICAL) ──────────────────────────

def test_cycle_stamp_from_the_future_is_critical_not_silence(tmp_path):
    _write(tmp_path, "cycle_status.json", {"last_run": _stamp(-_AHEAD_H)})
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == CRITICAL
    assert any("daily cycle" in i and "FUTURE" in i for i in issues)
    assert checks["cycle_freshness_h"] == pytest.approx(-_AHEAD_H, abs=0.01)


def test_cycle_within_clock_skew_stays_fresh(tmp_path):
    _write(tmp_path, "cycle_status.json", {"last_run": _stamp(-(CLOCK_SKEW_H - 0.2))})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert not any("daily cycle" in i for i in issues)


def test_cycle_stale_branch_keeps_its_exact_wording(tmp_path):
    _write(tmp_path, "cycle_status.json", {"last_run": _stamp(CYCLE_STALE_H + 4.0)})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == CRITICAL
    assert any(i.startswith("daily cycle stale ") and "h (>" in i for i in issues)


# ── читатель 3: DR-постура resilience (WARNING) ─────────────────────────────

def test_resilience_stamp_from_the_future_warns(tmp_path):
    _write(tmp_path, "resilience_status.json",
           {"generated_at": _stamp(-_AHEAD_H), "overall": "OK"})
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING, "постура из будущего выглядела «молча свежей»"
    assert any("resilience posture" in i and "FUTURE" in i for i in issues)
    assert checks["resilience_age_h"] == pytest.approx(-_AHEAD_H, abs=0.01)


def test_resilience_within_clock_skew_stays_fresh(tmp_path):
    _write(tmp_path, "resilience_status.json",
           {"generated_at": _stamp(-(CLOCK_SKEW_H - 0.2)), "overall": "OK"})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert not any("resilience" in i for i in issues)


def test_resilience_stale_branch_keeps_its_exact_wording(tmp_path):
    _write(tmp_path, "resilience_status.json",
           {"generated_at": _stamp(RESILIENCE_STALE_H + 5.0), "overall": "OK"})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING
    assert any("resilience posture stale" in i for i in issues)


# ── читатель 4: fleet parity (WARNING) ──────────────────────────────────────

def test_fleet_parity_stamp_from_the_future_warns(tmp_path):
    _write(tmp_path, "fleet_parity.json",
           {"generated_at": _stamp(-_AHEAD_H), "status": "OK"})
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING
    assert any("fleet parity" in i and "FUTURE" in i for i in issues)
    assert checks["fleet_parity_age_h"] == pytest.approx(-_AHEAD_H, abs=0.01)


def test_fleet_parity_within_clock_skew_stays_fresh(tmp_path):
    _write(tmp_path, "fleet_parity.json",
           {"generated_at": _stamp(-(CLOCK_SKEW_H - 0.2)), "status": "OK"})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert not any("fleet parity" in i for i in issues)


def test_fleet_parity_stale_branch_keeps_its_exact_wording(tmp_path):
    _write(tmp_path, "fleet_parity.json",
           {"generated_at": _stamp(FLEET_PARITY_STALE_H + 3.0), "status": "OK"})
    _, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING
    assert any("fleet parity stale" in i for i in issues)


# ── пятый читатель: вердикт об отказе замка (поведение сохранено) ───────────
# `judge_lock_refusal` считал знаковый возраст СВОИМ выражением в обход
# `_hours_since` — ровно потому, что тот зажимал. Зажима больше нет, выражение
# сведено к общему помощнику, а допуск взят из общей константы. Тесты ниже —
# доказательство, что смена реализации не сменила ответ.

def test_lock_refusal_still_unchecked_on_a_future_stamp(tmp_path):
    _write(tmp_path, "cycle_status.json", {"last_run": _stamp(-_AHEAD_H)})
    verdict = judge_lock_refusal(tmp_path, NOW)
    assert verdict.state == REFUSAL_UNCHECKED
    assert "БУДУЩЕМ" in verdict.words


def test_lock_refusal_still_protected_on_a_fresh_cycle(tmp_path):
    _write(tmp_path, "cycle_status.json", {"last_run": _stamp(3.0)})
    verdict = judge_lock_refusal(tmp_path, NOW)
    assert verdict.state == REFUSAL_PROTECTED
    assert verdict.cycle_age_h == pytest.approx(3.0, abs=0.01)


def test_lock_refusal_tolerance_is_the_shared_constant(tmp_path):
    """Допуск у замка и у четырёх проверок — ОДНО число, а не две копии.

    Мерим поведением по обе стороны порога: копия, разошедшаяся с `CLOCK_SKEW_H`,
    покраснит здесь, а не всплывёт через месяц расхождением двух сторожей.
    """
    _write(tmp_path, "cycle_status.json", {"last_run": _stamp(-(CLOCK_SKEW_H + 0.1))})
    assert judge_lock_refusal(tmp_path, NOW).state == REFUSAL_UNCHECKED

    _write(tmp_path, "cycle_status.json", {"last_run": _stamp(-(CLOCK_SKEW_H - 0.1))})
    assert judge_lock_refusal(tmp_path, NOW).state == REFUSAL_PROTECTED
