"""Строка дневных лимитов (DL-01…DL-05) в дневном отчёте владельцу.

Находка карточки `inbox-stroka-risk-gate-dnevnogo-limita-ubytka` (цикл #227):
`DailyLimitsChecker` исполняется каждый цикл (`cycle_runner` Step 2a) и пишет
вердикт в `data/risk_limits_check.json`, но **витрина** этого вердикта жила
только в списанном `scripts/daily_paper_report.py`, чей агент отключён с 21.06.
Владелец в живом отчёте видел лишь счётчик блокировок RiskPolicy — ДРУГОГО
сторожа — и не мог узнать, что сказал дневной лимит убытка.

**Положительный контроль** — `test_positive_control_*` ниже: они воспроизводят
именно то состояние диска, при котором отчёт молчал (HALT в снимке; протухший
снимок), и краснеют на коде до этой работы. Тест без пережитой аварии —
украшение.

Время — вход, а не окружение: и `checked_at` снимка, и `now` отчёта задаёт тест,
поэтому сдвиг календаря эти тесты не красит.

# FROZEN-DATE-OK: injected-clock — единственный литерал `_NOW` уходит в отчёт
# как `now=`, а все отметки снимков считаются от ТОГО ЖЕ якоря
# (`_checked_at(hours_ago=…)`). Обе стороны окна свежести закреплены, стенные
# часы в файле не читаются нигде — календарь эти тесты не красит (preference #1
# of .claude/rules/deployment.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from spa_core.reporting.daily_telegram_report import (
    DAILY_LIMITS_MAX_AGE_HOURS,
    RISK_LIMITS_FILENAME,
    build_report_data,
    format_daily_message,
)

_NOW = datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc)
_DATE = "2026-08-15"


def _write_snapshot(tmp_path, doc) -> None:
    (tmp_path / RISK_LIMITS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")


def _checked_at(hours_ago: float) -> str:
    return (_NOW - timedelta(hours=hours_ago)).isoformat()


def _snapshot(
    gate: str = "PASS",
    *,
    hours_ago: float = 1.0,
    dl01_status: str = "PASS",
    dl01_value: float | None = 0.12,
    halt_reasons: list[str] | None = None,
    warn_reasons: list[str] | None = None,
    **over,
) -> dict:
    doc = {
        "gate": gate,
        "checked_at": _checked_at(hours_ago),
        "checks": [
            {
                "id": "DL-01",
                "name": "Daily Loss",
                "status": dl01_status,
                "value": dl01_value,
                "limit": 2.0,
                "message": "daily loss 0.12% within limit",
            },
            {
                "id": "DL-02",
                "name": "Peak Drawdown",
                "status": "PASS",
                "value": 0.4,
                "limit": 10.0,
            },
        ],
        "halt_reasons": halt_reasons or [],
        "warn_reasons": warn_reasons or [],
    }
    doc.update(over)
    return doc


def _message(tmp_path) -> str:
    return format_daily_message(
        build_report_data(_DATE, data_dir=tmp_path, now=_NOW)
    )


# ── Положительный контроль: ровно то состояние, при котором отчёт молчал ──────


def test_positive_control_halt_verdict_reaches_the_owner(tmp_path):
    """HALT дневного лимита убытка ОБЯЗАН быть в сообщении, с причиной."""
    _write_snapshot(
        tmp_path,
        _snapshot(
            "HALT",
            dl01_status="FAIL",
            dl01_value=3.1,
            halt_reasons=[
                "DL-01 Daily Loss: daily loss 3.10% exceeds limit 2.0%",
            ],
        ),
    )
    text = _message(tmp_path)
    assert "Daily limits: HALT" in text, text
    assert "DL-01 Daily Loss" in text, text
    assert "3.10%" in text, text


def test_positive_control_stale_snapshot_is_never_shown_as_a_clean_day(tmp_path):
    """Протухший PASS страшнее отсутствующего: владелец примет его за сегодняшний."""
    _write_snapshot(
        tmp_path, _snapshot("PASS", hours_ago=DAILY_LIMITS_MAX_AGE_HOURS + 5.0)
    )
    data = build_report_data(_DATE, data_dir=tmp_path, now=_NOW)
    assert data["daily_limits"]["gate"] == "UNKNOWN"
    text = format_daily_message(data)
    assert "NO FRESH VERDICT" in text, text
    assert "UNCONFIRMED" in text, text
    assert "PASS" not in text, text


# ── Вердикт в обе стороны ────────────────────────────────────────────────────


def test_clean_day_states_pass_with_the_measured_loss(tmp_path):
    """Чистый день называется чистым И числом — вопрос карточки был про число."""
    _write_snapshot(tmp_path, _snapshot("PASS"))
    data = build_report_data(_DATE, data_dir=tmp_path, now=_NOW)
    assert data["daily_limits"]["gate"] == "PASS"
    text = _message(tmp_path)
    assert "Daily limits (DL-01..05): PASS" in text, text
    assert "daily loss 0.12% (limit 2.0%)" in text, text
    assert "HALT" not in text, text


def test_warn_verdict_lists_its_reasons(tmp_path):
    _write_snapshot(
        tmp_path,
        _snapshot(
            "WARN",
            warn_reasons=["DL-03 Adapter Concentration: aave_v3 at 55.0% exceeds limit 40.0%"],
        ),
    )
    text = _message(tmp_path)
    assert "Daily limits: WARN" in text, text
    assert "DL-03 Adapter Concentration" in text, text


def test_profit_day_is_not_printed_as_a_loss(tmp_path):
    """Отрицательное значение DL-01 — прибыль дня, а не «убыток −0.30%»."""
    _write_snapshot(tmp_path, _snapshot("PASS", dl01_value=-0.3))
    text = _message(tmp_path)
    assert "daily change +0.30%" in text, text


# ── Fail-CLOSED: незнание НАЗЫВАЕТСЯ, а не подменяется нулём или тишиной ─────


def test_missing_snapshot_is_named_unknown_not_silence(tmp_path):
    data = build_report_data(_DATE, data_dir=tmp_path, now=_NOW)
    dl = data["daily_limits"]
    assert dl["gate"] == "UNKNOWN"
    assert "no snapshot" in dl["unknown_reason"]
    text = format_daily_message(data)
    assert "NO FRESH VERDICT" in text, text
    # Отчёт остаётся отчётом: остальные секции живы.
    assert "SPA Daily Report" in text


def test_corrupt_snapshot_does_not_crash_the_report(tmp_path):
    (tmp_path / RISK_LIMITS_FILENAME).write_text("{not json", encoding="utf-8")
    text = _message(tmp_path)
    assert "NO FRESH VERDICT" in text, text


def test_snapshot_without_timestamp_is_unknown(tmp_path):
    doc = _snapshot("PASS")
    doc.pop("checked_at")
    _write_snapshot(tmp_path, doc)
    dl = build_report_data(_DATE, data_dir=tmp_path, now=_NOW)["daily_limits"]
    assert dl["gate"] == "UNKNOWN"
    assert "timestamp" in dl["unknown_reason"]


def test_unknown_gate_word_is_refused(tmp_path):
    """Чужой формат снимка не превращается в вердикт по невнимательности."""
    _write_snapshot(tmp_path, _snapshot("OK-ISH"))
    dl = build_report_data(_DATE, data_dir=tmp_path, now=_NOW)["daily_limits"]
    assert dl["gate"] == "UNKNOWN"
    assert "no known verdict" in dl["unknown_reason"]


def test_future_timestamp_is_refused(tmp_path):
    """Снимок «из будущего» — рассогласование часов, а не свежесть."""
    _write_snapshot(tmp_path, _snapshot("PASS", hours_ago=-48.0))
    assert build_report_data(_DATE, data_dir=tmp_path, now=_NOW)["daily_limits"]["gate"] == "UNKNOWN"


def test_dl01_skip_is_reported_as_not_measured(tmp_path):
    """Нет двух бар истории — так и сказано; 0.00% было бы выдумкой."""
    _write_snapshot(tmp_path, _snapshot("PASS", dl01_status="SKIP", dl01_value=None))
    text = _message(tmp_path)
    assert "daily loss: not measured (SKIP)" in text, text


# ── Границы: отчётный слой ничего не решает и не пишет ───────────────────────


def test_report_only_reads_the_snapshot_and_writes_nothing(tmp_path):
    _write_snapshot(tmp_path, _snapshot("PASS"))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    build_report_data(_DATE, data_dir=tmp_path, now=_NOW)
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert before == after


def test_reporting_layer_carries_no_thresholds_of_its_own():
    """Пороги живут в DailyLimitsChecker; отчёт их не дублирует и не судит."""
    from pathlib import Path

    import spa_core.reporting.daily_telegram_report as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "MAX_DAILY_LOSS_PCT" not in src, "порог продублирован в отчётном слое"
    assert "spa_core.risk.daily_limits" not in src, (
        "отчёт читает готовый снимок; импорт гейта завёл бы второй счётчик"
    )


def test_cio_and_risk_block_sections_are_untouched(tmp_path):
    """Соседние секции не пострадали: ссылка на risk_blocks_daily на месте."""
    (tmp_path / "paper_trading_status.json").write_text(
        json.dumps({"risk_policy_approved": True}), encoding="utf-8"
    )
    (tmp_path / "risk_policy_blocks.json").write_text(
        json.dumps([{"date": _DATE}]), encoding="utf-8"
    )
    _write_snapshot(tmp_path, _snapshot("PASS"))
    text = _message(tmp_path)
    assert f"risk_blocks_daily/{_DATE}.json" in text, text
    assert "Daily limits (DL-01..05): PASS" in text, text
