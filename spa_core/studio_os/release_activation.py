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

import json
import os
import subprocess
from pathlib import Path

RELEASE_SHA_FILE = ".release_sha"   # written inside each materialised release dir = its own identity
#: Состав релиза (E5.3): путь → (режим git, git-blob sha1). Штамп ``.release_sha`` пишется ПОСЛЕДНИМ, после
#: сверки состава с деревом коммита; сам по себе штамп состав не доказывает.
MANIFEST_FILE = ".release_manifest.json"
_IGNORED_DIRS = ("__pycache__",)   # байткод, который пишет сам интерпретатор при исполнении из релиза


def _blob_sha(data: bytes) -> str:
    """git-blob sha1 содержимого — тот же хеш, что у объекта в дереве коммита."""
    import hashlib
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _git_tree(sha, repo: Path):
    """Состав коммита из ЛОКАЛЬНЫХ объектов: {путь: (режим, blob)}; не прочли — ``None``."""
    r = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", sha], cwd=str(repo),
                       capture_output=True)
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


def _file_blob(path: Path, mode: str) -> str:
    if mode == "120000":                         # ссылка в дереве: blob — это текст цели
        return _blob_sha(os.readlink(path).encode("utf-8", "surrogateescape"))
    return _blob_sha(path.read_bytes())


def _release_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if rel in (RELEASE_SHA_FILE, MANIFEST_FILE):
                continue
            yield rel, full


def _composition_problem(root: Path, files: dict):
    """Сверка каталога с составом: ``None`` — совпал; иначе причина (первое расхождение)."""
    seen = set()
    for rel, full in _release_files(root):
        if rel not in files:
            return f"лишний файл {rel}"
        seen.add(rel)
        mode, blob = files[rel]
        if _file_blob(full, mode) != blob:
            return f"содержимое {rel} не совпадает с {blob[:12]}"
    missing = sorted(set(files) - seen)
    if missing:
        return f"нет файла {missing[0]} (всего недостаёт {len(missing)})"
    return None


def verify_release(root: Path, sha) -> tuple:
    """Каталог релиза ДОКАЗАННО равен коммиту ``sha``? ``(True, '')`` либо ``(False, причина)``.

    Штамп, манифест и КАЖДЫЙ файл по git-blob-хешу; ``__pycache__`` не учитывается (его пишет исполнение).
    Только чтение."""
    root = Path(root)
    stamp = root / RELEASE_SHA_FILE
    if not stamp.exists():
        return False, "нет штампа .release_sha (резерв не завершён)"
    if stamp.read_text().strip() != sha:
        return False, "штамп указывает на другой sha"
    try:
        doc = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8"))
        files = {k: tuple(v) for k, v in doc["files"].items()}
        if doc.get("sha") != sha:
            return False, "манифест другого sha"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, f"манифест не прочитан: {type(exc).__name__}"
    problem = _composition_problem(root, files)
    return (False, problem) if problem else (True, "")


def exec_root(approved_sha, releases_dir: Path):
    """PURE: the immutable directory a process MUST exec from, given the approved sha. Never returns the
    shared tree. Returns (root_path | None, verdict):
      (releases/<A>, 'ACTIVATE_OK')          — approved release present and PROVEN equal to A (E5.3)
      (None, 'DEPLOYMENT_APPROVAL_REQUIRED')  — no approved release recorded → execute nothing
      (None, 'APPROVED_RELEASE_MISSING')      — approved set but not materialised → recover, do NOT run the tree
      (None, 'APPROVED_RELEASE_CORRUPT')      — dir exists but its stamp/manifest/files do not prove A → refuse
    """
    if not approved_sha:
        return None, "DEPLOYMENT_APPROVAL_REQUIRED"
    root = Path(releases_dir) / approved_sha
    if not root.is_dir():
        return None, "APPROVED_RELEASE_MISSING"
    ok, _why = verify_release(root, approved_sha)
    if not ok:
        return None, "APPROVED_RELEASE_CORRUPT"
    return root, "ACTIVATE_OK"


def materialise_release(sha, releases_dir: Path, repo: Path):
    """Create the immutable `releases/<sha>/` from LOCAL git objects. Returns (path, 'OK') or (None, reason).

    E5.3 (STUDIO-AUTONOMY-01): ничего не удаляется — ни временного каталога, ни чужого релиза.
      * каталог релиза РЕЗЕРВИРУЕТСЯ атомарным ``os.mkdir`` — второй претендент получает отказ, а не подмену;
      * извлечение из ``git archive`` → сверка состава с деревом коммита по git-blob-хешам → манифест →
        штамп ``.release_sha`` ПОСЛЕДНИМ: каталог без штампа = незавершённый и исполнению не подлежит;
      * существующий каталог: доказанно равен ``sha`` — возвращается без изменений (идемпотентно); иначе он
        СОХРАНЯЕТСЯ и возвращается названный отказ (`RELEASE_DIR_INCOMPLETE` / `RELEASE_DIR_CORRUPT`);
      * сбой посередине оставляет незавершённую копию на месте и называет её в отказе.
    No network for a known local sha."""
    releases_dir = Path(releases_dir)
    dest = releases_dir / sha
    if dest.exists() or dest.is_symlink():
        return _existing_verdict(dest, sha)
    # object must be present locally (fail CLOSED, never fetch silently under an agent)
    if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(repo),
                      capture_output=True).returncode != 0:
        return None, "OBJECT_MISSING"
    files = _git_tree(sha, repo)
    if files is None:
        return None, "MATERIALISE_FAILED:git ls-tree"
    releases_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(dest)                                   # уникальное резервирование
    except FileExistsError:
        return _existing_verdict(dest, sha)              # успел другой процесс
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
    (dest / MANIFEST_FILE).write_text(
        json.dumps({"sha": sha, "files": {k: list(v) for k, v in sorted(files.items())}},
                   ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (dest / RELEASE_SHA_FILE).write_text(sha)            # штамп — последним
    return dest, "OK"


def _existing_verdict(dest: Path, sha):
    """Каталог уже есть: доказан — ``OK`` без изменений; иначе СОХРАНЯЕТСЯ и называется отказ."""
    ok, why = verify_release(dest, sha)
    if ok:
        return dest, "OK"
    if not (dest / RELEASE_SHA_FILE).exists():
        return None, f"RELEASE_DIR_INCOMPLETE:{why}; каталог сохранён: {dest}"
    return None, f"RELEASE_DIR_CORRUPT:{why}; каталог сохранён: {dest}"


def activation_plan(approved_sha, staged_sha, releases_dir: Path, repo: Path):
    """What a restart/self-heal/reboot/scheduled-cycle MUST do to guarantee it runs APPROVED, not STAGED.
    Deterministic, side-effect-free (only reads); the caller performs materialise/exec. Never selects the tree."""
    root, verdict = exec_root(approved_sha, releases_dir)
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
