"""spa_core/monitoring/rtmr_service.py — RTMR (ADR-053) sense+emergency service entrypoint.

Persistent launchd service (com.spa.rtmr_sense). Each tick (interval from monitoring_config.json):
  1. run every registered sensor → normalise to RiskSignals, persist signals/latest.json (+heartbeat),
  2. run the deterministic reaction ladder and apply it in PAPER mode (posture + reaction_log +
     Telegram alert ON CHANGE only). **Never moves capital** (§13.3). Posture is honored by the
     rebalance-loop only once S10.5b is wired (owner-gated) — until then a de-risk writes a dormant
     posture + an early-warning alert. Fail-closed, LLM-forbidden, deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import time

from spa_core.monitoring import actions as A
from spa_core.monitoring import sense_loop as SL
from spa_core.monitoring.sensors.build import register_default_sensors


_SEV_RANK = {"info": 0, "warn": 1, "critical": 2}


def _worst_by_scope(signals) -> dict:
    """scope → worst current severity (stale counts as critical) — for posture re-entry."""
    out: dict = {}
    for s in signals:
        sev = "critical" if not s.staleness_ok else s.severity
        if _SEV_RANK.get(sev, 2) > _SEV_RANK.get(out.get(s.scope, "info"), 0):
            out[s.scope] = sev
        out.setdefault(s.scope, sev)
    return out


def tick(cfg: dict, now_ts: int) -> list:
    from spa_core.monitoring import posture as P
    signals = SL.run_tick(cfg=cfg, now_ts=now_ts)          # sense + persist + heartbeat
    A.react_and_apply(signals, now_ts=now_ts, cfg=cfg, notify=True)  # emergency-path (PAPER): add de-risks
    # re-entry / self-clear: drop postures whose scope has recovered for N clean ticks (§5.2)
    reentry = int((cfg.get("peg", {}) or {}).get("reentry_periods", 4))
    pos = P.load_posture()
    new_pos, cleared = P.reconcile_recovered(pos, _worst_by_scope(signals), now_ts=now_ts,
                                             reentry_periods=reentry)
    if cleared:
        P.save_posture(new_pos, now_ts=now_ts)
    return signals


def main() -> int:  # pragma: no cover — long-running service
    register_default_sensors()
    cfg = SL.load_config()
    interval = int(cfg.get("sense_interval_sec", 45))
    print(f"rtmr_service: started, sensors={SL.registered_sources()}, interval={interval}s (PAPER)", flush=True)
    while True:
        try:
            tick(cfg, int(time.time()))
        except Exception as exc:  # noqa: BLE001 — never die silently; the dead-man switch also guards
            print(f"rtmr_service: tick failed ({exc!r})")
        time.sleep(interval)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
