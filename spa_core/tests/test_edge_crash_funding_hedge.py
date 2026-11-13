"""Контроли прибора #158 CFH (`scripts/edge_crash_funding_hedge.py`).

Реальные ряды `data/rates_desk/` в git не лежат, поэтому каждый контроль — СИНТЕТИЧЕСКАЯ сцена
с известным ответом, и у каждого вопроса прибора (канал · величина · портфель) есть сцена,
где вердикт срабатывает, и сцена, где он НЕ должен. Положительный контроль хеджа — мир, где
implied yield падает на 5 pp в каждый крах при длинном сроке: там прибор ОБЯЗАН сказать
«хедж пригоден»; отрицательный — мир с неподвижной ставкой, где марка тождественно ноль.

# FROZEN-DATE-OK: fixture-subject — ДАТЫ здесь являются ПРЕДМЕТОМ: календарь синтетических
# сцен и шов TRAIN/TEST конвенции #153 — входные данные прибора. Понятия СВЕЖЕСТИ на его пути
# нет (ни `now()`, ни `today()`), сдвиг календаря не меняет ни один вердикт.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "edge_crash_funding_hedge", ROOT / "scripts" / "edge_crash_funding_hedge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


H = _load()
D = datetime.date
START = D(2024, 6, 1)
N_DAYS = 760


def _dates():
    return [START + datetime.timedelta(days=i) for i in range(N_DAYS)]


def _write_world(tmp_path: Path, *, crashes, y_drop_per_crash: float, y0: float = 0.15,
                 float_yield: float = 0.10, maturity_years: int = 3,
                 funding_crash: float = -0.0001) -> Path:
    """Мир: ETH падает на 2.5 %/день внутри окон `crashes`, иначе +0.1 %/день; funding 1 bp/день
    в норме и −1 bp в крах; implied yield одного длинного рынка PT падает ступенью на y_drop в
    ПОСЛЕДНИЙ день каждого окна (к этому дню 7-дневное правило крах уже видит)."""
    dates = _dates()
    crash_days = set()
    for s, n in crashes:
        for i in range(n):
            crash_days.add(s + datetime.timedelta(days=i))
    eth, fund, series = {}, {}, []
    p, y = 1000.0, y0
    for d in dates:
        in_crash = d in crash_days
        p *= 0.975 if in_crash else 1.001
        eth[d.isoformat()] = p
        fund[d.isoformat()] = funding_crash if in_crash else 0.0001
        if any(d == s + datetime.timedelta(days=n - 1) for s, n in crashes):
            y -= y_drop_per_crash
        series.append({"date": d.isoformat(), "implied_yield": round(y, 8), "pt_price": None,
                       "tvl_usd": 1e6, "underlying_yield": float_yield})
    mat = D(START.year + maturity_years, 12, 31)
    (tmp_path / "prices_deep.json").write_text(json.dumps({"series": {"eth": eth}}))
    (tmp_path / "funding_deep.json").write_text(json.dumps({"series": fund}))
    (tmp_path / "pendle_pt_history.json").write_text(json.dumps({"markets": {
        "PT-sUSDE-LONG": {"underlying": "sUSDe", "maturity": mat.isoformat(), "series": series},
        "PT-weETH-X": {"underlying": "weETH", "maturity": mat.isoformat(), "series": series[:5]},
    }}))
    return tmp_path


CRASHES = [(D(2024, 8, 1), 6), (D(2025, 2, 1), 6), (D(2025, 10, 1), 6), (D(2026, 2, 1), 6)]


# ── §0 формула марки ──────────────────────────────────────────────────────────────────────

def test_pt_price_is_discount_at_the_implied_rate():
    assert H.pt_price(0.10, 1.0) == pytest.approx(1 / 1.1)
    assert H.pt_price(0.10, 0.0) == pytest.approx(1.0)


def test_decomposition_sums_and_isolates_the_rate_move():
    total, carry, mark = H.decompose_day(0.10, 0.08, 365, 364)
    assert total == pytest.approx(carry + mark)
    assert carry > 0                       # срок ушёл на день при той же ставке — pull-to-par
    assert mark > 0                        # ставка упала — фиксированная нога подорожала
    _, carry0, mark0 = H.decompose_day(0.10, 0.10, 365, 364)
    assert mark0 == pytest.approx(0.0, abs=1e-15)   # ставка стоит — марка ровно ноль
    assert carry0 == pytest.approx(carry)
    _, _, mark_up = H.decompose_day(0.10, 0.12, 365, 364)
    assert mark_up < 0                     # ставка выросла — PT подешевел


def test_mark_scales_with_time_to_maturity():
    _, _, short = H.decompose_day(0.10, 0.09, 30, 29)
    _, _, long = H.decompose_day(0.10, 0.09, 700, 699)
    assert long > short * 10


# ── §1 ряд PT: самый длинный живой рынок, перекат без P&L ─────────────────────────────────

def test_series_picks_the_longest_live_market_and_rolls_without_pnl():
    s = [{"date": "2025-01-01", "implied_yield": 0.1, "underlying_yield": 0.05},
         {"date": "2025-01-02", "implied_yield": 0.1, "underlying_yield": 0.05},
         {"date": "2025-01-03", "implied_yield": 0.1, "underlying_yield": 0.05}]
    markets = {
        "SHORT": {"underlying": "sUSDe", "maturity": "2025-01-10", "series": s},        # < 14 дней — не живой
        "MID": {"underlying": "sUSDe", "maturity": "2025-06-30", "series": s[:2]},
        "LONG": {"underlying": "sUSDe", "maturity": "2025-12-31", "series": s[1:]},     # появляется 02.01
    }
    rows = H.build_pt_series(markets)
    # вход в самый длинный живой (MID; LONG ещё не торгуется, SHORT не живой); держим MID,
    # пока он наблюдается; 03.01 MID исчез ⇒ перекат в LONG без P&L
    assert [r["market"] for r in rows] == ["MID", "MID", "LONG"]
    assert rows[0]["rolled"] is False and rows[0]["total"] is None       # первый день — вход
    assert rows[1]["rolled"] is False and rows[1]["total"] is not None   # второй день в MID — доход
    assert rows[1]["mark"] == pytest.approx(0.0, abs=1e-15)             # ставка не двигалась
    assert rows[2]["rolled"] is True and rows[2]["total"] is None        # перекат — без P&L
    assert rows[0]["float_daily"] == pytest.approx(0.05 / 365)


def test_entry_prefers_the_LONGEST_of_two_live_markets():
    """Выживший мутант пробы #158: `max` → `min` не ловился, потому что на входе был один живой рынок."""
    s = [{"date": "2025-01-01", "implied_yield": 0.1, "underlying_yield": 0.05},
         {"date": "2025-01-02", "implied_yield": 0.1, "underlying_yield": 0.05}]
    markets = {"MID": {"underlying": "sUSDe", "maturity": "2025-06-30", "series": s},
               "LONG": {"underlying": "sUSDe", "maturity": "2025-12-31", "series": s}}
    rows = H.build_pt_series(markets)
    assert [r["market"] for r in rows] == ["LONG", "LONG"]


