"""Проверяемый установочный пакет доверенного корня + снимок и восстановление его конфигурации (S2, ARB 01.11 п. 2–3).

TRUST CLOSURE: только stdlib, ни одного импорта проекта. Владелец запускает ЭТОТ файл, извлечённый из
рассмотренного коммита, интерпретатором ОС: ``/usr/bin/python3 -I trusted_install_bundle.py <команда> …``.

``stage`` — установочный пакет из ЗАФИКСИРОВАННОГО коммита, а не из рабочего дерева:
  * коммит называется явно (``--sha``, 40 символов); HEAD не подставляется никогда;
  * каждый объект (коммит → деревья → blob) читается с отключёнными replace-объектами и ПЕРЕПРОВЕРЯЕТСЯ по sha1;
  * sha256 каждого файла пакета обязан совпасть с ДВУМЯ независимыми источниками: значением из отчёта ARB
    (``--expect путь=sha256``, вводит владелец) и пином, лежащим в том же коммите (``INSTALL_PIN.json``);
    «вычислить хеш и принять его» здесь невозможно — ожидаемое значение приходит снаружи;
  * любое расхождение — отказ (код 2), пакет не пишется; каталог пакета должен не существовать.

``snapshot`` / ``verify`` / ``restore`` — конфигурация доверенного корня до изменения: содержимое, sha256, uid/gid,
режим каждого управляемого файла и перечень ``bin/``, ``releases/``. ``verify`` сверяет текущее состояние со
снимком (код 1 при расхождении); ``restore`` возвращает файлы снимка (атомарно, с владельцем и режимом) и сам
перепроверяет результат. Защита снимка (ревью 01.11): (1) хеш снимка печатается при создании и ОБЯЗАТЕЛЕН в restore —
владелец записывает его вне снимка, поэтому переписать снимок «вместе с хешем» бесполезно; (2) под root снимок обязан
принадлежать root и не быть доступным на запись группе/прочим; (3) копии читаются без перехода по ссылкам;
(4) под root восстанавливается только владелец root. Ничего не удаляется.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BUNDLE = ("scripts/install_trusted_bootstrap.sh", "scripts/build_trusted_runtime.sh",
          "spa_core/studio_os/release_launcher.py", "spa_core/studio_os/trusted_install_bundle.py")
PIN_PATH = "docs/evidence/studio-autonomy-01-2026-10-29/s2/INSTALL_PIN.json"
CONFIG_FILES = ("approved_release.json", "runtime.json")
LISTED_DIRS = ("bin", "releases", "toolchains")
_GIT_ENV = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}


class Refused(Exception):
    """Отказ с причиной; пакет/восстановление не выполнены."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Objects:
    """``git cat-file --batch`` с отключёнными replace-объектами; каждый объект перепроверяется по sha1."""

    def __init__(self, repo: str):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(_GIT_ENV)
        self.p = subprocess.Popen(["git", "--no-replace-objects", "-C", repo, "cat-file", "--batch"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)

    def get(self, oid: str, kind: str) -> bytes:
        self.p.stdin.write(oid.encode() + b"\n")
        self.p.stdin.flush()
        head = self.p.stdout.readline().split()
        if len(head) != 3 or head[1].decode() != kind:
            raise Refused(f"объект {oid} ({kind}) отсутствует или иного вида")
        size = int(head[2])
        data = self.p.stdout.read(size)
        self.p.stdout.read(1)
        if hashlib.sha1(b"%s %d\0" % (kind.encode(), size) + data).hexdigest() != oid:
            raise Refused(f"объект {oid} не сходится со своим sha1 — хранилище подменено")
        return data

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.p.kill()


def _blob_at(obj: _Objects, sha: str, path: str) -> bytes:
    commit = obj.get(sha, "commit")
    if not commit.startswith(b"tree "):
        raise Refused(f"{sha}: не коммит")
    tree = commit[5:45].decode()
    parts = path.split("/")
    for i, name in enumerate(parts):
        data, j, found = obj.get(tree, "tree"), 0, None
        while j < len(data):
            sp, nul = data.index(b" ", j), data.index(b"\0", data.index(b" ", j))
            mode, nm, oid = data[j:sp].decode(), data[sp + 1:nul].decode("utf-8", "surrogateescape"), data[nul + 1:nul + 21].hex()
            j = nul + 21
            if nm == name:
                found = (mode, oid)
                break
        if found is None:
            raise Refused(f"{path}: нет в дереве коммита {sha}")
        if i < len(parts) - 1:
            if found[0] != "40000":
                raise Refused(f"{path}: {name} не каталог")
            tree = found[1]
        else:
            if found[0] not in ("100644", "100755"):
                raise Refused(f"{path}: не обычный файл (режим {found[0]})")
            return obj.get(found[1], "blob")
    raise Refused(f"{path}: путь пуст")


def stage(repo: str, sha: str, dest: str, expect: dict) -> dict:
    if not (isinstance(sha, str) and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)):
        raise Refused("--sha должен быть полным sha коммита (40 hex); HEAD/ветка не принимаются")
    missing = [p for p in BUNDLE if p not in expect]
    if missing:
        raise Refused(f"нет ожидаемых sha256 из отчёта ARB для: {missing}")
    if Path(dest).exists():
        raise Refused(f"{dest} уже существует — пакет пишется только в новый каталог")
    obj = _Objects(repo)
    try:
        pin = json.loads(_blob_at(obj, sha, PIN_PATH))
        files = {p: _blob_at(obj, sha, p) for p in BUNDLE}
    finally:
        obj.close()
    report = {}
    for p, data in files.items():
        got, want, pinned = _sha256(data), expect[p], (pin.get("files") or {}).get(p, {}).get("sha256")
        report[p] = {"sha256": got, "expected": want, "pinned": pinned}
        if got != want or got != pinned:
            raise Refused(f"{p}: sha256 {got} ≠ отчёт ARB {want} или пин {pinned} — пакет не создан")
    os.makedirs(dest)
    for p, data in files.items():
        out = Path(dest) / p
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        os.chmod(out, 0o444)
    manifest = {"schema": "studio-install-bundle/1", "sha": sha, "files": report,
                "runtime_digest_pinned": (pin.get("runtime") or {}).get("digest")}
    (Path(dest) / "BUNDLE_MANIFEST.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return manifest


# ── снимок конфигурации доверенного корня ───────────────────────────────────────────────────────────
def _file_record(p: Path) -> dict:
    st = os.lstat(p)
    return {"sha256": _sha256(p.read_bytes()), "uid": st.st_uid, "gid": st.st_gid, "mode": oct(st.st_mode & 0o7777),
            "size": st.st_size}


def _state(root: Path) -> dict:
    files = {n: (_file_record(root / n) if (root / n).is_file() else None) for n in CONFIG_FILES}
    dirs = {d: (sorted(os.listdir(root / d)) if (root / d).is_dir() else None) for d in LISTED_DIRS}
    return {"files": files, "dirs": dirs}


def snapshot(root: str, out: str) -> dict:
    root_p, out_p = Path(root), Path(out)
    if out_p.exists():
        raise Refused(f"{out} уже существует — снимок пишется только в новый каталог")
    out_p.mkdir(parents=True)
    state = _state(root_p)
    for n in CONFIG_FILES:
        if state["files"][n] is not None:
            shutil.copyfile(root_p / n, out_p / n)
    doc = {"schema": "studio-trusted-root-snapshot/1", "root": str(root_p), "state": state}
    body = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    (out_p / "SNAPSHOT.json").write_text(body)
    (out_p / "SNAPSHOT.sha256").write_text(_sha256(body.encode()))
    return doc


def _read_nofollow(path: Path) -> bytes:
    """Чтение без перехода по ссылке: копия в снимке, подменённая ссылкой на чужой файл, — отказ, а не раскрытие."""
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as fh:
        return fh.read()


def _owner_problem(snap: Path, euid: int):
    """Под root снимок обязан принадлежать root и не быть доступным на запись группе/прочим (каталог и файлы):
    иначе обычный пользователь мог бы переписать его вместе с хешем, а root — установить подменённое."""
    if euid != 0:
        return None
    for q in [snap] + [snap / n for n in ("SNAPSHOT.json", "SNAPSHOT.sha256", *CONFIG_FILES)]:
        if not q.exists() and not q.is_symlink():
            continue
        st = os.lstat(q)
        if os.path.islink(q) or st.st_uid != 0 or st.st_mode & 0o022:
            return f"{q}: не принадлежит root или доступен на запись не только root — восстановление под root запрещено"
    return None


def snapshot_digest(snap: str) -> str:
    """Хеш снимка, который владелец ЗАПИСЫВАЕТ вне снимка (печатается при создании) и передаёт в restore."""
    return _sha256((Path(snap) / "SNAPSHOT.json").read_bytes())


def _load_snapshot(snap: str, expect_sha256=None, euid=None) -> dict:
    s = Path(snap)
    euid = os.geteuid() if euid is None else euid
    owner = _owner_problem(s, euid)
    if owner:
        raise Refused(owner)
    body = _read_nofollow(s / "SNAPSHOT.json").decode("utf-8")
    if _sha256(body.encode()) != _read_nofollow(s / "SNAPSHOT.sha256").decode().strip():
        raise Refused("снимок изменён после создания (SNAPSHOT.sha256 не сходится)")
    if expect_sha256 is not None and _sha256(body.encode()) != expect_sha256:
        raise Refused("хеш снимка не совпадает с записанным владельцем при создании — снимок подменён")
    doc = json.loads(body)
    for n, rec in doc["state"]["files"].items():
        if rec is not None and _sha256(_read_nofollow(s / n)) != rec["sha256"]:
            raise Refused(f"копия {n} в снимке не сходится со своим sha256")
    return doc


def verify(root: str, snap: str, expect_sha256=None) -> list:
    """Расхождения текущего состояния со снимком (пусто — совпало)."""
    doc = _load_snapshot(snap, expect_sha256)
    cur, want = _state(Path(root)), doc["state"]
    diffs = [f"{n}: {want['files'][n]} → {cur['files'][n]}" for n in CONFIG_FILES if cur["files"][n] != want["files"][n]]
    diffs += [f"{d}/: {want['dirs'][d]} → {cur['dirs'][d]}" for d in LISTED_DIRS if cur["dirs"][d] != want["dirs"][d]]
    return diffs


def restore(root: str, snap: str, expect_sha256: str, euid=None) -> list:
    """Вернуть управляемые файлы снимка (содержимое, владелец, режим). Хеш снимка, записанный владельцем при
    создании, ОБЯЗАТЕЛЕН; под root снимок обязан быть root-owned, а восстанавливаемый владелец — root. Перечни
    каталогов НЕ правятся (ничего не удаляется). Возвращает расхождения ПОСЛЕ восстановления (пусто — восстановлено);
    файл, которого в снимке не было, не создаётся и не удаляется — и это называется расхождением."""
    if not expect_sha256:
        raise Refused("restore без хеша снимка, записанного при создании, не выполняется")
    euid = os.geteuid() if euid is None else euid
    doc, root_p, s = _load_snapshot(snap, expect_sha256, euid), Path(root), Path(snap)
    for n, rec in doc["state"]["files"].items():
        if rec is not None and euid == 0 and rec["uid"] != 0:
            raise Refused(f"{n}: в снимке владелец uid {rec['uid']}, под root восстанавливается только root")
    for n, rec in doc["state"]["files"].items():
        target = root_p / n
        if rec is None:
            continue
        tmp = target.with_name(target.name + ".restore-tmp")
        if tmp.is_symlink() or tmp.exists():
            raise Refused(f"{tmp} уже существует — восстановление не продолжается")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(_read_nofollow(s / n))
        os.chmod(tmp, int(rec["mode"], 8))
        if (os.lstat(tmp).st_uid, os.lstat(tmp).st_gid) != (rec["uid"], rec["gid"]):
            os.chown(tmp, rec["uid"], rec["gid"])
        os.replace(tmp, target)
    cur = _state(root_p)
    out = [f"{n}: {doc['state']['files'][n]} → {cur['files'][n]}" for n in CONFIG_FILES
           if doc["state"]["files"][n] is not None and cur["files"][n] != doc["state"]["files"][n]]
    out += [f"{n}: в снимке отсутствовал, сейчас есть — не удаляется (вне полномочий)" for n in CONFIG_FILES
            if doc["state"]["files"][n] is None and cur["files"][n] is not None]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="trusted_install_bundle")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("stage")
    a.add_argument("--repo", required=True)
    a.add_argument("--sha", required=True)
    a.add_argument("--stage", required=True)
    a.add_argument("--expect", action="append", default=[], help="путь=sha256 из отчёта ARB (по одному на файл)")
    for name in ("snapshot", "verify", "restore"):
        b = sub.add_parser(name)
        b.add_argument("--root", required=True)
        b.add_argument("--snapshot", required=True)
        if name != "snapshot":
            b.add_argument("--expect-snapshot-sha256", required=(name == "restore"),
                           help="хеш, напечатанный при создании снимка и записанный владельцем вне снимка")
    ns = ap.parse_args(argv)
    try:
        if ns.cmd == "stage":
            exp = dict(e.split("=", 1) for e in ns.expect)
            print(json.dumps(stage(ns.repo, ns.sha, ns.stage, exp), indent=1, ensure_ascii=False))
            return 0
        if ns.cmd == "snapshot":
            snapshot(ns.root, ns.snapshot)
            print(f"snapshot: {ns.snapshot}")
            print(f"SNAPSHOT_SHA256={snapshot_digest(ns.snapshot)}   # ЗАПИСАТЬ вне снимка: нужен для restore")
            return 0
        exp = ns.expect_snapshot_sha256
        diffs = verify(ns.root, ns.snapshot, exp) if ns.cmd == "verify" else restore(ns.root, ns.snapshot, exp)
        for d in diffs:
            print("DIFF", d)
        print("MATCH" if not diffs else f"{len(diffs)} difference(s)")
        return 0 if not diffs else 1
    except (Refused, OSError, ValueError, KeyError) as exc:
        sys.stderr.write(f"REFUSED: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
