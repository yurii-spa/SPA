"""
tests/test_research_progress_telegram.py

30 unit tests for spa_core/alerts/research_progress_telegram.py (MP-1346 v9.62).

Coverage:
  * ResearchProgressTelegram.__init__
  * build_message()   — full message, graceful without any JSON files
  * gate_section()    — contains Backtest and Pre-Paper
  * strategy_section() — contains RS-001 and RS-002
  * source_section()  — contains numeric counts
  * next_steps_section() — at least 1 step
  * send()            — mocked urllib, returns bool

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
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.alerts.research_progress_telegram import ResearchProgressTelegram  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

def _make_base() -> Path:
    td = Path(tempfile.mkdtemp())
    (td / "data" / "backtest").mkdir(parents=True)
    return td


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _populate(base: Path, regime: str = "STABLE") -> None:
    _write_json(
        base / "data" / "backtest" / "pre_paper_backtest_gate.json",
        {
            "status": "PASS",
            "paper_test_can_be_designed": True,
            "paper_trading_allowed": False,
            "generated_at": "2026-06-19",
        },
    )
    _write_json(
        base / "data" / "backtest" / "paper_ready_gate.json",
        {
            "status": "NOT_READY",
            "paper_trading_allowed": False,
            "blockers": ["Owner acceptance not signed", "Paper period incomplete"],
            "generated_at": "2026-06-19",
            "owner_acceptance": {"accepted": False, "owner": None},
        },
    )
    _write_json(
        base / "data" / "market_regime.json",
        {"regime": regime, "t1_avg_apy": 4.58, "recommendation": "hold"},
    )
    _write_json(
        base / "data" / "paper_trading_status.json",
        {"is_demo": False, "days_running": 30, "current_equity": 100020.0, "apy_today_pct": 3.95},
    )


# ===========================================================================
# Tests
# ===========================================================================

class TestInit(unittest.TestCase):
    def test_init_with_explicit_credentials(self):
        rpt = ResearchProgressTelegram(bot_token="tok", chat_id="cid")
        self.assertEqual(rpt._bot_token, "tok")
        self.assertEqual(rpt._chat_id, "cid")

    def test_init_no_credentials(self):
        rpt = ResearchProgressTelegram()
        self.assertIsNone(rpt._bot_token)
        self.assertIsNone(rpt._chat_id)

    def test_init_base_dir(self):
        rpt = ResearchProgressTelegram(base_dir="/tmp/spa")
        self.assertEqual(str(rpt._base_dir), "/tmp/spa")


# ---------------------------------------------------------------------------
class TestBuildMessage(unittest.TestCase):

    def setUp(self):
        self.base = _make_base()
        _populate(self.base)

    def _make(self) -> ResearchProgressTelegram:
        return ResearchProgressTelegram(base_dir=str(self.base))

    def test_build_message_returns_string(self):
        rpt = self._make()
        msg = rpt.build_message()
        self.assertIsInstance(msg, str)

    def test_build_message_not_empty(self):
        rpt = self._make()
        msg = rpt.build_message()
        self.assertTrue(len(msg) > 0)

    def test_build_message_contains_russian(self):
        """Message contains Russian-language keywords."""
        rpt = self._make()
        msg = rpt.build_message()
        self.assertTrue(
            any(word in msg for word in ("Стратеги", "RS-00", "Источник", "Неделя", "Gate"))
        )

    def test_build_message_graceful_no_files(self):
        """build_message() works without any JSON data files."""
        empty = Path(tempfile.mkdtemp())
        rpt   = ResearchProgressTelegram(base_dir=str(empty))
        msg   = rpt.build_message()
        self.assertIsInstance(msg, str)
        self.assertTrue(len(msg) > 0)

    def test_build_message_contains_week_number(self):
        """Header contains a week number."""
        rpt = self._make()
        msg = rpt.build_message()
        self.assertIn("Неделя", msg)

    def test_build_message_contains_research_update(self):
        rpt = self._make()
        msg = rpt.build_message()
        self.assertIn("Research Update", msg)


# ---------------------------------------------------------------------------
class TestGateSection(unittest.TestCase):

    def setUp(self):
        self.base = _make_base()
        _populate(self.base)

    def _make(self) -> ResearchProgressTelegram:
        return ResearchProgressTelegram(base_dir=str(self.base))

    def test_gate_section_returns_string(self):
        rpt = self._make()
        section = rpt.gate_section()
        self.assertIsInstance(section, str)

    def test_gate_section_contains_backtest(self):
        rpt = self._make()
        section = rpt.gate_section()
        self.assertIn("Backtest", section)

    def test_gate_section_contains_pre_paper(self):
        rpt = self._make()
        section = rpt.gate_section()
        self.assertIn("Pre-Paper", section)

    def test_gate_section_graceful_no_files(self):
        """gate_section() works without any JSON data files."""
        empty = Path(tempfile.mkdtemp())
        rpt   = ResearchProgressTelegram(base_dir=str(empty))
        section = rpt.gate_section()
        self.assertIsInstance(section, str)
        self.assertIn("Backtest", section)

    def test_gate_section_shows_pass_when_backtest_passes(self):
        rpt     = self._make()
        section = rpt.gate_section()
        self.assertIn("PASS", section)


# ---------------------------------------------------------------------------
class TestStrategySection(unittest.TestCase):

    def setUp(self):
        self.base = _make_base()
        _populate(self.base)

    def _make(self, regime="STABLE") -> ResearchProgressTelegram:
        _populate(self.base, regime=regime)
        return ResearchProgressTelegram(base_dir=str(self.base))

    def test_strategy_section_returns_string(self):
        rpt = self._make()
        self.assertIsInstance(rpt.strategy_section(), str)

    def test_strategy_section_contains_rs001(self):
        rpt = self._make()
        self.assertIn("RS-001", rpt.strategy_section())

    def test_strategy_section_contains_rs002(self):
        rpt = self._make()
        self.assertIn("RS-002", rpt.strategy_section())

    def test_strategy_section_rs002_paused_in_bear(self):
        rpt     = self._make(regime="BEAR")
        section = rpt.strategy_section()
        self.assertIn("ПРИОСТАНОВЛЕНО", section)

    def test_strategy_section_rs002_allowed_in_bull(self):
        rpt     = self._make(regime="BULL")
        section = rpt.strategy_section()
        self.assertNotIn("ПРИОСТАНОВЛЕНО", section)

    def test_strategy_section_graceful_no_regime_file(self):
        empty = Path(tempfile.mkdtemp())
        rpt   = ResearchProgressTelegram(base_dir=str(empty))
        s     = rpt.strategy_section()
        self.assertIn("RS-001", s)
        self.assertIn("RS-002", s)


# ---------------------------------------------------------------------------
class TestSourceSection(unittest.TestCase):

    def setUp(self):
        self.base = _make_base()
        _populate(self.base)

    def _make(self) -> ResearchProgressTelegram:
        return ResearchProgressTelegram(base_dir=str(self.base))

    def test_source_section_returns_string(self):
        rpt = self._make()
        self.assertIsInstance(rpt.source_section(), str)

    def test_source_section_contains_numbers(self):
        """Source section must contain at least one digit."""
        rpt     = self._make()
        section = rpt.source_section()
        self.assertTrue(any(c.isdigit() for c in section))

    def test_source_section_graceful_no_files(self):
        empty   = Path(tempfile.mkdtemp())
        rpt     = ResearchProgressTelegram(base_dir=str(empty))
        section = rpt.source_section()
        self.assertIsInstance(section, str)

    def test_source_section_contains_источники(self):
        rpt = self._make()
        self.assertIn("Источники", rpt.source_section())


# ---------------------------------------------------------------------------
class TestNextStepsSection(unittest.TestCase):

    def setUp(self):
        self.base = _make_base()
        _populate(self.base)

    def _make(self) -> ResearchProgressTelegram:
        return ResearchProgressTelegram(base_dir=str(self.base))

    def test_next_steps_returns_string(self):
        rpt = self._make()
        self.assertIsInstance(rpt.next_steps_section(), str)

    def test_next_steps_contains_at_least_one_step(self):
        rpt = self._make()
        section = rpt.next_steps_section()
        # Must contain at least "1."
        self.assertIn("1.", section)

    def test_next_steps_graceful_no_files(self):
        """Falls back to static defaults when gate JSON absent."""
        empty   = Path(tempfile.mkdtemp())
        rpt     = ResearchProgressTelegram(base_dir=str(empty))
        section = rpt.next_steps_section()
        self.assertIsInstance(section, str)
        self.assertIn("1.", section)

    def test_next_steps_contains_следующие(self):
        rpt = self._make()
        self.assertIn("Следующие шаги", rpt.next_steps_section())


# ---------------------------------------------------------------------------
class TestSend(unittest.TestCase):

    def setUp(self):
        self.base = _make_base()
        _populate(self.base)

    def test_send_returns_true_on_success(self):
        rpt = ResearchProgressTelegram(
            bot_token="test_tok",
            chat_id="test_cid",
            base_dir=str(self.base),
        )
        mock_resp       = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        ctx = MagicMock()
        ctx.__enter__ = lambda s: mock_resp
        ctx.__exit__  = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=ctx):
            result = rpt.send()
        self.assertTrue(result)

    def test_send_returns_false_on_network_error(self):
        rpt = ResearchProgressTelegram(
            bot_token="test_tok",
            chat_id="test_cid",
            base_dir=str(self.base),
        )
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = rpt.send()
        self.assertFalse(result)

    def test_send_returns_bool(self):
        rpt = ResearchProgressTelegram(
            bot_token="test_tok",
            chat_id="test_cid",
            base_dir=str(self.base),
        )
        with patch("urllib.request.urlopen", side_effect=Exception("err")):
            result = rpt.send()
        self.assertIsInstance(result, bool)

    def test_send_returns_false_when_no_credentials(self):
        rpt = ResearchProgressTelegram(base_dir=str(self.base))
        with patch.object(
            rpt, "_read_keychain", side_effect=EnvironmentError("no key")
        ):
            result = rpt.send()
        self.assertFalse(result)


# ===========================================================================

if __name__ == "__main__":
    unittest.main()
