#!/usr/bin/env bash
# scripts/pre_commit_check.sh
# SPA Pre-commit quality gates
# MP-1522 (v11.38) — updated with security + code-quality gates
#
# Install: bash scripts/install_pre_commit.sh
#     OR:  cp scripts/pre_commit_check.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#
# Gates (run in order — fail fast):
#   [1/6] No bare exceptions (raise Exception / raise RuntimeError)
#   [2/6] KANBAN health
#   [3/6] Stdlib contract guard
#   [4/6] No hardcoded secrets
#   [5/6] Architecture audit (fast, errors only)
#   [6/6] Public API import check

set -euo pipefail

REPO_DIR="$(git rev-parse --show-toplevel)"
cd "$REPO_DIR"

echo "=== SPA Pre-commit Quality Gates ==="
echo "Repo: $REPO_DIR"
echo "Date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# ── [1/6] No bare exceptions ─────────────────────────────────────────────────
echo "[1/6] Checking for bare exceptions..."
if grep -rn \
     --include="*.py" \
     --exclude-dir=__pycache__ \
     --exclude-dir=tests \
     --exclude-dir=scripts \
     --exclude-dir=".git" \
     -E "raise\s+(Exception|RuntimeError)\s*\(" \
     spa_core/ 2>/dev/null | grep -q .; then
  echo "❌ FAIL: Bare exceptions found in spa_core/"
  grep -rn --include="*.py" --exclude-dir=__pycache__ \
    -E "raise\s+(Exception|RuntimeError)\s*\(" spa_core/ 2>/dev/null | head -5
  exit 1
fi
echo "✅ PASS: No bare exceptions"

# ── [2/6] KANBAN health ──────────────────────────────────────────────────────
echo ""
echo "[2/6] KANBAN health..."
if python3 scripts/kanban_health.py 2>/dev/null; then
  echo "✅ PASS: KANBAN healthy"
else
  echo "⚠️  WARN: KANBAN issues detected (non-blocking)"
fi

# ── [3/6] Stdlib contract guard ──────────────────────────────────────────────
echo ""
echo "[3/6] Stdlib contract guard..."
if python3 scripts/stdlib_contract_guard.py --check 2>/dev/null; then
  echo "✅ PASS: Stdlib contracts OK"
else
  echo "⚠️  WARN: Stdlib contract issues (non-blocking)"
fi

# ── [4/6] No hardcoded secrets ───────────────────────────────────────────────
echo ""
echo "[4/6] Checking for hardcoded secrets..."
SECRET_FOUND=0

# GitHub PAT pattern: ghp_ or github_pat_ prefixes
if grep -rn --include="*.py" --include="*.sh" --include="*.json" \
     --exclude-dir=__pycache__ --exclude-dir=".git" --exclude-dir=data \
     -E "(ghp_|github_pat_|sk-[A-Za-z0-9]{20,})" . 2>/dev/null \
   | grep -v "test\|example\|placeholder\|PATTERN\|pattern\|#" \
   | grep -q .; then
  echo "❌ FAIL: Potential GitHub PAT found"
  grep -rn --include="*.py" --include="*.sh" \
    --exclude-dir=__pycache__ --exclude-dir=".git" --exclude-dir=data \
    -E "(ghp_|github_pat_)" . 2>/dev/null | head -3
  exit 1
fi

# Raw private keys (64-char hex — Ethereum private keys)
if grep -rn --include="*.py" \
     --exclude-dir=__pycache__ --exclude-dir=".git" --exclude-dir=data \
     --exclude-dir=tests \
     -E "0x[a-fA-F0-9]{64}" . 2>/dev/null | grep -q .; then
  echo "❌ FAIL: Potential raw private key (64-char hex) found"
  exit 1
fi

echo "✅ PASS: No hardcoded secrets detected"

# ── [5/6] Architecture audit (fast) ──────────────────────────────────────────
echo ""
echo "[5/6] Architecture audit..."
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
    print(f"✅ PASS: Audit OK ({len(violations)} warning(s))")
except ImportError:
    print("⚠️  architecture_audit module not found — skipping (non-blocking)")
    sys.exit(0)
PYEOF

# ── [6/6] Public API import check ────────────────────────────────────────────
echo ""
echo "[6/6] Public API import check..."
if python3 -c "import spa_core; print('✅ PASS: SPA ' + str(spa_core.VERSION))"; then
  : # success message already printed
else
  echo "❌ FAIL: spa_core import failed — check spa_core/__init__.py"
  exit 1
fi

echo ""
echo "══════════════════════════════════════════"
echo "✅ All pre-commit gates passed — safe to commit"
echo "══════════════════════════════════════════"
exit 0
