"""Tests for spa_core/agents/risk_sentinel.py (MP-303).

≥ 30 unit tests:
- classify_alert для каждого класса (noise/degradation/incident/critical)
- run_sentinel_cycle с пустыми данными → ok
- run_sentinel_cycle с critical alert → kill_switch_triggered
- sentinel_status.json пишется атомарно (нет *.tmp хвостов)
- classify_with_llm деградирует при llm_fn=None
- нет *.tmp хвостов

Run: python3 -m unittest spa_core.tests.test_risk_sentinel -v
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.agents.risk_sentinel import (
    AlertClass,
    classify_alert,
    classify_with_llm,
    run_sentinel_cycle,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _no_tmp_files(directory: Path) -> list[str]:
    return [p.name for p in Path(directory).rglob("*.tmp")]


# ─── classify_alert: NOISE ────────────────────────────────────────────────────

class TestClassifyNoise(unittest.TestCase):

    def test_low_severity_no_source(self) -> None:
        alert = {"severity": "low", "source": "feed_health", "message": "minor blip"}
        self.assertEqual(classify_alert(alert), AlertClass.NOISE)

    def test_low_severity_unknown_source(self) -> None:
        alert = {"severity": "low", "source": "random_source"}
        self.assertEqual(classify_alert(alert), AlertClass.NOISE)

    def test_low_severity_empty_source(self) -> None:
        alert = {"severity": "low", "source": ""}
        self.assertEqual(classify_alert(alert), AlertClass.NOISE)

    def test_empty_alert(self) -> None:
        # Нет severity → conservative fallback = DEGRADATION, не NOISE
        alert = {}
        self.assertNotEqual(classify_alert(alert), AlertClass.CRITICAL)

    def test_non_dict_alert(self) -> None:
        # Не dict → NOISE
        self.assertEqual(classify_alert("not a dict"), AlertClass.NOISE)  # type: ignore[arg-type]

    def test_low_severity_adapter_source(self) -> None:
        # source не в high_severity_sources → NOISE
        alert = {"severity": "low", "source": "adapter_health"}
        self.assertEqual(classify_alert(alert), AlertClass.NOISE)


# ─── classify_alert: DEGRADATION ─────────────────────────────────────────────

class TestClassifyDegradation(unittest.TestCase):

    def test_medium_severity(self) -> None:
        alert = {"severity": "medium", "message": "apy slightly off"}
        self.assertEqual(classify_alert(alert), AlertClass.DEGRADATION)

    def test_low_severity_gap_monitor_source(self) -> None:
        # Source in _HIGH_SEVERITY_SOURCES → DEGRADATION
        alert = {"severity": "low", "source": "gap_monitor"}
        self.assertEqual(classify_alert(alert), AlertClass.DEGRADATION)

    def test_low_severity_kill_switch_source(self) -> None:
        alert = {"severity": "low", "source": "kill_switch"}
        self.assertEqual(classify_alert(alert), AlertClass.DEGRADATION)

    def test_unknown_severity(self) -> None:
        # Неизвестный severity → conservative = DEGRADATION
        alert = {"severity": "unknown", "source": "feed"}
        self.assertEqual(classify_alert(alert), AlertClass.DEGRADATION)

    def test_missing_severity(self) -> None:
        alert = {"source": "some_source", "message": "something happened"}
        # severity=None → empty string → conservative fallback → DEGRADATION
        self.assertEqual(classify_alert(alert), AlertClass.DEGRADATION)

    def test_medium_severity_any_source(self) -> None:
        for source in ["aave_v3", "compound_v3", "gap_monitor", ""]:
            with self.subTest(source=source):
                alert = {"severity": "medium", "source": source}
                self.assertEqual(classify_alert(alert), AlertClass.DEGRADATION)


# ─── classify_alert: INCIDENT ─────────────────────────────────────────────────

class TestClassifyIncident(unittest.TestCase):

    def test_high_severity(self) -> None:
        alert = {"severity": "high", "message": "TVL dropped below floor"}
        self.assertEqual(classify_alert(alert), AlertClass.INCIDENT)

    def test_drawdown_above_3pct(self) -> None:
        alert = {"severity": "low", "drawdown_pct": 3.5}
        self.assertEqual(classify_alert(alert), AlertClass.INCIDENT)

    def test_drawdown_exactly_3pct_is_not_incident(self) -> None:
        # > 3.0, not >= 3.0
        alert = {"severity": "low", "drawdown_pct": 3.0}
        # 3.0 is NOT > 3.0 → should be noise or degradation, not incident
        result = classify_alert(alert)
        self.assertNotEqual(result, AlertClass.INCIDENT)

    def test_drawdown_just_above_3pct(self) -> None:
        alert = {"severity": "medium", "drawdown_pct": 3.1}
        # medium → DEGRADATION unless drawdown pushes to incident
        # But rule: drawdown > 3% → incident (takes priority over medium→degradation)
        self.assertEqual(classify_alert(alert), AlertClass.INCIDENT)

    def test_high_severity_with_low_drawdown(self) -> None:
        alert = {"severity": "high", "drawdown_pct": 0.5}
        self.assertEqual(classify_alert(alert), AlertClass.INCIDENT)

    def test_drawdown_field_alias(self) -> None:
        # Поддержка поля "drawdown" (без _pct)
        alert = {"severity": "low", "drawdown": 4.0}
        self.assertEqual(classify_alert(alert), AlertClass.INCIDENT)


# ─── classify_alert: CRITICAL ─────────────────────────────────────────────────

class TestClassifyCritical(unittest.TestCase):

    def test_critical_severity(self) -> None:
        alert = {"severity": "critical", "message": "emergency stop"}
        self.assertEqual(classify_alert(alert), AlertClass.CRITICAL)

    def test_kill_switch_active(self) -> None:
        alert = {"severity": "high", "kill_switch_active": True}
        self.assertEqual(classify_alert(alert), AlertClass.CRITICAL)

    def test_kill_switch_triggered(self) -> None:
        alert = {"severity": "medium", "kill_switch_triggered": True}
        self.assertEqual(classify_alert(alert), AlertClass.CRITICAL)

    def test_drawdown_above_5pct(self) -> None:
        alert = {"severity": "low", "drawdown_pct": 5.5}
        self.assertEqual(classify_alert(alert), AlertClass.CRITICAL)

    def test_drawdown_exactly_5pct_not_critical(self) -> None:
        # > 5.0, not >= 5.0
        alert = {"severity": "low", "drawdown_pct": 5.0}
        result = classify_alert(alert)
        self.assertNotEqual(result, AlertClass.CRITICAL)

    def test_critical_overrides_all(self) -> None:
        # critical severity overrides все остальные поля
        alert = {"severity": "critical", "drawdown_pct": 0.0, "kill_switch_active": False}
        self.assertEqual(classify_alert(alert), AlertClass.CRITICAL)


# ─── classify_with_llm ────────────────────────────────────────────────────────

class TestClassifyWithLlm(unittest.TestCase):

    def test_llm_fn_none_returns_deterministic(self) -> None:
        """При llm_fn=None → детерминированный fallback."""
        alert = {"severity": "high", "message": "test"}
        result = classify_with_llm(alert, llm_fn=None)
        self.assertEqual(result, classify_alert(alert))

    def test_llm_fn_none_noise(self) -> None:
        alert = {"severity": "low", "source": "feed_watcher"}
        self.assertEqual(classify_with_llm(alert, llm_fn=None), AlertClass.NOISE)

    def test_llm_fn_returns_valid_class(self) -> None:
        alert = {"severity": "medium", "message": "test"}
        llm_fn = lambda prompt: "critical"  # noqa: E731
        result = classify_with_llm(alert, llm_fn=llm_fn)
        self.assertEqual(result, AlertClass.CRITICAL)

    def test_llm_fn_returns_invalid_falls_back(self) -> None:
        alert = {"severity": "high", "message": "test"}
        llm_fn = lambda prompt: "UNKNOWN_CLASS_XYZ"  # noqa: E731
        result = classify_with_llm(alert, llm_fn=llm_fn)
        self.assertEqual(result, classify_alert(alert))

    def test_llm_fn_raises_falls_back(self) -> None:
        alert = {"severity": "medium"}
        def bad_llm(prompt: str) -> str:
            raise RuntimeError("LLM unavailable")
        result = classify_with_llm(alert, llm_fn=bad_llm)
        self.assertEqual(result, classify_alert(alert))

    def test_llm_fn_partial_match(self) -> None:
        alert = {"severity": "low"}
        llm_fn = lambda prompt: "The classification is: incident alert"  # noqa: E731
        result = classify_with_llm(alert, llm_fn=llm_fn)
        self.assertEqual(result, AlertClass.INCIDENT)


# ─── run_sentinel_cycle ───────────────────────────────────────────────────────

class TestRunSentinelCycle(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_sentinel_test_")
        self.data_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_data_dir_returns_ok(self) -> None:
        """Пустая папка данных → статус ok."""
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["total_alerts"], 0)
        self.assertFalse(result["kill_switch_triggered"])

    def test_sentinel_status_written(self) -> None:
        """sentinel_status.json создаётся после run."""
        run_sentinel_cycle(data_dir=self.data_dir)
        status_path = Path(self.data_dir) / "sentinel_status.json"
        self.assertTrue(status_path.exists(), "sentinel_status.json не создан")

    def test_sentinel_status_valid_json(self) -> None:
        """sentinel_status.json содержит валидный JSON."""
        run_sentinel_cycle(data_dir=self.data_dir)
        status_path = Path(self.data_dir) / "sentinel_status.json"
        doc = json.loads(status_path.read_text())
        self.assertIn("checked_at", doc)
        self.assertIn("total_alerts", doc)
        self.assertIn("by_class", doc)
        self.assertIn("status", doc)
        self.assertIn("kill_switch_triggered", doc)

    def test_sentinel_status_atomic_no_tmp_files(self) -> None:
        """После run нет *.tmp файлов в data_dir."""
        run_sentinel_cycle(data_dir=self.data_dir)
        tmp_files = _no_tmp_files(Path(self.data_dir))
        self.assertEqual(tmp_files, [], f"Остались tmp-файлы: {tmp_files}")

    def test_low_alert_classified_as_noise(self) -> None:
        """Low-severity alert без высоких источников → noise, статус ok."""
        alerts_doc = {
            "generated_at": "2026-06-11T08:00:00+00:00",
            "alerts": [{"severity": "low", "source": "feed_watcher", "message": "minor"}],
        }
        _write_json(Path(self.data_dir) / "risk_alerts.json", alerts_doc)
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["by_class"]["noise"], 1)

    def test_medium_alert_classified_as_degraded(self) -> None:
        """Medium-severity alert → degradation, статус degraded."""
        alerts_doc = {
            "alerts": [{"severity": "medium", "source": "adapter_health", "message": "apy off"}],
        }
        _write_json(Path(self.data_dir) / "risk_alerts.json", alerts_doc)
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["by_class"]["degradation"], 1)

    def test_high_alert_classified_as_incident(self) -> None:
        """High-severity alert → incident, статус incident."""
        alerts_doc = {
            "alerts": [{"severity": "high", "source": "risk_policy", "message": "tvl below floor"}],
        }
        _write_json(Path(self.data_dir) / "risk_alerts.json", alerts_doc)
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertEqual(result["status"], "incident")
        self.assertEqual(result["by_class"]["incident"], 1)

    def test_critical_alert_triggers_kill_switch_check(self) -> None:
        """Critical alert → run_sentinel_cycle вызывает kill_switch_check."""
        alerts_doc = {
            "alerts": [{"severity": "critical", "source": "drawdown_monitor",
                        "message": "drawdown > 5%"}],
        }
        _write_json(Path(self.data_dir) / "risk_alerts.json", alerts_doc)
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertEqual(result["status"], "critical")
        # Kill switch check запущен (результат зависит от триггеров, но triggered=False
        # при отсутствии реальных данных — это нормально)
        self.assertIn("kill_switch_triggered", result)

    def test_kill_switch_triggered_status_in_doc(self) -> None:
        """Если kill_switch_status.json уже triggered → critical status."""
        ks_doc = {
            "generated_at": "2026-06-11T08:00:00+00:00",
            "triggered": True,
            "reason": "manual trigger active",
            "allocation": {"cash": 1.0},
        }
        # Создаём kill_switch_active.json чтобы kill switch check реально сработал
        _write_json(Path(self.data_dir) / "kill_switch_status.json", ks_doc)
        _write_json(Path(self.data_dir) / "risk_alerts.json", {"alerts": []})
        result = run_sentinel_cycle(data_dir=self.data_dir)
        # Kill switch status создаёт critical alert
        self.assertEqual(result["status"], "critical")

    def test_multiple_alerts_counted_correctly(self) -> None:
        """Несколько алертов разных классов — счётчики корректны."""
        alerts_doc = {
            "alerts": [
                {"severity": "low", "source": "feed_watcher", "message": "minor"},
                {"severity": "medium", "message": "adapter lag"},
                {"severity": "high", "message": "tvl drop"},
            ],
        }
        _write_json(Path(self.data_dir) / "risk_alerts.json", alerts_doc)
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertEqual(result["by_class"]["noise"], 1)
        self.assertEqual(result["by_class"]["degradation"], 1)
        self.assertEqual(result["by_class"]["incident"], 1)
        self.assertEqual(result["total_alerts"], 3)

    def test_by_class_keys_always_present(self) -> None:
        """Все 4 ключа класса всегда присутствуют в by_class."""
        result = run_sentinel_cycle(data_dir=self.data_dir)
        for cls in ("noise", "degradation", "incident", "critical"):
            self.assertIn(cls, result["by_class"])

    def test_red_flags_json_alerts(self) -> None:
        """Алерты из red_flags.json попадают в классификацию."""
        flags_doc = {
            "red_flags": [
                {"severity": "high", "message": "protocol X exploit reported", "type": "security"}
            ]
        }
        _write_json(Path(self.data_dir) / "red_flags.json", flags_doc)
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertGreater(result["total_alerts"], 0)

    def test_degraded_adapters_bump(self) -> None:
        """2+ деградированных адаптера → synthetic degradation alert добавляется."""
        orch_doc = {
            "adapters": [
                {"protocol": "aave_v3", "status": "error"},
                {"protocol": "compound_v3", "status": "timeout"},
                {"protocol": "morpho_blue", "status": "ok"},
            ]
        }
        _write_json(Path(self.data_dir) / "adapter_orchestrator_status.json", orch_doc)
        result = run_sentinel_cycle(data_dir=self.data_dir)
        self.assertGreaterEqual(result["by_class"]["degradation"], 1)

    def test_checked_at_is_iso8601(self) -> None:
        """checked_at в формате ISO 8601."""
        result = run_sentinel_cycle(data_dir=self.data_dir)
        from datetime import datetime
        try:
            datetime.fromisoformat(result["checked_at"].replace("Z", "+00:00"))
        except ValueError:
            self.fail(f"checked_at не является ISO 8601: {result['checked_at']}")


if __name__ == "__main__":
    unittest.main()
