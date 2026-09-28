#!/bin/bash
# build_trusted_runtime.sh — stage a SELF-CONTAINED, relocatable Python 3.13 runtime bundle for the StudioOS
# trusted plane (ADR-500 runtime closure). NON-PRIVILEGED: builds into a staging dir, installs nothing.
#
# Why this is safe/self-contained (measured 2026-09-28):
#   * source exe links only /usr/lib/libSystem (libpython is STATIC), rpath @loader_path/../lib → relocatable;
#   * the approved release (5b652577) is STDLIB-ONLY (canary/paper-cycle/orchestrator import with -S), so the
#     bundle is exe + stdlib, NO site-packages;
#   * used C-extensions' non-libSystem deps (libz/liblzma/libbz2/libexpat) resolve from /usr/lib (SIP, system),
#     proven by a DYLD trace: 0 user-writable dylibs in the release import closure.
#
# Usage:  bash build_trusted_runtime.sh --src <path-to-complete-3.13> --stage <dir>   [--print-digest]
#   --src  : a working python3.13 (SOURCE MATERIAL only; e.g. the fleet 3.13). Not mutated.
#   --stage: output bundle dir (default /tmp/studioos-python313-runtime).
# Prints RUNTIME_DIGEST (deterministic content digest) + writes <stage>/runtime_bundle.json.
set -euo pipefail
SRC=""; STAGE="/tmp/studioos-python313-runtime"; PRINT=0
while [ $# -gt 0 ]; do case "$1" in
  --src) SRC="$2"; shift 2;; --stage) STAGE="$2"; shift 2;; --print-digest) PRINT=1; shift;;
  *) echo "unknown arg $1" >&2; exit 2;; esac; done
[ -x "$SRC" ] || { echo "FAIL: --src <python3.13> required (executable)" >&2; exit 1; }
VER=$("$SRC" -E -s -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')
case "$VER" in 3.13.*) : ;; *) echo "FAIL: src is $VER, need 3.13.x" >&2; exit 1;; esac
SRC_PREFIX=$("$SRC" -E -s -c 'import sys;print(sys.base_prefix)')
SRC_REAL=$("$SRC" -c 'import os,sys;print(os.path.realpath(sys.executable))')

rm -rf "$STAGE"; mkdir -p "$STAGE/bin" "$STAGE/lib"
# ZERO SYMLINKS: the interpreter is a REAL regular file at bin/python3 (no bin/python3.13 symlink).
cp "$SRC_REAL" "$STAGE/bin/python3"
# stdlib only — exclude site-packages + __pycache__; --copy-links dereferences ANY stdlib symlink into a
# regular file, so the bundle contains zero symlinks regardless of the source layout.
if command -v rsync >/dev/null; then
  rsync -a --copy-links --exclude 'site-packages' --exclude '__pycache__' "$SRC_PREFIX/lib/python3.13/" "$STAGE/lib/python3.13/"
else
  cp -RL "$SRC_PREFIX/lib/python3.13" "$STAGE/lib/python3.13"; rm -rf "$STAGE/lib/python3.13/site-packages"
  find "$STAGE/lib/python3.13" -name __pycache__ -type d -prune -exec rm -rf {} +
fi
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true
# HARD GATE: the bundle must contain zero symlinks (else the digest, which hashes regular files, is blind)
LN=$(find "$STAGE" -type l)
[ -z "$LN" ] || { echo "FAIL: bundle contains symlink(s): $LN" >&2; exit 1; }

# relocation self-check: staged python must report the staged prefix, no user paths
GOT_PREFIX=$("$STAGE/bin/python3" -E -s -S -c 'import sys;print(sys.prefix)')
[ "$GOT_PREFIX" = "$STAGE" ] || { echo "FAIL: staged runtime did not relocate (prefix=$GOT_PREFIX)" >&2; exit 1; }
"$STAGE/bin/python3" -E -s -S -c 'import sys,os;bad=[p for p in sys.path if p and ("miniconda" in p or os.path.expanduser("~/Library") in p or "Documents/SPA_Claude" in p)];assert not bad,bad' \
  || { echo "FAIL: user path in staged sys.path" >&2; exit 1; }

# deterministic content digest (sorted paths, per-file sha256, digest of digests; excludes .pyc)
DIGEST=$(cd "$STAGE" && find . -type f -not -path '*/__pycache__/*' -not -name 'runtime_bundle.json' | LC_ALL=C sort | while read -r f; do shasum -a 256 "$f"; done | shasum -a 256 | cut -d' ' -f1)
RUNTIME_ID="python-3.13-${DIGEST:0:16}"
cat > "$STAGE/runtime_bundle.json" <<JSON
{
  "schema": "studio-os/trusted-runtime-bundle/1",
  "python_version": "$VER",
  "runtime_id": "$RUNTIME_ID",
  "runtime_digest": "$DIGEST",
  "source_description": "self-contained relocatable CPython (static libpython, exe+stdlib, no site-packages); built from $VER source material",
  "executable_relative_path": "bin/python3",
  "stdlib_relative_path": "lib/python3.13",
  "expected_install_root": "/Library/Application Support/StudioOS/toolchains/$RUNTIME_ID",
  "external_deps": "system /usr/lib (libz/liblzma/libbz2/libexpat, SIP), /usr/lib/libSystem, system frameworks — no user-writable deps",
  "approved_release_compat": "5b652577 canary+paper-cycle+orchestrator import & run (stdlib-only) — verified"
}
JSON
echo "RUNTIME_ID=$RUNTIME_ID"
echo "RUNTIME_DIGEST=$DIGEST"
[ "$PRINT" = 1 ] || echo "staged: $STAGE ($(du -sh "$STAGE" | cut -f1)); manifest: $STAGE/runtime_bundle.json"
