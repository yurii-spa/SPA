"""GSM pause delay: the gate must open on an observation and shut by itself.

Why this file exists. ``sky_monitor`` ran on schedule, exited 0, and wrote
``gsm_hours: null`` on every single run — for long enough that two protocols
were locked out permanently and it looked like policy rather than breakage.
Nothing alerted, because every part was individually honest: the agent
succeeded, the file was fresh, and the field was truthfully null. The cause was
that all three public RPC endpoints had stopped serving anonymous requests
(measured 2026-08-05: 403, internal error, "Unauthorized"), and a fetcher that
returns None is indistinguishable from a governance parameter that is genuinely
absent.

So these tests pin the producer AND the consumer, in both directions. A suite
that only checks "48h opens the gate" would pass the version that never
produces 48h; a suite that only checks "missing shuts the gate" would pass the
version that is permanently shut. Both failure modes were real here.

Network is never touched: the fetcher takes its endpoint list as an argument and
``_eth_call`` is replaced with a deterministic fake.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.adapters.status_reader import GSM_MAX_AGE_H, gsm_confirmed
from spa_core.data_pipeline import sky_monitor as SM
from spa_core.monitoring import adapter_status_generator as gen
from spa_core.tests._freshness import now_utc, ts

# 48h in seconds, as DSPause.delay() returns it.
_HEX_48H = hex(172_800)
_HEX_24H = hex(86_400)


class TestOnchainQuorum(unittest.TestCase):
    """The delay decides whether capital may enter — one witness is not enough."""

    def _fake_call(self, mapping: dict):
        def _call(_to, _data, rpc_url, timeout=5):
            return mapping.get(rpc_url)
        return _call

    def test_quorum_of_agreeing_endpoints_is_observed(self):
        eps = ["rpc-a", "rpc-b", "rpc-c"]
        with mock.patch.object(SM, "_eth_call",
                               self._fake_call({"rpc-a": _HEX_48H, "rpc-b": _HEX_48H})):
            hours, witnesses = SM._fetch_gsm_delay_onchain(endpoints=eps)
        self.assertEqual(hours, 48.0)
        self.assertEqual(sorted(witnesses), ["rpc-a", "rpc-b"])

    def test_single_endpoint_is_not_enough(self):
        """One answer is a single point of trust, not an observation."""
        with mock.patch.object(SM, "_eth_call", self._fake_call({"rpc-a": _HEX_48H})):
            hours, witnesses = SM._fetch_gsm_delay_onchain(endpoints=["rpc-a", "rpc-b"])
        self.assertIsNone(hours)
        self.assertEqual(witnesses, [])

    def test_disagreement_is_refused_not_majority_ruled(self):
        """Two witnesses, two different safety parameters — we do not pick.

        Majority rule would let two coordinated (or simply stale) endpoints
        outvote a correct one on a number that gates capital.
        """
        with mock.patch.object(SM, "_eth_call", self._fake_call(
                {"rpc-a": _HEX_48H, "rpc-b": _HEX_48H, "rpc-c": _HEX_24H})):
            hours, witnesses = SM._fetch_gsm_delay_onchain(
                endpoints=["rpc-a", "rpc-b", "rpc-c"])
        self.assertIsNone(hours, "disagreement must refuse, even with a 2:1 majority")
        self.assertEqual(witnesses, [])

    def test_all_endpoints_dead_refuses(self):
        """The exact production failure: every endpoint stopped answering."""
        with mock.patch.object(SM, "_eth_call", self._fake_call({})):
            hours, _ = SM._fetch_gsm_delay_onchain(endpoints=["rpc-a", "rpc-b"])
        self.assertIsNone(hours)

    def test_nonsense_values_are_ignored(self):
        for bad in ("0x0", "not-hex", "", None):
            with self.subTest(value=bad):
                with mock.patch.object(SM, "_eth_call",
                                       self._fake_call({"rpc-a": bad, "rpc-b": bad})):
                    hours, _ = SM._fetch_gsm_delay_onchain(endpoints=["rpc-a", "rpc-b"])
                self.assertIsNone(hours)


class TestGsmConfirmed(unittest.TestCase):
    """The consumer side: value AND age, both fail-CLOSED."""

    def test_fresh_value_at_threshold_confirms(self):
        block = {"gsm_hours": 48.0, "gsm_hours_as_of": ts(1)}
        self.assertTrue(gsm_confirmed(block, 48.0))

    def test_value_below_threshold_refuses(self):
        block = {"gsm_hours": 47.9, "gsm_hours_as_of": ts(1)}
        self.assertFalse(gsm_confirmed(block, 48.0))

    def test_stale_value_shuts_the_gate_by_itself(self):
        """A producer that dies must not leave the door open on an old reading.

        This is the ``riskwire`` class: data served as current while nothing had
        refreshed it for 840 hours.
        """
        block = {"gsm_hours": 48.0, "gsm_hours_as_of": ts(GSM_MAX_AGE_H + 1)}
        self.assertFalse(gsm_confirmed(block, 48.0))

    def test_value_inside_the_window_still_confirms(self):
        """Pins the window from both sides — "always refuse" must not pass."""
        block = {"gsm_hours": 48.0, "gsm_hours_as_of": ts(GSM_MAX_AGE_H - 1)}
        self.assertTrue(gsm_confirmed(block, 48.0))

    def test_missing_or_undateable_stamp_refuses(self):
        for stamp in (None, "", "not-a-date"):
            with self.subTest(stamp=stamp):
                self.assertFalse(gsm_confirmed({"gsm_hours": 48.0, "gsm_hours_as_of": stamp}, 48.0))

    def test_missing_field_refuses_and_is_never_defaulted(self):
        self.assertFalse(gsm_confirmed({}, 48.0))
        self.assertFalse(gsm_confirmed({"gsm_hours": None, "gsm_hours_as_of": ts(1)}, 48.0))
        self.assertFalse(gsm_confirmed({"gsm_hours": True, "gsm_hours_as_of": ts(1)}, 48.0))

    def test_clock_is_an_input(self):
        block = {"gsm_hours": 48.0, "gsm_hours_as_of": ts(1)}
        future = now_utc() + timedelta(hours=GSM_MAX_AGE_H + 5)
        self.assertFalse(gsm_confirmed(block, 48.0, now=future))


class TestMergeIntoStatus(unittest.TestCase):
    """Only Sky's own protocol inherits Sky's number."""

    def _merge(self, sky_doc: dict | None) -> dict:
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            if sky_doc is not None:
                (d / "sky_status.json").write_text(json.dumps(sky_doc), encoding="utf-8")
            adapters = {"spark_susds": {}, "fluid_fusdc": {}, "maple": {}}
            gen._merge_gsm_hours(adapters, d)
            return adapters

    def test_observed_delay_reaches_spark(self):
        rows = self._merge({"gsm_hours": 48.0, "source": "onchain",
                            "last_checked": ts(1), "witnesses": ["a", "b"]})
        self.assertEqual(rows["spark_susds"]["gsm_hours"], 48.0)
        self.assertEqual(rows["spark_susds"]["gsm_source"], "onchain")

    def test_fluid_does_not_inherit_another_protocols_parameter(self):
        """Fluid has its own governance. Maker's delay is not evidence about it.

        Writing 48h here would be indistinguishable, downstream, from having
        actually read Fluid's timelock — the precise substitution the evidence
        gate exists to prevent.
        """
        rows = self._merge({"gsm_hours": 48.0, "source": "onchain", "last_checked": ts(1)})
        self.assertNotIn("gsm_hours", rows["fluid_fusdc"])
        self.assertNotIn("gsm_hours", rows["maple"])

    def test_manual_source_never_reaches_a_gate(self):
        """"manual" is the module's hardcoded constant, not an observation."""
        rows = self._merge({"gsm_hours": 48.0, "source": "manual", "last_checked": ts(1)})
        self.assertNotIn("gsm_hours", rows["spark_susds"])

    def test_null_and_missing_file_leave_the_field_absent(self):
        self.assertNotIn("gsm_hours", self._merge(None)["spark_susds"])
        self.assertNotIn("gsm_hours", self._merge(
            {"gsm_hours": None, "source": "onchain", "last_checked": ts(1)})["spark_susds"])


