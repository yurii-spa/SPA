"""Tests for red_flags kill_switch gate (MP-fix: bootstrap/fallback фильтр).

Покрывает:
- source=bootstrap → kill_switch=False (document-level)
- fallback_used=true → kill_switch=False
- live source, 6 флагов → kill_switch=True
- live source, 4 флага → kill_switch=False
- live source, ровно 5 флагов → kill_switch=False (граница, > не >=)
- mixed flags (часть bootstrap на уровне флага, часть live) → считаются только live
- RED_FLAGS_IGNORE_BOOTSTRAP=false в policy → bootstrap НЕ игнорируется
- custom threshold из risk_policy.json
- пустой список флагов → kill_switch=False
- missing red_flags.json → kill_switch=False
- invalid red_flags.json → kill_switch=False
- источники — несколько источников (не только bootstrap) → флаги считаются
- sources=[] (пустой список) → флаги считаются (не bootstrap)
- fallback_used=false, источники не bootstrap → флаги считаются
- 6 live + 3 bootstrap индивидуальных → effective_count=6 → True
- 4 live + 10 bootstrap индивидуальных → effective_count=4 → False
- risk_policy.json отсутствует → compile-time defaults (threshold=5, ignore_bootstrap=True)
- risk_policy.json не читается (invalid JSON) → compile-time defaults
- 5 флагов, threshold из policy=4 → True (кастомный порог)
- 5 флагов, threshold из policy=6 → False (кастомный порог)
- 0 флагов, fallback_used=false → False
- sources содержит "bootstrap" но не единственный → флаги считаются
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


def _make_checker(data_dir):
    """Создаёт KillSwitchChecker с указанной data_dir."""
    from spa_core.governance.kill_switch import KillSwitchChecker
    return KillSwitchChecker(data_dir=data_dir)


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _make_flag(category="apy_spike", source_field="defillama", bootstrap_field=False,
               protocol="test-protocol", severity="CRITICAL"):
    """Возвращает dict одного красного флага.

    N1: the kill-switch now counts only CRITICAL flags on HELD protocols whose
    OWN ``source != "bootstrap"``. The default fixture therefore emits a
    CRITICAL flag on ``test-protocol`` (held — see ``_write_flags`` below) with a
    live source. ``bootstrap_field=True`` sets ``source="bootstrap"`` so the
    per-flag bootstrap filter (b) excludes it.
    """
    flag = {
        "protocol": protocol,
        "category": category,
        "severity": severity,
        "message": "test flag",
        "source": "bootstrap" if bootstrap_field else source_field,
    }
    return flag


def _make_doc(flags, fallback_used=False, sources=None):
    """Возвращает dict верхнего уровня red_flags.json."""
    doc = {
        "generated_at": "2026-06-20T00:00:00Z",
        "monitor_version": "1.0",
        "sources": sources if sources is not None else ["defillama"],
        "fallback_used": fallback_used,
        "red_flags": flags,
    }
    return doc


class TestRedFlagsGate(unittest.TestCase):
    """Unit-тесты для KillSwitchChecker.check_red_flags_trigger()."""

    # Protocols that the fixtures hold so their CRITICAL flags count (N1: the
    # gate only counts CRITICAL flags on HELD protocols). Covers the default
    # fixture protocol plus every protocol used by the incident-scenario doc.
    _HELD = {
        "test-protocol": 10_000.0,
        "ethena-susde": 10_000.0,
        "pendle-pt": 10_000.0,
        "aave-v3": 10_000.0,
        "compound-v3": 10_000.0,
        "euler-v2": 10_000.0,
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp)
        # Hold the fixture protocols so CRITICAL-on-held logic counts them.
        _write_json(self.data_dir / "current_positions.json",
                    {"positions": dict(self._HELD)})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _write_flags(self, doc):
        _write_json(self.data_dir / "red_flags.json", doc)

    def _write_policy(self, policy):
        _write_json(self.data_dir / "risk_policy.json", policy)

    def _check(self):
        return _make_checker(self.data_dir).check_red_flags_trigger()

    # ── Test 1: document-level fallback_used=true → False ────────────────────

    def test_01_fallback_used_true_ignores_all_flags(self):
        """fallback_used=true на уровне документа → все 6 флагов игнорируются."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=True,
            sources=["bootstrap"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("ignored", reason)

    # ── Test 2: sources=["bootstrap"] → False ────────────────────────────────

    def test_02_sources_bootstrap_only_ignores_all_flags(self):
        """sources=["bootstrap"] → флаги не считаются (даже если fallback_used=False)."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=False,
            sources=["bootstrap"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("ignored", reason)

    # ── Test 3: live source, 6 flags → True ──────────────────────────────────

    def test_03_live_source_6_flags_triggers(self):
        """Живые данные, 6 флагов > порог 5 → kill_switch=True."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=False,
            sources=["defillama", "snapshot"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertTrue(triggered)
        self.assertIn("6", reason)

    # ── Test 4: live source, 4 flags → False ─────────────────────────────────

    def test_04_live_source_4_flags_no_trigger(self):
        """4 флага ≤ порог 5 → kill_switch=False."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(4)],
            fallback_used=False,
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("4", reason)

    # ── Test 5: exactly 5 flags, boundary (> not >=) → False ─────────────────

    def test_05_exactly_5_flags_boundary_no_trigger(self):
        """Ровно 5 флагов = порогу → kill_switch=False (условие > 5, не >= 5)."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(5)],
            fallback_used=False,
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)

    # ── Test 6: fallback_used=false + live sources → флаги считаются ─────────

    def test_06_fallback_false_live_sources_6_flags(self):
        """fallback_used=False и реальные источники → 6 флагов триггерят."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=False,
            sources=["defillama"],
        )
        self._write_flags(doc)
        triggered, _ = self._check()
        self.assertTrue(triggered)

    # ── Test 7: mixed flag-level bootstrap flags ──────────────────────────────

    def test_07_mixed_individual_bootstrap_flags_filtered(self):
        """6 live-флагов + 3 флага с bootstrap=True → effective=6 → True."""
        live = [_make_flag() for _ in range(6)]
        boot = [_make_flag(bootstrap_field=True) for _ in range(3)]
        doc = _make_doc(
            flags=live + boot,
            fallback_used=False,
            sources=["defillama"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertTrue(triggered)
        self.assertIn("6", reason)

    # ── Test 8: 4 live + 10 individual-bootstrap → effective=4 → False ───────

    def test_08_4_live_10_individual_bootstrap_no_trigger(self):
        """4 live + 10 bootstrap на уровне флага → effective=4 → False."""
        live = [_make_flag() for _ in range(4)]
        boot = [_make_flag(bootstrap_field=True) for _ in range(10)]
        doc = _make_doc(
            flags=live + boot,
            fallback_used=False,
            sources=["defillama"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("4", reason)

    # ── Test 9: RED_FLAGS_IGNORE_BOOTSTRAP=false → bootstrap считается ────────

    def test_09_ignore_bootstrap_false_counts_all_flags(self):
        """RED_FLAGS_IGNORE_BOOTSTRAP=false → fallback_used/sources игнорируется, все флаги считаются."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=True,
            sources=["bootstrap"],
        )
        self._write_flags(doc)
        self._write_policy({"RED_FLAGS_IGNORE_BOOTSTRAP": False, "RED_FLAGS_THRESHOLD": 5})
        triggered, reason = self._check()
        self.assertTrue(triggered)
        self.assertIn("6", reason)

    # ── Test 10: custom threshold from risk_policy.json ───────────────────────

    def test_10_custom_threshold_4_triggers_at_5_flags(self):
        """Кастомный threshold=4 → 5 флагов триггерят (5 > 4)."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(5)],
            fallback_used=False,
        )
        self._write_flags(doc)
        self._write_policy({"RED_FLAGS_THRESHOLD": 4})
        triggered, reason = self._check()
        self.assertTrue(triggered)

    # ── Test 11: custom threshold=6 → 5 flags don't trigger ──────────────────

    def test_11_custom_threshold_6_no_trigger_at_5_flags(self):
        """Кастомный threshold=6 → 5 флагов не триггерят (5 ≤ 6)."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(5)],
            fallback_used=False,
        )
        self._write_flags(doc)
        self._write_policy({"RED_FLAGS_THRESHOLD": 6})
        triggered, reason = self._check()
        self.assertFalse(triggered)

    # ── Test 12: empty flags list → False ─────────────────────────────────────

    def test_12_empty_flags_list_no_trigger(self):
        """Пустой список флагов → False."""
        doc = _make_doc(flags=[], fallback_used=False)
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("0", reason)

    # ── Test 13: missing red_flags.json → False ───────────────────────────────

    def test_13_missing_red_flags_file_no_trigger(self):
        """Файл red_flags.json отсутствует → False (безопасный дефолт).

        _read_json возвращает {} при отсутствии файла, поэтому reason будет
        'no red_flags list in file' (ключ red_flags отсутствует в пустом doc).
        """
        triggered, reason = self._check()
        self.assertFalse(triggered)
        # reason содержит "missing" (invalid doc) или "no red_flags list" (empty doc)
        self.assertTrue(
            "missing" in reason.lower() or "no red_flags list" in reason.lower(),
            f"Unexpected reason: {reason}",
        )

    # ── Test 14: invalid JSON → False ─────────────────────────────────────────

    def test_14_invalid_json_no_trigger(self):
        """Невалидный JSON в red_flags.json → False."""
        (self.data_dir / "red_flags.json").write_text("not json {{{", encoding="utf-8")
        triggered, reason = self._check()
        self.assertFalse(triggered)

    # ── Test 15: missing risk_policy.json → compile-time defaults ─────────────

    def test_15_missing_policy_uses_compile_defaults(self):
        """Отсутствующий risk_policy.json → дефолты (threshold=5, ignore_bootstrap=True)."""
        # 6 флагов с bootstrap=True → игнорируются → False (bootstrap)
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=True,
            sources=["bootstrap"],
        )
        self._write_flags(doc)
        # Нет risk_policy.json → compile-time defaults → ignore_bootstrap=True
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("ignored", reason)

    # ── Test 16: invalid risk_policy.json → compile-time defaults ─────────────

    def test_16_invalid_policy_json_uses_defaults(self):
        """Невалидный risk_policy.json → compile-time defaults."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=True,
            sources=["bootstrap"],
        )
        self._write_flags(doc)
        (self.data_dir / "risk_policy.json").write_text("INVALID", encoding="utf-8")
        triggered, reason = self._check()
        self.assertFalse(triggered)

    # ── Test 17: sources=[] (empty) → flags are counted ──────────────────────

    def test_17_empty_sources_flags_counted(self):
        """sources=[] — не bootstrap → флаги считаются нормально."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=False,
            sources=[],
        )
        self._write_flags(doc)
        triggered, _ = self._check()
        self.assertTrue(triggered)

    # ── Test 18: sources contains "bootstrap" but not ONLY bootstrap ──────────

    def test_18_sources_mixed_with_bootstrap_not_ignored(self):
        """sources=["bootstrap","defillama"] (не только bootstrap) → флаги считаются."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=False,
            sources=["bootstrap", "defillama"],
        )
        self._write_flags(doc)
        triggered, _ = self._check()
        self.assertTrue(triggered)

    # ── Test 19: 0 live + many individual-bootstrap → effective=0 → False ─────

    def test_19_only_individual_bootstrap_flags_effective_zero(self):
        """Все флаги с bootstrap=True на уровне флага → effective=0 → False."""
        boot = [_make_flag(bootstrap_field=True) for _ in range(10)]
        doc = _make_doc(
            flags=boot,
            fallback_used=False,
            sources=["defillama"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("0", reason)

    # ── Test 20: red_flags key is not a list → False ──────────────────────────

    def test_20_red_flags_not_a_list_no_trigger(self):
        """red_flags — не список (dict) → False."""
        doc = {
            "generated_at": "2026-06-20T00:00:00Z",
            "fallback_used": False,
            "red_flags": {"error": "not a list"},
        }
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("no red_flags list", reason)

    # ── Test 21: reason string includes bootstrap info when ignored ───────────

    def test_21_reason_includes_bootstrap_info(self):
        """При игнорировании reason содержит информацию о fallback_used и sources."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=True,
            sources=["bootstrap"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("fallback_used=True", reason)
        self.assertIn("bootstrap", reason)

    # ── Test 22: 6 CRITICAL flags live → trigger with count in reason ─────────

    def test_22_6_critical_live_flags_reason_contains_count(self):
        """6 CRITICAL живых флагов → triggered=True, reason содержит '6 > 5'."""
        doc = _make_doc(
            flags=[_make_flag(category="tvl_collapse") for _ in range(6)],
            fallback_used=False,
            sources=["defillama"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertTrue(triggered)
        self.assertIn("6", reason)
        self.assertIn("5", reason)

    # ── Test 23: fallback_used=true overrides even with live sources ──────────

    def test_23_fallback_true_with_live_sources_still_ignored(self):
        """fallback_used=True даже при sources=["defillama"] → флаги игнорируются."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(8)],
            fallback_used=True,
            sources=["defillama"],
        )
        self._write_flags(doc)
        triggered, reason = self._check()
        self.assertFalse(triggered)
        self.assertIn("ignored", reason)

    # ── Test 24: exact scenario from the incident (6 bootstrap flags) ─────────

    def test_24_incident_scenario_6_bootstrap_flags_not_triggered(self):
        """Точный сценарий инцидента: red_flags.json с fallback_used=True, 6 дефолтных флагов."""
        # Воспроизводим файл из инцидента
        incident_doc = {
            "generated_at": "2026-06-20T15:42:42.532632Z",
            "monitor_version": "1.0",
            "sources": ["bootstrap"],
            "fallback_used": True,
            "red_flags": [
                {
                    "protocol": "ethena-susde",
                    "category": "apy_spike",
                    "severity": "WARN",
                    "message": "APY 18.40% is 2.56x baseline 7.20%",
                    "source": "historical_apy",
                    "evidence": {"baseline_apy": 7.2, "current_apy": 18.4},
                },
                {
                    "protocol": "pendle-pt",
                    "category": "apy_spike",
                    "severity": "CRITICAL",
                    "message": "APY 24.60% is 4.03x baseline 6.10%",
                    "source": "historical_apy",
                    "evidence": {"baseline_apy": 6.1, "current_apy": 24.6},
                },
                {
                    "protocol": "aave-v3",
                    "category": "governance_proposal",
                    "severity": "WARN",
                    "message": "Risk-sensitive proposal [risk-param]",
                    "source": "snapshot",
                },
                {
                    "protocol": "compound-v3",
                    "category": "governance_proposal",
                    "severity": "WARN",
                    "message": "Upgrade Comet implementation",
                    "source": "snapshot",
                },
                {
                    "protocol": "euler-v2",
                    "category": "tvl_drop",
                    "severity": "WARN",
                    "message": "TVL dropped 33.4% over 7d",
                    "source": "defillama",
                },
                {
                    "protocol": "aave-v3",
                    "category": "tvl_drop",
                    "severity": "WARN",
                    "message": "TVL dropped 12.1% over 24h",
                    "source": "defillama",
                },
            ],
        }
        self._write_flags(incident_doc)
        triggered, reason = self._check()
        # ДОЛЖЕН быть False — это bootstrap-данные, не живые
        self.assertFalse(triggered, f"Инцидент не должен был триггерить, но reason: {reason}")
        self.assertIn("ignored", reason)

    # ── Test 25: after fix, 6 REAL live flags still trigger ───────────────────

    def test_25_real_live_6_flags_after_fix_still_triggers(self):
        """После фикса 6 реальных live-флагов всё равно триггерят (безопасность не снижается)."""
        live_doc = {
            "generated_at": "2026-06-20T16:00:00Z",
            "monitor_version": "1.0",
            "sources": ["defillama", "snapshot", "chainalysis"],
            "fallback_used": False,
            "red_flags": [_make_flag(source_field="defillama") for _ in range(6)],
        }
        self._write_flags(live_doc)
        triggered, reason = self._check()
        self.assertTrue(triggered, f"6 live-флагов должны были триггерить, reason: {reason}")

    # ── Test 26: RED_FLAGS_THRESHOLD read from policy overrides constant ───────

    def test_26_policy_threshold_overrides_module_constant(self):
        """RED_FLAGS_THRESHOLD=3 в policy → порог становится 3, не 5."""
        doc = _make_doc(
            flags=[_make_flag() for _ in range(4)],
            fallback_used=False,
            sources=["defillama"],
        )
        self._write_flags(doc)
        self._write_policy({"RED_FLAGS_THRESHOLD": 3, "RED_FLAGS_IGNORE_BOOTSTRAP": True})
        triggered, reason = self._check()
        self.assertTrue(triggered)  # 4 > 3

    # ── Test 27: fallback_used key missing → treated as False (live data) ──────

    def test_27_missing_fallback_used_key_treated_as_false(self):
        """fallback_used ключ отсутствует в doc → считается False (live-данные)."""
        doc = {
            "generated_at": "2026-06-20T00:00:00Z",
            "sources": ["defillama"],
            "red_flags": [_make_flag() for _ in range(6)],
        }
        # fallback_used отсутствует → default False → флаги считаются
        self._write_flags(doc)
        triggered, _ = self._check()
        self.assertTrue(triggered)


class TestRedFlagsGateIntegration(unittest.TestCase):
    """Интеграционные тесты: run_kill_switch_check с red_flags триггером."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp)
        # Hold the fixture protocol so CRITICAL-on-held logic counts it (N1).
        _write_json(self.data_dir / "current_positions.json",
                    {"positions": {"test-protocol": 10_000.0}})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_flags(self, doc):
        _write_json(self.data_dir / "red_flags.json", doc)

    def _write_equity(self, n=5, value=100_000.0):
        """Пишет минимальную equity curve чтобы не триггерить drawdown."""
        curve = {"daily": [{"date": f"2026-06-{i+1:02d}", "close_equity": value} for i in range(n)]}
        _write_json(self.data_dir / "equity_curve_daily.json", curve)

    def test_integration_bootstrap_no_kill_switch(self):
        """run_kill_switch_check: bootstrap-данные не активируют kill_switch."""
        from spa_core.governance.kill_switch import run_kill_switch_check

        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=True,
            sources=["bootstrap"],
        )
        self._write_flags(doc)
        self._write_equity()

        result = run_kill_switch_check(equity_curve=None, data_dir=self.data_dir)
        self.assertFalse(result["triggered"])
        # kill_switch_active.json НЕ должен появиться
        self.assertFalse((self.data_dir / "kill_switch_active.json").exists())

    def test_integration_live_flags_activate_kill_switch(self):
        """run_kill_switch_check: 6 live-флагов активируют kill_switch и пишут файл."""
        from spa_core.governance.kill_switch import run_kill_switch_check

        doc = _make_doc(
            flags=[_make_flag() for _ in range(6)],
            fallback_used=False,
            sources=["defillama"],
        )
        self._write_flags(doc)
        self._write_equity()

        result = run_kill_switch_check(equity_curve=None, data_dir=self.data_dir)
        self.assertTrue(result["triggered"])
        self.assertIn("red_flags", result["reason"])
        # kill_switch_active.json ДОЛЖЕН появиться
        self.assertTrue((self.data_dir / "kill_switch_active.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
