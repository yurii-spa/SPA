"""
spa_core/tests/test_rates_desk_integration.py — the rates-desk WIRING (§7 integration) tests.

Covers the five integration pieces built on top of the engine + gate + 4 sleeves + feeds:
  1. backtest_rates  — replay is DETERMINISTIC + produces per-sleeve metrics (net_apy/maxDD/deflated
                        Sharpe/beats_floor/kills/refusals); BasisHedge is honestly BLOCKED-NO-HEDGE.
  2. promotion_rates — maps the backtest into the lab promotion rubric → a stage per sleeve; FixedCarry
                        reaches PAPER_CANDIDATE, BasisHedge is BLOCKED-NO-HEDGE.
  3. proof_chain     — appends BOTH entries AND refusals to the hash_chain, verifies, deterministic.
  4. paper_rates     — registers FixedCarry into a live-style paper service; restart-survival + per-day
                        idempotency (no double-accrue).
  5. surface_io      — round-trips a cached surface + scans it (the shape the API serves).

Hermetic + fast: a tiny SYNTHETIC deep dataset (one stable-synth carry market + one toxic LRT market)
drives the backtest, so the tests do not depend on the multi-MB live cache. stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from decimal import Decimal as D

import pytest

from spa_core.audit import hash_chain
from spa_core.strategy_lab.rates_desk import (
    backtest_rates,
    promotion_rates,
    proof_chain,
    surface_io,
)
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.feeds import BorosFeed
from spa_core.strategy_lab.rates_desk.sleeves import FixedCarrySleeve

try:
    from spa_core.strategy_lab.rates_desk import pendle_pt_history as _pph
    _pph.load()
    _DEEP_AVAILABLE = True
except Exception:  # noqa: BLE001 — deep cache may be absent in a fresh clone / hermetic CI
    _DEEP_AVAILABLE = False


# ── a tiny synthetic deep dataset (carry market + toxic LRT market) ───────────────────────────────
def _series(start_day: int, n: int, implied: float, underlying: float):
    import datetime
    base = datetime.date(2024, 6, 1)
    return [
        {"date": (base + datetime.timedelta(days=start_day + i)).isoformat(),
         "implied_yield": implied, "underlying_yield": underlying, "pt_price": None}
        for i in range(n)
    ]


@pytest.fixture
def deep_dataset():
    """Synthetic deep dataset: one harvestable sUSDe carry market (implied >> fair) maturing well past
    the window, and one toxic ezETH LRT market (the gate must refuse it). 220 days of history."""
    return {
        "generated_at": "2024-06-01T00:00:00+00:00",
        "method": "synthetic_test",
        "underlyings": ["sUSDe", "ezETH"],
        "window": {"start": "2024-06-01", "end": "2025-01-07"},
        "markets": {
            "PT-sUSDE-TEST": {
                "underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-TEST",
                "market_address": "0xcarry", "pt_address": "0xpt", "maturity": "2026-01-01",
                "method": "synthetic", "series": _series(0, 220, 0.12, 0.09),
            },
            "PT-ezETH-TEST": {
                "underlying": "ezETH", "kind": "lrt", "symbol": "PT-ezETH-TEST",
                "market_address": "0xtoxic", "pt_address": "0xptx", "maturity": "2026-01-01",
                "method": "synthetic", "series": _series(0, 220, 0.35, 0.03),
            },
        },
    }


@pytest.fixture
def funding():
    """Benign funding (no negative streak) so the funding-flip kill is not the dominant signal."""
    import datetime
    base = datetime.date(2024, 6, 1)
    return {(base + datetime.timedelta(days=i)).isoformat(): 0.0001 for i in range(260)}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1) backtest replay
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_backtest_replay_deterministic(deep_dataset, funding):
    r1 = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    r2 = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    r1["sleeves"]  # touch
    a = json.dumps(r1["sleeves"], sort_keys=True)
    b = json.dumps(r2["sleeves"], sort_keys=True)
    assert a == b, "backtest replay is not deterministic"


def test_backtest_replay_per_sleeve_metrics(deep_dataset, funding):
    r = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    sleeves = r["sleeves"]
    assert set(sleeves) == {"fixed_carry", "levered_carry", "basis_hedge", "rate_matrix"}
    for kind, blk in sleeves.items():
        for field in ("net_apy_pct", "max_drawdown_pct", "deflated_sharpe",
                      "beats_floor", "kills", "refusals_count", "approvals_count", "carry_days"):
            assert field in blk, f"{kind} missing {field}"
    # the gate REFUSED the toxic LRT book (the refusal edge), and OPENED the harvestable carry leg
    assert sleeves["fixed_carry"]["refusals_count"] > 0
    assert sleeves["fixed_carry"]["approvals_count"] > 0
    assert sleeves["fixed_carry"]["carry_days"] > 0


@pytest.mark.skipif(not _DEEP_AVAILABLE, reason="deep pendle_pt_history cache not present")
def test_backtest_real_deep_carry_beats_floor():
    """On the REAL cached deep dataset the harvestable carry sleeve must beat the ~3.4% floor (the
    validated GO result) — the thin synthetic fixture is exit-cap-bound so it under-states this."""
    r = backtest_rates.run(write=False)
    assert r["sleeves"]["fixed_carry"]["beats_floor"] is True
    assert r["sleeves"]["fixed_carry"]["deflated_sharpe_passes_0_95"] is True


def test_backtest_basis_hedge_blocked_no_hedge(deep_dataset, funding):
    r = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    bh = r["sleeves"]["basis_hedge"]
    assert bh.get("blocked_no_hedge") is True
    assert bh["beats_floor"] is False
    assert bh["refusals_count"] == 0 and bh["approvals_count"] == 0
    # honest: the Boros hedge is unavailable for every underlying
    assert r["hedge_available_any"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2) promotion mapping
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_promotion_mapping_assigns_stages(deep_dataset, funding):
    bt = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    report = promotion_rates.build_report(write=False, backtest=bt)
    stages = {s["id"]: s["stage"] for s in report["sleeves"]}
    assert report["n_sleeves"] == 4
    # every sleeve is assigned a valid stage + carries a reason string
    valid = {"REJECT", "BACKTEST_PASS", "PAPER_CANDIDATE", promotion_rates.STAGE_BLOCKED_NO_HEDGE}
    for s in report["sleeves"]:
        assert s["stage"] in valid, s["stage"]
        assert isinstance(s.get("reason"), str) and s["reason"]
    # BasisHedge is honestly blocked (cannot be promoted on no hedge venue)
    assert stages["rates_desk_basis_hedge"] == promotion_rates.STAGE_BLOCKED_NO_HEDGE


@pytest.mark.skipif(not _DEEP_AVAILABLE, reason="deep pendle_pt_history cache not present")
def test_promotion_real_deep_fixed_carry_reaches_paper_candidate():
    """On the REAL deep dataset the validated FixedCarry sleeve reaches PAPER_CANDIDATE (the GO
    result), BasisHedge stays BLOCKED-NO-HEDGE."""
    bt = backtest_rates.run(write=False)
    report = promotion_rates.build_report(write=False, backtest=bt)
    stages = {s["id"]: s["stage"] for s in report["sleeves"]}
    assert stages["rates_desk_fixed_carry"] == "PAPER_CANDIDATE"
    assert stages["rates_desk_basis_hedge"] == promotion_rates.STAGE_BLOCKED_NO_HEDGE


def test_promotion_mapping_deterministic(deep_dataset, funding):
    bt = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    r1 = promotion_rates.build_report(write=False, backtest=bt)
    r2 = promotion_rates.build_report(write=False, backtest=bt)
    assert json.dumps(r1["sleeves"], sort_keys=True) == json.dumps(r2["sleeves"], sort_keys=True)


def test_promotion_missing_backtest_fail_closed():
    report = promotion_rates.build_report(write=False, backtest={})
    assert report["n_sleeves"] == 0
    assert report["sleeves"] == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3) proof chain
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _toxic_and_carry_verdicts():
    """A scan over one carry + one toxic quote → one ENTRY + one REFUSAL (deterministic)."""
    carry_q = RateQuote(
        underlying="susde", kind=UnderlyingKind.STABLE_SYNTH, venue=RateVenue.PENDLE_PT,
        protocol="pendle", market_id="PT-susde", tenor_seconds=86400 * 90, as_of="2026-01-01",
        quoted_rate=D("0.12"), tvl_usd=D("5e7"), exit_liquidity_usd=D("2e6"), hedge_available=True)
    toxic_q = RateQuote(
        underlying="ezeth", kind=UnderlyingKind.LRT, venue=RateVenue.PENDLE_PT,
        protocol="pendle", market_id="PT-ezeth", tenor_seconds=86400 * 90, as_of="2026-01-01",
        quoted_rate=D("0.35"), tvl_usd=D("5e7"), exit_liquidity_usd=D("2e6"), hedge_available=False)
    carry_risk = UnderlyingRisk(
        underlying="susde", as_of="2026-01-01", nav_redemption_value=D("1"), market_price=D("1"),
        peg_distance=D0, peg_vol_30d=D0, redemption_sla_seconds=86400, reserve_fund_ratio=D("0.05"),
        funding_neg_frac_90d=D("0.1"), oracle_kind="chainlink", oracle_staleness_seconds=300,
        nested_protocol_count=1, top_borrower_share=D("0.1"))
    toxic_risk = UnderlyingRisk(
        underlying="ezeth", as_of="2026-01-01", nav_redemption_value=D("1"), market_price=D("0.994"),
        peg_distance=D("0.006"), peg_vol_30d=D("0.02"), redemption_sla_seconds=86400 * 7,
        reserve_fund_ratio=D0, funding_neg_frac_90d=D("0.30"), oracle_kind="redstone",
        oracle_staleness_seconds=600, nested_protocol_count=4, top_borrower_share=D("0.45"))
    sleeve = FixedCarrySleeve()
    sleeve.init(100000, {})
    return sleeve.scan_and_enter([carry_q, toxic_q],
                                 {"susde": carry_risk, "ezeth": toxic_risk}, "2026-01-01")


def test_proof_chain_appends_entries_and_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    log_path = tmp_path / "decision_log.jsonl"
    verdicts = _toxic_and_carry_verdicts()
    assert any(v.approved for v in verdicts) and any(not v.approved for v in verdicts)

    entries = proof_chain.record_decisions(verdicts, ts="2026-01-01T00:00:00+00:00", log_path=log_path)
    assert len(entries) == len(verdicts)
    # the chain verifies (tamper-evident, prev-linked)
    assert proof_chain.verify()["valid"] is True
    # the readable mirror carries BOTH kinds
    rows = proof_chain.recent_decisions(100, log_path=log_path)
    kinds = {r["kind"] for r in rows}
    assert "ENTRY" in kinds and "REFUSAL" in kinds
    # each decision carries a proof hash + the decomposition
    for r in rows:
        assert r["proof_hash"] and "decomposition" in r


def test_proof_chain_payload_deterministic():
    verdicts = _toxic_and_carry_verdicts()
    p1 = [proof_chain.decision_payload(v)["proof_hash"] for v in verdicts]
    p2 = [proof_chain.decision_payload(v)["proof_hash"] for v in verdicts]
    assert p1 == p2


def test_proof_chain_tamper_detected(tmp_path, monkeypatch):
    chain = tmp_path / "audit_chain.jsonl"
    monkeypatch.setattr(hash_chain, "_CHAIN", chain)
    verdicts = _toxic_and_carry_verdicts()
    proof_chain.record_decisions(verdicts, ts="2026-01-01T00:00:00+00:00",
                                 log_path=tmp_path / "decision_log.jsonl")
    # mutate a historical entry → the chain must break
    lines = chain.read_text().splitlines()
    obj = json.loads(lines[0])
    obj["payload"]["approved"] = not obj["payload"]["approved"]
    lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    chain.write_text("\n".join(lines) + "\n")
    assert proof_chain.verify()["valid"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 4) paper service registration (restart-survival + idempotency)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _paper_provider(deep_dataset):
    """A surface provider over the synthetic deep dataset at a fixed day (deterministic)."""
    day = "2024-09-01"
    hedge = BorosFeed().hedge_available(["susde", "ezeth"])
    surface, risks = backtest_rates.build_deep_surface(day, deep_dataset, D0, hedge,
                                                       include_lending=False)
    quotes = list(surface.pt_quotes.values())

    def provider(as_of=None):
        return quotes, risks
    return provider, day


def test_paper_registration_restart_survival(tmp_path, deep_dataset, monkeypatch):
    from spa_core.strategy_lab.rates_desk import paper_rates
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    provider, day = _paper_provider(deep_dataset)

    svc = paper_rates.RatesDeskPaperService(surface_provider=provider, state_dir=tmp_path,
                                            record_proof=True)
    st1 = svc.tick(as_of=day)
    assert st1["gap"] is False
    eq1 = st1["sleeve"]["equity_usd"]
    open1 = st1["sleeve"]["open_books"]
    assert open1 >= 1, "the carry sleeve should have opened a book"

    # RESTART: a fresh service must restore the book, not zero it
    svc2 = paper_rates.RatesDeskPaperService(surface_provider=provider, state_dir=tmp_path,
                                             record_proof=False)
    assert len(svc2._sleeve._books) == open1
    assert svc2._last_tick == day

    # IDEMPOTENT: re-ticking the same day does NOT double-accrue
    st2 = svc2.tick(as_of=day)
    assert abs(st2["sleeve"]["equity_usd"] - eq1) < 1e-6, "same-day re-tick double-accrued"


def test_paper_fail_closed_on_empty_surface(tmp_path):
    from spa_core.strategy_lab.rates_desk import paper_rates

    def empty_provider(as_of=None):
        return [], {}
    svc = paper_rates.RatesDeskPaperService(surface_provider=empty_provider, state_dir=tmp_path,
                                            record_proof=False, alert_on_gap=False)
    st = svc.tick(as_of="2026-01-01")
    assert st["gap"] is True  # no usable quote → fail-closed gap, no advance


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 5) surface_io round-trip + scan (the API shape)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_surface_io_roundtrip_and_scan():
    raw = {
        "generated_at": "2026-06-25T00:00:00+00:00", "as_of": "2026-06-25", "mode": "live",
        "hedge_available": {"susde": False},
        "quotes": [{
            "underlying": "susde", "kind": "stable_synth", "venue": "pendle_pt", "protocol": "pendle",
            "market_id": "PT-susde", "tenor_seconds": 86400 * 90, "as_of": "2026-06-25",
            "quoted_rate": "0.12", "tvl_usd": "50000000", "exit_liquidity_usd": "2000000",
            "hedge_available": False, "utilization": "0", "ltv": "0", "cap_headroom_usd": "0",
        }],
        "underlying_risk": {"susde": {
            "underlying": "susde", "as_of": "2026-06-25", "nav_redemption_value": "1",
            "market_price": "1", "peg_distance": "0", "peg_vol_30d": "0",
            "redemption_sla_seconds": 86400, "reserve_fund_ratio": "0.05",
            "funding_neg_frac_90d": "0.1", "oracle_kind": "chainlink",
            "oracle_staleness_seconds": 300, "nested_protocol_count": 1, "top_borrower_share": "0.1",
        }},
    }
    surface, risks = surface_io.surface_from_cached(raw)
    assert "susde" in surface.pt_quotes and "susde" in risks
    out = surface_io.scan_cached_surface(raw)
    assert out["as_of"] == "2026-06-25"
    assert out["n_opportunities"] >= 1
    shapes = {o["shape"] for o in out["opportunities"]}
    assert "fixed_carry" in shapes
