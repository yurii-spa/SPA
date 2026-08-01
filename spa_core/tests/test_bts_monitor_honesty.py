"""test_bts_monitor_honesty.py — the BTS pair must not report a scan it did not perform.

Cycle #78. `com.spa.bts-monitor` runs every 15 minutes and published, every single time:

    {'opportunities': 0, 'new_excellent': 0, 'errors': [], 'status': 'ok'}
    {'signal_count': 0, 'clear': True, 'signals': [], 'status': 'ok'}

while its own log said `No rates in funding data`. Cause: both modules asked the funding
payload for `rates` and `generated_at`; `spa_core/feeds/perp_funding_feed.py` writes
`assets`, `fetched_at`, `timestamp` and `stale`, and `git log -S'"rates"'` on the feed
returns zero commits — those keys were never written by anybody.

Every test here is hermetic (tmpdir, no network, no live `data/`) and each one is red on
the pre-#78 code, EXCEPT the ones marked "positive control", which must be green both
before and after — they pin the behaviour that must NOT change (legacy payloads still
read, thresholds unchanged, an unmeasured check never fabricated into a signal).
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.analytics.bts_exit_monitor import BTSExitMonitor
from spa_core.feeds.funding_schema import (
    CANONICAL_RATES_KEY,
    LEGACY_RATES_KEY,
    feed_age_seconds,
    read_rates,
)
from spa_core.monitoring.bts_monitor import (
    ADAPTER_STATUS_FILENAME,
    FUNDING_FILENAME,
    OPP_FILENAME,
    STATUS_FILENAME,
    BTSMonitor,
)
from spa_core.utils.atomic import atomic_save


def _live_shape(assets=None, stale=False, fetched_at=None):
    """A payload in the shape `perp_funding_feed.run()` actually writes."""
    now = datetime.now(timezone.utc)
    if assets is None:
        assets = {
            "ETH": {"funding_rate_annual": 0.12, "mark_price": 1847.96},
            "BTC": {"funding_rate_annual": 0.09, "mark_price": 61000.0},
            "SOL": {"funding_rate_annual": 0.15, "mark_price": 140.0},
        }
    return {
        "timestamp": now.isoformat(),
        "fetched_at": fetched_at if fetched_at is not None else now.timestamp(),
        "stale": stale,
        "assets": assets,
    }


def _legacy_shape(rates=None, generated_at=None):
    """The shape the pre-existing test fixtures build — must keep working untouched."""
    gen = generated_at or datetime.now(timezone.utc).isoformat()
    if rates is None:
        rates = {
            "ETH": {"funding_rate_annual": 0.12},
            "BTC": {"funding_rate_annual": 0.09},
            "SOL": {"funding_rate_annual": 0.15},
        }
    return {"generated_at": gen, "stale": False, "rates": rates}


def _adapter_status():
    return {"aave_v3": {"apy": 4.5}, "morpho_steakhouse": {"apy": 5.2}}


class TestFundingSchemaReader(unittest.TestCase):
    """The single reader both monitors share."""

    def test_reads_the_key_the_live_feed_writes(self):
        read = read_rates(_live_shape())
        self.assertTrue(read.measured)
        self.assertEqual(read.source_key, CANONICAL_RATES_KEY)
        self.assertEqual(set(read.rates), {"ETH", "BTC", "SOL"})

    def test_still_reads_the_legacy_key(self):
        # positive control — no existing fixture may stop working.
        read = read_rates(_legacy_shape())
        self.assertTrue(read.measured)
        self.assertEqual(read.source_key, LEGACY_RATES_KEY)

    def test_live_key_wins_when_both_present(self):
        payload = _live_shape()
        payload[LEGACY_RATES_KEY] = {"DOGE": {"funding_rate_annual": 9.0}}
        read = read_rates(payload)
        self.assertEqual(read.source_key, CANONICAL_RATES_KEY)
        self.assertNotIn("DOGE", read.rates)

    def test_neither_key_is_not_measured_and_says_which_keys_were_there(self):
        read = read_rates({"timestamp": "x", "stale": False, "funding": {}})
        self.assertFalse(read.measured)
        self.assertIn(CANONICAL_RATES_KEY, read.unchecked)
        # the reason quotes what WAS in the file, so the mismatch is diagnosable
        self.assertIn("funding", read.unchecked)

    def test_present_but_empty_map_is_a_measurement_not_a_failure(self):
        # positive control — "the feed reported no assets" is a fact, not an unknown.
        read = read_rates(_live_shape(assets={}))
        self.assertTrue(read.measured)
        self.assertEqual(read.rates, {})

    def test_non_mapping_under_the_key_is_not_measured(self):
        read = read_rates({CANONICAL_RATES_KEY: ["ETH"]})
        self.assertFalse(read.measured)
        self.assertIn("list", read.unchecked)

    def test_age_read_from_the_epoch_key_the_feed_writes(self):
        payload = _live_shape(fetched_at=time.time() - 600)
        age = feed_age_seconds(payload)
        self.assertTrue(age.measured)
        self.assertEqual(age.source_key, "fetched_at")
        self.assertAlmostEqual(age.age_seconds, 600, delta=30)

    def test_age_falls_back_to_iso_keys(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=900)).isoformat()
        age = feed_age_seconds({"timestamp": old})
        self.assertTrue(age.measured)
        self.assertAlmostEqual(age.age_seconds, 900, delta=30)

    def test_legacy_generated_at_still_parsed(self):
        # positive control
        old = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        age = feed_age_seconds({"generated_at": old})
        self.assertTrue(age.measured)
        self.assertEqual(age.source_key, "generated_at")

    def test_unparseable_age_is_not_measured_and_quotes_the_keys(self):
        age = feed_age_seconds({"fetched_at": "not-a-number", "stale": False})
        self.assertFalse(age.measured)
        self.assertIsNone(age.age_seconds)
        self.assertIn("fetched_at", age.unchecked)


class TestMonitorReadsTheLiveFeed(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSMonitor(data_dir=self.data_dir, use_alert_dispatcher=False)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, payload, name=FUNDING_FILENAME):
        atomic_save(payload, str(self.data_dir / name))

    def test_live_shape_produces_opportunities(self):
        """The headline: the shape the feed writes must actually be scanned."""
        self._write(_live_shape())
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        opps = self.monitor.scan()
        self.assertEqual({o.asset for o in opps}, {"ETH", "BTC", "SOL"})

    def test_extra_untracked_asset_is_ignored_not_fatal(self):
        assets = _live_shape()["assets"]
        assets["ARB"] = {"funding_rate_annual": 0.20}  # the live feed does send ARB
        self._write(_live_shape(assets=assets))
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        self.assertEqual({o.asset for o in self.monitor.scan()}, {"ETH", "BTC", "SOL"})

    def test_stale_by_age_from_fetched_at_refuses(self):
        """The age gate finally runs — and refuses, threshold unchanged."""
        self._write(_live_shape(fetched_at=time.time() - 4000))
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        scan = self.monitor.scan_with_reasons()
        self.assertEqual(scan.opportunities, [])
        self.assertTrue(scan.stale_feed)
        self.assertIn("exceeds", scan.refusal)

    def test_fresh_by_age_is_not_refused(self):
        # positive control — the threshold must not have moved.
        self._write(_live_shape(fetched_at=time.time() - 60))
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        self.assertTrue(self.monitor.scan())


class TestStatusIsNotOkWhenNothingWasRead(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSMonitor(data_dir=self.data_dir, use_alert_dispatcher=False)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, payload, name=FUNDING_FILENAME):
        atomic_save(payload, str(self.data_dir / name))

    def _status(self):
        return json.loads((self.data_dir / STATUS_FILENAME).read_text())

    def test_unknown_schema_is_unchecked_not_ok(self):
        """The live defect, reproduced: a payload this monitor cannot read."""
        self._write({"timestamp": "x", "stale": False, "quotes": {"ETH": 1}})
        report = self.monitor.run()
        self.assertEqual(report["status"], "unchecked")
        self.assertTrue(report["unchecked"])
        self.assertEqual(self._status()["status"], "unchecked")

    def test_unchecked_reason_is_verbatim_in_the_artifact(self):
        self._write({"timestamp": "x", "stale": False, "quotes": {"ETH": 1}})
        self.monitor.run()
        blob = json.dumps(self._status()["unchecked"])
        self.assertIn("quotes", blob)

    def test_missing_funding_file_is_not_ok(self):
        report = self.monitor.run()
        self.assertNotEqual(report["status"], "ok")
        self.assertTrue(report["unchecked"])

    def test_unmeasurable_age_is_reported_even_when_rates_parse(self):
        payload = _live_shape()
        payload.pop("fetched_at")
        payload.pop("timestamp")
        self._write(payload)
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        report = self.monitor.run()
        self.assertGreater(report["opportunities"], 0)  # it still scans
        self.assertEqual(report["status"], "unchecked")  # but says the age is unknown
        self.assertTrue(any("age NOT MEASURED" in u for u in report["unchecked"]))

    def test_ok_when_everything_really_was_measured(self):
        # positive control — a healthy run must still say "ok", or the verdict is useless.
        self._write(_live_shape())
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        report = self.monitor.run()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["unchecked"], [])

    def test_legacy_payload_still_reports_ok(self):
        # positive control — the pre-existing fixtures must not start reporting unchecked.
        self._write(_legacy_shape())
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        self.assertEqual(self.monitor.run()["status"], "ok")

    def test_empty_asset_map_is_measured_and_ok(self):
        # positive control — an honest zero is not an unknown.
        self._write(_live_shape(assets={}))
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        report = self.monitor.run()
        self.assertEqual(report["opportunities"], 0)
        self.assertEqual(report["status"], "ok")


class TestAlertTransportIsDisarmedButNotSilent(unittest.TestCase):
    """Repointing the feed reader wakes an alert path that had never fired once.

    A read-only smoke on a COPY of production data showed the first live run would send
    three "BTS EXCELLENT … Annual PnL $N" Telegram messages (EXCELLENT is >=100bps net
    against a hardcoded 5% spot baseline, so any non-negative funding clears it). Arming
    an owner-facing claim from an unvalidated model is an owner decision — but the
    suppression must be visible, not silent.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.sent = []

        class _Recording(BTSMonitor):
            outer = self

            def _create_alerts(inner, new_excellent):  # noqa: N805
                inner.outer.sent.extend(o.asset for o in new_excellent)
                return len(new_excellent)

        self.monitor = _Recording(data_dir=self.data_dir, use_alert_dispatcher=False)
        atomic_save(_live_shape(), str(self.data_dir / FUNDING_FILENAME))
        atomic_save(_adapter_status(), str(self.data_dir / ADAPTER_STATUS_FILENAME))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_disarmed_by_default_nothing_is_sent(self):
        report = self.monitor.run()
        self.assertGreater(report["new_excellent"], 0)
        self.assertEqual(self.sent, [])

    def test_suppression_is_recorded_verbatim_not_silent(self):
        self.monitor.run()
        status = json.loads((self.data_dir / STATUS_FILENAME).read_text())
        blob = json.dumps(status["suppressed_alerts"])
        self.assertIn("NOT sent to Telegram", blob)
        self.assertIn("SPA_BTS_ALERTS_ARMED", blob)

    def test_suppression_does_not_masquerade_as_an_unmeasured_check(self):
        # positive control — a healthy run stays "ok"; suppression is its own field.
        report = self.monitor.run()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["unchecked"], [])

    def test_owner_can_arm_it(self):
        import os

        os.environ["SPA_BTS_ALERTS_ARMED"] = "1"
        try:
            self.monitor.run()
        finally:
            os.environ.pop("SPA_BTS_ALERTS_ARMED", None)
        self.assertEqual(set(self.sent), {"ETH", "BTC", "SOL"})


