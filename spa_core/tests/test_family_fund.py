"""
Tests for spa_core/family_fund/ — Phase 0 Skeleton
50+ unit tests covering models, registry, pnl_attribution, telegram_blast.
Pure stdlib. No external dependencies. No real Telegram calls.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path when running tests directly
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.family_fund.models import FundSnapshot, Investor, InvestorStatement
from spa_core.family_fund.registry import InvestorRegistry
from spa_core.family_fund.pnl_attribution import PnLAttributor
from spa_core.family_fund.telegram_blast import TelegramBlast


# ======================================================================
# Helpers
# ======================================================================

def _make_investor(
    id_="inv-001",
    name="Alice",
    email="alice@example.com",
    wallet_address="0xABCDEF",
    joined_at="2026-06-12T00:00:00Z",
    initial_capital_usd=50000.0,
    current_share_pct=100.0,
    status="active",
    notes="",
) -> Investor:
    return Investor(
        id=id_,
        name=name,
        email=email,
        wallet_address=wallet_address,
        joined_at=joined_at,
        initial_capital_usd=initial_capital_usd,
        current_share_pct=current_share_pct,
        status=status,
        notes=notes,
    )


def _make_statement(
    investor_id="inv-001",
    period="2026-06",
    opening_balance=50000.0,
    closing_balance=50500.0,
    pnl_usd=500.0,
    pnl_pct=1.0,
    apy_annualized=12.68,
    generated_at="2026-06-30T00:00:00Z",
) -> InvestorStatement:
    return InvestorStatement(
        investor_id=investor_id,
        period=period,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        apy_annualized=apy_annualized,
        generated_at=generated_at,
    )


def _make_snapshot(
    snapshot_date="2026-06-30",
    total_aum_usd=100000.0,
    nav_per_share=1.005,
    investor_count=2,
    strategy_mix=None,
    realized_apy=6.0,
) -> FundSnapshot:
    return FundSnapshot(
        snapshot_date=snapshot_date,
        total_aum_usd=total_aum_usd,
        nav_per_share=nav_per_share,
        investor_count=investor_count,
        strategy_mix=strategy_mix or {"S0": 0.6, "S1": 0.4},
        realized_apy=realized_apy,
    )


# ======================================================================
# 1. Investor Dataclass Tests
# ======================================================================

class TestInvestorModel(unittest.TestCase):

    def test_create_basic(self):
        inv = _make_investor()
        self.assertEqual(inv.id, "inv-001")
        self.assertEqual(inv.name, "Alice")
        self.assertEqual(inv.email, "alice@example.com")
        self.assertEqual(inv.status, "active")

    def test_to_dict_roundtrip(self):
        inv = _make_investor()
        d = inv.to_dict()
        inv2 = Investor.from_dict(d)
        self.assertEqual(inv, inv2)

    def test_to_json_roundtrip(self):
        inv = _make_investor()
        s = inv.to_json()
        inv2 = Investor.from_json(s)
        self.assertEqual(inv, inv2)

    def test_from_dict_defaults(self):
        d = {
            "id": "x", "name": "Bob", "email": "bob@x.com",
            "wallet_address": "", "joined_at": "2026-01-01T00:00:00Z",
            "initial_capital_usd": 1000.0,
        }
        inv = Investor.from_dict(d)
        self.assertEqual(inv.current_share_pct, 0.0)
        self.assertEqual(inv.status, "pending")
        self.assertEqual(inv.notes, "")

    def test_validate_ok(self):
        _make_investor().validate()  # no exception

    def test_validate_bad_email(self):
        inv = _make_investor(email="notanemail")
        with self.assertRaises(ValueError):
            inv.validate()

    def test_validate_bad_status(self):
        inv = _make_investor(status="unknown")
        with self.assertRaises(ValueError):
            inv.validate()

    def test_validate_negative_capital(self):
        inv = _make_investor(initial_capital_usd=-1.0)
        with self.assertRaises(ValueError):
            inv.validate()

    def test_validate_share_out_of_range(self):
        inv = _make_investor(current_share_pct=101.0)
        with self.assertRaises(ValueError):
            inv.validate()

    def test_validate_empty_id(self):
        inv = _make_investor(id_="")
        with self.assertRaises(ValueError):
            inv.validate()

    def test_all_statuses_valid(self):
        for status in ("active", "pending", "exited"):
            _make_investor(status=status).validate()

    def test_notes_field_default(self):
        inv = _make_investor()
        self.assertEqual(inv.notes, "")


# ======================================================================
# 2. InvestorStatement Dataclass Tests
# ======================================================================

class TestInvestorStatementModel(unittest.TestCase):

    def test_create_basic(self):
        stmt = _make_statement()
        self.assertEqual(stmt.investor_id, "inv-001")
        self.assertEqual(stmt.period, "2026-06")
        self.assertAlmostEqual(stmt.pnl_usd, 500.0)

    def test_to_dict_roundtrip(self):
        stmt = _make_statement()
        d = stmt.to_dict()
        stmt2 = InvestorStatement.from_dict(d)
        self.assertEqual(stmt, stmt2)

    def test_to_json_roundtrip(self):
        stmt = _make_statement()
        s = stmt.to_json()
        stmt2 = InvestorStatement.from_json(s)
        self.assertEqual(stmt, stmt2)

    def test_validate_ok(self):
        _make_statement().validate()

    def test_validate_bad_period(self):
        stmt = _make_statement(period="June-2026")
        with self.assertRaises(ValueError):
            stmt.validate()

    def test_validate_negative_opening(self):
        stmt = _make_statement(opening_balance=-1.0)
        with self.assertRaises(ValueError):
            stmt.validate()

    def test_validate_empty_investor_id(self):
        stmt = _make_statement(investor_id="")
        with self.assertRaises(ValueError):
            stmt.validate()


# ======================================================================
# 3. FundSnapshot Dataclass Tests
# ======================================================================

class TestFundSnapshotModel(unittest.TestCase):

    def test_create_basic(self):
        snap = _make_snapshot()
        self.assertEqual(snap.snapshot_date, "2026-06-30")
        self.assertAlmostEqual(snap.total_aum_usd, 100000.0)

    def test_to_dict_roundtrip(self):
        snap = _make_snapshot()
        d = snap.to_dict()
        snap2 = FundSnapshot.from_dict(d)
        self.assertEqual(snap, snap2)

    def test_to_json_roundtrip(self):
        snap = _make_snapshot()
        s = snap.to_json()
        snap2 = FundSnapshot.from_json(s)
        self.assertEqual(snap, snap2)

    def test_validate_ok(self):
        _make_snapshot().validate()

    def test_validate_bad_date(self):
        snap = _make_snapshot(snapshot_date="2026-06")
        with self.assertRaises(ValueError):
            snap.validate()

    def test_validate_bad_mix_sum(self):
        snap = _make_snapshot(strategy_mix={"S0": 0.6, "S1": 0.6})
        with self.assertRaises(ValueError):
            snap.validate()

    def test_validate_negative_aum(self):
        snap = _make_snapshot(total_aum_usd=-1.0)
        with self.assertRaises(ValueError):
            snap.validate()

    def test_validate_zero_nav(self):
        snap = _make_snapshot(nav_per_share=0.0)
        with self.assertRaises(ValueError):
            snap.validate()

    def test_empty_strategy_mix_ok(self):
        snap = _make_snapshot(strategy_mix={})
        snap.validate()  # empty mix is valid


# ======================================================================
# 4. InvestorRegistry CRUD Tests
# ======================================================================

class TestInvestorRegistry(unittest.TestCase):

    def setUp(self):
        # Use a temporary directory for each test
        self._tmpdir = tempfile.mkdtemp()
        self._path = Path(self._tmpdir) / "investors.json"
        self.reg = InvestorRegistry(investors_path=self._path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_load_empty(self):
        investors = self.reg.load()
        self.assertEqual(investors, [])

    def test_add_and_load(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        loaded = self.reg.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "inv-001")

    def test_add_duplicate_raises(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        with self.assertRaises(ValueError):
            self.reg.add_investor(inv)

    def test_get_investor_found(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        found = self.reg.get_investor("inv-001")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Alice")

    def test_get_investor_not_found(self):
        result = self.reg.get_investor("nonexistent")
        self.assertIsNone(result)

    def test_update_investor_name(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        updated = self.reg.update_investor("inv-001", name="Alicia")
        self.assertEqual(updated.name, "Alicia")
        # persisted
        loaded = self.reg.get_investor("inv-001")
        self.assertEqual(loaded.name, "Alicia")

    def test_update_investor_not_found(self):
        with self.assertRaises(KeyError):
            self.reg.update_investor("ghost", name="X")

    def test_update_unknown_field_raises(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        with self.assertRaises(ValueError):
            self.reg.update_investor("inv-001", nonexistent_field="x")

    def test_active_investors_filter(self):
        active = _make_investor(id_="a1", status="active")
        pending = _make_investor(id_="a2", email="b@x.com", status="pending")
        exited = _make_investor(id_="a3", email="c@x.com", status="exited")
        for inv in (active, pending, exited):
            self.reg.add_investor(inv)
        active_list = self.reg.active_investors()
        self.assertEqual(len(active_list), 1)
        self.assertEqual(active_list[0].id, "a1")

    def test_total_capital_usd_active_only(self):
        self.reg.add_investor(_make_investor(id_="a1", initial_capital_usd=60000.0, status="active"))
        self.reg.add_investor(_make_investor(id_="a2", email="b@x.com", initial_capital_usd=40000.0, status="pending"))
        total = self.reg.total_capital_usd()
        self.assertAlmostEqual(total, 60000.0)

    def test_recompute_shares_single_investor(self):
        inv = _make_investor(initial_capital_usd=100000.0, current_share_pct=0.0)
        self.reg.add_investor(inv)
        loaded = self.reg.get_investor("inv-001")
        self.assertAlmostEqual(loaded.current_share_pct, 100.0)

    def test_recompute_shares_two_investors(self):
        inv1 = _make_investor(id_="a", initial_capital_usd=60000.0)
        inv2 = _make_investor(id_="b", email="b@x.com", initial_capital_usd=40000.0)
        self.reg.add_investor(inv1)
        self.reg.add_investor(inv2)
        a = self.reg.get_investor("a")
        b = self.reg.get_investor("b")
        self.assertAlmostEqual(a.current_share_pct, 60.0, places=2)
        self.assertAlmostEqual(b.current_share_pct, 40.0, places=2)

    def test_recompute_shares_exited_investor_zero(self):
        inv1 = _make_investor(id_="a", initial_capital_usd=50000.0)
        inv2 = _make_investor(id_="b", email="b@x.com", initial_capital_usd=50000.0, status="exited")
        self.reg.add_investor(inv1)
        self.reg.add_investor(inv2)
        b = self.reg.get_investor("b")
        self.assertEqual(b.current_share_pct, 0.0)

    def test_atomic_write_creates_file(self):
        self.assertFalse(self._path.exists())
        inv = _make_investor()
        self.reg.add_investor(inv)
        self.assertTrue(self._path.exists())

    def test_file_is_valid_json_after_save(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        with open(self._path, "r") as fh:
            data = json.load(fh)
        self.assertIn("investors", data)
        self.assertEqual(len(data["investors"]), 1)

    def test_save_then_load_idempotent(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        investors = self.reg.load()
        self.reg.save(investors)
        investors2 = self.reg.load()
        self.assertEqual(len(investors2), 1)


# ======================================================================
# 5. PnLAttributor Tests (with mock data)
# ======================================================================

_MOCK_EQUITY_CURVE = [
    {"date": "2026-05-31", "equity": 100000.0},
    {"date": "2026-06-01", "equity": 100100.0},
    {"date": "2026-06-15", "equity": 100500.0},
    {"date": "2026-06-30", "equity": 101000.0},
]


class TestPnLAttributor(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data_dir = Path(self._tmpdir)

        # Write mock equity curve
        curve_path = data_dir / "equity_curve_daily.json"
        with open(curve_path, "w") as fh:
            json.dump(_MOCK_EQUITY_CURVE, fh)

        # Registry with investors
        investors_path = data_dir / "investors.json"
        self.reg = InvestorRegistry(investors_path=investors_path)
        inv1 = _make_investor(id_="i1", initial_capital_usd=60000.0)
        inv2 = _make_investor(id_="i2", email="bob@x.com", initial_capital_usd=40000.0)
        self.reg.add_investor(inv1)
        self.reg.add_investor(inv2)

        self.attributor = PnLAttributor(data_dir=data_dir, registry=self.reg)
        self._data_dir = data_dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_compute_period_pnl_returns_two_statements(self):
        result = self.attributor.compute_period_pnl("2026-06")
        self.assertEqual(len(result), 2)
        self.assertIn("i1", result)
        self.assertIn("i2", result)

    def test_compute_period_pnl_fund_pnl_correct(self):
        # opening = 100000 (2026-05-31), closing = 101000 (2026-06-30)
        result = self.attributor.compute_period_pnl("2026-06")
        total = sum(s.pnl_usd for s in result.values())
        self.assertAlmostEqual(total, 1000.0, places=1)

    def test_compute_period_pnl_proportional_split(self):
        result = self.attributor.compute_period_pnl("2026-06")
        pnl_i1 = result["i1"].pnl_usd
        pnl_i2 = result["i2"].pnl_usd
        # i1 = 60%, i2 = 40%
        self.assertAlmostEqual(pnl_i1, 600.0, places=1)
        self.assertAlmostEqual(pnl_i2, 400.0, places=1)

    def test_compute_period_pnl_closing_balance(self):
        result = self.attributor.compute_period_pnl("2026-06")
        closing_i1 = result["i1"].closing_balance
        # 60% of 101000
        self.assertAlmostEqual(closing_i1, 60600.0, places=1)

    def test_compute_period_pnl_apy_positive(self):
        result = self.attributor.compute_period_pnl("2026-06")
        for stmt in result.values():
            self.assertGreater(stmt.apy_annualized, 0.0)

    def test_generate_all_statements_saves_files(self):
        statements = self.attributor.generate_all_statements("2026-06")
        self.assertEqual(len(statements), 2)
        stmts_dir = self._data_dir / "statements"
        self.assertTrue(stmts_dir.exists())
        files = list(stmts_dir.glob("*.json"))
        self.assertEqual(len(files), 2)

    def test_generate_all_statements_json_valid(self):
        self.attributor.generate_all_statements("2026-06")
        stmts_dir = self._data_dir / "statements"
        for f in stmts_dir.glob("*.json"):
            with open(f) as fh:
                d = json.load(fh)
            self.assertIn("investor_id", d)
            self.assertIn("pnl_usd", d)

    def test_fund_summary_keys(self):
        summary = self.attributor.fund_summary("2026-06")
        for key in ("period", "total_aum_usd", "total_pnl_usd",
                    "active_investors", "apy_annualized"):
            self.assertIn(key, summary)

    def test_fund_summary_total_pnl(self):
        summary = self.attributor.fund_summary("2026-06")
        self.assertAlmostEqual(summary["total_pnl_usd"], 1000.0, places=1)

    def test_fund_summary_active_investors(self):
        summary = self.attributor.fund_summary("2026-06")
        self.assertEqual(summary["active_investors"], 2)

    def test_empty_curve_returns_zero_pnl(self):
        # No equity curve file
        data_dir = Path(tempfile.mkdtemp())
        inv_path = data_dir / "investors.json"
        reg = InvestorRegistry(investors_path=inv_path)
        reg.add_investor(_make_investor())
        attributor = PnLAttributor(data_dir=data_dir, registry=reg)
        result = attributor.compute_period_pnl("2026-06")
        for stmt in result.values():
            self.assertEqual(stmt.pnl_usd, 0.0)

    def test_no_active_investors_empty_result(self):
        data_dir = Path(tempfile.mkdtemp())
        inv_path = data_dir / "investors.json"
        reg = InvestorRegistry(investors_path=inv_path)
        inv = _make_investor(status="exited")
        reg.add_investor(inv)
        curve_path = data_dir / "equity_curve_daily.json"
        with open(curve_path, "w") as fh:
            json.dump(_MOCK_EQUITY_CURVE, fh)
        attributor = PnLAttributor(data_dir=data_dir, registry=reg)
        result = attributor.compute_period_pnl("2026-06")
        self.assertEqual(len(result), 0)


# ======================================================================
# 6. TelegramBlast Tests (mock subprocess — no real HTTP)
# ======================================================================

class TestTelegramBlast(unittest.TestCase):

    def _blast_with_overrides(self) -> TelegramBlast:
        """Return a TelegramBlast that bypasses Keychain."""
        return TelegramBlast(token="fake-token-123", chat_id="-100987654")

    def test_get_token_calls_security(self):
        blast = TelegramBlast()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="mytoken\n", stderr="")
            token = blast._get_token("TELEGRAM_BOT_TOKEN_SPA")
        self.assertEqual(token, "mytoken")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("security", args)
        self.assertIn("TELEGRAM_BOT_TOKEN_SPA", args)

    def test_get_token_raises_on_failure(self):
        blast = TelegramBlast()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
            with self.assertRaises(RuntimeError):
                blast._get_token("MISSING_KEY")

    def test_resolve_credentials_uses_overrides(self):
        blast = self._blast_with_overrides()
        token, chat_id = blast._resolve_credentials()
        self.assertEqual(token, "fake-token-123")
        self.assertEqual(chat_id, "-100987654")

    def test_resolve_credentials_calls_keychain_when_no_override(self):
        blast = TelegramBlast()
        with patch.object(blast, "_get_token", return_value="tok") as mock_get:
            blast._resolve_credentials()
        self.assertEqual(mock_get.call_count, 2)

    def test_send_monthly_report_calls_post(self):
        blast = self._blast_with_overrides()
        statements = [_make_statement("i1"), _make_statement("i2", pnl_usd=300.0)]
        with patch.object(blast, "_post", return_value={"ok": True}) as mock_post:
            result = blast.send_monthly_report("2026-06", statements)
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        text = call_args[0][2]
        self.assertIn("SPA Monthly Report", text)
        self.assertIn("June 2026", text)

    def test_send_monthly_report_contains_investor_count(self):
        blast = self._blast_with_overrides()
        statements = [_make_statement("i1"), _make_statement("i2")]
        with patch.object(blast, "_post", return_value={"ok": True}) as mock_post:
            blast.send_monthly_report("2026-06", statements)
        text = mock_post.call_args[0][2]
        self.assertIn("2", text)  # Investors: 2

    def test_send_monthly_report_empty_statements(self):
        blast = self._blast_with_overrides()
        with patch.object(blast, "_post", return_value={"ok": True}) as mock_post:
            blast.send_monthly_report("2026-06", [])
        mock_post.assert_called_once()

    def test_send_alert_info(self):
        blast = self._blast_with_overrides()
        with patch.object(blast, "_post", return_value={"ok": True}) as mock_post:
            blast.send_alert("Test message", level="info")
        text = mock_post.call_args[0][2]
        self.assertIn("INFO", text)
        self.assertIn("Test message", text)

    def test_send_alert_warn(self):
        blast = self._blast_with_overrides()
        with patch.object(blast, "_post", return_value={"ok": True}) as mock_post:
            blast.send_alert("Watch out", level="warn")
        text = mock_post.call_args[0][2]
        self.assertIn("WARN", text)
        self.assertIn("⚠️", text)

    def test_send_alert_critical(self):
        blast = self._blast_with_overrides()
        with patch.object(blast, "_post", return_value={"ok": True}) as mock_post:
            blast.send_alert("Critical!", level="critical")
        text = mock_post.call_args[0][2]
        self.assertIn("CRITICAL", text)
        self.assertIn("🚨", text)

    def test_send_alert_unknown_level_defaults(self):
        blast = self._blast_with_overrides()
        with patch.object(blast, "_post", return_value={"ok": True}) as mock_post:
            blast.send_alert("Msg", level="weird_level")
        text = mock_post.call_args[0][2]
        self.assertIn("Msg", text)

    def test_post_uses_correct_url(self):
        blast = self._blast_with_overrides()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = b'{"ok":true,"result":{}}'
            mock_urlopen.return_value = mock_resp
            blast.send_alert("hello")
        req = mock_urlopen.call_args[0][0]
        self.assertIn("fake-token-123", req.full_url)

    def test_post_sends_json_body(self):
        blast = self._blast_with_overrides()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = b'{"ok":true,"result":{}}'
            mock_urlopen.return_value = mock_resp
            blast.send_alert("test")
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        self.assertIn("chat_id", payload)
        self.assertIn("text", payload)


# ======================================================================
# 7. Atomic Write Behavior Tests
# ======================================================================

class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._path = Path(self._tmpdir) / "investors.json"
        self.reg = InvestorRegistry(investors_path=self._path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_temp_files_left_after_write(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        tmp_files = list(Path(self._tmpdir).glob(".investors_tmp_*"))
        self.assertEqual(len(tmp_files), 0)

    def test_file_valid_json_after_concurrent_writes(self):
        for i in range(5):
            inv = _make_investor(
                id_=f"inv-{i:03d}",
                email=f"user{i}@x.com",
                initial_capital_usd=10000.0 * (i + 1),
            )
            self.reg.add_investor(inv)
        with open(self._path, "r") as fh:
            data = json.load(fh)
        self.assertEqual(len(data["investors"]), 5)

    def test_envelope_metadata_preserved(self):
        inv = _make_investor()
        self.reg.add_investor(inv)
        with open(self._path, "r") as fh:
            data = json.load(fh)
        self.assertIn("fund_name", data)
        self.assertIn("metadata", data)


# ======================================================================
# 8. Import Hygiene
# ======================================================================

class TestImportHygiene(unittest.TestCase):

    def _check_no_external_imports(self, module_path: Path):
        """Assert that a module file has no non-stdlib imports."""
        stdlib_prefixes = (
            "from __future__",
            "from spa_core",
            "import json",
            "import os",
            "import sys",
            "import math",
            "import tempfile",
            "import subprocess",
            "import urllib",
            "import unittest",
            "from dataclasses",
            "from pathlib",
            "from typing",
            "from datetime",
        )
        disallowed = ("fastapi", "flask", "pydantic", "sqlalchemy", "requests",
                      "aiohttp", "httpx")
        content = module_path.read_text(encoding="utf-8")
        for bad in disallowed:
            self.assertNotIn(
                bad, content,
                msg=f"Found disallowed import '{bad}' in {module_path.name}"
            )

    def test_models_no_external_imports(self):
        path = _PROJECT_ROOT / "spa_core" / "family_fund" / "models.py"
        self._check_no_external_imports(path)

    def test_registry_no_external_imports(self):
        path = _PROJECT_ROOT / "spa_core" / "family_fund" / "registry.py"
        self._check_no_external_imports(path)

    def test_pnl_attribution_no_external_imports(self):
        path = _PROJECT_ROOT / "spa_core" / "family_fund" / "pnl_attribution.py"
        self._check_no_external_imports(path)

    def test_telegram_blast_no_external_imports(self):
        path = _PROJECT_ROOT / "spa_core" / "family_fund" / "telegram_blast.py"
        self._check_no_external_imports(path)

    def test_no_tokens_in_files(self):
        """Verify no hardcoded secrets exist in family_fund source files."""
        forbidden_patterns = ("ghp_", "xoxb-", "xoxp-", "sk-", "bearer ")
        family_fund_dir = _PROJECT_ROOT / "spa_core" / "family_fund"
        for py_file in family_fund_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8").lower()
            for pattern in forbidden_patterns:
                self.assertNotIn(
                    pattern,
                    content,
                    msg=f"Found suspicious pattern '{pattern}' in {py_file.name}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
