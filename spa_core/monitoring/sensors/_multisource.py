"""spa_core/monitoring/sensors/_multisource.py — RTMR (ADR-053) S10.3a quorum/median helper.

Owner direction (§13.1): don't trust a single feed — read **5–10 sources in parallel** and
cross-validate. This is the DataTrust core every deterministic sensor (peg/tvl/oracle) sits on.

Rules (fail-closed by construction — §1.3):
  * A provider that raises / returns None / non-finite is UNAVAILABLE (dropped, not zeroed).
  * If fewer than ``min_quorum`` providers are fresh → NOT ok (caller emits a critical signal).
  * If the fresh readings DISAGREE beyond ``max_spread`` (relative range) → NOT ok (critical).
    Disagreement is never averaged away — a split feed is itself a risk signal.
  * Otherwise the consensus value is the MEDIAN (robust to one bad outlier within tolerance).

Pure + deterministic + stdlib-only + LLM-forbidden. Providers are injected callables so this
is fully unit-testable without touching the network; concrete keyless providers (CoinGecko,
DeFiLlama, public RPC, Chainlink, DEX/CEX) plug in as those callables.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median


@dataclass(frozen=True)
class QuorumResult:
    ok: bool                       # quorum met AND agreement within tolerance
    value: float | None            # median of fresh readings (None when not ok)
    n_fresh: int
    n_total: int
    spread: float                  # relative range (max-min)/|median|; 0 for a single reading
    reason: str = ""               # why not ok (for RiskSignal.detail)
    readings: dict = field(default_factory=dict)  # provider_name → value (fresh only)


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def collect(providers: dict) -> dict:
    """Call each provider callable safely → {name: value} for the ones that returned a finite number.

    ``providers`` maps name → zero-arg callable. A raising/None/non-finite provider is simply
    absent from the result (UNAVAILABLE — never counted, never zeroed).
    """
    out: dict = {}
    for name, fn in providers.items():
        try:
            v = fn()
        except Exception:  # noqa: BLE001 — an unavailable source is dropped, not fatal
            continue
        if _finite(v):
            out[str(name)] = float(v)
    return out


def quorum(readings: dict, *, min_quorum: int = 3, max_spread: float = 0.02) -> QuorumResult:
    """Cross-validate fresh ``{name: value}`` readings into a consensus (median) or a fail-closed miss."""
    n_total = len(readings)
    fresh = {k: v for k, v in readings.items() if _finite(v)}
    n = len(fresh)
    if n == 0:
        return QuorumResult(False, None, 0, n_total, 0.0, "no fresh sources")
    med = float(median(fresh.values()))
    lo, hi = min(fresh.values()), max(fresh.values())
    denom = abs(med) if med != 0 else 1.0
    spread = (hi - lo) / denom
    if n < min_quorum:
        return QuorumResult(False, None, n, n_total, spread,
                            f"quorum {n}/{min_quorum} — too few fresh sources", dict(fresh))
    if spread > max_spread:
        return QuorumResult(False, None, n, n_total, spread,
                            f"sources disagree: spread {spread:.4f} > {max_spread}", dict(fresh))
    return QuorumResult(True, med, n, n_total, spread, "", dict(fresh))


def quorum_from(providers: dict, *, min_quorum: int = 3, max_spread: float = 0.02) -> QuorumResult:
    """Convenience: collect() then quorum() — the shape sensors actually call."""
    return quorum(collect(providers), min_quorum=min_quorum, max_spread=max_spread)
