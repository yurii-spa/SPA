# FROZEN-DATE-OK: injected-clock — build_report_data принимает now=, дата бара выведена
# из того же якоря; календарь на вердикт не влияет.
"""Утренний отчёт называет ПРИЧИНУ упавшего APY рядом с самой цифрой (ADR-298/299).

С ADR-298 позиция под ненаблюдаемой ставкой начисляет ноль. Владелец увидит в отчёте
меньшее число — и без причины рядом решит, что испортился рынок, а не что мы перестали
записывать в доход то, чего не наблюдали.

Молчание строки тоже проверяется: когда вся книга наблюдаема, объяснять нечего, и лишняя
строка каждое утро была бы шумом.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from spa_core.reporting.daily_telegram_report import build_report_data, format_daily_message

NOW = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)


def _seed(ddir: Path, *, unobservable: list[str], forgone: float, apy: float, expected: float) -> None:
    bar = {
        "date": "2026-09-10", "open_equity": 101251.32, "close_equity": 101260.0,
        "equity": 101260.0, "apy_today": apy, "apy_expected_pct": expected,
        "daily_yield_usd": 8.6833, "cost_usd": 0.0,
        "unobservable_pools": unobservable, "yield_forgone_usd": forgone,
        "positions": {"compound_v3": 40000.0, "pendle": 20000.0},
    }
    (ddir / "equity_curve_daily.json").write_text(json.dumps({
        "summary": {"start_equity": 100000.0, "end_equity": 101260.0,
                    "total_return_pct": 1.26, "num_days": 79},
        "daily": [bar],
    }), encoding="utf-8")


def test_the_reason_is_printed_next_to_the_number(tmp_path):
    _seed(tmp_path, unobservable=["pendle"], forgone=4.3836, apy=3.1302, expected=4.7098)
    data = build_report_data(data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)
    assert "pendle" in msg, "пул с ненаблюдаемой ставкой обязан быть НАЗВАН"
    assert "не наблюдается" in msg
    assert "НОЛЬ" in msg, "владелец должен прочитать, что позиция начисляет ноль, а не продана"
    # и ожидание рядом — чтобы цена ненаблюдаемости была видна, а не додумывалась
    assert "4.71" in msg or "4,71" in msg


def test_a_fully_observable_book_says_nothing_extra(tmp_path):
    """Положительный контроль в обратную сторону: без ненаблюдаемых строки НЕТ.

    Иначе тест выше проходил бы и на строке, которая печатается всегда.
    """
    _seed(tmp_path, unobservable=[], forgone=0.0, apy=4.7098, expected=4.7098)
    msg = format_daily_message(build_report_data(data_dir=tmp_path, now=NOW))
    assert "не наблюдается" not in msg


def test_the_position_line_says_the_registry_rate_is_not_earned(tmp_path):
    """Ставка из справочника рядом с позицией, которая НЕ начисляет, — тихая неправда.

    В блоке позиций `pendle` печатался как «8.0% APY», хотя с ADR-298 он даёт ноль.
    Число стои́т, денег с него нет — и это заметнее всего именно в списке позиций.
    """
    _seed(tmp_path, unobservable=["pendle"], forgone=4.3836, apy=3.1302, expected=4.7098)
    (tmp_path / "adapter_status.json").write_text(json.dumps({"adapters": {
        "pendle": {"display_name": "Pendle Finance", "apy": 8.0},
        "compound_v3": {"display_name": "Compound V3", "apy": 4.05},
    }}), encoding="utf-8")
    msg = format_daily_message(build_report_data(data_dir=tmp_path, now=NOW))
    pend = [l for l in msg.split("\n") if "Pendle" in l]
    assert pend, "строки позиции нет — предпосылка теста не обеспечена"
    assert "начисляет 0" in pend[0], pend[0]
    comp = [l for l in msg.split("\n") if "Compound" in l]
    assert comp and "начисляет 0" not in comp[0], (
        "наблюдаемая позиция не должна получать эту пометку")
