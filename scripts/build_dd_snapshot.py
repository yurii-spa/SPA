#!/usr/bin/env python3
"""Q2-10 — self-contained reproducible DD data snapshot (deterministic, offline-verifiable).

Freezes SPA's cleanly-reproducing proof surfaces into data/dd_snapshot/ with a SNAPSHOT_MANIFEST.json
that PINS the verifier's expected output (reproduced decision-chain head + surfaces + ok verdict) and the
exact offline replay command. A funder clones the snapshot and runs the standalone verifier OFFLINE — no
live API, no trust in us — and gets a PASS that matches the pinned head. Reproducibility no longer depends
on the live endpoint.

HONEST scope: the ANCHORS surface (C) is EXCLUDED on purpose — it is unsound at index 0 by the known
re-based ring-buffer mirror issue ([[rates-desk-anchor-mirror-unsound]], roadmap Q1-4), so freezing it
would ship a known-broken surface. The snapshot pins the surfaces that DO reproduce cleanly (A decision
chain, B exit-NAV, D equity track) and records the exclusion + reason in the manifest (documented, never
hidden). stdlib-only (hashlib/shutil), fail-OPEN on a missing source (recorded), advisory / read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Clean-reproducing proof surfaces to freeze (source rel path → arcname in the snapshot).
_SURFACES = [
    ("data/rates_desk/decision_log.jsonl", "decision_log.jsonl", "A", "rates-desk decision chain"),
    ("data/rates_desk/exit_nav.json", "exit_nav.json", "B", "exit-NAV per-row proofs"),
    ("data/rates_desk/equity_track.jsonl", "equity_track.jsonl", "D", "evidenced equity track"),
]
_EXCLUDED = [{
    "surface": "C", "name": "anchors.jsonl",
    "reason": "excluded — anchors are unsound at index 0 (re-based ring-buffer mirror, roadmap Q1-4); "
              "shipping them would freeze a known-broken surface. The three surfaces above reproduce cleanly.",
}]

OUT_DIR = ROOT / "data" / "dd_snapshot"


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build(out_dir: Path = OUT_DIR, now: datetime | None = None) -> dict:
    from scripts import verify_spa
    now = now or datetime.now(timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = []
    for rel, arc, letter, desc in _SURFACES:
        src = ROOT / rel
        dst = out_dir / arc
        if src.is_file():
            data = src.read_bytes()
            dst.write_bytes(data)
            files.append({"arcname": arc, "surface": letter, "desc": desc,
                          "sha256": _sha256(data), "bytes": len(data)})
        else:
            files.append({"arcname": arc, "surface": letter, "desc": desc,
                          "sha256": None, "bytes": 0, "absent": True})

    # Run the standalone verifier against the frozen snapshot → pin its reproduced output.
    frozen = [str(out_dir / f["arcname"]) for f in files if f.get("sha256")]
    report = verify_spa.run(frozen)
    head = ((report.get("decision_chain") or {}).get("head_hash"))
    surfaces = sorted(f["surface"] for f in files if f.get("sha256"))
    replay_cmd = (f"python3 scripts/verify_spa.py <snapshot_dir> "
                  f"--expect-head {head} --expect-surfaces {','.join(surfaces)}")
    # one-flag equivalent (Q2-10): --offline reads THIS manifest, checksums every pinned file, and
    # auto-applies expected_decision_head + expected_surfaces — the funder needn't copy them by hand.
    offline_cmd = "python3 scripts/verify_spa.py <snapshot_dir> --offline"

    manifest = {
        "model": "spa_dd_snapshot_manifest",
        "generated_at": now.isoformat(),
        "is_advisory": True,
        "deterministic": True,
        "verifier_ok": bool(report.get("ok")),
        "verifier_errors": report.get("errors", []),
        "expected_decision_head": head,
        "expected_surfaces": surfaces,
        "replay_command": replay_cmd,
        "offline_command": offline_cmd,
        "files": files,
        "excluded_surfaces": _EXCLUDED,
        "note": ("Frozen, offline-verifiable DD snapshot. Clone it, then run the offline_command (or the "
                 "explicit replay_command) — the standalone verifier checksums every pinned file against "
                 "this manifest AND re-derives the decision-chain head from the raw files with ZERO "
                 "dependencies, asserting it equals expected_decision_head. No live API, no trust in us. "
                 "The anchors surface is excluded (known-unsound, documented). Advisory / read-only."),
    }
    (out_dir / "SNAPSHOT_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the offline-verifiable SPA DD data snapshot")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    m = build(out_dir=Path(args.out_dir) if args.out_dir else OUT_DIR)
    print(f"[build_dd_snapshot] verifier_ok={m['verifier_ok']} head={str(m['expected_decision_head'])[:16]} "
          f"surfaces={m['expected_surfaces']}")
    print(f"  replay: {m['replay_command']}")
    print(f"  → wrote {OUT_DIR}/SNAPSHOT_MANIFEST.json")
    return 0 if m["verifier_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
