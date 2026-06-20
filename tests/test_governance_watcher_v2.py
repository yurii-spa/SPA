"""
Tests for spa_core/alerts/governance_watcher_v2.py — Yield Parameter Tracker
(Sprint v12.59).

Run:
    python -m pytest tests/test_governance_watcher_v2.py -v
    python -m unittest tests.test_governance_watcher_v2 -v

Target: 25 tests, all PASS.  No network — proposals are injected or offline.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Path bootstrap
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.alerts.governance_watcher import GovernanceProposal
from spa_core.alerts import governance_watcher_v2 as v2
from spa_core.alerts.governance_watcher_v2 import (
    YieldParameterTracker,
    YieldParameterAlert,
    normalize_protocol_family,
    detect_yield_keywords,
    estimate_apy_impact,
    proposal_to_alert,
    detect_yield_proposals,
    build_telegram_message,
    get_tracker,
    YIELD_PARAM_KEYWORDS,
)


def _prop(
    pid="p-1",
    protocol="aave-v3",
    title="Test proposal",
    category="parameter_change",
    severity="MEDIUM",
    state="active",
    source="bootstrap",
    end_at="2026-07-01T00:00:00Z",
    url="https://snapshot.org/x",
) -> GovernanceProposal:
    return GovernanceProposal(
        id=pid, protocol=protocol, title=title, category=category,
        severity=severity, state=state, source=source,
        start_at="2026-06-20T00:00:00Z", end_at=end_at, url=url,
    )


class TestProtocolFamily(unittest.TestCase):
    def test_aave_variants(self):
        self.assertEqual(normalize_protocol_family("aave-v3"), "aave")
        self.assertEqual(normalize_protocol_family("aave-v3-arbitrum"), "aave")

    def test_compound_morpho_sky(self):
        self.assertEqual(normalize_protocol_family("compound-v3"), "compound")
        self.assertEqual(normalize_protocol_family("morpho-blue"), "morpho")
        self.assertEqual(normalize_protocol_family("maker"), "sky")
        self.assertEqual(normalize_protocol_family("susds"), "sky")

    def test_case_insensitive_and_whitespace(self):
        self.assertEqual(normalize_protocol_family("  AAVE-V3 "), "aave")

    def test_untracked_returns_none(self):
        self.assertIsNone(normalize_protocol_family("uniswap-v3"))
        self.assertIsNone(normalize_protocol_family(""))


class TestKeywordDetection(unittest.TestCase):
    def test_aave_keywords(self):
        self.assertIn("reserve factor",
                      detect_yield_keywords("aave", "Update reserve factor for USDC"))
        self.assertIn("slope", detect_yield_keywords("aave", "Adjust slope2 of the IRM"))

    def test_compound_keywords(self):
        self.assertIn("supply cap",
                      detect_yield_keywords("compound", "Raise supply cap on cUSDCv3"))
        self.assertIn("interest rate model",
                      detect_yield_keywords("compound", "New interest rate model"))

    def test_morpho_keywords(self):
        self.assertIn("curve", detect_yield_keywords("morpho", "Adjust IRM curve params"))
        self.assertIn("apr", detect_yield_keywords("morpho", "Boost APR on vault"))

    def test_sky_keywords(self):
        self.assertIn("dsr", detect_yield_keywords("sky", "Increase the DSR to 8%"))
        self.assertIn("savings rate",
                      detect_yield_keywords("sky", "Change Dai savings rate"))

    def test_case_insensitive(self):
        self.assertIn("reserve factor",
                      detect_yield_keywords("aave", "RESERVE FACTOR bump"))

    def test_no_match_returns_empty(self):
        self.assertEqual(detect_yield_keywords("aave", "Treasury grant for marketing"), [])

    def test_unknown_family_empty(self):
        self.assertEqual(detect_yield_keywords("nope", "reserve factor"), [])


class TestApyImpact(unittest.TestCase):
    def test_increase_reserve_factor_down(self):
        self.assertEqual(estimate_apy_impact("Increase reserve factor to 20%"), "down")

    def test_decrease_reserve_factor_up(self):
        self.assertEqual(estimate_apy_impact("Decrease reserve factor to 5%"), "up")

    def test_increase_supply_cap_down(self):
        self.assertEqual(estimate_apy_impact("Increase supply cap for USDC"), "down")

    def test_decrease_supply_cap_up(self):
        self.assertEqual(estimate_apy_impact("Reduce supply cap on cUSDCv3"), "up")

    def test_increase_dsr_up(self):
        self.assertEqual(estimate_apy_impact("Increase the DSR to 9%"), "up")

    def test_decrease_savings_rate_down(self):
        self.assertEqual(estimate_apy_impact("Lower the Dai savings rate"), "down")

    def test_default_unknown(self):
        self.assertEqual(estimate_apy_impact("Add LINK as collateral"), "unknown")

    def test_ambiguous_direction_unknown(self):
        # both increase + decrease words present → ambiguous → unknown
        self.assertEqual(
            estimate_apy_impact("Increase supply cap then decrease reserve factor"),
            "unknown",
        )

    def test_param_without_direction_unknown(self):
        self.assertEqual(estimate_apy_impact("Discussion: reserve factor review"), "unknown")


class TestProposalToAlert(unittest.TestCase):
    def test_builds_alert_fields(self):
        p = _prop(title="Increase reserve factor on USDC", protocol="aave-v3")
        alert = proposal_to_alert(p)
        self.assertIsInstance(alert, YieldParameterAlert)
        self.assertEqual(alert.family, "aave")
        self.assertEqual(alert.protocol_label, "Aave")
        self.assertEqual(alert.apy_impact, "down")
        self.assertIn("reserve factor", alert.matched_keywords)
        self.assertEqual(alert.vote_deadline, "2026-07-01T00:00:00Z")

    def test_non_tracked_protocol_none(self):
        self.assertIsNone(proposal_to_alert(_prop(protocol="uniswap-v3")))

    def test_tracked_protocol_no_keyword_none(self):
        self.assertIsNone(proposal_to_alert(_prop(protocol="aave-v3", title="Marketing grant")))

    def test_to_dict_serializable(self):
        alert = proposal_to_alert(_prop(title="Increase supply cap", protocol="compound-v3"))
        d = alert.to_dict()
        json.dumps(d)  # must not raise
        self.assertEqual(d["apy_impact"], "down")
        self.assertEqual(d["family"], "compound")


class TestDetectYieldProposals(unittest.TestCase):
    def test_filters_mixed_list(self):
        props = [
            _prop(pid="a", protocol="aave-v3", title="Increase reserve factor"),
            _prop(pid="b", protocol="uniswap-v3", title="Increase reserve factor"),
            _prop(pid="c", protocol="compound-v3", title="Add LINK collateral"),
            _prop(pid="d", protocol="maker", title="Increase the DSR"),
        ]
        alerts = detect_yield_proposals(props)
        ids = {a.id for a in alerts}
        self.assertEqual(ids, {"a", "d"})

    def test_empty_list(self):
        self.assertEqual(detect_yield_proposals([]), [])

    def test_none_safe(self):
        self.assertEqual(detect_yield_proposals(None), [])


class TestTelegramMessage(unittest.TestCase):
    def test_message_contains_header_and_impact(self):
        alert = proposal_to_alert(_prop(title="Increase reserve factor", protocol="aave-v3"))
        msg = build_telegram_message(alert)
        self.assertIn("⚠️ GOVERNANCE: Aave proposal may affect yield parameters", msg)
        self.assertIn("DOWN", msg)
        self.assertIn("2026-07-01T00:00:00Z", msg)


class TestTracker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.alerts_file = Path(self._tmp.name) / "governance_alerts.json"
        self.sent = []
        self.tracker = YieldParameterTracker(
            alerts_file=self.alerts_file,
            notifier=lambda text: (self.sent.append(text) or True),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_with_injected_proposals(self):
        props = [
            _prop(pid="x", protocol="aave-v3", title="Increase reserve factor"),
            _prop(pid="y", protocol="curve", title="fee switch"),
        ]
        alerts = self.tracker.scan(proposals=props)
        self.assertEqual([a.id for a in alerts], ["x"])

    def test_scan_dedup_by_id(self):
        props = [
            _prop(pid="dup", protocol="aave-v3", title="Increase reserve factor"),
            _prop(pid="dup", protocol="aave-v3", title="Increase reserve factor"),
        ]
        self.assertEqual(len(self.tracker.scan(proposals=props)), 1)

    def test_export_writes_file(self):
        props = [_prop(pid="w1", protocol="aave-v3", title="Increase reserve factor")]
        result = self.tracker.export(dry_run=False, proposals=props)
        self.assertTrue(self.alerts_file.exists())
        on_disk = json.loads(self.alerts_file.read_text())
        self.assertEqual(on_disk["tracker_version"], "2.0")
        self.assertEqual(len(on_disk["alerts"]), 1)
        self.assertEqual(result["summary"]["new_alerts"], 1)

    def test_export_notify_sends_telegram(self):
        props = [_prop(pid="n1", protocol="compound-v3", title="Increase supply cap")]
        self.tracker.export(dry_run=True, notify=True, proposals=props)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Compound", self.sent[0])

    def test_dedup_no_duplicate_notifications(self):
        props = [_prop(pid="once", protocol="aave-v3", title="Increase reserve factor")]
        # First run: writes + notifies
        self.tracker.export(dry_run=False, notify=True, proposals=props)
        # Second run: same proposal already logged → no new notification
        self.tracker.export(dry_run=False, notify=True, proposals=props)
        self.assertEqual(len(self.sent), 1)
        on_disk = json.loads(self.alerts_file.read_text())
        self.assertEqual(len(on_disk["alerts"]), 1)

    def test_ring_buffer_cap(self):
        v2._ALERTS_RING_CAP = 5
        try:
            for i in range(8):
                p = _prop(pid=f"r{i}", protocol="aave-v3", title="Increase reserve factor")
                self.tracker.export(dry_run=False, proposals=[p])
            on_disk = json.loads(self.alerts_file.read_text())
            self.assertEqual(len(on_disk["alerts"]), 5)
            # newest kept
            self.assertEqual(on_disk["alerts"][-1]["id"], "r7")
        finally:
            v2._ALERTS_RING_CAP = 200

    def test_notifier_failure_does_not_raise(self):
        boom = YieldParameterTracker(
            alerts_file=self.alerts_file,
            notifier=lambda text: (_ for _ in ()).throw(RuntimeError("network down")),
        )
        props = [_prop(pid="boom", protocol="aave-v3", title="Increase reserve factor")]
        # must not raise
        result = boom.export(dry_run=True, notify=True, proposals=props)
        self.assertEqual(result["summary"]["new_alerts"], 1)

    def test_offline_scan_never_raises(self):
        # offline uses bootstrap proposals; just assert it returns a list
        alerts = self.tracker.scan(offline=True)
        self.assertIsInstance(alerts, list)

    def test_summary_by_impact_and_protocol(self):
        props = [
            _prop(pid="s1", protocol="aave-v3", title="Increase reserve factor"),     # down
            _prop(pid="s2", protocol="compound-v3", title="Decrease supply cap"),     # up
            _prop(pid="s3", protocol="maker", title="DSR review"),                     # unknown
        ]
        result = self.tracker.export(dry_run=True, proposals=props)
        self.assertEqual(result["summary"]["by_impact"].get("down"), 1)
        self.assertEqual(result["summary"]["by_impact"].get("up"), 1)
        self.assertEqual(result["summary"]["by_impact"].get("unknown"), 1)
        self.assertEqual(result["summary"]["by_protocol"].get("aave"), 1)


class TestSingletonAndConfig(unittest.TestCase):
    def test_get_tracker_singleton(self):
        self.assertIs(get_tracker(), get_tracker())

    def test_all_families_have_keywords(self):
        for fam in ("aave", "compound", "morpho", "sky"):
            self.assertTrue(YIELD_PARAM_KEYWORDS.get(fam))


if __name__ == "__main__":
    unittest.main(verbosity=2)
