"""test_dfb_alerts.py — DFB Month-2 Lane-B: ALERTS on the desk's kill signals (+ watchlist API).

The KILLER alert is REFUSAL_FLIP: a pool that flips SAFE/WATCH → REFUSE (the desk would now refuse a
pool you watch). These tests pin the charter's three verifications for WS-2.3:

  • PROPERTY  — deterministic: same (prev, today) → same alert set; severity ranking is stable;
                the alert reuses the engine's evaluate_hold (no-fork); proof-chain re-derives.
  • RED-TEAM  — a SAFE→REFUSE flip MUST fire REFUSAL_FLIP (the killer can't be missed); a missing /
                thin prior history MUST NOT fabricate a flip (fail-CLOSED); severity reflects the
                real signal (a REFUSE flip outranks an APY wobble); a depeg/oracle engine kill from
                evaluate_hold surfaces with its real KillReason; an alert is not re-fired idempotently.
  • SMOKE     — feed a synthetic SAFE→REFUSE transition → alert fires + persists + chains; the
                /api/dfb/alerts + /api/dfb/pool/{id}/alerts endpoints serve; the watchlist (pool_id
                filter) returns only the requested pool's alerts.

PURE / hermetic (tmp dirs) / no network / no live-data mutation.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spa_core.dfb import alerts  # noqa: E402
from spa_core.strategy_lab.rates_desk import rate_policy as engine_policy  # noqa: E402
from spa_core.strategy_lab.rates_desk.contracts import (  # noqa: E402
    KillReason,
    RatePolicyParams,
    UnderlyingRisk,
)


# ── fixtures ────────────────────────────────────────────────────────────────────────────
def _overlay(
    *, pool_id="pendle__ethereum__ezeth", protocol="pendle", asset="ezeth", chain="Ethereum",
    verdict="REFUSE", reason="tail_veto", tail_veto=True, apy_total=0.12, tvl_usd=30_000_000.0,
    structural=0.15, exit_hole=True, as_of="2026-06-30",
) -> dict:
    exit_1m = {"ticket_usd": 1_000_000,
               "absorbable_usd": (None if exit_hole else 5_000_000.0),
               "dex_exit_frac": (None if exit_hole else 0.9), "flagged": exit_hole}
    return {
        "pool_id": pool_id, "protocol": protocol, "chain": chain, "asset": asset, "tier": "T2",
        "apy": {"total": apy_total, "base": apy_total, "reward": 0.0}, "tvl_usd": tvl_usd,
        "structural_haircut": structural, "total_haircut": 0.30,
        "exit_liquidity": [exit_1m],
        "refusal": {"verdict": verdict, "reason": reason, "tail_veto": tail_veto},
        "as_of": as_of,
    }


def _prev(*, verdict="SAFE", apy_total=0.12, tvl_usd=30_000_000.0, structural=0.02,
          exit_hole=False, as_of="2026-06-29") -> dict:
    return {"as_of": as_of, "capture_date": as_of, "refusal_verdict": verdict,
            "apy_total": apy_total, "tvl_usd": tvl_usd, "structural_haircut": structural,
            "exit_1m_is_hole": exit_hole}


# ══════════════════════════════════════ RED-TEAM ══════════════════════════════════════════
def test_redteam_safe_to_refuse_fires_refusal_flip():
    """The KILLER: a pool flipping SAFE→REFUSE MUST fire a REFUSAL_FLIP. Cannot be missed."""
    out = alerts.compute_alerts(_overlay(verdict="REFUSE"), _prev(verdict="SAFE"))
    types = [a["type"] for a in out]
    assert alerts.ALERT_REFUSAL_FLIP in types, "the killer SAFE→REFUSE alert was MISSED"
    flip = next(a for a in out if a["type"] == alerts.ALERT_REFUSAL_FLIP)
    assert flip["severity"] == "critical"
    assert flip["detail"]["prev_verdict"] == "SAFE"
    assert flip["detail"]["today_verdict"] == "REFUSE"


def test_redteam_watch_to_refuse_also_fires():
    """A WATCH→REFUSE crossing is also the killer (any non-REFUSE → REFUSE)."""
    out = alerts.compute_alerts(_overlay(verdict="REFUSE"), _prev(verdict="WATCH"))
    assert any(a["type"] == alerts.ALERT_REFUSAL_FLIP for a in out)


def test_redteam_no_prior_history_no_fabricated_flip():
    """fail-CLOSED: with NO prior snapshot we cannot assert a transition → NO flip is fabricated."""
    out = alerts.compute_alerts(_overlay(verdict="REFUSE"), None)
    assert not any(a["type"] == alerts.ALERT_REFUSAL_FLIP for a in out), \
        "fabricated a flip with no prior history (would be a lie)"


def test_redteam_already_refused_does_not_refire():
    """A pool REFUSE yesterday AND today is NOT a crossing → no REFUSAL_FLIP (edge-triggered)."""
    out = alerts.compute_alerts(_overlay(verdict="REFUSE"), _prev(verdict="REFUSE"))
    assert not any(a["type"] == alerts.ALERT_REFUSAL_FLIP for a in out)


def test_redteam_severity_refuse_flip_outranks_apy_wobble():
    """Severity must reflect the real signal: a REFUSE flip outranks an APY collapse."""
    # today: flipped to REFUSE AND apy collapsed.
    today = _overlay(verdict="REFUSE", apy_total=0.02)
    prev = _prev(verdict="SAFE", apy_total=0.12)
    out = alerts.compute_alerts(today, prev)
    out_sorted = sorted(out, key=lambda a: a["severity_rank"])
    assert out_sorted[0]["type"] == alerts.ALERT_REFUSAL_FLIP, "REFUSE flip must rank above APY wobble"
    assert alerts.ALERT_APY_COLLAPSE in [a["type"] for a in out]
    assert (alerts.SEVERITY_RANK[alerts.ALERT_REFUSAL_FLIP]
            < alerts.SEVERITY_RANK[alerts.ALERT_APY_COLLAPSE])


def test_redteam_evaluate_hold_engine_kill_surfaces_real_reason():
    """A depeg engine kill from evaluate_hold surfaces with its REAL KillReason (no-fork reuse)."""
    today = _overlay(pool_id="pendle__ethereum__susde", asset="susde", verdict="SAFE",
                     reason="none", tail_veto=False, structural=0.01, exit_hole=False)
    toxic = UnderlyingRisk(
        underlying="susde", as_of="2026-06-30", nav_redemption_value=Decimal("1"),
        market_price=Decimal("0.90"), peg_distance=Decimal("0.10"), peg_vol_30d=Decimal("0.05"),
        redemption_sla_seconds=86400, reserve_fund_ratio=Decimal("0.5"),
        funding_neg_frac_90d=Decimal("0"), oracle_kind="chainlink", oracle_staleness_seconds=60,
        nested_protocol_count=1, top_borrower_share=Decimal("0.1"))
    v = alerts.hold_verdict(today, params=RatePolicyParams(), risk_override=toxic)
    assert v is not None and not v.approved and v.reason == KillReason.UNDERLYING_DEPEG
    out = alerts.compute_alerts(today, _prev(verdict="SAFE"), hold_result=v)
    peg = [a for a in out if a["type"] == alerts.ALERT_PEG_IL_SPIKE]
    assert peg and peg[0]["kill_reason"] == "underlying_depeg"


# ══════════════════════════════════════ PROPERTY ══════════════════════════════════════════
def test_property_deterministic():
    """Same (prev, today) → byte-identical alert set across runs."""
    a = alerts.compute_alerts(_overlay(), _prev())
    b = alerts.compute_alerts(_overlay(), _prev())
    assert a == b


def test_property_alert_reuses_evaluate_hold_no_fork():
    """The hold verdict IS the engine's own evaluate_hold object (import-not-fork)."""
    assert alerts.evaluate_hold is engine_policy.evaluate_hold


