#!/bin/bash
# recover_trusted_runtime.sh — narrowly-scoped OWNER recovery for a trusted runtime that is content-correct but
# INACCESSIBLE to the fleet user (the Checkpoint-D 0700 defect). OWNER-RUN, sudo. NOT executed during dev.
#
# It touches ONLY the one content-addressed runtime directory, preserving launcher/release/approval/runtime.json.
# It does NOT re-run the full bootstrap installer (which fails-closed on the broken runtime and would needlessly
# rewrite those artifacts). Atomic, reversible, fail-closed. NOT a general deployment framework.
#
# Recovery state machine (explicit — cleanup behaviour is decided by the phase reached):
#   INIT → PREPARE → TEMP_VERIFIED → QUARANTINED → PUBLISHED
#     • before QUARANTINED: a failure may clean ONLY a TEMP THIS invocation created; existing runtime untouched.
#     • at QUARANTINED (publish did not finish): NEVER auto-delete quarantine; if TEMP still exists PRESERVE it;
#       do NOT auto-restore the known-broken runtime (rollback-to-broken != restoration-of-service); STOP.
#     • at PUBLISHED: post-publish verification is mandatory (already run before we reach this state).
#
# Modes (explicit — a bare/incorrect invocation mutates NOTHING):
#   --dry-run   report only, no mutation, no root needed
#   --execute   perform the recovery (requires root)
set -euo pipefail
# ROOT defaults to the production trusted plane; STUDIO_TRUSTED_ROOT is a TEST-ONLY seam (mirrors the installer's
# STUDIO_BOOTSTRAP_PY) so the guard logic can be exercised in a sandbox without root. Production sets no such env.
ROOT="${STUDIO_TRUSTED_ROOT:-/Library/Application Support/StudioOS}"
TOOLCHAINS="$ROOT/toolchains"
USER_NAME="${SUDO_USER:-$(id -un)}"                       # the FLEET user (NOT root, even under sudo)
INSTALLER_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE=""; RUNTIME=""; RDIGEST=""
while [ $# -gt 0 ]; do case "$1" in
  --runtime) RUNTIME="$2"; shift 2;; --runtime-digest) RDIGEST="$2"; shift 2;;
  --dry-run) MODE="dry"; shift;; --execute) MODE="execute"; shift;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done
say(){ echo "[recover] $*"; }
die(){ echo "[recover] FAIL-CLOSED: $*" >&2; exit 1; }

# ── recovery state (drives cleanup) ─────────────────────────────────────────────
STATE="INIT"          # INIT|PREPARE|TEMP_VERIFIED|QUARANTINED|PUBLISHED
TEMP_OWNED=0          # 1 only after THIS invocation atomically created $TEMP (mkdir)
LOCK_OWNED=0          # 1 only after THIS invocation atomically created $LOCK

# (15) explicit execution mode — no mode ⇒ refuse, mutate nothing
[ "$MODE" = dry ] || [ "$MODE" = execute ] || die "specify exactly one of --dry-run | --execute (nothing mutated)"
DRY=0; [ "$MODE" = dry ] && DRY=1
[ -n "$RUNTIME" ] && [ -n "$RDIGEST" ] || die "need --runtime <staged good bundle> --runtime-digest <sha256>"
case "$RDIGEST" in *[!0-9a-f]* | "") die "runtime-digest must be lowercase hex";; esac

