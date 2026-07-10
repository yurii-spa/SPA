"""
spa_core/strategy_lab/aggressive_lab/scorecard.py — the multi-metric tournament SCORECARD.

This is the honest tournament ranking for the Aggressive Lab: NOT a single yield-sorted leaderboard
(that would mislead the owner into the exact trap the desk exists to avoid), but a multi-metric
HONEST scorecard the owner sorts/picks from — with the RISK surfaced next to the RETURN, always.

Per strategy it shows:
  • net realized return (forward + backtest),
  • risk-adjusted (Sharpe / Sortino / Calmar — THIN-aware, trustworthy-gated),
  • max realized drawdown,
  • THE TAIL — worst loss-in-stress + worst stressed drawdown across the canonical windows
    (the −X% that comes WITH the yield), and time-to-recover,
  • the RISK CLASS (A=alpha / B=beta / C=risk-compensation / D=incentive),
  • an honest VERDICT label (see _verdict below).

THE TRUSTWORTHY GATE (reused WS1.4 fail-closed logic): a strategy on thin/degenerate data is flagged
trustworthy=False / INSUFFICIENT_DATA on its ratios — NEVER presented as a real number. The existing
tournament's degenerate-Sharpe flaw does not recur.

GUARDRAIL stamps: every entry + the doc carry is_advisory / outside_riskpolicy / owner_selectable /
separate_from_golive_track. This layer NEVER touches the go-live track or live allocation.

stdlib-only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN.

Run (offline, on the fixture or live Lane-1 data):
    python3 -m spa_core.strategy_lab.aggressive_lab.scorecard
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.strategy_lab.aggressive_lab import (
    AGGRESSIVE_LAB_DIR,
    RISK_CLASS_LABEL,
    SCORECARD_FILE,
    RiskClass,
)
from spa_core.strategy_lab.aggressive_lab import loader as ld
from spa_core.strategy_lab.aggressive_lab import risk_metrics as rm
from spa_core.strategy_lab.aggressive_lab import tail_overlay as tov
from spa_core.strategy_lab.aggressive_lab import fixtures as fx

INSUFFICIENT = rm.INSUFFICIENT

# A tail this deep (worst stressed/realized drawdown %) is flagged as a SEVERE tail regardless of the
# headline yield — the whole point is to stop a fat APY from burying a catastrophic drawdown. Mirrors
# the lab's promotion drawdown band (15%): a strategy whose stress tail blows past it is SEVERE_TAIL.
SEVERE_TAIL_DD_PCT = 15.0


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _verdict(
    *,
    risk_class: str,
    trustworthy: bool,
    worst_tail_dd_pct: float,
    backtest_status: str,
) -> str:
    """The honest verdict label. The ORDER matters — the tail and the class are surfaced BEFORE any
    'good return' read, so a fat yield can never outrank a catastrophic tail in the label itself.

      INSUFFICIENT_DATA   — neither track is trustworthy yet (thin / locked-vol / broken). The owner
                            sees a return + tail but NO risk-adjusted verdict (honest, not a PASS).
      SEVERE_TAIL         — the worst stress drawdown blows past the band → eyes-open DANGER, whatever
                            the headline. The owner can still PICK it, but the label does not hide it.
      DIRECTIONAL_BETA    — RiskClass B: this is market beta dressed as yield, not alpha (flagged).
      INCENTIVE_DECAY     — RiskClass D: emissions/points — not a durable edge (flagged).
      RISK_COMPENSATION   — RiskClass C with a bounded tail: the yield is a real risk premium; pickable
                            with eyes open (the desk's normal-refusal zone, now measured).
      ALPHA_CANDIDATE     — RiskClass A with a bounded tail + a trustworthy risk-adjusted record.
    """
    if not trustworthy:
        return "INSUFFICIENT_DATA"
    if worst_tail_dd_pct >= SEVERE_TAIL_DD_PCT:
        return "SEVERE_TAIL"
    if risk_class == RiskClass.B_BETA.value:
        return "DIRECTIONAL_BETA"
    if risk_class == RiskClass.D_INCENTIVE.value:
        return "INCENTIVE_DECAY"
    if risk_class == RiskClass.A_ALPHA.value:
        return "ALPHA_CANDIDATE"
    return "RISK_COMPENSATION"


def score_strategy(s: ld.LoadedStrategy) -> dict:
    """The full honest scorecard ENTRY for ONE loaded strategy: return + risk + tail + class + verdict.

    fail-CLOSED throughout: thin/broken tracks → INSUFFICIENT_DATA ratios (never a fabricated number);
    the tail overlay is computed on the BACKTEST track (the deep one carrying the windows in-sample),
    falling back to the forward track if there is no backtest (shape-shock still applies)."""
    fwd_m = rm.compute_track_metrics(s.forward.series, name=f"{s.strategy_id}/forward")
    bt_m = rm.compute_track_metrics(s.backtest.series, name=f"{s.strategy_id}/backtest")

    # tail overlay on the deepest track that carries the stress windows: the backtest, else forward.
    tail_doc = (s.backtest.series if s.backtest.n_points >= 2 else s.forward.series)
    tail = tov.build_tail_overlay(tail_doc, risk_shape=s.risk_shape, name=s.strategy_id)

    # the trustworthy verdict rests on the BACKTEST risk-adjusted record when present (deep enough for
    # a stress-window-bearing Sharpe); else the forward (which is usually THIN → INSUFFICIENT_DATA).
    primary = bt_m if bt_m["status"] == "OK" else (fwd_m if fwd_m["status"] == "OK" else bt_m
                                                   if s.backtest.n_points >= 2 else fwd_m)
    trustworthy = bool(primary["trustworthy"])

    verdict = _verdict(
        risk_class=s.risk_class,
        trustworthy=trustworthy,
        worst_tail_dd_pct=tail["worst_tail_dd_pct"],
        backtest_status=bt_m["status"],
    )

    return {
        "strategy_id": s.strategy_id,
        "risk_class": s.risk_class,
        "risk_class_label": RISK_CLASS_LABEL.get(s.risk_class, "unknown"),
        "risk_shape": s.risk_shape,
        "headline_apy_pct": s.headline_apy_pct,
        "note": s.note,
        # ── RETURN ──
        "forward": fwd_m,
        "backtest": bt_m,
        # ── RISK-ADJUSTED (the trustworthy, primary read) ──
        "trustworthy": trustworthy,
        "sharpe": primary["sharpe"],
        "sortino": primary["sortino"],
        "calmar": primary["calmar"],
        "max_dd_pct": primary["max_dd_pct"],
        "realized_apy_pct": primary["realized_apy_pct"],
        # Backlog #5: honesty-safe customer-facing fields — `realized_apy_display` is the annualized APY
        # ONLY when the window is long enough (>= MIN_DAYS_FOR_APY), else the INSUFFICIENT_HISTORY_FOR_APY
        # sentinel; `period_return_pct` is the honest cumulative return over the window. A /packages card
        # must render `realized_apy_display` (never the raw over-annualized `realized_apy_pct`) so a thin
        # forward track can never surface a 200%+ artifact as a realized APY.
        "realized_apy_display": primary.get("realized_apy_display"),
        "period_return_pct": primary.get("period_return_pct"),
        "apy_trustworthy": primary.get("apy_trustworthy", False),
        "ratio_source": primary["name"],
        # ── THE TAIL (surfaced next to the yield, always) ──
        "tail": {
            "worst_tail_dd_pct": tail["worst_tail_dd_pct"],
            "worst_in_sample_dd_pct": tail["worst_in_sample_dd_pct"],
            "worst_in_sample_loss_pct": tail["worst_in_sample_loss_pct"],
            "worst_shape_shock_dd_pct": tail["worst_shape_shock_dd_pct"],
            "max_time_to_recover_days": tail["max_time_to_recover_days"],
            "windows": tail["windows"],
        },
        # ── the honest verdict + guardrail stamps ──
        "verdict": verdict,
        "is_advisory": True,
        "outside_riskpolicy": True,
        "owner_selectable": True,
        "n_malformed_lines": s.n_malformed_lines,
    }


def _sort_keys(entries: List[dict]) -> Dict[str, List[str]]:
    """A few PRE-COMPUTED honest sort orders the owner (or Lane 3) can offer. Deliberately MULTIPLE —
    there is no single 'best' order (that is the whole point). Ties broken by strategy_id for
    determinism. A non-numeric (INSUFFICIENT_DATA) ratio sorts LAST in a risk-adjusted order."""
    def _num(v: Any, default: float) -> float:
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default

    by_return = sorted(entries, key=lambda e: (-_num(e["realized_apy_pct"], -1e18), e["strategy_id"]))
    # risk-adjusted: trustworthy Sharpe desc, INSUFFICIENT_DATA last
    by_sharpe = sorted(
        entries,
        key=lambda e: (0 if isinstance(e["sharpe"], (int, float)) else 1,
                       -_num(e["sharpe"], -1e18), e["strategy_id"]))
    # smallest tail first (the SAFEST eyes-open pick) — worst_tail_dd ascending
    by_tail = sorted(entries, key=lambda e: (_num(e["tail"]["worst_tail_dd_pct"], 1e18),
                                             e["strategy_id"]))
    return {
        "by_return_desc": [e["strategy_id"] for e in by_return],
        "by_sharpe_desc": [e["strategy_id"] for e in by_sharpe],
        "by_tail_asc": [e["strategy_id"] for e in by_tail],
    }


def build_scorecard(
    *,
    data_dir: Optional[Path] = None,
    use_fixture_if_empty: bool = True,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Build the full Aggressive-Lab honest scorecard over the roster.

    Reads Lane 1's realized series from ``data_dir`` (default: the live aggressive-lab dir). If no
    strategies are found AND use_fixture_if_empty, materializes the documented fixture into a temp
    view in-memory (it does NOT pollute live data unless the caller's data_dir IS live AND empty —
    in which case the fixture is loaded read-only via the loader against a fresh tmp materialization).

    fail-CLOSED throughout. Writes ``data/aggressive_lab/scorecard.json`` atomically (unless write=
    False). ``now_iso`` is injectable for byte-stable tests (the only wall-clock field)."""
    root = Path(data_dir) if data_dir is not None else AGGRESSIVE_LAB_DIR
    now = now_iso if now_iso is not None else _utc_now_iso()

    loaded = ld.load_all(data_dir=root)
    fixture_used = False
    if not loaded and use_fixture_if_empty:
        # offline fallback: materialize the fixture into a sibling tmp dir and load from there, so the
        # ranking is demonstrable even before Lane 1 ships its files (NEVER writes into live data).
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="aggr_lab_fixture_"))
        fx.materialize(tmp)
        loaded = ld.load_all(data_dir=tmp)
        fixture_used = True

    entries = [score_strategy(loaded[sid]) for sid in sorted(loaded.keys())]

    n_trustworthy = sum(1 for e in entries if e["trustworthy"])
    n_severe_tail = sum(1 for e in entries if e["verdict"] == "SEVERE_TAIL")
    n_insufficient = sum(1 for e in entries if e["verdict"] == "INSUFFICIENT_DATA")

    out = {
        "generated_at": now,
        "model": "aggressive_lab_scorecard",
        "schema_version": "1.0",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "outside_riskpolicy": True,
        "owner_selectable": True,
        "separate_from_golive_track": True,
        "fixture_used": fixture_used,
        "min_points_for_ratio": rm.MIN_POINTS,
        "severe_tail_dd_pct": SEVERE_TAIL_DD_PCT,
        "n_strategies": len(entries),
        "n_trustworthy": n_trustworthy,
        "n_severe_tail": n_severe_tail,
        "n_insufficient_data": n_insufficient,
        "risk_class_legend": dict(RISK_CLASS_LABEL),
        "sort_orders": _sort_keys(entries) if entries else {},
        "strategies": entries,
        "note": (
            "Aggressive Strategy Paper Lab — HONEST multi-metric scorecard. These are the 10-15% "
            "strategies the desk normally REFUSES, paper-tested so the owner can choose WITH EYES "
            "OPEN. The headline yield is RISK-COMPENSATION: the TAIL (worst stress drawdown / "
            "loss-in-stress, surfaced next to the yield) is what it pays for. NOT a yield-sorted "
            "leaderboard — a multi-metric scorecard the owner sorts/picks. Thin/degenerate tracks "
            "read INSUFFICIENT_DATA, never a fabricated Sharpe. ADVISORY / OUTSIDE_RISKPOLICY — "
            "never touches the go-live track or live allocation."),
    }
    if write:
        root.mkdir(parents=True, exist_ok=True)
        atomic_save(out, str(root / SCORECARD_FILE.name))
    return out


