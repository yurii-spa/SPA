"""Контроли прибора #165 DNS / #166 LDG (`scripts/edge_duration_liquidity_pt.py`).

Реальный ряд `data/rates_desk/pendle_pt_history.json` в git не лежит, поэтому каждый
контроль — СИНТЕТИЧЕСКАЯ сцена с известным ответом, и у каждого утверждения прибора есть
сцена, где вердикт срабатывает, и сцена, где он срабатывать НЕ ДОЛЖЕН:

* мир с ИНВЕРТИРОВАННОЙ кривой и марочным шумом ∝ τ ⇒ DNS обязана бить покупку-и-держание;
* мир с ПЛОСКОЙ кривой и τ-независимым шумом ⇒ DNS обязана НЕ бить (она просто держит меньше);
* тот же первый мир с пошлиной 500 bp ⇒ выигрыш обязан исчезнуть (граница по пошлине);
* мир, где TVL действительно предсказывает марку ⇒ знаковый тест обязан увидеть;
* мир без связи TVL и марки ⇒ обязан НЕ увидеть.

# FROZEN-DATE-OK: fixture-subject — ДАТЫ здесь ПРЕДМЕТ: календарь синтетических сцен и шов
# TRAIN/TEST — входные данные прибора. Понятия СВЕЖЕСТИ на его пути нет (ни `now()`, ни
# `today()`), сдвиг календаря не меняет ни один вердикт.
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
        "edge_duration_liquidity_pt", ROOT / "scripts" / "edge_duration_liquidity_pt.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


E = _load()
H = E.H
D = datetime.date


def _day(base: D, i: int) -> str:
    return (base + datetime.timedelta(days=i)).isoformat()


def _scene(*, n_days=720, life=180, inverted=True, shock_tau=160, shock_size=0.10,
           shock_len=30, noise=0.002, base_rate=0.12, seed=1, float_rate=0.0,
           start=D(2024, 1, 1)):
    """Лента последовательных рынков одного актива с УПРАВЛЯЕМЫМ моментом удара.

    `shock_tau` — дюрация, НА КОТОРОЙ приходит скачок ставки. Это и есть условие
    механизма DNS: удар ∝ τ·w, и при w = D*/τ он постоянен, тогда как у держания
    он растёт с τ. Удар на БОЛЬШОЙ дюрации ⇒ DNS обязана выиграть; удар у самого
    погашения (τ мало, w = 1) ⇒ обязана проиграть. `inverted=True` — короткий конец
    платит больше (форма, измеренная #117). Детерминированный LCG: без numpy и random.
    """
    u = H.Underlying("SCENE")
    state = seed
    for i in range(n_days):
        day = _day(start, i)
        k = i // life
        mkt = f"PT-{k}"
        maturity = _day(start, (k + 1) * life)
        tau = H.days(day, maturity)
        if tau <= 0:
            continue
        state = (1103515245 * state + 12345) % (1 << 31)
        y = base_rate + (state / (1 << 31) - 0.5) * noise
        if inverted:
            y += -0.0006 * (tau - 60) / 30.0
        if shock_tau - shock_len < tau <= shock_tau:
            y += shock_size
        u.add(mkt, maturity, {"date": day, "implied_yield": max(0.005, y),
                              "tvl_usd": 5e6, "underlying_yield": float_rate})
    return u


def _run(u, weight, *, cost=0.0, select=None, start=None, end=None):
    return E.Sim(u, select=select or E.longest_live(), weight=weight,
                 cash_rate=E.cash_zero, roll_cost_bp=cost, start=start, end=end).run()


# ───────────────────────── тождество разложения (несущая часть #165) ─────────────────────────

def test_leg_step_decomposition_is_exact_not_approximate():
    y0, y1, tau, dt = 0.11, 0.13, 123.0, 1
    carry, mark = E.leg_step(y0, tau, y1, dt)
    lp = lambda y, t: -(t / 365.0) * math.log1p(y)  # noqa: E731
    assert carry + mark == pytest.approx(lp(y1, tau - dt) - lp(y0, tau), abs=1e-15)


def test_carry_does_not_depend_on_duration():
    """Несущий факт всей записи: carry на единицу номинала τ-независим."""
    short = E.leg_step(0.12, 20.0, 0.12, 1)[0]
    long_ = E.leg_step(0.12, 300.0, 0.12, 1)[0]
    assert short == pytest.approx(long_, abs=1e-15)


def test_mark_scales_linearly_with_duration():
    m50 = E.leg_step(0.10, 51.0, 0.11, 1)[1]
    m200 = E.leg_step(0.10, 201.0, 0.11, 1)[1]
    assert m200 / m50 == pytest.approx(200.0 / 50.0, rel=1e-12)


def test_dollar_duration_is_years_not_days():
    assert E.dollar_duration(365.0) == pytest.approx(1.0)


# ───────────────────────── третий исход (инв. #17) ─────────────────────────

def test_missing_series_is_unmeasured_not_empty(tmp_path):
    with pytest.raises(H.Unmeasured):
        H.load(tmp_path)


def test_empty_markets_is_unmeasured_not_zero(tmp_path):
    (tmp_path / "rates_desk").mkdir()
    (tmp_path / "rates_desk" / "pendle_pt_history.json").write_text(
        json.dumps({"markets": {}}))
    with pytest.raises(H.Unmeasured, match="markets empty"):
        H.load(tmp_path)


def test_too_short_window_is_unmeasured_not_zero():
    u = _scene(n_days=2)
    with pytest.raises(H.Unmeasured, match="нечего мерить"):
        _run(u, E.flat_weight(1.0))


def test_calmar_is_blocked_below_the_entry_toll():
    """Просадка ниже 96 bp ⇒ Calmar НЕ риск-взвешенная величина (урок #129): None, не число."""
    tiny = E._metrics([("2024-01-02", 0.0001), ("2024-01-03", -0.00002)])
    assert tiny["calmar"] is None and tiny["calmar_blocked"] is True
    big = E._metrics([("2024-01-02", 0.05), ("2024-01-03", -0.03)])
    assert big["calmar"] is not None and big["calmar_blocked"] is False


def test_the_rate_is_annualised_over_observed_days_not_calendar_span():
    """У sUSDe/sUSDS ряд содержит дыры: размах включил бы НЕНАБЛЮДЁННЫЕ дни и растянул
    ставку на них. Знаменатель — наблюдённые дни; размах печатается отдельно."""
    u = H.Underlying("HOLE")
    mat = "2027-12-31"
    for day in ("2024-01-01", "2024-01-02", "2024-01-03",
                "2024-06-01", "2024-06-02", "2024-06-03"):
        u.add("PT-H", mat, {"date": day, "implied_yield": 0.10, "tvl_usd": 5e6,
                            "underlying_yield": 0.0})
    r = _run(u, E.flat_weight(1.0))
    assert r["observed"] == 4 and r["span"] == 153
    # ставка стои́т, срок уходит ⇒ годовая ставка обязана выйти РОВНО implied_yield.
    # При знаменателе-размахе вышло бы 0.10·4/153 — то есть в 38 раз меньше.
    assert r["apy"] == pytest.approx(0.10, rel=1e-12)
    # вторая сцена — наблюдения ЧЕРЕЗ ДЕНЬ (dt = 2, внутри MAX_GAP_DAYS): наблюдённых
    # дней обязано быть 2 на шаг, а не 1. Иначе «observed += 1» неотличим (найдено прогоном).
    v = H.Underlying("STRIDE")
    for i in range(0, 40, 2):
        v.add("PT-S", mat, {"date": _day(D(2024, 1, 1), i), "implied_yield": 0.10,
                            "tvl_usd": 5e6, "underlying_yield": 0.0})
    rv = _run(v, E.flat_weight(1.0))
    assert rv["days"] == 19 and rv["observed"] == 38
    assert rv["apy"] == pytest.approx(0.10, rel=1e-12)


def test_a_hole_in_the_series_breaks_the_position_not_bridges_it():
    u = H.Underlying("GAP")
    mat = "2024-12-31"
    for day in ("2024-01-01", "2024-01-02", "2024-03-01", "2024-03-02"):
        u.add("PT-G", mat, {"date": day, "implied_yield": 0.1, "tvl_usd": 5e6,
                            "underlying_yield": 0.0})
    r = _run(u, E.flat_weight(1.0))
    assert r["breaks"] == 1, "разрыв шире MAX_GAP_DAYS обязан рвать наблюдение"
    assert r["days"] == 2


# ───────────────────────── полоса анти-черна ─────────────────────────

def test_zero_band_is_identical_to_plain_dns():
    u = _scene()
    plain = _run(u, E.dns_weight(60.0))
    banded = _run(u, E.BandWeight(60.0, 0.0))
    assert plain["apy"] == pytest.approx(banded["apy"], abs=1e-15)
    assert plain["turnover"] == pytest.approx(banded["turnover"], abs=1e-15)


def test_a_wider_band_buys_less_turnover():
    u = _scene()
    tight = _run(u, E.BandWeight(60.0, 0.0))["turnover"]
    wide = _run(u, E.BandWeight(60.0, 0.25))["turnover"]
    assert wide < tight


def test_a_negative_band_is_refused_not_clamped():
    with pytest.raises(ValueError):
        E.BandWeight(60.0, -0.01)


def test_the_sizer_memory_does_not_outlive_the_window():
    """Политика с памятью обязана сбрасываться: иначе TRAIN красит TEST.

    Сцена РАЗЛИЧАЮЩАЯ: один объект проходит сначала ПЕРВОЕ окно, потом второе, и его
    вердикт на втором обязан совпасть с вердиктом СВЕЖЕГО объекта на том же втором окне.
    Прогнать одно и то же окно дважды мало — там состояние конца и начала почти совпадают
    (мутация «reset снят» такую сцену ПЕРЕЖИЛА, найдено мутационным прогоном).
    """
    u = _scene()
    # шов НЕ кратен жизни рынка (180 дн) намеренно: на кратном дне дюрация та же,
    # что в первый день сцены, цель совпадает — и устаревший вес неотличим от свежего
    # (мутация «reset снят» пережила шов на дне 360, найдено прогоном)
    seam = _day(D(2024, 1, 1), 300)
    # полоса ШИРОКАЯ намеренно: при узкой устаревший вес на первом дне второго окна
    # всё равно уехал бы за полосу и перезаписался целью — сцена не различала бы
    # «сброс есть» от «сброса нет» (мутация пережила узкую полосу, найдено прогоном)
    used = E.BandWeight(60.0, 0.9)
    _run(u, used, end=seam)                       # окно 1 оставляет вес в памяти
    after = _run(u, used, start=seam)
    fresh = _run(u, E.BandWeight(60.0, 0.9), start=seam)
    assert after["apy"] == pytest.approx(fresh["apy"], abs=1e-15)
    assert after["turnover"] == pytest.approx(fresh["turnover"], abs=1e-15)


# ───────────────────────── DNS: сцена «обязана выиграть» и «обязана НЕ выиграть» ─────────────────────────

def test_dns_beats_buy_and_hold_when_the_blow_lands_on_long_duration():
    """Положительный контроль: удар приходит при τ ≈ 160 ⇒ держание получает его целиком."""
    u = _scene(shock_tau=160)
    bh = _run(u, E.flat_weight(1.0))
    dns = _run(u, E.dns_weight(60.0))
    assert bh["maxdd"] > 0.0096 and dns["maxdd"] > 0.0096, "обе просадки обязаны быть измеримы"
    assert dns["calmar"] > bh["calmar"], (dns["calmar"], bh["calmar"])
    assert dns["maxdd"] < bh["maxdd"]


def test_the_inverted_curve_raises_the_rate_dns_actually_holds():
    """Вторая, независимая улика механизма: вес смещён к КОРОТКОМУ концу, где ставка выше."""
    # сцена БЕЗ удара: иначе +10 pp, сидящие в полосе большой дюрации, сами поднимают
    # удерживаемую ставку держания и подменяют предмет (найдено прогоном, а не рассуждением)
    inv = _scene(inverted=True, shock_size=0.0)
    flat = _scene(inverted=False, shock_size=0.0)
    assert _run(inv, E.dns_weight(60.0))["y_held_w"] > _run(inv, E.flat_weight(1.0))["y_held_w"]
    assert _run(flat, E.dns_weight(60.0))["y_held_w"] == pytest.approx(
        _run(flat, E.flat_weight(1.0))["y_held_w"], rel=0.02), \
        "без инверсии удерживаемая ставка обязана СОВПАДАТЬ — иначе улика выдумана"


def test_dns_loses_when_the_blow_lands_near_maturity():
    """Отрицательный контроль того же прибора: удар при τ ≈ 30, где DNS держит ВЕСЬ капитал."""
    # удар крупнее: у самого погашения множитель τ/365 мал, и при +10 pp просадка
    # ОБЕИХ политик уходит под пошлину входа — сравнивать было бы нечего (#129)
    u = _scene(shock_tau=30, shock_len=20, shock_size=0.30)
    bh = _run(u, E.flat_weight(1.0))
    dns = _run(u, E.dns_weight(60.0))
    assert bh["maxdd"] > 0.0096 and dns["maxdd"] > 0.0096
    assert dns["calmar"] <= bh["calmar"], (dns["calmar"], bh["calmar"])


def test_the_flat_placebo_holds_the_same_average_weight():
    """Плацебо обязано отличаться от DNS ТОЛЬКО постоянством веса, иначе сравнение не о целении."""
    u = _scene()
    dns = _run(u, E.dns_weight(60.0))
    flat = _run(u, E.flat_weight(min(1.0, 60.0 / dns["mean_tau"])))
    assert flat["w_mean"] == pytest.approx(dns["w_mean"], rel=0.25)
    assert flat["turnover"] == pytest.approx(0.0, abs=1e-12)


def test_a_heavy_toll_destroys_the_dns_advantage():
    """Граница по пошлине: тот же мир, где DNS выигрывает, при 500 bp обязан её похоронить."""
    u = _scene(shock_tau=160)
    free_bh, free_dns = _run(u, E.flat_weight(1.0)), _run(u, E.dns_weight(60.0))
    paid_bh = _run(u, E.flat_weight(1.0), cost=500.0)
    paid_dns = _run(u, E.dns_weight(60.0), cost=500.0)
    assert free_dns["calmar"] > free_bh["calmar"]
    assert paid_dns["calmar"] < paid_bh["calmar"]
    assert paid_dns["fees_bp"] > free_dns["fees_bp"]


def test_anti_dns_is_the_mirror_and_loses_where_dns_wins():
    u = _scene(shock_tau=160)
    dns = _run(u, E.dns_weight(60.0))
    anti = _run(u, E.anti_dns_weight(60.0))
    assert anti["calmar"] < dns["calmar"], (anti["calmar"], dns["calmar"])
    assert anti["mean_tau"] == pytest.approx(dns["mean_tau"]), \
        "обе политики обязаны держать ТОТ ЖЕ рынок — различаться только весом"


def test_mark_vs_tau_control_sees_the_identity_it_must_see():
    sh = E.mark_vs_tau(_scene())
    assert sh["τ≥180"]["mark_vol_bp"] is None or sh["60≤τ<180"]["mark_vol_bp"] > \
        sh["τ<60"]["mark_vol_bp"], "марочный шум обязан расти с дюрацией"


# ───────────────────────── #166 ворота глубины ─────────────────────────

def _tvl_scene(rich_tvl=5e6, thin_tvl=1e4):
    """Два живых рынка: длинный ТОНКИЙ, короткий БОГАТЫЙ — ворота обязаны выбрать короткий."""
    u = H.Underlying("TVL")
    for i in range(40):
        day = _day(D(2024, 1, 1), i)
        u.add("PT-long", "2024-12-31", {"date": day, "implied_yield": 0.10,
                                        "tvl_usd": thin_tvl, "underlying_yield": 0.0})
        u.add("PT-short", "2024-06-30", {"date": day, "implied_yield": 0.10,
                                         "tvl_usd": rich_tvl, "underlying_yield": 0.0})
    return u


def test_the_gate_skips_a_thin_market_and_takes_the_next_one():
    u = _tvl_scene()
    pick = E.tvl_gated(1e6, require_growth=False, history=E.tvl_history(u))(
        "2024-01-10", u.legs("2024-01-10"))
    assert pick is not None and pick[3] == "PT-short"


def test_the_gate_refuses_when_every_market_is_thin():
    u = _tvl_scene(rich_tvl=1e4, thin_tvl=1e4)
    assert E.tvl_gated(1e6, require_growth=False, history=E.tvl_history(u))(
        "2024-01-10", u.legs("2024-01-10")) is None


def test_the_anti_gate_takes_exactly_what_the_gate_rejects():
    u = _tvl_scene()
    hist = E.tvl_history(u)
    gate = E.tvl_gated(1e6, require_growth=True, history=hist)
    anti = E.tvl_gated(1e6, require_growth=True, history=hist, invert=True)
    day = "2024-01-20"
    g, a = gate(day, u.legs(day)), anti(day, u.legs(day))
    assert g is not None and a is not None and g[3] != a[3]


def test_a_newborn_market_is_a_third_outcome_not_a_drained_one():
    """Нет наблюдения на lookback дней назад ⇒ рынок воротами НЕ судится (инв. #17)."""
    u = _tvl_scene()
    hist = E.tvl_history(u)
    gate = E.tvl_gated(1e6, require_growth=True, history=hist)
    assert gate("2024-01-01", u.legs("2024-01-01")) is None, \
        "в первый день истории роста нет ни у одного рынка — это НЕ ИЗМЕРЕНО, не «упал»"
    assert E.tvl_gated(1e6, require_growth=False, history=hist)(
        "2024-01-01", u.legs("2024-01-01")) is not None
    rich_only = _tvl_scene(rich_tvl=9e6, thin_tvl=8e6)   # пол проходят ОБА: судится только рост
    h2 = E.tvl_history(rich_only)
    day1 = "2024-01-01"
    assert E.tvl_gated(1e6, require_growth=True, history=h2)(
        day1, rich_only.legs(day1)) is None
    assert E.tvl_gated(1e6, require_growth=True, history=h2, invert=True)(
        day1, rich_only.legs(day1)) is None, \
        "НЕИЗМЕРЕННЫЙ рост не есть ОТВЕРГНУТЫЙ: его не берёт и АНТИ-гейт"


def test_tvl_information_is_seen_where_it_exists():
    """Положительный контроль §C1: мир, где сохнущий рынок ТЕРЯЕТ, обязан дать знак."""
    u = H.Underlying("INFO")
    mat = "2025-06-30"
    y, tvl = 0.10, 8e6
    for i in range(200):
        day = _day(D(2024, 6, 1), i)
        drying = (i // 40) % 2 == 1        # режим ДЕРЖИТСЯ 40 дней: прошлое изменение TVL
        tvl = tvl * (0.97 if drying else 1.03)   # предсказывает следующие 7 дней, а не спорит с ними
        y = y + (0.004 if drying else -0.001)          # сохнет ⇒ ставка растёт ⇒ марка ПАДАЕТ
        u.add("PT-I", mat, {"date": day, "implied_yield": max(0.01, y), "tvl_usd": tvl,
                            "underlying_yield": 0.0})
    c = E.tvl_conditional(u, floor_usd=1e6)
    assert c["n"] > 0 and c["independent"] < c["n"], "независимых винтажей обязано быть меньше n"
    assert c["indep"]["drain_mean_bp"] < c["indep"]["grow_mean_bp"]


def test_tvl_information_is_not_invented_where_it_is_absent():
    """Отрицательный контроль §C1: TVL шумит независимо от ставки ⇒ знака быть не должно."""
    u = H.Underlying("NOISE")
    mat = "2025-06-30"
    state = 7
    for i in range(200):
        day = _day(D(2024, 6, 1), i)
        state = (1103515245 * state + 12345) % (1 << 31)
        tvl = 5e6 * (1.0 + (state / (1 << 31) - 0.5) * 0.4)
        u.add("PT-N", mat, {"date": day, "implied_yield": 0.10, "tvl_usd": tvl,
                            "underlying_yield": 0.0})
    c = E.tvl_conditional(u, floor_usd=1e6)
    assert c["indep"]["drain_mean_bp"] == pytest.approx(0.0, abs=1e-9), \
        "неподвижная ставка ⇒ марка тождественно ноль в ОБЕИХ корзинах"


def test_the_rich_thin_axis_actually_splits_the_population():
    """Ось §C1 обязана делить: иначе «богат» и «тонк» — одна и та же корзина под двумя именами."""
    u = H.Underlying("SPLIT")
    mat = "2025-06-30"
    for i in range(120):
        day = _day(D(2024, 6, 1), i)
        u.add("PT-rich", mat, {"date": day, "implied_yield": 0.10, "tvl_usd": 9e6,
                               "underlying_yield": 0.0})
        u.add("PT-thin", mat, {"date": day, "implied_yield": 0.10, "tvl_usd": 2e4,
                               "underlying_yield": 0.0})
    c = E.tvl_conditional(u, floor_usd=1e6)
    assert c["all"]["rich_n"] > 0 and c["all"]["thin_n"] > 0
    assert c["all"]["rich_n"] + c["all"]["thin_n"] == c["n"]


def test_conditional_without_pairs_is_unmeasured_not_zero_information():
    u = H.Underlying("SHORT")
    u.add("PT-S", "2024-01-20", {"date": "2024-01-01", "implied_yield": 0.1,
                                 "tvl_usd": 5e6, "underlying_yield": 0.0})
    c = E.tvl_conditional(u)
    assert c["n"] == 0 and "НЕ ИЗМЕРЕНО" in c["unmeasured"]


# ───────────────────────── перепись и безрисковая нога ─────────────────────────

def test_census_counts_what_is_there_and_refuses_an_empty_series():
    res = E.section_census({"SCENE": _scene(n_days=100)})
    assert res["rows"][0]["obs"] > 0 and res["rows"][0]["tvl_null"] == 0
    with pytest.raises(H.Unmeasured):
        E.section_census({})


def test_a_missing_float_rate_is_not_invented():
    """USDe: `underlying_yield` = 0 ПО ПОСТРОЕНИЮ. Ставку выдумывать запрещено."""
    u = _scene(n_days=60, float_rate=0.0)
    assert u.has_float is False
    assert E.cash_float(u)("2024-01-15") == 0.0
    v = _scene(n_days=60, float_rate=0.05)
    assert v.has_float is True and E.cash_float(v)("2024-01-15") == pytest.approx(0.05)


def test_cash_leg_pays_only_the_unheld_part():
    """Кэш платит РОВНО на (1−w), и мерка — РАВЕНСТВО, а не «больше».

    Сцена — ОДИН рынок с далёким погашением и окно строго внутри его жизни: иначе в
    дни, когда ни один рынок не проходит порог входа, вес честно падает до нуля и
    кэш платит на весь капитал ВЕРНО — тогда равенство не сходится по причине, не
    имеющей отношения к предмету (найдено прогоном, а не рассуждением).
    """
    u = H.Underlying("CASH")
    for i in range(100):
        u.add("PT-C", "2026-12-31", {"date": _day(D(2024, 1, 1), i), "implied_yield": 0.10,
                                     "tvl_usd": 5e6, "underlying_yield": 0.0})
    w, r = 0.5, 0.10
    free = E.Sim(u, select=E.longest_live(), weight=E.flat_weight(w),
                 cash_rate=E.cash_zero, roll_cost_bp=0.0).run()
    paid = E.Sim(u, select=E.longest_live(), weight=E.flat_weight(w),
                 cash_rate=lambda _d: r, roll_cost_bp=0.0).run()
    gap = (math.log1p(paid["apy"]) - math.log1p(free["apy"])) * paid["observed"] / 365.0
    assert gap == pytest.approx((1.0 - w) * math.log1p(r) * paid["days"] / 365.0, rel=1e-9)
    assert paid["refusals"] == 0, "сцена обязана не иметь отказов, иначе мерка не о предмете"


def test_cli_returns_the_third_outcome_code_on_a_missing_series(tmp_path, capsys):
    rc = E.main(["--data-dir", str(tmp_path), "--section", "census"])
    assert rc == 2, "ряда нет ⇒ ненулевой код, а не «чисто»"
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err