class TestStaleFeedDescribesTheFeed(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSMonitor(data_dir=self.data_dir, use_alert_dispatcher=False)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, payload, name=FUNDING_FILENAME):
        atomic_save(payload, str(self.data_dir / name))

    def _opps_file(self):
        return json.loads((self.data_dir / OPP_FILENAME).read_text())

    def test_fresh_feed_with_zero_opportunities_is_not_called_stale(self):
        """`stale_feed` used to be `len(opps) == 0` — a claim about a file, derived
        from something else entirely. Live evidence: stale_feed=true while the feed
        said stale=false, 7 minutes old."""
        self._write(_live_shape(assets={}))  # fresh feed, nothing to analyse
        self._write(_adapter_status(), ADAPTER_STATUS_FILENAME)
        self.monitor.run()
        self.assertFalse(self._opps_file()["stale_feed"])

    def test_feed_that_marked_itself_stale_is_stale(self):
        # positive control
        self._write(_live_shape(stale=True))
        self.monitor.run()
        self.assertTrue(self._opps_file()["stale_feed"])

    def test_missing_feed_is_stale(self):
        # positive control — pins the pre-existing behaviour of test_run_empty_writes_stale
        self.monitor.run()
        self.assertTrue(self._opps_file()["stale_feed"])

    def test_measured_flag_travels_with_the_summary(self):
        self._write({"timestamp": "x", "stale": False, "quotes": {}})
        self.monitor.run()
        self.assertFalse(self._opps_file()["summary"]["measured"])


