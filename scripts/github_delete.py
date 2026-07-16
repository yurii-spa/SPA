#!/usr/bin/env python3
"""github_delete — удалить файл(ы) из origin через GitHub Contents API.

Нужен для НЕДЕСТРУКТИВНОГО перемещения (attic/archive): копию кладём push_to_github,
оригинал удаляем этим. Переиспользует PAT + get_file_sha из push_to_github.py.
Порядок безопасного move: сначала запушить копию (add), УБЕДИТЬСЯ что она на origin,
потом удалить оригинал этим скриптом.

Usage: python3 scripts/github_delete.py --paths <repo/rel/path> [...] --message "..."
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from push_to_github import REPO, get_file_sha, get_pat  # noqa: E402


def delete_path(pat: str, repo_path: str, message: str, repo: str, branch: str = "main") -> dict:
    sha = get_file_sha(pat, repo, repo_path, branch)
    if sha is None:
        return {"ok": True, "path": repo_path, "action": "already-absent"}
    url = f"https://api.github.com/repos/{repo}/contents/{repo_path}"
    body = json.dumps({"message": message, "sha": sha, "branch": branch}).encode()
    req = urllib.request.Request(url, data=body, method="DELETE")
    req.add_header("Authorization", f"token {pat}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        return {"ok": True, "path": repo_path, "action": "deleted"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "path": repo_path, "error": f"HTTP {exc.code}: {exc.read()[:180]!r}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "path": repo_path, "error": str(exc)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Delete files from origin (GitHub Contents API).")
    ap.add_argument("--paths", nargs="+", required=True, help="repo-relative paths")
    ap.add_argument("--message", "-m", required=True)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--branch", default="main")
    args = ap.parse_args(argv)
    pat = get_pat()
    ok = 0
    for p in args.paths:
        r = delete_path(pat, p, args.message, args.repo, args.branch)
        print(("  OK " if r["ok"] else "  FAIL ") + f"{r['path']} ({r.get('action', r.get('error'))})")
        ok += 1 if r["ok"] else 0
        time.sleep(0.25)
    print(f"deleted {ok}/{len(args.paths)}")
    return 0 if ok == len(args.paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())
