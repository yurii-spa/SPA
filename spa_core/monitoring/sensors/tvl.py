"""spa_core/monitoring/sensors/tvl.py — RTMR (ADR-053) S10.3b TVL-collapse sensor.

Same shape as the peg sensor; reuses the TVL-drop concept from `red_flag_monitor` (>15%/24h) but
sources current TVL from the multi-source quorum and reads thresholds from `monitoring_config.json`
(§8: tvl.drop_24h_exit, tvl.drop_1h_exit). A protocol bleeding TVL fast is an exit trigger (§5.2).

Fail-closed: no quorum on current TVL, or missing history ⇒ critical stale signal for that scope.
Deterministic, off-chain, LLM-forbidden. Providers/history injected → unit-testable.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.monitoring import signal as S
from spa_core.monitoring.sensors import _multisource as M

_DEFAULT = {"drop_24h_exit": 0.20, "drop_1h_exit": 0.10}
_WARN_FRAC = 0.5  # warn at half the exit drop


def tvl_config(cfg: dict) -> dict:
    base = dict(_DEFAULT)
    base.update(cfg.get("tvl", {}) or {})
    return base


def tvl_severity(drop_24h: float, drop_1h: float, tcfg: dict) -> tuple[str, bool, str]:
    """(severity, crossed, worst_metric) from the larger normalised drop."""
    e24, e1 = float(tcfg["drop_24h_exit"]), float(tcfg["drop_1h_exit"])
    if drop_24h >= e24 or drop_1h >= e1:
        return S.CRITICAL, True, ("tvl_drop_24h_pct" if drop_24h >= e24 else "tvl_drop_1h_pct")
    if drop_24h >= _WARN_FRAC * e24 or drop_1h >= _WARN_FRAC * e1:
        return S.WARN, True, "tvl_drop_24h_pct"
    return S.INFO, False, "tvl_drop_24h_pct"


class TvlSensor:
    """``current_providers``: {scope: {name: callable()->tvl}}; ``history``: {scope: (tvl_1h_ago, tvl_24h_ago)}."""

    source = "tvl"

    def __init__(self, current_providers: dict, history: dict):
        self._cur = dict(current_providers)
        self._hist = dict(history)

    def __call__(self, cfg, now_ts):
        return self.poll(cfg, now_ts)

    def poll(self, cfg: dict, now_ts: int) -> list:
        tcfg = tvl_config(cfg)
        min_q = int(tcfg.get("min_quorum", 2))   # TVL is DeFiLlama-dominated → lower quorum than price
        max_spread = float(tcfg.get("max_spread", 0.05))  # TVL spreads wider than price
        out: list = []
        for scope, providers in self._cur.items():
            q = M.quorum_from(providers, min_quorum=min_q, max_spread=max_spread)
            hist = self._hist.get(scope)
            if callable(hist):        # lazy history provider — fetch at poll, not at build
                try:
                    hist = hist()
                except Exception:  # noqa: BLE001
                    hist = None
            if not q.ok or not hist:
                out.append(S.stale_signal(ts=now_ts, source=self.source, scope=scope,
                                          metric="tvl_drop", reason=(q.reason or "no tvl history")))
                continue
            tvl_1h, tvl_24h = float(hist[0]), float(hist[1])
            drop_1h = max(0.0, (tvl_1h - q.value) / tvl_1h) if tvl_1h > 0 else 0.0
            drop_24h = max(0.0, (tvl_24h - q.value) / tvl_24h) if tvl_24h > 0 else 0.0
            sev, crossed, metric = tvl_severity(drop_24h, drop_1h, tcfg)
            out.append(S.make_signal(
                ts=now_ts, source=self.source, scope=scope, metric=metric,
                value=(drop_24h if metric.endswith("24h_pct") else drop_1h),
                severity=sev, threshold_crossed=crossed, staleness_ok=True,
                detail={"tvl": q.value, "drop_1h": drop_1h, "drop_24h": drop_24h, "n_fresh": q.n_fresh},
            ))
        return out
