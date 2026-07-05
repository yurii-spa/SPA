"""spa_core/monitoring/sensors/liquidity.py — RTMR (ADR-053) S10.3b exit-liquidity sensor.

Measures whether a position can actually be EXITED: ``liq_ratio = exit_depth_usd / position_usd``
across the multi-source depth quorum. Below ``liquidity.min_liq_ratio`` (§8, default 2.0) the reaction
ladder REDUCEs until the ratio recovers, then FULL_EXIT if it doesn't (§5.2).

Fail-closed: no depth quorum, or unknown position size => critical stale. Deterministic, off-chain,
LLM-forbidden. Depth providers / sizes injected → unit-testable.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.monitoring import signal as S
from spa_core.monitoring.sensors import _multisource as M


class LiquiditySensor:
    """``depth_providers``: {scope: {name: callable()->exit_depth_usd}}; ``position_usd``: {scope: usd}."""

    source = "liquidity"

    def __init__(self, depth_providers: dict, position_usd: dict):
        self._depth = dict(depth_providers)
        self._pos = dict(position_usd)

    def __call__(self, cfg, now_ts):
        return self.poll(cfg, now_ts)

    def poll(self, cfg: dict, now_ts: int) -> list:
        lcfg = cfg.get("liquidity", {}) or {}
        min_ratio = float(lcfg.get("min_liq_ratio", 2.0))
        min_q = int(lcfg.get("min_quorum", 1))   # depth proxy is DeFiLlama single-source
        max_spread = float(lcfg.get("max_spread", 0.10))
        out: list = []
        for scope, providers in self._depth.items():
            pos = float(self._pos.get(scope, 0.0))
            q = M.quorum_from(providers, min_quorum=min_q, max_spread=max_spread)
            if not q.ok or pos <= 0:
                out.append(S.stale_signal(ts=now_ts, source=self.source, scope=scope,
                                          metric="liq_ratio", reason=(q.reason or "unknown position size")))
                continue
            ratio = q.value / pos
            crossed = ratio < min_ratio
            sev = S.CRITICAL if ratio < 0.5 * min_ratio else (S.WARN if crossed else S.INFO)
            out.append(S.make_signal(
                ts=now_ts, source=self.source, scope=scope, metric="liq_ratio",
                value=ratio, severity=sev, threshold_crossed=crossed, staleness_ok=True,
                detail={"exit_depth_usd": q.value, "position_usd": pos, "min_liq_ratio": min_ratio, "n_fresh": q.n_fresh},
            ))
        return out
