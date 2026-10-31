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
DRY=0; LAUNCHER=""; LSHA=""; REPO=""; APPROVED=""; RUNTIME=""; RDIGEST=""; VERIFY_ONLY=""; SELF_TEST_ROOT=""; SELF_TEST_APP=""
while [ $# -gt 0 ]; do case "$1" in
  --launcher) LAUNCHER="$2"; shift 2;; --launcher-sha256) LSHA="$2"; shift 2;;
  --repo) REPO="$2"; shift 2;; --approved) APPROVED="$2"; shift 2;;
  --runtime) RUNTIME="$2"; shift 2;; --runtime-digest) RDIGEST="$2"; shift 2;;
  --verify-runtime) VERIFY_ONLY="$2"; shift 2;;
  --self-test-root) SELF_TEST_ROOT="$2"; shift 2;; --self-test-app-python) SELF_TEST_APP="$2"; shift 2;;
  --dry-run) DRY=1; shift;; *) echo "unknown arg $1" >&2; exit 2;; esac; done
say(){ echo "[trusted-bootstrap] $*"; }
die(){ echo "[trusted-bootstrap] FAIL-CLOSED: $*" >&2; exit 1; }
run(){ if [ "$DRY" = 1 ]; then echo "  [dry] $*"; else "$@"; fi; }
rt_digest(){ ( cd "$1" && find . -type f -not -path '*/__pycache__/*' -not -name 'runtime_bundle.json' | LC_ALL=C sort | while read -r f; do shasum -a 256 "$f"; done | shasum -a 256 | cut -d' ' -f1 ); }

# WHOLE-TREE read-only verification of an installed/candidate runtime. Never modifies the tree. `who` is the
# identity that must not be able to write (default USER_NAME). Fails CLOSED (exit 1) on the first violation.
BOOTSTRAP_PY="${STUDIO_BOOTSTRAP_PY:-/usr/bin/python3}"   # OS python for the as-user verifier (accessible, root:wheel)

