#!/usr/bin/env python3
"""
push_to_github.py — универсальный пуш файлов в GitHub через Contents API.
Читает PAT из переменной окружения GITHUB_PAT, файла ~/.spa_pat
или macOS Keychain (сервис GITHUB_PAT_SPA).
НЕ содержит hardcoded secrets.

Использование:
  python3 push_to_github.py --file path/to/file.py --message "feat: описание"
  python3 push_to_github.py --files file1.py file2.py --message "feat: описание"
  python3 push_to_github.py --files file1.py --message "feat: ..." --repo other-owner/repo
"""
import os
import sys
import json
import base64
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
      1. macOS Keychain (сервис GITHUB_PAT_SPA) — рекомендуется для локальной машины
      2. Переменная окружения GITHUB_PAT_SPA
      3. Переменная окружения SPA_GITHUB_PAT
      4. Файл .github_pat (~/.github_pat или рядом со скриптом) — для агентов/Linux sandbox
    Обратная совместимость: GITHUB_PAT env и ~/.spa_pat тоже проверяются.
    """
    # 1. macOS Keychain — сервис GITHUB_PAT_SPA
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

    # 2–3. Переменные окружения (в порядке приоритета)
    for env_var in ("GITHUB_PAT_SPA", "SPA_GITHUB_PAT", "GITHUB_PAT"):
        pat = os.environ.get(env_var, "").strip()
        if pat:
            return pat

    # 4. Файл .github_pat: сначала ~/.github_pat, потом рядом со скриптом
    #    (и ~/.spa_pat для обратной совместимости)
    for pat_file in [
        Path.home() / ".github_pat",
        PROJECT_ROOT / ".github_pat",
        Path.home() / ".spa_pat",          # backward compat
    ]:
        if pat_file.exists():
            pat = pat_file.read_text().strip()
            if pat:
                return pat

    raise RuntimeError(
        "❌ PAT не найден.\n\n"
        "  Запусти: ./setup_github_pat.sh ghp_ТВОЙ_ТОКЕН\n\n"
        "  Или вручную (один из вариантов):\n"
        "  A) macOS Keychain:  bash setup_pat.sh ghp_ТОКЕН\n"
        "  B) Env:             export GITHUB_PAT_SPA=ghp_ТОКЕН\n"
        "  C) Файл:            echo 'ghp_ТОКЕН' > ~/.github_pat && chmod 600 ~/.github_pat\n"
    )


def get_file_sha(pat: str, repo: str, repo_path: str) -> Optional[str]:
    """Возвращает SHA файла на GitHub (нужно для обновления существующего файла)."""
    import urllib.request
    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}"
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


def push_file(pat: str, local_path: str, message: str, repo: str, dry_run: bool = False) -> dict:
    """Пушит один файл через GitHub Contents API."""
    import urllib.request
    import urllib.error

    local = Path(local_path)
    if not local.exists():
        return {"ok": False, "error": f"Файл не найден: {local_path}", "path": local_path}

    # Путь в репо относительно корня проекта
    try:
        repo_path = str(local.relative_to(PROJECT_ROOT))
    except ValueError:
        repo_path = local.name

    if dry_run:
        sha = get_file_sha(pat, repo, repo_path)
        action = "update" if sha else "create"
        return {"ok": True, "dry_run": True, "path": repo_path, "action": action}

    content_b64 = base64.b64encode(local.read_bytes()).decode()
    sha = get_file_sha(pat, repo, repo_path)

    payload: dict = {
        "message": message,
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    url = f"{API_BASE}/repos/{repo}/contents/{repo_path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
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
        # Retry once on rate-limit
        if e.code == 429 or e.code == 403 and "rate limit" in body.lower():
            print(f"  ⏳ Rate limit, ждём 60с...")
            time.sleep(60)
            return push_file(pat, local_path, message, repo, dry_run)
        return {"ok": False, "error": f"HTTP {e.code}: {body[:200]}", "path": repo_path}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": repo_path}


def main():
    parser = argparse.ArgumentParser(
        description="Пуш файлов в GitHub без hardcoded PAT"
    )
    parser.add_argument("--file", help="Один файл для пуша")
    parser.add_argument("--files", nargs="+", help="Несколько файлов")
    parser.add_argument("--message", "-m", required=True, help="Commit message")
    parser.add_argument("--repo", default=REPO, help=f"Репо (default: {REPO})")
    parser.add_argument("--dry-run", action="store_true", help="Проверить без пуша")
    parser.add_argument("--pat", help="GitHub PAT (переопределяет Keychain/env/файл)")
    parser.add_argument(
        "--trigger-deploy", action="store_true",
        help="Разрешить CF Pages/CI билд (по умолчанию все коммиты добавляют [skip ci])"
    )
    args = parser.parse_args()

    files = []
    if args.file:
        files.append(args.file)
    if args.files:
        files.extend(args.files)

    if not files:
        parser.error("Укажи --file или --files")

    # CI: больше не добавляем [skip ci] автоматически — CI должен запускаться на каждый коммит.
    # Исключение: если сообщение явно содержит [skip ci] — оставляем как есть.
    message = args.message

    # --pat аргумент имеет приоритет над авто-обнаружением
    if args.pat:
        pat = args.pat.strip()
    else:
        try:
            pat = get_pat()
        except RuntimeError as e:
            print(str(e))
            sys.exit(2)

    if args.dry_run:
        print(f"🔍 DRY RUN — репо: {args.repo}, файлов: {len(files)}")
    else:
        print(f"🚀 Пушу {len(files)} файл(ов) в {args.repo}...")

    results = []
    for f in files:
        r = push_file(pat, f, message, args.repo, dry_run=args.dry_run)
        results.append(r)
        if r.get("ok"):
            if r.get("dry_run"):
                print(f"  🔍 {r['path']} → {r['action']}")
            else:
                print(f"  ✅ {r['path']} (sha: {r.get('sha', '?')})")
        else:
            print(f"  ❌ {r.get('path', f)}: {r.get('error', '?')}")

    failed = [r for r in results if not r.get("ok")]
    if failed:
        print(f"\n⚠️  Не удалось: {len(failed)}/{len(results)}")
        sys.exit(1)
    else:
        print(f"\n✅ Готово: {len(results)} файл(ов)")
        sys.exit(0)


if __name__ == "__main__":
    main()
