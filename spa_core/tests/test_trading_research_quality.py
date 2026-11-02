"""Мандат 01.11 §2.3: forward против HOLD за то же окно, свежесть рыночных данных, поправка на отбор (DSR).

Контроль в обе стороны у каждого вопроса: сравнение с HOLD — число на непрерывном окне и INCOMPLETE на дыре;
свежесть — FRESH / STALE / UNKNOWN; DSR — сильная стратегия отличима от удачи, лучший из ста шумов — нет
(ровно то, что прячет «выбрали лучший из 138»)."""
import random
import sqlite3

from spa_core.studio_os import trading_engines as te
from spa_core.trading_research import research_quality as rq

H = 3_600_000


def _obs(rows):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE observations (candidate_id TEXT, bar_open_time INT, bar_close_time INT, bar_open REAL, "
              "bar_close REAL, equity REAL, gap_bars INT)")
    c.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?)", rows)
    return c


def test_forward_is_compared_with_hold_over_the_same_window_after_costs():
    # 3 бара 1h: цена 100 → 110; кандидат закончил с equity 1.05
    c = _obs([("x", 0, H, 100.0, 104.0, 1.01, 0), ("x", H, 2 * H, 104.0, 107.0, 1.03, 0),
              ("x", 2 * H, 3 * H, 107.0, 110.0, 1.05, 0)])
    v = rq.forward_vs_hold(c, "x", "1h")
    assert v["state"] == rq.MEASURED and v["bars"] == v["expected_bars"] == 3
    hold = 110 / 100 * (1 - 0.0015) - 1                       # одна сторона spot: 10 + 5 bps
    assert abs(v["hold_net"] - round(hold, 6)) < 1e-9 and abs(v["forward_net"] - 0.05) < 1e-9
    assert abs(v["excess_vs_hold"] - round(0.05 - hold, 6)) < 1e-6 and v["excess_vs_hold"] < 0


def test_a_window_with_a_hole_is_incomplete_not_a_number():
    c = _obs([("x", 0, H, 100.0, 104.0, 1.0, 0), ("x", 2 * H, 3 * H, 104.0, 110.0, 1.0, 0)])   # бар 1 пропущен
    v = rq.forward_vs_hold(c, "x", "1h")
    assert v["state"] == rq.INCOMPLETE and "hold_net" not in v
    c2 = _obs([("x", 0, H, 100.0, 104.0, 1.0, 1)])                                           # gap_bars > 0
    assert rq.forward_vs_hold(c2, "x", "1h")["state"] == rq.INCOMPLETE
    assert rq.forward_vs_hold(_obs([]), "x", "1h")["state"] == rq.UNKNOWN


def _market(open_time):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE candles (symbol TEXT, tf TEXT, open_time INT)")
    if open_time is not None:
        c.execute("INSERT INTO candles VALUES ('BTCUSDT','1h',?)", (open_time,))
    return c


def test_market_data_freshness_has_three_outcomes():
    now = 100 * H
    assert rq.market_freshness(_market(now - 2 * H), now)["state"] == "FRESH"          # закрылась час назад
    assert rq.market_freshness(_market(now - 5 * H), now)["state"] == "STALE"
    assert rq.market_freshness(_market(None), now)["state"] == rq.UNKNOWN
    assert rq.market_freshness(sqlite3.connect(":memory:"), now)["state"] == rq.UNKNOWN   # схемы нет


def _results(n_noise, strong=None, days=400, seed=7):
    rnd = random.Random(seed)
    out = [{"id": f"noise{i}", "oos_daily_returns": {str(d): rnd.gauss(0, 0.02) for d in range(days)}}
           for i in range(n_noise)]
    if strong is not None:
        out.append({"id": "strong", "oos_daily_returns": {str(d): rnd.gauss(strong, 0.02) for d in range(days)}})
    return out


def test_dsr_tells_a_real_edge_from_the_best_of_many_noises():
    res = _results(100, strong=0.006)
    best_noise = max((r for r in res if r["id"].startswith("noise")),
                     key=lambda r: sum(r["oos_daily_returns"].values()))["id"]
    d = rq.deflated_sharpe(res, ["strong", best_noise])
    assert d["state"] == rq.MEASURED and d["trials_tested"] == 101
    assert d["candidates"]["strong"]["distinguishable_from_luck"] is True
    assert d["candidates"][best_noise]["distinguishable_from_luck"] is False      # лучший из ста — всё равно удача


def test_dsr_without_enough_data_is_unknown_not_zero():
    short = [{"id": "a", "oos_daily_returns": {"1": 0.01, "2": 0.02}}]
    d = rq.deflated_sharpe(short, ["a"])
    assert d["state"] == rq.UNKNOWN and d["candidates"] == {}


def test_effective_trials_shrink_with_correlation():
    rnd = random.Random(1)
    base = {str(d): rnd.gauss(0, 0.02) for d in range(200)}
    clones = [{"id": f"c{i}", "oos_daily_returns": dict(base)} for i in range(10)]
    assert abs(rq.effective_trials(clones) - 1.0) < 1e-6                         # одна идея в десяти копиях
    indep = _results(10, days=200, seed=3)
    assert rq.effective_trials(indep) > 8.5


def test_cockpit_card_names_hypothesis_control_trust_and_never_sums():
    st = {"research_quality": {
        "market_data": {"state": "STALE", "age_minutes": 300.0},
        "selection": {"all_trials": {"trials_tested": 138, "candidates": {"a": {"state": "MEASURED", "dsr": 0.003}}},
                      "effective_trials": {"trials_used": 91.4,
                                           "candidates": {"a": {"state": "MEASURED", "dsr": 0.006}}}}}}
    card = te._research_card(st, [{"id": "a"}])
    assert "HOLD BTC" in card["control"] and "после издержек" in card["hypothesis"]
    assert "ни один" in card["selection"]["text"] and "УСТАРЕЛИ" in card["data"]["text"]
    empty = te._research_card({}, [])
    assert "НЕ ИЗМЕРЕНА" in empty["selection"]["text"] and empty["data"]["state"] == "UNKNOWN"
    assert te._vs_hold(None)["state"] == "UNKNOWN"
    m = te._vs_hold({"state": "MEASURED", "forward_net": -0.04, "hold_net": -0.07, "excess_vs_hold": 0.03, "bars": 31})
    assert m["text"].startswith("лучше HOLD на 3.0 п.п.")


def _bt(tmp, name, code, sharpe):
    import json as _j
    p = tmp / name
    p.write_text(_j.dumps({"manifest": {"code_version": code}, "results": [
        {"id": "c1", "in_sample": {"bars": 10, "net_return": 0.1, "sharpe": sharpe, "max_drawdown": -0.1, "trades": 3},
         "out_of_sample": {}, "gating": {}}]}))
    return p


def test_closed_windows_are_stable_across_data_updates_and_a_rewrite_is_named(tmp_path):
    a = _bt(tmp_path, "backtest_1.json", "v1", 0.5)
    b = _bt(tmp_path, "backtest_2.json", "v1", 0.5)
    assert rq.closed_window_stability([a, b])["state"] == "STABLE"
    c = _bt(tmp_path, "backtest_3.json", "v1", 0.9)                       # то же прошлое, другое число
    r = rq.closed_window_stability([a, b, c])
    assert r["state"] == "REWRITTEN" and r["changed"][0]["window"] == "in_sample"
    d = _bt(tmp_path, "backtest_4.json", "v2", 0.9)                       # смена кода — не переписывание
    assert rq.closed_window_stability([a, d])["state"] == rq.UNKNOWN
