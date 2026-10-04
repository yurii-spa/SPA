"""Tests for the ADR-564 (RM-EVIDENCE-01) Package E2 paper ledger (``spa_core.research_factory.
paper``) — admission gating, no-missing-as-zero fee accounting, units math, stale marks (never
forward-filled), mark provenance/circularity, performance-fee net-price skip, two-leg funding
positions, forward-counting separation, and every refusal path.

Time is INJECTED throughout: every call passes ``now=NOW`` (or an offset derived from it); the
only thing read from a cell's own fields is ``as_of``/``retrieved_at`` strings that are
themselves built from NOW. Nothing here asks the wall clock anything.
# FROZEN-DATE-OK: injected-clock — the anchor NOW (and every NOW + timedelta(...) built from it)
# is passed as the `now=` argument to every open_position/mark/cashflow/unit_change/close/nav
# call in this file; no assertion compares a literal date to the real clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from spa_core.research_factory import contract as c1
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory import paper

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────

def _cell(state=c1.ESTIMATED_WITH_METHOD, value=None, **kw):
    if state in c1.VALUED_STATES:
        kw.setdefault("method", "test fixture")
        # H3: mark() now judges a price cell's OWN as_of for freshness — default every valued
        # test cell to "just observed" (NOW) unless a test explicitly says otherwise, so existing
        # fixtures stay FRESH without each call site having to think about freshness.
        kw.setdefault("as_of", NOW.isoformat())
        return c1.cell(state, value, **kw)
    kw.setdefault("reason", "test fixture")
    return c1.cell(state, reason=kw.pop("reason"))


def _fee(kind, state=c1.ESTIMATED_WITH_METHOD, value=0.0, unit="usd"):
    return {"kind": kind, "cell": _cell(state, value), "unit": unit,
           "effective_from": NOW.isoformat(), "subject_to_change": False, "one_off": kind in ("entry", "exit")}


def _acc_block(**overrides):
    block = {
        "entry_price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
        "entry_fee_components": [_fee("entry", c1.ESTIMATED_WITH_METHOD, 0.0)],
        "exit_fee_components": [_fee("exit", c1.ESTIMATED_WITH_METHOD, 0.0)],
        "redemption_delay_days": _cell(c1.ESTIMATED_WITH_METHOD, 0.0),
        "price_is_net_of_performance_fee": _cell(c1.NOT_APPLICABLE, reason="no performance fee on this product"),
        "performance_fee_rate": None,
        "leverage": _cell(c1.NOT_APPLICABLE, reason="no leverage"),
        "maintenance_margin_rate": _cell(c1.NOT_APPLICABLE, reason="no leverage"),
        "collateral_yield_rate": None,
        "fee_source": "test fixture",
        "holding_period_days_declared": 30.0,
        "return_origin_group": "group:issuer",
    }
    block.update(overrides)
    return block


def _setup(paper_mode=ec.PAPER_MODE_HOLDABLE, acc=None, candidate_id="cand1", decision_id="dec1",
          admission_id="adm1", bundle_digest="bd1"):
    acc = acc if acc is not None else _acc_block()
    decision = {"schema_version": ec.SCHEMA_DECISION, "decision_id": decision_id, "candidate_id": candidate_id,
               "generated_at": NOW.isoformat(), "decision": ec.ADMIT_TO_PAPER, "bundle_digest": bundle_digest,
               "paper_mode": paper_mode, "policy_version": ec.POLICY_VERSION}
    admission = {"schema": ec.SCHEMA_ADMISSION_V2, "admission_id": admission_id, "candidate_id": candidate_id,
                "decision_id": decision_id, "bundle_digest": bundle_digest, "policy_version": ec.POLICY_VERSION,
                "paper_mode": paper_mode, "evidence_ceiling": ec.CEILING_OBSERVED, "as_of": NOW.isoformat(),
                "recorded_at": NOW.isoformat(), "code_identity": "test"}
    bundle = {"schema_version": ec.SCHEMA_BUNDLE, "candidate_id": candidate_id, "evidence_digest": bundle_digest,
             "paper_accounting_evidence": acc}
    return decision, admission, bundle


def _open(tmp_path, **kw) -> dict:
    decision, admission, bundle = _setup(**kw)
    return paper.open_position(tmp_path, decision, admission, bundle, NOW)["payload"]


def _mark(tmp_path, position_id, obs, now):
    return paper.mark(tmp_path, position_id, obs, now)["payload"]


def _cashflow(tmp_path, position_id, settlement, now):
    return paper.cashflow(tmp_path, position_id, settlement, now)["payload"]


def _unit_change(tmp_path, position_id, event, now):
    return paper.unit_change(tmp_path, position_id, event, now)["payload"]


def _close(tmp_path, position_id, obs, now, reason):
    return paper.close(tmp_path, position_id, obs, now, reason)["payload"]


# ── gate ─────────────────────────────────────────────────────────────────────────────────────

def test_open_refuses_without_admit_decision(tmp_path):
    decision, admission, bundle = _setup()
    decision["decision"] = ec.HOLD
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)


def test_open_refuses_admission_schema_mismatch(tmp_path):
    decision, admission, bundle = _setup()
    admission["schema"] = "paper-admission/1"
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)


def test_open_refuses_decision_id_mismatch(tmp_path):
    decision, admission, bundle = _setup()
    admission["decision_id"] = "some-other-decision"
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)


def test_open_refuses_bundle_digest_mismatch_admission(tmp_path):
    decision, admission, bundle = _setup()
    admission["bundle_digest"] = "wrong-digest"
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)


def test_open_refuses_bundle_digest_mismatch_bundle(tmp_path):
    decision, admission, bundle = _setup()
    bundle["evidence_digest"] = "wrong-digest"
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)


def test_open_refuses_candidate_id_mismatch(tmp_path):
    decision, admission, bundle = _setup()
    bundle["candidate_id"] = "someone-else"
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)


def test_open_refuses_unknown_paper_mode(tmp_path):
    decision, admission, bundle = _setup()
    decision["paper_mode"] = "SOMETHING_ELSE"
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)


# ── no missing-as-zero ───────────────────────────────────────────────────────────────────────

def test_open_refuses_not_measured_entry_price(tmp_path):
    acc = _acc_block(entry_price=_cell(c1.NOT_MEASURED))
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc)


def test_open_refuses_missing_entry_fee_components(tmp_path):
    acc = _acc_block(entry_fee_components=[])
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc)


def test_open_refuses_not_measured_entry_fee_component(tmp_path):
    acc = _acc_block(entry_fee_components=[_fee("entry", c1.NOT_MEASURED)])
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc)


def test_open_refuses_missing_exit_fee_components_for_holdable(tmp_path):
    acc = _acc_block(exit_fee_components=[])
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc, paper_mode=ec.PAPER_MODE_HOLDABLE)


def test_open_refuses_not_measured_exit_fee_component(tmp_path):
    acc = _acc_block(exit_fee_components=[_fee("exit", c1.NOT_MEASURED)])
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc, paper_mode=ec.PAPER_MODE_HOLDABLE)


def test_open_refuses_not_measured_redemption_delay_for_holdable(tmp_path):
    acc = _acc_block(redemption_delay_days=_cell(c1.NOT_MEASURED))
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc, paper_mode=ec.PAPER_MODE_HOLDABLE)


def test_open_reference_track_does_not_need_exit_fee_components(tmp_path):
    acc = _acc_block(exit_fee_components=[])
    row = _open(tmp_path, acc=acc, paper_mode=ec.PAPER_MODE_REFERENCE_TRACK)
    assert row["paper_mode"] == ec.PAPER_MODE_REFERENCE_TRACK
    assert row["redemption_delay_days"] == 0.0


def test_mutation_check_entry_fee_refusal_depends_on_valued_states(tmp_path, monkeypatch):
    """Prove the "no missing-as-zero" refusal genuinely reads contract.VALUED_STATES — not a
    vacuous always-raise. A raw (non-contract.cell()) NOT_MEASURED cell smuggling a numeric
    value is refused as-is; widen VALUED_STATES to (wrongly) accept NOT_MEASURED and the SAME
    call now succeeds, proving the guard's sensitivity to the real constant."""
    smuggled = {"state": c1.NOT_MEASURED, "value": 123.0}
    acc = _acc_block(entry_fee_components=[{"kind": "entry", "cell": smuggled, "unit": "usd"}])
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc)
    monkeypatch.setattr(c1, "VALUED_STATES", c1.VALUED_STATES + (c1.NOT_MEASURED,))
    row = _open(tmp_path, acc=acc)
    assert row["entry_fees_usd"] == 123.0


