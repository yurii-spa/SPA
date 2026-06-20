#!/usr/bin/env bash
# FIX 6 (P2) — Append-only audit trail with SHA-256 hash chain
# New module: spa_core/audit/audit_trail_signer.py
#   - append(record) → adds chain_hash = SHA256(prev_hash + canonical_json(record))
#   - verify_chain() → raises AuditChainTamperedError on tampering
#   - read_chain() → all records in insertion order
#   test_p2_audit_trail.py (16 tests)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/audit/audit_trail_signer.py" \
    "${REPO_ROOT}/tests/test_p2_audit_trail.py" \
    "${REPO_ROOT}/scripts/push_v1222.sh" \
  --message "FIX-P2: append-only audit_trail_signer with SHA-256 hash chain + AuditChainTamperedError"
