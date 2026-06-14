#!/bin/bash
cd "$(dirname "$0")"
export GITHUB_TOKEN="$(security find-generic-password -s GITHUB_PAT_SPA -w)"
LOG="$(pwd)/push_log.txt"

cat > /tmp/_spa_push.py << 'PYEOF'
import urllib.request, urllib.error, json, os, base64, sys

TOKEN = os.environ["GITHUB_TOKEN"]
OWNER = "yurii-spa"
REPO  = "SPA"
BRANCH = "main"
BASE   = f"https://api.github.com/repos/{OWNER}/{REPO}/contents"

def hdr():
    return {"Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}

def p(msg, end="\n"):
    print(msg, end=end, flush=True)

# Token check
p("=== Token check ===")
try:
    req = urllib.request.Request(f"https://api.github.com/repos/{OWNER}/{REPO}", headers=hdr())
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
        push_ok = d.get("permissions", {}).get("push", False)
        p(f"  OK: {d['full_name']}  push={push_ok}")
        if not push_ok:
            p("  ERROR: no write access — need 'repo' scope classic token")
            sys.exit(1)
except Exception as e:
    p(f"  ERROR: {e}")
    sys.exit(1)

# Load manifest
sys.path.insert(0, os.getcwd())
from spa_core.tools.github_pusher import PUSH_MANIFEST
p(f"\n=== Pushing {len(PUSH_MANIFEST)} files ===")
pushed = errors = skipped = 0

for i, (local_path, repo_path, commit_msg) in enumerate(PUSH_MANIFEST, 1):
    p(f"[{i:02}/{len(PUSH_MANIFEST)}] {repo_path} ... ", end="")
    if not os.path.exists(local_path):
        p("SKIP")
        skipped += 1
        continue

    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    sha = None
    try:
        req = urllib.request.Request(f"{BASE}/{repo_path}?ref={BRANCH}", headers=hdr())
        with urllib.request.urlopen(req, timeout=10) as r:
            sha = json.loads(r.read()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            p(f"GET-ERR {e.code}")
            errors += 1
            continue

    payload = {"message": commit_msg, "content": content, "branch": BRANCH}
    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}/{repo_path}", data=data,
          headers={**hdr(), "Content-Type": "application/json"}, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            p("OK")
            pushed += 1
    except urllib.error.HTTPError as e:
        body = {}
        try: body = json.loads(e.read())
        except: pass
        p(f"ERR {e.code}: {body.get('message', e.reason)}")
        errors += 1
    except Exception as e:
        p(f"ERR: {e}")
        errors += 1

p(f"\n{'='*40}")
p(f"RESULT: pushed={pushed}  errors={errors}  skipped={skipped}")
p(f"{'='*40}")
PYEOF

echo "=== SPA GitHub Pusher — 111 files ==="
python3 /tmp/_spa_push.py 2>&1 | tee "$LOG"

echo ""
echo "Log saved: $LOG"
read -p "Press Enter to close..."
