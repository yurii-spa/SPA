"""Release ACTIVATION resolver (PROPOSED ADR-500, revised for ARB) — the piece the marker-only design was
missing: it proves which EXACT code a process will execute BEFORE exec, because Python imports resolve from
the filesystem, not from a marker.

ARB proof requirement: given APPROVED=A while the shared tree already holds STAGED=B, what operation makes an
agent execute A rather than B? Answer here (Option B — immutable release directory):

  * Each approved release is materialised ONCE into an immutable, content-addressed directory
    `releases/<sha>/`, from LOCAL git objects (`git archive <sha>` — no network for a known local sha).
  * A process execs with `releases/<APPROVED>/` at the FRONT of its module path. That directory contains
    exactly A and nothing else; the autosync only ever writes a DIFFERENT `releases/<B>/`, so it can never
    turn A into B (no TOCTOU, no partial-write race on the active release).
  * If APPROVED is unset → fail CLOSED (execute nothing). If APPROVED is set but its release dir is missing →
    recover by re-materialising from git; if the object is absent → fail CLOSED (never fall back to the tree).

This module is pure resolution + materialisation. It performs NO production side effects on import, starts
nothing, moves no capital, and is imported by no money-path module. stdlib only; all paths injectable."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

RELEASE_SHA_FILE = ".release_sha"   # written inside each materialised release dir = its own identity
#: Штамп пишется ПОСЛЕДНИМ и отличает завершённую материализацию от прерванной. Доказательством состава он НЕ
#: является: эталон состава — только дерево ОДОБРЕННОГО коммита из локальных git-объектов (S2-01, ARB раунд 5).
#: Манифест внутри проверяемого каталога больше не пишется и не читается — каталог не может задавать эталон
#: собственной проверки.
_IGNORED_DIRS = ("__pycache__",)   # байткод, который пишет сам интерпретатор при исполнении из релиза


def _blob_sha(data: bytes) -> str:
    """git-blob sha1 содержимого — тот же хеш, что у объекта в дереве коммита."""
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def trusted_tree(sha, repo):
    """ДОВЕРЕННЫЙ эталон состава: дерево коммита ``sha`` из локальных git-объектов ``repo``.

    ``{путь: (режим, blob)}``; объекта нет / репозиторий не указан / дерево не прочитано — ``None``
    (это «проверить нечем», а не «пусто»)."""
    if not sha or repo is None:
        return None
    r = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", f"{sha}^{{commit}}"],
                       cwd=str(repo), capture_output=True)
    if r.returncode != 0:
        return None
    out = {}
    for entry in r.stdout.split(b"\0"):
        if not entry:
            continue
        meta, path = entry.split(b"\t", 1)
        mode, kind, blob = meta.decode().split(" ")
        if kind != "blob":                       # подмодуль: git archive его не кладёт
            continue
        out[path.decode("utf-8", "surrogateescape")] = (mode, blob)
    return out


def _entry_problem(full: Path, rel: str, mode: str, blob: str):
    """Один путь против эталона: род (ссылка / файл), исполняемость, содержимое."""
    is_link = full.is_symlink()
    if mode == "120000":
        if not is_link:
            return f"{rel}: в коммите ссылка, в каталоге — не ссылка"
        data = os.readlink(full).encode("utf-8", "surrogateescape")
    else:
        if is_link or not full.is_file():
            return f"{rel}: в коммите обычный файл, в каталоге — нет"
        executable = bool(full.stat().st_mode & 0o111)
        if executable != (mode == "100755"):
            return f"{rel}: режим не совпадает с {mode}"
        data = full.read_bytes()
    if _blob_sha(data) != blob:
        return f"{rel}: содержимое не совпадает с {blob[:12]}"
    return None


def _release_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if rel == RELEASE_SHA_FILE:
                continue
            yield rel, full


def _composition_problem(root: Path, files: dict):
    """Сверка каталога с ДОВЕРЕННЫМ составом: ``None`` — совпал; иначе причина (первое расхождение)."""
    seen = set()
    for rel, full in _release_files(root):
        if rel not in files:
            return f"лишний файл {rel}"
        seen.add(rel)
        problem = _entry_problem(full, rel, *files[rel])
        if problem:
            return problem
    missing = sorted(set(files) - seen)
    if missing:
        return f"нет файла {missing[0]} (всего недостаёт {len(missing)})"
    return None


def verify_release(root: Path, sha, repo) -> tuple:
    """Каталог релиза ДОКАЗАННО равен дереву коммита ``sha``? ``(True, '')`` либо ``(False, причина)``.

    Эталон — :func:`trusted_tree` (локальные git-объекты ``repo``), а не что-либо внутри ``root``. Штамп
    проверяется только как признак завершённой материализации. ``__pycache__`` не учитывается. Только чтение."""
    root = Path(root)
    stamp = root / RELEASE_SHA_FILE
    if not stamp.exists():
        return False, "нет штампа .release_sha (резерв не завершён)"
    if stamp.read_text().strip() != sha:
        return False, "штамп указывает на другой sha"
    files = trusted_tree(sha, repo)
    if files is None:
        return False, "НЕ ПРОВЕРЕНО: доверенного дерева коммита нет (объекты/репозиторий недоступны)"
    problem = _composition_problem(root, files)
    return (False, problem) if problem else (True, "")


def exec_root(approved_sha, releases_dir: Path, repo=None):
    """The immutable directory a process MUST exec from, given the approved sha. Never returns the shared
    tree. Reads the release dir and the LOCAL git objects of ``repo`` (the trusted reference). Returns
    (root_path | None, verdict):
      (releases/<A>, 'ACTIVATE_OK')            — release PROVEN equal to the tree of commit A (S2-01)
      (None, 'DEPLOYMENT_APPROVAL_REQUIRED')    — no approved release recorded → execute nothing
      (None, 'APPROVED_RELEASE_MISSING')        — approved set but not materialised → recover, do NOT run the tree
      (None, 'APPROVED_RELEASE_UNVERIFIABLE')   — no trusted tree of A available (no repo / object) → refuse
      (None, 'APPROVED_RELEASE_CORRUPT')        — dir does not match the trusted tree of A → refuse
    """
    if not approved_sha:
        return None, "DEPLOYMENT_APPROVAL_REQUIRED"
    root = Path(releases_dir) / approved_sha
    if not root.is_dir():
        return None, "APPROVED_RELEASE_MISSING"
    if trusted_tree(approved_sha, repo) is None:
        return None, "APPROVED_RELEASE_UNVERIFIABLE"
    ok, _why = verify_release(root, approved_sha, repo)
    if not ok:
        return None, "APPROVED_RELEASE_CORRUPT"
    return root, "ACTIVATE_OK"


def materialise_release(sha, releases_dir: Path, repo: Path):
    """Create the immutable `releases/<sha>/` from LOCAL git objects. Returns (path, 'OK') or (None, reason).

    E5.3 (STUDIO-AUTONOMY-01): ничего не удаляется — ни временного каталога, ни чужого релиза.
      * каталог релиза РЕЗЕРВИРУЕТСЯ атомарным ``os.mkdir`` — второй претендент получает отказ, а не подмену;
      * извлечение из ``git archive`` → сверка с ДОВЕРЕННЫМ деревом коммита (состав, режимы, ссылки, git-blob)
        → штамп ``.release_sha`` ПОСЛЕДНИМ: каталог без штампа = незавершённый и исполнению не подлежит;
      * существующий каталог: доказанно равен дереву ``sha`` — возвращается без изменений; иначе он
        СОХРАНЯЕТСЯ и возвращается названный отказ (`RELEASE_DIR_INCOMPLETE` / `RELEASE_DIR_CORRUPT`);
      * сбой посередине оставляет незавершённую копию на месте и называет её в отказе.
    No network for a known local sha."""
    releases_dir = Path(releases_dir)
    dest = releases_dir / sha
    files = trusted_tree(sha, repo)
    if files is None:
        return None, "OBJECT_MISSING"
    if dest.exists() or dest.is_symlink():
        return _existing_verdict(dest, sha, repo)
    releases_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(dest)                                   # уникальное резервирование
    except FileExistsError:
        return _existing_verdict(dest, sha, repo)        # успел другой процесс
    keep = f"; незавершённая копия СОХРАНЕНА: {dest}"
    ar = subprocess.run(["git", "archive", "--format=tar", sha], cwd=str(repo), capture_output=True)
    if ar.returncode != 0:
        return None, "MATERIALISE_FAILED:git archive" + keep
    ex = subprocess.run(["tar", "-x", "-C", str(dest)], input=ar.stdout, capture_output=True)
    if ex.returncode != 0:
        return None, "MATERIALISE_FAILED:tar extract" + keep
    problem = _composition_problem(dest, files)
    if problem:
        return None, f"MATERIALISE_FAILED:состав не совпал ({problem})" + keep
    (dest / RELEASE_SHA_FILE).write_text(sha)            # штамп — последним
    return dest, "OK"


def _existing_verdict(dest: Path, sha, repo):
    """Каталог уже есть: доказан против дерева ``sha`` — ``OK`` без изменений; иначе СОХРАНЯЕТСЯ и отказ."""
    ok, why = verify_release(dest, sha, repo)
    if ok:
        return dest, "OK"
    if not (dest / RELEASE_SHA_FILE).exists():
        return None, f"RELEASE_DIR_INCOMPLETE:{why}; каталог сохранён: {dest}"
    return None, f"RELEASE_DIR_CORRUPT:{why}; каталог сохранён: {dest}"


def activation_plan(approved_sha, staged_sha, releases_dir: Path, repo: Path):
    """What a restart/self-heal/reboot/scheduled-cycle MUST do to guarantee it runs APPROVED, not STAGED.
    Deterministic, side-effect-free (only reads); the caller performs materialise/exec. Never selects the tree."""
    root, verdict = exec_root(approved_sha, releases_dir, repo)
    if verdict == "ACTIVATE_OK":
        return {"action": "EXEC_FROM_RELEASE", "root": str(root), "sha": approved_sha,
                "note": "exec with this dir at module-path front; the shared tree (staged=%s) is NOT on the path" % (staged_sha or "?")}
    if verdict == "APPROVED_RELEASE_MISSING":
        # recoverable if the object is local; otherwise fail CLOSED
        can = subprocess.run(["git", "cat-file", "-e", f"{approved_sha}^{{commit}}"], cwd=str(repo),
                             capture_output=True).returncode == 0 if approved_sha else False
        return {"action": "MATERIALISE_THEN_EXEC" if can else "FAIL_CLOSED",
                "sha": approved_sha, "recoverable": can, "verdict": verdict}
    return {"action": "FAIL_CLOSED", "verdict": verdict, "sha": approved_sha,
            "note": "execute NOTHING; never fall back to the staged tree"}
