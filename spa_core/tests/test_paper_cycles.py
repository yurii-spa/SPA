"""The two sleeves run their new mechanics through the REAL cycle code (ADR-533) — sandboxed.

# LLM_FORBIDDEN

Each test points the cycle's book file and inputs at ``tmp_path``, injects fake feeds and a fake
clock, and runs ``run_hy_cycle`` / ``run_lp_cycle`` exactly as the scheduled agent does. Nothing
here can write the working books: the module paths are monkeypatched before the first call, and a
guard test proves the live files are untouched.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading import loop_book as L
from spa_core.paper_trading import morpho_market as MM
from spa_core.paper_trading import pendle_market as PM
from spa_core.paper_trading import sleeve_book
from spa_core.utils import clock

# FROZEN-DATE-OK: injected-clock — BASE feeds the patched clock.utcnow (the only clock the cycles read)
BASE = datetime(2026, 1, 15, 1, 55, 0)


def _rows(*pairs):
    return [{"protocol": p, "apy_pct": a, "apy": a, "tvl_usd": 50_000_000.0, "apy_source": "live",
             "tvl_source": "live", "chain": "ethereum", "tier": "T2"} for p, a in pairs]


def _write_ranking(tmp: Path, *pairs):
    (tmp / "apy_ranking.json").write_text(json.dumps({"by_apy": _rows(*pairs)}), encoding="utf-8")


class _Clock:
    def __init__(self, monkeypatch, start: datetime):
        self.t = start
        monkeypatch.setattr(clock, "utcnow", lambda: self.t)

    def advance(self, **kw):
        self.t = self.t + timedelta(**kw)


def _mobs(now, **kw):
    o = {"ok": True, "missing": [], "lltv": 0.915, "collateral_price_in_loan": 1.25,
         "collateral_share_price": 1.25, "implied_underlying_price_in_loan": 1.0,
         "borrow_share_price": 1e-12, "borrow_apy_pct": 4.0, "last_update": now.timestamp(),
         "utilization": 0.80, "available_liquidity": 50_000_000.0,
         "liquidation_incentive_factor": MM.liquidation_incentive_factor(0.915)}
    o.update(kw)
    return o


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    import spa_core.investment_os.directive as directive
    import spa_core.paper_trading.hy_cycle as hy
    import spa_core.paper_trading.lp_cycle as lp
    monkeypatch.setattr(hy, "_HY_DATA_PATH", tmp_path / "hy_paper_trading.json")
    monkeypatch.setattr(hy, "_HY_REGIME_LOG_PATH", tmp_path / "hy_regime_log.json")
    monkeypatch.setattr(hy, "get_hy_regime", lambda: "ENTER")
    monkeypatch.setattr(hy, "refresh_hy_regime", lambda *a, **k: "ENTER")
    monkeypatch.setattr(lp, "_LP_DATA_PATH", tmp_path / "lp_paper_trading.json")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)
    _write_ranking(tmp_path, ("maple", 5.0), ("fluid_fusdc", 4.8), ("susde", 9.0))
    clk = _Clock(monkeypatch, BASE)
    return {"hy": hy, "lp": lp, "tmp": tmp_path, "clock": clk, "mp": monkeypatch}


def _pendle(monkeypatch, *, implied=0.05, days=60.0, ok=True):
    def fake(now=None, **_k):
        exp = now + timedelta(days=days)
        return {"ok": ok, "reason": None if ok else "down", "markets": [] if not ok else [
            {"underlying": "sUSDS", "market": "0xmkt", "pt": "0xpt", "listed": True,
             "expiry": exp.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "days_to_expiry": days,
             "implied_apy_pct": implied * 100, "liquidity_usd": 5e6, "fee_rate": 0.001,
             "peg_evidence": "USDS", "pt_price_usd": PM.implied_price(implied, days), "mark_ok": True}]}
    monkeypatch.setattr(PM, "observe", fake)


def _morpho(monkeypatch, **kw):
    monkeypatch.setattr(MM, "observe", lambda now=None, **_k: _mobs(now, **kw))


def _state(tmp, name):
    return json.loads((tmp / name).read_text())


def test_balanced_buys_a_pt_leg_opens_its_experiment_and_replays(sandbox):
    s = sandbox
    _pendle(s["mp"], implied=0.06)        # ≥ the floating benchmark (mean of top candidates) − 1 pp
    s["hy"].run_hy_cycle(dry_run=False)
    st = _state(s["tmp"], "hy_paper_trading.json")
    bar = st["daily_history"][-1]
    assert bar["strategy_version"] == "balanced-fixed-carry-v1" and bar["fixed_carry_decision"] == "buy", bar.get("fixed_carry_reasons")
    assert bar["equity"] == pytest.approx(bar["floating_equity_usd"] + bar["fixed_carry_value_usd"], abs=0.02)
    assert [e["status"] for e in st["experiments"]][-1] == "active"
    from spa_core.audit import sleeve_replay
    assert sleeve_replay.replay(s["tmp"], "balanced")["status"] == "PASS"


def test_balanced_refuses_a_pt_below_the_floating_benchmark(sandbox):
    s = sandbox
    _pendle(s["mp"], implied=0.04)
    s["hy"].run_hy_cycle(dry_run=False)
    bar = _state(s["tmp"], "hy_paper_trading.json")["daily_history"][-1]
    assert bar["fixed_carry_decision"] == "hold" and "floor" in " ".join(bar["fixed_carry_reasons"])


def test_aggressive_loop_enters_supervises_hourly_and_deleverages(sandbox):
    s = sandbox
    _morpho(s["mp"])
    s["lp"].run_lp_cycle(dry_run=False)
    st = _state(s["tmp"], "lp_paper_trading.json")
    bar = st["daily_history"][-1]
    assert bar["strategy_version"] == "aggressive-susde-loop-v1" and bar["loop_decision"] == "enter"
    assert st["loop"]["status"] == "open" and bar["loop_hf"] == pytest.approx(0.915 / 0.70, abs=1e-3)
    from spa_core.audit import sleeve_replay
    assert sleeve_replay.replay(s["tmp"], "aggressive")["status"] == "PASS"
    # next scheduled run, an hour later, the collateral price falls: HF 1.12 ⇒ deleverage NOW
    s["clock"].advance(hours=1)
    _morpho(s["mp"], collateral_price_in_loan=1.25 * 1.12 / (0.915 / 0.70), implied_underlying_price_in_loan=0.99)
    s["lp"].run_lp_cycle(dry_run=False)
    st = _state(s["tmp"], "lp_paper_trading.json")
    assert st["loop"]["events"][-1]["event"] == "deleveraged"
    assert len(st["daily_history"]) == 1, "an intraday run writes no second accounting row"
    obs = [json.loads(l) for l in (s["tmp"] / "paper_observations" / "aggressive.jsonl").read_text().splitlines()]
    assert [o["supervision_action"] for o in obs] == [None, "deleveraged"]
    # the same hour again: no duplicate observation, no second trade
    s["lp"].run_lp_cycle(dry_run=False)
    obs2 = (s["tmp"] / "paper_observations" / "aggressive.jsonl").read_text().splitlines()
    assert len(obs2) == 2


def test_unmeasured_feed_holds_and_says_so(sandbox):
    s = sandbox
    s["mp"].setattr(MM, "observe", lambda now=None, **_k: {"ok": False, "missing": ["rpc down"]})
    s["lp"].run_lp_cycle(dry_run=False)
    bar = _state(s["tmp"], "lp_paper_trading.json")["daily_history"][-1]
    assert bar["loop_decision"] == "hold" and "unmeasured" in bar["loop_reason"]
    assert bar["loop_status"] == "flat"


def test_book_kill_unwinds_an_open_loop(sandbox):
    s = sandbox
    _morpho(s["mp"])
    s["lp"].run_lp_cycle(dry_run=False)
    st = _state(s["tmp"], "lp_paper_trading.json")
    st["peak_equity"] = st["equity"] * 1.5          # simulated deep drawdown from peak
    (s["tmp"] / "lp_paper_trading.json").write_text(json.dumps(st))
    s["clock"].advance(hours=1)
    res = s["lp"].run_lp_cycle(dry_run=False)
    st = _state(s["tmp"], "lp_paper_trading.json")
    assert res.get("kill_switch") is True and st["loop"]["status"] == "flat"
    assert st["loop"]["events"][-1]["reason"] == "book kill switch"


def test_sandbox_never_touches_the_working_books(sandbox):
    live = Path(__file__).resolve().parents[2] / "data"
    before = {n: (live / n).stat().st_mtime if (live / n).exists() else None
              for n in ("hy_paper_trading.json", "lp_paper_trading.json")}
    _morpho(sandbox["mp"])
    _pendle(sandbox["mp"])
    sandbox["hy"].run_hy_cycle(dry_run=False)
    sandbox["lp"].run_lp_cycle(dry_run=False)
    after = {n: (live / n).stat().st_mtime if (live / n).exists() else None for n in before}
    assert before == after
    assert L.LOAN_USD_ASSUMPTION  # the loan-asset peg assumption is named, not silent


def _replay(tmp, book):
    from spa_core.audit import sleeve_replay
    return sleeve_replay.replay(tmp, book)


def test_balanced_pt_held_marked_and_redeemed_over_days_replays_with_continuity(sandbox):
    s = sandbox
    first = {}                                         # expiry fixed at the first observation

    def fixed(now=None, **_k):
        exp = first.setdefault("exp", now + timedelta(days=30))
        days = (exp - now).total_seconds() / 86400.0
        return {"ok": True, "reason": None, "markets": [{
            "underlying": "sUSDS", "market": "0xmkt", "pt": "0xpt", "listed": True,
            "expiry": exp.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "days_to_expiry": days,
            "implied_apy_pct": 6.0, "liquidity_usd": 5e6, "fee_rate": 0.001, "peg_evidence": "USDS",
            "pt_price_usd": PM.implied_price(0.06, max(days, 0.0)), "mark_ok": True}]}
    s["mp"].setattr(PM, "observe", fixed)
    for _day in range(3):
        s["hy"].run_hy_cycle(dry_run=False)
        s["clock"].advance(days=1)
    s["clock"].advance(days=30)                         # past expiry
    s["hy"].run_hy_cycle(dry_run=False)
    st = _state(s["tmp"], "hy_paper_trading.json")
    rows = [r for r in st["daily_history"] if r.get("fixed_carry_decision")]
    assert rows[0]["fixed_carry_decision"] == "buy" and rows[0]["fixed_carry_value_usd"] > 0
    from spa_core.audit import sleeve_inputs_archive as A
    events = [e for rec in A.read_all(s["tmp"], "balanced")
              for e in ((rec.get("payload") or {}).get("sub_book") or {}).get("events") or []]
    assert any(e["event"] == "redeemed_at_par" for e in events), events
    rp = _replay(s["tmp"], "balanced")
    assert rp["status"] == "PASS", rp["diffs"]


def test_aggressive_intraday_liquidation_hits_the_book_kill(sandbox):
    """HF ≤ 1 needs a ~24 % collateral fall; a 3.3× loop on half the book then loses > 25 % of the
    book, so the next run's book kill switch engages — the liquidation is not a small event."""
    s = sandbox
    _morpho(s["mp"])
    s["lp"].run_lp_cycle(dry_run=False)
    s["clock"].advance(hours=2)
    _morpho(s["mp"], collateral_price_in_loan=1.25 * 0.99 / (0.915 / 0.70), implied_underlying_price_in_loan=0.99)
    s["lp"].run_lp_cycle(dry_run=False)
    st = _state(s["tmp"], "lp_paper_trading.json")
    assert st["loop"]["events"][-1]["event"] == "liquidated" and st["pending_floating_cash_usd"] > 0
    s["clock"].advance(days=1)
    _morpho(s["mp"])
    res = s["lp"].run_lp_cycle(dry_run=False)
    assert res.get("kill_switch") is True


