#!/usr/bin/env python3
"""
push_to_github_batch.py — BATCHED пуш многих файлов в GitHub ОДНИМ коммитом
через GitHub Git Data API.

ЗАЧЕМ: push_to_github.py (Contents API) делает 1 коммит на файл → N файлов =
N коммитов = N триггеров сборки Cloudflare Pages. CF собирает очередь
последовательно → при сотнях пушей очередь отстаёт на часы.

ЭТОТ скрипт собирает ВСЕ файлы в ОДИН коммит через Git Data API:
  1. GET  /repos/{REPO}/git/ref/heads/{branch}      → base commit sha
  2. GET  /repos/{REPO}/git/commits/{base_sha}      → base tree sha
  3. POST /repos/{REPO}/git/blobs  (per file)       → blob sha (base64)
  4. POST /repos/{REPO}/git/trees  (base_tree + entries) → new tree sha
  5. POST /repos/{REPO}/git/commits (tree, parents) → new commit sha
  6. PATCH /repos/{REPO}/git/refs/heads/{branch}    → move ref → 1 коммит, 1 CF build

Stdlib only: urllib + json + base64.
Drop-in CLI совместим с push_to_github.py:
  python3 push_to_github_batch.py --message "msg" --files <abs paths...>
  python3 push_to_github_batch.py --message "msg" file1 file2     (positional)
  python3 push_to_github_batch.py --dry-run --files ...           (no writes)

НЕ поддерживает удаления (add/update только) — удаления через Contents API отдельно.
НЕ содержит hardcoded secrets — PAT из Keychain GITHUB_PAT_SPA (см. get_pat).
"""
import os
import sys
import json
import base64
import argparse
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

REPO = "yurii-spa/SPA"
API_BASE = "https://api.github.com"
PROJECT_ROOT = Path("/Users/yuriikulieshov/Documents/SPA_Claude")


def get_pat() -> str:
    """Читает PAT (никогда из hardcode). Идентично push_to_github.py."""
    # 1. macOS Keychain
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            pat = result.stdout.strip()
            if pat:
                return pat
    except Exception:
        pass

    # 2–3. Переменные окружения
    for env_var in ("GITHUB_PAT_SPA", "SPA_GITHUB_PAT", "GITHUB_PAT"):
        pat = os.environ.get(env_var, "").strip()
        if pat:
            return pat

    # 4. Файл
    for pat_file in [
        Path.home() / ".github_pat",
        PROJECT_ROOT / ".github_pat",
        Path.home() / ".spa_pat",
    ]:
        if pat_file.exists():
            pat = pat_file.read_text().strip()
            if pat:
                return pat

    raise RuntimeError(
        "PAT не найден в Keychain (GITHUB_PAT_SPA).\n"
        "Добавь PAT командой:\n"
        "  security add-generic-password -s GITHUB_PAT_SPA -a yurii-spa -w ghp_ТОКЕН\n"
    )


def _api(pat: str, method: str, path: str, payload: Optional[dict] = None) -> dict:
    """Один вызов GitHub API. Бросает urllib.error.HTTPError (с телом) на ошибке."""
    url = f"{API_BASE}{path}"
    data_bytes = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data_bytes, method=method, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def get_base_ref(pat: str, repo: str, branch: str) -> tuple:
    """Шаги 1-2: вернуть (base_commit_sha, base_tree_sha)."""
    ref = _api(pat, "GET", f"/repos/{repo}/git/ref/heads/{branch}")
    base_commit_sha = ref["object"]["sha"]
    commit = _api(pat, "GET", f"/repos/{repo}/git/commits/{base_commit_sha}")
    base_tree_sha = commit["tree"]["sha"]
    return base_commit_sha, base_tree_sha


def resolve_files(file_args: list) -> list:
    """Преобразовать пути в [(repo_relative_path, abs_path)]. Бросает на отсутствующий файл."""
    resolved = []
    for fa in file_args:
        local = Path(fa)
        if not local.is_absolute():
            local = PROJECT_ROOT / local
        if not local.exists():
            raise RuntimeError(f"Файл не найден: {fa}")
        if not local.is_file():
            raise RuntimeError(f"Не файл (директории не поддерживаются): {fa}")
        try:
            repo_path = str(local.relative_to(PROJECT_ROOT))
        except ValueError:
            repo_path = local.name
        resolved.append((repo_path, local))
    return resolved


def create_blob(pat: str, repo: str, abs_path: Path) -> str:
    """Шаг 3: создать blob из файла (base64, безопасно для бинарных и текстовых)."""
    content_b64 = base64.b64encode(abs_path.read_bytes()).decode()
    blob = _api(pat, "POST", f"/repos/{repo}/git/blobs",
                {"content": content_b64, "encoding": "base64"})
    return blob["sha"]


def create_tree(pat: str, repo: str, base_tree_sha: str, entries: list) -> str:
    """Шаг 4: новое дерево = base_tree + по записи на файл."""
    tree = _api(pat, "POST", f"/repos/{repo}/git/trees",
                {"base_tree": base_tree_sha, "tree": entries})
    return tree["sha"]


