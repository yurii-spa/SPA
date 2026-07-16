"""Tests for spa_core/cmo/honesty_gate.py — deterministic, fail-CLOSED honesty gate."""
from __future__ import annotations

import pytest
from spa_core.cmo.honesty_gate import check_draft, GateResult, _extract_numbers, _collect_source_numbers, _number_allowed


# ── helpers ────────────────────────────────────────────────────────────────────

GOOD_FACTS = {
    "paper_apy_pct": 12.5,
    "track_days": 22,
    "nav_usd": 101200.0,
    "drawdown_pct": -3.1,
}

GOOD_DRAFT = (
    "Our paper trading strategy has achieved a paper APY of 12.5% over 22 days. "
    "This is not a guarantee of future returns. Past performance is no guarantee. "
    "Current NAV is $101,200. There is risk of drawdown. "
    "Simulated results only — not real capital."
)


# ── GateResult ─────────────────────────────────────────────────────────────────

class TestGateResult:
    def test_passed_is_truthy(self):
        assert GateResult(passed=True)

    def test_failed_is_falsy(self):
        assert not GateResult(passed=False)

    def test_violations_default_empty(self):
        r = GateResult(passed=True)
        assert r.violations == []


# ── _extract_numbers ───────────────────────────────────────────────────────────

class TestExtractNumbers:
    def test_plain_integer(self):
        assert 42.0 in _extract_numbers("foo 42 bar")

    def test_decimal(self):
        assert 12.5 in _extract_numbers("APY of 12.5%")

    def test_with_currency(self):
        assert 1000.0 in _extract_numbers("NAV $1,000")

    def test_comma_separated(self):
        assert 101200.0 in _extract_numbers("NAV $101,200")

    def test_ignores_zero(self):
        assert 0.0 not in _extract_numbers("0% drawdown")

    def test_ignores_trillion_plus(self):
        # numbers >= 1e12 (1 trillion) are excluded as implausible financial figures
        assert 1e12 not in _extract_numbers("value 1000000000000")

    def test_multiple(self):
        nums = _extract_numbers("12.5% over 22 days, NAV $101,200")
        assert 12.5 in nums
        assert 22.0 in nums
        assert 101200.0 in nums


# ── _collect_source_numbers ────────────────────────────────────────────────────

class TestCollectSourceNumbers:
    def test_dict_values(self):
        nums = _collect_source_numbers({"a": 12.5, "b": 22})
        assert 12.5 in nums
        assert 22.0 in nums

    def test_nested_dict(self):
        nums = _collect_source_numbers({"outer": {"inner": 99.9}})
        assert 99.9 in nums

    def test_list_values(self):
        nums = _collect_source_numbers([1.1, 2.2, 3.3])
        assert 2.2 in nums

    def test_string_extraction(self):
        nums = _collect_source_numbers("APY 12.5%")
        assert 12.5 in nums

    def test_bool_excluded(self):
        nums = _collect_source_numbers({"flag": True})
        assert 1.0 not in nums  # bool must not be treated as 1.0

    def test_depth_limit(self):
        # depth > 6 should return []
        deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 999.9}}}}}}}
        nums = _collect_source_numbers(deep)
        # the value at depth 7 should be excluded
        assert 999.9 not in nums


# ── _number_allowed ────────────────────────────────────────────────────────────

class TestNumberAllowed:
    def test_small_integer_always_ok(self):
        assert _number_allowed(30.0, [])
        assert _number_allowed(100.0, [])

    def test_small_integer_boundary(self):
        assert _number_allowed(100.0, [])
        assert not _number_allowed(101.0, [])  # 101 is not a small round int

    def test_exact_match(self):
        assert _number_allowed(12.5, [12.5])

    def test_within_tolerance(self):
        # 12.5 * 1.019 = 12.7375 — within 2%
        assert _number_allowed(12.7375, [12.5])

    def test_outside_tolerance(self):
        # 12.5 * 1.03 = 12.875 — outside 2%
        assert not _number_allowed(12.875, [12.5])

    def test_no_source_numbers(self):
        assert not _number_allowed(999.0, [])


# ── check_draft — happy path ───────────────────────────────────────────────────

class TestCheckDraftPass:
    def test_good_draft_passes(self):
        result = check_draft(GOOD_DRAFT, GOOD_FACTS)
        assert result.passed, result.violations

    def test_returns_gate_result(self):
        result = check_draft(GOOD_DRAFT, GOOD_FACTS)
        assert isinstance(result, GateResult)

    def test_no_violations_on_pass(self):
        result = check_draft(GOOD_DRAFT, GOOD_FACTS)
        assert result.violations == []


# ── (1) numbers-match check ────────────────────────────────────────────────────

