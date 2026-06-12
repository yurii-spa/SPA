#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.exit_liquidity (SPA-V431 / MP-114).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir. Covers:
protocol normalization, the static map vs the adapter constants, weight/cash
computation, ladder buckets, exitable-within windows, weighted-mean latency,
policy verdict boundaries (reuse-by-import proof), kill-switch reuse,
missing/broken input, idempotent persistence + history rotation, the CLI
(direct + subprocess), and import hygiene via the real AST linter.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading import exit_liquidity as el
from spa_core.adapters.exit_latency_policy import (
    classify_exit_latency,
    check_exit_latency_policy,
    kill_switch_exit_order,
    ILLIQUID_THRESHOLD_HOURS,
    MAX_ILLIQUID_SHARE,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_positions(data_dir: Path, doc) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / el.POSITIONS_FILENAME
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="exit_liq_test_")
        self.data_dir = Path(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


# ─── Protocol normalization ──────────────────────────────────────────────────


class TestNormalization(unittest.TestCase):
    def test_basic_variants(self):
        for raw in ("aave_v3", "Aave V3", "aave-v3", "AAVE_V3", " aave  v3 ",
                    "Aave.V3", "aave--v3"):
            self.assertEqual(el.normalize_protocol(raw), "aave_v3", raw)

    def test_compound_variants(self):
        self.assertEqual(el.normalize_protocol("Compound V3"), "compound_v3")
        self.assertEqual(el.normalize_protocol("compound-v3"), "compound_v3")

    def test_l2_variants(self):
        self.assertEqual(el.normalize_protocol("aave_v3_arbitrum"), "aave_v3_arbitrum")
        self.assertEqual(el.normalize_protocol("Aave V3 Arbitrum"), "aave_v3_arbitrum")
        self.assertEqual(el.normalize_protocol("morpho-blue-base"), "morpho_blue_base")

    def test_strips_underscores(self):
        self.assertEqual(el.normalize_protocol("__maple__"), "maple")
        self.assertEqual(el.normalize_protocol("!!!"), "")

    def test_numbers_preserved(self):
        self.assertEqual(el.normalize_protocol("euler v2"), "euler_v2")
        self.assertEqual(el.normalize_protocol("yearn_v3"), "yearn_v3")

    def test_non_string(self):
        self.assertEqual(el.normalize_protocol(123), "123")


# ─── Static map matches the adapter constants ────────────────────────────────


class TestStaticMapMatchesAdapters(unittest.TestCase):
    def _adapter_const(self, module_rel, attr="EXIT_LATENCY_HOURS"):
        """Read EXIT_LATENCY_HOURS textually from the adapter source (no network)."""
        src = (_REPO_ROOT / module_rel).read_text(encoding="utf-8")
        # find the LAST class-level assignment of EXIT_LATENCY_HOURS = <num>
        import re
        vals = re.findall(rf"{attr}\s*[:=]\s*(?:float\s*=\s*)?([0-9]+\.?[0-9]*)", src)
        self.assertTrue(vals, f"no {attr} in {module_rel}")
        return float(vals[-1])

    def test_aave_v3(self):
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["aave_v3"],
                         self._adapter_const("spa_core/adapters/aave_v3.py"))

    def test_compound_v3(self):
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["compound_v3"],
                         self._adapter_const("spa_core/adapters/compound_v3.py"))

    def test_euler_v2(self):
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["euler_v2"],
                         self._adapter_const("spa_core/adapters/euler_v2.py"))

    def test_morpho_blue(self):
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["morpho_blue"],
                         self._adapter_const("spa_core/adapters/morpho_blue.py"))

    def test_yearn_v3(self):
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["yearn_v3"],
                         self._adapter_const("spa_core/adapters/yearn_v3.py"))
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["yearn_v3"], 1.0)

    def test_maple(self):
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["maple"],
                         self._adapter_const("spa_core/adapters/maple.py"))
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["maple"], 336.0)

    def test_l2_all_instant(self):
        for slug in ("aave_v3_arbitrum", "aave_v3_base",
                     "compound_v3_base", "morpho_blue_base"):
            self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS[slug], 0.0, slug)

    def test_known_values(self):
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["aave_v3"], 0.0)
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["compound_v3"], 0.0)
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["euler_v2"], 0.0)
        self.assertEqual(el.PROTOCOL_EXIT_LATENCY_HOURS["morpho_blue"], 0.0)

    def test_latency_for_protocol_normalizes(self):
        self.assertEqual(el.latency_for_protocol("Aave V3"), 0.0)
        self.assertEqual(el.latency_for_protocol("Maple"), 336.0)

    def test_unknown_protocol_none(self):
        self.assertIsNone(el.latency_for_protocol("sky_susds"))
        self.assertIsNone(el.latency_for_protocol("totally_unknown"))


