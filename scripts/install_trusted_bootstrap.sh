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
DRY=0; LAUNCHER=""; LSHA=""; REPO=""; APPROVED=""; APP_PYTHON=""
while [ $# -gt 0 ]; do case "$1" in
  --launcher) LAUNCHER="$2"; shift 2;; --launcher-sha256) LSHA="$2"; shift 2;;
  --repo) REPO="$2"; shift 2;; --approved) APPROVED="$2"; shift 2;;
  --app-python) APP_PYTHON="$2"; shift 2;;
  --dry-run) DRY=1; shift;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
say(){ echo "[trusted-bootstrap] $*"; }
die(){ echo "[trusted-bootstrap] FAIL-CLOSED: $*" >&2; exit 1; }
run(){ if [ "$DRY" = 1 ]; then echo "  [dry] $*"; else "$@"; fi; }

[ -n "$LAUNCHER" ] && [ -n "$LSHA" ] && [ -n "$REPO" ] && [ -n "$APPROVED" ] || die "missing required arg"
[ -n "$APP_PYTHON" ] || die "missing --app-python <trusted 3.13 path> (the root-owned app runtime)"
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || die "needs root (sudo); for review: bash $0 --dry-run ..."

# 0) verify the APP runtime is a real, TRUSTED (non-user-writable) python3 before anything else
[ -x "$APP_PYTHON" ] || die "app runtime $APP_PYTHON not executable"
APP_VER=$("$APP_PYTHON" -E -s -c "import sys;print('%d.%d.%d'%sys.version_info[:3])" 2>/dev/null) || die "app runtime does not run"
case "$APP_VER" in 3.13.*) : ;; *) die "app runtime is $APP_VER, expected 3.13.x" ;; esac
# it (and its real target) must NOT be writable by the invoking non-root owner
if [ "$DRY" = 0 ]; then
  RP=$(/usr/bin/python3 -c "import os,sys;print(os.path.realpath(sys.argv[1]))" "$APP_PYTHON")
  if sudo -u "$USER_NAME" test -w "$APP_PYTHON" || sudo -u "$USER_NAME" test -w "$RP"; then
    die "app runtime $APP_PYTHON (real $RP) is writable by $USER_NAME — NOT trusted"
  fi
fi
say "app runtime trusted: $APP_PYTHON ($APP_VER, not user-writable)"

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

# 5b) runtime manifest → root:wheel 0644. The launcher reads app_python from HERE (root-owned), never
#     sys.executable (=3.9 bootstrap) and never the approval file. Only a fixed interpreter path.
RUNTIME="$ROOT/runtime.json"
if [ "$DRY" = 1 ]; then echo "  [dry] write $RUNTIME = {\"app_python\":\"$APP_PYTHON\",\"app_python_version\":\"$APP_VER\"}; chown root:wheel; chmod 0644"; else
  APP_SHA=$(shasum -a 256 "$RP" 2>/dev/null | cut -d' ' -f1)
  printf '{"app_python": "%s", "app_python_version": "%s", "app_python_sha256": "%s"}\n' "$APP_PYTHON" "$APP_VER" "$APP_SHA" > "$RUNTIME"
  chown root:wheel "$RUNTIME"; chmod 0644 "$RUNTIME"
  say "runtime manifest written: $RUNTIME (app_python=$APP_PYTHON $APP_VER root:wheel 0644)"
fi

# 6) prove the ordinary user CANNOT modify launcher / approval / release / runtime manifest
if [ "$DRY" = 0 ]; then
  for f in "$DST_BIN" "$APPROVAL" "$RUNTIME" "$REL/.release_sha"; do
    if sudo -u "$USER_NAME" test -w "$f"; then die "PERMISSION LEAK: $USER_NAME can write $f"; fi
  done
  say "permission proof: $USER_NAME cannot write launcher/approval/runtime/release ✓"
fi

say "DONE. Next (owner): Phase 6 canary — repoint ONE benign plist's ProgramArguments to the BOOTSTRAP python:"
echo "    /usr/bin/python3 -I \"$DST_BIN\" canary"
echo "    (bootstrap = OS /usr/bin/python3 -I; the launcher then execs the release with the trusted 3.13 from runtime.json)"
say "Do NOT repoint the fleet until the canary + daily-cycle proofs pass."