class TestNumbersMatch:
    def test_invented_number_rejected(self):
        draft = GOOD_DRAFT + " The projected return is 47.3%."
        result = check_draft(draft, GOOD_FACTS)
        assert not result.passed
        assert any("number-not-in-source" in v for v in result.violations)

    def test_number_within_tolerance_passes(self):
        # 12.55 is within 2% of 12.5 in source
        draft = (
            "Paper APY of 12.55% over 22 days. Not a guarantee. "
            "There is drawdown risk. Simulated results, not real capital."
        )
        result = check_draft(draft, GOOD_FACTS)
        assert result.passed, result.violations

    def test_extra_allowed_numbers_pass(self):
        draft = (
            "Paper APY of 12.5% over 22 days with a 365-day track. "
            "Not a guarantee. There is drawdown risk. Simulated results, not real capital."
        )
        result = check_draft(draft, GOOD_FACTS, extra_allowed_numbers=[365.0])
        assert result.passed, result.violations

    def test_small_integer_always_allowed(self):
        draft = (
            "Paper APY 12.5% over 22 days in 5 protocols. "
            "Not a guarantee. There is drawdown risk. Simulated results, not real capital."
        )
        result = check_draft(draft, GOOD_FACTS)
        assert result.passed, result.violations

    def test_large_round_integer_not_allowed(self):
        draft = GOOD_DRAFT + " History: 120 days."
        result = check_draft(draft, GOOD_FACTS)
        assert not result.passed
        assert any("number-not-in-source" in v for v in result.violations)


# ── (2) disclaimer groups ──────────────────────────────────────────────────────

class TestDisclaimerGroups:
    def _base_draft(self, facts=None):
        return (
            "Paper APY of 12.5% over 22 days. "
            "Not a guarantee of future returns. "
            "There is drawdown risk. Simulated results, not real capital."
        )

    def test_missing_paper_framing(self):
        draft = (
            "APY of 12.5% over 22 days. "
            "Not a guarantee of future returns. "
            "There is drawdown risk."
        )
        result = check_draft(draft, GOOD_FACTS)
        assert not result.passed
        assert any("paper-framing" in v for v in result.violations)

    def test_missing_not_a_guarantee(self):
        draft = (
            "Paper APY of 12.5% over 22 days. "
            "There is drawdown risk. Simulated results."
        )
        result = check_draft(draft, GOOD_FACTS)
        assert not result.passed
        assert any("not-a-guarantee" in v for v in result.violations)

    def test_missing_tail_shown(self):
        draft = (
            "Paper APY of 12.5% over 22 days. "
            "Not a guarantee. Simulated results only."
        )
        result = check_draft(draft, GOOD_FACTS)
        assert not result.passed
        assert any("tail-shown" in v for v in result.violations)

    def test_require_all_false_skips_groups(self):
        draft = "Paper APY 12.5% over 22 days."
        result = check_draft(draft, GOOD_FACTS, require_all_disclaimer_groups=False)
        assert not any("missing-disclaimer-group" in v for v in result.violations)

    def test_russian_keywords_satisfy_groups(self):
        draft = (
            "Бумажная торговля APY 12.5% за 22 дня. "
            "Это не гарантия доходности. "
            "Существует риск просадки."
        )
        result = check_draft(draft, GOOD_FACTS)
        assert result.passed, result.violations

    def test_all_three_groups_satisfied(self):
        result = check_draft(GOOD_DRAFT, GOOD_FACTS)
        assert not any("missing-disclaimer-group" in v for v in result.violations)


# ── (3) promissory language ────────────────────────────────────────────────────

