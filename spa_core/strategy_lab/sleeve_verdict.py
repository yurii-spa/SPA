"""
spa_core/strategy_lab/sleeve_verdict.py — HONEST per-sleeve verdicts over the shared backtest harness.

WHY THIS EXISTS (Proof-of-Risk C2): the backtest harness (backtest.run_backtest) runs EVERY sleeve —
the rates-desk-adjacent ETH/BTC sleeves (variant_n/d, eth_lst_neutral/staking, btc_neutral/
btc_lending_sleeve) and the baselines — through the SAME snapshots, and FAIL-CLOSES a sleeve to a
flat equity the instant a required datapoint is missing (the harness contract). That is correct, but
it CONFLATES two very different outcomes into the same `apy=0 / beats_floor=False` row:

  • the sleeve actually LOST (a real risk kill fired: drawdown / depeg / funding-kill), versus
  • the sleeve could NOT BE JUDGED at all (the cached feed had no funding / price on the window, so
    the sleeve fail-closed on tick 1 and never traded a single real day).

Presenting the second as "BELOW_FLOOR" would be a FABRICATED verdict — the harness never let the
sleeve run. This module classifies each sleeve's harness result into an HONEST verdict that keeps the
two apart, so "promote the BTC/ETH sleeves with honest verdicts" means exactly that: a beats-floor GO,
a genuine risk-kill NO-GO, or an explicit INSUFFICIENT_DATA — never a number the data did not earn.

VERDICTS (deterministic, fail-CLOSED):
  INSUFFICIENT_DATA  — the sleeve was killed by a `fail-closed:` data-gap (missing/invalid feed
                       datapoint) and traded fewer than MIN_REALIZED_DAYS real days. NOT a strategy
                       loss — the data was not there to judge it. (The dominant offline outcome for
                       the neutral sleeves: the cached funding feed does not cover the window start.)
  RISK_KILL          — a GENUINE kill rule fired (drawdown stop / depeg / funding-kill / fail-closed
                       AFTER >= MIN_REALIZED_DAYS of real trading). The sleeve ran, then its own
                       safety rule unwound it. An honest NO-GO with the kill reason recorded.
  BEATS_FLOOR        — the sleeve survived and its net APY beat the RWA floor (risk-adjusted intent;
                       the harness already computes beats_rwa_floor against the live floor).
  BELOW_FLOOR        — the sleeve survived but did NOT beat the floor. Honest NO-GO.

Each verdict carries the realized-day count + the kill reason so day-30 lands a real, auditable
artifact (not an apy=0 mirage). is_advisory is asserted for EVERY sleeve (a non-advisory sleeve in
this advisory research surface is a bug → raises).

stdlib only, deterministic, PURE (operates on the harness result dict, no IO unless write=True),
fail-CLOSED, LLM FORBIDDEN. Advisory: reports verdicts, never moves capital.

Run:  python3 -m spa_core.strategy_lab.sleeve_verdict
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
OUT_FILE = DATA_DIR / "strategy_lab" / "sleeve_verdicts.json"

# The sleeves this Proof-of-Risk workstream promotes through the harness (the rates-desk-adjacent
# ETH/BTC sleeves). The baselines (engine_a/b/c, rwa_floor) are scored too for context but are NOT
# the promotion targets.
PROMOTE_SLEEVE_IDS = (
    "eth_lst_neutral", "eth_lst_staking", "btc_neutral", "btc_lending_sleeve",
    "variant_n", "variant_d",
)

# A sleeve must have traded at least this many REAL (non-fail-closed) days before a kill is treated as
# a genuine RISK_KILL rather than a data-gap. Below this, a kill is INSUFFICIENT_DATA (the sleeve never
# really ran). MIRRORS forward_analytics.MIN_POINTS_FOR_RATIO intent (a handful of days is not a trade
# record). Conservative: 5 real trading days.
MIN_REALIZED_DAYS = 5

VERDICT_INSUFFICIENT = "INSUFFICIENT_DATA"
VERDICT_RISK_KILL = "RISK_KILL"
VERDICT_BEATS = "BEATS_FLOOR"
VERDICT_BELOW = "BELOW_FLOOR"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_data_gap_kill(kill: Optional[dict]) -> bool:
    """True when the kill was a FAIL-CLOSED data-gap (a missing/invalid feed datapoint), not a real
    risk rule. The harness stamps these with a 'fail-closed' reason prefix (both the harness-boundary
    guard and the sleeve's own require()-fail path use that exact prefix)."""
    if not isinstance(kill, dict):
        return False
    reason = str(kill.get("reason", "")).lower()
    return "fail-closed" in reason or "fail closed" in reason or "missing/invalid" in reason


def _realized_days(strat_result: dict) -> int:
    """Number of REAL trading days the sleeve had before being killed (or the whole series if it
    survived). The harness freezes equity at the kill day, so the equity series length up to the kill
    is the realized-day proxy. We use n_snapshots-until-kill when a kill date is present, else the full
    sampled series length. Deterministic; never negative."""
    kill = strat_result.get("kill")
    series = strat_result.get("equity_series") or []
    n = len(series)
    if isinstance(kill, dict) and kill.get("date"):
        # the sampled series is downsampled, so it is only a proxy; a data-gap kill on tick 1 yields a
        # tiny realized count regardless. We treat the equity series length as the upper bound and, for
        # a data-gap kill, additionally require the equity to have actually MOVED off the start to count
        # a day as "realized" (a flat fail-closed hold did not trade).
        first = strat_result.get("equity_first")
        last_eq = kill.get("equity_at_kill")
        if first is not None and last_eq is not None and abs(float(last_eq) - float(first)) < 1e-9:
            return 0  # killed at the start value with no movement → never really traded
    return max(0, n)


def classify_sleeve(strat_result: dict) -> dict:
    """Classify ONE harness per-strategy result dict into an HONEST verdict. PURE / fail-CLOSED.

    The harness result shape (backtest.run_backtest -> result['strategies'][id]):
      {id, name, mandate, is_advisory, is_benchmark, metrics:{net_apy_pct, max_drawdown_pct,
       beats_rwa_floor, ...}, equity_series, equity_first, equity_last, kill: {date,reason,...}|None}

    Verdict logic (deterministic, in order):
      1. a data-gap fail-closed kill with < MIN_REALIZED_DAYS real days → INSUFFICIENT_DATA (honest:
         the data was not there — NOT a strategy loss).
      2. any kill that is NOT an early data-gap → RISK_KILL (a real safety rule fired; honest NO-GO).
      3. survivor: beats_rwa_floor True → BEATS_FLOOR; else BELOW_FLOOR.
    """
    metrics = strat_result.get("metrics") or {}
    kill = strat_result.get("kill")
    realized = _realized_days(strat_result)
    data_gap = _is_data_gap_kill(kill)

    if kill is not None:
        if data_gap and realized < MIN_REALIZED_DAYS:
            verdict = VERDICT_INSUFFICIENT
            note = ("fail-closed on a missing/invalid feed datapoint before trading a real record — "
                    "the harness could not judge this sleeve on the available (offline-cached) data. "
                    "NOT a strategy loss.")
        else:
            verdict = VERDICT_RISK_KILL
            note = ("a real kill rule fired (drawdown / depeg / funding-kill) after the sleeve traded "
                    "a record — honest NO-GO: the sleeve's own safety rule unwound it.")
    else:
        beats = bool(metrics.get("beats_rwa_floor"))
        verdict = VERDICT_BEATS if beats else VERDICT_BELOW
        note = ("survived the window and beat the RWA floor → GO" if beats else
                "survived the window but did NOT beat the RWA floor → NO-GO")

    return {
        "id": strat_result.get("id"),
        "name": strat_result.get("name"),
        "mandate": strat_result.get("mandate"),
        "is_advisory": bool(strat_result.get("is_advisory", True)),
        "verdict": verdict,
        "net_apy_pct": metrics.get("net_apy_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "beats_rwa_floor": metrics.get("beats_rwa_floor"),
        "realized_days_proxy": realized,
        "killed": kill is not None,
        "kill_reason": (kill or {}).get("reason"),
        "data_gap_kill": data_gap,
        "note": note,
    }


def build_verdicts(backtest_result: dict, *, now_iso: Optional[str] = None,
                   write: bool = False, out_path: Optional[Path] = None) -> dict:
    """Build the honest sleeve-verdict scorecard from a harness result dict.

    fail-CLOSED ADVISORY GUARD: EVERY promoted sleeve MUST be is_advisory=True (the advisory research
    mandate). A non-advisory promoted sleeve is a contract violation → RAISES (never silently passes a
    live-capable sleeve through the advisory surface).

    Returns {generated_at, n_sleeves, verdicts:[...], counts:{verdict->n}, advisory_all_true}. Writes
    data/strategy_lab/sleeve_verdicts.json atomically when write=True.
    """
    strategies = (backtest_result or {}).get("strategies") or {}
    verdicts: List[dict] = []
    for sid in PROMOTE_SLEEVE_IDS:
        sr = strategies.get(sid)
        if sr is None:
            continue  # a sleeve absent from the harness result → simply not scored (never fabricated)
        # ADVISORY ENFORCEMENT (fail-CLOSED): a promoted sleeve must be advisory.
        if not bool(sr.get("is_advisory", True)):
            raise ValueError(
                f"sleeve_verdict: promoted sleeve {sid!r} is_advisory=False — a live-capable sleeve "
                "must NOT be promoted through the advisory research surface (fail-closed).")
        verdicts.append(classify_sleeve(sr))

    counts: Dict[str, int] = {}
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1

    out = {
        "generated_at": now_iso if now_iso is not None else _utc_now_iso(),
        "model": "strategy_lab_sleeve_verdict",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "min_realized_days": MIN_REALIZED_DAYS,
        "rwa_floor_apy_pct": (backtest_result.get("manifest") or {}).get("rwa_floor_apy_pct"),
        "window_realized": (backtest_result.get("manifest") or {}).get("window_realized"),
        "n_sleeves": len(verdicts),
        "counts": dict(sorted(counts.items())),
        "advisory_all_true": all(v["is_advisory"] for v in verdicts),
        "verdicts": verdicts,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        path = out_path or OUT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(out, str(path))
    return out


def main() -> int:
    import json
    import socket
    from spa_core.strategy_lab import backtest as bt
    socket.setdefaulttimeout(20)
    result = bt.run_backtest()
    out = build_verdicts(result, write=True)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
