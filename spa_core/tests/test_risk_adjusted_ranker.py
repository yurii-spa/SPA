"""Tests for spa_core/analytics/risk_adjusted_ranker.py — MP-593.

Usage:
    python3 -m unittest spa_core.tests.test_risk_adjusted_ranker -v

All tests use mock/temp data — do NOT depend on the real adapter_status.json
and do NOT overwrite the production data/risk_adjusted_report.json.
100+ test cases across multiple test classes.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.risk_adjusted_ranker import (
    RISK_FREE_PCT,
    DEFAULT_RISK_SCORE,
    MIN_APY_PCT,
    EPS,
    RankedAdapter,
    RankerReport,
    RiskAdjustedRanker,
    _extract_apy,
    _extract_risk_score,
    _extract_tvl,
    _extract_peg_healthy,
    _resolve_network,
    _resolve_protocol,
    _num,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_status(entries: dict | None = None, adapters: list | None = None) -> dict:
    """Build a minimal adapter_status.json dict for tests."""
    result: dict = {}
    if entries:
        result.update(entries)
    if adapters is not None:
        result["adapters"] = adapters
    return result


def _write_status(tmp_dir: str, status: dict) -> str:
    """Write adapter_status.json to tmp_dir and return its path."""
    path = os.path.join(tmp_dir, "adapter_status.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(status, fh)
    return path


def _make_ranker(tmp_dir: str, status: dict) -> RiskAdjustedRanker:
    """Convenience: write status to tmp_dir and return a Ranker for it."""
    path = _write_status(tmp_dir, status)
    return RiskAdjustedRanker(data_path=path)


def _entry(apy=5.0, **kw) -> dict:
    """Build a protocol-level entry with an apy field."""
    d = {"apy": apy}
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_risk_free_pct(self):
        self.assertEqual(RISK_FREE_PCT, 4.0)

    def test_default_risk_score(self):
        self.assertEqual(DEFAULT_RISK_SCORE, 0.5)

    def test_min_apy_pct(self):
        self.assertEqual(MIN_APY_PCT, 0.0)

    def test_eps_small_positive(self):
        self.assertGreater(EPS, 0.0)
        self.assertLess(EPS, 1e-6)

    def test_default_risk_in_range(self):
        self.assertTrue(0.0 < DEFAULT_RISK_SCORE <= 1.0)


# ---------------------------------------------------------------------------
# _num helper
# ---------------------------------------------------------------------------

class TestNumHelper(unittest.TestCase):
    def test_int(self):
        self.assertEqual(_num(5), 5.0)

    def test_float(self):
        self.assertEqual(_num(5.5), 5.5)

    def test_zero(self):
        self.assertEqual(_num(0), 0.0)

    def test_negative(self):
        self.assertEqual(_num(-3), -3.0)

    def test_bool_true_rejected(self):
        self.assertIsNone(_num(True))

    def test_bool_false_rejected(self):
        self.assertIsNone(_num(False))

    def test_string_rejected(self):
        self.assertIsNone(_num("5"))

    def test_none_rejected(self):
        self.assertIsNone(_num(None))

    def test_list_rejected(self):
        self.assertIsNone(_num([1, 2]))

    def test_returns_float_type(self):
        self.assertIsInstance(_num(5), float)


# ---------------------------------------------------------------------------
# _extract_* helpers
# ---------------------------------------------------------------------------

class TestExtractHelpers(unittest.TestCase):
    def test_apy_from_apy_pct_priority(self):
        self.assertEqual(_extract_apy({"apy_pct": 7.0, "apy": 5.0}), 7.0)

    def test_apy_from_apy(self):
        self.assertEqual(_extract_apy({"apy": 5.0}), 5.0)

    def test_apy_missing_zero(self):
        self.assertEqual(_extract_apy({}), 0.0)

    def test_apy_bool_rejected(self):
        self.assertEqual(_extract_apy({"apy": True}), 0.0)

    def test_apy_string_rejected(self):
        self.assertEqual(_extract_apy({"apy": "5"}), 0.0)

    def test_apy_zero_allowed(self):
        self.assertEqual(_extract_apy({"apy": 0}), 0.0)

    def test_apy_negative(self):
        self.assertEqual(_extract_apy({"apy": -1.0}), -1.0)

    def test_risk_score_present(self):
        self.assertEqual(_extract_risk_score({"risk_score": 0.3}), 0.3)

    def test_risk_score_fallback(self):
        self.assertEqual(_extract_risk_score({}), DEFAULT_RISK_SCORE)

    def test_risk_score_zero_allowed(self):
        self.assertEqual(_extract_risk_score({"risk_score": 0.0}), 0.0)

    def test_risk_score_bool_fallback(self):
        self.assertEqual(_extract_risk_score({"risk_score": True}), DEFAULT_RISK_SCORE)

    def test_risk_score_string_fallback(self):
        self.assertEqual(_extract_risk_score({"risk_score": "x"}), DEFAULT_RISK_SCORE)

    def test_tvl_present(self):
        self.assertEqual(_extract_tvl({"tvl_usd": 1000.0}), 1000.0)

    def test_tvl_missing_zero(self):
        self.assertEqual(_extract_tvl({}), 0.0)

    def test_tvl_bool_zero(self):
        self.assertEqual(_extract_tvl({"tvl_usd": True}), 0.0)


# ---------------------------------------------------------------------------
# Peg health
# ---------------------------------------------------------------------------

class TestPegHealthy(unittest.TestCase):
    def test_missing_price_healthy(self):
        self.assertTrue(_extract_peg_healthy({}))

    def test_exact_peg_healthy(self):
        self.assertTrue(_extract_peg_healthy({"usdc_price": 1.0}))

    def test_boundary_lower_0995_healthy(self):
        self.assertTrue(_extract_peg_healthy({"usdc_price": 0.995}))

    def test_boundary_upper_1005_healthy(self):
        self.assertTrue(_extract_peg_healthy({"usdc_price": 1.005}))

    def test_below_0_99_unhealthy(self):
        self.assertFalse(_extract_peg_healthy({"usdc_price": 0.99}))

    def test_above_1_01_unhealthy(self):
        self.assertFalse(_extract_peg_healthy({"usdc_price": 1.01}))

    def test_just_below_boundary_unhealthy(self):
        self.assertFalse(_extract_peg_healthy({"usdc_price": 0.9949}))

    def test_just_above_boundary_unhealthy(self):
        self.assertFalse(_extract_peg_healthy({"usdc_price": 1.0051}))

    def test_bool_price_treated_missing(self):
        self.assertTrue(_extract_peg_healthy({"usdc_price": True}))

    def test_string_price_treated_missing(self):
        self.assertTrue(_extract_peg_healthy({"usdc_price": "1.0"}))


# ---------------------------------------------------------------------------
# _resolve helpers
# ---------------------------------------------------------------------------

class TestResolveHelpers(unittest.TestCase):
    def test_network_from_network(self):
        self.assertEqual(_resolve_network({"network": "ethereum"}), "ethereum")

    def test_network_from_chain(self):
        self.assertEqual(_resolve_network({"chain": "arbitrum"}), "arbitrum")

    def test_network_priority(self):
        self.assertEqual(_resolve_network({"network": "a", "chain": "b"}), "a")

    def test_network_missing_empty(self):
        self.assertEqual(_resolve_network({}), "")

    def test_protocol_from_protocol(self):
        self.assertEqual(_resolve_protocol({"protocol": "Aave"}, "x"), "Aave")

    def test_protocol_from_name(self):
        self.assertEqual(_resolve_protocol({"name": "Yearn"}, "x"), "Yearn")

    def test_protocol_from_display_name(self):
        self.assertEqual(_resolve_protocol({"display_name": "Sky"}, "x"), "Sky")

    def test_protocol_fallback_name(self):
        self.assertEqual(_resolve_protocol({}, "fallback"), "fallback")


# ---------------------------------------------------------------------------
# RankedAdapter dataclass
# ---------------------------------------------------------------------------

class TestRankedAdapter(unittest.TestCase):
    def _make(self, **kw):
        base = dict(
            name="x", protocol="X", tier="T1", network="ethereum",
            apy_pct=5.0, risk_score=0.25, tvl_usd=100.0,
            risk_adjusted_score=20.0, excess_yield_pct=1.0,
            peg_healthy=True, eligible=True, rank=1,
        )
        base.update(kw)
        return RankedAdapter(**base)

    def test_name_field(self):
        self.assertEqual(self._make().name, "x")

    def test_protocol_field(self):
        self.assertEqual(self._make().protocol, "X")

    def test_tier_field(self):
        self.assertEqual(self._make().tier, "T1")

    def test_network_field(self):
        self.assertEqual(self._make().network, "ethereum")

    def test_apy_field(self):
        self.assertEqual(self._make().apy_pct, 5.0)

    def test_risk_field(self):
        self.assertEqual(self._make().risk_score, 0.25)

    def test_tvl_field(self):
        self.assertEqual(self._make().tvl_usd, 100.0)

    def test_ras_field(self):
        self.assertEqual(self._make().risk_adjusted_score, 20.0)

    def test_excess_field(self):
        self.assertEqual(self._make().excess_yield_pct, 1.0)

    def test_peg_field(self):
        self.assertTrue(self._make().peg_healthy)

    def test_eligible_field(self):
        self.assertTrue(self._make().eligible)

    def test_rank_field(self):
        self.assertEqual(self._make().rank, 1)

    def test_rank_default_none(self):
        a = RankedAdapter(
            name="x", protocol="X", tier="T1", network="e",
            apy_pct=5.0, risk_score=0.25, tvl_usd=100.0,
            risk_adjusted_score=20.0, excess_yield_pct=1.0,
            peg_healthy=True, eligible=True,
        )
        self.assertIsNone(a.rank)

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        expected = {
            "name", "protocol", "tier", "network", "apy_pct", "risk_score",
            "tvl_usd", "risk_adjusted_score", "excess_yield_pct",
            "peg_healthy", "eligible", "rank",
        }
        self.assertEqual(set(d.keys()), expected)

    def test_to_dict_values(self):
        d = self._make().to_dict()
        self.assertEqual(d["name"], "x")
        self.assertEqual(d["rank"], 1)

    def test_to_dict_json_serializable(self):
        json.dumps(self._make().to_dict())

    def test_to_dict_rank_none_serializable(self):
        d = self._make(rank=None).to_dict()
        self.assertIsNone(d["rank"])
        json.dumps(d)


# ---------------------------------------------------------------------------
# RankerReport dataclass
# ---------------------------------------------------------------------------

class TestRankerReport(unittest.TestCase):
    def _make(self):
        ra = RankedAdapter(
            name="x", protocol="X", tier="T1", network="e",
            apy_pct=5.0, risk_score=0.25, tvl_usd=100.0,
            risk_adjusted_score=20.0, excess_yield_pct=1.0,
            peg_healthy=True, eligible=True, rank=1,
        )
        return RankerReport(
            generated_at="2026-06-13T00:00:00+00:00",
            ranked=[ra], total_adapters=1, eligible_count=1,
            best_adapter="x", best_score=20.0,
            top_tier_leaders={"T1": "x"},
        )

    def test_generated_at(self):
        self.assertIsInstance(self._make().generated_at, str)

    def test_ranked_list(self):
        self.assertIsInstance(self._make().ranked, list)

    def test_total_adapters(self):
        self.assertEqual(self._make().total_adapters, 1)

    def test_eligible_count(self):
        self.assertEqual(self._make().eligible_count, 1)

    def test_best_adapter(self):
        self.assertEqual(self._make().best_adapter, "x")

    def test_best_score(self):
        self.assertEqual(self._make().best_score, 20.0)

    def test_top_tier_leaders(self):
        self.assertEqual(self._make().top_tier_leaders, {"T1": "x"})

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        expected = {
            "generated_at", "ranked", "total_adapters", "eligible_count",
            "best_adapter", "best_score", "top_tier_leaders",
        }
        self.assertEqual(set(d.keys()), expected)

    def test_to_dict_ranked_is_dicts(self):
        d = self._make().to_dict()
        self.assertIsInstance(d["ranked"][0], dict)

    def test_to_dict_json_serializable(self):
        json.dumps(self._make().to_dict())

    def test_to_dict_leaders_copy(self):
        report = self._make()
        d = report.to_dict()
        d["top_tier_leaders"]["T1"] = "mutated"
        self.assertEqual(report.top_tier_leaders["T1"], "x")


# ---------------------------------------------------------------------------
# load_adapter_status fail-safe
# ---------------------------------------------------------------------------

class TestLoadAdapterStatus(unittest.TestCase):
    def test_loads_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"a": 1})
            self.assertEqual(r.load_adapter_status(), {"a": 1})

    def test_missing_file_returns_empty(self):
        r = RiskAdjustedRanker(data_path="/nonexistent/xyz/adapter_status.json")
        self.assertEqual(r.load_adapter_status(), {})

    def test_empty_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "adapter_status.json")
            open(path, "w").close()
            r = RiskAdjustedRanker(data_path=path)
            self.assertEqual(r.load_adapter_status(), {})

    def test_malformed_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "adapter_status.json")
            with open(path, "w") as fh:
                fh.write("{not valid json,,,")
            r = RiskAdjustedRanker(data_path=path)
            self.assertEqual(r.load_adapter_status(), {})

    def test_json_array_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "adapter_status.json")
            with open(path, "w") as fh:
                json.dump([1, 2, 3], fh)
            r = RiskAdjustedRanker(data_path=path)
            self.assertEqual(r.load_adapter_status(), {})

    def test_json_string_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "adapter_status.json")
            with open(path, "w") as fh:
                json.dump("hello", fh)
            r = RiskAdjustedRanker(data_path=path)
            self.assertEqual(r.load_adapter_status(), {})

    def test_never_raises_directory(self):
        with tempfile.TemporaryDirectory() as td:
            r = RiskAdjustedRanker(data_path=td)  # a dir, not a file
            self.assertEqual(r.load_adapter_status(), {})

    def test_unicode_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"note": "доходность"})
            self.assertEqual(r.load_adapter_status()["note"], "доходность")


# ---------------------------------------------------------------------------
# _extract_adapters dual-source
# ---------------------------------------------------------------------------

class TestExtractAdapters(unittest.TestCase):
    def test_protocol_level_entry(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, _make_status({"foo": _entry(apy=5.0)}))
            adapters = r._extract_adapters()
            self.assertEqual(len(adapters), 1)
            self.assertEqual(adapters[0].name, "foo")

    def test_adapter_id_used_as_name(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, _make_status({"foo": _entry(adapter_id="bar")}))
            self.assertEqual(r._extract_adapters()[0].name, "bar")

    def test_skips_skip_keys(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "generated_at": "2026",
                "schema_version": 1,
                "execution_mode": "dry_run",
                "live_apy_enabled": False,
                "mev_protection": {"apy": 5.0},  # skip-key even though has apy
                "base_gas_monitor": {"apy": 5.0},
                "real": _entry(apy=5.0),
            }
            r = _make_ranker(td, status)
            names = [a.name for a in r._extract_adapters()]
            self.assertEqual(names, ["real"])

    def test_skips_underscore_keys(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"_meta": _entry(), "real": _entry()})
            names = [a.name for a in r._extract_adapters()]
            self.assertEqual(names, ["real"])

    def test_skips_non_dict(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": 5, "y": "str", "real": _entry()})
            names = [a.name for a in r._extract_adapters()]
            self.assertEqual(names, ["real"])

    def test_skips_dict_without_apy(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"noapy": {"tier": "T1"}, "real": _entry()})
            names = [a.name for a in r._extract_adapters()]
            self.assertEqual(names, ["real"])

    def test_accepts_apy_pct_only(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": {"apy_pct": 6.0, "tier": "T1"}})
            self.assertEqual(len(r._extract_adapters()), 1)

    def test_adapters_list_source(self):
        with tempfile.TemporaryDirectory() as td:
            status = _make_status(adapters=[{"protocol_key": "aave", "apy": 4.0}])
            r = _make_ranker(td, status)
            names = [a.name for a in r._extract_adapters()]
            self.assertIn("aave", names)

    def test_adapters_list_dedup_by_name(self):
        with tempfile.TemporaryDirectory() as td:
            status = _make_status(
                {"aave": _entry(apy=5.0)},
                adapters=[{"protocol_key": "aave", "apy": 4.0}],
            )
            r = _make_ranker(td, status)
            adapters = r._extract_adapters()
            self.assertEqual(len(adapters), 1)
            # protocol-level wins (apy 5.0)
            self.assertEqual(adapters[0].apy_pct, 5.0)

    def test_adapters_list_non_dict_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            status = _make_status(adapters=["x", 5, {"protocol_key": "aave", "apy": 4.0}])
            r = _make_ranker(td, status)
            self.assertEqual(len(r._extract_adapters()), 1)

    def test_adapters_list_unknown_name(self):
        with tempfile.TemporaryDirectory() as td:
            status = _make_status(adapters=[{"apy": 4.0}])
            r = _make_ranker(td, status)
            self.assertEqual(r._extract_adapters()[0].name, "unknown")

    def test_empty_status_no_adapters(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {})
            self.assertEqual(r._extract_adapters(), [])

    def test_dual_source_combined(self):
        with tempfile.TemporaryDirectory() as td:
            status = _make_status(
                {"foo": _entry(apy=5.0)},
                adapters=[{"protocol_key": "bar", "apy": 6.0}],
            )
            r = _make_ranker(td, status)
            names = sorted(a.name for a in r._extract_adapters())
            self.assertEqual(names, ["bar", "foo"])


# ---------------------------------------------------------------------------
# Math: risk_adjusted_score / excess
# ---------------------------------------------------------------------------

class TestMath(unittest.TestCase):
    def _build(self, td, **kw):
        r = _make_ranker(td, {"x": _entry(**kw)})
        return r._extract_adapters()[0]

    def test_ras_basic(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=10.0, risk_score=0.5)
            self.assertAlmostEqual(a.risk_adjusted_score, 20.0)

    def test_ras_fallback_risk(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=10.0)  # no risk_score
            self.assertAlmostEqual(a.risk_adjusted_score, 10.0 / DEFAULT_RISK_SCORE)

    def test_ras_risk_zero_eps_protected(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=5.0, risk_score=0.0)
            # divides by EPS, huge but finite, no exception
            self.assertGreater(a.risk_adjusted_score, 1e6)

    def test_ras_zero_apy(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=0.0, risk_score=0.5)
            self.assertEqual(a.risk_adjusted_score, 0.0)

    def test_excess_positive(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=10.0)
            self.assertAlmostEqual(a.excess_yield_pct, 10.0 - RISK_FREE_PCT)

    def test_excess_negative(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=2.0)
            self.assertAlmostEqual(a.excess_yield_pct, 2.0 - RISK_FREE_PCT)

    def test_excess_zero_at_risk_free(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=RISK_FREE_PCT)
            self.assertAlmostEqual(a.excess_yield_pct, 0.0)

    def test_risk_score_stored(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=5.0, risk_score=0.3)
            self.assertEqual(a.risk_score, 0.3)

    def test_risk_score_fallback_stored(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._build(td, apy=5.0)
            self.assertEqual(a.risk_score, DEFAULT_RISK_SCORE)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

class TestEligibility(unittest.TestCase):
    def _build(self, td, **kw):
        r = _make_ranker(td, {"x": _entry(**kw)})
        return r._extract_adapters()[0]

    def test_healthy_positive_apy_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(self._build(td, apy=5.0).eligible)

    def test_zero_apy_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(self._build(td, apy=0.0).eligible)

    def test_negative_apy_not_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(self._build(td, apy=-1.0).eligible)

    def test_peg_unhealthy_not_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(self._build(td, apy=5.0, usdc_price=0.95).eligible)

    def test_peg_boundary_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(self._build(td, apy=5.0, usdc_price=0.995).eligible)

    def test_missing_peg_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(self._build(td, apy=5.0).eligible)


# ---------------------------------------------------------------------------
# rank_all
# ---------------------------------------------------------------------------

class TestRankAll(unittest.TestCase):
    def test_sorted_desc(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "low": _entry(apy=4.0, risk_score=0.5),    # ras 8
                "high": _entry(apy=10.0, risk_score=0.5),  # ras 20
                "mid": _entry(apy=6.0, risk_score=0.5),    # ras 12
            }
            r = _make_ranker(td, status)
            names = [a.name for a in r.rank_all()]
            self.assertEqual(names, ["high", "mid", "low"])

    def test_ranks_assigned(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "a": _entry(apy=10.0, risk_score=0.5),
                "b": _entry(apy=4.0, risk_score=0.5),
            }
            r = _make_ranker(td, status)
            ranked = r.rank_all()
            self.assertEqual(ranked[0].rank, 1)
            self.assertEqual(ranked[1].rank, 2)

    def test_tie_break_apy_desc(self):
        with tempfile.TemporaryDirectory() as td:
            # both ras = 20, but different apy
            status = {
                "lowapy": _entry(apy=10.0, risk_score=0.5),  # ras 20
                "highapy": _entry(apy=20.0, risk_score=1.0),  # ras 20
            }
            r = _make_ranker(td, status)
            names = [a.name for a in r.rank_all()]
            self.assertEqual(names, ["highapy", "lowapy"])

    def test_tie_break_name_asc(self):
        with tempfile.TemporaryDirectory() as td:
            # identical ras and apy -> name asc
            status = {
                "zeta": _entry(apy=10.0, risk_score=0.5),
                "alpha": _entry(apy=10.0, risk_score=0.5),
            }
            r = _make_ranker(td, status)
            names = [a.name for a in r.rank_all()]
            self.assertEqual(names, ["alpha", "zeta"])

    def test_excludes_non_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "ok": _entry(apy=5.0),
                "bad": _entry(apy=5.0, usdc_price=0.9),
            }
            r = _make_ranker(td, status)
            names = [a.name for a in r.rank_all()]
            self.assertEqual(names, ["ok"])

    def test_empty_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {})
            self.assertEqual(r.rank_all(), [])

    def test_all_non_eligible_empty(self):
        with tempfile.TemporaryDirectory() as td:
            status = {"bad": _entry(apy=5.0, usdc_price=0.5)}
            r = _make_ranker(td, status)
            self.assertEqual(r.rank_all(), [])

    def test_single_adapter_rank_one(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            ranked = r.rank_all()
            self.assertEqual(len(ranked), 1)
            self.assertEqual(ranked[0].rank, 1)

    def test_ranks_sequential(self):
        with tempfile.TemporaryDirectory() as td:
            status = {f"a{i}": _entry(apy=float(i + 1)) for i in range(5)}
            r = _make_ranker(td, status)
            ranks = [a.rank for a in r.rank_all()]
            self.assertEqual(ranks, [1, 2, 3, 4, 5])


# ---------------------------------------------------------------------------
# get_excluded
# ---------------------------------------------------------------------------

class TestGetExcluded(unittest.TestCase):
    def test_returns_non_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "ok": _entry(apy=5.0),
                "bad": _entry(apy=5.0, usdc_price=0.9),
            }
            r = _make_ranker(td, status)
            excluded = r.get_excluded()
            self.assertEqual([a.name for a in excluded], ["bad"])

    def test_rank_remains_none(self):
        with tempfile.TemporaryDirectory() as td:
            status = {"bad": _entry(apy=-1.0)}
            r = _make_ranker(td, status)
            self.assertIsNone(r.get_excluded()[0].rank)

    def test_empty_when_all_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            self.assertEqual(r.get_excluded(), [])

    def test_negative_apy_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=-5.0)})
            self.assertEqual(len(r.get_excluded()), 1)


# ---------------------------------------------------------------------------
# get_top_n
# ---------------------------------------------------------------------------

class TestGetTopN(unittest.TestCase):
    def _ranker(self, td):
        status = {f"a{i}": _entry(apy=float(i + 1)) for i in range(5)}
        return _make_ranker(td, status)

    def test_top_3(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(len(self._ranker(td).get_top_n(3)), 3)

    def test_top_n_larger_than_len(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(len(self._ranker(td).get_top_n(100)), 5)

    def test_top_n_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self._ranker(td).get_top_n(0), [])

    def test_top_n_negative(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self._ranker(td).get_top_n(-3), [])

    def test_top_1_is_best(self):
        with tempfile.TemporaryDirectory() as td:
            top = self._ranker(td).get_top_n(1)
            self.assertEqual(top[0].rank, 1)

    def test_top_n_empty_ranker(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {})
            self.assertEqual(r.get_top_n(5), [])


# ---------------------------------------------------------------------------
# get_by_tier
# ---------------------------------------------------------------------------

class TestGetByTier(unittest.TestCase):
    def _ranker(self, td):
        status = {
            "a": _entry(apy=5.0, tier="T1"),
            "b": _entry(apy=6.0, tier="T2"),
            "c": _entry(apy=7.0, tier="T1"),
        }
        return _make_ranker(td, status)

    def test_t1_count(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(len(self._ranker(td).get_by_tier("T1")), 2)

    def test_t2_count(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(len(self._ranker(td).get_by_tier("T2")), 1)

    def test_case_insensitive_lower(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(len(self._ranker(td).get_by_tier("t1")), 2)

    def test_case_insensitive_mixed(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(len(self._ranker(td).get_by_tier(" t1 ")), 2)

    def test_nonexistent_tier_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self._ranker(td).get_by_tier("T99"), [])

    def test_returns_sorted(self):
        with tempfile.TemporaryDirectory() as td:
            # T1: a(apy5)->ras10, c(apy7)->ras14 ; sorted desc => c first
            names = [a.name for a in self._ranker(td).get_by_tier("T1")]
            self.assertEqual(names, ["c", "a"])

    def test_tier_conditional(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0, tier="T2-conditional")})
            self.assertEqual(len(r.get_by_tier("T2-CONDITIONAL")), 1)


# ---------------------------------------------------------------------------
# get_tier_leaders
# ---------------------------------------------------------------------------

class TestTierLeaders(unittest.TestCase):
    def test_best_per_tier(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "a": _entry(apy=5.0, tier="T1"),   # ras 10
                "c": _entry(apy=7.0, tier="T1"),   # ras 14 -> leader
                "b": _entry(apy=6.0, tier="T2"),
            }
            r = _make_ranker(td, status)
            leaders = r.get_tier_leaders()
            self.assertEqual(leaders["T1"], "c")
            self.assertEqual(leaders["T2"], "b")

    def test_normalized_uppercase(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0, tier="t1")})
            self.assertIn("T1", r.get_tier_leaders())

    def test_empty_tier_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0, tier="")})
            self.assertEqual(r.get_tier_leaders().get("UNKNOWN"), "x")

    def test_no_eligible_empty(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0, usdc_price=0.5)})
            self.assertEqual(r.get_tier_leaders(), {})

    def test_excluded_not_in_leaders(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "ok": _entry(apy=5.0, tier="T1"),
                "bad": _entry(apy=99.0, tier="T1", usdc_price=0.5),
            }
            r = _make_ranker(td, status)
            self.assertEqual(r.get_tier_leaders()["T1"], "ok")


# ---------------------------------------------------------------------------
# get_report
# ---------------------------------------------------------------------------

class TestGetReport(unittest.TestCase):
    def test_total_adapters_includes_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "ok": _entry(apy=5.0),
                "bad": _entry(apy=5.0, usdc_price=0.5),
            }
            r = _make_ranker(td, status)
            report = r.get_report()
            self.assertEqual(report.total_adapters, 2)
            self.assertEqual(report.eligible_count, 1)

    def test_best_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "lo": _entry(apy=4.0),
                "hi": _entry(apy=10.0),
            }
            r = _make_ranker(td, status)
            self.assertEqual(r.get_report().best_adapter, "hi")

    def test_best_score_matches_top(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=10.0, risk_score=0.5)})
            self.assertAlmostEqual(r.get_report().best_score, 20.0)

    def test_empty_report_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {})
            report = r.get_report()
            self.assertEqual(report.best_adapter, "")
            self.assertEqual(report.best_score, 0.0)
            self.assertEqual(report.eligible_count, 0)

    def test_generated_at_iso(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry()})
            self.assertIn("T", r.get_report().generated_at)

    def test_ranked_type(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry()})
            report = r.get_report()
            self.assertIsInstance(report.ranked[0], RankedAdapter)

    def test_tier_leaders_present(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0, tier="T1")})
            self.assertIn("T1", r.get_report().top_tier_leaders)


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

class TestToDict(unittest.TestCase):
    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "a": _entry(apy=5.0, tier="T1"),
                "b": _entry(apy=6.0, tier="T2", usdc_price=0.5),
            }
            r = _make_ranker(td, status)
            json.dumps(r.to_dict())

    def test_has_expected_keys(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry()})
            d = r.to_dict()
            self.assertIn("ranked", d)
            self.assertIn("total_adapters", d)

    def test_empty_serializable(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {})
            json.dumps(r.to_dict())

    def test_ranked_entries_are_dicts(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry()})
            d = r.to_dict()
            self.assertIsInstance(d["ranked"][0], dict)


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "risk_adjusted_report.json")
            path = r.save_report(output_path=out)
            self.assertTrue(os.path.exists(path))

    def test_default_output_path(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            path = r.save_report()
            self.assertTrue(path.endswith("risk_adjusted_report.json"))
            self.assertTrue(os.path.exists(path))

    def test_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "rep.json")
            r.save_report(output_path=out)
            with open(out) as fh:
                data = json.load(fh)
            self.assertIn("snapshots", data)
            self.assertIn("latest", data)

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "rep.json")
            r.save_report(output_path=out)
            self.assertFalse(os.path.exists(out + ".tmp"))

    def test_ring_buffer_caps_at_30(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "rep.json")
            for _ in range(35):
                r.save_report(output_path=out)
            with open(out) as fh:
                data = json.load(fh)
            self.assertLessEqual(len(data["snapshots"]), 30)
            self.assertEqual(len(data["snapshots"]), 30)

    def test_ring_buffer_grows(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "rep.json")
            r.save_report(output_path=out)
            r.save_report(output_path=out)
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(len(data["snapshots"]), 2)

    def test_idempotent_shape(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "rep.json")
            r.save_report(output_path=out)
            with open(out) as fh:
                d1 = json.load(fh)
            r.save_report(output_path=out)
            with open(out) as fh:
                d2 = json.load(fh)
            self.assertEqual(set(d1.keys()), set(d2.keys()))

    def test_schema_version(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "rep.json")
            r.save_report(output_path=out)
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(data["schema_version"], 1)

    def test_latest_matches_last_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "rep.json")
            r.save_report(output_path=out)
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(data["latest"], data["snapshots"][-1])

    def test_recovers_from_corrupt_existing(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "rep.json")
            with open(out, "w") as fh:
                fh.write("{corrupt")
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            r.save_report(output_path=out)
            with open(out) as fh:
                data = json.load(fh)
            self.assertEqual(len(data["snapshots"]), 1)

    def test_does_not_touch_production(self):
        # ensure tests use isolated paths
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0)})
            out = os.path.join(td, "isolated.json")
            path = r.save_report(output_path=out)
            self.assertTrue(path.startswith(td))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_empty_adapter_status(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {})
            self.assertEqual(r.rank_all(), [])
            self.assertEqual(r.get_excluded(), [])
            self.assertEqual(r.get_tier_leaders(), {})

    def test_all_non_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            status = {
                "a": _entry(apy=5.0, usdc_price=0.5),
                "b": _entry(apy=-1.0),
            }
            r = _make_ranker(td, status)
            self.assertEqual(r.rank_all(), [])
            self.assertEqual(len(r.get_excluded()), 2)

    def test_single_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=5.0, tier="T1")})
            report = r.get_report()
            self.assertEqual(report.total_adapters, 1)
            self.assertEqual(report.eligible_count, 1)
            self.assertEqual(report.best_adapter, "x")

    def test_missing_file_no_crash(self):
        r = RiskAdjustedRanker(data_path="/no/such/file.json")
        self.assertEqual(r.rank_all(), [])
        self.assertEqual(r.get_report().total_adapters, 0)

    def test_many_adapters(self):
        with tempfile.TemporaryDirectory() as td:
            status = {f"a{i}": _entry(apy=float(i + 1)) for i in range(50)}
            r = _make_ranker(td, status)
            ranked = r.rank_all()
            self.assertEqual(len(ranked), 50)
            self.assertEqual(ranked[0].rank, 1)
            self.assertEqual(ranked[-1].rank, 50)

    def test_zero_apy_eligible_in_ranking(self):
        with tempfile.TemporaryDirectory() as td:
            r = _make_ranker(td, {"x": _entry(apy=0.0)})
            self.assertEqual(len(r.rank_all()), 1)


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    def test_main_check_returns_zero(self):
        from spa_core.analytics.risk_adjusted_ranker import main
        rc = main(["--check"])
        self.assertEqual(rc, 0)

    def test_main_default_returns_zero(self):
        from spa_core.analytics.risk_adjusted_ranker import main
        rc = main([])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
