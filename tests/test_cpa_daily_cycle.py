"""
tests/test_cpa_daily_cycle.py

40 unit tests for spa_core/backtesting/cpa_daily_cycle.py (MP-1345 v9.61).

Coverage:
  * CPADailyCycle.__init__
  * gate_check()
  * source_status()
  * evidence_update()
  * regime_check()
  * research_gates()
  * governance_log()
  * save()
  * to_telegram_message()
  * send_telegram()   (urllib mocked)
  * run()             (full cycle, also with missing optional files)

stdlib only, no external dependencies.
All tests use temporary directories for isolation.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path regardless of cwd
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.backtesting.cpa_daily_cycle import CPADailyCycle  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

def _make_base_dir() -> Path:
    """Create a minimal directory tree for CPADailyCycle."""
    td = Path(tempfile.mkdtemp())
    (td / "data" / "backtest").mkdir(parents=True)
    (td / "data" / "cpa").mkdir(parents=True)
    return td


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _write_pre_paper_gate(base: Path, status="PASS") -> None:
    _write_json(
        base / "data" / "backtest" / "pre_paper_backtest_gate.json",
        {
            "status": status,
            "paper_test_can_be_designed": True,
            "paper_trading_allowed": False,
            "generated_at": "2026-06-19",
            "strict_blockers": [],
            "warnings": [],
        },
    )


def _write_paper_ready_gate(base: Path, ready=False) -> None:
    _write_json(
        base / "data" / "backtest" / "paper_ready_gate.json",
        {
            "status": "READY" if ready else "NOT_READY",
            "paper_trading_allowed": ready,
            "blockers": [] if ready else ["Paper period not complete"],
            "generated_at": "2026-06-19",
            "owner_acceptance": {"accepted": False},
        },
    )


def _write_market_regime(base: Path, regime="STABLE") -> None:
    _write_json(
        base / "data" / "market_regime.json",
        {
            "regime": regime,
            "t1_avg_apy": 4.58,
            "recommendation": "hold",
            "detected_at": "2026-06-19T06:00:00Z",
        },
    )


def _write_paper_trading_status(base: Path) -> None:
    _write_json(
        base / "data" / "paper_trading_status.json",
        {
            "is_demo": False,
            "paper_start_date": "2026-05-20",
            "last_cycle_ts": "2026-06-19T06:00:01Z",
            "days_running": 30,
            "current_equity": 100021.69,
            "apy_today_pct": 3.95,
        },
    )


# ===========================================================================
# Test classes
# ===========================================================================

class TestCPADailyCycleInit(unittest.TestCase):
    """__init__ and basic construction."""

    def test_init_default_date_is_today(self):
        """date defaults to today's UTC date."""
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        cycle = CPADailyCycle()
        self.assertEqual(cycle._date, today)

    def test_init_custom_date(self):
        """date can be overridden."""
        cycle = CPADailyCycle(date="2026-01-01")
        self.assertEqual(cycle._date, "2026-01-01")

    def test_init_base_dir_stored(self):
        """base_dir is stored as Path."""
        cycle = CPADailyCycle(base_dir="/tmp/spa_test", date="2026-01-01")
        self.assertEqual(str(cycle._base_dir), "/tmp/spa_test")


