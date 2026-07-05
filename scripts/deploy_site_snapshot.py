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


# Volatile fields that change every regeneration (wall-clock stamps) and must be IGNORED when
# deciding whether a deploy is warranted — otherwise every run looks "changed" and pushes noise.
_VOLATILE = ("generated_at",)


def _meaningful(d: dict) -> dict:
    """Snapshot content minus volatile wall-clock fields, for change detection."""
    return {k: v for k, v in d.items() if k not in _VOLATILE}


def _origin_snapshot():
    """track_snapshot.json as it currently exists on origin/main — the DEPLOY TRUTH (parsed), or None.

    We compare the freshly-generated snapshot against ORIGIN, not against the previous LOCAL copy:
    the local working tree drifts from origin (pushes go via the GitHub API, not `git push`), so a
    local file that is already fresh while origin is stale would otherwise read as "unchanged" and
    the push would be skipped forever — origin stuck a day behind (the recurring stale-site bug).
    Returns None if origin can't be read → caller pushes to be safe (never silently skip).
    """
    try:
        import base64
        import json as _json
        import urllib.request

        pat = subprocess.run(
            ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if not pat:
            return None
        req = urllib.request.Request(
            "https://api.github.com/repos/yurii-spa/SPA/contents/"
            "landing/src/data/track_snapshot.json?ref=main",
            headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _json.loads(base64.b64decode(_json.load(resp)["content"]))
    except Exception as e:  # noqa: BLE001 — fail-safe: unreadable origin => push (don't silently skip)
        print(f"deploy_site_snapshot: could not read origin snapshot ({e}) — will push to be safe")
        return None


def main() -> int:
    import json

    # 1. regenerate from the freshly-written committed data
    r = subprocess.run([_PY, str(_GEN)], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        print("deploy_site_snapshot: generator FAILED — not deploying", file=sys.stderr)
        return 1
    # 2. deploy only if the MEANINGFUL content differs from ORIGIN (deploy truth), ignoring the
    #    volatile generated_at stamp — and NOT vs the previous local copy (local drifts from origin).
    local = json.loads(_SNAP.read_text())
    origin = _origin_snapshot()
    if origin is not None and _meaningful(origin) == _meaningful(local):
        print("deploy_site_snapshot: snapshot matches origin/main (data identical) — no deploy needed")
        return 0
    # 3. push ONLY the snapshot -> deploy-landing.yml rebuilds the site (landing/** trigger)
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
