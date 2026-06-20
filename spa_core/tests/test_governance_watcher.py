"""
Tests for spa_core/alerts/governance_watcher.py — FEAT-MON-002 (v3.18).

Run:
    python -m unittest spa_core/tests/test_governance_watcher.py -v

Expected: ≥ 60 tests, all PASS.
"""

from __future__ import annotations

import json
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Path bootstrap
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.alerts import governance_watcher as _gw
from spa_core.alerts.governance_watcher import (
    GovernanceProposal,
    GovernanceWatcher,
    classify_category,
    classify_severity,
    get_watcher,
    BOOTSTRAP_PROPOSALS,
    SNAPSHOT_SPACES,
    TALLY_GOVERNORS,
    RISK_TRIGGER_CATEGORIES,
    _ts,
    _ts_str,
    _http_post_retry,
)


# Patch out backoff sleeps for the whole module so retry-path tests run fast.
_gw._sleep = lambda *_a, **_k: None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proposal(
    pid="test-001",
    protocol="aave-v3",
    title="Test proposal",
    category="general",
    severity="LOW",
    state="active",
    source="bootstrap",
) -> GovernanceProposal:
    return GovernanceProposal(
        id=pid,
        protocol=protocol,
        title=title,
        category=category,
        severity=severity,
        state=state,
        source=source,
        start_at="2026-05-01T00:00:00Z",
        end_at="2026-05-07T00:00:00Z",
        url="https://example.com",
    )


# ---------------------------------------------------------------------------
# 1. classify_category
# ---------------------------------------------------------------------------

class TestClassifyCategory(unittest.TestCase):

    def test_emergency_keyword(self):
        self.assertEqual(classify_category("Emergency: Pause all borrowing"), "emergency")

    def test_upgrade_keyword(self):
        self.assertEqual(classify_category("V3 Migration: Upgrade proxy implementation"), "upgrade")

    def test_risk_param_ltv(self):
        self.assertEqual(classify_category("ARFC: Update USDC LTV to 88%"), "risk_param")

    def test_risk_param_liquidation_threshold(self):
        self.assertEqual(
            classify_category("Adjust liquidation threshold for WETH"), "risk_param"
        )

    def test_risk_param_borrow_cap(self):
        self.assertEqual(classify_category("Increase borrow cap for USDC"), "risk_param")

    def test_parameter_change_interest_rate(self):
        self.assertEqual(classify_category("Update interest rate model for stables"), "parameter_change")

    def test_parameter_change_fee(self):
        self.assertEqual(classify_category("Adjust protocol fee to 5bps"), "parameter_change")

    def test_treasury_grant(self):
        self.assertEqual(classify_category("Grant funding to Aave Grants DAO"), "treasury")

    def test_treasury_fund(self):
        self.assertEqual(classify_category("Treasury allocation for Q3 2026"), "treasury")

    def test_general_fallback(self):
        self.assertEqual(classify_category("Add support for new chain"), "general")

    def test_body_used_for_classification(self):
        # Title alone is generic, body has the keyword
        result = classify_category("Proposal 42", "This proposal updates the LTV ratio")
        self.assertEqual(result, "risk_param")

    def test_emergency_takes_priority_over_upgrade(self):
        # "emergency upgrade" — emergency wins
        result = classify_category("Emergency upgrade to fix exploit")
        self.assertEqual(result, "emergency")

    def test_case_insensitive(self):
        self.assertEqual(classify_category("EMERGENCY PAUSE"), "emergency")

    def test_empty_string_returns_general(self):
        self.assertEqual(classify_category(""), "general")

    def test_freeze_is_emergency(self):
        self.assertEqual(classify_category("Freeze WBTC collateral due to oracle issue"), "emergency")


# ---------------------------------------------------------------------------
# 2. classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity(unittest.TestCase):

    def test_emergency_is_high(self):
        self.assertEqual(classify_severity("emergency", "active"), "HIGH")

    def test_upgrade_is_high(self):
        self.assertEqual(classify_severity("upgrade", "active"), "HIGH")

    def test_risk_param_active_is_high(self):
        self.assertEqual(classify_severity("risk_param", "active"), "HIGH")

    def test_risk_param_closed_is_medium(self):
        self.assertEqual(classify_severity("risk_param", "closed"), "MEDIUM")

    def test_parameter_change_is_medium(self):
        self.assertEqual(classify_severity("parameter_change", "active"), "MEDIUM")

    def test_treasury_is_medium(self):
        self.assertEqual(classify_severity("treasury", "active"), "MEDIUM")

    def test_general_is_low(self):
        self.assertEqual(classify_severity("general", "active"), "LOW")

    def test_unknown_is_low(self):
        self.assertEqual(classify_severity("unknown", "active"), "LOW")


