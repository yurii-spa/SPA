#!/usr/bin/env python3
"""Run all SPA stress test scenarios and print a summary report (MP-112).

Usage:
    python3 scripts/run_stress_tests.py

Output:
  - Prints the stress test report to stdout.
  - Saves full results to data/stress_test_results.json (atomic write).

Stdlib only. No external dependencies.
"""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from dataclasses import asdict
from pathlib import Path

# Allow running from repo root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.stress.stress_engine import run_all_scenarios, generate_stress_report


def _result_to_dict(result) -> dict:
    """Convert StressResult dataclass to a JSON-serialisable dict."""
    return asdict(result)


def main() -> None:
    print("Running SPA stress tests...\n")

    results = run_all_scenarios()
    report = generate_stress_report(results)

    print(report)

    # ── Save to data/stress_test_results.json (atomic write) ─────────────────
    data_dir = _REPO_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    output_path = data_dir / "stress_test_results.json"

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": {sid: _result_to_dict(r) for sid, r in results.items()},
        "summary": report,
    }

    # Atomic write: tmp file + os.replace (never direct open("w") on state files)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(data_dir),
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(payload, tmp, indent=2)
        tmp_path = tmp.name

    os.replace(tmp_path, str(output_path))
    print(f"Results saved → {output_path}")


if __name__ == "__main__":
    main()
