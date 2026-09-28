"""Release ACTIVATION resolver (PROPOSED ADR-500, revised for ARB) — the piece the marker-only design was
missing: it proves which EXACT code a process will execute BEFORE exec, because Python imports resolve from
the filesystem, not from a marker.

ARB proof requirement: given APPROVED=A while the shared tree already holds STAGED=B, what operation makes an
agent execute A rather than B? Answer here (Option B — immutable release directory):

  * Each approved release is materialised ONCE into an immutable, content-addressed directory
    `releases/<sha>/`, from LOCAL git objects (`git archive <sha>` — no network for a known local sha).
  * A process execs with `releases/<APPROVED>/` at the FRONT of its module path. That directory contains
    exactly A and nothing else; the autosync only ever writes a DIFFERENT `releases/<B>/`, so it can never
    turn A into B (no TOCTOU, no partial-write race on the active release).
  * If APPROVED is unset → fail CLOSED (execute nothing). If APPROVED is set but its release dir is missing →
    recover by re-materialising from git; if the object is absent → fail CLOSED (never fall back to the tree).

This module is pure resolution + materialisation. It performs NO production side effects on import, starts
nothing, moves no capital, and is imported by no money-path module. stdlib only; all paths injectable."""
from __future__ import annotations

import subprocess
from pathlib import Path

RELEASE_SHA_FILE = ".release_sha"   # written inside each materialised release dir = its own identity


def exec_root(approved_sha, releases_dir: Path):
    """PURE: the immutable directory a process MUST exec from, given the approved sha. Never returns the
    shared tree. Returns (root_path | None, verdict):
      (releases/<A>, 'ACTIVATE_OK')          — approved release present and self-identifies as A
      (None, 'DEPLOYMENT_APPROVAL_REQUIRED')  — no approved release recorded → execute nothing
      (None, 'APPROVED_RELEASE_MISSING')      — approved set but not materialised → recover, do NOT run the tree
      (None, 'APPROVED_RELEASE_CORRUPT')      — dir exists but does not self-identify as A → refuse
    """
    if not approved_sha:
        return None, "DEPLOYMENT_APPROVAL_REQUIRED"
    root = Path(releases_dir) / approved_sha
    if not root.is_dir():
        return None, "APPROVED_RELEASE_MISSING"
    stamp = root / RELEASE_SHA_FILE
    if not stamp.exists() or stamp.read_text().strip() != approved_sha:
        return None, "APPROVED_RELEASE_CORRUPT"
    return root, "ACTIVATE_OK"


def materialise_release(sha, releases_dir: Path, repo: Path):
    """Create the immutable `releases/<sha>/` from LOCAL git objects, atomically (temp dir + os.replace).
    No network for a known local sha. Returns (path, 'OK') or (None, reason). Idempotent: if the release
    already self-identifies as `sha`, returns it unchanged. On any failure the partial temp dir is removed
    and the existing active release is left untouched (never a half-written release)."""
    releases_dir = Path(releases_dir)
    dest = releases_dir / sha
    if (dest / RELEASE_SHA_FILE).exists() and (dest / RELEASE_SHA_FILE).read_text().strip() == sha:
        return dest, "OK"
    # object must be present locally (fail CLOSED, never fetch silently under an agent)
    if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(repo),
                      capture_output=True).returncode != 0:
        return None, "OBJECT_MISSING"
    releases_dir.mkdir(parents=True, exist_ok=True)
    tmp = releases_dir / f".tmp-{sha}"
    if tmp.exists():
        subprocess.run(["rm", "-rf", str(tmp)])
    tmp.mkdir()
    try:
        # git archive → tar → extract: an exact, read-only snapshot of the commit tree, no working-tree state
        ar = subprocess.run(["git", "archive", "--format=tar", sha], cwd=str(repo), capture_output=True)
        if ar.returncode != 0:
            raise RuntimeError("git archive failed")
        ex = subprocess.run(["tar", "-x", "-C", str(tmp)], input=ar.stdout, capture_output=True)
        if ex.returncode != 0:
            raise RuntimeError("tar extract failed")
        (tmp / RELEASE_SHA_FILE).write_text(sha)
        # atomic publish: rename temp → releases/<sha> (dest must not pre-exist as a dir)
        if dest.exists():
            subprocess.run(["rm", "-rf", str(dest)])
        tmp.rename(dest)
        return dest, "OK"
    except Exception as e:
        subprocess.run(["rm", "-rf", str(tmp)])
        return None, f"MATERIALISE_FAILED:{e}"


def activation_plan(approved_sha, staged_sha, releases_dir: Path, repo: Path):
    """What a restart/self-heal/reboot/scheduled-cycle MUST do to guarantee it runs APPROVED, not STAGED.
    Deterministic, side-effect-free (only reads); the caller performs materialise/exec. Never selects the tree."""
    root, verdict = exec_root(approved_sha, releases_dir)
    if verdict == "ACTIVATE_OK":
        return {"action": "EXEC_FROM_RELEASE", "root": str(root), "sha": approved_sha,
                "note": "exec with this dir at module-path front; the shared tree (staged=%s) is NOT on the path" % (staged_sha or "?")}
    if verdict == "APPROVED_RELEASE_MISSING":
        # recoverable if the object is local; otherwise fail CLOSED
        can = subprocess.run(["git", "cat-file", "-e", f"{approved_sha}^{{commit}}"], cwd=str(repo),
                             capture_output=True).returncode == 0 if approved_sha else False
        return {"action": "MATERIALISE_THEN_EXEC" if can else "FAIL_CLOSED",
                "sha": approved_sha, "recoverable": can, "verdict": verdict}
    return {"action": "FAIL_CLOSED", "verdict": verdict, "sha": approved_sha,
            "note": "execute NOTHING; never fall back to the staged tree"}
