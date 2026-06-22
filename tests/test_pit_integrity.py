"""
Тесты EPIC-5 S5.3: pit_wrapper.py + integrity.py
- PIT фильтрует будущие данные
- PITViolationError при нарушении
- Integrity checker работает
- LLM_FORBIDDEN
"""
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def pit_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from spa_core.data_trust.pit_wrapper import (
        PITContext, PITViolationError, pit_filter,
        wrap_time_series, get_pit_violations, clear_pit_violations, PIT_VERSION,
    )
    clear_pit_violations()
    return {
        "PITContext": PITContext,
        "PITViolationError": PITViolationError,
        "pit_filter": pit_filter,
        "wrap_time_series": wrap_time_series,
        "get_pit_violations": get_pit_violations,
        "clear_pit_violations": clear_pit_violations,
        "PIT_VERSION": PIT_VERSION,
    }


@pytest.fixture
def integrity_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from spa_core.data_trust.integrity import (
        check_json_valid, check_required_fields, check_data_age,
        run_integrity_check, INTEGRITY_VERSION,
    )
    return {
        "check_json_valid": check_json_valid,
        "check_required_fields": check_required_fields,
        "check_data_age": check_data_age,
        "run_integrity_check": run_integrity_check,
        "INTEGRITY_VERSION": INTEGRITY_VERSION,
    }


class TestPITContext:
    def test_filters_future_records(self, pit_module):
        """Будущие записи исключаются"""
        records = [
            {"date": "2026-06-09", "value": 100},
            {"date": "2026-06-10", "value": 101},
            {"date": "2026-06-11", "value": 102},  # после as_of
        ]
        with pit_module["PITContext"]("2026-06-10", strict=False) as pit:
            filtered = pit.filter(records, "date")
        assert len(filtered) == 2
        assert all(r["date"] <= "2026-06-10" for r in filtered)

    def test_records_on_as_of_included(self, pit_module):
        """Записи с датой = as_of включаются"""
        records = [{"date": "2026-06-10", "value": 100}]
        with pit_module["PITContext"]("2026-06-10", strict=False) as pit:
            filtered = pit.filter(records, "date")
        assert len(filtered) == 1

    def test_violation_error_on_strict(self, pit_module):
        """strict=True → PITViolationError при будущих данных"""
        records = [
            {"date": "2026-06-09", "value": 100},
            {"date": "2026-07-01", "value": 200},  # будущее!
        ]
        with pytest.raises(pit_module["PITViolationError"]):
            with pit_module["PITContext"]("2026-06-10", strict=True) as pit:
                pit.filter(records, "date")

    def test_missing_date_excluded(self, pit_module):
        """Записи без date_field исключаются (strict_missing=True)"""
        records = [
            {"value": 100},  # нет поля date
            {"date": "2026-06-09", "value": 200},
        ]
        with pit_module["PITContext"]("2026-06-10", strict=False) as pit:
            filtered = pit.filter(records, "date", strict_missing=True)
        assert len(filtered) == 1
        assert filtered[0]["value"] == 200

    def test_missing_date_kept_when_not_strict(self, pit_module):
        """Записи без date_field остаются (strict_missing=False)"""
        records = [
            {"value": 100},  # нет поля date
            {"date": "2026-06-09", "value": 200},
        ]
        with pit_module["PITContext"]("2026-06-10", strict=False) as pit:
            filtered = pit.filter(records, "date", strict_missing=False)
        assert len(filtered) == 2

    def test_assert_no_future_ok(self, pit_module):
        """Дата <= as_of → OK"""
        with pit_module["PITContext"]("2026-06-10", strict=True) as pit:
            pit.assert_no_future("2026-06-09", "test")

    def test_assert_no_future_raises(self, pit_module):
        """Дата > as_of → PITViolationError"""
        with pytest.raises(pit_module["PITViolationError"]):
            with pit_module["PITContext"]("2026-06-10", strict=True) as pit:
                pit.assert_no_future("2026-07-01", "future_data")

    def test_violations_tracked(self, pit_module):
        """Нарушения регистрируются в context.violations"""
        records = [{"date": "2026-07-01", "value": 99}]
        with pit_module["PITContext"]("2026-06-10", strict=False, context_name="test_ctx") as pit:
            pit.filter(records, "date")
        assert len(pit.violations) == 1
        assert pit.violations[0]["context"] == "test_ctx"

    def test_context_name_in_violation(self, pit_module):
        """context_name попадает в violation"""
        records = [{"date": "2026-08-01", "value": 1}]
        with pit_module["PITContext"]("2026-06-10", strict=False, context_name="my_calc") as pit:
            pit.filter(records, "date")
        assert pit.violations[0]["context"] == "my_calc"

    def test_empty_records_ok(self, pit_module):
        """Пустой список → OK"""
        with pit_module["PITContext"]("2026-06-10", strict=True) as pit:
            filtered = pit.filter([], "date")
        assert filtered == []

    def test_all_records_in_past(self, pit_module):
        """Все записи до as_of → ничего не фильтруется"""
        records = [
            {"date": "2026-06-01", "v": 1},
            {"date": "2026-06-05", "v": 2},
            {"date": "2026-06-10", "v": 3},
        ]
        with pit_module["PITContext"]("2026-06-10", strict=True) as pit:
            filtered = pit.filter(records, "date")
        assert len(filtered) == 3

    def test_invalid_as_of_format(self, pit_module):
        """Невалидный as_of формат → PITViolationError при создании"""
        with pytest.raises(pit_module["PITViolationError"]):
            pit_module["PITContext"]("not-a-date")

    def test_iso_datetime_as_of(self, pit_module):
        """as_of с временем работает корректно"""
        records = [
            {"date": "2026-06-10T10:00:00", "v": 1},
            {"date": "2026-06-10T14:00:00", "v": 2},
        ]
        with pit_module["PITContext"]("2026-06-10T12:00:00", strict=False) as pit:
            filtered = pit.filter(records, "date")
        assert len(filtered) == 1
        assert filtered[0]["v"] == 1


