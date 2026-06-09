#!/usr/bin/env python3
"""Remove all .fuse_hidden* artifacts from the yurii-spa/SPA GitHub repo."""
import json
import subprocess
import time
import urllib.request
import urllib.error
import urllib.parse

REPO = "yurii-spa/SPA"
BRANCH = "main"
RATE_LIMIT = 0.2


def get_pat():
    return subprocess.check_output(
        ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-a", "spa", "-w"]
    ).decode().strip()


def api_request(url, pat, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {pat}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main():
    pat = get_pat()
    tree = api_request(
        f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1", pat
    )["tree"]
    fuse = [f for f in tree if ".fuse_hidden" in f["path"]]
    print(f"Found {len(fuse)} fuse_hidden files to delete")

    deleted = 0
    failed = []
    for i, f in enumerate(fuse, 1):
        path = f["path"]
        sha = f["sha"]
        url = f"https://api.github.com/repos/{REPO}/contents/{urllib.parse.quote(path)}"
        body = {
            "message": "chore: remove fuse_hidden artifacts",
            "sha": sha,
            "branch": BRANCH,
        }
        try:
            api_request(url, pat, method="DELETE", body=body)
            deleted += 1
            if i % 25 == 0 or i == len(fuse):
                print(f"  [{i}/{len(fuse)}] deleted {deleted}")
        except urllib.error.HTTPError as e:
            failed.append((path, e.code, e.read().decode()[:200]))
            print(f"  FAILED {path}: {e.code}")
        time.sleep(RATE_LIMIT)

    print(f"\nDone. Deleted {deleted}/{len(fuse)}. Failed: {len(failed)}")
    for p, code, msg in failed:
        print(f"  - {p} ({code}): {msg}")


if __name__ == "__main__":
    main()
