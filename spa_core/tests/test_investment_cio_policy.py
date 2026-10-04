# FROZEN-DATE-OK: injected-clock — NOW is passed into recommend(..., now=NOW)
"""Tests for spa_core.investment_cio.policy (ADR-554 WP-A03, rules 1-10).

sleeves.py does not exist yet (concurrent work-package) — every sleeve here is a hand-built dict
using contract.measured/absent, matching contract.SLEEVE_FIELDS exactly, as the task instructs.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from spa_core.investment_cio import contract
from spa_core.investment_cio.policy import recommend

NOW = datetime(2026, 10, 4, 9, 30, 0, tzinfo=timezone.utc)
AS_OF = "2026-10-03T09:00:00Z"


def mk_sleeve(sleeve_id: str, **overrides) -> dict:
    base = {
        "sleeve_id": sleeve_id,
        "name": sleeve_id,
        "mechanism": "test mechanism",
        "mechanism_class": "unlevered_lending",
        "mode": contract.MODE,
        "allocatable": True,
        "live_admission": True,
        "experiment_id": "exp-1",
        "experiment_start": "2026-01-01",
        "versions_closed": [],
        "capital_basis": contract.measured(100000.0, unit="usd", source="test", as_of=AS_OF),
        "current_equity": contract.measured(101000.0, unit="usd", source="test", as_of=AS_OF),
        "observation_window": contract.measured(102, unit="days", source="test", as_of=AS_OF),
        "valid_periods": contract.measured(102, unit="days", source="test", as_of=AS_OF),
        "maturity": contract.measured(contract.MATURITY_MATURE, unit=None, source="test", as_of=AS_OF),
        "expected_return": contract.measured(0.05, unit="pct_annualized", source="test", as_of=AS_OF, n=102),
        "realized_return": contract.measured(0.05, unit="pct_annualized", source="test", as_of=AS_OF, n=102),
        "volatility": contract.measured(0.01, unit="pct", source="test", as_of=AS_OF),
        "max_drawdown": contract.measured(0.01, unit="pct", source="test", as_of=AS_OF),
        "liquidity": contract.measured("daily", unit=None, source="test", as_of=AS_OF),
        "time_to_exit": contract.measured(1, unit="days", source="test", as_of=AS_OF),
        "cash_share": contract.measured(0.05, unit="pct", source="test", as_of=AS_OF),
        "gross_exposure_over_nav": contract.measured(1.0, unit="x", source="test", as_of=AS_OF),
        "leverage": contract.measured(1.0, unit="x", source="test", as_of=AS_OF),
        "nearest_enforced_stop": contract.measured(0.08, unit="pct", source="test", as_of=AS_OF),
        "loss_budget": contract.measured(0.03, unit="pct", source="test", as_of=AS_OF),
        "stress_loss": contract.measured(0.10, unit="pct", source="test", as_of=AS_OF),
        "worst_case_loss": contract.measured(0.10, unit="pct", source="test", as_of=AS_OF),
        "mtm_coverage": contract.measured(0.0, unit="pct", source="test", as_of=AS_OF),
        "data_freshness": contract.measured("fresh", unit=None, source="test", as_of=AS_OF),
        "evidence_state": contract.measured("HEALTHY", unit=None, source="test", as_of=AS_OF),
        "regime_fit": contract.measured("fit", unit=None, source="test", as_of=AS_OF),
        "confidence": contract.measured("MEDIUM", unit=None, source="test", as_of=AS_OF),
        "capacity": contract.measured(1_000_000.0, unit="usd", source="test", as_of=AS_OF),
        "risk": {},
        "composition": {},
        "factors": {},
        "correlation_features": {},
        "gates": [{"gate": "data_health", "state": "PASS", "reason": "ok"}],
        "warnings": [],
        "unknowns": [],
    }
    base.update(overrides)
    missing = [f for f in contract.SLEEVE_FIELDS if f not in base]
    assert not missing, f"test sleeve missing contract.SLEEVE_FIELDS: {missing}"
    return base


def mk_cash(**overrides) -> dict:
    return mk_sleeve("cash", mechanism_class="cash", maturity=contract.measured(
        contract.MATURITY_MATURE, unit=None, source="test", as_of=AS_OF), worst_case_loss=contract.measured(
        0.0, unit="pct", source="test", as_of=AS_OF), **overrides)


def mk_doc(sleeves: dict, *, seed_split=None, inputs=None, hurdle=None, real_capital_usd=None) -> dict:
    return {
        "schema": contract.SCHEMA_SLEEVES,
        "generated_at": AS_OF,
        "sleeves": sleeves,
        "inputs": inputs if inputs is not None else [
            {"name": "defi_engine_status", "path": "data/defi_engine/status.json", "as_of": AS_OF,
             "age_hours": 1.0, "digest": "deadbeef", "state": "FRESH"},
        ],
        "exposure": {},
        "correlation": {},
        "seed_split_weights": seed_split if seed_split is not None else {},
        **({"hurdle": hurdle} if hurdle is not None else {}),
        **({"real_capital_usd": real_capital_usd} if real_capital_usd is not None else {}),
    }


def test_rec_fields_complete():
    doc = mk_doc({"cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    missing = [f for f in contract.REC_FIELDS if f not in rec]
    assert not missing


def test_determinism_same_input_byte_identical():
    doc = mk_doc({
        "defi_conservative": mk_sleeve("defi_conservative"),
        "defi_balanced": mk_sleeve("defi_balanced", maturity=contract.measured(
            contract.MATURITY_DEVELOPING, unit=None, source="test", as_of=AS_OF), valid_periods=contract.measured(
            45, unit="days", source="test", as_of=AS_OF), worst_case_loss=contract.measured(
            0.15, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    })
    rec1 = recommend(copy.deepcopy(doc), None, NOW)
    rec2 = recommend(copy.deepcopy(doc), None, NOW)
    j1 = json.dumps(rec1, sort_keys=True, default=str)
    j2 = json.dumps(rec2, sort_keys=True, default=str)
    assert j1 == j2
    assert rec1["recommendation_id"] == rec2["recommendation_id"]


def test_missing_worst_case_loss_never_becomes_zero():
    doc = mk_doc({
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.absent(
            contract.NOT_MEASURED, reason="stop sensor offline")),
        "defi_balanced": mk_sleeve("defi_balanced"),
        "cash": mk_cash(),
    })
    rec = recommend(doc, None, NOW)
    assert "defi_conservative" not in rec["recommended_weights"]
    assert "defi_conservative" in rec["abstentions"]
    assert "worst_case_loss" in rec["abstentions"]["defi_conservative"]


def test_stale_gate_makes_sleeve_ineligible():
    doc = mk_doc({
        "defi_conservative": mk_sleeve("defi_conservative", gates=[
            {"gate": "data_freshness", "state": "FAIL", "reason": "STALE 40h"}]),
        "defi_balanced": mk_sleeve("defi_balanced"),
        "cash": mk_cash(),
    })
    rec = recommend(doc, None, NOW)
    assert "defi_conservative" not in rec["recommended_weights"]
    assert "STALE" in rec["abstentions"]["defi_conservative"]


def test_unknown_can_never_produce_high_confidence():
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative"),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            0.2, unit="pct", source="test", as_of=AS_OF)),
        "defi_aggressive": mk_sleeve("defi_aggressive", worst_case_loss=contract.measured(
            0.3, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves), None, NOW)
    assert rec["confidence"] in ("LOW", "MEDIUM")
    assert rec["confidence"] != "HIGH"
    assert contract.POLICY["high_confidence_reachable"] is False


def test_todays_like_scene_insufficient_evidence():
    """conservative MATURE 102 periods; balanced/aggressive IMMATURE 2 periods."""
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative"),
        "defi_balanced": mk_sleeve("defi_balanced", maturity=contract.measured(
            contract.MATURITY_IMMATURE, unit=None, source="test", as_of=AS_OF),
            valid_periods=contract.measured(2, unit="days", source="test", as_of=AS_OF)),
        "defi_aggressive": mk_sleeve("defi_aggressive", maturity=contract.measured(
            contract.MATURITY_IMMATURE, unit=None, source="test", as_of=AS_OF),
            valid_periods=contract.measured(2, unit="days", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves), None, NOW)
    assert rec["stance"] == contract.STANCE_INSUFFICIENT
    assert rec["recommended_weights"] == {}
    evidence_only = rec["alternatives_considered"]["EVIDENCE_ONLY"]["weights"]
    assert evidence_only.get("defi_conservative", 0.0) <= contract.POLICY["cap_mature"] + 1e-9
    assert evidence_only.get("defi_conservative", 0.0) > 0
    assert evidence_only.get("cash", 0.0) >= contract.POLICY["cash_floor"] - 1e-9
    assert "2/30" in rec["abstentions"]["defi_balanced"] or "IMMATURE" in rec["abstentions"]["defi_balanced"]


def test_two_mature_scene_recommend_weights_inverse_to_loss_capped():
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.measured(
            0.05, unit="pct", source="test", as_of=AS_OF)),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            0.25, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves), None, NOW)
    assert rec["stance"] == contract.STANCE_RECOMMEND
    w = rec["recommended_weights"]
    assert w["defi_conservative"] > w["defi_balanced"]  # lower loss -> higher weight
    assert w["defi_conservative"] <= contract.POLICY["cap_mature"] + 1e-9
    assert w["defi_balanced"] <= contract.POLICY["cap_mature"] + 1e-9
    assert w.get("cash", 0.0) >= contract.POLICY["cash_floor"] - 1e-9
    assert pytest.approx(sum(w.values()), abs=1e-9) == 1.0


def test_hysteresis_hold_below_threshold():
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.measured(
            0.05, unit="pct", source="test", as_of=AS_OF)),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            0.06, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec1 = recommend(mk_doc(sleeves), None, NOW)
    assert rec1["stance"] == contract.STANCE_RECOMMEND
    # tiny nudge, well under the 5pp hysteresis threshold
    sleeves2 = copy.deepcopy(sleeves)
    sleeves2["defi_balanced"]["worst_case_loss"] = contract.measured(
        0.0601, unit="pct", source="test", as_of=AS_OF)
    rec2 = recommend(mk_doc(sleeves2), rec1, NOW)
    assert rec2["stance"] == contract.STANCE_HOLD
    assert rec2["recommended_weights"] == rec1["recommended_weights"]


def test_return_gate_fails_mature_sleeve_below_hurdle():
    hurdle = contract.measured(0.08, unit="pct_annualized", source="test", as_of=AS_OF)
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", realized_return=contract.measured(
            0.03, unit="pct_annualized", source="test", as_of=AS_OF, n=102)),
        "defi_balanced": mk_sleeve("defi_balanced"),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves, hurdle=hurdle), None, NOW)
    assert "defi_conservative" not in rec["recommended_weights"]
    assert "hurdle" in rec["abstentions"]["defi_conservative"].lower() or \
        "return gate" in rec["abstentions"]["defi_conservative"].lower()


def test_return_gate_skipped_when_hurdle_unreadable():
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", realized_return=contract.measured(
            0.001, unit="pct_annualized", source="test", as_of=AS_OF, n=102)),
        "defi_balanced": mk_sleeve("defi_balanced"),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves), None, NOW)  # no hurdle key at all
    assert "defi_conservative" in rec["recommended_weights"]
    assert any("SKIPPED" in u or "hurdle" in u for u in rec["unknowns"])


def test_cash_floor_with_unknown_look_through():
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", cash_share=contract.absent(
            contract.NOT_MEASURED, reason="book does not report idle cash")),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            0.3, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves), None, NOW)
    assert rec["recommended_weights"].get("cash", 0.0) >= contract.POLICY["cash_floor"] - 1e-9
    assert any("look-through" in u or "UNDEFINED" in u for u in rec["unknowns"])


def test_rounding_sums_to_100():
    for n_eligible, extra in ((0, {}), (1, {"defi_balanced": mk_sleeve(
            "defi_balanced", maturity=contract.measured(contract.MATURITY_IMMATURE, unit=None,
                                                        source="test", as_of=AS_OF))}),
                              (2, {"defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
                                  0.17, unit="pct", source="test", as_of=AS_OF))})):
        sleeves = {"defi_conservative": mk_sleeve("defi_conservative"), "cash": mk_cash(), **extra}
        if n_eligible == 0:
            sleeves["defi_conservative"] = mk_sleeve("defi_conservative", worst_case_loss=contract.absent(
                contract.NOT_MEASURED, reason="offline"))
        rec = recommend(mk_doc(sleeves), None, NOW)
        total = sum(rec["recommended_weights"].values())
        if rec["recommended_weights"]:
            assert pytest.approx(total, abs=1e-9) == 1.0, (n_eligible, rec["recommended_weights"])


def test_observe_only_sleeve_never_eligible():
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative"),
        "defi_balanced": mk_sleeve("defi_balanced"),
        "trading_research": mk_sleeve("trading_research", allocatable=False,
                                      mechanism_class="directional_trading"),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves), None, NOW)
    assert "trading_research" not in rec["recommended_weights"]
    assert "observe-only" in rec["abstentions"]["trading_research"]


def test_no_recommendation_when_zero_eligible():
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", maturity=contract.measured(
            contract.MATURITY_IMMATURE, unit=None, source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec = recommend(mk_doc(sleeves), None, NOW)
    assert rec["stance"] == contract.STANCE_NONE
    assert rec["recommended_weights"] == {}


def test_real_capital_usd_passthrough_not_hardcoded():
    doc = mk_doc({"cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    assert rec["real_capital_usd"] is None
    doc2 = mk_doc({"cash": mk_cash()}, real_capital_usd=0)
    rec2 = recommend(doc2, None, NOW)
    assert rec2["real_capital_usd"] == 0


def test_explanation_facts_eight_and_named_states():
    doc = mk_doc({"defi_conservative": mk_sleeve("defi_conservative"),
                  "defi_balanced": mk_sleeve("defi_balanced"), "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    facts = rec["explanation_facts"]
    assert len(facts) == 8
    for f in facts:
        assert f["state"] in ("SPOKEN", "UNKNOWN")
        assert f["fact"] and f["text"]


def test_factor_ids_from_the_read_model_reach_major_risks_on_the_seed_split():
    """Integration defect found on live data: the read model publishes factor ids as a LIST; the policy only
    read a dict and returned no major risks at all — a shared failure mode across all books went unreported."""
    a = mk_sleeve("defi_conservative")                          # MATURE by default
    b = mk_sleeve("defi_balanced", maturity=contract.measured(contract.MATURITY_IMMATURE, unit=None,
                                                              source="test", as_of=AS_OF))
    a["factors"] = ["maple_credit", "fluid", "usdc_peg"]
    b["factors"] = ["maple_credit", "usde_peg"]
    doc = mk_doc({"defi_conservative": a, "defi_balanced": b, "cash": mk_cash()},
                 seed_split={"defi_conservative": 0.5, "defi_balanced": 0.5})
    r = recommend(doc, None, NOW)
    assert r["stance"] == contract.STANCE_INSUFFICIENT and r["recommended_weights"] == {}
    assert r["major_risks"]["basis"] == "seed_split"  # no recommendation -> the basis is NAMED (finding #14)
    maple = r["major_risks"]["factors"]["maple_credit"]
    assert set(maple["contributors"]) == {"defi_conservative", "defi_balanced"}
    assert maple["sleeve_weight_touching"] == 1.0


def test_loss_budget_check_does_not_claim_ok_without_weights():
    r = recommend(mk_doc({"defi_conservative": mk_sleeve("defi_conservative"), "cash": mk_cash()}), None, NOW)
    assert r["stance"] == contract.STANCE_INSUFFICIENT
    lb = [c for c in r["binding_constraints"] if c["constraint"] == "portfolio_loss_budget"][0]
    assert lb["state"] == "NOT_APPLICABLE"


# ── finding #4: hysteresis HOLD must never copy a now-ineligible sleeve's weight ───────────────

def test_hysteresis_hold_never_copies_a_now_ineligible_sleeves_weight():
    """A small |delta| alone is not sufficient for HOLD: if the eligible SET changed, or a sleeve
    the previous recommendation actually weighted is now an abstention, the stance must be
    RECOMMEND, never a HOLD that quietly keeps recommending a now-ineligible sleeve."""
    scene1 = {
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.measured(
            0.05, unit="pct", source="test", as_of=AS_OF)),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            3.0, unit="pct", source="test", as_of=AS_OF)),
        "defi_aggressive": mk_sleeve("defi_aggressive", maturity=contract.measured(
            contract.MATURITY_IMMATURE, unit=None, source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec1 = recommend(mk_doc(scene1), None, NOW)
    assert rec1["stance"] == contract.STANCE_RECOMMEND
    assert rec1["recommended_weights"].get("defi_balanced", 0.0) > 0.0

    scene2 = {
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.measured(
            0.05, unit="pct", source="test", as_of=AS_OF)),
        "defi_balanced": mk_sleeve("defi_balanced", gates=[
            {"gate": "data_freshness", "state": "FAIL", "reason": "STALE 40h"}]),
        "defi_aggressive": mk_sleeve("defi_aggressive", worst_case_loss=contract.measured(
            3.0, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec2 = recommend(mk_doc(scene2), rec1, NOW)
    assert rec2["stance"] == contract.STANCE_RECOMMEND, \
        "a previously-weighted sleeve is now gated — HOLD must never fire here"
    assert rec2["recommended_weights"].get("defi_balanced", 0.0) == 0.0
    assert "defi_balanced" in rec2["abstentions"]
    assert rec2["recommended_weights"].get("defi_aggressive", 0.0) > 0.0


def test_hysteresis_hold_still_fires_when_eligible_set_is_truly_unchanged():
    """Sanity control for the fix above: HOLD must still work in the ordinary case."""
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.measured(
            0.05, unit="pct", source="test", as_of=AS_OF)),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            0.06, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec1 = recommend(mk_doc(sleeves), None, NOW)
    assert rec1["stance"] == contract.STANCE_RECOMMEND
    sleeves2 = copy.deepcopy(sleeves)
    sleeves2["defi_balanced"]["worst_case_loss"] = contract.measured(0.0601, unit="pct", source="test", as_of=AS_OF)
    rec2 = recommend(mk_doc(sleeves2), rec1, NOW)
    assert rec2["stance"] == contract.STANCE_HOLD
    assert rec2["recommended_weights"] == rec1["recommended_weights"]


# ── finding #8: protocol cap check must not claim MEASURED while partly unchecked ──────────────

def test_protocol_cap_check_reports_partial_when_a_protocol_share_is_unchecked():
    a = mk_sleeve("defi_conservative", worst_case_loss=contract.measured(0.05, unit="pct", source="test", as_of=AS_OF))
    a["composition"] = [{"protocol": "shared_proto", "tier": "T1",
                         "share": contract.measured(0.5, unit="share", source="test", as_of=AS_OF)}]
    b = mk_sleeve("defi_balanced", worst_case_loss=contract.measured(0.2, unit="pct", source="test", as_of=AS_OF))
    b["composition"] = [{"protocol": "shared_proto", "tier": "T1",
                         "share": contract.absent(contract.NOT_MEASURED, reason="no per-protocol split")}]
    doc = mk_doc({"defi_conservative": a, "defi_balanced": b, "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    assert rec["stance"] == contract.STANCE_RECOMMEND
    check = rec["diversification_summary"]["protocol_cap_check"]
    assert check["state"] == "PARTIAL"
    assert any(u.get("protocol") == "shared_proto" for u in check["unchecked_protocols"])
    assert check["breaches"] == []  # absent weight counted as 0 — never silently claims a breach either


def test_protocol_cap_check_reports_measured_when_every_holder_share_is_known():
    a = mk_sleeve("defi_conservative", worst_case_loss=contract.measured(0.05, unit="pct", source="test", as_of=AS_OF))
    a["composition"] = [{"protocol": "solo_proto_a", "tier": "T2",
                         "share": contract.measured(0.3, unit="share", source="test", as_of=AS_OF)}]
    b = mk_sleeve("defi_balanced", worst_case_loss=contract.measured(0.2, unit="pct", source="test", as_of=AS_OF))
    b["composition"] = [{"protocol": "solo_proto_b", "tier": "T2",
                         "share": contract.measured(0.3, unit="share", source="test", as_of=AS_OF)}]
    doc = mk_doc({"defi_conservative": a, "defi_balanced": b, "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    assert rec["stance"] == contract.STANCE_RECOMMEND
    check = rec["diversification_summary"]["protocol_cap_check"]
    assert check["state"] == "MEASURED"
    assert "unchecked_protocols" not in check
    assert check["breaches"] == []


# ── finding #13: UNKNOWN must dominate a combined risk level, never rank below LOW ──────────────

def test_portfolio_risk_summary_unknown_dominates_but_names_max_known():
    a = mk_sleeve("defi_conservative")
    a["risk"] = {"MARKET": {"level": "LOW", "evidence": "x", "source": "test"}}
    b = mk_sleeve("defi_balanced", worst_case_loss=contract.measured(0.2, unit="pct", source="test", as_of=AS_OF))
    b["risk"] = {"MARKET": {"level": "UNKNOWN", "evidence": "y", "source": "test"}}
    doc = mk_doc({"defi_conservative": a, "defi_balanced": b, "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    market = rec["portfolio_risk_summary"]["MARKET"]
    assert market["level"] == "UNKNOWN"
    assert market["any_unknown"] is True
    assert market["max_known"] == "LOW"


def test_major_risks_level_unknown_dominates_even_with_many_contributors():
    a = mk_sleeve("defi_conservative")
    a["factors"] = {"fluid": {"level": "HIGH"}}
    b = mk_sleeve("defi_balanced", worst_case_loss=contract.measured(0.2, unit="pct", source="test", as_of=AS_OF))
    b["factors"] = {"fluid": {"level": "UNKNOWN"}}
    doc = mk_doc({"defi_conservative": a, "defi_balanced": b, "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    fluid = rec["major_risks"]["factors"]["fluid"]
    assert fluid["level"] == "UNKNOWN"
    assert fluid["max_known"] == "HIGH"
    assert fluid["any_unknown"] is True


# ── finding #14: major_risks basis must be named, never silently the seed split ─────────────────

def test_major_risks_basis_is_recommended_when_there_is_a_recommendation_else_seed_split():
    doc = mk_doc({"defi_conservative": mk_sleeve("defi_conservative"),
                  "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
                      0.2, unit="pct", source="test", as_of=AS_OF)),
                  "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    assert rec["stance"] == contract.STANCE_RECOMMEND
    assert rec["major_risks"]["basis"] == "recommended"
    assert "factors" in rec["major_risks"]

    doc2 = mk_doc({"defi_conservative": mk_sleeve("defi_conservative", maturity=contract.measured(
                      contract.MATURITY_IMMATURE, unit=None, source="test", as_of=AS_OF)),
                  "cash": mk_cash()}, seed_split={"defi_conservative": 1.0})
    rec2 = recommend(doc2, None, NOW)
    assert rec2["stance"] == contract.STANCE_NONE
    assert rec2["major_risks"]["basis"] == "seed_split"


# ── finding #19: portfolio_expected_return is labelled realised, never a forecast; evidence_cutoff
#    names incomplete inputs instead of silently absorbing a stale/unmeasured one into the min() ──

def test_portfolio_expected_return_is_labelled_realised_trailing_not_a_forecast():
    doc = mk_doc({"defi_conservative": mk_sleeve("defi_conservative"),
                  "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
                      0.2, unit="pct", source="test", as_of=AS_OF)),
                  "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    per = rec["portfolio_expected_return"]
    assert per.get("kind") == "realised_trailing"
    assert "not a forecast" in (per.get("note") or "")


def test_evidence_cutoff_marks_incomplete_when_an_input_is_stale_or_unmeasured():
    doc = mk_doc({"defi_conservative": mk_sleeve("defi_conservative"), "cash": mk_cash()},
                 inputs=[
                     {"name": "defi_engine_status", "path": "x", "as_of": AS_OF, "age_hours": 1.0,
                      "digest": "d1", "state": contract.MEASURED},
                     {"name": "chief_posture", "path": "y", "as_of": AS_OF, "age_hours": 50.0,
                      "digest": "d2", "state": contract.STALE},
                 ])
    rec = recommend(doc, None, NOW)
    assert rec["evidence_cutoff_complete"] is False
    assert "chief_posture" in rec["evidence_cutoff_incomplete_inputs"]
    assert any("evidence_cutoff" in u for u in rec["unknowns"])


def test_evidence_cutoff_complete_when_every_input_is_measured():
    doc = mk_doc({"defi_conservative": mk_sleeve("defi_conservative"), "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    assert rec["evidence_cutoff_complete"] is True
    assert rec["evidence_cutoff_incomplete_inputs"] == []


# ── finding N1: HOLD must never freeze a previous weight that now breaches a TIGHTENED cap ──────

def test_hold_refuses_when_a_previous_weight_now_exceeds_its_current_cap():
    """cons .05 loss, balanced .2 loss -> balanced lands at 0.20 with the default 50% cap. A
    tightened mechanism cap of 16% on balanced the next day keeps the eligible SET unchanged and
    the raw |delta| small (0.20 -> 0.16 is 4pp, under the 5pp hysteresis) — exactly the scene a
    small-delta-only HOLD check would freeze at the STALE 0.20, breaching the new 16% cap."""
    sleeves1 = {
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.measured(
            0.05, unit="pct", source="test", as_of=AS_OF)),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            0.2, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    rec1 = recommend(mk_doc(sleeves1), None, NOW)
    assert rec1["stance"] == contract.STANCE_RECOMMEND
    assert rec1["recommended_weights"]["defi_balanced"] == pytest.approx(0.20, abs=1e-9)

    sleeves2 = copy.deepcopy(sleeves1)
    sleeves2["defi_balanced"]["risk"] = {"mechanism_cap_pct": 0.16}  # tightened via its own ADR
    rec2 = recommend(mk_doc(sleeves2), rec1, NOW)
    assert rec2["stance"] == contract.STANCE_RECOMMEND, \
        "a previous weight breaching the NEW cap must never be frozen by HOLD"
    assert rec2["recommended_weights"]["defi_balanced"] <= 0.16 + 1e-9
    breach = [c for c in rec2["binding_constraints"] if c["constraint"] == "defi_balanced_cap"]
    assert breach and breach[0]["state"] == "BINDING"


def test_hold_refuses_when_previous_explicit_cash_is_below_the_current_floor():
    """Sanity control for the OTHER half of N1 (cash floor): hand-build a `previous` recommendation
    whose explicit cash is already below today's floor, with everything else set up so the
    eligible-set/abstention/cap checks alone would allow a HOLD — only the cash-floor check stops it."""
    sleeves = {
        "defi_conservative": mk_sleeve("defi_conservative", worst_case_loss=contract.measured(
            0.05, unit="pct", source="test", as_of=AS_OF)),
        "defi_balanced": mk_sleeve("defi_balanced", worst_case_loss=contract.measured(
            0.06, unit="pct", source="test", as_of=AS_OF)),
        "cash": mk_cash(),
    }
    doc = mk_doc(sleeves)
    real_rec = recommend(doc, None, NOW)
    assert real_rec["stance"] == contract.STANCE_RECOMMEND
    bad_previous = dict(real_rec)
    bad_previous["recommended_weights"] = dict(real_rec["recommended_weights"])
    # below today's 5% floor, but close enough that the |delta| alone (0.02) is still under the
    # 5pp hysteresis threshold — isolating the cash-floor check from the delta check
    bad_previous["recommended_weights"]["cash"] = 0.03
    rec2 = recommend(doc, bad_previous, NOW)
    assert rec2["stance"] == contract.STANCE_RECOMMEND, \
        "a previous explicit cash below the current floor must never be frozen by HOLD"
    assert rec2["recommended_weights"]["cash"] >= contract.POLICY["cash_floor"] - 1e-9


# ── finding N6: real_capital_usd outside the paper boundary is refused to None ───────────────────

def test_real_capital_usd_outside_paper_boundary_is_refused_to_none():
    doc = mk_doc({"cash": mk_cash()}, real_capital_usd=5000)
    rec = recommend(doc, None, NOW)
    assert rec["real_capital_usd"] is None
    assert any("real capital" in u.lower() for u in rec["unknowns"])


def test_real_capital_usd_true_bool_is_refused_too():
    doc = mk_doc({"cash": mk_cash()}, real_capital_usd=True)
    rec = recommend(doc, None, NOW)
    assert rec["real_capital_usd"] is None
    assert any("real capital" in u.lower() for u in rec["unknowns"])


# ── finding N7: a weighted contributor missing a risk axis counts as UNKNOWN, never dropped ─────

def test_portfolio_risk_summary_missing_axis_counts_as_unknown_not_dropped():
    a = mk_sleeve("defi_conservative")
    a["risk"] = {}  # COUNTERPARTY (and every other axis) simply not assessed
    b = mk_sleeve("defi_balanced", worst_case_loss=contract.measured(0.2, unit="pct", source="test", as_of=AS_OF))
    b["risk"] = {"COUNTERPARTY": {"level": "LOW", "evidence": "x", "source": "test"}}
    doc = mk_doc({"defi_conservative": a, "defi_balanced": b, "cash": mk_cash()})
    rec = recommend(doc, None, NOW)
    counterparty = rec["portfolio_risk_summary"]["COUNTERPARTY"]
    assert counterparty["level"] == "UNKNOWN"
    assert counterparty["any_unknown"] is True
    assert counterparty["max_known"] == "LOW"


def test_rounding_never_lifts_a_weight_above_its_cap():
    """Final-check N1 residual: a 16.5 % cap rounded to whole points must give 16 %, not 17 %."""
    from spa_core.investment_cio.policy import _round_pp
    out = _round_pp({"a": 0.165, "b": 0.165, "cash": 0.67}, 1.0, ceilings={"a": 0.165, "b": 0.165})
    assert out["a"] <= 0.165 and out["b"] <= 0.165
    assert abs(sum(out.values()) - 1.0) < 1e-9
