"""Tests for spa_core/governance/kill_switch.py (MP-108).

10+ unit tests covering:
- drawdown trigger (ADR-048: fires at ≥10%, doesn't fire at 9%)
- manual trigger (file-based)
- red_flags trigger (>5 flags)
- sharpe trigger (< -1.0)
- all-cash allocation (all protocols = 0.0)
- deactivate removes file
- no triggers → returns False
- run_kill_switch_check integration
- drill script passes
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from pathlib import Path

# ── Ensure repo root on sys.path ──────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.governance.kill_switch import (
    DRAWDOWN_THRESHOLD_PCT,
    RED_FLAGS_THRESHOLD,
    SHARPE_THRESHOLD,
    KillSwitchChecker,
    run_kill_switch_check,
)


def _make_equity_curve(
    peak: float = 100_000.0,
    drawdown_pct: float = 0.0,
    days: int = 10,
) -> list[dict]:
    """Helper: equity curve с заданной просадкой от peak.

    Bars are dated ON OR AFTER PAPER_REAL_START (2026-06-10) and carry
    ``source="cycle"`` / ``evidenced=True`` so they count as REAL evidenced
    bars (the drawdown trigger now operates strictly over the evidenced series;
    pre-anchor / warmup bars are excluded by design).
    """
    from datetime import date, timedelta
    from spa_core.paper_trading.track_evidence import PAPER_REAL_START

    bars = []
    current = peak
    base = PAPER_REAL_START
    for i in range(days - 1):
        d = base + timedelta(days=i)
        bars.append({
            "date": d.isoformat(),
            "close_equity": round(current, 2),
            "open_equity": round(current, 2),
            "source": "cycle",
            "evidenced": True,
        })
    final = round(peak * (1.0 - drawdown_pct / 100.0), 2)
    bars.append({
        "date": (base + timedelta(days=days - 1)).isoformat(),
        "close_equity": final,
        "open_equity": round(current, 2),
        "source": "cycle",
        "evidenced": True,
    })
    return bars


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


class TestDrawdownTrigger(unittest.TestCase):
    """Tests for check_drawdown_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.checker = KillSwitchChecker(data_dir=self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_drawdown_trigger_fires(self) -> None:
        """Просадка 16% > 15% — должна сработать."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=16.0)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"Expected trigger at 16%, got: reason={reason}")
        self.assertIn("drawdown", reason.lower())

    def test_drawdown_trigger_no_fire_9pct(self) -> None:
        """ADR-048: просадка 9% < 10% — НЕ должна сработать."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=9.0)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"Expected no trigger at 9%, got: reason={reason}")

    def test_drawdown_trigger_fires_exact_threshold(self) -> None:
        """ADR-048: просадка ровно 10% — ДОЛЖНА сработать (граница inclusive >=)."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=DRAWDOWN_THRESHOLD_PCT)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"Expected trigger at exact 10% threshold, got: {reason}")

    def test_drawdown_trigger_no_fire_empty_curve(self) -> None:
        """Пустая equity curve — не сработать."""
        triggered, reason = self.checker.check_drawdown_trigger([])
        self.assertFalse(triggered)

    def test_drawdown_trigger_no_fire_single_bar(self) -> None:
        """Один evidenced бар — нет предыдущего максимума, не сработать."""
        curve = [{"date": "2026-06-12", "close_equity": 100_000.0,
                  "source": "cycle", "evidenced": True}]
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered)

    def test_drawdown_excludes_warmup_bars(self) -> None:
        """N1 SAFETY: inflated warmup peak must NOT fabricate a drawdown.

        A pre-anchor warmup bar at $200k followed by real $100k bars would be a
        50% drawdown if naively counted — but warmup bars are excluded, so the
        real series (flat $100k) has 0% drawdown → NO trigger.
        """
        curve = [
            {"date": "2026-05-01", "close_equity": 200_000.0, "is_warmup": True},
        ]
        for i in range(5):
            curve.append({"date": f"2026-06-{10 + i:02d}",
                          "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered,
                         f"warmup peak must not fabricate drawdown: {reason}")

    def test_drawdown_trigger_large_drawdown(self) -> None:
        """Просадка 50% — гарантированное срабатывание."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=50.0, days=30)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered)

    def test_drawdown_uses_last_30_days(self) -> None:
        """Окно 30 дней: пик вне окна не считается (на evidenced барах)."""
        from datetime import date, timedelta
        from spa_core.paper_trading.track_evidence import PAPER_REAL_START

        # 50 evidenced баров: первые 20 с большим пиком (вне 30-дн окна),
        # последние 30 — нормальные. Все пост-anchor, source=cycle.
        base = PAPER_REAL_START
        long_peak_bars = [
            {"date": (base + timedelta(days=i)).isoformat(),
             "close_equity": 200_000.0, "source": "cycle", "evidenced": True}
            for i in range(20)
        ]
        normal_bars = [
            {"date": (base + timedelta(days=20 + i)).isoformat(),
             "close_equity": 99_000.0, "source": "cycle", "evidenced": True}
            for i in range(30)
        ]
        # Текущая просадка от max в 30-дневном окне: max=99000, current=99000 → 0%
        curve = long_peak_bars + normal_bars
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"Should not trigger since 30d window is flat: {reason}")


