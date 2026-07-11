"""Swarm tier-port S2 — lead-time evidence: does the shadow vol-signal LEAD real defense events?

Charter: docs/SWARM_ARCHITECTURE.md («Тир-перенос» S2). S3 (wiring the vol-regime into the live
cycle as an RTMR sensor) is ADR + owner-gated and needs EVIDENCE, not vibes. This harness produces
that evidence deterministically, every run, from two things the fleet already writes:

  • the LIVE conservative track (data/equity_curve_daily.json, read-only) — from which the REAL
    defense-relevant episodes are derived with the ladder's own thresholds:
        DL01_LIKE   daily loss ≤ −2%           (DL-01 single-day halt territory)
        SOFT_LIKE   peak-to-close drawdown ≥ 5%  (SOFT de-risk rung)
        HARD_LIKE   peak-to-close drawdown ≥ 10% (HARD all-cash rung)
  • the shadow guardian's DERISK events on that same track (guardian_forward.json → shadow.
    live_track.derisk_events — causal, recomputed from scratch each tick).

For each real episode: did a shadow DERISK fire in the LOOKBACK_DAYS before it (lead), on the
day (coincident), or not at all (missed)? Shadow DERISKs with no episode within FALSE_ALARM_DAYS
after are counted as false alarms — the cost side of the ledger, reported with the same weight.

HONEST LIMITS: with a calm track this stays NO_EVENTS_YET for a long time — that is the correct
output, not a failure; evidence cannot be manufactured. Day-granular (the curve is daily), so
"lead" means days, not hours. SIGNAL-ONLY ancestry: nothing here acts on anything.

Writes ONLY data/swarm/leadtime_evidence.json. Deterministic, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save

__all__ = ["run_leadtime_evidence", "detect_episodes"]

REPO_ROOT = Path(__file__).resolve().parents[3]
SWARM_DIR = REPO_ROOT / "data" / "swarm"
LIVE_TRACK_PATH = REPO_ROOT / "data" / "equity_curve_daily.json"
GUARDIAN_PATH = SWARM_DIR / "guardian_forward.json"
STATUS_NAME = "leadtime_evidence.json"

DL01_DAILY_LOSS_PCT = -2.0   # DL-01 single-day rung (spa_core/governance)
SOFT_DD_PCT = -5.0           # SOFT de-risk rung (ADR-034/048)
HARD_DD_PCT = -10.0          # HARD all-cash rung
LOOKBACK_DAYS = 14           # a DERISK within this window BEFORE an episode counts as lead
FALSE_ALARM_DAYS = 14        # a DERISK with no episode within this window after = false alarm


def _load_track(path: Path) -> List[dict]:
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    rows = doc.get("daily") if isinstance(doc, dict) else None
    out = []
    for r in rows or []:
        if (isinstance(r, dict) and r.get("date")
                and isinstance(r.get("close_equity"), (int, float))):
            out.append(r)
    out.sort(key=lambda r: str(r["date"]))
    return out


def detect_episodes(rows: List[dict]) -> List[dict]:
    """Derive the real defense-relevant episodes from the daily curve (ladder thresholds)."""
    episodes: List[dict] = []
    peak = float("-inf")
    for r in rows:
        d, eq = str(r["date"]), float(r["close_equity"])
        peak = max(peak, eq)
        dd_pct = (eq / peak - 1.0) * 100.0 if peak > 0 else 0.0
        daily = r.get("daily_return_pct")
        if isinstance(daily, (int, float)) and daily <= DL01_DAILY_LOSS_PCT:
            episodes.append({"date": d, "kind": "DL01_LIKE", "daily_return_pct": daily})
        if dd_pct <= HARD_DD_PCT:
            episodes.append({"date": d, "kind": "HARD_LIKE", "drawdown_pct": round(dd_pct, 4)})
        elif dd_pct <= SOFT_DD_PCT:
            episodes.append({"date": d, "kind": "SOFT_LIKE", "drawdown_pct": round(dd_pct, 4)})
    return episodes


def _days_between(a: str, b: str) -> Optional[int]:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except ValueError:
        return None


def run_leadtime_evidence(
    live_track_path: Path = LIVE_TRACK_PATH,
    guardian_path: Path = GUARDIAN_PATH,
    out_dir: Path = SWARM_DIR,
) -> dict:
    rows = _load_track(live_track_path)
    episodes = detect_episodes(rows)

    derisks: List[str] = []
    try:
        gdoc = json.loads(guardian_path.read_text())
        events = ((gdoc.get("shadow") or {}).get("live_track") or {}).get("derisk_events") or []
        derisks = sorted(str(e["date"]) for e in events
                         if isinstance(e, dict) and e.get("action") == "DERISK" and e.get("date"))
    except (OSError, ValueError):
        pass

    matches: List[dict] = []
    for ep in episodes:
        prior = [d for d in derisks
                 if (n := _days_between(d, ep["date"])) is not None and 0 <= n <= LOOKBACK_DAYS]
        lead = _days_between(prior[-1], ep["date"]) if prior else None
        matches.append({**ep,
                        "shadow_led": bool(prior),
                        "lead_days": lead,
                        "verdict": ("LED" if prior and lead and lead > 0 else
                                    "COINCIDENT" if prior else "MISSED")})

    episode_dates = [e["date"] for e in episodes]
    false_alarms = [d for d in derisks
                    if not any((n := _days_between(d, ed)) is not None
                               and 0 <= n <= FALSE_ALARM_DAYS for ed in episode_dates)]
    # an alarm younger than the window can't be judged yet — exclude it from the false list
    last_track_day = str(rows[-1]["date"]) if rows else None
    pending = [d for d in false_alarms
               if last_track_day and (_days_between(d, last_track_day) or 99) < FALSE_ALARM_DAYS]
    false_alarms = [d for d in false_alarms if d not in pending]

    led = sum(1 for m in matches if m["verdict"] == "LED")
    doc = {
        "domain": "swarm.leadtime_evidence",
        "label": "S2 lead-time evidence for the S3 ADR / SIGNAL-ONLY ancestry / read-only",
        "is_advisory": True,
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thresholds": {"dl01_daily_loss_pct": DL01_DAILY_LOSS_PCT, "soft_dd_pct": SOFT_DD_PCT,
                       "hard_dd_pct": HARD_DD_PCT, "lookback_days": LOOKBACK_DAYS,
                       "false_alarm_days": FALSE_ALARM_DAYS},
        "track_days": len(rows),
        "state": ("NO_TRACK" if not rows else
                  "NO_EVENTS_YET" if not episodes and not derisks else "EVIDENCE"),
        "episodes": matches,
        "shadow_derisk_dates": derisks,
        "false_alarms": false_alarms,
        "pending_alarms": pending,
        "score": {"episodes": len(episodes), "led": led,
                  "coincident": sum(1 for m in matches if m["verdict"] == "COINCIDENT"),
                  "missed": sum(1 for m in matches if m["verdict"] == "MISSED"),
                  "false_alarms": len(false_alarms)},
        "honest_note": (
            "evidence accrues only when the market provides events — a long NO_EVENTS_YET on a "
            "calm track is the honest state, not a malfunction. The S3 case needs LED > 0 with "
            "few false alarms; MISSED episodes or an alarm-heavy ledger argue AGAINST wiring the "
            "signal in. Both outcomes are findings."
        ),
    }
    atomic_save(doc, str(out_dir / STATUS_NAME))
    return doc


def main() -> int:
    doc = run_leadtime_evidence()
    s = doc["score"]
    print(f"swarm.leadtime_evidence: state={doc['state']} track_days={doc['track_days']} "
          f"episodes={s['episodes']} led={s['led']} missed={s['missed']} "
          f"false_alarms={s['false_alarms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