def test_mutation_check_admit_gate_depends_on_admit_to_paper_constant(tmp_path, monkeypatch):
    """Prove the admission gate reads evidence_contract.ADMIT_TO_PAPER, not a hard-coded
    string: a HOLD decision is refused as-is, but passes once the constant is (wrongly)
    redefined to equal HOLD."""
    decision, admission, bundle = _setup()
    decision["decision"] = "HOLD"
    with pytest.raises(paper.PaperRefusal):
        paper.open_position(tmp_path, decision, admission, bundle, NOW)
    monkeypatch.setattr(ec, "ADMIT_TO_PAPER", "HOLD")
    paper.open_position(tmp_path, decision, admission, bundle, NOW)  # no longer refuses


# ── units / fees math ────────────────────────────────────────────────────────────────────────

def test_units_equals_notional_over_entry_price(tmp_path):
    acc = _acc_block(entry_price=_cell(c1.ESTIMATED_WITH_METHOD, 2.5))
    row = _open(tmp_path, acc=acc)
    assert row["units"] == pytest.approx(ec.PAPER_NOTIONAL_USD / 2.5)
    assert row["entry_value_usd"] == pytest.approx(ec.PAPER_NOTIONAL_USD)


def test_entry_fee_bps_scales_off_notional(tmp_path):
    acc = _acc_block(entry_fee_components=[_fee("entry", c1.ESTIMATED_WITH_METHOD, 50.0, unit="bps")])
    row = _open(tmp_path, acc=acc)
    assert row["entry_fees_usd"] == pytest.approx(ec.PAPER_NOTIONAL_USD * 50.0 / 10_000.0)
    assert row["cash_usd"] == pytest.approx(-row["entry_fees_usd"])


