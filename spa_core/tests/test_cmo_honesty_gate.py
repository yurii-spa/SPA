"""spa_core/tests/test_cmo_honesty_gate.py — CMO honesty-gate (AAA product-layer, step 1).

The deterministic, fail-CLOSED safety primitive of the CMO editorial layer
(docs/CMO_EDITORIAL_LAYER.md §3). Proves: a rewrite may not introduce/alter a number, may not drop a
disclaimer category, and may not use promissory or solicitation language. PURE / no network / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.cmo import honesty_gate as hg

# A realistic source-facts record (the dry journal shape: real, sourced numbers + honesty tokens).
FACTS = {
    "tier": "conservative",
    "realized_apy_pct": 3.3,
    "band_max_pct": 6,
    "drawdown_pct": 0.0,
    "capital_usd": 100000,
    "anchor": "2026-06-22",
    "evidence": "L6",
    "note": "live paper track, variable, realized to date, not a guarantee, worst drawdown shown",
}

# A copy that stays inside the honesty floor: only sourced numbers, all four disclaimer categories.
GOOD_COPY = (
    "The Conservative book runs a live paper track since 2026-06-22 — ~3.3% realized so far at "
    "0.0% drawdown, up to 6% target (variable, not a guarantee). Evidence L6; the worst drawdown "
    "is shown, never hidden. Virtual $100,000, paper-stage."
)


def test_good_copy_passes():
    r = hg.check(GOOD_COPY, FACTS)
    assert r.passed, r.reasons
    assert r.unmatched_numbers == []
    assert r.missing_disclaimers == []


def test_fabricated_number_rejected():
    bad = GOOD_COPY.replace("up to 6% target", "up to 9% target")  # 9 not in facts
    r = hg.check(bad, FACTS)
    assert not r.passed
    assert 9.0 in r.unmatched_numbers
    assert any("unmatched numbers" in x for x in r.reasons)


def test_ru_decimal_comma_matches():
    # RU copy uses "3,3" for the same 3.3 realized — must be recognised as matching, not fabricated.
    ru = ("Живой бумажный трек с 2026-06-22 — ~3,3% реализовано при 0,0% просадки, до 6% "
          "(переменная, не гарантия). Evidence L6, макс. просадка показана. Виртуальные $100,000.")
    r = hg.check(ru, FACTS)
    assert r.passed, r.reasons


def test_thousands_separator_matches():
    assert hg._normalize_number("100,000") == 100000.0
    assert hg._normalize_number("3,3") == 3.3
    assert hg._normalize_number("1,234.5") == 1234.5
    assert hg._normalize_number("~4.5") == 4.5


def test_number_suffix_k_m():
    nums = hg._extract_numbers("we hold $100k in a paper book, cap $1m")
    assert 100000.0 in nums and 1000000.0 in nums


def test_each_missing_disclaimer_category_rejects():
    # Drop one category at a time by removing all its synonyms → gate must flag exactly that category.
    base = GOOD_COPY
    # remove 'paper'/'virtual' tokens
    no_paper = (base.replace("paper-stage", "").replace("paper track", "track")
                    .replace("Virtual", "").replace("paper", ""))
    r = hg.check(no_paper, FACTS)
    assert not r.passed and "paper" in r.missing_disclaimers


def test_promissory_language_rejected_en_and_ru():
    r_en = hg.check(GOOD_COPY + " Returns are guaranteed and risk-free.", FACTS)
    assert not r_en.passed and r_en.promissory_hits
    r_ru = hg.check(GOOD_COPY + " Доход гарантирован, без риска.", FACTS)
    assert not r_ru.passed and r_ru.promissory_hits


def test_solicitation_framing_rejected():
    r = hg.check(GOOD_COPY + " Minimum investment $10,000 — invest now!", FACTS)
    assert not r.passed
    assert r.solicitation_hits
    # note: 10,000 is also an unmatched number → both reasons fire (fail-closed)
    assert 10000.0 in r.unmatched_numbers


def test_relaxable_required_disclaimers():
    # A short chip needn't carry all four — caller may require a subset.
    chip = "up to 6% (variable, not a guarantee)"
    assert not hg.check(chip, FACTS).passed  # default: all four required → fails
    r = hg.check(chip, FACTS, required_disclaimers=("not_a_guarantee",))
    assert r.passed, r.reasons


def test_empty_copy_is_fail_closed_never_raises():
    r = hg.check("", FACTS)
    assert not r.passed              # no disclaimers present → fail-closed
    r2 = hg.check(None, None)        # type: ignore[arg-type]
    assert not r2.passed            # never raises


def test_integer_band_matches_percent_token():
    # facts band_max_pct = 6 (int); copy "up to 6%" must match (suffix % ignored for value match).
    r = hg.check("up to 6% net, variable, paper, realized track, drawdown shown", FACTS)
    assert 6.0 not in r.unmatched_numbers
