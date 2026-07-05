"""spa_core/monitoring/sense_loop.py — RTMR (ADR-053) S10.2 continuous sense-loop.

The persistent poller (interval from config, §7). Each tick it runs every registered sensor,
collects normalised RiskSignals, and writes ``signals/latest.json`` + appends ``signal_log.json``,
then stamps a heartbeat. It does NOT move capital and takes no reaction decision — it only senses.

Fail-closed (§1.3, §1.7): if a sensor raises or returns nothing, the loop synthesises a
``stale_signal`` (critical) for that source — a blind/dead sensor surfaces as CRITICAL, never
as silence. The heartbeat lets the ops dead-man-switch (later sprint) detect a dead loop.

Deterministic, stdlib-only, LLM-forbidden. Sensors register via ``register_sensor`` (S10.3).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from spa_core.monitoring import signal as S

_ROOT = Path(__file__).resolve().parents[2]
_MON_DIR = _ROOT / "data" / "monitoring"
_SIGNALS_DIR = _MON_DIR / "signals"
_LATEST = _SIGNALS_DIR / "latest.json"
_LOG = _MON_DIR / "signal_log.json"
_HEARTBEAT = _MON_DIR / "sense_heartbeat.json"
_CONFIG = _MON_DIR / "monitoring_config.json"

_LOG_MAX = 2000  # ring-buffer bound on the append-only signal log

# Sensor registry. A sensor is a callable ``poll(cfg, now_ts) -> list[RiskSignal]`` carrying a
# ``.source`` attribute. S10.3 sensors register here; empty until then (loop still runs + heartbeats).
_SENSORS: list = []


def register_sensor(sensor) -> None:
    """Register a sensor callable (idempotent by .source)."""
    src = getattr(sensor, "source", None)
    if src is not None:
        _SENSORS[:] = [s for s in _SENSORS if getattr(s, "source", None) != src]
    _SENSORS.append(sensor)


def registered_sources() -> list:
    return [getattr(s, "source", "unknown") for s in _SENSORS]


def load_config() -> dict:
    try:
        with open(_CONFIG, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 — fail-closed default: aggressive interval, short staleness
        return {"sense_interval_sec": 45, "staleness_max_sec": 120}


def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(str(path), obj)
        return
    except Exception:  # noqa: BLE001
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)


def run_tick(sensors=None, cfg: dict | None = None, *, now_ts: int) -> list:
    """One sense pass: poll every sensor (fail-closed on death), persist, heartbeat. Returns signals."""
    sensors = _SENSORS if sensors is None else sensors
    cfg = cfg if cfg is not None else load_config()
    def _poll(sensor):
        src = getattr(sensor, "source", "unknown")
        try:
            out = sensor.poll(cfg, now_ts) if hasattr(sensor, "poll") else sensor(cfg, now_ts)
            if not out:
                return [S.stale_signal(ts=now_ts, source=src, scope=src, reason="sensor produced no signal")]
            return list(out)
        except Exception as exc:  # noqa: BLE001 — a dead sensor MUST surface as critical, not crash the loop
            return [S.stale_signal(ts=now_ts, source=src, scope=src, reason=f"sensor raised: {exc!r}"[:200])]

    signals: list = []
    if sensors:
        import concurrent.futures as _cf
        per_sensor_timeout = int(cfg.get("sensor_timeout_sec", 25))  # a slow sensor must not block the tick
        sensors = list(sensors)
        with _cf.ThreadPoolExecutor(max_workers=min(8, len(sensors))) as ex:
            futs = {ex.submit(_poll, sensor): sensor for sensor in sensors}
            for fut, sensor in futs.items():
                src = getattr(sensor, "source", "unknown")
                try:
                    signals.extend(fut.result(timeout=per_sensor_timeout))
                except Exception:  # noqa: BLE001 — timeout/error → treat the whole sensor as stale (fail-closed)
                    signals.append(S.stale_signal(ts=now_ts, source=src, scope=src,
                                                  reason="sensor exceeded time budget"))
    _persist(signals, now_ts)
    _heartbeat(now_ts, len(sensors))
    return signals


def _persist(signals: list, now_ts: int) -> None:
    snapshot = {
        "ts": int(now_ts),
        "max_severity": S.max_severity(signals),
        "count": len(signals),
        "signals": [S.to_dict(s) for s in signals],
    }
    _atomic_write(_LATEST, snapshot)
    # append-only log (ring-buffered)
    log = []
    try:
        with open(_LOG, encoding="utf-8") as fh:
            log = json.load(fh)
            if not isinstance(log, list):
                log = []
    except Exception:  # noqa: BLE001
        log = []
    log.append(snapshot)
    if len(log) > _LOG_MAX:
        log = log[-_LOG_MAX:]
    _atomic_write(_LOG, log)


def _heartbeat(now_ts: int, n_sensors: int) -> None:
    _atomic_write(_HEARTBEAT, {"ts": int(now_ts), "sensors": int(n_sensors), "alive": True})


def heartbeat_age_sec(now_ts: int) -> float | None:
    """Seconds since the last heartbeat, or None if never/unreadable (caller treats None as stale)."""
    try:
        with open(_HEARTBEAT, encoding="utf-8") as fh:
            hb = json.load(fh)
        return max(0.0, float(now_ts) - float(hb.get("ts", 0)))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:  # pragma: no cover — long-running service entrypoint
    cfg = load_config()
    interval = int(cfg.get("sense_interval_sec", 45))
    while True:
        try:
            run_tick(cfg=cfg, now_ts=int(time.time()))
        except Exception as exc:  # noqa: BLE001 — never let the loop die silently
            print(f"sense_loop: tick failed ({exc!r})")
        time.sleep(interval)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
