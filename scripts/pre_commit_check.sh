#!/usr/bin/env bash
# scripts/pre_commit_check.sh
# SPA Pre-commit quality gates
#
# Install: cp scripts/pre_commit_check.sh .git/hooks/pre-commit
#          chmod +x .git/hooks/pre-commit
# Or run:  bash scripts/install_git_hooks.sh
#
# Gates (run in order — fail fast):
#   [1/4] KANBAN health
#   [2/4] Architecture audit (fast, errors only)
#   [3/4] Core tests (fast subset)
#   [4/4] Public API import check

set -euo pipefail

REPO_DIR="$(git rev-parse --show-toplevel)"
cd "$REPO_DIR"

echo "=== SPA Pre-commit checks ==="
echo "Repo: $REPO_DIR"
echo "Date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# ── [1/4] KANBAN health ───────────────────────────────────────────────────────
echo "[1/4] KANBAN health..."
if python3 scripts/kanban_health.py; then
  echo "✅ KANBAN OK"
else
  echo "❌ KANBAN unhealthy — fix KANBAN.json before committing"
  exit 1
fi

# ── [2/4] Architecture audit (fast) ──────────────────────────────────────────
echo ""
echo "[2/4] Architecture audit..."
python3 - <<'PYEOF'
import sys
try:
    from spa_core.analytics.architecture_audit import ArchitectureAudit
    audit = ArchitectureAudit()
    violations = audit.run_all()
    errors = [v for v in violations if v.severity == 'ERROR']
    if errors:
        print(f"❌ {len(errors)} ERROR violation(s):")
        for v in errors[:3]:
            print(f"  {v.file}: {v.message}")
        sys.exit(1)
    print(f"✅ Audit OK ({len(violations)} warning(s))")
except ImportError:
    # architecture_audit not yet wired — warn and continue
    print("⚠️  architecture_audit module not found — skipping (non-blocking)")
    sys.exit(0)
PYEOF

# ── [3/4] Core tests (fast subset) ───────────────────────────────────────────
echo ""
echo "[3/4] Core tests..."
CORE_TESTS=""
for t in \
  tests/test_spa_utils.py \
  tests/test_spa_base.py \
  tests/test_spa_errors.py; do
  [ -f "$t" ] && CORE_TESTS="$CORE_TESTS $t"
done

if [ -z "$CORE_TESTS" ]; then
  echo "⚠️  No core test files found — skipping (non-blocking)"
else
  # shellcheck disable=SC2086
  if python3 -m pytest $CORE_TESTS -q --tb=short 2>&1 | tail -8; then
    echo "✅ Core tests passed"
  else
    echo "❌ Core tests failed"
    exit 1
  fi
fi

# ── [4/4] Public API import check ────────────────────────────────────────────
echo ""
echo "[4/4] Public API..."
if python3 -c "import spa_core; print(f'✅ SPA {spa_core.VERSION}')"; then
  : # already printed success
else
  echo "❌ spa_core import failed — check __init__.py"
  exit 1
fi

echo ""
echo "✅ All pre-commit checks passed"
exit 0
