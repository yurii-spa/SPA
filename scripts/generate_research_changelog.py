#!/usr/bin/env python3
"""Q2-14 — auto-generated research changelog from the LIVE pipeline (deterministic, honest).

The blog was a hardcoded 3-post array frozen 2026-06-20. This generator turns the live track + refusal
data into a dated, machine-readable changelog (`landing/src/data/changelog.json`) that the /changelog
page and the RSS feed render — a public heartbeat for the track and a re-index reason for crawlers / AI
answer engines. The digest text is a DETERMINISTIC TEMPLATE (NO LLM): it only interpolates real numbers
from data/track_ledger.json (Q2-18) + data/rates_desk/decision_log.jsonl. Every number is evidence-tagged
and honestly labelled (evidenced track days, refusal count from the hash-chained log).

Idempotent: an entry is keyed by its data signature (last evidenced date + day-count + refusal count);
re-running with unchanged data does NOT create a duplicate. stdlib-only, fail-CLOSED (missing source →
skip that field / emit nothing rather than a fabricated number). Advisory / read-only on the live data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
_LEDGER = ROOT / "data" / "track_ledger.json"
_DECISIONS = ROOT / "data" / "rates_desk" / "decision_log.jsonl"
_OUT = ROOT / "landing" / "src" / "data" / "changelog.json"
_MAX_ENTRIES = 52  # keep ~a year of weekly digests


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _count_refusals(p: Path) -> tuple:
    entries = refusals = 0
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            entries += 1
            if d.get("approved") is False:
                refusals += 1
    except OSError:
        return (None, None)
    return (entries, refusals)


def build_entry(*, date: str) -> Optional[dict]:
    ledger = _load_json(_LEDGER)
    n_days = ledger.get("n_evidenced_days")
    needed = ledger.get("days_needed", 30)
    cum = ledger.get("cumulative_return_pct")
    dd = ledger.get("max_drawdown_from_peak_pct")
    last = ledger.get("last_evidenced_date")
    entries, refusals = _count_refusals(_DECISIONS)

    if n_days is None and refusals is None:
        return None  # fail-CLOSED: no real data → no fabricated digest

    # deterministic template — real numbers only, honestly labelled
    parts_en = []
    parts_ru = []
    if n_days is not None:
        parts_en.append(f"Evidenced paper track: {n_days}/{needed} days"
                        + (f" (cumulative {cum:+.2f}%, max drawdown {dd:.2f}%)" if cum is not None else ""))
        parts_ru.append(f"Evidenced paper-трек: {n_days}/{needed} дней"
                        + (f" (кумулятивно {cum:+.2f}%, макс. просадка {dd:.2f}%)" if cum is not None else ""))
    if refusals is not None:
        parts_en.append(f"Refusal log: {refusals} declined of {entries} hash-chained decisions")
        parts_ru.append(f"Журнал отказов: {refusals} отклонено из {entries} hash-chained решений")

    summary_en = ". ".join(parts_en) + ". Paper research, advisory — the refusal log is the differentiator, not a rate."
    summary_ru = ". ".join(parts_ru) + ". Paper-исследование, advisory — differentiator это журнал отказов, а не ставка."

    return {
        "slug": f"changelog-{date}",
        "date": date,
        "title": f"Track & refusal digest — {date}",
        "titleRu": f"Дайджест трека и отказов — {date}",
        "summary": summary_en,
        "summaryRu": summary_ru,
        "tag": "Changelog",
        "tagRu": "Changelog",
        "auto": True,
        "evidence": "L4 · evidenced track + hash-chained refusal log",
        "_sig": {"last": last, "n_days": n_days, "refusals": refusals},
    }


def generate(*, date: str, write: bool = True) -> dict:
    try:
        existing = json.loads(_OUT.read_text())
        if not isinstance(existing, list):
            existing = []
    except (OSError, ValueError):
        existing = []

    entry = build_entry(date=date)
    result = {"created": False, "reason": "", "n_entries": len(existing)}
    if entry is None:
        result["reason"] = "no live data (fail-closed)"
        return result

    # idempotent: skip if an entry with the SAME data signature already exists
    if any(e.get("_sig") == entry["_sig"] for e in existing):
        result["reason"] = "unchanged data — no duplicate digest"
        return result
    # also replace a same-date entry (re-run on the same day with newer data)
    existing = [e for e in existing if e.get("slug") != entry["slug"]]
    existing.insert(0, entry)
    existing = existing[:_MAX_ENTRIES]
    result.update(created=True, n_entries=len(existing), entry=entry)

    if write:
        _OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(_OUT)  # atomic same-dir rename
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the research changelog from live track + refusals")
    ap.add_argument("--date", required=True, help="ISO date for the digest (YYYY-MM-DD)")
    args = ap.parse_args()
    r = generate(date=args.date)
    if r["created"]:
        print(f"[changelog] added digest {args.date} → {r['n_entries']} entries · {r['entry']['summary'][:80]}…")
    else:
        print(f"[changelog] no new entry: {r['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