verify_runtime_tree(){ # $1=dir $2=expected_digest [$3=who] [$4=require_root]
  local D="$1" EXP="$2" WHO="${3:-$USER_NAME}" REQROOT="${4:-0}"
  # do not let a diagnostic run claim verification for an identity it is not actually executing as (FIRST)
  if [ "$(id -u)" != 0 ] && [ "$WHO" != "$(id -un)" ]; then
    die "verify must run AS $WHO (root uses sudo -u); current identity is $(id -un) — refuse to certify for $WHO"
  fi
  # run a command AS the intended ordinary user: sudo -u when we are root (install), else directly (verify mode)
  runas(){ if [ "$(id -u)" = 0 ]; then sudo -u "$WHO" "$@"; else "$@"; fi; }
  [ -f "$D/bin/python3" ] || die "runtime $D: bin/python3 missing (regular file)"
  # 1) AS-USER EFFECTIVE tree verification (walked + os.access → honors ACLs, not just mode bits): accessibility,
  #    listability/traversal, actual file readability, EFFECTIVE non-writability, object-type + symlink rejection,
  #    and (require_root) root ownership. Exit status is authoritative; diagnostics retained.
  local out st
  set +e
  out=$(runas "$BOOTSTRAP_PY" -E -s - "$D" "$REQROOT" <<'PYV' 2>&1
import os, sys, stat
root, reqroot = sys.argv[1], (sys.argv[2] == "1")
bad, errs = [], []
def add(k, p):
    if len(bad) < 50: bad.append("%s: %s" % (k, p))
for dp, dirs, files in os.walk(root, onerror=lambda e: errs.append("walk:%s" % e)):
    dst = os.lstat(dp)
    if not stat.S_ISDIR(dst.st_mode): add("nondir", dp)
    if reqroot and dst.st_uid != 0: add("dir_not_root_owned", dp)
    if not os.access(dp, os.R_OK | os.X_OK): add("dir_not_listable_or_traversable", dp)
    if os.access(dp, os.W_OK): add("dir_writable_by_user", dp)          # effective — honors ACLs
    if dst.st_mode & 0o022: add("dir_group_or_other_writable", dp)      # mode-bit hygiene (any non-owner write)
    for d in list(dirs):
        if os.path.islink(os.path.join(dp, d)): add("symlink_dir", os.path.join(dp, d))
    for f in files:
        p = os.path.join(dp, f); ls = os.lstat(p)
        if stat.S_ISLNK(ls.st_mode): add("symlink", p); continue
        if not stat.S_ISREG(ls.st_mode): add("nonregular_object", p); continue
        if reqroot and ls.st_uid != 0: add("file_not_root_owned", p)
        if not os.access(p, os.R_OK): add("file_unreadable", p)          # actual readability, not just -print
        if os.access(p, os.W_OK): add("file_writable_by_user", p)        # effective — honors ACLs
        if ls.st_mode & 0o022: add("file_group_or_other_writable", p)    # mode-bit hygiene
if errs:
    sys.stderr.write("\n".join(errs[:20]) + "\n"); sys.exit(2)           # accessibility failure (traversal)
if bad:
    sys.stderr.write("\n".join(bad[:20]) + "\n"); sys.exit(1)
print("USER_TREE_OK")
PYV
)
  st=$?
  set -e
  [ "$st" = 0 ] || die "runtime $D: as-user ($WHO) tree verification FAILED exit=$st — $(printf '%s' "$out" | grep -v USER_TREE_OK | head -1)"
  # 2) content digest (content only; independent of permissions)
  [ "$(rt_digest "$D")" = "$EXP" ] || die "runtime $D: digest != $EXP"
  # 3) startup + relocation + isolation AS WHO — proves the fleet user can actually run the interpreter
  local se
  se=$(runas "$D/bin/python3" -E -s -c "import sys;assert sys.version_info[:2]==(3,13)" 2>&1) \
    || die "runtime $D: 3.13 startup as $WHO failed — $(printf '%s' "$se" | tail -1)"
  se=$(runas "$D/bin/python3" -E -s -S -c "import sys,os;assert os.path.realpath(sys.prefix)==os.path.realpath('$D');assert not [p for p in sys.path if p and ('miniconda' in p or os.path.expanduser('~/Library') in p)]" 2>&1) \
    || die "runtime $D: relocation/isolation as $WHO failed — $(printf '%s' "$se" | tail -1)"
}

