# FROZEN-DATE-OK: injected-clock — build_report_data принимает now=, фикстуры
# start_date и дата отчёта выведены из одного якоря; календарь на вердикт не влияет.
"""Дневной отчёт показывает ВСЕ ТРИ пакета и общую картину (запрос владельца 2026-08-31).

До этого дневной Telegram-отчёт видел только Conservative-книгу — Balanced и
Aggressive не упоминались вовсе, хотя оба ведут реальный трек с 23.08 (ADR-125).
Числа обязаны совпадать с тем, что дашборд уже считает (/api/live/books, phase B):
эти тесты кормят ОБЕ реализации одной фикстурой и сверяют выводы — дрейф двух
копий парсинга краснит тест, а не живёт молча.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from spa_core.reporting.books_summary import collect_books_summary
from spa_core.reporting.daily_telegram_report import build_report_data, format_daily_message

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)


def _seed_three_books(ddir: Path) -> None:
    (ddir / "equity_curve_daily.json").write_text(json.dumps({"summary": {
        "start_equity": 100000.0, "end_equity": 101123.06,
        "total_return_pct": 1.1231, "num_days": 70,
    }}), encoding="utf-8")
    (ddir / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100174.78, "start_date": "2026-08-23",
    }), encoding="utf-8")
    (ddir / "lp_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100213.89, "start_date": "2026-08-23",
    }), encoding="utf-8")


# ─── collect_books_summary (данные) ─────────────────────────────────────────


def test_all_three_books_collected_and_combined(tmp_path):
    _seed_three_books(tmp_path)
    result = collect_books_summary(tmp_path)
    assert result["books"]["conservative"]["equity"] == 101123.06
    assert result["books"]["balanced"]["equity"] == 100174.78
    assert result["books"]["aggressive"]["equity"] == 100213.89
    c = result["combined"]
    assert c["books_available"] == 3
    assert c["total_seed_usd"] == 300000.0
    assert c["total_equity_usd"] == round(101123.06 + 100174.78 + 100213.89, 2)
    # доллары, не среднее процентов
    assert c["combined_return_pct"] == round((c["total_equity_usd"] / 300000.0 - 1) * 100, 4)


def test_missing_book_is_named_not_zeroed(tmp_path):
    _seed_three_books(tmp_path)
    (tmp_path / "lp_paper_trading.json").unlink()
    result = collect_books_summary(tmp_path)
    assert result["books"]["aggressive"]["available"] is False
    assert result["books"]["aggressive"]["reason"] == "file_missing"
    # сумма — только по доступным, и это ВИДНО
    assert result["combined"]["books_available"] == 2
    assert result["combined"]["total_seed_usd"] == 200000.0


def test_corrupt_book_degrades_that_book_only(tmp_path):
    _seed_three_books(tmp_path)
    (tmp_path / "hy_paper_trading.json").write_text("{broken", encoding="utf-8")
    result = collect_books_summary(tmp_path)
    assert result["books"]["balanced"]["available"] is False
    assert result["books"]["conservative"]["available"] is True
    assert result["combined"]["books_available"] == 2


def test_zero_seed_book_excluded_from_combined_no_divide_by_zero(tmp_path):
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 0.0, "equity": 500.0, "start_date": "2026-08-23",
    }), encoding="utf-8")
    result = collect_books_summary(tmp_path)  # не падает
    assert result["books"]["balanced"]["return_pct"] is None
    assert result["combined"]["books_available"] == 0


def test_unavailable_book_with_numbers_still_excluded_from_combined():
    """Сегодня ни один producer не создаёт available:False С числами — поэтому
    проверка `available` в фильтре не фальсифицируема через файлы (класс
    «guard untested when default makes it redundant»). Пиним её напрямую:
    книга, помеченная недоступной, не участвует в сумме, какие бы числа она
    ни несла."""
    from spa_core.reporting.books_summary import _combine_books
    books = {
        "conservative": {"label": "Conservative", "available": True,
                         "seed_equity": 100000.0, "equity": 101000.0},
        "balanced": {"label": "Balanced", "available": False, "reason": "stale",
                     "seed_equity": 100000.0, "equity": 999999.0},  # числа есть, доверия нет
    }
    c = _combine_books(books)
    assert c["books_available"] == 1
    assert c["total_equity_usd"] == 101000.0  # 999999 не просочилось


def test_combined_return_is_dollar_weighted_not_average_of_percents(tmp_path):
    """НЕРАВНЫЕ seed'ы — на равных ($100k каждый) среднее процентов совпадает с
    долларовой суммой ПО СОВПАДЕНИЮ, и мутация «среднее вместо суммы» невидима.
    Та же ловушка уже задокументирована в тестах /api/live/books."""
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 110000.0, "start_date": "2026-08-23",
    }), encoding="utf-8")  # +10%
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps({
        "seed_equity": 300000.0, "equity": 303000.0, "start_date": "2026-08-23",
    }), encoding="utf-8")  # +1%
    c = collect_books_summary(tmp_path)["combined"]
    # среднее (+10% и +1%) было бы +5.5%; долларовая правда — +3.25%
    assert c["combined_return_pct"] == 3.25
    assert c["combined_return_pct"] != 5.5


# ─── сверка с дашбордом: одна фикстура — одни числа ─────────────────────────


def test_report_numbers_match_the_dashboard_endpoint(tmp_path, monkeypatch):
    """Две копии парсинга (books_summary и /api/live/books) кормятся одной
    фикстурой и обязаны выдать одинаковые NAV/сумму — дрейф краснит здесь."""
    import importlib
    fastapi_testclient = __import__("pytest").importorskip("fastapi.testclient")
    _seed_three_books(tmp_path)

    ours = collect_books_summary(tmp_path)

    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    import spa_core.api.server as server
    importlib.reload(server)
    with fastapi_testclient.TestClient(server.app) as client:
        theirs = client.get("/api/live/books").json()

    for key in ("conservative", "balanced", "aggressive"):
        assert ours["books"][key]["equity"] == theirs["books"][key]["equity"], key
        assert ours["books"][key]["return_pct"] == theirs["books"][key]["return_pct"], key
    assert ours["combined"]["total_equity_usd"] == theirs["combined"]["total_equity_usd"]
    assert ours["combined"]["combined_return_pct"] == theirs["combined"]["combined_return_pct"]


def test_annualized_anchor_logic_matches_between_the_two_copies():
    """``annualized_apy_pct`` зависит от ``now`` — сравнивать через живой
    FastAPI-эндпоинт (два независимых чтения часов) флаково на границе суток.
    Пинуем НАПРЯМУЮ: те же вход + тот же явный ``now`` в обе копии функции
    ``_book_from_seed_equity`` (books_summary.py и live.py) обязаны выдать
    одно и то же — дрейф якорной логики между копиями краснит здесь, не в
    полночь по UTC где-то в CI."""
    from spa_core.api.routers.live import _book_from_seed_equity as live_parser
    from spa_core.reporting.books_summary import _book_from_seed_equity as report_parser
    doc = {
        "seed_equity": 100000.0, "equity": 100291.48, "start_date": "2026-06-22",
        "daily_history": [{"date": "2026-08-24"}, {"date": "2026-09-01"}],
    }
    ours = report_parser("Balanced", doc, now=NOW)
    theirs = live_parser("Balanced", doc, now=NOW)
    assert ours["annualized_apy_pct"] is not None
    # Разные формулы (books_summary: линейная; live.py: сложная) расходятся на
    # короткого окна на пару пп — это НЕ предмет теста. Предмет — якорь: если
    # бы одна копия молча вернулась к start_date (63д простоя), а другая
    # осталась на daily_history (9д), разрыв был бы на ПОРЯДОК (~15% vs ~1.5%),
    # не в разы. Порог с большим запасом от формульного шума (замерено: 1.19пп).
    assert abs(ours["annualized_apy_pct"] - theirs["annualized_apy_pct"]) < 5.0


# ─── аннуализация: якорь — реальный первый день, не номинальный start_date ──


def test_annualized_rate_uses_real_accrual_anchor_not_stale_start_date(tmp_path):
    """Прод-разрыв 02.09.2026: ``start_date`` книги — 2026-06-22, а позиции
    реально открылись только 2026-08-24 (63 дня простоя между ними). Старая
    аннуализация делила накопленный % на весь интервал ОТ start_date — это
    превращало реальную ставку ~10-13% годовых в видимость ~1.5%. Фикс:
    якорь — первый день ``daily_history``, а не ``start_date``. ``now``
    пинуется явно (время — вход, не окружение, deployment.md)."""
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100291.48, "start_date": "2026-06-22",
        "daily_history": [{"date": "2026-08-24"}, {"date": "2026-09-01"}],
    }), encoding="utf-8")
    result = collect_books_summary(tmp_path, now=NOW.replace(day=2, month=9))
    ann = result["books"]["balanced"]["annualized_apy_pct"]
    assert ann is not None
    # 9 дней от якоря 2026-08-24 до запиненного «сейчас» 2026-09-02 — на
    # 63-дневном (start_date) якоре число было бы < 2%; на реальном — двузначное.
    assert ann > 8.0, ann


def test_annualized_rate_falls_back_to_start_date_when_no_history(tmp_path):
    """Без daily_history (день открытия книги == первый учётный день) —
    старое поведение сохраняется, не регрессия."""
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100050.0, "start_date": "2026-08-31",
    }), encoding="utf-8")
    result = collect_books_summary(tmp_path, now=NOW)
    assert result["books"]["balanced"]["annualized_apy_pct"] is not None


def test_daily_message_shows_annualized_rate_next_to_cumulative(tmp_path):
    """Дневной отчёт обязан показывать годовую ставку РЯДОМ с накопленным %,
    иначе за 9 дней трека +0.29% выглядит «смешно», хотя ставка нормальная."""
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"summary": {
        "start_equity": 100000.0, "end_equity": 101123.06,
        "total_return_pct": 1.1231, "num_days": 70,
    }}), encoding="utf-8")
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100291.48, "start_date": "2026-06-22",
        "daily_history": [{"date": "2026-08-24"}],
    }), encoding="utf-8")
    data = build_report_data("2026-08-31", data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)
    assert "год." in msg  # годовая ставка подписана, не только накопленный %


# ─── format_daily_message (доставка владельцу) ──────────────────────────────


def test_daily_message_carries_all_three_books_and_total(tmp_path):
    _seed_three_books(tmp_path)
    data = build_report_data("2026-08-31", data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)
    assert "Пакеты" in msg
    assert "Conservative" in msg
    assert "Balanced" in msg
    assert "Aggressive" in msg
    assert "Σ Всего" in msg
    assert "$301,512" in msg  # 101123.06+100174.78+100213.89 округлённое


def test_daily_message_partial_sum_is_labelled_partial(tmp_path):
    _seed_three_books(tmp_path)
    (tmp_path / "lp_paper_trading.json").unlink()
    data = build_report_data("2026-08-31", data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)
    assert "Aggressive: недоступно" in msg
    assert "ЧАСТИЧНАЯ (2 из 3" in msg


def test_daily_message_survives_empty_data_dir(tmp_path):
    data = build_report_data("2026-08-31", data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)  # не падает; секция честно показывает недоступность
    assert "недоступно" in msg