def create_commit(pat: str, repo: str, message: str, tree_sha: str, parent_sha: str) -> str:
    """Шаг 5: один коммит со всеми изменениями."""
    commit = _api(pat, "POST", f"/repos/{repo}/git/commits",
                  {"message": message, "tree": tree_sha, "parents": [parent_sha]})
    return commit["sha"]


def update_ref(pat: str, repo: str, branch: str, commit_sha: str, force: bool = False) -> dict:
    """Шаг 6: переместить ветку на новый коммит."""
    return _api(pat, "PATCH", f"/repos/{repo}/git/refs/heads/{branch}",
                {"sha": commit_sha, "force": force})


def batch_push(pat: str, file_args: list, message: str, repo: str, branch: str,
               dry_run: bool = False) -> dict:
    """Собрать N файлов в ОДИН коммит через Git Data API."""
    files = resolve_files(file_args)

    # Шаги 1-2: база
    base_commit_sha, base_tree_sha = get_base_ref(pat, repo, branch)
    print(f"  base commit: {base_commit_sha[:8]}  base tree: {base_tree_sha[:8]}")

    if dry_run:
        print(f"DRY RUN — закоммитил бы {len(files)} файл(ов) ОДНИМ коммитом:")
        for repo_path, _ in files:
            print(f"    + {repo_path}")
        return {"ok": True, "dry_run": True, "count": len(files),
                "base_commit": base_commit_sha}

    # Шаг 3: blobs
    entries = []
    for repo_path, abs_path in files:
        blob_sha = create_blob(pat, repo, abs_path)
        print(f"  blob {blob_sha[:8]}  {repo_path}")
        entries.append({
            "path": repo_path,
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha,
        })

    # Шаг 4: tree
    new_tree_sha = create_tree(pat, repo, base_tree_sha, entries)
    print(f"  tree {new_tree_sha[:8]}")

    # Шаг 5: commit
    new_commit_sha = create_commit(pat, repo, message, new_tree_sha, base_commit_sha)
    print(f"  commit {new_commit_sha[:8]}")

    # Шаг 6: move ref, с одним ретраем на 409 (stale ref)
    try:
        update_ref(pat, repo, branch, new_commit_sha)
    except urllib.error.HTTPError as e:
        if e.code == 409:
            body = e.read().decode(errors="replace")
            print(f"  409 stale ref: {body[:200]} — пересобираю на свежей базе...")
            # Пересобираем коммит поверх свежего HEAD (база сдвинулась)
            fresh_base_commit, fresh_base_tree = get_base_ref(pat, repo, branch)
            new_tree_sha = create_tree(pat, repo, fresh_base_tree, entries)
            new_commit_sha = create_commit(pat, repo, message, new_tree_sha, fresh_base_commit)
            print(f"  recommit {new_commit_sha[:8]} (parent {fresh_base_commit[:8]})")
            update_ref(pat, repo, branch, new_commit_sha)
        else:
            raise

    return {"ok": True, "count": len(files), "commit": new_commit_sha,
            "tree": new_tree_sha, "files": [p for p, _ in files]}


def main():
    parser = argparse.ArgumentParser(
        description="BATCHED пуш: N файлов = 1 коммит = 1 CF build (Git Data API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files_pos", nargs="*", metavar="FILE", help="Файлы (positional)")
    parser.add_argument("--file", help="Один файл (совместимость)")
    parser.add_argument("--files", nargs="+", help="Несколько файлов")
    parser.add_argument("--message", "-m", default=None, help="Commit message")
    parser.add_argument("--repo", default=REPO, help=f"Репо (default: {REPO})")
    parser.add_argument("--branch", default="main", help="Ветка (default: main)")
    parser.add_argument("--dry-run", action="store_true", help="Шаги 1-2 + что закоммитили бы (без записи)")
    parser.add_argument("--pat", help="GitHub PAT (переопределяет Keychain/env/файл)")
    args = parser.parse_args()

    all_files: list = []
    if args.files_pos:
        all_files.extend(args.files_pos)
    if args.file:
        all_files.append(args.file)
    if args.files:
        all_files.extend(args.files)

    if not all_files:
        parser.error("Укажи файлы (positional) или --file / --files")

    message = args.message or f"chore: batch push {len(all_files)} file(s) in one commit"

    if args.pat and args.pat.strip():
        pat = args.pat.strip()
    else:
        try:
            pat = get_pat()
        except RuntimeError as e:
            print(str(e))
            sys.exit(2)

    if args.dry_run:
        print(f"DRY RUN — репо: {args.repo}, ветка: {args.branch}, файлов: {len(all_files)}")
    else:
        print(f"Batch-пуш {len(all_files)} файл(ов) → {args.repo} ({args.branch}) ОДНИМ коммитом...")

    try:
        result = batch_push(pat, all_files, message, args.repo, args.branch,
                            dry_run=args.dry_run)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"\nFAIL HTTP {e.code}: {body[:500]}")
        sys.exit(1)
    except Exception as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)

    if result.get("dry_run"):
        print(f"\nDRY OK: {result['count']} файл(ов) попали бы в 1 коммит")
    else:
        print(f"\nOK: 1 коммит {result['commit'][:8]} со {result['count']} файл(ами)")
    sys.exit(0)


if __name__ == "__main__":
    main()
