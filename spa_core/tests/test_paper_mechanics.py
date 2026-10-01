"""Three paper mechanics (ADR-533): PT carry, simulated loop, observations, mandates, feeds.

# LLM_FORBIDDEN

Offline: every feed is a fake passed in; time is injected (``now``), so nothing here depends on the
calendar or the network. Each economic rule has a control both ways.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.paper_trading import loop_book as L
from spa_core.paper_trading import morpho_market as MM
from spa_core.paper_trading import onchain_read as R
from spa_core.paper_trading import paper_observations as PO
from spa_core.paper_trading import pendle_market as PM
from spa_core.paper_trading import pt_carry as PT
from spa_core.paper_trading import strategy_mandates as SM

# FROZEN-DATE-OK: injected-clock — NOW is passed as now= to every model, feed and journal call below
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ── fakes ───────────────────────────────────────────────────────────────────

def _mobs(**kw) -> dict:
    """A measured Morpho observation (loan 6 dp, collateral 18 dp)."""
    o = {"ok": True, "missing": [], "lltv": 0.915, "collateral_price_in_loan": 1.25,
         "collateral_share_price": 1.25, "implied_underlying_price_in_loan": 1.0,
         "borrow_share_price": 1e-12, "borrow_apy_pct": 4.0, "last_update": NOW.timestamp(),
         "utilization": 0.80, "available_liquidity": 50_000_000.0,
         "liquidation_incentive_factor": MM.liquidation_incentive_factor(0.915)}
    o.update(kw)
    return o


def _pt_market(**kw) -> dict:
    exp = NOW + timedelta(days=60)
    m = {"underlying": "sUSDS", "market": "0xmkt", "pt": "0xpt", "listed": True,
         "expiry": exp.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "days_to_expiry": 60.0,
         "implied_apy_pct": 5.0, "liquidity_usd": 5_000_000.0, "fee_rate": 0.001,
         "peg_evidence": "USDS", "pt_price_usd": PM.implied_price(0.05, 60.0), "mark_ok": True,
         "pt_price_updated_at": NOW.isoformat()}
    m.update(kw)
    return m


# ── Morpho primary-source arithmetic ────────────────────────────────────────

def test_liquidation_incentive_is_morpho_blues_formula():
    assert MM.liquidation_incentive_factor(0.915) == pytest.approx(1 / (1 - 0.3 * 0.085))
    assert MM.liquidation_incentive_factor(0.0) == 1.15, "capped at MAX_LIQUIDATION_INCENTIVE_FACTOR"


def test_rpc_quorum_needs_two_agreeing_witnesses():
    answers = iter([{"result": "0x" + "1" * 64}, {"result": "0x" + "2" * 64}, {"result": "0x" + "1" * 64}])
    q = R.eth_call_quorum("0xto", "0x", post=lambda u, p: next(answers),
                          endpoints=("https://a/x", "https://b/x", "https://c/x"))
    assert q["result"] == "0x" + "1" * 64 and q["witnesses"] == ["a", "c"]
    lone = iter([{"result": "0x" + "1" * 64}, {"error": "x"}])
    q2 = R.eth_call_quorum("0xto", "0x", post=lambda u, p: next(lone), endpoints=("https://a/x", "https://b/x"))
    assert q2["result"] is None and "agreement" in q2["reason"], "one witness is not evidence"


def test_morpho_observe_without_sources_is_not_ok():
    def no_rpc(u, p):
        raise OSError("down")
    o = MM.observe(post=no_rpc, get_json=lambda *a, **k: (_ for _ in ()).throw(OSError("down")), now=NOW)
    assert o["ok"] is False and o["missing"]
    assert "collateral_price_in_loan" not in o, "no price is ever filled in"


# ── loop: valuation, no double counting ─────────────────────────────────────

def _open_loop(obs: dict, budget: float = 50_000.0) -> dict:
    sub = {"status": "flat"}
    dec = L.daily_decide(sub, obs, budget_usd=budget, yield_hint_pct=9.0, allow_new=True, now=NOW)
    assert dec["decision"] == "enter", dec
    return sub


def test_entry_sizes_to_target_ltv_and_pays_its_cost():
    sub = _open_loop(_mobs())
    v = L.valuation(sub, _mobs(), NOW)
    assert v["ltv"] == pytest.approx(L.TARGET_LTV, abs=1e-6)
    assert v["equity"] < 50_000.0 and v["equity"] == pytest.approx(sub["entry"]["equity_in_usd"], abs=0.01)
    assert v["hf"] == pytest.approx(0.915 / 0.70, abs=1e-4)


def test_no_double_counting_yield_comes_only_from_prices():
    """A day later with share price +x and debt grown by the borrow rate: equity change is exactly
    collateral × Δprice − debt × Δrate. No APY is added on top."""
    obs0 = _mobs()
    sub = _open_loop(obs0)
    v0 = L.valuation(sub, obs0, NOW)
    later = NOW + timedelta(days=1)
    obs1 = _mobs(collateral_price_in_loan=1.25 * 1.0002, last_update=NOW.timestamp())
    v1 = L.valuation(sub, obs1, later)
    want = (v0["collateral_value"] * 0.0002
            - v0["debt_value"] * ((1.04) ** (1 / 365) - 1))
    assert v1["equity"] - v0["equity"] == pytest.approx(want, rel=1e-6)


def test_unmeasured_inputs_mean_no_action_and_no_value():
    sub = _open_loop(_mobs())
    before = copy.deepcopy(sub)
    r = L.supervise(sub, {"ok": False, "missing": ["rpc"]}, NOW)
    assert r["valuation"]["measured"] is False and r["action"].startswith("none")
    assert sub["collateral_units"] == before["collateral_units"] and sub["unmeasured_runs"] == 1


def test_hf_below_delever_threshold_deleverages_to_target():
    sub = _open_loop(_mobs())
    # price falls until HF ≈ 1.12 (between EMERGENCY 1.08 and DELEVER 1.15)
    drop = 1.12 / (0.915 / 0.70)
    obs = _mobs(collateral_price_in_loan=1.25 * drop, implied_underlying_price_in_loan=0.99)
    r = L.supervise(sub, obs, NOW)
    assert r["action"] == "deleveraged"
    assert r["valuation"]["ltv"] == pytest.approx(L.TARGET_LTV, abs=2e-3)


def test_emergency_unwind_on_depeg_and_on_low_hf():
    sub = _open_loop(_mobs())
    r = L.supervise(sub, _mobs(implied_underlying_price_in_loan=0.95), NOW)
    assert r["action"] == "emergency_unwind" and sub["status"] == "flat" and r["cash_out_usd"] > 0
    sub2 = _open_loop(_mobs())
    r2 = L.supervise(sub2, _mobs(collateral_price_in_loan=1.25 * (1.05 / (0.915 / 0.70))), NOW)
    assert r2["action"] == "emergency_unwind"


def test_liquidation_seizes_debt_times_lif_and_names_bad_debt():
    sub = _open_loop(_mobs())
    v = L.valuation(sub, _mobs(), NOW)
    crash = 0.95 / (0.915 / 0.70)                   # HF 0.95 ⇒ liquidatable
    obs = _mobs(collateral_price_in_loan=1.25 * crash, implied_underlying_price_in_loan=0.99)
    r = L.supervise(sub, obs, NOW)
    assert r["action"] == "liquidated"
    e = sub["events"][-1]
    debt = v["debt_value"]
    assert e["seized_units"] == pytest.approx(debt * e["lif"] / obs["collateral_price_in_loan"], rel=1e-6)
    assert e["bad_debt_usd"] == 0.0
    deep = _open_loop(_mobs())
    r3 = L.supervise(deep, _mobs(collateral_price_in_loan=1.25 * 0.5), NOW)
    assert r3["action"] == "liquidated" and deep["events"][-1]["bad_debt_usd"] > 0


def test_entry_refused_when_leverage_does_not_pay():
    sub = {"status": "flat"}
    dec = L.daily_decide(sub, _mobs(borrow_apy_pct=4.73), budget_usd=50_000, yield_hint_pct=5.29,
                         allow_new=True, now=NOW)
    assert dec["decision"] == "hold" and "levered net" in dec["reason"] and sub["status"] == "flat"
    dec2 = L.daily_decide(sub, _mobs(utilization=0.97), budget_usd=50_000, yield_hint_pct=9.0,
                          allow_new=True, now=NOW)
    assert "utilisation" in dec2["reason"]
    dec3 = L.daily_decide(sub, _mobs(), budget_usd=50_000, yield_hint_pct=9.0, allow_new=False, now=NOW)
    assert "CIO" in dec3["reason"]


def test_negative_carry_three_days_unwinds():
    sub = _open_loop(_mobs())
    dec: dict = {}
    for i in range(3):
        dec = L.daily_decide(sub, _mobs(borrow_apy_pct=12.0), budget_usd=0, yield_hint_pct=5.0,
                             allow_new=True, now=NOW + timedelta(days=i + 1))
    assert dec["decision"] == "exit" and sub["status"] == "flat"


def test_stress_scenarios_cover_depeg_rate_spike_and_yield_loss():
    sub = _open_loop(_mobs())
    out = {s["scenario"]: s for s in L.stress(sub, _mobs(), NOW, yield_pct=9.0)}
    # at target LTV 0.70 (HF ≈ 1.31): −20 % triggers the emergency unwind, −30 % is liquidatable
    assert out["usde_depeg_20"]["emergency_unwind"] is True and out["usde_depeg_20"]["liquidatable"] is False
    assert out["usde_depeg_30"]["liquidatable"] is True
    assert out["usde_depeg_2"]["liquidatable"] is False and out["usde_depeg_2"]["emergency_unwind"] is False
    # −5 % puts implied USDe at 0.95 < 0.97: the supervisor would unwind — the stress table must say so
    assert out["usde_depeg_5"]["liquidatable"] is False and out["usde_depeg_5"]["emergency_unwind"] is True
    assert out["borrow_spike_30pct_30d"]["equity_change_pct"] < 0
    assert out["yield_zero_60d"]["equity_change_pct"] < 0
    flat = {s["scenario"]: s for s in L.stress({"status": "flat"}, _mobs(), NOW, yield_pct=9.0)}
    assert all(s["hypothetical_unit_position"] for s in flat.values())


# ── PT carry ────────────────────────────────────────────────────────────────

def _pobs(*markets):
    return {"ok": True, "markets": list(markets) or [_pt_market()]}


def test_pt_buy_respects_caps_and_embeds_its_cost():
    r = PT.daily_step(None, _pobs(), equity_total=100_000.0, benchmark_apy_pct=5.0, allow_new=True, now=NOW)
    assert r["decision"] == "buy"
    assert r["bought_usd"] == pytest.approx(25_000.0)                  # per-market 25 % binds before 40 %
    assert r["value_after"] == pytest.approx(25_000.0 - r["cost_usd"], abs=1e-6), "cost embedded once"


def test_pt_earns_through_price_only_and_redeems_at_par():
    r = PT.daily_step(None, _pobs(), equity_total=100_000.0, benchmark_apy_pct=5.0, allow_new=True, now=NOW)
    sub = r["sub"]
    units = sub["legs"][0]["units"]
    mid = NOW + timedelta(days=30)
    p30 = PM.implied_price(0.05, 30.0)
    r2 = PT.daily_step(sub, _pobs(_pt_market(pt_price_usd=p30, days_to_expiry=30.0)), equity_total=100_000.0,
                       benchmark_apy_pct=5.0, allow_new=False, now=mid)
    assert r2["mark_pnl_usd"] == pytest.approx(units * (p30 - sub["legs"][0]["mark"]), abs=1e-5)
    at_expiry = NOW + timedelta(days=61)
    r3 = PT.daily_step(r2["sub"], _pobs(), equity_total=100_000.0, benchmark_apy_pct=5.0,
                       allow_new=False, now=at_expiry)
    assert r3["redeemed_usd"] == pytest.approx(units * 1.0, abs=1e-5) and r3["sub"]["legs"] == []


def test_pt_unobserved_mark_is_kept_not_invented():
    r = PT.daily_step(None, _pobs(), equity_total=100_000.0, benchmark_apy_pct=5.0, allow_new=True, now=NOW)
    r2 = PT.daily_step(r["sub"], {"ok": False, "reason": "down", "markets": []}, equity_total=100_000.0,
                       benchmark_apy_pct=5.0, allow_new=True, now=NOW + timedelta(days=1))
    assert r2["mark_pnl_usd"] == 0.0 and r2["degraded"] and r2["sub"]["legs"][0]["mark_ok"] is False


@pytest.mark.parametrize("kw,why", [
    ({"listed": False}, "not listed"), ({"peg_evidence": None}, "peg"), ({"mark_ok": False}, "not confirmed"),
    ({"days_to_expiry": 5.0}, "outside"), ({"liquidity_usd": 1_000_000.0}, "liquidity"),
    ({"implied_apy_pct": 2.0}, "floor"),
])
def test_pt_entry_gate_refuses_with_a_named_reason(kw, why):
    ok, reason = PT.eligible(_pt_market(**kw), benchmark_apy_pct=5.0)
    assert ok is False and why in reason
    assert PT.eligible(_pt_market(), benchmark_apy_pct=None)[0] is False, "unmeasured benchmark refuses"


def test_pendle_observation_rejects_a_price_that_disagrees_with_the_implied_rate():
    exp = (NOW + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    act = {"markets": [{"name": "sUSDS", "address": "0xm", "expiry": exp, "pt": "1-0xpt",
                        "details": {"impliedApy": 0.05, "liquidity": 5e6, "feeRate": 0.001}},
                       {"name": "sUSDe", "address": "0xe", "expiry": exp, "details": {}}]}

    def get(url, price=0.90, updated=NOW):
        return act if url.endswith("/active") else {
            "pt": {"price": {"usd": price}, "priceUpdatedAt": updated.strftime("%Y-%m-%dT%H:%M:%S.000Z")}}
    bad = PM.observe(get=get, now=NOW)
    assert [m["underlying"] for m in bad["markets"]] == ["sUSDS"], "sUSDe has no evidenced peg"
    assert bad["markets"][0]["mark_ok"] is False
    good = PM.observe(get=lambda u: get(u, PM.implied_price(0.05, 60.0)), now=NOW)
    assert good["markets"][0]["mark_ok"] is True
    stale = PM.observe(get=lambda u: get(u, PM.implied_price(0.05, 60.0), NOW - timedelta(hours=7)), now=NOW)
    assert stale["markets"][0]["mark_ok"] is False and "age" in stale["markets"][0]["mark_reason"], \
        "a consistent but stale pair is not a mark"


# ── observations journal ───────────────────────────────────────────────────

def test_observation_journal_is_idempotent_per_hour_and_shows_gaps(tmp_path):
    assert PO.record(tmp_path, "aggressive", NOW, {"x": 1}) == "appended"
    assert PO.record(tmp_path, "aggressive", NOW + timedelta(minutes=20), {"x": 2}) == "duplicate_slot"
    PO.record(tmp_path, "aggressive", NOW + timedelta(hours=3), {"x": 3})
    rows = PO.read(tmp_path, "aggressive")
    assert [r["x"] for r in rows] == [1, 3]
    assert len(PO.gaps(rows)) == 2, "two missed hourly runs are visible"


# ── mandates / experiments ──────────────────────────────────────────────────

def test_three_packages_have_three_different_mechanics():
    mechs = {p: frozenset(m["target_mechanics"]) for p, m in SM.MANDATES.items()}
    assert len(set(mechs.values())) == 3
    assert "loop" in mechs["aggressive"] and "loop" not in mechs["balanced"] | mechs["conservative"]
    assert "pt_fixed" in mechs["balanced"]
    for m in SM.MANDATES.values():
        for k in ("strategy_id", "strategy_version", "accounting_version", "yield_source", "instruments",
                  "entry", "hold", "exit", "costs", "limits", "stop", "roles", "refs"):
            assert m.get(k), k
        assert m["strategy_version"] != m["accounting_version"]


def test_new_experiment_keeps_old_rows_and_is_idempotent():
    state = {"daily_history": [{"date": "old", "equity": 1.0}]}
    before = copy.deepcopy(state["daily_history"])
    e1 = SM.ensure_experiment(state, "aggressive", start_date="d1", run_ts="t1", initial_equity=99.0,
                              initial_note="n")
    e2 = SM.ensure_experiment(state, "aggressive", start_date="d2", run_ts="t2", initial_equity=1.0,
                              initial_note="n")
    assert e1 is e2 and e1["initial_state"]["equity_usd"] == 99.0
    assert state["daily_history"] == before
    assert [e["status"] for e in state["experiments"]] == ["closed", "active"]



def test_no_reentry_into_a_depeg_or_during_the_cooldown():
    sub = _open_loop(_mobs())
    L.supervise(sub, _mobs(implied_underlying_price_in_loan=0.95), NOW)
    assert sub["status"] == "flat"
    same_day = L.daily_decide(sub, _mobs(implied_underlying_price_in_loan=0.95), budget_usd=50_000,
                              yield_hint_pct=9.0, allow_new=True, now=NOW)
    assert same_day["decision"] == "hold" and "floor" in same_day["reason"]
    recovered = L.daily_decide(sub, _mobs(), budget_usd=50_000, yield_hint_pct=9.0, allow_new=True,
                               now=NOW + timedelta(days=2))
    assert recovered["decision"] == "hold" and "cooldown" in recovered["reason"]
    # the fake share price is flat, so the position's OWN 7-day yield would be 0 % — drop that history so
    # this test isolates the cooldown (the own-yield rule is tested on its own)
    sub["share_price_history"] = []
    later = L.daily_decide(sub, _mobs(), budget_usd=50_000, yield_hint_pct=9.0, allow_new=True,
                           now=NOW + timedelta(days=8))
    assert later["decision"] == "enter"


def test_one_cost_basis_for_entry_exit_and_the_gate():
    e = L.economics(9.0, 4.0)
    lev = 1 / (1 - L.TARGET_LTV)
    assert e["round_trip_cost_pct_of_equity"] == pytest.approx(2 * lev * L.SWAP_COST * 100, abs=1e-4)
    sub = _open_loop(_mobs(), budget=50_000.0)
    entry_cost = sub["entry"]["cost_usd"] - 3 * L.GAS_USD
    assert entry_cost == pytest.approx(50_000.0 * lev * L.SWAP_COST, abs=0.01)


def test_unmeasured_yield_neither_advances_nor_resets_the_negative_carry_count():
    sub = _open_loop(_mobs())
    L.daily_decide(sub, _mobs(borrow_apy_pct=12.0), budget_usd=0, yield_hint_pct=5.0, allow_new=True,
                   now=NOW + timedelta(days=1))
    assert sub["negative_carry_days"] == 1
    sub["share_price_history"] = []
    L.daily_decide(sub, _mobs(borrow_apy_pct=12.0, collateral_share_price=None), budget_usd=0,
                   yield_hint_pct=None, allow_new=True, now=NOW + timedelta(days=2))
    assert sub["negative_carry_days"] == 1
