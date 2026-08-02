"""
spa_core/risk/policy_enforcer.py — Policy Enforcer (P0 Architecture Fix)

LLM_FORBIDDEN: все проверки детерминированные, без AI.
FAIL-CLOSED: невалидный портфель всегда REJECT'ится.

Запускается ПЕРЕД любой записью в current_positions.json.
Любое нарушение → логируется + Telegram алерт + exit code 1.

Правило: "Политика не может быть нарушена молчаливо."
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("spa.risk.policy_enforcer")

# SINGLE SOURCE OF TRUTH (owner-approved 2026-07-08): every cap below is now read from RiskConfig
# (policy.py — the authoritative v1.0 gate) so the enforcer can NEVER drift from it again. This
# RECONCILES the stale risk_adjusted-era constants that made rules_watchdog CRITICAL: per_protocol
# 25%->40% (policy.max_single_protocol) and the 55% T1 floor -> REMOVED (policy.py has no T1 minimum;
# the optimized_yield book at T1 45% is compliant under the authoritative gate). Import-guarded for
# test isolation; the fallbacks equal policy.py's v1.0 defaults.
try:
    from spa_core.risk.policy import RiskConfig as _RiskConfig
    _CFG = _RiskConfig()
    _MAX_PROTOCOLS = int(_CFG.max_protocols)
    _PER_PROTOCOL_MAX_PCT = float(_CFG.max_single_protocol) * 100.0   # 40% (was stale 25%)
    _T2_MAX_PCT = float(_CFG.max_total_t2_allocation) * 100.0         # 50%
    _T3_MAX_PCT = float(getattr(_CFG, "max_total_t3_allocation", 0.15)) * 100.0  # 15%
    _CASH_MIN_PCT = float(_CFG.min_cash_pct) * 100.0                  # 5%
    # ── ADR-062 (W4.1): caps that policy.py enforces per-trade but the enforcer
    # never checked on a WHOLE portfolio. Values read from the same RiskConfig —
    # nothing new is invented, coverage is widened. See ADR-062.
    _PER_PROTOCOL_T1_MAX_PCT = float(_CFG.max_concentration_t1) * 100.0   # 40%
    _PER_PROTOCOL_T2_MAX_PCT = float(_CFG.max_concentration_t2) * 100.0   # 20% (T2 AND T3 —
    #     mirrors policy.py:410-411, where the T1 cap applies to T1 and the T2 cap to everything else)
    _BASE_CHAIN_MAX_PCT = float(getattr(_CFG, "BASE_CHAIN_CAP", 0.20)) * 100.0        # 20% (ADR-025)
    _L2_TOTAL_MAX_PCT = float(_CFG.max_l2_total_allocation) * 100.0                   # 50%
    _SINGLE_CHAIN_MAX_PCT = float(_CFG.max_single_chain_allocation) * 100.0           # 90% (MP-352)
except Exception:  # pragma: no cover — import guard for test isolation (fallbacks = policy v1.0)
    _MAX_PROTOCOLS = 8
    _PER_PROTOCOL_MAX_PCT = 40.0
    _T2_MAX_PCT = 50.0
    _T3_MAX_PCT = 15.0
    _CASH_MIN_PCT = 5.0
    _PER_PROTOCOL_T1_MAX_PCT = 40.0
    _PER_PROTOCOL_T2_MAX_PCT = 20.0
    _BASE_CHAIN_MAX_PCT = 20.0
    _L2_TOTAL_MAX_PCT = 50.0
    _SINGLE_CHAIN_MAX_PCT = 90.0

# Float-noise tolerance: a position sized exactly AT a cap (e.g. 20 000/100 000)
# can surface as 20.000000000000004 %. Without a tolerance the enforcer would
# reject a compliant book on arithmetic dust. 1e-9 pp is far below any real cap.
_EPS_PCT = 1e-9

# Chains counted toward the combined L2 cap. Mirrors policy.py (line 450) and
# chain_limits._L2_CHAINS. NOTE (documented, not changed here): policy.py's
# docstring at line 203 says "Arbitrum+Base+Optimism+Polygon" while its code uses
# {arbitrum, base} in BOTH places that matter. The enforcer follows the CODE, the
# stricter-in-practice reading, and the discrepancy is reported in ADR-062 rather
# than silently resolved — changing it would move a policy threshold.
_L2_CHAINS: frozenset = frozenset({"arbitrum", "base"})
# policy.py has NO T1 minimum → the enforcer must not impose a stricter one. 0.0 = floor disabled.
_T1_MIN_PCT = 0.0

# ── T1 adapter set (single source of truth; matches ADAPTER_REGISTRY T1 entries) ──
T1_ADAPTERS: frozenset = frozenset({
    "aave_v3",
    "compound_v3",
    "spark_susds",
    "morpho_steakhouse",
    "aave_arbitrum",
    "aave_v3_optimism",
    "aave_v3_polygon",
    "aave_v3_base",
    "sky_susds",
})

# ── T3 adapter set (highest risk, separate cap) ──
T3_ADAPTERS: frozenset = frozenset({
    "susde",
    "extra_finance_base",
    "moonwell_base",
    "stusd",
    "usual_usd0pp",
})

# ── Policy rules (deterministic, matches RiskConfig v1.0) ──────────────────
RULES: Dict[str, object] = {
    "max_protocols": _MAX_PROTOCOLS,          # ALLOC-002 (single-source from RiskConfig)
    "per_protocol_max_pct": _PER_PROTOCOL_MAX_PCT,  # policy.max_single_protocol (40%)
    "t1_min_pct": _T1_MIN_PCT,                # policy.py has NO T1 floor → 0.0 (disabled)
    "t2_max_pct": _T2_MAX_PCT,                # policy.max_total_t2_allocation (50%, ADR-019)
    "t3_max_pct": _T3_MAX_PCT,                # policy.max_total_t3_allocation (15%, ADR-020)
    "cash_min_pct": _CASH_MIN_PCT,            # policy.min_cash_pct (5%)
    "apy_rank_tolerance": 3,                  # top-3 по APY должны быть в top-5 по аллокации
    # ── ADR-062 (W4.1): newly COVERED caps (values unchanged, from RiskConfig) ──
    "per_protocol_t1_max_pct": _PER_PROTOCOL_T1_MAX_PCT,  # policy.max_concentration_t1 (40%)
    "per_protocol_t2_max_pct": _PER_PROTOCOL_T2_MAX_PCT,  # policy.max_concentration_t2 (20%, T2+T3)
    "base_chain_max_pct": _BASE_CHAIN_MAX_PCT,            # policy.BASE_CHAIN_CAP (20%, ADR-025)
    "l2_total_max_pct": _L2_TOTAL_MAX_PCT,                # policy.max_l2_total_allocation (50%)
    "single_chain_max_pct": _SINGLE_CHAIN_MAX_PCT,        # policy.max_single_chain_allocation (90%)
}


def _resolve_chain_map(protocols) -> tuple:
    """Resolve protocol → chain (lowercase). Returns ``(chain_map, unresolved)``.

    ADR-062. Source order, most authoritative first:

    1. ``data/adapter_registry.json`` → ``adapters[p].chain`` — the live, maintained
       registry (34 adapters as of 2026-08-02).
    2. ``chain_limits.get_default_chain_map()`` — the legacy static map. It covers
       only 10 of 34 adapters and MISSES ``morpho_steakhouse`` and ``pendle``, i.e.
       60 % of the current book; used as a fallback for the two keys it holds that
       the registry does not (``aave_v3_arbitrum``, ``compound_v3_base``).

    A protocol resolved by NEITHER source is returned in ``unresolved`` — never
    silently bucketed as "unknown" and dropped, because an unattributed position
    would make a chain cap under-count (fail-OPEN). The caller decides what an
    unresolved chain means for the verdict.

    Never raises: an unreadable registry degrades to the static map.
    """
    chain_map: Dict[str, str] = {}
    try:
        _reg_path = Path(__file__).resolve().parents[2] / "data" / "adapter_registry.json"
        _reg = json.loads(_reg_path.read_text(encoding="utf-8"))
        for name, entry in (_reg.get("adapters", {}) or {}).items():
            if isinstance(entry, dict) and entry.get("chain"):
                chain_map[str(name)] = str(entry["chain"]).strip().lower()
    except Exception as exc:  # noqa: BLE001 — registry is best-effort, static map remains
        log.warning("ADR-062: adapter_registry.json unreadable (%s) — static chain map only", exc)

    try:
        from spa_core.risk.chain_limits import get_default_chain_map
        for name, chain in (get_default_chain_map() or {}).items():
            chain_map.setdefault(str(name), str(chain).strip().lower())
    except Exception as exc:  # noqa: BLE001
        log.warning("ADR-062: chain_limits map unavailable (%s)", exc)

    unresolved = sorted(p for p in (protocols or []) if p not in chain_map)
    return chain_map, unresolved

# Suspended/compromised adapters — fail immediately if present in portfolio
SUSPENDED_ADAPTERS: frozenset = frozenset()


@dataclass
class Violation:
    """Одно нарушение политики."""
    rule: str
    severity: str   # "CRITICAL" | "WARNING"
    message: str
    actual: object = None
    expected: object = None

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "actual": self.actual,
            "expected": self.expected,
        }


@dataclass
class ValidationResult:
    """Результат валидации портфеля."""
    passed: bool
    violations: List[Violation] = field(default_factory=list)
    warnings: List[Violation] = field(default_factory=list)
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    portfolio_summary: Dict = field(default_factory=dict)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checked_at": self.checked_at,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [v.to_dict() for v in self.warnings],
            "violation_count": len(self.violations),
            "warning_count": len(self.warnings),
            "portfolio_summary": self.portfolio_summary,
        }


def _normalize_tier(protocol: str, adapter_apy: Optional[Dict] = None) -> str:
    """Determine tier string for a protocol.

    Priority:
    1. T1_ADAPTERS set (authoritative)
    2. T3_ADAPTERS set
    3. adapter_apy dict tier field (integer or string)
    4. Default: "T2" (conservative)
    """
    if protocol in T1_ADAPTERS:
        return "T1"
    if protocol in T3_ADAPTERS:
        return "T3"
    if adapter_apy and protocol in adapter_apy:
        raw = adapter_apy[protocol].get("tier") if isinstance(adapter_apy[protocol], dict) else None
        if raw is not None:
            s = str(raw).strip().upper()
            if s in ("1", "T1"):
                return "T1"
            if s in ("3", "T3"):
                return "T3"
    return "T2"


def validate_positions(
    positions: Optional[Dict],
    capital_usd: float,
    adapter_apy: Optional[Dict] = None,
    cash_usd: float = 0.0,
    chain_map: Optional[Dict] = None,
) -> "ValidationResult":
    """Validate a portfolio against all policy rules.

    FAIL-CLOSED: any error or None input -> REJECT with violations.

    Args:
        positions:   Dict mapping protocol_key -> USD amount.
        capital_usd: Total capital in USD.
        adapter_apy: Optional adapter status dict (for APY coherence checks).
        cash_usd:    Cash reserve amount in USD.
        chain_map:   Optional {protocol: chain} override (ADR-062). None → resolved
                     from adapter_registry.json + chain_limits. Tests inject it so
                     the suite never depends on the live registry.

    Returns:
        ValidationResult with passed=False and violations if any rule is broken.
    """
    violations: List[Violation] = []
    warnings: List[Violation] = []

    # ── Fail-closed: None or invalid input -> immediate reject ─────────────
    if positions is None:
        return ValidationResult(
            passed=False,
            violations=[Violation(
                rule="input_validation",
                severity="CRITICAL",
                message="positions is None — fail-closed reject",
            )],
        )

    if not isinstance(positions, dict):
        return ValidationResult(
            passed=False,
            violations=[Violation(
                rule="input_validation",
                severity="CRITICAL",
                message="positions must be dict, got {}".format(type(positions).__name__),
            )],
        )

    if capital_usd <= 0:
        return ValidationResult(
            passed=False,
            violations=[Violation(
                rule="input_validation",
                severity="CRITICAL",
                message="capital_usd must be > 0, got {}".format(capital_usd),
                actual=capital_usd,
                expected=">0",
            )],
        )

    # ── Compute totals ────────────────────────────────────────────────────
    deployed_usd = sum(float(v or 0) for v in positions.values())
    denom = capital_usd  # denominator for % calculations

    # Tier buckets
    t1_usd = 0.0
    t2_usd = 0.0
    t3_usd = 0.0
    tier_map: Dict[str, str] = {}

    for proto, usd in positions.items():
        tier = _normalize_tier(proto, adapter_apy)
        tier_map[proto] = tier
        usd_f = float(usd or 0)
        if tier == "T1":
            t1_usd += usd_f
        elif tier == "T3":
            t3_usd += usd_f
        else:
            t2_usd += usd_f

    t1_pct = t1_usd / denom * 100.0
    t2_pct = t2_usd / denom * 100.0
    t3_pct = t3_usd / denom * 100.0
    cash_pct = cash_usd / denom * 100.0

    portfolio_summary = {
        "capital_usd": capital_usd,
        "deployed_usd": round(deployed_usd, 2),
        "cash_usd": round(cash_usd, 2),
        "protocol_count": len(positions),
        "t1_pct": round(t1_pct, 2),
        "t2_pct": round(t2_pct, 2),
        "t3_pct": round(t3_pct, 2),
        "cash_pct": round(cash_pct, 2),
        "tier_map": tier_map,
    }

    # ── Rule 1: max_protocols ──────────────────────────────────────────────
    max_p = int(RULES["max_protocols"])
    if len(positions) > max_p:
        violations.append(Violation(
            rule="max_protocols",
            severity="CRITICAL",
            message=(
                "Portfolio has {} protocols — exceeds maximum {}. "
                "Over-diversification destroys T1 concentration and signal quality."
            ).format(len(positions), max_p),
            actual=len(positions),
            expected="<={}".format(max_p),
        ))

    # ── Rule 2: per_protocol_max_pct (ADR-062: now TIER-AWARE) ────────────
    # policy.py:410-411 applies max_concentration_t1 to T1 and max_concentration_t2
    # to everything else. The enforcer previously applied ONE flat 40 % cap to every
    # protocol, so a T2 pool at 21-40 % passed here while the authoritative gate
    # would have refused it per-trade. Same values, wider coverage.
    per_max = float(RULES["per_protocol_max_pct"])
    per_max_t1 = float(RULES["per_protocol_t1_max_pct"])
    per_max_t2 = float(RULES["per_protocol_t2_max_pct"])
    for proto, usd in positions.items():
        pct = float(usd or 0) / denom * 100.0
        tier = tier_map.get(proto, "T2")
        tier_cap = per_max_t1 if tier == "T1" else per_max_t2
        # The global single-protocol ceiling still applies on top (never looser).
        effective_cap = min(tier_cap, per_max)
        if pct > effective_cap + _EPS_PCT:
            violations.append(Violation(
                rule="per_protocol_max_pct",
                severity="CRITICAL",
                message="{} ({}) = {:.1f}% exceeds per-protocol cap {}%".format(
                    proto, tier, pct, effective_cap
                ),
                actual=round(pct, 2),
                expected="<={}".format(effective_cap),
            ))

    # ── Rule 3: t1_min_pct ────────────────────────────────────────────────
    t1_min = float(RULES["t1_min_pct"])
    if t1_pct < t1_min:
        t1_protos = sorted(p for p, t in tier_map.items() if t == "T1")
        violations.append(Violation(
            rule="t1_min_pct",
            severity="CRITICAL",
            message=(
                "T1 allocation {:.1f}% is below minimum {}%. "
                "T1 protocols present: {}. "
                "This violates the anchor-first allocation principle."
            ).format(t1_pct, t1_min, t1_protos),
            actual=round(t1_pct, 2),
            expected=">={}".format(t1_min),
        ))

    # ── Rule 4: t2_max_pct (ADR-019) ─────────────────────────────────────
    t2_max = float(RULES["t2_max_pct"])
    if t2_pct > t2_max:
        violations.append(Violation(
            rule="t2_max_pct",
            severity="CRITICAL",
            message="T2 allocation {:.1f}% exceeds ADR-019 cap {}%".format(t2_pct, t2_max),
            actual=round(t2_pct, 2),
            expected="<={}".format(t2_max),
        ))

    # ── Rule 5: t3_max_pct (ADR-020) ─────────────────────────────────────
    t3_max = float(RULES["t3_max_pct"])
    if t3_pct > t3_max:
        t3_protos = sorted(p for p, t in tier_map.items() if t == "T3")
        violations.append(Violation(
            rule="t3_max_pct",
            severity="CRITICAL",
            message=(
                "T3 allocation {:.1f}% exceeds ADR-020 cap {}%. "
                "T3 protocols: {}"
            ).format(t3_pct, t3_max, t3_protos),
            actual=round(t3_pct, 2),
            expected="<={}".format(t3_max),
        ))

    # ── Rule 6: cash_min_pct ──────────────────────────────────────────────
    cash_min = float(RULES["cash_min_pct"])
    if cash_pct < cash_min:
        violations.append(Violation(
            rule="cash_min_pct",
            severity="CRITICAL",
            message=(
                "Cash buffer {:.1f}% is below minimum {}%. Cash: ${:.0f}"
            ).format(cash_pct, cash_min, cash_usd),
            actual=round(cash_pct, 2),
            expected=">={}".format(cash_min),
        ))

    # ── Rule 7: no_suspended ──────────────────────────────────────────────
    for proto in positions:
        if proto in SUSPENDED_ADAPTERS:
            violations.append(Violation(
                rule="no_suspended",
                severity="CRITICAL",
                message="{} is on the suspended/hacked adapter list".format(proto),
                actual=proto,
                expected="not in SUSPENDED_ADAPTERS",
            ))

    # ── Rules 9-11 (ADR-062): chain concentration caps ────────────────────
    # policy.py enforces these PER TRADE (lines 435-457); nothing checked them on a
    # whole portfolio, so a book assembled from individually-legal trades could sit
    # over a chain cap indefinitely. Values from RiskConfig — coverage, not change.
    resolved_map, unresolved = _resolve_chain_map(list(positions.keys()))
    if chain_map:  # explicit injection wins (tests / callers with their own map)
        resolved_map = {str(k): str(v).strip().lower() for k, v in chain_map.items()}
        unresolved = sorted(p for p in positions if p not in resolved_map)

    chain_usd: Dict[str, float] = {}
    unresolved_usd = 0.0
    for proto, usd in positions.items():
        usd_f = float(usd or 0)
        chain = resolved_map.get(proto)
        if chain is None:
            unresolved_usd += usd_f
            continue
        chain_usd[chain] = chain_usd.get(chain, 0.0) + usd_f

    chain_pct = {c: v / denom * 100.0 for c, v in chain_usd.items()}
    base_pct = chain_pct.get("base", 0.0)
    l2_pct = sum(v for c, v in chain_pct.items() if c in _L2_CHAINS)
    max_chain_pct = max(chain_pct.values()) if chain_pct else 0.0
    max_chain_name = max(chain_pct, key=lambda c: chain_pct[c]) if chain_pct else None
    unresolved_pct = unresolved_usd / denom * 100.0

    portfolio_summary["chain_pct"] = {c: round(v, 2) for c, v in sorted(chain_pct.items())}
    portfolio_summary["base_pct"] = round(base_pct, 2)
    portfolio_summary["l2_pct"] = round(l2_pct, 2)
    portfolio_summary["chain_unresolved"] = unresolved
    portfolio_summary["chain_unresolved_pct"] = round(unresolved_pct, 2)

    base_max = float(RULES["base_chain_max_pct"])
    l2_max = float(RULES["l2_total_max_pct"])
    single_max = float(RULES["single_chain_max_pct"])

    if base_pct > base_max + _EPS_PCT:
        violations.append(Violation(
            rule="base_chain_max_pct",
            severity="CRITICAL",
            message="Base chain allocation {:.1f}% exceeds ADR-025 cap {}%".format(
                base_pct, base_max
            ),
            actual=round(base_pct, 2),
            expected="<={}".format(base_max),
        ))

    if l2_pct > l2_max + _EPS_PCT:
        violations.append(Violation(
            rule="l2_total_max_pct",
            severity="CRITICAL",
            message="Combined L2 allocation {:.1f}% (chains {}) exceeds cap {}%".format(
                l2_pct, sorted(c for c in chain_pct if c in _L2_CHAINS), l2_max
            ),
            actual=round(l2_pct, 2),
            expected="<={}".format(l2_max),
        ))

    if max_chain_pct > single_max + _EPS_PCT:
        violations.append(Violation(
            rule="single_chain_max_pct",
            severity="CRITICAL",
            message="Chain '{}' holds {:.1f}% — exceeds single-chain cap {}%".format(
                max_chain_name, max_chain_pct, single_max
            ),
            actual=round(max_chain_pct, 2),
            expected="<={}".format(single_max),
        ))
    elif max_chain_pct > single_max * 0.85:
        # Mirrors policy.py:443 — approaching the limit is a warning, not a block.
        warnings.append(Violation(
            rule="single_chain_approaching",
            severity="WARNING",
            message="Chain '{}' holds {:.1f}%, approaching the {}% single-chain cap".format(
                max_chain_name, max_chain_pct, single_max
            ),
            actual=round(max_chain_pct, 2),
            expected="<={}".format(single_max),
        ))

    # Unattributed capital: reported as explicitly UNCHECKED, never silently dropped
    # — and never converted into a violation.
    #
    # A first version escalated to CRITICAL when the unresolved USD *could* breach a
    # cap in the worst case. That is wrong on two counts. (1) Logically: with unknown
    # chains the worst case is not evidence — each unresolved protocol could equally
    # sit on its OWN chain, in which case nothing is breached, so "could breach" is a
    # guess dressed as a verdict, and fail-CLOSED means refusing to guess in EITHER
    # direction. (2) Operationally: it turns a registry gap into a total stop the
    # allocator cannot clear by itself — the "irreversible unchecked starves the
    # queue" failure mode already recorded in this project.
    #
    # So: the caps are enforced on what IS known, and what is NOT known is published
    # as unchecked scope (rule + portfolio_summary), which a monitor can act on.
    # Residual gap, stated openly in ADR-062: an UNREGISTERED protocol on Base could
    # push real Base exposure over its cap without this rule firing. The right guard
    # for that is "funded protocol missing from the registry" as its own signal —
    # card `agent-funded-protocol-not-in-registry.md` — not a guess inside this one.
    if unresolved:
        warnings.append(Violation(
            rule="chain_unresolved",
            severity="WARNING",
            message=(
                "Chain UNCHECKED for {} protocol(s) ({:.1f}% of capital): {}. "
                "Chain caps were verified only on the resolved {:.1f}%."
            ).format(
                len(unresolved), unresolved_pct, unresolved, 100.0 - unresolved_pct
            ),
            actual=unresolved,
            expected="every funded protocol resolvable to a chain",
        ))

    # ── Rule 8: apy_coherence (top APY <-> top allocation) ────────────────
    # Top-3 by APY should be in top-5 by allocation (advisory warning only)
    if adapter_apy and isinstance(adapter_apy, dict):
        apy_map: Dict[str, float] = {}
        for proto in positions:
            info = adapter_apy.get(proto)
            if isinstance(info, dict):
                apy_val = info.get("apy") or info.get("live_apy") or 0
                if apy_val and float(apy_val) > 0:
                    apy_map[proto] = float(apy_val)

        if len(apy_map) >= 3:
            top_apy = sorted(apy_map, key=lambda p: -apy_map[p])[:3]
            top_alloc = sorted(
                positions,
                key=lambda p: -float(positions.get(p) or 0)
            )[:5]
            top_apy_not_in_alloc = [p for p in top_apy if p not in top_alloc]

            if top_apy_not_in_alloc:
                warnings.append(Violation(
                    rule="apy_coherence",
                    severity="WARNING",
                    message=(
                        "APY coherence: top-APY protocols {} not in top-5 allocation. "
                        "Consider reallocating."
                    ).format(top_apy_not_in_alloc),
                    actual=top_apy_not_in_alloc,
                    expected="top-3 APY in top-5 allocation",
                ))

    passed = len(violations) == 0
    result = ValidationResult(
        passed=passed,
        violations=violations,
        warnings=warnings,
        portfolio_summary=portfolio_summary,
    )

    if not passed:
        log.error(
            "PolicyEnforcer: %d violation(s) — portfolio REJECTED. Rules: %s",
            len(violations),
            [v.rule for v in violations],
        )
    elif warnings:
        log.warning(
            "PolicyEnforcer: portfolio PASSED with %d warning(s): %s",
            len(warnings),
            [w.rule for w in warnings],
        )
    else:
        log.info("PolicyEnforcer: portfolio PASSED all %d rules.", len(RULES))

    return result


def validate_positions_from_file(
    positions_path: str,
    adapter_status_path: Optional[str] = None,
) -> "ValidationResult":
    """Load current_positions.json and validate it.

    Convenience wrapper for CLI / monitoring usage.
    """
    try:
        with open(positions_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        return ValidationResult(
            passed=False,
            violations=[Violation(
                rule="file_exists",
                severity="CRITICAL",
                message="current_positions.json not found: {}".format(positions_path),
            )],
        )
    except json.JSONDecodeError as e:
        return ValidationResult(
            passed=False,
            violations=[Violation(
                rule="file_valid_json",
                severity="CRITICAL",
                message="current_positions.json is invalid JSON: {}".format(e),
            )],
        )

    positions = doc.get("positions") if isinstance(doc, dict) else None
    capital_usd = float(doc.get("capital_usd", 0) or 0) if isinstance(doc, dict) else 0.0
    cash_usd = float(doc.get("cash_usd", 0) or 0) if isinstance(doc, dict) else 0.0

    # Load adapter APY data if available
    adapter_apy: Optional[Dict] = None
    if adapter_status_path:
        try:
            with open(adapter_status_path, "r", encoding="utf-8") as f:
                status = json.load(f)
            adapter_apy = status.get("adapters") if isinstance(status, dict) else None
        except Exception:
            pass

    return validate_positions(
        positions=positions,
        capital_usd=capital_usd,
        adapter_apy=adapter_apy,
        cash_usd=cash_usd,
    )


def format_violations_text(result: "ValidationResult") -> str:
    """Format violations for Telegram / CLI output."""
    lines = []
    if result.passed:
        lines.append("✅ Portfolio PASSED all policy rules.")
        if result.warnings:
            lines.append("⚠️ {} warning(s):".format(len(result.warnings)))
            for w in result.warnings:
                lines.append("  • [{}] {}".format(w.rule, w.message))
    else:
        lines.append(
            "🚨 Portfolio REJECTED — {} critical violation(s):".format(
                len(result.violations)
            )
        )
        for v in result.violations:
            lines.append("  ❌ [{}] {}".format(v.rule, v.message))
        if result.warnings:
            lines.append("⚠️ Plus {} warning(s).".format(len(result.warnings)))

    summary = result.portfolio_summary
    if summary:
        lines.append(
            "\n📊 Summary: {} protocols, "
            "T1={:.1f}% T2={:.1f}% T3={:.1f}% Cash={:.1f}%".format(
                summary.get("protocol_count", 0),
                summary.get("t1_pct", 0),
                summary.get("t2_pct", 0),
                summary.get("t3_pct", 0),
                summary.get("cash_pct", 0),
            )
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _REPO = Path(__file__).resolve().parents[2]
    _pos_path = str(_REPO / "data" / "current_positions.json")
    _adp_path = str(_REPO / "data" / "adapter_status.json")
    result = validate_positions_from_file(_pos_path, _adp_path)
    print(format_violations_text(result))
    sys.exit(0 if result.passed else 1)
