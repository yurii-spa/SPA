"""Swarm block 4 — L3 Dynamic Leverage Guardian, forward (the brain that sizes risk to weather).

Charter: docs/SWARM_ARCHITECTURE.md · registry: docs/DYNAMIC_LEVERAGE_GUARDIAN.md idea #1
(UPD3/UPD4 verdict). The validated insight: a guardian WIDENS survivable leverage on historical
crises (with-guardian survives 4× where no-guardian liquidates), but "safe leverage" can NEVER be
proven forward — so this brain only ever RECOMMENDS a paper leverage multiplier, with the whole
formula published, and it REFUSES (null) whenever an input it needs is missing, stale or flagged.

    leverage_reco(book) = base_cap(risk_class) × regime_factor × guardian_factor × depth_factor

Inputs (all fleet artifacts this swarm already produces — nothing new is fetched here):
  • data/swarm/funding_regime.json   (block 3)  — GREEN/YELLOW/RED/UNKNOWN carry weather
  • data/swarm/guardian_forward.json (block 1)  — per-book ARMED/DERISKED + live vol_ratio
  • data/rates_desk/depth_at_size.json          — conservative per-market exit-liquidity bound

Fail-CLOSED rules (the charter's "no measurable exit → no leverage", made executable):
  • LIQUIDATION-shaped (levered) books REQUIRE fresh, unflagged exit-depth — else reco = null
    (REFUSED_NO_DEPTH). Today's honest day-1 output: depth is flagged insufficient → the brain
    visibly refuses leverage on every levered book. That refusal IS the feature.
  • A DERISKED guardian → 0.0. A WARMUP/NO_FORWARD guardian (can't see the book) → null.
  • Regime UNKNOWN → carry-shaped books get 0.0 (a broken barometer is not good weather);
    non-carry shapes keep factor 1.0 (funding is not their driver) but RED cuts EVERYTHING
    (systemic risk-off correlates the crypto legs).
  • null means "refuse to recommend" — any consumer MUST read null as 0 exposure.

base_cap by risk_class is a documented JUDGMENT constant (not fitted, not a safety promise):
B → 2.0×, C → 1.5×, D → 1.0× (no leverage on the most tail-heavy class, ever).

ADVISORY / paper-only / OUTSIDE_RISKPOLICY: recommends, never allocates; go-live track untouched.
Deterministic given the input artifacts, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from spa_core.strategy_lab.swarm.common import append_daily_proof
from spa_core.utils.atomic import atomic_save

__all__ = ["run_leverage_brain", "BASE_CAP", "REGIME_FACTORS"]

REPO_ROOT = Path(__file__).resolve().parents[3]
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "leverage_brain.json"
PROOF_NAME = "leverage_brain_proof.jsonl"

REGIME_PATH = SWARM_DIR / "funding_regime.json"
GUARDIAN_PATH = SWARM_DIR / "guardian_forward.json"
DEPTH_PATH = REPO_ROOT / "data" / "rates_desk" / "depth_at_size.json"

# Judgment constants — documented, deterministic, NEVER presented as proven-safe.
BASE_CAP: Dict[str, float] = {"B": 2.0, "C": 1.5, "D": 1.0}
REGIME_FACTORS = {
    # funding-carry books live and die by the funding regime:
    "carry": {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.0, "UNKNOWN": 0.0},
    # other tail shapes: funding is not their driver, but RED = systemic risk-off cuts everyone:
    "other": {"GREEN": 1.0, "YELLOW": 1.0, "RED": 0.5, "UNKNOWN": 1.0},
}
CARRY_SHAPES = {"funding_flip"}
LEVERED_SHAPES = {"liquidation"}  # books whose tail is a liquidation cascade REQUIRE exit depth
VOL_SOFT_START = 1.0   # vol_ratio ≤ 1 → full factor
VOL_HARD_END = 2.0     # the guardian's own derisk threshold; linear decay 1.0 → MIN in between
VOL_MIN_FACTOR = 0.25
REGIME_MAX_AGE_H = 24.0   # hourly agent; older → treat regime as UNKNOWN
GUARDIAN_MAX_AGE_H = 24.0
DEPTH_MAX_AGE_DAYS = 7    # depth artifact older than this cannot license leverage


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


def _regime(now: datetime) -> tuple[str, str]:
    """(regime, provenance) — stale/missing collapses to UNKNOWN, honestly labeled."""
    doc = _load_json(REGIME_PATH)
    if not doc:
        return "UNKNOWN", "funding_regime.json missing/unreadable"
    age = _age_hours(str(doc.get("as_of_utc", "")), now)
    if age is None or age > REGIME_MAX_AGE_H:
        return "UNKNOWN", f"funding_regime stale ({age and round(age, 1)}h > {REGIME_MAX_AGE_H}h)"
    return str(doc.get("regime", "UNKNOWN")), f"live ({round(age, 2)}h old)"


def _guardian_factor(book_view: dict) -> tuple[Optional[float], str]:
    state = book_view.get("state")
    if state == "DERISKED":
        return 0.0, "guardian DERISKED — vol regime hostile"
    if state != "ARMED":
        return None, f"guardian cannot see the book (state={state})"
    ratio = (book_view.get("signal") or {}).get("ratio")
    if not isinstance(ratio, (int, float)):
        return None, "guardian ARMED but no vol signal"
    if ratio <= VOL_SOFT_START:
        return 1.0, f"vol calm (ratio {ratio})"
    if ratio >= VOL_HARD_END:
        return VOL_MIN_FACTOR, f"vol at derisk threshold (ratio {ratio})"
    span = VOL_HARD_END - VOL_SOFT_START
    f = 1.0 - (1.0 - VOL_MIN_FACTOR) * (ratio - VOL_SOFT_START) / span
    return round(f, 4), f"vol elevated (ratio {ratio}) — linear decay"


def _depth_factor(levered: bool, now: datetime) -> tuple[Optional[float], str]:
    """Levered books need fresh, unflagged exit depth; unlevered books don't consume this."""
    if not levered:
        return 1.0, "not a liquidation-shaped book — depth gate not required at 1.0× base"
    doc = _load_json(DEPTH_PATH)
    if not doc:
        return None, "depth_at_size.json missing — no measurable exit → no leverage"
    age_h = _age_hours(str(doc.get("generated_at", "")), now)
    if age_h is None or age_h > DEPTH_MAX_AGE_DAYS * 24:
        return None, (f"exit-depth stale ({age_h and round(age_h / 24, 1)}d > "
                      f"{DEPTH_MAX_AGE_DAYS}d) — no measurable exit → no leverage")
    if doc.get("flagged"):
        return None, ("exit-depth flagged insufficient_contemporaneous_depth — "
                      "no measurable exit → no leverage (refusal-first)")
    return 1.0, "exit depth fresh and unflagged"


