# FROZEN-DATE-OK: injected-clock — build_report_data принимает now=, фикстуры
# start_date и дата отчёта выведены из одного якоря; календарь на вердикт не влияет.
"""Дневной отчёт показывает ВСЕ ТРИ пакета и общую картину (запрос владельца 2026-08-31).

До этого дневной Telegram-отчёт видел только Conservative-книгу — Balanced и
Aggressive не упоминались вовсе, хотя оба ведут реальный трек с 23.08 (ADR-125).
Числа обязаны совпадать с тем, что дашборд уже считает (/api/live/books, phase B):
эти тесты кормят ОБЕ реализации одной фикстурой и сверяют выводы — дрейф двух
копий парсинга краснит тест, а не живёт молча.

RM-TRUTH-01 W5 (ADR-580 C2, 2026-10-05): фикстуры этого файла переписаны вместе с
``spa_core/reporting/books_summary.py``. Прежние фикстуры (``seed_equity``/``equity``/
``start_date``, без ``daily_history``/``economics_model``) кормили ЛИНЕЙНУЮ
аннуализацию по номинальному якорю — тот самый механизм, который на проде держал
Balanced −4.36% / Aggressive 1.36% ниже Conservative 4.15% (A3 §2, D1). Новые
фикстуры несут v2-помеченную историю ADR-531/533, а короткие/немаркированные —
проверяют, что НЕЗРЕЛАЯ книга честно отвечает ``None`` + ``accumulating``, а не
выдуманным числом. Намеренное изменение теста (инв. #16): старое поведение само
было дефектом, который этот цикл чинит по прямому заданию (применяет уже принятые
ADR-531/548, не вводит новое публичное число).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from spa_core.reporting.books_summary import collect_books_summary
from spa_core.reporting.daily_telegram_report import build_report_data, format_daily_message

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)

#: Та же граница зрелости, что в books_summary.py (REPORTABLE_AFTER, ADR-533/537) —
#: число НЕ перепечатывается литералом, а проверяется через саму библиотеку, чтобы
#: смена порога не рассинхронизировала фикстуры и код молча.
from spa_core.defi_engine.package_status import REPORTABLE_AFTER as _MATURITY_DAYS


def _mature_v2_history(final_equity: float, n: int = _MATURITY_DAYS,
                        start: str = "2026-09-01") -> list[dict]:
    """``n`` честных (``sleeve-econ-v2``, ``positions_count>0``) дней, линейно
    двигающих equity от $100k до *final_equity* — достаточно, чтобы пройти
    30-дневный порог зрелости (ADR-531/533)."""
    d0 = date.fromisoformat(start)
    seed = 100000.0
    out = []
    for i in range(n):
        frac = i / (n - 1) if n > 1 else 1.0
        eq = seed + (final_equity - seed) * frac
        out.append({
            "date": (d0 + timedelta(days=i)).isoformat(),
            "equity": round(eq, 2),
            "positions_count": 2,
            "economics_model": "sleeve-econ-v2",
        })
    return out


def _evidenced_bars(final_equity: float, n: int = 70,
                     start_equity: float = 100000.0, start: str = "2026-06-22") -> list[dict]:
    """``n`` evidenced-бар equity_curve_daily.json, линейно от *start_equity* до
    *final_equity* — тот же вход, который ``compound_apy.compound_annualized_pct``
    читает у настоящей книги."""
    d0 = date.fromisoformat(start)
    out = []
    for i in range(n):
        frac = i / (n - 1) if n > 1 else 1.0
        eq = start_equity + (final_equity - start_equity) * frac
        out.append({"date": (d0 + timedelta(days=i)).isoformat(), "equity": round(eq, 2),
                     "evidenced": True, "drawdown_pct": 0.0})
    return out


def _seed_three_books(ddir: Path) -> None:
    (ddir / "equity_curve_daily.json").write_text(json.dumps({
        "summary": {
            "start_equity": 100000.0, "end_equity": 101123.06,
            "total_return_pct": 1.1231, "num_days": 70,
        },
        "daily": _evidenced_bars(101123.06, n=70),
    }), encoding="utf-8")
    (ddir / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100174.78, "start_date": "2026-08-23",
        "daily_history": _mature_v2_history(100174.78),
    }), encoding="utf-8")
    (ddir / "lp_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100213.89, "start_date": "2026-08-23",
        "daily_history": _mature_v2_history(100213.89),
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
    """Два НЕЗАВИСИМЫХ файла (``books_summary.py`` / ``live.py``) обязаны выдать
    ОДНО и то же число и статус для ОДНОГО и того же документа — ADR-580 C1.
    До RM-TRUTH-01 W5 они расходились по ФОРМУЛЕ (линейная, разный якорь) — само
    расхождение было проявлением дефекта A3 §2/D1, не только риском его появления.
    Теперь обе копии зовут ОДИН общий ``sleeve_track_view`` + ``compound_apy``, так
    что дрейф возможен только на уровне ЭТОГО файла (две копии всё ещё не делят
    FastAPI-импорт, инвариант #4), не внутри формулы."""
    from spa_core.api.routers.live import _book_from_seed_equity as live_parser
    from spa_core.reporting.books_summary import _book_from_seed_equity as report_parser
    doc = {
        "seed_equity": 100000.0, "equity": 100291.48, "start_date": "2026-06-22",
        "daily_history": _mature_v2_history(100291.48),
    }
    ours = report_parser("Balanced", doc)
    theirs = live_parser("Balanced", doc)
    assert ours["annualized_apy_pct"] is not None
    assert ours["annualized_apy_pct"] == theirs["annualized_apy_pct"]
    assert ours["status"] == theirs["status"] == "paper_test_running"


# ─── аннуализация v2/current-experiment/maturity-gated (ADR-531/533/567 C2) ──


def test_v1_rows_never_blend_into_the_realized_rate(tmp_path):
    """ADR-531 вариант A: дни модели ``sleeve-econ-v1`` (искажены выявленным
    дефектом учёта газа — ADR-530 P0-1) НЕ смешиваются со днями v2 в одну
    ставку — число считается ТОЛЬКО по v2. Старый якорный баг (анализ 02.09:
    аннуализация по номинальному ``start_date`` вместо реального первого дня
    начисления) был частным случаем того же класса «посторонние дни внутри
    окна»; теперь граница — явная (поле ``economics_model``), не подразумеваемая
    (дата)."""
    v1_rows = [{"date": f"2026-08-{d:02d}", "equity": 100000.0 - d, "positions_count": 1}
               for d in range(1, 10)]  # без economics_model => v1 по определению, теряет деньги
    v2_rows = _mature_v2_history(100500.0, start="2026-09-10")
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100500.0, "start_date": "2026-06-22",
        "daily_history": v1_rows + v2_rows,
    }), encoding="utf-8")
    result = collect_books_summary(tmp_path)
    b = result["books"]["balanced"]
    assert b["annualized_apy_pct"] is not None
    # v2-дни одни прибыльны; если бы убыточные v1-дни молча подмешались, ставка
    # ушла бы в минус или сильно упала — она должна остаться позитивной.
    assert b["annualized_apy_pct"] > 0, b["annualized_apy_pct"]
    assert b["annualized_apy_pct_rate"]["window_days"] == _MATURITY_DAYS


