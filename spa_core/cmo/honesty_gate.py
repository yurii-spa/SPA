"""spa_core/cmo/honesty_gate.py — deterministic honesty gate for CMO editorial copy.

THE safety primitive of the CMO layer (docs/CMO_EDITORIAL_LAYER.md §3, build-order #1). Before any
rewritten "selling" copy may become a draft, it MUST pass this gate. Deterministic · stdlib-only ·
NO LLM · fail-CLOSED. A honesty-first product cannot let a "make it sell" rewrite overstate — that is
legal risk + it kills the differentiator.

Four checks (ALL must pass):
  1. **Numbers match** — every numeric value in the copy also appears in the source facts. A rewrite may
     never introduce or change a figure. Unmatched number → REJECT (fail-closed: an unresolvable number
     is treated as fabricated, not waved through).
  2. **Disclaimers present** — the honesty tokens the dry version carries (paper · not-a-guarantee ·
     tail-shown · evidence-tagged) must survive the rewrite. A dropped category → REJECT.
  3. **No promissory language** — a blocklist ("guaranteed", "risk-free", "гарантирован", …) → REJECT.
  4. **No solicitation / live-offer framing** — paper is never presented as a live fund or an offer
     ("minimum investment", "invest now", "оферта", …) → REJECT (site-copy.md invariant).

Public API::

    result = check(copy, facts)          # facts: dict of the source journal record
    if result.passed: ...                # else result.reasons lists every violation

Invariants: stdlib only, deterministic, no network, never raises on normal input.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# ── Blocklists ───────────────────────────────────────────────────────────────
# Promissory / guaranteed-return language — never allowed (EN + RU).
# NOTE: bare nouns "guarantee"/"гарантия" are intentionally NOT listed — they are substrings of the
# legitimate disclaimer "not a guarantee" / "не гарантия". Only promise-FORMS (guaranteed, guarantee-verb,
# гарантирован…) are blocked, so a negated disclaimer never false-trips the gate.
PROMISSORY_BLOCKLIST: tuple[str, ...] = (
    "guaranteed", "guaranteed return", "guaranteed returns", "we guarantee", "is guaranteed",
    "will earn", "will make", "risk-free", "risk free", "riskless", "no risk",
    "cannot lose", "can't lose", "assured return", "locked-in return", "fixed return guaranteed",
    "гарантирован", "гарантируем", "заработаете", "заработаешь",
    "без риска", "безрисков", "доход гарант", "гарантированн",
)

# Solicitation / live-offer framing — paper stage, external capital closed (site-copy.md invariant).
SOLICITATION_BLOCKLIST: tuple[str, ...] = (
    "invest now", "deposit now", "buy now", "sign up to earn", "start earning now",
    "minimum investment", "minimum deposit", "act now", "limited offer", "limited time",
    "open your account", "fund your account", "join the fund", "wire your funds",
    "оферта", "инвестируйте сейчас", "вложите сейчас", "внесите депозит",
    "минимальный депозит", "минимальная сумма", "откройте счёт", "пополните счёт",
)

# ── Disclaimer categories (each: at least one synonym must be present) ────────
# The honesty tokens the dry facts carry MUST survive the rewrite.
DISCLAIMER_CATEGORIES: dict[str, tuple[str, ...]] = {
    "paper": ("paper", "paper-stage", "paper trading", "virtual", "simulated",
              "бумаж", "виртуальн", "симулир", "не боевой"),
    "not_a_guarantee": ("not a guarantee", "not guaranteed", "no guarantee", "variable",
                        "past performance", "не гаранти", "без гаранти", "переменн",
                        "не гарантия", "прошлые результаты"),
    "tail_shown": ("drawdown", "tail", "worst", "max drawdown", "downside",
                   "просадк", "хвост", "макс. просадка", "убыт"),
    "evidence_tagged": ("evidence", "evidenced", "realized", "realised", "track", "audit",
                        "подтвержд", "реализова", "трек", "проверяем",
                        "l0", "l1", "l2", "l3", "l4", "l5", "l6"),
}
DEFAULT_REQUIRED_DISCLAIMERS: tuple[str, ...] = tuple(DISCLAIMER_CATEGORIES.keys())

# A numeric token: optional ~/≈/$ prefix, digits with , or . groupings, optional % / bps / k suffix.
_NUM_RE = re.compile(r"[~≈]?\$?\s?(\d[\d.,]*)\s?(%|bps|bp|k|m|x)?", re.IGNORECASE)


@dataclass
class GateResult:
    """Outcome of a honesty-gate check. ``passed`` is True only if every check passed."""
    passed: bool
    reasons: list[str] = field(default_factory=list)
    copy_numbers: list[float] = field(default_factory=list)
    fact_numbers: list[float] = field(default_factory=list)
    unmatched_numbers: list[float] = field(default_factory=list)
    missing_disclaimers: list[str] = field(default_factory=list)
    promissory_hits: list[str] = field(default_factory=list)
    solicitation_hits: list[str] = field(default_factory=list)


# ── Number normalization ─────────────────────────────────────────────────────
def _normalize_number(raw: str) -> float | None:
    """Parse one raw numeric token into a float value, handling EN (1,234.5) and RU (3,3) forms.

    Heuristic for a lone comma: if the part after the LAST comma is 1-2 digits and there is no dot,
    the comma is a decimal separator (RU "3,3" → 3.3); otherwise commas are thousands separators
    ("100,000" → 100000). Returns None if unparseable."""
    s = (raw or "").strip().lstrip("~≈$ ").rstrip("% ").strip()
    # drop a trailing unit suffix if one slipped in (e.g. "4.5bps")
    for suf in ("bps", "bp", "%"):
        if s.lower().endswith(suf):
            s = s[: -len(suf)].strip()
    if not s:
        return None
    has_dot = "." in s
    if "," in s and not has_dot:
        tail = s.rsplit(",", 1)[1]
        if len(tail) in (1, 2) and s.count(",") == 1:
            s = s.replace(",", ".")          # decimal comma
        else:
            s = s.replace(",", "")           # thousands
    else:
        s = s.replace(",", "")               # thousands (dot is the decimal)
    s = s.strip(".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _extract_numbers(text: str) -> list[float]:
    """Extract every numeric value from free text as normalized floats (order-preserving)."""
    out: list[float] = []
    for m in _NUM_RE.finditer(text or ""):
        val = _normalize_number(m.group(1))
        if val is not None:
            suffix = (m.group(2) or "").lower()
            if suffix == "k":
                val *= 1_000
            elif suffix == "m":
                val *= 1_000_000
            out.append(round(val, 6))
    return out


def _flatten_facts(facts: Any) -> str:
    """Flatten a facts dict/list/scalar into one text blob for number + token extraction."""
    parts: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for vv in v.values():
                walk(vv)
        elif isinstance(v, (list, tuple)):
            for vv in v:
                walk(vv)
        elif v is not None:
            parts.append(str(v))

    walk(facts)
    return " ".join(parts)


def _contains_any(haystack_low: str, needles: Iterable[str]) -> list[str]:
    """Return every needle (lowercased match) present in the already-lowercased haystack."""
    return [n for n in needles if n.lower() in haystack_low]


# ── Public API ───────────────────────────────────────────────────────────────
def check(
    copy: str,
    facts: Any,
    *,
    required_disclaimers: Iterable[str] = DEFAULT_REQUIRED_DISCLAIMERS,
    number_tolerance: float = 1e-6,
) -> GateResult:
    """Run the deterministic honesty gate over ``copy`` against the source ``facts``.

    Parameters
    ----------
    copy : the rewritten marketing copy to validate.
    facts : the source journal record (dict/list/scalar) — the ONLY sanctioned numbers + tokens.
    required_disclaimers : which disclaimer categories must be present (default: all four).
    number_tolerance : max abs difference for a copy number to count as matching a fact number.

    Returns a ``GateResult``; ``passed`` is True only if all checks pass. Fail-CLOSED: an unmatched
    number, a missing disclaimer, or any blocklist hit fails the gate. Never raises on normal input.
    """
    reasons: list[str] = []
    copy = copy or ""
    copy_low = copy.lower()
    facts_blob = _flatten_facts(facts)

    # 1. numbers match — every copy number must appear in facts.
    copy_nums = _extract_numbers(copy)
    fact_nums = _extract_numbers(facts_blob)
    unmatched: list[float] = []
    for n in copy_nums:
        if not any(abs(n - f) <= number_tolerance for f in fact_nums):
            unmatched.append(n)
    if unmatched:
        reasons.append(
            "unmatched numbers (not in source facts — possible fabrication): "
            + ", ".join(_fmt(n) for n in unmatched)
        )

    # 2. disclaimers present — each required category needs ≥1 synonym in the copy.
    missing: list[str] = []
    for cat in required_disclaimers:
        syns = DISCLAIMER_CATEGORIES.get(cat)
        if syns is None:
            continue
        if not _contains_any(copy_low, syns):
            missing.append(cat)
    if missing:
        reasons.append("missing disclaimer categories: " + ", ".join(missing))

    # 3. no promissory language.
    promissory = _contains_any(copy_low, PROMISSORY_BLOCKLIST)
    if promissory:
        reasons.append("promissory language: " + ", ".join(promissory))

    # 4. no solicitation / live-offer framing.
    solicitation = _contains_any(copy_low, SOLICITATION_BLOCKLIST)
    if solicitation:
        reasons.append("solicitation / live-offer framing: " + ", ".join(solicitation))

    return GateResult(
        passed=not reasons,
        reasons=reasons,
        copy_numbers=copy_nums,
        fact_numbers=fact_nums,
        unmatched_numbers=unmatched,
        missing_disclaimers=missing,
        promissory_hits=promissory,
        solicitation_hits=solicitation,
    )


def _fmt(n: float) -> str:
    """Compact number formatting for reason strings (drops a trailing .0)."""
    return str(int(n)) if float(n).is_integer() else str(n)
