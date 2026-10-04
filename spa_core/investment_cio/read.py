"""Investment CIO — the canonical READ function for consumers (Mission Control, ADR-552).

``latest(data_dir)`` is read-only: it never writes ``latest.json``, never appends to the ledger,
never scores outcomes. If the pointer is missing or doesn't match the ledger tail, it rebuilds the
answer IN MEMORY from the ledger itself — the file on disk is left exactly as found.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.investment_cio import contract, ledger, outcomes


def latest(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Finding #5: a torn ledger line used to raise a bare exception out of every reader of
    ``latest()`` (Mission Control included) — now it is reported as NOT_MEASURED with a reason
    naming the torn line and the remedy, never a raised exception.

    Finding #6: the recommendation served is ALWAYS the ledger tail, read straight off disk —
    never ``latest.json``'s own copy, even when its ``entry_hash`` field happens to match the
    tail's. That field is just a cached string; a pointer file whose ``recommendation`` content
    was edited without recomputing ``entry_hash`` used to be served verbatim as long as the stale
    hash string still matched. The pointer is now only ever a HINT: ``pointer_mismatch`` is True
    when its content disagrees with the tail it claims to mirror.
    """
    now = now or datetime.now(timezone.utc)
    try:
        entries = ledger.read_all(data_dir)
    except ledger.LedgerError as exc:
        return {"state": contract.NOT_MEASURED, "integrity": "BROKEN", "reason": str(exc)}
    if not entries:
        return {"state": contract.NOT_MEASURED, "reason": "no recommendations have been written yet"}

    try:
        chain = ledger.verify_chain(data_dir)
    except ledger.LedgerError as exc:
        return {"state": contract.NOT_MEASURED, "integrity": "BROKEN", "reason": str(exc)}

    # N3: a chain that is not intact (hash break, tampering caught via the anchors, or a missing
    # anchor) must NEVER be served as a trustworthy recommendation — the entry at the tail might
    # itself be the tampered one. State drops to NOT_MEASURED and the recommendation is withheld
    # entirely, rather than returning MEASURED with ``chain_ok: False`` next to a live value.
    if not chain.get("ok", False):
        return {"state": contract.NOT_MEASURED, "integrity": "BROKEN",
                "reason": f"ledger chain is not intact (break_at={chain.get('break_at')}, "
                         f"reason={chain.get('reason') or 'chain'}) — recommendation withheld"}

    tail = entries[-1]
    recommendation = tail["recommendation"]  # ALWAYS the ledger tail — the pointer is a hint only
    pointer = ledger.read_latest_pointer(data_dir)
    pointer_entry_hash_matches = pointer is not None and pointer.get("entry_hash") == tail.get("entry_hash")
    pointer_content_matches = pointer_entry_hash_matches and pointer.get("recommendation") == recommendation
    rebuilt_in_memory = not pointer_content_matches
    pointer_mismatch = pointer is not None and pointer_entry_hash_matches and not pointer_content_matches

    scored = outcomes.distinct_scored_keys(data_dir)
    pending = len(outcomes.find_due(data_dir, now))

    generated_at = recommendation.get("generated_at")
    age_hours = None
    if generated_at:
        try:
            gen = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age_hours = round((now - gen).total_seconds() / 3600.0, 2)
        except ValueError:
            age_hours = None

    return {
        "state": contract.MEASURED,
        "recommendation": recommendation,
        "rebuilt_in_memory": rebuilt_in_memory,
        "pointer_mismatch": pointer_mismatch,
        "ledger": {
            "entries": len(entries),
            "chain_ok": chain["ok"],
            "first_date": entries[0]["recommendation"].get("date"),
            "last_date": entries[-1]["recommendation"].get("date"),
        },
        "outcomes": {"scored": scored, "pending": pending},
        "age_hours": age_hours,
    }