class TestExitMonitorHonesty(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)
        self.monitor = BTSExitMonitor(data_dir=self.data_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_funding(self, payload):
        atomic_save(payload, str(self.data_dir / "perp_funding_rates.json"))

    def _exit_file(self):
        return json.loads((self.data_dir / "bts_exit_signals.json").read_text())

    def test_live_shape_is_evaluated(self):
        """Negative funding in the live shape must reach the exit rules."""
        self._write_funding(
            _live_shape(assets={"ETH": {"funding_rate_annual": -0.10}})
        )
        result = self.monitor.run()
        reasons = {s["reason"] for s in result["signals"]}
        self.assertIn("FUNDING_REVERSAL", reasons)

    def test_unknown_schema_is_unchecked_not_clear(self):
        self._write_funding({"timestamp": "x", "stale": False, "quotes": {"ETH": 1}})
        result = self.monitor.run()
        self.assertEqual(result["status"], "unchecked")
        self.assertTrue(result["unchecked"])

    def test_crash_does_not_publish_clear_true(self):
        """A crashed exit check used to publish `clear: True` — "no reason to exit"
        about a check that never finished."""

        class _Boom(BTSExitMonitor):
            def evaluate_with_reasons(self, funding_data):  # noqa: D102
                raise RuntimeError("analyzer exploded")

        monitor = _Boom(data_dir=self.data_dir)
        self._write_funding(_live_shape())
        result = monitor.run()
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["clear"])
        self.assertIsNone(self._exit_file()["clear"])
        self.assertFalse(self._exit_file()["measured"])
        self.assertIn("analyzer exploded", json.dumps(self._exit_file()["unchecked"]))

    def test_clear_true_survives_a_healthy_run(self):
        # positive control — `clear` must still mean something on the happy path.
        self._write_funding(
            _live_shape(assets={"ETH": {"funding_rate_annual": 0.40}})
        )
        result = self.monitor.run()
        self.assertTrue(result["clear"])
        self.assertTrue(self._exit_file()["measured"])

    def test_absent_kill_switch_file_stays_off(self):
        # positive control — absent = not armed is the documented semantics, unchanged.
        self._write_funding(_live_shape())
        signals, unchecked = self.monitor.evaluate_with_reasons(_live_shape())
        self.assertNotIn("MANUAL_KILL", {s.reason for s in signals})
        self.assertEqual([u for u in unchecked if "kill-switch" in u], [])

    def test_corrupt_kill_switch_file_is_unchecked_not_off(self):
        """Unparseable JSON: reads back as nothing, which is not the same as 'not armed'."""
        (self.data_dir / "bts_kill_switch.json").write_text("[not, a, mapping")
        signals, unchecked = self.monitor.evaluate_with_reasons(_live_shape())
        self.assertTrue(any("kill-switch" in u for u in unchecked))
        # ... and it is NOT escalated into a fabricated CRITICAL signal
        self.assertNotIn("MANUAL_KILL", {s.reason for s in signals})

    def test_kill_switch_file_holding_a_non_mapping_is_unchecked_not_off(self):
        """Valid JSON of the wrong shape — a distinct branch from the corrupt one.

        Found by a mutation control: silencing this branch reddened no test until this
        case existed, i.e. `active` could go unread with nobody noticing.
        """
        (self.data_dir / "bts_kill_switch.json").write_text("[1, 2, 3]")
        signals, unchecked = self.monitor.evaluate_with_reasons(_live_shape())
        self.assertTrue(any("NOT MEASURED" in u for u in unchecked))
        self.assertNotIn("MANUAL_KILL", {s.reason for s in signals})

    def test_armed_kill_switch_still_fires(self):
        # positive control — the real MANUAL_KILL path is untouched.
        atomic_save({"active": True}, str(self.data_dir / "bts_kill_switch.json"))
        signals, _ = self.monitor.evaluate_with_reasons(_live_shape())
        self.assertIn("MANUAL_KILL", {s.reason for s in signals})

    def test_unmeasurable_age_is_reported_and_not_called_stale(self):
        payload = _live_shape()
        payload.pop("fetched_at")
        payload.pop("timestamp")
        self._write_funding(payload)
        result = self.monitor.run()
        self.assertTrue(any("age NOT MEASURED" in u for u in result["unchecked"]))
        self.assertNotIn("STALE_DATA", {s["reason"] for s in result["signals"]})

    def test_old_feed_by_fetched_at_raises_stale_data(self):
        self._write_funding(_live_shape(fetched_at=time.time() - 4000))
        result = self.monitor.run()
        self.assertIn("STALE_DATA", {s["reason"] for s in result["signals"]})


if __name__ == "__main__":
    unittest.main()
