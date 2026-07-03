#!/usr/bin/env python3
"""deploy_site_snapshot.py — Site Custodian block 1: auto-deploy the fresh snapshot after each cycle.

The daily cycle writes data/golive_status.json + data/equity_curve_daily.json (+ paper_trading_status).
This regenerates landing/src/data/track_snapshot.json from them and, if it CHANGED, commits + pushes it
so the existing .github/workflows/deploy-landing.yml (triggers on `landing/**`) rebuilds the public site
with no manual step — target lag <= 30 min after the cycle.

Deterministic, fail-safe, logged. No push if the snapshot is unchanged (avoid empty deploys). Uses the
repo's canonical push_to_github_batch.py (PAT from Keychain — never in code). Called from
scripts/run_daily_paper_cycle.sh after the cycle. Safe to run standalone.
"""
# LLM_FORBIDDEN
import hashlib
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SNAP = _ROOT / "landing" / "src" / "data" / "track_snapshot.json"
_GEN = _ROOT / "scripts" / "generate_track_snapshot.py"
_PUSH = _ROOT / "push_to_github_batch.py"
_PY = sys.executable


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def main() -> int:
    before = _sha(_SNAP)
    # 1. regenerate from the freshly-written committed data
    r = subprocess.run([_PY, str(_GEN)], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        print("deploy_site_snapshot: generator FAILED — not deploying", file=sys.stderr)
        return 1
    after = _sha(_SNAP)
    if after == before:
        print("deploy_site_snapshot: snapshot unchanged — no deploy needed")
        return 0
    # 2. push ONLY the snapshot -> deploy-landing.yml rebuilds the site (landing/** trigger)
    p = subprocess.run(
        [_PY, str(_PUSH), "--files", str(_SNAP),
         "--message", "chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle"],
        capture_output=True, text=True, timeout=180,
    )
    print(p.stdout.strip() or p.stderr.strip())
    if p.returncode != 0:
        print("deploy_site_snapshot: push FAILED", file=sys.stderr)
        return 1
    print("deploy_site_snapshot: pushed fresh snapshot -> deploy-landing triggered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