class TestManualTrigger(unittest.TestCase):
    """Tests for check_manual_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_manual_trigger_no_file(self) -> None:
        """Без файла — не срабатывает."""
        triggered, reason = self.checker.check_manual_trigger()
        self.assertFalse(triggered)

    def test_manual_trigger_file_exists(self) -> None:
        """Файл kill_switch_active.json существует — срабатывает."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(json.dumps({"reason": "test"}), encoding="utf-8")
        triggered, reason = self.checker.check_manual_trigger()
        self.assertTrue(triggered)
        self.assertIn("manual", reason.lower())

    def test_manual_trigger_carries_reason(self) -> None:
        """Причина из файла включается в reason."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(
            json.dumps({"reason": "emergency stop by operator"}), encoding="utf-8"
        )
        triggered, reason = self.checker.check_manual_trigger()
        self.assertTrue(triggered)
        self.assertIn("emergency stop by operator", reason)

    def test_manual_trigger_empty_file(self) -> None:
        """Пустой JSON в файле — всё равно срабатывает (файл = сигнал)."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text("{}", encoding="utf-8")
        triggered, reason = self.checker.check_manual_trigger()
        self.assertTrue(triggered)


class TestRedFlagsTrigger(unittest.TestCase):
    """Tests for check_red_flags_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_flags(self, count: int) -> None:
        """Write `count` CRITICAL flags on HELD protocols with LIVE sources.

        N1: only CRITICAL flags on held protocols (live, non-bootstrap source)
        count toward the trigger — so the fixture writes a current_positions.json
        holding all those protocols and tags each flag source="defillama".
        """
        protos = [f"proto_{i}" for i in range(count)]
        # Hold every protocol so the flags are "on held protocols".
        _write_json(
            self.data_dir / "current_positions.json",
            {"positions": {p: 10_000.0 for p in protos}},
        )
        flags = [
            {"protocol": p, "severity": "CRITICAL", "source": "defillama"}
            for p in protos
        ]
        _write_json(
            self.data_dir / "red_flags.json",
            {"red_flags": flags, "sources": ["defillama"],
             "fallback_used": False, "generated_at": "2026-06-11T00:00:00Z"},
        )

    def test_red_flags_trigger_fires(self) -> None:
        """6 CRITICAL флагов на held протоколах > 5 — должна сработать."""
        self._write_flags(6)
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertTrue(triggered, f"Expected trigger at 6 flags: {reason}")
        self.assertIn("6", reason)

    def test_red_flags_trigger_no_fire(self) -> None:
        """5 флагов = порог — НЕ должна сработать (строгое >)."""
        self._write_flags(RED_FLAGS_THRESHOLD)
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered, f"Expected no trigger at exact threshold: {reason}")

    def test_red_flags_trigger_no_file(self) -> None:
        """Нет файла — не сработать."""
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered)

    def test_red_flags_many_flags(self) -> None:
        """100 CRITICAL флагов на held протоколах — гарантированное срабатывание."""
        self._write_flags(100)
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertTrue(triggered)

    def test_red_flags_warn_unheld_no_fire(self) -> None:
        """N1 SAFETY: 6 WARN флагов на НЕ-удерживаемых протоколах → НЕ сработать."""
        flags = [
            {"protocol": f"external_{i}", "severity": "WARN", "source": "defillama"}
            for i in range(6)
        ]
        _write_json(
            self.data_dir / "red_flags.json",
            {"red_flags": flags, "sources": ["defillama"], "fallback_used": False},
        )
        # No positions file → nothing held.
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered,
                         f"WARN/unheld flags must not trigger: {reason}")


class TestSharpeTrigger(unittest.TestCase):
    """Tests for check_sharpe_trigger."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_analytics(self, sharpe: float, num_days: int = 30) -> None:
        _write_json(
            self.data_dir / "analytics_summary.json",
            {
                "num_days": num_days,
                "metrics": {"sharpe": sharpe},
                "source": "analytics_runner",
            },
        )

    def test_sharpe_trigger_fires(self) -> None:
        """Sharpe = -1.5 < -1.0 — должна сработать (normal period, num_days=61 ≥ 60d grace)."""
        # Grace period = first 60 days (SHARPE_EARLY_PERIOD_DAYS); threshold there
        # is SHARPE_EARLY_THRESHOLD = -2.0.  At 30 days -1.5 > -2.0 → no trigger.
        # Use num_days=61 to be in normal_period where threshold is -1.0 and -1.5 fires.
        self._write_analytics(-1.5, num_days=61)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered, f"Expected trigger at sharpe=-1.5 (normal_period): {reason}")
        self.assertIn("-1.5", reason)

    def test_sharpe_trigger_no_fire(self) -> None:
        """Sharpe = 0.5 > -1.0 — НЕ должна сработать."""
        self._write_analytics(0.5, num_days=30)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Expected no trigger at sharpe=0.5: {reason}")

    def test_sharpe_trigger_exact_threshold(self) -> None:
        """Sharpe ровно -1.0 — НЕ должна сработать (строгое <)."""
        self._write_analytics(SHARPE_THRESHOLD, num_days=30)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Expected no trigger at exact threshold: {reason}")

    def test_sharpe_trigger_insufficient_data(self) -> None:
        """Sharpe = -2.0, но только 3 дня данных — не срабатывает."""
        self._write_analytics(-2.0, num_days=3)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Expected no trigger with 3 days: {reason}")
        self.assertIn("insufficient", reason.lower())

    def test_sharpe_trigger_no_file(self) -> None:
        """Нет файла — не сработать."""
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered)


