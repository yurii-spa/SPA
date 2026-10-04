"""Investment CIO — daily driver (ADR-554). ``python -m spa_core.investment_cio.run``.

build_sleeves -> previous = ledger tail -> recommend -> ledger.append (idempotent per UTC date) ->
outcomes.score_due -> one-line summary. Never a raw traceback: exit 0 ok, 2 on a ledger error or any
unexpected exception, 75 when another run holds the ledger lock.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from spa_core.investment_cio import ledger, outcomes, policy
from spa_core.utils.live_paths import live_data_dir


def _parse_now(value: Optional[str]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    s = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m spa_core.investment_cio.run")
    ap.add_argument("--data-dir", default=None, help="defaults to the live data/ dir")
    ap.add_argument("--now", default=None, help="ISO-8601, defaults to real UTC now")
    ap.add_argument("--repair", action="store_true",
                    help="verify the ledger chain and move any torn/broken tail into "
                         "ledger.jsonl.torn-<UTCstamp> (never deletes); does not build a recommendation")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else live_data_dir(Path(__file__).resolve().parents[2])
    try:
        now = _parse_now(args.now)
    except ValueError as exc:
        print(f"investment_cio.run: --now unparsable — {exc}")
        return 2

    if args.repair:
        try:
            result = ledger.repair(data_dir)
        except ledger.LockBusy as exc:
            print(f"investment_cio.run --repair: ledger lock held by another run — {exc}")
            return 75
        print(f"investment_cio.run --repair: {result}")
        # N3: repair() itself refuses (fixable=False) when the ledger file is internally
        # self-consistent but disagrees with its external anchors — that is tampering, not a torn
        # write, and there is nothing repair can move aside to fix it.
        if result.get("fixable") is False:
            return 2
        return 0

    try:
        from spa_core.investment_cio import sleeves  # may not exist yet (concurrent WP)
    except ImportError as exc:
        print(f"investment_cio.run: spa_core.investment_cio.sleeves not available yet ({exc}) — nothing built")
        return 2

    try:
        now_date = now.astimezone(timezone.utc).strftime("%Y-%m-%d") if now.tzinfo else now.strftime("%Y-%m-%d")
        previous_entry = ledger.read_tail(data_dir)
        if previous_entry is not None and previous_entry["recommendation"].get("date") == now_date:
            # finding #21: an idempotent same-date re-run must NOT rebuild the sleeves document or
            # save a new snapshot before learning that — doing so unconditionally orphans a fresh
            # *.json.gz every retry, never referenced by the ledger (ledger.append's own idempotent
            # return path discards it). The date alone (derived from --now, not from the sleeves
            # document) is enough to decide this before any of that work starts.
            outcome_summary = outcomes.score_due(data_dir, now)
            written_rec = previous_entry["recommendation"]
            print(f"investment_cio: date={written_rec.get('date')} stance={written_rec.get('stance')} "
                 f"seq={previous_entry.get('seq')} confidence={written_rec.get('confidence')} "
                 f"outcomes_scored={outcome_summary['scored']}/{outcome_summary['due']} "
                 f"(idempotent re-run — no new snapshot)")
            return 0

        # finding N8: a back-dated run must be refused BEFORE building the sleeves document or
        # saving a snapshot — ledger.append's own refusal (finding #15) comes too late: by then
        # the snapshot is already on disk, orphaned forever (append's idempotent-return path is
        # the only one that discards a snapshot, and this is not that path). The date alone,
        # derived from --now, is enough to decide this up front.
        if previous_entry is not None:
            tail_date = previous_entry["recommendation"].get("date")
            if tail_date is not None and now_date < tail_date:
                print(f"investment_cio.run: refusing back-dated run — --now date {now_date!r} is not "
                     f"later than the ledger tail's date {tail_date!r}; not building a recommendation "
                     "or snapshot (finding N8)")
                return 2

        previous = previous_entry["recommendation"] if previous_entry else None
        sleeves_doc = sleeves.build_sleeves(data_dir, now)
        rec = policy.recommend(sleeves_doc, previous, now)
        snap_digest = ledger.save_snapshot(data_dir, sleeves_doc)
        code_id = ledger.code_identity()
        line = ledger.append(data_dir, rec, snapshot_digest_=snap_digest, code_identity_=code_id)
        outcome_summary = outcomes.score_due(data_dir, now)
        ledger.prune_snapshots(data_dir, now=now)
        written_rec = line["recommendation"]
        print(f"investment_cio: date={written_rec.get('date')} stance={written_rec.get('stance')} "
             f"seq={line.get('seq')} confidence={written_rec.get('confidence')} "
             f"outcomes_scored={outcome_summary['scored']}/{outcome_summary['due']}")
        return 0
    except ledger.LockBusy as exc:
        print(f"investment_cio.run: ledger lock held by another run — {exc}")
        return 75
    except ledger.LedgerError as exc:
        msg = str(exc)
        # N3: --repair cannot fix an anchor disagreement (that is tampering, not a torn write —
        # see ledger.repair's own fixable=False path), so don't dangle it as a suggestion here.
        hint = "" if "anchor" in msg else " (try --repair)"
        print(f"investment_cio.run: ledger error — {msg}{hint}")
        return 2
    except Exception as exc:  # fail-CLOSED: never a raw traceback
        print(f"investment_cio.run: unexpected error — {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