def test_aggressive_intraday_unwind_cash_reaches_the_next_row_with_continuity(sandbox):
    s = sandbox
    _morpho(s["mp"])
    s["lp"].run_lp_cycle(dry_run=False)                 # day 1: enter
    s["clock"].advance(hours=2)
    _morpho(s["mp"], implied_underlying_price_in_loan=0.95)
    s["lp"].run_lp_cycle(dry_run=False)                 # intraday: implied USDe < 0.97 ⇒ emergency unwind
    st = _state(s["tmp"], "lp_paper_trading.json")
    assert st["loop"]["events"][-1]["event"] == "unwound" and st["pending_floating_cash_usd"] > 0
    s["clock"].advance(days=1)
    _morpho(s["mp"])
    s["lp"].run_lp_cycle(dry_run=False)                 # day 2: the cash is in the floating part
    st = _state(s["tmp"], "lp_paper_trading.json")
    assert st["pending_floating_cash_usd"] == 0.0 and len(st["daily_history"]) == 2
    assert "cooldown" in st["daily_history"][-1]["loop_reason"]
    rp = _replay(s["tmp"], "aggressive")
    assert rp["status"] == "PASS", rp["diffs"]


def test_aggressive_negative_carry_exit_through_the_cycle_replays(sandbox):
    s = sandbox
    _morpho(s["mp"])
    s["lp"].run_lp_cycle(dry_run=False)
    for _ in range(3):
        s["clock"].advance(days=1)
        _morpho(s["mp"], borrow_apy_pct=20.0)
        s["lp"].run_lp_cycle(dry_run=False)
    st = _state(s["tmp"], "lp_paper_trading.json")
    assert st["loop"]["status"] == "flat" and st["daily_history"][-1]["loop_decision"] == "exit"
    rp = _replay(s["tmp"], "aggressive")
    assert rp["status"] == "PASS", rp["diffs"]



def test_balanced_benchmark_is_the_held_floating_yield_not_a_spiking_candidate(sandbox):
    """02.10 in production: a candidate spiking to 12.6 % (not held) lifted the candidate mean to 7.3 %
    and refused a PT the held legs (5.0 %) would have accepted."""
    s = sandbox
    _pendle(s["mp"], implied=0.06)
    s["hy"].run_hy_cycle(dry_run=False)                      # day 1: legs exist, PT bought
    _write_ranking(s["tmp"], ("maple", 5.0), ("fluid_fusdc", 4.8), ("susde", 5.0), ("aave_v3", 25.0))
    st = _state(s["tmp"], "hy_paper_trading.json")
    st["fixed_carry"] = {"legs": []}                        # make room for a new decision
    (s["tmp"] / "hy_paper_trading.json").write_text(json.dumps(st))
    s["clock"].advance(days=1)
    _pendle(s["mp"], implied=0.055)   # ≥ held-legs floor 5.27 %, < the spiked candidate-mean floor 8.95 %
    s["hy"].run_hy_cycle(dry_run=False)
    bar = _state(s["tmp"], "hy_paper_trading.json")["daily_history"][-1]
    assert bar["fixed_carry_decision"] == "buy", bar["fixed_carry_reasons"]