def test_series_refuses_a_market_without_maturity_and_an_empty_roster():
    with pytest.raises(H.Unmeasured):
        H.build_pt_series({"X": {"underlying": "sUSDe", "series": [{"date": "2025-01-01", "implied_yield": 0.1}]}})
    with pytest.raises(H.Unmeasured):
        H.build_pt_series({"X": {"underlying": "sUSDe", "maturity": "2025-12-31", "series": []}})


def test_float_daily_is_the_median_across_markets_of_the_day():
    s = lambda u: [{"date": "2025-01-01", "implied_yield": 0.1, "underlying_yield": u}]   # noqa: E731
    markets = {f"M{i}": {"underlying": "sUSDe", "maturity": "2025-12-31", "series": s(u)}
               for i, u in enumerate([0.02, 0.10, 0.04])}
    rows = H.build_pt_series(markets)
    assert rows[0]["float_daily"] == pytest.approx(0.04 / 365)


# ── §2 крах: дни и эпизоды ────────────────────────────────────────────────────────────────

def test_crash_days_use_the_7d_threshold_and_bridge_gaps():
    prices = {D(2025, 1, 1) + datetime.timedelta(days=i): 100.0 for i in range(20)}
    for i in range(8, 20):
        prices[D(2025, 1, 1) + datetime.timedelta(days=i)] = 85.0     # −15 % против 7 дней назад
    del prices[D(2025, 1, 2)]                                           # пропуск в ряде
    days = H.crash_days(prices, -10.0)
    assert D(2025, 1, 9) in days          # 85 против 100: 02.01 пропущен — мост на 8..10 дней назад
    assert D(2025, 1, 10) in days         # 85 против 100 (03.01)
    assert D(2025, 1, 8) not in days      # ещё 100 — до падения
    assert D(2025, 1, 16) not in days     # 85 против 85 (09.01) — краха уже нет


