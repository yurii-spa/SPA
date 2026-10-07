"""PUBLIC PROFILE ↔ INTERNAL BOOK — the one explicit mapping (PRODUCT-TRUTH-02, ADR-630).

This module holds NO name, date or book of its own — every field is read from the canon that owns it
(review 07.10: a hand-typed copy here would drift silently from them):

* public / historical names — `landing/src/lib/tier_bands.json` (`en`/`ru`/`alt_en`; owner choice #6,
  ADR-OWN-2026-07: primary = Conservative/Balanced/Aggressive, alt = Preserve/Core/Max Yield — HISTORICAL
  names, no paper history attributed to them);
* internal book, book file, decision refs — `spa_core/paper_trading/strategy_mandates.MANDATES`;
* decision date — the header of the deciding ADR, parsed by the continuity generator's `adr_effective`
  (ADR-593 for Conservative = the evidenced book; ADR-533 for the two sleeves);
* track start — the experiment the book records itself (`package_status` → `experiment_id`), and for
  Conservative the snapshot's own `evidenced_anchor`;
* maturity — `package_status.REPORTABLE_AFTER`.

The only literal here is WHICH ADR decides each profile — that is the claim this module makes, and the
parity test checks it against the ADRs. Any disagreement ⇒ ``MappingConflict`` (refuse, never repair).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from spa_core.defi_engine.package_status import REPORTABLE_AFTER
from spa_core.paper_trading.strategy_mandates import MANDATES

ROOT = Path(__file__).resolve().parents[2]
TIER_BANDS = ROOT / "landing" / "src" / "lib" / "tier_bands.json"
DECISIONS_DIR = ROOT / "docs" / "decisions"


def decisions_dir_default() -> Path:
    """Where decision headers are read. The production tree does NOT sync ``docs/`` (CLAUDE.md, ADR-152),
    so reading its own ``docs/decisions`` made a shelf built on the Mac differ from the same shelf built
    from origin (decision dates «UNKNOWN» there) — and the Mac pipeline could never verify a shelf the
    owner approved (found at publication 2026-10-07). Same operand rule as the cadence: ``$SPA_DECISIONS_DIR``
    → the origin mirror (``cadence.DEFAULT_MIRROR``) when present → this tree."""
    import os
    env = os.environ.get("SPA_DECISIONS_DIR")
    if env:
        return Path(env)
    from spa_core.publication.cadence import DEFAULT_MIRROR
    mirror = DEFAULT_MIRROR / "docs" / "decisions"
    return mirror if mirror.is_dir() else DECISIONS_DIR
PROFILES = ("conservative", "balanced", "aggressive")
NAMING_DECISION = "ADR-OWN-2026-07"
#: the deciding ADR of each profile's CURRENT book (the claim of this module)
DECIDING_ADR = {"conservative": "ADR-593", "balanced": "ADR-533", "aggressive": "ADR-533"}
UNKNOWN = "UNKNOWN"


class MappingConflict(ValueError):
    """The decided mapping and the measured books disagree — refuse, do not guess."""


def _read_json(p: Path) -> Optional[dict]:
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def adr_date(adr_id: str, decisions_dir: Optional[Path] = None) -> str:
    """Decision date from the ADR header (continuity's parser — one parser for both readers)."""
    from spa_core.studio_os.memory.continuity import adr_effective
    hits = sorted(Path(decisions_dir if decisions_dir is not None else decisions_dir_default()).glob(f"{adr_id}-*.md"))
    if len(hits) != 1:
        return UNKNOWN
    return adr_effective(hits[0].read_text(encoding="utf-8", errors="replace"))


def _start_from_experiment(exp_id) -> Optional[str]:
    if not isinstance(exp_id, str) or "@" not in exp_id:
        return None
    return exp_id.rsplit("@", 1)[1] or None


def build(package_status: Optional[dict], *, evidenced_anchor: Optional[str] = None,
          tier_bands: Optional[dict] = None, decisions_dir: Optional[Path] = None) -> list[dict]:
    """One row per public profile. Unreadable inputs ⇒ the field is None/UNKNOWN, never a guess."""
    bands = tier_bands if tier_bands is not None else (_read_json(TIER_BANDS) or {})
    pk = (package_status or {}).get("packages") if isinstance(package_status, dict) else None
    pk = pk if isinstance(pk, dict) else {}
    rows = []
    for key in PROFILES:
        m = MANDATES[key]
        tb = bands.get(key) if isinstance(bands.get(key), dict) else {}
        meas = pk.get(key) if isinstance(pk.get(key), dict) else {}
        hist = meas.get("history") if isinstance(meas.get("history"), dict) else {}
        periods = hist.get("valid_periods")
        periods = periods if isinstance(periods, int) and not isinstance(periods, bool) else None
        maturity = UNKNOWN if periods is None else ("REPORTABLE" if periods >= REPORTABLE_AFTER else "ACCUMULATING")
        exp_id = meas.get("experiment_id")
        start = _start_from_experiment(exp_id) or meas.get("experiment_start_date")
        rows.append({
            "profile": key,
            "public_name": tb.get("en"), "public_name_ru": tb.get("ru"),
            "historical_name": tb.get("alt_en"),
            "historical_name_note": "historical name only — no paper history is attributed to it",
            "naming_decision": NAMING_DECISION,
            "internal_book": m["strategy_version"], "book_file": m["book"],
            "deciding_adr": DECIDING_ADR[key], "decision_date": adr_date(DECIDING_ADR[key], decisions_dir),
            "track_decisions": list((m.get("refs") or {}).get("decision") or []),
            "experiment_id": exp_id, "track_start": start,
            "evidenced_anchor": evidenced_anchor if key == "conservative" else None,
            "valid_periods": periods, "reportable_after": REPORTABLE_AFTER, "maturity": maturity,
            "result_metric_type": "REALIZED_PAPER_RETURN" if maturity == "REPORTABLE" else None,
            "target_metric_type": "TARGET_RETURN",
        })
    return rows


def conflicts(rows: list[dict]) -> list[str]:
    out: list[str] = []
    seen: dict = {}
    names = [r.get("public_name") for r in rows]
    for r in rows:
        key, book = r["profile"], r["internal_book"]
        if not r.get("public_name"):
            out.append(f"{key}: public name not readable from tier_bands.json")
        if book in seen:
            out.append(f"{key}: internal book {book} already mapped to {seen[book]}")
        seen[book] = key
        exp = r.get("experiment_id")
        if exp is not None and not str(exp).startswith(f"{book}@"):
            out.append(f"{key}: measured experiment {exp!r} is not the decided book {book!r}")
        if r.get("historical_name") and r.get("historical_name") in names:
            out.append(f"{key}: historical name {r['historical_name']!r} collides with a current public name")
        anchor = r.get("evidenced_anchor")
        if key == "conservative" and anchor and r.get("track_start") and r["track_start"] != anchor:
            out.append(f"conservative: track start {r['track_start']!r} ≠ the snapshot's evidenced anchor {anchor!r}")
        if r.get("deciding_adr") not in (r.get("track_decisions") or []) and key != "conservative":
            out.append(f"{key}: deciding {r.get('deciding_adr')} is not among the book's decisions")
    if len(set(names)) != len(names):
        out.append(f"duplicate public names: {names}")
    return out


def checked(package_status: Optional[dict], **kw) -> list[dict]:
    rows = build(package_status, **kw)
    bad = conflicts(rows)
    if bad:
        raise MappingConflict("; ".join(bad))
    return rows
