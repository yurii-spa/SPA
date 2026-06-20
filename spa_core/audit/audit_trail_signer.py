"""spa_core.audit.audit_trail_signer — Append-only audit trail with SHA-256 hash chain.

FIX-P2 (audit trail integrity):

The existing ``audit_trail.jsonl`` is a plain JSONL file — any record can be
silently edited or deleted without leaving a trace.  This module wraps it with
a cryptographic hash chain so any tampering is immediately detectable.

Hash chain design
-----------------
Each record written by this module contains a ``chain_hash`` field::

    chain_hash = SHA256(prev_chain_hash + canonical_json(record_without_chain_hash))

The very first record uses ``prev_chain_hash = "0" * 64`` (genesis sentinel).

The chain is stored in a separate file (``data/audit_chain.jsonl``) so it does
not interfere with the existing ``audit_trail.jsonl`` written by cycle_runner.

Public API
----------
append(record: dict, *, data_dir=None) -> dict
    Add ``chain_hash`` to *record* and atomically append it to the chain file.
    Returns the full record (with ``chain_hash``).

verify_chain(filepath=None, *, data_dir=None) -> bool
    Read every record in the chain file and verify the hash linkage.
    Returns ``True`` if the chain is intact.
    Raises ``AuditChainTamperedError`` if any record is inconsistent.

read_chain(filepath=None, *, data_dir=None) -> list[dict]
    Return all records from the chain file in insertion order.

Constraints
-----------
- Pure stdlib: ``hashlib``, ``json``, ``os``, ``pathlib``, ``tempfile``
- Atomic writes: tmp + os.replace (never partial records on crash)
- LLM FORBIDDEN in this module (SPA security policy)
- NEVER modifies risk / execution / allocator / cycle_runner state
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.audit_trail_signer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHAIN_FILENAME = "audit_chain.jsonl"
GENESIS_HASH = "0" * 64  # sentinel for the first record

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuditChainTamperedError(Exception):
    """Raised when ``verify_chain`` detects a broken hash linkage.

    Attributes
    ----------
    record_index : int
        0-based index of the first inconsistent record.
    expected_hash : str
        The hash that the record *should* have.
    actual_hash : str
        The ``chain_hash`` value found in the record.
    """

    def __init__(
        self,
        message: str,
        record_index: int = -1,
        expected_hash: str = "",
        actual_hash: str = "",
    ) -> None:
        super().__init__(message)
        self.record_index = record_index
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_chain_path(data_dir: str | Path | None = None) -> Path:
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    return ddir / CHAIN_FILENAME


def _canonical_json(obj: dict) -> str:
    """Produce a deterministic, compact JSON string with sorted keys."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _compute_chain_hash(prev_hash: str, record_without_chain_hash: dict) -> str:
    """SHA-256(prev_hash + canonical_json(record_without_chain_hash))."""
    payload = prev_hash + _canonical_json(record_without_chain_hash)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _atomic_append_jsonl(path: Path, line: str) -> None:
    """Atomically append one JSONL line (read entire file → append → os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = b""
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError:
            existing = b""
    new_content = existing + (line.rstrip("\n") + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
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


def _read_last_chain_hash(path: Path) -> str:
    """Return the ``chain_hash`` of the last record, or GENESIS_HASH if empty."""
    if not path.exists():
        return GENESIS_HASH
    try:
        last_line: str | None = None
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if raw:
                    last_line = raw
        if last_line is None:
            return GENESIS_HASH
        record = json.loads(last_line)
        return str(record.get("chain_hash") or GENESIS_HASH)
    except (OSError, json.JSONDecodeError, KeyError):
        return GENESIS_HASH


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def append(
    record: dict[str, Any],
    *,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Append *record* to the hash chain and return the full record with ``chain_hash``.

    Parameters
    ----------
    record : dict
        Arbitrary payload to append.  Must be JSON-serialisable.
        Must NOT already contain a ``chain_hash`` key (it will be added here).

    Returns
    -------
    dict
        The record as written, including the ``chain_hash`` and
        ``appended_at`` (UTC ISO-8601) fields.

    Never raises (fail-safe): on any internal error, logs a WARNING and
    returns ``{"error": str(exc)}``.
    """
    try:
        chain_path = _get_chain_path(data_dir)

        # Strip any existing chain_hash so the hash is computed on clean data
        clean = {k: v for k, v in record.items() if k != "chain_hash"}
        if "appended_at" not in clean:
            clean["appended_at"] = datetime.now(timezone.utc).isoformat()

        prev_hash = _read_last_chain_hash(chain_path)
        chain_hash = _compute_chain_hash(prev_hash, clean)

        full_record: dict[str, Any] = {**clean, "chain_hash": chain_hash}
        _atomic_append_jsonl(chain_path, _canonical_json(full_record))
        log.debug("audit_chain: appended record chain_hash=%s…", chain_hash[:12])
        return full_record
    except Exception as exc:
        log.warning("audit_trail_signer.append failed (%s)", exc)
        return {"error": str(exc)}


def verify_chain(
    filepath: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
) -> bool:
    """Verify the integrity of the hash chain.

    Parameters
    ----------
    filepath : path-like, optional
        Explicit path to the chain file.  If omitted, uses the default
        location derived from *data_dir*.

    Returns
    -------
    bool
        ``True`` if the chain is intact (all hashes verify correctly).

    Raises
    ------
    AuditChainTamperedError
        If any record's ``chain_hash`` does not match the expected value.
        The exception carries ``record_index``, ``expected_hash``, and
        ``actual_hash`` for forensic inspection.
    """
    path = Path(filepath) if filepath else _get_chain_path(data_dir)

    if not path.exists():
        log.info("audit_chain: no chain file at %s — nothing to verify", path)
        return True

    prev_hash = GENESIS_HASH
    records = read_chain(filepath=path)

    for idx, record in enumerate(records):
        actual_hash = record.get("chain_hash", "")
        # Re-compute over the record without the chain_hash field
        clean = {k: v for k, v in record.items() if k != "chain_hash"}
        expected_hash = _compute_chain_hash(prev_hash, clean)

        if actual_hash != expected_hash:
            msg = (
                f"audit chain tampered at record {idx}: "
                f"expected {expected_hash[:16]}… got {actual_hash[:16]}…"
            )
            log.error("AuditChainTamperedError: %s", msg)
            raise AuditChainTamperedError(
                msg,
                record_index=idx,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
            )
        prev_hash = actual_hash

    log.info("audit_chain: verified %d records — chain intact", len(records))
    return True


def read_chain(
    filepath: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return all records from the chain file in insertion order.

    Returns an empty list if the file does not exist or is unreadable.
    Malformed JSONL lines are skipped with a WARNING (fail-safe).
    """
    path = Path(filepath) if filepath else _get_chain_path(data_dir)
    if not path.exists():
        return []
    results: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for i, raw in enumerate(fh):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    results.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    log.warning(
                        "audit_chain: skipping malformed JSONL line %d: %s", i, exc
                    )
    except OSError as exc:
        log.warning("audit_chain: could not read chain file: %s", exc)
    return results
