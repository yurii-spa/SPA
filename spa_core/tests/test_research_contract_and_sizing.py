"""S3 E6.1/E6.4: контракт исследования (форма, ledgers, бюджет попыток) и research-модель spot_frac@v1.

Боевой контракт не тратится: каждый тест работает на копии в tmp. Сцена свечей — синтетическая."""
import copy
import json
import math
import shutil
import sqlite3
from pathlib import Path

import pytest

from spa_core.trading_research import market_data as md
from spa_core.trading_research import research_contract as rc
from spa_core.trading_research import sizing_experiment as sx
from spa_core.trading_research.execution import EXEC_MODELS, simulate
from spa_core.trading_research.strategies import by_id

ROOT = Path(__file__).resolve().parents[2] / "docs" / "research_contracts"
TRP05 = ROOT / "trp05-sizing-band-2026-11-01.json"
EARN = ROOT / "earn-defi-btc-engine-v0.3-forward-2026-11-01.json"
CTRL = "ma_cross@v1:BTC:1D:spot_long:3479f26323"
D = 86_400_000
T0 = 1_500_000_000_000 - (1_500_000_000_000 % D)  # FROZEN-DATE-OK: injected-clock — every bar derives from T0


def _bars(n=1600, seed=0.0):
    out, px = [], 5000.0
    for i in range(n):
        o = px
        px *= 1 + 0.03 * math.sin(i / 40.0 + seed) + 0.01 * math.cos(i / 9.0)
        out.append(md.Bar(T0 + i * D, o, max(o, px) * 1.01, min(o, px) * 0.99, px, 1.0))
    return out


def test_committed_contracts_are_valid_and_cover_both_engines():
    cs = [json.loads(p.read_text()) for p in (TRP05, EARN)]
    assert [rc.validate(c) for c in cs] == [[], []]
    assert {c["engine"] for c in cs} == set(rc.ENGINES)


@pytest.mark.parametrize("mutate, needle", [
    (lambda c: c.pop("hypothesis"), "hypothesis"),
    (lambda c: c.update(engine="investment_engine"), "Investment Engine"),
    (lambda c: c["strategy"]["configs"].append(dict(c["strategy"]["configs"][1], name="x")), "от 1 до 6"),
    (lambda c: c["strategy"]["configs"][1].update(role="control"), "ровно один"),
    (lambda c: c["scope"]["periods"].update(forward_from="2020-01-01T00:00:00Z"), "forward_from"),
    (lambda c: c.update(attempt_budget=0), "attempt_budget"),
    (lambda c: c["ledger_refs"].pop("candidates"), "ledger_refs"),
])
def test_validate_names_the_broken_field(mutate, needle):
    c = json.loads(TRP05.read_text())
    mutate(c)
    errs = rc.validate(c)
    assert errs and any(needle in e for e in errs), errs


def test_check_ledgers_three_outcomes(tmp_path):
    c = json.loads(TRP05.read_text())
    assert rc.check_ledgers(c, {"evidence": tmp_path / "none.db"})["status"] == rc.INCOMPLETE
    db = tmp_path / "ev.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE candidates (candidate_id TEXT, def_hash TEXT)")
    conn.commit()
    assert rc.check_ledgers(c, {"evidence": db})["status"] == rc.INCOMPLETE
    conn.execute("INSERT INTO candidates VALUES (?, ?)", (CTRL, "other"))
    conn.commit()
    assert rc.check_ledgers(c, {"evidence": db})["status"] == rc.MISMATCH
    conn.execute("UPDATE candidates SET def_hash=?", (by_id()[CTRL].def_hash,))
    conn.commit()
    assert rc.check_ledgers(c, {"evidence": db})["status"] == rc.OK
    e = json.loads(EARN.read_text())
    edb = tmp_path / "ed.db"
    sqlite3.connect(edb).executescript("CREATE TABLE config_versions (version TEXT, config_hash TEXT);"
                                       "INSERT INTO config_versions VALUES ('0.3', 'tampered');")
    assert rc.check_ledgers(e, {"db": edb})["status"] == rc.MISMATCH


def test_attempt_budget_is_spent_before_the_run_and_then_refuses(tmp_path):
    p = tmp_path / "c.json"
    shutil.copy(TRP05, p)
    assert [rc.spend_attempt(p, {"why": i}) for i in range(2)] == [1, 2]
    with pytest.raises(rc.AttemptBudgetExceeded):
        rc.spend_attempt(p, {"why": 3})
    assert len(rc.attempts(p)) == 2                         # отказ ничего не дописал


