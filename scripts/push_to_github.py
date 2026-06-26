#!/usr/bin/env python3
"""
scripts/push_to_github.py — THIN SHIM (no implementation lives here).

The single canonical implementation is the ROOT copy:
``/Users/yuriikulieshov/Documents/SPA_Claude/push_to_github.py``.

Historically there were TWO byte-identical copies of this file (root + scripts/)
that had to be kept manually in sync and DRIFTED before. This shim removes that
drift hazard: it imports the root module and re-exports every public symbol, so
both invocation paths keep working against ONE implementation.

Invocation paths preserved:
  * autopush / push_v*.sh (launchd):  python3 scripts/push_to_github.py --files ... --message ...
  * `cd <root>; python3 push_to_github.py ...`  (root copy, unchanged)
  * `import push_to_github` with scripts/ on sys.path  (re-exported symbols)

stdlib-only, deterministic. Contains no secrets and no logic of its own.
"""
import sys
from pathlib import Path

# The root copy is the canonical source. Put the project root on sys.path so we
# can import it whether this shim is run as a script (launchd PATH has no cwd
# guarantee) or imported via scripts/ being on sys.path.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Import the canonical module under an unambiguous name to avoid a self-import
# when scripts/ is the first entry on sys.path (both files are named
# push_to_github). We load the root file by its explicit path.
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("_push_to_github_root", _ROOT / "push_to_github.py")
_root_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_root_mod)

# Re-export the public API so `from push_to_github import push_file` etc. keep
# working through the shim, identical to the old duplicated copy.
get_pat = _root_mod.get_pat
git_blob_sha = _root_mod.git_blob_sha
get_file_sha = _root_mod.get_file_sha
push_file = _root_mod.push_file
main = _root_mod.main
REPO = _root_mod.REPO
API_BASE = _root_mod.API_BASE
PROJECT_ROOT = _root_mod.PROJECT_ROOT

# Also expose anything else public the root module may grow, so the shim never
# silently drops a symbol callers rely on.
for _name in dir(_root_mod):
    if not _name.startswith("_") and _name not in globals():
        globals()[_name] = getattr(_root_mod, _name)


if __name__ == "__main__":
    # Delegate the CLI verbatim to the canonical implementation. argparse in
    # main() reads sys.argv directly, so flags pass through unchanged.
    main()