def test_property_other_diffs_fire():
    """TVL drain + APY collapse + exit-liquidity drop each fire on a real crossing."""
    # exit flip: prev not a hole, today a hole.
    out = alerts.compute_alerts(
        _overlay(verdict="SAFE", reason="none", tail_veto=False, apy_total=0.02, tvl_usd=10_000_000.0,
                 exit_hole=True),
        _prev(verdict="SAFE", apy_total=0.12, tvl_usd=30_000_000.0, exit_hole=False))
    types = {a["type"] for a in out}
    assert alerts.ALERT_APY_COLLAPSE in types
    assert alerts.ALERT_TVL_DRAIN in types
    assert alerts.ALERT_EXIT_LIQUIDITY_DROP in types
    assert alerts.ALERT_REFUSAL_FLIP not in types  # verdict stayed SAFE


def test_property_no_alert_when_quiet():
    """No crossing, no diff → no alerts (no noise)."""
    quiet = _overlay(verdict="SAFE", reason="none", tail_veto=False, apy_total=0.12,
                     tvl_usd=30_000_000.0, structural=0.02, exit_hole=False)
    out = alerts.compute_alerts(quiet, _prev(verdict="SAFE", apy_total=0.12, tvl_usd=30_000_000.0,
                                             structural=0.02, exit_hole=False))
    assert out == []


