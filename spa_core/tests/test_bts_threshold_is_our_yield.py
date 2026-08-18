"""test_bts_threshold_is_our_yield.py — the BTS alert threshold must be OUR yield.

ADR-070 п.12 (owner decision 2026-08-07, option "сначала честный порог, потом включить").
Measured before this change, on a copy of production data (2026-08-01, funding
ETH −2.18% / BTC +10.95% / SOL +5.07% annual):

  * "EXCELLENT" meant ">=100 bps net over a hardcoded 5% spot baseline" ⇒ ETH 262,
    BTC 1575, SOL 987 bps — all three EXCELLENT at once, the label carried no
    information, and the first armed run would have sent three Telegram messages;
  * each message priced the opportunity off a hardcoded $20,000 that this sleeve does
    not hold: "Annual PnL $3,150" about money that does not exist.

The order in the owner's decision is the point: arming an unvalidated threshold produces
a weekly false red, and a false red trains everyone to ignore the channel. So the hurdle
is now OUR OWN measured yield, an unmeasurable hurdle refuses everything, and no dollar
figure is published at all.

Hermetic: tmpdir, no network, no live ``data/``, and every freshness assertion passes a
fixed ``now`` with fixed timestamps — no wall clock is read at module level.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring.bts_baseline import (
    OUR_YIELD_MIN_DAYS,
    OUR_YIELD_WINDOW_DAYS,
    read_our_yield,
)
from spa_core.monitoring.bts_monitor import (
    ADAPTER_STATUS_FILENAME,
    EVIDENCE_FILENAME,
    FUNDING_FILENAME,
    OPP_FILENAME,
    STATUS_FILENAME,
    BTS_ALERTS_ARMED_ENV,
    BTSMonitor,
)
from spa_core.utils.atomic import atomic_save

# A fixed instant for the PURE reader, which takes `now` as an argument: both sides of
# the freshness comparison are pinned, so these tests cannot rot with the calendar. The
# monitor itself reads the real clock, so fixtures aimed at it are built RELATIVE to it
# (`end=None` below) — never against a literal date
# (`.claude/rules/deployment.md`, "фиксированная дата это бомба замедленного действия").
# FROZEN-DATE-OK: injected-clock — `_NOW` is passed to read_our_yield(now=...) AND used to
# build every stamp it is compared against (`_track(end=_NOW)`), so both sides move
# together and the calendar cannot reach these tests. Fixtures aimed at the monitor,
# which reads the real clock, are built relative to `datetime.now` instead.
_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def _track(days: int = 10, apy_pct=5.9, *, end: datetime | None = None):
    """Evidenced track ending at ``end`` (default: now); ``apy_pct`` scalar or list."""
    end = end or datetime.now(timezone.utc)
    values = apy_pct if isinstance(apy_pct, list) else [apy_pct] * days
    return {
        "days": [
            {
                "date": (end - timedelta(days=offset)).strftime("%Y-%m-%d"),
                "apy_pct": values[offset % len(values)],
                "equity_value": 100_000.0,
            }
            for offset in range(days)
        ]
    }


def _funding(eth=0.12, btc=0.09, sol=0.15, *, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    return {
        "timestamp": now.isoformat(),
        "fetched_at": now.timestamp(),
        "stale": False,
        "assets": {
            "ETH": {"funding_rate_annual": eth},
            "BTC": {"funding_rate_annual": btc},
            "SOL": {"funding_rate_annual": sol},
        },
    }


def _adapters(apy=5.2):
    return {"morpho_steakhouse": {"apy": apy}}


# ---------------------------------------------------------------------------
# 1. Our own yield: measured, or refused verbatim — never a literal
# ---------------------------------------------------------------------------

class TestOurYieldReader(unittest.TestCase):

    def test_median_of_the_evidenced_window_is_our_yield(self):
        read = read_our_yield(_track(10, 5.9, end=_NOW), now=_NOW)
        self.assertTrue(read.measured)
        self.assertAlmostEqual(read.apy_annual, 0.059, places=6)
        self.assertAlmostEqual(read.bps, 590.0, places=3)
        self.assertEqual(read.days_used, 10)

    def test_median_not_mean_so_one_freak_day_cannot_set_the_hurdle(self):
        values = [5.0] * 9 + [500.0]
        read = read_our_yield(_track(10, values, end=_NOW), now=_NOW)
        self.assertTrue(read.measured)
        self.assertAlmostEqual(read.bps, 500.0, places=3)

    def test_stale_track_is_refused_not_extrapolated(self):
        stale_end = _NOW - timedelta(days=5)
        read = read_our_yield(_track(10, 5.9, end=stale_end), now=_NOW)
        self.assertFalse(read.measured)
        self.assertIn("stale", read.unchecked)
        self.assertIsNone(read.apy_annual)

    def test_too_few_days_is_refused_with_the_count(self):
        read = read_our_yield(_track(OUR_YIELD_MIN_DAYS - 1, 5.9, end=_NOW), now=_NOW)
        self.assertFalse(read.measured)
        self.assertIn(f">= {OUR_YIELD_MIN_DAYS}", read.unchecked)

    def test_positive_control_exactly_the_minimum_is_enough(self):
        read = read_our_yield(_track(OUR_YIELD_MIN_DAYS, 5.9, end=_NOW), now=_NOW)
        self.assertTrue(read.measured)

    def test_missing_days_list_is_refused_and_names_the_keys(self):
        read = read_our_yield({"start_date": _NOW.strftime("%Y-%m-%d")}, now=_NOW)
        self.assertFalse(read.measured)
        self.assertIn("start_date", read.unchecked)

    def test_non_mapping_payload_is_refused(self):
        self.assertFalse(read_our_yield(["nope"], now=_NOW).measured)

    def test_unparseable_apy_days_are_ignored_and_the_shortfall_is_reported(self):
        payload = {"days": [{"date": _NOW.strftime("%Y-%m-%d"), "apy_pct": "n/a"}] * 10}
        read = read_our_yield(payload, now=_NOW)
        self.assertFalse(read.measured)
        self.assertIsNone(read.apy_annual)

    def test_days_outside_the_window_do_not_count(self):
        old = _track(10, 5.9, end=_NOW - timedelta(days=OUR_YIELD_WINDOW_DAYS + 5))
        fresh = _track(3, 6.0, end=_NOW)
        read = read_our_yield({"days": old["days"] + fresh["days"]}, now=_NOW)
        self.assertFalse(read.measured)
        self.assertEqual(read.days_used, 3)

    def test_never_raises_and_never_invents(self):
        for payload in (None, 42, {"days": "no"}, {"days": [None, 3]}):
            read = read_our_yield(payload, now=_NOW)
            self.assertFalse(read.measured)
            self.assertIsNone(read.bps)


# ---------------------------------------------------------------------------
# 2. The scan refuses instead of pricing the spot leg at a literal
# ---------------------------------------------------------------------------

class _MonitorCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sent = []
        outer = self

        class _Recording(BTSMonitor):
            def _create_alerts(inner, new_excellent, our_yield=None):  # noqa: N805
                outer.sent.extend(o.asset for o in new_excellent)
                return len(new_excellent)

        self.monitor = _Recording(data_dir=self.tmp, use_alert_dispatcher=False)
        os.environ.pop(BTS_ALERTS_ARMED_ENV, None)

    def tearDown(self):
        os.environ.pop(BTS_ALERTS_ARMED_ENV, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, *, funding=True, adapters=True, track=10, apy_pct=5.9):
        if funding:
            atomic_save(_funding(), str(self.tmp / FUNDING_FILENAME))
        if adapters:
            atomic_save(_adapters(), str(self.tmp / ADAPTER_STATUS_FILENAME))
        if track:
            atomic_save(_track(track, apy_pct), str(self.tmp / EVIDENCE_FILENAME))

    def status(self):
        return json.loads((self.tmp / STATUS_FILENAME).read_text())

    def artifact(self):
        return json.loads((self.tmp / OPP_FILENAME).read_text())


class TestSpotLegIsMeasuredOrRefused(_MonitorCase):

    def test_no_adapter_apy_refuses_instead_of_using_the_five_percent_literal(self):
        self.write(adapters=False)
        scan = self.monitor.scan_with_reasons()
        self.assertEqual(scan.opportunities, [])
        self.assertTrue(any("spot-leg yield NOT MEASURED" in u for u in scan.unchecked))

    def test_the_refusal_is_published_not_silent(self):
        self.write(adapters=False)
        report = self.monitor.run()
        self.assertEqual(report["status"], "unchecked")
        self.assertTrue(any("scan NOT PERFORMED" in u for u in report["unchecked"]))

    def test_positive_control_a_measured_spot_leg_still_produces_opportunities(self):
        self.write()
        scan = self.monitor.scan_with_reasons()
        self.assertEqual({o.asset for o in scan.opportunities}, {"ETH", "BTC", "SOL"})
        self.assertEqual(scan.unchecked, [])


# ---------------------------------------------------------------------------
# 3. No dollar figure is published anywhere
# ---------------------------------------------------------------------------

class TestNoInventedCapital(_MonitorCase):

    def test_opportunities_carry_no_dollar_claim(self):
        self.write()
        self.monitor.run()
        for opp in self.artifact()["opportunities"]:
            self.assertIsNone(opp["annual_pnl_usd"])
            self.assertIsNone(opp["capital_usd"])
            self.assertIn("no capital is allocated", opp["pnl_unchecked"])

    def test_the_artifact_says_why_there_is_no_number(self):
        self.write()
        self.monitor.run()
        capital = self.artifact()["capital"]
        self.assertIsNone(capital["allocated_usd"])
        self.assertIn("$20,000", capital["unchecked"])

    def test_no_twenty_thousand_survives_anywhere_in_the_artifact(self):
        self.write()
        self.monitor.run()
        blob = json.dumps(self.artifact()["opportunities"])
        self.assertNotIn("20000", blob)


# ---------------------------------------------------------------------------
# 4. The alert hurdle is our own yield — and an unmeasured hurdle refuses
# ---------------------------------------------------------------------------

class TestAlertGateUsesOurYield(_MonitorCase):

    def test_excess_over_our_yield_is_published_per_opportunity(self):
        self.write(apy_pct=5.9)
        self.monitor.run()
        by_asset = {o["asset"]: o for o in self.artifact()["opportunities"]}
        # SOL: (0.052 + 0.15) * 10000 - 20 = 2000 bps net, hurdle 590 bps.
        self.assertAlmostEqual(by_asset["SOL"]["net_spread_bps"], 2000.0, places=1)
        self.assertAlmostEqual(by_asset["SOL"]["excess_vs_our_yield_bps"], 1410.0, places=1)

    def test_an_opportunity_below_our_own_yield_is_not_alert_worthy(self):
        # Hurdle 25% annual = 2500 bps; nothing in the fixture beats it.
        self.write(apy_pct=25.0)
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        report = self.monitor.run()
        self.assertGreater(report["new_excellent"], 0)
        self.assertEqual(report["alert_worthy"], 0)
        self.assertEqual(self.sent, [])
        blob = json.dumps(report["suppressed_alerts"])
        self.assertIn("does not beat our own measured yield", blob)

    def test_positive_control_armed_and_above_the_hurdle_really_sends(self):
        self.write(apy_pct=5.9)
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        report = self.monitor.run()
        self.assertEqual(set(self.sent), {"ETH", "BTC", "SOL"})
        self.assertEqual(report["alert_worthy"], 3)

    def test_unmeasurable_hurdle_refuses_every_alert(self):
        self.write(track=0)  # no evidenced track at all
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        report = self.monitor.run()
        self.assertGreater(report["new_excellent"], 0)
        self.assertEqual(self.sent, [])
        blob = json.dumps(report["suppressed_alerts"])
        self.assertIn("our own yield NOT MEASURED", blob)

    def test_a_stale_track_is_an_unmeasurable_hurdle(self):
        atomic_save(_funding(), str(self.tmp / FUNDING_FILENAME))
        atomic_save(_adapters(), str(self.tmp / ADAPTER_STATUS_FILENAME))
        atomic_save(
            _track(10, 5.9, end=datetime.now(timezone.utc) - timedelta(days=9)),
            str(self.tmp / EVIDENCE_FILENAME),
        )
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        self.monitor.run()
        self.assertEqual(self.sent, [])

    def test_refusing_the_hurdle_does_not_masquerade_as_a_failed_scan(self):
        # positive control — the spread WAS measured; only the alert is impossible.
        self.write(track=0)
        report = self.monitor.run()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["unchecked"], [])

    def test_status_file_publishes_the_hurdle_and_the_arming_state(self):
        self.write(apy_pct=5.9)
        self.monitor.run()
        gate = self.status()["alert_gate"]
        self.assertTrue(gate["hurdle"]["measured"])
        self.assertAlmostEqual(gate["hurdle"]["bps"], 590.0, places=1)
        self.assertFalse(gate["armed"])
        self.assertEqual(gate["alert_worthy"], 3)

    def test_status_file_publishes_the_refusal_when_the_hurdle_is_unknown(self):
        self.write(track=0)
        self.monitor.run()
        gate = self.status()["alert_gate"]
        self.assertFalse(gate["hurdle"]["measured"])
        self.assertTrue(gate["hurdle"]["unchecked"])

    # ── "not measured" must not be published as a reassuring zero ────────────
    # Three-way control: an insufficient spread is caught, a sufficient one passes
    # silently, and an unmeasurable hurdle reads as "not measured" — never as 0.

    def test_unmeasured_hurdle_publishes_no_count_and_says_why(self):
        self.write(track=0)
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        report = self.monitor.run()
        self.assertIsNone(report["alert_worthy"])
        gate = self.status()["alert_gate"]
        self.assertIsNone(gate["alert_worthy"])
        # The reason is the hurdle's own refusal, verbatim — not a re-worded summary.
        self.assertTrue(gate["alert_worthy_unchecked"])
        self.assertEqual(gate["alert_worthy_unchecked"], gate["hurdle"]["unchecked"])
        summary = self.artifact()["summary"]
        self.assertIsNone(summary["alert_worthy_count"])
        self.assertTrue(summary["alert_worthy_unchecked"])

    def test_positive_control_measured_hurdle_publishes_a_real_zero(self):
        # Hurdle 25% annual: measured, and nothing in the fixture beats it. THIS zero is
        # a statement, and it must stay distinguishable from the null above.
        self.write(apy_pct=25.0)
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        report = self.monitor.run()
        self.assertEqual(report["alert_worthy"], 0)
        gate = self.status()["alert_gate"]
        self.assertEqual(gate["alert_worthy"], 0)
        self.assertIsNone(gate["alert_worthy_unchecked"])
        self.assertEqual(self.artifact()["summary"]["alert_worthy_count"], 0)
        self.assertIsNone(self.artifact()["summary"]["alert_worthy_unchecked"])

    def test_positive_control_measured_hurdle_beaten_counts_and_stays_silent(self):
        self.write(apy_pct=5.9)
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        report = self.monitor.run()
        self.assertEqual(report["alert_worthy"], 3)
        self.assertEqual(self.artifact()["summary"]["alert_worthy_count"], 3)
        self.assertIsNone(self.artifact()["summary"]["alert_worthy_unchecked"])
        self.assertEqual(report["suppressed_alerts"], [])

    def test_disarmed_transport_still_says_so_verbatim(self):
        self.write(apy_pct=5.9)
        report = self.monitor.run()
        blob = json.dumps(report["suppressed_alerts"])
        self.assertIn("NOT sent to Telegram", blob)
        self.assertIn(BTS_ALERTS_ARMED_ENV, blob)
        self.assertEqual(self.sent, [])


# ---------------------------------------------------------------------------
# 5. The owner-facing message itself
# ---------------------------------------------------------------------------

class TestAlertMessageContent(_MonitorCase):

    def _message(self):
        captured = []

        class _Dispatcher:
            def create_alert(self, level, title, message):
                captured.append((title, message))
                return object()

            def dispatch(self, alert):
                return True

        monitor = BTSMonitor(data_dir=self.tmp, use_alert_dispatcher=True)
        monitor._dispatcher = _Dispatcher()
        self.write(apy_pct=5.9)
        os.environ[BTS_ALERTS_ARMED_ENV] = "1"
        monitor.run()
        return captured

    def test_message_names_the_hurdle_and_the_excess(self):
        captured = self._message()
        self.assertTrue(captured)
        _, msg = captured[0]
        self.assertIn("Our own yield (hurdle): 590 bps", msg)
        self.assertIn("Excess over our own yield:", msg)

    def test_message_carries_no_dollar_figure(self):
        for _, msg in self._message():
            self.assertNotIn("Annual PnL: $", msg)
            self.assertIn("no capital is allocated", msg)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
