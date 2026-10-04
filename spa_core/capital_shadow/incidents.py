"""capital_shadow.incidents — sticky, HASH-CHAINED incidents (ADR-556 binding review #14, hardened
per MEDIUM finding #11a/#11b and the second independent re-review's N4/N7).

Separate append-only file (``data/capital_shadow/incidents.jsonl``) from the main hash-chained
ledger — incidents are a SIGNAL, not a decision record, and must remain writable even when the main
ledger's own chain is being investigated (``raise_incident`` always appends onto the physical tail;
it never refuses merely because an EARLIER part of its own history, or the main ledger, is broken —
refusing to log the alert for a break would be the worst possible silent failure).

INCIDENT never auto-clears: :func:`clear_incident` requires a recorded repair with evidence, and —
for the kinds in :data:`OWNER_CONFIRMATION_REQUIRED_KINDS` — an out-of-band OWNER act: this module
mints a one-time nonce into the incident row at ``raise_incident`` time, and the OWNER (never this
runtime) must create ``data/capital_shadow/owner_confirmations/<incident_id>.json`` containing that
exact nonce before ``clear_incident`` will accept it. An arbitrary string is never a substitute —
the token is VERIFIED against what this module itself minted, not merely checked for non-emptiness.

**Finding #11a (fixed):** the previous :func:`read_all` silently ``continue``d past any line that
failed ``json.JSONDecodeError`` — a torn write and "nothing happened" were indistinguishable. Every
row is now hash-chained (``prev_hash``/``entry_hash``) with a sibling anchor file, and a torn line,
a broken chain, a missing/mismatched anchor, or the whole file deleted while its anchors still exist
all raise :class:`IncidentStoreBroken` — never silently "no incidents". :func:`store_state` exposes
this as a plain ``{"state": "OK"|"BROKEN", ...}`` for readers (e.g. ``readiness.py``, Mission
Control) that need a distinct third state rather than catching an exception themselves.

**Finding N7 (fixed):** ``raise_incident(dispatcher=None)`` used to always construct the REAL
``AlertDispatcher()`` with its hard-coded defaults — which point at the REPO'S OWN live
``data/alert_log.json`` / ``data/alert_dispatcher_dedup.json`` regardless of the ``data_dir`` this
call was actually scoped to, so a test or scratch run writing incidents under a ``tmp_path`` was
STILL mutating the real repo's tracked state. Now the real dispatcher is only ever used when
``data_dir`` resolves to the actual production live data dir
(``spa_core.utils.live_paths.live_data_dir()``); every other ``data_dir`` gets a local, no-network
stand-in that appends to ``<data_dir>/capital_shadow/alerts_outbox.jsonl`` instead.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from spa_core.capital_shadow import contract

KINDS = ("ledger_broken", "anchor_broken", "forbidden_method", "quorum_disagreement", "unexpected_position",
        "ledger_repaired", "ledger_tampered")
#: these are the ones a FALSE clear would hurt most (a broken audit trail, money appearing where
#: no intent/runbook accounts for it, a repair nobody reviewed, or tampering) — clearing them needs
#: the out-of-band owner-confirmation-file flow below, never auto-supplied (review #11b / N4-ii/iii).
OWNER_CONFIRMATION_REQUIRED_KINDS = frozenset({"ledger_broken", "anchor_broken", "unexpected_position",
                                               "ledger_repaired", "ledger_tampered"})
GENESIS = "0" * 64
ANCHOR_FILE = "incidents_anchors.jsonl"
#: where the OWNER (never this runtime) places the confirmation file (review N4-ii).
CONFIRMATIONS_SUBDIR = "owner_confirmations"
#: non-production fallback for alerts that would otherwise reach for the real, repo-global
#: AlertDispatcher (review N7).
ALERTS_OUTBOX_FILE = "alerts_outbox.jsonl"


class IncidentStoreBroken(Exception):
    """The incidents store's own hash chain or external anchor disagrees with itself — a torn
    line, a hash mismatch, a missing/mismatched anchor, or the file gone while anchors still
    exist. Never silently treated as "no incidents" (review #11a)."""


def _path(data_dir: Path) -> Path:
    return Path(data_dir) / contract.DATA_SUBDIR / contract.INCIDENTS


def _lock_path(data_dir: Path) -> Path:
    return Path(data_dir) / contract.DATA_SUBDIR / ".incidents.lock"


def _anchors_path(data_dir: Path) -> Path:
    return Path(data_dir) / contract.ANCHORS_SUBDIR / ANCHOR_FILE


def _confirmation_path(data_dir: Path, incident_id: str) -> Path:
    return Path(data_dir) / contract.DATA_SUBDIR / CONFIRMATIONS_SUBDIR / f"{incident_id}.json"


class _Lock:
    def __init__(self, path: Path, timeout_s: float = 5.0):
        self._path = path
        self._timeout_s = timeout_s
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
                    raise TimeoutError(f"could not acquire {self._path}")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
        return False


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _entry_hash(prev_hash: str, seq: int, incident_id: str, kind: str, detail: Any, status: str,
                raised_at: Optional[str], cleared_at: Optional[str], repair_evidence: Optional[str],
                confirmation_token: Optional[str], confirmation_nonce: Optional[str]) -> str:
    payload_ = {"seq": seq, "prev_hash": prev_hash, "incident_id": incident_id, "kind": kind, "detail": detail,
               "status": status, "raised_at": raised_at, "cleared_at": cleared_at,
               "repair_evidence": repair_evidence, "confirmation_token": confirmation_token,
               "confirmation_nonce": confirmation_nonce}
    return hashlib.sha256((prev_hash + _canonical(payload_)).encode("utf-8")).hexdigest()


def _row_entry_hash(row: dict) -> str:
    return _entry_hash(row.get("prev_hash"), row.get("seq"), row.get("incident_id"), row.get("kind"),
                       row.get("detail"), row.get("status"), row.get("raised_at"), row.get("cleared_at"),
                       row.get("repair_evidence"), row.get("confirmation_token"), row.get("confirmation_nonce"))


def _append_line(data_dir: Path, row: dict) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (_canonical(row) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def _append_anchor(data_dir: Path, seq: int, entry_hash: str) -> None:
    row = {"seq": seq, "entry_hash": entry_hash}
    path = _anchors_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (_canonical(row) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_anchors(data_dir: Path) -> List[dict]:
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


def _raw_lines(data_dir: Path) -> List[str]:
    path = _path(data_dir)
    if not path.exists():
        return []
    return [ln for ln in path.read_text().splitlines() if ln.strip()]


def _tail_raw(data_dir: Path) -> Optional[dict]:
    """The last PARSEABLE row, read WITHOUT verifying the chain — used only to extend the
    physical file. Appending must never refuse merely because an earlier part of the chain broke;
    that is exactly the situation this store exists to report (verification, via :func:`read_all`,
    still catches and names the historical break — it just does not block new appends)."""
    for raw in reversed(_raw_lines(data_dir)):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            return row
    return None


def verify_chain(data_dir: Path) -> dict:
    """Recomputes every hash and cross-checks the sibling anchor file. Returns
    ``{"ok": bool, "reason": str|None, "entries": int, "break_at": int|None}``."""
    path = _path(data_dir)
    anchors = _read_anchors(data_dir)
    if not path.exists():
        if anchors:
            return {"ok": False, "reason": "file_deleted_with_anchors", "entries": 0, "break_at": None}
        return {"ok": True, "reason": None, "entries": 0, "break_at": None}

    rows: List[dict] = []
    raw_lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    for i, raw in enumerate(raw_lines, start=1):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "reason": "torn_line", "entries": len(rows), "break_at": i}
        if not isinstance(parsed, dict):
            return {"ok": False, "reason": "torn_line", "entries": len(rows), "break_at": i}
        rows.append(parsed)

    anchors_by_seq = {a.get("seq"): a for a in anchors}
    prev = GENESIS
    for idx, row in enumerate(rows, start=1):
        if row.get("seq") != idx or row.get("prev_hash") != prev:
            return {"ok": False, "reason": "chain", "entries": len(rows), "break_at": idx}
        if _row_entry_hash(row) != row.get("entry_hash"):
            return {"ok": False, "reason": "chain", "entries": len(rows), "break_at": idx}
        anchor = anchors_by_seq.get(idx)
        if anchor is None:
            return {"ok": False, "reason": "anchor_missing", "entries": len(rows), "break_at": idx}
        if anchor.get("entry_hash") != row.get("entry_hash"):
            return {"ok": False, "reason": "anchor_mismatch", "entries": len(rows), "break_at": idx}
        prev = row["entry_hash"]
    beyond = [a.get("seq") for a in anchors if isinstance(a.get("seq"), int) and a.get("seq") > len(rows)]
    if beyond:
        return {"ok": False, "reason": "ledger_truncated", "entries": len(rows), "break_at": min(beyond)}
    return {"ok": True, "reason": None, "entries": len(rows), "break_at": None}


def store_state(data_dir: Path) -> dict:
    """``{"state": "OK"|"BROKEN", "reason": str|None}`` — the plain, exception-free form of
    :func:`verify_chain` for readers (``readiness.py``'s ``kill_switch_clear``/incident gates,
    Mission Control) that need BROKEN to be a distinct, displayable state rather than something
    they have to catch."""
    verdict = verify_chain(data_dir)
    if verdict["ok"]:
        return {"state": "OK", "reason": None}
    return {"state": "BROKEN",
           "reason": f"{verdict['reason']} (break_at={verdict['break_at']}, entries={verdict['entries']})"}


def read_all(data_dir: Path) -> List[dict]:
    """Verified read: a torn line, a hash-chain break, a missing/mismatched anchor, or the file
    being gone while anchors exist all raise :class:`IncidentStoreBroken` — never silently return
    fewer rows than actually exist (review #11a)."""
    verdict = verify_chain(data_dir)
    if not verdict["ok"]:
        raise IncidentStoreBroken(f"incidents store is BROKEN (reason={verdict['reason']}, "
                                  f"break_at={verdict['break_at']}, entries={verdict['entries']})")
    return [json.loads(ln) for ln in _raw_lines(data_dir)]


def open_incidents(data_dir: Path) -> List[dict]:
    """The latest row per ``incident_id`` where ``status`` is still ``OPEN``. Raises
    :class:`IncidentStoreBroken` (via :func:`read_all`) rather than silently reporting zero open
    incidents on a torn/tampered store — existing callers (``readiness.py``, ``read.py``) already
    wrap this in ``try/except Exception`` and surface an UNKNOWN/unreadable gate, never a clean
    pass."""
    latest: dict = {}
    for row in read_all(data_dir):
        iid = row.get("incident_id")
        if iid is None:
            continue
        if iid not in latest or row.get("seq", 0) >= latest[iid].get("seq", 0):
            latest[iid] = row
    return [r for r in latest.values() if r.get("status") == "OPEN"]


def read_owner_confirmation_nonce(data_dir: Path, incident_id: str) -> Optional[str]:
    """Reads the OWNER-CREATED confirmation file
    (``data/capital_shadow/owner_confirmations/<incident_id>.json``). The runtime NEVER writes
    this file — only a human, out-of-band, creates it, naming the nonce :func:`raise_incident`
    itself minted. Missing file, unparseable JSON, or no ``nonce`` field ⇒ ``None`` (never "assume
    confirmed"; review N4-ii)."""
    path = _confirmation_path(data_dir, incident_id)
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    nonce = doc.get("nonce") if isinstance(doc, dict) else None
    return nonce if isinstance(nonce, str) and nonce else None


class _OutboxDispatcher:
    """Review N7: the stand-in used for every NON-production ``data_dir`` — never touches the
    real alert pipeline (``AlertDispatcher``'s hard-coded repo-global log/dedup paths, or the
    Telegram digest queue it routes through). Appends one line per alert to
    ``<data_dir>/capital_shadow/alerts_outbox.jsonl`` instead."""

    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)

    def create_alert(self, level: Any, title: str, message: str, adapter_id: Optional[str] = None) -> dict:
        return {"level": getattr(level, "name", str(level)), "title": title, "message": message,
               "adapter_id": adapter_id}

    def dispatch(self, alert: dict) -> dict:
        path = self._data_dir / contract.DATA_SUBDIR / ALERTS_OUTBOX_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (_canonical({**alert, "ts": time.time()}) + "\n").encode("utf-8")
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        return {"channels_succeeded": ["outbox"]}


def _is_production_data_dir(data_dir: Path) -> bool:
    try:
        from spa_core.utils.live_paths import live_data_dir
        return Path(data_dir).resolve() == live_data_dir().resolve()
    except Exception:  # noqa: BLE001 — any uncertainty here must land on "not production"
        return False


def _default_dispatcher(data_dir: Path) -> Any:
    """``dispatcher=None`` used to always reach for the REAL ``AlertDispatcher()`` — which, through
    its hard-coded defaults and the retired Telegram push's digest-queue fallback, writes into the
    repo's own live ``data/`` regardless of what ``data_dir`` this call was scoped to. Now the real
    dispatcher is used ONLY when ``data_dir`` IS the actual production live data dir; every other
    caller (tests, scratch runs, another agent's sandbox) gets :class:`_OutboxDispatcher` bound to
    ITS OWN ``data_dir`` instead (review N7)."""
    if _is_production_data_dir(data_dir):
        try:
            from spa_core.alerts.alert_dispatcher import AlertDispatcher
            return AlertDispatcher()
        except ImportError:
            return None
    return _OutboxDispatcher(data_dir)


def raise_incident(data_dir: Path, kind: str, detail: str, *, now: Optional[datetime] = None,
                    dispatcher: Any = None) -> dict:
    """Appends an OPEN, hash-chained incident row (+ its sibling anchor) and sends an owner alert.
    ``dispatcher`` is injected for tests/callers that want a specific one; ``None`` resolves via
    :func:`_default_dispatcher` (review N7 — never the real dispatcher for a non-production
    ``data_dir``). Mints a one-time ``confirmation_nonce`` into the row — the only credential
    :func:`clear_incident` will ever accept for a kind in :data:`OWNER_CONFIRMATION_REQUIRED_KINDS`.
    Appends onto the physical tail regardless of whether the STORED chain currently verifies — see
    the module docstring for why refusing here would be the worst possible silent failure."""
    if kind not in KINDS:
        raise ValueError(f"unknown incident kind {kind!r}; must be one of {KINDS}")
    now = now or datetime.now(timezone.utc)
    confirmation_nonce = uuid.uuid4().hex
    with _Lock(_lock_path(data_dir)):
        tail = _tail_raw(data_dir)
        prev_hash = tail["entry_hash"] if tail else GENESIS
        seq = (tail["seq"] + 1) if tail else 1
        incident_id = str(uuid.uuid4())
        raised_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        entry_hash = _entry_hash(prev_hash, seq, incident_id, kind, detail, "OPEN", raised_at, None, None, None,
                                 confirmation_nonce)
        row = {"seq": seq, "prev_hash": prev_hash, "entry_hash": entry_hash, "incident_id": incident_id,
              "kind": kind, "detail": detail, "status": "OPEN", "raised_at": raised_at, "cleared_at": None,
              "repair_evidence": None, "confirmation_token": None, "confirmation_nonce": confirmation_nonce}
        _append_line(data_dir, row)
        _append_anchor(data_dir, seq, entry_hash)

    if dispatcher is None:
        dispatcher = _default_dispatcher(data_dir)
    if dispatcher is not None:
        try:
            try:
                from spa_core.alerts.alert_dispatcher import AlertLevel
                level = AlertLevel.CRITICAL
            except ImportError:
                level = "CRITICAL"
            alert = dispatcher.create_alert(level, f"capital_shadow INCIDENT: {kind}", detail,
                                            adapter_id="capital_shadow")
            dispatcher.dispatch(alert)
        except Exception:
            pass  # the alert path must never crash incident recording itself (fail-closed on THIS write)
    return row


def clear_incident(data_dir: Path, incident_id: str, repair_evidence: str, *,
                   now: Optional[datetime] = None) -> dict:
    """Clearing requires a recorded repair with evidence. For ``kind`` in
    :data:`OWNER_CONFIRMATION_REQUIRED_KINDS`, this ALSO reads
    ``data/capital_shadow/owner_confirmations/<incident_id>.json`` (an OUT-OF-BAND OWNER act — this
    runtime never writes that file) and refuses unless its ``nonce`` field EXACTLY matches the one
    ``raise_incident`` minted for this incident. An arbitrary string can never satisfy this: there
    is no caller-supplied token to simply pass through anymore (review #11b / N4-ii)."""
    if not repair_evidence:
        raise ValueError("clear_incident requires non-empty repair_evidence")
    now = now or datetime.now(timezone.utc)
    with _Lock(_lock_path(data_dir)):
        rows = read_all(data_dir)
        found = None
        for r in rows:
            if r.get("incident_id") == incident_id and r.get("status") == "OPEN":
                found = r
        if found is None:
            raise ValueError(f"no OPEN incident {incident_id!r} to clear")
        kind = found.get("kind")
        confirmation_token = None
        if kind in OWNER_CONFIRMATION_REQUIRED_KINDS:
            stored_nonce = found.get("confirmation_nonce")
            supplied_nonce = read_owner_confirmation_nonce(data_dir, incident_id)
            if not stored_nonce or not supplied_nonce or supplied_nonce != stored_nonce:
                raise ValueError(
                    f"clearing a {kind!r} incident requires the owner's confirmation file "
                    f"(data/capital_shadow/owner_confirmations/{incident_id}.json) to contain the EXACT nonce "
                    f"recorded at raise time — missing, unreadable, or mismatched. This is an OUT-OF-BAND "
                    f"OWNER act; the runtime never writes this file itself (review #11b / N4-ii)")
            confirmation_token = supplied_nonce
        tail = _tail_raw(data_dir)
        prev_hash = tail["entry_hash"] if tail else GENESIS
        seq = (tail["seq"] + 1) if tail else 1
        cleared_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        entry_hash = _entry_hash(prev_hash, seq, incident_id, kind, found.get("detail"), "CLEARED",
                                 found.get("raised_at"), cleared_at, repair_evidence, confirmation_token,
                                 found.get("confirmation_nonce"))
        row = {"seq": seq, "prev_hash": prev_hash, "entry_hash": entry_hash, "incident_id": incident_id,
              "kind": kind, "detail": found.get("detail"), "status": "CLEARED", "raised_at": found.get("raised_at"),
              "cleared_at": cleared_at, "repair_evidence": repair_evidence,
              "confirmation_token": confirmation_token, "confirmation_nonce": found.get("confirmation_nonce")}
        _append_line(data_dir, row)
        _append_anchor(data_dir, seq, entry_hash)
    return row
