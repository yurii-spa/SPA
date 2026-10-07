"""CAPITAL-SOURCES-01 / ADR-640 — the Trading Alpha sleeve and the Capital Sources view.

Every scene builds a throw-away evidence.db with the engine's own writers (`evidence.register/append_*`), so the
sleeve is tested against the real schema and hash chains. The clock is an explicit input everywhere (`as_of_ms`,
`now_ms`, event `now_ms`) — nothing here reads the wall clock.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from spa_core.investment_cio import capital_sources as cs
from spa_core.investment_cio import contract
from spa_core.trading_research import alpha_sleeve as al
from spa_core.trading_research import evidence as ev
from spa_core.trading_research import forward as fw
from spa_core.trading_research import lifecycle as lc

T0 = 1_800_000_000_000            # an arbitrary epoch-ms anchor; every instant below is relative to it
H = 3_600_000
D = 24 * H
ASM = json.dumps({"exec_model": "spot_long", "exec_model_version": 2, "fee_bps": 10.0, "slippage_bps": 5.0,
                  "leverage": 1.0, "funding": False, "timing": "x"}, sort_keys=True)


def _db(tmp_path, name="evidence.db"):
    return ev.connect(tmp_path / name)


def _register(conn, cid, *, at=T0, tf="1D", family=None):
    ev.register(conn, cid, "h" + cid, {"family": family or cid.split("@")[0], "timeframe": tf}, now_ms=at,
                code_version="cv1")


def _admit(conn, cid, *, at=T0, policy=True):
    evidence = {"admission_policy_version": lc.ADMISSION_POLICY_VERSION} if policy else {}
    for frm, to in ((None, "DISCOVERED"), ("DISCOVERED", "BACKTESTING"), ("BACKTESTING", "BACKTEST_QUALIFIED"),
                    ("BACKTEST_QUALIFIED", "FORWARD_PAPER")):
        ev.append_event(conn, cid, frm, to, "test", evidence, actor="t", now_ms=at)


def _obs(conn, cid, i, *, equity, pos=1, tf_ms=D, cost=0.0, action="HOLD", start=T0, signal_delay=60_000,
         trade=None):
    open_t = start + i * tf_ms
    ev.append_observation(conn, {
        "candidate_id": cid, "asset": "BTC", "timeframe": "1D" if tf_ms == D else "4h",
        "bar_open_time": open_t, "bar_close_time": open_t + tf_ms, "signal_ts_ms": open_t + tf_ms + signal_delay,
        "late": 0, "gap_bars": 0, "bar_open": 1.0, "bar_close": 1.0, "position_before": pos, "fill_price": None,
        "fill_cost": cost, "funding": 0.0, "position_held": pos, "equity": equity, "target": pos,
        "action": action, "closed_trade": json.dumps(trade) if trade else None,
        "book_state": json.dumps({"entry_eq": 1.0}), "assumptions": ASM, "data_ref": "r", "code_version": "cv1",
        "release": None})


def _tick(conn, at):
    ev.record_tick(conn, started_ms=at - 1000, finished_ms=at, new_bars=0, new_obs=0, ok=True, detail={},
                   code_version="cv1")


def _scene(tmp_path, days=6, *, dup=False):
    conn = _db(tmp_path)
    for cid in ("a@v1:1D", "b@v1:1D", "c@v1:1D"):
        _register(conn, cid)
        _admit(conn, cid)
    for i in range(days):
        _obs(conn, "a@v1:1D", i, equity=1.0 + 0.01 * (i + 1))
        _obs(conn, "b@v1:1D", i, equity=1.0 + 0.01 * (i + 1) if dup else 1.0 - 0.005 * (i + 1))
        _obs(conn, "c@v1:1D", i, equity=1.0, pos=0)
    end = T0 + (days + 1) * D
    _tick(conn, end)
    conn.commit()
    return conn, end


# ── determinism & causality ────────────────────────────────────────────────────────────────────────────────
def test_rebuild_is_byte_identical(tmp_path):
    conn, end = _scene(tmp_path)
    a = al.dumps(al.build(conn, as_of_ms=end))
    b = al.dumps(al.build(conn, as_of_ms=end))
    assert a == b


def test_as_of_build_sees_only_what_was_knowable(tmp_path):
    conn, end = _scene(tmp_path)
    early = al.build(conn, as_of_ms=T0 + 2 * D + 120_000)        # two daily bars closed AND recorded
    late = al.build(conn, as_of_ms=end)
    assert early["evidence"]["observations_in_sleeve"] == 2 * 3
    assert late["evidence"]["observations_in_sleeve"] == 6 * 3
    assert early["nav"]["value"] != late["nav"]["value"]


def test_an_observation_recorded_after_as_of_is_not_used_even_if_its_bar_closed(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _admit(conn, "a@v1:1D")
    _obs(conn, "a@v1:1D", 0, equity=1.10, signal_delay=5 * H)       # bar closes T0+1D, recorded 5 h later
    conn.commit()
    before = al.build(conn, as_of_ms=T0 + D + H)                       # closed, not yet recorded
    after = al.build(conn, as_of_ms=T0 + D + 6 * H)
    assert before["nav"]["value"] == 1.0                               # lookahead leak would give 1.10
    assert before["evidence"]["observations_in_sleeve"] == 0          # and the row is not even counted
    assert after["nav"]["value"] == pytest.approx(1.10)


def test_membership_before_admission_is_empty_and_later_admission_does_not_rewrite_the_past(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _register(conn, "b@v1:1D")
    _admit(conn, "a@v1:1D", at=T0)
    _admit(conn, "b@v1:1D", at=T0 + 3 * D)                            # admitted 3 days later
    for i in range(5):
        _obs(conn, "a@v1:1D", i, equity=1.0)
        _obs(conn, "b@v1:1D", i, equity=1.0 + 0.05 * (i + 1))            # b's early winners must NOT count
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + 2 * D + H)
    assert [m["candidate_id"] for m in d["members"]] == ["a@v1:1D"]
    assert d["nav"]["value"] == 1.0
    d2 = al.build(conn, as_of_ms=T0 + 6 * D)
    assert {m["candidate_id"] for m in d2["members"]} == {"a@v1:1D", "b@v1:1D"}
    assert d2["nav"]["value"] < 1.0 + 0.05 * 5                            # b contributes only after admission


def test_backdated_admission_takes_effect_only_when_knowable_and_is_flagged(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _register(conn, "b@v1:1D")
    _admit(conn, "a@v1:1D", at=T0 + 2 * D)
    _admit(conn, "b@v1:1D", at=T0 + D)            # written AFTER a's events, but stamped earlier: backdated
    for i in range(4):
        _obs(conn, "b@v1:1D", i, equity=1.0 + 0.1 * (i + 1))
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + D + 2 * H)
    assert d["members"] == []                        # retroactive champion admission refused
    late = al.build(conn, as_of_ms=T0 + 5 * D)
    assert any(x["kind"] == "BACKDATED_EVENT" for x in late["anomalies"])
    b = [m for m in late["members"] if m["candidate_id"] == "b@v1:1D"][0]
    assert b["admitted_at"] == al._iso(T0 + 2 * D)
    assert any("anomal" in x for x in late["eligibility"]["blockers"])


def test_admission_policy_is_recorded_and_unversioned_history_is_labelled(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "v@v1:1D")
    _register(conn, "u@v1:1D")
    _admit(conn, "v@v1:1D")
    _admit(conn, "u@v1:1D", policy=False)
    _obs(conn, "v@v1:1D", 0, equity=1.0)
    _obs(conn, "u@v1:1D", 0, equity=1.0)
    conn.commit()
    d = {m["candidate_id"]: m for m in al.build(conn, as_of_ms=T0 + 2 * D)["members"]}
    assert d["v@v1:1D"]["admission_policy"] == lc.ADMISSION_POLICY_VERSION
    assert d["u@v1:1D"]["admission_policy"].startswith("reconstructed:cv1")


def test_engine_writes_the_admission_policy_version_into_new_events(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "x@v1:1D")
    bt = {"results": [{"id": "x@v1:1D", "out_of_sample": {"sharpe": 1.0}, "definition": {"timeframe": "1D"}}],
          "manifest": {"code_version": "bt1"}}
    fw._derive_stages(conn, bt, [{"id": "x@v1:1D", "qualified": True, "score": 1.0, "rejections": []}], T0)
    evs = [json.loads(r[0]) for r in conn.execute("SELECT evidence FROM lifecycle_events ORDER BY seq")]
    assert evs and all(e.get("admission_policy_version") == lc.ADMISSION_POLICY_VERSION for e in evs)
    assert all(e.get("admission_threshold_fingerprint") == lc.admission_threshold_fingerprint() for e in evs)


def test_policy_fingerprint_changes_when_a_threshold_changes(monkeypatch):
    from spa_core.trading_research import ranking
    before = lc.admission_threshold_fingerprint()
    monkeypatch.setitem(ranking.THRESHOLDS, "oos_sharpe", 0.7)
    assert lc.admission_threshold_fingerprint() != before


# ── clusters / fake diversification ────────────────────────────────────────────────────────────────────────
def test_identical_in_position_paths_collapse_into_one_cluster(tmp_path):
    conn, end = _scene(tmp_path, dup=True)
    d = al.build(conn, as_of_ms=end)
    assert ["a@v1:1D", "b@v1:1D"] in d["correlation_state"]["exact_duplicates"]
    assert d["correlation_state"]["independent_clusters"]["upper_bound"] == 2


def test_merely_flat_together_is_not_identity(tmp_path):
    conn = _db(tmp_path)
    for cid in ("p@v1:1D", "q@v1:1D"):
        _register(conn, cid)
        _admit(conn, cid)
        for i in range(5):
            _obs(conn, cid, i, equity=1.0, pos=0)
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + 6 * D)
    assert d["correlation_state"]["exact_duplicates"] == []
    assert d["correlation_state"]["independent_clusters"]["upper_bound"] == 2


def test_all_members_from_one_family_are_reported_as_concentration(tmp_path):
    conn, end = _scene(tmp_path, dup=True)
    fam = al.build(conn, as_of_ms=end)["concentration"]["value"]["families"]
    assert sum(fam.values()) == 3


# ── maturity, costs, eligibility ───────────────────────────────────────────────────────────────────────────
def test_under_30_days_no_annualised_figures(tmp_path):
    conn, end = _scene(tmp_path)
    d = al.build(conn, as_of_ms=end)
    for k in ("annualized_return", "volatility", "sharpe", "sortino"):
        assert d[k]["state"] == "NOT_ENOUGH_HISTORY" and d[k]["value"] is None


def test_at_30_days_rates_are_measured(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _admit(conn, "a@v1:1D")
    for i in range(35):
        _obs(conn, "a@v1:1D", i, equity=1.0 + 0.001 * (i + 1) + (0.002 if i % 3 == 0 else 0.0))
    _tick(conn, T0 + 36 * D)
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + 36 * D)
    assert d["annualized_return"]["state"] == "MEASURED" and d["sharpe"]["state"] == "MEASURED"


def test_unknown_cost_components_block_eligibility_and_are_never_zero(tmp_path):
    conn, end = _scene(tmp_path)
    d = al.build(conn, as_of_ms=end)
    assert d["eligibility"]["state"] == "NOT_ELIGIBLE"
    for k, v in al.COST_COMPONENTS.items():
        if v == "UNKNOWN":
            assert any(k in b for b in d["eligibility"]["blockers"])
    assert d["realized_costs"]["state"] == "NOT_MEASURED" and d["realized_costs"]["value"] is None


def test_modelled_costs_are_split_and_gross_exceeds_net(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _admit(conn, "a@v1:1D")
    _obs(conn, "a@v1:1D", 0, equity=0.9985, cost=0.0015, action="BUY")
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + 2 * D)
    c = d["estimated_costs"]["value"]
    assert c["fees"] == pytest.approx(0.001) and c["slippage"] == pytest.approx(0.0005)
    assert d["gross_return"]["value"] > d["net_return"]["value"]
    assert d["turnover"]["value"]["trading"] == pytest.approx(1.0)


def test_stale_trading_data_is_flagged_and_blocks_eligibility(tmp_path):
    conn, end = _scene(tmp_path)
    d = al.build(conn, as_of_ms=end + 5 * H, now_ms=end + 5 * H)
    assert d["freshness"]["value"]["state"] == "STALE"
    assert "trading data is STALE" in d["eligibility"]["blockers"]


def test_missing_observation_is_not_filled_in(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _admit(conn, "a@v1:1D")
    _obs(conn, "a@v1:1D", 0, equity=1.02)
    _obs(conn, "a@v1:1D", 3, equity=1.05)           # bars 1–2 missing: no fabricated path between
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + 5 * D)
    assert d["nav"]["value"] == pytest.approx(1.05) and d["evidence"]["observations_in_sleeve"] == 2


def test_duplicated_experiment_registration_and_observation_are_refused_by_the_store(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    assert ev.register(conn, "a@v1:1D", "h", {}, now_ms=T0, code_version="cv1") is False
    _admit(conn, "a@v1:1D")
    _obs(conn, "a@v1:1D", 0, equity=1.02)
    _obs(conn, "a@v1:1D", 0, equity=9.99)           # the same bar again: never overwrites
    conn.commit()
    assert al.build(conn, as_of_ms=T0 + 2 * D)["nav"]["value"] == pytest.approx(1.02)


# ── refusals (fail-CLOSED) ────────────────────────────────────────────────────────────────────────────────
def test_corrupt_forward_ledger_is_refused(tmp_path):
    conn, end = _scene(tmp_path)
    conn.execute("DROP TRIGGER observations_no_update")
    conn.execute("UPDATE observations SET equity = equity + 0.5 WHERE seq = 2")
    conn.commit()
    with pytest.raises(al.SleeveRefused) as e:
        al.build(conn, as_of_ms=end)
    assert e.value.code == "CORRUPT_LEDGER"


def test_reset_or_reseed_is_refused(tmp_path):
    conn, end = _scene(tmp_path)
    prev = al.build(conn, as_of_ms=end)
    fresh = _db(tmp_path, "reseeded.db")
    _register(fresh, "a@v1:1D", at=T0 + 3 * D)                  # forward clock moved
    _admit(fresh, "a@v1:1D", at=T0 + 3 * D)
    fresh.commit()
    with pytest.raises(al.SleeveRefused) as e:
        al.build(fresh, as_of_ms=end, previous=prev)
    assert e.value.code == "RESET_DETECTED"
    shrunk = dict(prev)
    shrunk["provenance"] = {**prev["provenance"], "counts": {**prev["provenance"]["counts"], "observations": 10 ** 6}}
    with pytest.raises(al.SleeveRefused):
        al.build(conn, as_of_ms=end, previous=shrunk)


def test_a_live_stage_anywhere_refuses_the_paper_sleeve(tmp_path):
    conn, end = _scene(tmp_path)
    ev.append_event(conn, "a@v1:1D", "FORWARD_PAPER", "PRODUCTION", "forged", {}, actor="x", now_ms=end)
    conn.commit()
    with pytest.raises(al.SleeveRefused) as e:
        al.build(conn, as_of_ms=end)
    assert e.value.code == "LIVE_STAGE_PRESENT"


def test_the_sleeve_never_claims_real_capital_or_execution(tmp_path):
    conn, end = _scene(tmp_path)
    d = al.build(conn, as_of_ms=end)
    assert d["real_capital_usd"] == 0 and d["executes"] is False and d["capital_mode"] == "PAPER"
    assert d["evidence_class"] == "FORWARD_PAPER"


def test_the_sleeve_opens_the_store_read_only(tmp_path):
    conn, _ = _scene(tmp_path)
    conn.close()
    ro = al.open_readonly(tmp_path / "evidence.db")
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO ticks (started_ms,finished_ms,new_bars,new_observations,ok,detail,code_version) "
                   "VALUES (1,1,0,0,1,'{}','x')")


# ── Capital Sources view ───────────────────────────────────────────────────────────────────────────────────
def _sleeve(sid, **cells):
    base = {f: contract.absent(contract.NOT_MEASURED, reason="test") for f in contract.SLEEVE_FIELDS}
    base.update({"sleeve_id": sid, "name": contract.SLEEVES[sid]["name"],
                 "allocatable": contract.SLEEVES[sid]["allocatable"], "gates": [], "experiment_start": None})
    base.update(cells)
    return base


def test_registry_has_every_source_type_and_every_contract_field(tmp_path):
    conn, end = _scene(tmp_path)
    alpha = al.build(conn, as_of_ms=end)
    sleeves = {sid: _sleeve(sid) for sid in contract.SLEEVES}
    reg = cs.registry(sleeves, trading_alpha=alpha)
    assert set(reg["source_types"]) == set(contract.SOURCE_TYPES)
    for s in reg["sources"]:
        assert set(contract.CAPITAL_SOURCE_FIELDS) <= set(s)
    assert reg["executes"] is False and reg["real_capital_usd"] == 0


def test_placeholder_sources_keep_numbers_absent_never_zero():
    reg = cs.registry({sid: _sleeve(sid) for sid in contract.SLEEVES})
    basis = [s for s in reg["sources"] if s["source_type"] == contract.SOURCE_MARKET_NEUTRAL_BASIS][0]
    for k in ("net_return", "annualized_return", "drawdown", "volatility", "sharpe"):
        assert basis[k]["state"] != contract.MEASURED and basis[k]["value"] is None


def test_an_immature_source_is_not_eligible():
    mat = contract.measured(contract.MATURITY_IMMATURE, unit=None, source="t", as_of=None)
    reg = cs.registry({"defi_aggressive": _sleeve("defi_aggressive", maturity=mat)})
    agg = [s for s in reg["sources"] if s["source_id"] == "defi_aggressive"][0]
    assert agg["eligibility"]["state"] == "NOT_ELIGIBLE"
    assert any("IMMATURE" in b for b in agg["blockers"])


def test_percent_returns_are_normalised_to_fractions_with_the_unit_kept():
    rr = contract.measured(4.8943, unit="pct_annualized", source="t", as_of="x", n=106)
    reg = cs.registry({"defi_conservative": _sleeve("defi_conservative", realized_return=rr)})
    c = [s for s in reg["sources"] if s["source_id"] == "defi_conservative"][0]
    assert c["annualized_return"]["value"] == pytest.approx(0.048943)
    assert "pct_annualized" in c["annualized_return"]["unit"]


def test_a_refused_trading_alpha_sleeve_becomes_a_named_blocker():
    reg = cs.registry({sid: _sleeve(sid) for sid in contract.SLEEVES},
                      trading_alpha_refusal="CORRUPT_LEDGER: hash chain breaks")
    tr = [s for s in reg["sources"] if s["source_type"] == contract.SOURCE_TRADING_ALPHA][0]
    assert tr["blockers"][0].startswith("Trading Alpha sleeve refused: CORRUPT_LEDGER")
    assert tr["net_return"]["state"] != contract.MEASURED



# ── independent review of 0b065dd64 (07.10) ────────────────────────────────────────────────────────────────
def _long_scene(tmp_path, days, paths):
    """`paths`: {cid: [daily equity…]} — all admitted at T0, 1D bars, in a position every day."""
    conn = _db(tmp_path)
    for cid, eqs in paths.items():
        _register(conn, cid)
        _admit(conn, cid)
        for i, e in enumerate(eqs[:days]):
            _obs(conn, cid, i, equity=e)
    _tick(conn, T0 + (days + 1) * D)
    conn.commit()
    return conn, T0 + (days + 1) * D


def _walk(seed, n, scale=0.01):
    import random
    rnd = random.Random(seed)
    eq, out = 1.0, []
    for _ in range(n):
        eq *= 1 + rnd.uniform(-scale, scale)
        out.append(eq)
    return out


def test_p1_1_unmeasured_diversification_blocks_eligibility_and_count_is_an_upper_bound(tmp_path):
    conn, end = _scene(tmp_path)
    d = al.build(conn, as_of_ms=end)
    ic = d["correlation_state"]["independent_clusters"]
    assert ic["verified"] is False and ic["display"].startswith("≤")
    assert any(b.startswith("diversification not measured") for b in d["eligibility"]["blockers"])


def test_p1_1_near_duplicates_merge_once_overlap_suffices(tmp_path):
    base = _walk(1, 40)
    near = [e * (1.0 + (0.0005 if i >= 5 else 0.0)) for i, e in enumerate(base)]   # diverges from bar 5 on
    other = _walk(99, 40)
    conn, end = _long_scene(tmp_path, 40, {"a@v1:1D": base, "b@v1:1D": near, "c@v1:1D": other})
    d = al.build(conn, as_of_ms=end)
    assert d["correlation_state"]["forward_cluster_correlation"]["state"] == "MEASURED"
    assert d["correlation_state"]["independent_clusters"] == {"upper_bound": 2, "verified": True, "display": "2"}
    assert ["a@v1:1D", "b@v1:1D"] in [c["members"] for c in d["clusters"]]
    assert not any(b.startswith("diversification") for b in d["eligibility"]["blockers"])
    # causal: before 30 shared days the same pair is NOT merged by correlation
    early = al.build(conn, as_of_ms=T0 + 15 * D)          # divergence known, overlap 14 d < 30
    assert ["a@v1:1D", "b@v1:1D"] not in [c["members"] for c in early["clusters"]]


def test_p2_3_bar_straddling_admission_is_not_credited(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _register(conn, "z@v1:1D")
    _admit(conn, "z@v1:1D", at=T0)                       # opens the sleeve at T0
    _admit(conn, "a@v1:1D", at=T0 + 12 * H)               # a joins mid-bar
    _obs(conn, "z@v1:1D", 0, equity=1.0)
    _obs(conn, "a@v1:1D", 0, equity=1.50)                 # bar 0 opened BEFORE a's admission: +50 %
    _obs(conn, "a@v1:1D", 1, equity=1.50)
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + 3 * D)
    assert d["nav"]["value"] == pytest.approx(1.0)        # the pre-admission half-bar is never credited
    assert "1 bar(s) that opened before an admission were not credited" in d["notes"]


def test_p2_5_readmission_uses_the_latest_episode(tmp_path):
    conn = _db(tmp_path)
    _register(conn, "a@v1:1D")
    _register(conn, "z@v1:1D")
    _admit(conn, "z@v1:1D", at=T0)
    _admit(conn, "a@v1:1D", at=T0)
    _obs(conn, "a@v1:1D", 0, equity=1.10)
    ev.append_event(conn, "a@v1:1D", "FORWARD_PAPER", "REJECTED", "test", {}, actor="t", now_ms=T0 + D + H)
    _obs(conn, "a@v1:1D", 1, equity=2.00)                 # while rejected (still in position): not credited
    ev.append_event(conn, "a@v1:1D", "REJECTED", "BACKTEST_QUALIFIED", "t",
                    {"admission_policy_version": "v-new"}, actor="t", now_ms=T0 + 2 * D + H)
    ev.append_event(conn, "a@v1:1D", "BACKTEST_QUALIFIED", "FORWARD_PAPER", "t",
                    {"admission_policy_version": "v-new"}, actor="t", now_ms=T0 + 2 * D + H)
    _obs(conn, "a@v1:1D", 2, equity=2.00)
    _obs(conn, "a@v1:1D", 3, equity=2.20)                 # +10 % inside the new episode
    for i in range(4):
        _obs(conn, "z@v1:1D", i, equity=1.0)
    conn.commit()
    d = al.build(conn, as_of_ms=T0 + 5 * D)
    a = [m for m in d["members"] if m["candidate_id"] == "a@v1:1D"][0]
    assert a["admitted_at"] == al._iso(T0 + 2 * D + H) and a["admission_episode"] == 2
    assert a["admission_policy"] == "v-new"
    # credited: +10 % in episode 1 (bar 0) and +10 % in episode 2 (bar 3); the +81.8 % while rejected is not
    assert d["nav"]["value"] < 1.25


def test_p2_8_robust_share_is_by_weight(tmp_path):
    conn, end = _scene(tmp_path)
    d = al.build(conn, as_of_ms=end)
    assert d["robust_weight_share"]["value"] == 0.0
    assert any("forward-robust" in b for b in d["eligibility"]["blockers"])


def test_p2_d_selection_check_compares_admitted_with_all_candidates(tmp_path):
    conn, end = _scene(tmp_path)
    _register(conn, "r@v1:1D")                            # a rejected candidate is still observed forward
    for i in range(3):
        _obs(conn, "r@v1:1D", i, equity=0.9)
    conn.commit()
    sc = al.build(conn, as_of_ms=end)["selection_check"]
    assert sc["state"] == "MEASURED" and sc["value"]["all_candidates_n"] == 4
    assert "never an admission input" in sc["note"]


def test_p2_10_notes_name_partial_day_mixed_cadence_and_tick_start(tmp_path):
    conn, end = _scene(tmp_path)
    notes = " ".join(al.build(conn, as_of_ms=end)["notes"])
    for k in ("partial", "cadence", "tick", "excludes rebalance"):
        assert k in notes


def test_p1_2_no_constant_is_stamped_measured_in_capital_sources(tmp_path):
    conn, end = _scene(tmp_path)
    src = cs.from_trading_alpha(al.build(conn, as_of_ms=end))
    assert src["liquidity"]["state"] != contract.MEASURED and src["confidence"]["state"] != contract.MEASURED
    assert src["declared_assumptions"]["kind"].startswith("ASSUMPTION")


def test_p2_9_trading_alpha_carries_the_research_only_blocker(tmp_path):
    conn, end = _scene(tmp_path)
    src = cs.from_trading_alpha(al.build(conn, as_of_ms=end))
    assert src["blockers"][0] == "not allocatable in the ADR-554 contract (research only)"


def test_p2_4_gates_judge_only_history_before_the_forward_clock():
    from spa_core.trading_research import ranking
    from types import SimpleNamespace as B
    bars = [B(open_time=i, close=100 + i) for i in range(10)] + [B(open_time=10 + i, close=10.0) for i in range(5)]
    full = ranking.benchmark(bars, "1D")
    cut = ranking.benchmark(bars, "1D", end_ms=10)
    assert cut["max_drawdown"] > full["max_drawdown"]        # the crash after forward start is not seen
    r = {"gating": {"trades": 20, "max_drawdown": -0.1, "calmar": 9.0},
         "full": {"trades": 1, "max_drawdown": -0.9, "calmar": 0.1}}
    assert ranking._gate(r, "trades") == 20 and ranking._gate(r, "max_drawdown") == -0.1
    assert ranking._gate({"full": {"trades": 3}}, "trades") == 3     # old backtest.json: refresh is forced


# ── re-review residuals (07.10) ────────────────────────────────────────────────────────────────────────────
def test_gate_window_is_one_window_for_metrics_and_benchmark():
    from spa_core.trading_research import ranking
    with_slice = {"manifest": {"oos_end_ms": 123}, "results": [{"gating": {}}, {"gating": {}}]}
    old_file = {"manifest": {"oos_end_ms": 123}, "results": [{"gating": {}}, {"full": {}}]}
    assert ranking.gate_window_end(with_slice) == 123
    assert ranking.gate_window_end(old_file) is None        # metrics fall back to `full` ⇒ benchmark too


def test_status_names_the_benchmark_window():
    src = (al.Path(fw.__file__)).read_text(encoding="utf-8")
    assert '"benchmark_window": {"kind": "buy_and_hold_btc"' in src
    assert '"benchmark": {tf: {"sharpe"' in src                # existing consumers keep their field


def test_constant_series_pair_is_undefined_not_independent(tmp_path):
    flat_in_position = [1.0] * 40                            # in a position, equity never moves
    conn, end = _long_scene(tmp_path, 40, {"a@v1:1D": _walk(3, 40), "b@v1:1D": flat_in_position})
    d = al.build(conn, as_of_ms=end)
    cs_ = d["correlation_state"]
    pair = list(cs_["forward_cluster_correlation"]["value"]["pairs"].values())[0] \
        if cs_["forward_cluster_correlation"]["state"] == "MEASURED" else None
    assert pair is None                                      # never «measured and not merged»
    assert cs_["forward_cluster_correlation"]["state"] == "UNDEFINED"
    assert cs_["independent_clusters"]["verified"] is False and "UNDEFINED" in cs_["independent_clusters"]["display"]
    assert any(b.startswith("diversification not measured") for b in d["eligibility"]["blockers"])