class TestPromissoryLanguage:
    def _draft_with(self, phrase):
        return (
            f"Paper APY 12.5% over 22 days. {phrase} "
            "Not a guarantee. There is drawdown risk. Simulated, not real capital."
        )

    def test_guaranteed_return_rejected(self):
        result = check_draft(self._draft_with("Guaranteed return of 10%."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_will_earn_rejected(self):
        result = check_draft(self._draft_with("You will earn 5% monthly."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_risk_free_rejected(self):
        result = check_draft(self._draft_with("This is risk-free income."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_no_risk_rejected(self):
        result = check_draft(self._draft_with("There is no risk in this strategy."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_zero_risk_rejected(self):
        result = check_draft(self._draft_with("Zero-risk portfolio construction."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_guarantees_rejected(self):
        result = check_draft(self._draft_with("The strategy guarantees a profit."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_proven_profit_rejected(self):
        result = check_draft(self._draft_with("This is a proven profit system."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_guaranteed_yield_rejected(self):
        result = check_draft(self._draft_with("Enjoy guaranteed yield every month."), GOOD_FACTS)
        assert not result.passed
        assert any("promissory-language" in v for v in result.violations)

    def test_clean_draft_no_promissory(self):
        result = check_draft(GOOD_DRAFT, GOOD_FACTS)
        assert not any("promissory-language" in v for v in result.violations)


# ── (4) live/offer framing ─────────────────────────────────────────────────────

class TestLiveOfferFraming:
    def _draft_with(self, phrase):
        return (
            f"Paper APY 12.5% over 22 days. {phrase} "
            "Not a guarantee. There is drawdown risk. Simulated, not real capital."
        )

    def test_invest_now_rejected(self):
        result = check_draft(self._draft_with("Invest now and earn."), GOOD_FACTS)
        assert not result.passed
        assert any("live-offer-framing" in v for v in result.violations)

    def test_deposit_now_rejected(self):
        result = check_draft(self._draft_with("Deposit now to start earning."), GOOD_FACTS)
        assert not result.passed
        assert any("live-offer-framing" in v for v in result.violations)

    def test_accepting_capital_rejected(self):
        result = check_draft(self._draft_with("We are accepting capital from investors."), GOOD_FACTS)
        assert not result.passed
        assert any("live-offer-framing" in v for v in result.violations)

    def test_open_for_investment_rejected(self):
        result = check_draft(self._draft_with("The fund is open for investment."), GOOD_FACTS)
        assert not result.passed
        assert any("live-offer-framing" in v for v in result.violations)

    def test_live_trading_rejected(self):
        result = check_draft(self._draft_with("Currently live trading on mainnet."), GOOD_FACTS)
        assert not result.passed
        assert any("live-offer-framing" in v for v in result.violations)

    def test_actual_fund_rejected(self):
        result = check_draft(self._draft_with("Join the actual fund today."), GOOD_FACTS)
        assert not result.passed
        assert any("live-offer-framing" in v for v in result.violations)

    def test_solicitation_rejected(self):
        result = check_draft(self._draft_with("This is not a solicitation."), GOOD_FACTS)
        assert not result.passed
        assert any("live-offer-framing" in v for v in result.violations)

    def test_clean_draft_no_live_framing(self):
        result = check_draft(GOOD_DRAFT, GOOD_FACTS)
        assert not any("live-offer-framing" in v for v in result.violations)


# ── fail-CLOSED behavior ───────────────────────────────────────────────────────

class TestFailClosed:
    def test_exception_in_facts_returns_rejected(self):
        class ExplodingDict(dict):
            def values(self):
                raise RuntimeError("db exploded")
        result = check_draft("some draft", ExplodingDict())
        assert not result.passed
        assert any("gate-error" in v for v in result.violations)

    def test_none_draft_returns_rejected(self):
        result = check_draft(None, GOOD_FACTS)
        assert not result.passed

    def test_empty_draft_fails_disclaimers(self):
        result = check_draft("", GOOD_FACTS)
        assert not result.passed
        assert any("missing-disclaimer-group" in v for v in result.violations)

    def test_multiple_violations_all_reported(self):
        draft = "Guaranteed return of 47.3%. Invest now."
        result = check_draft(draft, {})
        assert not result.passed
        assert len(result.violations) >= 3  # numbers + promissory + live-offer + disclaimers


# ── edge cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_case_insensitive_disclaimer(self):
        draft = (
            "PAPER trading strategy with 12.5% over 22 days. "
            "NOT A GUARANTEE. DRAWDOWN risk. NOT REAL CAPITAL."
        )
        result = check_draft(draft, GOOD_FACTS)
        assert result.passed, result.violations

    def test_case_insensitive_promissory(self):
        draft = GOOD_DRAFT + " GUARANTEED RETURN of 5%."
        result = check_draft(draft, GOOD_FACTS)
        assert not result.passed

    def test_empty_source_facts_fails_numbers(self):
        result = check_draft(GOOD_DRAFT, {})
        assert not result.passed
        # 12.5, 22, 101200 are all non-trivial numbers not in empty source
        assert any("number-not-in-source" in v for v in result.violations)

    def test_source_facts_as_list(self):
        draft = (
            "Paper APY 12.5% over 22 days. "
            "Not a guarantee. There is drawdown risk. Simulated, not real capital."
        )
        result = check_draft(draft, [12.5, 22])
        assert result.passed, result.violations

    def test_number_only_in_string_source_fact(self):
        draft = (
            "Paper APY 12.5% over 22 days. "
            "Not a guarantee. There is drawdown risk. Simulated, not real capital."
        )
        result = check_draft(draft, {"note": "APY 12.5%, track 22 days"})
        assert result.passed, result.violations
