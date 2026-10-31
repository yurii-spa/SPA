"""Trusted release LAUNCHER (ACCEPTED ADR-500, Trusted-Bootstrap) — SELF-CONTAINED reference logic that, in
production, is INSTALLED into the root-owned trusted plane so the autosync cannot replace it.

TRUST CLOSURE (ARB Phase 2): this file has **NO import from `~/Documents/SPA_Claude`** — only stdlib. It must
not depend on any mutable project module to select the approved release, or a malicious staged tree could
subvert the selector before the release is chosen. (The earlier draft imported `spa_core.studio_os.
release_activation`; that was a mutable pre-exec dependency and is inlined here.) The installed copy execs the
approved release with an ISOLATED interpreter (`python -E -s`: ignore PYTHONPATH + user-site, keep the release dir on the path) and cwd set to the
immutable release dir, so imports resolve ONLY from the approved release + stdlib — never the mutable tree.

The final boundary: every launchd entrypoint today is `/bin/bash ~/Documents/SPA_Claude/scripts/*.sh` (inside
autosync). The fix reuses the existing root-owned trusted plane `/Library/Application Support/StudioOS/`
(user-write-DENIED — proven live; same pattern as `worker_runner-<sha>.py` at root:wheel 0444). Installed as
`/Library/Application Support/StudioOS/bin/release_launcher-<sha256>.py`; launchd ProgramArguments repoint to
it. It reads APPROVED from a root-owned control file the user cannot write, maps a FIXED service id to an
ALLOW-LISTED argv (never arbitrary shell from the approval file), and execs ONLY from `releases/<APPROVED>/`.
FAIL CLOSED before any application code loads on: approval missing · sha invalid · release missing/corrupt ·
service/role not allow-listed."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

RELEASE_SHA_FILE = ".release_sha"    # each materialised release self-identifies with its own sha

# FIXED service → allow-listed argv. Lives in the launcher (immutable, root plane), NOT in the approval file,
# so an approval can only ever name a SHA — never a command. `-E -s` = ignore PYTHONPATH + user site (proven: blocks an injected PYTHONPATH) while cwd=<release>
# keeps the module path = the approved release only. `-I` was rejected: it drops cwd, so `-m` cannot find the release.
SERVICE_ALLOWLIST = {
    "paper-cycle":  ["-B", "-E", "-s", "-m", "spa_core.paper_trading.cycle_runner", "--verbose", "--live"],
    "orchestrator": ["-B", "-E", "-s", "-m", "spa_core.orchestrator.adapter_orchestrator"],
    "telegram":     ["-B", "-E", "-s", "-m", "spa_core.telegram.bot"],
    "canary": ["-B", "-E", "-s", "-m", "spa_core.monitoring.deployment_acceptance"],  # benign, non-money, exits — the CANARY service
}
AGENT_ROLE_MANIFEST = "studio_release_agents.json"   # {role: "spa_core.module.path"} committed in the release


# Ничего не исключается из сверки (ARB-самопроверка S2, 31.10): `__pycache__` раньше пропускался как «байткод
# исполнения», но интерпретатор читает его РАНЬШЕ исходника — подложенный .pyc (или ссылка `__pycache__`) исполнялся
# бы под видом одобренного релиза. Исполнение идёт с `-B` (байткод в релиз не пишется), любой `__pycache__` в
# каталоге — лишний файл состава.
_IGNORED_DIRS = ()

# Чтение git-объектов: replace-объекты ОТКЛЮЧЕНЫ (иначе `git replace` в изменяемом репозитории подменил бы эталон),
# и каждый прочитанный объект ПЕРЕПРОВЕРЯЕТСЯ по своему sha1 — доверие идёт от одобренного sha, а не от репозитория.
_GIT_ENV = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}


def _blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class _ObjectReader:
    """Один процесс `git cat-file --batch`; объект возвращается ТОЛЬКО если его sha1 совпал с запрошенным."""

    def __init__(self, repo):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(_GIT_ENV)
        self.p = subprocess.Popen(["git", "--no-replace-objects", "-C", str(repo), "cat-file", "--batch"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=env)

    def get(self, oid, kind):
        self.p.stdin.write(oid.encode() + b"\n")
        self.p.stdin.flush()
        header = self.p.stdout.readline()
        parts = header.split()
        if len(parts) != 3:
            return None                                        # `<oid> missing` / сбой — объекта нет
        got_oid, got_kind, size = parts[0].decode(), parts[1].decode(), int(parts[2])
        data = self.p.stdout.read(size)
        self.p.stdout.read(1)
        if got_oid != oid or got_kind != kind:
            return None
        if hashlib.sha1(b"%s %d\0" % (kind.encode(), size) + data).hexdigest() != oid:
            return None                                        # объект не тот, за кого себя выдаёт
        return data

    def close(self):
        try:
            self.p.stdin.close()
        finally:
            self.p.wait(timeout=30)


def trusted_tree(sha, repo):
    """ДОВЕРЕННЫЙ эталон состава: дерево коммита ``sha`` из git-объектов ``repo`` с проверкой sha1 каждого объекта.

    ``{путь: (режим, blob)}``; репозиторий не указан / объекта нет / объект не сверился — ``None`` («проверить
    нечем», а не «пусто»). stdlib + системный git; изменяемого кода проекта не импортирует (TRUST CLOSURE)."""
    if not sha or not repo or not Path(repo).is_dir():
        return None
    try:
        reader = _ObjectReader(repo)
    except OSError:
        return None
    try:
        commit = reader.get(sha, "commit")
        if commit is None or not commit.startswith(b"tree "):
            return None
        out = {}
        todo = [("", commit[5:45].decode())]
        while todo:
            prefix, tree_oid = todo.pop()
            data = reader.get(tree_oid, "tree")
            if data is None:
                return None
            i = 0
            while i < len(data):
                sp = data.index(b" ", i)
                nul = data.index(b"\0", sp)
                mode = data[i:sp].decode()
                name = data[sp + 1:nul].decode("utf-8", "surrogateescape")
                oid = data[nul + 1:nul + 21].hex()
                i = nul + 21
                path = prefix + name
                if mode == "40000":
                    todo.append((path + "/", oid))
                elif mode == "160000":                         # подмодуль: git archive его не кладёт
                    continue
                else:
                    out[path] = (mode, oid)
        return out
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        try:
            reader.close()
        except Exception:                                      # noqa: BLE001 — закрытие не меняет вердикт
            pass


def _composition_problem(root, files):
    """Каталог против эталона: пути, род (ссылка/файл), бит исполнения, git-blob. ``None`` — совпал."""
    root = Path(root)
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIRS]
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if rel == RELEASE_SHA_FILE:
                continue
            if rel not in files:
                return f"лишний файл {rel}"
            seen[rel] = full
            mode, blob = files[rel]
            if mode == "120000":
                if not full.is_symlink():
                    return f"{rel}: в коммите ссылка"
                data = os.readlink(full).encode("utf-8", "surrogateescape")
            else:
                if full.is_symlink() or not full.is_file():
                    return f"{rel}: в коммите обычный файл"
                if bool(full.stat().st_mode & 0o111) != (mode == "100755"):
                    return f"{rel}: режим не совпадает с {mode}"
                data = full.read_bytes()
            if _blob_sha(data) != blob:
                return f"{rel}: содержимое не совпадает"
    missing = []
    for rel in sorted(set(files) - set(seen)):
        partner = _case_partner(root, rel, seen)       # S2 задача 03: отвечает ФС (inode), не строки
        if partner is None:
            missing.append(rel)
        elif files[partner] != files[rel]:
            return f"коллизия регистра {rel} ↔ {partner}: разные режим или содержимое"
    return f"нет файла {missing[0]}" if missing else None


def _case_partner(root, rel, seen):
    """Путь эталона, которого нет в обходе, на ФС без различия регистра — тот же объект (lstat inode), что
    уже проверенный путь каталога? Партнёр или ``None``. Копия правила ``release_activation`` (TRUST CLOSURE)."""
    try:
        st = os.lstat(Path(root) / rel)
    except OSError:
        return None
    for other, full in seen.items():
        if other.lower() == rel.lower():
            o = os.lstat(full)
            if (o.st_dev, o.st_ino) == (st.st_dev, st.st_ino):
                return other
    return None


def exec_root(approved_sha, releases_dir, repo=None):
    """stdlib-only: the immutable dir a process MUST exec from. Never the mutable tree. Returns (root|None, verdict):
    ACTIVATE_OK · DEPLOYMENT_APPROVAL_REQUIRED · APPROVED_RELEASE_MISSING · APPROVED_RELEASE_UNVERIFIABLE (no trusted
    tree of the approved commit) · APPROVED_RELEASE_CORRUPT (stamp or composition does not match that tree).
    E5.3 (S2 задача 02): штамп больше не доказательство — состав сверяется с деревом одобренного коммита."""
    if not approved_sha:
        return None, "DEPLOYMENT_APPROVAL_REQUIRED"
    root = Path(releases_dir) / approved_sha
    if not root.is_dir():
        return None, "APPROVED_RELEASE_MISSING"
    stamp = root / RELEASE_SHA_FILE
    if not stamp.exists() or stamp.read_text().strip() != approved_sha:
        return None, "APPROVED_RELEASE_CORRUPT"
    files = trusted_tree(approved_sha, repo)
    if files is None:
        return None, "APPROVED_RELEASE_UNVERIFIABLE"
    if _composition_problem(root, files) is not None:
        return None, "APPROVED_RELEASE_CORRUPT"
    return root, "ACTIVATE_OK"


def _agent_argv(release_root: Path, role: str):
    try:
        m = json.loads((Path(release_root) / AGENT_ROLE_MANIFEST).read_text())
        mod = m.get(role)
        return ["-B", "-E", "-s", "-m", mod] if isinstance(mod, str) and mod.startswith("spa_core.") else None
    except Exception:
        return None


def plan_exec(service, approved_sha, releases_dir, repo=None):
    """PURE: how the trusted launcher must exec `service`, or why it fails CLOSED. Returns (plan|None, verdict).
    plan = {argv, cwd, exec_root, sha} — exec `python <argv>` with cwd=exec_root so imports come from the
    APPROVED release only. The mutable tree is never read here."""
    if service not in SERVICE_ALLOWLIST and not service.startswith("agent:"):
        return None, "SERVICE_NOT_ALLOWLISTED"
    root, verdict = exec_root(approved_sha, releases_dir, repo)
    if verdict != "ACTIVATE_OK":
        return None, verdict
    argv = SERVICE_ALLOWLIST.get(service)
    if argv is None:
        argv = _agent_argv(root, service.split(":", 1)[1])
        if argv is None:
            return None, "AGENT_ROLE_NOT_ALLOWLISTED"
    return {"argv": argv, "cwd": str(root), "exec_root": str(root), "sha": approved_sha}, "EXEC_FROM_RELEASE"


# ── installed entrypoint (root plane). launchd runs: /usr/bin/python3 -I  <this file> <service-id> ──────────
# Trusted-plane fixed locations (all root-owned, user-write-denied). Overridable ONLY for hermetic tests.
TRUSTED_ROOT = "/Library/Application Support/StudioOS"
# TWO interpreters, two trust roots:
#   BOOTSTRAP  — the OS `/usr/bin/python3 -I` (root:wheel, system stdlib; -I drops PYTHONPATH/HOME/user-site/cwd)
#                runs THIS launcher. The launcher is stdlib-only, so it needs nothing user-writable.
#   APPLICATION— the launcher execs the approved release with a FIXED trusted 3.13 read from the ROOT-OWNED
#                runtime manifest (`_read_app_python`), NEVER sys.executable (=3.9 bootstrap) and NEVER a path
#                from the (user-influenced) approval file. Missing manifest → FAIL CLOSED before any app code.
# ACTIVE is an observation marker (what actually started), not authority; written user-side, never read as a gate.
ACTIVE_MARKER_PATH = str(Path.home() / "Documents" / "SPA_Claude" / "data" / "active_release.json")


def _read_approved(approved_file):
    try:
        return json.loads(Path(approved_file).read_text()).get("approved_sha")
    except Exception:
        return None


def _read_app_python(root):
    """The APPLICATION runtime interpreter — a FIXED trusted 3.13 named in the ROOT-OWNED runtime manifest
    (`<root>/runtime.json` → app_python). NOT sys.executable: launchd bootstraps the launcher with the OS
    /usr/bin/python3 (3.9), so sys.executable would run 3.13 app code on 3.9. NOT from approved_release.json
    (user-influenced). None → fail CLOSED."""
    try:
        return json.loads((Path(root) / "runtime.json").read_text()).get("app_python")
    except Exception:
        return None


def _read_trusted_repo(root):
    """Репозиторий с git-объектами — эталон состава. Из ROOT-OWNED runtime manifest (как и интерпретатор), не из
    файла одобрения. None → APPROVED_RELEASE_UNVERIFIABLE, fail CLOSED."""
    try:
        return json.loads((Path(root) / "runtime.json").read_text()).get("trusted_repo")
    except Exception:
        return None


def main(service_id, *, root=None, python=None, active_path=None):
    """The installed launcher's exec: resolve the approved release, record ACTIVE, exec from the release with the
    FIXED trusted 3.13 app runtime (root-owned runtime manifest), isolated (`-E -s`, cwd=release). FAIL CLOSED
    (exit 3) before any application code loads. Never touches the mutable tree; the application is ALWAYS exec'd
    with `app_py` (the trusted 3.13 from runtime.json) — NEVER sys.executable (which would be the 3.9 bootstrap).
    Returns a verdict string in test mode (python is a list sink) or execs for real."""
    root = Path(root or TRUSTED_ROOT)
    approved = _read_approved(root / "approved_release.json")
    plan, verdict = plan_exec(service_id, approved, root / "releases", _read_trusted_repo(root))
    if verdict != "EXEC_FROM_RELEASE":
        return ("FAIL_CLOSED", verdict)
    # resolve the trusted APP runtime BEFORE recording anything — fail CLOSED if the runtime manifest is absent
    app_py = python if python is not None else _read_app_python(root)
    if app_py is None:
        return ("FAIL_CLOSED", "APP_RUNTIME_MISSING")   # no trusted 3.13 configured → execute nothing
    # record ACTIVE = the sha we are about to exec (observation only)
    try:
        ap = Path(active_path or ACTIVE_MARKER_PATH)
        ap.parent.mkdir(parents=True, exist_ok=True)
        ap.write_text(json.dumps({"active_sha": plan["sha"], "service": service_id}))
    except Exception:
        pass
    if isinstance(app_py, list):                 # test hook: capture the plan; the test supplies its own interpreter
        app_py.append((py_exec := ["<app_python-from-runtime.json>", *plan["argv"]], plan["cwd"]))
        return ("EXEC_FROM_RELEASE", py_exec, plan["cwd"])
    # THE ONE application exec path: the trusted 3.13 (app_py) execs the release; imports come from the release only
    os.chdir(plan["cwd"])
    os.execv(app_py, [app_py, *plan["argv"]])


if __name__ == "__main__":                       # pragma: no cover — exercised in production, not CI
    import sys
    if len(sys.argv) < 2:
        sys.stderr.write("usage: release_launcher.py <service-id>\n"); sys.exit(2)
    r = main(sys.argv[1])
    if r and r[0] == "FAIL_CLOSED":
        sys.stderr.write(f"trusted-launcher FAIL_CLOSED: {r[1]}\n"); sys.exit(3)
