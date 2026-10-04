"""capital_shadow.ledger — append-only, hash-chained ledger (ADR-556, modelled on
``spa_core/investment_cio/ledger.py``; patterns reused, no private functions imported).

One file, many kinds of rows (``intent`` / ``transition`` / ``simulation`` / ``shadow_fill`` /
``reconciliation`` / ``readiness`` / ``incident``). Idempotency is a first-class citizen: every
write names a ``key`` and a second write under the same key is refused (:class:`DuplicateKey`),
never silently duplicated and never silently overwritten — the caller decides what "idempotent"
means for its own kind (machine.py treats a duplicate transition as a no-op; ledger.py itself only
ever refuses).

External anchors live in a SIBLING directory (``data/capital_shadow_anchors/``), exactly as
ADR-554's investment_cio ledger — so wiping or restoring one directory cannot silently also wipe
or restore the other.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence

from spa_core.capital_shadow import contract
from spa_core.utils.atomic import atomic_save

GENESIS = "0" * 64


class LedgerError(Exception):
    """Chain-integrity or write-contract violation. Nothing is auto-healed."""


class LockBusy(Exception):
    """Another process holds the ledger lock past the wait timeout (CLI layer exits 75)."""


class DuplicateKey(Exception):
    """A write was refused because its (kind, key) already exists. Carries the EXISTING entry so
    a caller that treats a repeat as idempotent (machine.py) does not need a second read."""

    def __init__(self, existing: dict):
        super().__init__(f"duplicate key: kind={existing.get('kind')!r} key={existing.get('key')!r}")
        self.existing = existing


# ── paths ────────────────────────────────────────────────────────────────────────────────────────

def _root(data_dir: Path) -> Path:
    return Path(data_dir) / contract.DATA_SUBDIR


def _ledger_path(data_dir: Path) -> Path:
    return _root(data_dir) / contract.LEDGER


def _latest_path(data_dir: Path) -> Path:
    return _root(data_dir) / contract.LATEST


def _lock_path(data_dir: Path) -> Path:
    return _root(data_dir) / contract.LOCK


def _anchors_root(data_dir: Path) -> Path:
    return Path(data_dir) / contract.ANCHORS_SUBDIR


def _anchors_path(data_dir: Path) -> Path:
    return _anchors_root(data_dir) / "anchors.jsonl"


def sim_dir(data_dir: Path) -> Path:
    return _root(data_dir) / contract.SIM_DIR


def sim_path(data_dir: Path, intent_id: str) -> Path:
    return sim_dir(data_dir) / f"{intent_id}.json"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key_list(key: Sequence) -> list:
    return [k for k in key]


# ── locking (modelled on investment_cio._FileLock) ──────────────────────────────────────────────

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


def file_lock(data_dir: Path, timeout_s: float = 5.0) -> _FileLock:
    """Exposed so :mod:`incidents` (a sibling append-only file, same directory) can serialise
    against the SAME lock rather than inventing its own."""
    return _FileLock(_lock_path(data_dir), timeout_s=timeout_s)


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


# ── read ─────────────────────────────────────────────────────────────────────────────────────────

def read_all(data_dir: Path) -> List[dict]:
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
                raise LedgerError(f"ledger has a torn line {i} ({_ledger_path(data_dir)}): {exc}") from exc
    return out


def read_tail(data_dir: Path) -> Optional[dict]:
    entries = read_all(data_dir)
    return entries[-1] if entries else None


def find_by_key(data_dir: Path, kind: str, key: Sequence) -> Optional[dict]:
    key_l = _key_list(key)
    for e in read_all(data_dir):
        if e.get("kind") == kind and e.get("key") == key_l:
            return e
    return None


def _entry_hash(prev_hash: str, seq: int, kind: str, key: list, payload: dict, at: str) -> str:
    payload_ = {"seq": seq, "prev_hash": prev_hash, "kind": kind, "key": key, "payload": payload, "at": at}
    return _sha256_hex((prev_hash + _canonical(payload_)).encode("utf-8"))


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
                continue
    return out


def _append_anchor(data_dir: Path, line: dict) -> None:
    row = {"seq": line["seq"], "kind": line["kind"], "entry_hash": line["entry_hash"]}
    path = _anchors_path(data_dir)
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


def verify_chain(data_dir: Path) -> dict:
    """Recompute every hash, cross-check external anchors. Any break is named; nothing repaired."""
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
        want = _entry_hash(prev, e["seq"], e["kind"], e["key"], e["payload"], e["at"])
        if want != e.get("entry_hash"):
            return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "chain"}
        anchor = anchors_by_seq.get(e["seq"])
        if anchor is None:
            return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "anchor_missing"}
        if anchor.get("entry_hash") != e.get("entry_hash") or anchor.get("kind") != e.get("kind"):
            return {"ok": False, "break_at": e.get("seq"), "entries": len(entries), "reason": "anchor_mismatch"}
        prev = e["entry_hash"]
        expected_seq += 1
    beyond = [q for q in seqs if isinstance(q, int) and q > len(entries)]
    if beyond:
        return {"ok": False, "break_at": min(beyond), "entries": len(entries), "reason": "ledger_truncated"}
    return {"ok": True, "break_at": None, "entries": len(entries)}


def repair(data_dir: Path, *, lock_timeout_s: float = 5.0, dispatcher: Any = None) -> dict:
    """Move a torn/broken TAIL aside as ``ledger.jsonl.torn-<stamp>`` — never deletes. Refuses
    outright (``fixable: False``) when the file parses and chains cleanly end-to-end but still
    disagrees with the external anchors: that is tampering, not a torn write."""
    with file_lock(data_dir, timeout_s=lock_timeout_s):
        path = _ledger_path(data_dir)
        if not path.exists():
            return {"repaired": False, "reason": "no ledger file", "fixable": True, "good_lines": 0, "moved_lines": 0}
        raw_lines = path.read_text().splitlines()
        non_empty_lines = [r for r in raw_lines if r.strip()]
        parsed: List[dict] = []
        first_bad_idx = None
        for raw in raw_lines:
            s = raw.strip()
            if not s:
                continue
            try:
                parsed.append(json.loads(s))
            except json.JSONDecodeError:
                first_bad_idx = len(parsed)
                break

        # review N4-iv: a bad/unparseable line is a torn WRITE only if it is the very LAST line —
        # a crash mid-append leaves at most one incomplete trailing line. A bad line with MORE
        # content after it is not a crash, it is mid-chain TAMPERING, and nothing may be moved
        # aside: moving a "torn tail" that isn't actually the tail would silently discard
        # legitimate later entries while dressing the damage up as a routine repair.
        if first_bad_idx is not None and first_bad_idx != len(non_empty_lines) - 1:
            try:
                from spa_core.capital_shadow import incidents as _incidents
                _incidents.raise_incident(
                    data_dir, "ledger_tampered",
                    f"bad/unparseable line at position {first_bad_idx + 1} of {len(non_empty_lines)}, "
                    f"followed by {len(non_empty_lines) - first_bad_idx - 1} more line(s) — mid-chain "
                    f"tampering, not a torn tail; refusing to move anything aside",
                    now=datetime.now(timezone.utc), dispatcher=dispatcher)
            except Exception:  # noqa: BLE001 — the refusal below is authoritative either way
                pass
            return {"repaired": False,
                    "reason": "ledger_tampered: a bad line is followed by more content mid-chain — only a "
                             "torn LAST line may ever be moved aside",
                    "fixable": False, "good_lines": first_bad_idx, "moved_lines": 0}

        prev = GENESIS
        expected_seq = 1
        verified_good: List[dict] = []
        for e in parsed:
            if e.get("seq") != expected_seq or e.get("prev_hash") != prev:
                break
            want = _entry_hash(prev, e["seq"], e["kind"], e["key"], e["payload"], e["at"])
            if want != e.get("entry_hash"):
                break
            verified_good.append(e)
            prev = e["entry_hash"]
            expected_seq += 1

        if first_bad_idx is None and len(verified_good) == len(parsed):
            chain_verdict = verify_chain(data_dir)
            # MEDIUM review finding #11c: re-anchoring is allowed ONLY when the tail entry's own
            # anchor is the thing missing AND that entry's hash chains correctly from the last
            # ANCHORED entry (every entry up to the tail already passed verify_chain's own
            # per-entry anchor check above — this is not "the file parses", it is "every entry
            # before the tail was already witnessed"). It must never re-anchor a tail whose chain
            # is merely self-consistent but diverges from an already-anchored entry (that is
            # tampering, handled by the branch below, not here).
            if not chain_verdict.get("ok", False) and chain_verdict.get("reason") == "anchor_missing" \
                    and verified_good and chain_verdict.get("break_at") == verified_good[-1]["seq"]:
                # review N4-iv: automatic re-anchoring is GONE entirely — even a tail that chains
                # correctly from the last anchored entry is EXACTLY the shape a forged append
                # would also take, and "fixed automatically" must never mean "silently certified".
                # This only RAISES the incident (minting the nonce the owner must copy into
                # data/capital_shadow/owner_confirmations/<incident_id>.json) and reports NOT
                # repaired; :func:`reanchor_with_owner_confirmation` performs the actual write,
                # and only once that file exists with the matching nonce.
                tail_entry = verified_good[-1]
                incident_id = None
                try:
                    from spa_core.capital_shadow import incidents as _incidents
                    row = _incidents.raise_incident(
                        data_dir, "anchor_broken",
                        f"tail entry seq={tail_entry.get('seq')} kind={tail_entry.get('kind')!r} "
                        f"entry_hash={tail_entry.get('entry_hash')!r} chains correctly from the last "
                        f"anchored entry but its OWN anchor row is missing (likely a crash between the "
                        f"ledger write and the anchor write) — re-anchoring now REQUIRES owner "
                        f"confirmation (ledger.reanchor_with_owner_confirmation), never automatic",
                        now=datetime.now(timezone.utc), dispatcher=dispatcher)
                    incident_id = row.get("incident_id")
                except Exception:  # noqa: BLE001 — the refusal below is authoritative either way
                    pass
                return {"repaired": False,
                        "reason": "missing tail anchor — owner confirmation required before re-anchoring"
                                 + (f" (incident {incident_id})" if incident_id else ""),
                        "fixable": True, "good_lines": len(verified_good), "moved_lines": 0,
                        "incident_id": incident_id}
            if not chain_verdict.get("ok", False) and chain_verdict.get("reason") in (
                    "anchor_mismatch", "anchor_missing", "ledger_truncated", "anchor_duplicate"):
                return {"repaired": False, "reason": chain_verdict["reason"], "fixable": False,
                        "detail": "ledger file self-consistent but disagrees with external anchors — tampering, "
                                 "not a torn write; repair cannot fix tampering",
                        "break_at": chain_verdict.get("break_at"), "good_lines": len(verified_good), "moved_lines": 0}
            return {"repaired": False, "reason": "chain already intact", "fixable": True,
                    "good_lines": len(verified_good), "moved_lines": 0}

        good_count = len(verified_good)
        kept_raw, seen_parsed = 0, 0
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
        while torn_path.exists():
            torn_path = path.with_name(path.name + f".torn-{stamp}-{n}")
            n += 1
        torn_text = ("\n".join(tail_raw_lines) + "\n") if tail_raw_lines else ""
        _atomic_write_bytes(torn_path, torn_text.encode("utf-8"))
        kept_text = ("\n".join(raw_lines[:kept_raw]) + "\n") if kept_raw else ""
        _atomic_write_bytes(path, kept_text.encode("utf-8"))
        rebuild_latest(data_dir)
        return {"repaired": True, "reason": "torn/broken tail moved", "fixable": True, "good_lines": good_count,
                "moved_lines": len(tail_raw_lines), "torn_file": str(torn_path)}


def reanchor_with_owner_confirmation(data_dir: Path, incident_id: str, *, now: Optional[datetime] = None,
                                     lock_timeout_s: float = 5.0) -> dict:
    """Review N4-iv: the ONLY way a missing tail anchor gets re-anchored. ``repair()`` no longer
    does this automatically — it only raises the ``anchor_broken`` incident ``incident_id`` names.
    Requires the SAME owner-confirmation-file mechanism :func:`incidents.clear_incident` uses
    (``data/capital_shadow/owner_confirmations/<incident_id>.json``, naming the nonce
    ``incidents.raise_incident`` minted for THAT incident) — the runtime never writes that file.
    On success, records a ``ledger_repaired`` incident and clears the originating ``anchor_broken``
    one with the SAME confirmation, spent once."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    from spa_core.capital_shadow import incidents as _incidents
    rows = _incidents.read_all(data_dir)
    found = None
    for r in rows:
        if r.get("incident_id") == incident_id and r.get("kind") == "anchor_broken" and r.get("seq", 0) >= \
                (found.get("seq", 0) if found else 0):
            if r.get("status") == "OPEN" or found is None:
                found = r
    if found is None or found.get("status") != "OPEN":
        raise LedgerError(f"no OPEN anchor_broken incident {incident_id!r} to act on")
    supplied_nonce = _incidents.read_owner_confirmation_nonce(data_dir, incident_id)
    stored_nonce = found.get("confirmation_nonce")
    if not stored_nonce or not supplied_nonce or supplied_nonce != stored_nonce:
        raise LedgerError(f"owner confirmation missing/mismatched for incident {incident_id!r} — refusing to "
                          f"re-anchor without it (out-of-band owner act required)")

    with file_lock(data_dir, timeout_s=lock_timeout_s):
        chain_verdict = verify_chain(data_dir)
        if chain_verdict.get("ok") or chain_verdict.get("reason") != "anchor_missing":
            raise LedgerError(f"ledger is no longer in the anchor_missing state this confirmation was for "
                              f"(ok={chain_verdict.get('ok')} reason={chain_verdict.get('reason')!r})")
        entries = read_all(data_dir)
        tail_entry = entries[-1] if entries else None
        if tail_entry is None or chain_verdict.get("break_at") != tail_entry.get("seq"):
            raise LedgerError("anchor_missing is not at the tail — this confirmation only covers a tail repair")
        _append_anchor(data_dir, tail_entry)
        after = verify_chain(data_dir)

    _incidents.raise_incident(data_dir, "ledger_repaired",
                              f"owner-confirmed re-anchor of seq={tail_entry.get('seq')} "
                              f"entry_hash={tail_entry.get('entry_hash')!r} (incident {incident_id})",
                              now=now)
    _incidents.clear_incident(data_dir, incident_id,
                              f"re-anchored under owner confirmation; chain ok={after.get('ok')}", now=now)
    return {"repaired": bool(after.get("ok")), "reason": "owner-confirmed re-anchor", "fixable": True}


