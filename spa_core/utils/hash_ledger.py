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

import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence

GENESIS = "0" * 64

# ── per-process read cache for READ-ONLY consumers (ADR-763 package 2, 2026-10-16) ──────────────
# Measured: one Mission Control build parsed data/research_factory/ledger.jsonl (45 MB, 15 455 lines)
# 4 336 times — 1 077 s of a 1 175 s build (92 %), while the file changes once a day. The M7 caution on
# HashLedger.read_all forbids an opportunistic cache keyed by NOTHING; this one is keyed by the file's
# identity AND size AND mtime, so any append (append-only file ⇒ size grows) is a cache miss and the
# M7 race cannot occur. It is OFF by default and switched on only by processes that never write a
# hash ledger (the cockpit builder), so writer semantics are untouched. Callers get a fresh list; the
# shared row objects are FROZEN (FrozenDict/FrozenList): an in-place change by any reader raises
# instead of corrupting what the next reader gets (ARB 16.10). Writers must still never enable it.
# ADR-777 (cycle #893): the ONE door is now the SCOPED `read_cache()` below, opened by the READ
# MODEL (`research_factory.read.VIEW_ENTRY_POINTS`), not by each entry point. The permanent
# `enable_read_cache()` is gone: it was flipped in exactly one caller, while the cost lives in
# the read model, so eleven other readers of the same model never got the remedy at all.
_READ_CACHE_ENABLED = False
_READ_CACHE: dict = {}
#: how many `read_cache()` scopes are open (nesting), so the outermost one owns the drop
_READ_CACHE_DEPTH = 0


def _refuse(*_a, **_k):
    raise TypeError("cached ledger rows are read-only (ADR-763): copy with dict(row)/list(rows) before changing")


class FrozenDict(dict):
    """A dict a cached row is served as: reading, ``dict(x)``, ``json.dumps`` and ``isinstance(x, dict)``
    behave as before; any in-place change raises instead of silently corrupting the shared cache."""
    __slots__ = ()
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _refuse

    def __copy__(self):
        return dict(self)

    def __deepcopy__(self, memo):
        return {k: _thaw(v) for k, v in self.items()}

    def __reduce__(self):
        return (dict, (dict(self),))


class FrozenList(list):
    __slots__ = ()
    __setitem__ = __delitem__ = append = extend = insert = remove = pop = clear = sort = reverse = _refuse
    __iadd__ = __imul__ = _refuse

    def __copy__(self):
        return list(self)

    def __deepcopy__(self, memo):
        return [_thaw(v) for v in self]

    def __reduce__(self):
        return (list, (list(self),))


def _freeze(v):
    if isinstance(v, dict):
        return FrozenDict((k, _freeze(x)) for k, x in v.items())
    if isinstance(v, list):
        return FrozenList(_freeze(x) for x in v)
    return v