class TestAllCashAllocation(unittest.TestCase):
    """Tests for get_kill_switch_allocation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_cash_allocation_complete(self) -> None:
        """Все протоколы = 0.0, cash = 1.0."""
        alloc = self.checker.get_kill_switch_allocation()
        self.assertIn("cash", alloc, "allocation must include 'cash'")
        self.assertEqual(alloc["cash"], 1.0, "cash must be 1.0")

        protocols = [k for k in alloc if k != "cash"]
        self.assertTrue(protocols, "Must have at least one protocol key")
        for p in protocols:
            self.assertEqual(
                alloc[p], 0.0,
                f"Protocol {p} must be 0.0 in all-cash allocation, got {alloc[p]}"
            )

    def test_all_cash_contains_known_protocols(self) -> None:
        """Аллокация содержит все известные протоколы."""
        alloc = self.checker.get_kill_switch_allocation()
        from spa_core.governance.kill_switch import _KNOWN_PROTOCOLS
        for p in _KNOWN_PROTOCOLS:
            self.assertIn(p, alloc, f"Known protocol {p} missing from kill-switch allocation")
            self.assertEqual(alloc[p], 0.0)

    def test_all_cash_reads_from_orchestrator_status(self) -> None:
        """Если adapter_orchestrator_status.json существует — читает протоколы оттуда."""
        orch_doc = {
            "adapters": [
                {"protocol": "custom_proto_1", "status": "ok"},
                {"protocol": "custom_proto_2", "status": "ok"},
            ]
        }
        _write_json(self.data_dir / "adapter_orchestrator_status.json", orch_doc)
        alloc = self.checker.get_kill_switch_allocation()
        self.assertIn("custom_proto_1", alloc)
        self.assertIn("custom_proto_2", alloc)
        self.assertEqual(alloc["custom_proto_1"], 0.0)
        self.assertEqual(alloc["custom_proto_2"], 0.0)


class TestActivateDeactivate(unittest.TestCase):
    """Tests for activate_kill_switch / deactivate_kill_switch."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_activate_creates_file(self) -> None:
        """activate_kill_switch() создаёт kill_switch_active.json."""
        active_path = Path(self._tmp.name) / "kill_switch_active.json"
        self.assertFalse(active_path.exists())
        self.checker.activate_kill_switch("test activation")
        self.assertTrue(active_path.exists())
        doc = json.loads(active_path.read_text())
        self.assertEqual(doc["reason"], "test activation")
        self.assertIn("activated_at", doc)

    def test_deactivate_removes_file(self) -> None:
        """deactivate_kill_switch() удаляет файл."""
        self.checker.activate_kill_switch("reason")
        active_path = Path(self._tmp.name) / "kill_switch_active.json"
        self.assertTrue(active_path.exists())
        self.checker.deactivate_kill_switch()
        self.assertFalse(active_path.exists())

    def test_deactivate_idempotent(self) -> None:
        """Повторная деактивация без файла — не бросает исключение."""
        # Нет файла — не должно упасть
        self.checker.deactivate_kill_switch()