# ---------------------------------------------------------------------------
# 3. GovernanceProposal dataclass
# ---------------------------------------------------------------------------

class TestGovernanceProposal(unittest.TestCase):

    def test_to_dict_has_all_keys(self):
        p = _make_proposal()
        d = p.to_dict()
        for key in ["id", "protocol", "title", "category", "severity", "state",
                    "source", "start_at", "end_at", "url", "votes_for",
                    "votes_against", "quorum_met", "detected_at"]:
            self.assertIn(key, d)

    def test_detected_at_auto_populated(self):
        p = _make_proposal()
        self.assertIn("T", p.detected_at)  # ISO-8601

    def test_votes_default_zero(self):
        p = _make_proposal()
        self.assertEqual(p.votes_for, 0.0)
        self.assertEqual(p.votes_against, 0.0)


# ---------------------------------------------------------------------------
# 4. Bootstrap proposals
# ---------------------------------------------------------------------------

class TestBootstrapProposals(unittest.TestCase):

    def test_has_proposals(self):
        self.assertGreater(len(BOOTSTRAP_PROPOSALS), 0)

    def test_all_have_required_fields(self):
        for p in BOOTSTRAP_PROPOSALS:
            self.assertIsInstance(p.id, str)
            self.assertIsInstance(p.protocol, str)
            self.assertIsInstance(p.title, str)
            self.assertIn(p.category, [
                "emergency", "upgrade", "risk_param",
                "parameter_change", "treasury", "general", "unknown"
            ])
            self.assertIn(p.severity, ["HIGH", "MEDIUM", "LOW"])
            self.assertIn(p.state, ["active", "closed", "pending", "queued"])

    def test_has_high_severity(self):
        high = [p for p in BOOTSTRAP_PROPOSALS if p.severity == "HIGH"]
        self.assertGreater(len(high), 0)

    def test_protocols_are_whitelisted(self):
        all_known = set(SNAPSHOT_SPACES.keys()) | set(TALLY_GOVERNORS.keys())
        for p in BOOTSTRAP_PROPOSALS:
            self.assertIn(p.protocol, all_known, f"{p.protocol} not in whitelist")


# ---------------------------------------------------------------------------
# 5. GovernanceWatcher — offline mode
# ---------------------------------------------------------------------------

class TestGovernanceWatcherOffline(unittest.TestCase):

    def setUp(self):
        self.watcher = GovernanceWatcher()

    def test_scan_all_offline_returns_bootstrap(self):
        proposals = self.watcher.scan_all(offline=True)
        self.assertEqual(len(proposals), len(BOOTSTRAP_PROPOSALS))

    def test_scan_all_offline_never_raises(self):
        try:
            self.watcher.scan_all(offline=True)
        except Exception:
            self.fail("scan_all raised an exception")

    def test_export_offline_returns_dict(self):
        result = self.watcher.export(dry_run=True, offline=True)
        self.assertIsInstance(result, dict)
        self.assertIn("proposals", result)

    def test_export_offline_summary_populated(self):
        result = self.watcher.export(dry_run=True, offline=True)
        summary = result.get("summary", {})
        self.assertIn("total_proposals", summary)
        self.assertGreater(summary["total_proposals"], 0)

    def test_export_offline_by_severity_present(self):
        result = self.watcher.export(dry_run=True, offline=True)
        by_sev = result["summary"]["by_severity"]
        self.assertIn("HIGH", by_sev)

    def test_get_risk_triggers_offline(self):
        triggers = self.watcher.get_risk_triggers(offline=True)
        self.assertIsInstance(triggers, list)
        for t in triggers:
            self.assertIn(t.category, RISK_TRIGGER_CATEGORIES)
            self.assertEqual(t.state, "active")

    def test_has_active_risk_proposals_aave(self):
        # Bootstrap has an active aave-v3 upgrade → True
        result = self.watcher.has_active_risk_proposals("aave-v3", offline=True)
        self.assertTrue(result)

    def test_has_active_risk_proposals_unknown(self):
        result = self.watcher.has_active_risk_proposals("nonexistent-protocol-xyz", offline=True)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 6. GovernanceWatcher — export to file
# ---------------------------------------------------------------------------

