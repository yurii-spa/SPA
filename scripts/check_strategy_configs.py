#!/usr/bin/env python3
"""
SPA Strategy-as-Config CHANGE-CONTROL GUARD (Strategy Plane 1.1)
================================================================

CI-style guard that enforces change-control on strategy configs.

A strategy's *behaviour* is captured by its config descriptor (see
``spa_core.strategies.strategy_config_schema``), pinned to a deterministic
``config_hash``. This guard recomputes every registry strategy's config + hash
and compares them against a COMMITTED baseline.

Rule (the whole point of the layer):
    If a strategy's ``config_hash`` CHANGED but its ``version`` field did NOT
    change → FAIL. A behaviour change MUST be accompanied by a version bump.

    * hash changed AND version bumped → OK (a legitimate, declared change).
    * hash unchanged                  → OK (no change).
    * new strategy (not in baseline)  → reported (informational, not a failure
                                        unless --strict-new).
    * removed strategy                → reported (informational).

Baseline location
-----------------
``data/*.json`` is gitignored, so the baseline lives at a COMMITTABLE path:
    spa_core/strategies/strategy_configs_baseline.json

Regenerate it deliberately (and commit it) with ``--update-baseline`` whenever
you have legitimately changed configs (with version bumps).

CLI:
    python3 scripts/check_strategy_configs.py              # check (exit 0/1)
    python3 scripts/check_strategy_configs.py --update-baseline
    python3 scripts/check_strategy_configs.py --strict-new # new strats also fail

# LLM_FORBIDDEN — pure deterministic comparison. No model calls, ever.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

# Make the project root importable when invoked as a plain script.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.strategies.strategy_config_schema import (  # noqa: E402
    all_configs,
    config_hash,
)

# Committable baseline (data/ is gitignored; spa_core/ is not).
BASELINE_PATH = (
    _PROJECT_ROOT / "spa_core" / "strategies" / "strategy_configs_baseline.json"
)

BASELINE_SCHEMA_VERSION = "1.1"


# ─── Baseline I/O ────────────────────────────────────────────────────────────────

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + shutil.move)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True, default=str)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    shutil.move(tmp, str(path))


def compute_current() -> dict[str, dict]:
    """
    Compute the current change-control snapshot for every registry strategy.

    Returns a mapping ``{id: {"version": str, "config_hash": str}}`` sorted by
    id (dict insertion order is deterministic from sorted all_configs()).
    """
    snapshot: dict[str, dict] = {}
    for cfg in all_configs():
        sid = str(cfg.get("id"))
        snapshot[sid] = {
            "version": str(cfg.get("version")),
            "config_hash": config_hash(cfg),
        }
    return dict(sorted(snapshot.items()))


def build_baseline() -> dict:
    """Build the full baseline document from the live registry."""
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "strategies": compute_current(),
    }


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict]:
    """
    Load the committed baseline → ``{id: {"version", "config_hash"}}``.

    Raises FileNotFoundError if the baseline is missing (caller decides).
    """
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    strategies = doc.get("strategies", {})
    if not isinstance(strategies, dict):
        raise ValueError("baseline 'strategies' must be an object")
    return strategies


def update_baseline(path: Path = BASELINE_PATH) -> dict:
    """Regenerate and atomically write the baseline. Returns the document."""
    doc = build_baseline()
    _atomic_write_json(path, doc)
    return doc


# ─── Comparison ──────────────────────────────────────────────────────────────────

def compare(current: dict[str, dict], baseline: dict[str, dict]) -> dict:
    """
    Compare current snapshot against baseline.

    Returns a result dict:
        {
          "silent_changes":  [ {id, baseline_version, current_version,
                                baseline_hash, current_hash}, ... ],  # FAIL
          "versioned_changes": [ {id, ...}, ... ],   # OK (declared)
          "new":     [id, ...],
          "removed": [id, ...],
          "unchanged_count": int,
        }
    """
    silent_changes: list[dict] = []
    versioned_changes: list[dict] = []
    new: list[str] = []
    unchanged_count = 0

    for sid in sorted(current.keys()):
        cur = current[sid]
        base = baseline.get(sid)
        if base is None:
            new.append(sid)
            continue
        if cur["config_hash"] == base.get("config_hash"):
            unchanged_count += 1
            continue
        # Hash changed → must be accompanied by a version bump.
        record = {
            "id": sid,
            "baseline_version": base.get("version"),
            "current_version": cur["version"],
            "baseline_hash": base.get("config_hash"),
            "current_hash": cur["config_hash"],
        }
        if cur["version"] != base.get("version"):
            versioned_changes.append(record)
        else:
            silent_changes.append(record)

    removed = sorted(set(baseline.keys()) - set(current.keys()))

    return {
        "silent_changes": silent_changes,
        "versioned_changes": versioned_changes,
        "new": new,
        "removed": removed,
        "unchanged_count": unchanged_count,
    }


# ─── Reporting ───────────────────────────────────────────────────────────────────

def format_result(result: dict, strict_new: bool = False) -> str:
    """Human-readable summary of a compare() result."""
    lines: list[str] = []
    lines.append("Strategy-as-Config change-control guard")
    lines.append(
        f"  unchanged: {result['unchanged_count']}  "
        f"versioned-changes: {len(result['versioned_changes'])}  "
        f"new: {len(result['new'])}  removed: {len(result['removed'])}  "
        f"SILENT-CHANGES: {len(result['silent_changes'])}"
    )

    for rec in result["versioned_changes"]:
        lines.append(
            f"  OK   {rec['id']}: config changed, version "
            f"{rec['baseline_version']} -> {rec['current_version']} (declared)"
        )
    for sid in result["new"]:
        tag = "FAIL" if strict_new else "NEW "
        lines.append(f"  {tag} {sid}: new strategy not in baseline")
    for sid in result["removed"]:
        lines.append(f"  GONE {sid}: removed strategy (was in baseline)")
    for rec in result["silent_changes"]:
        lines.append(
            f"  FAIL {rec['id']}: config_hash changed but version did NOT "
            f"(version={rec['current_version']}). Bump 'version' or revert."
        )

    return "\n".join(lines)


def has_failures(result: dict, strict_new: bool = False) -> bool:
    """True when the guard should exit non-zero."""
    if result["silent_changes"]:
        return True
    if strict_new and result["new"]:
        return True
    return False


# ─── CLI ─────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strategy-as-Config change-control guard."
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Regenerate the committed baseline (commit it deliberately).",
    )
    parser.add_argument(
        "--strict-new",
        action="store_true",
        help="Treat new strategies (absent from baseline) as a failure too.",
    )
    parser.add_argument(
        "--baseline",
        default=str(BASELINE_PATH),
        help="Path to the baseline JSON (default: committed baseline).",
    )
    args = parser.parse_args(argv)
    baseline_path = Path(args.baseline)

    if args.update_baseline:
        doc = update_baseline(baseline_path)
        n = len(doc["strategies"])
        print(f"baseline updated: {n} strategies -> {baseline_path}")
        return 0

    try:
        baseline = load_baseline(baseline_path)
    except FileNotFoundError:
        print(
            f"FAIL: baseline not found at {baseline_path}\n"
            f"      run: python3 scripts/check_strategy_configs.py "
            f"--update-baseline",
            file=sys.stderr,
        )
        return 1

    current = compute_current()
    result = compare(current, baseline)
    print(format_result(result, strict_new=args.strict_new))

    if has_failures(result, strict_new=args.strict_new):
        print(
            "\nGUARD FAILED: strategy behaviour changed without a version bump.",
            file=sys.stderr,
        )
        return 1

    print("\nguard clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