def _thaw(v):
    if isinstance(v, dict):
        return {k: _thaw(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_thaw(x) for x in v]
    return v


@contextlib.contextmanager
def read_cache():
    """The ONE door to the stat-keyed read cache above: open it around a READ-ONLY section.

    Why a scope and not a process-wide flag (ADR-777, cycle #893). The remedy shipped by
    ADR-763 was ``enable_read_cache()`` — a permanent, process-wide switch — and it was
    flipped in exactly ONE place, ``mission_build.main()``. The expensive work, however,
    lives in the READ MODEL, not in that entry point: measured on the owner's Mac,
    ``research_factory.read.latest()`` parses ``data/research_factory/ledger.jsonl``
    (52 108 460 B) **4 958 times** per call, from a dozen different helpers. Every OTHER
    caller of that same read model — the UI-contract test, the owner's Telegram ``/capital``
    view, ``investment_cio.research_universe``, ``capital_shadow.readiness`` — therefore kept
    paying the full price in silence: the same build took **1 613 s** uncached against
    **18.3 s** cached (x88). A remedy that reaches one of a dozen readers is the project's
    standing class "one rule, one copy" — so the switch moves to the reader, and there is
    exactly one way to touch it.

    Two properties the permanent flag did not have:

    * **it ends.** A process that reads a ledger now and writes one later is not poisoned
      for its whole life; the M7 caution on :meth:`HashLedger.read_all` keeps its force
      outside the scope, where writers live.
    * **it is re-entrant and restoring.** Nested scopes (a read model calling another read
      model) keep the cache for the OUTERMOST scope and drop it exactly once, so a caller
      cannot be surprised by a sibling's bookkeeping.

    Correctness is unchanged: the key is ``(dev, inode, size, mtime_ns)``, the file is
    append-only, so any append is a miss; ``verify()`` and the trusted-writer path never
    answer from the cache (both held by tests). Inside one scope the view also becomes
    internally CONSISTENT — without it, 4 958 sequential reads could straddle a sibling's
    append and mix two states of the ledger inside a single answer.
    """
    global _READ_CACHE_ENABLED, _READ_CACHE_DEPTH
    was = _READ_CACHE_ENABLED
    _READ_CACHE_ENABLED = True
    _READ_CACHE_DEPTH += 1
    try:
        yield
    finally:
        _READ_CACHE_DEPTH -= 1
        if _READ_CACHE_DEPTH == 0:
            _READ_CACHE_ENABLED = was
            _READ_CACHE.clear()


def read_cache_depth() -> int:
    """How many :func:`read_cache` scopes are open — observable so a test can assert the
    OUTCOME ("this reader opened the scope") instead of the structure ("the source mentions
    the name"). Zero is a value, not an absence."""
    return _READ_CACHE_DEPTH


def _file_identity(path) -> Optional[tuple]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


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
        #: ADR-797: указатель ключей перенесённого префикса, разобранный ОДИН раз за жизнь
        #: объекта. ``None`` — ещё не читали; ``{}`` — переноса нет. Два разных состояния.
        self._archive_index: Optional[dict] = None

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

    def _stem(self) -> str:
        return self.ledger_name[: -len(".jsonl")] if self.ledger_name.endswith(".jsonl") else self.ledger_name

    def truncation_path(self) -> Path:
        """ОБЪЯВЛЕНИЕ переноса префикса в архив (ADR-797). Его отсутствие и его наличие —
        два разных утверждения: усечённый файл БЕЗ объявления есть молчаливое усечение, и
        :meth:`verify` обязан на него ломаться."""
        return self.root() / f"{self._stem()}.truncation.json"

    def truncation_keys_path(self) -> Path:
        """Указатель ключей перенесённого префикса: сверка ключа → ``[архив, смещение,
        длина]``. Без него :meth:`find` ослеп бы на ключи архива, и
        :meth:`append_idempotent` молча создал бы второй ряд с тем же ключом."""
        return self.root() / f"{self._stem()}.truncation.keys.json"

    def read_truncation(self) -> Optional[dict]:
        path = self.truncation_path()
        if not path.exists():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise LedgerError(f"ledger truncation declaration unreadable ({path}): {exc}") from exc
        if not isinstance(doc, dict):
            raise LedgerError(f"ledger truncation declaration is not an object ({path})")
        return doc

    @staticmethod
    def key_digest(kind: str, key: Sequence) -> str:
        """Личность ПАРЫ (вид, ключ) — то, по чему :meth:`find` ищет дубль."""
        return _sha256_hex(_canonical([kind, _key_list(key)]).encode("utf-8"))

    def _archived_entry(self, kind: str, key_l: list) -> Optional[dict]:
        """Строка архива с этим ключом, либо ``None``.

        Три исхода, и ни один не подменяет другой: переноса не было (``None``) · ключ в
        архиве есть (строка читается ПО СМЕЩЕНИЮ — один seek, а не разбор 72 МБ) · перенос
        объявлен, а указателя нет или он не сходится ⇒ :class:`LedgerError`. Тихий ``None``
        в третьем случае был бы fail-OPEN ровно того класса, против которого указатель и
        написан: «дубля нет» стало бы неотличимо от «мы не смотрели».
        """
        if self._archive_index is None:
            if self.read_truncation() is None:
                self._archive_index = {}
            else:
                path = self.truncation_keys_path()
                if not path.exists():
                    raise LedgerError(
                        f"ledger truncation is declared ({self.truncation_path()}) but its key "
                        f"index is missing ({path}) — duplicate keys in the archive would be "
                        "UNDETECTABLE; refusing to answer 'no duplicate'")
                doc = json.loads(path.read_text(encoding="utf-8"))
                self._archive_index = dict(doc.get("keys") or {})
        hit = self._archive_index.get(self.key_digest(kind, key_l))
        if hit is None:
            return None
        rel, offset, length = hit[0], int(hit[1]), int(hit[2])
        blob = self.root() / rel
        if not blob.exists():
            raise LedgerError(f"archived key points at {blob}, which does not exist")
        with open(blob, "rb") as fh:
            fh.seek(offset)
            raw = fh.read(length)
        entry = json.loads(raw.decode("utf-8"))
        if entry.get("kind") != kind or entry.get("key") != key_l:
            raise LedgerError(f"archived key index points at a row with a DIFFERENT key "
                              f"({entry.get('kind')!r}/{entry.get('key')!r}) — index is unfaithful")
        return entry

    def file_lock(self, timeout_s: float = 5.0) -> _FileLock:
        return _FileLock(self._lock_path(), timeout_s=timeout_s)

    def run_lock(self) -> _RunLock:
        return _RunLock(self._run_lock_path())

    # ── read ─────────────────────────────────────────────────────────────────────────────────
    def _read_all_from_disk(self) -> List[dict]:
        path = self.ledger_path()
        if not path.exists():
            return []
        if _READ_CACHE_ENABLED and not self._trusted:
            ident = _file_identity(path)
            hit = _READ_CACHE.get(str(path))
            if ident is not None and hit is not None and hit[0] == ident:
                return list(hit[1])
            out = self._parse(path)
            if ident is not None and _file_identity(path) == ident:   # unchanged while we parsed
                out = [_freeze(e) for e in out]                        # shared rows cannot be changed in place
                _READ_CACHE[str(path)] = (ident, out)
            return list(out)
        return self._parse(path)

    def _seed_read_cache(self, path: Path, entries: List[dict], ident: Optional[tuple]) -> bool:
        """Отдать ОБЛАСТНОМУ кэшу чтения (ADR-777) записи, которые :meth:`verify` ТОЛЬКО ЧТО
        разобрал с диска. Возвращает, состоялся ли посев, — чтобы исход был наблюдаем тестом,
        а не выводился из текста (ADR-787, цикл #908).

        Зачем (ЗАМЕР, а не рассуждение). Один зов читающего вида
        ``research_factory.read.latest()`` на живой ленте 69 101 205 Б разбирал файл ДВАЖДЫ:
        свежий ``verify()`` (он кэшу не доверяет НИКОГДА — N3) и ещё один разбор, который
        делят все помощники вида. Замер 2026-10-22 на живом ``data/``: оба разбора видели
        ОДНУ И ТУ ЖЕ личность файла ``(dev, inode, size, mtime_ns)`` ⇒ второй читал те же
        байты и был избыточен ПО ЗАМЕРУ. Цена этой избыточности названа прибором
        ``ledger_parse_census``: при темпе 3.599 МБ/сутки бюджет 1.00 с на зов вида
        проходится через ~13 суток, и вернуть запас можно ровно тремя путями — меньше
        разборов, меньше лента, больше бюджет (заказ G784). Это первый из них.

        Что НЕ меняется и почему посев не ослабляет N3. :meth:`verify` по-прежнему разбирает
        файл САМ и из кэша не отвечает никогда — меняется только направление: раньше он
        выбрасывал разобранное, теперь отдаёт. Байты, попадающие в кэш, строго СВЕЖЕЕ тех,
        что положил бы туда обычный читатель следом, и они только что прошли проверку цепи.

        Три условия посева, и каждое — не осторожность, а необходимость:

        * **область открыта** (``_READ_CACHE_ENABLED``). Вне области кэша нет вовсе, и посев
          пережил бы читающую секцию — ровно свойство вечного флага, снятого ADR-777.
        * **писателю не доверено** (``not self._trusted``). У доверенного писателя своя
          память (``self._cache``), и класть мимо неё значило бы завести вторую копию.
        * **личность файла не изменилась, пока шли разбор и обход** — перепроверяется
          ПОСЛЕ, тем же сравнением, что у :meth:`_read_all_from_disk`. Чужая дописка внутри
          нашего разбора делает посев ложью о содержимом файла, и тогда его просто нет:
          следующий читатель разберёт сам. Это третий исход (посева не было), а не тихий
          успех.
        """
        if not _READ_CACHE_ENABLED or self._trusted or ident is None:
            return False
        if _file_identity(path) != ident:   # файл сменился, пока мы читали и обходили
            return False
        _READ_CACHE[str(path)] = (ident, [_freeze(e) for e in entries])
        return True

    @staticmethod
    def _parse(path: Path) -> List[dict]:
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
        self._archive_index = None

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
        #: ADR-797: горячий файл — не вся лента. Ключ, уехавший в архив, обязан по-прежнему
        #: находиться, иначе идемпотентность записи кончается в день первого переноса.
        return self._archived_entry(kind, key_l)

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
        ``ledger_truncated`` break on a ledger that is actually fine. The opt-in stat-keyed read
        cache (ADR-763) is bypassed here too: verify parses the file itself, always.

        ADR-787 (cycle #908) changed the direction of that traffic and nothing else: a verify
        that came back OK now HANDS its freshly parsed entries to the scoped read cache
        (:meth:`_seed_read_cache`), so the helpers that run right after it inside the same
        ``read_cache()`` scope do not parse the same unchanged bytes a second time. Reading
        FROM the cache here is still never done — that is the property N3 names, and it is
        untouched."""
        path = self.ledger_path()
        ident_before = _file_identity(path)
        entries = self._parse(path) if path.exists() else []
        anchors = self.read_anchors()
        seqs = [a.get("seq") for a in anchors]
        if len(seqs) != len(set(seqs)):
            dup = next(q for q in seqs if seqs.count(q) > 1)
            return {"ok": False, "break_at": dup, "entries": len(entries), "reason": "anchor_duplicate"}
        anchors_by_seq = {a.get("seq"): a for a in anchors}
        prev = GENESIS
        expected_seq = 1
        #: ADR-797: горячий файл может НАЧИНАТЬСЯ не с первой записи — если перенос
        #: префикса в архив ОБЪЯВЛЕН. Объявления нет, а первая запись не первая ⇒ это
        #: молчаливое усечение, и ниже оно ломает цепь, как ломало всегда.
        truncated_through = 0
        truncation = self.read_truncation()
        truncation_state = "absent" if truncation is None else "pending"
        if truncation is not None:
            declared = truncation.get("through_seq")
            declared_hash = truncation.get("through_entry_hash")
            anchor_hash = (anchors_by_seq.get(declared) or {}).get("entry_hash")
            first_seq = entries[0].get("seq") if entries else None
            if first_seq == 1:
                #: Перенос объявлен, а префикс ещё на месте — процесс умер между
                #: объявлением и подменой файла. Цепь читается от начала: состояние
                #: ИСПРАВНОЕ, и оно НАЗВАНО (`pending`), а не выдано за обычное.
                pass
            elif (isinstance(declared, int) and declared >= 1 and declared_hash is not None
                    and anchor_hash == declared_hash
                    and (first_seq is None
                         or (first_seq == declared + 1
                             and entries[0].get("prev_hash") == declared_hash))):
                prev = declared_hash
                expected_seq = declared + 1
                truncated_through = declared
                truncation_state = "applied"
            else:
                return {"ok": False, "break_at": first_seq, "entries": len(entries),
                        "reason": "truncation_declaration_mismatch",
                        "truncated_through": 0, "truncation": "mismatch",
                        "declared_through_seq": declared,
                        "declared_through_entry_hash": declared_hash,
                        "anchor_entry_hash_at_declared": anchor_hash}
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
        #: ADR-797: «свой хвост» считается от ОБЪЯВЛЕННОЙ точки усечения, а не от нуля —
        #: иначе перенос префикса сам выглядел бы обрезанным хвостом.
        beyond = [q for q in seqs if isinstance(q, int) and q > truncated_through + len(entries)]
        if beyond:
            return {"ok": False, "break_at": min(beyond), "entries": len(entries),
                    "reason": "ledger_truncated", "truncated_through": truncated_through,
                    "truncation": truncation_state}
        # Цепь сошлась — и ровно здесь разобранное ещё в руках. Посев только на ИСПРАВНОЙ
        # ленте: «повод не верить кэшу есть повод не верить последнему verify»
        # (:meth:`invalidate_cache`), и порванная лента — именно такой повод.
        self._seed_read_cache(path, entries, ident_before)
        return {"ok": True, "break_at": None, "entries": len(entries), "reason": None,
                "truncated_through": truncated_through, "truncation": truncation_state}

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