# ── --execute hardened preconditions — ALL enforced BEFORE any mutation ──────────
if [ "$DRY" = 0 ]; then
  # (item 1) the trusted root MUST be exactly production; STUDIO_TRUSTED_ROOT is a --dry-run/test seam ONLY.
  #          Checked on BOTH the resolved root and the env var (not merely relying on sudo env filtering).
  [ "$ROOT" = "/Library/Application Support/StudioOS" ] \
    || die "--execute refuses a non-production trusted root ($ROOT) — STUDIO_TRUSTED_ROOT is a test/--dry-run seam only"
  [ -z "${STUDIO_TRUSTED_ROOT:-}" ] \
    || die "--execute refuses with STUDIO_TRUSTED_ROOT set — unset the test seam for real recovery"
  # (item 2) execution model: ordinary fleet user → sudo. Never certify the runtime as root; never an
  #          arbitrary root/login shell. Require euid 0 AND a real, non-root, resolvable SUDO_USER.
  [ "$(id -u)" = 0 ] || die "--execute needs root (sudo); review with --dry-run"
  [ -n "${SUDO_USER:-}" ] || die "--execute requires sudo FROM a fleet user (SUDO_USER unset — refuse root/login shell)"
  [ "$SUDO_USER" != root ] || die "--execute refuses SUDO_USER=root — recovery must run as an ordinary fleet user via sudo"
  _fuid=$(id -u "$SUDO_USER" 2>/dev/null) || die "--execute cannot resolve uid for fleet user '$SUDO_USER'"
  [ -n "$_fuid" ] && [ "$_fuid" != 0 ] \
    || die "--execute refuses fleet uid 0 ('$SUDO_USER') — the runtime must never be certified as root"
fi

RID="python-3.13-${RDIGEST:0:16}"
DST="$TOOLCHAINS/$RID"
QUAR="$TOOLCHAINS/.quarantine-$RID.$(date -u +%Y%m%dT%H%M%SZ)"
TEMP="$TOOLCHAINS/.recover-$RID.$$"
LOCK="$TOOLCHAINS/.recover.lock"
rt_digest(){ ( cd "$1" && find . -type f -not -path '*/__pycache__/*' -not -name 'runtime_bundle.json' | LC_ALL=C sort | while read -r f; do shasum -a 256 "$f"; done | shasum -a 256 | cut -d' ' -f1 ); }
VERIFY(){ bash "$INSTALLER_DIR/install_trusted_bootstrap.sh" --verify-runtime "$1" --runtime-digest "$RDIGEST" \
          --launcher x --launcher-sha256 x --repo x --approved x --runtime x; }
realp(){ /usr/bin/python3 -c "import os,sys;print(os.path.realpath(sys.argv[1]))" "$1"; }