class TestEndToEnd(unittest.TestCase):
    """Producer → status file → adapter gate, with no network."""

    def test_observation_opens_the_gate_and_absence_shuts_it(self):
        from spa_core.adapters.spark_susds_adapter import SparkSusdsAdapter

        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            rows = {"spark_susds": {"live_apy": 5.5}}

            # 1. No observation → shut.
            (d / "adapter_status.json").write_text(
                json.dumps({"generated_at": ts(1), "adapters": rows}), encoding="utf-8")
            self.assertFalse(SparkSusdsAdapter(data_dir=d).is_gsm_compliant())

            # 2. Observation merged in → open.
            (d / "sky_status.json").write_text(json.dumps(
                {"gsm_hours": 48.0, "source": "onchain", "last_checked": ts(1)}),
                encoding="utf-8")
            gen._merge_gsm_hours(rows, d)
            (d / "adapter_status.json").write_text(
                json.dumps({"generated_at": ts(1), "adapters": rows}), encoding="utf-8")
            self.assertTrue(SparkSusdsAdapter(data_dir=d).is_gsm_compliant())

            # 3. The same observation, gone stale → shut again, by itself.
            rows["spark_susds"]["gsm_hours_as_of"] = ts(GSM_MAX_AGE_H + 1)
            (d / "adapter_status.json").write_text(
                json.dumps({"generated_at": ts(1), "adapters": rows}), encoding="utf-8")
            self.assertFalse(SparkSusdsAdapter(data_dir=d).is_gsm_compliant())


if __name__ == "__main__":
    unittest.main()
