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
USER_NAME="${SUDO_USER:-$(id -un)}"   # under sudo: the real invoking user; else the current (non-root) user
DRY=0; LAUNCHER=""; LSHA=""; REPO=""; APPROVED=""; RUNTIME=""; RDIGEST=""; VERIFY_ONLY=""
while [ $# -gt 0 ]; do case "$1" in
  --launcher) LAUNCHER="$2"; shift 2;; --launcher-sha256) LSHA="$2"; shift 2;;
  --repo) REPO="$2"; shift 2;; --approved) APPROVED="$2"; shift 2;;
  --runtime) RUNTIME="$2"; shift 2;; --runtime-digest) RDIGEST="$2"; shift 2;;
  --verify-runtime) VERIFY_ONLY="$2"; shift 2;;
  --dry-run) DRY=1; shift;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
say(){ echo "[trusted-bootstrap] $*"; }
die(){ echo "[trusted-bootstrap] FAIL-CLOSED: $*" >&2; exit 1; }
run(){ if [ "$DRY" = 1 ]; then echo "  [dry] $*"; else "$@"; fi; }
rt_digest(){ ( cd "$1" && find . -type f -not -path '*/__pycache__/*' -not -name 'runtime_bundle.json' | LC_ALL=C sort | while read -r f; do shasum -a 256 "$f"; done | shasum -a 256 | cut -d' ' -f1 ); }

# WHOLE-TREE read-only verification of an installed/candidate runtime. Never modifies the tree. `who` is the
# identity that must not be able to write (default USER_NAME). Fails CLOSED (exit 1) on the first violation.
verify_runtime_tree(){ # $1=dir $2=expected_digest [$3=who] [$4=require_root]
  local D="$1" EXP="$2" WHO="${3:-$USER_NAME}" REQROOT="${4:-0}"
  [ -f "$D/bin/python3" ] || die "runtime $D: bin/python3 missing (regular file)"
  local SL; SL=$(find "$D" -type l 2>/dev/null); [ -z "$SL" ] || die "runtime $D: symlink present ($SL)"
  [ "$(rt_digest "$D")" = "$EXP" ] || die "runtime $D: digest != $EXP"
  # writability: no file OR directory anywhere may be writable by WHO (WHO-owned + user-write, or group/other-write)
  local W; W=$(find "$D" -user "$WHO" -perm -0200 -print -quit 2>/dev/null)
  [ -z "$W" ] || die "runtime $D: object writable by $WHO ($W)"
  local W2; W2=$(find "$D" \( -perm -0020 -o -perm -0002 \) -print -quit 2>/dev/null)
  [ -z "$W2" ] || die "runtime $D: group/other-writable object ($W2)"
  if [ "$REQROOT" = 1 ]; then
    local NR; NR=$(find "$D" ! -user root -print -quit 2>/dev/null)
    [ -z "$NR" ] || die "runtime $D: non-root-owned object ($NR)"
  fi
  "$D/bin/python3" -E -s -c "import sys;assert sys.version_info[:2]==(3,13)" 2>/dev/null || die "runtime $D: 3.13 smoke failed"
  "$D/bin/python3" -E -s -S -c "import sys,os;assert os.path.realpath(sys.prefix)==os.path.realpath('$D');assert not [p for p in sys.path if p and ('miniconda' in p or os.path.expanduser('~/Library') in p)]" 2>/dev/null \
    || die "runtime $D: relocation/isolation failed"
}

# read-only diagnostic mode: verify a runtime tree and exit (no install, no root needed)
if [ -n "$VERIFY_ONLY" ]; then
  [ -n "$RDIGEST" ] || die "--verify-runtime needs --runtime-digest"
  verify_runtime_tree "$VERIFY_ONLY" "$RDIGEST" "$USER_NAME" 0
  say "runtime tree verified (0 symlink, digest, non-writable, smoke, isolation): $VERIFY_ONLY"; exit 0
fi

[ -n "$LAUNCHER" ] && [ -n "$LSHA" ] && [ -n "$REPO" ] && [ -n "$APPROVED" ] || die "missing required arg"
[ -n "$RUNTIME" ] && [ -n "$RDIGEST" ] || die "missing --runtime <staged bundle dir> --runtime-digest <sha256>"
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || die "needs root (sudo); for review: bash $0 --dry-run ..."

# 0) verify the STAGED runtime bundle (zero symlinks, digest, version, relocation)
[ -f "$RUNTIME/bin/python3" ] || die "runtime bundle exe $RUNTIME/bin/python3 missing (must be a regular file)"
[ -d "$RUNTIME/lib/python3.13" ] || die "runtime bundle stdlib missing"
# ZERO-SYMLINK HARD GATE (the digest hashes regular files; a symlink would escape it)
SL=$(find "$RUNTIME" -type l 2>/dev/null); [ -z "$SL" ] || die "runtime bundle contains symlink(s): $SL"
APP_VER=$("$RUNTIME/bin/python3" -E -s -c "import sys;print('%d.%d.%d'%sys.version_info[:3])" 2>/dev/null) || die "runtime does not run"
case "$APP_VER" in 3.13.*) : ;; *) die "runtime is $APP_VER, expected 3.13.x" ;; esac
GOTD=$(rt_digest "$RUNTIME")
[ "$GOTD" = "$RDIGEST" ] || die "runtime digest $GOTD != reviewed $RDIGEST (tampered/unexpected bundle)"
"$RUNTIME/bin/python3" -E -s -S -c "import sys,os;assert os.path.realpath(sys.prefix)==os.path.realpath('$RUNTIME'),sys.prefix;assert not [p for p in sys.path if p and ('miniconda' in p or os.path.expanduser('~/Library') in p)]" \
  || die "runtime does not relocate / user path on sys.path"
