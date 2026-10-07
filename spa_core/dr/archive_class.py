"""
spa_core/dr/archive_class.py — WHICH KIND of backup an archive is, proven, never guessed.

WHY THIS EXISTS (ARB-CONTINUITY-01 Wave B, ADR-611)
---------------------------------------------------
``data/backups/`` holds two archive classes under ONE prefix (see ``archive_names.py``):

    spa_state_2026-10-06.tar.gz         FULL      scripts/daily_backup.py  (~765 members:
                                                  all state + append-only ledgers + sqlite
                                                  evidence/market DBs + CIO replay snapshots)
    spa_state_20261006T051505Z.tar.gz   CRITICAL  tier1 dr_backup.py       (~29 members:
                                                  the DR-critical set, NO ledgers)

``offsite_copy`` took "the newest archive" across both. Measured 2026-10-07: a manual run at
01:21 local shipped the 05:15Z CRITICAL archive to iCloud while the FULL archive of the same
day — the only one carrying the ledgers — stayed on the Mac. Newer is not the question; WHICH
CLASS is. The caller now declares the class it needs, and this module proves it.

PROOF = two independent witnesses that must AGREE
-------------------------------------------------
1. the NAME format (the producer's own strftime — ``archive_names.parse_archive_name``);
2. the embedded ``backup_manifest.json`` ``schema`` (``spa_daily_backup/*`` or
   ``spa_dr_backup/*``) — written by the producer inside the tar.

Either witness absent or the two disagreeing ⇒ the class is UNPROVEN and the archive is
refused (fail-CLOSED, inv. #2). A refused newest archive is NOT replaced by an older one:
silently shipping yesterday's backup as tonight's is exactly the dishonesty this replaces.

No renaming, no migration: historical names keep their meaning; the proof reads what is
already there. stdlib-only · read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.dr import archive_names

CLASS_FULL = "full"
CLASS_CRITICAL = "critical"
CLASSES = (CLASS_FULL, CLASS_CRITICAL)

MANIFEST_NAME = "backup_manifest.json"

#: class → (name series, manifest-schema prefix). One row per producer.
_WITNESSES = {
    CLASS_FULL: (archive_names.SERIES_DAILY, "spa_daily_backup/"),
    CLASS_CRITICAL: (archive_names.SERIES_DR, "spa_dr_backup/"),
}

ARCHIVE_GLOB = archive_names.ARCHIVE_PREFIX + "*" + archive_names.ARCHIVE_SUFFIX

#: The offsite copy is a daily job — a status older than 2 days means it skipped a day.
#: ONE source: ``resilience_status.OFFSITE_STALE_DAYS`` is this constant.
OFFSITE_STALE_DAYS = 2.0


def _class_for_series(series: str) -> Optional[str]:
    for cls, (s, _p) in _WITNESSES.items():
        if s == series:
            return cls
    return None


def _class_for_schema(schema: Any) -> Optional[str]:
    if not isinstance(schema, str):
        return None
    for cls, (_s, prefix) in _WITNESSES.items():
        if schema.startswith(prefix):
            return cls
    return None


def read_manifest(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """``(manifest, None)`` or ``(None, reason)``. Streams the tar and stops at the manifest
    (both producers write it FIRST, so this normally reads one member)."""
    try:
        with tarfile.open(str(path), "r|gz") as tar:
            for member in tar:
                if member.name == MANIFEST_NAME and member.isfile():
                    f = tar.extractfile(member)
                    if f is None:
                        return None, "manifest_unreadable"
                    doc = json.loads(f.read().decode("utf-8"))
                    return (doc, None) if isinstance(doc, dict) else (None, "manifest_not_object")
    except (OSError, tarfile.TarError, EOFError) as exc:
        return None, f"archive_unreadable:{type(exc).__name__}"
    except (ValueError, UnicodeDecodeError):
        return None, "manifest_not_json"
    return None, "manifest_missing"


def prove_class(path: Path) -> Dict[str, Any]:
    """``{"class": "full"|"critical"|None, "name_class", "manifest_class", "schema", "reason"}``.

    ``class`` is set ONLY when both witnesses exist and agree.
    """
    series, _instant = archive_names.parse_archive_name(str(path))
    name_cls = _class_for_series(series)
    manifest, why = read_manifest(Path(path))
    schema = manifest.get("schema") if manifest else None
    manifest_cls = _class_for_schema(schema)
    out: Dict[str, Any] = {"class": None, "name_class": name_cls, "manifest_class": manifest_cls,
                           "schema": schema, "reason": None}
    if name_cls is None:
        out["reason"] = "name_format_unrecognised"
    elif manifest is None:
        out["reason"] = why
    elif manifest_cls is None:
        out["reason"] = f"manifest_schema_unrecognised:{schema!r}"
    elif manifest_cls != name_cls:
        out["reason"] = f"witnesses_disagree:name={name_cls},manifest={manifest_cls}"
    else:
        out["class"] = name_cls
    return out


def candidates(backup_dir: Path, cls: str) -> List[Path]:
    """Archives whose NAME belongs to *cls*, newest first. Other classes never appear."""
    if cls not in _WITNESSES:
        raise ValueError(f"unknown archive class {cls!r} (expected one of {CLASSES})")
    series = _WITNESSES[cls][0]
    if not Path(backup_dir).is_dir():
        return []
    mine = [p for p in Path(backup_dir).glob(ARCHIVE_GLOB)
            # a symlink is not a backup this host wrote — it can point anywhere (ADR-611 review)
            if p.is_file() and not p.is_symlink()
            and archive_names.archive_series(p.name) == series]
    return archive_names.newest_first(mine)


def select(backup_dir: Path, cls: str) -> Tuple[Optional[Path], Dict[str, Any]]:
    """The newest archive OF CLASS *cls*, proven — or ``(None, proof-with-reason)``.

    Never compares across classes; never falls back to an older archive when the newest
    one cannot be proven (that would ship stale data under a fresh-looking status).
    """
    found = candidates(backup_dir, cls)
    if not found:
        return None, {"class": None, "reason": f"no_{cls}_archive"}
    newest = found[0]
    proof = prove_class(newest)
    if proof["class"] != cls:
        proof.setdefault("reason", None)
        if proof["class"] is not None:  # pragma: no cover — candidates() filters by name
            proof["reason"] = f"class_mismatch:{proof['class']}"
        return None, dict(proof, archive=newest.name)
    return newest, dict(proof, archive=newest.name)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


#: tolerated clock skew for a status stamp (same 10-min allowance as the cockpit readers)
FUTURE_SKEW_S = 600


def full_offsite_proven(doc: Any, now: Optional[datetime] = None,
                        stale_days: float = OFFSITE_STALE_DAYS) -> Tuple[Optional[bool], Optional[str]]:
    """ONE reading of ``data/dr_offsite_status.json`` for every consumer (resilience rollup,
    Mission Control, Company Truth) — ``(True, None)`` only when the copy is sha-verified,
    proven to be the FULL class, and that FULL archive passed ``full_archive_verify``.

    Also ``(False, "stale: …")`` when ``last_offsite_ts`` is older than ``OFFSITE_STALE_DAYS``
    (``now`` injectable) — every consumer applies the SAME age bound, not only the rollup.

    ``(None, reason)`` = not measured (no readable status); ``(False, reason)`` = measured and
    not proven. A pre-ADR-611 status (no ``archive_class``) is NOT proven: it may well have
    carried the 29-member CRITICAL archive — exactly the defect this replaces.
    """
    if not isinstance(doc, dict):
        return None, "offsite status not readable"
    if doc.get("archive_class") != CLASS_FULL:
        return False, f"offsite copy not proven to be the FULL archive (class={doc.get('archive_class')!r})"
    if doc.get("verified") is not True:
        return False, "offsite copy not verified"
    if doc.get("complete") is not True:
        return False, ("FULL archive incomplete" if doc.get("complete") is False
                       else "FULL archive completeness not measured")
    # A proof has an age: yesterday's complete copy is not proof the job still runs.
    ts = _parse_ts(doc.get("last_offsite_ts"))
    if ts is None:
        return False, "offsite timestamp not readable"
    now = now or datetime.now(timezone.utc)
    age_days = (now - ts).total_seconds() / 86400.0
    if age_days < -FUTURE_SKEW_S / 86400.0:
        # a proof from the future is not a proof (clock skew or a forged stamp) — fail-closed
        return False, f"offsite timestamp is {-age_days * 24:.1f} h in the future — not trusted"
    if age_days > stale_days:
        return False, f"stale: last FULL offsite copy {age_days:.1f} days old (> {stale_days:g})"
    return True, None


__all__ = ["CLASS_FULL", "CLASS_CRITICAL", "CLASSES", "read_manifest", "prove_class",
           "candidates", "select", "full_offsite_proven"]

if __name__ == "__main__":  # pragma: no cover — manual inspection aid
    import sys
    for a in sys.argv[1:]:
        print(os.path.basename(a), prove_class(Path(a)))