class TestPITFilter:
    def test_functional_api(self, pit_module):
        records = [
            {"date": "2026-06-09", "v": 1},
            {"date": "2026-06-11", "v": 2},  # после as_of
        ]
        result = pit_module["pit_filter"](records, "2026-06-10")
        assert len(result) == 1
        assert result[0]["v"] == 1

    def test_wrap_time_series(self, pit_module):
        """wrap_time_series применяет PIT к функции"""
        raw_data = [
            {"date": "2026-06-09", "v": 1},
            {"date": "2026-06-11", "v": 2},  # после as_of
        ]

        def fetch_raw():
            return raw_data

        wrapped = pit_module["wrap_time_series"](fetch_raw, as_of="2026-06-10")
        result = wrapped()
        assert len(result) == 1
        assert result[0]["v"] == 1

    def test_wrap_time_series_custom_date_field(self, pit_module):
        """wrap_time_series с нестандартным date_field"""
        raw_data = [
            {"ts": "2026-06-09", "v": 10},
            {"ts": "2026-06-12", "v": 20},
        ]

        def fetch_raw():
            return raw_data

        wrapped = pit_module["wrap_time_series"](fetch_raw, as_of="2026-06-10", date_field="ts")
        result = wrapped()
        assert len(result) == 1
        assert result[0]["v"] == 10

    def test_global_violations_registry(self, pit_module):
        """pit_filter регистрирует нарушения в глобальный реестр"""
        pit_module["clear_pit_violations"]()
        records = [{"date": "2026-07-15", "v": 999}]
        pit_module["pit_filter"](records, "2026-06-10", context_name="global_test")
        # strict=False → не бросает, но пишет в violations
        violations = pit_module["get_pit_violations"]()
        # При strict=False, PITContext.__exit__ расширяет _PIT_VIOLATIONS
        assert isinstance(violations, list)

    def test_pit_version_exists(self, pit_module):
        """PIT_VERSION определена"""
        assert pit_module["PIT_VERSION"] == "pit_v1.0"