def test_episodes_cluster_within_the_gap_and_split_beyond_it():
    days = [D(2025, 1, 1), D(2025, 1, 3), D(2025, 1, 8), D(2025, 1, 20)]
    eps = H.cluster_episodes(days, gap_days=5)
    assert [len(e) for e in eps] == [3, 1]


# ── §3 канал и величина: контроль в обе стороны ────────────────────────────────────────────

def test_positive_control_a_big_rate_drop_in_every_crash_makes_a_usable_hedge(tmp_path):
    H_dir = _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05)
    r = H.build_report(H_dir)
    v = r["verdict"]
    assert v["channel_direction_confirmed"] is True
    assert v["n_episodes"] == len(CRASHES)
    assert v["median_hedge_ratio"] > 0.25
    assert v["notionals_for_half_hedge"] <= 2.0
    assert v["hedge_is_usable"] is True
    assert "кандидат" in v["answer"]


def test_negative_control_a_frozen_rate_has_no_channel_and_no_hedge(tmp_path):
    H_dir = _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.0)
    r = H.build_report(H_dir)
    v = r["verdict"]
    assert v["channel_direction_confirmed"] is False       # Δy и марка в крах НЕ отличаются от нормы
    assert v["hedge_is_usable"] is False
    assert "НЕ подтверждён" in v["answer"]
    assert r["channel"]["crash"]["mark_mean"] == pytest.approx(0.0, abs=1e-12)


def test_negative_control_rates_fall_but_funding_does_not_so_the_channel_is_not_the_funding_one(tmp_path):
    """Выживший мутант пробы #158: снятие условия по funding не меняло ни одной сцены. Сцена, где
    ставка PT падает в крах, а funding НЕ ниже обычного: это другой канал, и прибор обязан сказать
    «НЕ подтверждён», а не продать падение ставки как funding-хедж."""
    H_dir = _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05, funding_crash=0.0001)
    r = H.build_report(H_dir)
    assert r["channel"]["crash"]["mark_mean"] > r["channel"]["normal"]["mark_mean"]   # марка выше — да
    assert r["channel"]["crash"]["funding_mean"] == pytest.approx(r["channel"]["normal"]["funding_mean"])
    assert r["verdict"]["channel_direction_confirmed"] is False
    assert r["verdict"]["hedge_is_usable"] is False
    assert "НЕ подтверждён" in r["verdict"]["answer"]


def test_a_real_but_tiny_channel_is_named_as_direction_yes_magnitude_no(tmp_path):
    """Форма реального замера: знак верный, величина — десятки номиналов."""
    H_dir = _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.002, maturity_years=1)
    r = H.build_report(H_dir)
    v = r["verdict"]
    assert v["channel_direction_confirmed"] is True
    assert v["hedge_is_usable"] is False
    assert v["notionals_for_half_hedge"] > 2.0
    assert "хеджем это не является" in v["answer"]


def test_episode_rows_carry_the_independent_count_and_the_year_decay(tmp_path):
    H_dir = _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05)
    ch = H.build_report(H_dir)["channel"]
    assert ch["n_episodes"] == 4 and len(ch["episodes"]) == 4
    assert sorted(ch["by_year"]) == [2024, 2025, 2026]
    assert ch["by_year"][2025]["episodes"] == 2
    for e in ch["episodes"]:
        assert e["eth_drop_from_pre"] < -0.05 and e["pt_mark_cum"] > 0 and e["hedge_ratio"] > 0


# ── §4 портфель: пошлина ДОХОДИТ до чисел ─────────────────────────────────────────────────

def test_the_toll_reaches_the_portfolio_numbers_and_the_float_control_shares_the_carry(tmp_path):
    H_dir = _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05)
    prices = H.load_eth_prices(H_dir)
    pt = H.build_pt_series(H.load_pt_markets(H_dir))
    a, b = D(2024, 6, 1), D(2026, 6, 1)
    with_toll = H.simulate(prices, pt, a, b, leg="pt", toll_bps=96.0)
    no_toll = H.simulate(prices, pt, a, b, leg="pt", toll_bps=0.0)
    assert no_toll[0] > with_toll[0]                      # пошлина применена, а не только объявлена
    cash = H.simulate(prices, pt, a, b, leg="cash", toll_bps=96.0)
    flt = H.simulate(prices, pt, a, b, leg="float", toll_bps=96.0)
    assert flt[0] > cash[0]                               # плавающая нога начисляет
    assert with_toll[1] < flt[1]                          # выпуклость: PT срезает просадку против плавающей
    with pytest.raises(ValueError):
        H.simulate(prices, pt, a, b, leg="gold")