# ─── Weight computation incl. cash ───────────────────────────────────────────


class TestWeights(_TmpBase):
    def test_weights_over_capital(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0,
            "cash_usd": 0.0,
            "is_demo": False,
            "positions": {"aave_v3": 50000.0, "compound_v3": 50000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["breakdown"]["aave_v3"]["weight"], 0.5)
        self.assertAlmostEqual(r["breakdown"]["compound_v3"]["weight"], 0.5)
        self.assertEqual(r["aum_usd"], 100000.0)

    def test_cash_synthetic_position(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0,
            "cash_usd": 20000.0,
            "is_demo": False,
            "positions": {"aave_v3": 80000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertIn(el.CASH_KEY, r["breakdown"])
        self.assertAlmostEqual(r["breakdown"][el.CASH_KEY]["weight"], 0.2)
        self.assertEqual(r["breakdown"][el.CASH_KEY]["exit_latency_hours"], 0.0)
        self.assertEqual(r["breakdown"][el.CASH_KEY]["bucket"], "instant")
        self.assertAlmostEqual(r["cash_share"], 0.2)
        self.assertEqual(r["cash_usd"], 20000.0)

    def test_cash_weights_over_full_aum(self):
        # 80k aave + 20k cash on 100k capital → illiquid honest over full AUM.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 20000.0,
            "positions": {"maple": 80000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        # maple illiquid share = 0.8 of full AUM (NOT of deployed only)
        self.assertAlmostEqual(r["policy"]["illiquid_share"], 0.8)

    def test_zero_cash_no_synthetic(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertNotIn(el.CASH_KEY, r["breakdown"])

    def test_fallback_denominator(self):
        # capital_usd missing → sum(positions)+cash
        _write_positions(self.data_dir, {
            "cash_usd": 1000.0,
            "positions": {"aave_v3": 3000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["aum_usd"], 4000.0)
        self.assertTrue(any("fallback" in n for n in r["notes"]))

    def test_fallback_when_capital_zero(self):
        _write_positions(self.data_dir, {
            "capital_usd": 0.0, "cash_usd": 500.0,
            "positions": {"aave_v3": 500.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["aum_usd"], 1000.0)

    def test_zero_aum_honest_empty(self):
        _write_positions(self.data_dir, {
            "capital_usd": 0.0, "cash_usd": 0.0, "positions": {},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["aum_usd"], 0.0)
        self.assertIsNone(r["weighted_mean_exit_latency_hours"])
        self.assertEqual(r["breakdown"], {})
        self.assertTrue(any("empty" in n.lower() for n in r["notes"]))

    def test_negative_position_skipped(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0, "maple": -5.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertNotIn("maple", r["breakdown"])
        self.assertTrue(any("negative" in n for n in r["notes"]))

    def test_nonnumeric_position_skipped(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0, "maple": "oops"},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertNotIn("maple", r["breakdown"])

    def test_negative_cash_treated_zero(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": -100.0,
            "positions": {"aave_v3": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["cash_usd"], 0.0)

    def test_protocol_name_normalized_in_input(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"Aave V3": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertIn("aave_v3", r["breakdown"])


# ─── Classification + ladder aggregation (hand-computed) ─────────────────────


class TestLadder(_TmpBase):
    def test_buckets_aggregate(self):
        # aave(instant) 40k, yearn(liquid,1h) 30k, maple(illiquid,336h) 20k,
        # unknown 10k, on 100k capital, no cash.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {
                "aave_v3": 40000.0, "yearn_v3": 30000.0,
                "maple": 20000.0, "sky_susds": 10000.0,
            },
        })
        r = el.build_exit_liquidity(self.data_dir)
        lad = r["ladder"]
        self.assertEqual(lad["instant"]["usd"], 40000.0)
        self.assertAlmostEqual(lad["instant"]["share"], 0.4)
        self.assertEqual(lad["liquid"]["usd"], 30000.0)
        self.assertAlmostEqual(lad["liquid"]["share"], 0.3)
        self.assertEqual(lad["illiquid"]["usd"], 20000.0)
        self.assertAlmostEqual(lad["illiquid"]["share"], 0.2)
        self.assertEqual(lad["unknown"]["usd"], 10000.0)
        self.assertAlmostEqual(lad["unknown"]["share"], 0.1)

    def test_buckets_match_classify(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 25000.0, "yearn_v3": 25000.0,
                          "maple": 25000.0, "sky_susds": 25000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["breakdown"]["aave_v3"]["bucket"],
                         classify_exit_latency(0.0))
        self.assertEqual(r["breakdown"]["yearn_v3"]["bucket"],
                         classify_exit_latency(1.0))
        self.assertEqual(r["breakdown"]["maple"]["bucket"],
                         classify_exit_latency(336.0))
        self.assertEqual(r["breakdown"]["sky_susds"]["bucket"],
                         classify_exit_latency(None))

    def test_ladder_shares_sum_to_one(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 10000.0,
            "positions": {"aave_v3": 50000.0, "maple": 40000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        total = sum(b["share"] for b in r["ladder"].values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_ladder_usd_sum_equals_aum_when_full(self):
        _write_positions(self.data_dir, {
            "capital_usd": 90000.0, "cash_usd": 10000.0,
            "positions": {"aave_v3": 50000.0, "maple": 30000.0},
        })
        # capital 90k but deployed+cash = 90k; sum buckets usd == 90k
        r = el.build_exit_liquidity(self.data_dir)
        total = sum(b["usd"] for b in r["ladder"].values())
        self.assertAlmostEqual(total, 90000.0)


# ─── exitable_within boundaries ──────────────────────────────────────────────


class TestExitableWithin(_TmpBase):
    def _build(self, latency_map):
        # latency_map: slug -> usd; we use sky_susds for unknown
        _write_positions(self.data_dir, {
            "capital_usd": sum(latency_map.values()), "cash_usd": 0.0,
            "positions": latency_map,
        })
        return el.build_exit_liquidity(self.data_dir)

    def test_instant_and_liquid_within_24(self):
        # aave(0h), yearn(1h) → both <=24
        r = self._build({"aave_v3": 50000.0, "yearn_v3": 50000.0})
        self.assertAlmostEqual(r["exitable_within"]["24h"], 1.0)
        self.assertAlmostEqual(r["exitable_within"]["72h"], 1.0)
        self.assertAlmostEqual(r["exitable_within"]["gt_72h"], 0.0)

    def test_maple_gt_72(self):
        r = self._build({"aave_v3": 50000.0, "maple": 50000.0})
        self.assertAlmostEqual(r["exitable_within"]["24h"], 0.5)
        self.assertAlmostEqual(r["exitable_within"]["72h"], 0.5)
        self.assertAlmostEqual(r["exitable_within"]["gt_72h"], 0.5)

    def test_unknown_counts_gt72(self):
        r = self._build({"aave_v3": 50000.0, "sky_susds": 50000.0})
        self.assertAlmostEqual(r["exitable_within"]["gt_72h"], 0.5)

    def test_boundary_exactly_24(self):
        # inject a protocol with latency exactly 24 via monkeypatch of the map.
        # Use a slug that survives normalize_protocol (lowercase alnum).
        el.PROTOCOL_EXIT_LATENCY_HOURS["t24"] = 24.0
        try:
            r = self._build({"t24": 100000.0})
            self.assertAlmostEqual(r["exitable_within"]["24h"], 1.0)
            self.assertAlmostEqual(r["exitable_within"]["72h"], 1.0)
            self.assertAlmostEqual(r["exitable_within"]["gt_72h"], 0.0)
        finally:
            el.PROTOCOL_EXIT_LATENCY_HOURS.pop("t24", None)

    def test_boundary_just_above_24(self):
        el.PROTOCOL_EXIT_LATENCY_HOURS["t25"] = 25.0
        try:
            r = self._build({"t25": 100000.0})
            self.assertAlmostEqual(r["exitable_within"]["24h"], 0.0)
            self.assertAlmostEqual(r["exitable_within"]["72h"], 1.0)
        finally:
            el.PROTOCOL_EXIT_LATENCY_HOURS.pop("t25", None)

    def test_boundary_exactly_72(self):
        el.PROTOCOL_EXIT_LATENCY_HOURS["t72"] = 72.0
        try:
            r = self._build({"t72": 100000.0})
            self.assertAlmostEqual(r["exitable_within"]["72h"], 1.0)
            self.assertAlmostEqual(r["exitable_within"]["gt_72h"], 0.0)
            # exactly 72 is "liquid" (classify_exit_latency uses <= threshold)
            self.assertEqual(r["breakdown"]["t72"]["bucket"], "liquid")
        finally:
            el.PROTOCOL_EXIT_LATENCY_HOURS.pop("t72", None)

    def test_boundary_just_above_72(self):
        el.PROTOCOL_EXIT_LATENCY_HOURS["t73"] = 73.0
        try:
            r = self._build({"t73": 100000.0})
            self.assertAlmostEqual(r["exitable_within"]["72h"], 0.0)
            self.assertAlmostEqual(r["exitable_within"]["gt_72h"], 1.0)
            self.assertEqual(r["breakdown"]["t73"]["bucket"], "illiquid")
        finally:
            el.PROTOCOL_EXIT_LATENCY_HOURS.pop("t73", None)


# ─── Weighted mean exit latency ──────────────────────────────────────────────


class TestWeightedMean(_TmpBase):
    def test_hand_computed(self):
        # aave 0h @ 0.5, yearn 1h @ 0.5 → mean = (0.5*0 + 0.5*1)/(1.0) = 0.5
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 50000.0, "yearn_v3": 50000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertAlmostEqual(r["weighted_mean_exit_latency_hours"], 0.5)

    def test_unknown_skipped_in_mean(self):
        # aave 0h @ 50k, maple 336h @ 50k, unknown @ 100k (skipped from mean)
        # known weight = 0.25+0.25 = 0.5; sum = 0.25*0 + 0.25*336 = 84
        # mean = 84 / 0.5 = 168
        _write_positions(self.data_dir, {
            "capital_usd": 200000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 50000.0, "maple": 50000.0,
                          "sky_susds": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertAlmostEqual(r["weighted_mean_exit_latency_hours"], 168.0)

    def test_cash_counts_as_zero(self):
        # cash @ 0h is a known instant position; mean over aave + cash = 0
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 50000.0,
            "positions": {"aave_v3": 50000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertAlmostEqual(r["weighted_mean_exit_latency_hours"], 0.0)

    def test_no_known_none(self):
        # only unknown protocol → mean None
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"sky_susds": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertIsNone(r["weighted_mean_exit_latency_hours"])
        self.assertTrue(any("weighted mean" in n for n in r["notes"]))


# ─── Policy verdict boundaries + reuse-by-import ─────────────────────────────


class TestPolicyVerdict(_TmpBase):
    def test_maple_exactly_25pct_ok(self):
        # maple 25k illiquid on 100k AUM = exactly 0.25 → policy ok (eps).
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 75000.0, "maple": 25000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertAlmostEqual(r["policy"]["illiquid_share"], 0.25)
        self.assertTrue(r["policy"]["ok"])
        self.assertEqual(r["verdict"], "ok")

    def test_above_25pct_fail(self):
        # maple 30k on 100k = 0.3 > 0.25 → fail
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 70000.0, "maple": 30000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertFalse(r["policy"]["ok"])
        self.assertEqual(r["verdict"], "fail")

    def test_unknown_present_warn(self):
        # all-liquid + small unknown under 25% → warn (not fail)
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 90000.0, "sky_susds": 10000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertTrue(r["policy"]["ok"])
        self.assertEqual(r["verdict"], "warn")

    def test_unknown_over_25_is_fail(self):
        # unknown 30% pushes illiquid_share over cap → fail wins over warn
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 70000.0, "sky_susds": 30000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["verdict"], "fail")

    def test_clean_ok(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 60000.0, "yearn_v3": 40000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["verdict"], "ok")

    def test_cash_only_warn(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 100000.0, "positions": {},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["verdict"], "warn")
        self.assertTrue(any("cash-only" in n for n in r["notes"]))

    def test_policy_equals_direct_call(self):
        # Proves reuse: our policy block equals a direct check_exit_latency_policy.
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 10000.0,
            "positions": {"aave_v3": 50000.0, "yearn_v3": 20000.0,
                          "maple": 15000.0, "sky_susds": 5000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        # rebuild the same positions mapping and call directly
        aum = 100000.0
        direct_map = {
            "aave_v3": {"weight": 50000.0 / aum, "exit_latency_hours": 0.0},
            "yearn_v3": {"weight": 20000.0 / aum, "exit_latency_hours": 1.0},
            "maple": {"weight": 15000.0 / aum, "exit_latency_hours": 336.0},
            "sky_susds": {"weight": 5000.0 / aum, "exit_latency_hours": None},
            el.CASH_KEY: {"weight": 10000.0 / aum, "exit_latency_hours": 0.0},
        }
        direct = check_exit_latency_policy(direct_map)
        self.assertEqual(r["policy"]["ok"], direct["ok"])
        self.assertAlmostEqual(r["policy"]["illiquid_share"],
                               round(direct["illiquid_share"], 9))
        self.assertEqual(set(r["policy"]["illiquid_positions"]),
                         set(direct["illiquid_positions"]))

    def test_kill_switch_equals_direct_call(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 10000.0,
            "positions": {"aave_v3": 50000.0, "yearn_v3": 20000.0,
                          "maple": 15000.0, "sky_susds": 5000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        aum = 100000.0
        direct_map = {
            "aave_v3": {"weight": 50000.0 / aum, "exit_latency_hours": 0.0},
            "yearn_v3": {"weight": 20000.0 / aum, "exit_latency_hours": 1.0},
            "maple": {"weight": 15000.0 / aum, "exit_latency_hours": 336.0},
            "sky_susds": {"weight": 5000.0 / aum, "exit_latency_hours": None},
            el.CASH_KEY: {"weight": 10000.0 / aum, "exit_latency_hours": 0.0},
        }
        self.assertEqual(r["kill_switch_order"], kill_switch_exit_order(direct_map))

    def test_max_illiquid_share_surfaced(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertEqual(r["policy"]["max_illiquid_share"], MAX_ILLIQUID_SHARE)
        self.assertEqual(r["policy"]["threshold_hours"], ILLIQUID_THRESHOLD_HOURS)


# ─── Missing / broken input ──────────────────────────────────────────────────


class TestMissingBroken(_TmpBase):
    def test_missing_file(self):
        r = el.build_exit_liquidity(self.data_dir)  # empty dir
        self.assertFalse(r["available"])
        self.assertTrue(any("missing" in n for n in r["notes"]))
        # honest empty schema present
        self.assertIn("ladder", r)
        self.assertEqual(r["breakdown"], {})

    def test_broken_json(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / el.POSITIONS_FILENAME).write_text("{not json", encoding="utf-8")
        r = el.build_exit_liquidity(self.data_dir)  # must not raise
        self.assertFalse(r["available"])

    def test_top_level_not_dict(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / el.POSITIONS_FILENAME).write_text("[1,2,3]", encoding="utf-8")
        r = el.build_exit_liquidity(self.data_dir)
        self.assertFalse(r["available"])

    def test_positions_not_dict(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 100000.0, "positions": "bad",
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertTrue(any("not a dict" in n for n in r["notes"]))

    def test_is_demo_absent_null(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0,
            "positions": {"aave_v3": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertIsNone(r["is_demo"])

    def test_is_demo_honest(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 0.0, "is_demo": True,
            "positions": {"aave_v3": 100000.0},
        })
        r = el.build_exit_liquidity(self.data_dir)
        self.assertTrue(r["is_demo"])

    def test_never_raises_on_junk_dir(self):
        # nonexistent / odd data_dir path → honest empty, no raise
        r = el.build_exit_liquidity("/nonexistent/path/xyz123")
        self.assertFalse(r["available"])


# ─── Persistence + idempotency ───────────────────────────────────────────────


class TestPersistence(_TmpBase):
    def _good_positions(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 60000.0, "maple": 15000.0,
                          "yearn_v3": 20000.0},
        })

    def test_run_writes(self):
        self._good_positions()
        doc = el.build_status_doc(data_dir=self.data_dir)
        out = el.write_status(doc, data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        path = self.data_dir / el.STATUS_FILENAME
        self.assertTrue(path.exists())
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded["source"], el.SOURCE_NAME)
        self.assertIn("history", loaded)
        self.assertEqual(len(loaded["history"]), 1)

    def test_run_twice_byte_identical(self):
        self._good_positions()
        fixed = datetime(2026, 6, 12, tzinfo=timezone.utc)
        doc1 = el.build_status_doc(data_dir=self.data_dir, now=fixed)
        el.write_status(doc1, data_dir=self.data_dir)
        path = self.data_dir / el.STATUS_FILENAME
        bytes1 = path.read_bytes()
        # second run with a DIFFERENT timestamp — content unchanged → no rewrite
        later = datetime(2026, 6, 13, tzinfo=timezone.utc)
        doc2 = el.build_status_doc(data_dir=self.data_dir, now=later)
        out2 = el.write_status(doc2, data_dir=self.data_dir)
        self.assertFalse(out2["changed"])
        self.assertEqual(path.read_bytes(), bytes1)

    def test_generated_at_stable_when_unchanged(self):
        self._good_positions()
        doc1 = el.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 6, 12, tzinfo=timezone.utc))
        el.write_status(doc1, data_dir=self.data_dir)
        path = self.data_dir / el.STATUS_FILENAME
        ga1 = json.loads(path.read_text())["meta"]["generated_at"]
        doc2 = el.build_status_doc(data_dir=self.data_dir,
                                   now=datetime(2026, 7, 1, tzinfo=timezone.utc))
        el.write_status(doc2, data_dir=self.data_dir)
        ga2 = json.loads(path.read_text())["meta"]["generated_at"]
        self.assertEqual(ga1, ga2)

    def test_history_grows_on_change(self):
        self._good_positions()
        el.write_status(el.build_status_doc(data_dir=self.data_dir,
                        now=datetime(2026, 6, 12, tzinfo=timezone.utc)),
                        data_dir=self.data_dir)
        # change the data
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 95000.0},
        })
        out2 = el.write_status(el.build_status_doc(data_dir=self.data_dir,
                               now=datetime(2026, 6, 13, tzinfo=timezone.utc)),
                               data_dir=self.data_dir)
        self.assertTrue(out2["changed"])
        loaded = json.loads((self.data_dir / el.STATUS_FILENAME).read_text())
        self.assertEqual(len(loaded["history"]), 2)

    def test_history_rotation_exactly_500(self):
        self._good_positions()
        path = self.data_dir / el.STATUS_FILENAME
        # seed status file with 500 existing history entries + a fingerprint
        # that will differ from the new doc.
        seed = {"history": [{"generated_at": f"t{i}"} for i in range(600)]}
        path.write_text(json.dumps(seed), encoding="utf-8")
        doc = el.build_status_doc(data_dir=self.data_dir)
        el.write_status(doc, data_dir=self.data_dir)
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), el.HISTORY_MAX)
        self.assertEqual(el.HISTORY_MAX, 500)

    def test_no_tmp_leftovers(self):
        self._good_positions()
        el.write_status(el.build_status_doc(data_dir=self.data_dir),
                        data_dir=self.data_dir)
        leftovers = list(self.data_dir.glob("*.tmp")) + \
            list(self.data_dir.glob(".*tmp"))
        self.assertEqual(leftovers, [])

    def test_broken_prior_status_tolerated(self):
        self._good_positions()
        path = self.data_dir / el.STATUS_FILENAME
        path.write_text("{broken", encoding="utf-8")
        out = el.write_status(el.build_status_doc(data_dir=self.data_dir),
                              data_dir=self.data_dir)
        self.assertTrue(out["changed"])
        loaded = json.loads(path.read_text())
        self.assertEqual(len(loaded["history"]), 1)

    def test_fingerprint_excludes_volatile(self):
        a = {"meta": {"generated_at": "2026-01-01"}, "verdict": "ok",
             "history": [1, 2]}
        b = {"meta": {"generated_at": "2099-12-31"}, "verdict": "ok",
             "history": [9]}
        self.assertEqual(el.content_fingerprint(a), el.content_fingerprint(b))

    def test_fingerprint_detects_content_change(self):
        a = {"meta": {"generated_at": "x"}, "verdict": "ok"}
        b = {"meta": {"generated_at": "x"}, "verdict": "fail"}
        self.assertNotEqual(el.content_fingerprint(a), el.content_fingerprint(b))

    def test_fingerprint_invalid(self):
        self.assertEqual(el.content_fingerprint("not a dict"), "<invalid>")


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(_TmpBase):
    def _good_positions(self):
        _write_positions(self.data_dir, {
            "capital_usd": 100000.0, "cash_usd": 5000.0, "is_demo": False,
            "positions": {"aave_v3": 60000.0, "maple": 15000.0,
                          "yearn_v3": 20000.0},
        })

    def test_check_default_exit0_valid_json(self):
        self._good_positions()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = el.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["source"], el.SOURCE_NAME)
        self.assertIn("verdict", doc)

    def test_default_is_check(self):
        self._good_positions()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = el.main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        json.loads(out.getvalue())  # valid JSON => behaved as --check

    def test_check_does_not_write(self):
        self._good_positions()
        before = sorted(p.name for p in self.data_dir.iterdir())
        with contextlib.redirect_stdout(io.StringIO()):
            el.main(["--check", "--data-dir", str(self.data_dir)])
        after = sorted(p.name for p in self.data_dir.iterdir())
        self.assertEqual(before, after)
        self.assertNotIn(el.STATUS_FILENAME, after)

    def test_run_writes_exit0(self):
        self._good_positions()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = el.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.data_dir / el.STATUS_FILENAME).exists())

    def test_run_twice_idempotent(self):
        self._good_positions()
        with contextlib.redirect_stdout(io.StringIO()):
            el.main(["--run", "--data-dir", str(self.data_dir)])
        path = self.data_dir / el.STATUS_FILENAME
        b1 = path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            el.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(path.read_bytes(), b1)

    def test_empty_data_dir_exit0(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = el.main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)

    def test_junk_arg_exit0_no_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = el.main(["--frobnicate"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_run_no_tmp_leftover_after_cli(self):
        self._good_positions()
        with contextlib.redirect_stdout(io.StringIO()):
            el.main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_subprocess_check_exit0(self):
        self._good_positions()
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.exit_liquidity",
             "--check", "--data-dir", str(self.data_dir)],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        json.loads(proc.stdout)  # valid JSON
        self.assertNotIn("Traceback", proc.stderr)

    def test_subprocess_junk_arg_exit0(self):
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.paper_trading.exit_liquidity",
             "--no-such-flag"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("ERROR", proc.stderr)


# ─── Hygiene / reuse ─────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    def _module_source(self):
        return (_REPO_ROOT / "spa_core" / "paper_trading"
                / "exit_liquidity.py").read_text(encoding="utf-8")

    def test_no_forbidden_imports_via_ast(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = self._module_source()
        self.assertEqual(find_forbidden_imports(src, "exit_liquidity.py"), [])

    def test_test_file_clean(self):
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        src = (_REPO_ROOT / "spa_core" / "tests"
               / "test_exit_liquidity.py").read_text(encoding="utf-8")
        self.assertEqual(find_forbidden_imports(src, "test_exit_liquidity.py"), [])

    def test_no_network_imports(self):
        src = self._module_source()
        for forbidden in ("import requests", "import web3", "import socket",
                          "import urllib", "from urllib", "import anthropic",
                          "import openai"):
            self.assertNotIn(forbidden, src, forbidden)

    def test_reuses_exit_latency_policy(self):
        src = self._module_source()
        self.assertIn("from spa_core.adapters.exit_latency_policy import", src)
        self.assertIn("check_exit_latency_policy", src)
        self.assertIn("kill_switch_exit_order", src)
        self.assertIn("classify_exit_latency", src)

    def test_constants_present(self):
        self.assertEqual(el.ILLIQUID_THRESHOLD_HOURS, 72.0)
        self.assertEqual(el.MAX_ILLIQUID_SHARE, 0.25)
        self.assertTrue(hasattr(el, "PROTOCOL_EXIT_LATENCY_HOURS"))
        self.assertTrue(hasattr(el, "build_exit_liquidity"))
        self.assertTrue(hasattr(el, "write_status"))
        self.assertTrue(hasattr(el, "content_fingerprint"))

    def test_does_not_redefine_thresholds(self):
        # imported, not hard-coded duplicates
        src = self._module_source()
        self.assertNotIn("ILLIQUID_THRESHOLD_HOURS =", src)
        self.assertNotIn("MAX_ILLIQUID_SHARE =", src)


if __name__ == "__main__":
    unittest.main()