class TestNoTriggers(unittest.TestCase):
    """Tests for the 'all clear' case."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_triggers_returns_false(self) -> None:
        """Без триггеров is_kill_switch_active() возвращает False."""
        # Пишем нормальную equity curve (нет просадки)
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=0.0, days=10)
        # Нет red_flags файла, нет manual файла, нет analytics
        triggered, reason = self.checker.is_kill_switch_active(equity_curve=curve)
        self.assertFalse(triggered, f"Expected no trigger, got: {reason}")

    def test_run_kill_switch_check_no_triggers(self) -> None:
        """run_kill_switch_check без триггеров → triggered=False."""
        curve = _make_equity_curve(peak=100_000.0, drawdown_pct=5.0, days=10)
        status = run_kill_switch_check(equity_curve=curve, data_dir=self._tmp.name)
        self.assertFalse(status["triggered"])
        self.assertEqual(status["allocation"], {})


class TestRunKillSwitchCheck(unittest.TestCase):
    """Integration tests for run_kill_switch_check."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_test_")
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_triggered_returns_allocation(self) -> None:
        """При срабатывании возвращает allocation с cash=1.0."""
        # Создаём manual trigger
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(json.dumps({"reason": "test"}), encoding="utf-8")
        status = run_kill_switch_check(equity_curve=[], data_dir=self.data_dir)
        self.assertTrue(status["triggered"])
        self.assertIn("allocation", status)
        alloc = status["allocation"]
        self.assertEqual(alloc.get("cash"), 1.0)

    def test_triggered_writes_status_file(self) -> None:
        """При срабатывании создаёт data/kill_switch_status.json."""
        active_path = self.data_dir / "kill_switch_active.json"
        active_path.write_text(json.dumps({"reason": "test"}), encoding="utf-8")
        run_kill_switch_check(equity_curve=[], data_dir=self.data_dir)
        status_path = self.data_dir / "kill_switch_status.json"
        self.assertTrue(status_path.exists(), "kill_switch_status.json must be written")
        doc = json.loads(status_path.read_text())
        self.assertTrue(doc["triggered"])
        self.assertIn("reason", doc)

    def test_not_triggered_writes_status_file(self) -> None:
        """Даже при отсутствии триггеров пишет kill_switch_status.json."""
        run_kill_switch_check(equity_curve=[], data_dir=self.data_dir)
        status_path = self.data_dir / "kill_switch_status.json"
        self.assertTrue(status_path.exists())
        doc = json.loads(status_path.read_text())
        self.assertFalse(doc["triggered"])