def test_the_roll_toll_reaches_the_numbers_not_only_the_entry_toll():
    """Выживший мутант пробы #158: обнуление пошлины ПЕРЕКАТА не меняло ни одной сцены, потому что
    в синтетическом мире был один рынок и ни одного переката. Сцена с перекатом — здесь."""
    prices = {D(2025, 1, 1): 100.0, D(2025, 1, 2): 100.0, D(2025, 1, 3): 100.0}
    pt = [{"date": D(2025, 1, 1), "total": None, "rolled": False, "float_daily": None},
          {"date": D(2025, 1, 2), "total": None, "rolled": True, "float_daily": None},   # перекат
          {"date": D(2025, 1, 3), "total": 0.0, "rolled": False, "float_daily": None}]
    sim = lambda toll: H.simulate(prices, pt, D(2025, 1, 1), D(2025, 1, 3), leg="pt", toll_bps=toll)   # noqa: E731
    # цены стоят, доход PT ноль ⇒ весь результат — пошлины: вход (100 %) и перекат (на 50 % ноги)
    apy_toll, dd_toll, _ = sim(96.0)
    apy_free, dd_free, _ = sim(0.0)
    assert dd_free == pytest.approx(0.0)
    assert dd_toll == pytest.approx(0.5 * 0.0096 * 100.0, rel=1e-6)   # просадка ровно = пошлина переката на половине
    assert apy_toll < apy_free
    cash_toll = H.simulate(prices, pt, D(2025, 1, 1), D(2025, 1, 3), leg="cash", toll_bps=96.0)
    assert cash_toll[1] == pytest.approx(0.0)                           # у кэша перекатов нет — пошлина только на входе


def test_portfolio_section_has_train_test_full_and_three_legs(tmp_path):
    H_dir = _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05)
    p = H.build_report(H_dir)["portfolio"]
    assert len(p["results"]) == 3
    names = list(p["results"])
    assert names[0].startswith("TRAIN") and names[1].startswith("TEST") and names[2].startswith("FULL")
    for res in p["results"].values():
        assert len(res) == 3
        for apy, dd, cal in res.values():
            assert math.isfinite(apy) and dd >= 0


# ── §5 три исхода различимы ───────────────────────────────────────────────────────────────

def test_unmeasured_when_a_file_is_missing_or_the_roster_has_no_susde(tmp_path):
    with pytest.raises(H.Unmeasured):
        H.build_report(tmp_path)                                  # файлов нет
    _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05)
    doc = json.loads((tmp_path / "pendle_pt_history.json").read_text())
    doc["markets"] = {k: v for k, v in doc["markets"].items() if v["underlying"] != "sUSDe"}
    (tmp_path / "pendle_pt_history.json").write_text(json.dumps(doc))
    with pytest.raises(H.Unmeasured):
        H.build_report(tmp_path)


def test_unmeasured_when_there_are_too_few_crash_episodes(tmp_path):
    _write_world(tmp_path, crashes=[(D(2025, 2, 1), 6)], y_drop_per_crash=0.05)
    with pytest.raises(H.Unmeasured, match="эпизодов краха"):
        H.build_report(tmp_path)


def test_cli_exit_2_on_unreadable_dir_and_json_on_success(tmp_path, capsys):
    assert H.main(["--rates-dir", str(tmp_path / "nope")]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err
    _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05)
    assert H.main(["--rates-dir", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) >= {"inputs", "channel", "portfolio", "verdict", "is_advisory", "outside_riskpolicy"}
    assert doc["is_advisory"] is True and doc["outside_riskpolicy"] is True


def test_human_output_prints_the_tail_next_to_the_rate(tmp_path, capsys):
    _write_world(tmp_path, crashes=CRASHES, y_drop_per_crash=0.05)
    assert H.main(["--rates-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "maxDD" in out and "APY" in out and "эпизодах" in out
    assert "data/ только читается" in out
