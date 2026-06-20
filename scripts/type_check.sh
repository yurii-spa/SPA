#!/bin/bash
# scripts/type_check.sh
# Run mypy type check on spa_core critical modules
# MP-1520 (v11.36)
set -euo pipefail

echo "=== SPA Type Check (mypy) ==="
echo "Targets: spa_core/utils/ spa_core/safety/ spa_core/risk/ spa_core/allocator/"
echo ""

TARGETS=(
    "spa_core/utils/"
    "spa_core/safety/"
    "spa_core/risk/"
    "spa_core/allocator/"
)

if python3 -c "import mypy" 2>/dev/null; then
    python3 -m mypy "${TARGETS[@]}" \
        --config-file mypy.ini \
        --ignore-missing-imports \
        --no-error-summary \
        2>&1 | grep -v "^$" || true
    echo ""
    echo "✅ mypy check complete (see output above)"
else
    echo "⚠️  mypy not installed. To install:"
    echo "    pip install mypy --break-system-packages"
    echo ""
    echo "Running lightweight annotation audit instead..."
    python3 - <<'PYEOF'
import os
from pathlib import Path

targets = [
    "spa_core/utils",
    "spa_core/safety",
    "spa_core/risk",
    "spa_core/allocator",
]

total_funcs = 0
typed_funcs = 0
issues = []

for target in targets:
    for path in sorted(Path(target).rglob("*.py")):
        if "__pycache__" in str(path) or path.name.startswith("__"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("def ") and not stripped.startswith("def __"):
                total_funcs += 1
                if "->" in stripped or ":" in stripped.split("(")[0]:
                    typed_funcs += 1
                else:
                    issues.append(f"  {path}:{lineno}: {stripped[:60]}")

pct = typed_funcs / total_funcs * 100 if total_funcs else 0
print(f"Type annotation coverage: {typed_funcs}/{total_funcs} functions ({pct:.1f}%)")
if issues:
    print(f"\nPossibly untyped functions ({len(issues)}):")
    for i in issues[:10]:
        print(i)
else:
    print("✅ All public functions have type hints")
PYEOF
fi