def test_open_refuses_non_positive_entry_price(tmp_path):
    acc = _acc_block(entry_price=_cell(c1.ESTIMATED_WITH_METHOD, 0.0))
    with pytest.raises(paper.PaperRefusal):
        _open(tmp_path, acc=acc)


def test_open_is_idempotent_same_admission_returns_same_row(tmp_path):
    from spa_core.research_factory._common import ledger_for
    row1 = _open(tmp_path)
    row2 = _open(tmp_path)
    assert row1["position_id"] == row2["position_id"]
    opens = [e for e in ledger_for(tmp_path).read_all() if e.get("kind") == "paper_open"]
    assert len(opens) == 1


def test_open_different_admission_opens_a_new_position(tmp_path):
    row1 = _open(tmp_path, admission_id="adm1")
    row2 = _open(tmp_path, admission_id="adm2")
    assert row1["position_id"] != row2["position_id"]


# ── two-leg (funding pair) positions ─────────────────────────────────────────────────────────

def test_two_leg_bundle_opens_two_positions_with_leg_id(tmp_path):
    legs_acc = {"legs": {"perp": _acc_block(), "spot": _acc_block()}}
    decision, admission, bundle = _setup(acc=legs_acc)
    result = paper.open_position(tmp_path, decision, admission, bundle, NOW)
    legs = {leg_id: entry["payload"] for leg_id, entry in result["legs"].items()}
    assert set(legs) == {"perp", "spot"}
    assert legs["perp"]["leg_id"] == "perp"
    assert legs["spot"]["leg_id"] == "spot"
    assert legs["perp"]["position_id"] != legs["spot"]["position_id"]


def test_single_leg_position_has_leg_id_none(tmp_path):
    row = _open(tmp_path)
    assert row["leg_id"] is None


# ── mark: stale never forward-fills ──────────────────────────────────────────────────────────

def test_mark_records_fresh_price_and_nav(tmp_path):
    row = _open(tmp_path)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.1),
                                                 "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m["mark_state"] == "FRESH"
    assert m["position_value_usd"] == pytest.approx(row["units"] * 1.1)
    assert m["nav_usd"] is not None


def test_mark_needs_mark_origin(tmp_path):
    row = _open(tmp_path)
    with pytest.raises(paper.PaperRefusal):
        paper.mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.1)},
                  NOW + timedelta(days=1))


def test_mark_refuses_on_closed_position(tmp_path):
    row = _open(tmp_path)
    paper.close(tmp_path, row["position_id"],
               {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                "redemption_delay_haircut_rate": _cell(c1.NOT_APPLICABLE, reason="n/a"),
                "slippage": _cell(c1.NOT_APPLICABLE, reason="n/a")},
               NOW + timedelta(days=2), reason="test close")
    with pytest.raises(paper.PaperRefusal):
        paper.mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.1),
                                                   "mark_origin": "issuer:acme"}, NOW + timedelta(days=3))


def test_stale_mark_has_no_price_and_never_forward_fills(tmp_path):
    row = _open(tmp_path)
    fresh = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.2),
                                                       "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert fresh["nav_usd"] is not None
    stale = _mark(tmp_path, row["position_id"], {"price": _cell(c1.NOT_MEASURED),
                                                       "mark_origin": "issuer:acme"}, NOW + timedelta(days=2))
    assert stale["mark_state"] == "STALE"
    assert stale["position_value_usd"] is None
    assert stale["nav_usd"] is None  # never forward-filled from the fresh row above


def test_mutation_check_stale_never_leaks_a_smuggled_price(tmp_path, monkeypatch):
    """A raw cell claiming NOT_MEASURED but smuggling a numeric value must still produce a
    NAV-less STALE row. Widening VALUED_STATES to (wrongly) accept it proves the guard: the
    smuggled number then leaks straight into nav_usd."""
    row = _open(tmp_path)
    smuggled = {"state": c1.NOT_MEASURED, "value": 999.0, "as_of": NOW.isoformat()}
    stale = _mark(tmp_path, row["position_id"], {"price": smuggled, "mark_origin": "issuer:acme"},
                       NOW + timedelta(days=1))
    assert stale["nav_usd"] is None
    monkeypatch.setattr(c1, "VALUED_STATES", c1.VALUED_STATES + (c1.NOT_MEASURED,))
    # a DIFFERENT upstream as_of than the first call's — otherwise H3's own (position_id, as_of)
    # idempotency key would dedupe this to the FIRST (STALE) row and the mutation would prove
    # nothing about THIS code path.
    smuggled2 = {"state": c1.NOT_MEASURED, "value": 999.0, "as_of": (NOW + timedelta(hours=6)).isoformat()}
    leaked = _mark(tmp_path, row["position_id"], {"price": smuggled2, "mark_origin": "issuer:acme"},
                        NOW + timedelta(days=2))
    assert leaked["nav_usd"] is not None
    assert leaked["position_value_usd"] == pytest.approx(row["units"] * 999.0)


