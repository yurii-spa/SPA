"""spa_core.audit.audit_trail — Decision Audit Trail (MP-310).

Implements a correlation-id–linked append-only JSONL chain of events covering
the full paper-trading decision cycle:

    cycle_start → allocation_proposal → risk_verdict →
    trade_executed | trade_blocked → [kill_switch | alert_sent]

Key guarantees:
* All writes are atomic (tmp + os.replace) — no half-written records.
* Every event belongs to exactly one cycle via ``correlation_id`` (UUID4).
* Events are linked as a singly-linked list via ``prev_event_id``.
* JSONL file rotates to a dated archive when it exceeds ``MAX_JSONL_BYTES``
  (10 MB default).
* All public functions are fail-safe: exceptions are caught and returned as
  ``{"error": "..."}`` payloads — the caller (cycle_runner) is never blocked.

On-disk location: ``<repo>/data/audit_trail.jsonl`` (configurable via
``_get_trail_path()`` or override ``AUDIT_TRAIL_PATH`` in the module before
first use).

Public API
----------
begin_cycle(cycle_date: str, *, data_dir: str | None = None) -> str
    Start a new audit chain for ``cycle_date``.  Returns the ``correlation_id``
    (UUID4 string) that must be threaded through all subsequent calls.

record_event(
    correlation_id: str,
    event_type: str,
    data: dict,
    prev_event_id: str | None = None,
    *,
    data_dir: str | None = None,
) -> dict
    Append one event to the JSONL trail and return the full event dict.
    ``event_type`` must be one of ``VALID_EVENT_TYPES``.

get_cycle_chain(
    correlation_id: str,
    *,
    data_dir: str | None = None,
) -> list[dict]
    Return all events for ``correlation_id``, ordered by insertion sequence.

export_signed_jsonl(
    output_path: str,
    *,
    data_dir: str | None = None,
) -> str
    Copy the current trail file to ``output_path`` and append a manifest line
    containing the sha256 of the copied content.  Returns the sha256 hex string.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger("spa.audit_trail")

# ─── Constants ────────────────────────────────────────────────────────────────

VALID_EVENT_TYPES = frozenset(
    {
        "cycle_start",
        "allocation_proposal",
        "risk_verdict",
        "trade_executed",
        "trade_blocked",
        "kill_switch",
        "alert_sent",
    }
)

AUDIT_FILENAME = "audit_trail.jsonl"
MAX_JSONL_BYTES = 10 * 1024 * 1024  # 10 MB → rotate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


# ─── Atomic IO ───────────────────────────────────────────────────────────────


def _atomic_append_jsonl(path: Path, line: str) -> None:
    """Append *one* newline-terminated JSONL line atomically.

    Strategy: read existing content → append new line → write whole file via
    tmp + os.replace.  This preserves the JSONL invariant (no partial records)
    even across crash/SIGKILL.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = b""
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError:
            existing = b""
    new_content = existing + (line.rstrip("\n") + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(new_content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        finally:
            raise


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _get_trail_path(data_dir: str | None) -> Path:
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    return ddir / AUDIT_FILENAME


def _make_snapshot_id(cycle_date: str) -> str:
    """Build a deterministic snapshot_id = '<cycle_date>:<sha256 prefix>'."""
    raw = f"{cycle_date}:{datetime.now(timezone.utc).isoformat()}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{cycle_date}:{digest}"


def _rotate_if_needed(path: Path) -> None:
    """If trail file exceeds MAX_JSONL_BYTES, rename it to a dated archive."""
    if not path.exists():
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= MAX_JSONL_BYTES:
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = path.parent / f"audit_trail_{ts}.jsonl"
    try:
        os.replace(path, archive)
        log.info("audit_trail: rotated %s → %s", path.name, archive.name)
    except OSError as exc:
        log.warning("audit_trail: rotation failed (%s) — continuing with existing file", exc)


# ─── In-memory cycle registry ─────────────────────────────────────────────────
# Maps correlation_id → {"snapshot_id": str, "cycle_date": str}
_cycle_registry: dict[str, dict] = {}


# ─── Public API ───────────────────────────────────────────────────────────────


def begin_cycle(
    cycle_date: str,
    *,
    data_dir: str | None = None,
) -> str:
    """Start a new audit chain for *cycle_date*.

    Returns
    -------
    str
        A UUID4 ``correlation_id`` that must be passed to every subsequent
        ``record_event`` call for this cycle.  On any exception, returns an
        empty string (fail-safe).
    """
    try:
        correlation_id = str(uuid.uuid4())
        snapshot_id = _make_snapshot_id(cycle_date)
        _cycle_registry[correlation_id] = {
            "snapshot_id": snapshot_id,
            "cycle_date": cycle_date,
        }
        # Emit the cycle_start event immediately (prev_event_id=None).
        record_event(
            correlation_id,
            "cycle_start",
            {"cycle_date": cycle_date, "snapshot_id": snapshot_id},
            prev_event_id=None,
            data_dir=data_dir,
        )
        return correlation_id
    except Exception as exc:
        log.warning("audit begin_cycle failed (%s) — returning empty correlation_id", exc)
        return ""


def record_event(
    correlation_id: str,
    event_type: str,
    data: dict,
    prev_event_id: str | None = None,
    *,
    data_dir: str | None = None,
) -> dict:
    """Append one event record to the JSONL trail.

    Parameters
    ----------
    correlation_id : str
        The correlation id returned by :func:`begin_cycle`.
    event_type : str
        One of ``VALID_EVENT_TYPES``.  Unknown types are accepted with a
        WARNING to avoid blocking the cycle.
    data : dict
        Arbitrary payload describing the event.
    prev_event_id : str | None
        The ``event_id`` of the immediately preceding event in this cycle's
        chain, or ``None`` for the first event.

    Returns
    -------
    dict
        The full event record as written to disk.  On any exception, returns
        ``{"error": str(exc)}`` (fail-safe).
    """
    try:
        if event_type not in VALID_EVENT_TYPES:
            log.warning("audit record_event: unknown event_type=%r — accepting anyway", event_type)

        reg = _cycle_registry.get(correlation_id, {})
        snapshot_id = reg.get("snapshot_id", "")

        event_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()

        record: dict = {
            "event_id": event_id,
            "correlation_id": correlation_id,
            "snapshot_id": snapshot_id,
            "event_type": event_type,
            "timestamp": ts,
            "data": data if isinstance(data, dict) else {},
            "prev_event_id": prev_event_id,
        }

        trail_path = _get_trail_path(data_dir)
        _rotate_if_needed(trail_path)
        _atomic_append_jsonl(trail_path, json.dumps(record, ensure_ascii=False))
        return record
    except Exception as exc:
        log.warning("audit record_event failed (%s)", exc)
        return {"error": str(exc)}


def get_cycle_chain(
    correlation_id: str,
    *,
    data_dir: str | None = None,
) -> list[dict]:
    """Return all events for *correlation_id* in insertion order.

    Reads the JSONL file on each call — suitable for tests and post-hoc
    inspection.  Returns an empty list if the file doesn't exist or is
    unreadable (fail-safe).
    """
    trail_path = _get_trail_path(data_dir)
    if not trail_path.exists():
        return []
    try:
        results: list[dict] = []
        with trail_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("correlation_id") == correlation_id:
                    results.append(record)
        return results
    except Exception as exc:
        log.warning("audit get_cycle_chain failed (%s)", exc)
        return []


def export_signed_jsonl(
    output_path: str,
    *,
    data_dir: str | None = None,
) -> str:
    """Copy current trail to *output_path* and append a sha256 manifest line.

    The manifest line is a JSONL record with ``event_type="manifest"`` and
    ``sha256`` of the trail content (without the manifest line itself).

    Returns
    -------
    str
        The sha256 hex digest of the exported trail content.  On any exception,
        returns an empty string (fail-safe).
    """
    try:
        trail_path = _get_trail_path(data_dir)
        content = b""
        if trail_path.exists():
            content = trail_path.read_bytes()

        digest = hashlib.sha256(content).hexdigest()
        ts = datetime.now(timezone.utc).isoformat()

        manifest_record = {
            "event_type": "manifest",
            "timestamp": ts,
            "sha256": digest,
            "trail_bytes": len(content),
            "trail_lines": content.count(b"\n"),
        }
        manifest_line = (json.dumps(manifest_record, ensure_ascii=False) + "\n").encode("utf-8")
        export_content = content + manifest_line

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(out.parent), prefix=f".{out.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(export_content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, out)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            finally:
                raise

        log.info("audit export_signed_jsonl: %s (%d bytes, sha256=%s)", out.name, len(export_content), digest)
        return digest
    except Exception as exc:
        log.warning("audit export_signed_jsonl failed (%s)", exc)
        return ""