# ══════════════════════════════════════ SMOKE: run + persist + chain ══════════════════════
def test_smoke_run_alerts_persists_and_chains(tmp_path):
    """run_alerts against a universe with a seeded prior history → REFUSAL_FLIP fires, alerts.json +
    alerts.jsonl are written, and the log chain verifies."""
    from spa_core.dfb import history
    from spa_core.dfb import PoolOverlay, RefusalVerdict, ExitLiquidityRow, RiskClass

    data_dir = tmp_path
    # Seed a PRIOR history snapshot (yesterday: SAFE) so today's REFUSE is a real crossing.
    prev_ov = PoolOverlay(
        pool_id="pendle__ethereum__ezeth", protocol="pendle", chain="Ethereum", asset="ezeth",
        tier="T2", apy={"total": 0.12, "base": 0.12, "reward": 0.0}, tvl_usd=30_000_000.0,
        risk_class=RiskClass.A, risk_class_label="alpha", structural_haircut=0.02, total_haircut=0.05,
        exit_liquidity=[ExitLiquidityRow(1_000_000, 5_000_000.0, 0.9, False)],
        refusal=RefusalVerdict(verdict="SAFE", reason="none", tail_veto=False),
        as_of="2026-06-29", data_source="live", feed_coverage="full", flagged=False,
        flag_reason=None, engine_proof_hash="x", prev_hash="0" * 64, row_hash="seed")
    history.capture_pool(prev_ov, "2026-06-29", data_dir=data_dir)

    today = _overlay(verdict="REFUSE", as_of="2026-06-30")
    payload = alerts.run_alerts([today], data_dir=data_dir, write=True)

    assert payload["n_refusal_flips"] == 1
    assert payload["alerts"][0]["type"] == alerts.ALERT_REFUSAL_FLIP
    assert (data_dir / "dfb" / "alerts.json").exists()
    assert (data_dir / "dfb" / "alerts.jsonl").exists()
    chain = alerts.verify_log_chain(data_dir=data_dir)
    assert chain["valid"], chain


def test_smoke_log_idempotent(tmp_path):
    """Re-running the same day does NOT duplicate the alert in the append-only log."""
    from spa_core.dfb import history
    from spa_core.dfb import PoolOverlay, RefusalVerdict, ExitLiquidityRow, RiskClass
    data_dir = tmp_path
    prev_ov = PoolOverlay(
        pool_id="pendle__ethereum__ezeth", protocol="pendle", chain="Ethereum", asset="ezeth",
        tier="T2", apy={"total": 0.12, "base": 0.12, "reward": 0.0}, tvl_usd=30_000_000.0,
        risk_class=RiskClass.A, risk_class_label="alpha", structural_haircut=0.02, total_haircut=0.05,
        exit_liquidity=[ExitLiquidityRow(1_000_000, 5_000_000.0, 0.9, False)],
        refusal=RefusalVerdict(verdict="SAFE", reason="none", tail_veto=False),
        as_of="2026-06-29", data_source="live", feed_coverage="full", flagged=False,
        flag_reason=None, engine_proof_hash="x", prev_hash="0" * 64, row_hash="seed")
    history.capture_pool(prev_ov, "2026-06-29", data_dir=data_dir)
    today = _overlay(verdict="REFUSE", as_of="2026-06-30")
    alerts.run_alerts([today], data_dir=data_dir, write=True)
    alerts.run_alerts([today], data_dir=data_dir, write=True)  # re-run same day
    log = alerts._read_jsonl(data_dir / "dfb" / "alerts.jsonl")
    flip_lines = [r for r in log if r.get("type") == alerts.ALERT_REFUSAL_FLIP]
    assert len(flip_lines) == 1, f"alert duplicated on re-run: {len(flip_lines)}"


def test_smoke_telegram_digest_off_by_default(tmp_path, monkeypatch):
    """The Telegram digest is OFF unless the flag is set (no flooding agent)."""
    monkeypatch.delenv("SPA_DFB_TELEGRAM_DIGEST", raising=False)
    res = alerts.digest_telegram({"alerts": [], "as_of": "2026-06-30"}, data_dir=tmp_path)
    assert res["sent"] is False and "disabled" in res["reason"]