def test_mark_leg_id_must_match_position(tmp_path):
    legs_acc = {"legs": {"perp": _acc_block(), "spot": _acc_block()}}
    decision, admission, bundle = _setup(acc=legs_acc)
    result = paper.open_position(tmp_path, decision, admission, bundle, NOW)
    perp_id = result["legs"]["perp"]["payload"]["position_id"]
    with pytest.raises(paper.PaperRefusal):
        paper.mark(tmp_path, perp_id, {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                       "mark_origin": "venue:binance", "leg_id": "spot"}, NOW + timedelta(days=1))


# ── mark provenance + circularity ────────────────────────────────────────────────────────────

def test_mark_circular_true_when_same_origin_group(tmp_path):
    row = _open(tmp_path)  # return_origin_group == "group:issuer"
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                                   "mark_origin": "issuer:acme", "origin_group": "group:issuer"},
                  NOW + timedelta(days=1))
    assert m["mark_circular"] is True


def test_mark_circular_false_when_different_origin_group(tmp_path):
    row = _open(tmp_path)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                                   "mark_origin": "chain:1", "origin_group": "group:chainlink"},
                  NOW + timedelta(days=1))
    assert m["mark_circular"] is False


def test_mark_circular_unknown_when_origin_group_not_given(tmp_path):
    row = _open(tmp_path)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                                   "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m["mark_circular"] is None  # absence represented distinctly, never False-by-default


# ── performance fee ──────────────────────────────────────────────────────────────────────────

def test_performance_fee_not_applicable_when_price_is_net(tmp_path):
    acc = _acc_block(price_is_net_of_performance_fee=_cell(c1.NOT_APPLICABLE, reason="price is net"),
                     performance_fee_rate=_cell(c1.ESTIMATED_WITH_METHOD, 0.5))
    row = _open(tmp_path, acc=acc)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 2.0),
                                                   "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m["performance_fee_accrual_usd"] == 0.0  # 2x gain, 50% perf fee, but NOT_APPLICABLE wins


def test_performance_fee_accrues_on_gain_above_high_water_mark(tmp_path):
    acc = _acc_block(price_is_net_of_performance_fee=None,
                     performance_fee_rate=_cell(c1.ESTIMATED_WITH_METHOD, 0.2))
    row = _open(tmp_path, acc=acc)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 2.0),
                                                   "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    gain = row["units"] * 2.0 - row["initial_notional_usd"]
    assert m["performance_fee_accrual_usd"] == pytest.approx(0.2 * gain)


def test_mutation_check_performance_fee_sensitive_to_price_is_net_flag(tmp_path):
    """Prove the performance-fee skip is reading row['price_is_net'], not vacuously always 0:
    the SAME rate+gain accrues a fee once price_is_net is turned off."""
    net_acc = _acc_block(price_is_net_of_performance_fee=_cell(c1.NOT_APPLICABLE, reason="price is net"),
                         performance_fee_rate=_cell(c1.ESTIMATED_WITH_METHOD, 0.3))
    row_net = _open(tmp_path, acc=net_acc, admission_id="adm-net")
    m_net = _mark(tmp_path, row_net["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 3.0),
                                                          "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m_net["performance_fee_accrual_usd"] == 0.0

    gross_acc = _acc_block(price_is_net_of_performance_fee=None,
                           performance_fee_rate=_cell(c1.ESTIMATED_WITH_METHOD, 0.3))
    row_gross = _open(tmp_path, acc=gross_acc, admission_id="adm-gross")
    m_gross = _mark(tmp_path, row_gross["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 3.0),
                                                              "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m_gross["performance_fee_accrual_usd"] > 0.0


# ── leveraged legs: margin / liquidation distance ────────────────────────────────────────────

def test_liquidation_distance_is_estimated_with_method_never_measured(tmp_path):
    acc = _acc_block(leverage=_cell(c1.ESTIMATED_WITH_METHOD, 5.0),
                     maintenance_margin_rate=_cell(c1.ESTIMATED_WITH_METHOD, 0.05))
    row = _open(tmp_path, acc=acc)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                                   "mark_origin": "venue:binance"}, NOW + timedelta(days=1))
    assert m["liquidation_distance"]["state"] == c1.ESTIMATED_WITH_METHOD
    assert m["margin_usd"] == pytest.approx(ec.PAPER_NOTIONAL_USD / 5.0)


def test_liquidation_distance_is_none_without_leverage(tmp_path):
    row = _open(tmp_path)  # leverage is NOT_APPLICABLE in the default fixture
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                                   "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m["liquidation_distance"] is None
    assert m["margin_usd"] is None


# ── cashflow (funding) ───────────────────────────────────────────────────────────────────────

def test_cashflow_refuses_without_a_prior_mark(tmp_path):
    row = _open(tmp_path)
    settlement = {"settlement_ts": (NOW + timedelta(hours=8)).isoformat(),
                 "funding_rate": _cell(c1.ESTIMATED_WITH_METHOD, 0.0001)}
    with pytest.raises(paper.PaperRefusal):
        paper.cashflow(tmp_path, row["position_id"], settlement, NOW + timedelta(hours=8))


def test_cashflow_uses_notional_at_settlement_mark(tmp_path):
    row = _open(tmp_path)
    paper.mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 2.0),
                                              "mark_origin": "venue:binance"}, NOW + timedelta(hours=1))
    settlement_ts = NOW + timedelta(hours=8)
    settlement = {"settlement_ts": settlement_ts.isoformat(), "funding_rate": _cell(c1.ESTIMATED_WITH_METHOD, 0.001)}
    cf = _cashflow(tmp_path, row["position_id"], settlement, settlement_ts)
    notional_at_mark = row["units"] * 2.0
    assert cf["funding_usd"] == pytest.approx(notional_at_mark * 0.001)


