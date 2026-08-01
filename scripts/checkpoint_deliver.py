#!/usr/bin/env python3
"""
scripts/checkpoint_deliver.py — ЧЕКПОЙНТ-ДОСТАВКА в ветку-черновик.

Карточка `agent-verification-outlives-cycle-budget`, гипотеза 3.

## Зачем (измерено, не предположено)

Протокол ОБЯЗЫВАЕТ зелёные тесты до пуша (§3.4), а полный срез `spa_core/tests/`
идёт ~900 с на НЕЗАГРУЖЕННОМ хосте и **часами** на загруженном (замер цикла #59:
40 минут → ~50 %, пока фоновый `node` держал 195 % CPU). Оркестратор при этом
живёт ограниченный бюджет. Значит цикл, дошедший до полной верификации, пушит в
последние минуты бюджета — и любая задержка отправляет работу в `/tmp` вместо
`origin`. За трое суток это случилось **семь раз** (#41, #42, #43, #52, #54, #60,
#62): каждый раз работу поднимала руками следующая сессия, пофайловой
археологией по `/tmp`-worktree.

Это структурная неизбежность, а не невезение: единственное место, где живёт
готовая-но-непроверенная работа, — локальная файловая система умирающей сессии.

## Что делает этот инструмент

Даёт работе ВТОРОЕ место жизни — ветку `wip/<сессия>` на `origin`, куда она
уезжает СРАЗУ по готовности, ДО полной верификации. Смерть сессии перестаёт быть
потерей: следующий цикл видит чекпойнт командой `list`, а не поиском по `/tmp`.

**Инвариант #16 НЕ ослаблен, и это главное.** Объём проверок не сокращается ни на
один тест, и чекпойнт НЕ является доставкой: в `main` работа по-прежнему уезжает
только после зелёного полного среза, обычным `push_to_github.py`. Меняется ровно
одно — МОМЕНТ, начиная с которого работа переживает смерть процесса. Коммит
чекпойнта помечен `CHECKPOINT (UNVERIFIED)` в самом сообщении, чтобы его нельзя
было принять за проверенную доставку ни глазами, ни `git log`.

## Почему ветка-черновик ничего не публикует (измерено циклом #65)

Все 12 workflow в `.github/workflows/` срабатывают ТОЛЬКО на `push`/`pull_request`
в `main`, либо по `schedule`, либо по `workflow_dispatch`. Пуш в `wip/*` не
триггерит ни один — проверено разбором блоков `on:` всех двенадцати файлов, а не
принято на веру из отчёта прошлого цикла.

**`landing/**` — ОТКАЗ, без исключений.** Cloudflare Pages билдит сайт по
git-интеграции, ВНЕ GitHub Actions, и может собирать preview-деплой с не-main
ветки. Поэтому чекпойнт не создаёт второго маршрута в обход owner-gate
(ADR-OWN-2026-07): файлы сайта уезжают только через `scripts/safe_site_push.py`.
Отказ здесь fail-CLOSED и снять его флагом нельзя — это не забытая функция.

## Честность вердиктов (класс дефектов #29/#31/#35–#38/#40)

`list` различает ТРИ состояния, а не два: `undelivered` (содержимое чекпойнта на
`main` отличается), `delivered` (всё побайтово совпало с `main`) и **`unmeasured`**
(измерить не удалось). «Не измерено» НИКОГДА не сворачивается в «доставлено» —
именно так этот репозиторий уже семь раз получал успокоительный вердикт о
проверке, которой не было. `drop` удаляет ветку только при `delivered`.

## Граница, которую здесь НЕ переходят (сказано прямо, а не умолчано)

Чекпойнт НЕ прогоняет сверку комплекта доставки
(`push_to_github.enforce_delivery_toolchain`, карточка `agent-host-pusher-copy-is-stale`):
та проверка защищает ДОСТАВКУ от устаревшего инструмента, а чекпойнт доставкой
не является и в `main` ничего не двигает. Не считать, что она отработала.
Защищает чекпойнт другое, и оно измерено тестами: двойной запрет на `main`,
безусловный отказ по `landing/**` и по живому треку.

Только stdlib (инвариант #4). Сеть — единственный побочный эффект, и она
инъецируется параметром `api`, поэтому тесты герметичны.

Запуск:
    python3 scripts/checkpoint_deliver.py push --files <abs...> [--session <id>]
    python3 scripts/checkpoint_deliver.py list [--json]
    python3 scripts/checkpoint_deliver.py drop wip/<сессия>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.error
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_ROOT = Path(__file__).resolve().parent.parent


def _load_pusher():
    """Загрузить КАНОНИЧЕСКИЙ пушер по явному пути (как это делает шим)."""
    spec = importlib.util.spec_from_file_location(
        "_checkpoint_push_root", _ROOT / "push_to_github.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Константы домена ─────────────────────────────────────────────────────────

CHECKPOINT_PREFIX = "wip/"
#: Ветки, в которые чекпойнт не уедет никогда. `main` — потому что чекпойнт по
#: определению НЕ проверен, а `main` обязан быть проверенным (§3.4).
#:
#: ИЗБЫТОЧНОСТЬ ЗДЕСЬ НАМЕРЕННАЯ, НЕ МУСОР. `main` запрещён ДВУМЯ независимыми
#: проверками `guard_branch`: этим списком И требованием префикса `wip/`. Замер
#: цикла #65 (мутационный контроль M1/M1b): снятие ЛЮБОЙ одной из них по
#: отдельности оставляет `main` запрещённым, и только снятие обеих открывает
#: путь. Не «упрощать», убрав одну как якобы недостижимую.
PROTECTED_BRANCHES = frozenset({"main", "master", "trunk", "HEAD", "gh-pages"})

#: Домен owner-gate: только `scripts/safe_site_push.py` (ADR-OWN-2026-07).
SITE_PREFIX = "landing/"
#: Живой go-live трек — автономно не трогается ничем (мандат протокола).
LIVE_TRACK = "data/equity_curve_daily.json"

_RE_SESSION_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

CHECKPOINT_MARK = "CHECKPOINT (UNVERIFIED)"

DELIVERED = "delivered"
UNDELIVERED = "undelivered"
UNMEASURED = "unmeasured"


class CheckpointRefused(RuntimeError):
    """Отказ fail-CLOSED. Никогда не превращается в предупреждение."""


# ── Ветка ────────────────────────────────────────────────────────────────────

def branch_for(session: str) -> str:
    """`cycle65` → `wip/cycle65`. Мусорный идентификатор → ОТКАЗ, не «дефолт».

    Дефолтная ветка здесь была бы худшим из возможных поведений: две сессии
    молча делили бы один чекпойнт и затирали работу друг друга.
    """
    s = (session or "").strip()
    if not s:
        raise CheckpointRefused(
            "идентификатор сессии пуст — ветку чекпойнта не из чего строить "
            "(дефолтной ветки нет намеренно: две сессии затирали бы друг друга)")
    if not _RE_SESSION_OK.match(s):
        raise CheckpointRefused(
            f"идентификатор сессии {s!r} содержит символы, недопустимые в имени "
            "ветки git (разрешены A-Z a-z 0-9 . _ -)")
    return f"{CHECKPOINT_PREFIX}{s}"


def guard_branch(branch: str) -> str:
    """Пропустить только `wip/*`. Всё остальное — отказ."""
    b = (branch or "").strip()
    if not b:
        raise CheckpointRefused("имя ветки пусто")
    if b in PROTECTED_BRANCHES:
        raise CheckpointRefused(
            f"ветка {b!r} защищена: чекпойнт по определению НЕ проверен, а "
            f"{b!r} обязана быть проверенной (§3.4). Проверенная работа уезжает "
            "обычным push_to_github.py")
    if not b.startswith(CHECKPOINT_PREFIX):
        raise CheckpointRefused(
            f"ветка {b!r} не начинается с {CHECKPOINT_PREFIX!r} — чекпойнт "
            "пишет только в свои ветки-черновики")
    if ".." in b or b.endswith("/") or b.endswith(".lock"):
        raise CheckpointRefused(f"имя ветки {b!r} недопустимо для git")
    return b


# ── Файлы ────────────────────────────────────────────────────────────────────

def classify_path(repo_path: str) -> Optional[str]:
    """Вернуть причину отказа для пути, либо None если путь разрешён.

    Причина возвращается ВЕРБАТИМ и целиком — чтобы отказ можно было прочитать
    и проверить, а не гадать, какое из правил сработало.
    """
    p = str(repo_path).replace("\\", "/").lstrip("./")
    if p == LIVE_TRACK:
        return (f"{p}: живой go-live трек — автономный цикл его не публикует "
                "(мандат протокола). Только карточкой владельцу")
    if p.startswith(SITE_PREFIX):
        return (f"{p}: файлы сайта уезжают ТОЛЬКО через scripts/safe_site_push.py "
                "(owner-gate ADR-OWN-2026-07). Cloudflare Pages билдит landing/ по "
                "git-интеграции ВНЕ Actions и может собрать preview с не-main ветки, "
                "поэтому чекпойнт не создаёт второго маршрута в обход гейта")
    return None


def guard_files(repo_paths: Iterable[str]) -> list:
    """Отказать, если хоть один путь запрещён. Отказ — по ВСЕМ сразу.

    Показать первую причину и замолчать об остальных значило бы чинить их по
    одной, по кругу; список причин полный.
    """
    paths = [str(p) for p in repo_paths]
    if not paths:
        raise CheckpointRefused("список файлов пуст — чекпойнтить нечего")
    reasons = [r for r in (classify_path(p) for p in paths) if r]
    if reasons:
        raise CheckpointRefused(
            "чекпойнт отклонён (" + str(len(reasons)) + "):\n  - "
            + "\n  - ".join(reasons))
    return paths


# ── Ссылка на ветку ──────────────────────────────────────────────────────────

def ensure_ref(api: Callable[..., Any], repo: str, branch: str,
               base_sha: str) -> str:
    """Ветка есть → `existed`; нет → создать от `base_sha` и вернуть `created`.

    404 на `GET ref` — единственный код, который считается «ветки нет». Любая
    другая ошибка пробрасывается: «не смог прочитать» не равно «не существует»
    (иначе сетевой сбой молча создавал бы ветку от неверной базы).
    """
    guard_branch(branch)
    try:
        api("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        return "existed"
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    api("POST", f"/repos/{repo}/git/refs",
        {"ref": f"refs/heads/{branch}", "sha": base_sha})
    return "created"


# ── Сообщение коммита ────────────────────────────────────────────────────────

def checkpoint_message(session: str, note: str = "") -> str:
    """Пометка `CHECKPOINT (UNVERIFIED)` обязательна и стоит ПЕРВОЙ.

    Чекпойнт не должен читаться как проверенная доставка ни глазами, ни в
    `git log --oneline`, где видно только начало строки.
    """
    head = f"{CHECKPOINT_MARK} {session}"
    body = (note or "").strip()
    return f"{head}: {body}" if body else head


# ── Вердикт «доставлено ли» ──────────────────────────────────────────────────

def delivery_verdict(checkpoint_blobs: Optional[dict],
                     main_blobs: Optional[dict]) -> tuple:
    """(вердикт, причина). Три состояния, и «не измерено» — отдельное.

    `checkpoint_blobs`/`main_blobs`: {repo_path: blob_sha} либо None, если
    прочитать не удалось. None → `unmeasured`. Ровно здесь этот репозиторий
    семь раз получал бы «всё доставлено» о том, чего не читал.
    """
    if checkpoint_blobs is None or main_blobs is None:
        which = []
        if checkpoint_blobs is None:
            which.append("дерево чекпойнта")
        if main_blobs is None:
            which.append("дерево main")
        return UNMEASURED, "не прочитано: " + ", ".join(which)
    if not checkpoint_blobs:
        return UNMEASURED, "в чекпойнте не найдено ни одного изменённого файла"
    missing = [p for p in checkpoint_blobs if p not in main_blobs]
    differing = [p for p, sha in checkpoint_blobs.items()
                 if p in main_blobs and main_blobs[p] != sha]
    if missing or differing:
        parts = []
        if missing:
            parts.append(f"нет на main: {', '.join(sorted(missing))}")
        if differing:
            parts.append(f"отличается от main: {', '.join(sorted(differing))}")
        return UNDELIVERED, "; ".join(parts)
    return DELIVERED, (f"все {len(checkpoint_blobs)} файл(ов) побайтово совпали "
                       "с main")


def _tree_blobs(api: Callable[..., Any], repo: str, commit_sha: str) -> Optional[dict]:
    """{repo_path: blob_sha} для коммита, либо None если измерить не удалось."""
    try:
        commit = api("GET", f"/repos/{repo}/git/commits/{commit_sha}")
        tree_sha = commit["tree"]["sha"]
        tree = api("GET", f"/repos/{repo}/git/trees/{tree_sha}?recursive=1")
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, TypeError):
        return None
    if tree.get("truncated"):
        # Обрезанное дерево — это НЕ «файла нет». Молчаливое «доставлено» по
        # неполному списку — ровно тот дефект, против которого написан вердикт.
        return None
    return {e["path"]: e["sha"] for e in tree.get("tree", [])
            if e.get("type") == "blob"}


def _resolve_head(api: Callable[..., Any], repo: str, branch: str) -> Optional[str]:
    """Имя ветки → sha коммита, либо None.

    Git Data API (`/git/commits/<sha>`) НЕ принимает имя ветки — только sha.
    Первая версия передавала туда «main», получала ошибку и честно отвечала
    `unmeasured`; вердикт не соврал, но и не работал. Живой прогон это вскрыл,
    а герметичный тест — нет: фейк отвечал на вызов, который настоящий API
    отвергает (тавтология). Фейк приведён к настоящему контракту.
    """
    try:
        ref = api("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        return str(ref["object"]["sha"])
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, TypeError):
        return None


def _changed_vs_base(api: Callable[..., Any], repo: str, branch: str,
                     base: str = "main") -> Optional[dict]:
    """Файлы, которыми ветка отличается от базы: {repo_path: blob_sha}."""
    try:
        cmp_ = api("GET", f"/repos/{repo}/compare/{base}...{branch}")
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None
    files = cmp_.get("files")
    if files is None:
        return None
    return {f["filename"]: f["sha"] for f in files
            if f.get("status") != "removed" and f.get("sha")}


# ── Команды ──────────────────────────────────────────────────────────────────

def list_checkpoints(api: Callable[..., Any], repo: str) -> list:
    """Все ветки `wip/*` с вердиктом доставки. Источник правды — origin."""
    try:
        refs = api("GET", f"/repos/{repo}/git/matching-refs/heads/{CHECKPOINT_PREFIX}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    out = []
    for ref in refs or []:
        branch = str(ref.get("ref", "")).replace("refs/heads/", "")
        head = (ref.get("object") or {}).get("sha", "")
        changed = _changed_vs_base(api, repo, branch)
        main_blobs = None
        if changed is not None:
            main_sha = _resolve_head(api, repo, "main")
            if main_sha:
                main_blobs = _tree_blobs(api, repo, main_sha)
        if changed is None:
            verdict, why = delivery_verdict(None, None)
        else:
            verdict, why = delivery_verdict(changed, main_blobs)
        out.append({
            "branch": branch,
            "session": branch[len(CHECKPOINT_PREFIX):],
            "head": head,
            "files": sorted(changed) if changed else [],
            "verdict": verdict,
            "why": why,
        })
    return out


def checkpoint_push(files: list, session: str, note: str = "",
                    repo: Optional[str] = None, pat: Optional[str] = None,
                    api: Optional[Callable[..., Any]] = None,
                    pusher: Any = None, dry_run: bool = False) -> dict:
    """Уложить `files` ОДНИМ коммитом в `wip/<session>`. Ничего не публикует."""
    pusher = pusher or _load_pusher()
    repo = repo or pusher.REPO
    branch = guard_branch(branch_for(session))

    resolved = pusher.resolve_files(files)          # fail-CLOSED на путях
    repo_paths = [rp for rp, _ in resolved]
    guard_files(repo_paths)

    message = checkpoint_message(session, note)
    if dry_run:
        return {"ok": True, "dry_run": True, "branch": branch,
                "files": repo_paths, "message": message}

    if pat is None:
        pat = pusher.get_pat()
    if api is None:
        def api(method, path, payload=None):
            return pusher._api(pat, method, path, payload)

    base_commit, _ = pusher.get_base_ref(pat, repo, "main")
    ref_state = ensure_ref(api, repo, branch, base_commit)

    result: dict = dict(pusher.batch_push(pat, files, message, repo, branch))
    result.update({"branch": branch, "ref": ref_state, "message": message,
                   "checkpoint": True})
    return result


def drop_checkpoint(api: Callable[..., Any], repo: str, branch: str,
                    force: bool = False) -> dict:
    """Удалить ветку чекпойнта. Только `delivered` — иначе отказ.

    `force` существует для случая «работа осознанно брошена» и обязан быть
    явным: неизмеренный вердикт не должен удалять работу, которую не читали.
    """
    guard_branch(branch)
    rows = [r for r in list_checkpoints(api, repo) if r["branch"] == branch]
    if not rows:
        raise CheckpointRefused(f"ветки {branch!r} среди чекпойнтов нет")
    row = rows[0]
    if row["verdict"] != DELIVERED and not force:
        raise CheckpointRefused(
            f"ветка {branch!r}: вердикт {row['verdict']} ({row['why']}) — "
            "удаляется только доставленное. Работу, которая не измерена или не "
            "доставлена, чекпойнт не уничтожает (--force, если брошена осознанно)")
    api("DELETE", f"/repos/{repo}/git/refs/heads/{branch}")
    return {"ok": True, "branch": branch, "verdict": row["verdict"],
            "forced": bool(force and row["verdict"] != DELIVERED)}


# ── CLI ──────────────────────────────────────────────────────────────────────

def _session_default() -> str:
    return (os.environ.get("SPA_SESSION_ID") or "").strip()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Чекпойнт-доставка непроверенной работы в ветку-черновик "
                    "(НЕ замена проверенной доставки в main)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("push", help="уложить файлы в wip/<сессия>")
    sp.add_argument("--files", nargs="+", required=True, help="абсолютные пути")
    sp.add_argument("--session", default=None, help="идентификатор сессии")
    sp.add_argument("--note", default="", help="что сделано (в тело сообщения)")
    sp.add_argument("--dry-run", action="store_true")

    sl = sub.add_parser("list", help="открытые чекпойнты на origin")
    sl.add_argument("--json", action="store_true")

    sd = sub.add_parser("drop", help="удалить ветку доставленного чекпойнта")
    sd.add_argument("branch")
    sd.add_argument("--force", action="store_true")

    a = p.parse_args(argv)
    pusher = _load_pusher()

    def _api_factory():
        pat = pusher.get_pat()
        return lambda m, path, payload=None: pusher._api(pat, m, path, payload)

    try:
        if a.cmd == "push":
            session = (a.session or _session_default())
            r = checkpoint_push(a.files, session, note=a.note, dry_run=a.dry_run,
                                pusher=pusher)
            tag = "DRY RUN — " if r.get("dry_run") else ""
            print(f"{tag}чекпойнт → {r['branch']}  ({len(r.get('files') or [])} файл(ов))")
            if not r.get("dry_run"):
                print(f"  commit {str(r.get('commit') or '')[:9]}  ref: {r.get('ref')}")
                print("  ЭТО НЕ ДОСТАВКА: в main работа уезжает только после "
                      "зелёного полного среза, обычным push_to_github.py")
            return 0

        if a.cmd == "list":
            rows = list_checkpoints(_api_factory(), pusher.REPO)
            if a.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            elif not rows:
                print("открытых чекпойнтов нет")
            else:
                for r in rows:
                    print(f"{r['branch']:<28} {r['verdict']:<12} {r['head'][:9]}  "
                          f"файлов: {len(r['files'])}")
                    print(f"    {r['why']}")
            # Код возврата — сигнал шагу 0a: есть недоставленное / есть неизмеренное.
            if any(r["verdict"] == UNMEASURED for r in rows):
                return 2
            return 1 if any(r["verdict"] == UNDELIVERED for r in rows) else 0

        if a.cmd == "drop":
            r = drop_checkpoint(_api_factory(), pusher.REPO, a.branch, force=a.force)
            print(f"удалена {r['branch']} (вердикт: {r['verdict']})")
            return 0
    except CheckpointRefused as e:
        print(f"ОТКАЗ: {e}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
