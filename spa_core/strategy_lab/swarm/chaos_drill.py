"""Swarm block 5b — chaos drill: PROVE the immune layer actually catches each failure mode.

Charter: docs/SWARM_ARCHITECTURE.md · philosophy: the Resilience Plane (R-sprint) — a defense
that has never been exercised is dormant, not real. This drill copies the CURRENT live swarm
artifacts into a sandbox, injects each failure mode the immune layer claims to catch, and asserts
`swarm_health` actually flags it (and, as the control, stays OK on the untouched copy):

    control            untouched copy → overall OK (otherwise the drill can't prove anything)
    missing_organ      delete one status file → WARNING with "never ran"
    stale_organ        age one as_of_utc beyond the freshness budget → WARNING (not fresh)
    contract_break     levered book given a numeric reco WITHOUT depth → refusal invariant trips
    proof_tamper       mutate the last proof line without recomputing the hash → tamper flagged
    bad_regime         unknown regime value → contract check trips

Runs entirely against a sandbox copy — NEVER mutates data/swarm/ (only writes its own status
file). Fail-CLOSED: if the live artifacts are absent/degraded so the control itself isn't OK, the
drill reports all_ok=False with reason (an unexercisable immune system is a finding, not a pass).
Deterministic, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional

from spa_core.strategy_lab.swarm import swarm_health as sh
from spa_core.utils.atomic import atomic_save

__all__ = ["run_chaos_drill"]

REPO_ROOT = Path(__file__).resolve().parents[3]
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "chaos_drill_status.json"


def _copy_swarm(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for organ in sh.ORGANS.values():
        for key in ("status", "proof"):
            p = src / organ[key]
            if p.exists():
                shutil.copy2(p, dst / organ[key])


def _inject_missing(d: Path) -> str:
    (d / sh.ORGANS["blend_forward"]["status"]).unlink(missing_ok=True)
    return "blend_forward"


def _inject_stale(d: Path) -> str:
    p = d / sh.ORGANS["guardian_forward"]["status"]
    doc = json.loads(p.read_text())
    doc["as_of_utc"] = (datetime.now(timezone.utc)
                        - timedelta(hours=sh.FRESH_HOURS + 2)).isoformat(timespec="seconds")
    p.write_text(json.dumps(doc))
    return "guardian_forward"


def _inject_contract_break(d: Path) -> str:
    p = d / sh.ORGANS["leverage_brain"]["status"]
    doc = json.loads(p.read_text())
    books = doc.get("books") or {}
    books["__chaos_levered__"] = {"state": "RECOMMENDED", "leverage_reco": 4.0,
                                  "levered_shape": True, "factors": {"depth_factor": None}}
    doc["books"] = books
    p.write_text(json.dumps(doc))
    return "leverage_brain"


def _inject_proof_tamper(d: Path) -> str:
    p = d / sh.ORGANS["funding_regime"]["proof"]
    lines = [ln for ln in p.read_text().splitlines() if ln.strip()]
    rec = json.loads(lines[-1])
    rec["regime"] = "GREEN" if rec.get("regime") != "GREEN" else "RED"  # mutate, keep old hash
    lines[-1] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    return "funding_regime"


def _inject_bad_regime(d: Path) -> str:
    p = d / sh.ORGANS["funding_regime"]["status"]
    doc = json.loads(p.read_text())
    doc["regime"] = "SUPER_GREEN"
    p.write_text(json.dumps(doc))
    return "funding_regime"


SCENARIOS: List[tuple] = [
    ("missing_organ", _inject_missing),
    ("stale_organ", _inject_stale),
    ("contract_break", _inject_contract_break),
    ("proof_tamper", _inject_proof_tamper),
    ("bad_regime", _inject_bad_regime),
]


def run_chaos_drill(swarm_dir: Path = SWARM_DIR, out_dir: Optional[Path] = None) -> dict:
    """Execute all scenarios against sandbox copies. Writes chaos_drill_status.json."""
    out_dir = out_dir or swarm_dir
    now = datetime.now(timezone.utc)
    results: List[dict] = []

    with tempfile.TemporaryDirectory(prefix="swarm_chaos_") as tmp:
        tmp_root = Path(tmp)

        # control: the untouched copy must be OK, else nothing below is provable
        control_dir = tmp_root / "control"
        _copy_swarm(swarm_dir, control_dir)
        control = sh.run_swarm_health(swarm_dir=control_dir, out_dir=control_dir)
        control_ok = control["overall"] == "OK"
        results.append({"scenario": "control", "expected": "OK",
                        "observed": control["overall"], "ok": control_ok})

        if control_ok:
            for name, inject in SCENARIOS:
                d = tmp_root / name
                _copy_swarm(swarm_dir, d)
                try:
                    organ = inject(d)
                    verdict = sh.run_swarm_health(swarm_dir=d, out_dir=d)
                    organ_flagged = not verdict["organs"].get(organ, {}).get("ok", True)
                    ok = verdict["overall"] == "WARNING" and organ_flagged
                    results.append({"scenario": name, "expected": f"WARNING on {organ}",
                                    "observed": verdict["overall"],
                                    "organ_flagged": organ_flagged, "ok": ok})
                except Exception as exc:  # noqa: BLE001 — a crashing drill is a failed drill
                    results.append({"scenario": name, "ok": False,
                                    "error": f"{type(exc).__name__}: {exc}"})

    all_ok = all(r["ok"] for r in results) and len(results) == len(SCENARIOS) + 1
    doc = {
        "domain": "swarm.chaos_drill",
        "label": "SWARM immune-layer chaos drill / sandbox-only / proves detection, changes nothing",
        "is_advisory": True,
        "as_of_utc": now.isoformat(timespec="seconds"),
        "all_ok": all_ok,
        "scenarios": results,
        "note": ("all_ok=True means every injected failure mode was CAUGHT by swarm_health in a "
                 "sandbox copy (and the untouched control stayed OK). all_ok=False = the immune "
                 "layer has a hole or the live artifacts are too degraded to exercise — either "
                 "way a real finding. Live data/swarm/ is never mutated by this drill."),
    }
    atomic_save(doc, str(out_dir / STATUS_NAME))
    return doc


def main() -> int:
    doc = run_chaos_drill()
    print(f"swarm.chaos_drill: all_ok={doc['all_ok']}")
    for r in doc["scenarios"]:
        mark = "✅" if r["ok"] else "❌"
        print(f"  {mark} {r['scenario']:15s} expected={r.get('expected')} "
              f"observed={r.get('observed', r.get('error'))}")
    return 0 if doc["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