# ── RELEASE MATERIALISATION (S2 T08, E5.3) — ONE code path for the real install AND the isolated self-test ──
# No rm: a new release dir is RESERVED with mkdir (an existing one is never replaced), extracted from LOCAL git
# objects, its composition proven by the INSTALLED launcher's own inline verifier (the sha256-checked artifact —
# no second trust mechanism), and the stamp is written LAST. Failure keeps the copy for inspection, FAIL-CLOSED.
launcher_composition(){ # $1=launcher file $2=release dir $3=sha $4=repo → prints "" (proven) or the problem
  "$BOOTSTRAP_PY" -I - "$1" "$2" "$3" "$4" <<'PYL'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("installed_release_launcher", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
files = m.trusted_tree(sys.argv[3], sys.argv[4])
if files is None:
    print("UNVERIFIABLE: no trusted tree of the approved commit"); sys.exit(0)
print(m._composition_problem(sys.argv[2], files) or "")
PYL
}

materialise_release_dir(){ # $1=releases dir $2=approved sha $3=repo $4=launcher file $5=require cycle_runner (1/0)
  local RD="$1" SHA="$2" RP="$3" LF="$4" REQ="$5" DEST="$1/$2" prob
  if [ -e "$DEST" ] || [ -L "$DEST" ]; then
    prob=$(launcher_composition "$LF" "$DEST" "$SHA" "$RP") || die "composition check could not run for $DEST"
    [ -z "$prob" ] && [ "$(cat "$DEST/.release_sha" 2>/dev/null)" = "$SHA" ] \
      || die "existing release dir is NOT proven ($prob${prob:+; }stamp=$(cat "$DEST/.release_sha" 2>/dev/null || echo none)) — KEPT untouched: $DEST"
    say "release dir already present and PROVEN against the approved commit — reused untouched: $DEST"
    MATERIALISED_NEW=0; return 0
  fi
  mkdir -p "$RD"
  mkdir "$DEST" || die "cannot reserve $DEST (someone else created it) — nothing replaced"
  git -C "$RP" archive --format=tar "$SHA" | tar -x -C "$DEST" || die "materialise failed — partial copy KEPT: $DEST"
  prob=$(launcher_composition "$LF" "$DEST" "$SHA" "$RP") || die "composition check could not run — copy KEPT: $DEST"
  [ -z "$prob" ] || die "release composition != approved commit ($prob) — copy KEPT, no stamp: $DEST"
  if [ "$REQ" = 1 ]; then [ -f "$DEST/spa_core/paper_trading/cycle_runner.py" ] || die "release incomplete: cycle_runner missing — copy KEPT: $DEST"; fi
  printf '%s' "$SHA" > "$DEST/.release_sha"                    # stamp LAST
  MATERIALISED_NEW=1
  say "release materialised + composition PROVEN by the installed launcher: $DEST"
}

write_runtime_json(){ # $1=path $2=app_python $3=version $4=runtime_id $5=digest $6=trusted repo
  printf '{"app_python": "%s", "app_python_version": "%s", "runtime_id": "%s", "runtime_digest": "%s", "trusted_repo": "%s"}\n' \
    "$2" "$3" "$4" "$5" "$6" > "$1"
}

# ISOLATED SELF-TEST of the two functions above (S2 T08): a temporary root, never as root, never the real root.
if [ -n "$SELF_TEST_ROOT" ]; then
  [ "$(id -u)" != 0 ] || die "--self-test-root refuses to run as root"
  case "$(cd "$SELF_TEST_ROOT" 2>/dev/null && pwd -P)" in ""|"$ROOT"|"$ROOT"/*) die "--self-test-root must be an existing directory outside $ROOT";; esac
  [ -n "$LAUNCHER" ] && [ -n "$LSHA" ] && [ -n "$REPO" ] && [ -n "$APPROVED" ] || die "missing required arg"
  [ "$(shasum -a 256 "$LAUNCHER" | cut -d' ' -f1)" = "$LSHA" ] || die "launcher sha256 != expected $LSHA"
  git -C "$REPO" cat-file -e "${APPROVED}^{commit}" 2>/dev/null || die "approved sha $APPROVED not in local objects at $REPO"
  T_BIN="$SELF_TEST_ROOT/bin/release_launcher-$LSHA.py"; mkdir -p "$SELF_TEST_ROOT/bin"
  [ -f "$T_BIN" ] || { cp "$LAUNCHER" "$T_BIN"; chmod 0444 "$T_BIN"; }
  materialise_release_dir "$SELF_TEST_ROOT/releases" "$APPROVED" "$REPO" "$T_BIN" 0
  printf '{"approved_sha": "%s"}\n' "$APPROVED" > "$SELF_TEST_ROOT/approved_release.json"
  write_runtime_json "$SELF_TEST_ROOT/runtime.json" "${SELF_TEST_APP:-NOT_INSTALLED}" "self-test" "self-test" "self-test" "$REPO"
  say "SELF-TEST done (user-owned root, nothing root-owned, nothing outside $SELF_TEST_ROOT): new=$MATERIALISED_NEW"
  exit 0
fi

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
  # B) not installed → build into a TEMP inside the trusted root, NORMALISE permissions, verify AS THE
  #    INTENDED USER, then ATOMIC rename. Publish only after the fleet user is proven able to run it.
  TEMP="$ROOT/toolchains/.tmp-$RID.$$"; rm -rf "$TEMP"
  trap 'rm -rf "$TEMP"' EXIT
  cp -R "$RUNTIME" "$TEMP"
  chown -R root:wheel "$TEMP"
  # EXPLICIT installed permission model (the source may be 0700/0600; do NOT preserve it):
  #   directories 0755 (root write; everyone traverse+list) · library files 0644 (root write; everyone read)
  #   executable  0755 (root write; everyone read+execute). All root-owned ⇒ the fleet user has read/exec, NOT write.
  find "$TEMP" -type d -exec chmod 0755 {} +
  find "$TEMP" -type f -exec chmod 0644 {} +
  chmod 0755 "$TEMP/bin/python3"
  # verify the WHOLE tree AS THE INTENDED USER before publication (accessibility, symlink, digest, ownership,
  # non-writability, startup, relocation, isolation). This would have caught the 0700-unreadable defect.
  verify_runtime_tree "$TEMP" "$RDIGEST" "$USER_NAME" 1
  mv "$TEMP" "$RUNTIME_DST"          # ATOMIC publish (same filesystem); TEMP never visible as final
  trap - EXIT
  say "runtime installed atomically, whole tree verified AS $USER_NAME (accessible, non-writable, runs): $RUNTIME_DST ($APP_VER) ✓"
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

# 4) materialise the approved release (S2 T08): reserve → git archive → composition PROVEN by the installed
#    launcher → stamp last; an existing dir is reused only if proven, otherwise KEPT and the install fails closed.
if [ "$DRY" = 1 ]; then echo "  [dry] materialise_release_dir $ROOT/releases $APPROVED (mkdir reservation; git archive | tar; launcher composition proof; stamp last; NO rm)"; else
  materialise_release_dir "$ROOT/releases" "$APPROVED" "$REPO" "$DST_BIN" 1
  if [ "$MATERIALISED_NEW" = 1 ]; then
    chown -R root:wheel "$REL"; chmod -R a-w "$REL"; chmod -R o+rX,g+rX "$REL"
  fi
  [ "$(cat "$REL/.release_sha")" = "$APPROVED" ] || die "release stamp mismatch after install"
  say "release ready: $REL (root:wheel, read-only)"
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
if [ "$DRY" = 1 ]; then echo "  [dry] write $RUNTIME_JSON = {app_python:$APP_PYTHON, runtime_id:$RID, runtime_digest:$RDIGEST, trusted_repo:$REPO}; chown root:wheel; chmod 0644"; else
  write_runtime_json "$RUNTIME_JSON" "$APP_PYTHON" "$APP_VER" "$RID" "$RDIGEST" "$REPO"
  chown root:wheel "$RUNTIME_JSON"; chmod 0644 "$RUNTIME_JSON"
  say "runtime.json written: $RUNTIME_JSON (app_python=$APP_PYTHON $APP_VER digest $RDIGEST trusted_repo=$REPO root:wheel 0644)"
fi

# 6) prove the ordinary user CANNOT modify launcher / approval / release / runtime manifest
if [ "$DRY" = 0 ]; then
  for f in "$DST_BIN" "$APPROVAL" "$RUNTIME_JSON" "$REL/.release_sha"; do
    if sudo -u "$USER_NAME" test -w "$f"; then die "PERMISSION LEAK: $USER_NAME can write $f"; fi
  done
  say "permission proof: $USER_NAME cannot write launcher/approval/runtime/release ✓"
fi

# 6b) APPROVED-RELEASE IMPORT as the fleet user (SEPARATE step: the release is materialised at step 4, AFTER
#     the runtime TEMP verification at step 0, so this end-to-end check runs here once both are installed —
#     before any canary). Proves the trusted 3.13 can import the approved release paths as the ordinary user.
if [ "$DRY" = 0 ]; then
  IMPERR=$(cd "$REL" && sudo -u "$USER_NAME" "$APP_PYTHON" -E -s -c "import importlib;[importlib.import_module(m) for m in ['spa_core.monitoring.deployment_acceptance','spa_core.paper_trading.cycle_runner','spa_core.orchestrator.adapter_orchestrator']]" 2>&1) \
    || die "approved-release import as $USER_NAME FAILED — $(printf '%s' "$IMPERR" | tail -1)"
  say "approved-release imports as $USER_NAME on the trusted runtime ✓ (canary-ready)"
fi

say "DONE. Next (owner): Phase 6 canary — repoint ONE benign plist's ProgramArguments to the BOOTSTRAP python:"
echo "    /usr/bin/python3 -I \"$DST_BIN\" canary"
echo "    (bootstrap = OS /usr/bin/python3 -I; the launcher then execs the release with the trusted 3.13 from runtime.json)"
say "Do NOT repoint the fleet until the canary + daily-cycle proofs pass."
