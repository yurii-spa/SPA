"""
tests/test_optimizer_ab_harness.py — Cutover-Bulletproof WS-1.3 + WS-1.4.

Pins the Optimizer A/B harness (scripts/optimizer_ab.py) and the two API
surfaces (/api/optimizer-ab, /api/captured-book):

  PROPERTY  — the A/B uplift is INVARIANT under bar-reordering + idempotent on
              re-run (deterministic); the optimizer book in the A/B respects ALL
              RiskPolicy caps (the uplift is never a cap breach); the optimizer
              stays BEHIND A FLAG (cycle default unchanged).
  RED-TEAM  — a degenerate / look-ahead bar set (future-dated, duplicate,
              fabricated-high, non-finite) → the harness REFUSES with a null
              uplift, NEVER an inflated number; the captured-book API never leaks
              a fabricated number on missing data (fail-closed 200).
  SMOKE     — run the harness on a SANDBOX copy → an honest risk-adjusted uplift;
              hit both endpoints → 200 + real-or-honest-unavailable; confirm live
              data/ is never written.

Pure stdlib + pytest. Deterministic. LLM-forbidden. NEVER touches live data/.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import scripts.optimizer_ab as ab  # noqa: E402
from spa_core.allocator.allocator import StrategyAllocator  # noqa: E402

T1_CAP = StrategyAllocator.T1_CAP
T2_CAP = StrategyAllocator.T2_CAP
T2_TOTAL_CAP = StrategyAllocator.T2_TOTAL_CAP
_CAP_TOL = 1e-4


# ---------------------------------------------------------------------------
# Fixtures — a clean evidenced window + a poisoned one, both in a temp file.
# ---------------------------------------------------------------------------
def _write_track(tmp: Path, days: list[dict]) -> Path:
    p = tmp / "equity_curve_daily.json"
    p.write_text(json.dumps({"daily": days}), encoding="utf-8")
    return p


def _clean_days() -> list[dict]:
    # PAST evidenced days (so the look-ahead guard does not fire), held protocols
    # spanning T1 + T2 so the replay universe has real cap geometry.
    return [
        {"date": "2026-06-22", "evidenced": True, "apy_today": 4.48,
         "positions": {"aave_v3": 23250.0, "compound_v3": 15852.0,
                       "maple": 15852.0, "euler_v2": 10568.0, "yearn_v3": 3170.0}},
        {"date": "2026-06-23", "evidenced": True, "apy_today": 4.47,
         "positions": {"aave_v3": 23250.0, "compound_v3": 15852.0,
                       "maple": 15852.0, "euler_v2": 10568.0, "yearn_v3": 3170.0}},
        {"date": "2026-06-24", "evidenced": True, "apy_today": 4.47,
         "positions": {"aave_v3": 23250.0, "compound_v3": 15852.0,
                       "maple": 15852.0, "euler_v2": 10568.0, "yearn_v3": 3170.0}},
    ]


def _registry_path() -> Path:
    return _REPO_ROOT / "data" / "adapter_registry.json"


# ===========================================================================
# SMOKE — honest uplift on a sandbox window; optimizer stays behind a flag.
# ===========================================================================
def test_smoke_ab_produces_honest_uplift_behind_flag():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        track = _write_track(tmp, _clean_days())
        out = ab.run_ab(equity_path=track, registry_path=_registry_path())
    assert out["status"] == "ok"
    assert out["n_days"] == 3
    # honest risk-adjusted uplift (yield-on-deployed): finite, optimizer ≥ legacy.
    assert math.isfinite(out["uplift_pp"])
    assert out["optimized_apy"] >= out["legacy_apy"] - _CAP_TOL
    assert out["uplift_pp"] >= -_CAP_TOL
    # the optimizer is SHADOW — never the cycle default.
    assert out["optimizer_cycle_default"] is False
    assert out["optimizer_behind_flag"] is True
    # honest caveat present (risk-adjusted, cap-headroom-dependent).
    assert "risk-adjusted" in out["honest_caveat"].lower()
    assert "cap" in out["honest_caveat"].lower()


def test_cycle_default_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("SPA_OPTIMIZER_CYCLE_DEFAULT", raising=False)
    assert ab.optimizer_cycle_default() is False
    # DEFAULT_MODEL of the live allocator is unchanged (still the heuristic).
    from spa_core.allocator.allocator import DEFAULT_MODEL
    assert DEFAULT_MODEL == "risk_adjusted"
    monkeypatch.setenv("SPA_OPTIMIZER_CYCLE_DEFAULT", "1")
    assert ab.optimizer_cycle_default() is True


# ===========================================================================
# PROPERTY — bar-reorder invariant + idempotent re-run (deterministic).
# ===========================================================================
def test_prop_uplift_invariant_under_bar_reorder():
    days = _clean_days()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        t1 = _write_track(tmp, days)
        r1 = ab.run_ab(equity_path=t1, registry_path=_registry_path())
        t2 = _write_track(tmp, list(reversed(days)))
        r2 = ab.run_ab(equity_path=t2, registry_path=_registry_path())
    # per-DATE uplift is identical regardless of bar order in the file.
    m1 = {x["date"]: x["uplift_pp"] for x in r1["per_day"]}
    m2 = {x["date"]: x["uplift_pp"] for x in r2["per_day"]}
    assert m1 == m2


def test_prop_idempotent_rerun_byte_identical():
    days = _clean_days()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        t = _write_track(tmp, days)
        r1 = ab.run_ab(equity_path=t, registry_path=_registry_path())
        r2 = ab.run_ab(equity_path=t, registry_path=_registry_path())
    # everything except the wall-clock as_of timestamp is identical.
    for k in ("uplift_pp", "legacy_apy", "optimized_apy",
              "riskadj_score_uplift", "per_day"):
        assert r1[k] == r2[k], f"non-deterministic field {k}"


# ===========================================================================
# PROPERTY — the A/B optimizer book respects ALL RiskPolicy caps (never a breach).
# ===========================================================================
def test_prop_ab_optimizer_book_respects_caps():
    days = _clean_days()
    registry = ab.load_registry_apy(_registry_path())
    with tempfile.TemporaryDirectory() as d:
        sandbox = Path(d)
        for day in days:
            adapters = ab.build_universe_for_day(day, registry)
            opt = ab._sandbox_allocator(
                sandbox, adapters, model_objective="max_yield", risk_scores_doc=None
            ).allocate(model="optimized_yield")
            tier = {a["protocol"]: a["tier"] for a in adapters}
            allocated = sum(opt.target_weights.values())
            # cash floor honored (optimizer reserves ≥5%).
            assert (1.0 - allocated) >= 0.05 - _CAP_TOL
            t2_total = 0.0
            for p, w in opt.target_weights.items():
                is_t1 = str(tier.get(p, "T2")).upper() == "T1"
                cap = T1_CAP if is_t1 else T2_CAP
                assert w <= cap + _CAP_TOL, f"cap breach {p}={w}>{cap}"
                if not is_t1:
                    t2_total += w
            assert t2_total <= T2_TOTAL_CAP + _CAP_TOL


# ===========================================================================
# RED-TEAM — degenerate / look-ahead bar sets must REFUSE (null uplift).
# ===========================================================================
@pytest.mark.parametrize("bad_days,expect_flag_substr", [
    ([{"date": "2099-01-01", "evidenced": True, "apy_today": 5.0,
       "positions": {"aave_v3": 1000}}], "look_ahead"),
    ([{"date": "2026-06-22", "evidenced": True, "apy_today": 5000.0,
       "positions": {"aave_v3": 1000}}], "fabricated_high"),
    ([{"date": "2026-06-22", "evidenced": True, "apy_today": 5.0, "positions": {"aave_v3": 1}},
      {"date": "2026-06-22", "evidenced": True, "apy_today": 5.0, "positions": {"aave_v3": 1}}],
     "duplicate"),
    ([{"date": "2026-06-22", "evidenced": True, "apy_today": float("inf"),
       "positions": {"aave_v3": 1000}}], "nonfinite"),
])
def test_redteam_degenerate_bars_refuse(bad_days, expect_flag_substr):
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        track = _write_track(tmp, bad_days)
        out = ab.run_ab(equity_path=track, registry_path=_registry_path())
    assert out["status"] == "unavailable", "poisoned bars produced an uplift!"
    assert out["uplift_pp"] is None, "REFUSED run leaked a non-null uplift"
    assert any(expect_flag_substr in f for f in out["flags"]), out["flags"]


def test_redteam_missing_track_fails_closed():
    out = ab.run_ab(equity_path=Path("/nonexistent/equity.json"))
    assert out["status"] == "unavailable"
    assert out["reason"] == "track_unreadable"
    assert out["uplift_pp"] is None


def test_redteam_empty_window_fails_closed():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # only NON-evidenced (warmup) days → empty evidenced window.
        track = _write_track(tmp, [
            {"date": "2026-06-10", "evidenced": False, "apy_today": 4.0,
             "positions": {"aave_v3": 1000}},
        ])
        out = ab.run_ab(equity_path=track)
    assert out["status"] == "unavailable"
    assert out["reason"] == "no_evidenced_days"
    assert out["uplift_pp"] is None


# ===========================================================================
# WS-1.4 ENDPOINTS — 200 + real-or-honest-unavailable, never 500, never fabricated.
# ===========================================================================
def _client():
    from fastapi.testclient import TestClient
    from spa_core.api import server
    return TestClient(server.app), server


def test_api_optimizer_ab_and_captured_book_graceful(monkeypatch):
    client, server = _client()
    with tempfile.TemporaryDirectory() as d:
        # point the API at an EMPTY data dir → both must fail-CLOSED gracefully.
        monkeypatch.setattr(server, "_DATA_DIR", Path(d))
        r1 = client.get("/api/optimizer-ab")
        r2 = client.get("/api/captured-book")
        assert r1.status_code == 200 and r2.status_code == 200
        b1, b2 = r1.json(), r2.json()
        assert b1["status"] == "unavailable" and b1["uplift_pp"] is None
        assert b1["optimizer_behind_flag"] is True
        assert b2["status"] == "unavailable" and b2["accrued_carry_usd"] is None
        assert b2["is_advisory"] is True

        # corrupt JSON in both sources → still 200 (no 500, no fabricated number).
        (Path(d) / "optimizer_ab.json").write_text("{not json", encoding="utf-8")
        (Path(d) / "rates_desk" / "paper").mkdir(parents=True, exist_ok=True)
        (Path(d) / "rates_desk" / "paper" / "status.json").write_text(
            "broken{", encoding="utf-8"
        )
        assert client.get("/api/optimizer-ab").status_code == 200
        assert client.get("/api/captured-book").status_code == 200


def test_api_serves_real_artifacts_when_present(monkeypatch, tmp_path):
    """With a real A/B artifact + captured book staged in a temp data dir, both
    endpoints return status:ok and pass the numbers through VERBATIM."""
    client, server = _client()
    # stage a minimal-but-valid optimizer_ab artifact + captured book.
    (tmp_path / "optimizer_ab.json").write_text(json.dumps({
        "status": "ok", "as_of": "2026-06-28T00:00:00+00:00",
        "model": "optimizer_ab_harness", "n_days": 3,
        "legacy_apy": 4.5, "optimized_apy": 5.87, "uplift_pp": 1.37,
        "optimizer_cycle_default": False, "optimizer_behind_flag": True,
        "cap_binding_diagnostics": {"days_total": 3, "days_uplift_materialised": 3},
    }), encoding="utf-8")
    paper = tmp_path / "rates_desk" / "paper"
    paper.mkdir(parents=True)
    (paper / "status.json").write_text(json.dumps({
        "gap": False,
        "sleeve": {"id": "rates_desk_fixed_carry", "name": "FixedCarry",
                   "equity_usd": 100005.74, "net_apy_pct": 0.0057,
                   "open_books": 3, "closed_books": 0, "last_tick": "2026-06-28"},
        "scan_diag": {"approvals": 1, "refusals": 1, "refused_by_reason": {"size_floor": 1}},
    }), encoding="utf-8")
    (paper / "rates_desk_fixed_carry_series.json").write_text(json.dumps({
        "id": "rates_desk_fixed_carry",
        "series": [
            {"date": "2026-06-25", "equity_usd": 100000.0, "net_apy_pct": 0.0,
             "open_books": 0, "approvals": 0, "refusals": 3},
            {"date": "2026-06-28", "equity_usd": 100005.74, "net_apy_pct": 0.0057,
             "open_books": 3, "approvals": 1, "refusals": 1},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    b1 = client.get("/api/optimizer-ab").json()
    b2 = client.get("/api/captured-book").json()
    assert b1["status"] == "ok" and b1["uplift_pp"] == 1.37
    assert b1["optimizer_cycle_default"] is False
    assert b2["status"] == "ok" and b2["n_open_books"] == 3
    # accrued carry derived verbatim: 100005.74 − 100000.0.
    assert abs(b2["accrued_carry_usd"] - 5.74) < 1e-6
    assert b2["refusals"] == {"size_floor": 1}
    assert b2["is_advisory"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-p", "no:randomly", "-q"]))