# (2) destination MUST resolve strictly under the trusted toolchains root
case "$(realp "$DST")/" in "$(realp "$TOOLCHAINS")"/*) : ;; *) die "destination $DST escapes $TOOLCHAINS";; esac
# (3) basename must match the content-addressed runtime named in the trusted runtime.json
[ -f "$ROOT/runtime.json" ] || die "runtime.json missing — cannot confirm expected runtime"
CFG_RID=$(/usr/bin/python3 -E -s -c "import json,sys;print(json.load(open(sys.argv[1])).get('runtime_id',''))" "$ROOT/runtime.json")
CFG_APP=$(/usr/bin/python3 -E -s -c "import json,sys;print(json.load(open(sys.argv[1])).get('app_python',''))" "$ROOT/runtime.json")
[ "$CFG_RID" = "$RID" ] || die "runtime.json runtime_id ($CFG_RID) != recovery target ($RID)"
[ "$CFG_APP" = "$DST/bin/python3" ] || die "runtime.json app_python ($CFG_APP) != $DST/bin/python3"

# (1) preconditions: control files preserved; existing runtime present, NOT a symlink, digest matches, but FAILS as-user verify
for f in "$ROOT/approved_release.json" "$ROOT/runtime.json"; do [ -f "$f" ] || die "control file missing: $f"; done
ls "$ROOT"/bin/release_launcher-*.py >/dev/null 2>&1 || die "launcher missing"
ls -d "$ROOT"/releases/* >/dev/null 2>&1 || die "approved release missing"
[ -e "$DST" ] || die "no existing runtime at $DST — use the installer, not recovery"
# (5) existing target must not be a symlink
[ -L "$DST" ] && die "existing runtime $DST is a symlink — refuse"
[ -d "$DST" ] || die "existing runtime $DST is not a directory — refuse"
# (4) digest verified — needs root to read a root-owned 0700 tree; enforced under --execute, deferred in dry-run
GOTD=$(rt_digest "$DST" 2>/dev/null || true)
if [ "$GOTD" != "$RDIGEST" ]; then
  [ "$DRY" = 1 ] && say "note: cannot read root-owned runtime as $(id -un) — digest check deferred to --execute (root)" \
                 || die "existing runtime digest ($GOTD) != $RDIGEST — not the expected broken runtime; refuse"
fi

# (Point 4) refuse if the runtime is referenced by an ACTIVE production launchd workload.
#   Recovery runs under sudo/root, but StudioOS workloads run as the FLEET USER's LaunchAgents, which live in that
#   user's GUI domain (gui/<uid>), NOT in root's context. A root `launchctl list` cannot prove visibility of the
#   fleet user's GUI domain, and under sudo $HOME is root's home — so we resolve the fleet user's uid + home
#   deterministically and probe gui/<uid>/<label> (LaunchAgents) and system/<label> (LaunchDaemons) by exit status.
FLEET_UID=$(id -u "$USER_NAME" 2>/dev/null) || die "cannot resolve uid for fleet user $USER_NAME"
FLEET_HOME=$(dscl . -read "/Users/$USER_NAME" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
[ -n "$FLEET_HOME" ] || FLEET_HOME=$(eval echo "~$USER_NAME")
[ -d "$FLEET_HOME" ] || die "fleet user home not resolvable ($USER_NAME → '$FLEET_HOME') — cannot prove launchd visibility"
say "launchd domains checked: gui/$FLEET_UID (user LaunchAgents under $FLEET_HOME/Library/LaunchAgents) + system (LaunchDaemons)"
ACTIVE=""
for pl in "$FLEET_HOME"/Library/LaunchAgents/com.spa.*.plist; do
  [ -f "$pl" ] || continue
  lbl="com.spa.$(basename "$pl" .plist | sed 's/^com\.spa\.//')"
  grep -qE "release_launcher-|$RID" "$pl" 2>/dev/null || continue
  if launchctl print "gui/$FLEET_UID/$lbl" >/dev/null 2>&1; then ACTIVE="$ACTIVE gui/$FLEET_UID/$lbl"; fi
done
for pl in /Library/LaunchDaemons/com.spa.*.plist; do
  [ -f "$pl" ] || continue
  lbl="com.spa.$(basename "$pl" .plist | sed 's/^com\.spa\.//')"
  grep -qE "release_launcher-|$RID" "$pl" 2>/dev/null || continue
  if launchctl print "system/$lbl" >/dev/null 2>&1; then ACTIVE="$ACTIVE system/$lbl"; fi
done
[ -z "$ACTIVE" ] || die "runtime is referenced by ACTIVE launchd workload(s):$ACTIVE — refuse (owner-approved active recovery is a separate procedure)"

say "BEFORE evidence:"; ls -la "$DST" 2>&1 | sed 's/^/    /' | head -4
if VERIFY "$DST" >/dev/null 2>&1; then die "existing runtime already PASSES as-user verify — recovery not needed"; fi
say "confirmed: broken runtime present (correct digest, fails as-user verify), not active, not a symlink"

[ "$DRY" = 1 ] && { say "[dry] would: mkdir lock; create sibling TEMP (must not pre-exist); build+verify TEMP; mv DST→QUARANTINE; mv TEMP→DST; verify as $USER_NAME; keep quarantine"; say "[dry] no mutation performed."; exit 0; }

# ── cleanup driven by STATE (see header) ────────────────────────────────────────
cleanup(){
  local rc=$?
  case "$STATE" in
    INIT|PREPARE|TEMP_VERIFIED)
      # nothing quarantined yet — remove ONLY a TEMP we created; existing runtime is untouched by construction
      [ "$TEMP_OWNED" = 1 ] && [ -d "$TEMP" ] && rm -rf "$TEMP" 2>/dev/null
      ;;
    QUARANTINED)
      # publish did not complete: PRESERVE TEMP + quarantine; do NOT auto-restore the broken runtime
      echo "[recover] FAIL-CLOSED: publish did not complete. $DST may be EMPTY → launcher fails-closed APP_RUNTIME_MISSING (NO execution)." >&2
      echo "[recover] PRESERVED: quarantine=$QUAR ; TEMP=$TEMP (if present). Broken runtime NOT restored (rollback-to-broken != restoration-of-service). STOP and escalate." >&2
      ;;
    PUBLISHED)
      : # success — TEMP was consumed by the publish rename; quarantine kept intentionally
      ;;
  esac
  [ "$LOCK_OWNED" = 1 ] && rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT

# (12) concurrent-invocation lock — mkdir is atomic on macOS; we own it only if mkdir succeeded
mkdir "$LOCK" 2>/dev/null || die "another recovery is in progress ($LOCK exists) — refuse"
LOCK_OWNED=1

# (1/2/6) TEMP: sibling of DST; must NOT pre-exist as ANY object (incl. dangling symlink); we claim it atomically.
STATE="PREPARE"
[ "$(dirname "$TEMP")" = "$TOOLCHAINS" ] || die "TEMP not a sibling of the runtime target"
if [ -e "$TEMP" ] || [ -L "$TEMP" ]; then
  die "TEMP path already exists as a filesystem object (or dangling symlink): $TEMP — refuse; will NOT delete an unknown/pre-existing TEMP"
fi
mkdir "$TEMP" 2>/dev/null || die "could not atomically create TEMP $TEMP (raced or pre-existing) — refuse"
TEMP_OWNED=1                                       # from here, cleanup may remove TEMP — but only pre-quarantine
# populate the owned TEMP with the staged good bundle's CONTENTS (TEMP stays the same dir we created)
cp -R "$RUNTIME/." "$TEMP/"; chown -R root:wheel "$TEMP"
find "$TEMP" -type d -exec chmod 0755 {} +; find "$TEMP" -type f -exec chmod 0644 {} +; chmod 0755 "$TEMP/bin/python3"
VERIFY "$TEMP" || die "corrected TEMP failed full as-user verification — existing runtime UNTOUCHED"
STATE="TEMP_VERIFIED"
say "corrected TEMP built + verified AS $USER_NAME (existing runtime still untouched)"

# (3/7) QUARANTINE: sibling of DST; must NOT pre-exist as ANY object incl. dangling symlink; (9) never auto-deleted
[ "$(dirname "$QUAR")" = "$TOOLCHAINS" ] || die "quarantine not a sibling of the runtime target"
if [ -e "$QUAR" ] || [ -L "$QUAR" ]; then
  die "quarantine path already exists as a filesystem object (or dangling symlink): $QUAR — refuse (no deletion/replacement)"
fi
mv "$DST" "$QUAR" || die "quarantine rename failed — NOTHING changed, existing runtime intact"
STATE="QUARANTINED"                                # from here, cleanup PRESERVES TEMP + quarantine
say "quarantined broken runtime → $QUAR (kept until explicit cleanup approval)"

# PUBLISH (atomic). If this fails, STATE stays QUARANTINED ⇒ cleanup preserves TEMP + quarantine and STOPs.
mv "$TEMP" "$DST" || die "PUBLISH failed after quarantine: $DST is EMPTY → launcher fails-closed APP_RUNTIME_MISSING (no execution). Quarantine + TEMP preserved. Do NOT restore the broken quarantine (still broken). STOP and escalate."
# publish consumed TEMP (it is now $DST); disown TEMP so cleanup never touches the published runtime
TEMP_OWNED=0
# (11) full as-user verification again after publish — mandatory
VERIFY "$DST" || die "published runtime FAILED post-publish verify — quarantine kept at $QUAR. STOP."
STATE="PUBLISHED"
say "PUBLISHED + verified AS $USER_NAME: $DST"
say "AFTER evidence:"; ls -la "$DST" 2>&1 | sed 's/^/    /' | head -4
say "control files preserved (launcher/release/approval/runtime.json untouched); quarantine kept: $QUAR"
say "Run full Checkpoint D as the fleet user before any canary. Quarantine cleanup requires SEPARATE approval: sudo rm -rf \"$QUAR\""