def test_cashflow_refuses_on_unvalued_funding_rate(tmp_path):
    row = _open(tmp_path)
    paper.mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                              "mark_origin": "venue:binance"}, NOW + timedelta(hours=1))
    settlement = {"settlement_ts": (NOW + timedelta(hours=8)).isoformat(), "funding_rate": _cell(c1.NOT_MEASURED)}
    with pytest.raises(paper.PaperRefusal):
        paper.cashflow(tmp_path, row["position_id"], settlement, NOW + timedelta(hours=8))


def test_cashflow_bps_unit_normalised(tmp_path):
    row = _open(tmp_path)
    paper.mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                              "mark_origin": "venue:binance"}, NOW + timedelta(hours=1))
    settlement_ts = NOW + timedelta(hours=8)
    settlement = {"settlement_ts": settlement_ts.isoformat(), "funding_rate": _cell(c1.ESTIMATED_WITH_METHOD, 5.0),
                 "unit": "bps"}
    cf = _cashflow(tmp_path, row["position_id"], settlement, settlement_ts)
    assert cf["funding_usd"] == pytest.approx(row["units"] * 1.0 * 5.0 / 10_000.0)


def test_cashflow_is_idempotent_same_settlement(tmp_path):
    row = _open(tmp_path)
    paper.mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                              "mark_origin": "venue:binance"}, NOW + timedelta(hours=1))
    settlement_ts = NOW + timedelta(hours=8)
    settlement = {"settlement_ts": settlement_ts.isoformat(), "funding_rate": _cell(c1.ESTIMATED_WITH_METHOD, 0.001)}
    cf1 = _cashflow(tmp_path, row["position_id"], settlement, settlement_ts)
    cf2 = _cashflow(tmp_path, row["position_id"], settlement, settlement_ts)
    assert cf1["funding_usd"] == cf2["funding_usd"]


# ── unit change (dividend mints, rebases) ────────────────────────────────────────────────────

def test_unit_change_dividend_mint_increases_units(tmp_path):
    row = _open(tmp_path)
    event = {"event_id": "div-2026-10-05", "units_delta": _cell(c1.ESTIMATED_WITH_METHOD, 1.0)}
    r = _unit_change(tmp_path, row["position_id"], event, NOW + timedelta(days=1))
    assert r["units"] == pytest.approx(row["units"] + 1.0)


def test_unit_change_rebase_sets_absolute_units(tmp_path):
    row = _open(tmp_path)
    event = {"event_id": "rebase-1", "new_units": _cell(c1.ESTIMATED_WITH_METHOD, 42.0)}
    r = _unit_change(tmp_path, row["position_id"], event, NOW + timedelta(days=1))
    assert r["units"] == 42.0


def test_unit_change_requires_event_id(tmp_path):
    row = _open(tmp_path)
    event = {"units_delta": _cell(c1.ESTIMATED_WITH_METHOD, 1.0)}
    with pytest.raises(paper.PaperRefusal):
        paper.unit_change(tmp_path, row["position_id"], event, NOW + timedelta(days=1))


def test_unit_change_refuses_without_valued_delta(tmp_path):
    row = _open(tmp_path)
    event = {"event_id": "div-x", "units_delta": _cell(c1.NOT_MEASURED)}
    with pytest.raises(paper.PaperRefusal):
        paper.unit_change(tmp_path, row["position_id"], event, NOW + timedelta(days=1))


def test_unit_change_same_event_id_is_idempotent(tmp_path):
    row = _open(tmp_path)
    event = {"event_id": "div-dup", "units_delta": _cell(c1.ESTIMATED_WITH_METHOD, 1.0)}
    r1 = _unit_change(tmp_path, row["position_id"], event, NOW + timedelta(days=1))
    r2 = _unit_change(tmp_path, row["position_id"], event, NOW + timedelta(days=1))
    assert r1["units"] == r2["units"]


# ── close ────────────────────────────────────────────────────────────────────────────────────