class TestDrillScript(unittest.TestCase):
    """Test that the drill script runs successfully."""

    def test_drill_script_passes(self) -> None:
        """scripts/kill_switch_drill.py должен завершиться с кодом 0."""
        drill_path = Path(__file__).resolve().parents[2] / "scripts" / "kill_switch_drill.py"
        self.assertTrue(drill_path.exists(), f"Drill script not found: {drill_path}")

        import subprocess
        result = subprocess.run(
            [sys.executable, str(drill_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f"Drill script failed (rc={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}",
        )


class TestN1SafetyFix(unittest.TestCase):
    """N10 — the safety-critical paths must be the best-tested.

    Covers both false-trigger bugs (N1) AND confirms the real-crisis trigger is
    preserved:
      * mixed-source red_flags + bootstrap/WARN flags → NO trigger
      * CRITICAL flag on a HELD protocol → DOES trigger
      * CRITICAL on an UNHELD/external protocol → NO trigger
      * inflated warmup bar → NO drawdown trigger
      * real > threshold drawdown on evidenced bars → DOES trigger
      * per-flag source == "bootstrap" filtered
    Aims for ~full branch coverage of check_red_flags_trigger /
    check_drawdown_trigger.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_n1_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _hold(self, *protocols: str) -> None:
        _write_json(self.data_dir / "current_positions.json",
                    {"positions": {p: 10_000.0 for p in protocols}})

    def _flags(self, flags: list, *, sources=None, fallback_used=False) -> None:
        _write_json(self.data_dir / "red_flags.json", {
            "sources": sources if sources is not None else ["defillama"],
            "fallback_used": fallback_used,
            "red_flags": flags,
        })

    # ── (1) mixed-source + bootstrap/WARN flags → NO trigger ─────────────────

    def test_mixed_source_bootstrap_warn_flags_no_trigger(self) -> None:
        """MIXED sources + 6 WARN/bootstrap flags → NO trigger (bugs a+b+c)."""
        self._hold("ethena_susde", "pendle_pt")
        flags = [
            {"protocol": "ethena-susde", "severity": "WARN", "source": "historical_apy"},
            {"protocol": "pendle-pt", "severity": "WARN", "source": "defillama"},
            {"protocol": "aave-v3", "severity": "WARN", "source": "snapshot"},
            {"protocol": "euler-v2", "severity": "CRITICAL", "source": "bootstrap"},
            {"protocol": "maple", "severity": "WARN", "source": "bootstrap"},
            {"protocol": "compound-v3", "severity": "WARN", "source": "snapshot"},
        ]
        # MIXED sources — must NOT be treated as a bootstrap document (bug a).
        self._flags(flags, sources=["defillama", "bootstrap", "snapshot"])
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered, f"advisory/WARN/bootstrap must not trigger: {reason}")

    def test_mixed_source_document_not_ignored_wholesale(self) -> None:
        """A mixed-source doc is NOT short-circuited as bootstrap (bug a).

        Reason must reflect the CRITICAL-on-held count path, not the
        'flags ignored' document-level path.
        """
        self._hold("aave_v3")
        self._flags(
            [{"protocol": "aave-v3", "severity": "CRITICAL", "source": "defillama"}],
            sources=["defillama", "bootstrap"],
        )
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered)  # only 1 ≤ 5
        self.assertNotIn("ignored", reason)
        self.assertIn("CRITICAL-on-held", reason)

    # ── (2) CRITICAL on HELD → trigger ───────────────────────────────────────

    def test_critical_on_held_triggers(self) -> None:
        """6 CRITICAL flags on a HELD protocol (live) → TRIGGER (real crisis)."""
        self._hold("aave_v3")
        flags = [{"protocol": "aave-v3", "severity": "CRITICAL", "source": "defillama"}
                 for _ in range(6)]
        self._flags(flags, sources=["defillama"])
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertTrue(triggered, f"CRITICAL-on-held must trigger: {reason}")
        self.assertIn("aave-v3", reason)

    def test_critical_on_held_hyphen_underscore_normalized(self) -> None:
        """Held slug 'aave_v3' matches flag slug 'aave-v3' (normalization)."""
        self._hold("aave_v3")
        flags = [{"protocol": "aave-v3", "severity": "CRITICAL", "source": "defillama"}
                 for _ in range(6)]
        self._flags(flags, sources=["defillama"])
        triggered, _ = self.checker.check_red_flags_trigger()
        self.assertTrue(triggered)

    # ── (3) CRITICAL on UNHELD/external → no trigger ─────────────────────────

    def test_critical_on_unheld_no_trigger(self) -> None:
        """6 CRITICAL flags on an UNHELD/external protocol → NO trigger."""
        self._hold("aave_v3")  # we hold aave, NOT pendle
        flags = [{"protocol": "pendle-pt", "severity": "CRITICAL", "source": "defillama"}
                 for _ in range(6)]
        self._flags(flags, sources=["defillama"])
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered, f"CRITICAL on external protocol must not trigger: {reason}")

    def test_no_positions_file_nothing_held(self) -> None:
        """No current_positions.json → nothing held → CRITICAL flags don't trigger."""
        flags = [{"protocol": "aave-v3", "severity": "CRITICAL", "source": "defillama"}
                 for _ in range(6)]
        self._flags(flags, sources=["defillama"])
        triggered, _ = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered)

    # ── (4) per-flag source == "bootstrap" filtered ──────────────────────────

    def test_per_flag_bootstrap_source_filtered(self) -> None:
        """6 CRITICAL-on-held flags but each source='bootstrap' → filtered → no trigger (bug b)."""
        self._hold("aave_v3")
        flags = [{"protocol": "aave-v3", "severity": "CRITICAL", "source": "bootstrap"}
                 for _ in range(6)]
        self._flags(flags, sources=["defillama"])  # doc mixed but flags bootstrap
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertFalse(triggered, f"per-flag bootstrap source must be filtered: {reason}")

    def test_mix_live_and_bootstrap_source_only_live_counts(self) -> None:
        """6 live CRITICAL-on-held + 10 bootstrap-source → effective 6 → trigger."""
        self._hold("aave_v3")
        live = [{"protocol": "aave-v3", "severity": "CRITICAL", "source": "defillama"}
                for _ in range(6)]
        boot = [{"protocol": "aave-v3", "severity": "CRITICAL", "source": "bootstrap"}
                for _ in range(10)]
        self._flags(live + boot, sources=["defillama"])
        triggered, reason = self.checker.check_red_flags_trigger()
        self.assertTrue(triggered)
        self.assertIn("6", reason)

    # ── (5) drawdown: warmup excluded, real drawdown triggers ────────────────

    def test_warmup_bar_no_drawdown_trigger(self) -> None:
        """Inflated warmup bar ($200k) + flat real $100k → NO drawdown trigger."""
        curve = [{"date": "2026-05-15", "close_equity": 200_000.0, "is_warmup": True}]
        for i in range(5):
            curve.append({"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"warmup peak must not fabricate drawdown: {reason}")

    def test_real_drawdown_above_threshold_triggers(self) -> None:
        """Real -18% drawdown on evidenced bars → TRIGGER (threshold unchanged)."""
        curve = []
        for i in range(10):
            curve.append({"date": f"2026-06-{10 + i:02d}", "close_equity": 100_000.0,
                          "source": "cycle", "evidenced": True})
        curve.append({"date": "2026-06-20", "close_equity": 82_000.0,
                      "source": "cycle", "evidenced": True})  # -18%
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"real -18% drawdown must trigger: {reason}")
        self.assertIn("drawdown", reason.lower())

    def test_all_warmup_no_evidenced_no_trigger(self) -> None:
        """Curve of ONLY warmup bars → no evidenced data → no trigger."""
        curve = [{"date": "2026-05-0{}".format(i + 1), "close_equity": 200_000.0 - i * 50_000,
                  "is_warmup": True} for i in range(3)]
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered)
        self.assertIn("evidenced", reason.lower())

    def test_threshold_value(self) -> None:
        """OWNER-GATED (ADR-048, owner-approved 2026-06-27): hard-kill drawdown
        threshold lowered 15.0 → 10.0 (now owns the DL-02 10% peak rung)."""
        self.assertEqual(DRAWDOWN_THRESHOLD_PCT, 10.0)


class TestLiveDataDoesNotFalseTrigger(unittest.TestCase):
    """Sanity check against the REAL repo data/ — must not false-trigger.

    The live red_flags.json (advisory/WARN/bootstrap flags) and
    equity_curve_daily.json (warmup bars) must NOT activate the kill-switch.
    """

    def test_live_red_flags_do_not_trigger(self) -> None:
        repo_data = Path(__file__).resolve().parents[2] / "data"
        if not (repo_data / "red_flags.json").exists():
            self.skipTest("live red_flags.json not present")
        checker = KillSwitchChecker(data_dir=repo_data)
        triggered, reason = checker.check_red_flags_trigger()
        self.assertFalse(triggered,
                         f"live red_flags must not trigger kill-switch: {reason}")

    def test_live_equity_curve_no_drawdown_trigger(self) -> None:
        repo_data = Path(__file__).resolve().parents[2] / "data"
        eq = repo_data / "equity_curve_daily.json"
        if not eq.exists():
            self.skipTest("live equity_curve_daily.json not present")
        doc = json.loads(eq.read_text(encoding="utf-8"))
        daily = doc.get("daily") if isinstance(doc, dict) else []
        checker = KillSwitchChecker(data_dir=repo_data)
        triggered, reason = checker.check_drawdown_trigger(daily or [])
        self.assertFalse(triggered,
                         f"live equity (warmup bars) must not fabricate drawdown: {reason}")


if __name__ == "__main__":
    unittest.main()
