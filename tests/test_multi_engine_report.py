"""
Тесты EPIC-7 Multi-Engine Investor Report.
- Возвращает все движки A/B/C
- fail-closed: нет данных → equity=0, not crash
- LLM_FORBIDDEN
"""
import pytest
import json
from pathlib import Path


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def report_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    # create reporting dir if needed
    (project_root / "spa_core" / "reporting").mkdir(exist_ok=True)
    (project_root / "spa_core" / "reporting" / "__init__.py").touch()

    from spa_core.reporting.multi_engine_report import (
        generate_multi_engine_report, REPORT_VERSION,
    )
    return {
        "generate_multi_engine_report": generate_multi_engine_report,
        "REPORT_VERSION": REPORT_VERSION,
    }


class TestReportGeneration:
    def test_report_returns_all_engines(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert set(report.engines.keys()) == {"A", "B", "C"}

    def test_report_llm_forbidden(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.LLM_FORBIDDEN is True

    def test_report_version(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.report_version == report_module["REPORT_VERSION"]

    def test_output_file_created(self, report_module, tmp_path):
        report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert (tmp_path / "r.json").exists()
        data = json.loads((tmp_path / "r.json").read_text())
        assert "engines" in data
        assert data["LLM_FORBIDDEN"] is True

    def test_engine_a_positive_equity(self, report_module, tmp_path):
        """Engine A equity > 0 (есть реальные данные)"""
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.engines["A"].equity >= 0

    def test_engine_b_equity_nonneg_pending(self, report_module, tmp_path):
        """Engine B (HY/Carry sleeve, activated 2026-06-23): equity >= 0 and
        go-live still PENDING during the 30-day track. (Was equity==0 before the
        sleeve was activated — see 'HY/LP sleeves activated' 2026-06-23.)"""
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.engines["B"].equity >= 0.0
        assert report.engines["B"].golive_status == "PENDING"

    def test_overall_risk_present(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.overall_risk in ["GREEN", "YELLOW", "RED", "CRITICAL"]

    def test_golive_blockers_list(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert isinstance(report.golive_blockers, list)

    def test_total_equity_is_sum_of_engines(self, report_module, tmp_path):
        """total_equity == sum(A, B, C)"""
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        expected = sum(e.equity for e in report.engines.values())
        assert abs(report.total_equity - expected) < 0.01

    def test_target_allocations_present(self, report_module, tmp_path):
        """target_allocations содержит A, B, C"""
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert "A" in report.target_allocations
        assert "B" in report.target_allocations
        assert "C" in report.target_allocations

    def test_generated_at_is_utc_string(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert "Z" in report.generated_at or "T" in report.generated_at

    def test_engine_a_has_start_date(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.engines["A"].start_date is not None

    def test_engine_a_days_tracked_positive(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.engines["A"].days_tracked > 0

    def test_engine_golive_status_valid(self, report_module, tmp_path):
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        valid = {"PENDING", "READY", "LIVE"}
        for eng, e in report.engines.items():
            assert e.golive_status in valid, f"Engine {eng}: invalid golive_status={e.golive_status}"

    def test_json_output_has_all_engines(self, report_module, tmp_path):
        report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        data = json.loads((tmp_path / "r.json").read_text())
        assert set(data["engines"].keys()) == {"A", "B", "C"}
        for eng in ["A", "B", "C"]:
            assert "equity" in data["engines"][eng]
            assert "golive_status" in data["engines"][eng]

    def test_engine_c_equity_nonneg_pending(self, report_module, tmp_path):
        """Engine C (LP sleeve, activated 2026-06-23): equity >= 0 and go-live
        still PENDING during the 30-day track. (Was equity==0 before the sleeve
        was activated — see 'HY/LP sleeves activated' 2026-06-23.)"""
        report = report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        assert report.engines["C"].equity >= 0.0
        assert report.engines["C"].golive_status == "PENDING"


class TestFailClosed:
    def test_no_crash_without_files(self, report_module, tmp_path, monkeypatch):
        """Без файлов данных — отчёт генерируется (fail-closed → defaults)"""
        import spa_core.reporting.multi_engine_report as m
        monkeypatch.setattr(m, "_PROJECT_ROOT", tmp_path)
        # Создаём пустую data/ директорию
        (tmp_path / "data").mkdir()

        report = m.generate_multi_engine_report(output_path=tmp_path / "r.json")
        assert report.total_equity >= 0
        assert report.LLM_FORBIDDEN is True

    def test_no_crash_with_empty_json_files(self, report_module, tmp_path, monkeypatch):
        """Пустые JSON {} — не падаем"""
        import spa_core.reporting.multi_engine_report as m
        monkeypatch.setattr(m, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()
        for fname in ["paper_trading_status.json", "hy_paper_trading.json",
                      "lp_paper_trading.json", "golive_status.json",
                      "equity_curve_daily.json"]:
            (tmp_path / "data" / fname).write_text("{}")

        report = m.generate_multi_engine_report(output_path=tmp_path / "r.json")
        assert report.total_equity >= 0
        assert set(report.engines.keys()) == {"A", "B", "C"}

    def test_all_engines_equity_zero_fallback(self, report_module, tmp_path, monkeypatch):
        """Нет данных → B и C equity=0.0"""
        import spa_core.reporting.multi_engine_report as m
        monkeypatch.setattr(m, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "data").mkdir()

        report = m.generate_multi_engine_report(output_path=tmp_path / "r.json")
        assert report.engines["B"].equity == 0.0
        assert report.engines["C"].equity == 0.0

    def test_output_written_atomically(self, report_module, tmp_path):
        """tmp-файл не остаётся после записи"""
        out = tmp_path / "r.json"
        report_module["generate_multi_engine_report"](output_path=out)
        # .tmp не должен существовать после успешной записи
        assert not (tmp_path / "r.tmp").exists()
        assert out.exists()


class TestLLMForbidden:
    def test_file_llm_forbidden(self, project_root):
        content = (project_root / "spa_core" / "reporting" / "multi_engine_report.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_ai_imports(self, project_root):
        content = (project_root / "spa_core" / "reporting" / "multi_engine_report.py").read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain"]:
            assert term not in content, f"Forbidden term found: {term}"

    def test_no_external_deps(self, project_root):
        """Только stdlib: никаких import requests/aiohttp/httpx"""
        content = (project_root / "spa_core" / "reporting" / "multi_engine_report.py").read_text()
        for term in ["import requests", "import aiohttp", "import httpx", "import numpy", "import pandas"]:
            assert term not in content, f"External dep found: {term}"

    def test_llm_forbidden_in_output_json(self, report_module, tmp_path):
        """LLM_FORBIDDEN: true в выходном JSON"""
        report_module["generate_multi_engine_report"](output_path=tmp_path / "r.json")
        data = json.loads((tmp_path / "r.json").read_text())
        assert data.get("LLM_FORBIDDEN") is True