# ── write ────────────────────────────────────────────────────────────────────────────────────────

def _validate_money_path_payload(payload: dict) -> None:
    """Money-path boundary mirrors investment_cio's finding N6: a payload claiming ``executes``
    not False, or ``real_capital_usd`` not 0/None, is refused outright — this ledger NEVER records
    a row that claims to have moved money."""
    executes = payload.get("executes", False)
    if executes is not False:
        raise LedgerError(f"refusing to append: executes must be False, got {executes!r}")
    real_capital_usd = payload.get("real_capital_usd")
    if real_capital_usd not in (0, None) or isinstance(real_capital_usd, bool):
        raise LedgerError(f"refusing to append: real_capital_usd must be 0 or None, got {real_capital_usd!r}")


def _append_entry_locked(data_dir: Path, *, kind: str, key: Sequence, payload: dict, now: datetime) -> dict:
    """The lock-free CRITICAL SECTION of :func:`append_entry` — assumes the caller already holds
    ``file_lock(data_dir)``. Exists so a caller that needs to check something ELSE (e.g. "is there
    an outstanding owner_action for this sleeve") and then append, ATOMICALLY under ONE lock
    acquisition, can do so without re-entering ``file_lock`` (which would time out: ``flock`` on a
    second, freshly-opened fd from the SAME process does not merge with one already held —
    it just blocks/`LockBusy`s against itself). See :func:`open_owner_action_if_none_outstanding`
    (review N3)."""
    _validate_money_path_payload(payload)
    key_l = _key_list(key)
    at = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if now.tzinfo else \
        now.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verdict = verify_chain(data_dir)
    if not verdict["ok"]:
        raise LedgerError(f"ledger chain broken at seq={verdict['break_at']} "
                          f"(reason={verdict.get('reason')}); refusing to append")
    existing = find_by_key(data_dir, kind, key_l)
    if existing is not None:
        raise DuplicateKey(existing)
    tail = read_tail(data_dir)
    prev_hash = tail["entry_hash"] if tail else GENESIS
    seq = (tail["seq"] + 1) if tail else 1
    entry_hash = _entry_hash(prev_hash, seq, kind, key_l, payload, at)
    line = {"seq": seq, "prev_hash": prev_hash, "entry_hash": entry_hash, "kind": kind, "key": key_l,
           "payload": payload, "at": at}
    path = _ledger_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def append_entry(data_dir: Path, *, kind: str, key: Sequence, payload: dict, now: datetime,
                  lock_timeout_s: float = 5.0) -> dict:
    """Append one row. Raises :class:`DuplicateKey` (carrying the existing row) if ``(kind, key)``
    already exists — the caller decides whether that is an error or a no-op."""
    with file_lock(data_dir, timeout_s=lock_timeout_s):
        return _append_entry_locked(data_dir, kind=kind, key=key, payload=payload, now=now)


