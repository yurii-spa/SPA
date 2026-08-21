"""Тесты внутридневного актора рукавов B/C (ADR-114).

Каждый тест — герметичный: свой tmp data-dir, директива собирается файлами
(intraday_equity.json / risk_posture.json / chief_investment.json — те же
входы, что читает настоящий load_directive), часы инъектируются с обеих
сторон. Ни сети, ни живого data/.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from spa_core.paper_trading import intraday_actor

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock (обе стороны — вход)


def _book(positions):
    return {"seed_equity": 25_000.0, "equity": 25_100.0, "peak_equity": 25_150.0,
            "positions": positions, "daily_history": []}


def _write(base, name, doc):
    (base / name).write_text(json.dumps(doc), encoding="utf-8")


def _movement(base):
    """Движение вниз: intraday tier SOFT_DERISK (сенсор 300с, ADR-104)."""
    _write(base, "intraday_equity.json", {"tier": "SOFT_DERISK", "drawdown_pct": 6.1})


def _quiet(base):
    _write(base, "intraday_equity.json", {"tier": "NONE", "drawdown_pct": 0.4})


@pytest.fixture()
def base(tmp_path):
    (tmp_path / "monitoring").mkdir()
    return tmp_path


def test_movement_closes_both_sleeves_and_records_action(base):
    _movement(base)
    _write(base, "hy_paper_trading.json",
           _book([{"protocol": "pendle", "apy_pct": 14.0, "notional_usd": 12_500.0},
                  {"protocol": "maple", "apy_pct": 9.5, "notional_usd": 12_500.0}]))
    _write(base, "lp_paper_trading.json",
           _book([{"protocol": "aerodrome", "apy_pct": 11.0, "notional_usd": 25_000.0}]))

    report = intraday_actor.run_intraday_actor(base, now=_NOW)

    assert report["triggered"] is True
    assert report["sleeves"]["B"]["action"] == "closed"
    assert report["sleeves"]["B"]["count"] == 2
    assert report["sleeves"]["C"]["action"] == "closed"

    hy = json.loads((base / "hy_paper_trading.json").read_text())
    assert hy["positions"] == []
    act = hy["intraday_actions"][-1]
    assert act["action"] == "derisk_close_all"
    assert act["ts"] == _NOW.isoformat()
    assert {c["protocol"] for c in act["closed"]} == {"pendle", "maple"}


def test_equity_untouched_by_close(base):
    """ADR-114: закрытие НЕ трогает equity — внутридневное начисление было бы
    изобретённой ценой (начисляет только цикл, ADR-103)."""
    _movement(base)
    _write(base, "hy_paper_trading.json",
           _book([{"protocol": "pendle", "apy_pct": 14.0, "notional_usd": 25_000.0}]))

    intraday_actor.run_intraday_actor(base, now=_NOW)

    hy = json.loads((base / "hy_paper_trading.json").read_text())
    assert hy["equity"] == 25_100.0
    assert hy["peak_equity"] == 25_150.0


def test_idempotent_second_pass_is_noop(base):
    """Анти-шторм: то же движение на следующем такте сенсора не плодит записей."""
    _movement(base)
    _write(base, "hy_paper_trading.json",
           _book([{"protocol": "pendle", "apy_pct": 14.0, "notional_usd": 25_000.0}]))
    _write(base, "lp_paper_trading.json", _book([]))

    intraday_actor.run_intraday_actor(base, now=_NOW)
    report2 = intraday_actor.run_intraday_actor(base, now=_NOW)

    assert report2["sleeves"]["B"]["action"] == "noop"
    hy = json.loads((base / "hy_paper_trading.json").read_text())
    assert len(hy["intraday_actions"]) == 1  # одна запись, не две


def test_quiet_sensors_no_action(base):
    _quiet(base)
    _write(base, "hy_paper_trading.json",
           _book([{"protocol": "pendle", "apy_pct": 14.0, "notional_usd": 25_000.0}]))

    report = intraday_actor.run_intraday_actor(base, now=_NOW)

    assert report["triggered"] is False
    hy = json.loads((base / "hy_paper_trading.json").read_text())
    assert len(hy["positions"]) == 1
    assert "intraday_actions" not in hy


def test_daily_red_without_movement_is_not_a_trigger(base):
    """Обратный контроль границы ADR-114: суточный house-view RED (без движения
    сенсоров) даёт no_increase, но НЕ MOVEMENT_DERISK — актор не дублирует цикл."""
    _quiet(base)
    (base / "investment_os").mkdir()
    _write(base, "investment_os/chief_investment.json", {
        "status": "ok",
        "generated_at": _NOW.isoformat(),
        "house_view": {"overall_posture": "RED"},
    })
    _write(base, "hy_paper_trading.json",
           _book([{"protocol": "pendle", "apy_pct": 14.0, "notional_usd": 25_000.0}]))

    report = intraday_actor.run_intraday_actor(base, now=_NOW)

    assert report["triggered"] is False
    hy = json.loads((base / "hy_paper_trading.json").read_text())
    assert len(hy["positions"]) == 1


def test_unreadable_sleeve_skipped_neighbour_processed(base):
    _movement(base)
    (base / "hy_paper_trading.json").write_text("{ not json", encoding="utf-8")
    _write(base, "lp_paper_trading.json",
           _book([{"protocol": "curve_3pool", "apy_pct": 7.0, "notional_usd": 25_000.0}]))

    report = intraday_actor.run_intraday_actor(base, now=_NOW)

    assert report["sleeves"]["B"]["action"] == "skipped"
    assert "unreadable" in report["sleeves"]["B"]["why"]
    assert report["sleeves"]["C"]["action"] == "closed"
    lp = json.loads((base / "lp_paper_trading.json").read_text())
    assert lp["positions"] == []


def test_missing_sleeve_named_not_crash(base):
    _movement(base)
    report = intraday_actor.run_intraday_actor(base, now=_NOW)
    assert report["sleeves"]["B"]["action"] == "skipped"
    assert report["sleeves"]["B"]["why"] == "book missing"


def test_dry_run_writes_nothing(base):
    _movement(base)
    _write(base, "hy_paper_trading.json",
           _book([{"protocol": "pendle", "apy_pct": 14.0, "notional_usd": 25_000.0}]))
    before = (base / "hy_paper_trading.json").read_text()

    report = intraday_actor.run_intraday_actor(base, now=_NOW, dry_run=True)

    assert report["sleeves"]["B"]["action"] == "would_close"
    assert (base / "hy_paper_trading.json").read_text() == before


def test_rtmr_posture_also_triggers(base):
    """Второй непрерывный сигнал ADR-104 (RTMR ≠ NORMAL) — тоже движение."""
    _quiet(base)
    _write(base, "monitoring/risk_posture.json", {"portfolio": "DEFENSIVE"})
    _write(base, "lp_paper_trading.json",
           _book([{"protocol": "aerodrome", "apy_pct": 11.0, "notional_usd": 25_000.0}]))

    report = intraday_actor.run_intraday_actor(base, now=_NOW)

    assert report["triggered"] is True
    assert report["sleeves"]["C"]["action"] == "closed"