def test_immature_book_is_null_and_accumulating_not_a_guessed_rate(tmp_path):
    """RM-TRUTH-01 W5 (ADR-531/533/567 C2): книга младше 30 валидных дней честно
    отвечает ``annualized_apy_pct: None`` + ``status: accumulating`` — НЕ
    экстраполированной ставкой короткого окна (тот механизм и держал на проде
    Balanced −4.36% / Aggressive 1.36% ниже Conservative, A3 §2/D1)."""
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100291.48, "start_date": "2026-06-22",
        "daily_history": _mature_v2_history(100291.48, n=9, start="2026-08-24"),
    }), encoding="utf-8")
    result = collect_books_summary(tmp_path)
    b = result["books"]["balanced"]
    assert b["annualized_apy_pct"] is None
    assert b["status"] == "accumulating"
    assert b["days_with_positions"] == 9
    assert b["annualized_apy_pct_rate"]["reportable"] is False


def test_no_history_is_not_started_not_a_guessed_rate(tmp_path):
    """Без ``daily_history`` (книга заведена, но ни дня начисления ещё не было) —
    статус ``not_started`` и ставка ``None`` — НЕ старый фоллбэк на номинальный
    ``start_date`` (тот подставлял видимость ставки там, где начисления не было
    вовсе: 63 дня простоя читались как 63 дня трека)."""
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100050.0, "start_date": "2026-08-31",
    }), encoding="utf-8")
    result = collect_books_summary(tmp_path, now=NOW)
    b = result["books"]["balanced"]
    assert b["annualized_apy_pct"] is None
    assert b["status"] == "not_started"


