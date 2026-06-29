"""Aggressive-Lab router (Lane 3 SURFACE) — the public, advisory surface for the Aggressive
Strategy Paper Lab.

WHAT THIS IS
════════════
The Aggressive Lab paper-tests the 10-15% strategies the desk normally REFUSES (sUSDe delta-
neutral, LRT carry, leverage loops, points/incentive farms) so the owner can SEE them — exactly
like the tournament — and CHOOSE later, WITH EYES OPEN ON THE RISK. This router SURFACES Lane 1's
realized series + Lane 2's honest multi-metric scorecard. It computes NOTHING and ranks NOTHING:
it serves the producers' outputs VERBATIM (the ranking/risk lives in Lane 2).

GUARDRAILS (mirrored in every payload)
══════════════════════════════════════
  • OUTSIDE_RISKPOLICY / AGGRESSIVE / ADVISORY — every response is stamped advisory=True,
    live_eligible=False, outside_riskpolicy=True. These strategies are NEVER live-allocated and
    NEVER touch the go-live $100k track.
  • The TAIL/RISK is NEVER hidden — the scorecard carries net return AND Sharpe/Calmar AND max-DD
    AND tail-loss-in-stress AND risk-class AND a trustworthy flag, side by side.
  • FAIL-CLOSED: a missing/corrupt scorecard → 200 with an honest "unavailable" envelope (empty
    leaderboard, advisory note), NEVER a 500 and NEVER a fabricated number.
  • Read-only. GET is public (WS2 CORS allow-list governs origins). No secret access.

DATA CONTRACT (consume Lane 1 + Lane 2)
═══════════════════════════════════════
  • Lane 2 writes the honest scorecard to  data/aggressive_lab/scorecard.json
    (the multi-metric ranking — return AND risk AND tail). Served VERBATIM by /scorecard.
  • Lane 1 writes per-strategy realized series to
    data/aggressive_lab/<strategy_id>/realized_series.jsonl (append-only, proof-chained, one JSON
    object per line). /strategy/{id} serves that series + the strategy's risk shape (pulled from
    the scorecard row + the optional sidecar data/aggressive_lab/<id>/meta.json).

The scorecard.json shape this router serves VERBATIM (Lane 2 owns it; documented here so the
fail-closed envelope matches it and so /strategy/{id} can resolve a row). A scorecard row:

    {
      "id": "<strategy_id>",
      "name": "<human name>",
      "mandate": "<one-liner>",
      "net_return_pct": <float>,        # net annualized return (the yield headline)
      "sharpe": <float|null>,           # null/INSUFFICIENT_DATA below N points (NEVER a degenerate #)
      "calmar": <float|null>,
      "max_drawdown_pct": <float>,      # realized max drawdown (negative = loss)
      "tail_loss_in_stress_pct": <float>,  # worst marked loss replayed thru the stress windows
      "risk_class": "A"|"B"|"C"|"D",    # alpha / beta / risk-compensation / incentive
      "risk_class_label": "<human>",
      "risk_shape": "funding_flip"|"depeg"|"liquidation"|"il"|"incentive_decay",
      "trustworthy": <bool>,            # False until enough realized points → never an honest rank yet
      "verdict": "<label>",             # e.g. SHOW / WATCH / INSUFFICIENT_DATA
      "n_points": <int>,
      ...                               # other Lane-2 fields passed through verbatim
    }

stdlib-only on the serve path. LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os

from fastapi import APIRouter

from spa_core.api._shared import (
    backtest_meta,
    data_dir,
    parse_log_line,
    read_state,
    scrub_nonfinite,
)

router = APIRouter(tags=["aggressive_lab"])

# ── canonical advisory stamp — attached to EVERY response so the surface can never be mistaken
#    for a live-allocated book. The dashboard reads these flags to render the OUTSIDE-RiskPolicy
#    banner; they are NOT optional. ──────────────────────────────────────────────────────────────
_ADVISORY_NOTE = (
    "OUTSIDE RiskPolicy · paper-only · ADVISORY. These are the strategies the desk REFUSES — "
    "shown with the risk that comes with the yield (max-DD, tail-in-stress, risk-class), for "
    "OWNER SELECTION only. They are NEVER live-allocated and NEVER touch the go-live track. "
    "Promoting one to real capital is owner-gated AND custody-gated (SPA_AGGRESSIVE_LAB_SELECT)."
)


def _advisory_envelope() -> dict:
    return {
        "advisory": True,
        "live_eligible": False,
        "outside_riskpolicy": True,
        "owner_selectable": True,
        # Surface the owner-selection flag STATE (read-only) so the dashboard can show whether
        # selection is even wired. Default OFF; flipping it does NOTHING to live allocation.
        "owner_select_enabled": _select_enabled(),
        "note": _ADVISORY_NOTE,
    }


def _select_enabled() -> bool:
    """SPA_AGGRESSIVE_LAB_SELECT — owner-selection flag (default OFF). When OFF, the surface is
    pure read-only advisory. When ON, the owner MAY mark a strategy 'selected for consideration'
    (scaffold only — selection still does NOTHING to live allocation without an explicit
    owner+custody decision). Fail-CLOSED: anything but an explicit truthy value → OFF."""
    return os.environ.get("SPA_AGGRESSIVE_LAB_SELECT", "").strip().lower() in ("1", "true", "yes", "on")


@router.get("/api/aggressive-lab/scorecard")
def get_aggressive_lab_scorecard():
    """Aggressive-Lab honest multi-metric scorecard — data/aggressive_lab/scorecard.json.

    Serves Lane 2's ranking VERBATIM: per-strategy net return AND Sharpe/Calmar AND max-DD AND
    tail-loss-in-stress AND risk-class AND trustworthy flag AND verdict — return and RISK side by
    side. Read-only, FAIL-CLOSED: a missing/corrupt scorecard returns 200 with an honest empty
    envelope (advisory note, empty strategies list), NEVER a 500 and NEVER a fabricated leaderboard.
    NaN/inf in a corrupt file are scrubbed to null (never crash the serializer).
    """
    raw = read_state("aggressive_lab/scorecard.json", {})
    meta = backtest_meta(
        basis="honest multi-metric scorecard over Lane-1 realized series — net return AND "
              "Sharpe/Calmar AND max-DD AND tail-in-stress AND risk-class; NOT a yield-sorted "
              "leaderboard; trustworthy=false until enough realized points",
        period="aggressive-lab forward track + 2024-2026 backtest stress windows",
    )
    env = _advisory_envelope()
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "aggressive_lab_scorecard",
            **env,
            "available": False,
            "unavailable_reason": "scorecard not generated yet (Lane 2 has not produced "
                                  "data/aggressive_lab/scorecard.json)",
            "rwa_floor_pct": None,
            "n_strategies": 0,
            "trustworthy": False,
            "strategies": [],
            "meta": meta,
        }

    strategies = raw.get("strategies")
    strategies = strategies if isinstance(strategies, list) else []
    # Force the advisory/non-live stamps over whatever the file says — the surface can NEVER
    # present an aggressive strategy as live-eligible, even if a producer bug set it.
    out = dict(raw)
    out["available"] = True
    out.setdefault("model", "aggressive_lab_scorecard")
    # Normalize each row to the dashboard's stable column names WITHOUT dropping any Lane-2 field
    # (the original keys pass through verbatim; the normalized aliases are ADDED). No fabrication:
    # a column the producer didn't emit stays null.
    out["strategies"] = [_normalize_row(r) for r in strategies if isinstance(r, dict)]
    out["n_strategies"] = len(out["strategies"])
    out.update(env)  # advisory/live_eligible/outside_riskpolicy/owner_select_enabled/note — authoritative
    out["trustworthy"] = _derive_trustworthy(raw)
    out.setdefault("meta", meta)
    return scrub_nonfinite(out)


@router.get("/api/aggressive-lab/strategy/{strategy_id}")
def get_aggressive_lab_strategy(strategy_id: str):
    """A single aggressive strategy's realized series + its risk shape.

    Serves Lane 1's data/aggressive_lab/<id>/realized_series.jsonl (append-only proof-chained
    JSONL, one point per line) plus the strategy's risk shape / risk class (resolved from the
    scorecard row + optional sidecar meta.json). Read-only, FAIL-CLOSED: an unknown id or a
    missing/corrupt series returns 200 with an honest empty series (advisory), NEVER a 500.
    A path-traversal attempt in the id is rejected to an empty series (the id is used as a dir name).
    """
    env = _advisory_envelope()
    meta = backtest_meta(
        basis="Lane-1 realized series (forward paper + 2024-2026 backtest) + the strategy's "
              "dominant risk shape",
        period="forward track + backtest stress windows",
    )
    # id hardening: the id becomes a directory name — refuse anything that is not a plain slug so
    # a crafted id can never escape data/aggressive_lab/.
    safe = (strategy_id or "").strip()
    if (not safe) or ("/" in safe) or ("\\" in safe) or (".." in safe) or safe.startswith("."):
        return {
            "id": strategy_id, "model": "aggressive_lab_strategy", **env,
            "available": False, "unavailable_reason": "invalid strategy id",
            "risk_shape": None, "risk_class": None, "scorecard_row": None,
            "n_points": 0, "forward": [], "backtest": [], "series": [], "meta": meta,
        }

    # The series file (read JSONL VERBATIM, fail-CLOSED on corrupt lines).
    series = _read_realized_series(safe)
    forward = [p for p in series if (p.get("phase") or "forward") == "forward"]
    backtest = [p for p in series if p.get("phase") == "backtest"]

    # The strategy's risk shape / class — prefer the scorecard row, then the Lane-1 sidecar meta,
    # then any inline risk_shape on a point. None when truly unknown (never fabricated).
    row = _scorecard_row(safe)
    sidecar = read_state(f"aggressive_lab/{safe}/meta.json", {})
    sidecar = sidecar if isinstance(sidecar, dict) else {}
    inline_shape = next((p.get("risk_shape") for p in series if p.get("risk_shape")), None)
    risk_shape = (row or {}).get("risk_shape") or sidecar.get("risk_shape") or inline_shape
    risk_class = (row or {}).get("risk_class") or sidecar.get("risk_class")

    available = bool(series) or row is not None
    return scrub_nonfinite({
        "id": safe,
        "model": "aggressive_lab_strategy",
        **env,
        "available": available,
        "unavailable_reason": None if available else "no realized series or scorecard row for this id",
        "name": (row or {}).get("name") or sidecar.get("name") or safe,
        "mandate": (row or {}).get("mandate") or sidecar.get("mandate"),
        "risk_shape": risk_shape,
        "risk_class": risk_class,
        "risk_class_label": (row or {}).get("risk_class_label") or sidecar.get("risk_class_label"),
        "scorecard_row": row,           # the honest metrics row (return + risk), verbatim
        "n_points": len(series),
        "n_forward": len(forward),
        "n_backtest": len(backtest),
        "forward": forward,
        "backtest": backtest,
        "series": series,               # full series (both phases), verbatim
        "meta": meta,
    })


def _read_realized_series(strategy_id: str) -> list:
    """Read data/aggressive_lab/<id>/realized_series.jsonl VERBATIM, fail-CLOSED.

    One JSON object per line; a corrupt or non-finite-bearing line is DROPPED (never echoed, never
    crashes). Missing file → empty list. We do not re-verify Lane 1's proof-chain crypto here; the
    surface just serves what Lane 1 wrote.
    """
    path = data_dir() / "aggressive_lab" / strategy_id / "realized_series.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = parse_log_line(line, corrupt_marker=None)
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _scorecard_row(strategy_id: str) -> dict | None:
    """The NORMALIZED scorecard row for one strategy id, or None if absent/corrupt. Matches on the
    Lane-2 ``strategy_id`` (or legacy ``id``)."""
    raw = read_state("aggressive_lab/scorecard.json", {})
    if not isinstance(raw, dict):
        return None
    for row in (raw.get("strategies") or []):
        if isinstance(row, dict) and (row.get("strategy_id") == strategy_id or row.get("id") == strategy_id):
            return _normalize_row(row)
    return None


# ── normalization: map the Lane-2 producer's field names onto the dashboard's stable column names.
#    Lane 2 owns its schema; this surface ADDS aliases (original keys still pass through verbatim) so
#    the dashboard renders without coupling the producer to UI names. No fabrication: a metric the
#    producer didn't emit stays null. ──────────────────────────────────────────────────────────────
def _first_num(*vals):
    for v in vals:
        if isinstance(v, (int, float)):
            return v
    return None


def _normalize_row(row: dict) -> dict:
    out = dict(row)  # pass EVERY original Lane-2 field through verbatim
    out["id"] = row.get("id") or row.get("strategy_id")
    # net return: prefer realized (the honest one), fall back to headline; keep both available.
    out.setdefault("net_return_pct",
                    _first_num(row.get("net_return_pct"), row.get("realized_apy_pct"),
                               row.get("headline_apy_pct")))
    # max drawdown: Lane 2 emits a POSITIVE magnitude `max_dd_pct`; the UI shows a signed loss.
    if not isinstance(out.get("max_drawdown_pct"), (int, float)):
        dd = _first_num(row.get("max_dd_pct"))
        out["max_drawdown_pct"] = (-abs(dd) if dd is not None else None)
    # tail-in-stress: the worst replayed stress drawdown (positive magnitude) → signed loss.
    if not isinstance(out.get("tail_loss_in_stress_pct"), (int, float)):
        tail = row.get("tail") if isinstance(row.get("tail"), dict) else {}
        t = _first_num(tail.get("worst_tail_dd_pct"), tail.get("worst_shape_shock_dd_pct"),
                       tail.get("worst_in_sample_loss_pct"))
        out["tail_loss_in_stress_pct"] = (-abs(t) if t is not None else None)
    return out


def _derive_trustworthy(raw: dict) -> bool:
    """Top-level trustworthy: True only if Lane 2 explicitly said so OR at least one strategy is
    trustworthy. Fail-CLOSED — absent signal → False (a THIN forward track is never 'trustworthy')."""
    if raw.get("trustworthy") is True:
        return True
    n = raw.get("n_trustworthy")
    if isinstance(n, int) and n > 0:
        return True
    return False
