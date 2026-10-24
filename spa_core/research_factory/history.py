"""spa_core/research_factory/history.py — the COMPACTION record of a candidate's transition
history, and the single merged reader of that history (ADR-795, order G794 §1).

Why this record exists — the measured reason, not a design preference.

The ledger ``data/research_factory/ledger.jsonl`` grows 3.907 MB/day (measured 23.10, ADR-794)
and age truncation has **no safe window at all** (ADR-793: even 14 days out of 18.74 change
25.29 % of the answer). ADR-794 then priced the next named cure — periodically RE-RECORDING the
newest description of each live candidate — and closed it too: one ``candidate_snapshot`` per
candidate per day costs +1.218 MB/day and moves the answer's dependency on rows older than a day
only 33.35 % → 19.05 %; adding ``evidence_bundle`` and ``admission_decision`` reaches 3.72 % and
still opens no window.

The whole remainder is ONE class, and it cannot be cured by re-recording: the ACCUMULATING reason
lists. ``read._rejection_reasons`` walks EVERY ``transition`` row of a candidate whose
``to_state`` is a hold state, so ``latest.candidates[].reasons`` and ``latest.rejections[].reasons``
list the reasons of a candidate's whole life. Repeating those rows does not refresh them — it
APPENDS to them: the same measurement showed the answer shifting by 4 554 leaves. The medicine
makes the very thing it guards worse. What blocks truncation is therefore not the price but the
SHAPE, and the only cure for a shape is a different record: ONE row that carries the candidate's
history in itself, plus a reader that merges it with whatever ``transition`` rows are still there.

The merge rule, and why it cannot double
----------------------------------------
A compaction row records, verbatim, the entry-like ``{"at", "payload"}`` of every transition it
absorbed, in ledger order. :func:`transitions_for` then merges the NEWEST compaction row for a
candidate with the ``transition`` rows still in the ledger as a MULTISET keyed by content:

* per content token, the merged history holds ``max(count_in_compaction, count_in_ledger)``
  copies — a token present in both is the SAME transition recorded twice, never two transitions;
* compaction entries are emitted first, in their recorded order, then ledger entries whose
  token quota is not yet filled.

On the FULL ledger that reproduces today's answer byte for byte (the compaction covers a prefix,
the ledger holds the whole thing, every quota is 1). After truncation the prefix lives only in the
compaction and the suffix only in the ledger, and the merge is still the same list. And repeating
the compaction row every tact does NOT accumulate anything, because only the newest row is read —
which is exactly the property the ``transition`` rows lack.

Addressing by CONTENT WITH THE REPEAT NUMBER (the multiset, not the set) is deliberate: ADR-794
found a measured defect in the neighbouring instrument caused by exactly the opposite choice —
nine identical reasons collapsed into one address because the repeat number was dropped.

The third outcome (inv. #17)
----------------------------
A compaction row that is not a faithful prefix of the history still in the ledger is not silently
preferred and not silently ignored: :func:`transitions_for` returns the LEDGER-ONLY history (which
is exactly today's behaviour — it can under-report, never invent) together with a NAMED reason,
and ``read.latest()`` publishes it in its ``history_compaction`` block. "OK", "ABSENT" and
"BROKEN" are three different values there, never one.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.research_factory import contract, registry
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.hash_ledger import HashLedger

#: The ledger record kind. Declared HERE and not in ``contract.LEDGER_KINDS``: that tuple has no
#: reader anywhere in the tree (measured 24.10 — the only hit for its name is its own definition)
#: and is already missing EIGHT of the eleven kinds the live ledger actually carries, so adding a
#: ninth to it would be a declaration inside an untrue list. The writer and both readers of this
#: kind live in this module, and the name below is the one they share.
KIND = "candidate_history"
SCHEMA = "candidate-history/1"

#: How often the writer refreshes the row. It must match (or be shorter than) the truncation
#: window a reader wants: a compaction row older than the window is cut away with everything
#: else, and the history goes with it. One day is the cadence of ``com.spa.research_factory``
#: itself, which is what actually calls :func:`compact`.
COMPACTION_TACT_DAYS = 1

STATUS_OK = "OK"
STATUS_ABSENT = "ABSENT"
STATUS_BROKEN = "BROKEN"


class CompactionRefused(Exception):
    """The writer refuses to record a compaction it cannot stand behind."""


# ── reading ──────────────────────────────────────────────────────────────────────────────────────


def _token(entry: dict) -> str:
    """Content identity of ONE transition — the multiset key. ``at`` plus the whole payload:
    two transitions of the same candidate differing in nothing a reader can see are, to every
    reader, the same transition twice."""
    return contract.digest([entry.get("at"), entry.get("payload")])


def _counts(entries: Sequence[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for entry in entries:
        key = _token(entry)
        out[key] = out.get(key, 0) + 1
    return out


def ledger_transitions(ledger: HashLedger, candidate_id: str) -> List[dict]:
    """The candidate's ``transition`` rows still in the ledger, in LEDGER ORDER.

    Ledger order — not ``seq`` order — on purpose: a scene rebuilt from a subset of a ledger is
    renumbered from 1 (``ledger_window_dependency_census.rechain``), so ``seq`` is not an identity
    that survives truncation. Within one file the two orders are the same thing.
    """
    out: List[dict] = []
    for entry in ledger.read_all():
        if entry.get("kind") != "transition":
            continue
        payload = entry.get("payload") or {}
        if payload.get("candidate_id") != candidate_id:
            continue
        out.append({"kind": "transition", "at": entry.get("at"), "payload": payload,
                    "seq": entry.get("seq"), "source": "ledger"})
    return out


def compaction_rows(ledger: HashLedger, candidate_id: str) -> List[dict]:
    """Every compaction row recorded for this candidate, in ledger order."""
    out: List[dict] = []
    for entry in ledger.read_all():
        if entry.get("kind") != KIND:
            continue
        payload = entry.get("payload") or {}
        if payload.get("candidate_id") != candidate_id:
            continue
        out.append(entry)
    return out


def newest_compaction(ledger: HashLedger, candidate_id: str) -> Optional[dict]:
    """The NEWEST compaction row, or ``None``. Only the newest is ever read — that is what makes
    repeating the row every tact free of accumulation."""
    rows = compaction_rows(ledger, candidate_id)
    return rows[-1] if rows else None


def _absorbed_entries(payload: dict) -> Tuple[List[dict], Optional[str]]:
    """The transitions a compaction payload claims, or a NAMED reason why it cannot be read."""
    if payload.get("schema") != SCHEMA:
        return [], (f"compaction schema is {payload.get('schema')!r}, not {SCHEMA!r}")
    raw = payload.get("transitions")
    if not isinstance(raw, list):
        return [], f"compaction `transitions` is {type(raw).__name__}, not a list"
    declared = payload.get("absorbed")
    if declared != len(raw):
        return [], (f"compaction declares absorbed={declared!r} but carries {len(raw)} "
                    "transition(s) — the payload is truncated or was built by something else")
    out: List[dict] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
            return [], (f"compaction transition #{index} has no payload dict — it cannot be "
                        "merged with a ledger row")
        out.append({"kind": "transition", "at": item.get("at"), "payload": item["payload"],
                    "seq": None, "source": "compaction"})
    return out, None


def merge(ledger_rows: Sequence[dict], compacted: Sequence[dict]) -> List[dict]:
    """Multiset merge: ``max(count)`` per content token, compaction first, then the ledger."""
    quota = _counts(ledger_rows)
    for token, count in _counts(compacted).items():
        quota[token] = max(quota.get(token, 0), count)
    emitted: Dict[str, int] = {}
    out: List[dict] = []
    for entry in list(compacted) + list(ledger_rows):
        token = _token(entry)
        if emitted.get(token, 0) >= quota.get(token, 0):
            continue
        emitted[token] = emitted.get(token, 0) + 1
        out.append(entry)
    return out


def transitions_for(ledger: HashLedger, candidate_id: str) -> Tuple[List[dict], Optional[str]]:
    """The candidate's FULL transition history as every reader should see it, plus a reason.

    ``(rows, None)`` — the history, merged from the newest compaction row and the ledger rows.
    ``(ledger_rows, "<reason>")`` — the compaction could not be stood behind; the answer falls
    back to the ledger alone, which is precisely the behaviour that existed before this module,
    and the reason is NAMED rather than swallowed.
    """
    rows = ledger_transitions(ledger, candidate_id)
    row = newest_compaction(ledger, candidate_id)
    if row is None:
        return rows, None
    compacted, reason = _absorbed_entries(row.get("payload") or {})
    if reason is not None:
        return rows, reason
    through = (row.get("payload") or {}).get("compacted_through")
    known = _counts(compacted)
    #: Unfaithfulness is DETECTABLE only while the absorbed rows are still in the ledger; once
    #: they are truncated away there is nothing left to compare against, and this module says so
    #: out loud rather than implying a guarantee it cannot give.
    for entry in rows:
        at = entry.get("at")
        if through is not None and at is not None and str(at) >= str(through):
            continue
        token = _token(entry)
        if known.get(token, 0) <= 0:
            return rows, (f"compaction claims compacted_through={through!r} but the ledger still "
                          f"holds an OLDER transition it does not carry (at={at!r}, "
                          f"to_state={(entry.get('payload') or {}).get('to_state')!r}) — it is "
                          "not a faithful prefix of this history")
        known[token] -= 1
    return merge(rows, compacted), None


def history_status(ledger: HashLedger, candidate_ids: Sequence[str]) -> dict:
    """The ``history_compaction`` block of :func:`read.latest` — three values, never one."""
    broken: List[dict] = []
    compacted = 0
    for cid in candidate_ids:
        row = newest_compaction(ledger, cid)
        _, reason = transitions_for(ledger, cid)
        if reason is not None:
            broken.append({"candidate_id": cid, "reason": reason})
        elif row is not None:
            compacted += 1
    if broken:
        status = STATUS_BROKEN
    elif compacted:
        status = STATUS_OK
    else:
        status = STATUS_ABSENT
    return {"status": status, "schema": SCHEMA, "candidates_compacted": compacted,
            "tact_days": COMPACTION_TACT_DAYS, "broken": broken}


# ── writing ──────────────────────────────────────────────────────────────────────────────────────


def build_payload(candidate_id: str, rows: Sequence[dict], *, recorded_at: str) -> dict:
    """The compaction payload for one candidate. ``rows`` is its history in order."""
    if not rows:
        raise CompactionRefused(f"{candidate_id!r} has no transition to compact")
    absorbed = [{"at": entry.get("at"), "payload": entry.get("payload") or {}} for entry in rows]
    return {"schema": SCHEMA, "candidate_id": candidate_id, "recorded_at": recorded_at,
            "compacted_through": absorbed[-1]["at"], "absorbed": len(absorbed),
            "transitions": absorbed}


def _is_due(row: Optional[dict], rows: Sequence[dict], now: datetime, tact_days: int) -> bool:
    """A refresh is due when the history GREW, or when the newest row is a tact old.

    Both halves are needed, and the second is the one that matters for the cure: a compaction row
    that is never rewritten ages past the truncation window and is cut away with the history it
    was supposed to save.
    """
    if row is None:
        return True
    payload = row.get("payload") or {}
    if payload.get("absorbed") != len(rows):
        return True
    recorded = contract.parse_ts(payload.get("recorded_at") or row.get("at"))
    if recorded is None:
        return True
    return (now - recorded) >= timedelta(days=tact_days)


def compact(data_dir: Path, *, now: Optional[datetime] = None,
            tact_days: int = COMPACTION_TACT_DAYS) -> dict:
    """Record/refresh one compaction row per candidate. Called by ``run.run_once`` each run.

    Returns a measured report: who was written, who was already current, and who was REFUSED with
    a reason. "Nobody was written" and "the writer did not look" are different answers.
    """
    moment = now or datetime.now(timezone.utc)
    at = iso(moment)
    ledger = ledger_for(Path(data_dir))
    written: List[str] = []
    current: List[str] = []
    refused: List[dict] = []
    #: Четвёртый исход, а не слияние с «уже свеж»: ключ строки несёт МОМЕНТ записи, и
    #: второй зов в ту же секунду с выросшей историей упёрся бы в него. Писать поверх
    #: нельзя (лента append-only), падать нельзя (это дневной прогон агента), но и
    #: называть это «уже свежим» нельзя — история в таком случае как раз НЕ записана.
    collided: List[str] = []
    for cid in registry.all_candidate_ids(ledger):
        rows, reason = transitions_for(ledger, cid)
        if reason is not None:
            refused.append({"candidate_id": cid, "reason": reason})
            continue
        if not rows:
            continue
        if not _is_due(newest_compaction(ledger, cid), rows, moment, tact_days):
            current.append(cid)
            continue
        payload = build_payload(cid, rows, recorded_at=at)
        _, created = ledger.append_idempotent(KIND, [KIND, cid, at], payload, at)
        (written if created else collided).append(cid)
    return {"schema": SCHEMA, "at": at, "tact_days": tact_days, "written": written,
            "already_current": current, "key_collision": collided, "refused": refused}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Строка УПЛОТНЕНИЯ истории кандидата: одна запись вместо накапливающего "
        "списка причин (ADR-795)."))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="только показать, кому запись НУЖНА (в ленту не пишет)")
    args = parser.parse_args(argv)
    root = Path(args.data_dir)
    if args.dry_run:
        ledger = ledger_for(root)
        moment = datetime.now(timezone.utc)
        due = []
        for cid in registry.all_candidate_ids(ledger):
            rows, reason = transitions_for(ledger, cid)
            if reason is None and rows and _is_due(newest_compaction(ledger, cid), rows,
                                                   moment, COMPACTION_TACT_DAYS):
                due.append(cid)
        report = {"dry_run": True, "due": due, "tact_days": COMPACTION_TACT_DAYS}
    else:
        report = compact(root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"уплотнение истории ({root}): записано {len(report.get('written', report.get('due', [])))} · "
              f"уже свежих {len(report.get('already_current', []))} · "
              f"ОТКАЗ {len(report.get('refused', []))}")
        for item in report.get("refused", []):
            print(f"  ОТКАЗ {item['candidate_id']}: {item['reason']}")
    return 1 if report.get("refused") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
