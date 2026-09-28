"""Deterministic repo/promotion status (ADR-494) — answers CANONICAL / CANDIDATE / PRODUCTION and the
sync state so a persistent OS never has ambiguous code ownership. Network-free by default (reads local
refs); flags when the canonical ref may be stale vs the true remote. No CI platform, just a read model."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROD = Path.home() / "Documents" / "SPA_Claude"
MIRROR = Path.home() / "Documents" / "SPA_mirror"
CANONICAL_REF = "origin/main"


def _git(args, cwd=REPO):
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _sha(ref, cwd=REPO):
    return _git(["rev-parse", ref], cwd)


def _count(range_expr, cwd=REPO):
    out = _git(["rev-list", "--count", range_expr], cwd)
    try:
        return int(out)
    except (TypeError, ValueError):
        return None


def _remote_sha(timeout=8):
    try:
        r = subprocess.run(["git", "ls-remote", "origin", "main"], cwd=str(REPO),
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()[0]
    except Exception:
        pass
    return None


def status(check_remote: bool = False) -> dict:
    candidate = _sha("HEAD")
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    canonical_local = _sha(CANONICAL_REF)
    production = _sha("HEAD", cwd=PROD) if (PROD / ".git").exists() or PROD.exists() else None
    mirror = _sha("HEAD", cwd=MIRROR) if MIRROR.exists() else None
    remote = _remote_sha() if check_remote else None

    # candidate vs canonical (both in this tree's object db)
    ahead = _count(f"{CANONICAL_REF}..HEAD")
    behind = _count(f"HEAD..{CANONICAL_REF}")
    if candidate == canonical_local:
        cand_state = "IN_SYNC"
    elif ahead and not behind:
        cand_state = "AHEAD"          # candidate has commits not on canonical → promotion possible
    elif behind and not ahead:
        cand_state = "BEHIND"
    elif ahead and behind:
        cand_state = "DIVERGED"
    else:
        cand_state = "UNKNOWN"

    # production vs canonical — cross-tree; compare by SHA equality (precise ancestry needs a shared objdb)
    if production and canonical_local:
        prod_state = "IN_SYNC" if production == canonical_local else "DIVERGED_OR_STALE"
    else:
        prod_state = "UNKNOWN"

    # canonical staleness vs the true remote (only if we checked)
    canonical_stale = (remote is not None and canonical_local is not None and remote != canonical_local)

    deployment_required = bool(candidate and production and candidate != production and cand_state in ("AHEAD", "DIVERGED"))

    # Release-state (PROPOSED ADR-500): CANONICAL vs STAGED (on-disk, autosync target) vs ACTIVE (running).
    # production.sha above is the production git HEAD — it is NOT what is executing (the autosync checks out
    # code paths without touching HEAD), so it must never be read as ACTIVE. The `release` block is the truth.
    from spa_core.studio_os.release_state import release_state
    release = release_state(canonical_local, prod=PROD)
    # deployment is required whenever newer code is staged than is provably active (or ACTIVE is unproven).
    deployment_required = deployment_required or release["restart_would_activate"] or release["active_sha"] == "UNKNOWN"

    return {
        "schema": "studio-os/repo-status/1",
        "policy": "ADR-494 + ADR-500(PROPOSED)",
        "canonical": {"ref": CANONICAL_REF, "sha": canonical_local, "sha_short": (canonical_local or "")[:12],
                      "stale_vs_remote": canonical_stale, "remote_sha_short": (remote or "")[:12] if remote else None},
        "candidate": {"tree": str(REPO), "branch": branch, "sha": candidate, "sha_short": (candidate or "")[:12],
                      "state_vs_canonical": cand_state, "ahead": ahead, "behind": behind},
        "production": {"tree": str(PROD), "sha": production, "sha_short": (production or "")[:12],
                       "state_vs_canonical": prod_state,
                       "warning": "git HEAD only — NOT what is executing; see `release` for STAGED/ACTIVE"},
        "release": release,
        "mirror": {"tree": str(MIRROR), "sha_short": (mirror or "")[:12] if mirror else None},
        "deployment_required": deployment_required,
        "promotion_path": "candidate → push_to_github.py → origin/main → autosync → owner-gated restart (ADR-494)",
        "rollback": "revert the offending commit on origin/main (never force-push); restore backup + restart for a hot agent",
        "note": "Network-free unless check_remote=True. Candidate AHEAD = commits await owner-gated promotion; "
                "it is NOT a defect — it is the normal pre-promotion state.",
    }


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(status(check_remote="--remote" in sys.argv), ensure_ascii=False, indent=1))
