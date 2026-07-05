"""spa_core/monitoring/signal.py — RTMR (ADR-053) RiskSignal model + fail-closed normalisation.

S10.1 scaffold. The ONE normalised shape every sensor emits and the reaction engine
consumes, so the reaction ladder never parses raw feeds. Deterministic, stdlib-only,
LLM-forbidden, no money-path — this module only builds/normalises signals.

Fail-closed invariant (§1.3, §4): a signal whose data is stale/missing (`staleness_ok=False`)
is FORCED to ``severity="critical"`` regardless of value. Absence of a signal is never
treated as "all clear" — callers must synthesise a critical signal when a sensor is silent.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass, field, replace

INFO = "info"
WARN = "warn"
CRITICAL = "critical"
SEVERITIES = (INFO, WARN, CRITICAL)

_SEV_RANK = {INFO: 0, WARN: 1, CRITICAL: 2}


@dataclass(frozen=True)
class RiskSignal:
    """A single normalised risk observation (ADR-053 §4).

    ``severity`` is authoritative for the reaction engine. Build signals via
    :func:`make_signal` so the fail-closed rule (stale ⇒ critical) is always applied —
    do not hand-construct a signal with ``staleness_ok=False`` and a non-critical severity.
    """

    ts: int                      # unix seconds — moment of measurement
    source: str                  # "peg" | "tvl" | "oracle" | "liquidity" | ...
    scope: str                   # protocol/asset id, e.g. "aave_v3:USDC"
    metric: str                  # "depeg_pct" | "tvl_drop_24h_pct" | ...
    value: float
    severity: str                # info | warn | critical (fail-closed-normalised)
    threshold_crossed: bool
    staleness_ok: bool           # False ⇒ severity forced to critical (fail-closed)
    detail: dict = field(default_factory=dict)  # context only — never used for decisions

    def is_actionable(self) -> bool:
        """warn/critical (or any stale signal) — i.e. the reaction engine should look at it."""
        return self.severity in (WARN, CRITICAL) or not self.staleness_ok

    def is_critical(self) -> bool:
        return self.severity == CRITICAL


def _norm_severity(severity: str) -> str:
    s = str(severity).strip().lower()
    return s if s in SEVERITIES else CRITICAL  # unknown severity is treated as critical (fail-closed)


def make_signal(
    *,
    ts: int,
    source: str,
    scope: str,
    metric: str,
    value: float,
    severity: str,
    threshold_crossed: bool,
    staleness_ok: bool,
    detail: dict | None = None,
) -> RiskSignal:
    """Construct a RiskSignal with the fail-closed rule applied.

    Stale/unknown-severity data ⇒ ``critical``. This is the ONLY sanctioned constructor.
    """
    sev = _norm_severity(severity)
    if not staleness_ok:
        sev = CRITICAL  # fail-closed: stale/missing data outranks any measured value
    return RiskSignal(
        ts=int(ts),
        source=str(source),
        scope=str(scope),
        metric=str(metric),
        value=float(value),
        severity=sev,
        threshold_crossed=bool(threshold_crossed),
        staleness_ok=bool(staleness_ok),
        detail=dict(detail or {}),
    )


def stale_signal(*, ts: int, source: str, scope: str, metric: str = "stale", reason: str = "") -> RiskSignal:
    """A sensor that couldn't produce fresh data emits THIS, not silence (§1.3, §7).

    A dead/blind sensor must surface as a critical signal so the reaction engine de-risks,
    rather than the loop reading no-signal as safe.
    """
    return make_signal(
        ts=ts, source=source, scope=scope, metric=metric, value=0.0,
        severity=CRITICAL, threshold_crossed=True, staleness_ok=False,
        detail={"stale": True, "reason": str(reason)},
    )


def max_severity(signals) -> str:
    """Highest severity across a batch (info if empty). Stale counts as critical."""
    top = INFO
    for s in signals:
        sev = CRITICAL if not s.staleness_ok else s.severity
        if _SEV_RANK.get(sev, 2) > _SEV_RANK[top]:
            top = sev
    return top


def to_dict(sig: RiskSignal) -> dict:
    from dataclasses import asdict
    return asdict(sig)


def from_dict(d: dict) -> RiskSignal:
    """Rebuild a signal from a persisted dict, re-applying the fail-closed rule."""
    return make_signal(
        ts=d.get("ts", 0), source=d.get("source", "unknown"), scope=d.get("scope", ""),
        metric=d.get("metric", ""), value=d.get("value", 0.0),
        severity=d.get("severity", CRITICAL),
        threshold_crossed=d.get("threshold_crossed", False),
        staleness_ok=d.get("staleness_ok", False),
        detail=d.get("detail", {}),
    )


# re-export for callers that want to adjust one field immutably
def with_severity(sig: RiskSignal, severity: str) -> RiskSignal:
    return replace(sig, severity=_norm_severity(severity))
