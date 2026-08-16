#!/usr/bin/env python3
"""
push_to_github_batch.py — BATCHED пуш многих файлов в GitHub ОДНИМ коммитом
через GitHub Git Data API.

ЗАЧЕМ ОТДЕЛЬНЫЙ CLI: исторически batch был единственным атомарным путём, и на
него завязаны вызывающие (`scripts/safe_site_push.py`, `deploy_site_snapshot.py`,
`site_freshness_monitor.py`, `agent_novel_edge_rnd.sh`). Сегодня «N файлов = один
коммит» умеет и канонический `push_to_github.py` — РЕАЛИЗАЦИЯ У НИХ ОДНА (см.
блок делегирования ниже), этот файл остался стабильной точкой входа.

Шаги Git Data API (реализация — `push_to_github.py::batch_push`):
  1. GET  /repos/{REPO}/git/ref/heads/{branch}      → base commit sha
  2. GET  /repos/{REPO}/git/commits/{base_sha}      → base tree sha
  3. POST /repos/{REPO}/git/blobs  (per file)       → blob sha (base64)
  4. POST /repos/{REPO}/git/trees  (base_tree + entries) → new tree sha
  5. POST /repos/{REPO}/git/commits (tree, parents) → new commit sha
  6. PATCH /repos/{REPO}/git/refs/heads/{branch}    → move ref → 1 коммит, 1 CF build

Stdlib only (сеть/кодирование — в каноническом модуле, здесь только CLI).
Drop-in CLI совместим с push_to_github.py:
  python3 push_to_github_batch.py --message "msg" --files <abs paths...>
  python3 push_to_github_batch.py --message "msg" file1 file2     (positional)
  python3 push_to_github_batch.py --dry-run --files ...           (no writes)

НЕ поддерживает удаления (add/update только) — удаления через Contents API отдельно.
НЕ содержит hardcoded secrets — PAT из Keychain GITHUB_PAT_SPA (см. get_pat).
"""
import os
import sys
import argparse
import subprocess
import urllib.error
from pathlib import Path

REPO = "yurii-spa/SPA"
API_BASE = "https://api.github.com"
PROJECT_ROOT = Path("/Users/yuriikulieshov/Documents/SPA_Claude")

# ── Определение пути внутри репо — ОДНА реализация на оба пушера ────────────────
# Историю см. в push_to_github.py::repo_relative_path: копия этой логики здесь
# молча роняла worktree-путь в basename, и файл уезжал в КОРЕНЬ репо (для
# landing/** это значит, что страница сайта НЕ менялась, а в корне появлялся
# стрэй). Второй копии больше нет — грузим канонический модуль по явному пути
# (не через sys.path: launchd-окружение не гарантирует cwd). Не загрузился →
# падаем сразу, а не работаем со старой ловушкой.
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "_push_to_github_root", Path(__file__).resolve().parent / "push_to_github.py")
if _spec is None or _spec.loader is None:
    raise RuntimeError(
        "рядом с push_to_github_batch.py не найден канонический push_to_github.py — "
        "определение пути внутри репо живёт только там. Пуш невозможен (fail-CLOSED)."
    )
_root_push = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_root_push)
repo_relative_path = _root_push.repo_relative_path
RepoPathError = _root_push.RepoPathError

# Источник ФАЙЛА (а не пути внутри репо) — тоже ОДНА реализация: относительный
# путь читается из ДЕРЕВА ОТПРАВКИ, а не из хост-чекаута PROJECT_ROOT (карточка
# `agent-pusher-relative-path-silently-reads-the-host-tree`, цикл #109). Под этим
# CLI стоит safe_site_push — «файл взят из чужого дерева» нельзя починить в одном
# пушере и забыть в другом.
resolve_local_path = _root_push.resolve_local_path
delivery_tree = _root_push.delivery_tree
tree_divergence_note = _root_push.tree_divergence_note
DeliveryTreeError = _root_push.DeliveryTreeError


# ── Реализация доставки — ОДНА, живёт в каноническом push_to_github.py ─────────
# Здесь были СВОИ копии get_pat / _api / get_base_ref / resolve_files /
# create_blob / create_tree / create_commit / update_ref / batch_push. Копия
# логики доставки — тот самый механизм, которым цикл #37 оставил CI красным
# (починили один экземпляр из двух), а цикл #40 разослал файлы в корень репо
# (вторая копия repo_relative_path). Второй копии больше нет: оба CLI зовут
# одни и те же функции, поэтому «N файлов = 1 коммит», сохранение x-бита и
# идемпотентность нельзя починить в одном пушере и забыть в другом.
get_pat = _root_push.get_pat
_api = _root_push._api
get_base_ref = _root_push.get_base_ref
resolve_files = _root_push.resolve_files
remote_tree_modes = _root_push.remote_tree_modes
tree_entry_mode = _root_push.tree_entry_mode
create_blob = _root_push.create_blob
create_tree = _root_push.create_tree
create_commit = _root_push.create_commit
update_ref = _root_push.update_ref
split_unchanged = _root_push.split_unchanged
batch_push = _root_push.batch_push
TreeModeError = _root_push.TreeModeError
BLOB_MODE = _root_push.BLOB_MODE
EXEC_MODE = _root_push.EXEC_MODE

