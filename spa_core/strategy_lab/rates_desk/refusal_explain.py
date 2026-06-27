"""
spa_core/strategy_lab/rates_desk/refusal_explain.py — the HUMAN-READABLE rationale layer
for the rates-desk decision log (the public REFUSAL-LOG surface).

THE EDGE we publish: a plain-language, independently-verifiable record of the trades the desk
DECLINED and exactly why — the discipline no competitor publishes. The machine layer (proof_chain.py
+ the hash chain) already exists and is tamper-evident; this module turns one hashed decision row into
an honest English/Russian explanation whose EVERY number is traceable to that row's own hashed
YieldDecomposition. Nothing here prices, decides, or moves capital — it only RE-NARRATES a verdict the
deterministic gate already produced and signed.

PURE / DETERMINISTIC / LLM-FORBIDDEN by construction. `REASON_EXPLAIN` is a STATIC, AUDITED
dictionary — one fixed entry per reason token the policy enum (`contracts.KillReason`) can emit. It is
NOT generative: there is no model, no template that reads anything but the row's own numbers, so an
explanation can never be hallucinated and two runs over the same row are byte-identical. A reason token
the policy can emit but this dict does not cover is impossible — `assert_total()` (and the test suite)
proves every `KillReason` value is mapped, so a `KeyError` cannot occur in production.

fail-CLOSED: a missing/unknown reason, or a malformed row, degrades to an explicit "unmapped /
unverifiable" explanation — NEVER a fabricated SAFE-sounding one.

stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from spa_core.strategy_lab.rates_desk.contracts import KillReason

# ──────────────────────────────────────────────────────────────────────────────────────────────
# STATIC AUDITED REASON DICTIONARY
#
# token → {en, ru} : the fixed, human-authored explanation skeleton for EVERY KillReason the gate
# can emit. `{u}` is filled with the underlying symbol; the live numbers are appended by `explain()`
# from the row's OWN hashed decomposition/detail (never invented here). This is the entire "model":
# a lookup table. Audited once, reproducible forever. NOT generative.
# ──────────────────────────────────────────────────────────────────────────────────────────────
REASON_EXPLAIN: Dict[str, Dict[str, str]] = {
    KillReason.NONE.value: {
        "en": ("We APPROVED {u}: after subtracting every structural risk haircut from the honest "
               "baseline, the quoted rate still cleared fair value plus round-trip cost — this is "
               "harvestable carry, not risk premium."),
        "ru": ("Мы ОДОБРИЛИ {u}: после вычитания всех структурных риск-хейркатов из честного "
               "базового дохода котируемая ставка всё ещё превысила справедливую стоимость плюс "
               "стоимость сделки — это реальный carry, а не премия за риск."),
    },
    KillReason.TAIL_VETO.value: {
        "en": ("We DECLINED {u}: the quoted yield was outweighed by the total structural haircut — "
               "that yield pays you for tail risk, not carry. Refusal comes BEFORE economics, so a "
               "great quote cannot buy its way past a toxic book."),
        "ru": ("Мы ОТКАЗАЛИ {u}: котируемая доходность перекрыта суммарным структурным хейркатом — "
               "эта доходность платит вам за хвостовой риск, а не за carry. Отказ срабатывает ДО "
               "экономики, поэтому отличная котировка не купит проход для токсичной книги."),
    },
    KillReason.UNDERLYING_DEPEG.value: {
        "en": ("We DECLINED {u}: the underlying token's market price has drifted too far from its "
               "honest redemption (NAV) value — a depeg signal. We do not underwrite a yield whose "
               "collateral is already off-peg."),
        "ru": ("Мы ОТКАЗАЛИ {u}: рыночная цена базового токена слишком далеко отошла от его честной "
               "стоимости погашения (NAV) — сигнал депега. Мы не андеррайтим доходность, чей залог "
               "уже потерял привязку."),
    },
    KillReason.ORACLE_STALE.value: {
        "en": ("We DECLINED {u}: the price/rate oracle is stale beyond tolerance — we cannot price "
               "or exit a position safely on data we cannot trust is current. Fail-closed."),
        "ru": ("Мы ОТКАЗАЛИ {u}: оракул цены/ставки устарел сверх допустимого — мы не можем безопасно "
               "оценить или закрыть позицию по данным, актуальность которых не подтверждена. "
               "Fail-closed."),
    },
    KillReason.STABLE_DEPEG.value: {
        "en": ("We DECLINED {u}: the debt/quote stablecoin has broken its peg — the leg we would "
               "borrow or settle in is itself unstable, so the carry is built on shifting ground."),
        "ru": ("Мы ОТКАЗАЛИ {u}: долговой/котировочный стейблкоин потерял привязку — нога, в которой "
               "мы бы занимали или рассчитывались, сама нестабильна, и carry стоит на зыбкой почве."),
    },
    KillReason.FUNDING_FLIP.value: {
        "en": ("We DECLINED {u}: perp funding has stayed negative long enough (a sustained streak, "
               "with hysteresis) to signal the carry regime is unwinding — holding would mean paying "
               "to carry, not getting paid."),
        "ru": ("Мы ОТКАЗАЛИ {u}: funding по перпам оставался отрицательным достаточно долго "
               "(устойчивая серия, с гистерезисом), что сигнализирует о развороте carry-режима — "
               "удержание означало бы платить за carry, а не получать за него."),
    },
    KillReason.ECONOMICS.value: {
        "en": ("We DECLINED {u}: it is structurally sound, but after fair-value and round-trip cost "
               "the net edge does not clear the hurdle — there is simply no carry left to harvest. "
               "A clean refusal on economics, not on risk."),
        "ru": ("Мы ОТКАЗАЛИ {u}: структурно всё в порядке, но после справедливой стоимости и "
               "стоимости сделки чистый edge не превышает порог — harvestable carry попросту не "
               "осталось. Отказ по экономике, а не по риску."),
    },
    KillReason.SIZE_FLOOR.value: {
        "en": ("We DECLINED {u}: bounded by one-tick exit capacity, the tradeable size collapses "
               "below our minimum — a position we could not exit at size is an illiquid bag, so we "
               "do not open it however attractive the rate."),
        "ru": ("Мы ОТКАЗАЛИ {u}: ограниченный однотактовой ёмкостью выхода, торгуемый размер падает "
               "ниже минимума — позицию, из которой нельзя выйти по размеру, мы не открываем, какой "
               "бы привлекательной ни была ставка."),
    },
    KillReason.CARRY_COMPRESSION.value: {
        "en": ("We UNWOUND {u}: the carry locked at entry has compressed below our retention floor — "
               "the spread we were paid for has decayed, so we exit rather than hold a position whose "
               "edge has evaporated."),
        "ru": ("Мы ЗАКРЫЛИ {u}: carry, зафиксированный при входе, сжался ниже порога удержания — "
               "спред, за который нам платили, истощился, поэтому мы выходим, а не держим позицию с "
               "исчезнувшим edge."),
    },
    KillReason.MATURITY_BUFFER.value: {
        "en": ("We UNWOUND {u}: the position is too close to maturity to safely hold or roll — we "
               "exit inside the buffer rather than risk a forced, illiquid settlement at the wire."),
        "ru": ("Мы ЗАКРЫЛИ {u}: позиция слишком близка к погашению, чтобы безопасно держать или "
               "ролловать — мы выходим внутри буфера, а не рискуем вынужденным неликвидным расчётом "
               "в последний момент."),
    },
    KillReason.UTILIZATION_TRAP.value: {
        "en": ("We UNWOUND {u}: pool utilization has stayed above the ceiling long enough that we "
               "could be trapped — a lending/levered leg that cannot be exited when borrowed-out is a "
               "liquidity trap, so we derisk before it closes."),
        "ru": ("Мы ЗАКРЫЛИ {u}: утилизация пула оставалась выше потолка достаточно долго, чтобы мы "
               "могли оказаться в ловушке — кредитную/плечевую ногу, из которой нельзя выйти при "
               "полной выдаче, мы дерискуем до того, как ловушка захлопнется."),
    },
    KillReason.CONCENTRATION.value: {
        "en": ("We DECLINED {u}: the position is too large versus current exit liquidity, or one "
               "borrower dominates the pool — concentration we cannot prove is safe is concentration "
               "we refuse. Fail-closed where the borrow leg matters."),
        "ru": ("Мы ОТКАЗАЛИ {u}: позиция слишком велика относительно текущей ликвидности выхода, либо "
               "один заёмщик доминирует в пуле — концентрацию, безопасность которой нельзя доказать, "
               "мы отклоняем. Fail-closed там, где есть долговая нога."),
    },
    KillReason.EXIT_CAPACITY.value: {
        "en": ("We UNWOUND {u}: one-tick exit capacity has collapsed below the open position size — "
               "we literally cannot get out at size anymore. A safe carry book that became an "
               "illiquid bag is exited immediately, before the basis even compresses."),
        "ru": ("Мы ЗАКРЫЛИ {u}: однотактовая ёмкость выхода упала ниже размера открытой позиции — мы "
               "буквально больше не можем выйти по размеру. Безопасную carry-книгу, ставшую "
               "неликвидным грузом, мы закрываем немедленно, ещё до сжатия базиса."),
    },
}

# Headlines: a short, fixed label per token (the at-a-glance verdict line).
REASON_HEADLINE: Dict[str, str] = {
    KillReason.NONE.value: "Approved — priced carry clears fair value + cost",
    KillReason.TAIL_VETO.value: "Refused — structural haircut outweighs the quote (tail-comp, not carry)",
    KillReason.UNDERLYING_DEPEG.value: "Refused — underlying token off its NAV peg",
    KillReason.ORACLE_STALE.value: "Refused — price/rate oracle stale beyond tolerance",
    KillReason.STABLE_DEPEG.value: "Refused — debt/quote stablecoin broke peg",
    KillReason.FUNDING_FLIP.value: "Refused — sustained negative funding (carry unwinding)",
    KillReason.ECONOMICS.value: "Refused — net edge below hurdle (no carry left)",
    KillReason.SIZE_FLOOR.value: "Refused — exit-bounded size below tradeable floor",
    KillReason.CARRY_COMPRESSION.value: "Unwound — locked carry compressed away",
    KillReason.MATURITY_BUFFER.value: "Unwound — too close to maturity to hold safely",
    KillReason.UTILIZATION_TRAP.value: "Unwound — pool utilization trap (cannot exit)",
    KillReason.CONCENTRATION.value: "Refused — concentration vs exit liquidity / borrower",
    KillReason.EXIT_CAPACITY.value: "Unwound — exit capacity collapsed below position size",
}

# Fail-CLOSED fallback for a token NOT in the dict (impossible for the enum, but a row from an
# unknown/future producer must never crash or invent a benign story).
_UNMAPPED = {
    "en": ("We have a DECISION on {u} whose reason token is not in the audited explanation map — "
           "treating as unverifiable (fail-closed). See the raw structural_reason."),
    "ru": ("По {u} есть РЕШЕНИЕ, чей токен причины отсутствует в аудированной карте объяснений — "
           "считаем непроверяемым (fail-closed). Смотрите сырой structural_reason."),
}
_UNMAPPED_HEADLINE = "Unmapped reason — fail-closed (unverifiable)"

# The exact percent-bearing fields inside a hashed YieldDecomposition we surface as DRIVERS, in the
# fixed order they should be narrated. Each is a Decimal APY string in the row.
_DECOMP_DRIVER_FIELDS = (
    "baseline",
    "peg_haircut",
    "funding_flip_haircut",
    "oracle_haircut",
    "liquidity_haircut",
    "protocol_haircut",
    "total_haircut",
    "fair_yield",
)

# Human labels for the driver fields (English keys are stable; UI localizes if desired).
_DRIVER_LABEL = {
    "baseline": "baseline",
    "peg_haircut": "peg",
    "funding_flip_haircut": "funding-flip",
    "oracle_haircut": "oracle",
    "liquidity_haircut": "liquidity",
    "protocol_haircut": "protocol(nest+conc)",
    "total_haircut": "total haircut",
    "fair_yield": "fair yield",
}


def assert_total() -> None:
    """Prove the dictionary is TOTAL over the policy enum: every KillReason value has an EN+RU
    explanation and a headline. Raises AssertionError if a token is missing — wired into the test
    suite so a new KillReason cannot ship without its audited explanation. PURE, no IO."""
    for reason in KillReason:
        tok = reason.value
        assert tok in REASON_EXPLAIN, f"REASON_EXPLAIN missing token: {tok}"
        assert "en" in REASON_EXPLAIN[tok] and REASON_EXPLAIN[tok]["en"], f"missing EN for {tok}"
        assert "ru" in REASON_EXPLAIN[tok] and REASON_EXPLAIN[tok]["ru"], f"missing RU for {tok}"
        assert tok in REASON_HEADLINE and REASON_HEADLINE[tok], f"missing headline for {tok}"


def _fmt_pct(raw) -> Optional[str]:
    """Decimal-fraction string (e.g. '0.024071120') → a human percent string ('2.41%'), rounded to
    2 dp for display ONLY — the EXACT value stays in `drivers[*].decimal`. Returns None on a
    malformed value (fail-closed: we never fabricate a number)."""
    if raw is None:
        return None
    try:
        d = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
    pct = (d * Decimal("100")).quantize(Decimal("0.01"))
    return f"{pct}%"


def _drivers_from_row(row: dict) -> List[dict]:
    """Pull the ACTUAL numbers from the row's hashed decomposition into an ordered driver list.

    Each driver = {field, label, decimal (verbatim string from the hashed row), pct (display)}.
    Only fields PRESENT in the decomposition are emitted (a partial/legacy row degrades gracefully,
    never invents a haircut). Every `decimal` is the byte-exact value that the entry_hash covers —
    so a reader can re-hash the row and confirm these numbers were not altered."""
    decomp = row.get("decomposition")
    drivers: List[dict] = []
    if not isinstance(decomp, dict):
        return drivers
    for f in _DECOMP_DRIVER_FIELDS:
        if f not in decomp:
            continue
        raw = decomp.get(f)
        drivers.append({
            "field": f,
            "label": _DRIVER_LABEL.get(f, f),
            "decimal": None if raw is None else str(raw),  # verbatim, hash-covered
            "pct": _fmt_pct(raw),
        })
    return drivers


def _quant_phrase(row: dict, drivers: List[dict]) -> str:
    """A compact, number-bearing clause built ONLY from the row's own hashed values, e.g.
    '(peg 2.41% + funding 6.00% + oracle 0.67% + liquidity 6.00% + protocol 1.40% = total 16.47%
    structural haircut vs 12.00% cap)'. Empty string if the row lacks a decomposition (we never
    fabricate the breakdown)."""
    by_field = {d["field"]: d for d in drivers}
    haircut_fields = ("peg_haircut", "funding_flip_haircut", "oracle_haircut",
                      "liquidity_haircut", "protocol_haircut")
    parts: List[str] = []
    for f in haircut_fields:
        d = by_field.get(f)
        if d and d.get("pct") is not None:
            parts.append(f"{_DRIVER_LABEL[f]} {d['pct']}")
    if not parts:
        return ""
    total = by_field.get("total_haircut", {}).get("pct")
    cap = (row.get("detail") or {}).get("max_total_haircut")
    cap_pct = _fmt_pct(cap)
    tail = ""
    if total is not None:
        tail = f" = total {total} structural haircut"
        if cap_pct is not None:
            tail += f" vs {cap_pct} cap"
    return "(" + " + ".join(parts) + tail + ")"


def explain(row: dict, lang: Optional[str] = None) -> dict:
    """Turn ONE hashed decision-log row into a human-readable, fully-traceable explanation.

    Args:
        row:  a decision_log.jsonl mirror row (the dict written by proof_chain.record_decisions).
        lang: ignored for the dict return (we always return BOTH languages); accepted for callers
              that want to pass through a preference. Kept for API symmetry.

    Returns:
        {headline, plain_en, plain_ru, structural_reason, drivers, advisory_size_usd}
        - headline:          fixed at-a-glance label for the reason token
        - plain_en/plain_ru: the audited skeleton for the token + a quant clause built from the
                             row's OWN hashed numbers (every figure re-derivable from the hash)
        - structural_reason: the raw reason token (machine key)
        - drivers:           ordered list of {field,label,decimal,pct} from the hashed decomposition
        - advisory_size_usd: the size LABELED advisory (never raw 'size' implying real capital)

    PURE / deterministic / LLM-FORBIDDEN: no model, no IO, no clock. Fail-CLOSED on an unknown
    token (degrades to the unmapped skeleton) — never a fabricated benign explanation."""
    underlying = row.get("underlying")
    if not isinstance(underlying, str) or not underlying:
        decomp = row.get("decomposition")
        underlying = (decomp.get("underlying") if isinstance(decomp, dict) else None) or "?"

    token = row.get("reason")
    mapped = REASON_EXPLAIN.get(token)
    headline = REASON_HEADLINE.get(token, _UNMAPPED_HEADLINE)
    skel = mapped if mapped is not None else _UNMAPPED

    drivers = _drivers_from_row(row)
    quant = _quant_phrase(row, drivers)

    plain_en = skel["en"].format(u=underlying)
    plain_ru = skel["ru"].format(u=underlying)
    if quant:
        plain_en = f"{plain_en} {quant}"
        plain_ru = f"{plain_ru} {quant}"

    # advisory size label: never expose a raw 'size' field implying real capital.
    advisory_size = row.get("approved_size_usd")
    advisory_size = None if advisory_size is None else str(advisory_size)

    return {
        "underlying": underlying,
        "headline": headline,
        "plain_en": plain_en,
        "plain_ru": plain_ru,
        "structural_reason": token,
        "drivers": drivers,
        "advisory_size_usd": advisory_size,
    }
