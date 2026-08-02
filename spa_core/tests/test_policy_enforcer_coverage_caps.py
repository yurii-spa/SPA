"""ADR-062 (W4.1) — caps policy.py enforces per-trade but the enforcer never
checked on a WHOLE portfolio.

Before this change ``validate_positions`` applied ONE flat 40 % per-protocol cap
and no chain caps at all, so a book assembled from individually-legal trades could
sit over ``max_concentration_t2`` (20 %), ``BASE_CHAIN_CAP`` (20 %),
``max_l2_total_allocation`` (50 %) or ``max_single_chain_allocation`` (90 %)
indefinitely.

Values are NOT changed by this work — only coverage. The parity tests below pin
that every new threshold still reads from RiskConfig, so the enforcer can never
drift from the authoritative gate.

Deterministic + offline: every test injects its own ``chain_map`` so the suite
never depends on the live ``data/adapter_registry.json``.
"""
from __future__ import annotations

import pytest

from spa_core.risk import policy_enforcer as PE
from spa_core.risk.policy_enforcer import RULES, validate_positions

try:
    from spa_core.risk.policy import RiskConfig
    _CFG = RiskConfig()
except Exception:  # pragma: no cover
    _CFG = None


CAP = 100_000.0
# Chains chosen so each test states its own topology explicitly.
CHAINS = {
    "aave_v3": "ethereum",          # T1
    "compound_v3": "ethereum",      # T1
    "maple": "ethereum",            # T2
    "yearn_v3": "ethereum",         # T2
    "morpho_blue_base": "base",     # T2 on Base
    "moonwell_base": "base",        # T3 on Base
    "aave_v3_base": "base",         # T1 on Base
    "aave_arbitrum": "arbitrum",    # T1 on Arbitrum
    "susde": "ethereum",            # T3
}


def _check(positions, cash=None, chain_map=CHAINS):
    deployed = sum(positions.values())
    return validate_positions(
        positions=positions,
        capital_usd=CAP,
        cash_usd=CAP - deployed if cash is None else cash,
        chain_map=chain_map,
    )


def _rules(result):
    return {v.rule for v in result.violations}


def _warn_rules(result):
    return {w.rule for w in result.warnings}


# ── parity: every new threshold comes from RiskConfig, nothing hardcoded ─────


@pytest.mark.skipif(_CFG is None, reason="policy.py not importable")
def test_new_caps_are_read_from_riskconfig() -> None:
    assert float(RULES["per_protocol_t1_max_pct"]) == _CFG.max_concentration_t1 * 100.0
    assert float(RULES["per_protocol_t2_max_pct"]) == _CFG.max_concentration_t2 * 100.0
    assert float(RULES["base_chain_max_pct"]) == _CFG.BASE_CHAIN_CAP * 100.0
    assert float(RULES["l2_total_max_pct"]) == _CFG.max_l2_total_allocation * 100.0
    assert float(RULES["single_chain_max_pct"]) == _CFG.max_single_chain_allocation * 100.0


# ── per-protocol cap is now tier-aware (the gap the card was about) ──────────


def test_t2_protocol_over_20pct_is_now_rejected() -> None:
    """The exact case that used to pass: a T2 pool at 21 % under the flat 40 % cap."""
    r = _check({"maple": 21_000.0, "aave_v3": 30_000.0})
    assert not r.passed
    assert "per_protocol_max_pct" in _rules(r)
    assert any("maple" in v.message and "T2" in v.message for v in r.violations)


def test_t3_protocol_uses_the_t2_cap() -> None:
    """policy.py:410-411 gives the T1 cap to T1 and the T2 cap to everything else."""
    r = _check({"susde": 14_000.0, "aave_v3": 30_000.0})   # 14 % T3 ≤ 20 % ✓ (T3 total 15 %)
    assert r.passed, [v.message for v in r.violations]
    r2 = _check({"moonwell_base": 21_000.0, "aave_v3": 30_000.0})
    assert not r2.passed and "per_protocol_max_pct" in _rules(r2)


def test_t1_protocol_keeps_its_40pct_cap() -> None:
    assert _check({"aave_v3": 40_000.0, "maple": 20_000.0}).passed
    over = _check({"aave_v3": 41_000.0, "maple": 20_000.0})
    assert not over.passed and "per_protocol_max_pct" in _rules(over)


def test_position_exactly_at_cap_is_not_rejected_by_float_noise() -> None:
    """20 000/100 000 can surface as 20.000000000000004 — that must not reject."""
    r = _check({"maple": 20_000.0, "aave_v3": 40_000.0})
    assert r.passed, [v.message for v in r.violations]


# ── chain caps (never checked on a portfolio before) ─────────────────────────


