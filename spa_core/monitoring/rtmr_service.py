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


def tick(cfg: dict, now_ts: int) -> list:
    signals = SL.run_tick(cfg=cfg, now_ts=now_ts)          # sense + persist + heartbeat
    A.react_and_apply(signals, now_ts=now_ts, cfg=cfg, notify=True)  # emergency-path (PAPER)
    return signals


def main() -> int:  # pragma: no cover — long-running service
    register_default_sensors()
    cfg = SL.load_config()
    interval = int(cfg.get("sense_interval_sec", 45))
    print(f"rtmr_service: started, sensors={SL.registered_sources()}, interval={interval}s (PAPER)")
    while True:
        try:
            tick(cfg, int(time.time()))
        except Exception as exc:  # noqa: BLE001 — never die silently; the dead-man switch also guards
            print(f"rtmr_service: tick failed ({exc!r})")
        time.sleep(interval)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