def append_idempotent(data_dir: Path, *, kind: str, key: Sequence, payload: dict, now: datetime,
                       lock_timeout_s: float = 5.0) -> tuple[dict, bool]:
    """Convenience wrapper: returns ``(entry, created)`` — ``created=False`` means the existing
    row was returned unchanged (idempotent no-op), never a silently-overwritten duplicate."""
    try:
        return append_entry(data_dir, kind=kind, key=key, payload=payload, now=now,
                            lock_timeout_s=lock_timeout_s), True
    except DuplicateKey as dup:
        return dup.existing, False


def rebuild_latest(data_dir: Path) -> Optional[dict]:
    tail = read_tail(data_dir)
    if tail is None:
        return None
    atomic_save(tail, str(_latest_path(data_dir)))
    return tail


def read_latest_pointer(data_dir: Path) -> Optional[dict]:
    path = _latest_path(data_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# ── simulations (immutable, write-once, keyed by intent_id) ────────────────────────────────────

def record_simulation(data_dir: Path, intent_id: str, record: dict) -> Path:
    """Write-once: an existing simulation record for the same intent must be byte-identical, or
    this raises (a simulation is evidence — it is never silently replaced)."""
    path = sim_path(data_dir, intent_id)
    payload_bytes = (json.dumps(record, sort_keys=True, indent=2, default=str)).encode("utf-8")
    if path.exists():
        existing = path.read_bytes()
        if existing != payload_bytes:
            # allow a semantically-identical re-simulation (default=str/indent noise aside) by
            # comparing canonical forms rather than raw bytes.
            try:
                if json.loads(existing) == record:
                    return path
            except json.JSONDecodeError:
                pass
            raise LedgerError(f"simulation record for {intent_id} is immutable and differs from the new one")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload_bytes)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def load_simulation(data_dir: Path, intent_id: str) -> Optional[dict]:
    path = sim_path(data_dir, intent_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def record_simulation_entry(data_dir: Path, intent: dict, sim_record: dict, now: datetime) -> dict:
    """Writes BOTH halves of the simulation evidence: the immutable write-once file (full record,
    :func:`record_simulation`) AND a queryable ledger row (kind ``simulation``, key
    ``("simulation", intent_id, block_number)``).

    ``simulate.py``'s own output (``contract.SCHEMA_SIMULATION``) carries no ``venue``/``instrument``
    field — only ``intent_id`` — so the venue for readiness's per-venue gates is read off the
    INTENT that was simulated (``network_or_venue``), never guessed from the simulation record
    itself (a prior cut of this code assumed the record echoed a ``venue`` key that does not exist
    on the real simulator's output, so no simulation ever matched a held venue — found via an
    integration run against real data)."""
    intent_id = intent["intent_id"]
    venue = intent.get("network_or_venue")
    block = (sim_record.get("block") or {}).get("number")
    record_simulation(data_dir, intent_id, sim_record)
    payload = {"intent_id": intent_id, "sleeve_id": intent.get("sleeve_id"), "venue": venue, "block": block,
              "result": sim_record.get("result"), "revert_reason": sim_record.get("revert_reason"),
              "simulated_at": sim_record.get("simulated_at")}
    entry, _ = append_idempotent(data_dir, kind="simulation", key=("simulation", intent_id, block), payload=payload,
                                 now=now)
    return entry


def simulations_for_venues(ledger_entries: Sequence[dict], venues: Sequence[str]) -> dict:
    """Latest ``kind=="simulation"`` ledger row per venue (venue comes from the recording intent,
    via :func:`record_simulation_entry`'s own payload — never re-derived from the simulation
    record). ``None`` for a venue with no simulation on record yet."""
    out: dict = {v: None for v in venues}
    for e in ledger_entries:
        if e.get("kind") != "simulation":
            continue
        payload = e.get("payload") or {}
        venue = payload.get("venue")
        if venue not in out:
            continue
        prev = out[venue]
        if prev is None or e["seq"] > prev["seq"]:
            out[venue] = e
    return out


# ── owner-action single-outstanding tracking (HIGH review finding #6) ──────────────────────────
#: terminal statuses a runbook's own owner_action row can reach — once here, a NEW one may open.
_OWNER_ACTION_CLOSED_STATUSES = ("EXPIRED", "CANCELLED", "RECONCILED")


def _parse_iso_utc(value: str) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        v = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def outstanding_owner_action(data_dir: Path, sleeve_id: str, now: datetime) -> Optional[dict]:
    """The latest ``owner_action`` row for ``sleeve_id`` whose status is still open. "Open" is
    computed from ``now`` EVERY TIME (TOCTOU-safe, same discipline as ``machine.is_expired``):
    not EXPIRED/CANCELLED/RECONCILED by status, AND not past its own recorded ``expires_at`` even
    if nobody ever wrote the EXPIRED row. ``None`` means a new runbook may be issued."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    latest = None
    for e in read_all(data_dir):
        if e.get("kind") != "owner_action":
            continue
        payload = e.get("payload") or {}
        if payload.get("sleeve_id") != sleeve_id:
            continue
        if latest is None or e["seq"] > latest["seq"]:
            latest = e
    if latest is None:
        return None
    payload = latest.get("payload") or {}
    if payload.get("status") in _OWNER_ACTION_CLOSED_STATUSES:
        return None
    expires_at = _parse_iso_utc(payload.get("expires_at"))
    if expires_at is not None and now >= expires_at:
        return None
    return latest


def open_owner_action(data_dir: Path, *, sleeve_id: str, intent_id: str, block: Any, expires_at: str,
                      now: datetime) -> dict:
    """Records the single outstanding owner action a generated runbook represents (review #5).
    Idempotent per ``intent_id`` — generating the SAME runbook twice is a no-op, never a second
    open row that ``outstanding_owner_action`` would have to reconcile."""
    payload = {"sleeve_id": sleeve_id, "intent_id": intent_id, "status": "OPEN", "block": block,
              "expires_at": expires_at, "executes": False, "real_capital_usd": 0}
    entry, _ = append_idempotent(data_dir, kind="owner_action", key=("owner_action", "open", intent_id),
                                 payload=payload, now=now)
    return entry


class OwnerActionAlreadyOpen(Exception):
    """A DIFFERENT intent's owner action is still open for this sleeve. Carries the existing row."""

    def __init__(self, existing: dict):
        payload = existing.get("payload") or {}
        super().__init__(f"sleeve {payload.get('sleeve_id')!r} already has an outstanding owner action open "
                         f"(intent_id={payload.get('intent_id')!r})")
        self.existing = existing


def open_owner_action_if_none_outstanding(data_dir: Path, *, sleeve_id: str, intent_id: str, block: Any,
                                          expires_at: str, now: datetime) -> tuple[dict, bool]:
    """Review N3: the check ("is one already open for this sleeve?") and the append MUST happen
    under ONE lock acquisition — the previous code read ``outstanding_owner_action`` and wrote
    ``open_owner_action`` as two SEPARATE, unlocked-between-them steps, so two concurrent
    ``runbook.generate`` calls for the SAME sleeve but DIFFERENT intents could each observe "none
    open" before either had written theirs, and both would then open — exactly the bypass the
    single-outstanding-action guarantee exists to prevent.

    Every ISSUANCE gets its OWN key (``intent_id`` + microsecond ``issued_at``) — re-issuing for
    the SAME intent is allowed (returns a NEW row, not an idempotent no-op: each issuance is its
    own audit entry) and does not count as "a different action", but a DIFFERENT intent's still-
    open action blocks (:class:`OwnerActionAlreadyOpen`, carrying the existing row)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    with file_lock(data_dir):
        existing = outstanding_owner_action(data_dir, sleeve_id, now)
        if existing is not None and (existing.get("payload") or {}).get("intent_id") != intent_id:
            raise OwnerActionAlreadyOpen(existing)
        issued_at = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        payload = {"sleeve_id": sleeve_id, "intent_id": intent_id, "status": "OPEN", "block": block,
                  "expires_at": expires_at, "issued_at": issued_at, "executes": False, "real_capital_usd": 0}
        key = ("owner_action", "open", intent_id, issued_at)
        try:
            return _append_entry_locked(data_dir, kind="owner_action", key=key, payload=payload, now=now), True
        except DuplicateKey as dup:
            return dup.existing, False


def close_owner_action(data_dir: Path, *, sleeve_id: str, intent_id: str, status: str, now: datetime,
                       detail: Optional[str] = None) -> dict:
    """Appends the CLOSING row for an outstanding owner action — append-only, so this is a NEW row
    (never a mutation of the OPEN one), keyed distinctly by its own terminal status so it cannot
    collide with ``open_owner_action``'s key or with a different terminal status recorded earlier."""
    if status not in _OWNER_ACTION_CLOSED_STATUSES:
        raise ValueError(f"close_owner_action: status must be one of {_OWNER_ACTION_CLOSED_STATUSES}, "
                         f"got {status!r}")
    payload = {"sleeve_id": sleeve_id, "intent_id": intent_id, "status": status, "detail": detail,
              "executes": False, "real_capital_usd": 0}
    entry, _ = append_idempotent(data_dir, kind="owner_action", key=("owner_action", "close", intent_id, status),
                                 payload=payload, now=now)
    return entry


# ── single-use owner approval (review #5: "an owner approval recorded by the system binds
# intent_id + block + expires_at and is single-use") ────────────────────────────────────────────

class ApprovalAlreadyUsed(Exception):
    """A recorded owner approval may be consumed exactly once. Unlike most of this module's
    idempotent writes, a SECOND consumption is loud, never a silent no-op — re-use of a signing
    approval is the one thing here that must never be treated as "already done, carry on"."""


class ApprovalExpired(Exception):
    """Review N8: an approval past its own ``expires_at`` may never be consumed, even on its
    first and only use — an approval surviving past its window is not "still good"."""


def record_owner_approval(data_dir: Path, intent_id: str, block: Any, expires_at: str, *, now: datetime) -> dict:
    """Binds ``(intent_id, block, expires_at)`` as one recorded, as-yet-unused owner approval."""
    payload = {"intent_id": intent_id, "block": block, "expires_at": expires_at, "used": False,
              "executes": False, "real_capital_usd": 0}
    entry, _ = append_idempotent(data_dir, kind="owner_approval",
                                 key=("owner_approval", intent_id, block, expires_at), payload=payload, now=now)
    return entry


def consume_owner_approval(data_dir: Path, intent_id: str, block: Any, expires_at: str, *, now: datetime) -> dict:
    """Marks the ``(intent_id, block, expires_at)``-bound approval used — EXACTLY once. Relies on
    ``append_entry``'s own lock-protected duplicate-key refusal for the actual atomicity guarantee
    (the ``find_by_key`` precondition check below is only a clearer error message on the common
    path, not the safety net). Review N8: an approval past its OWN ``expires_at`` is refused even
    on its first use — expiry is computed from ``now``, never trusted as "still fresh"."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    existing = find_by_key(data_dir, "owner_approval", ("owner_approval", intent_id, block, expires_at))
    if existing is None:
        raise LedgerError(f"no recorded owner approval for intent_id={intent_id!r} block={block!r} "
                          f"expires_at={expires_at!r} — cannot consume what was never recorded")
    expiry_dt = _parse_iso_utc(expires_at)
    if expiry_dt is not None and now >= expiry_dt:
        raise ApprovalExpired(f"owner approval for intent_id={intent_id!r} block={block!r} expired at "
                              f"{expires_at!r} (now={now.isoformat()})")
    consumed_payload = {"intent_id": intent_id, "block": block, "expires_at": expires_at, "used": True,
                        "executes": False, "real_capital_usd": 0}
    try:
        return append_entry(data_dir, kind="owner_approval_consumed",
                            key=("owner_approval_consumed", intent_id, block, expires_at),
                            payload=consumed_payload, now=now)
    except DuplicateKey as dup:
        raise ApprovalAlreadyUsed(f"owner approval for intent_id={intent_id!r} block={block!r} "
                                  f"expires_at={expires_at!r} was already consumed") from dup
