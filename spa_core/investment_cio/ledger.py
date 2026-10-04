"""Investment CIO — immutable paper decision ledger (ADR-554 WP-S03).

Three append-only artefacts under ``<data_dir>/investment_cio/``:

* ``snapshots/<sha256>.json.gz`` — content-addressed, gzipped, immutable input snapshot of the
  sleeves document used for one recommendation. Never rewritten once a digest exists.
* ``ledger.jsonl`` — append-only, hash-chained (``prev_hash`` -> ``entry_hash``). ONE entry per UTC
  date: a second run on the same date returns the existing entry, it does not append.
* ``latest.json`` — an atomic pointer to the ledger tail, rebuildable from the ledger itself.

All writes are serialised by ``fcntl.flock`` on ``<data_dir>/investment_cio/.ledger.lock``, and the
chain is verified before every append (a broken chain refuses the append — fail-CLOSED, never
"heals" by writing over it).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.investment_cio import contract
from spa_core.investment_cio.policy import code_identity as _code_identity
from spa_core.utils.atomic import atomic_save

GENESIS = "0" * 64
#: N3: the external anchor file lives in a SEPARATE directory, a SIBLING of ``investment_cio/``
#: (not nested inside it) — so wiping or restoring one directory does not silently also wipe or
#: restore the other. A missing anchor is now itself a break (``anchor_missing``), so the anchor
#: can only do its job (catching a fully-rewritten-but-internally-consistent ledger) if it cannot
#: be erased along with the thing it is meant to witness.
ANCHORS_DIRNAME = "investment_cio_anchors"


class LedgerError(Exception):
    """A chain-integrity or write-contract violation. Nothing is auto-healed; the caller is told."""


class LockBusy(Exception):
    """Another process holds the ledger lock past the wait timeout (run.py exits 75 on this)."""


# ── paths ────────────────────────────────────────────────────────────────────────────────────────

def _root(data_dir: Path) -> Path:
    return Path(data_dir) / contract.DATA_SUBDIR


def _ledger_path(data_dir: Path) -> Path:
    return _root(data_dir) / contract.LEDGER


def _latest_path(data_dir: Path) -> Path:
    return _root(data_dir) / contract.LATEST


def _snapshot_dir(data_dir: Path) -> Path:
    return _root(data_dir) / contract.SNAPSHOT_DIR


def _lock_path(data_dir: Path) -> Path:
    return _root(data_dir) / contract.LOCK


def _anchors_root(data_dir: Path) -> Path:
    return Path(data_dir) / ANCHORS_DIRNAME


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_identity() -> str:
    return _code_identity()


# ── locking ──────────────────────────────────────────────────────────────────────────────────────

class _FileLock:
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


# ── snapshots ────────────────────────────────────────────────────────────────────────────────────

def snapshot_digest(sleeves_doc: dict) -> str:
    return _sha256_hex(_canonical(sleeves_doc).encode("utf-8"))


def save_snapshot(data_dir: Path, sleeves_doc: dict) -> str:
    """Content-addressed, gzipped, immutable. Returns the digest. Never overwrites an existing one."""
    digest = snapshot_digest(sleeves_doc)
    path = _snapshot_dir(data_dir) / f"{digest}.json.gz"
    if path.exists():
        return digest
    payload = gzip.compress(_canonical(sleeves_doc).encode("utf-8"))
    _atomic_write_bytes(path, payload)
    return digest


def load_snapshot(data_dir: Path, digest: str) -> Optional[dict]:
    path = _snapshot_dir(data_dir) / f"{digest}.json.gz"
    if not path.exists():
        return None
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def prune_snapshots(data_dir: Path, *, retention_days: Optional[int] = None,
                    now: Optional[datetime] = None) -> List[str]:
    """Delete UNREFERENCED snapshots older than retention. A referenced snapshot is NEVER deleted,
    regardless of age."""
    retention_days = retention_days if retention_days is not None else contract.POLICY["snapshot_retention_days"]
    now = now or datetime.now(timezone.utc)
    referenced = {e["snapshot_digest"] for e in read_all(data_dir) if e.get("snapshot_digest")}
    removed = []
    sdir = _snapshot_dir(data_dir)
    if not sdir.exists():
        return removed
    cutoff = now.timestamp() - retention_days * 86400
    for p in sdir.glob("*.json.gz"):
        digest = p.name[: -len(".json.gz")]
        if digest in referenced:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            p.unlink(missing_ok=True)
            removed.append(digest)
    return removed


# ── ledger read ──────────────────────────────────────────────────────────────────────────────────

def read_all(data_dir: Path) -> List[dict]:
    """Finding #5: a torn last line (a partial write, e.g. a crash mid-append) used to raise a bare
    ``json.JSONDecodeError`` here — every caller (``read_tail``, ``verify_chain``, ``append``,
    ``read.latest``) inherited that crash, and ``run.py`` then exited 2 forever with no path
    forward. The line number is named so ``repair()`` (and a human) know exactly where the ledger
    tears."""
    path = _ledger_path(data_dir)
    if not path.exists():
        return []
    out = []
    with open(path, "r") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise LedgerError(
                    f"ledger has a torn line {i} — run --repair ({_ledger_path(data_dir)}): {exc}"
                ) from exc
    return out


def read_tail(data_dir: Path) -> Optional[dict]:
    entries = read_all(data_dir)
    return entries[-1] if entries else None


def _entry_hash(prev_hash: str, seq: int, recommendation: dict, snapshot_digest_: str, code_identity_: str) -> str:
    payload = {"seq": seq, "prev_hash": prev_hash, "recommendation": recommendation,
              "snapshot_digest": snapshot_digest_, "code_identity": code_identity_}
    return _sha256_hex((prev_hash + _canonical(payload)).encode("utf-8"))


def _anchors_path(data_dir: Path) -> Path:
    return _anchors_root(data_dir) / "anchors.jsonl"


def _append_anchor(data_dir: Path, line: dict) -> None:
    """Finding #21: a separate, append-only external anchor for each ledger line (seq + date +
    entry_hash). A fully REWRITTEN ledger.jsonl can recompute an internally self-consistent hash
    chain over different content — the chain-verify above cannot catch that by itself. The anchor
    file is never rewritten by :func:`append`, so it disagrees with a rewritten ledger even when
    the rewrite's own hashes check out."""
    row = {"seq": line["seq"], "date": line["recommendation"].get("date"), "entry_hash": line["entry_hash"]}
    path = _anchors_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    row_bytes = (_canonical(row) + "\n").encode("utf-8")
    # a torn previous anchor line (crash mid-write) must not glue onto this one
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


