#!/bin/bash
# scripts/spaerror_coverage_report.sh
# MP-1444 (v10.60) — SPAError Coverage Report
# Usage: bash scripts/spaerror_coverage_report.sh
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 - <<'EOF'
import subprocess, sys

def count(pattern, extra_args=None):
    cmd = ["grep", "-rn", pattern, "spa_core/", "--include=*.py"]
    if extra_args:
        cmd += extra_args
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines()
             if "test" not in l and "__pycache__" not in l]
    return lines

import datetime
print("=== SPAError Coverage Report ===")
print(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

migrated = count("from spa_core.utils.errors import")
bare_exc = count(r"raise Exception\b")
bare_rt  = count(r"raise RuntimeError")

print(f"Files using SPAError:        {len(migrated)}")
print(f"Remaining bare Exception:    {len(bare_exc)}")
print(f"Remaining bare RuntimeError: {len(bare_rt)}")
print(f"Total remaining bare raises: {len(bare_exc) + len(bare_rt)}")
print()

remaining = bare_exc + bare_rt
if not remaining:
    print("✅ FULL COVERAGE — zero bare Exception/RuntimeError in spa_core/ (non-test)")
else:
    print("⚠️  Remaining locations:")
    seen = set()
    for line in remaining:
        f = ":".join(line.split(":")[:2])
        if f not in seen:
            seen.add(f)
            print(f"  {f}")

total = len(migrated) + len(remaining)
if total > 0:
    pct = len(migrated) / total * 100
    print(f"\nCoverage: {len(migrated)} / {total} ({pct:.1f}%)")
EOF