def run_leverage_brain(now: Optional[datetime] = None, out_dir: Path = SWARM_DIR) -> dict:
    """One brain pass: a paper leverage recommendation (or an explicit refusal) per book."""
    now = now or datetime.now(timezone.utc)
    guardian = _load_json(GUARDIAN_PATH)
    regime, regime_src = _regime(now)

    books: Dict[str, dict] = {}
    g_age = _age_hours(str((guardian or {}).get("as_of_utc", "")), now)
    guardian_fresh = guardian is not None and g_age is not None and g_age <= GUARDIAN_MAX_AGE_H

    for name, view in ((guardian or {}).get("books") or {}).items():
        risk_class = str(view.get("risk_class") or "D")
        shape = str(view.get("risk_shape") or "")
        levered = shape in LEVERED_SHAPES
        base = BASE_CAP.get(risk_class, 1.0)
        kind = "carry" if shape in CARRY_SHAPES else "other"
        rf = REGIME_FACTORS[kind][regime if regime in REGIME_FACTORS[kind] else "UNKNOWN"]

        if not guardian_fresh:
            gf, g_reason = None, (f"guardian_forward stale/missing "
                                  f"({g_age and round(g_age, 1)}h > {GUARDIAN_MAX_AGE_H}h)")
        else:
            gf, g_reason = _guardian_factor(view)
        df, d_reason = _depth_factor(levered, now)

        factors = {
            "base_cap": base,
            "regime_factor": rf,
            "guardian_factor": gf,
            "depth_factor": df,
        }
        reasons = [f"regime={regime} ({kind} book): ×{rf}", g_reason, d_reason]
        if gf is None or df is None:
            reco, state = None, ("REFUSED_NO_DEPTH" if df is None else "REFUSED_NO_TELEMETRY")
        else:
            reco = round(base * rf * gf * df, 4)
            state = "RECOMMENDED" if reco > 0 else "ZERO_EXPOSURE"
        books[name] = {
            "risk_class": risk_class,
            "risk_shape": shape,
            "levered_shape": levered,
            "leverage_reco": reco,
            "state": state,
            "factors": factors,
            "reasons": reasons,
        }

    doc = {
        "domain": "swarm.leverage_brain",
        "label": "SWARM L3 dynamic-leverage brain / ADVISORY / paper / OUTSIDE_RISKPOLICY",
        "is_advisory": True,
        "outside_riskpolicy": True,
        "as_of_utc": now.isoformat(timespec="seconds"),
        "formula": "leverage_reco = base_cap(risk_class) × regime_factor × guardian_factor × depth_factor",
        "constants": {"base_cap": BASE_CAP, "regime_factors": REGIME_FACTORS,
                      "vol_decay": {"start": VOL_SOFT_START, "end": VOL_HARD_END,
                                    "min_factor": VOL_MIN_FACTOR}},
        "inputs": {"regime": regime, "regime_source": regime_src,
                   "guardian_fresh": guardian_fresh},
        "honest_limits": (
            "paper recommendation only — leverage safety is UNPROVABLE forward (registry UPD4); "
            "base caps are judgment constants, not fitted, not a promise; null = REFUSAL and any "
            "consumer must read it as zero exposure; gap risk is never covered by any factor here."
        ),
        "books": books,
        "summary": {
            "books": len(books),
            "recommended": sum(1 for b in books.values() if b["state"] == "RECOMMENDED"),
            "zero": sum(1 for b in books.values() if b["state"] == "ZERO_EXPOSURE"),
            "refused": sum(1 for b in books.values() if b["state"].startswith("REFUSED")),
        },
    }
    atomic_save(doc, str(out_dir / STATUS_NAME))
    payload = {"regime": regime, **doc["summary"],
               "recos": {n: b["leverage_reco"] for n, b in books.items()}}
    doc["proof_appended"] = append_daily_proof(payload, out_dir / PROOF_NAME,
                                               day=doc["as_of_utc"][:10])
    return doc


def main() -> int:
    doc = run_leverage_brain()
    s = doc["summary"]
    print(f"swarm.leverage_brain: regime={doc['inputs']['regime']} books={s['books']} "
          f"recommended={s['recommended']} zero={s['zero']} refused={s['refused']} "
          f"proof_appended={doc['proof_appended']}")
    for name, b in doc["books"].items():
        print(f"  {name:18s} {b['state']:20s} reco={b['leverage_reco']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