def read_anchors(data_dir: Path) -> List[dict]:
    path = _anchors_path(data_dir)
    if not path.exists():
        return []
    out = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn anchor line degrades the cross-check for that seq; the ledger's
                          # own chain-hash verification above is still the hard-fail path
    return out


def verify_chain(data_dir: Path) -> dict:
    """Recompute every hash, then cross-check against the external anchors (finding #21). Any
    break is named; nothing is repaired.

    N3: a MISSING anchor for an entry that exists in the ledger is itself a break
    (``anchor_missing``) — an anchor that can be silently absent is not a witness, it is a witness
    only when it is PRESENT and checked. The anchor lives in its own sibling directory
    (``ANCHORS_DIRNAME``), never nested under ``investment_cio/``, precisely so wiping or
    restoring one directory cannot silently also erase or restore the other."""
    entries = read_all(data_dir)
    anchors = read_anchors(data_dir)
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
        want = _entry_hash(prev, e["seq"], e["recommendation"], e.get("snapshot_digest"), e.get("code_identity"))
        if want != e.get("entry_hash"):
            return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "chain"}
        anchor = anchors_by_seq.get(e["seq"])
        if anchor is None:
            return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "anchor_missing"}
        if anchor.get("entry_hash") != e.get("entry_hash") or anchor.get("date") != e["recommendation"].get("date"):
            return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "anchor_mismatch"}
        prev = e["entry_hash"]
        expected_seq += 1
    # final-check N3: an anchor for a seq the ledger no longer has means entries were cut off the tail
    beyond = [q for q in seqs if isinstance(q, int) and q > len(entries)]
    if beyond:
        return {"ok": False, "break_at": min(beyond), "entries": len(entries), "reason": "ledger_truncated"}
    return {"ok": True, "break_at": None, "entries": len(entries)}