def test_k1_without_band_is_exactly_the_control_simulator():
    bars = _bars()
    cand = by_id()[CTRL]
    t = cand.signal(bars)
    m = EXEC_MODELS[cand.exec_model]
    for mult in (1.0, 2.0):
        a = simulate(bars, t, m, tf_ms=D, cost_mult=mult).equity
        b = sx.simulate_frac(bars, t, k=1.0, band=None, cost_per_side=m.cost_per_side, cost_mult=mult).equity
        assert max(abs(x - y) for x, y in zip(a, b)) < 1e-12


def test_no_look_ahead_future_bars_do_not_change_the_past():
    bars = _bars()
    alt = bars[:1200] + _bars(1600, seed=2.0)[1200:]
    cand = by_id()[CTRL]
    r1 = sx.simulate_frac(bars, cand.signal(bars), k=0.75, band=0.05, cost_per_side=0.0015)
    r2 = sx.simulate_frac(alt, cand.signal(alt), k=0.75, band=0.05, cost_per_side=0.0015)
    assert r1.equity[:1200] == r2.equity[:1200]
    assert r1.equity[1200:] != r2.equity[1200:]


def test_band_rebalances_only_beyond_the_band_and_charges_costs():
    bars = _bars()
    t = [1] * len(bars)
    none = sx.simulate_frac(bars, t, k=0.5, band=None, cost_per_side=0.0015)
    wide = sx.simulate_frac(bars, t, k=0.5, band=0.10, cost_per_side=0.0015)
    tight = sx.simulate_frac(bars, t, k=0.5, band=0.02, cost_per_side=0.0015)
    assert none.rebalances == 0 and 0 < wide.rebalances < tight.rebalances
    # реже ≠ дешевле: редкий ребаланс торгует бо́льшую долю за раз — поэтому порядок издержек между полосами
    # НЕ утверждается; утверждается, что каждый ребаланс оплачен и учтён
    assert none.cost_paid < min(wide.cost_paid, tight.cost_paid)
    for r in (wide, tight):
        assert all(c > 0 for c, rb in zip(r.bar_cost, r.bar_rebalance) if rb)
        assert abs(sum(r.bar_cost) - r.cost_paid) < 1e-12
    assert all(abs(w - 0.5) <= 0.10 + 0.05 for w in wide.weight[2:])   # дрейф за один бар сверх полосы мал


def test_full_run_on_a_scene_spends_one_attempt_and_reports_every_field(tmp_path):
    bars = []
    for b in _bars(2700):
        for h in range(24):
            bars.append((T0 + (b.open_time - T0) + h * 3_600_000, b))
    db = tmp_path / "m.db"
    conn = md.connect(db)
    for ot, b in bars:
        conn.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ("BTCUSDT", "1h", ot, b.open, b.high, b.low, b.close, 1.0, "test", T0))
    conn.commit()
    conn.close()
    c = json.loads(TRP05.read_text())
    p = tmp_path / "c.json"
    p.write_text(json.dumps(c))
    out = sx.run(p, db)
    assert out["attempt"] == 1 and len(rc.attempts(p)) == 1
    assert out["equivalence_k1_vs_control_max_abs"] < 1e-9
    assert set(out["configs"]) == {x["name"] for x in c["strategy"]["configs"]}
    oos = out["configs"]["k075_band05"]["1x"]["oos"]
    for k in ("net_return", "max_drawdown", "calmar", "cost_paid", "turnover_weight_per_year",
              "cash_share_mean", "funding", "rebalances"):
        assert k in oos
    assert out["configs"]["k075_band05"]["2x"]["oos"]["cost_paid"] > oos["cost_paid"]
    assert set(out["verdict"]) == {x["name"] for x in c["strategy"]["configs"] if x["role"] != "control"}
    assert "oos" in out["hold"]["1x"]


def test_verdict_requires_both_cost_levels_and_no_deeper_drawdown():
    def row(c1, d1, c2, d2, role="variant"):
        return {"role": role, "1x": {"oos": {"calmar": c1, "max_drawdown": d1}},
                "2x": {"oos": {"calmar": c2, "max_drawdown": d2}}}
    out = {"configs": {"control": row(1.0, -0.3, 0.9, -0.3, "control"),
                       "win": row(1.2, -0.2, 1.1, -0.2), "only1x": row(1.2, -0.2, 0.8, -0.2),
                       "deeper": row(1.5, -0.4, 1.4, -0.4), "unk": row(None, -0.2, 1.0, -0.2)}}
    v = sx.verdict(copy.deepcopy(out))
    assert v == {"win": "лучше контроля", "only1x": "не подтверждено", "deeper": "не подтверждено",
                 "unk": "UNKNOWN: Calmar не измерен"}
