"""test_api_cockpit.py — Desk-Cockpit read-API contract (Sprint-0 Lane A).

Property + red-team + smoke tests for the SPA-001/SPA-002 endpoints
(spa_core/api/routers/cockpit.py):

  • /api/decisions + /api/refusals  — unified decision/refusal facade
  • /api/regime                     — live market_regime passthrough
  • /api/strategies + /{id}         — strategy-lab reshape
  • /api/kill-gauge                 — per-condition kill headroom (SPA-002)

Every test asserts the CONTRACT properties the Cockpit depends on:
  1. every response carries ``ts`` + ``stale``;
  2. fail-CLOSED on missing data — 200 honest-unavailable, never 500/fabricated;
  3. refusal reasons map to the enum HONESTLY (no invented reason);
  4. the kill-gauge drawdown headroom is REAL (computed from the live evidenced
     drawdown vs the REAL SOFT 5% / HARD 10% thresholds); a THIN/absent condition
     → UNKNOWN, never a fabricated headroom;
  5. NO-FORK: reuses kill_switch / rate_policy — no re-derived risk math.

Hermetic: _DATA_DIR is redirected so we can drive both the empty (fail-closed)
and a seeded (populated) data dir deterministically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402
from spa_core.api.routers import cockpit  # noqa: E402

# ── Contract endpoints (every one must carry ts+stale, be fail-closed) ──────────
COCKPIT_ENDPOINTS = [
    "/api/decisions",
    "/api/refusals",
    "/api/regime",
    "/api/strategies",
    "/api/strategies/engine_a",
    "/api/kill-gauge",
]


@pytest.fixture()
def empty_client(tmp_path, monkeypatch):
    """TestClient over an EMPTY hermetic data dir → every fail-closed branch fires."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


def _seed(tmp: Path) -> None:
    """Seed a realistic populated data dir for the happy-path assertions."""
    (tmp / "rates_desk").mkdir(parents=True, exist_ok=True)
    # decision_log.jsonl: one ENTRY, one REFUSAL(size_floor), one REFUSAL(peg_haircut).
    rows = [
        {"kind": "ENTRY", "ts": "2026-07-01T17:00:00+00:00", "underlying": "susde",
         "approved": True, "shape": "fixed_carry", "net_edge": 0.11,
         "entry_hash": "aaa", "detail": {"action": "hold"},
         "decomposition": {"total_haircut": 0.03}},
        {"kind": "REFUSAL", "ts": "2026-07-01T17:05:00+00:00", "underlying": "usde",
         "approved": False, "shape": "fixed_carry", "net_edge": 0.066,
         "reason": "size_floor", "entry_hash": "bbb",
         "detail": {"exit_cap": 530.73, "min_tradeable_size_usd": 1000},
         "decomposition": {"total_haircut": 0.0303}},
        {"kind": "REFUSAL", "ts": "2026-07-01T17:06:00+00:00", "underlying": "ezeth",
         "approved": False, "shape": "fixed_carry", "net_edge": 0.05,
         "reason": "peg_haircut", "entry_hash": "ccc",
         "detail": {"exit_cap": 200.0},
         "decomposition": {"total_haircut": 0.07}},
    ]
    (tmp / "rates_desk" / "decision_log.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    (tmp / "market_regime.json").write_text(json.dumps({
        "regime": "VOLATILE", "t1_avg_apy": 3.83, "apy_std_dev": 3.24,
        "recommendation": "diversify", "detected_at": "2026-07-01T06:00:00+00:00",
    }), encoding="utf-8")
    (tmp / "strategy_lab_backtest.json").write_text(json.dumps({
        "manifest": {"generated_at": "2026-07-01T06:00:00+00:00"},
        "kills": {"btc_neutral": {"type": "kill", "reason": "fail-closed", "date": "2024-06-05"}},
        "strategies": {
            "engine_a": {
                "id": "engine_a", "name": "Engine A", "mandate": "T1 blend",
                "equity_first": 100000.0, "equity_last": 100500.0,
                "metrics": {"net_apy_pct": 4.2, "beta_to_eth": 0.0, "sharpe": 1.5,
                            "sortino": 2.0, "max_drawdown_pct": -1.2,
                            "volatility_pct": 0.3, "beats_rwa_floor": True,
                            "funding_drag_pct": 0.0, "extra": {}},
            },
            "btc_neutral": {
                "id": "btc_neutral", "name": "BTC Neutral", "mandate": "btc",
                "is_advisory": True,
                "metrics": {"net_apy_pct": None, "extra": {}},
            },
        },
    }), encoding="utf-8")