class TestGovernanceWatcherExportFile(unittest.TestCase):

    def setUp(self):
        self.watcher = GovernanceWatcher()

    def test_export_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "gov.json"
            watcher = GovernanceWatcher(output_file=str(out))
            watcher.export(dry_run=False, offline=True)
            self.assertTrue(out.exists())

    def test_exported_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "gov.json"
            watcher = GovernanceWatcher(output_file=str(out))
            watcher.export(dry_run=False, offline=True)
            with out.open() as fh:
                data = json.load(fh)
            self.assertIn("proposals", data)

    def test_dry_run_does_not_write_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "gov.json"
            watcher = GovernanceWatcher(output_file=str(out))
            watcher.export(dry_run=True, offline=True)
            self.assertFalse(out.exists())


# ---------------------------------------------------------------------------
# 7. scan_all with mocked live network (Snapshot success)
# ---------------------------------------------------------------------------

class TestGovernanceWatcherLiveMocked(unittest.TestCase):

    def _snapshot_response(self, protocol: str) -> dict:
        """Build a fake Snapshot GraphQL response."""
        return {
            "data": {
                "proposals": [
                    {
                        "id": f"0xfake{protocol}",
                        "title": f"Risk Parameter Update for {protocol}",
                        "body": "Proposal to update LTV to 85%",
                        "state": "active",
                        "start": 1_716_000_000,
                        "end":   1_716_600_000,
                        "scores": [1_000_000, 50_000],
                        "scores_total": 1_050_000,
                        "quorum": 500_000,
                        "link": f"https://snapshot.org/#/example/proposal/0xfake{protocol}",
                    }
                ]
            }
        }

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_live_scan_uses_snapshot_data(self, mock_post):
        # Return success for Snapshot, raise for Tally (acceptable)
        def side_effect(url, payload, **kwargs):
            if "snapshot" in url:
                space = payload.get("variables", {}).get("space", "aave.eth")
                protocol = next(
                    (k for k, v in SNAPSHOT_SPACES.items() if v == space), "unknown"
                )
                return self._snapshot_response(protocol)
            raise Exception("Tally not mocked")

        mock_post.side_effect = side_effect
        watcher = GovernanceWatcher()
        proposals = watcher.scan_all(offline=False)
        self.assertGreater(len(proposals), 0)
        # Should have at least one risk_param proposal
        categories = {p.category for p in proposals}
        self.assertIn("risk_param", categories)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_network_failure_falls_back_to_bootstrap(self, mock_post):
        mock_post.side_effect = Exception("Network unreachable")
        watcher = GovernanceWatcher()
        proposals = watcher.scan_all(offline=False)
        self.assertGreater(len(proposals), 0)
        # Should contain bootstrap proposals
        bootstrap_ids = {p.id for p in BOOTSTRAP_PROPOSALS}
        result_ids = {p.id for p in proposals}
        self.assertTrue(result_ids & bootstrap_ids)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_partial_failure_uses_available_data(self, mock_post):
        """Only some spaces fail — should still return proposals from successful ones."""
        call_count = [0]
        def side_effect(url, payload, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return self._snapshot_response("aave-v3")
            raise Exception("Simulated failure")
        mock_post.side_effect = side_effect
        watcher = GovernanceWatcher()
        proposals = watcher.scan_all(offline=False)
        self.assertGreater(len(proposals), 0)


# ---------------------------------------------------------------------------
# 8. Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication(unittest.TestCase):

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_duplicate_ids_removed(self, mock_post):
        """Same proposal ID returned from multiple spaces — deduplicated."""
        duplicate_id = "0xdup"
        def side_effect(url, payload, **kwargs):
            return {
                "data": {
                    "proposals": [{
                        "id": duplicate_id,
                        "title": "Duplicate proposal",
                        "body": "",
                        "state": "active",
                        "start": 1_716_000_000,
                        "end":   1_716_600_000,
                        "scores": [100, 0],
                        "scores_total": 100,
                        "quorum": 0,
                        "link": "https://example.com",
                    }]
                }
            }
        mock_post.side_effect = side_effect
        watcher = GovernanceWatcher()
        proposals = watcher.scan_all(offline=False)
        ids = [p.id for p in proposals]
        # snapshot: prefix is added
        prefixed = f"snapshot:{duplicate_id}"
        count = ids.count(prefixed)
        self.assertEqual(count, 1)


# ---------------------------------------------------------------------------
# 9. Sort order
# ---------------------------------------------------------------------------

class TestSortOrder(unittest.TestCase):

    def test_active_proposals_before_closed(self):
        watcher = GovernanceWatcher()
        proposals = watcher.scan_all(offline=True)
        states = [p.state for p in proposals]
        if "active" in states and "closed" in states:
            first_active = states.index("active") if "active" in states else len(states)
            first_closed = states.index("closed") if "closed" in states else len(states)
            self.assertLessEqual(first_active, first_closed)

    def test_high_before_low_within_active(self):
        watcher = GovernanceWatcher()
        proposals = watcher.scan_all(offline=True)
        active = [p for p in proposals if p.state == "active"]
        if len(active) >= 2:
            sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            sevs = [sev_order.get(p.severity, 9) for p in active]
            self.assertEqual(sevs, sorted(sevs))


# ---------------------------------------------------------------------------
# 10. RISK_TRIGGER_CATEGORIES
# ---------------------------------------------------------------------------

class TestRiskTriggerCategories(unittest.TestCase):

    def test_contains_expected_categories(self):
        self.assertIn("risk_param", RISK_TRIGGER_CATEGORIES)
        self.assertIn("upgrade", RISK_TRIGGER_CATEGORIES)
        self.assertIn("emergency", RISK_TRIGGER_CATEGORIES)

    def test_general_not_in_triggers(self):
        self.assertNotIn("general", RISK_TRIGGER_CATEGORIES)

    def test_treasury_not_in_triggers(self):
        self.assertNotIn("treasury", RISK_TRIGGER_CATEGORIES)


# ---------------------------------------------------------------------------
# 11. Time helpers
# ---------------------------------------------------------------------------

class TestTimeHelpers(unittest.TestCase):

    def test_ts_from_valid_unix(self):
        result = _ts(1_716_000_000)
        self.assertIn("T", result)
        self.assertTrue(result.endswith("Z"))

    def test_ts_none_returns_epoch(self):
        result = _ts(None)
        self.assertEqual(result, "1970-01-01T00:00:00Z")

    def test_ts_str_iso_passthrough(self):
        result = _ts_str("2026-05-28T12:00:00Z")
        self.assertIn("2026-05-28", result)

    def test_ts_str_empty_returns_epoch(self):
        result = _ts_str("")
        self.assertEqual(result, "1970-01-01T00:00:00Z")

    def test_ts_str_unix_numeric(self):
        result = _ts_str("1716000000")
        self.assertIn("T", result)


# ---------------------------------------------------------------------------
# 12. get_watcher singleton
# ---------------------------------------------------------------------------

class TestGetWatcherSingleton(unittest.TestCase):

    def test_returns_same_instance(self):
        w1 = get_watcher()
        w2 = get_watcher()
        self.assertIs(w1, w2)

    def test_returns_governance_watcher(self):
        self.assertIsInstance(get_watcher(), GovernanceWatcher)


# ---------------------------------------------------------------------------
# 13. Never-raises robustness
# ---------------------------------------------------------------------------

class TestNeverRaises(unittest.TestCase):

    def test_scan_all_offline_never_raises(self):
        watcher = GovernanceWatcher()
        for _ in range(3):
            try:
                watcher.scan_all(offline=True)
            except Exception as e:
                self.fail(f"scan_all raised: {e}")

    def test_export_never_raises(self):
        watcher = GovernanceWatcher()
        try:
            watcher.export(dry_run=True, offline=True)
        except Exception as e:
            self.fail(f"export raised: {e}")

    def test_get_risk_triggers_never_raises(self):
        watcher = GovernanceWatcher()
        try:
            watcher.get_risk_triggers(offline=True)
        except Exception as e:
            self.fail(f"get_risk_triggers raised: {e}")

    def test_has_active_risk_proposals_never_raises(self):
        watcher = GovernanceWatcher()
        try:
            watcher.has_active_risk_proposals("any-protocol", offline=True)
        except Exception as e:
            self.fail(f"has_active_risk_proposals raised: {e}")


# ---------------------------------------------------------------------------
# 14. Fallback / health-check behaviour (fix verification)
# ---------------------------------------------------------------------------

def _snapshot_ok_response(active=True):
    """A successful Snapshot GraphQL response with one active proposal."""
    return {
        "data": {
            "proposals": [{
                "id": "0xlive",
                "title": "Risk Parameter Update: USDC LTV to 88%",
                "body": "Update LTV",
                "state": "active" if active else "closed",
                "start": 1_716_000_000,
                "end":   1_716_600_000,
                "scores": [1_000_000, 50_000],
                "scores_total": 1_050_000,
                "quorum": 500_000,
                "link": "https://snapshot.org/#/example/proposal/0xlive",
            }]
        }
    }


def _snapshot_empty_response():
    """A successful Snapshot call that simply has NO active proposals."""
    return {"data": {"proposals": []}}


class TestFallbackUsedWhenApiUnavailable(unittest.TestCase):
    """fallback_used must be True ONLY when no live source responds."""

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_fallback_used_when_api_unavailable(self, mock_post):
        # Every HTTP call fails → genuine network outage → fallback
        mock_post.side_effect = Exception("Network unreachable")
        watcher = GovernanceWatcher()
        result = watcher.export(dry_run=True, offline=False)
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fetch_method"], "fallback")
        self.assertFalse(result["snapshot_ok"])
        self.assertFalse(result["tally_ok"])
        self.assertIn("bootstrap", result["sources"])

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_no_fallback_when_snapshot_ok_but_empty(self, mock_post):
        # Snapshot responds successfully for every space but with ZERO active
        # proposals. This must NOT be treated as a fallback condition (the bug).
        mock_post.return_value = _snapshot_empty_response()
        watcher = GovernanceWatcher()
        result = watcher.export(dry_run=True, offline=False)
        self.assertFalse(result["fallback_used"],
                         "empty-but-healthy live scan wrongly flagged as fallback")
        self.assertEqual(result["fetch_method"], "live")
        self.assertTrue(result["snapshot_ok"])
        self.assertEqual(result["summary"]["total_proposals"], 0)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_no_fallback_when_snapshot_has_live_data(self, mock_post):
        mock_post.return_value = _snapshot_ok_response(active=True)
        watcher = GovernanceWatcher()
        result = watcher.export(dry_run=True, offline=False)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["fetch_method"], "live")
        self.assertIn("snapshot", result["sources"])
        self.assertGreater(result["summary"]["total_proposals"], 0)

    def test_offline_sets_fallback_used(self):
        watcher = GovernanceWatcher()
        result = watcher.export(dry_run=True, offline=True)
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["fetch_method"], "fallback")


