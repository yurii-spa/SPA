"""spa_core/utils/hash_ledger.py — shared, parameterised append-only hash-chained JSONL ledger.

Two deliberate hash-chained ledgers already exist (``spa_core/capital_shadow/ledger.py``,
``spa_core/investment_cio/ledger.py``, modelled on each other, read but NEVER modified while
building this). Both bind the SAME generic engine — paths, locking, hash chain, sibling anchors,
append/read/verify — to their own domain. This module extracts exactly that generic engine, so
the Research Factory (ADR-560, RM-EXPAND-01) does not become a THIRD hand-written copy. The two
existing modules keep every domain-specific helper (owner actions, approvals, simulations,
snapshots) — migrating them onto this helper is recorded debt, not done here.

Design choices carried over unchanged from both originals:

* one JSONL ledger file + a SIBLING anchors directory (``data/<x>/`` and ``data/<x>_anchors/``)
  — wiping or restoring one directory can never silently wipe or restore the other;
* ``(kind, key)`` is the idempotency key: a repeated write raises :class:`DuplicateKey` carrying
  the EXISTING row, never silently duplicated and never silently overwritten — the caller decides
  what "idempotent" means for its own kind;
* one line is one ``os.write()`` on an ``O_APPEND`` fd + ``os.fsync()`` — the OS-level unit a
  crash cannot bisect (a buffered ``file.write()`` can still land as two separate writes);
* this module NEVER auto-repairs. ``verify()`` only detects and NAMES a break; a caller that
  wants repair semantics builds its own on top, exactly as both existing ledgers already do.

A separate, NON-BLOCKING run lock (:meth:`HashLedger.run_lock`) is distinct from the (blocking,
short-timeout) per-write file lock (:meth:`HashLedger.file_lock`): a whole run holds the run lock
for its duration so a second concurrent run refuses immediately (:class:`RunLocked`, which CLI
layers map to exit 75) rather than queuing behind the first.

# LLM_FORBIDDEN — deterministic I/O only, no judgement calls.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence

GENESIS = "0" * 64


class LedgerError(Exception):
    """Chain-integrity or write-contract violation. Nothing is auto-repaired."""


class LockBusy(Exception):
    """Another process holds the per-write file lock past the wait timeout."""


class RunLocked(Exception):
    """Another process holds the run lock. CLI layers map this to exit code 75."""


class DuplicateKey(Exception):
    """A write was refused because its ``(kind, key)`` already exists. Carries the EXISTING
    entry so a caller that treats a repeat as idempotent does not need a second read."""

    def __init__(self, existing: dict):
        super().__init__(f"duplicate key: kind={existing.get('kind')!r} key={existing.get('key')!r}")
        self.existing = existing


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key_list(key: Sequence) -> list:
    return [k for k in key]


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class _FileLock:
    """Blocking (up to ``timeout_s``), exclusive, re-entrant-safe per-process flock."""

    def __init__(self, path: Path, timeout_s: float, poll_s: float = 0.05):
        self._path = path
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._fh = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a+")
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._fh.close()
                    raise LockBusy(f"could not acquire {self._path} within {self._timeout_s}s")
                time.sleep(self._poll_s)

    def __exit__(self, exc_type, exc, tb):
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
        return False


class _RunLock:
    """Non-blocking: a held lock raises :class:`RunLocked` immediately, never waits."""

    def __init__(self, path: Path):
        self._path = path
        self._fh = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a+")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._fh.close()
            self._fh = None
            raise RunLocked(f"another run holds {self._path}")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
        return False


class HashLedger:
    """One append-only hash-chained JSONL ledger, parameterised over its storage location.

    ``data_dir`` is the data root (e.g. ``Path("data")``); the ledger file lives at
    ``data_dir / subdir / ledger_name`` and its sibling anchors at
    ``data_dir / anchors_subdir / <ledger stem>.anchors.jsonl``.
    """

    def __init__(self, data_dir: Path, subdir: str, anchors_subdir: str, ledger_name: str = "ledger.jsonl"):
        self.data_dir = Path(data_dir)
        self.subdir = subdir
        self.anchors_subdir = anchors_subdir
        self.ledger_name = ledger_name
        self._cache: Optional[List[dict]] = None
        #: M7: set True only by :meth:`mark_verified`, after an EXPLICIT, successful
        #: :meth:`verify` — skips the full O(n) chain+anchor re-walk on every subsequent
        #: append for the rest of this object's life. Defaults False, so every existing
        #: caller's behaviour (verify before every append) is UNCHANGED unless it opts in.
        self._trusted = False

    # ── paths ────────────────────────────────────────────────────────────────────────────────
    def root(self) -> Path:
        return self.data_dir / self.subdir

    def ledger_path(self) -> Path:
        return self.root() / self.ledger_name

    def _lock_path(self) -> Path:
        return self.root() / f".{self.ledger_name}.lock"

    def _run_lock_path(self) -> Path:
        return self.root() / f".{self.ledger_name}.run.lock"

    def anchors_root(self) -> Path:
        return self.data_dir / self.anchors_subdir

    def anchors_path(self) -> Path:
        stem = self.ledger_name[: -len(".jsonl")] if self.ledger_name.endswith(".jsonl") else self.ledger_name
        return self.anchors_root() / f"{stem}.anchors.jsonl"

    def file_lock(self, timeout_s: float = 5.0) -> _FileLock:
        return _FileLock(self._lock_path(), timeout_s=timeout_s)

    def run_lock(self) -> _RunLock:
        return _RunLock(self._run_lock_path())

    # ── read ─────────────────────────────────────────────────────────────────────────────────
    def _read_all_from_disk(self) -> List[dict]:
        path = self.ledger_path()
        if not path.exists():
            return []
        out: List[dict] = []
        with open(path, "r") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise LedgerError(f"ledger has a torn line {i} ({path}): {exc}") from exc
        return out

    def read_all(self, *, fresh: bool = False) -> List[dict]:
        """All entries, in order.

        M7 CAUTION, read before touching this: caching here is memoised ONLY after
        :meth:`mark_verified` (``self._trusted``) — NEVER opportunistically on an ordinary,
        un-trusted read. An EARLIER version cached on every call, and a concurrent-writer test
        immediately exposed the hazard: ``registry.upsert`` calls an UNLOCKED ``read_all()``
        (its own duplicate-key pre-check) before ever acquiring the write lock; if THAT call
        populated the cache, a sibling process's write landing in between was invisible to the
        LOCKED ``verify()`` inside the same ``upsert()`` call, which read the STALE cache while
        ``read_anchors()`` (never cached) saw the sibling's fresh anchor — a guaranteed
        ``ledger_truncated`` false alarm under real concurrency. Caching is therefore safe ONLY
        once ``_trusted`` is True: that only happens inside one already-run_lock-and-file_lock-
        serialised run, where THIS process is provably the only writer for the cache's lifetime.
        """
        if self._trusted and self._cache is not None and not fresh:
            return self._cache
        out = self._read_all_from_disk()
        if self._trusted:
            self._cache = out
        return out

    def invalidate_cache(self) -> None:
        """Force the next :meth:`read_all` to re-read from disk. Also drops the ``_trusted``
        flag — a reason to distrust the cache is a reason to distrust the last verify too."""
        self._cache = None
        self._trusted = False

    def mark_verified(self) -> None:
        """Record that the caller already ran a successful :meth:`verify` against the CURRENT
        content (M7), under a lock that serialises this process as the only writer for as long
        as the resulting trust lasts (``run.py`` holds BOTH ``run_lock()`` and, per append,
        ``file_lock()`` for the rest of the run). From this exact moment, :meth:`read_all`
        memoises (and :meth:`append`/:meth:`append_locked` skip the full O(n) chain+anchor
        re-walk on every write) — the anchor file is still extended on every write, so a LATER,
        independent :meth:`verify` by anyone else still catches a torn/tampered history; only
        the REPEATED, redundant re-verification/re-read within one already-verified run is
        skipped. Never call this without first holding a lock that actually excludes other
        writers for the duration of the trust — see the caution on :meth:`read_all`."""
        self._cache = self._read_all_from_disk()
        self._trusted = True

    def read_tail(self) -> Optional[dict]:
        entries = self.read_all()
        return entries[-1] if entries else None

    def find(self, kind: str, key: Sequence) -> Optional[dict]:
        key_l = _key_list(key)
        for e in self.read_all():
            if e.get("kind") == kind and e.get("key") == key_l:
                return e
        return None

    def head_hash(self) -> str:
        tail = self.read_tail()
        return tail["entry_hash"] if tail else GENESIS

    # ── anchors ──────────────────────────────────────────────────────────────────────────────
    def read_anchors(self) -> List[dict]:
        path = self.anchors_path()
        if not path.exists():
            return []
        out: List[dict] = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def _append_anchor(self, line: dict) -> None:
        row = {"seq": line["seq"], "kind": line["kind"], "entry_hash": line["entry_hash"]}
        path = self.anchors_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row_bytes = (_canonical(row) + "\n").encode("utf-8")
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                if fh.tell() > 0:
                    fh.seek(-1, os.SEEK_END)
                    if fh.read(1) != b"\n":
                        row_bytes = b"\n" + row_bytes
        except OSError:
            pass
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, row_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)

    # ── hashing ──────────────────────────────────────────────────────────────────────────────
    def _entry_hash(self, prev_hash: str, seq: int, kind: str, key: list, payload: dict, at: str) -> str:
        payload_ = {"seq": seq, "prev_hash": prev_hash, "kind": kind, "key": key, "payload": payload, "at": at}
        return _sha256_hex((prev_hash + _canonical(payload_)).encode("utf-8"))

    # ── verify ───────────────────────────────────────────────────────────────────────────────
    def verify(self) -> dict:
        """Recompute every hash, cross-check the sibling anchors, name any break. Nothing here
        repairs anything — see the module docstring.

        N3: this ALWAYS reads fresh from disk — ``_read_all_from_disk()``, never the memoised
        ``read_all()`` cache, and ``read_anchors()`` was never cached to begin with. A verify
        is exactly the operation a stale in-process cache must never be allowed to answer: a
        cache populated before an OUTSIDE writer's perfectly legitimate append would otherwise
        see fewer entries than the (also fresh) anchors file now has, and report a false
        ``ledger_truncated`` break on a ledger that is actually fine."""
        entries = self._read_all_from_disk()
        anchors = self.read_anchors()
        seqs = [a.get("seq") for a in anchors]
        if len(seqs) != len(set(seqs)):
            dup = next(q for q in seqs if seqs.count(q) > 1)
            return {"ok": False, "break_at": dup, "entries": len(entries), "reason": "anchor_duplicate"}
        anchors_by_seq = {a.get("seq"): a for a in anchors}
        prev = GENESIS
        expected_seq = 1
        for e in entries:
            if e.get("seq") != expected_seq or e.get("prev_hash") != prev:
                return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "chain"}
            want = self._entry_hash(prev, e["seq"], e["kind"], e["key"], e["payload"], e["at"])
            if want != e.get("entry_hash"):
                return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "chain"}
            anchor = anchors_by_seq.get(e["seq"])
            if anchor is None:
                return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "anchor_missing"}
            if anchor.get("entry_hash") != e.get("entry_hash") or anchor.get("kind") != e.get("kind"):
                return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "anchor_mismatch"}
            prev = e["entry_hash"]
            expected_seq += 1
        # an anchor beyond the ledger's own tail means entries were cut off the end
        beyond = [q for q in seqs if isinstance(q, int) and q > len(entries)]
        if beyond:
            return {"ok": False, "break_at": min(beyond), "entries": len(entries), "reason": "ledger_truncated"}
        return {"ok": True, "break_at": None, "entries": len(entries), "reason": None}

    # ── write ────────────────────────────────────────────────────────────────────────────────
    def append_locked(self, kind: str, key: Sequence, payload: dict, at: str) -> dict:
        """The LOCK-FREE critical section of :meth:`append` — the caller must already hold
        ``file_lock()``. Exists so a caller that needs to check something ELSE (e.g. "what is
        this candidate's current state") and then append, ATOMICALLY under ONE lock
        acquisition, can do so — re-entering :meth:`file_lock` from the same process on a
        freshly-opened fd does NOT merge with a lock already held; it just blocks against
        itself (the exact deadlock a composed caller must avoid)."""
        return self._append_locked(kind, key, payload, at)

    def _append_locked(self, kind: str, key: Sequence, payload: dict, at: str) -> dict:
        key_l = _key_list(key)
        if not self._trusted:
            # M7: this full O(n) chain+anchor walk is the expensive default, run on EVERY
            # append unless the caller already ran mark_verified() once this run — a run
            # that appends hundreds of rows must not pay O(n) EACH time (O(n^2) total).
            verdict = self.verify()
            if not verdict["ok"]:
                raise LedgerError(f"ledger chain broken at seq={verdict['break_at']} "
                                  f"(reason={verdict.get('reason')}); refusing to append")
        existing = self.find(kind, key_l)
        if existing is not None:
            raise DuplicateKey(existing)
        tail = self.read_tail()
        prev_hash = tail["entry_hash"] if tail else GENESIS
        seq = (tail["seq"] + 1) if tail else 1
        entry_hash = self._entry_hash(prev_hash, seq, kind, key_l, payload, at)
        line = {"seq": seq, "prev_hash": prev_hash, "entry_hash": entry_hash, "kind": kind, "key": key_l,
               "payload": payload, "at": at}
        path = self.ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line_bytes = (_canonical(line) + "\n").encode("utf-8")
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._append_anchor(line)
        if self._cache is not None:
            self._cache.append(line)  # keep the memoised read_all() in sync with our own write
        return line

    def append(self, kind: str, key: Sequence, payload: dict, at: str, *, lock_timeout_s: float = 5.0) -> dict:
        """Append one row. Raises :class:`DuplicateKey` (carrying the existing row) if
        ``(kind, key)`` already exists, and :class:`LedgerError` if the chain is already broken.
        """
        with self.file_lock(timeout_s=lock_timeout_s):
            return self._append_locked(kind, key, payload, at)

    def append_idempotent(self, kind: str, key: Sequence, payload: dict, at: str,
                          *, lock_timeout_s: float = 5.0) -> tuple[dict, bool]:
        """``(entry, created)`` — ``created=False`` means the existing row was returned
        unchanged (idempotent no-op), never a silently-overwritten duplicate."""
        try:
            return self.append(kind, key, payload, at, lock_timeout_s=lock_timeout_s), True
        except DuplicateKey as dup:
            return dup.existing, False
