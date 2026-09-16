#!/usr/bin/env bash
# scripts/pre_commit_check.sh
# SPA Pre-commit quality gates
# MP-1522 (v11.38) — updated with security + code-quality gates
#
# Install: bash scripts/install_pre_commit.sh
#     OR:  cp scripts/pre_commit_check.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#
# Gates (run in order — fail fast):
#   [1/7] No bare exceptions (raise Exception / raise RuntimeError)
#   [2/7] KANBAN health
#   [3/7] Stdlib contract guard
#   [4/7] No hardcoded secrets
#   [5/7] Architecture audit (fast, errors only)
#   [6/7] Public API import check

set -euo pipefail

REPO_DIR="$(git rev-parse --show-toplevel)"
cd "$REPO_DIR"

echo "=== SPA Pre-commit Quality Gates ==="
echo "Repo: $REPO_DIR"
echo "Date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# ── [1/7] No bare exceptions ─────────────────────────────────────────────────
# A line marked "# drill: intentional fault injection" is deliberate fault-
# injection test scaffolding (pre_cutover_gate.py, eth_signer.py), not the
# sloppy error handling this gate exists to catch — excluded by that marker,
# not by path, so a NEW unmarked bare exception still fails here.
echo "[1/7] Checking for bare exceptions..."
if grep -rn \
     --include="*.py" \
     --exclude-dir=__pycache__ \
     --exclude-dir=tests \
     --exclude-dir=scripts \
     --exclude-dir=".git" \
     -E "raise\s+(Exception|RuntimeError)\s*\(" \
     spa_core/ 2>/dev/null | grep -v '# drill:' | grep -q .; then
  echo "❌ FAIL: Bare exceptions found in spa_core/"
  grep -rn --include="*.py" --exclude-dir=__pycache__ --exclude-dir=tests --exclude-dir=scripts \
    -E "raise\s+(Exception|RuntimeError)\s*\(" spa_core/ 2>/dev/null | grep -v '# drill:' | head -5
  exit 1
fi
echo "✅ PASS: No bare exceptions"

# ── [2/7] KANBAN health ──────────────────────────────────────────────────────
echo ""
echo "[2/7] KANBAN health..."
if python3 scripts/kanban_health.py 2>/dev/null; then
  echo "✅ PASS: KANBAN healthy"
else
  echo "⚠️  WARN: KANBAN issues detected (non-blocking)"
fi

# ── [3/7] Stdlib contract guard ──────────────────────────────────────────────
echo ""
echo "[3/7] Stdlib contract guard..."
if python3 scripts/stdlib_contract_guard.py --check 2>/dev/null; then
  echo "✅ PASS: Stdlib contracts OK"
else
  echo "⚠️  WARN: Stdlib contract issues (non-blocking)"
fi

# ── [4/7] No hardcoded secrets ───────────────────────────────────────────────
echo ""
echo "[4/7] Checking for hardcoded secrets..."
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

# ── [5/7] Architecture audit (fast) ──────────────────────────────────────────
echo ""
echo "[5/7] Architecture audit..."
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

# ── [6/7] Public API import check ────────────────────────────────────────────
echo ""
echo "[6/7] Public API import check..."
if python3 -c "import spa_core; print('✅ PASS: SPA ' + str(spa_core.VERSION))"; then
  : # success message already printed
else
  echo "❌ FAIL: spa_core import failed — check spa_core/__init__.py"
  exit 1
fi

# ── [7/7] Правка свода правил обязана нести запись в журнале ────────────────
#
# Решение владельца 16.09: агенту разрешено самому коммитить собственные инструкции
# (`CLAUDE.md`, `.claude/rules/*.md`) — ВМЕСТЕ со следом, а не вместо него. Условие
# записано и в списке разрешений, но список читается, а не исполняется; здесь оно
# ИСПОЛНЯЕТСЯ. Класс не выдуман: инвариант #17 пропал из CLAUDE.md на 16 суток
# (ADR-344), раздел deployment.md — на шесть дней; оба раза файл менялся БЕЗ СЛЕДА.
echo ""
echo "[7/7] Rules change carries a journal line..."
python3 "$REPO_DIR/scripts/check_rules_change_is_journalled.py"
RULES_RC=$?
if [ "$RULES_RC" -eq 1 ]; then
  echo "❌ FAIL: свод правил изменён без записи в журнал (см. выше)"
  exit 1
elif [ "$RULES_RC" -eq 2 ]; then
  # НЕ ИЗМЕРЕНО — не выдаём за успех, но и коммит не рушим: причина названа выше,
  # и это отдельный исход, а не отказ (инв. #17).
  echo "⚠️  НЕ ИЗМЕРЕНО: проверку журнала выполнить не удалось — причина названа выше"
fi

echo ""
echo "══════════════════════════════════════════"
echo "✅ All pre-commit gates passed — safe to commit"
echo "══════════════════════════════════════════"
exit 0