def repair(data_dir: Path, *, lock_timeout_s: float = 5.0) -> dict:
    """Finding #5: verify the chain up to the last good line and move any torn/broken tail into
    ``ledger.jsonl.torn-<UTCstamp>`` — NEVER deletes. Returns a summary dict; never raises on an
    already-intact ledger.

    N3: when the ledger FILE parses and hash-chains cleanly end-to-end but still disagrees with
    the external anchors (``anchor_mismatch`` / ``anchor_missing``), that is TAMPERING, not a
    torn write — there is no tail to move aside, because every line looks well-formed. Repair
    refuses outright (``repaired: False, fixable: False``) instead of reporting "chain already
    intact", which would be true of the FILE and false of the ledger as a whole."""
    with _FileLock(_lock_path(data_dir), timeout_s=lock_timeout_s):
        path = _ledger_path(data_dir)
        if not path.exists():
            return {"repaired": False, "reason": "no ledger file", "fixable": True, "good_lines": 0,
                    "moved_lines": 0}
        raw_lines = path.read_text().splitlines()
        parsed: List[dict] = []
        first_bad_parsed_idx = None
        for raw in raw_lines:
            s = raw.strip()
            if not s:
                continue
            try:
                parsed.append(json.loads(s))
            except json.JSONDecodeError:
                first_bad_parsed_idx = len(parsed)
                break

        prev = GENESIS
        expected_seq = 1
        verified_good: List[dict] = []
        for e in parsed:
            if e.get("seq") != expected_seq or e.get("prev_hash") != prev:
                break
            want = _entry_hash(prev, e["seq"], e["recommendation"], e.get("snapshot_digest"), e.get("code_identity"))
            if want != e.get("entry_hash"):
                break
            verified_good.append(e)
            prev = e["entry_hash"]
            expected_seq += 1

        if first_bad_parsed_idx is None and len(verified_good) == len(parsed):
            chain_verdict = verify_chain(data_dir)
            # final-check D1: a crash between the ledger write and the anchor write leaves exactly the
            # TAIL entry without an anchor while its own hash chain checks out — that is a recoverable
            # torn write, not tampering: restore that one anchor from the verified entry
            if (not chain_verdict.get("ok", False) and chain_verdict.get("reason") == "anchor_missing"
                    and verified_good and chain_verdict.get("break_at") == verified_good[-1]["seq"]):
                _append_anchor(data_dir, verified_good[-1])
                after = verify_chain(data_dir)
                return {"repaired": bool(after.get("ok")), "reason": "missing tail anchor restored "
                        "(crash between the ledger write and the anchor write)", "fixable": True,
                        "good_lines": len(verified_good), "moved_lines": 0}
            if not chain_verdict.get("ok", False) and chain_verdict.get("reason") in (
                    "anchor_mismatch", "anchor_missing", "ledger_truncated", "anchor_duplicate"):
                return {"repaired": False, "reason": chain_verdict["reason"], "fixable": False,
                        "detail": "the ledger file's own hash chain is self-consistent but disagrees with "
                                 "the external anchors — this is tampering, not a torn write; repair cannot "
                                 "fix tampering",
                        "break_at": chain_verdict.get("break_at"), "good_lines": len(verified_good),
                        "moved_lines": 0}
            return {"repaired": False, "reason": "chain already intact", "fixable": True,
                    "good_lines": len(verified_good), "moved_lines": 0}

        good_count = len(verified_good)
        kept_raw = 0
        seen_parsed = 0
        for raw in raw_lines:
            if seen_parsed >= good_count:
                break
            if raw.strip():
                seen_parsed += 1
            kept_raw += 1
        tail_raw_lines = raw_lines[kept_raw:]

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        torn_path = path.with_name(path.name + f".torn-{stamp}")
        n = 1
        while torn_path.exists():  # extremely unlikely within the same second, but never overwrite
            torn_path = path.with_name(path.name + f".torn-{stamp}-{n}")
            n += 1
        torn_text = ("\n".join(tail_raw_lines) + "\n") if tail_raw_lines else ""
        _atomic_write_bytes(torn_path, torn_text.encode("utf-8"))

        kept_text = ("\n".join(raw_lines[:kept_raw]) + "\n") if kept_raw else ""
        _atomic_write_bytes(path, kept_text.encode("utf-8"))
        rebuild_latest(data_dir)
        return {"repaired": True, "reason": "torn/broken tail moved", "fixable": True, "good_lines": good_count,
                "moved_lines": len(tail_raw_lines), "torn_file": str(torn_path)}


