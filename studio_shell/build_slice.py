#!/usr/bin/env python3
"""Emit slice_<protocol>.json + compare.json for the Desktop panels — thin wrappers over the SHARED
projectors spa_core.owner_remote.{slice,compare} (same truth the Telegram gateway reads)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def main():
    # lazy import: studio_shell/ is outside the autosync dirs, so a top-level spa_core import would be
    # an undeliverable hard dependency in prod (test_unsynced_hard_imports). Import at call time instead.
    sys.path.insert(0, str(REPO))
    from spa_core.owner_remote.slice import build_investment_slice
    from spa_core.owner_remote.compare import compare_slices
    aave = build_investment_slice("aave_v3")
    pendle = build_investment_slice("pendle")
    comp = compare_slices("aave_v3", "pendle")
    (HERE / "slice_aave.json").write_text(json.dumps(aave, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "slice_pendle.json").write_text(json.dumps(pendle, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "compare.json").write_text(json.dumps(comp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"aave": aave["result"]["label"]["value"],
                      "pendle": pendle["result"]["label"]["value"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