def test_close_holdable_applies_fees_haircut_and_slippage(tmp_path):
    acc = _acc_block(exit_fee_components=[_fee("exit", c1.ESTIMATED_WITH_METHOD, 10.0, unit="bps")],
                     redemption_delay_days=_cell(c1.ESTIMATED_WITH_METHOD, 7.0))
    row = _open(tmp_path, acc=acc)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
          "redemption_delay_haircut_rate": _cell(c1.ESTIMATED_WITH_METHOD, 0.02),
          "slippage": _cell(c1.ESTIMATED_WITH_METHOD, 1.0)}
    closed = _close(tmp_path, row["position_id"], obs, NOW + timedelta(days=10), reason="test exit")
    gross = row["units"] * 1.0
    expected_fee = gross * 10.0 / 10_000.0
    expected_haircut = gross * 0.02 * (7.0 / 365.0)
    assert closed["exit_fees_usd"] == pytest.approx(expected_fee)
    assert closed["redemption_delay_haircut_usd"] == pytest.approx(expected_haircut)
    assert closed["slippage_usd"] == 1.0
    assert closed["status"] == "CLOSED"
    assert closed["realised_return"] is not None
    assert closed["unrealised_return"] is None


def test_close_reference_track_skips_redemption_and_slippage(tmp_path):
    acc = _acc_block(exit_fee_components=[])
    row = _open(tmp_path, acc=acc, paper_mode=ec.PAPER_MODE_REFERENCE_TRACK)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0)}  # no slippage/haircut needed for REFERENCE_TRACK
    closed = _close(tmp_path, row["position_id"], obs, NOW + timedelta(days=5), reason="track NAV only")
    assert closed["exit_fees_usd"] == 0.0
    assert closed["redemption_delay_haircut_usd"] == 0.0
    assert closed["slippage_usd"] == 0.0
    assert closed["exit_value_usd"] == pytest.approx(row["units"] * 1.0)


def test_close_refuses_without_slippage_cell_for_holdable(tmp_path):
    row = _open(tmp_path)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
          "redemption_delay_haircut_rate": _cell(c1.NOT_APPLICABLE, reason="n/a")}
    with pytest.raises(paper.PaperRefusal):
        paper.close(tmp_path, row["position_id"], obs, NOW + timedelta(days=1), reason="test")


def test_close_refuses_without_haircut_rate_when_delay_positive(tmp_path):
    acc = _acc_block(redemption_delay_days=_cell(c1.ESTIMATED_WITH_METHOD, 3.0))
    row = _open(tmp_path, acc=acc)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0), "slippage": _cell(c1.NOT_APPLICABLE, reason="n/a")}
    with pytest.raises(paper.PaperRefusal):
        paper.close(tmp_path, row["position_id"], obs, NOW + timedelta(days=5), reason="test")


def test_close_refuses_without_reason(tmp_path):
    row = _open(tmp_path)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0), "slippage": _cell(c1.NOT_APPLICABLE, reason="n/a"),
          "redemption_delay_haircut_rate": _cell(c1.NOT_APPLICABLE, reason="n/a")}
    with pytest.raises(paper.PaperRefusal):
        paper.close(tmp_path, row["position_id"], obs, NOW + timedelta(days=1), reason="")


def test_close_is_idempotent(tmp_path):
    row = _open(tmp_path)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0), "slippage": _cell(c1.NOT_APPLICABLE, reason="n/a"),
          "redemption_delay_haircut_rate": _cell(c1.NOT_APPLICABLE, reason="n/a")}
    c1_ = _close(tmp_path, row["position_id"], obs, NOW + timedelta(days=1), reason="first")
    c2_ = _close(tmp_path, row["position_id"], obs, NOW + timedelta(days=1), reason="second, different!")
    assert c1_["close_reason"] == c2_["close_reason"] == "first"  # never re-closed with different terms


def test_mutation_check_haircut_sensitive_to_delay_days(tmp_path):
    """Prove the haircut computation actually scales with redemption_delay_days: doubling the
    declared delay doubles the haircut for the same rate and exit value."""
    short = _acc_block(redemption_delay_days=_cell(c1.ESTIMATED_WITH_METHOD, 7.0))
    row_short = _open(tmp_path, acc=short, admission_id="adm-short")
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
          "redemption_delay_haircut_rate": _cell(c1.ESTIMATED_WITH_METHOD, 0.05),
          "slippage": _cell(c1.NOT_APPLICABLE, reason="n/a")}
    closed_short = _close(tmp_path, row_short["position_id"], obs, NOW + timedelta(days=1), reason="x")

    long = _acc_block(redemption_delay_days=_cell(c1.ESTIMATED_WITH_METHOD, 14.0))
    row_long = _open(tmp_path, acc=long, admission_id="adm-long")
    closed_long = _close(tmp_path, row_long["position_id"], obs, NOW + timedelta(days=1), reason="x")
    assert closed_long["redemption_delay_haircut_usd"] == pytest.approx(2 * closed_short["redemption_delay_haircut_usd"])


# ── views ────────────────────────────────────────────────────────────────────────────────────

def test_nav_raises_for_unknown_position(tmp_path):
    with pytest.raises(paper.PaperRefusal):
        paper.nav(tmp_path, "does-not-exist")


def test_positions_lists_every_opened_position(tmp_path):
    row1 = _open(tmp_path, admission_id="adm1")
    row2 = _open(tmp_path, admission_id="adm2")
    ids = {p["position_id"] for p in paper.positions(tmp_path)}
    assert {row1["position_id"], row2["position_id"]} <= ids


