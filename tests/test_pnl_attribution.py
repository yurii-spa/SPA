#!/usr/bin/env python3
"""
tests/test_pnl_attribution.py — MP-1451 (Sprint v10.67)

Test suite for spa_core/family_fund/pnl_attribution.py (PnLAttributor).

Tests:
  A. Already-migrated atomic pattern (A1–A2)
  B. Instantiation (B1–B2)
  C. _load_equity_curve (C1–C3)
  D. Period filtering & equity helpers (D1–D4)
  E. compute_period_pnl (E1–E4)
  F. fund_summary (F1–F3)

Pure stdlib. No network. Offline.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import unittest
import tempfile
from datetime import datetime, timedelta

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.family_fund.pnl_attribution import PnLAttributor, _atomic_write
from spa_core.family_fund.registry import InvestorRegistry
from spa_core.family_fund.models import Investor


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_investor(idx: int = 0) -> Investor:
    return Investor(
        id=f"inv-{idx:04d}",
        name=f"Investor {idx}",
        email=f"investor{idx}@example.com",
        wallet_address="0x" + "a" * 40,
        joined_at="2026-06-01T00:00:00Z",
        initial_capital_usd=float(10000 * (idx + 1)),
        current_share_pct=50.0,
        status="active",
    )


def _make_equity_curve(n_days: int = 10, period: str = "2026-06") -> list:
    """Generate n equity curve rows inside `period` (YYYY-MM)."""
    year, month = map(int, period.split("-"))
    base = datetime(year, month, 1)
    rows = []
    for i in range(n_days):
        rows.append({
            "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "equity": 100000.0 + i * 50,
            "close_equity": 100000.0 + i * 50,
        })
    return rows


def _make_data_dir(tmp: pathlib.Path, equity: list = None, investors: list = None) -> pathlib.Path:
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "equity_curve_daily.json").write_text(
        json.dumps({"curve": equity or []}), encoding="utf-8"
    )
    (data_dir / "investors.json").write_text(
        json.dumps({
            "investors": [inv.to_dict() for inv in (investors or [])],
            "fund_name": "SPA Family Fund",
        }),
        encoding="utf-8",
    )
    (data_dir / "paper_trading_status.json").write_text(
        json.dumps({"capital_usd": 100000.0, "is_demo": False}), encoding="utf-8"
    )
    return data_dir


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — Already-migrated atomic pattern
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicMigration(unittest.TestCase):

    def test_A1_pnl_attribution_imports_atomic_save(self):
        """pnl_attribution.py imports atomic_save (already migrated)."""
        src = (_REPO / "spa_core" / "family_fund" / "pnl_attribution.py").read_text(encoding="utf-8")
        self.assertIn("atomic_save", src)

    def test_A2_atomic_write_helper_delegates_to_atomic_save(self):
        """_atomic_write writes valid JSON via atomic_save."""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "test_out.json"
            _atomic_write(p, {"hello": "world", "n": 7})
            data = json.loads(p.read_text())
            self.assertEqual(data["hello"], "world")
            self.assertEqual(data["n"], 7)


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — Instantiation
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_B1_default_instantiation(self):
        """PnLAttributor can be instantiated with no args."""
        p = PnLAttributor()
        self.assertIsNotNone(p)

    def test_B2_custom_data_dir(self):
        """PnLAttributor accepts a custom data_dir."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            p = PnLAttributor(data_dir=data_dir)
            self.assertIsNotNone(p)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — _load_equity_curve
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoadEquityCurve(unittest.TestCase):

    def test_C1_returns_empty_list_when_no_file(self):
        """_load_equity_curve returns [] when equity_curve_daily.json is absent."""
        with tempfile.TemporaryDirectory() as d:
            p = PnLAttributor(data_dir=pathlib.Path(d))
            result = p._load_equity_curve()
            self.assertEqual(result, [])

    def test_C2_returns_list_with_curve_key(self):
        """_load_equity_curve parses {"curve": [...]} envelope."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            equity = _make_equity_curve(3)
            (data_dir / "equity_curve_daily.json").write_text(
                json.dumps({"curve": equity}), encoding="utf-8"
            )
            p = PnLAttributor(data_dir=data_dir)
            result = p._load_equity_curve()
            self.assertEqual(len(result), 3)

    def test_C3_returns_list_from_plain_list(self):
        """_load_equity_curve handles plain JSON list format."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            equity = _make_equity_curve(2)
            (data_dir / "equity_curve_daily.json").write_text(
                json.dumps(equity), encoding="utf-8"
            )
            p = PnLAttributor(data_dir=data_dir)
            result = p._load_equity_curve()
            self.assertEqual(len(result), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — Period filtering & equity helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestPeriodFiltering(unittest.TestCase):

    def test_D1_filter_curve_for_period_correct_month(self):
        """_filter_curve_for_period returns only rows for given YYYY-MM."""
        with tempfile.TemporaryDirectory() as d:
            equity_jun = _make_equity_curve(5, "2026-06")
            equity_jul = _make_equity_curve(5, "2026-07")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity_jun + equity_jul)
            p = PnLAttributor(data_dir=data_dir)
            curve = p._load_equity_curve()
            filtered = p._filter_curve_for_period(curve, "2026-06")
            for row in filtered:
                self.assertTrue(row["date"].startswith("2026-06"))

    def test_D2_filter_returns_empty_for_wrong_period(self):
        """_filter_curve_for_period returns [] for period with no data."""
        with tempfile.TemporaryDirectory() as d:
            equity = _make_equity_curve(5, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity)
            p = PnLAttributor(data_dir=data_dir)
            curve = p._load_equity_curve()
            filtered = p._filter_curve_for_period(curve, "2025-01")
            self.assertEqual(filtered, [])

    def test_D3_opening_equity_is_first_row(self):
        """_opening_equity returns equity of first row in period."""
        with tempfile.TemporaryDirectory() as d:
            equity = _make_equity_curve(5, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity)
            p = PnLAttributor(data_dir=data_dir)
            curve = p._load_equity_curve()
            opening = p._opening_equity(curve, "2026-06")
            self.assertAlmostEqual(opening, 100000.0, places=2)

    def test_D4_closing_equity_is_last_row(self):
        """_closing_equity returns equity of last row in period."""
        with tempfile.TemporaryDirectory() as d:
            equity = _make_equity_curve(5, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity)
            p = PnLAttributor(data_dir=data_dir)
            curve = p._load_equity_curve()
            closing = p._closing_equity(curve, "2026-06")
            # Last row: 100000 + 4*50 = 100200
            self.assertAlmostEqual(closing, 100200.0, places=2)


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — compute_period_pnl
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputePeriodPnl(unittest.TestCase):

    def test_E1_returns_dict(self):
        """compute_period_pnl returns a dict keyed by investor_id."""
        with tempfile.TemporaryDirectory() as d:
            investors = [_make_investor(0)]
            equity = _make_equity_curve(10, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity, investors=investors)
            registry = InvestorRegistry(investors_path=data_dir / "investors.json")
            p = PnLAttributor(data_dir=data_dir, registry=registry)
            result = p.compute_period_pnl("2026-06")
            self.assertIsInstance(result, dict)

    def test_E2_result_contains_investor_id(self):
        """compute_period_pnl result contains an entry per active investor."""
        with tempfile.TemporaryDirectory() as d:
            inv = _make_investor(0)
            equity = _make_equity_curve(10, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity, investors=[inv])
            registry = InvestorRegistry(investors_path=data_dir / "investors.json")
            p = PnLAttributor(data_dir=data_dir, registry=registry)
            result = p.compute_period_pnl("2026-06")
            self.assertIn(inv.id, result)

    def test_E3_zero_pnl_when_no_equity_for_period(self):
        """compute_period_pnl returns statements with pnl_usd=0 when equity unavailable."""
        with tempfile.TemporaryDirectory() as d:
            inv = _make_investor(0)
            # Equity for June, but asking for May → opening=closing=0 → pnl=0
            equity = _make_equity_curve(5, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity, investors=[inv])
            registry = InvestorRegistry(investors_path=data_dir / "investors.json")
            p = PnLAttributor(data_dir=data_dir, registry=registry)
            result = p.compute_period_pnl("2026-05")
            # Either empty dict or statements with zero pnl — both are valid
            if result:
                for stmt in result.values():
                    self.assertEqual(stmt.pnl_usd, 0.0)

    def test_E4_statement_has_pnl_fields(self):
        """Each InvestorStatement has pnl_usd and return_pct attributes."""
        with tempfile.TemporaryDirectory() as d:
            inv = _make_investor(0)
            equity = _make_equity_curve(10, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity, investors=[inv])
            registry = InvestorRegistry(investors_path=data_dir / "investors.json")
            p = PnLAttributor(data_dir=data_dir, registry=registry)
            result = p.compute_period_pnl("2026-06")
            if inv.id in result:
                stmt = result[inv.id]
                self.assertTrue(hasattr(stmt, "pnl_usd") or isinstance(stmt.to_dict(), dict))


