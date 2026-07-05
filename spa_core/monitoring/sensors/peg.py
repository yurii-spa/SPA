"""spa_core/monitoring/sensors/peg.py — RTMR (ADR-053) S10.3b peg (depeg) sensor.

Reuses the project's peg concept (cf. `peg_monitor` / `risk_monitor` depeg detectors) but sources
its price from the multi-source quorum (§13.1, 5–10 keyless feeds) instead of a single feed, and
classifies severity from `monitoring_config.json` (§8) — no hardcoded thresholds.

Per scope (e.g. "aave_v3:USDC") it computes ``depeg_pct = |median_price/peg − 1|`` across the fresh,
agreeing sources and maps it to a RiskSignal severity via the peg ladder (reduce_at / exit_at).
Fail-closed: if the sources can't form a quorum or disagree, it emits a **critical** stale signal
for that scope — a price it can't trust is treated as danger, not smoothed over.

Deterministic, read-only, off-chain, LLM-forbidden. Price providers are injected (name → callable),
so this is fully unit-testable; concrete keyless providers (CoinGecko, DeFiLlama, Chainlink on-chain,
DEX/CEX public) plug in as those callables.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.monitoring import signal as S
from spa_core.monitoring.sensors import _multisource as M

_DEFAULT_PEG = {"reduce_at": 0.005, "exit_at": 0.010}
_DEFAULT_QUORUM = 3
_DEFAULT_MAX_SPREAD = 0.02


def peg_config(cfg: dict, scope: str) -> dict:
    """peg thresholds for a scope, applying per-asset overrides (§8 'overrides')."""
    base = dict(_DEFAULT_PEG)
    base.update(cfg.get("peg", {}) or {})
    ov = ((cfg.get("overrides", {}) or {}).get(scope, {}) or {}).get("peg", {}) or {}
    base.update(ov)
    return base


def peg_severity(depeg_pct: float, peg_cfg: dict) -> tuple[str, bool]:
    """Map a depeg magnitude to (severity, threshold_crossed) via the peg ladder (§5.2)."""
    if depeg_pct >= float(peg_cfg["exit_at"]):
        return S.CRITICAL, True     # ≥ exit_at → FULL_EXIT territory
    if depeg_pct >= float(peg_cfg["reduce_at"]):
        return S.WARN, True         # ≥ reduce_at → REDUCE + TIGHTEN
    return S.INFO, False


class PegSensor:
    """A peg sensor over a set of scopes, each with its own multi-source price providers.

    ``price_providers``: ``{scope: {provider_name: callable() -> price}}``
    ``peg_targets``:      ``{scope: peg_value}`` (defaults to 1.0 for stablecoins)
    """

    source = "peg"

    def __init__(self, price_providers: dict, peg_targets: dict | None = None):
        self._providers = dict(price_providers)
        self._peg = dict(peg_targets or {})

    def __call__(self, cfg: dict, now_ts: int) -> list:
        return self.poll(cfg, now_ts)

    def poll(self, cfg: dict, now_ts: int) -> list:
        min_q = int(cfg.get("min_quorum", _DEFAULT_QUORUM))
        max_spread = float(cfg.get("max_spread", _DEFAULT_MAX_SPREAD))
        out: list = []
        for scope, providers in self._providers.items():
            q = M.quorum_from(providers, min_quorum=min_q, max_spread=max_spread)
            if not q.ok:
                # fail-closed: an untrusted price is danger, not a smoothed number
                out.append(S.stale_signal(
                    ts=now_ts, source=self.source, scope=scope, metric="depeg_pct",
                    reason=q.reason,
                ))
                continue
            peg = float(self._peg.get(scope, 1.0)) or 1.0
            depeg = abs(q.value / peg - 1.0)
            pcfg = peg_config(cfg, scope)
            sev, crossed = peg_severity(depeg, pcfg)
            out.append(S.make_signal(
                ts=now_ts, source=self.source, scope=scope, metric="depeg_pct",
                value=depeg, severity=sev, threshold_crossed=crossed, staleness_ok=True,
                detail={"price": q.value, "peg": peg, "n_fresh": q.n_fresh,
                        "spread": q.spread, "exit_at": pcfg["exit_at"], "reduce_at": pcfg["reduce_at"]},
            ))
        return out