def test_positions_reflects_closed_status(tmp_path):
    row = _open(tmp_path)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0), "slippage": _cell(c1.NOT_APPLICABLE, reason="n/a"),
          "redemption_delay_haircut_rate": _cell(c1.NOT_APPLICABLE, reason="n/a")}
    paper.close(tmp_path, row["position_id"], obs, NOW + timedelta(days=1), reason="done")
    found = [p for p in paper.positions(tmp_path) if p["position_id"] == row["position_id"]]
    assert found and found[0]["status"] == "CLOSED"


# ── PAPER_FIELDS vocabulary coverage (every row carries at least the frozen fields) ─────────

@pytest.mark.parametrize("acc_mode", [ec.PAPER_MODE_HOLDABLE, ec.PAPER_MODE_REFERENCE_TRACK])
def test_every_kind_of_row_carries_every_frozen_paper_field(tmp_path, acc_mode):
    acc = _acc_block(exit_fee_components=[] if acc_mode == ec.PAPER_MODE_REFERENCE_TRACK
                     else [_fee("exit", c1.ESTIMATED_WITH_METHOD, 0.0)])
    row = _open(tmp_path, acc=acc, paper_mode=acc_mode, admission_id=f"adm-{acc_mode}")
    assert set(ec.PAPER_FIELDS) <= set(row)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0),
                                                   "mark_origin": "issuer:x"}, NOW + timedelta(days=1))
    assert set(ec.PAPER_FIELDS) <= set(m)
    obs = {"price": _cell(c1.ESTIMATED_WITH_METHOD, 1.0), "slippage": _cell(c1.NOT_APPLICABLE, reason="n/a"),
          "redemption_delay_haircut_rate": _cell(c1.NOT_APPLICABLE, reason="n/a")}
    closed = _close(tmp_path, row["position_id"], obs, NOW + timedelta(days=2), reason="x")
    assert set(ec.PAPER_FIELDS) <= set(closed)


def test_e3_fee_units_are_understood_and_annual_fees_are_never_one_off_charges():
    """Integration finding: paper.py refused E3's honest units. One-off units charge once; an annual fee is
    never charged as one-off (embedded/zero ⇒ 0, otherwise refused); a performance fee is not an entry charge."""
    from spa_core.research_factory import paper as p
    def comp(unit, value, embedded=None):
        cell = {"state": "DOCUMENTED", "value": value, "embedded_in_return": embedded}
        return {"kind": "entry", "unit": unit, "cell": cell}
    f = p._fee_component_usd
    assert f is not None
    assert f(comp("fraction_one_off", 0.0004), 10_000.0, "entry_fee") == pytest.approx(4.0)
    assert f(comp("bps_one_off", 3), 10_000.0, "exit_fee") == pytest.approx(3.0)
    assert f(comp("fraction_apy", 0.0), 10_000.0, "entry_fee") == 0.0
    assert f(comp("fraction_apy", 0.0015, embedded=True), 10_000.0, "entry_fee") == 0.0
    with pytest.raises(p.PaperRefusal):
        f(comp("fraction_apy", 0.0015), 10_000.0, "entry_fee")
    assert f(comp("fraction_of_yield", 0.10), 10_000.0, "entry_fee") == 0.0


# ── H3 (post-implementation review, HIGH): mark() must judge the PRICE CELL'S OWN as_of ──────
# via grades.freshness_verdict — never FRESH just because the cell's state is VALUED. Keyed by
# (position_id, upstream as_of), not by wall clock, so the SAME upstream reading looked at twice
# is one row.

def test_h3_an_old_oracle_reading_is_not_marked_fresh(tmp_path):
    """Reproduces the reviewer's finding exactly: a cell dated 2026-10-02, marked on 2026-11-20
    (48 days later — far past nav_business_day's 96h/3-business-day window), must come back
    STALE with NO price — never FRESH 10000.0."""
    row = _open(tmp_path)
    old_as_of = datetime(2026, 10, 2, tzinfo=timezone.utc)
    check_now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    stale_cell = c1.cell(c1.MEASURED, 1.0, source_ref="https://example/feed", source_class=c1.PRIMARY_PROTOCOL,
                        source_root="chain:1", as_of=old_as_of.isoformat(), now=check_now)
    m = _mark(tmp_path, row["position_id"], {"price": stale_cell, "mark_origin": "issuer:acme"}, check_now)
    assert m["mark_state"] == "STALE"
    assert m["position_value_usd"] is None
    assert m["nav_usd"] is None


def test_h3_a_fresh_oracle_reading_within_the_window_is_still_fresh(tmp_path):
    """Positive control for the SAME code path: a reading within the freshness window (here,
    1 hour old against the 96h/nav_business_day default) must still mark FRESH — the fix judges
    age, it does not simply refuse to ever mark fresh."""
    row = _open(tmp_path)
    as_of = NOW - timedelta(hours=1)
    fresh_cell = c1.cell(c1.MEASURED, 1.1, source_ref="https://example/feed", source_class=c1.PRIMARY_PROTOCOL,
                        source_root="chain:1", as_of=as_of.isoformat(), now=NOW)
    m = _mark(tmp_path, row["position_id"], {"price": fresh_cell, "mark_origin": "issuer:acme"}, NOW)
    assert m["mark_state"] == "FRESH"
    assert m["position_value_usd"] == pytest.approx(row["units"] * 1.1)


