"""spa_core/monitoring/resource_cleanup.py — the daily allow-listed cleanup + orphan report (ADR-551).

Runs as com.spa.resource_cleanup (05:40). Three steps, in order:
1. remove ONLY allow-listed disposable directories past their TTL
   (``architecture/resource_policy.json`` → ``cleanup.disposable_dirs``; links never followed;
   ``never_touch`` honoured; each removal logged to ``data/resource_cleanup_log.jsonl``);
2. linked git worktrees ONLY through ``scripts/reap_stale_worktrees.py`` (idle ≥ 24 h, every changed
   path proven delivered or superseded, archived before removal — anything unproven stays);
3. write the orphan & supervision report ``data/orphan_report.json`` — it deletes nothing.

Exit code 2 when the reaper or the orphan report could not be measured (never «clean» by silence).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from spa_core.monitoring import resource_guard as rg

#: Contract (ADR-154/158): what this agent PRODUCES.
PRODUCES = ("data/resource_cleanup_log.jsonl", "data/orphan_report.json")


def run(*, data_dir: Path, policy: Optional[dict] = None, reap: bool = True, orphans: bool = True) -> dict:
    policy = policy or rg.load_policy()
    unmeasured: list = []
    cands = rg.cleanup_candidates(policy, unmeasured=unmeasured)
    removed = [d for d in rg.apply_cleanup(cands, policy, log_path=data_dir / "resource_cleanup_log.jsonl")
               if d.get("removed")]
    out = {"mode": "maintenance", "disposable_removed": len(removed),
           "disposable_gb": round(sum(d.get("bytes") or 0 for d in removed) / rg.GB, 2),
           "unmeasured_roots": unmeasured}
    if reap:
        wt = rg.reap_worktrees(apply=True)
        out["worktrees"] = {k: wt.get(k) for k in ("state", "rc", "counts", "base_read", "reason")}
    if orphans:
        try:
            from spa_core.studio_os import orphans as _orph
            from spa_core.utils.atomic import atomic_save
            rep = _orph.report()
            atomic_save(rep, str(data_dir / "orphan_report.json"))
            out["orphan_findings"] = rep["total"]
        except Exception as exc:  # noqa: BLE001 — named NOT MEASURED, never silently skipped
            out["orphan_findings"] = f"{rg.UNMEASURED}: {type(exc).__name__}: {exc}"
    return out


def main(argv: Optional[list[str]] = None) -> int:
    from spa_core.utils.live_paths import live_data_dir
    res = run(data_dir=Path(live_data_dir()))
    print(json.dumps(res, ensure_ascii=False, default=str))
    ok = (isinstance(res.get("orphan_findings"), int) and (res.get("worktrees") or {}).get("state") == rg.OK
          and not res.get("unmeasured_roots"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
