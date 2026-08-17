"""test_governance_watchlist_is_ours.py — the governance watchlist must be OUR protocols.

ADR-070 п.14 (owner decision 2026-08-07).  Measured on the shipped config before this
change: eight Snapshot spaces answered every scan, ``snapshot_spaces_failed=0``,
``last_error=null`` — and six of the eight protocols (``balancer``, ``curve``, ``lido``,
``maker``, ``uniswap-v3``, ``yearn``) are ones we cannot invest in, while the protocols
holding paper capital right now (``maple``, ``morpho_steakhouse``, ``euler_v2``,
``spark_susds``, ``yearn_v3``) had no source at all.  Whitelist coverage was 2/36 and
HELD coverage was not even a measured quantity.

Every test here is hermetic: no network, no live ``data/`` writes, no wall clock.  Each
one is red on the pre-ADR-070 module except those marked "positive control", which pin
behaviour that must NOT change.
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from spa_core.alerts import governance_watcher as _gw
from spa_core.alerts.governance_watcher import (
    BOOTSTRAP_PROPOSALS,
    GOVERNANCE_SOURCE_UNCONFIRMED,
    REMOVED_NOT_INVESTABLE,
    SNAPSHOT_SPACES,
    TALLY_GOVERNORS,
    GovernanceWatcher,
    _normalise_protocol_key,
    _print_report,
    coverage_report,
    monitored_protocol_keys,
    read_held_protocol_keys,
    whitelisted_protocol_keys,
)
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# 1. The watchlist contains only protocols we can invest in
# ---------------------------------------------------------------------------

class TestWatchlistIsOurs(unittest.TestCase):

    def test_every_watched_protocol_is_in_our_registry(self):
        registry = whitelisted_protocol_keys()
        self.assertIsNotNone(registry, "registry unreadable — cannot judge the watchlist")
        known = {_normalise_protocol_key(k) for k in registry or []}
        strangers = sorted(
            key for key in monitored_protocol_keys()
            if _normalise_protocol_key(key) not in known
        )
        self.assertEqual(
            strangers, [],
            f"watching protocols we cannot invest in: {strangers}",
        )

    def test_the_six_protocols_the_owner_removed_are_gone_by_name(self):
        for key in REMOVED_NOT_INVESTABLE:
            self.assertNotIn(key, SNAPSHOT_SPACES, f"{key} is back in SNAPSHOT_SPACES")
            self.assertNotIn(key, TALLY_GOVERNORS, f"{key} is back in TALLY_GOVERNORS")

    def test_removed_protocols_are_gone_from_the_fallback_seed_too(self):
        # A stranger surviving in BOOTSTRAP_PROPOSALS keeps showing up in the artifact
        # of every fallback run, which is where a reader looks when live sources are down.
        seeded = {p.protocol for p in BOOTSTRAP_PROPOSALS}
        for key in REMOVED_NOT_INVESTABLE:
            self.assertNotIn(key, seeded)

    def test_positive_control_the_watchlist_is_not_simply_empty(self):
        # "Remove the strangers" must not degenerate into "watch nothing" — that would
        # make every assertion above true and the module useless.
        self.assertGreater(len(monitored_protocol_keys()), 0)
        self.assertGreater(len(BOOTSTRAP_PROPOSALS), 0)


# ---------------------------------------------------------------------------
# 2. Channels we do not have are NAMED, never invented
# ---------------------------------------------------------------------------

class TestUnconfirmedSourcesAreNamedNotInvented(unittest.TestCase):

    def test_the_protocols_the_owner_asked_to_add_are_accounted_for(self):
        for key in ("pendle", "maple", "morpho_blue"):
            self.assertIn(
                key,
                set(GOVERNANCE_SOURCE_UNCONFIRMED) | set(SNAPSHOT_SPACES) | set(TALLY_GOVERNORS),
                f"{key} is neither watched nor listed as an unconfirmed channel",
            )

    def test_every_unconfirmed_entry_carries_a_verbatim_reason(self):
        for key, entry in GOVERNANCE_SOURCE_UNCONFIRMED.items():
            self.assertTrue(str(entry.get("reason", "")).strip(), f"{key} has no reason")

    def test_a_candidate_slug_is_never_used_as_a_live_source(self):
        # The whole point: an unverified slug must not be fetched from, because it
        # either 404s forever or resolves to a stranger's space and is published as
        # our coverage.
        candidates = {
            str(e.get("candidate_space", "")) for e in GOVERNANCE_SOURCE_UNCONFIRMED.values()
        }
        candidates.discard("")
        self.assertEqual(candidates & set(SNAPSHOT_SPACES.values()), set())

    def test_report_marks_them_unverified(self):
        for entry in _gw.unconfirmed_source_report():
            self.assertEqual(entry["verified"], "no")


# ---------------------------------------------------------------------------
# 3. HELD coverage — the gap that costs money
# ---------------------------------------------------------------------------

class TestHeldSetReader(unittest.TestCase):

    def test_reads_the_mapping_the_cycle_writes(self):
        keys, reason = read_held_protocol_keys(
            {"current_positions": {"aave_v3": 23250.0, "maple": 15852.27}}
        )
        self.assertIsNone(reason)
        self.assertEqual(keys, ["aave_v3", "maple"])

    def test_positive_control_empty_position_map_is_a_measurement(self):
        keys, reason = read_held_protocol_keys({"current_positions": {}})
        self.assertEqual(keys, [])
        self.assertIsNone(reason)

    def test_missing_key_is_not_measured_and_says_which_keys_were_there(self):
        keys, reason = read_held_protocol_keys({"current_equity": 100273.91})
        self.assertIsNone(keys)
        self.assertIn("current_positions", reason or "")
        self.assertIn("current_equity", reason or "")

    def test_non_mapping_payload_is_not_measured(self):
        keys, reason = read_held_protocol_keys(["aave_v3"])
        self.assertIsNone(keys)
        self.assertTrue(reason)

    def test_list_of_position_records_is_also_understood(self):
        keys, reason = read_held_protocol_keys(
            {"current_positions": [{"protocol": "maple", "amount_usd": 1.0}]}
        )
        self.assertIsNone(reason)
        self.assertEqual(keys, ["maple"])

    def test_unreadable_file_is_not_measured_never_an_empty_held_set(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            keys, reason = _gw.load_held_protocol_keys(tmp / "nope.json")
            self.assertIsNone(keys)
            self.assertTrue(reason)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestHeldCoverageIsReported(unittest.TestCase):

    def test_held_protocol_without_a_source_is_named(self):
        cov = coverage_report(held=["aave_v3", "maple", "spark_susds"])
        self.assertTrue(cov["held_measured"])
        self.assertIn("maple", cov["held_unchecked"])
        self.assertIn("spark_susds", cov["held_unchecked"])

    def test_positive_control_held_protocol_with_a_source_is_covered(self):
        cov = coverage_report(held=["aave_v3", "maple"])
        self.assertIn("aave_v3", cov["held_covered"])
        self.assertNotIn("aave_v3", cov["held_unchecked"])

    def test_held_source_that_failed_this_scan_is_not_covered(self):
        cov = coverage_report(
            scan_status={"aave-v3": "failed"}, held=["aave_v3", "maple"]
        )
        self.assertIn("aave_v3", cov["held_unchecked"])
        self.assertNotIn("aave_v3", cov["held_covered"])

    def test_unsupplied_held_set_is_not_measured_not_a_zero_gap(self):
        cov = coverage_report()
        self.assertFalse(cov["held_measured"])
        self.assertTrue(cov["held_reason"])
        self.assertEqual(cov["held_covered"], [])

    def test_verbatim_held_reason_is_carried_through(self):
        cov = coverage_report(held_unchecked="portfolio status missing or unreadable")
        self.assertFalse(cov["held_measured"])
        self.assertIn("portfolio status missing", cov["held_reason"])


# ---------------------------------------------------------------------------
# 4. The published artifact and the operator report say it out loud
# ---------------------------------------------------------------------------

class TestExportNamesTheHeldGap(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.status = self.tmp / "paper_trading_status.json"
        atomic_save(
            {"current_positions": {"aave_v3": 10.0, "maple": 20.0}}, str(self.status)
        )
        self.watcher = GovernanceWatcher(
            output_file=self.tmp / "governance_proposals.json",
            portfolio_status_file=self.status,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_offline_run_reports_held_protocols_and_the_gap(self):
        result = self.watcher.export(dry_run=True, offline=True)
        cov = result["coverage"]
        self.assertEqual(cov["held_protocols"], ["aave_v3", "maple"])
        # Offline/fallback measured nothing live, so nothing held may read as covered.
        self.assertEqual(cov["held_covered"], [])
        self.assertEqual(sorted(cov["held_unchecked"]), ["aave_v3", "maple"])
        self.assertEqual(result["summary"]["unchecked_held_count"], 2)

    def test_unreadable_status_file_publishes_not_measured_not_zero(self):
        watcher = GovernanceWatcher(
            output_file=self.tmp / "governance_proposals.json",
            portfolio_status_file=self.tmp / "absent.json",
        )
        result = watcher.export(dry_run=True, offline=True)
        self.assertFalse(result["coverage"]["held_measured"])
        self.assertIsNone(result["summary"]["unchecked_held_count"])

    def test_positive_control_live_scan_covers_a_held_protocol(self):
        def _fake_post(url, payload, **kwargs):
            if "snapshot" in url:
                return {"data": {"proposals": []}}
            raise RuntimeError("tally not mocked")

        with patch.object(_gw, "_http_post", side_effect=_fake_post):
            result = self.watcher.export(dry_run=True, offline=False)
        cov = result["coverage"]
        self.assertFalse(result["fallback_used"])
        self.assertIn("aave_v3", cov["held_covered"])
        self.assertIn("maple", cov["held_unchecked"])

    def test_dry_run_writes_nothing(self):
        self.watcher.export(dry_run=True, offline=True)
        self.assertFalse((self.tmp / "governance_proposals.json").exists())

    def test_operator_report_prints_the_held_gap_by_name(self):
        result = self.watcher.export(dry_run=True, offline=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_report(result)
        text = buf.getvalue()
        self.assertIn("Held coverage:", text)
        self.assertIn("HELD, NOT CHECKED", text)
        self.assertIn("maple", text)
        self.assertIn("no channel: pendle", text)

    def test_operator_report_says_not_measured_when_it_is_not(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_report({"coverage": {"measured": True, "whitelist_size": 36}})
        self.assertIn("Held coverage:    NOT MEASURED", buf.getvalue())

    def test_artifact_is_json_serialisable(self):
        result = self.watcher.export(dry_run=True, offline=True)
        json.dumps(result)  # must not raise


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