def test_h3_same_upstream_reading_marked_twice_is_one_row(tmp_path):
    """The SAME upstream as_of, marked at two different wall-clock run times, must collapse to
    ONE paper_mark row — never one row per run."""
    from spa_core.research_factory._common import ledger_for
    row = _open(tmp_path)
    as_of = NOW - timedelta(hours=1)
    cell_ = c1.cell(c1.MEASURED, 1.1, source_ref="https://example/feed", source_class=c1.PRIMARY_PROTOCOL,
                   source_root="chain:1", as_of=as_of.isoformat(), now=NOW)
    obs = {"price": cell_, "mark_origin": "issuer:acme"}
    _mark(tmp_path, row["position_id"], obs, NOW)
    _mark(tmp_path, row["position_id"], obs, NOW + timedelta(hours=6))  # a later run, same reading
    rows = [e for e in ledger_for(tmp_path).read_all() if e.get("kind") == "paper_mark"]
    assert len(rows) == 1


def test_h3_no_as_of_at_all_keys_by_day_not_by_call(tmp_path):
    """A price cell with NO judgeable as_of at all (e.g. NOT_MEASURED) is keyed by
    (position_id, "stale", today) — two calls on the SAME day collapse to one row; a call the
    NEXT day produces a new one."""
    from spa_core.research_factory._common import ledger_for
    row = _open(tmp_path)
    obs = {"price": c1.cell(c1.NOT_MEASURED, reason="feed down"), "mark_origin": "issuer:acme"}
    _mark(tmp_path, row["position_id"], obs, NOW)
    _mark(tmp_path, row["position_id"], obs, NOW + timedelta(hours=3))  # same day, different instant
    rows_day1 = [e for e in ledger_for(tmp_path).read_all() if e.get("kind") == "paper_mark"]
    assert len(rows_day1) == 1
    _mark(tmp_path, row["position_id"], obs, NOW + timedelta(days=1))  # a new day
    rows_day2 = [e for e in ledger_for(tmp_path).read_all() if e.get("kind") == "paper_mark"]
    assert len(rows_day2) == 2


# ── H4 (post-implementation review, HIGH): a DOCUMENTED/MEASURED "price is net" fact of 1.0 ──
# must skip the performance fee too — not only a NOT_APPLICABLE cell.

def test_h4_documented_price_is_net_fact_skips_performance_fee_usyc_shaped(tmp_path):
    """Reproduces the reviewer's USYC-shaped finding: price_is_net_of_performance_fee is
    DOCUMENTED 1.0 (the issuer's own cited fact: "price is net of fees"), NOT NOT_APPLICABLE.
    A +3% NAV move must give exactly 10300 (no fee skimmed), never 10270."""
    acc = _acc_block(
        price_is_net_of_performance_fee=c1.cell(c1.DOCUMENTED, 1.0, source_ref="https://usyc.hashnote.com/terms",
                                                 source_class=c1.OFFICIAL_API, source_root="issuer:hashnote",
                                                 as_of=NOW.isoformat()),
        performance_fee_rate=c1.cell(c1.ESTIMATED_WITH_METHOD, 0.10, method="USYC cited 10% perf fee"),
    )
    row = _open(tmp_path, acc=acc)
    assert row["units"] == pytest.approx(ec.PAPER_NOTIONAL_USD / 1.0)
    grown_price = 1.03  # +3%
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, grown_price),
                                             "mark_origin": "issuer:hashnote"}, NOW + timedelta(days=1))
    assert m["performance_fee_accrual_usd"] == 0.0
    assert m["nav_usd"] == pytest.approx(10300.0)


def test_h4_not_applicable_price_is_net_still_means_no_performance_fee(tmp_path):
    """Positive control: the OTHER legitimate state (NOT_APPLICABLE — no performance fee exists
    on this product at all) must keep behaving exactly as before the fix."""
    acc = _acc_block(price_is_net_of_performance_fee=c1.cell(c1.NOT_APPLICABLE, reason="no perf fee product"),
                     performance_fee_rate=None)
    row = _open(tmp_path, acc=acc)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 2.0),
                                             "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m["performance_fee_accrual_usd"] == 0.0


def test_h4_mutation_check_price_is_net_requires_value_one_not_just_valued_state(tmp_path):
    """Proves the fix reads the CELL'S VALUE, not merely its state: a VALUED cell whose value is
    0.0 ("price is NOT net") must NOT skip the fee — only value == 1.0 does."""
    acc = _acc_block(
        price_is_net_of_performance_fee=c1.cell(c1.ESTIMATED_WITH_METHOD, 0.0, method="price is gross"),
        performance_fee_rate=c1.cell(c1.ESTIMATED_WITH_METHOD, 0.10, method="10% perf fee"),
    )
    row = _open(tmp_path, acc=acc)
    m = _mark(tmp_path, row["position_id"], {"price": _cell(c1.ESTIMATED_WITH_METHOD, 2.0),
                                             "mark_origin": "issuer:acme"}, NOW + timedelta(days=1))
    assert m["performance_fee_accrual_usd"] > 0.0
