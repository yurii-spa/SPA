#!/bin/bash
# scripts/atomic_coverage_report.sh
# MP-1446 (v10.62) — Atomic Save Coverage Report
# Usage: bash scripts/atomic_coverage_report.sh
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

python3 - <<'EOF'
import subprocess, datetime

def lines(pattern, path="spa_core/", extra_args=None):
    cmd = ["grep", "-rn", pattern, path, "--include=*.py"]
    if extra_args:
        cmd += extra_args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines()
            if "__pycache__" not in l and "/tests/" not in l]

print("=== Atomic Save Coverage Report ===")
print(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

migrated  = lines("from spa_core.utils.atomic import")
remaining = lines(r"def _atomic_write")

print(f"Files using centralized atomic_save:  {len(migrated)}")
print(f"Remaining local _atomic_write* defs:  {len(remaining)}")
print()

if not remaining:
    print("✅ FULL MIGRATION — zero local _atomic_write definitions in spa_core/ (non-test)")
else:
    print(f"⏳ {len(remaining)} local definitions still to migrate:")
    seen = set()
    for line in remaining:
        f = ":".join(line.split(":")[:2])
        if f not in seen:
            seen.add(f)
            print(f"  {f}")

total = len(migrated) + len(remaining)
if total > 0:
    pct = len(migrated) / total * 100
    print(f"\nMigration progress: {len(migrated)} / {total} ({pct:.1f}%)")
EOF
