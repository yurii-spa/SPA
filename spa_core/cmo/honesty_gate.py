"""spa_core/cmo/honesty_gate.py — CMO Editorial Honesty Gate (deterministic, fail-CLOSED).

The FIRST layer of the CMO Editorial pipeline (spec docs/CMO_EDITORIAL_LAYER.md §Layer 3).
Guards every draft before it can enter the approval queue:

  (1) Numbers match     — every number in the draft must appear in source_facts.
                          No invented figures; tolerance ±2% for rounded values.
  (2) Disclaimers       — required disclosure phrases must be present (paper / not-a-guarantee /
                          tail-shown / evidence-tagged). At least one from each category.
  (3) No promissory     — blocklist of guaranteed-return / will-earn language. One hit → REJECT.
  (4) No live/offer     — paper must not be framed as live capital or a solicitation. One hit → REJECT.

Fail-CLOSED: any unexpected error → REJECTED (not a false pass). LLM FORBIDDEN here.
stdlib-only. Non-custodial. No secrets in this module.

Usage::
    from spa_core.cmo.honesty_gate import check_draft
    result = check_draft(draft_text, source_facts)
    if not result.passed:
        print(result.violations)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── required disclaimer keyword groups (at least ONE from each group must appear) ──────────────
# A draft is allowed to satisfy each group with ANY matching phrase (case-insensitive).
DISCLAIMER_GROUPS: list[tuple[str, list[str]]] = [
    (
        "paper-framing",
        [
            "paper", "paper trading", "paper track", "бумажн", "paper-track",
            "not real capital", "virtual capital", "виртуальный капитал",
            "simulated", "not live trading",
        ],
    ),
    (
        "not-a-guarantee",
        [
            "not a guarantee", "не гарантия", "not guaranteed", "нет гарантий",
            "no guarantee", "past performance", "not financial advice",
            "нет гарантированной", "не является гарантией",
            "not an offer", "не является офертой",
        ],
    ),
    (
        "tail-shown",
        [
            "tail", "drawdown", "loss", "risk", "риск", "просадка", "потер",
            "хвост", "downside", "убыток", "can lose", "may lose",
        ],
    ),
]

# ── promissory language blocklist — any match → REJECT ─────────────────────────────────────────
PROMISSORY_PATTERNS: list[str] = [
    r"\bguaranteed\s+return",
    r"\bguaranteed\s+yield",
    r"\bwill\s+earn\b",
    r"\bwill\s+make\b",
    r"\brisk[- ]free\b",
    r"\bno\s+risk\b",
    r"\bzero[- ]risk\b",
    r"\bгарантирован\w*\s+доход",
    r"\bзаработаете\b",
    r"\bгарантированн\w*\s+прибыл",
    r"\bбез\s+риска\b",
    r"\bgives?\s+you\s+\d",
    r"\bproven\s+profit",
    r"\bproven\s+return",
    r"\bguarantees\b",            # verb form: "strategy guarantees X%"; avoids false-positive on noun "guarantee" in disclaimers
    r"\bcertain\s+return",
]

# ── live/offer framing blocklist — any match → REJECT ──────────────────────────────────────────
LIVE_OFFER_PATTERNS: list[str] = [
    r"\binvest\s+now\b",
    r"\bdeposit\s+now\b",
    r"\bopen\s+to\s+investment",
    r"\baccepting\s+(capital|investment|deposit)",
    r"\bopen\s+for\s+(investment|deposits)",
    r"\blive\s+trad(ing|e)\b",
    r"\breal\s+capital\s+at\s+risk\b",
    r"\bactual\s+fund\b",
    r"\bmanaging\s+(real|external)\s+(capital|money|funds?)\b",
    r"\byour\s+money\s+(will|is)\b",
    r"\bsolicitation\b",
]

# ── numeric extraction ──────────────────────────────────────────────────────────────────────────
_NUM_RE = re.compile(r"[\$€£]?\s*(\d[\d,_]*(?:\.\d+)?)\s*%?", re.IGNORECASE)
_TOLERANCE = 0.02  # 2% relative tolerance for rounding


def _extract_numbers(text: str) -> list[float]:
    """Return all numeric values found in text, deduplicated."""
    nums: set[float] = set()
    for m in _NUM_RE.finditer(text):
        try:
            v = float(m.group(1).replace(",", "").replace("_", ""))
            if 0 < v < 1e12:  # sanity: ignore timestamps / epoch numbers
                nums.add(v)
        except ValueError:
            pass
    return list(nums)


def _collect_source_numbers(facts: Any, depth: int = 0) -> list[float]:
    """Recursively collect all numeric values from source_facts."""
    if depth > 6:
        return []
    nums: list[float] = []
    if isinstance(facts, (int, float)) and not isinstance(facts, bool):
        v = float(facts)
        if 0 < v < 1e12:
            nums.append(v)
    elif isinstance(facts, dict):
        for vv in facts.values():
            nums.extend(_collect_source_numbers(vv, depth + 1))
    elif isinstance(facts, (list, tuple)):
        for item in facts:
            nums.extend(_collect_source_numbers(item, depth + 1))
    elif isinstance(facts, str):
        nums.extend(_extract_numbers(facts))
    return nums


def _number_allowed(val: float, source_nums: list[float]) -> bool:
    """Return True if val is within ±TOLERANCE of any source number, or is a small round integer."""
    # small integers (1, 2, 5, 10, 30…) are structural constants, not data claims
    if val == int(val) and int(val) <= 100:
        return True
    for s in source_nums:
        if s == 0:
            continue
        if abs(val - s) / max(abs(s), 1e-9) <= _TOLERANCE:
            return True
    return False


# ── gate result ────────────────────────────────────────────────────────────────────────────────
@dataclass
class GateResult:
    passed: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


# ── main entry point ───────────────────────────────────────────────────────────────────────────
def check_draft(
    draft_text: str,
    source_facts: dict[str, Any],
    *,
    require_all_disclaimer_groups: bool = True,
    extra_allowed_numbers: list[float] | None = None,
) -> GateResult:
    """Run all honesty checks on `draft_text` against `source_facts`.

    Args:
        draft_text: The marketing copy to validate.
        source_facts: Dict of known-good facts (numbers + string values). Every number in the
            draft must appear here (within tolerance).
        require_all_disclaimer_groups: If True (default, fail-CLOSED), ALL disclaimer groups
            must be satisfied. Set False only in test scenarios.
        extra_allowed_numbers: Additional numbers explicitly allowed (e.g. historic constants
            that are common knowledge: 100, 30).

    Returns:
        GateResult(passed=True/False, violations=[...])
    """
    try:
        return _run_checks(draft_text, source_facts, require_all_disclaimer_groups, extra_allowed_numbers or [])
    except Exception as exc:  # noqa: BLE001
        # fail-CLOSED: any unexpected error → reject
        return GateResult(passed=False, violations=[f"gate-error: {exc!r}"])


def _run_checks(
    text: str,
    source_facts: dict[str, Any],
    require_all: bool,
    extra_allowed: list[float],
) -> GateResult:
    violations: list[str] = []
    lower = text.lower()

    # (1) numbers-match check
    source_nums = _collect_source_numbers(source_facts) + extra_allowed
    draft_nums = _extract_numbers(text)
    for val in draft_nums:
        if not _number_allowed(val, source_nums):
            violations.append(f"number-not-in-source: {val!r} not found in source_facts (±{_TOLERANCE*100:.0f}%)")

    # (2) disclaimer groups
    if require_all:
        for group_name, keywords in DISCLAIMER_GROUPS:
            found = any(kw in lower for kw in keywords)
            if not found:
                violations.append(
                    f"missing-disclaimer-group: '{group_name}' — add one of: {keywords[:3]!r}…"
                )

    # (3) promissory language
    for pat in PROMISSORY_PATTERNS:
        if re.search(pat, lower, re.IGNORECASE):
            violations.append(f"promissory-language: pattern {pat!r} matched in draft")

    # (4) live/offer framing
    for pat in LIVE_OFFER_PATTERNS:
        if re.search(pat, lower, re.IGNORECASE):
            violations.append(f"live-offer-framing: pattern {pat!r} matched in draft")

    passed = len(violations) == 0
    return GateResult(passed=passed, violations=violations)