class TestLiveDataFormatValid(unittest.TestCase):
    """The output dict must always carry the health-check schema."""

    HEALTH_KEYS = [
        "fetch_method", "snapshot_ok", "tally_ok",
        "snapshot_spaces_ok", "snapshot_spaces_failed",
        "last_live_fetch", "last_error", "sources", "fallback_used",
    ]

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_live_data_format_valid(self, mock_post):
        mock_post.return_value = _snapshot_ok_response(active=True)
        watcher = GovernanceWatcher()
        result = watcher.export(dry_run=True, offline=False)
        for key in self.HEALTH_KEYS:
            self.assertIn(key, result, f"missing health field {key}")
        self.assertIsInstance(result["snapshot_ok"], bool)
        self.assertIsInstance(result["tally_ok"], bool)
        self.assertIn(result["fetch_method"], ("live", "fallback"))
        # last_live_fetch populated on a successful live scan
        self.assertIsNotNone(result["last_live_fetch"])

    def test_health_keys_present_offline(self):
        watcher = GovernanceWatcher()
        result = watcher.export(dry_run=True, offline=True)
        for key in self.HEALTH_KEYS:
            self.assertIn(key, result)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_spaces_failed_counter_partial_outage(self, mock_post):
        # First space ok, rest fail → snapshot_ok True but failures counted
        calls = {"n": 0}
        def side_effect(url, payload, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _snapshot_ok_response(active=True)
            raise Exception("Simulated outage")
        mock_post.side_effect = side_effect
        watcher = GovernanceWatcher()
        result = watcher.export(dry_run=True, offline=False)
        self.assertTrue(result["snapshot_ok"])
        self.assertEqual(result["snapshot_spaces_ok"], 1)
        self.assertGreater(result["snapshot_spaces_failed"], 0)
        self.assertFalse(result["fallback_used"])


class TestRetryLogic(unittest.TestCase):
    """_http_post_retry retries with backoff and surfaces the final error."""

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_retry_succeeds_on_second_attempt(self, mock_post):
        calls = {"n": 0}
        def side_effect(url, payload, **kwargs):
            calls["n"] += 1
            if calls["n"] < 2:
                raise Exception("transient")
            return {"data": {"ok": True}}
        mock_post.side_effect = side_effect
        out = _http_post_retry("https://x", {"q": 1}, retries=3)
        self.assertEqual(out, {"data": {"ok": True}})
        self.assertEqual(calls["n"], 2)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_retry_exhausts_and_raises(self, mock_post):
        mock_post.side_effect = Exception("permanent failure")
        with self.assertRaises(Exception) as ctx:
            _http_post_retry("https://x", {"q": 1}, retries=3)
        self.assertIn("permanent failure", str(ctx.exception))
        self.assertEqual(mock_post.call_count, 3)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_retry_respects_retries_arg(self, mock_post):
        mock_post.side_effect = Exception("fail")
        with self.assertRaises(Exception):
            _http_post_retry("https://x", {"q": 1}, retries=1)
        self.assertEqual(mock_post.call_count, 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
