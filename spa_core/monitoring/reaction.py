"""spa_core/monitoring/reaction.py — RTMR (ADR-053) S10.4 deterministic reaction ladder.

Triggers → actions, pure threshold logic (§5). **LLM_FORBIDDEN, de-risk-only (§1.4):** every action
can only REDUCE risk (freeze / tighten / reduce / exit / market-exit) — never raise exposure. That
is asserted here and property-tested. No capital math lives here; actions are applied by `actions.py`
(paper: posture + log + Telegram). This ladder COMPOSES the existing kill-switch / cycle-gates
semantics rather than adding a parallel one (see docs/RTMR_INTEGRATION_MAP.md).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass, field

from spa_core.monitoring import signal as S

# Action types (§5.1) — all strictly de-risk
FREEZE = "FREEZE"                # stop new allocation, hold
TIGHTEN = "TIGHTEN"             # lower allowed cap/range
REDUCE = "REDUCE"              # cut position to `pct`
FULL_EXIT = "FULL_EXIT"        # 100% out → rotate to safe
ROTATE_TO_SAFE = "ROTATE_TO_SAFE"
MARKET_EXIT = "MARKET_EXIT"    # whole portfolio → defensive, wait
_DE_RISK_ONLY = {FREEZE, TIGHTEN, REDUCE, FULL_EXIT, ROTATE_TO_SAFE, MARKET_EXIT}

PORTFOLIO = "PORTFOLIO"


@dataclass(frozen=True)
class Action:
    kind: str
    scope: str
    pct: float | None = None      # for REDUCE/TIGHTEN: target max exposure fraction (0..1)
    reason: str = ""
    detail: dict = field(default_factory=dict)

    def is_de_risk_only(self) -> bool:
        # de-risk vocabulary only, and any cap must be a REDUCTION (<= 1.0, never an increase)
        if self.kind not in _DE_RISK_ONLY:
            return False
        if self.pct is not None and not (0.0 <= self.pct <= 1.0):
            return False
        return True


def match_rule(sig: S.RiskSignal, cfg: dict) -> Action | None:
    """Pure signal→action mapping (§5.2). Returns None for non-actionable (info & fresh)."""
    # fail-closed: a stale/blind sensor de-risks by freezing the scope
    if not sig.staleness_ok:
        return Action(FREEZE, sig.scope, reason=f"stale/blind {sig.source} sensor")
    if sig.severity == S.INFO:
        return None
    critical = sig.severity == S.CRITICAL
    src = sig.source
    if src in ("peg", "tvl", "liquidity"):
        return (Action(FULL_EXIT, sig.scope, reason=f"{src} critical")
                if critical else Action(REDUCE, sig.scope, pct=0.5, reason=f"{src} warn"))
    if src == "oracle":
        # oracle bad price = freeze first (fail-closed); persistence escalates via repeated criticals
        return Action(FREEZE, sig.scope, reason="oracle critical") if critical else Action(TIGHTEN, sig.scope, pct=0.5, reason="oracle warn")
    # unknown source → conservative freeze (never nothing on an actionable signal)
    return Action(FREEZE, sig.scope, reason=f"{src} {sig.severity}")


def systemic_condition(signals, cfg: dict) -> bool:
    """N distinct scopes in warn/critical (or any stale) at once ⇒ portfolio-wide exit (§5.2)."""
    n_cfg = int((cfg.get("systemic", {}) or {}).get("warn_protocols_n", 3))
    # require FRESH warn/critical — a genuine market-wide event. Many STALE sensors mean a DATA outage
    # (often our own rate-limiting), which must NOT cascade the whole portfolio to DEFENSIVE. A stale
    # scope still de-risks INDIVIDUALLY (FREEZE via match_rule); it just doesn't trigger the systemic exit.
    hot = {s.scope for s in signals if s.staleness_ok and s.severity in (S.WARN, S.CRITICAL)}
    return len(hot) >= n_cfg


def _dedupe(actions) -> list:
    """Idempotent: one action per scope, keeping the most severe (exit > freeze/reduce)."""
    rank = {MARKET_EXIT: 4, FULL_EXIT: 3, ROTATE_TO_SAFE: 3, FREEZE: 2, TIGHTEN: 1, REDUCE: 1}
    best: dict = {}
    for a in actions:
        cur = best.get(a.scope)
        if cur is None or rank.get(a.kind, 0) > rank.get(cur.kind, 0):
            best[a.scope] = a
    return list(best.values())


def evaluate(signals, cfg: dict) -> list:
    """Signals → de-risk actions (deterministic, idempotent). Enforces the de-risk-only invariant."""
    actions = []
    for s in signals:
        a = match_rule(s, cfg)
        if a is not None:
            assert a.is_de_risk_only(), f"reaction produced a non-de-risk action: {a}"  # invariant §1.4
            actions.append(a)
    if systemic_condition(signals, cfg):
        mx = Action(MARKET_EXIT, PORTFOLIO, reason="systemic: many scopes degraded")
        assert mx.is_de_risk_only()
        actions.append(mx)
    return _dedupe(actions)
