"""Trading Research Engine v0 — the properties the evidence depends on (ADR-525).

Hermetic: synthetic candles, an injected HTTP fake, tmp data dirs. No network, no live data/.
Clock: every time is a fixed epoch-ms anchor passed INTO the code under test.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from spa_core.trading_research import evidence as ev
from spa_core.trading_research import forward as fw
from spa_core.trading_research import lifecycle as lc
from spa_core.trading_research import market_data as md
from spa_core.trading_research import ranking as rk
from spa_core.trading_research import strategies as st
from spa_core.trading_research.execution import EXEC_MODELS, ExecModel, simulate
from spa_core.trading_research.market_data import HOUR_MS, Bar

T0 = 1_600_000_000_000 - (1_600_000_000_000 % (24 * HOUR_MS))       # a UTC midnight, epoch ms


def synth(n=3000, seed=7, t0=1_600_000_000_000):
    x, p, out = seed, 20000.0, []
    for i in range(n):
        x = (1103515245 * x + 12345) % 2 ** 31
        r = (x / 2 ** 31 - 0.5) * 0.02 + (0.0004 if (i // 700) % 2 == 0 else -0.0004)
        o = p; c = p * (1 + r); h = max(o, c) * 1.003; l = min(o, c) * 0.997
        out.append(Bar(t0 + i * HOUR_MS, o, h, l, c, 1.0)); p = c
    return out


def kline(b: Bar):
    return [b.open_time, str(b.open), str(b.high), str(b.low), str(b.close), str(b.volume),
            b.open_time + HOUR_MS - 1]


# ── market data ────────────────────────────────────────────────────────────────────────────────
def test_an_open_candle_is_never_stored(tmp_path):
    c = md.connect(tmp_path / "m.db")
    bars = synth(5, t0=T0)
    now = T0 + 3 * HOUR_MS + 10_000            # bar #3 closed 10 s ago (< grace), #4 is open
    assert md.store_closed_klines(c, "X", [kline(b) for b in bars], now_ms=now) == 2
    assert [b.open_time for b in md.load_1h(c, "X")] == [T0, T0 + HOUR_MS]


def test_stored_candles_are_immutable_and_refetch_conflicts_are_recorded(tmp_path):
    c = md.connect(tmp_path / "m.db")
    b = synth(1, t0=T0)[0]
    md.store_closed_klines(c, "X", [kline(b)], now_ms=T0 + 10 * HOUR_MS)
    changed = kline(b); changed[4] = str(b.close * 1.01)
    md.store_closed_klines(c, "X", [changed], now_ms=T0 + 11 * HOUR_MS)
    assert md.load_1h(c, "X")[0].close == pytest.approx(b.close)          # not applied
    assert c.execute("SELECT COUNT(*) FROM data_conflicts").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE candles SET close=1")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("DELETE FROM candles")


def test_aggregation_emits_only_complete_utc_buckets_and_reports_gaps():
    bars = synth(48, t0=T0)
    holed = bars[:5] + bars[6:]                                            # hour 5 missing
    four = md.aggregate(holed, "4h")
    assert [b.open_time for b in four][0] == T0 and all(b.open_time % (4 * HOUR_MS) == 0 for b in four)
    assert T0 + 4 * HOUR_MS not in [b.open_time for b in four]            # the holed bucket is dropped
    assert len(md.aggregate(bars, "1D")) == 2 and len(md.aggregate(holed, "1D")) == 1
    d = md.aggregate(bars[:24], "1D")[0]
    assert (d.open, d.close) == (bars[0].open, bars[23].close)
    assert d.high == max(b.high for b in bars[:24])
    assert md.gaps_1h(holed) == [{"after": T0 + 4 * HOUR_MS, "missing_hours": 1}]


# ── no look-ahead ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fam", sorted(st.FAMILIES))
def test_no_indicator_or_signal_looks_ahead(fam):
    bars = synth(1200)
    _, fn = st.FAMILIES[fam]
    p = st.GRIDS[fam][0]
    full = fn(bars, p)
    for t in (250, 400, 777, 1000, 1199):
        assert fn(bars[:t + 1], p)[t] == full[t], f"{fam} at {t} changed when the future was removed"


FINGERPRINTS = {
    "ma_cross@v1": "43eb121cd59a7202", "price_vs_ma@v1": "a0d837f73a0aa2bc",
    "momentum@v1": "2c44887498e6fce4", "donchian@v1": "e03c2636f3742bcd",
    "supertrend@v1": "a8915832d41f932d", "rsi_meanrev@v1": "a85e5467a266c7a9",
    "macd@v1": "76836a3062fa8386", "bollinger_meanrev@v1": "73a54c370545093f",
    "trend_vol_filter@v1": "14d108e33d613d1b", "supertrend_and_ma@v1": "5d55bab2b9bc2f98",
}


def test_family_fingerprints_are_pinned():
    """Changing a family's output WITHOUT bumping its version would silently rewrite what a candidate
    id means. Bump the version in strategies.FAMILIES, then update the fingerprint here."""
    bars = synth()
    got = {}
    for fam, grid in st.GRIDS.items():
        ver, fn = st.FAMILIES[fam]
        got[f"{fam}@v{ver}"] = hashlib.sha256(json.dumps(fn(bars, grid[0])).encode()).hexdigest()[:16]
    assert got == FINGERPRINTS


def test_a_new_version_is_a_new_identity():
    c = st.registry()[0]
    bumped = st.Candidate(c.family, c.family_version + 1, c.params, c.asset, c.timeframe, c.exec_model)
    assert bumped.id != c.id and bumped.def_hash != c.def_hash
    assert len({x.id for x in st.registry()}) == len(st.registry())


# ── execution timing, costs, funding, liquidation ──────────────────────────────────────────────
def _flat_bars(prices):
    return [Bar(T0 + i * HOUR_MS, p, p, p, p, 1.0) for i, p in enumerate(prices)]


def test_a_signal_on_bar_t_is_filled_at_the_open_of_bar_t_plus_1():
    bars = [Bar(T0, 100, 100, 100, 100, 1), Bar(T0 + HOUR_MS, 110, 121, 110, 121, 1),
            Bar(T0 + 2 * HOUR_MS, 121, 121, 121, 121, 1)]
    free = ExecModel("x", 1, 0.0, 0.0, allow_short=False)
    r = simulate(bars, [1, 1, 1], free, tf_ms=HOUR_MS)
    # target 1 decided at bar 0's close is filled at bar 1's OPEN (110), so the 100→110 gap is NOT earned
    assert r.equity[1] == pytest.approx(121 / 110)
    r0 = simulate(bars, [0, 1, 1], free, tf_ms=HOUR_MS)
    assert r0.equity[1] == pytest.approx(1.0)                             # decided at bar 1: not yet held


def test_costs_are_charged_per_side_on_traded_notional():
    bars = _flat_bars([100] * 5)
    m = EXEC_MODELS["spot_long"]
    r = simulate(bars, [1, 1, 0, 0, 0], m, tf_ms=HOUR_MS)
    # exec model v2: a fixed-size position — both legs pay the fee on the same traded notional qty·price
    assert r.equity[-1] == pytest.approx(1 - 2 * m.cost_per_side)
    assert simulate(bars, [1, 1, 0, 0, 0], m, tf_ms=HOUR_MS, cost_mult=0).equity[-1] == pytest.approx(1.0)


def test_funding_long_pays_short_receives():
    bars = _flat_bars([100] * 4)
    free = ExecModel("p", 1, 0.0, 0.0, allow_short=True, funding=True)
    f = [(T0 + 2 * HOUR_MS - 1, 0.001)]
    assert simulate(bars, [1] * 4, free, tf_ms=HOUR_MS, funding=f).equity[-1] == pytest.approx(0.999)
    assert simulate(bars, [-1] * 4, free, tf_ms=HOUR_MS, funding=f).equity[-1] == pytest.approx(1.001)
    # (open, open+tf]: a funding stamp exactly at a bar's open belongs to the PREVIOUS bar only
    edge = [(T0 + 2 * HOUR_MS, 0.001)]
    assert simulate(bars, [1] * 4, free, tf_ms=HOUR_MS, funding=edge).funding_paid == pytest.approx(0.001)


def test_a_short_loses_like_a_real_short_and_is_liquidated_near_2x():
    """Review 2026-09-30: per-bar re-scaling let a liquidated 1× short keep ~half its equity."""
    px = [100 * 1.007 ** i for i in range(120)]
    bars = [Bar(T0 + i * HOUR_MS, p, p * 1.001, p * 0.999, p, 1) for i, p in enumerate(px)]
    free = ExecModel("p", 1, 0.0, 0.0, allow_short=True)
    r = simulate(bars, [-1] * len(bars), free, tf_ms=HOUR_MS)
    assert r.liquidations == 1 and r.equity[-1] < 0.02
    mid = next(i for i, p in enumerate(px) if p >= 150)
    assert r.equity[mid] == pytest.approx(1 - (bars[mid].close / bars[1].open - 1), rel=1e-9)


def test_a_gap_through_liquidation_is_never_a_gain():
    bars = [Bar(T0, 100, 100, 100, 100, 1), Bar(T0 + HOUR_MS, 100, 100, 100, 100, 1),
            Bar(T0 + 2 * HOUR_MS, 300, 300, 300, 300, 1)]
    free = ExecModel("p", 1, 0.0, 0.0, allow_short=True)
    r = simulate(bars, [-1, -1, -1], free, tf_ms=HOUR_MS)
    assert r.liquidations == 1 and r.equity[-1] == 0.0


def test_a_round_trip_return_includes_both_fees():
    bars = _flat_bars([100] * 4)
    m = EXEC_MODELS["spot_long"]
    r = simulate(bars, [1, 0, 0, 0], m, tf_ms=HOUR_MS)
    assert r.trades[0]["ret"] == pytest.approx(r.equity[-1] - 1)


def test_leveraged_long_is_liquidated_and_spot_cannot_short():
    bars = [Bar(T0, 100, 100, 100, 100, 1), Bar(T0 + HOUR_MS, 100, 100, 40, 50, 1)]
    lev = ExecModel("p2", 1, 0.0, 0.0, allow_short=True, leverage=2.0)
    r = simulate(bars, [1, 1], lev, tf_ms=HOUR_MS)
    assert r.liquidations == 1 and r.position[-1] == 0
    spot = simulate(bars, [-1, -1], EXEC_MODELS["spot_long"], tf_ms=HOUR_MS)
    assert set(spot.position) == {0}


# ── evidence store ─────────────────────────────────────────────────────────────────────────────
def _obs(cid="c1", t=T0, eq=1.0):
    return {k: None for k in ev.OBS_FIELDS} | {
        "candidate_id": cid, "asset": "BTC", "timeframe": "1h", "bar_open_time": t, "bar_close_time": t + HOUR_MS,
        "signal_ts_ms": t + HOUR_MS, "late": 0, "gap_bars": 0, "bar_open": 1.0, "bar_close": 1.0,
        "position_before": 0, "fill_cost": 0.0, "funding": 0.0, "position_held": 0, "equity": eq, "target": 0,
        "action": "HOLD", "book_state": "{}", "assumptions": "{}", "data_ref": "r", "code_version": "v"}


def test_evidence_is_append_only_chained_and_forward_only(tmp_path):
    c = ev.connect(tmp_path / "e.db")
    assert ev.append_observation(c, _obs(t=T0))
    assert ev.append_observation(c, _obs(t=T0 + HOUR_MS))
    assert not ev.append_observation(c, _obs(t=T0 + HOUR_MS))            # same bar: nothing
    assert not ev.append_observation(c, _obs(t=T0 - HOUR_MS))            # the past: never
    ev.register(c, "c1", "h", {"x": 1}, now_ms=T0, code_version="v")
    ev.append_event(c, "c1", None, "DISCOVERED", "r", {}, actor="t", now_ms=T0)
    for sql in ("UPDATE observations SET equity=2", "DELETE FROM observations",
                "UPDATE candidates SET def_hash='x'", "DELETE FROM lifecycle_events"):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)
    assert ev.verify(c)["ok"]


def test_verify_names_a_tampered_record(tmp_path):
    c = ev.connect(tmp_path / "e.db")
    ev.append_observation(c, _obs(t=T0)); ev.append_observation(c, _obs(t=T0 + HOUR_MS))
    c.commit()
    c.execute("DROP TRIGGER observations_no_update")                      # an attacker, not the code
    c.execute("UPDATE observations SET equity=9 WHERE bar_open_time=?", (T0,))
    v = ev.verify(c)
    assert not v["ok"] and v["breaks"] == [f"observation c1@{T0}"]


# ── the forward tick end-to-end ────────────────────────────────────────────────────────────────
class FakeExchange:
    def __init__(self, bars):
        self.bars = bars

    def __call__(self, url, params, timeout=20.0):
        if "fundingRate" in url:
            return []
        s = params["startTime"]
        return [kline(b) for b in self.bars if b.open_time >= s][:params["limit"]]


def test_forward_tick_is_forward_only_idempotent_and_catches_up(tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_TRADING_DATA_DIR", str(tmp_path))
    bars = synth(6000, t0=md.FIRST_1H_MS)
    ex = FakeExchange(bars)
    one = [c for c in st.registry() if c.timeframe == "1h" and c.exec_model == "spot_long"][:3]
    monkeypatch.setattr(fw, "registry", lambda: one)
    monkeypatch.setattr(fw, "by_id", lambda: {c.id: c for c in one})
    monkeypatch.setattr(fw.bt, "registry", lambda: one)
    reg_at = bars[5000].open_time + 30 * 60_000                           # registered mid-bar 5000
    r1 = fw.tick(now_ms=reg_at, http=ex)
    assert r1["ok"] and r1["registered"] == 3 and r1["new_observations"] == 0
    later = bars[5010].open_time + HOUR_MS + 120_000                      # bar 5010 closed 2 min ago
    r2 = fw.tick(now_ms=later, http=ex)
    assert r2["new_observations"] == 3 * 10                               # bars 5001..5010, not 5000
    assert fw.tick(now_ms=later, http=ex)["new_observations"] == 0        # same tick again: nothing
    c = ev.connect(tmp_path / "evidence.db")
    first = c.execute("SELECT MIN(bar_open_time), MIN(position_before) FROM observations").fetchone()
    assert first[0] == bars[5001].open_time                              # nothing before registration
    much_later = bars[5030].open_time + HOUR_MS + 120_000                 # 20 missed hourly ticks
    assert fw.tick(now_ms=much_later, http=ex)["new_observations"] == 3 * 20
    late = c.execute("SELECT COUNT(*) FROM observations WHERE late=1").fetchone()[0]
    assert late > 0 and ev.verify(c)["ok"]
    assert fw.funding_covered([T0], T0 + 8 * HOUR_MS - 1) is True
    assert fw.funding_covered([T0], T0 + 8 * HOUR_MS) is False    # the 08:00 stamp is not synced yet
    assert fw.funding_covered([], T0) is False
    s = json.loads((tmp_path / "status.json").read_text())
    assert s["ok"] and s["live_capital_usd"] == 0 and s["observations"] == 90
    # the observation replays what the backtest simulation would have done over the same bars
    for cand in one:
        rows = list(c.execute("SELECT bar_open_time, equity FROM observations WHERE candidate_id=? "
                              "ORDER BY bar_open_time", (cand.id,)))
        j = next(i for i, b in enumerate(bars) if b.open_time == rows[0][0])
        seg = bars[j - 1:j + len(rows)]
        tg = cand.signal(bars[:j + len(rows)])[j - 1:]
        tg[0] = 0                                          # the forward book starts flat
        sim = simulate(seg, tg, EXEC_MODELS[cand.exec_model], tf_ms=HOUR_MS)
        assert [round(e, 12) for _, e in rows] == [round(e, 12) for e in sim.equity[1:]], cand.id


# ── lifecycle and ranking ──────────────────────────────────────────────────────────────────────
def test_real_capital_stages_are_refused_and_review_stages_need_the_owner():
    for to in ("LIMITED_LIVE", "PRODUCTION"):
        with pytest.raises(lc.TransitionRefused):
            lc.check("SHADOW", to, owner_decision_ref="dec-1")
    with pytest.raises(lc.TransitionRefused):
        lc.check("ROBUST", "CHAMPION_CANDIDATE")
    assert lc.check("ROBUST", "CHAMPION_CANDIDATE", owner_decision_ref="dec-1") == "owner"
    assert lc.check("BACKTESTING", "BACKTEST_QUALIFIED") == "auto"
    with pytest.raises(lc.TransitionRefused):
        lc.check("DISCOVERED", "FORWARD_PAPER")


def test_the_shortlist_drops_the_same_trade_twice():
    base = [0.01, -0.02, 0.015, 0.0, 0.03, -0.01, 0.02, -0.005, 0.01, 0.004, -0.003, 0.02]
    other = [-x for x in base]
    day = lambda xs, off=0: {str(1000 + i + off): x for i, x in enumerate(xs)}
    # «b» is «a» shifted by one missing day in its series: keyed alignment still sees the same trade
    b = day([x * 1.01 for x in base])
    b.pop("1003")
    res = [{"id": "a", "oos_daily_returns": day(base)}, {"id": "b", "oos_daily_returns": b},
           {"id": "c", "oos_daily_returns": day(other)}]
    quals = [{"id": "a", "qualified": True, "score": 1.0}, {"id": "b", "qualified": True, "score": 0.9},
             {"id": "c", "qualified": True, "score": 0.8}]
    assert [p["id"] for p in rk.shortlist(res, quals)] == ["a", "c"]


# ── safety: nothing in the package can trade ───────────────────────────────────────────────────
PKG = Path(fw.__file__).resolve().parent


def test_the_package_has_no_execution_path():
    src = "\n".join(p.read_text() for p in PKG.glob("*.py"))
    for forbidden in ("spa_core.execution", "from spa_core import execution", "X-MBX-APIKEY", "api_key",
                      "secret", "/api/v3/order", "/fapi/v1/order", "method=\"POST\"", "method='POST'",
                      "urlopen(req, data", "withdraw"):
        assert forbidden not in src, forbidden
    import spa_core.trading_research as tr
    assert tr.EXECUTION_ENABLED is False and tr.RESEARCH_ONLY is True


def test_the_fleet_sandbox_redirects_all_engine_state(tmp_path, monkeypatch):
    monkeypatch.delenv("SPA_TRADING_DATA_DIR", raising=False)
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path))
    assert fw.data_dir() == tmp_path / "trading_research"
