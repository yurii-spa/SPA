"""Equivalence of the cockpit build with and without the ledger read cache on FROZEN data and time."""
import sys, os, json, time, resource
from datetime import datetime, timezone
from pathlib import Path
mode, out = sys.argv[1], sys.argv[2]
F = Path("/private/tmp/claude-501/frozen_1016")
sys.path.insert(0, "/tmp/spa_wt_res2")
os.chdir(F / "repo")
try:  # evidence script, not delivered to prod (test_unsynced_hard_imports): run it from a worktree of the named commit
    from spa_core.utils import hash_ledger as hl
except ImportError as exc:  # noqa: BLE001
    raise SystemExit(f"run from a worktree of the evidence commit: {exc}")
if mode == "on":
    hl.enable_read_cache()
try:
    from spa_core.studio_os import mission_control as mc
except ImportError as exc:  # noqa: BLE001
    raise SystemExit(f"run from a worktree of the evidence commit: {exc}")
now = datetime.fromisoformat((F / "frozen_at.txt").read_text().strip().replace("Z", "+00:00"))
lc = (F / "launchctl.txt").read_text()
inp = mc.MCInputs(repo=F / "repo", mirror=F / "mirror", now=now, measure_host=False,
                  launchctl_full=lambda: lc, leases=lambda: [], mirror_synced_at=now)
t = time.time()
model = mc.build(inp)
dt = time.time() - t
json.dump(model, open(out, "w"), sort_keys=True, default=str, ensure_ascii=False)
print(json.dumps({"mode": mode, "seconds": round(dt, 1),
                  "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576, 1)}))
