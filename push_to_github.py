#!/usr/bin/env python3
"""
push_to_github.py — универсальный пуш файлов в GitHub через Contents API.
Читает PAT из переменной окружения GITHUB_PAT, файла ~/.spa_pat
или macOS Keychain (сервис GITHUB_PAT_SPA).
НЕ содержит hardcoded secrets.

Использование:
  # Positional files (новый стиль):
  python3 scripts/push_to_github.py --repo yurii-spa/SPA --pat "$PAT" file1.py file2.py

  # --files флаг (старый стиль):
  python3 scripts/push_to_github.py --files file1.py file2.py --message "feat: описание"

  # --file одиночный (старый стиль):
  python3 scripts/push_to_github.py --file path/to/file.py --message "feat: описание"
"""
import os
import sys
import json
import base64
import hashlib
import argparse
import subprocess
import time
from pathlib import Path
from typing import Optional

REPO = "yurii-spa/SPA"
API_BASE = "https://api.github.com"
PROJECT_ROOT = Path("/Users/yuriikulieshov/Documents/SPA_Claude")


def get_pat() -> str:
    """Читает PAT (никогда из hardcode).

    Порядок поиска:
      1. macOS Keychain (сервис GITHUB_PAT_SPA)
      2. Переменная окружения GITHUB_PAT_SPA
      3. Переменная окружения SPA_GITHUB_PAT
      4. Файл ~/.github_pat или рядом со скриптом
    """
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
        "Или через setup_pat.sh:\n"
        "  bash scripts/setup_pat.sh ghp_ТОКЕН\n"
    )


def git_blob_sha(content: bytes) -> str:
    """Вычисляет git blob SHA-1 для байтов файла.

    Это в точности тот же хеш, что GitHub возвращает в поле ``sha`` Contents API
    (git хеширует blob как ``"blob <len>\\0" + content``). Детерминированно,
    stdlib-only. Позволяет сравнить локальное содержимое с тем, что уже лежит
    на remote, БЕЗ скачивания файла — и пропустить пуш, если они идентичны.
    """
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def get_file_sha(pat: str, repo: str, repo_path: str, branch: str = "main") -> Optional[str]:
    """Возвращает SHA файла на GitHub (на указанной ветке)."""
    import urllib.request
    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}?ref={branch}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return data.get("sha")
    except Exception:
        return None


def push_file(pat: str, local_path: str, message: str, repo: str, dry_run: bool = False,
              branch: str = "main") -> dict:
    """Пушит один файл через GitHub Contents API."""
    import urllib.request
    import urllib.error

    local = Path(local_path)
    # Resolve relative to PROJECT_ROOT if not absolute
    if not local.is_absolute():
        local = PROJECT_ROOT / local
    if not local.exists():
        return {"ok": False, "error": f"Файл не найден: {local_path}", "path": local_path}

    # Relative path in repo
    try:
        repo_path = str(local.relative_to(PROJECT_ROOT))
    except ValueError:
        repo_path = local.name

    local_bytes = local.read_bytes()
    local_blob_sha = git_blob_sha(local_bytes)

    if dry_run:
        sha = get_file_sha(pat, repo, repo_path, branch)
        if sha is not None and sha == local_blob_sha:
            return {"ok": True, "dry_run": True, "path": repo_path, "action": "skip"}
        action = "update" if sha else "create"
        return {"ok": True, "dry_run": True, "path": repo_path, "action": action}

    content_b64 = base64.b64encode(local_bytes).decode()
    sha = get_file_sha(pat, repo, repo_path, branch)

    # Idempotency guard (fail-CLOSED): пропускаем PUT, только если remote SHA
    # ТОЧНО совпадает с локальным git-blob-SHA. Любая неопределённость
    # (sha=None из-за сетевой ошибки/нового файла) → пушим как обычно, чтобы
    # реальные изменения никогда не потерялись. Идентичный контент → no-op PUT
    # создаёт пустой коммит в Contents API — именно его мы и устраняем.
    if sha is not None and sha == local_blob_sha:
        return {"ok": True, "skipped": True, "path": repo_path, "sha": sha[:8]}

    payload: dict = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}"
    data_bytes = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data_bytes, method="PUT", headers={
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            sha_short = result.get("content", {}).get("sha", "")[:8]
            return {"ok": True, "path": repo_path, "sha": sha_short}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code in (429, 403) and "rate limit" in body.lower():
            print(f"  Rate limit — ждём 60с...")
            time.sleep(60)
            return push_file(pat, local_path, message, repo, dry_run, branch)
        return {"ok": False, "error": f"HTTP {e.code}: {body[:300]}", "path": repo_path}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": repo_path}


def main():
    parser = argparse.ArgumentParser(
        description="Пуш файлов в GitHub без hardcoded PAT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Новый стиль: positional file args
    parser.add_argument("files_pos", nargs="*", metavar="FILE", help="Файлы для пуша (positional)")
    # Старый стиль
    parser.add_argument("--file", help="Один файл (старый стиль)")
    parser.add_argument("--files", nargs="+", help="Несколько файлов (старый стиль)")
    # Общие опции
    parser.add_argument("--message", "-m", default=None, help="Commit message (авто-генерируется если не указан)")
    parser.add_argument("--repo", default=REPO, help=f"Репо (default: {REPO})")
    parser.add_argument("--branch", default="main", help="Целевая ветка (default: main)")
    parser.add_argument("--dry-run", action="store_true", help="Проверить без пуша")
    parser.add_argument("--pat", help="GitHub PAT (переопределяет Keychain/env/файл)")
    args = parser.parse_args()

    # Собираем все файлы из всех источников
    all_files: list = []
    if args.files_pos:
        all_files.extend(args.files_pos)
    if args.file:
        all_files.append(args.file)
    if args.files:
        all_files.extend(args.files)

    if not all_files:
        parser.error("Укажи файлы (positional) или --file / --files")

    # Авто-сообщение если не указано
    message = args.message or f"chore: push {len(all_files)} file(s) via push_to_github.py"

    # PAT
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
        print(f"Пушу {len(all_files)} файл(ов) в {args.repo} ({args.branch})...")

    results = []
    for f in all_files:
        r = push_file(pat, f, message, args.repo, dry_run=args.dry_run, branch=args.branch)
        results.append(r)
        if r.get("ok"):
            if r.get("dry_run"):
                print(f"  {r['path']} → {r['action']}")
            elif r.get("skipped"):
                print(f"  SKIP {r['path']} (unchanged, sha: {r.get('sha', '?')})")
            else:
                print(f"  OK {r['path']} (sha: {r.get('sha', '?')})")
        else:
            print(f"  FAIL {r.get('path', f)}: {r.get('error', '?')}")
        time.sleep(0.3)  # avoid rate limit

    failed = [r for r in results if not r.get("ok")]
    skipped = [r for r in results if r.get("ok") and r.get("skipped")]
    pushed = [r for r in results if r.get("ok") and not r.get("skipped") and not r.get("dry_run")]
    if failed:
        print(f"\nFAIL: {len(failed)}/{len(results)}")
        sys.exit(1)
    else:
        print(f"\nOK: {len(results)} файл(ов) (pushed={len(pushed)}, skipped={len(skipped)})")
        sys.exit(0)


if __name__ == "__main__":
    main()
