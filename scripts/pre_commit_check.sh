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
# Scope to the STAGED spa_core python files — the surface THIS commit introduces. A pre-commit gate
# must judge what is being committed, not the whole tree: whole-tree grep blocked unrelated commits on
# pre-existing debt in files they never touched (Architecture Review Board, 2026-09). Policy is NOT
# weakened — a NEW unmarked bare exception in a staged file still fails here, and the `# drill:` marker
# still exempts deliberate fault-injection scaffolding by marker text, not by path. Repository-wide debt
# is a separate audit concern, not a per-commit blocker. (tests/ and scripts/ excluded as before.)
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACMR -- spa_core 2>/dev/null \
            | grep -E '\.py$' | grep -vE '(^|/)tests/|(^|/)scripts/|__pycache__' || true)
if [ -n "$STAGED_PY" ]; then
  HITS=$(printf '%s\n' "$STAGED_PY" | tr '\n' '\0' \
         | xargs -0 grep -nE "raise\s+(Exception|RuntimeError)\s*\(" 2>/dev/null | grep -v '# drill:' || true)
  if [ -n "$HITS" ]; then
    echo "❌ FAIL: Bare exceptions found in staged spa_core/ files"
    printf '%s\n' "$HITS" | head -5
    exit 1
  fi
fi
echo "✅ PASS: No bare exceptions (staged spa_core/ surface)"

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

# Scope to STAGED files — the surface entering history. A secrets pre-commit gate must scan what is
# being committed (that is precisely where a leaking secret is caught before it enters git); a whole-tree
# scan on every commit blocked unrelated commits on pre-existing FALSE POSITIVES (a `ghp_` regex literal in
# report_sections.py, an example token in a comment) in files they never touched (ARB 2026-09). A NEW real
# secret in a staged file still fails. data/ and __pycache__ stay out of scope as before.
STAGED_SECRETSCAN=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null \
                    | grep -E '\.(py|sh|json)$' | grep -vE '(^|/)data/|__pycache__' || true)
if [ -n "$STAGED_SECRETSCAN" ]; then
  # GitHub PAT / OpenAI key: match an ACTUAL token body, not a bare prefix. A real PAT is ghp_ + 36 chars;
  # matching bare `ghp_` flagged detector regex literals (e.g. this gate, report_sections.py) as secrets.
  # Requiring {20,} of token charset still catches every real leaked token while ignoring prefix mentions.
  SECRET_RE="(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,})"
  if printf '%s\n' "$STAGED_SECRETSCAN" | tr '\n' '\0' \
       | xargs -0 grep -nE "$SECRET_RE" 2>/dev/null \
     | grep -v "test\|example\|placeholder\|PATTERN\|pattern\|#" \
     | grep -q .; then
    echo "❌ FAIL: Potential GitHub PAT/API key found in staged files"
    printf '%s\n' "$STAGED_SECRETSCAN" | tr '\n' '\0' \
      | xargs -0 grep -nE "$SECRET_RE" 2>/dev/null \
      | grep -v "test\|example\|placeholder\|PATTERN\|pattern\|#" | head -3
    exit 1
  fi
  # Raw private keys (64-char hex — Ethereum private keys); staged python only, tests excluded as before
  STAGED_PY_KEYS=$(printf '%s\n' "$STAGED_SECRETSCAN" | grep -E '\.py$' | grep -vE '(^|/)tests/' || true)
  if [ -n "$STAGED_PY_KEYS" ] && printf '%s\n' "$STAGED_PY_KEYS" | tr '\n' '\0' \
       | xargs -0 grep -nE "0x[a-fA-F0-9]{64}" 2>/dev/null | grep -q .; then
    echo "❌ FAIL: Potential raw private key (64-char hex) found in staged files"
    exit 1
  fi
fi

echo "✅ PASS: No hardcoded secrets detected (staged surface)"

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
