"""
spa_core.strategies.runner — fan one snapshot out across all shadow strategies.

Loads (or initialises) one :class:`VirtualPortfolio` per registered strategy,
advances each by a single step against the current orchestrator snapshot, applies
the uniform risk guard to every strategy's raw weights, persists state, and logs
the step.

CLI::
    python3 -m spa_core.strategies.runner [--verbose]

Stdlib only. Advisory/read-only — execution, feed_health and risk agents are
never imported.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from spa_core.utils.atomic import atomic_save

from .base import apply_risk_policy, tier_map
from .vportfolio import VirtualPortfolio

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SNAPSHOT = _PROJECT_ROOT / "data" / "adapter_orchestrator_status.json"
_DEFAULT_HISTORY = _PROJECT_ROOT / "data" / "orchestrator_runs.json"
_DATA_DIR = _PROJECT_ROOT / "data" / "strategies"
_RUN_LOG = _DATA_DIR / "run_log.json"

#: run_log.json keeps at most this many most-recent step records.
RUN_LOG_MAX = 200


def _load_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}



def _registry():
    # Imported lazily so importing the package never has a hard dependency on
    # every strategy module resolving at import time.
    from . import STRATEGY_REGISTRY

    return STRATEGY_REGISTRY


def run_all_strategies(
    snapshot_path: str | os.PathLike = _DEFAULT_SNAPSHOT,
    history_path: str | os.PathLike = _DEFAULT_HISTORY,
    capital: float = 100_000.0,
) -> dict:
    """Run one shadow step for every registered strategy.

    Returns ``{strategy_name: {"equity": float, "weights": dict,
    "yield_today": float}}``. Each portfolio's updated state is persisted to
    ``data/strategies/{name}.json`` and the step is appended to
    ``data/strategies/run_log.json`` (ring-buffered to :data:`RUN_LOG_MAX`).
    """
    snapshot = _load_json(Path(snapshot_path))
    history_doc = _load_json(Path(history_path))
    history = history_doc.get("runs", []) if isinstance(history_doc, dict) else []
    ts = snapshot.get("run_ts") or snapshot.get("generated_at") or _fallback_ts(history)

    caps = tier_map(snapshot)
    state = {"history": history, "history_path": str(history_path)}

    results: dict[str, dict] = {}
    for strat in _registry():
        vp = VirtualPortfolio.load(strat.name)
        if vp.initial_capital != capital and not vp.equity_curve:
            vp = VirtualPortfolio(name=strat.name, capital=capital)

        raw = strat.target_weights(snapshot, state)
        # Single external risk guard, applied uniformly to every strategy.
        weights = apply_risk_policy(raw, caps)
        yield_today = vp.step(snapshot, weights, ts)
        vp.save()

        results[strat.name] = {
            "equity": round(vp.equity, 6),
            "weights": {k: round(v, 6) for k, v in weights.items()},
            "yield_today": round(yield_today, 6),
        }

    _append_run_log(ts, results)
    return results


def _fallback_ts(history: list) -> str:
    for run in reversed(history or []):
        if isinstance(run, dict) and run.get("run_ts"):
            return str(run["run_ts"])
    return "1970-01-01T00:00:00+00:00"


def _append_run_log(ts: str, results: dict) -> None:
    doc = _load_json(_RUN_LOG)
    entries = doc.get("entries", []) if isinstance(doc, dict) else []
    entries.append(
        {
            "ts": ts,
            "strategies": {
                name: {"equity": r["equity"], "yield_today": r["yield_today"]}
                for name, r in results.items()
            },
        }
    )
    entries = entries[-RUN_LOG_MAX:]
    atomic_save({"entries": entries, "max_entries": RUN_LOG_MAX}, str(_RUN_LOG))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run all shadow strategies one step.")
    parser.add_argument("--snapshot", default=str(_DEFAULT_SNAPSHOT))
    parser.add_argument("--history", default=str(_DEFAULT_HISTORY))
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    results = run_all_strategies(args.snapshot, args.history, args.capital)

    n = len(results)
    deployed = sum(1 for r in results.values() if r["weights"])
    print(f"SHADOW {n} strategies | {deployed} deployed | step recorded")
    if args.verbose:
        for name, r in results.items():
            wstr = ", ".join(f"{k}={v:.3f}" for k, v in sorted(r["weights"].items()))
            print(
                f"  {name:18s} equity=${r['equity']:>12,.2f}  "
                f"yield_today=${r['yield_today']:>8.4f}  [{wstr or 'cash'}]"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
