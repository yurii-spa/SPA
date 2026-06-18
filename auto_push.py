#!/usr/bin/env python3
"""auto_push.py — автоматически пушит новые файлы после каждого спринта SPA."""
import json, os, subprocess, sys, time, base64, urllib.request
from pathlib import Path
from datetime import datetime

REPO = "yurii-spa/SPA"
SPA_DIR = Path("/Users/yuriikulieshov/Documents/SPA_Claude")
STATE_FILE = Path.home() / ".spa_push_state.json"
LOG_FILE = Path.home() / ".spa_push.log"
SKIP_PATTERNS = {"push_v", ".bak.", "__pycache__", ".git", ".DS_Store", "auto_push", ".fuse_hidden",
                 ".claude", ".pytest_cache"}  # .claude/settings.local.json может содержать секреты в строках команд
PUSH_SCRIPT = SPA_DIR / "push_to_github.py"

# SPA-V434: файлы, которые пушатся ВСЕГДА независимо от mtime.
# Это гарантирует, что критические data-файлы не пропустятся при первом запуске
# или если их mtime оказался раньше last_push_ts.
ALWAYS_INCLUDE_FILES: list[Path] = [
    SPA_DIR / "index.html",                             # SPA-V434: дашборд — всегда пушить
    SPA_DIR / "data" / "decisions.json",
    SPA_DIR / "data" / "dashboard_metrics_history.json",
    SPA_DIR / "data" / "adapter_status.json",
]

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def get_pat():
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-a", "spa", "-w"],
        capture_output=True, text=True, timeout=5
    )
    if r.returncode == 0:
        return r.stdout.strip()
    raise RuntimeError("PAT не найден в Keychain")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_pushed_sprint": "", "last_push_ts": 0}

def save_state(sprint, ts):
    STATE_FILE.write_text(json.dumps({"last_pushed_sprint": sprint, "last_push_ts": ts}))

def should_skip(path: Path) -> bool:
    s = str(path)
    return any(p in s for p in SKIP_PATTERNS)

def find_changed_files(since_ts: float) -> list[Path]:
    changed = []
    for p in SPA_DIR.rglob("*"):
        if not p.is_file():
            continue
        if should_skip(p):
            continue
        try:
            if p.stat().st_mtime > since_ts:
                changed.append(p)
        except OSError:
            pass
    return sorted(changed, key=lambda p: p.stat().st_mtime)

def push_batch(files: list[Path], pat: str, message: str) -> list[dict]:
    results = []
    for f in files:
        repo_path = str(f.relative_to(SPA_DIR))
        content_b64 = base64.b64encode(f.read_bytes()).decode()
        # Get SHA if exists
        sha = None
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/contents/{repo_path}",
                headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                sha = json.loads(resp.read()).get("sha")
        except Exception:
            pass
        payload = {"message": message, "content": content_b64, "branch": "main"}
        if sha:
            payload["sha"] = sha
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/contents/{repo_path}",
                data=json.dumps(payload).encode(), method="PUT",
                headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json",
                         "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                res = json.loads(resp.read())
                results.append({"ok": True, "path": repo_path, "sha": res.get("content", {}).get("sha", "")[:8]})
        except Exception as e:
            results.append({"ok": False, "path": repo_path, "error": str(e)[:80]})
        time.sleep(0.3)  # rate limit
    return results

def main():
    # Читаем KANBAN
    kanban_path = SPA_DIR / "KANBAN.json"
    if not kanban_path.exists():
        log("KANBAN.json не найден — выход"); return
    kanban = json.loads(kanban_path.read_text())
    current_sprint = kanban.get("sprint_completed", "")

    state = load_state()
    last_sprint = state["last_pushed_sprint"]
    last_ts = state["last_push_ts"]

    if current_sprint == last_sprint:
        log(f"Sprint не изменился ({current_sprint}) — нечего пушить"); return

    log(f"Новый спринт: {last_sprint} → {current_sprint}. Ищу изменённые файлы...")

    pat = get_pat()
    changed = find_changed_files(last_ts)

    # SPA-V434: добавить always-include файлы (если существуют и не в skip-листе).
    changed_set = set(changed)
    for always_file in ALWAYS_INCLUDE_FILES:
        if always_file.exists() and not should_skip(always_file) and always_file not in changed_set:
            changed.append(always_file)

    if not changed:
        log("Изменённых файлов не найдено");
        save_state(current_sprint, time.time()); return

    log(f"Найдено {len(changed)} файлов. Пушу...")
    # [skip ci] — не триггерить CF Pages / GitHub Actions на data-коммитах.
    # Лендинг деплоится только через git push напрямую.
    message = f"feat: auto-push after {current_sprint} ({datetime.now().strftime('%Y-%m-%d %H:%M')}) [skip ci]"

    # По 5 файлов за раз
    batch_size = 5
    ok_count = 0
    for i in range(0, len(changed), batch_size):
        batch = changed[i:i+batch_size]
        results = push_batch(batch, pat, message)
        for r in results:
            if r.get("ok"):
                log(f"  ✅ {r['path']} ({r.get('sha','')})")
                ok_count += 1
            else:
                log(f"  ❌ {r['path']}: {r.get('error','')}")

    log(f"Итого: {ok_count}/{len(changed)} файлов запушено")
    save_state(current_sprint, time.time())

if __name__ == "__main__":
    main()
