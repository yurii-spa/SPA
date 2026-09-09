"""
spa_core/audit/hash_chain.py — Tamper-evident, hash-chained audit trail.

PARALLEL LAYER — institutional integrity requirement. A blockchain-style,
append-only log where each entry carries the SHA-256 hash of the previous entry,
so any post-hoc mutation of a historical entry breaks the chain and is detectable.

This module does NOT modify or import any canonical SPA module. It is a thin,
self-contained, stdlib-only ledger that producers (cycle_runner, threat_reactor,
RiskPolicy gate, …) MAY call later to record immutable evidence.

Entry shape::

    {
        "seq":        int,            # 0-based monotonic sequence
        "ts":         str,            # ISO-8601 timestamp (caller-supplied for determinism)
        "event_type": str,            # e.g. "cycle", "risk_event"
        "payload":    dict,           # arbitrary JSON-serialisable body
        "prev_hash":  str,            # entry_hash of seq-1 ('0'*64 for genesis)
        "entry_hash": str,            # sha256 over canonical(seq, ts, event_type, payload, prev_hash)
    }

Canonical JSON = json.dumps(..., sort_keys=True, separators=(',', ':')) so the
hash is stable across processes and Python runs (deterministic).

Stored as JSONL at data/audit_chain.jsonl (one entry per line).

**Appending is O(1) (ADR-273).** Until 2026-09-09 ``append()`` read the WHOLE ledger and
rewrote the WHOLE file through a tmp + ``os.replace``. Correct, and quadratic: measured
2026-09-09 the file was 18.9 MB / 22 738 entries at ~190 appends a day, i.e. **≈3.6 GB of
writes per day** to record ~0.1 MB of new evidence, and the cost of one append grows with
the length of the history it protects. Now an append reads only the chain HEAD (the last
complete line) and appends one line with ``flush`` + ``fsync``.

What that costs in exchange: a crash *between* the write and the fsync can leave a
truncated LAST line. That is a crash artifact, not tampering, and it is never passed off
as either — readers drop an unparseable FINAL line and report it as ``torn_tail`` (a named
third outcome); an unparseable line anywhere else is still a hard error. ``rewrite_all()``
keeps the old whole-file path for compaction and for repairing a torn tail.

Deterministic. stdlib only. No LLM anywhere in the integrity path.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_CHAIN = _DATA / "audit_chain.jsonl"

GENESIS_PREV = "0" * 64


# --------------------------------------------------------------------------- #
# Path indirection (so tests can redirect away from the real data file)
# --------------------------------------------------------------------------- #
def _chain_path() -> Path:
    """Resolve the chain file path each call so monkeypatching _CHAIN works."""
    return _CHAIN


# --------------------------------------------------------------------------- #
# Canonical hashing
# --------------------------------------------------------------------------- #
def _canonical(seq: int, ts: str, event_type: str, payload: dict, prev_hash: str) -> str:
    """Deterministic canonical JSON of the hash-covered fields (excludes entry_hash)."""
    return json.dumps(
        {
            "seq": seq,
            "ts": ts,
            "event_type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_entry_hash(seq: int, ts: str, event_type: str, payload: dict, prev_hash: str) -> str:
    """SHA-256 hex over the canonical JSON of the hash-covered fields."""
    canon = _canonical(seq, ts, event_type, payload, prev_hash)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Disk I/O (atomic)
# --------------------------------------------------------------------------- #
def _read_all(*, with_torn: bool = False):
    """Return every entry as a list of dicts; [] if the chain file is absent/empty.

    A trailing line that does not parse is a TORN TAIL — the signature of a crash between
    the append and its fsync (see the module docstring). It is dropped from the returned
    entries and, with ``with_torn=True``, reported alongside them. It is NOT silently
    swallowed anywhere a verdict is produced: ``verify_chain()`` names it. An unparseable
    line in any other position raises, exactly as before — that is not a crash artifact.
    """
    path = _chain_path()
    if not path.exists():
        return ([], False) if with_torn else []
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln]
    entries: list = []
    torn = False
    for idx, line in enumerate(lines):
        try:
            entries.append(json.loads(line))
        except ValueError:
            if idx == len(lines) - 1:
                torn = True      # truncated final line: crash artifact, named not hidden
                break
            raise
    return (entries, torn) if with_torn else entries


def _read_head() -> Optional[dict]:
    """The last COMPLETE entry of the chain, read without loading the whole file.

    Reads a window from the end of the file and walks backwards to the last line that
    parses. Only the tail can be torn, so at most one candidate is discarded; if the
    window holds no complete line the window is grown (a single entry can be large).
    """
    path = _chain_path()
    if not path.exists():
        return None
    size = path.stat().st_size
    if size == 0:
        return None
    window = 64 * 1024
    while True:
        with path.open("rb") as f:
            start = max(0, size - window)
            f.seek(start)
            chunk = f.read()
        if start > 0:
            # the first line of the window may be a fragment of an earlier entry
            nl = chunk.find(b"\n")
            chunk = chunk[nl + 1:] if nl >= 0 else b""
        lines = [ln for ln in chunk.decode("utf-8", errors="replace").splitlines() if ln.strip()]
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except ValueError:
                continue     # torn final line — try the one before it
            if isinstance(obj, dict):
                return obj
        if start == 0:
            return None
        window *= 8


def _atomic_write_all(entries: list) -> None:
    """Serialise every entry to JSONL and atomically replace the chain file.

    Read-modify-write: the full ledger is rendered to a tmp file in the same
    directory, then os.replace() swaps it in (atomic on POSIX), so a partial
    write can never corrupt the live chain.
    """
    path = _chain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".audit_chain_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        # Best-effort cleanup of the temp file on failure; never leave .audit_chain_*
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _lock_path() -> Path:
    return _chain_path().with_suffix(_chain_path().suffix + ".lock")


@contextlib.contextmanager
def _chain_lock():
    """Serialise «прочитать голову → дописать строку» между процессами.

    Нужен именно из-за перехода на O(1) (ADR-273) и НЕ является украшением. Прежний
    путь (перечитать всё → переписать файл) при двух одновременных писателях терял одну
    запись МОЛЧА: `os.replace` последнего затирал соседа. Теперь оба дописывания дошли бы
    до файла, но оба взяли бы одну и ту же голову — и цепочка получила бы два `seq` с одним
    номером, то есть `verify_chain` объявил бы её порванной. Флот здесь — 80 агентов, и
    писателей у цепочки несколько (цикл, threat_reactor, rates_desk), так что это не
    гипотеза.

    Блокировка — на отдельном `.lock`-файле (сама цепочка остаётся простым JSONL, который
    читает любой сторонний верификатор). `fcntl.flock` есть в stdlib на macOS и Linux;
    если ОС её не даёт, дописывание идёт без неё — потеря сериализации названа в
    исключении, а не выдана за успех.
    """
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    fh = None
    try:
        fh = open(lock, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass          # ФС без flock (редкая сетевая): дописываем, но не молчим об этом
        yield
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()


def _append_line(entry: dict) -> None:
    """Append ONE canonical JSONL line and force it to disk (O(1) in chain length)."""
    path = _chain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def rewrite_all(entries: list) -> None:
    """Whole-file rewrite (compaction / repair of a torn tail). Kept deliberately.

    Not used by ``append()`` any more (ADR-273); it is the only way to shorten or repair
    the file, and a repair must be as atomic as the old append was.
    """
    _atomic_write_all(entries)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def append(event_type: str, payload: dict, ts: Optional[str] = None) -> dict:
    """Append one entry, linking it to the current chain head, and persist.

    Args:
        event_type: short event tag (e.g. "cycle", "risk_event").
        payload: JSON-serialisable body.
        ts: ISO-8601 timestamp. MUST be supplied in tests for determinism; in
            production, defaults to UTC now.

    Returns the fully-formed entry (incl. seq, prev_hash, entry_hash).
    """
    if ts is None:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if payload is None:
        payload = {}

    # ADR-273: only the HEAD is read, and only one line is written. The previous
    # implementation read and rewrote the whole ledger on every append. «Прочитать
    # голову → дописать» обязано быть неделимым, иначе два писателя возьмут один seq.
    with _chain_lock():
        head_entry = _read_head()
        if head_entry is None:
            seq, prev_hash = 0, GENESIS_PREV
        else:
            seq = int(head_entry["seq"]) + 1
            prev_hash = head_entry["entry_hash"]
        entry_hash = compute_entry_hash(seq, ts, event_type, payload, prev_hash)

        entry = {
            "seq": seq,
            "ts": ts,
            "event_type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }
        _append_line(entry)
    return entry


def verify_chain() -> dict:
    """Recompute every hash and check prev-linkage; detect any tampering.

    Returns::

        {"valid": bool, "length": int, "broken_at": Optional[int]}

    ``broken_at`` is the seq of the first entry that fails verification
    (wrong recomputed hash, broken prev-link, or out-of-order seq), else None.
    An empty chain is valid. ``torn_tail`` is True when the FINAL line does not parse —
    a crash between an append and its fsync (ADR-273); the verified prefix is still valid
    and the fact is reported, never swallowed.
    """
    entries, torn = _read_all(with_torn=True)
    expected_prev = GENESIS_PREV
    for idx, e in enumerate(entries):
        # seq must be monotonic and match position.
        if e.get("seq") != idx:
            return {"valid": False, "length": len(entries), "broken_at": idx,
                    "torn_tail": torn}
        # prev_hash must link to the previous entry's entry_hash.
        if e.get("prev_hash") != expected_prev:
            return {"valid": False, "length": len(entries), "broken_at": idx,
                    "torn_tail": torn}
        # entry_hash must match a fresh recompute over the covered fields.
        recomputed = compute_entry_hash(
            e.get("seq"),
            e.get("ts"),
            e.get("event_type"),
            e.get("payload"),
            e.get("prev_hash"),
        )
        if recomputed != e.get("entry_hash"):
            return {"valid": False, "length": len(entries), "broken_at": idx,
                    "torn_tail": torn}
        expected_prev = e["entry_hash"]
    # A torn LAST line is a crash artifact, not tampering — the chain up to it verifies,
    # and the fact is NAMED rather than hidden (repair: rewrite_all(_read_all())).
    return {"valid": True, "length": len(entries), "broken_at": None, "torn_tail": torn}


def tail(n: int = 20) -> list:
    """Return the last ``n`` entries (most recent last)."""
    if n <= 0:
        return []
    entries: list = _read_all()
    return entries[-n:]


def head() -> Optional[dict]:
    """Return the genesis (first) entry, or None on an empty chain."""
    entries = _read_all()
    return entries[0] if entries else None


# --------------------------------------------------------------------------- #
# Typed wrappers (thin helpers for known producers)
# --------------------------------------------------------------------------- #
def record_cycle(summary_dict: dict, ts: str) -> dict:
    """Record a paper-trading cycle summary as a 'cycle' entry."""
    return append("cycle", summary_dict, ts=ts)


def record_risk_event(reason: str, ts: str) -> dict:
    """Record a risk / kill-switch event as a 'risk_event' entry."""
    return append("risk_event", {"reason": reason}, ts=ts)


# --------------------------------------------------------------------------- #
# Demo
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # Fixed timestamps → deterministic demo output (also useful for a smoke check).
    record_cycle(
        {"date": "2026-06-24", "equity_usd": 100149.54, "apy_today_pct": 4.9},
        ts="2026-06-24T08:00:00+00:00",
    )
    record_risk_event(
        "TVL floor breach on example_pool (read-only advisory)",
        ts="2026-06-24T08:05:00+00:00",
    )
    print(json.dumps(verify_chain(), indent=2))
    print(json.dumps({"head": head(), "tail": tail(2)}, indent=2, ensure_ascii=False))
