"""
spa_core/strategy_lab/rates_desk/paper_realized_at_size.py — Lane B B2.6: the STANDING
forward-measurement agent for the realized-at-size killer test.

The killer test (realized_at_size.py) answers the ONE question — does the edge survive at fundable
size? — on whatever realized forward track Lane A has accumulated. On day 1 the honest answer is
INSUFFICIENT_DATA. The VALUE compounds with the track: every UTC day this agent re-runs the killer
test on the freshest books and appends ONE row to a growing verdict track, so a reviewer can watch
the verdict EVOLVE (INSUFFICIENT_DATA → the real SURVIVES_AT / DOES_NOT_SURVIVE_PAST answer) as the
forward track crosses MIN_REALIZED_DAYS. The track is the proof the answer was measured forward, not
back-fit.

CONTRACT (the standing-agent invariants)
═════════════════════════════════════════
  • Idempotent per UTC day: re-ticking the same calendar day REPLACES today's row (a refresh), never
    appends a duplicate — the track has at most one row per UTC date.
  • Advisory / read-only of capital: it reads Lane A's books + writes ONLY its own
    data/rates_desk/realized_at_size.json + data/rates_desk/paper/realized_at_size_track.jsonl. It
    NEVER moves capital, NEVER touches the go-live track (equity_curve_daily.json et al.), NEVER
    imports execution/.
  • fail-CLOSED: a thin/absent books dir → an INSUFFICIENT_DATA row (the honest default), never a
    fabricated survival. A malformed track file is treated as empty (rebuilt forward), never crashes.
  • deterministic / stdlib-only / atomic writes (repo rule #4) / LLM-FORBIDDEN.

The track row is a COMPACT verdict summary (the full scored payload lives in realized_at_size.json):
    {as_of_utc, data_as_of, verdict, survives_at_aum_usd, does_not_survive_past_aum_usd,
     floor_plus_bps_at_5M, realized_days, combined_deployable_usd, correlation_haircut_usd,
     n_exit_venues, verdict_stable_across_band, proof_hash}

Run (one tick — what the launchd agent invokes):
    python3 -m spa_core.strategy_lab.rates_desk.paper_realized_at_size
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import List, Optional

from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import realized_at_size as RAS

_ROOT = Path(__file__).resolve().parents[3]
_PAPER_DIR = _ROOT / "data" / "rates_desk" / "paper"
_TRACK = _PAPER_DIR / "realized_at_size_track.jsonl"


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _read_track(path: Path) -> List[dict]:
    """The growing verdict track (one JSON object per line). fail-CLOSED: a missing/garbled file →
    []; a malformed line is SKIPPED (the track is rebuilt forward, never crashes the tick)."""
    out: List[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _track_row(result: dict, as_of_utc: str) -> dict:
    """The compact per-day verdict row appended to the track (the full payload is in the JSON)."""
    c = result.get("combined", {}) or {}
    hs = result.get("haircut_sensitivity", {}) or {}
    return {
        "as_of_utc": as_of_utc,
        "data_as_of": result.get("as_of"),
        "verdict": result.get("verdict"),
        "survives_at_aum_usd": result.get("survives_at_aum_usd"),
        "does_not_survive_past_aum_usd": result.get("does_not_survive_past_aum_usd"),
        "floor_plus_bps_at_5M": result.get("floor_plus_bps_at_5M"),
        "realized_days": result.get("realized_days"),
        "n_books_deployable": result.get("n_books_deployable"),
        "combined_deployable_usd": c.get("combined_deployable_usd"),
        "correlation_haircut_usd": c.get("correlation_haircut_usd"),
        "n_exit_venues": c.get("n_exit_venues"),
        "verdict_stable_across_band": hs.get("verdict_stable_across_band"),
        "proof_hash": result.get("proof_hash"),
        "generated_at": _utc_now_iso(),
    }


def tick(
    books_dir: Optional[Path] = None,
    track_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    as_of_utc: Optional[str] = None,
) -> dict:
    """Run ONE forward-measurement tick: re-run the killer test on the freshest books, write the full
    realized_at_size.json, and append/refresh today's row in the growing verdict track (idempotent per
    UTC day). Returns {as_of_utc, verdict, realized_days, track_len, refreshed}.

    Idempotent: if a row for today's UTC date already exists it is REPLACED (a refresh on re-tick),
    not duplicated — the track holds at most one row per UTC date. fail-CLOSED throughout."""
    today = as_of_utc or _utc_today()
    tp = track_path or _TRACK
    tp.parent.mkdir(parents=True, exist_ok=True)

    # the killer test on the freshest books (writes realized_at_size.json atomically)
    result = RAS.build_realized_at_size(write=True, books_dir=books_dir, out_path=out_path)

    track = _read_track(tp)
    refreshed = any(r.get("as_of_utc") == today for r in track)
    track = [r for r in track if r.get("as_of_utc") != today]  # drop today (idempotent refresh)
    track.append(_track_row(result, today))
    track.sort(key=lambda r: str(r.get("as_of_utc") or ""))

    # atomic rewrite of the whole JSONL (small, one row/day; deterministic order)
    body = "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in track)
    _io.atomic_write_text(tp, body)

    return {
        "as_of_utc": today,
        "verdict": result.get("verdict"),
        "realized_days": result.get("realized_days"),
        "track_len": len(track),
        "refreshed": refreshed,
        "proof_hash": result.get("proof_hash"),
    }


def main() -> int:
    summary = tick()
    print("Rates Desk — STANDING realized-at-size forward measurement (advisory; one tick)")
    print(f"  as_of_utc:      {summary['as_of_utc']}  ({'refreshed' if summary['refreshed'] else 'new'} row)")
    print(f"  verdict:        {summary['verdict']}  (realized_days={summary['realized_days']})")
    print(f"  track length:   {summary['track_len']} day(s)")
    print(f"  proof_hash:     {summary['proof_hash']}")
    print(f"  track:          {_TRACK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
