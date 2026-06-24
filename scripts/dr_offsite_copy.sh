#!/usr/bin/env bash
# scripts/dr_offsite_copy.sh — copy the newest DR backup to an OFFSITE/secondary location.
#
# Self-Healing Plane 1.7 — DR offsite copy.
#
# spa_core/backtesting/tier1/dr_backup.py produces data/backups/spa_state_*.tar.gz on the
# SAME host. A single-host backup is necessary-but-not-sufficient for HA: if the Mac mini
# dies, the backups die with it. This script copies the newest archive to a SEPARATE
# destination directory (a stand-in for a second disk / offsite host) and verifies the copy
# is bit-for-bit identical via sha256.
#
# HONEST SCOPE: with no real offsite target configured this copies to a local stand-in dir
# ($HOME/spa_offsite_backups/ by default). That proves the MECHANISM (newest-archive
# selection + transfer + integrity verify). TRUE offsite (cloud bucket / remote host) is
# INFRASTRUCTURE, not code: set SPA_OFFSITE_DEST to a real target. A remote target would be
# wired the same way — replace the `cp` with `rsync`/`aws s3 cp` to SPA_OFFSITE_DEST and the
# sha256 verify stays identical in spirit.
#
#   SPA_OFFSITE_DEST   override destination dir (default: $HOME/spa_offsite_backups)
#
# Deterministic, stdlib-only tooling (cp + shasum). Fail-safe: non-zero exit on any failure.
#
# Usage:  bash scripts/dr_offsite_copy.sh
#         SPA_OFFSITE_DEST=/Volumes/Backup/spa bash scripts/dr_offsite_copy.sh

set -uo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
BACKUP_DIR="$REPO/data/backups"
DEST_DIR="${SPA_OFFSITE_DEST:-$HOME/spa_offsite_backups}"

echo "=============================================="
echo " SPA DR offsite copy"
echo "=============================================="
echo "  source:  $BACKUP_DIR"
echo "  dest:    $DEST_DIR"
echo ""

# 1) Find the newest backup archive (names are lexically sortable: spa_state_<UTCts>.tar.gz).
if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "[FAIL] backup dir not found: $BACKUP_DIR — run dr_backup.snapshot() first."
    exit 1
fi

NEWEST="$(ls -1 "$BACKUP_DIR"/spa_state_*.tar.gz 2>/dev/null | sort | tail -n 1)"
if [[ -z "$NEWEST" ]]; then
    echo "[FAIL] no spa_state_*.tar.gz archives in $BACKUP_DIR — nothing to copy."
    exit 1
fi
echo "[OK] newest archive: $(basename "$NEWEST")"

# 2) Compute source sha256.
SRC_SHA="$(shasum -a 256 "$NEWEST" | awk '{print $1}')"
if [[ -z "$SRC_SHA" ]]; then
    echo "[FAIL] could not compute source sha256."
    exit 1
fi
echo "[OK] source sha256: $SRC_SHA"

# 3) Copy to the offsite/secondary destination.
mkdir -p "$DEST_DIR" || { echo "[FAIL] cannot create dest dir: $DEST_DIR"; exit 1; }
DEST_FILE="$DEST_DIR/$(basename "$NEWEST")"
if ! cp -f "$NEWEST" "$DEST_FILE"; then
    echo "[FAIL] copy failed → $DEST_FILE"
    exit 1
fi
echo "[OK] copied → $DEST_FILE"

# 4) Verify the copy's sha256 matches the source (integrity proof).
DST_SHA="$(shasum -a 256 "$DEST_FILE" | awk '{print $1}')"
echo "[OK] dest   sha256: $DST_SHA"
if [[ "$SRC_SHA" != "$DST_SHA" ]]; then
    echo "[FAIL] sha256 MISMATCH — offsite copy is CORRUPT. Removing."
    rm -f "$DEST_FILE"
    exit 1
fi

echo ""
echo "[VERIFIED] offsite copy sha256 matches source — backup transferred INTACT."
echo ""
echo "NOTE: destination '$DEST_DIR' is a LOCAL stand-in for offsite. TRUE offsite"
echo "      (cloud bucket / remote host) is INFRASTRUCTURE: set SPA_OFFSITE_DEST and"
echo "      swap 'cp' for 'rsync'/'aws s3 cp' to that target. The mechanism is proven here."
exit 0
