#!/usr/bin/env python3
"""Unit tests for MP-1093 ProtocolDeFiSmartContractUpgradeRiskAnalyzer (SPA-V784).

Run:
    python3 -m unittest spa_core/tests/test_protocol_defi_smart_contract_upgrade_risk_analyzer.py -v

All tests use stdlib unittest only — no pytest, no numpy, no external deps.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.protocol_defi_smart_contract_upgrade_risk_analyzer import (
    ProtocolDeFiSmartContractUpgradeRiskAnalyzer,
    analyze,
    timelock_adequacy,
    upgrade_risk_label,
    governance_decentralization_score,
    upgrade_risk_score,
    _load_json_list,
    _atomic_write,
    LOG_FILENAME,
    RING_BUFFER_CAP,
    SCHEMA_VERSION,
    SOURCE_NAME,
    MP_TAG,
    TIMELOCK_STRONG_H,
    TIMELOCK_ADEQUATE_H,
    GOV_MULTISIG_MAX,
    GOV_TIMELOCK_MAX,
    GOV_AUDIT_MAX,
    GOV_AUDIT_PER_UNIT,
    GOV_STABILITY_BONUS,
    MULTISIG_RATIO_MIN,
    RISK_TIMELOCK_STRONG_REDUCTION,
    RISK_TIMELOCK_ADEQUATE_REDUCTION,
    RISK_TIMELOCK_WEAK_REDUCTION,
    RISK_FREQUENCY_PENALTY,
    RISK_FREQUENCY_THRESHOLD,
    RISK_RECENCY_PENALTY,
    RISK_RECENCY_MAX_DAYS,
)


# ===========================================================================
# 1. timelock_adequacy
# ===========================================================================

class TestTimelockAdequacy(unittest.TestCase):

    def test_zero_hours_is_none(self):
        self.assertEqual(timelock_adequacy(0), "NONE")

    def test_negative_is_none(self):
        """Negative timelock treated as no timelock."""
        self.assertEqual(timelock_adequacy(-1), "NONE")

    def test_one_hour_is_weak(self):
        self.assertEqual(timelock_adequacy(1), "WEAK")

    def test_twelve_hours_is_weak(self):
        self.assertEqual(timelock_adequacy(12), "WEAK")

    def test_twenty_three_hours_is_weak(self):
        """Just below ADEQUATE threshold."""
        self.assertEqual(timelock_adequacy(23), "WEAK")

    def test_twenty_four_hours_is_adequate(self):
        self.assertEqual(timelock_adequacy(TIMELOCK_ADEQUATE_H), "ADEQUATE")

    def test_forty_eight_hours_is_adequate(self):
        self.assertEqual(timelock_adequacy(48), "ADEQUATE")

    def test_seventy_one_hours_is_adequate(self):
        """Just below STRONG threshold."""
        self.assertEqual(timelock_adequacy(71), "ADEQUATE")

    def test_seventy_two_hours_is_strong(self):
        self.assertEqual(timelock_adequacy(TIMELOCK_STRONG_H), "STRONG")

    def test_one_week_is_strong(self):
        self.assertEqual(timelock_adequacy(168), "STRONG")

    def test_very_long_timelock_is_strong(self):
        self.assertEqual(timelock_adequacy(720), "STRONG")

    def test_adequacy_constant_adequate_h(self):
        self.assertEqual(TIMELOCK_ADEQUATE_H, 24)

    def test_adequacy_constant_strong_h(self):
        self.assertEqual(TIMELOCK_STRONG_H, 72)


# ===========================================================================
# 2. upgrade_risk_label — all 5 categories and boundary conditions
# ===========================================================================

class TestUpgradeRiskLabel(unittest.TestCase):

    # IMMUTABLE_SAFE — rule 1
    def test_immutable_safe_not_upgradeable(self):
        self.assertEqual(
            upgrade_risk_label(False, 0, False, 0), "IMMUTABLE_SAFE"
        )

    def test_immutable_safe_ignores_timelock(self):
        """Rule 1 short-circuits: any timelock, still IMMUTABLE_SAFE."""
        self.assertEqual(
            upgrade_risk_label(False, 168, True, 5), "IMMUTABLE_SAFE"
        )

    def test_immutable_safe_ignores_multisig(self):
        self.assertEqual(
            upgrade_risk_label(False, 72, True, 2), "IMMUTABLE_SAFE"
        )

    # WELL_GOVERNED — rule 2
    def test_well_governed_all_conditions_met(self):
        self.assertEqual(
            upgrade_risk_label(True, 72, True, 2), "WELL_GOVERNED"
        )

    def test_well_governed_strong_timelock_many_audits(self):
        self.assertEqual(
            upgrade_risk_label(True, 168, True, 5), "WELL_GOVERNED"
        )

    def test_well_governed_requires_multisig(self):
        """Without multisig, rule 2 fails; falls to rule 3 (timelock>=24 AND audits>=1)."""
        result = upgrade_risk_label(True, 72, False, 5)
        self.assertEqual(result, "MODERATE_RISK")

    def test_well_governed_requires_audit_count_2(self):
        """audit_count=1 fails rule 2; falls to rule 3."""
        result = upgrade_risk_label(True, 72, True, 1)
        self.assertEqual(result, "MODERATE_RISK")

    def test_well_governed_requires_timelock_72(self):
        """timelock=48 fails rule 2; with multisig falls to rule 3."""
        result = upgrade_risk_label(True, 48, True, 2)
        self.assertEqual(result, "MODERATE_RISK")

    def test_well_governed_exact_boundary_72h_2audits(self):
        self.assertEqual(upgrade_risk_label(True, 72, True, 2), "WELL_GOVERNED")

    # MODERATE_RISK — rule 3
    def test_moderate_risk_timelock_24_multisig(self):
        self.assertEqual(
            upgrade_risk_label(True, 24, True, 0), "MODERATE_RISK"
        )

    def test_moderate_risk_timelock_24_audits_1(self):
        self.assertEqual(
            upgrade_risk_label(True, 24, False, 1), "MODERATE_RISK"
        )

    def test_moderate_risk_timelock_48_multisig(self):
        self.assertEqual(
            upgrade_risk_label(True, 48, True, 0), "MODERATE_RISK"
        )

    def test_moderate_risk_timelock_48_audits_only(self):
        self.assertEqual(
            upgrade_risk_label(True, 48, False, 3), "MODERATE_RISK"
        )

    def test_moderate_risk_timelock_24_no_governance_is_high(self):
        """timelock=24h but NO multisig AND 0 audits fails rule 3."""
        result = upgrade_risk_label(True, 24, False, 0)
        self.assertEqual(result, "HIGH_RISK")

    # HIGH_RISK — rule 4
    def test_high_risk_small_timelock_no_governance(self):
        self.assertEqual(
            upgrade_risk_label(True, 12, False, 0), "HIGH_RISK"
        )

    def test_high_risk_one_hour_timelock(self):
        self.assertEqual(
            upgrade_risk_label(True, 1, False, 0), "HIGH_RISK"
        )

    def test_high_risk_23_hours_no_governance(self):
        self.assertEqual(
            upgrade_risk_label(True, 23, False, 0), "HIGH_RISK"
        )

    # CRITICAL_UPGRADE_RISK — rule 5
    def test_critical_upgradeable_no_timelock(self):
        self.assertEqual(
            upgrade_risk_label(True, 0, False, 0), "CRITICAL_UPGRADE_RISK"
        )

    def test_critical_upgradeable_no_timelock_despite_multisig(self):
        """Even with multisig+audits, if timelock=0 it's CRITICAL."""
        self.assertEqual(
            upgrade_risk_label(True, 0, True, 10), "CRITICAL_UPGRADE_RISK"
        )

    def test_critical_upgradeable_no_timelock_despite_audits(self):
        self.assertEqual(
            upgrade_risk_label(True, 0, False, 5), "CRITICAL_UPGRADE_RISK"
        )

    def test_all_five_labels_exist(self):
        labels = {
            upgrade_risk_label(False, 0, False, 0),
            upgrade_risk_label(True, 72, True, 2),
            upgrade_risk_label(True, 48, True, 0),
            upgrade_risk_label(True, 12, False, 0),
            upgrade_risk_label(True, 0, False, 0),
        }
        self.assertEqual(labels, {
            "IMMUTABLE_SAFE", "WELL_GOVERNED", "MODERATE_RISK",
            "HIGH_RISK", "CRITICAL_UPGRADE_RISK",
        })


