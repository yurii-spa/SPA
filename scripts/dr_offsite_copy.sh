#!/usr/bin/env bash
# scripts/dr_offsite_copy.sh — copy the newest DR backup OFFSITE + sha256-verify + status.
#
# Resilience Plane (R6) — make the offsite-backup mechanism PROVABLY EXERCISED.
#
# Thin wrapper over spa_core/dr/offsite_copy.py (stdlib-only, deterministic, atomic,
# fail-CLOSED). The Python helper holds the testable logic:
#   1) select newest data/backups/spa_state_*.tar.gz
#   2) atomic copy → $SPA_OFFSITE_DEST   (tmp + fsync + os.replace, never partial)
#   3) sha256 verify source == dest      (mismatch → remove dest, verified:false, exit!=0)
#   4) prune offsite copies, keep last 14
#   5) emit data/dr_offsite_status.json (atomic):
#        {last_offsite_ts, archive_name, sha256, dest, verified, n_offsite_kept, is_real_remote}
#
# HONEST SCOPE: with no real offsite target the dest is a LOCAL stand-in
# ($HOME/spa_offsite_backups). That proves the MECHANISM; is_real_remote=false then.
#
#   ┌─ ONE-LINE SWITCH TO A REAL REMOTE (owner-flagged infra, not code) ───────────┐
#   │  export SPA_OFFSITE_DEST=/Volumes/Backup/spa   # mounted 2nd disk / NAS / s3  │
#   │  Mechanism (copy + sha-verify + prune + status) is identical; is_real_remote  │
#   │  flips to true. Single-host backups remain a SPOF until this is set. (R6)     │
#   └──────────────────────────────────────────────────────────────────────────────┘
#   --> DR runbook follow-up: provision a real SPA_OFFSITE_DEST (owner decision).
#
# RUN MODES:
#   standalone:        bash scripts/dr_offsite_copy.sh
#   real remote:       SPA_OFFSITE_DEST=/Volumes/Backup/spa bash scripts/dr_offsite_copy.sh
#   backup-agent tail: the daily/weekly backup script calls this after the archive is built
#                      (see scripts/daily_backup.sh tail step). Idempotent + fail-CLOSED.
#
set -uo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
PY="/Users/yuriikulieshov/miniconda3/bin/python3"
[[ -x "$PY" ]] || PY="python3"

cd "$REPO" || { echo "[FAIL] cannot cd $REPO"; exit 1; }

# SPA_OFFSITE_DEST (if set) is honored by the Python helper via the env var.
exec "$PY" -m spa_core.dr.offsite_copy "$@"
