#!/usr/bin/env python3
"""Q2-9 — one-command hostile-reviewer DATA-ROOM bundle (deterministic, self-verifying).

Emits a single timestamped .zip a diligence reviewer clones and checks OFFLINE — "don't trust us, check
us" made turnkey. The bundle contains the standalone verifier, the honest fundability/DD sheets, the
hash-chained refusal/decision log, and the fresh safety-evidence artifacts — plus a MANIFEST.json that
lists every file with its sha256 so the reviewer can re-hash and confirm nothing was altered, and a
README with the exact reproduce commands (run the verifier, pull the live full-chain, re-derive the DD).

stdlib-only (zipfile + hashlib), fail-OPEN on a missing source (recorded in the manifest as absent, never
fabricated). Advisory: read-only, never touches the live track / RiskPolicy / execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "dataroom"

# (source path relative to repo root, arcname in the zip, one-line description)
ARTIFACTS = [
    ("scripts/verify_spa.py", "verifier/verify_spa.py", "standalone proof-chain verifier — run it yourself"),
    ("docs/FUNDABILITY.md", "docs/FUNDABILITY.md", "honest fundability sheet (realized-only, tail shown)"),
    ("docs/DD_PACK.md", "docs/DD_PACK.md", "structured due-diligence data-room (auto-generated, real data)"),
    ("docs/PILOT_ONE_PAGER.md", "docs/PILOT_ONE_PAGER.md", "pilot one-pager"),
    ("docs/STRUCTURAL_DESK.md", "docs/STRUCTURAL_DESK.md", "research arc + capacity verdicts"),
    ("data/rates_desk/decision_log.jsonl", "proof/decision_log.jsonl", "hash-chained refusal + entry log"),
    ("data/refusal_status.json", "proof/refusal_status.json", "per-underlying SAFE/WATCH/REFUSE"),
    ("data/rates_desk/refusal_value.json", "proof/refusal_value.json", "avoided-loss refusal P&L ledger"),
    ("data/rates_desk/n_book_capacity.json", "proof/n_book_capacity.json", "N-book above-floor scale curve"),
    ("data/kill_switch_drill_status.json", "proof/kill_switch_drill_status.json", "dated emergency-stop drill evidence"),
    ("data/data_trust_status.json", "proof/data_trust_status.json", "tournament data-trust monitor"),
]

_FULL_CHAIN = [
    "https://api.earn-defi.com/api/rates-desk/full-chain/decision_log",
    "https://api.earn-defi.com/api/rates-desk/full-chain/equity_track",
    "https://api.earn-defi.com/api/rates-desk/full-chain/anchors",
    "https://api.earn-defi.com/api/rates-desk/proof",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _readme(entries: list, generated_at: str) -> str:
    lines = [
        "# SPA data-room — self-verifying diligence bundle",
        "",
        f"Generated: {generated_at}",
        "",
        "This bundle is the turnkey \"don't trust us, check us\" package. Every file is listed in",
        "MANIFEST.json with its sha256 — re-hash and compare to confirm nothing was altered.",
        "",
        "## Verify integrity of THIS bundle",
        "```",
        "python3 - <<'PY'",
        "import hashlib, json",
        "m = json.load(open('MANIFEST.json'))",
        "for f in m['files']:",
        "    if f.get('sha256') is None: continue",
        "    h = hashlib.sha256(open(f['arcname'],'rb').read()).hexdigest()",
        "    print(('OK ' if h==f['sha256'] else 'MISMATCH '), f['arcname'])",
        "PY",
        "```",
        "",
        "## Re-run the proof yourself",
        "```",
        "python3 verifier/verify_spa.py .            # proof chain intact (offline where possible)",
        "```",
        "",
        "## Pull the LIVE full-chain (independent of this snapshot)",
        "```",
        *[f"curl -s {u}" for u in _FULL_CHAIN],
        "```",
        "",
        "## What's inside",
    ]
    for e in entries:
        mark = "" if e["sha256"] else "  (ABSENT at build time — not fabricated)"
        lines.append(f"- `{e['arcname']}` — {e['desc']}{mark}")
    lines += [
        "",
        "HONEST framing: numbers are evidence-tagged (L0–L6); backtest figures are labelled backtest, never",
        "realized. The differentiator is the refusal log + published NO-GO + reproducible verifier, not a rate.",
        "",
    ]
    return "\n".join(lines)


def build(out_dir: Path = OUT_DIR, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    generated_at = now.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"spa_dataroom_{stamp}.zip"

    entries = []
    payloads = {}
    for rel, arc, desc in ARTIFACTS:
        src = ROOT / rel
        if src.is_file():
            data = src.read_bytes()
            payloads[arc] = data
            entries.append({"arcname": arc, "source": rel, "desc": desc,
                            "sha256": _sha256(data), "bytes": len(data)})
        else:
            entries.append({"arcname": arc, "source": rel, "desc": desc,
                            "sha256": None, "bytes": 0})

    manifest = {
        "model": "spa_dataroom_manifest",
        "generated_at": generated_at,
        "is_advisory": True,
        "n_files": sum(1 for e in entries if e["sha256"]),
        "n_absent": sum(1 for e in entries if not e["sha256"]),
        "files": entries,
        "live_full_chain": _FULL_CHAIN,
        "note": ("Self-verifying: re-hash each file and compare to its sha256. Absent files are recorded, "
                 "never fabricated. Advisory / read-only — reproduces the public proof, moves no capital."),
    }
    readme = _readme(entries, generated_at)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, data in payloads.items():
            z.writestr(arc, data)
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        z.writestr("README.md", readme)
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the self-verifying SPA data-room bundle")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    path = build(out_dir=Path(args.out_dir) if args.out_dir else OUT_DIR)
    with zipfile.ZipFile(path) as z:
        n = len(z.namelist())
    print(f"[build_dataroom] wrote {path} ({n} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