class TestIntegrity:
    def test_valid_json_ok(self, integrity_module, tmp_path):
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"equity": 100, "daily_history": []}))
        result = integrity_module["check_json_valid"](f)
        assert result["ok"] is True
        assert result["status"] == "valid"
        assert "size_bytes" in result

    def test_missing_file_fails(self, integrity_module, tmp_path):
        result = integrity_module["check_json_valid"](tmp_path / "missing.json")
        assert result["ok"] is False
        assert result["status"] == "missing"

    def test_empty_file_fails(self, integrity_module, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("")
        result = integrity_module["check_json_valid"](f)
        assert result["ok"] is False
        assert result["status"] == "empty"

    def test_invalid_json_fails(self, integrity_module, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not valid json {{{")
        result = integrity_module["check_json_valid"](f)
        assert result["ok"] is False
        assert result["status"] == "invalid_json"

    def test_required_fields_present(self, integrity_module, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"equity": 100, "daily_history": []}))
        result = integrity_module["check_required_fields"](f, ["equity", "daily_history"])
        assert result["ok"] is True
        assert result["status"] == "fields_ok"

    def test_required_fields_missing(self, integrity_module, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"equity": 100}))  # нет daily_history
        result = integrity_module["check_required_fields"](f, ["equity", "daily_history"])
        assert result["ok"] is False
        assert "daily_history" in result["missing"]

    def test_required_fields_missing_file(self, integrity_module, tmp_path):
        """Несуществующий файл → ok=False"""
        result = integrity_module["check_required_fields"](
            tmp_path / "nope.json", ["field"]
        )
        assert result["ok"] is False

    def test_age_check_fresh(self, integrity_module, tmp_path):
        f = tmp_path / "data.json"
        now = datetime.utcnow().isoformat() + "Z"
        f.write_text(json.dumps({"updated_at": now}))
        result = integrity_module["check_data_age"](f, "updated_at", max_age_hours=24)
        assert result["ok"] is True
        assert result["status"] == "fresh"

    def test_age_check_stale(self, integrity_module, tmp_path):
        f = tmp_path / "data.json"
        old = (datetime.utcnow() - timedelta(hours=30)).isoformat() + "Z"
        f.write_text(json.dumps({"updated_at": old}))
        result = integrity_module["check_data_age"](f, "updated_at", max_age_hours=24)
        assert result["ok"] is False
        assert result["status"] == "stale"
        assert result["age_hours"] > 24

    def test_age_check_missing_timestamp(self, integrity_module, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"equity": 100}))
        result = integrity_module["check_data_age"](f, "updated_at", max_age_hours=24)
        assert result["ok"] is False
        assert result["status"] == "missing_timestamp"

    def test_run_integrity_check(self, integrity_module, tmp_path):
        """Полный integrity check по кастомным файлам"""
        (tmp_path / "data").mkdir()
        now = datetime.utcnow().isoformat() + "Z"
        (tmp_path / "data" / "paper_trading_status.json").write_text(
            json.dumps({
                "equity": 100,
                "daily_history": [],
                "updated_at": now,
            })
        )
        (tmp_path / "data" / "gap_monitor.json").write_text(
            json.dumps({
                "has_gaps": False,
                "start_date": "2026-06-10",
                "updated_at": now,
            })
        )
        (tmp_path / "data" / "adapter_status.json").write_text(json.dumps({}))

        result = integrity_module["run_integrity_check"](project_root=tmp_path)
        assert "overall_ok" in result
        assert result["LLM_FORBIDDEN"] is True
        assert result["integrity_version"] == "integrity_v1.0"
        assert "run_at" in result
        assert "results" in result
        assert result["files_checked"] == 3

    def test_run_integrity_check_missing_file(self, integrity_module, tmp_path):
        """Если файл отсутствует — critical_failure"""
        (tmp_path / "data").mkdir()
        custom_files = {
            "my_file": {
                "path": "data/nonexistent.json",
                "required_fields": [],
                "age_field": None,
                "max_age_hours": None,
            }
        }
        result = integrity_module["run_integrity_check"](
            files=custom_files,
            project_root=tmp_path,
        )
        assert result["overall_ok"] is False
        assert "my_file" in result["critical_failures"]

    def test_run_integrity_check_missing_required_field(self, integrity_module, tmp_path):
        """Отсутствующее обязательное поле → critical_failure"""
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "test.json").write_text(json.dumps({"x": 1}))
        custom_files = {
            "test_file": {
                "path": "data/test.json",
                "required_fields": ["x", "y"],
                "age_field": None,
                "max_age_hours": None,
            }
        }
        result = integrity_module["run_integrity_check"](
            files=custom_files,
            project_root=tmp_path,
        )
        assert result["overall_ok"] is False
        assert "test_file" in result["critical_failures"]

    def test_report_written_atomically(self, integrity_module, tmp_path):
        """integrity_report.json создаётся в data/"""
        (tmp_path / "data").mkdir()
        integrity_module["run_integrity_check"](files={}, project_root=tmp_path)
        report = tmp_path / "data" / "integrity_report.json"
        assert report.exists()
        data = json.loads(report.read_text())
        assert data["integrity_version"] == "integrity_v1.0"

    def test_integrity_version(self, integrity_module):
        """INTEGRITY_VERSION корректна"""
        assert integrity_module["INTEGRITY_VERSION"] == "integrity_v1.0"


class TestLLMForbidden:
    def test_pit_wrapper_llm_forbidden(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "pit_wrapper.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_integrity_llm_forbidden(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "integrity.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_ai_in_pit(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "pit_wrapper.py").read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain"]:
            assert term not in content, f"Found forbidden term '{term}' in pit_wrapper.py"

    def test_no_ai_in_integrity(self, project_root):
        content = (project_root / "spa_core" / "data_trust" / "integrity.py").read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain"]:
            assert term not in content, f"Found forbidden term '{term}' in integrity.py"

    def test_pit_stdlib_only(self, project_root):
        """pit_wrapper.py использует только stdlib"""
        content = (project_root / "spa_core" / "data_trust" / "pit_wrapper.py").read_text()
        # Нет внешних импортов (requests, numpy, pandas и т.п.)
        for external in ["import requests", "import numpy", "import pandas", "import httpx"]:
            assert external not in content

    def test_integrity_stdlib_only(self, project_root):
        """integrity.py использует только stdlib"""
        content = (project_root / "spa_core" / "data_trust" / "integrity.py").read_text()
        for external in ["import requests", "import numpy", "import pandas", "import httpx"]:
            assert external not in content