# ===========================================================================
# 3. governance_decentralization_score
# ===========================================================================

class TestGovernanceDecentralizationScore(unittest.TestCase):

    def _score(self, **kw):
        defaults = dict(
            is_upgradeable=True,
            has_timelock=True,
            timelock_hours=72,
            multisig_required=True,
            multisig_signers=5,
            multisig_threshold=3,
            audit_count=2,
            days_since_last_upgrade=0,
            upgrade_history_count=0,
        )
        defaults.update(kw)
        return governance_decentralization_score(**defaults)

    def test_immutable_returns_100(self):
        self.assertEqual(self._score(is_upgradeable=False), 100)

    def test_immutable_ignores_all_params(self):
        s = governance_decentralization_score(
            is_upgradeable=False, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, 100)

    def test_worst_case_upgradeable_no_governance(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, 0)

    def test_multisig_only_base(self):
        """Just multisig required, no threshold bonus or ratio bonus."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=1, multisig_threshold=1,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        # multisig base (20) only; threshold <2 → no bonus; ratio=1.0>=0.5 → +10
        self.assertEqual(s, 20 + 10)

    def test_multisig_threshold_bonus(self):
        """threshold >= 2 gives extra 10."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=5, multisig_threshold=2,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        # ratio = 2/5 = 0.4 < 0.5 → no ratio bonus
        self.assertEqual(s, 20 + 10)  # base + threshold bonus

    def test_multisig_ratio_bonus(self):
        """threshold/signers >= 0.5 gives additional 10."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=4, multisig_threshold=2,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        # ratio = 2/4 = 0.5 >= 0.5 → ratio bonus
        self.assertEqual(s, 20 + 10 + 10)  # base + threshold + ratio

    def test_multisig_all_three_components(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=5, multisig_threshold=3,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        # 3/5 = 0.6 >= 0.5 → all three: 20+10+10=40
        self.assertEqual(s, GOV_MULTISIG_MAX)

    def test_timelock_strong(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=72,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, GOV_TIMELOCK_MAX)

    def test_timelock_adequate(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=48,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, 20)

    def test_timelock_weak(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=12,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, 10)

    def test_audit_component_one(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=1, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, GOV_AUDIT_PER_UNIT)  # 8

    def test_audit_component_capped(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=10, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, GOV_AUDIT_MAX)  # 25

    def test_stability_bonus(self):
        """Upgrade history > 0 AND days > 180 gives stability bonus."""
        s_without = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=200, upgrade_history_count=1,
        )
        self.assertEqual(s_without, GOV_STABILITY_BONUS)

    def test_no_stability_bonus_if_no_history(self):
        """upgrade_history_count=0 → no stability bonus even if days > 180."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=200, upgrade_history_count=0,
        )
        self.assertEqual(s, 0)

    def test_no_stability_bonus_if_days_not_enough(self):
        """days_since_last_upgrade <= 180 → no stability bonus."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=180, upgrade_history_count=1,
        )
        self.assertEqual(s, 0)  # 180 is NOT > 180

    def test_maximum_score_all_components(self):
        """All components maxed out = 100."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=168,
            multisig_required=True, multisig_signers=5, multisig_threshold=4,
            audit_count=4, days_since_last_upgrade=200, upgrade_history_count=2,
        )
        # 40 + 30 + 25 + 5 = 100
        self.assertEqual(s, 100)

    def test_score_nonnegative(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertGreaterEqual(s, 0)

    def test_score_at_most_100(self):
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=1000,
            multisig_required=True, multisig_signers=100, multisig_threshold=99,
            audit_count=100, days_since_last_upgrade=1000, upgrade_history_count=100,
        )
        self.assertLessEqual(s, 100)

    def test_zero_signers_no_ratio_bonus(self):
        """multisig_signers=0 → division guard, no ratio bonus."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=0, multisig_threshold=3,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        # Only base multisig (20) + threshold bonus (10) if threshold>=2
        self.assertEqual(s, 20 + 10)

    def test_score_is_integer(self):
        s = self._score()
        self.assertIsInstance(s, int)


# ===========================================================================
# 4. upgrade_risk_score
# ===========================================================================

class TestUpgradeRiskScore(unittest.TestCase):

    def _score(self, **kw):
        defaults = dict(
            is_upgradeable=True,
            has_timelock=False,
            timelock_hours=0,
            multisig_required=False,
            multisig_signers=0,
            multisig_threshold=0,
            audit_count=0,
            days_since_last_upgrade=0,
            upgrade_history_count=0,
        )
        defaults.update(kw)
        return upgrade_risk_score(**defaults)

    def test_immutable_score_zero(self):
        self.assertEqual(self._score(is_upgradeable=False), 0)

    def test_worst_case_score_100(self):
        """Upgradeable, no timelock, no multisig, 0 audits, never upgraded."""
        self.assertEqual(self._score(), 100)

    def test_strong_timelock_reduces_score(self):
        s = self._score(timelock_hours=72)
        self.assertEqual(s, 100 - RISK_TIMELOCK_STRONG_REDUCTION)

    def test_adequate_timelock_reduces_score(self):
        s = self._score(timelock_hours=48)
        self.assertEqual(s, 100 - RISK_TIMELOCK_ADEQUATE_REDUCTION)

    def test_weak_timelock_reduces_score(self):
        s = self._score(timelock_hours=12)
        self.assertEqual(s, 100 - RISK_TIMELOCK_WEAK_REDUCTION)

    def test_multisig_base_reduces_score(self):
        """multisig_required=True, threshold=1, signers=3 (1/3<0.5, threshold<2)."""
        s = self._score(multisig_required=True, multisig_signers=3, multisig_threshold=1)
        # -15 (base), threshold=1 < 2 → no threshold reduction
        # ratio = 1/3 ≈ 0.333 < 0.5 → no ratio reduction
        self.assertEqual(s, 100 - 15)

    def test_multisig_with_threshold_reduces_score(self):
        """threshold=2, signers=5 (2/5=0.4 < 0.5): no ratio bonus."""
        s = self._score(multisig_required=True, multisig_signers=5, multisig_threshold=2)
        self.assertEqual(s, 100 - 15 - 8)

    def test_multisig_full_reduces_score(self):
        """threshold=3, signers=5 (3/5=0.6 >= 0.5): all three reductions."""
        s = self._score(multisig_required=True, multisig_signers=5, multisig_threshold=3)
        self.assertEqual(s, 100 - 15 - 8 - 7)

    def test_one_audit_reduces_score(self):
        s = self._score(audit_count=1)
        self.assertEqual(s, 100 - 8)

    def test_audit_reduction_capped(self):
        s_many = self._score(audit_count=10)
        self.assertEqual(s_many, 100 - 20)  # max reduction is 20

    def test_audit_cap_at_two_point_five(self):
        """2 audits = 16, 3 = 20 (capped at 20)."""
        self.assertEqual(self._score(audit_count=2), 100 - 16)
        self.assertEqual(self._score(audit_count=3), 100 - 20)

    def test_frequency_penalty_applied(self):
        # Use strong timelock so base score < 100 and penalty becomes visible
        s_normal = self._score(timelock_hours=72, upgrade_history_count=5)
        s_freq = self._score(timelock_hours=72, upgrade_history_count=6)
        self.assertEqual(s_freq - s_normal, RISK_FREQUENCY_PENALTY)

    def test_frequency_penalty_not_applied_at_threshold(self):
        """upgrade_history_count == RISK_FREQUENCY_THRESHOLD does NOT trigger penalty."""
        s_at = self._score(upgrade_history_count=RISK_FREQUENCY_THRESHOLD)
        s_below = self._score(upgrade_history_count=RISK_FREQUENCY_THRESHOLD - 1)
        self.assertEqual(s_at, s_below)  # no penalty at exactly threshold

    def test_recency_penalty_applied(self):
        # Use strong timelock so base score < 100 and penalty becomes visible
        s_old = self._score(timelock_hours=72, days_since_last_upgrade=50)
        s_recent = self._score(timelock_hours=72, days_since_last_upgrade=15)
        self.assertEqual(s_recent - s_old, RISK_RECENCY_PENALTY)

    def test_recency_penalty_not_applied_for_never_upgraded(self):
        """days_since_last_upgrade = 0 means never upgraded, no recency penalty."""
        s_never = self._score(days_since_last_upgrade=0)
        s_old = self._score(days_since_last_upgrade=50)
        self.assertEqual(s_never, s_old)

    def test_recency_penalty_not_applied_at_boundary(self):
        """days >= 30 does not trigger recency penalty."""
        s_at = self._score(days_since_last_upgrade=RISK_RECENCY_MAX_DAYS)
        s_old = self._score(days_since_last_upgrade=100)
        self.assertEqual(s_at, s_old)

    def test_recency_penalty_at_day_29(self):
        """day=29 < 30 triggers penalty; use strong timelock so base < 100."""
        s_29 = self._score(timelock_hours=72, days_since_last_upgrade=29)
        s_30 = self._score(timelock_hours=72, days_since_last_upgrade=30)
        self.assertEqual(s_29 - s_30, RISK_RECENCY_PENALTY)

    def test_well_governed_low_risk(self):
        """Aave-like: 168h timelock, 4/6 multisig, 4 audits, old upgrade."""
        s = upgrade_risk_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=168,
            multisig_required=True, multisig_signers=6, multisig_threshold=4,
            audit_count=4, days_since_last_upgrade=200, upgrade_history_count=2,
        )
        # 100 - 30 - 15 - 8 - 7 - 20 = 20
        self.assertEqual(s, 20)

    def test_score_clamped_at_zero(self):
        """Perfect governance cannot go below 0."""
        s = upgrade_risk_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=720,
            multisig_required=True, multisig_signers=10, multisig_threshold=9,
            audit_count=20, days_since_last_upgrade=500, upgrade_history_count=1,
        )
        self.assertGreaterEqual(s, 0)

    def test_score_clamped_at_100(self):
        """Worst governance with penalties still cannot exceed 100."""
        s = upgrade_risk_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=10, upgrade_history_count=10,
        )
        self.assertLessEqual(s, 100)

    def test_score_is_integer(self):
        self.assertIsInstance(self._score(), int)

    def test_combined_full_governance_with_frequency_penalty(self):
        """Good governance but many upgrades: penalties add back some risk."""
        s_good = upgrade_risk_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=72,
            multisig_required=True, multisig_signers=5, multisig_threshold=3,
            audit_count=2, days_since_last_upgrade=200, upgrade_history_count=3,
        )
        s_freq = upgrade_risk_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=72,
            multisig_required=True, multisig_signers=5, multisig_threshold=3,
            audit_count=2, days_since_last_upgrade=200, upgrade_history_count=6,
        )
        self.assertEqual(s_freq - s_good, RISK_FREQUENCY_PENALTY)

    def test_zero_signers_no_ratio_reduction(self):
        """multisig_signers=0 → guard prevents division, no ratio reduction."""
        s = upgrade_risk_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=0, multisig_threshold=3,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        # base (-15) + threshold>=2 (-8) + signers=0 (no ratio reduction)
        self.assertEqual(s, 100 - 15 - 8)

    def test_multiple_penalties_accumulate(self):
        """Both frequency and recency penalties stack; use strong timelock so base < 100."""
        s_no_penalty = upgrade_risk_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=72,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=50, upgrade_history_count=3,
        )
        s_both_penalties = upgrade_risk_score(
            is_upgradeable=True, has_timelock=True, timelock_hours=72,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=10, upgrade_history_count=6,
        )
        expected_diff = RISK_FREQUENCY_PENALTY + RISK_RECENCY_PENALTY
        self.assertEqual(s_both_penalties - s_no_penalty, expected_diff)


# ===========================================================================
# 5. analyze() — full end-to-end function
# ===========================================================================

class TestAnalyzeFunction(unittest.TestCase):

    def _call(self, **kw):
        defaults = dict(
            is_upgradeable=True,
            has_timelock=True,
            timelock_hours=72,
            multisig_required=True,
            multisig_signers=5,
            multisig_threshold=3,
            audit_count=2,
            days_since_last_upgrade=180,
            upgrade_history_count=2,
            protocol_name="TestProtocol",
        )
        defaults.update(kw)
        return analyze(**defaults)

    def test_returns_dict(self):
        self.assertIsInstance(self._call(), dict)

    def test_schema_version(self):
        self.assertEqual(self._call()["schema_version"], SCHEMA_VERSION)

    def test_source(self):
        self.assertEqual(self._call()["source"], SOURCE_NAME)

    def test_mp_tag(self):
        self.assertEqual(self._call()["mp_tag"], MP_TAG)

    def test_timestamp_present(self):
        r = self._call()
        self.assertIn("timestamp", r)
        ts = r["timestamp"]
        self.assertTrue(ts.endswith("Z") or "+" in ts or ts.endswith("+00:00"))

    def test_protocol_name_echoed(self):
        r = self._call(protocol_name="Aave")
        self.assertEqual(r["protocol_name"], "Aave")

    def test_immutable_safe_label(self):
        r = self._call(is_upgradeable=False)
        self.assertEqual(r["upgrade_risk_label"], "IMMUTABLE_SAFE")

    def test_immutable_risk_score_zero(self):
        r = self._call(is_upgradeable=False)
        self.assertEqual(r["upgrade_risk_score"], 0)

    def test_immutable_gov_score_100(self):
        r = self._call(is_upgradeable=False)
        self.assertEqual(r["governance_decentralization_score"], 100)

    def test_well_governed_label(self):
        r = self._call(timelock_hours=72, multisig_required=True, audit_count=2)
        self.assertEqual(r["upgrade_risk_label"], "WELL_GOVERNED")

    def test_critical_label(self):
        r = self._call(timelock_hours=0, multisig_required=False, audit_count=0)
        self.assertEqual(r["upgrade_risk_label"], "CRITICAL_UPGRADE_RISK")

    def test_timelock_adequacy_in_output(self):
        r = self._call(timelock_hours=0)
        self.assertEqual(r["timelock_adequacy"], "NONE")

    def test_timelock_adequacy_strong(self):
        r = self._call(timelock_hours=72)
        self.assertEqual(r["timelock_adequacy"], "STRONG")

    def test_all_output_keys_present(self):
        r = self._call()
        for key in [
            "governance_decentralization_score",
            "upgrade_risk_score",
            "timelock_adequacy",
            "upgrade_risk_label",
        ]:
            self.assertIn(key, r, f"Missing output key: {key}")

    def test_raw_inputs_echoed(self):
        r = self._call(
            is_upgradeable=True, timelock_hours=48, audit_count=3
        )
        self.assertIs(r["is_upgradeable"], True)
        self.assertEqual(r["timelock_hours"], 48)
        self.assertEqual(r["audit_count"], 3)

    def test_gov_score_in_range(self):
        r = self._call()
        self.assertGreaterEqual(r["governance_decentralization_score"], 0)
        self.assertLessEqual(r["governance_decentralization_score"], 100)

    def test_risk_score_in_range(self):
        r = self._call()
        self.assertGreaterEqual(r["upgrade_risk_score"], 0)
        self.assertLessEqual(r["upgrade_risk_score"], 100)

    def test_gov_score_is_int(self):
        r = self._call()
        self.assertIsInstance(r["governance_decentralization_score"], int)

    def test_risk_score_is_int(self):
        r = self._call()
        self.assertIsInstance(r["upgrade_risk_score"], int)

    def test_uniswap_v3_style_immutable(self):
        r = analyze(
            is_upgradeable=False, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=5, days_since_last_upgrade=0, upgrade_history_count=0,
            protocol_name="Uniswap V3",
        )
        self.assertEqual(r["upgrade_risk_label"], "IMMUTABLE_SAFE")
        self.assertEqual(r["upgrade_risk_score"], 0)

    def test_new_defi_critical_risk(self):
        r = analyze(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
            protocol_name="NewDeFi",
        )
        self.assertEqual(r["upgrade_risk_label"], "CRITICAL_UPGRADE_RISK")
        self.assertEqual(r["upgrade_risk_score"], 100)

    def test_timelock_adequacy_none_when_no_timelock(self):
        r = self._call(timelock_hours=0)
        self.assertEqual(r["timelock_adequacy"], "NONE")


# ===========================================================================
# 6. ProtocolDeFiSmartContractUpgradeRiskAnalyzer class
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.analyzer = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(
            data_dir=self.tmp_dir
        )

    def _run(self, **kw):
        defaults = dict(
            is_upgradeable=True,
            has_timelock=True,
            timelock_hours=72,
            multisig_required=True,
            multisig_signers=5,
            multisig_threshold=3,
            audit_count=2,
            days_since_last_upgrade=180,
            upgrade_history_count=2,
            protocol_name="Aave",
        )
        defaults.update(kw)
        return self.analyzer.analyze(**defaults)

    def test_analyze_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_get_last_result_before_analyze_is_none(self):
        fresh = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(data_dir=self.tmp_dir)
        self.assertIsNone(fresh.get_last_result())

    def test_get_last_result_after_analyze(self):
        r = self._run()
        self.assertEqual(self.analyzer.get_last_result(), r)

    def test_save_before_analyze_returns_false(self):
        fresh = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(data_dir=self.tmp_dir)
        self.assertFalse(fresh.save())

    def test_save_creates_log_file(self):
        self._run()
        self.analyzer.save()
        self.assertTrue((self.tmp_dir / LOG_FILENAME).exists())

    def test_save_returns_true_on_success(self):
        self._run()
        self.assertTrue(self.analyzer.save())

    def test_log_file_contains_list(self):
        self._run()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry_after_one_save(self):
        self._run()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        for _ in range(3):
            self._run()
            self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_last_result_updated_on_second_call(self):
        self._run(protocol_name="Aave")
        self._run(protocol_name="Compound")
        self.assertEqual(self.analyzer.get_last_result()["protocol_name"], "Compound")

    def test_ring_buffer_cap_enforced(self):
        for _ in range(RING_BUFFER_CAP + 5):
            self._run()
            self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), RING_BUFFER_CAP)

    def test_log_entry_has_upgrade_risk_label(self):
        self._run()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertIn("upgrade_risk_label", data[0])

    def test_log_entry_has_governance_score(self):
        self._run()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertIn("governance_decentralization_score", data[0])

    def test_custom_ring_cap(self):
        small = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(
            data_dir=self.tmp_dir, ring_cap=3
        )
        for _ in range(5):
            small.analyze(
                is_upgradeable=False, has_timelock=False, timelock_hours=0,
                multisig_required=False, multisig_signers=0, multisig_threshold=0,
                audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
                protocol_name="X",
            )
            small.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 3)

    def test_log_is_valid_json(self):
        self._run()
        self.analyzer.save()
        content = (self.tmp_dir / LOG_FILENAME).read_text()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)


# ===========================================================================
# 7. I/O helpers — _load_json_list and _atomic_write
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_load_nonexistent_returns_empty(self):
        self.assertEqual(_load_json_list(self.tmp_dir / "nope.json"), [])

    def test_load_valid_list(self):
        p = self.tmp_dir / "data.json"
        p.write_text(json.dumps([{"a": 1}]))
        self.assertEqual(_load_json_list(p), [{"a": 1}])

    def test_load_dict_returns_empty(self):
        p = self.tmp_dir / "dict.json"
        p.write_text(json.dumps({"key": "val"}))
        self.assertEqual(_load_json_list(p), [])

    def test_load_malformed_returns_empty(self):
        p = self.tmp_dir / "bad.json"
        p.write_text("{not: valid}")
        self.assertEqual(_load_json_list(p), [])

    def test_atomic_write_creates_file(self):
        p = self.tmp_dir / "out.json"
        _atomic_write(p, [{"x": 1}])
        self.assertTrue(p.exists())

    def test_atomic_write_correct_content(self):
        p = self.tmp_dir / "out.json"
        data = [{"protocol": "Aave", "score": 42}]
        _atomic_write(p, data)
        self.assertEqual(json.loads(p.read_text()), data)

    def test_atomic_write_no_tmp_leftover(self):
        p = self.tmp_dir / "out.json"
        _atomic_write(p, [])
        self.assertEqual(list(self.tmp_dir.glob("*.tmp")), [])

    def test_atomic_write_creates_parent_dirs(self):
        nested = self.tmp_dir / "a" / "b" / "out.json"
        _atomic_write(nested, [1, 2])
        self.assertTrue(nested.exists())


# ===========================================================================
# 8. Ring-buffer behaviour
# ===========================================================================

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_ring_buffer_cap_constant(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_below_cap_all_kept(self):
        analyzer = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(data_dir=self.tmp_dir)
        for i in range(30):
            analyzer.analyze(
                is_upgradeable=False, has_timelock=False, timelock_hours=0,
                multisig_required=False, multisig_signers=0, multisig_threshold=0,
                audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
                protocol_name=f"P{i}",
            )
            analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), 30)

    def test_ring_retains_most_recent(self):
        cap = 5
        analyzer = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(
            data_dir=self.tmp_dir, ring_cap=cap
        )
        for i in range(cap + 3):
            analyzer.analyze(
                is_upgradeable=False, has_timelock=False, timelock_hours=0,
                multisig_required=False, multisig_signers=0, multisig_threshold=0,
                audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
                protocol_name=f"P{i}",
            )
            analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), cap)
        self.assertEqual(data[-1]["protocol_name"], f"P{cap + 2}")

    def test_ring_overflow_exact(self):
        cap = 7
        analyzer = ProtocolDeFiSmartContractUpgradeRiskAnalyzer(
            data_dir=self.tmp_dir, ring_cap=cap
        )
        for _ in range(cap + 1):
            analyzer.analyze(
                is_upgradeable=False, has_timelock=False, timelock_hours=0,
                multisig_required=False, multisig_signers=0, multisig_threshold=0,
                audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
                protocol_name="X",
            )
            analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), cap)


# ===========================================================================
# 9. Constants and module metadata
# ===========================================================================

class TestConstantsAndMetadata(unittest.TestCase):

    def test_log_filename(self):
        self.assertEqual(LOG_FILENAME, "smart_contract_upgrade_risk_log.json")

    def test_ring_buffer_cap(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_schema_version_int(self):
        self.assertIsInstance(SCHEMA_VERSION, int)
        self.assertGreaterEqual(SCHEMA_VERSION, 1)

    def test_source_name(self):
        self.assertEqual(SOURCE_NAME, "protocol_defi_smart_contract_upgrade_risk_analyzer")

    def test_mp_tag(self):
        self.assertEqual(MP_TAG, "MP-1093")

    def test_timelock_strong_h(self):
        self.assertEqual(TIMELOCK_STRONG_H, 72)

    def test_timelock_adequate_h(self):
        self.assertEqual(TIMELOCK_ADEQUATE_H, 24)

    def test_gov_multisig_max(self):
        self.assertEqual(GOV_MULTISIG_MAX, 40)

    def test_gov_timelock_max(self):
        self.assertEqual(GOV_TIMELOCK_MAX, 30)

    def test_gov_audit_max(self):
        self.assertEqual(GOV_AUDIT_MAX, 25)

    def test_multisig_ratio_min(self):
        self.assertAlmostEqual(MULTISIG_RATIO_MIN, 0.5, places=8)


# ===========================================================================
# 10. Edge cases and real-world scenarios
# ===========================================================================

class TestEdgeCasesAndRealWorld(unittest.TestCase):

    def test_aave_v3_well_governed(self):
        r = analyze(
            is_upgradeable=True, has_timelock=True, timelock_hours=168,
            multisig_required=True, multisig_signers=6, multisig_threshold=4,
            audit_count=4, days_since_last_upgrade=300, upgrade_history_count=3,
            protocol_name="Aave V3",
        )
        self.assertEqual(r["upgrade_risk_label"], "WELL_GOVERNED")
        self.assertLess(r["upgrade_risk_score"], 50)

    def test_rugpull_risk_critical(self):
        r = analyze(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=5, upgrade_history_count=1,
            protocol_name="SuspiciousDeFi",
        )
        self.assertEqual(r["upgrade_risk_label"], "CRITICAL_UPGRADE_RISK")
        self.assertEqual(r["upgrade_risk_score"], 100)

    def test_uniswap_v3_immutable(self):
        r = analyze(
            is_upgradeable=False, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=5, days_since_last_upgrade=0, upgrade_history_count=0,
            protocol_name="Uniswap V3",
        )
        self.assertEqual(r["upgrade_risk_label"], "IMMUTABLE_SAFE")
        self.assertEqual(r["upgrade_risk_score"], 0)
        self.assertEqual(r["governance_decentralization_score"], 100)

    def test_compound_v3_moderate(self):
        r = analyze(
            is_upgradeable=True, has_timelock=True, timelock_hours=48,
            multisig_required=True, multisig_signers=5, multisig_threshold=3,
            audit_count=1, days_since_last_upgrade=90, upgrade_history_count=2,
            protocol_name="Compound V3",
        )
        self.assertEqual(r["upgrade_risk_label"], "MODERATE_RISK")

    def test_output_all_numeric_types(self):
        r = analyze(
            is_upgradeable=True, has_timelock=True, timelock_hours=72,
            multisig_required=True, multisig_signers=5, multisig_threshold=3,
            audit_count=2, days_since_last_upgrade=0, upgrade_history_count=0,
            protocol_name="Proto",
        )
        self.assertIsInstance(r["governance_decentralization_score"], int)
        self.assertIsInstance(r["upgrade_risk_score"], int)
        self.assertIsInstance(r["timelock_adequacy"], str)
        self.assertIsInstance(r["upgrade_risk_label"], str)

    def test_high_risk_label_with_small_timelock(self):
        r = analyze(
            is_upgradeable=True, has_timelock=True, timelock_hours=6,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
            protocol_name="HighRisk",
        )
        self.assertEqual(r["upgrade_risk_label"], "HIGH_RISK")

    def test_gov_score_reflects_good_multisig(self):
        """Good multisig should give higher gov score than no multisig."""
        s_no_ms = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        s_with_ms = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=5, multisig_threshold=3,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertGreater(s_with_ms, s_no_ms)

    def test_risk_score_inversely_related_to_gov_score_upgradeable(self):
        """For upgradeable protocols, better governance => lower risk."""
        r_poor = analyze(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
            protocol_name="Poor",
        )
        r_good = analyze(
            is_upgradeable=True, has_timelock=True, timelock_hours=168,
            multisig_required=True, multisig_signers=6, multisig_threshold=4,
            audit_count=4, days_since_last_upgrade=200, upgrade_history_count=2,
            protocol_name="Good",
        )
        self.assertGreater(r_poor["upgrade_risk_score"], r_good["upgrade_risk_score"])
        self.assertLess(r_poor["governance_decentralization_score"],
                        r_good["governance_decentralization_score"])

    def test_multisig_threshold_equal_to_signers(self):
        """M == N means all signers required (very conservative, ratio >= 0.5)."""
        s = governance_decentralization_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=True, multisig_signers=3, multisig_threshold=3,
            audit_count=0, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        # ratio = 3/3 = 1.0 >= 0.5 → all three multisig components = 40
        self.assertEqual(s, GOV_MULTISIG_MAX)

    def test_audit_count_3_gives_correct_reduction(self):
        """3 audits → min(3*8, 20) = 20 risk reduction."""
        s = upgrade_risk_score(
            is_upgradeable=True, has_timelock=False, timelock_hours=0,
            multisig_required=False, multisig_signers=0, multisig_threshold=0,
            audit_count=3, days_since_last_upgrade=0, upgrade_history_count=0,
        )
        self.assertEqual(s, 100 - 20)  # capped at 20


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
