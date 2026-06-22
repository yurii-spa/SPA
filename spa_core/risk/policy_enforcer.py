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
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("spa.risk.policy_enforcer")

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
    "max_protocols": 8,             # не более 8 позиций в портфеле
    "per_protocol_max_pct": 25.0,   # не более 25% в одном протоколе
    "t1_min_pct": 55.0,             # минимум 55% в T1 адаптерах
    "t2_max_pct": 50.0,             # максимум 50% в T2 (ADR-019)
    "t3_max_pct": 15.0,             # максимум 15% в T3 (ADR-020)
    "cash_min_pct": 5.0,            # минимум 5% кэш буфер
    "apy_rank_tolerance": 3,        # top-3 по APY должны быть в top-5 по аллокации
}

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
) -> "ValidationResult":
    """Validate a portfolio against all policy rules.

    FAIL-CLOSED: any error or None input -> REJECT with violations.

    Args:
        positions:   Dict mapping protocol_key -> USD amount.
        capital_usd: Total capital in USD.
        adapter_apy: Optional adapter status dict (for APY coherence checks).
        cash_usd:    Cash reserve amount in USD.

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

    # ── Rule 2: per_protocol_max_pct ──────────────────────────────────────
    per_max = float(RULES["per_protocol_max_pct"])
    for proto, usd in positions.items():
        pct = float(usd or 0) / denom * 100.0
        if pct > per_max:
            violations.append(Violation(
                rule="per_protocol_max_pct",
                severity="CRITICAL",
                message="{} = {:.1f}% exceeds per-protocol cap {}%".format(proto, pct, per_max),
                actual=round(pct, 2),
                expected="<={}".format(per_max),
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