# Страж перезаписи — тоже ОДНА реализация на оба CLI (карточка
# `agent-shared-doc-whole-file-push-overwrites`): под этим файлом стоит
# `safe_site_push.py`, и «доставка целыми файлами стирает чужую правку»
# чинится в одном месте, а не в двух.
create_blob_from_bytes = _root_push.create_blob_from_bytes
build_entries = _root_push.build_entries
guard_overwrite = _root_push.guard_overwrite
divergence_verdict = _root_push.divergence_verdict
rebase_append = _root_push.rebase_append
base_version = _root_push.base_version
get_file_content = _root_push.get_file_content
DivergenceRefused = _root_push.DivergenceRefused
DIVERGENCE_SAFE = _root_push.DIVERGENCE_SAFE
DIVERGENCE_DIVERGED = _root_push.DIVERGENCE_DIVERGED
DIVERGENCE_UNMEASURED = _root_push.DIVERGENCE_UNMEASURED
# Защита общей памяти (ADR-070 п.7) — из того же одного места. Ловля по
# `DivergenceRefused` работала бы и без этих строк (оба отказа — его подклассы),
# но символ, которого в CLI нет, нельзя ни поймать точечно, ни проверить тестом.
# `EntryLossRefused` не был экспортирован с самого начала — тот же недосмотр.
EntryLossRefused = _root_push.EntryLossRefused
UnmeasuredBaseRefused = _root_push.UnmeasuredBaseRefused
is_append_only_doc = _root_push.is_append_only_doc
is_shared_memory_doc = _root_push.is_shared_memory_doc

# Сверка доставленного (карточка `agent-pusher-does-not-verify-what-it-delivered`)
# — тоже ОДНА реализация: под этим CLI стоит `safe_site_push.py`, и «пушер
# отчитался OK о доставке, которую не сверял» нельзя починить в одном пушере.
DeliveryUnverified = _root_push.DeliveryUnverified
verify_sha_delivery = _root_push.verify_sha_delivery
verify_blob_delivery = _root_push.verify_blob_delivery

# Сверка инструмента доставки (карточка `agent-host-pusher-copy-is-stale`) —
# тоже ОДНА реализация: копия пушера в хост-репо отстала на 574 строки и без
# сверки молча доставляла по-старому.
enforce_delivery_toolchain = _root_push.enforce_delivery_toolchain
toolchain_verdict = _root_push.toolchain_verdict
ToolchainMismatch = _root_push.ToolchainMismatch
TOOLCHAIN_FILES = _root_push.TOOLCHAIN_FILES


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
    parser.add_argument("--allow-overwrite", action="store_true",
                        help="ОСОЗНАННО стереть правку, появившуюся на remote после нашей базы")
    parser.add_argument("--allow-toolchain-mismatch", action="store_true",
                        help="ОСОЗНАННО пушить инструментом, который разошёлся с копией в дереве "
                             "отправляемых файлов")
    args = parser.parse_args()

    allow_overwrite = bool(args.allow_overwrite) or \
        os.environ.get("SPA_PUSH_ALLOW_OVERWRITE") == "1"
    allow_toolchain = bool(args.allow_toolchain_mismatch) or \
        os.environ.get("SPA_PUSH_ALLOW_TOOLCHAIN_MISMATCH") == "1"

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

    # ── СВЕРКА ИНСТРУМЕНТА ДОСТАВКИ (карточка `agent-host-pusher-copy-is-stale`) ──
    # Реализация — одна, в каноническом модуле; здесь только вызов. Про `__file__`:
    # сверять надо дерево ЗАПУЩЕННОГО batch-CLI, а не канонического модуля,
    # который он загрузил (они всегда рядом, но подмена в тестах не должна врать).
    try:
        enforce_delivery_toolchain(all_files, allow=allow_toolchain, runner_file=__file__)
    except ToolchainMismatch:
        sys.exit(5)

    # ── OWNER-GATE INTERLOCK (ADR-OWN-2026-07) — autonomous context ONLY ──────────
    # Same guard as push_to_github.py: in the autonomous orchestrator (SPA_AUTONOMOUS=1)
    # any landing/ push MUST have passed the owner-gate guard via safe_site_push.py
    # (SPA_SITE_PUSH_VERIFIED=1). Otherwise re-run the guard and FAIL CLOSED.
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
                            dry_run=args.dry_run, allow_overwrite=allow_overwrite)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"\nFAIL HTTP {e.code}: {body[:500]}")
        sys.exit(1)
    except DivergenceRefused as e:
        print(f"\nОТКАЗ (страж перезаписи): {e}", file=sys.stderr)
        sys.exit(4)
    except DeliveryUnverified as e:
        # Не «не доставили», а «доставили НЕ ТО» — тот же код выхода, что и в
        # каноническом CLI, чтобы вызывающие (safe_site_push, кастодиан) могли
        # различать эти случаи одинаково в обоих путях.
        print(f"\nОТКАЗ (сверка доставленного): {e}", file=sys.stderr)
        sys.exit(6)
    except Exception as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)

    if result.get("dry_run"):
        print(f"\nDRY OK: {result['count']} файл(ов) попали бы в 1 коммит")
    elif result["count"] == 0:
        # Всё содержимое уже на remote ⇒ коммита нет вовсе (раньше здесь
        # создавался ПУСТОЙ коммит — и, для landing/**, лишняя сборка CF Pages).
        print(f"\nOK: {result['skipped']} файл(ов) уже на remote — коммита не потребовалось")
    else:
        print(f"\nOK: 1 коммит {result['commit'][:8]} со {result['count']} файл(ами)"
              f" (skipped={result['skipped']})")
    sys.exit(0)


if __name__ == "__main__":
    main()
