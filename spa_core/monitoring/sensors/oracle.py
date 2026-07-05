"""spa_core/monitoring/sensors/oracle.py — RTMR (ADR-053) S10.3b oracle-health sensor.

Two failure modes (§3, §5.2): oracle STALENESS (last update too old) and DEVIATION (oracle price
vs market quorum). Either past its config bound (§8: oracle.max_staleness_sec, oracle.max_dev)
=> critical (FREEZE + fail-closed; on persistence the reaction ladder escalates to FULL_EXIT).

Fail-closed: oracle unreadable or market quorum missing => critical stale. Deterministic,
off-chain, LLM-forbidden. Feeds injected → unit-testable.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.monitoring import signal as S
from spa_core.monitoring.sensors import _multisource as M

_DEFAULT = {"max_staleness_sec": 90, "max_dev": 0.01}


def oracle_config(cfg: dict) -> dict:
    base = dict(_DEFAULT)
    base.update(cfg.get("oracle", {}) or {})
    return base


class OracleSensor:
    """``feeds``: {scope: {"oracle": callable()->(price, ts), "market": {name: callable()->price}}}."""

    source = "oracle"

    def __init__(self, feeds: dict):
        self._feeds = dict(feeds)

    def __call__(self, cfg, now_ts):
        return self.poll(cfg, now_ts)

    def poll(self, cfg: dict, now_ts: int) -> list:
        ocfg = oracle_config(cfg)
        max_stale, max_dev = float(ocfg["max_staleness_sec"]), float(ocfg["max_dev"])
        min_q = int(cfg.get("min_quorum", 3))
        max_spread = float(cfg.get("max_spread", 0.02))
        out: list = []
        for scope, feed in self._feeds.items():
            try:
                oracle_price, oracle_ts = feed["oracle"]()
            except Exception as exc:  # noqa: BLE001 — oracle unreadable => danger, not silence
                out.append(S.stale_signal(ts=now_ts, source=self.source, scope=scope,
                                          metric="oracle", reason=f"oracle unreadable: {exc!r}"[:120]))
                continue
            q = M.quorum_from(feed.get("market", {}), min_quorum=min_q, max_spread=max_spread)
            if not q.ok or not (isinstance(oracle_price, (int, float)) and q.value):
                out.append(S.stale_signal(ts=now_ts, source=self.source, scope=scope,
                                          metric="oracle", reason=(q.reason or "bad oracle price")))
                continue
            staleness = max(0.0, float(now_ts) - float(oracle_ts))
            dev = abs(float(oracle_price) / q.value - 1.0)
            # staleness only escalates when OVERDUE (Chainlink stablecoin feeds have a ~24h heartbeat,
            # so a feed being <max_staleness old is NORMAL, not a warn). Deviation keeps warn+critical bands.
            crossed = staleness > max_stale or dev > max_dev
            if crossed:
                sev = S.CRITICAL
            elif dev > 0.5 * max_dev:
                sev = S.WARN
            else:
                sev = S.INFO
            out.append(S.make_signal(
                ts=now_ts, source=self.source, scope=scope,
                metric=("oracle_staleness_sec" if staleness > max_stale else "oracle_dev_pct"),
                value=(staleness if staleness > max_stale else dev),
                severity=sev, threshold_crossed=crossed, staleness_ok=True,
                detail={"staleness_sec": staleness, "dev": dev, "oracle": oracle_price,
                        "market": q.value, "max_staleness_sec": max_stale, "max_dev": max_dev},
            ))
        return out
