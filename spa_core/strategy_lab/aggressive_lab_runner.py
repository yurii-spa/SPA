"""
spa_core/strategy_lab/aggressive_lab_runner.py — the Lane 3 STANDING DAILY runner for the
Aggressive Strategy Paper Lab.

This is the orchestration entry-point the launchd agent (com.spa.aggressive_lab) calls once per
UTC day. It:

  1. ACCRUES the lab's forward paper track (Lane 1) — grows data/aggressive_lab/<id>/realized_series
     .jsonl one point per day. (Delegated to Lane 1's accrual producer if present.)
  2. RE-RANKS the honest multi-metric scorecard (Lane 2) — rewrites data/aggressive_lab/scorecard
     .json with net return AND Sharpe/Calmar AND max-DD AND tail-in-stress AND risk-class AND a
     trustworthy flag AND verdict. (Delegated to Lane 2's ranking producer if present.)

DECOUPLING (the lane boundary)
══════════════════════════════
This runner is Lane 3. It does NOT implement the accrual math (Lane 1) or the ranking math
(Lane 2) — it CALLS them. They are discovered by a tolerant import so this surface lane can ship
and be deployed NOW, before Lane 1/2 finish their producers:

  • Lane 1 accrual is looked up as  spa_core.strategy_lab.aggressive_lab.accrual:run_daily  (or
    .paper:tick / .lab:run_daily — any of those names).
  • Lane 2 ranking is looked up as  spa_core.strategy_lab.aggressive_lab.scorecard:rebuild  (or
    .ranking:rebuild / .scorecard:build / .scorecard:run).

If a producer is NOT importable yet, that step is recorded as "producer_not_available" — NO
fabricated track point and NO fabricated leaderboard. The status file says so honestly.

GUARDRAILS (non-negotiable)
═══════════════════════════
  • ISOLATED / ADVISORY — never touches the go-live track (data/equity_curve_daily.json) or live
    allocation. The runner reads/writes ONLY under data/aggressive_lab/. The pre-deploy gate
    additionally hash-asserts the go-live track is byte-unchanged by the sandboxed run.
  • Idempotent per UTC day — re-running the same day is a no-op-or-refresh (the producers are
    expected to be per-day idempotent; the runner records the day it last ran and skips a second
    full pass unless --force).
  • Fail-CLOSED — any producer error is caught and recorded; the runner still exits 0 (a recorded
    gap is a successful tick), and the prior scorecard/track are left untouched.
  • stdlib-only, deterministic, atomic. LLM-FORBIDDEN.

Run (one tick):
    python3 -m spa_core.strategy_lab.aggressive_lab_runner
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import importlib
import json
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.aggressive_lab.runner")

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude


def _data_dir() -> Path:
    """The active data dir. Honours SPA_DATA_DIR (the pre-deploy gate points it at a sandbox), so
    the sandboxed gate run writes its outputs into the sandbox, never into the canonical data/."""
    return Path(os.environ.get("SPA_DATA_DIR", str(_REPO_ROOT / "data")))


def _lab_dir() -> Path:
    d = _data_dir() / "aggressive_lab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── tolerant producer discovery (Lane 1 accrual + Lane 2 ranking) ────────────────────────────────
# Each candidate is "module:attr"; the first importable one wins. None → step records
# "producer_not_available" (honest), never fabricates.
# The live Lane-1 accrual producer is run.PaperService().tick() (forward paper track); the
# fallbacks cover earlier/alternate names so this surface lane never hard-couples to one symbol.
_ACCRUAL_CANDIDATES = (
    "spa_core.strategy_lab.aggressive_lab.run:run_daily",
    "spa_core.strategy_lab.aggressive_lab.accrual:run_daily",
    "spa_core.strategy_lab.aggressive_lab.paper:run_daily",
    "spa_core.strategy_lab.aggressive_lab.paper:tick",
)
# The live Lane-2 ranking producer is scorecard.build_scorecard(write=True).
_RANKING_CANDIDATES = (
    "spa_core.strategy_lab.aggressive_lab.scorecard:build_scorecard",
    "spa_core.strategy_lab.aggressive_lab.scorecard:rebuild",
    "spa_core.strategy_lab.aggressive_lab.ranking:rebuild",
    "spa_core.strategy_lab.aggressive_lab.scorecard:build",
)
# Special-case: the Lane-1 PaperService.tick() is an instance method, not a module function — handle
# it explicitly so the standing tick actually advances the forward track.
_PAPER_SERVICE_SPEC = "spa_core.strategy_lab.aggressive_lab.run:PaperService"


def _resolve(candidates) -> Optional[Callable]:
    for spec in candidates:
        mod_name, _, attr = spec.partition(":")
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001 — not built yet / optional
            continue
        fn = getattr(mod, attr, None)
        if callable(fn):
            return fn
    return None


def _call_producer(fn: Callable, as_of: str) -> dict:
    """Call a producer tolerantly. Never raises — returns a {ok, detail} record. Each producer
    writes its own outputs under data/aggressive_lab/. We probe the kwargs it accepts (data_dir=,
    as_of=) so the run HONOURS SPA_DATA_DIR — critical so the sandboxed pre-deploy gate run writes
    to the sandbox, not the canonical data/."""
    import inspect
    try:
        params = set()
        try:
            params = set(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            pass
        kwargs = {}
        if "data_dir" in params:
            kwargs["data_dir"] = _lab_dir()        # honour SPA_DATA_DIR (sandbox-safe)
        if "as_of" in params:
            kwargs["as_of"] = as_of
        res = fn(**kwargs)
        return {"ok": True, "detail": _summarize(res)}
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: a producer error is a recorded gap
        log.warning("aggressive-lab producer %s failed: %s", getattr(fn, "__name__", fn), exc)
        return {"ok": False, "detail": f"producer error: {exc}"}


def _accrue(as_of: str) -> dict:
    """Run the Lane-1 forward-track accrual for one day. Prefers a module-level run_daily; else uses
    the PaperService().tick() instance method (the live Lane-1 service). Never raises (fail-CLOSED)."""
    fn = _resolve(_ACCRUAL_CANDIDATES)
    if fn is not None:
        return _call_producer(fn, as_of)
    # PaperService.tick() — instance method, the live Lane-1 accrual.
    mod_name, _, attr = _PAPER_SERVICE_SPEC.partition(":")
    try:
        cls = getattr(importlib.import_module(mod_name), attr, None)
    except Exception:  # noqa: BLE001
        cls = None
    if cls is None:
        return {"ok": False, "detail": "producer_not_available (Lane 1 accrual not built yet)"}
    try:
        res = cls().tick()
        return {"ok": True, "detail": _summarize(res)}
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED
        log.warning("aggressive-lab PaperService.tick failed: %s", exc)
        return {"ok": False, "detail": f"producer error: {exc}"}


def _summarize(res) -> str:
    if res is None:
        return "ok"
    if isinstance(res, dict):
        keys = ",".join(sorted(res.keys())[:6])
        return f"dict[{keys}]"
    return str(res)[:120]


def _status_path() -> Path:
    return _lab_dir() / "runner_status.json"


def run_daily(as_of: Optional[str] = None, force: bool = False) -> dict:
    """One standing-agent tick: accrue (Lane 1) + re-rank (Lane 2), idempotent per UTC day,
    fail-CLOSED. Returns the status dict it also persists to data/aggressive_lab/runner_status.json.
    NEVER touches the go-live track / live allocation."""
    day = as_of or _utc_today()
    status_p = _status_path()
    prev = atomic_load(str(status_p), default={})
    prev = prev if isinstance(prev, dict) else {}

    already = (not force) and prev.get("last_run_date") == day and prev.get("completed") is True
    if already:
        log.info("aggressive-lab runner: already ran for %s (idempotent skip)", day)
        prev["idempotent_skip"] = True
        prev["checked_at"] = _utc_now_iso()
        atomic_save(prev, str(status_p))
        return prev

    ranking_fn = _resolve(_RANKING_CANDIDATES)

    accrual = _accrue(day)
    ranking = (_call_producer(ranking_fn, day) if ranking_fn
               else {"ok": False, "detail": "producer_not_available (Lane 2 ranking not built yet)"})

    # If Lane 2 has no producer yet, ensure an HONEST scorecard exists so the surface fail-closes
    # to "unavailable" rather than 404 — we NEVER write a fabricated leaderboard.
    if not ranking["ok"]:
        _ensure_honest_unavailable_scorecard(day, ranking["detail"])

    status = {
        "id": "aggressive_lab_runner",
        "generated_at": _utc_now_iso(),
        "as_of": day,
        "last_run_date": day,
        "completed": True,
        # ADVISORY stamps — the runner output, like the surface, is OUTSIDE RiskPolicy.
        "advisory": True,
        "outside_riskpolicy": True,
        "live_eligible": False,
        "touches_golive_track": False,
        "owner_select_enabled": _select_enabled(),
        "accrual": accrual,
        "ranking": ranking,
        "note": ("Aggressive-Lab standing daily tick — ADVISORY/paper-only. Grows the forward track "
                 "(Lane 1) + re-ranks the honest scorecard (Lane 2). NEVER touches the go-live track "
                 "or live allocation. Fail-CLOSED: a missing producer is recorded, never fabricated."),
    }
    atomic_save(status, str(status_p))
    return status


def _ensure_honest_unavailable_scorecard(day: str, reason: str) -> None:
    """Write an HONEST 'scorecard not yet produced' file IF none exists — so the surface fail-closes
    to a labeled 'unavailable' rather than a 404, WITHOUT fabricating any ranking. Never overwrites a
    real scorecard produced by Lane 2."""
    p = _lab_dir() / "scorecard.json"
    if p.exists():
        return  # a real (or prior) scorecard is present — do NOT clobber it
    doc = {
        "generated_at": _utc_now_iso(),
        "as_of": day,
        "model": "aggressive_lab_scorecard",
        "advisory": True,
        "outside_riskpolicy": True,
        "live_eligible": False,
        "available": False,
        "trustworthy": False,
        "unavailable_reason": reason,
        "rwa_floor_pct": None,
        "strategies": [],  # NEVER a fabricated leaderboard
    }
    atomic_save(doc, str(p))


def _select_enabled() -> bool:
    return os.environ.get("SPA_AGGRESSIVE_LAB_SELECT", "").strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    ap = argparse.ArgumentParser(description="Aggressive-Lab standing daily runner (advisory).")
    ap.add_argument("--as-of", default=None, help="UTC day YYYY-MM-DD (default: today)")
    ap.add_argument("--force", action="store_true", help="re-run even if already ran today")
    args = ap.parse_args()
    st = run_daily(as_of=args.as_of, force=args.force)
    print(json.dumps(st, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
