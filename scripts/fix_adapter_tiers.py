"""
scripts/fix_adapter_tiers.py — Fix adapter tier mapping in adapter_status.json

Проблема: adapter_status.json хранит tier как целое число (1, 2, 3),
что корректно обрабатывается _normalize_tier(), НО ряд инструментов
ожидают строковые "T1"/"T2"/"T3". Этот скрипт:

1. Читает adapter_status.json
2. Добавляет поле tier_str ("T1"/"T2"/"T3") для каждого адаптера
3. Проверяет соответствие ADAPTER_REGISTRY
4. Записывает обновлённый файл атомарно
5. Выводит итоговый отчёт

Запуск: python3 scripts/fix_adapter_tiers.py [--dry-run]
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ADAPTER_STATUS = _REPO / "data" / "adapter_status.json"

# Authoritative tier map (ground truth from ADAPTER_REGISTRY + ADR docs)
TIER_MAP: dict = {
    # T1 — highest trust, largest TVL, audited 3+ years
    "aave_v3":          1,
    "compound_v3":      1,
    "spark_susds":      1,
    "morpho_steakhouse": 1,
    "aave_arbitrum":    1,
    "aave_v3_optimism": 1,
    "aave_v3_polygon":  1,
    "aave_v3_base":     2,   # T2: Base chain bridge risk (ADR-025)
    "sky_susds":        1,

    # T2 — good but smaller TVL or newer
    "morpho_blue":      2,
    "yearn_v3":         2,
    "euler_v2":         2,
    "maple":            2,
    "pendle":           2,
    "pendle_pt":        2,
    "pendle_pt_susde":  2,
    "pendle_pt_usdc":   2,
    "fluid_fusdc":      2,
    "fluid_usdc":       2,
    "fluid_arbitrum":   2,
    "sfrax":            2,
    "frax":             2,
    "wusdm":            2,
    "scrvusd":          2,
    "sdai":             2,
    "morpho_blue_base": 2,
    "moonwell_base":    2,
    "notional_v3":      2,
    "ethena_susde":     2,
    "silo_arbitrum":    2,
    "dolomite_arbitrum": 2,
    "velodrome_optimism": 2,
    "aerodrome_base":   2,
    "usual_usd0pp":     2,

    # T3 — higher risk / yield / newer / experimental
    "susde":            3,
    "extra_finance_base": 3,
    "stusd":            2,   # reclassified from T3 (stable, audited)

    # Special
    "sky_usds":         0,   # watchlist, 0% allocation until GSM Pause Delay >= 48h
}

TIER_STR_MAP = {0: "WATCHLIST", 1: "T1", 2: "T2", 3: "T3"}


def _atomic_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fix_adapter_tiers(dry_run: bool = False) -> int:
    """Apply tier fixes. Returns number of adapters modified."""
    if not _ADAPTER_STATUS.exists():
        print(f"ERROR: {_ADAPTER_STATUS} not found")
        return 0

    with open(_ADAPTER_STATUS, "r", encoding="utf-8") as f:
        doc = json.load(f)

    adapters = doc.get("adapters", {})
    if not isinstance(adapters, dict):
        print("ERROR: adapters key is not a dict")
        return 0

    modified = 0
    report_lines = ["Adapter tier audit:"]

    for name, info in adapters.items():
        if not isinstance(info, dict):
            continue

        current_tier = info.get("tier")
        authoritative = TIER_MAP.get(name)

        # Compute tier_str
        tier_for_str = authoritative if authoritative is not None else current_tier
        try:
            tier_int = int(tier_for_str) if tier_for_str is not None else 2
        except (TypeError, ValueError):
            tier_int = 2
        tier_str = TIER_STR_MAP.get(tier_int, "T2")

        changes = []

        # Fix integer tier if authoritative mapping disagrees
        if authoritative is not None and current_tier != authoritative:
            changes.append("tier: {} -> {}".format(current_tier, authoritative))
            info["tier"] = authoritative

        # Always add/update tier_str
        if info.get("tier_str") != tier_str:
            info["tier_str"] = tier_str
            changes.append("tier_str={}".format(tier_str))

        if changes:
            modified += 1
            report_lines.append("  {} [{}]: {}".format(name, tier_str, ", ".join(changes)))
        else:
            report_lines.append("  {} [{}]: OK".format(name, tier_str))

    report_lines.append("\nTotal adapters: {}  Modified: {}".format(len(adapters), modified))

    for line in report_lines:
        print(line)

    if not dry_run and modified > 0:
        doc["tier_fix_applied_at"] = datetime.now(timezone.utc).isoformat()
        doc["tier_fix_version"] = "scripts/fix_adapter_tiers.py v1.0"
        _atomic_write(_ADAPTER_STATUS, doc)
        print("\nWrote updated adapter_status.json (atomic).")
    elif dry_run:
        print("\nDRY-RUN: no changes written.")
    else:
        print("\nNo changes needed.")

    return modified


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    n = fix_adapter_tiers(dry_run=dry_run)
    sys.exit(0)