# ── ledger write ─────────────────────────────────────────────────────────────────────────────────

def append(data_dir: Path, recommendation: dict, *, snapshot_digest_: str, code_identity_: Optional[str] = None,
          lock_timeout_s: float = 5.0) -> dict:
    """Append one ledger line for ``recommendation``. Idempotent per UTC date (``recommendation
    ["date"]``): a second call on the same date returns the EXISTING tail entry untouched. A
    call with a date that is EARLIER than the tail's date is refused outright (finding #15: a
    back-dated run must never insert itself into history) — only a later date is a real append.

    Raises :class:`LedgerError` if the chain is already broken (refuses to build on corruption),
    if the ledger has a torn line (see :func:`read_all`), if the new date is not later than the
    tail's, or if ``recommendation`` itself breaches the money-path boundary (finding N6:
    ``executes`` not ``False``, or ``real_capital_usd`` not ``0``/``None``); and :class:`LockBusy`
    if another writer holds the lock past ``lock_timeout_s``.
    """
    code_identity_ = code_identity_ or code_identity()
    # finding N6: this is the LAST gate before anything is written — a non-paper recommendation
    # must never reach the ledger, no matter what produced it.
    executes = recommendation.get("executes", False)
    if executes is not False:
        raise LedgerError(f"refusing to append: executes must be False, got {executes!r} "
                          "(money-path boundary, finding N6)")
    real_capital_usd = recommendation.get("real_capital_usd")
    if real_capital_usd not in (0, None) or isinstance(real_capital_usd, bool):
        raise LedgerError(f"refusing to append: real_capital_usd must be 0 or None, got "
                          f"{real_capital_usd!r} (money-path boundary, finding N6)")
    with _FileLock(_lock_path(data_dir), timeout_s=lock_timeout_s):
        verdict = verify_chain(data_dir)
        if not verdict["ok"]:
            raise LedgerError(f"ledger chain broken at seq={verdict['break_at']} "
                              f"(reason={verdict.get('reason')}); refusing to append")
        tail = read_tail(data_dir)
        new_date = recommendation.get("date")
        if tail is not None:
            tail_date = tail["recommendation"].get("date")
            if tail_date is not None and new_date is not None:
                if new_date == tail_date:
                    return tail  # one entry per UTC date — already have today's
                if new_date < tail_date:
                    raise LedgerError(
                        f"refusing back-dated append: new recommendation date {new_date!r} is not "
                        f"later than the ledger tail's date {tail_date!r} (finding #15)"
                    )
        prev_hash = tail["entry_hash"] if tail else GENESIS
        seq = (tail["seq"] + 1) if tail else 1
        rec2 = json.loads(_canonical(recommendation))  # deep copy via canonical round-trip
        rec2.setdefault("lineage", {})
        rec2["lineage"]["snapshot_digest"] = snapshot_digest_
        entry_hash = _entry_hash(prev_hash, seq, rec2, snapshot_digest_, code_identity_)
        line = {"seq": seq, "prev_hash": prev_hash, "entry_hash": entry_hash, "recommendation": rec2,
               "snapshot_digest": snapshot_digest_, "code_identity": code_identity_}
        path = _ledger_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        # finding #5: a single os.write() on an O_APPEND fd (+ fsync) rather than a buffered
        # file-object write — one write() call is the OS-level unit a crash can't bisect, where a
        # buffered f.write()+f.flush() can still land as two separate underlying writes.
        line_bytes = (_canonical(line) + "\n").encode("utf-8")
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
        atomic_save(line, str(_latest_path(data_dir)))
        _append_anchor(data_dir, line)
        return line


def rebuild_latest(data_dir: Path) -> Optional[dict]:
    """Rebuild ``latest.json`` from the ledger tail (used when the pointer is corrupt/missing)."""
    tail = read_tail(data_dir)
    if tail is None:
        return None
    atomic_save(tail, str(_latest_path(data_dir)))
    return tail


def read_latest_pointer(data_dir: Path) -> Optional[dict]:
    """Read ``latest.json`` as-is (no verification). ``None`` if missing or unparsable."""
    path = _latest_path(data_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