say "runtime bundle verified: $APP_VER digest $RDIGEST (0 symlinks, relocatable, stdlib-only)"
RID="python-3.13-${RDIGEST:0:16}"
RUNTIME_DST="$ROOT/toolchains/$RID"
APP_PYTHON="$RUNTIME_DST/bin/python3"
run mkdir -p "$ROOT/toolchains"

if [ "$DRY" = 1 ]; then
  echo "  [dry] IMMUTABLE ATOMIC INSTALL: TEMP=$ROOT/toolchains/.tmp-$RID → verify → atomic mv → $RUNTIME_DST"
  echo "  [dry]   if $RUNTIME_DST exists: verify (digest/symlinks/perms/smoke) → REUSE or FAIL-CLOSED; NEVER auto-delete"
elif [ -d "$RUNTIME_DST" ]; then
  # A) already installed → verify the WHOLE tree read-only, REUSE or FAIL CLOSED; NEVER delete/repair/chmod/chown.
  #    verify_runtime_tree touches nothing; on any violation it dies and the existing runtime is left byte-for-byte.
  verify_runtime_tree "$RUNTIME_DST" "$RDIGEST" "$USER_NAME" 1
  say "runtime already installed, WHOLE TREE verified (0 symlink, digest, root-owned, non-writable, smoke, isolation) — REUSED untouched: $RUNTIME_DST"
else
  # B) not installed → build into a TEMP inside the trusted root, verify everything, then ATOMIC rename
  TEMP="$ROOT/toolchains/.tmp-$RID.$$"; rm -rf "$TEMP"
  trap 'rm -rf "$TEMP"' EXIT
  cp -R "$RUNTIME" "$TEMP"
  chown -R root:wheel "$TEMP"; chmod -R go-w "$TEMP"; find "$TEMP" -type f -exec chmod a-w {} +; chmod 0755 "$TEMP/bin/python3"
  SL3=$(find "$TEMP" -type l 2>/dev/null); [ -z "$SL3" ] || die "TEMP has symlink(s) after copy: $SL3"
  [ "$(rt_digest "$TEMP")" = "$RDIGEST" ] || die "TEMP digest mismatch after copy"
  "$TEMP/bin/python3" -E -s -S -c "import sys,os;assert os.path.realpath(sys.prefix)==os.path.realpath('$TEMP')" || die "TEMP does not relocate"
  if sudo -u "$USER_NAME" test -w "$TEMP/bin/python3" || \
     [ -n "$(sudo -u "$USER_NAME" find "$TEMP" -writable -print -quit 2>/dev/null)" ]; then
    die "TEMP runtime has a component writable by $USER_NAME — NOT trusted"
  fi
  mv "$TEMP" "$RUNTIME_DST"          # ATOMIC publish (same filesystem); TEMP never visible as final
  trap - EXIT
  say "runtime installed atomically root-owned read-only: $RUNTIME_DST ($APP_VER); $USER_NAME cannot write it ✓"
fi

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

# 5b) runtime.json → root:wheel 0644. The launcher reads app_python from HERE (root-owned), never
#     sys.executable (=3.9 bootstrap) and never the approval file. Points at the installed trusted bundle.
RUNTIME_JSON="$ROOT/runtime.json"
if [ "$DRY" = 1 ]; then echo "  [dry] write $RUNTIME_JSON = {app_python:$APP_PYTHON, runtime_id:$RID, runtime_digest:$RDIGEST}; chown root:wheel; chmod 0644"; else
  printf '{"app_python": "%s", "app_python_version": "%s", "runtime_id": "%s", "runtime_digest": "%s"}\n' "$APP_PYTHON" "$APP_VER" "$RID" "$RDIGEST" > "$RUNTIME_JSON"
  chown root:wheel "$RUNTIME_JSON"; chmod 0644 "$RUNTIME_JSON"
  say "runtime.json written: $RUNTIME_JSON (app_python=$APP_PYTHON $APP_VER digest $RDIGEST root:wheel 0644)"
fi

# 6) prove the ordinary user CANNOT modify launcher / approval / release / runtime manifest
if [ "$DRY" = 0 ]; then
  for f in "$DST_BIN" "$APPROVAL" "$RUNTIME_JSON" "$REL/.release_sha"; do
    if sudo -u "$USER_NAME" test -w "$f"; then die "PERMISSION LEAK: $USER_NAME can write $f"; fi
  done
  say "permission proof: $USER_NAME cannot write launcher/approval/runtime/release ✓"
fi

say "DONE. Next (owner): Phase 6 canary — repoint ONE benign plist's ProgramArguments to the BOOTSTRAP python:"
echo "    /usr/bin/python3 -I \"$DST_BIN\" canary"
echo "    (bootstrap = OS /usr/bin/python3 -I; the launcher then execs the release with the trusted 3.13 from runtime.json)"
say "Do NOT repoint the fleet until the canary + daily-cycle proofs pass."