@pytest.fixture()
def seeded_client(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


# ── Property 1: every response carries ts + stale, never 500 ────────────────────

@pytest.mark.parametrize("path", COCKPIT_ENDPOINTS)
def test_every_response_has_ts_and_stale(empty_client, path):
    """Contract: every Cockpit response MUST carry ts + stale (fail-closed on empty)."""
    r = empty_client.get(path)
    assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert isinstance(body, dict)
    assert "ts" in body, f"{path} missing ts"
    assert "stale" in body, f"{path} missing stale"
    assert isinstance(body["ts"], (int, float))
    assert isinstance(body["stale"], bool)


# ── Property 2: fail-CLOSED on missing data (200 honest-unavailable) ────────────

def test_decisions_empty_is_honest_unavailable(empty_client):
    b = empty_client.get("/api/decisions").json()
    assert b["n_decisions"] == 0
    assert b["decisions"] == []
    assert b["stale"] is True  # no rows → newest unknown → fail-closed stale


def test_refusals_empty_is_honest_unavailable(empty_client):
    b = empty_client.get("/api/refusals").json()
    assert b["n_refusals"] == 0
    assert b["refusals"] == []
    assert b["stale"] is True
    assert b["reason_enum"] == list(cockpit.REFUSAL_REASONS)


def test_regime_empty_is_unknown_not_fabricated(empty_client):
    b = empty_client.get("/api/regime").json()
    assert b["available"] is False
    assert b["regime"] == "UNKNOWN"
    assert b["cycle_risk"] == "UNKNOWN"
    assert b["stale"] is True


def test_strategies_empty_is_empty_list(empty_client):
    b = empty_client.get("/api/strategies").json()
    assert b["n_strategies"] == 0
    assert b["strategies"] == []


def test_strategy_missing_id_is_honest_unavailable(empty_client):
    b = empty_client.get("/api/strategies/does_not_exist").json()
    assert b["available"] is False
    assert b["strategy_id"] == "does_not_exist"
    assert "reason" in b  # honest, not fabricated


def test_kill_gauge_empty_conditions_are_unknown(empty_client):
    """Empty data dir → drawdown/sharpe/red_flags UNKNOWN, never a fabricated headroom."""
    b = empty_client.get("/api/kill-gauge").json()
    conds = {c["name"]: c for c in b["conditions"]}
    # drawdown: no evidenced equity → UNKNOWN, null headroom (NEVER a fake number)
    assert conds["drawdown"]["status"] == "UNKNOWN"
    assert conds["drawdown"]["headroom_pct"] is None
    # sharpe: THIN → UNKNOWN, null headroom
    assert conds["sharpe"]["status"] == "UNKNOWN"
    assert conds["sharpe"]["headroom_pct"] is None


def test_corrupt_files_never_500(tmp_path, monkeypatch):
    """Red-team: corrupt JSON / decision log lines must degrade, never 500."""
    (tmp_path / "rates_desk").mkdir(parents=True)
    (tmp_path / "rates_desk" / "decision_log.jsonl").write_text(
        "not json\n{bad}\n{\"kind\":\"ENTRY\",\"ts\":\"2026-07-01T00:00:00+00:00\"}\n",
        encoding="utf-8",
    )
    (tmp_path / "market_regime.json").write_text("{not valid", encoding="utf-8")
    (tmp_path / "strategy_lab_backtest.json").write_text("[]", encoding="utf-8")
    (tmp_path / "equity_curve_daily.json").write_text("garbage", encoding="utf-8")
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        for path in COCKPIT_ENDPOINTS + ["/api/kill-gauge"]:
            r = c.get(path)
            assert r.status_code == 200, f"{path} corrupt → {r.status_code}"
        # the one valid ENTRY line survived; the two junk lines were dropped
        assert c.get("/api/decisions").json()["n_decisions"] == 1


# ── Property 3: refusal reasons map to the enum HONESTLY ────────────────────────

def test_refusal_reasons_map_to_enum_honestly(seeded_client):
    b = seeded_client.get("/api/refusals").json()
    assert b["n_refusals"] == 2
    by_op = {r["opportunity"]: r for r in b["refusals"]}
    # size_floor → liquidity bucket (honest map), raw preserved
    assert by_op["usde"]["reason"] == "liquidity"
    assert by_op["usde"]["reason_raw"] == "size_floor"
    # peg_haircut → counterparty_flag
    assert by_op["ezeth"]["reason"] == "counterparty_flag"
    assert by_op["ezeth"]["reason_raw"] == "peg_haircut"
    # every mapped reason is a member of the contract enum (nothing invented)
    for r in b["refusals"]:
        if r["reason"] is not None:
            assert r["reason"] in cockpit.REFUSAL_REASONS


def test_unmapped_reason_is_null_not_invented():
    """An unrecognised reason maps to None (never a fabricated enum member)."""
    assert cockpit._map_reason("some_novel_reason_xyz") is None
    assert cockpit._map_reason("") is None
    assert cockpit._map_reason(None) is None
    # known ones still map
    assert cockpit._map_reason("size_floor") == "liquidity"
    assert cockpit._map_reason("funding_flip") == "funding_flip_risk"


def test_refusal_fields_are_real_or_none(seeded_client):
    """expected_edge_pct / fee_drag_pct / capital_protected are real numbers or None."""
    b = seeded_client.get("/api/refusals").json()
    r = next(x for x in b["refusals"] if x["opportunity"] == "usde")
    assert r["verdict"] == "REFUSE"
    assert r["expected_edge_pct"] == pytest.approx(6.6, abs=0.5)  # 0.066 * 100
    assert r["fee_drag_pct"] == pytest.approx(3.03, abs=0.1)      # 0.0303 * 100
    assert r["capital_protected_est_usd"] == pytest.approx(530.73, abs=0.01)


def test_refusals_reason_filter(seeded_client):
    b = seeded_client.get("/api/refusals?reason=counterparty_flag").json()
    assert b["n_refusals"] == 1
    assert b["refusals"][0]["opportunity"] == "ezeth"


# ── Property 4: kill-gauge headroom is REAL (drawdown vs real thresholds) ───────

def test_kill_gauge_drawdown_headroom_is_real(tmp_path, monkeypatch):
    """A real evidenced drawdown series → a REAL headroom vs the SOFT 5%/HARD 10%.

    NO-FORK check: we seed a curve with a known ~3% drawdown from an evidenced
    peak; the gauge must report drawdown≈3% and headroom≈2% to the SOFT tier —
    computed by kill_switch.evidenced_drawdown_pct, not re-derived here.
    """
    from spa_core.paper_trading.track_evidence import PAPER_REAL_START
    from spa_core.governance.kill_switch import (
        SOFT_DERISK_THRESHOLD_PCT,
        evidenced_drawdown_pct,
    )

    # evidenced bars post-anchor: peak 100, current 97 → 3% drawdown.
    anchor = PAPER_REAL_START.isoformat()
    daily = [
        {"date": anchor, "close_equity": 100.0, "evidenced": True},
        {"date": "2026-06-11", "close_equity": 100.0, "evidenced": True},
        {"date": "2026-06-12", "close_equity": 97.0, "evidenced": True},
    ]
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps({"daily": daily, "generated_at": "2026-06-12T00:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)

    # oracle: what the REAL engine computes on the same data (NO-FORK).
    expected_dd = evidenced_drawdown_pct(daily)
    assert expected_dd is not None and expected_dd == pytest.approx(3.0, abs=0.01)

    with TestClient(server.app, raise_server_exceptions=True) as c:
        b = c.get("/api/kill-gauge").json()
    dd = next(x for x in b["conditions"] if x["name"] == "drawdown")
    assert dd["status"] == "ok"  # 3% < 5% SOFT
    assert dd["value"] == pytest.approx(expected_dd, abs=0.001)
    # headroom to the SOFT tier is the REAL 5% - 3% = 2%
    assert dd["headroom_pct"] == pytest.approx(SOFT_DERISK_THRESHOLD_PCT - expected_dd, abs=0.001)
    assert dd["threshold"] == 10.0 and dd["soft_threshold"] == 5.0


def test_kill_gauge_soft_band_is_warn(tmp_path, monkeypatch):
    """A 7% drawdown lands in [SOFT, HARD) → status warn, headroom to HARD (real)."""
    from spa_core.paper_trading.track_evidence import PAPER_REAL_START

    anchor = PAPER_REAL_START.isoformat()
    daily = [
        {"date": anchor, "close_equity": 100.0, "evidenced": True},
        {"date": "2026-06-11", "close_equity": 100.0, "evidenced": True},
        {"date": "2026-06-12", "close_equity": 93.0, "evidenced": True},
    ]
    (tmp_path / "equity_curve_daily.json").write_text(
        json.dumps({"daily": daily, "generated_at": "2026-06-12T00:00:00+00:00"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        b = c.get("/api/kill-gauge").json()
    dd = next(x for x in b["conditions"] if x["name"] == "drawdown")
    assert dd["status"] == "warn"
    assert dd["value"] == pytest.approx(7.0, abs=0.01)
    assert dd["headroom_pct"] == pytest.approx(3.0, abs=0.01)  # 10% - 7%
    assert b["overall_status"] == "warn"


# ── Strategies reshape (contract StrategySnapshot) ─────────────────────────────

def test_strategies_reshape_contract_shape(seeded_client):
    b = seeded_client.get("/api/strategies").json()
    by_id = {s["strategy_id"]: s for s in b["strategies"]}
    a = by_id["engine_a"]
    # required contract keys
    for k in ("strategy_id", "engine", "name", "status", "allocation", "pnl",
              "apy", "risk", "attribution", "kill_conditions", "liq_nav_by_tier"):
        assert k in a, f"engine_a missing contract key {k}"
    assert a["status"] == "paper"
    assert a["apy"] == 4.2
    assert a["pnl"] == pytest.approx(500.0)  # 100500 - 100000
    assert a["risk"]["sharpe"] == 1.5
    assert a["risk"]["max_dd"] == -1.2
    assert a["kill_conditions"] == []
    # killed sleeve reflects its realised kill honestly
    k = by_id["btc_neutral"]
    assert k["status"] == "killed"
    assert len(k["kill_conditions"]) == 1
    assert k["kill_conditions"][0]["status"] == "kill"


def test_strategy_detail_matches_list(seeded_client):
    detail = seeded_client.get("/api/strategies/engine_a").json()
    assert detail["available"] is True
    assert detail["strategy"]["strategy_id"] == "engine_a"


# ── Regime passthrough ─────────────────────────────────────────────────────────

def test_regime_passthrough_shape(seeded_client):
    b = seeded_client.get("/api/regime").json()
    assert b["available"] is True
    assert b["regime"] == "VOLATILE"
    assert b["cycle_risk"] == "elevated"  # honest derive from VOLATILE label
    assert b["vol"] == 3.24               # apy_std_dev proxy
    assert b["recommendation"] == "diversify"


# ── Decisions merge ────────────────────────────────────────────────────────────

def test_decisions_merge_and_shape(seeded_client):
    b = seeded_client.get("/api/decisions").json()
    # only the ENTRY row (refusals excluded from the decision feed)
    assert b["n_decisions"] == 1
    d = b["decisions"][0]
    for k in ("ts", "type", "engine", "action", "ref", "summary"):
        assert k in d
    assert d["type"] == "decision"
    assert d["engine"] == "rates_desk"
    assert isinstance(b["stale"], bool)  # freshness is wall-clock-dependent; shape-check only
