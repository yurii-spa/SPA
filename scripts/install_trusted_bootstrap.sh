#!/bin/bash
# install_trusted_bootstrap.sh — ADR-499 Trusted Bootstrap install (Phases 3-5). OWNER-RUN, sudo.
#
# Reuses the accepted worker-plane pattern (scripts/worker_plane/install-studio-worker-plane.sh):
# root-owned trusted plane, content-addressed sha256 artifact, root:wheel 0444, user-write DENIED.
# It installs the trusted launcher, materialises the APPROVED release from LOCAL git objects into an
# immutable root-owned dir, and creates the root-owned approval file. It does NOT repoint any launchd
# plist and does NOT start anything — the canary (Phase 6) and cutover (Phase 7) are separate owner steps.
#
# Usage:
#   sudo bash install_trusted_bootstrap.sh \
#       --launcher /abs/path/spa_core/studio_os/release_launcher.py \
#       --launcher-sha256 241eee5dfe95147b1fd485e0f60a66a5ffad9d23f1251b95a7f0dcb786edcf34 \
#       --repo /abs/path/to/git-repo-that-has-the-approved-sha \
#       --approved 5b65257784441f61568e6c3bd22e9d0a1e928c83 \
#       [--dry-run]
#
# Dry-run needs no root and only reports. Anything unverifiable → FAIL CLOSED (exit non-zero), nothing installed.
set -euo pipefail
ROOT="/Library/Application Support/StudioOS"
USER_NAME="${SUDO_USER:-$(stat -f %Su "$ROOT" 2>/dev/null || echo yuriikulieshov)}"
DRY=0; LAUNCHER=""; LSHA=""; REPO=""; APPROVED=""
while [ $# -gt 0 ]; do case "$1" in
  --launcher) LAUNCHER="$2"; shift 2;; --launcher-sha256) LSHA="$2"; shift 2;;
  --repo) REPO="$2"; shift 2;; --approved) APPROVED="$2"; shift 2;;
  --dry-run) DRY=1; shift;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
say(){ echo "[trusted-bootstrap] $*"; }
die(){ echo "[trusted-bootstrap] FAIL-CLOSED: $*" >&2; exit 1; }
run(){ if [ "$DRY" = 1 ]; then echo "  [dry] $*"; else "$@"; fi; }

[ -n "$LAUNCHER" ] && [ -n "$LSHA" ] && [ -n "$REPO" ] && [ -n "$APPROVED" ] || die "missing required arg"
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || die "needs root (sudo); for review: bash $0 --dry-run ..."

# 1) verify the launcher artifact matches the reviewed sha256 (content-address; refuse otherwise)
GOT=$(shasum -a 256 "$LAUNCHER" | cut -d' ' -f1)
[ "$GOT" = "$LSHA" ] || die "launcher sha256 $GOT != expected $LSHA"
say "launcher sha256 verified: $LSHA"

# 2) verify the approved commit exists in LOCAL git objects (no network)
git -C "$REPO" cat-file -e "${APPROVED}^{commit}" 2>/dev/null || die "approved sha $APPROVED not in local objects at $REPO"
say "approved release object present locally: $APPROVED"

DST_BIN="$ROOT/bin/release_launcher-$LSHA.py"
REL="$ROOT/releases/$APPROVED"
APPROVAL="$ROOT/approved_release.json"

# 3) install launcher → root:wheel 0444 (user cannot modify)
run mkdir -p "$ROOT/bin" "$ROOT/releases"
run cp "$LAUNCHER" "$DST_BIN"
run chown root:wheel "$DST_BIN"; run chmod 0444 "$DST_BIN"
say "launcher installed: $DST_BIN (root:wheel 0444)"

# 4) materialise the approved release: git archive → temp → verify → atomic rename → read-only root-owned
if [ "$DRY" = 1 ]; then echo "  [dry] git archive $APPROVED | tar -x -C <tmp>; stamp; rename → $REL; chmod -R a-w"; else
  TMP="$ROOT/releases/.tmp-$APPROVED"; rm -rf "$TMP"; mkdir -p "$TMP"
  git -C "$REPO" archive --format=tar "$APPROVED" | tar -x -C "$TMP" || die "materialise failed"
  printf '%s' "$APPROVED" > "$TMP/.release_sha"
  [ -f "$TMP/spa_core/paper_trading/cycle_runner.py" ] || die "release incomplete: cycle_runner missing"
  rm -rf "$REL"; mv "$TMP" "$REL"
  chown -R root:wheel "$REL"; chmod -R a-w "$REL"; chmod -R o+rX,g+rX "$REL"
  [ "$(cat "$REL/.release_sha")" = "$APPROVED" ] || die "release stamp mismatch after install"
  say "release materialised + verified: $REL (root:wheel, read-only)"
fi

# 5) approval file → root:wheel 0644 (user READS, only root WRITES). Only a SHA, never a command.
if [ "$DRY" = 1 ]; then echo "  [dry] write $APPROVAL = {\"approved_sha\":\"$APPROVED\"}; chown root:wheel; chmod 0644"; else
  printf '{"approved_sha": "%s"}\n' "$APPROVED" > "$APPROVAL"
  chown root:wheel "$APPROVAL"; chmod 0644 "$APPROVAL"
  say "approval written: $APPROVAL (root:wheel 0644)"
fi

# 6) prove the ordinary user CANNOT modify launcher / approval / release
if [ "$DRY" = 0 ]; then
  for f in "$DST_BIN" "$APPROVAL" "$REL/.release_sha"; do
    if sudo -u "$USER_NAME" test -w "$f"; then die "PERMISSION LEAK: $USER_NAME can write $f"; fi
  done
  say "permission proof: $USER_NAME cannot write launcher/approval/release ✓"
fi

say "DONE. Next (owner): Phase 6 canary — repoint ONE benign plist's ProgramArguments to:"
echo "    /bin/bash -c '\"$ROOT/toolchains/base/bin/python3\" \"$DST_BIN\" agent:<role>'   (or service id paper-cycle)"
say "Do NOT repoint the fleet until the canary + daily-cycle proofs pass."
