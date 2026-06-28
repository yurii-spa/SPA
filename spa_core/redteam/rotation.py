"""
spa_core/redteam/rotation.py — the rotating red-team scheduler + the hash-ANCHORED report.

WHY ROTATE
----------
Running all 7 surfaces every tick is fine for a smoke check, but the STANDING habit is "a different
surface gets adversarially probed every run" — so over a week the whole desk is continuously
red-teamed, the verdict is small, and a regression on ANY surface surfaces within a day. The
rotation is DETERMINISTIC by UTC day (``Surface.ALL[utc_ordinal % len]``), so the schedule is
reproducible and auditable (no RNG in the integrity path).

ANCHORED REPORT (the meta-claim is itself verifiable)
-----------------------------------------------------
The claim "we red-team ourselves" must be checkable, not asserted. So every rotation run:
  1. runs the chosen surface's scenarios (+ a fail-CLOSED live-data-untouched guard),
  2. computes a deterministic ``report_hash`` over the verdict body,
  3. APPENDS the verdict to the tamper-evident ``spa_core.audit.hash_chain`` (event_type
     ``redteam_verdict``) so a forged/edited historical red-team verdict breaks the chain,
  4. writes ``data/redteam_status.json`` ATOMICALLY (tmp + os.replace) with the verdict, the
     report_hash, and the chain anchor (seq / entry_hash) — the surface the /api/redteam endpoint and
     the dashboard panel read.

A consumer re-derives ``report_hash`` from the published verdict body and re-runs
``hash_chain.verify_chain()`` to confirm the anchor — the red-team report verifies itself.

stdlib-only · deterministic · fail-CLOSED · atomic · LLM-FORBIDDEN.

CLI:
    python3 -m spa_core.redteam.rotation              # run today's surface, write status, exit 0/1
    python3 -m spa_core.redteam.rotation --all        # run EVERY surface (full sweep)
    python3 -m spa_core.redteam.rotation --surface kill_switch
    python3 -m spa_core.redteam.rotation --no-anchor  # write status without appending to the chain
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from spa_core.redteam.base import Surface
from spa_core.redteam.registry import REGISTRY, covered_surfaces, scenarios_for_surface
from spa_core.redteam.runner import run_all

_ROOT = Path(__file__).resolve().parents[2]

REPORT_HASH_EVENT = "redteam_verdict"


def _data_dir() -> Path:
    """The data dir to WRITE status into. Honours SPA_DATA_DIR so a hermetic / pre-deploy-gate run
    (which exports SPA_DATA_DIR=<sandbox>) never writes the LIVE data/. Default = repo data/."""
    env = os.environ.get("SPA_DATA_DIR")
    return Path(env) if env else (_ROOT / "data")


def _status_path() -> Path:
    return _data_dir() / "redteam_status.json"


def surface_for_day(utc_date: Optional[datetime.date] = None) -> str:
    """The surface scheduled for a given UTC day — deterministic rotation over the surfaces that
    actually have a registered scenario (so the schedule never lands on an empty surface)."""
    d = utc_date or datetime.datetime.now(datetime.timezone.utc).date()
    surfaces = covered_surfaces() or list(Surface.ALL)
    return surfaces[d.toordinal() % len(surfaces)]


def report_hash(verdict_body: dict) -> str:
    """Deterministic SHA-256 over the canonical JSON of the verdict BODY (the fields a consumer
    re-derives). Excludes volatile/anchor fields (ts, the anchor block) so the same set of findings
    hashes identically run-to-run."""
    body = {
        "surface": verdict_body.get("surface"),
        "scope": verdict_body.get("scope"),
        "ok": verdict_body.get("ok"),
        "n": verdict_body.get("n"),
        "n_caught": verdict_body.get("n_caught"),
        "n_failed": verdict_body.get("n_failed"),
        "live_data_untouched": verdict_body.get("live_data_untouched"),
        # only the stable per-finding identity + outcome (not the free-text evidence) → reproducible.
        "findings": [
            {"scenario": f["scenario"], "surface": f["surface"], "ok": f["ok"],
             "caught": f["caught"], "control_ok": f["control_ok"], "attempted": f["attempted"]}
            for f in verdict_body.get("findings", [])
        ],
    }
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, obj: dict) -> None:
    """tmp + os.replace atomic write (repo rule #4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))


def run(*, surface: Optional[str] = None, run_all_surfaces: bool = False,
        anchor: bool = True, status_path: Optional[Path] = None,
        ts: Optional[str] = None) -> dict:
    """Run the scheduled (or chosen) surface's scenarios, hash-anchor the verdict, and write
    data/redteam_status.json atomically. Returns the full status dict.

    Args:
        surface:          a specific surface to probe (overrides the daily rotation).
        run_all_surfaces: probe EVERY registered scenario (full sweep) instead of one surface.
        anchor:           append the verdict to the tamper-evident hash_chain (default True).
        status_path:      override the status file (tests/hermetic).
        ts:               fixed timestamp for determinism (tests); default UTC now.
    """
    if run_all_surfaces:
        scope = "all"
        chosen_surface = "all"
        scens = list(REGISTRY)
    else:
        chosen_surface = surface or surface_for_day()
        scope = "surface"
        scens = scenarios_for_surface(chosen_surface)

    verdict = run_all(scens)
    verdict_body = {
        "surface": chosen_surface,
        "scope": scope,
        "rotation_surfaces": covered_surfaces(),
        **verdict,
    }
    rhash = report_hash(verdict_body)
    verdict_body["report_hash"] = rhash

    anchor_block = None
    if anchor:
        try:
            from spa_core.audit import hash_chain
            # Redirect the anchor chain to the active data dir so a hermetic / pre-deploy-gate run
            # (SPA_DATA_DIR=<sandbox>) anchors into the SANDBOX, never the live audit_chain.jsonl.
            _orig_chain = hash_chain._CHAIN
            env = os.environ.get("SPA_DATA_DIR")
            if env:
                hash_chain._CHAIN = Path(env) / "audit_chain.jsonl"
            try:
                entry = hash_chain.append(
                    REPORT_HASH_EVENT,
                    {"surface": chosen_surface, "scope": scope, "ok": verdict_body["ok"],
                     "n": verdict_body["n"], "n_caught": verdict_body["n_caught"],
                     "n_failed": verdict_body["n_failed"], "report_hash": rhash},
                    ts=ts,
                )
                chain_valid = hash_chain.verify_chain().get("valid")
            finally:
                hash_chain._CHAIN = _orig_chain
            anchor_block = {
                "anchored": True,
                "event_type": REPORT_HASH_EVENT,
                "seq": entry["seq"],
                "entry_hash": entry["entry_hash"],
                "prev_hash": entry["prev_hash"],
                "chain_valid": chain_valid,
            }
        except Exception as exc:  # noqa: BLE001 — anchoring must never abort the verdict write
            anchor_block = {"anchored": False, "error": repr(exc)}

    status = {
        "schema": "redteam_status.v1",
        "ts": ts or verdict["ts"],
        "report_hash": rhash,
        "anchor": anchor_block,
        "verdict": verdict_body,
        # a consumer re-derives report_hash from verdict and re-runs hash_chain.verify_chain().
        "reproduce": {
            "report_hash": "sha256(canonical_json(verdict_body_stable_fields))",
            "canonical_json_rule": "json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)",
            "anchor_chain": "data/audit_chain.jsonl (verify with spa_core.audit.hash_chain.verify_chain)",
            "note": "the red-team verdict is itself hash-anchored so 'we red-team ourselves' is verifiable.",
        },
    }
    _atomic_write_json(status_path or _status_path(), status)
    return status


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Rotating red-team scheduler + anchored report.")
    ap.add_argument("--surface", default=None, help="probe this surface (overrides daily rotation)")
    ap.add_argument("--all", action="store_true", help="probe EVERY surface (full sweep)")
    ap.add_argument("--no-anchor", action="store_true", help="do not append the verdict to the chain")
    ap.add_argument("--json", action="store_true", help="print the full status JSON")
    args = ap.parse_args(argv)

    status = run(surface=args.surface, run_all_surfaces=args.all, anchor=not args.no_anchor)
    v = status["verdict"]
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(f"red-team [{v['surface']}] scope={v['scope']}: caught {v['n_caught']}/{v['n']} "
              f"failed={v['n_failed']} live_untouched={v['live_data_untouched']} "
              f"report_hash={status['report_hash'][:16]}… "
              f"anchored={(status['anchor'] or {}).get('anchored')}")
        if not v["ok"]:
            for f in v["findings"]:
                if not f["ok"]:
                    print(f"  ✗ {f['surface']}/{f['scenario']}: "
                          f"{f['error'] or f['evidence']}")
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
