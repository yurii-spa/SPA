"""Investment CIO — forward outcome scoring (ADR-554 WP-S04).

For every ledger entry and horizon (``contract.POLICY["outcome_horizons_days"]``: 7, 30 days) whose
horizon has FULLY ELAPSED and that has no outcome yet, compute buy-and-hold portfolio returns for
RECOMMENDED (if the stance carried weights), SEED_SPLIT and EQUAL_WEIGHT (the three DeFi books,
fixed 1/3 each — a pre-registered universe, not "the eligible set at scoring time"), plus a
within-horizon max-drawdown estimate and per-sleeve stop proximity, from the books' own CONTINUOUS
equity series. Appends to ``outcomes.jsonl`` (append-only, flock). Never edits the ledger.

# LLM_FORBIDDEN — arithmetic only, no model, no judgement.

Equity sources (read directly, same shape the books themselves write):
* ``defi_conservative`` <- ``data_dir/equity_curve_daily.json`` -> ``daily`` list, bars with
  ``evidenced: true`` only (ADR-554 WP-S03: "conservative equity_curve_daily.json evidenced bars").
* ``defi_balanced`` <- ``data_dir/hy_paper_trading.json`` -> ``daily_history`` list.
* ``defi_aggressive`` <- ``data_dir/lp_paper_trading.json`` -> ``daily_history`` list.

Each bar is ``{"date": "YYYY-MM-DD", "equity": <float>}`` (the hy/lp cycles and the conservative
curve all write this shape). A re-versioning boundary, when the book records one
(``economics_model_boundary``), is listed as an EVENT alongside the series — it does not truncate
the series: "a re-versioned loser cannot escape the track" (WP-S03).

Switching cost: ``data_dir/rebalance_cost_evidence.json`` is inspected for a per-USD cost under one
of ``cost_per_usd`` / ``cost_bps`` / ``avg_cost_bps``. The file does not exist yet anywhere in the
tree at the time this module was written -> NOT_MEASURED, named, until WP-S04's cost evidence is
wired up by its own owner.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.investment_cio import contract, ledger

OUTCOMES_LOCK = ".outcomes.lock"
EQUAL_WEIGHT_UNIVERSE = {sid: 1.0 / len(contract.DEFI_SLEEVES) for sid in contract.DEFI_SLEEVES}
#: finding #16: a due item whose series is missing a bar at/after target_date stays PENDING (no
#: row written at all) for this many days past target_date before it is written as a terminal
#: NOT_MEASURED row with a reason. Retrying forever would be fine in principle, but a decision
#: track that never resolves is itself a silent failure — this names the cutoff instead of hiding it.
PENDING_GRACE_DAYS = 7
#: final-check D2: the target bar must land within this many days of the horizon end, otherwise a
#: 20-day return would be written under a 7-day label (the mirror image of finding N2)
TARGET_TOLERANCE_DAYS = 2

_EQUITY_SOURCES = {
    "defi_conservative": ("equity_curve_daily.json", "daily"),
    "defi_balanced": ("hy_paper_trading.json", "daily_history"),
    "defi_aggressive": ("lp_paper_trading.json", "daily_history"),
}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _outcomes_path(data_dir: Path) -> Path:
    return Path(data_dir) / contract.DATA_SUBDIR / contract.OUTCOMES


def load_equity_series(data_dir: Path, sleeve_id: str) -> Dict[str, Any]:
    """{"series": [{"date","equity"}...] sorted asc, "digest", "state", "events", "reason"}."""
    spec = _EQUITY_SOURCES.get(sleeve_id)
    if spec is None:
        return {"series": [], "digest": None, "state": contract.NOT_MEASURED,
               "reason": f"{sleeve_id} is not a book with a continuous equity series", "events": []}
    filename, list_key = spec
    path = Path(data_dir) / filename
    if not path.exists():
        return {"series": [], "digest": None, "state": contract.NOT_MEASURED,
               "reason": f"file absent: {filename}", "events": []}
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return {"series": [], "digest": None, "state": contract.NOT_MEASURED,
               "reason": f"{filename} unreadable: {exc}", "events": []}
    raw = doc.get(list_key) or []
    if sleeve_id == "defi_conservative":
        raw = [b for b in raw if isinstance(b, dict) and b.get("evidenced") is True]
    bars = [{"date": b.get("date"), "equity": b.get("equity")} for b in raw
            if isinstance(b, dict) and b.get("date") is not None and isinstance(b.get("equity"), (int, float))]
    bars.sort(key=lambda b: b["date"])
    events = []
    boundary = doc.get("economics_model_boundary")
    if boundary:
        events.append({"type": "re_versioning", "detail": boundary})
    if not bars:
        return {"series": [], "digest": None, "state": contract.NOT_MEASURED,
               "reason": f"{filename} has no usable bars in '{list_key}'", "events": events}
    digest = _sha256_hex(_canonical(bars).encode("utf-8"))
    return {"series": bars, "digest": digest, "state": contract.MEASURED, "reason": None, "events": events}


def _anchor_and_target(series: List[dict], rec_date: str, target_date: str) -> Tuple[Optional[dict], Optional[dict]]:
    """ANCHOR is the last bar at/before ``rec_date``. TARGET is the FIRST bar at/after
    ``target_date`` (finding N2 / #16 follow-up) — NOT the last bar at/before ``target_date``.
    The old rule picked whatever bar happened to be closest-but-earlier than the horizon boundary,
    so a book that last reported on day 3 of a 7-day horizon got that 3-day return written and
    labelled as the 7-day one, permanently (``run.py`` never saw it as missing). Returning
    ``None`` here when no bar has reached ``target_date`` yet is what lets the caller keep the
    item PENDING instead."""
    anchor = None
    for b in series:
        if b["date"] <= rec_date:
            anchor = b
        else:
            break
    target = None
    latest_ok = (datetime.strptime(target_date, "%Y-%m-%d")
                 + timedelta(days=TARGET_TOLERANCE_DAYS)).strftime("%Y-%m-%d")
    for b in series:
        if b["date"] >= target_date:
            # a bar far after the horizon end is NOT this horizon's target (D2): keep pending, and after
            # the grace the item is written NOT_MEASURED — never a longer return under a shorter label
            target = b if b["date"] <= latest_ok else None
            break
    return anchor, target


def anchor_equity_from_snapshot(data_dir: Path, snapshot_digest: Optional[str], sleeve_id: str) -> Optional[float]:
    """Finding #16: the ANCHOR for a horizon return is the sleeve's own ``current_equity`` as it
    was recorded in the recommendation's own immutable snapshot — not a live re-read of the
    (mutable, still-growing) equity file weeks later. Returns ``None`` when the snapshot is
    missing, unreadable, or does not carry this sleeve as a real sleeves document (e.g. the
    synthetic ``{"doc": 1}`` snapshots many ledger-mechanics tests use) — the caller then falls
    back to scanning the live series for the bar at/before ``rec_date`` (today's prior behaviour),
    so this is additive, not a breaking change to anchor sourcing when no real snapshot exists."""
    if not snapshot_digest:
        return None
    doc = ledger.load_snapshot(data_dir, snapshot_digest)
    if not isinstance(doc, dict):
        return None
    sleeve = (doc.get("sleeves") or {}).get(sleeve_id)
    if not isinstance(sleeve, dict):
        return None
    return contract.value_of(sleeve.get("current_equity"))


def _bah_leg(series: List[dict], rec_date: str, target_date: str, *,
            anchor_equity: Optional[float] = None) -> Optional[Dict[str, Any]]:
    anchor_bar, target = _anchor_and_target(series, rec_date, target_date)
    equity = anchor_equity if anchor_equity is not None else (
        anchor_bar["equity"] if anchor_bar is not None else None)
    if equity in (None, 0) or target is None:
        return None
    ret = target["equity"] / equity - 1.0
    # N2/N10: when the snapshot supplied the anchor EQUITY, the date must say so too — printing a
    # live series bar's date next to a value that did NOT come from that bar would misrepresent
    # where the number came from.
    anchor_date = "snapshot" if anchor_equity is not None else (
        anchor_bar["date"] if anchor_bar is not None else rec_date)
    return {"return_pct": round(ret, 8),
           "anchor_date": anchor_date,
           "anchor_source": "snapshot_current_equity" if anchor_equity is not None else
                            "series_bar_at_or_before_rec_date",
           "end_date": target["date"]}


def _portfolio_bah(weights: Dict[str, float], series_by_sleeve: Dict[str, dict], rec_date: str,
                   target_date: str, *, anchors_by_sleeve: Optional[Dict[str, Optional[float]]] = None) -> dict:
    """Buy-and-hold: Sigma w_i * (E_i(t+h)/E_i(t) - 1). Cash contributes 0. Books never rebalance
    between each other (each leg is independent)."""
    anchors_by_sleeve = anchors_by_sleeve or {}
    legs = {}
    missing = []
    total = 0.0
    for sid, w in weights.items():
        if w <= 0:
            continue
        if sid == "cash":
            legs[sid] = {"return_pct": 0.0, "weight": w}
            continue
        series = series_by_sleeve.get(sid)
        if series is None or series["state"] != contract.MEASURED:
            missing.append(sid)
            continue
        leg = _bah_leg(series["series"], rec_date, target_date, anchor_equity=anchors_by_sleeve.get(sid))
        if leg is None:
            missing.append(sid)
            continue
        legs[sid] = {**leg, "weight": w}
        total += w * leg["return_pct"]
    if missing:
        return {"state": contract.NOT_MEASURED, "reason": f"no usable bars for: {missing}", "legs": legs}
    return {"state": contract.MEASURED, "return_pct": round(total, 8), "legs": legs}


def _max_drawdown_in_horizon(weights: Dict[str, float], series_by_sleeve: Dict[str, dict], rec_date: str,
                             target_date: str, *, anchors_by_sleeve: Optional[Dict[str, Optional[float]]] = None,
                             target_bar_date: Optional[str] = None) -> dict:
    """N2/N10: uses the SAME anchor (the snapshot's current_equity, when available — the same one
    the return leg used) and the SAME target bar (``target_bar_date``, the first bar at/after
    ``target_date`` that the return leg actually resolved to) as :func:`_bah_leg`/`_portfolio_bah`
    — never a second, independently-sourced anchor or an upper bound that could cut a legitimately
    later target bar out of the path."""
    anchors_by_sleeve = anchors_by_sleeve or {}
    upper_bound = target_bar_date or target_date
    dates = set()
    for sid, w in weights.items():
        if w <= 0 or sid == "cash":
            continue
        s = series_by_sleeve.get(sid)
        if s and s["state"] == contract.MEASURED:
            for b in s["series"]:
                if rec_date <= b["date"] <= upper_bound:
                    dates.add(b["date"])
    if not dates:
        return {"state": contract.NOT_MEASURED, "reason": "no overlapping dated bars among weighted sleeves"}
    anchors = {}
    for sid, w in weights.items():
        if w <= 0 or sid == "cash":
            continue
        snap_anchor = anchors_by_sleeve.get(sid)
        if snap_anchor is not None:
            anchors[sid] = snap_anchor
            continue
        s = series_by_sleeve.get(sid)
        if not s or s["state"] != contract.MEASURED:
            return {"state": contract.NOT_MEASURED, "reason": f"{sid} has no usable series"}
        anchor, _ = _anchor_and_target(s["series"], rec_date, target_date)
        if anchor is None or not anchor["equity"]:
            return {"state": contract.NOT_MEASURED, "reason": f"{sid} has no anchor bar at/before {rec_date}"}
        anchors[sid] = anchor["equity"]
    peak = 1.0
    max_dd = 0.0
    for d in sorted(dates):
        value = 0.0
        ok = True
        for sid, w in weights.items():
            if w <= 0 or sid == "cash":
                value += w
                continue
            s = series_by_sleeve.get(sid)
            bar = next((b for b in s["series"] if b["date"] == d), None)
            if bar is None:
                ok = False
                break
            value += w * (bar["equity"] / anchors[sid])
        if not ok:
            continue
        peak = max(peak, value)
        dd = (peak - value) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return {"state": contract.MEASURED, "max_drawdown_pct": round(max_dd, 8), "n_dates": len(dates)}


def _switching_cost(data_dir: Path) -> dict:
    path = Path(data_dir) / "rebalance_cost_evidence.json"
    if not path.exists():
        return {"state": contract.NOT_MEASURED, "reason": "file absent: data/rebalance_cost_evidence.json"}
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return {"state": contract.NOT_MEASURED, "reason": f"rebalance_cost_evidence.json unreadable: {exc}"}
    for key, scale in (("cost_per_usd", 1.0), ("cost_bps", 1e-4), ("avg_cost_bps", 1e-4)):
        v = doc.get(key)
        if isinstance(v, (int, float)):
            return {"state": contract.MEASURED, "cost_per_usd": v * scale, "source_key": key}
    return {"state": contract.NOT_MEASURED,
           "reason": "rebalance_cost_evidence.json has none of cost_per_usd/cost_bps/avg_cost_bps"}


def _existing_keys(data_dir: Path) -> set:
    path = _outcomes_path(data_dir)
    if not path.exists():
        return set()
    keys = set()
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            keys.add((row.get("recommendation_id"), row.get("horizon_days")))
    return keys


def find_due(data_dir: Path, now: datetime) -> List[dict]:
    """Pure/read-only: ledger entries x horizons whose horizon has fully elapsed and have no
    outcome yet. Never writes."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    existing = _existing_keys(data_dir)
    due = []
    for entry in ledger.read_all(data_dir):
        rec = entry.get("recommendation", {})
        rec_id = rec.get("recommendation_id")
        rec_date_s = rec.get("date")
        if not rec_id or not rec_date_s:
            continue
        rec_date = datetime.strptime(rec_date_s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        for h in contract.POLICY["outcome_horizons_days"]:
            if (rec_id, h) in existing:
                continue
            due_at = rec_date + timedelta(days=h)
            if now >= due_at:
                due.append({"seq": entry["seq"], "recommendation_id": rec_id, "date": rec_date_s,
                           "horizon_days": h, "snapshot_digest": entry.get("snapshot_digest")})
    return due


def distinct_weight_episodes(data_dir: Path) -> int:
    last = None
    episodes = 0
    for entry in ledger.read_all(data_dir):
        w = entry.get("recommendation", {}).get("recommended_weights") or {}
        if not w:
            continue
        if w != last:
            episodes += 1
            last = w
    return episodes


def _rows_tolerant(data_dir: Path) -> List[dict]:
    """All parsed outcome rows, skipping (not raising on) a torn line — outcomes.jsonl is
    append-only evidence, not the decision record (``ledger.jsonl``'s torn-line handling, finding
    #5, is the hard-fail path); a bad line here simply breaks the hash chain at that point, which
    :func:`verify_outcomes_chain` already reports."""
    path = _outcomes_path(data_dir)
    if not path.exists():
        return []
    rows = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def distinct_scored_keys(data_dir: Path) -> int:
    """Finding #7: count distinct (recommendation_id, horizon_days) keys — NEVER raw lines, so a
    race-duplicated (pre-fix) or otherwise repeated row is counted once."""
    rows = _rows_tolerant(data_dir)
    return len({(r.get("recommendation_id"), r.get("horizon_days")) for r in rows})


def _entry_hash_outcome(prev_hash: str, seq: int, outcome_core: dict) -> str:
    payload = {"seq": seq, "prev_hash": prev_hash, "outcome": outcome_core}
    return _sha256_hex((prev_hash + _canonical(payload)).encode("utf-8"))


def verify_outcomes_chain(data_dir: Path) -> dict:
    """Finding #7: outcome rows are hash-chained the same way the ledger is (``seq``/``prev_hash``/
    ``entry_hash`` over the outcome's own fields), so a duplicated-by-race or tampered row is
    DETECTABLE, not merely one line among others."""
    rows = _rows_tolerant(data_dir)
    prev = ledger.GENESIS
    expected_seq = 1
    for row in rows:
        if row.get("seq") != expected_seq or row.get("prev_hash") != prev:
            return {"ok": False, "break_at": row.get("seq"), "entries": len(rows)}
        core = {k: v for k, v in row.items() if k not in ("seq", "prev_hash", "entry_hash")}
        want = _entry_hash_outcome(prev, row["seq"], core)
        if want != row.get("entry_hash"):
            return {"ok": False, "break_at": row.get("seq"), "entries": len(rows)}
        prev = row["entry_hash"]
        expected_seq += 1
    return {"ok": True, "break_at": None, "entries": len(rows)}


def score_due(data_dir: Path, now: datetime, *, lock_timeout_s: float = 5.0) -> dict:
    """Compute + append outcomes for everything due. Finding #7: the ENTIRE read-existing-keys +
    compute + append cycle holds the outcomes lock — :func:`find_due` alone is a pure peek for a
    caller that only wants a count, but a writer must re-read "what's already scored" INSIDE the
    same lock it appends under, or two concurrent writers can both decide the same item is due and
    both append it. Finding #16: an item whose series has no bar at/after its target_date yet
    stays PENDING (no row written, so it is retried next run) for up to
    ``PENDING_GRACE_DAYS`` past target_date; only after that grace does it get a terminal
    NOT_MEASURED row with a reason, so a permanently-silent book does not retry forever either.
    """
    from spa_core.investment_cio.ledger import _FileLock  # internal reuse of the same lock primitive
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    lock_path = Path(data_dir) / contract.DATA_SUBDIR / OUTCOMES_LOCK
    with _FileLock(lock_path, timeout_s=lock_timeout_s):
        due = find_due(data_dir, now_utc)  # re-decided INSIDE the lock — this is the authoritative read
        series_by_sleeve = {sid: load_equity_series(data_dir, sid) for sid in contract.DEFI_SLEEVES}
        switching_cost = _switching_cost(data_dir)
        existing_rows = _rows_tolerant(data_dir)
        prev_hash = existing_rows[-1]["entry_hash"] if existing_rows else ledger.GENESIS
        seq = (existing_rows[-1]["seq"] + 1) if existing_rows else 1
        path = _outcomes_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        scored = 0
        for item in due:
            entry = next((e for e in ledger.read_all(data_dir) if e["seq"] == item["seq"]), None)
            if entry is None:
                continue
            rec = entry["recommendation"]
            rec_date = item["date"]
            target_date = (datetime.strptime(rec_date, "%Y-%m-%d") + timedelta(days=item["horizon_days"])) \
                .strftime("%Y-%m-%d")
            anchors_by_sleeve = {sid: anchor_equity_from_snapshot(data_dir, entry.get("snapshot_digest"), sid)
                                for sid in contract.DEFI_SLEEVES}
            # N2/N10: the per-sleeve TARGET bar (first bar at/after target_date) — the same one
            # _bah_leg resolves to — so the drawdown path is bounded by the actual horizon-end
            # bar used for the return, not cut off at the calendar date if that bar landed later.
            target_bar_dates = []
            for sid in contract.DEFI_SLEEVES:
                s = series_by_sleeve.get(sid)
                if s and s["state"] == contract.MEASURED:
                    _, t = _anchor_and_target(s["series"], rec_date, target_date)
                    if t is not None:
                        target_bar_dates.append(t["date"])
            target_bar_date = max(target_bar_dates) if target_bar_dates else None

            portfolios = {"SEED_SPLIT": rec.get("seed_split_weights") or {},
                         "EQUAL_WEIGHT": dict(EQUAL_WEIGHT_UNIVERSE)}
            if rec.get("recommended_weights"):
                portfolios["RECOMMENDED"] = rec["recommended_weights"]
            results = {}
            drawdowns = {}
            for label, weights in portfolios.items():
                results[label] = _portfolio_bah(weights, series_by_sleeve, rec_date, target_date,
                                                anchors_by_sleeve=anchors_by_sleeve)
                drawdowns[label] = _max_drawdown_in_horizon(weights, series_by_sleeve, rec_date, target_date,
                                                            anchors_by_sleeve=anchors_by_sleeve,
                                                            target_bar_date=target_bar_date)

            any_pending = any(r.get("state") != contract.MEASURED
                             for r in list(results.values()) + list(drawdowns.values()))
            target_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            grace_deadline = target_dt + timedelta(days=PENDING_GRACE_DAYS)
            if any_pending and now_utc < grace_deadline:
                continue  # still pending: a bar on/after target_date may yet land — write nothing (finding #16)

            outcome_core = {
                "schema": contract.SCHEMA_OUTCOME,
                "recommendation_id": item["recommendation_id"],
                "recommendation_date": rec_date,
                "horizon_days": item["horizon_days"],
                "target_date": target_date,
                "scored_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "returns": results,
                "max_drawdown": drawdowns,
                "switching_cost_recommended_vs_seed_split": switching_cost,
                "series_digests": {sid: series_by_sleeve[sid]["digest"] for sid in contract.DEFI_SLEEVES},
                "series_states": {sid: series_by_sleeve[sid]["state"] for sid in contract.DEFI_SLEEVES},
                "events": {sid: series_by_sleeve[sid]["events"] for sid in contract.DEFI_SLEEVES
                          if series_by_sleeve[sid]["events"]},
            }
            if any_pending:
                outcome_core["note"] = (
                    f"written {PENDING_GRACE_DAYS}+ days past target_date with a bar still missing for at "
                    "least one portfolio — treated as a terminal absence (finding #16), not retried further")

            entry_hash = _entry_hash_outcome(prev_hash, seq, outcome_core)
            row = dict(outcome_core)
            row["seq"] = seq
            row["prev_hash"] = prev_hash
            row["entry_hash"] = entry_hash
            row_bytes = (_canonical(row) + "\n").encode("utf-8")
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, row_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)
            prev_hash = entry_hash
            seq += 1
            scored += 1
        return {"due": len(due), "scored": scored, "distinct_weight_episodes": distinct_weight_episodes(data_dir)}
