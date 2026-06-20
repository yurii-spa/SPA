"""
shadow_tracker — MP-106: advance all shadow strategies S0–S5 by one day.

``run_shadow_cycle`` is invoked from the real paper-trading cycle
(``cycle_runner.py``, fail-safe) AFTER the real track is persisted. It:

1. computes each strategy's target weights via ``compute_shadow_allocation``;
2. accrues one day of yield: ``daily_pnl = equity × Σ(wᵢ·apyᵢ) / 100 / 365``
   (the cash remainder yields 0%);
3. atomically rewrites ``data/shadow_portfolio.json``.

Idempotent per UTC day: a re-run on the same date recomputes the day from each
strategy's ``prev_equity`` instead of compounding twice (same convention as
the real equity curve in cycle_runner).

STRICTLY ADVISORY — never touches trades.json / equity_curve_daily.json /
the RiskPolicy gate. Stdlib only, no network.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from .shadow_allocator import _normalize_adapters, compute_shadow_allocation
from .shadow_registry import STRATEGIES
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.shadow_tracker")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SHADOW_FILENAME = "shadow_portfolio.json"
INITIAL_CAPITAL = 100_000.0
MAX_HISTORY_POINTS = 365  # ring-buffer of daily equity snapshots


def _atomic_write_json(path: Path, obj) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("%s unreadable (%s) — starting fresh", path.name, exc)
        return default


def run_shadow_cycle(
    adapters: list[dict],
    real_allocation: dict[str, float] | None,
    equity: float = 100_000.0,
    *,
    data_dir: str | os.PathLike | None = None,
    date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Advance every shadow strategy by one day and persist the result.

    Parameters
    ----------
    adapters        : live adapter snapshot (orchestrator or spec key form).
    real_allocation : the real allocator's effective positions, pool → USD
                      (S5 "CurrentSPA" mirrors it).
    equity          : real-track total equity in USD — S5's weight denominator
                      (preserves the real strategy's structural cash). New
                      shadow portfolios always start at ``INITIAL_CAPITAL``.
    data_dir / date / now : injectable for deterministic tests.

    Returns the document written to ``data/shadow_portfolio.json``::

        {"date": "...", "strategies": {"S0": {"equity": ..., "daily_pnl": ...},
         ...}, "history": [...]}
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now_dt = now or datetime.now(timezone.utc)
    today = date or now_dt.strftime("%Y-%m-%d")

    apy_map = {p["id"]: p["apy"] for p in _normalize_adapters(adapters)}

    prev_doc = _read_json(ddir / SHADOW_FILENAME, {})
    prev_strategies = (
        prev_doc.get("strategies", {}) if isinstance(prev_doc, dict) else {}
    )
    same_day = isinstance(prev_doc, dict) and prev_doc.get("date") == today

    strategies_out: dict[str, dict] = {}
    for sid, meta in STRATEGIES.items():
        prev = prev_strategies.get(sid) if isinstance(prev_strategies, dict) else None
        prev = prev if isinstance(prev, dict) else {}
        if same_day:
            # Re-run on the same date → recompute from the day's opening
            # equity instead of compounding today's yield twice.
            base = float(prev.get("prev_equity", prev.get("equity", INITIAL_CAPITAL)))
        else:
            base = float(prev.get("equity", INITIAL_CAPITAL))

        weights = compute_shadow_allocation(
            sid, adapters, real_allocation, real_equity=equity
        )
        weighted_apy = sum(w * apy_map.get(p, 0.0) for p, w in weights.items())
        daily_pnl = base * weighted_apy / 100.0 / 365.0
        new_equity = base + daily_pnl

        strategies_out[sid] = {
            "name": meta["name"],
            "equity": round(new_equity, 2),
            "daily_pnl": round(daily_pnl, 4),
            "prev_equity": round(base, 2),
            "weighted_apy_pct": round(weighted_apy, 4),
            "total_return_pct": round(
                (new_equity / INITIAL_CAPITAL - 1.0) * 100.0, 4
            ),
            "weights": {p: round(w, 6) for p, w in sorted(weights.items())},
            "cash_pct": round(max(0.0, 1.0 - sum(weights.values())) * 100.0, 2),
        }

    # Daily equity history (ring-buffer): one compact row per date.
    history = list(prev_doc.get("history") or []) if isinstance(prev_doc, dict) else []
    if history and isinstance(history[-1], dict) and history[-1].get("date") == today:
        history = history[:-1]
    history.append(
        {"date": today, **{sid: strategies_out[sid]["equity"] for sid in STRATEGIES}}
    )
    history = history[-MAX_HISTORY_POINTS:]

    doc = {
        "date": today,
        "generated_at": now_dt.isoformat(),
        "source": "shadow_tracker",
        "advisory_only": True,
        "initial_capital": INITIAL_CAPITAL,
        "real_equity_usd": round(float(equity), 2),
        "strategies": strategies_out,
        "history": history,
    }
    _atomic_write_json(ddir / SHADOW_FILENAME, doc)
    return doc