def test_base_chain_over_20pct_is_rejected() -> None:
    r = _check({"morpho_blue_base": 20_000.0, "aave_v3_base": 5_000.0, "aave_v3": 40_000.0})
    assert not r.passed
    assert "base_chain_max_pct" in _rules(r)
    assert r.portfolio_summary["base_pct"] == 25.0


def test_l2_combined_over_50pct_is_rejected() -> None:
    r = _check({
        "morpho_blue_base": 20_000.0,     # base
        "aave_v3_base": 20_000.0,         # base  → base 40 % (also breaches base cap)
        "aave_arbitrum": 15_000.0,        # arbitrum
        "aave_v3": 20_000.0,              # ethereum
    })
    assert not r.passed
    assert "l2_total_max_pct" in _rules(r)
    assert r.portfolio_summary["l2_pct"] == 55.0


def test_single_chain_over_90pct_is_rejected() -> None:
    r = _check({"aave_v3": 40_000.0, "compound_v3": 40_000.0, "maple": 15_000.0}, cash=5_000.0)
    assert not r.passed
    assert "single_chain_max_pct" in _rules(r)


def test_single_chain_between_85_and_90_warns_but_passes() -> None:
    """Mirrors policy.py:443 — approaching a limit informs, it does not block."""
    r = _check({"aave_v3": 40_000.0, "maple": 20_000.0, "yearn_v3": 20_000.0,
                "compound_v3": 5_000.0}, cash=15_000.0)
    assert r.passed
    assert "single_chain_approaching" in _warn_rules(r)


# ── unattributed capital: published as UNCHECKED, never guessed into a verdict ──


def test_unresolved_chain_is_reported_as_unchecked_not_as_a_violation() -> None:
    """An unknown chain is missing evidence, not proof of a breach.

    A first version of this rule escalated to CRITICAL when the unresolved USD
    *could* breach a cap in the worst case. That is a guess dressed as a verdict —
    each unresolved protocol could equally sit on its own chain, breaching nothing —
    and operationally it turns a registry gap into a stop the allocator cannot clear
    (the "irreversible unchecked" failure mode). Caps bind on what is known; what is
    unknown is published as unchecked scope.
    """
    r = _check({"aave_v3": 40_000.0, "mystery_pool": 20_000.0, "other_mystery": 5_000.0},
               chain_map={"aave_v3": "ethereum"})
    assert r.passed, [v.message for v in r.violations]
    assert "chain_unresolved" in _warn_rules(r)
    assert r.portfolio_summary["chain_unresolved"] == ["mystery_pool", "other_mystery"]
    assert r.portfolio_summary["chain_unresolved_pct"] == 25.0


def test_resolved_portion_still_binds_when_others_are_unknown() -> None:
    """Unknown neighbours never excuse a breach that the KNOWN positions already make."""
    r = _check({"morpho_blue_base": 20_000.0, "aave_v3_base": 5_000.0, "mystery_pool": 10_000.0},
               chain_map={"morpho_blue_base": "base", "aave_v3_base": "base"})
    assert not r.passed
    assert "base_chain_max_pct" in _rules(r)
    assert "chain_unresolved" in _warn_rules(r)


def test_unresolved_capital_is_never_silently_dropped() -> None:
    """The old failure mode: unattributed USD vanishing from the chain totals."""
    r = _check({"aave_v3": 40_000.0, "mystery_pool": 5_000.0}, chain_map={"aave_v3": "ethereum"})
    assert r.portfolio_summary["chain_unresolved_pct"] == 5.0
    assert r.portfolio_summary["chain_pct"] == {"ethereum": 40.0}


# ── the live book must keep passing (measured 2026-08-02) ───────────────────


def test_current_book_passes_every_new_check() -> None:
    """The post-ADR-061 book: only strengthening, no disruption of a valid book."""
    r = _check(
        {"pendle": 20_000.0, "maple": 20_000.0, "morpho_blue_base": 10_000.0,
         "morpho_steakhouse": 40_000.0, "compound_v3": 5_000.0},
        cash=5_000.0,
        chain_map={"pendle": "ethereum", "maple": "ethereum", "morpho_blue_base": "base",
                   "morpho_steakhouse": "ethereum", "compound_v3": "ethereum"},
    )
    assert r.passed, [v.message for v in r.violations]
    assert r.portfolio_summary["base_pct"] == 10.0
    assert r.portfolio_summary["l2_pct"] == 10.0


def test_chain_resolution_prefers_the_live_registry_over_the_static_map() -> None:
    """The static map covers 10 of 34 adapters and misses morpho_steakhouse/pendle.

    Resolving only through it would leave 60 % of the current book unattributed —
    a fail-OPEN hole in exactly the caps this ADR adds. The registry must win.
    """
    resolved, unresolved = PE._resolve_chain_map(["morpho_steakhouse", "pendle", "maple"])
    assert unresolved == [], unresolved
    assert resolved["morpho_steakhouse"] == "ethereum"