def test_daily_message_shows_annualized_rate_next_to_cumulative(tmp_path):
    """Дневной отчёт обязан показывать годовую ставку РЯДОМ с накопленным %,
    иначе за короткий трек накопленный % выглядит «смешно», хотя ставка
    нормальная. Conservative несёт ≥2 evidenced-бара (ставка идёт оттуда,
    compound/evidenced — не из ``summary.num_days``); Balanced младше 30
    валидных дней и честно показывает «накапливается», а не число."""
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({
        "summary": {"start_equity": 100000.0, "end_equity": 101123.06,
                    "total_return_pct": 1.1231, "num_days": 70},
        "daily": _evidenced_bars(101123.06, n=10),
    }), encoding="utf-8")
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({
        "seed_equity": 100000.0, "equity": 100291.48, "start_date": "2026-06-22",
        "daily_history": [{"date": "2026-08-24", "equity": 100291.48, "positions_count": 1,
                            "economics_model": "sleeve-econ-v2"}],
    }), encoding="utf-8")
    data = build_report_data("2026-08-31", data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)
    assert "год." in msg  # Conservative: годовая ставка подписана, не только накопленный %
    assert "накапливается" in msg  # Balanced: честно «пока нет числа», не выдумано


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


def test_advisory_books_annualized_rate_is_marked_paper(tmp_path):
    """Аудит 08.09: «~11.4%/~13.9% год.» у Balanced/Aggressive читались как живая
    доходность. Эти книги советующие (капитал не двигают, инвариант #9) —
    ставка обязана нести пометку; у Conservative (сам трек) пометки нет."""
    _seed_three_books(tmp_path)
    data = build_report_data("2026-08-31", data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)
    by_line = {ln.strip().split(":")[0].lstrip("• "): ln for ln in msg.splitlines() if "год." in ln}
    assert "Balanced" in by_line and "(paper, капитал не двигают)" in by_line["Balanced"]
    assert "Aggressive" in by_line and "(paper, капитал не двигают)" in by_line["Aggressive"]
    assert "Conservative" in by_line and "капитал не двигают" not in by_line["Conservative"]


def test_no_expired_phase_literal_and_headers_are_russian(tmp_path):
    """Строка «Phase 1: monitoring without capital → until 2026-07-12» истекла и
    ничего не читала; шапки — русские (аудит 08.09). Числа не меняются."""
    _seed_three_books(tmp_path)
    (tmp_path / "golive_status.json").write_text(json.dumps({
        "passed": 29, "total": 29, "real_track_days": 77, "evidenced_anchor": "2026-06-22",
    }), encoding="utf-8")
    data = build_report_data("2026-08-31", data_dir=tmp_path, now=NOW)
    msg = format_daily_message(data)
    assert "until 2026-07-12" not in msg
    assert "Base Chain (наблюдение без капитала)" in msg
    assert "подтверждённых дней 77 (с 2026-06-22)" in msg
    assert "30-дневный трек набран ✅" in msg
    for english in ("Portfolio:", "Positions:", "GoLive:", "Paper APY:"):
        assert english not in msg, english
