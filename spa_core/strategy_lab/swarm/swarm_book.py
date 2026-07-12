"""Swarm block A — the SWARM BOOK: the paper portfolio the swarm actually manages.

Charter: docs/SWARM_ARCHITECTURE.md («Усиление А»). Before this module the swarm only WATCHED:
guardians computed what-if overlays, the brain published recommendations — but no book ever
exercised them, so after 30 forward days the evidence would have been raw tracks + hypothetical
overlays (post-hoc, unconvincing). The swarm book closes that gap: a $100k virtual portfolio
whose DAILY position sizes are the swarm's own decisions, recorded BEFORE the bars they apply to.

CAUSALITY CONTRACT (the whole point):
  • Weights are decided at tick T from the swarm artifacts (brain recos × guardian/RTMR/systemic
    state) and PERSISTED. They apply only to bars that arrive AFTER they were decided.
  • On init the book starts at $100k from the CURRENT date — it never retro-applies today's
    weights to yesterday's bars. History is only ever appended, never recomputed.
  • Every day gets a hash-chained proof line: the decision trail is tamper-evident.

Sizing rules (deterministic, fail-CLOSED):
  • w_raw(book) = brain leverage_reco (null/REFUSED → 0). Stale (>3h) or missing brain → ALL CASH.
  • Guardian DERISKED / RTMR exogenous flag on a book → 0 regardless of the brain's number.
  • Systemic sentinel SYSTEMIC → ALL CASH (the contagion answer).
  • Normalize to Σ≤1 with a per-book concentration cap; the remainder sits in cash at 0%
    (deliberately conservative — idle cash earns nothing here, no fabricated floor yield).
  • A book with no bar for a date contributes 0 return that day (cash-like) and is flagged.
  • Returns are computed WITHIN the forward phase only (the backtest→forward seam is a re-base).

ADVISORY / paper-only / OUTSIDE_RISKPOLICY: virtual dollars, moves nothing, never touches the
go-live track. Deterministic, stdlib-only, restart-survivable. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.swarm.common import append_daily_proof, apy_pct, max_drawdown_pct
from spa_core.utils.atomic import atomic_save

__all__ = ["run_swarm_book", "decide_weights", "NOTIONAL_USD"]

REPO_ROOT = Path(__file__).resolve().parents[3]
AGGRESSIVE_LAB_DIR = REPO_ROOT / "data" / "aggressive_lab"
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "swarm_book.json"
PROOF_NAME = "swarm_book_proof.jsonl"

NOTIONAL_USD = 100_000.0
MAX_BOOK_WEIGHT = 0.25   # concentration cap — no single aggressive book above a quarter
ARTIFACT_MAX_AGE_H = 3.0  # brain/guardian older than this → fail-closed (all cash)
HISTORY_KEEP = 180        # ring buffer of daily rows kept in the status doc


def _load_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text())
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _age_hours(iso_ts: str, now: datetime) -> Optional[float]:
    try:
        ts = datetime.fromisoformat(iso_ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def _forward_series(agg_dir: Path) -> Dict[str, Dict[str, float]]:
    """{book: {date: equity}} — FORWARD phase bars only (the seam is a re-base, not a return)."""
    out: Dict[str, Dict[str, float]] = {}
    if not agg_dir.is_dir():
        return out
    for book_dir in sorted(p for p in agg_dir.iterdir() if p.is_dir()):
        path = book_dir / "realized_series.jsonl"
        if not path.exists():
            continue
        series: Dict[str, float] = {}
        try:
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except ValueError:
                        continue
                    if (isinstance(doc, dict) and doc.get("phase") == "forward"
                            and isinstance(doc.get("equity_usd"), (int, float)) and doc.get("date")):
                        series[str(doc["date"])] = float(doc["equity_usd"])
        except OSError:
            continue
        if series:
            out[book_dir.name] = series
    return out


def decide_weights(brain: Optional[dict], guardian: Optional[dict],
                   now: datetime) -> tuple[Dict[str, float], List[str]]:
    """The swarm's sizing decision for FUTURE bars. Returns (weights, reasons). Fail-CLOSED:
    any missing/stale input → all cash with the reason on record."""
    reasons: List[str] = []
    for name, doc in (("leverage_brain", brain), ("guardian_forward", guardian)):
        age = _age_hours(str((doc or {}).get("as_of_utc", "")), now)
        if doc is None or age is None or age > ARTIFACT_MAX_AGE_H:
            reasons.append(f"{name} missing/stale ({age and round(age, 1)}h) — ALL CASH (fail-closed)")
            return {}, reasons
    systemic = (guardian.get("systemic") or {}).get("state")
    if systemic == "SYSTEMIC":
        reasons.append("systemic sentinel SYSTEMIC — books co-moving + guardians firing → ALL CASH")
        return {}, reasons

    g_books = guardian.get("books") or {}
    raw: Dict[str, float] = {}
    for name, b in (brain.get("books") or {}).items():
        reco = b.get("leverage_reco")
        if not isinstance(reco, (int, float)) or reco <= 0:
            continue
        g = g_books.get(name) or {}
        if g.get("state") == "DERISKED":
            reasons.append(f"{name}: guardian DERISKED → 0")
            continue
        if (g.get("rtmr") or {}).get("exogenous_derisk"):
            reasons.append(f"{name}: RTMR exogenous de-risk → 0")
            continue
        raw[name] = float(reco)

    total = sum(raw.values())
    if total <= 0:
        reasons.append("no positive sized book — ALL CASH")
        return {}, reasons
    weights = {n: round(min(v / total, MAX_BOOK_WEIGHT), 6) for n, v in raw.items()}
    # 6dp rounding can push Σ a hair over 1.0 — the book must NEVER be levered, even by dust:
    # shave the excess off the largest weight (deterministic tie-break by name).
    overflow = round(sum(weights.values()) - 1.0, 6)
    if overflow > 0:
        biggest = min((n for n, v in weights.items()
                       if v == max(weights.values())))
        weights[biggest] = round(weights[biggest] - overflow, 6)
    cash = max(0.0, round(1.0 - sum(weights.values()), 6))
    reasons.append(f"{len(weights)} books sized (cap {MAX_BOOK_WEIGHT}), cash {cash}")
    return weights, reasons


def _apply_pending_bars(state: dict, series: Dict[str, Dict[str, float]]) -> List[dict]:
    """Apply every forward bar newer than last_applied_date using the PERSISTED weights
    (decided before those bars existed). Returns the new daily rows."""
    weights: Dict[str, float] = state.get("weights") or {}
    last = str(state.get("last_applied_date") or "")
    pending = sorted({d for s in series.values() for d in s if d > last})
    rows: List[dict] = []
    for day in pending:
        ret = 0.0
        gaps: List[str] = []
        for book, w in weights.items():
            s = series.get(book) or {}
            if day not in s:
                gaps.append(book)
                continue
            prev_dates = [d for d in s if d < day]
            if not prev_dates:
                gaps.append(book)
                continue
            prev = s[max(prev_dates)]
            if prev > 0:
                ret += w * (s[day] / prev - 1.0)
        state["equity"] = round(state["equity"] * (1.0 + ret), 2)
        state["last_applied_date"] = day
        rows.append({"date": day, "ret_pct": round(ret * 100.0, 6),
                     "equity_usd": state["equity"],
                     "weights_used": dict(weights),
                     "gap_books": gaps})
    return rows


def run_swarm_book(
    agg_dir: Path = AGGRESSIVE_LAB_DIR,
    swarm_dir: Path = SWARM_DIR,
    now: Optional[datetime] = None,
) -> dict:
    """One tick: apply pending bars with yesterday's decision, then decide for tomorrow."""
    now = now or datetime.now(timezone.utc)
    series = _forward_series(agg_dir)
    prior = _load_json(swarm_dir / STATUS_NAME)

    if prior and isinstance(prior.get("equity"), (int, float)) and prior.get("last_applied_date"):
        state = {"equity": float(prior["equity"]),
                 "last_applied_date": str(prior["last_applied_date"]),
                 "weights": prior.get("weights") or {},
                 "history": list(prior.get("history") or [])}
        init_note = None
    else:
        # INIT: start from NOW — never retro-apply today's weights to already-printed bars.
        latest = max((d for s in series.values() for d in s), default="")
        state = {"equity": NOTIONAL_USD, "last_applied_date": latest, "weights": {}, "history": []}
        init_note = (f"book initialized at ${NOTIONAL_USD:,.0f}; tracking starts after "
                     f"{latest or 'first forward bar'} (no retroactive application)")

    new_rows = _apply_pending_bars(state, series)
    state["history"] = (state["history"] + new_rows)[-HISTORY_KEEP:]

    brain = _load_json(swarm_dir / "leverage_brain.json")
    guardian = _load_json(swarm_dir / "guardian_forward.json")
    weights, reasons = decide_weights(brain, guardian, now)
    state["weights"] = weights

    eq_path = [NOTIONAL_USD] + [r["equity_usd"] for r in state["history"]]
    days = len(state["history"])
    doc = {
        "domain": "swarm.swarm_book",
        "label": "SWARM BOOK — the paper portfolio the swarm manages / ADVISORY / OUTSIDE_RISKPOLICY",
        "is_advisory": True,
        "outside_riskpolicy": True,
        "as_of_utc": now.isoformat(timespec="seconds"),
        "equity": state["equity"],
        "last_applied_date": state["last_applied_date"],
        "days_tracked": days,
        "metrics": {"apy_pct": apy_pct(eq_path, days) if days else None,
                    "max_dd_pct": max_drawdown_pct(eq_path) if days else None},
        "weights": weights,
        "cash_weight": max(0.0, round(1.0 - sum(weights.values()), 6)),
        "decision_reasons": reasons,
        "decided_at_utc": now.isoformat(timespec="seconds"),
        "history": state["history"],
        "causality_contract": (
            "weights are decided BEFORE the bars they apply to and persisted; init never "
            "retro-applies; history is append-only; the daily proof chain makes the decision "
            "trail tamper-evident. This book is the exercised evidence that the raw books lack."
        ),
    }
    if init_note:
        doc["init_note"] = init_note
    atomic_save(doc, str(swarm_dir / STATUS_NAME))

    payload = {"equity": state["equity"], "days": days,
               "last_applied_date": state["last_applied_date"],
               "cash_weight": doc["cash_weight"],
               "weights_hash": hashlib.sha256(
                   json.dumps(weights, sort_keys=True).encode()).hexdigest()[:16]}
    doc["proof_appended"] = append_daily_proof(payload, swarm_dir / PROOF_NAME,
                                               day=doc["as_of_utc"][:10])
    return doc


def main() -> int:
    doc = run_swarm_book()
    m = doc["metrics"]
    print(f"swarm.swarm_book: equity=${doc['equity']:,.2f} days={doc['days_tracked']} "
          f"apy={m['apy_pct']}% maxDD={m['max_dd_pct']}% cash={doc['cash_weight']:.2%} "
          f"proof_appended={doc['proof_appended']}")
    for name, w in sorted(doc["weights"].items(), key=lambda kv: -kv[1]):
        print(f"  {name:18s} w={w:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