# ---------------------------------------------------------------------------
class TestGateCheck(unittest.TestCase):
    """Section 1: gate_check()."""

    def setUp(self):
        self.base = _make_base_dir()
        _write_pre_paper_gate(self.base)
        _write_paper_ready_gate(self.base)

    def test_gate_check_returns_dict(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.gate_check()
        self.assertIsInstance(result, dict)

    def test_gate_check_contains_backtest(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.gate_check()
        self.assertIn("backtest", result)

    def test_gate_check_contains_pre_paper(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.gate_check()
        self.assertIn("pre_paper", result)

    def test_gate_check_contains_paper(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.gate_check()
        self.assertIn("paper", result)

    def test_gate_check_contains_live(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.gate_check()
        self.assertIn("live", result)

    def test_gate_check_missing_dir_graceful(self):
        """If gate files don't exist, returns UNKNOWN rather than raising."""
        empty = Path(tempfile.mkdtemp())
        cycle = CPADailyCycle(base_dir=str(empty), date="2026-06-19")
        result = cycle.gate_check()
        self.assertIsInstance(result, dict)
        self.assertIn("backtest", result)
        self.assertIn(result["backtest"], ("UNKNOWN", "PASS", "FAIL"))

    def test_gate_check_pass_status(self):
        """When pre-paper gate is PASS, backtest state == PASS."""
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.gate_check()
        self.assertEqual(result["backtest"], "PASS")


# ---------------------------------------------------------------------------
class TestSourceStatus(unittest.TestCase):
    """Section 2: source_status()."""

    def setUp(self):
        self.base = _make_base_dir()

    def test_source_status_returns_dict(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.source_status()
        self.assertIsInstance(result, dict)

    def test_source_status_has_total(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.source_status()
        self.assertIn("total", result)

    def test_source_status_has_clean_included(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.source_status()
        self.assertIn("clean_included", result)

    def test_source_status_has_by_state(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.source_status()
        self.assertIn("by_state", result)

    def test_source_status_graceful_no_data(self):
        """Returns zero counts rather than raising when no pipeline data."""
        empty = Path(tempfile.mkdtemp())
        cycle = CPADailyCycle(base_dir=str(empty), date="2026-06-19")
        result = cycle.source_status()
        self.assertIsInstance(result, dict)
        self.assertIn("total", result)


# ---------------------------------------------------------------------------
class TestEvidenceUpdate(unittest.TestCase):
    """Section 3: evidence_update()."""

    def setUp(self):
        self.base = _make_base_dir()

    def test_evidence_update_returns_dict(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.evidence_update()
        self.assertIsInstance(result, dict)

    def test_evidence_update_no_exception_without_paper_data(self):
        """evidence_update() must not raise when paper_trading_status.json absent."""
        empty = Path(tempfile.mkdtemp())
        cycle = CPADailyCycle(base_dir=str(empty), date="2026-06-19")
        # Should not raise
        result = cycle.evidence_update()
        self.assertIsInstance(result, dict)

    def test_evidence_update_paper_active_false_when_missing(self):
        """paper_active is False when file is absent."""
        empty = Path(tempfile.mkdtemp())
        cycle = CPADailyCycle(base_dir=str(empty), date="2026-06-19")
        result = cycle.evidence_update()
        self.assertFalse(result.get("paper_active"))

    def test_evidence_update_days_running_when_file_present(self):
        """days_running is read from status file."""
        _write_paper_trading_status(self.base)
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.evidence_update()
        self.assertTrue(result.get("paper_active"))
        self.assertEqual(result.get("days_running"), 30)

    def test_evidence_update_graceful_malformed_json(self):
        """Returns error dict rather than raising on malformed JSON."""
        (self.base / "data" / "paper_trading_status.json").write_text(
            "NOT JSON", encoding="utf-8"
        )
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.evidence_update()
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
class TestRegimeCheck(unittest.TestCase):
    """Section 4: regime_check()."""

    def setUp(self):
        self.base = _make_base_dir()

    def test_regime_check_returns_dict(self):
        _write_market_regime(self.base, "STABLE")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.regime_check()
        self.assertIsInstance(result, dict)

    def test_regime_check_regime_key_present(self):
        _write_market_regime(self.base, "STABLE")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.regime_check()
        self.assertIn("regime", result)

    def test_regime_check_bull_normalised(self):
        """BULL regime → 'bull'."""
        _write_market_regime(self.base, "BULL")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.regime_check()
        self.assertEqual(result["regime"], "bull")

    def test_regime_check_bear_normalised(self):
        """BEAR regime → 'bear'."""
        _write_market_regime(self.base, "BEAR")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.regime_check()
        self.assertEqual(result["regime"], "bear")

    def test_regime_check_stable_normalised_to_neutral(self):
        """STABLE regime → 'neutral'."""
        _write_market_regime(self.base, "STABLE")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.regime_check()
        self.assertEqual(result["regime"], "neutral")

    def test_regime_check_sideways_normalised_to_neutral(self):
        """SIDEWAYS regime → 'neutral'."""
        _write_market_regime(self.base, "SIDEWAYS")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.regime_check()
        self.assertEqual(result["regime"], "neutral")

    def test_regime_check_defaults_neutral_when_missing(self):
        """Returns regime='neutral' when market_regime.json absent."""
        empty = Path(tempfile.mkdtemp())
        cycle = CPADailyCycle(base_dir=str(empty), date="2026-06-19")
        result = cycle.regime_check()
        self.assertEqual(result.get("regime"), "neutral")

    def test_regime_check_valid_enum(self):
        """Returned regime is always one of: bull / bear / neutral."""
        for raw in ("BULL", "BEAR", "SIDEWAYS", "VOLATILE", "STABLE"):
            _write_market_regime(self.base, raw)
            cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
            regime = cycle.regime_check().get("regime")
            self.assertIn(regime, ("bull", "bear", "neutral"), msg=f"raw={raw}")


# ---------------------------------------------------------------------------
class TestResearchGates(unittest.TestCase):
    """Section 5: research_gates()."""

    def setUp(self):
        self.base = _make_base_dir()

    def test_research_gates_returns_dict(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.research_gates()
        self.assertIsInstance(result, dict)

    def test_research_gates_contains_rs001(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.research_gates()
        self.assertIn("RS-001", result)

    def test_research_gates_contains_rs002(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.research_gates()
        self.assertIn("RS-002", result)

    def test_research_gates_rs001_always_allowed(self):
        """RS-001 must be allowed in all regimes."""
        for regime in ("BULL", "BEAR", "STABLE"):
            _write_market_regime(self.base, regime)
            cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
            rs001 = cycle.research_gates().get("RS-001", {})
            self.assertTrue(rs001.get("allowed"), msg=f"RS-001 blocked in {regime}")

    def test_research_gates_rs002_paused_in_bear(self):
        """RS-002 must be paused when regime == bear."""
        _write_market_regime(self.base, "BEAR")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        rs002 = cycle.research_gates().get("RS-002", {})
        self.assertFalse(rs002.get("allowed"))

    def test_research_gates_rs002_allowed_in_bull(self):
        """RS-002 is allowed in bull regime."""
        _write_market_regime(self.base, "BULL")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        rs002 = cycle.research_gates().get("RS-002", {})
        self.assertTrue(rs002.get("allowed"))

    def test_research_gates_rs002_allowed_in_neutral(self):
        """RS-002 is allowed in neutral/stable regime."""
        _write_market_regime(self.base, "STABLE")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        rs002 = cycle.research_gates().get("RS-002", {})
        self.assertTrue(rs002.get("allowed"))

    def test_research_gates_regime_key_present(self):
        """research_gates() includes the normalised regime label."""
        _write_market_regime(self.base, "STABLE")
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.research_gates()
        self.assertIn("regime", result)


# ---------------------------------------------------------------------------
class TestGovernanceLog(unittest.TestCase):
    """Section 6: governance_log()."""

    def setUp(self):
        self.base = _make_base_dir()

    def test_governance_log_returns_dict(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.governance_log()
        self.assertIsInstance(result, dict)

    def test_governance_log_contains_date(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.governance_log()
        self.assertIn("date", result)
        self.assertEqual(result["date"], "2026-06-19")

    def test_governance_log_graceful_no_file(self):
        """Returns dict with pending_proposals=0 when file absent."""
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.governance_log()
        self.assertEqual(result.get("pending_proposals"), 0)

    def test_governance_log_counts_pending(self):
        """Counts events with status=pending."""
        _write_json(
            self.base / "data" / "governance_events.json",
            [
                {"status": "pending", "id": "gov-1"},
                {"status": "closed",  "id": "gov-2"},
                {"status": "pending", "id": "gov-3"},
            ],
        )
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = cycle.governance_log()
        self.assertEqual(result.get("pending_proposals"), 2)


# ---------------------------------------------------------------------------
class TestSave(unittest.TestCase):
    """save() method."""

    def setUp(self):
        self.base = _make_base_dir()

    def test_save_creates_file(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = {"date": "2026-06-19", "sections": {}}
        path = cycle.save(result)
        self.assertTrue(Path(path).exists())

    def test_save_file_contains_date_in_name(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = {"date": "2026-06-19", "sections": {}}
        path = cycle.save(result)
        self.assertIn("2026-06-19", Path(path).name)

    def test_save_returns_string_path(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = {"date": "2026-06-19", "sections": {}}
        path = cycle.save(result)
        self.assertIsInstance(path, str)

    def test_save_file_is_valid_json(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        payload = {"date": "2026-06-19", "sections": {"gate_check": {"backtest": "PASS"}}}
        path = cycle.save(payload)
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded["date"], "2026-06-19")

    def test_save_creates_cpa_directory(self):
        """data/cpa/ dir is created if absent."""
        base = Path(tempfile.mkdtemp())
        cycle = CPADailyCycle(base_dir=str(base), date="2026-06-19")
        cycle.save({"date": "2026-06-19", "sections": {}})
        self.assertTrue((base / "data" / "cpa").is_dir())


# ---------------------------------------------------------------------------
class TestToTelegramMessage(unittest.TestCase):
    """to_telegram_message()."""

    def setUp(self):
        self.base = _make_base_dir()
        _write_pre_paper_gate(self.base)
        _write_paper_ready_gate(self.base)
        _write_market_regime(self.base, "STABLE")
        _write_paper_trading_status(self.base)

    def _make_result(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        return {
            "date": "2026-06-19",
            "sections": {
                "gate_check":      cycle.gate_check(),
                "source_status":   cycle.source_status(),
                "evidence_update": cycle.evidence_update(),
                "regime_check":    cycle.regime_check(),
                "research_gates":  cycle.research_gates(),
                "governance_log":  cycle.governance_log(),
            },
        }

    def test_to_telegram_returns_string(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        msg = cycle.to_telegram_message(self._make_result())
        self.assertIsInstance(msg, str)

    def test_to_telegram_not_empty(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        msg = cycle.to_telegram_message(self._make_result())
        self.assertTrue(len(msg) > 0)

    def test_to_telegram_contains_russian(self):
        """Message contains Russian-language keywords."""
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        msg = cycle.to_telegram_message(self._make_result())
        self.assertTrue(
            any(word in msg for word in ("Ворота", "Режим", "Стратеги", "дней", "рынка"))
        )

    def test_to_telegram_contains_date(self):
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        msg = cycle.to_telegram_message(self._make_result())
        self.assertIn("2026-06-19", msg)

    def test_to_telegram_graceful_empty_result(self):
        """to_telegram_message() returns non-empty even on empty sections dict."""
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        msg = cycle.to_telegram_message({"date": "2026-06-19", "sections": {}})
        self.assertIsInstance(msg, str)
        self.assertTrue(len(msg) > 0)


# ---------------------------------------------------------------------------
class TestSendTelegram(unittest.TestCase):
    """send_telegram() — mocked urllib."""

    def setUp(self):
        self.base = _make_base_dir()

    def test_send_telegram_returns_bool(self):
        """send_telegram() returns a bool in all cases."""
        cycle  = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = {"date": "2026-06-19", "sections": {}}
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp       = MagicMock()
            mock_resp.read.return_value = json.dumps({"ok": True}).encode()
            mock_open.return_value.__enter__ = lambda s: mock_resp
            mock_open.return_value.__exit__  = MagicMock(return_value=False)
            outcome = cycle.send_telegram(result)
        self.assertIsInstance(outcome, bool)

    def test_send_telegram_false_on_exception(self):
        """send_telegram() returns False (not raises) when Keychain fails."""
        cycle  = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        result = {"date": "2026-06-19", "sections": {}}
        with patch(
            "spa_core.alerts.telegram_research_alerts._read_keychain",
            side_effect=EnvironmentError("no creds"),
        ):
            outcome = cycle.send_telegram(result)
        self.assertFalse(outcome)


# ---------------------------------------------------------------------------
class TestRun(unittest.TestCase):
    """run() — full cycle integration."""

    def setUp(self):
        self.base = _make_base_dir()
        _write_pre_paper_gate(self.base)
        _write_paper_ready_gate(self.base)
        _write_market_regime(self.base, "STABLE")
        _write_paper_trading_status(self.base)

    def _patched_run(self) -> dict:
        cycle = CPADailyCycle(base_dir=str(self.base), date="2026-06-19")
        with patch(
            "spa_core.alerts.telegram_research_alerts._read_keychain",
            side_effect=EnvironmentError("no creds"),
        ):
            return cycle.run()

    def test_run_returns_dict(self):
        result = self._patched_run()
        self.assertIsInstance(result, dict)

    def test_run_has_date_key(self):
        result = self._patched_run()
        self.assertIn("date", result)

    def test_run_has_sections_key(self):
        result = self._patched_run()
        self.assertIn("sections", result)

    def test_run_sections_contains_gate_check(self):
        result = self._patched_run()
        self.assertIn("gate_check", result["sections"])

    def test_run_sections_contains_source_status(self):
        result = self._patched_run()
        self.assertIn("source_status", result["sections"])

    def test_run_sections_contains_evidence_update(self):
        result = self._patched_run()
        self.assertIn("evidence_update", result["sections"])

    def test_run_sections_contains_regime_check(self):
        result = self._patched_run()
        self.assertIn("regime_check", result["sections"])

    def test_run_sections_contains_research_gates(self):
        result = self._patched_run()
        self.assertIn("research_gates", result["sections"])

    def test_run_sections_contains_governance_log(self):
        result = self._patched_run()
        self.assertIn("governance_log", result["sections"])

    def test_run_sections_contains_telegram(self):
        result = self._patched_run()
        self.assertIn("telegram", result["sections"])

    def test_run_seven_sections_present(self):
        result = self._patched_run()
        self.assertEqual(len(result["sections"]), 7)

    def test_run_no_exception_without_optional_files(self):
        """run() completes without any optional JSON data files."""
        empty = Path(tempfile.mkdtemp())
        (empty / "data" / "backtest").mkdir(parents=True)
        cycle = CPADailyCycle(base_dir=str(empty), date="2026-06-19")
        with patch(
            "spa_core.alerts.telegram_research_alerts._read_keychain",
            side_effect=EnvironmentError("no creds"),
        ):
            result = cycle.run()
        self.assertIsInstance(result, dict)
        self.assertIn("sections", result)


# ===========================================================================

if __name__ == "__main__":
    unittest.main()