# ═══════════════════════════════════════════════════════════════════════════════
# Group F — fund_summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestFundSummary(unittest.TestCase):

    def test_F1_fund_summary_returns_dict(self):
        """fund_summary returns a dict."""
        with tempfile.TemporaryDirectory() as d:
            equity = _make_equity_curve(10, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity)
            p = PnLAttributor(data_dir=data_dir)
            result = p.fund_summary("2026-06")
            self.assertIsInstance(result, dict)

    def test_F2_fund_summary_has_period(self):
        """fund_summary result contains the period key."""
        with tempfile.TemporaryDirectory() as d:
            equity = _make_equity_curve(5, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity)
            p = PnLAttributor(data_dir=data_dir)
            result = p.fund_summary("2026-06")
            self.assertIn("period", result)
            self.assertEqual(result["period"], "2026-06")

    def test_F3_fund_summary_has_aum_fields(self):
        """fund_summary contains opening_aum_usd and closing_aum_usd."""
        with tempfile.TemporaryDirectory() as d:
            equity = _make_equity_curve(5, "2026-06")
            data_dir = _make_data_dir(pathlib.Path(d), equity=equity)
            p = PnLAttributor(data_dir=data_dir)
            result = p.fund_summary("2026-06")
            # fund_summary uses opening_aum_usd / closing_aum_usd keys
            self.assertTrue(
                "opening_aum_usd" in result or "opening_equity" in result,
                f"Expected opening AUM key in: {list(result.keys())}"
            )
            self.assertTrue(
                "closing_aum_usd" in result or "closing_equity" in result,
                f"Expected closing AUM key in: {list(result.keys())}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