def test_smoke_telegram_digest_no_flips_no_send(tmp_path):
    """Even forced, an empty REFUSAL_FLIP set sends nothing (never an empty/spam digest)."""
    res = alerts.digest_telegram({"alerts": [], "as_of": "2026-06-30"}, data_dir=tmp_path, force=True)
    assert res["sent"] is False and res["reason"] == "no_refusal_flips"


# ══════════════════════════════════════ SMOKE: the API + watchlist ════════════════════════
@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi optional dep not installed")
    from fastapi.testclient import TestClient
    import spa_core.api.server as server
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


def _seed_alert_universe(data_dir: Path):
    """Seed a prior history snapshot for two pools, then run_alerts on today's overlays so both the
    current-set file and the log exist."""
    from spa_core.dfb import history
    from spa_core.dfb import PoolOverlay, RefusalVerdict, ExitLiquidityRow, RiskClass
    for pid, asset in (("pendle__ethereum__ezeth", "ezeth"), ("pendle__ethereum__susde", "susde")):
        prev_ov = PoolOverlay(
            pool_id=pid, protocol="pendle", chain="Ethereum", asset=asset, tier="T2",
            apy={"total": 0.12, "base": 0.12, "reward": 0.0}, tvl_usd=30_000_000.0,
            risk_class=RiskClass.A, risk_class_label="alpha", structural_haircut=0.02,
            total_haircut=0.05, exit_liquidity=[ExitLiquidityRow(1_000_000, 5_000_000.0, 0.9, False)],
            refusal=RefusalVerdict(verdict="SAFE", reason="none", tail_veto=False),
            as_of="2026-06-29", data_source="live", feed_coverage="full", flagged=False,
            flag_reason=None, engine_proof_hash="x", prev_hash="0" * 64, row_hash="seed")
        history.capture_pool(prev_ov, "2026-06-29", data_dir=data_dir)
    today = [
        _overlay(pool_id="pendle__ethereum__ezeth", asset="ezeth", verdict="REFUSE"),
        _overlay(pool_id="pendle__ethereum__susde", asset="susde", verdict="REFUSE",
                 reason="tail_veto", tail_veto=False),
    ]
    alerts.run_alerts(today, data_dir=data_dir, write=True)


def test_api_alerts_served_severity_ranked(api_client):
    c, data_dir = api_client
    _seed_alert_universe(data_dir)
    r = c.get("/api/dfb/alerts")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["is_advisory"] is True
    assert body["n_refusal_flips"] >= 1
    # severity-ranked: the first alert is the most severe (REFUSAL_FLIP at rank 0).
    assert body["alerts"][0]["type"] == alerts.ALERT_REFUSAL_FLIP


def test_api_alerts_fail_closed_when_absent(api_client):
    c, _ = api_client  # empty data dir → no alerts.json
    r = c.get("/api/dfb/alerts")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["alerts"] == []
    assert "fail-CLOSED" in (body.get("note") or "")


def test_api_watchlist_pool_filter(api_client):
    """The watchlist mechanism: the API serves alerts for a GIVEN pool set (pool_id filter)."""
    c, data_dir = api_client
    _seed_alert_universe(data_dir)
    r = c.get("/api/dfb/alerts", params={"pool_id": "pendle__ethereum__ezeth"})
    assert r.status_code == 200
    body = r.json()
    assert body["alerts"], "watchlist pool should have alerts"
    assert all(a["pool_id"] == "pendle__ethereum__ezeth" for a in body["alerts"])


def test_api_pool_alert_history(api_client):
    c, data_dir = api_client
    _seed_alert_universe(data_dir)
    r = c.get("/api/dfb/pool/pendle__ethereum__ezeth/alerts")
    assert r.status_code == 200
    body = r.json()
    assert body["pool_id"] == "pendle__ethereum__ezeth"
    assert body["n_alerts"] >= 1
    assert all(a["pool_id"] == "pendle__ethereum__ezeth" for a in body["alerts"])
    assert body["chain"]["verified"] is True  # the alert log chain re-derives


def test_api_pool_alerts_invalid_id_404(api_client):
    c, _ = api_client
    r = c.get("/api/dfb/pool/..%2F..%2Fsecret/alerts")
    assert r.status_code in (404, 400)
