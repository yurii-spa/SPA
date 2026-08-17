"""
Coverage honesty for spa_core/alerts/governance_watcher.py — cycle #76.

The defect these tests pin
--------------------------
``com.spa.governance_watcher`` runs every 15 minutes and published, on live
production data (2026-08-01T19:32:12Z)::

    "snapshot_spaces_ok": 8, "snapshot_spaces_failed": 0,
    "last_error": null, "fallback_used": false, "fetch_method": "live"

which reads as "everything was scanned".  What it actually scans is the
hard-coded ``SNAPSHOT_SPACES`` / ``TALLY_GOVERNORS`` sets, whose intersection
with the live portfolio (morpho / pendle / susde / extra_finance_base /
spark_susds — 80% of capital) was **empty**.  ``has_active_risk_proposals``
compounded it: for every unmonitored protocol it answers ``False``, i.e. the
same value as "checked, nothing found" — a claim about a check that never ran
(the recurring fail-OPEN class of cycles #29 / #31 / #35–#38 / #40).

Everything here is hermetic: no network, no live data files, no writes.  The
transport counters (``snapshot_ok`` True on partial outage) are deliberately
NOT touched — they are pinned as intentional by
``test_governance_watcher.py::test_spaces_failed_counter_partial_outage``.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.alerts import governance_watcher as _gw
from spa_core.alerts.governance_watcher import (
    UNCHECKED,
    GovernanceWatcher,
    coverage_report,
    monitored_protocol_keys,
    whitelisted_protocol_keys,
    _normalise_protocol_key,
)

_gw._sleep = lambda *_a, **_k: None  # no backoff sleeps


# ---------------------------------------------------------------------------
# Helpers — hermetic Snapshot responses
# ---------------------------------------------------------------------------

def _ok_response(active=True):
    return {
        "data": {
            "proposals": [{
                "id": "0xcov",
                "title": "Emergency pause of the USDC market",
                "body": "pause",
                "state": "active" if active else "closed",
                "start": 1_716_000_000,
                "end":   1_716_600_000,
                "scores": [1_000_000, 50_000],
                "scores_total": 1_050_000,
                "quorum": 500_000,
                "link": "https://snapshot.org/#/example/proposal/0xcov",
            }]
        }
    }


def _empty_response():
    return {"data": {"proposals": []}}


class _FakeWhitelist:
    """Swap ADAPTER_REGISTRY-derived whitelist for a deterministic one."""

    def __init__(self, keys):
        self.keys = keys

    def __enter__(self):
        self._patch = patch.object(
            _gw, "whitelisted_protocol_keys", lambda: self.keys
        )
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        return False


# ---------------------------------------------------------------------------
# 1. The whitelist source itself
# ---------------------------------------------------------------------------

class TestWhitelistSource(unittest.TestCase):

    def test_whitelist_comes_from_the_registry_not_a_second_hardcoded_list(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        keys = whitelisted_protocol_keys()
        self.assertIsNotNone(keys)
        self.assertEqual(len(keys), len(ADAPTER_REGISTRY))

    def test_unreadable_registry_returns_none_not_an_empty_whitelist(self):
        # An empty list would silently mean "nothing to cover" → full coverage.
        with patch.dict(sys.modules, {"spa_core.adapters": None}):
            self.assertIsNone(whitelisted_protocol_keys())

    def test_malformed_registry_returns_none(self):
        with patch.object(_gw, "whitelisted_protocol_keys", lambda: None):
            self.assertIsNone(_gw.whitelisted_protocol_keys())

    def test_monitored_set_is_the_union_of_both_source_tables(self):
        expected = set(_gw.SNAPSHOT_SPACES) | set(_gw.TALLY_GOVERNORS)
        self.assertEqual(monitored_protocol_keys(), expected)


# ---------------------------------------------------------------------------
# 2. coverage_report — the gap must be named
# ---------------------------------------------------------------------------

class TestCoverageReport(unittest.TestCase):

    def test_whitelisted_protocol_without_a_source_is_unchecked(self):
        with _FakeWhitelist(["aave-v3", "pendle", "susde"]):
            cov = coverage_report()
        self.assertTrue(cov["measured"])
        self.assertIn("pendle", cov["unchecked_protocols"])
        self.assertIn("susde", cov["unchecked_protocols"])

    def test_positive_control_a_monitored_protocol_IS_reported_covered(self):
        # Guards against "everything lands in unchecked", which would make the
        # report true but useless.
        with _FakeWhitelist(["aave-v3", "pendle"]):
            cov = coverage_report()
        self.assertIn("aave-v3", cov["covered_protocols"])
        self.assertNotIn("aave-v3", cov["unchecked_protocols"])

    def test_covered_and_unchecked_partition_the_whitelist(self):
        wl = ["aave-v3", "pendle", "susde", "compound-v3"]
        with _FakeWhitelist(list(wl)):
            cov = coverage_report()
        self.assertEqual(
            sorted(cov["covered_protocols"] + cov["unchecked_protocols"]),
            sorted(wl),
        )

    def test_source_that_failed_this_scan_is_unchecked_not_covered(self):
        with _FakeWhitelist(["aave-v3", "pendle"]):
            cov = coverage_report(scan_status={"aave-v3": "failed"})
        self.assertIn("aave-v3", cov["unchecked_protocols"])
        self.assertNotIn("aave-v3", cov["covered_protocols"])
        self.assertIn("aave-v3", cov["failed_this_scan"])

    def test_positive_control_same_protocol_ok_this_scan_is_covered(self):
        with _FakeWhitelist(["aave-v3", "pendle"]):
            cov = coverage_report(scan_status={"aave-v3": "ok"})
        self.assertIn("aave-v3", cov["covered_protocols"])
        self.assertEqual(cov["failed_this_scan"], [])

    def test_watched_but_not_investable_sources_are_named(self):
        # The mechanism (a configured source outside the whitelist must be NAMED) is
        # unchanged; the example had to move.  It used to rely on `balancer` sitting
        # in the production watchlist, and ADR-070 п.14 removed balancer/curve/lido/
        # maker/uniswap-v3/yearn by name — after that there is deliberately no
        # stranger left in the shipped config, so the stranger is now produced by the
        # injected whitelist instead of by a defect in the config.  Same assertion,
        # same guarantee; recorded in docs/journal/2026-W34.md (invariant #16).
        with _FakeWhitelist(["aave-v3"]):
            cov = coverage_report()
        self.assertIn("compound-v3", cov["monitored_not_whitelisted"])
        self.assertNotIn("aave-v3", cov["monitored_not_whitelisted"])

    def test_hyphen_underscore_spelling_does_not_create_a_false_gap(self):
        with _FakeWhitelist(["aave_v3", "compound_v3"]):
            cov = coverage_report()
        self.assertEqual(cov["unchecked_protocols"], [])
        self.assertEqual(sorted(cov["covered_protocols"]), ["aave_v3", "compound_v3"])

    def test_normalise_folds_case_and_separators(self):
        self.assertEqual(
            _normalise_protocol_key("Aave-V3"), _normalise_protocol_key("aave_v3")
        )

    # ── fail-CLOSED ────────────────────────────────────────────────────────

    def test_unreadable_whitelist_reports_not_measured_never_full_coverage(self):
        with _FakeWhitelist(None):
            cov = coverage_report()
        self.assertFalse(cov["measured"])
        self.assertTrue(cov["reason"])
        self.assertEqual(cov["covered_protocols"], [])
        self.assertIsNone(cov["whitelist_size"])

    def test_not_measured_does_not_silently_report_zero_gaps(self):
        with _FakeWhitelist(None):
            cov = coverage_report()
        # The gap is unknown, so it must not be published as an empty gap
        # with measured=True — the reader has to see the refusal.
        self.assertFalse(cov["measured"])

    def test_coverage_report_never_raises(self):
        def _boom():
            raise RuntimeError("registry exploded")
        with patch.object(_gw, "whitelisted_protocol_keys", _boom):
            cov = coverage_report()
        self.assertFalse(cov["measured"])
        self.assertIn("registry exploded", cov["reason"])


# ---------------------------------------------------------------------------
# 3. The published artifact
# ---------------------------------------------------------------------------

class TestExportCarriesCoverage(unittest.TestCase):

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_export_publishes_coverage_block(self, mock_post):
        mock_post.return_value = _empty_response()
        result = GovernanceWatcher().export(dry_run=True, offline=False)
        self.assertIn("coverage", result)
        self.assertIn("unchecked_protocols", result["coverage"])

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_summary_counts_the_gap(self, mock_post):
        mock_post.return_value = _empty_response()
        with _FakeWhitelist(["aave-v3", "pendle", "susde"]):
            result = GovernanceWatcher().export(dry_run=True, offline=False)
        self.assertEqual(result["summary"]["unchecked_protocol_count"], 2)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_unmeasured_gap_is_none_not_zero(self, mock_post):
        # 0 would read as "no protocol is unchecked" — the exact fail-OPEN.
        mock_post.return_value = _empty_response()
        with _FakeWhitelist(None):
            result = GovernanceWatcher().export(dry_run=True, offline=False)
        self.assertIsNone(result["summary"]["unchecked_protocol_count"])
        self.assertFalse(result["coverage"]["measured"])

    def test_bootstrap_fallback_covers_nothing(self):
        # Offline → seed data.  Seed data is not a measurement.
        with _FakeWhitelist(["aave-v3", "pendle"]):
            result = GovernanceWatcher().export(dry_run=True, offline=True)
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["coverage"]["covered_protocols"], [])
        self.assertIn("aave-v3", result["coverage"]["unchecked_protocols"])

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_failed_space_is_named_in_the_artifact(self, mock_post):
        # The aggregate snapshot_spaces_failed counter cannot say WHICH one.
        calls = {"n": 0}

        def side_effect(url, payload, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _empty_response()
            raise RuntimeError("simulated outage")

        mock_post.side_effect = side_effect
        result = GovernanceWatcher().export(dry_run=True, offline=False)
        self.assertTrue(result["coverage"]["failed_this_scan"])

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_export_still_carries_the_pre_existing_health_schema(self, mock_post):
        mock_post.return_value = _empty_response()
        result = GovernanceWatcher().export(dry_run=True, offline=False)
        for key in ("fetch_method", "snapshot_ok", "tally_ok",
                    "snapshot_spaces_ok", "snapshot_spaces_failed",
                    "last_live_fetch", "last_error", "sources", "fallback_used"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# 4. risk_proposal_state — refuse instead of guessing
# ---------------------------------------------------------------------------

class TestRiskProposalState(unittest.TestCase):

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_unmonitored_protocol_is_unchecked_not_clean(self, mock_post):
        mock_post.return_value = _empty_response()
        w = GovernanceWatcher()
        # "pendle" is 20% of the live book and has no governance source.
        self.assertEqual(w.risk_proposal_state("pendle"), UNCHECKED)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_the_old_bool_still_says_False_for_that_same_protocol(self, mock_post):
        # Documents the difference the new method exists to expose.  The old
        # method is deliberately left as-is for existing callers.
        mock_post.return_value = _empty_response()
        w = GovernanceWatcher()
        self.assertFalse(w.has_active_risk_proposals("pendle"))
        self.assertEqual(w.risk_proposal_state("pendle"), UNCHECKED)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_positive_control_monitored_and_clean_is_none_not_unchecked(self, mock_post):
        mock_post.return_value = _empty_response()
        w = GovernanceWatcher()
        self.assertEqual(w.risk_proposal_state("aave-v3"), "none")

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_positive_control_monitored_with_active_high_is_active_high(self, mock_post):
        mock_post.return_value = _ok_response(active=True)
        w = GovernanceWatcher()
        self.assertEqual(w.risk_proposal_state("aave-v3"), "active_high")

    def test_bootstrap_fallback_is_unchecked_for_everyone(self):
        w = GovernanceWatcher()
        self.assertEqual(w.risk_proposal_state("aave-v3", offline=True), UNCHECKED)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_failed_source_is_unchecked_for_that_protocol(self, mock_post):
        first = next(iter(_gw.SNAPSHOT_SPACES))

        def side_effect(url, payload, **kwargs):
            if _gw.SNAPSHOT_SPACES[first] in str(payload):
                raise RuntimeError("simulated outage")
            return _empty_response()

        mock_post.side_effect = side_effect
        w = GovernanceWatcher()
        self.assertEqual(w.risk_proposal_state(first), UNCHECKED)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_state_is_always_one_of_three_values(self, mock_post):
        mock_post.return_value = _empty_response()
        w = GovernanceWatcher()
        for key in ("aave-v3", "pendle", "nonexistent-protocol-xyz"):
            self.assertIn(w.risk_proposal_state(key), ("active_high", "none", UNCHECKED))

    def test_never_raises(self):
        w = GovernanceWatcher()
        with patch.object(GovernanceWatcher, "scan_all",
                          side_effect=RuntimeError("boom")):
            self.assertEqual(w.risk_proposal_state("aave-v3"), UNCHECKED)


# ---------------------------------------------------------------------------
# 5. What the operator actually reads
# ---------------------------------------------------------------------------

class TestCliSurface(unittest.TestCase):

    def _render(self, result):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _gw._print_report(result)
        return buf.getvalue()

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_cli_names_the_unchecked_protocols(self, mock_post):
        mock_post.return_value = _empty_response()
        with _FakeWhitelist(["aave-v3", "pendle", "susde"]):
            out = self._render(GovernanceWatcher().export(dry_run=True, offline=False))
        self.assertIn("NOT CHECKED", out)
        self.assertIn("pendle", out)
        self.assertIn("susde", out)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_cli_says_not_measured_when_coverage_is_unknown(self, mock_post):
        mock_post.return_value = _empty_response()
        with _FakeWhitelist(None):
            out = self._render(GovernanceWatcher().export(dry_run=True, offline=False))
        self.assertIn("NOT MEASURED", out)

    @patch("spa_core.alerts.governance_watcher._http_post")
    def test_transport_line_no_longer_reads_as_coverage(self, mock_post):
        mock_post.return_value = _empty_response()
        out = self._render(GovernanceWatcher().export(dry_run=True, offline=False))
        self.assertIn("transport only", out)


# ---------------------------------------------------------------------------
# 6. The false claim in the module docstring
# ---------------------------------------------------------------------------

class TestDocstringHonesty(unittest.TestCase):

    def test_module_no_longer_claims_to_monitor_the_whitelist(self):
        doc = _gw.__doc__ or ""
        self.assertNotIn(
            "Monitors active governance proposals for SPA whitelist protocols", doc
        )

    def test_module_docstring_points_at_coverage_accounting(self):
        doc = _gw.__doc__ or ""
        self.assertIn("coverage", doc)

    def test_old_bool_method_warns_about_its_own_blind_spot(self):
        doc = GovernanceWatcher.has_active_risk_proposals.__doc__ or ""
        self.assertIn("risk_proposal_state", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
