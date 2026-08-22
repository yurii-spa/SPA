"""Тесты paper-NAV бухгалтера BTC-движка (ADR-118).

Герметично: свой tmp data-dir, часы — вход с обеих сторон, сети и движка нет
(бухгалтер по построению читает только файл-сигнал продюсера).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.paper_trading import btc_nav

_NOW = datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock (обе стороны — вход)


def _write_signal(base, *, w=0.42, price=60_000.0, as_of="2026-08-22",
                  generated_at=None, regime="accumulation", **extra):
    doc = {"generated_at": (generated_at or _NOW.isoformat()),
           "as_of": as_of, "target_share_w": w, "btc_price_usd": price,
           "regime": regime, "engine_version": "v0.1-k0.7", **extra}
    p = base / "btc_cycle"
    p.mkdir(parents=True, exist_ok=True)
    (p / "target_share.json").write_text(json.dumps(doc), encoding="utf-8")


def _book(base):
    return json.loads((base / "btc_paper_trading.json").read_text(encoding="utf-8"))


@pytest.fixture()
def base(tmp_path):
    return tmp_path


def test_fresh_signal_seeds_the_book_and_rebalances_to_target(base):
    _write_signal(base, w=0.42, price=60_000.0)
    rep = btc_nav.run_btc_nav_tick(base, now=_NOW)
    assert rep["action"] == "booked"
    b = _book(base)
    assert b["equity_usdt"] == btc_nav.SEED_EQUITY_USDT
    assert b["btc_units"] == pytest.approx(0.42 * 25_000.0 / 60_000.0)
    assert b["usdt_cash"] == pytest.approx(0.58 * 25_000.0)
    assert b["IS_ADVISORY"] is True
    assert b["daily_history"][-1]["date"] == "2026-08-22"
    assert b["decisions"][-1]["to_share"] == 0.42  # из кэша 0.0 в 0.42 — решение


def test_same_day_second_tick_is_idempotent(base):
    _write_signal(base)
    btc_nav.run_btc_nav_tick(base, now=_NOW)
    rep2 = btc_nav.run_btc_nav_tick(base, now=_NOW)
    assert rep2["action"] == "noop"
    assert len(_book(base)["daily_history"]) == 1


def test_price_move_changes_nav_math_exactly(base):
    """Цена выросла на 10% при доле 0.42 → NAV вырос ровно на 4.2%."""
    _write_signal(base, w=0.42, price=60_000.0, as_of="2026-08-22")
    btc_nav.run_btc_nav_tick(base, now=_NOW)
    nxt = _NOW + timedelta(days=1)
    _write_signal(base, w=0.42, price=66_000.0, as_of="2026-08-23",
                  generated_at=nxt.isoformat())
    rep = btc_nav.run_btc_nav_tick(base, now=nxt)
    assert rep["nav_usdt"] == pytest.approx(25_000.0 * 1.042, rel=1e-9)
    b = _book(base)
    assert b["peak_equity_usdt"] == pytest.approx(25_000.0 * 1.042, rel=1e-9)
    assert b["drawdown_pct"] == 0.0
    # доля 0.42 не сдвинулась заметно — нового РЕШЕНИЯ в журнале нет
    assert len(b["decisions"]) == 1


def test_drawdown_measured_from_peak(base):
    _write_signal(base, w=1.0, price=60_000.0, as_of="2026-08-22")
    btc_nav.run_btc_nav_tick(base, now=_NOW)
    nxt = _NOW + timedelta(days=1)
    _write_signal(base, w=1.0, price=54_000.0, as_of="2026-08-23",
                  generated_at=nxt.isoformat())
    btc_nav.run_btc_nav_tick(base, now=nxt)
    b = _book(base)
    assert b["drawdown_pct"] == pytest.approx(10.0, rel=1e-6)
    assert b["peak_equity_usdt"] == pytest.approx(25_000.0)


def test_no_signal_records_one_gap_and_invents_nothing(base):
    rep = btc_nav.run_btc_nav_tick(base, now=_NOW)
    assert rep["action"] == "gap"
    assert "no signal" in rep["reason"]
    rep2 = btc_nav.run_btc_nav_tick(base, now=_NOW)  # тот же день — не шторм
    assert rep2["action"] == "gap"
    b = _book(base)
    assert len(b["gaps"]) == 1
    assert b["daily_history"] == []          # NAV не выдуман ни разу
    assert b["equity_usdt"] == btc_nav.SEED_EQUITY_USDT


def test_stale_signal_is_a_gap_not_a_booking(base):
    old = (_NOW - timedelta(hours=31)).isoformat()
    _write_signal(base, generated_at=old, as_of="2026-08-21")
    rep = btc_nav.run_btc_nav_tick(base, now=_NOW)
    assert rep["action"] == "gap"
    assert "stale" in rep["reason"]
    assert _book(base)["daily_history"] == []


def test_bad_price_and_bad_share_fail_closed(base):
    _write_signal(base, price=-1.0)
    assert btc_nav.run_btc_nav_tick(base, now=_NOW)["action"] == "gap"
    _write_signal(base, w=1.5)
    rep = btc_nav.run_btc_nav_tick(base, now=_NOW)
    assert rep["action"] == "gap"
    assert "out of [0,1]" in rep["reason"]


def test_dry_run_writes_nothing(base):
    _write_signal(base)
    rep = btc_nav.run_btc_nav_tick(base, now=_NOW, dry_run=True)
    assert rep["action"] == "would_book"
    assert not (base / "btc_paper_trading.json").exists()


def test_unreadable_signal_is_a_gap_never_a_crash(base):
    p = base / "btc_cycle"
    p.mkdir(parents=True)
    (p / "target_share.json").write_text("{ not json", encoding="utf-8")
    rep = btc_nav.run_btc_nav_tick(base, now=_NOW)
    assert rep["action"] == "gap"


def test_book_never_touches_main_track_files(base):
    """Обратный контроль границы ADR-118: тик пишет ТОЛЬКО свою книгу."""
    _write_signal(base)
    btc_nav.run_btc_nav_tick(base, now=_NOW)
    written = {f.name for f in base.rglob("*") if f.is_file()}
    assert written == {"target_share.json", "btc_paper_trading.json"}
