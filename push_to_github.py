#!/usr/bin/env python3
"""
push_to_github.py — универсальный пуш файлов в GitHub.
Читает PAT из переменной окружения GITHUB_PAT, файла ~/.spa_pat
или macOS Keychain (сервис GITHUB_PAT_SPA).
НЕ содержит hardcoded secrets.

ДОСТАВКА (что уезжает и как):
  * ОДИН файл  → Contents API, один PUT = один коммит (как было);
  * НЕСКОЛЬКО  → Git Data API (blobs → tree → commit → ref): весь набор
    приземляется ОДНИМ коммитом. Contents API принимает по одному файлу за
    вызов, поэтому раньше набор из N взаимозависимых файлов давал N коммитов
    и промежуточные состояния `main` были КРАСНЫМИ (карточка
    `agent-push-batch-per-file-commits`). Git Data API недоступен → честный
    отказ; файлы НЕ дошлются по одному молча.
  * неизменённые файлы пропускаются на обоих путях (пустых коммитов нет);
  * режим (x-бит) существующего файла сохраняется — снятый x-бит с
    bash-обёртки launchd = агент exit-78 (инвариант #12).

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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

REPO = "yurii-spa/SPA"
API_BASE = "https://api.github.com"
PROJECT_ROOT = Path("/Users/yuriikulieshov/Documents/SPA_Claude")

# Режимы записей дерева. Git различает обычный файл и исполняемый; в этом репо
# 27 файлов — 100755, и среди них bash-обёртки launchd (`scripts/auto_push.sh`,
# `scripts/install_agents.sh`, …). Потерянный x-бит = агент падает exit-78
# (инвариант #12), поэтому режим существующего файла НИКОГДА не выдумывается.
BLOB_MODE = "100644"
EXEC_MODE = "100755"


class RepoPathError(ValueError):
    """Локальный путь не удалось отобразить в путь ВНУТРИ целевого репозитория.

    Раньше этот случай молча превращался в ``local.name`` — файл уезжал в КОРЕНЬ
    репо под своим basename, а инструмент печатал ``OK`` с настоящей sha
    (цикл #40: 6 файлов из worktree легли в корень). Теперь это жёсткая ошибка:
    fail-CLOSED, инвариант #2 — лучше отказать, чем доставить не туда.
    """


def _git_out(args: list, cwd) -> Optional[str]:
    """Один `git -C <cwd> <args>`; None на любой сбой (нет git / не репо / ошибка).

    Никогда не бросает: отсутствие git в PATH (launchd-окружение autopush!) —
    штатный сценарий, вызывающий код падает обратно на PROJECT_ROOT.
    """
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _common_git_dir(start) -> Optional[Path]:
    """Разрешённый *общий* .git-каталог репозитория, содержащего ``start``.

    Все linked worktrees одного репозитория делят ОДИН common dir, поэтому это
    точный признак «тот же самый репозиторий», а не «просто какой-то git-репо».
    """
    out = _git_out(["rev-parse", "--git-common-dir"], start)
    if not out:
        return None
    p = Path(out)
    if not p.is_absolute():          # git отдаёт ".git" относительно cwd
        p = Path(start) / p
    try:
        return p.resolve()
    except OSError:
        return None


def repo_relative_path(local: Path, project_root: Optional[Path] = None) -> str:
    """Путь файла ВНУТРИ репозитория. Fail-CLOSED: никогда не возвращает basename.

    Корень определяется ПО ФАКТУ (`git rev-parse --show-toplevel`), а не по
    константе — поэтому файл из изолированного worktree (`/tmp/spa_wt_*/...`),
    в котором протокол оркестратора ОБЯЗЫВАЕТ работать (§3.4), релятивизируется
    правильно. Порядок:

      1. worktree/checkout, содержащий файл, принадлежит ТОМУ ЖЕ репозиторию,
         что и ``project_root`` (сверка по common git dir) → путь от его toplevel;
      2. иначе (git недоступен / не репо / сверку не провести) → путь от
         ``project_root``, как было исторически;
      3. иначе → :class:`RepoPathError`.

    Чужой репозиторий и путь вне любого репо дают ошибку, а не догадку.
    ``project_root=None`` берёт модульный :data:`PROJECT_ROOT` в момент ВЫЗОВА
    (а не в момент определения функции) — иначе константу нельзя подменить в тестах.
    """
    if project_root is None:
        project_root = PROJECT_ROOT
    local_res = Path(local).resolve()
    root_res = Path(project_root).resolve()

    parent = Path(local).parent
    top = _git_out(["rev-parse", "--show-toplevel"], parent) if parent.exists() else None
    if top:
        mine, theirs = _common_git_dir(parent), _common_git_dir(project_root)
        if mine is not None and theirs is not None and mine == theirs:
            try:
                return str(local_res.relative_to(Path(top).resolve()))
            except ValueError:
                pass  # ниже — попытка от project_root, затем честная ошибка

    try:
        return str(local_res.relative_to(root_res))
    except ValueError:
        raise RepoPathError(
            f"не могу определить путь внутри репозитория для {local}: путь вне "
            f"{project_root} и не принадлежит рабочей копии ЭТОГО же репозитория. "
            f"Пуш отменён (fail-CLOSED) — раньше здесь молча бралось имя файла и "
            f"файл уезжал в КОРЕНЬ репо. Передай путь внутри {project_root} либо "
            f"сделай worktree через `git worktree add`."
        )


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
              branch: str = "main", _stale_retries: int = 2) -> dict:
    """Пушит один файл через GitHub Contents API.

    409 stale-sha auto-retry: если параллельный писатель обновил файл между нашим
    get_file_sha и PUT, GitHub вернёт 409 (sha не совпадает с HEAD). Тогда мы
    заново читаем актуальный remote sha и повторяем PUT — до ``_stale_retries`` раз.
    Детерминированно, fail-safe (исчерпали ретраи → честный FAIL).
    """
    import urllib.request
    import urllib.error

    local = Path(local_path)
    # Resolve relative to PROJECT_ROOT if not absolute
    if not local.is_absolute():
        local = PROJECT_ROOT / local
    if not local.exists():
        return {"ok": False, "error": f"Файл не найден: {local_path}", "path": local_path}

    # Путь внутри репо. Fail-CLOSED: не удалось определить → честный FAIL,
    # а НЕ basename в корень репо (см. repo_relative_path).
    try:
        repo_path = repo_relative_path(local)
    except RepoPathError as e:
        return {"ok": False, "error": str(e), "path": local_path}

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
            return push_file(pat, local_path, message, repo, dry_run, branch, _stale_retries)
        # 409 stale-sha: параллельный писатель сдвинул HEAD. Перечитываем свежий
        # remote sha и повторяем PUT (bounded). 422 тоже может означать рассинхрон
        # sha ("does not match") — обрабатываем так же.
        if (e.code == 409 or (e.code == 422 and "sha" in body.lower())) and _stale_retries > 0:
            print(f"  409 stale-sha — перечитываю remote sha и повторяю ({_stale_retries} осталось)...")
            time.sleep(0.5)
            return push_file(pat, local_path, message, repo, dry_run, branch, _stale_retries - 1)
        return {"ok": False, "error": f"HTTP {e.code}: {body[:300]}", "path": repo_path}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": repo_path}


# ══════════════════════════════════════════════════════════════════════════════
# Git Data API: N файлов = ОДИН коммит
#
# ЗАЧЕМ (карточка `agent-push-batch-per-file-commits`, найдено циклом #48):
# Contents API принимает по ОДНОМУ файлу за вызов, поэтому набор из N
# взаимозависимых файлов приземлялся N последовательными коммитами — и
# промежуточные состояния дерева НЕСОГЛАСОВАНЫ. Измерено на реальных прогонах
# Actions: из пяти коммитов одного пуша ДВА промежуточных дали `SPA Tests` /
# `SPA CI` = failure (тесты уже на `main`, а правки, которые они проверяют, —
# ещё нет). Регулярный «нормальный» красный main учит игнорировать сигнал
# (инвариант #16), ломает `git bisect` и отправляет следующую сессию искать
# несуществующий дефект (ровно этим занимался цикл #47).
#
# Реализация ОДНА на оба CLI: `push_to_github_batch.py` импортирует эти функции
# отсюда, своих копий не держит (близнец такой же логики — механизм, которым
# цикл #37 оставил CI красным, а цикл #40 разослал файлы в корень репо).
# ══════════════════════════════════════════════════════════════════════════════


class TreeModeError(RuntimeError):
    """Режим (x-бит) файла, уже лежащего на remote, определить не удалось.

    Fail-CLOSED: молча поставить `100644` значит СНЯТЬ исполняемый бит с
    bash-обёртки launchd — агент после такого падает exit-78 (инвариант #12),
    и увидеть это можно только по мёртвому агенту. Лучше отказать в пуше.
    """


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
    base_commit_sha = str(ref["object"]["sha"])
    commit = _api(pat, "GET", f"/repos/{repo}/git/commits/{base_commit_sha}")
    base_tree_sha = str(commit["tree"]["sha"])
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
            repo_path = repo_relative_path(local)
        except RepoPathError as e:
            raise RuntimeError(str(e))   # fail-CLOSED: весь батч не уезжает
        resolved.append((repo_path, local))
    return resolved


def remote_tree_modes(pat: str, repo: str, tree_sha: str) -> tuple:
    """Карта `путь → режим` ветки. Вернуть (modes, truncated).

    Один рекурсивный GET на всё дерево. GitHub усекает ответ на очень больших
    деревьях и честно помечает это флагом ``truncated`` — тогда карта неполная,
    и ОТСУТСТВИЕ пути в ней уже НЕ значит «файла на remote нет» (см.
    :func:`tree_entry_mode`, который в этом случае отказывает, а не угадывает).
    """
    data = _api(pat, "GET", f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
    modes = {e["path"]: e["mode"] for e in data.get("tree", [])
             if e.get("type") == "blob" and e.get("path") and e.get("mode")}
    return modes, bool(data.get("truncated"))


def tree_entry_mode(repo_path: str, abs_path: Path, modes: dict, truncated: bool) -> str:
    """Режим записи дерева для файла.

    - файл уже есть на remote → его СОБСТВЕННЫЙ режим (x-бит сохраняется);
    - карта полная и пути в ней нет → файл новый, режим по правилу git:
      исполняемый локально → ``100755``, иначе ``100644``;
    - карта усечена и пути в ней нет → существование НЕ ИЗМЕРЕНО →
      :class:`TreeModeError` (fail-CLOSED, не догадка).
    """
    existing = modes.get(repo_path)
    if existing:
        return str(existing)
    if truncated:
        raise TreeModeError(
            f"дерево ветки пришло усечённым (GitHub `truncated: true`), и для "
            f"{repo_path} режим файла не измерен: если файл на remote исполняемый, "
            f"пуш снял бы x-бит молча. Пуш отменён (fail-CLOSED)."
        )
    return EXEC_MODE if os.access(abs_path, os.X_OK) else BLOB_MODE


def create_blob(pat: str, repo: str, abs_path: Path) -> str:
    """Шаг 3: создать blob из файла (base64, безопасно для бинарных и текстовых)."""
    content_b64 = base64.b64encode(Path(abs_path).read_bytes()).decode()
    blob = _api(pat, "POST", f"/repos/{repo}/git/blobs",
                {"content": content_b64, "encoding": "base64"})
    return str(blob["sha"])


def create_tree(pat: str, repo: str, base_tree_sha: str, entries: list) -> str:
    """Шаг 4: новое дерево = base_tree + по записи на файл."""
    tree = _api(pat, "POST", f"/repos/{repo}/git/trees",
                {"base_tree": base_tree_sha, "tree": entries})
    return str(tree["sha"])


def create_commit(pat: str, repo: str, message: str, tree_sha: str, parent_sha: str) -> str:
    """Шаг 5: один коммит со всеми изменениями."""
    commit = _api(pat, "POST", f"/repos/{repo}/git/commits",
                  {"message": message, "tree": tree_sha, "parents": [parent_sha]})
    return str(commit["sha"])


def update_ref(pat: str, repo: str, branch: str, commit_sha: str, force: bool = False) -> dict:
    """Шаг 6: переместить ветку на новый коммит."""
    return _api(pat, "PATCH", f"/repos/{repo}/git/refs/heads/{branch}",
                {"sha": commit_sha, "force": force})


def split_unchanged(pat: str, repo: str, branch: str, files: list) -> tuple:
    """Разделить [(repo_path, abs)] на (changed, unchanged) по git-blob-SHA.

    Та же идемпотентность, что у :func:`push_file`, и с тем же направлением
    ошибки: пропускаем ТОЛЬКО при точном совпадении remote sha с локальным
    blob-SHA; любая неопределённость (sha=None — новый файл ИЛИ сетевая
    ошибка) → файл считается изменённым и уезжает. Реальные правки не теряются.
    """
    changed, unchanged = [], []
    for repo_path, abs_path in files:
        local_sha = git_blob_sha(Path(abs_path).read_bytes())
        remote_sha = get_file_sha(pat, repo, repo_path, branch)
        if remote_sha is not None and remote_sha == local_sha:
            unchanged.append((repo_path, abs_path, remote_sha))
        else:
            changed.append((repo_path, abs_path))
    return changed, unchanged


def batch_push(pat: str, file_args: list, message: str, repo: str, branch: str,
               dry_run: bool = False) -> dict:
    """Собрать N файлов в ОДИН коммит через Git Data API.

    Порядок: разрешить пути (fail-CLOSED) → отсеять неизменённые →
    blobs → tree (с сохранением режимов) → commit → move ref.
    Ничего не изменилось → коммита НЕТ вовсе (пустые коммиты не создаются).
    """
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

    changed, unchanged = split_unchanged(pat, repo, branch, files)
    for repo_path, _, remote_sha in unchanged:
        print(f"  SKIP {repo_path} (unchanged, sha: {remote_sha[:8]})")
    if not changed:
        print("  всё содержимое уже на remote — коммит не создаётся")
        return {"ok": True, "count": 0, "commit": None, "skipped": len(unchanged),
                "files": [], "skipped_files": [p for p, _, _ in unchanged]}

    modes, truncated = remote_tree_modes(pat, repo, base_tree_sha)

    # Шаг 3: blobs (+ режим существующего файла сохраняется как есть)
    entries = []
    for repo_path, abs_path in changed:
        mode = tree_entry_mode(repo_path, abs_path, modes, truncated)
        blob_sha = create_blob(pat, repo, abs_path)
        print(f"  blob {blob_sha[:8]}  {repo_path}"
              f"{'  (exec)' if mode == EXEC_MODE else ''}")
        entries.append({
            "path": repo_path,
            "mode": mode,
            "type": "blob",
            "sha": blob_sha,
        })

    # Шаг 4: tree
    new_tree_sha = create_tree(pat, repo, base_tree_sha, entries)
    print(f"  tree {new_tree_sha[:8]}")

    # Шаг 5: commit
    new_commit_sha = create_commit(pat, repo, message, new_tree_sha, base_commit_sha)
    print(f"  commit {new_commit_sha[:8]}")

    # Шаг 6: move ref, с одним ретраем на устаревшую базу.
    # Коды: 409 (conflict) И 422 — GitHub отвечает именно 422 «Update is not a
    # fast forward», когда параллельный писатель сдвинул ветку между нашим
    # чтением базы и PATCH (в этом репо такой писатель есть: autopush + дневной
    # цикл). Ветка только на 409 не срабатывала бы на реальном коде ошибки.
    try:
        update_ref(pat, repo, branch, new_commit_sha)
    except urllib.error.HTTPError as e:
        if e.code in (409, 422):
            body = e.read().decode(errors="replace")
            print(f"  HTTP {e.code} stale ref: {body[:200]} — пересобираю на свежей базе...")
            # Пересобираем коммит поверх свежего HEAD (база сдвинулась). Режимы
            # перечитываем на СВЕЖЕМ дереве: параллельный писатель мог менять и их.
            fresh_base_commit, fresh_base_tree = get_base_ref(pat, repo, branch)
            fresh_modes, fresh_truncated = remote_tree_modes(pat, repo, fresh_base_tree)
            for entry, (repo_path, abs_path) in zip(entries, changed):
                entry["mode"] = tree_entry_mode(repo_path, abs_path,
                                                fresh_modes, fresh_truncated)
            new_tree_sha = create_tree(pat, repo, fresh_base_tree, entries)
            new_commit_sha = create_commit(pat, repo, message, new_tree_sha, fresh_base_commit)
            print(f"  recommit {new_commit_sha[:8]} (parent {fresh_base_commit[:8]})")
            update_ref(pat, repo, branch, new_commit_sha)
        else:
            raise

    return {"ok": True, "count": len(changed), "commit": new_commit_sha,
            "tree": new_tree_sha, "skipped": len(unchanged),
            "files": [p for p, _ in changed],
            "skipped_files": [p for p, _, _ in unchanged]}


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

    # ── OWNER-GATE INTERLOCK (ADR-OWN-2026-07) — autonomous context ONLY ──────────
    # In the autonomous orchestrator (SPA_AUTONOMOUS=1) any push touching landing/ MUST
    # have passed the owner-gate guard via scripts/safe_site_push.py (which sets
    # SPA_SITE_PUSH_VERIFIED=1). If not, re-run the guard here and FAIL CLOSED. Attended
    # sessions and the deterministic custodian run WITHOUT SPA_AUTONOMOUS → unaffected.
    if (not args.dry_run and os.environ.get("SPA_AUTONOMOUS") == "1"
            and os.environ.get("SPA_SITE_PUSH_VERIFIED") != "1"):
        _site = [f for f in all_files if "landing/" in str(f).replace("\\", "/")]
        if _site:
            _guard = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "scripts", "check_owner_gate.py")
            _rc = subprocess.run([sys.executable, _guard, "--diff-mode", "files",
                                  "--files", *_site, "--commit-message", message]).returncode
            if _rc != 0:
                print(f"BLOCKED (owner-gate rc={_rc}): autonomous site push must go through "
                      f"scripts/safe_site_push.py → owner card. Not pushing.", file=sys.stderr)
                sys.exit(3)

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
        if len(all_files) > 1:
            print("  (реальный пуш уложил бы изменённые файлы в ОДИН коммит)")
    else:
        print(f"Пушу {len(all_files)} файл(ов) в {args.repo} ({args.branch})...")

    # ── НАБОР ФАЙЛОВ = ОДИН КОММИТ ───────────────────────────────────────────
    # Contents API берёт по одному файлу за вызов ⇒ N взаимозависимых файлов
    # приземлялись N коммитами, и промежуточные состояния `main` были красными
    # (измерено на реальных прогонах Actions, цикл #48). Набор уезжает атомарно.
    # Одиночный файл — прежним путём: один PUT = один коммит, менять нечего.
    # Отката «дошлю по одному» НЕТ по требованию карточки: Git Data API
    # недоступен → честный отказ, а не тихий возврат к рваной доставке.
    if len(all_files) > 1 and not args.dry_run:
        try:
            result = batch_push(pat, all_files, message, args.repo, args.branch)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            print(f"\nFAIL HTTP {e.code}: {body[:500]}")
            print("Файлы НЕ досылались по одному: рваный набор на main — то, "
                  "что этот путь и устраняет (fail-CLOSED).", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\nFAIL: {e}")
            print("Файлы НЕ досылались по одному: рваный набор на main — то, "
                  "что этот путь и устраняет (fail-CLOSED).", file=sys.stderr)
            sys.exit(1)
        if result["count"] == 0:
            print(f"\nOK: {result['skipped']} файл(ов) уже на remote — коммита не потребовалось")
        else:
            print(f"\nOK: 1 коммит {result['commit'][:8]} — {result['count']} файл(ов) "
                  f"(skipped={result['skipped']})")
        sys.exit(0)

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