# ── human-readable scorecard (return AND tail, side by side) ─────────────────────────────────────
def render_table(doc: dict) -> str:
    """A compact text scorecard surfacing RETURN and TAIL together. Used by the smoke / CLI."""
    lines: List[str] = []
    lines.append("Aggressive Strategy Paper Lab — HONEST scorecard "
                 "(ADVISORY / OUTSIDE_RISKPOLICY / owner-selectable)")
    lines.append(f"floor for a trustworthy ratio: {doc['min_points_for_ratio']} pts · "
                 f"severe-tail band: {doc['severe_tail_dd_pct']}%")
    if doc.get("fixture_used"):
        lines.append("(fixture data — Lane 1 realized series not present yet)")
    lines.append("")
    hdr = (f"{'strategy':16s} {'cls':>3s} {'shape':>14s} {'head%':>6s} {'realAPY%':>9s} "
           f"{'Sharpe':>8s} {'Calmar':>7s} {'maxDD%':>7s} {'TAIL_DD%':>9s} {'TTR':>12s} {'verdict':>18s}")
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for e in doc["strategies"]:
        sharpe = e["sharpe"] if isinstance(e["sharpe"], (int, float)) else "n/a"
        calmar = e["calmar"] if isinstance(e["calmar"], (int, float)) else "n/a"
        rapy = e["realized_apy_pct"] if isinstance(e["realized_apy_pct"], (int, float)) else "n/a"
        mdd = e["max_dd_pct"] if isinstance(e["max_dd_pct"], (int, float)) else "n/a"
        ttr = e["tail"]["max_time_to_recover_days"]
        head = e["headline_apy_pct"] if e["headline_apy_pct"] is not None else "?"
        lines.append(
            f"{e['strategy_id']:16s} {e['risk_class']:>3s} {e['risk_shape']:>14s} "
            f"{str(head):>6s} {str(rapy):>9s} {str(sharpe):>8s} {str(calmar):>7s} "
            f"{str(mdd):>7s} {e['tail']['worst_tail_dd_pct']:>9.2f} {str(ttr):>12s} "
            f"{e['verdict']:>18s}")
    lines.append("")
    lines.append("Sort orders available: " + ", ".join(doc.get("sort_orders", {}).keys()))
    return "\n".join(lines)


def main() -> int:
    import json
    doc = build_scorecard(write=True)
    print(render_table(doc))
    print()
    print(json.dumps({"n_strategies": doc["n_strategies"], "n_trustworthy": doc["n_trustworthy"],
                      "n_severe_tail": doc["n_severe_tail"],
                      "n_insufficient_data": doc["n_insufficient_data"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
