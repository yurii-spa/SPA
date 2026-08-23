"""The "live" TVL label must travel WITH the measured number, not instead of it.

Owner decision 2026-08-23 (card ``owner-decision-dva-tvoih-resheniya-ot-18-08-ne-ispolnen``,
option 1; recorded as ADR-126). The finding it closes:

``_load_adapters`` has two merge paths that both upgrade a literal TVL to an
observation. The registry path wrote the observation into the row. The
orchestrator-snapshot path bound it to a local nothing read::

    if tvl_source != "live" and protocol in tvl_evidence:
        tvl, _pool = tvl_evidence[protocol]     # measured — and dropped here
        tvl_source = "live"
    _row = {..., "tvl_usd": float(a.get("tvl_usd", 0.0)),   # the literal
                 "tvl_source": tvl_source}                  # says "live"

So the row went out stamped ``live`` while carrying the very constant the
observation had been fetched to replace — the one thing
``.claude/rules/risk-engine.md`` forbids by name ("Never stamp `live` on a
constant"). ``moonwell_base`` is the worked example: ``TVL_USD = 500_000_000``
against $2.6M observed, i.e. a pool that fails the $5M floor presented as
clearing it by 100x, with ``tvl_source="live"`` vouching for the number.

RiskPolicy's own gate (``_filter_by_tvl``) is not the only reader that was
misled: ``tvl_used`` / ``tvl_sources`` feed the allocation choice, the data-honesty
report and the dashboard.

**Why these tests need the pytest guard lifted.** ``_load_adapters`` reads TVL
evidence only when ``PYTEST_CURRENT_TEST`` is absent — so that a test can never
rank on the live repo's ``data/``. That guard also makes the defective branch
unreachable from any ordinary test, which is exactly why the defect survived:
the code path with the bug had, by construction, no way to be exercised. Here
the guard is lifted deliberately AND the file read is replaced by a fixture, so
the branch runs while the live tree is still never touched.

Both directions are pinned. A test that only asserted "the measured number wins"
would stay green under a producer that overwrites every TVL with whatever it last
saw; the reverse control pins that without evidence the literal stays, labelled
``static``.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.tests._freshness import ts
from spa_core.allocator import allocator as alloc_mod
from spa_core.allocator.allocator import StrategyAllocator

# A pool the adapter overstates by two orders of magnitude — the worked example.
_PROTOCOL = "moonwell_base"
_LITERAL_TVL = 500_000_000.0
_MEASURED_TVL = 2_600_000.0
_POOL_ID = "1643c124-f047-4fc5-9642-d6fa91875184"


class _Fixture:
    """A one-protocol orchestrator snapshot plus an empty registry.

    The registry is emptied on purpose: this file is about the snapshot path,
    and a live registry would merge protocols whose numbers the assertions
    below would then have to know about.
    """

    def __init__(self, tmp: str, *, declared_tvl_source: str | None = None):
        self.dir = Path(tmp)
        row = {
            "protocol": _PROTOCOL,
            "status": "ok",
            "apy_pct": 5.73,
            "tvl_usd": _LITERAL_TVL,
            "tier": "T2",
            "last_updated": ts(hours_ago=1),
        }
        if declared_tvl_source is not None:
            row["tvl_source"] = declared_tvl_source
        self.status_path = self.dir / "adapter_orchestrator_status.json"
        self.status_path.write_text(json.dumps({"adapters": [row]}), encoding="utf-8")
        self.registry_path = self.dir / "adapter_registry.json"
        self.registry_path.write_text(json.dumps({"adapters": {}}), encoding="utf-8")

    def allocator(self) -> StrategyAllocator:
        return StrategyAllocator(
            status_path=self.status_path,
            registry_path=self.registry_path,
            # Injected provider doubles as the APY evidence map (see
            # ``_load_adapters``) — keeps the run offline and makes the
            # protocol fundable without touching the live feed.
            live_apy_provider={_PROTOCOL: 0.0573},
            strategy_loop_enabled=False,
        )


def _load_with_tvl_evidence(fx: _Fixture, evidence: dict[str, tuple[float, str]]):
    """Run ``_load_adapters`` with ``evidence`` standing in for the file read.

    Lifts ``PYTEST_CURRENT_TEST`` for the duration (see the module docstring)
    while patching the loader, so the branch executes and the live ``data/``
    tree is still never opened.
    """
    saved = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        with mock.patch.object(
            alloc_mod, "_load_evidenced_tvl", return_value=dict(evidence)
        ) as patched:
            a = fx.allocator()
            rows = a._load_adapters()
        assert patched.called, "the evidence loader was never reached — guard still on"
        return a, rows
    finally:
        if saved is not None:
            os.environ["PYTEST_CURRENT_TEST"] = saved


class TestSnapshotPathCarriesTheMeasuredNumber(unittest.TestCase):
    def test_the_numbers_differ_so_the_test_cannot_pass_by_coincidence(self):
        """Guard on the fixture itself, not on the code under test."""
        self.assertNotAlmostEqual(_LITERAL_TVL, _MEASURED_TVL, delta=1.0)

    def test_observation_replaces_the_literal_in_the_row(self):
        with TemporaryDirectory() as tmp:
            fx = _Fixture(tmp)
            a, rows = _load_with_tvl_evidence(
                fx, {_PROTOCOL: (_MEASURED_TVL, _POOL_ID)}
            )
            row = next(r for r in rows if r["protocol"] == _PROTOCOL)
            self.assertEqual(row["tvl_source"], "live")
            self.assertAlmostEqual(row["tvl_usd"], _MEASURED_TVL, delta=1.0)
            self.assertNotAlmostEqual(row["tvl_usd"], _LITERAL_TVL, delta=1.0)

    def test_the_number_the_floor_is_applied_to_is_the_measured_one(self):
        """``_tvl_used`` is what ``_filter_by_tvl`` and the reports read.

        The row and the provenance map are populated by different statements;
        a fix that only corrected the row would leave the gate on the literal.
        """
        with TemporaryDirectory() as tmp:
            fx = _Fixture(tmp)
            a, _rows = _load_with_tvl_evidence(
                fx, {_PROTOCOL: (_MEASURED_TVL, _POOL_ID)}
            )
            self.assertEqual(a._tvl_sources[_PROTOCOL], "live")
            self.assertAlmostEqual(a._tvl_used[_PROTOCOL], _MEASURED_TVL, delta=1.0)

    def test_a_sub_floor_observation_is_visible_as_sub_floor(self):
        """The consequence, stated in the units the gate uses.

        $2.6M observed is below the $5M floor; the literal it replaced was 100x
        above it. Before the fix this pool cleared the floor while claiming a
        live source for the claim.
        """
        with TemporaryDirectory() as tmp:
            fx = _Fixture(tmp)
            a, _rows = _load_with_tvl_evidence(
                fx, {_PROTOCOL: (_MEASURED_TVL, _POOL_ID)}
            )
            self.assertLess(a._tvl_used[_PROTOCOL], 5_000_000.0)


class TestReverseControls(unittest.TestCase):
    """Without evidence nothing may be upgraded — the other direction."""

    def test_no_observation_keeps_the_literal_and_says_static(self):
        with TemporaryDirectory() as tmp:
            fx = _Fixture(tmp)
            a, rows = _load_with_tvl_evidence(fx, {})
            row = next(r for r in rows if r["protocol"] == _PROTOCOL)
            self.assertEqual(row["tvl_source"], "static")
            self.assertAlmostEqual(row["tvl_usd"], _LITERAL_TVL, delta=1.0)
            self.assertAlmostEqual(a._tvl_used[_PROTOCOL], _LITERAL_TVL, delta=1.0)

    def test_snapshot_that_declares_live_keeps_its_own_number(self):
        """A row the orchestrator already declared live is not second-guessed.

        The upgrade branch is guarded by ``tvl_source != "live"``; a fix that
        dropped that guard would let a stale pinned observation overwrite a
        fresher declared reading.
        """
        with TemporaryDirectory() as tmp:
            fx = _Fixture(tmp, declared_tvl_source="live")
            a, rows = _load_with_tvl_evidence(
                fx, {_PROTOCOL: (_MEASURED_TVL, _POOL_ID)}
            )
            row = next(r for r in rows if r["protocol"] == _PROTOCOL)
            self.assertEqual(row["tvl_source"], "live")
            self.assertAlmostEqual(row["tvl_usd"], _LITERAL_TVL, delta=1.0)


class TestBothMergePathsAgree(unittest.TestCase):
    """The registry path was already correct — pin that they now match.

    The defect existed because one of two sibling paths was written correctly
    and the other was not, with nothing comparing them. This test is that
    comparison: same protocol, same observation, one arriving via the snapshot
    and one via the registry, must produce the same ``(tvl_usd, tvl_source)``.
    """

    def _registry_only(self, tmp: str):
        d = Path(tmp)
        status = d / "adapter_orchestrator_status.json"
        status.write_text(json.dumps({"adapters": []}), encoding="utf-8")
        registry = d / "adapter_registry.json"
        registry.write_text(
            json.dumps(
                {
                    "adapters": {
                        _PROTOCOL: {
                            "status": "active",
                            "tier": 2,
                            "fallback_apy": 0.0573,
                            "fallback_tvl_usd": _LITERAL_TVL,
                            "updated": ts(hours_ago=1),
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return StrategyAllocator(
            status_path=status,
            registry_path=registry,
            live_apy_provider={_PROTOCOL: 0.0573},
            strategy_loop_enabled=False,
        )

    def test_same_observation_same_row_from_either_path(self):
        with TemporaryDirectory() as tmp_a, TemporaryDirectory() as tmp_b:
            fx = _Fixture(tmp_a)
            _a, snapshot_rows = _load_with_tvl_evidence(
                fx, {_PROTOCOL: (_MEASURED_TVL, _POOL_ID)}
            )
            snap = next(r for r in snapshot_rows if r["protocol"] == _PROTOCOL)

            saved = os.environ.pop("PYTEST_CURRENT_TEST", None)
            try:
                with mock.patch.object(
                    alloc_mod,
                    "_load_evidenced_tvl",
                    return_value={_PROTOCOL: (_MEASURED_TVL, _POOL_ID)},
                ):
                    reg_rows = self._registry_only(tmp_b)._load_adapters()
            finally:
                if saved is not None:
                    os.environ["PYTEST_CURRENT_TEST"] = saved
            reg = next(r for r in reg_rows if r["protocol"] == _PROTOCOL)

            self.assertEqual(snap["tvl_source"], reg["tvl_source"])
            self.assertAlmostEqual(snap["tvl_usd"], reg["tvl_usd"], delta=1.0)


if __name__ == "__main__":
    unittest.main()
