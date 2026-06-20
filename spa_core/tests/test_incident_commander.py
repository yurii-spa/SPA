"""Tests for spa_core/agents/incident_commander.py (MP-308).

≥ 25 unit tests:
- create_incident создаёт файл в data/incidents/
- context_snapshot fail-safe (нет файлов → пустой dict)
- postmortem_draft заполнен для каждого типа (drawdown/gap/credit)
- response_checklist не пустой
- дедупликация в run_incident_check (1 инцидент/тип/час)
- resolve_incident меняет status на "resolved"
- нет *.tmp хвостов

Run: python3 -m unittest spa_core.tests.test_incident_commander -v
"""
from __future__ import annotations

import json
import sys
import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.agents.incident_commander import (
    IncidentSeverity,
    create_incident,
    list_open_incidents,
    resolve_incident,
    run_incident_check,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _no_tmp_files(directory: Path) -> list[str]:
    return [p.name for p in Path(directory).rglob("*.tmp")]


def _make_critical_alert(alert_type: str = "drawdown") -> dict:
    return {
        "severity": "critical",
        "source": "risk_sentinel",
        "message": f"Critical {alert_type} alert",
        "type": alert_type,
    }


# ─── create_incident ──────────────────────────────────────────────────────────

class TestCreateIncident(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ic_test_")
        self.data_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_creates_file_in_incidents_dir(self) -> None:
        """create_incident создаёт файл в data/incidents/."""
        alert = _make_critical_alert("drawdown")
        create_incident(alert, data_dir=self.data_dir)
        incidents_path = Path(self.data_dir) / "incidents"
        files = list(incidents_path.glob("incident_*.json"))
        self.assertEqual(len(files), 1, f"Expected 1 incident file, got: {files}")

    def test_incident_has_required_fields(self) -> None:
        """Возвращённый инцидент содержит все обязательные поля."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        for field in ("incident_id", "created_at", "severity", "trigger_alert",
                      "context_snapshot", "timeline", "postmortem_draft",
                      "response_checklist", "status", "resolved_at"):
            self.assertIn(field, incident, f"Поле {field!r} отсутствует в инциденте")

    def test_incident_status_open(self) -> None:
        """Новый инцидент имеет статус 'open'."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        self.assertEqual(incident["status"], "open")

    def test_incident_resolved_at_null(self) -> None:
        """resolved_at = None для нового инцидента."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        self.assertIsNone(incident["resolved_at"])

    def test_incident_id_is_uuid4(self) -> None:
        """incident_id — валидный UUID4."""
        import uuid
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        try:
            uuid.UUID(incident["incident_id"], version=4)
        except ValueError:
            self.fail(f"incident_id не является UUID4: {incident['incident_id']}")

    def test_no_tmp_files_after_create(self) -> None:
        """После create_incident нет *.tmp файлов."""
        alert = _make_critical_alert()
        create_incident(alert, data_dir=self.data_dir)
        tmp_files = _no_tmp_files(Path(self.data_dir))
        self.assertEqual(tmp_files, [], f"Остались tmp-файлы: {tmp_files}")

    def test_context_snapshot_fail_safe_empty(self) -> None:
        """context_snapshot заполнен пустыми dict при отсутствии файлов."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        snapshot = incident["context_snapshot"]
        self.assertIsInstance(snapshot, dict)
        # Все ожидаемые файлы присутствуют как ключи (с пустыми значениями)
        for key in ("equity_curve_daily.json", "kill_switch_status.json"):
            self.assertIn(key, snapshot, f"Ключ {key!r} отсутствует в snapshot")
        for key, value in snapshot.items():
            self.assertIsInstance(value, dict,
                f"snapshot[{key!r}] должен быть dict, получен {type(value)}")

    def test_context_snapshot_reads_existing_files(self) -> None:
        """context_snapshot содержит данные из существующих файлов."""
        equity_doc = {"daily": [{"date": "2026-06-11", "equity": 100500.0}]}
        _write_json(Path(self.data_dir) / "equity_curve_daily.json", equity_doc)
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        snapshot = incident["context_snapshot"]
        self.assertIn("daily", snapshot["equity_curve_daily.json"])

    def test_trigger_alert_stored_in_incident(self) -> None:
        """trigger_alert хранится в инциденте без изменений."""
        alert = {"severity": "critical", "source": "test", "message": "test message",
                 "type": "drawdown"}
        incident = create_incident(alert, data_dir=self.data_dir)
        self.assertEqual(incident["trigger_alert"], alert)

    def test_incident_written_to_disk_correctly(self) -> None:
        """Файл на диске содержит тот же инцидент, что вернул create_incident."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        incidents_path = Path(self.data_dir) / "incidents"
        files = list(incidents_path.glob("incident_*.json"))
        disk_doc = json.loads(files[0].read_text())
        self.assertEqual(disk_doc["incident_id"], incident["incident_id"])
        self.assertEqual(disk_doc["status"], "open")


# ─── postmortem_draft ─────────────────────────────────────────────────────────

class TestPostmortemDraft(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ic_pm_test_")
        self.data_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _create_and_get_postmortem(self, alert_type: str) -> dict:
        alert = _make_critical_alert(alert_type)
        incident = create_incident(alert, data_dir=self.data_dir)
        return incident["postmortem_draft"]

    def test_postmortem_drawdown_has_all_fields(self) -> None:
        pm = self._create_and_get_postmortem("drawdown")
        for field in ("what_happened", "impact", "contributing_factors", "action_items"):
            self.assertIn(field, pm, f"Поле {field!r} отсутствует в postmortem_draft")

    def test_postmortem_gap_has_all_fields(self) -> None:
        pm = self._create_and_get_postmortem("gap")
        for field in ("what_happened", "impact", "contributing_factors", "action_items"):
            self.assertIn(field, pm)

    def test_postmortem_credit_has_all_fields(self) -> None:
        pm = self._create_and_get_postmortem("credit")
        for field in ("what_happened", "impact", "contributing_factors", "action_items"):
            self.assertIn(field, pm)

    def test_postmortem_what_happened_from_message(self) -> None:
        alert = {"severity": "critical", "type": "drawdown",
                 "message": "Portfolio drawdown exceeded 5%"}
        incident = create_incident(alert, data_dir=self.data_dir)
        pm = incident["postmortem_draft"]
        self.assertIn("Portfolio drawdown exceeded 5%", pm["what_happened"])

    def test_postmortem_action_items_not_empty(self) -> None:
        for alert_type in ("drawdown", "gap", "credit", "depeg", "default"):
            with self.subTest(alert_type=alert_type):
                pm = self._create_and_get_postmortem(alert_type)
                self.assertGreater(len(pm["action_items"]), 0,
                    f"action_items пустой для {alert_type}")

    def test_postmortem_contributing_factors_from_red_flags(self) -> None:
        """contributing_factors включает red_flags из снэпшота."""
        flags_doc = {
            "red_flags": [
                {"severity": "high", "message": "protocol X hack", "type": "security"}
            ]
        }
        _write_json(Path(self.data_dir) / "red_flags.json", flags_doc)
        alert = _make_critical_alert("drawdown")
        incident = create_incident(alert, data_dir=self.data_dir)
        pm = incident["postmortem_draft"]
        self.assertIn("protocol X hack", pm["contributing_factors"])


# ─── response_checklist ───────────────────────────────────────────────────────

class TestResponseChecklist(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ic_ck_test_")
        self.data_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_checklist_not_empty(self) -> None:
        for alert_type in ("drawdown", "gap", "credit", "depeg", "kill_switch", "default"):
            with self.subTest(alert_type=alert_type):
                alert = _make_critical_alert(alert_type)
                incident = create_incident(alert, data_dir=self.data_dir)
                self.assertGreater(len(incident["response_checklist"]), 0,
                    f"response_checklist пустой для {alert_type}")

    def test_checklist_is_list_of_strings(self) -> None:
        alert = _make_critical_alert("drawdown")
        incident = create_incident(alert, data_dir=self.data_dir)
        for item in incident["response_checklist"]:
            self.assertIsInstance(item, str)

    def test_drawdown_checklist_mentions_kill_switch(self) -> None:
        alert = _make_critical_alert("drawdown")
        incident = create_incident(alert, data_dir=self.data_dir)
        combined = " ".join(incident["response_checklist"]).lower()
        self.assertIn("kill", combined)

    def test_gap_checklist_mentions_launchd(self) -> None:
        alert = _make_critical_alert("gap")
        incident = create_incident(alert, data_dir=self.data_dir)
        combined = " ".join(incident["response_checklist"]).lower()
        self.assertIn("launchd", combined)


# ─── resolve_incident ─────────────────────────────────────────────────────────

class TestResolveIncident(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ic_resolve_test_")
        self.data_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_resolve_changes_status(self) -> None:
        """resolve_incident меняет status на 'resolved'."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        success = resolve_incident(incident["incident_id"], data_dir=self.data_dir)
        self.assertTrue(success)
        # Перечитываем с диска
        incidents_path = Path(self.data_dir) / "incidents"
        files = list(incidents_path.glob("incident_*.json"))
        disk_doc = json.loads(files[0].read_text())
        self.assertEqual(disk_doc["status"], "resolved")

    def test_resolve_sets_resolved_at(self) -> None:
        """resolve_incident устанавливает resolved_at."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        resolve_incident(incident["incident_id"], data_dir=self.data_dir)
        incidents_path = Path(self.data_dir) / "incidents"
        files = list(incidents_path.glob("incident_*.json"))
        disk_doc = json.loads(files[0].read_text())
        self.assertIsNotNone(disk_doc["resolved_at"])

    def test_resolve_nonexistent_returns_false(self) -> None:
        """resolve_incident несуществующего ID возвращает False."""
        result = resolve_incident("non-existent-id-00000000", data_dir=self.data_dir)
        self.assertFalse(result)

    def test_resolve_no_tmp_files(self) -> None:
        """После resolve нет *.tmp файлов."""
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        resolve_incident(incident["incident_id"], data_dir=self.data_dir)
        tmp_files = _no_tmp_files(Path(self.data_dir))
        self.assertEqual(tmp_files, [], f"Остались tmp-файлы: {tmp_files}")


# ─── list_open_incidents ──────────────────────────────────────────────────────

class TestListOpenIncidents(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ic_list_test_")
        self.data_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_dir_returns_empty(self) -> None:
        result = list_open_incidents(data_dir=self.data_dir)
        self.assertEqual(result, [])

    def test_open_incidents_returned(self) -> None:
        for _ in range(3):
            create_incident(_make_critical_alert(), data_dir=self.data_dir)
        result = list_open_incidents(data_dir=self.data_dir)
        self.assertEqual(len(result), 3)

    def test_resolved_not_returned(self) -> None:
        alert = _make_critical_alert()
        incident = create_incident(alert, data_dir=self.data_dir)
        resolve_incident(incident["incident_id"], data_dir=self.data_dir)
        result = list_open_incidents(data_dir=self.data_dir)
        self.assertEqual(result, [])


# ─── run_incident_check ───────────────────────────────────────────────────────

class TestRunIncidentCheck(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ic_check_test_")
        self.data_dir = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_sentinel_status(self, status: str) -> None:
        doc = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "total_alerts": 1 if status == "critical" else 0,
            "by_class": {"noise": 0, "degradation": 0, "incident": 0,
                         "critical": 1 if status == "critical" else 0},
            "kill_switch_triggered": False,
        }
        _write_json(Path(self.data_dir) / "sentinel_status.json", doc)

    def test_no_sentinel_status_returns_skip(self) -> None:
        result = run_incident_check(data_dir=self.data_dir)
        self.assertEqual(result["action"], "skip")

    def test_non_critical_status_returns_skip(self) -> None:
        self._write_sentinel_status("ok")
        result = run_incident_check(data_dir=self.data_dir)
        self.assertEqual(result["action"], "skip")

    def test_critical_status_creates_incident(self) -> None:
        self._write_sentinel_status("critical")
        result = run_incident_check(data_dir=self.data_dir)
        self.assertEqual(result["action"], "created")
        self.assertIn("incident_id", result)

    def test_deduplication_same_type_same_hour(self) -> None:
        """Два вызова подряд для одного типа — второй дедуплицируется."""
        self._write_sentinel_status("critical")
        result1 = run_incident_check(data_dir=self.data_dir)
        self.assertEqual(result1["action"], "created")
        result2 = run_incident_check(data_dir=self.data_dir)
        self.assertEqual(result2["action"], "deduplicated",
            f"Ожидалась дедупликация, получен: {result2}")

    def test_deduplication_same_incident_id_returned(self) -> None:
        """При дедупликации возвращается incident_id первого инцидента."""
        self._write_sentinel_status("critical")
        result1 = run_incident_check(data_dir=self.data_dir)
        result2 = run_incident_check(data_dir=self.data_dir)
        self.assertEqual(result1["incident_id"], result2["incident_id"])

    def test_run_incident_check_no_tmp_files(self) -> None:
        """После run_incident_check нет *.tmp файлов."""
        self._write_sentinel_status("critical")
        run_incident_check(data_dir=self.data_dir)
        tmp_files = _no_tmp_files(Path(self.data_dir))
        self.assertEqual(tmp_files, [], f"Остались tmp-файлы: {tmp_files}")


if __name__ == "__main__":
    unittest.main()
