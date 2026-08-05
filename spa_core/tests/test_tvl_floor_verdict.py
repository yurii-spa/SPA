"""The TVL floor must be able to fail.

Eleven adapters answered "does this pool clear the $5M RiskPolicy floor?" with
``self.TVL_USD >= 5_000_000``, where ``TVL_USD`` is a hardcoded class constant.
Every one of those constants exceeds the floor, so the expression could not
return False for any input. It was the literal ``True`` wearing the name of a
risk gate — and it read as a passing check in every report that showed it.

``moonwell_base`` is the worked example: ``TVL_USD = 500_000_000`` against $2.6M
actually held, a 190x overstatement, so a pool that genuinely fails the floor
reported clearing it every single day.

Fixing the verdict surfaced a second, quieter defect. ``MoonwellBaseAdapter``
spells its key ``"moonwell-base"`` while the status file writes
``moonwell_base``, so the lookup returned ``{}`` — and an empty block is
indistinguishable from "not observed". Four adapters were reading nothing at all
regardless of what the producer had written, and drawing fail-CLOSED conclusions
from a punctuation mismatch. Both directions are pinned below.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.tests._freshness import ts
from spa_core.adapters.status_reader import (
    read_live_tvl_usd,
    read_status_block,
    tvl_floor_verdict,
)

FLOOR = 5_000_000.0


class _Dir:
    """A temp data dir holding one adapter_status.json."""

    def __init__(self, adapters: dict, legacy: dict | None = None):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name)
        doc: dict = {"generated_at": ts(1), "adapters": adapters}
        if legacy:
            doc.update(legacy)
        (self.path / "adapter_status.json").write_text(json.dumps(doc), encoding="utf-8")

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        self._tmp.cleanup()


def _row(tvl: float, source: str = "live") -> dict:
    return {"tvl_usd": tvl, "tvl_source": source, "live_apy": 4.0}


class TestVerdictHasThreeOutcomes(unittest.TestCase):

    def test_observed_below_floor_is_false(self):
        """The case the old check could never produce — moonwell's real number."""
        with _Dir({"moonwell_base": _row(2_617_063.0)}) as d:
            self.assertIs(tvl_floor_verdict("moonwell_base", d, FLOOR), False)

    def test_observed_above_floor_is_true(self):
        with _Dir({"morpho_blue_base": _row(587_289_575.0)}) as d:
            self.assertIs(tvl_floor_verdict("morpho_blue_base", d, FLOOR), True)

    def test_exactly_at_the_floor_passes(self):
        with _Dir({"x": _row(FLOOR)}) as d:
            self.assertIs(tvl_floor_verdict("x", d, FLOOR), True)

    def test_unobserved_is_none_not_true(self):
        """"We did not look" must never render as "it passed".

        Reporting an unmeasured gate as passing is the entire defect being
        replaced; returning True here would reintroduce it with extra steps.
        """
        with _Dir({"x": {"tvl_usd": 900_000_000.0, "tvl_source": "static"}}) as d:
            self.assertIsNone(tvl_floor_verdict("x", d, FLOOR))

    def test_unobserved_is_none_not_false(self):
        """Nor may it render as a failure.

        The allocator already freezes unverified pools (ADR-053). Restating
        "unmeasured" as "failed" would fill the queue with items no action can
        ever clear — the mirror failure this project has paid for before.
        """
        with _Dir({}) as d:
            self.assertIsNone(tvl_floor_verdict("absent", d, FLOOR))

    def test_a_literal_can_never_pass_the_floor(self):
        """However large. This is the whole point of the change."""
        for tvl in (500_000_000.0, 12_000_000_000.0):
            with self.subTest(tvl=tvl):
                with _Dir({"x": {"tvl_usd": tvl, "tvl_source": "static"}}) as d:
                    self.assertIsNone(tvl_floor_verdict("x", d, FLOOR))

    def test_nonsense_values_are_not_observations(self):
        for bad in (0, -1, None, True, "5000000"):
            with self.subTest(tvl=bad):
                with _Dir({"x": {"tvl_usd": bad, "tvl_source": "live"}}) as d:
                    self.assertIsNone(read_live_tvl_usd("x", d))

    def test_unreadable_dir_never_raises(self):
        self.assertIsNone(tvl_floor_verdict("x", Path("/nonexistent/spa"), FLOOR))


class TestSeparatorTolerance(unittest.TestCase):
    """Positive control for the silent key mismatch."""

    def test_hyphenated_protocol_finds_the_underscore_key(self):
        """``MoonwellBaseAdapter.PROTOCOL`` is 'moonwell-base'; the file is not."""
        with _Dir({"moonwell_base": _row(2_617_063.0)}) as d:
            block = read_status_block("moonwell-base", d)
            self.assertTrue(block, "a punctuation mismatch must not read as 'not observed'")
            self.assertIs(tvl_floor_verdict("moonwell-base", d, FLOOR), False)

    def test_underscore_protocol_finds_the_hyphen_key(self):
        with _Dir({"moonwell-base": _row(587_289_575.0)}) as d:
            self.assertIs(tvl_floor_verdict("moonwell_base", d, FLOOR), True)

    def test_exact_key_still_wins(self):
        """Tolerance must not shadow an exact match with a variant."""
        with _Dir({"a_b": _row(10_000_000.0), "a-b": _row(1_000.0)}) as d:
            self.assertEqual(read_live_tvl_usd("a_b", d), 10_000_000.0)

    def test_legacy_top_level_block_still_resolves(self):
        with _Dir({}, legacy={"moonwell_base": _row(2_617_063.0)}) as d:
            self.assertIs(tvl_floor_verdict("moonwell-base", d, FLOOR), False)

    def test_an_unrelated_protocol_is_not_matched(self):
        """Tolerance is for separators only — it must not blur distinct keys."""
        with _Dir({"aave_v3": _row(9_000_000_000.0)}) as d:
            self.assertIsNone(tvl_floor_verdict("aave_v3_base", d, FLOOR))


class TestAdaptersReportTheVerdict(unittest.TestCase):
    """The adapters actually publish it — not just the helper."""

    def test_moonwell_health_check_reports_false_on_its_real_tvl(self):
        from spa_core.adapters.moonwell_base_adapter import MoonwellBaseAdapter

        with _Dir({"moonwell_base": _row(2_617_063.0)}) as d:
            verdict = MoonwellBaseAdapter(data_dir=d).health_check()["tvl_floor_ok"]
        self.assertIs(verdict, False, "the 190x literal used to make this True")

    def test_moonwell_health_check_is_none_without_an_observation(self):
        from spa_core.adapters.moonwell_base_adapter import MoonwellBaseAdapter

        with _Dir({}) as d:
            verdict = MoonwellBaseAdapter(data_dir=d).health_check()["tvl_floor_ok"]
        self.assertIsNone(verdict)


if __name__ == "__main__":
    unittest.main()
