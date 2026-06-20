"""
spa_core/reporting/strategy_summary.py

Read-only analytics module: consumes data/tournament_ranking.json and
data/adapter_status.json, emits data/strategy_summary.json (atomic write).

Rules enforced:
  - Only Python stdlib — no external dependencies.
  - Atomic write only: tmp-file + os.replace.
  - No LLM calls, no execution-domain imports.
  - Exit code 0 always (errors → empty / safe defaults).

CLI:
  python3 -m spa_core.reporting.strategy_summary          # write summary
  python3 -m spa_core.reporting.strategy_summary --check  # compute + print, no write
"""

import json
import os
import sys
from datetime import date

from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DATA_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "..", "data"))
_GO_LIVE_DATE = date(2026, 8, 1)   # ADR-002 go-live target

# Top-level keys in adapter_status.json that are *not* adapter records
# (they are metadata, duplicate summaries, or monitoring config).
_ADAPTER_STATUS_META_KEYS = frozenset({
    "generated_at",
    "schema_version",
    "execution_mode",
    "live_apy_enabled",
    "mev_protection",
    "adapters",           # the array itself
    # duplicate sub-summaries written by execution domain — skip
    "morpho_steakhouse",
    "compound_v3",
    "aave_arbitrum",
    "pendle_pt",
    "spark_susds",
    "fluid_fusdc",
    "base_gas_monitor",
})

# APY thresholds for milestones L1 / L2 / L3
_MILESTONE_THRESHOLDS = [
    ("L1", 5.0, "realized"),   # any realized APY ≥ 5 %
    ("L2", 10.0, "realized"),  # any realized APY ≥ 10 %
    ("L3", 15.0, "any"),       # any target or realized APY ≥ 15 %
]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    """Load JSON from *path*. Returns empty dict on missing file or bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}



# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------

def _get_leading_strategy(strategies: list) -> dict:
    """Return compact info for the rank-1 strategy.

    Returns ``{}`` if no rank-1 entry found.
    """
    for s in strategies:
        if s.get("rank") == 1:
            raw_id = s.get("strategy_id") or s.get("id", "")
            return {
                "id": raw_id.lower().replace("-", "_"),
                "apy": s.get("apy_realized") if s.get("apy_realized") is not None
                       else s.get("apy_target"),
                "sharpe": s.get("sharpe"),
            }
    return {}


def _analyze_adapters(adapter_data: dict) -> tuple:
    """Parse adapter_status.json and return (registry_count, active_count, suspended_list).

    Counting strategy:
      1. Every entry in the ``adapters`` list is one adapter.
      2. Every top-level dict key that is *not* in ``_ADAPTER_STATUS_META_KEYS``
         and whose value is a dict containing an ``adapter_id``, ``protocol_id``,
         or ``protocol_key`` key is counted as an additional adapter (de-duplicated
         against the adapters-list by protocol key).
    """
    suspended: list = []
    seen_keys: set = set()

    # --- adapters list ---
    adapters_list = adapter_data.get("adapters", [])
    for entry in adapters_list:
        proto_key = (
            entry.get("protocol_key")
            or entry.get("adapter_id")
            or entry.get("protocol_id")
            or ""
        )
        seen_keys.add(proto_key)
        if entry.get("status") == "suspended":
            suspended.append(proto_key)

    total = len(adapters_list)

    # --- additional top-level adapter entries ---
    for key, val in adapter_data.items():
        if key in _ADAPTER_STATUS_META_KEYS or not isinstance(val, dict):
            continue
        proto_key = (
            val.get("adapter_id")
            or val.get("protocol_id")
            or val.get("protocol_key")
        )
        if proto_key is None:
            # Try the dict key itself as identifier if it looks like an adapter
            if any(k in val for k in ("apy_pct", "apy", "tier", "chain", "status")):
                proto_key = key
            else:
                continue
        if proto_key in seen_keys:
            continue
        seen_keys.add(proto_key)
        total += 1
        if val.get("status") == "suspended":
            suspended.append(proto_key)

    active = total - len(suspended)
    return total, active, suspended


def _compute_milestones(strategies: list) -> list:
    """Derive milestone labels from strategy APY data.

    L1 — at least one strategy has realized APY ≥ 5 %
    L2 — at least one strategy has realized APY ≥ 10 %
    L3 — at least one strategy has target *or* realized APY ≥ 15 %
    """
    realized_apys = [
        s["apy_realized"]
        for s in strategies
        if s.get("apy_realized") is not None
    ]
    all_apys = realized_apys + [
        s["apy_target"]
        for s in strategies
        if s.get("apy_target") is not None
    ]

    milestones = []
    for label, threshold, pool in _MILESTONE_THRESHOLDS:
        source = realized_apys if pool == "realized" else all_apys
        if any(a >= threshold for a in source):
            milestones.append(label)
    return milestones


def _days_to_go_live(today: date = None) -> int:
    """Return days from *today* to ``_GO_LIVE_DATE``; 0 if already past."""
    today = today or date.today()
    return max(0, (_GO_LIVE_DATE - today).days)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_summary(
    data_dir: str = None,
    output_path: str = None,
    today: date = None,
) -> dict:
    """Read ranking + adapter files, compute summary, write atomically.

    Parameters
    ----------
    data_dir:    Directory containing tournament_ranking.json and
                 adapter_status.json.  Defaults to ``<repo>/data/``.
    output_path: Destination for strategy_summary.json.
                 Defaults to ``<data_dir>/strategy_summary.json``.
    today:       Reference date for ``days_to_go_live`` (defaults to
                 ``date.today()``; injectable for tests).

    Returns
    -------
    dict — the summary that was written to disk.
    """
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    if output_path is None:
        output_path = os.path.join(data_dir, "strategy_summary.json")

    ranking_data = _load_json(os.path.join(data_dir, "tournament_ranking.json"))
    adapter_data = _load_json(os.path.join(data_dir, "adapter_status.json"))

    strategies = ranking_data.get("strategies", [])

    registry_count, active_count, suspended_list = _analyze_adapters(adapter_data)
    leading = _get_leading_strategy(strategies)
    milestones = _compute_milestones(strategies)
    days = _days_to_go_live(today)

    summary = {
        "generated": (today or date.today()).isoformat(),
        "leading_strategy": leading,
        "tournament_count": len(strategies),
        "active_adapters": active_count,
        "suspended_adapters": suspended_list,
        "adapter_registry_count": registry_count,
        "milestones_reached": milestones,
        "days_to_go_live": days,
    }

    atomic_save(summary, output_path)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:  # pragma: no cover
    check_only = "--check" in sys.argv
    result = generate_summary() if not check_only else _compute_only()
    print(json.dumps(result, indent=2))


def _compute_only() -> dict:  # pragma: no cover
    """Compute summary without writing to disk (used by --check)."""
    ranking_data = _load_json(os.path.join(_DEFAULT_DATA_DIR, "tournament_ranking.json"))
    adapter_data = _load_json(os.path.join(_DEFAULT_DATA_DIR, "adapter_status.json"))
    strategies = ranking_data.get("strategies", [])
    registry_count, active_count, suspended_list = _analyze_adapters(adapter_data)
    return {
        "generated": date.today().isoformat(),
        "leading_strategy": _get_leading_strategy(strategies),
        "tournament_count": len(strategies),
        "active_adapters": active_count,
        "suspended_adapters": suspended_list,
        "adapter_registry_count": registry_count,
        "milestones_reached": _compute_milestones(strategies),
        "days_to_go_live": _days_to_go_live(),
    }


if __name__ == "__main__":
    _cli()
