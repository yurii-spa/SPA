"""test_api_aggressive_lab.py — the Aggressive-Lab SURFACE (Lane 3) contract + red-team.

Covers /api/aggressive-lab/scorecard and /api/aggressive-lab/strategy/{id}:

  • FAIL-CLOSED: a missing scorecard → 200 with an honest "unavailable" envelope (advisory note,
    empty strategies), NEVER a 500 and NEVER a fabricated leaderboard.
  • VERBATIM: a present scorecard is served through, with the risk/tail columns intact.
  • RED-TEAM: the surface can NEVER present a strategy as live-allocated/live-eligible (the
    advisory/outside_riskpolicy stamps are FORCED on, even if a producer set live_eligible=True),
    and the tail (max-DD, tail-in-stress, risk-class) is preserved, not stripped.
  • a corrupt scorecard / NaN-bearing values → fail-closed (empty or scrubbed, no crash).
  • /strategy/{id} serves the realized JSONL series + the risk shape; path-traversal id rejected.

Hermetic: _DATA_DIR is redirected to a tmp dir per test (the canonical API-suite pattern).
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

pytest.importorskip("fastapi", reason="fastapi optional dep not installed — API suite skipped")
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


# ── A documented fixture matching the Lane-2 scorecard schema (return AND risk AND tail). ─────────
def _scorecard_fixture() -> dict:
    return {
        "generated_at": "2026-06-30T00:00:00+00:00",
        "model": "aggressive_lab_scorecard",
        "rwa_floor_pct": 3.4,
        "trustworthy": False,  # THIN forward track → honest: not yet a trustworthy ranking
        "strategies": [
            {
                "id": "susde_delta_neutral",
                "name": "sUSDe delta-neutral",
                "mandate": "stable carry, funding-flip tail",
                "net_return_pct": 11.2,
                "sharpe": None,  # INSUFFICIENT_DATA — never a degenerate number
                "calmar": None,
                "max_drawdown_pct": -8.4,
                "tail_loss_in_stress_pct": -22.0,  # 2025-10 USDe unwind replay
                "risk_class": "C",
                "risk_class_label": "risk-compensation (yield paid for a tail)",
                "risk_shape": "funding_flip",
                "trustworthy": False,
                "verdict": "INSUFFICIENT_DATA",
                "n_points": 6,
                # RED-TEAM: a producer bug sets this True — the surface MUST override it to False.
                "live_eligible": True,
            },
            {
                "id": "lrt_carry",
                "name": "LRT carry (rsETH)",
                "mandate": "restaking carry, depeg tail",
                "net_return_pct": 14.6,
                "sharpe": 1.1,
                "calmar": 0.7,
                "max_drawdown_pct": -12.0,
                "tail_loss_in_stress_pct": -31.0,
                "risk_class": "C",
                "risk_class_label": "risk-compensation (yield paid for a tail)",
                "risk_shape": "depeg",
                "trustworthy": True,
                "verdict": "WATCH",
                "n_points": 40,
            },
        ],
    }


def _write_scorecard(tmp_path: Path, doc) -> None:
    d = tmp_path / "aggressive_lab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "scorecard.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_series(tmp_path: Path, sid: str, lines: list) -> None:
    d = tmp_path / "aggressive_lab" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "realized_series.jsonl").write_text(
        "\n".join(json.dumps(o) for o in lines), encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    monkeypatch.delenv("SPA_AGGRESSIVE_LAB_SELECT", raising=False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c


# ── scorecard: fail-closed ────────────────────────────────────────────────────────────────────
def test_scorecard_missing_is_fail_closed(client):
    """No scorecard file → 200, honest unavailable, empty strategies — never 500, never fabricated."""
    r = client.get("/api/aggressive-lab/scorecard")
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is False
    assert b["strategies"] == []
    assert b["trustworthy"] is False
    assert b["advisory"] is True and b["live_eligible"] is False and b["outside_riskpolicy"] is True
    assert "OUTSIDE RiskPolicy" in b["note"]


def test_scorecard_corrupt_is_fail_closed(client, tmp_path):
    """A corrupt scorecard JSON → the same honest empty envelope, no crash."""
    d = tmp_path / "aggressive_lab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "scorecard.json").write_text("{ this is not json", encoding="utf-8")
    r = client.get("/api/aggressive-lab/scorecard")
    assert r.status_code == 200
    assert r.json()["available"] is False


# ── scorecard: verbatim + risk/tail preserved ───────────────────────────────────────────────────
def test_scorecard_serves_risk_and_tail_columns(client, tmp_path):
    """Return AND risk AND tail are all present per strategy — the tail is NOT stripped."""
    _write_scorecard(tmp_path, _scorecard_fixture())
    r = client.get("/api/aggressive-lab/scorecard")
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is True
    assert b["n_strategies"] == 2
    row = next(s for s in b["strategies"] if s["id"] == "susde_delta_neutral")
    # the mandatory risk/tail columns:
    for k in ("net_return_pct", "max_drawdown_pct", "tail_loss_in_stress_pct",
              "risk_class", "risk_shape", "verdict"):
        assert k in row, f"missing mandatory column {k}"
    assert row["tail_loss_in_stress_pct"] == -22.0
    assert row["risk_class"] == "C"


# ── RED-TEAM: never live-allocated ───────────────────────────────────────────────────────────────
def test_redteam_live_eligible_forced_false(client, tmp_path):
    """Even if a producer set a strategy live_eligible=True, the SURFACE forces advisory/non-live —
    an aggressive strategy can NEVER be presented as live-allocated."""
    _write_scorecard(tmp_path, _scorecard_fixture())
    b = client.get("/api/aggressive-lab/scorecard").json()
    assert b["live_eligible"] is False
    assert b["advisory"] is True
    assert b["outside_riskpolicy"] is True


def test_redteam_select_flag_default_off(client, tmp_path):
    """SPA_AGGRESSIVE_LAB_SELECT defaults OFF; the surface reports it OFF (selection wired to nothing)."""
    _write_scorecard(tmp_path, _scorecard_fixture())
    b = client.get("/api/aggressive-lab/scorecard").json()
    assert b["owner_select_enabled"] is False


def test_select_flag_on_is_read(client, tmp_path, monkeypatch):
    """When the owner flips SPA_AGGRESSIVE_LAB_SELECT, the surface reports it ON (still advisory)."""
    monkeypatch.setenv("SPA_AGGRESSIVE_LAB_SELECT", "1")
    _write_scorecard(tmp_path, _scorecard_fixture())
    b = client.get("/api/aggressive-lab/scorecard").json()
    assert b["owner_select_enabled"] is True
    assert b["live_eligible"] is False  # the flag NEVER makes a strategy live-eligible


# ── strategy/{id}: series + risk shape ───────────────────────────────────────────────────────────
def test_strategy_serves_series_and_risk_shape(client, tmp_path):
    _write_scorecard(tmp_path, _scorecard_fixture())
    _write_series(tmp_path, "susde_delta_neutral", [
        {"date": "2026-06-25", "equity_usd": 100000.0, "phase": "forward"},
        {"date": "2026-06-26", "equity_usd": 100030.0, "phase": "forward"},
        {"date": "2024-08-15", "equity_usd": 98000.0, "phase": "backtest"},
    ])
    r = client.get("/api/aggressive-lab/strategy/susde_delta_neutral")
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is True
    assert b["n_points"] == 3 and b["n_forward"] == 2 and b["n_backtest"] == 1
    assert b["risk_shape"] == "funding_flip"
    assert b["risk_class"] == "C"
    assert b["advisory"] is True and b["live_eligible"] is False
    assert b["scorecard_row"]["tail_loss_in_stress_pct"] == -22.0


def test_strategy_unknown_id_fail_closed(client):
    r = client.get("/api/aggressive-lab/strategy/does_not_exist")
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is False
    assert b["series"] == []


def test_strategy_path_traversal_rejected(client):
    """A crafted id (path traversal) never escapes the data dir: an encoded-slash id fails routing
    (404, never reaches the FS), and a literal dotted id is rejected by the handler guard to an
    honest empty series (200)."""
    # encoded slash → the router cannot match the single path segment → 404 (safe: no FS touch).
    r = client.get("/api/aggressive-lab/strategy/..%2f..%2fetc")
    assert r.status_code == 404
    # a dot-prefixed id DOES reach the handler (clean single segment) — the in-handler slug guard
    # rejects it to an honest empty series (it would otherwise name a hidden dir).
    r2 = client.get("/api/aggressive-lab/strategy/.ssh")
    assert r2.status_code == 200
    b = r2.json()
    assert b["available"] is False
    assert b["series"] == []
    assert b.get("unavailable_reason") == "invalid strategy id"


def test_real_lane2_schema_is_normalized(client, tmp_path):
    """The REAL Lane-2 scorecard uses strategy_id / realized_apy_pct / max_dd_pct / tail{} — the
    surface normalizes those onto id / net_return_pct / max_drawdown_pct / tail_loss_in_stress_pct
    WITHOUT dropping the originals and WITHOUT fabricating. Derived from the real producer schema."""
    doc = {
        "generated_at": "2026-06-30T00:00:00+00:00",
        "model": "aggressive_lab_scorecard",
        "n_trustworthy": 0,  # THIN → top-level trustworthy must derive False
        "strategies": [{
            "strategy_id": "leverage_loop",
            "risk_class": "C",
            "risk_class_label": "risk-compensation",
            "risk_shape": "liquidation",
            "headline_apy_pct": 15.0,
            "realized_apy_pct": -8.95,
            "max_dd_pct": 27.94,           # positive magnitude in Lane 2
            "sharpe": -0.66,
            "verdict": "SEVERE_TAIL",
            "trustworthy": False,
            "tail": {"worst_tail_dd_pct": 35.22, "worst_in_sample_loss_pct": 13.02},
        }],
    }
    d = tmp_path / "aggressive_lab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "scorecard.json").write_text(json.dumps(doc), encoding="utf-8")
    b = client.get("/api/aggressive-lab/scorecard").json()
    assert b["available"] is True
    assert b["trustworthy"] is False  # derived from n_trustworthy=0
    row = b["strategies"][0]
    assert row["id"] == "leverage_loop"                      # normalized from strategy_id
    assert row["strategy_id"] == "leverage_loop"             # original preserved verbatim
    assert row["net_return_pct"] == -8.95                    # realized preferred over headline
    assert row["max_drawdown_pct"] == -27.94                 # positive magnitude → signed loss
    assert row["tail_loss_in_stress_pct"] == -35.22          # worst replayed stress → signed loss
    assert row["risk_class"] == "C" and row["verdict"] == "SEVERE_TAIL"


def test_strategy_corrupt_jsonl_line_dropped(client, tmp_path):
    """A corrupt line in the JSONL is dropped, the good points still serve, no crash."""
    d = tmp_path / "aggressive_lab" / "lrt_carry"
    d.mkdir(parents=True, exist_ok=True)
    (d / "realized_series.jsonl").write_text(
        '{"date": "2026-06-25", "equity_usd": 100000.0, "phase": "forward"}\n'
        "{ corrupt line\n"
        '{"date": "2026-06-26", "equity_usd": 100050.0, "phase": "forward"}\n',
        encoding="utf-8")
    r = client.get("/api/aggressive-lab/strategy/lrt_carry")
    assert r.status_code == 200
    assert r.json()["n_points"] == 2


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Annual Contrast — the owner's sales surface (/api/aggressive-lab/annual-contrast)
#   the 15% aggressive books' year-long equity vs the desk's REAL steady ~5%, drawdowns DATED.
#   Served VERBATIM, fail-CLOSED, advisory/non-live stamps FORCED. Red-team: real baseline,
#   real dated annotations, modeled-vs-realized kept separate, no fabricated curve on a miss.
# ══════════════════════════════════════════════════════════════════════════════════════════════
def _contrast_fixture() -> dict:
    """A documented fixture matching data/aggressive_lab/annual_contrast.json (the data contract)."""
    return {
        "generated_at": "2026-06-30T00:00:00+00:00",
        "as_of": "2026-06-25",
        "model": "aggressive_lab_annual_contrast",
        "is_advisory": True,
        "outside_riskpolicy": True,
        "notional_usd": 100000.0,
        "stable_apy_pct": 4.14,
        "stable_apy_source": "live_conservative_book (paper_trading_status.json apy_today_pct)",
        "proof_hash": "bd77c779ca111f24afb28c981d7324184a62a4626d68fc16cf848d076108b1d1",
        "risk_class_legend": {"C": "risk-compensation (yield paid for a tail)"},
        "stress_windows": [
            {"key": "usde_unwind_2025_10", "event": "2025-10 USDe leverage unwind",
             "event_date": "2025-10-11"},
        ],
        "n_strategies": 1,
        "strategies": [
            {
                "strategy_id": "pendle_pt_levered",
                "risk_class": "C",
                "risk_class_label": "risk-compensation (yield paid for a tail)",
                "risk_shape": "liquidation",
                "headline_apy_pct": 15.0,
                "status": "OK",
                # RED-TEAM: a producer bug sets this True — the surface MUST override it to False.
                "live_eligible": True,
                "windows": [
                    {
                        "window": "trailing_12m", "label": "Trailing 12 months",
                        "date_from": "2025-06-25", "date_to": "2026-06-25",
                        "notional_usd": 100000.0,
                        "aggressive": {"side": "aggressive_15pct", "total_return_pct": 10.8,
                                       "cagr_pct": 10.8, "max_drawdown_pct": -4.2,
                                       "days_underwater": 31, "start_equity_usd": 100000.0,
                                       "end_equity_usd": 110800.0},
                        "stable": {"side": "stable_5pct", "total_return_pct": 4.14, "cagr_pct": 4.14,
                                   "max_drawdown_pct": 0.0, "days_underwater": 0,
                                   "start_equity_usd": 100000.0, "end_equity_usd": 104140.0},
                        "cost_of_chasing_dd_pct": -4.2,
                    },
                ],
                "dated_drawdown_timeline": {
                    "series_from": "2024-03-05", "series_to": "2026-06-25",
                    "realized_drawdowns": [],
                    "worst_realized_episode": None,
                    "dated_stress_overlay": [
                        {"window_key": "usde_unwind_2025_10",
                         "event": "2025-10 USDe leverage unwind (USDe $14B→$5.6B)",
                         "event_date": "2025-10-11", "risk_shape": "liquidation",
                         "depth_pct": -12.0, "modeled_loss_usd": -29729.02,
                         "source": "modeled_stress_overlay"},
                    ],
                },
            },
        ],
    }


def _write_contrast(tmp_path: Path, doc) -> None:
    d = tmp_path / "aggressive_lab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "annual_contrast.json").write_text(json.dumps(doc), encoding="utf-8")


def test_contrast_missing_is_fail_closed(client):
    """No contrast file → 200, honest unavailable, NO strategies, NO fabricated curve/baseline."""
    r = client.get("/api/aggressive-lab/annual-contrast")
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is False
    assert b["strategies"] == []
    assert b["stable_apy_pct"] is None          # red-team: never invent a baseline on a miss
    assert b["advisory"] is True and b["live_eligible"] is False and b["outside_riskpolicy"] is True
    assert "OUTSIDE RiskPolicy" in b["note"]


def test_contrast_corrupt_is_fail_closed(client, tmp_path):
    """A corrupt contrast JSON → the same honest empty envelope, no crash, no fake chart."""
    d = tmp_path / "aggressive_lab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "annual_contrast.json").write_text("{ not json", encoding="utf-8")
    r = client.get("/api/aggressive-lab/annual-contrast")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_contrast_serves_verbatim_with_real_baseline(client, tmp_path):
    """The REAL steady baseline (stable_apy_pct/source) + the dated stress overlay are served
    verbatim — the ~5% line is the real conservative book, not a flattering fake."""
    _write_contrast(tmp_path, _contrast_fixture())
    r = client.get("/api/aggressive-lab/annual-contrast")
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is True
    assert b["n_strategies"] == 1
    # RED-TEAM: the steady baseline is the REAL conservative book, traceable to its source.
    assert b["stable_apy_pct"] == 4.14
    assert "live_conservative_book" in b["stable_apy_source"]
    assert b["proof_hash"].startswith("bd77c779")


def test_contrast_dated_annotations_are_real(client, tmp_path):
    """RED-TEAM: drawdown annotations carry their REAL dates+events from the data (not invented),
    and modeled vs realized are kept SEPARATE (a modeled overlay is never echoed as a realized dip)."""
    _write_contrast(tmp_path, _contrast_fixture())
    b = client.get("/api/aggressive-lab/annual-contrast").json()
    ddt = b["strategies"][0]["dated_drawdown_timeline"]
    assert ddt["realized_drawdowns"] == []          # honest: empty (smooth accrual), not faked
    overlay = ddt["dated_stress_overlay"]
    assert len(overlay) == 1
    o = overlay[0]
    assert o["event_date"] == "2025-10-11"          # real dated event from the data
    assert "USDe" in o["event"]
    assert o["depth_pct"] == -12.0
    assert o["source"] == "modeled_stress_overlay"  # labelled MODELED — never as a realized dip


def test_contrast_redteam_live_eligible_forced_false(client, tmp_path):
    """Even if a producer set a strategy live_eligible=True, the SURFACE forces advisory/non-live."""
    _write_contrast(tmp_path, _contrast_fixture())
    b = client.get("/api/aggressive-lab/annual-contrast").json()
    assert b["live_eligible"] is False
    assert b["advisory"] is True
    assert b["outside_riskpolicy"] is True


def test_contrast_contrast_table_metrics_present(client, tmp_path):
    """Both sides carry CAGR / max-DD / days-underwater for the side-by-side contrast table."""
    _write_contrast(tmp_path, _contrast_fixture())
    b = client.get("/api/aggressive-lab/annual-contrast").json()
    win = b["strategies"][0]["windows"][0]
    for side in ("aggressive", "stable"):
        for k in ("cagr_pct", "max_drawdown_pct", "days_underwater"):
            assert k in win[side], f"missing {side}.{k}"
    assert win["stable"]["max_drawdown_pct"] == 0.0    # the steady book is ~flat
    assert win["aggressive"]["max_drawdown_pct"] < 0   # the aggressive book has a real cost
    assert win["cost_of_chasing_dd_pct"] == -4.2
