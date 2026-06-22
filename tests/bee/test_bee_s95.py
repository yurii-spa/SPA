"""
Тесты BEE S9.5: failure_boundary.py
- Все сценарии S1-S8 проходят evaluate_scenario
- Catastrophic (S5) → failed
- Mild (S1) → survived
- Failure boundary найден
- LLM_FORBIDDEN
- No APY promises
"""
import pytest
from pathlib import Path


@pytest.fixture(scope="module")
def project_root():
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fb_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from spa_core.bee.failure_boundary import (
        evaluate_scenario,
        find_failure_boundary,
        run_full_failure_analysis,
        SYNTHETIC_SCENARIOS,
        StressScenario,
        FAILURE_BOUNDARY_VERSION,
    )
    return {
        "evaluate_scenario": evaluate_scenario,
        "find_failure_boundary": find_failure_boundary,
        "run_full_failure_analysis": run_full_failure_analysis,
        "SYNTHETIC_SCENARIOS": SYNTHETIC_SCENARIOS,
        "StressScenario": StressScenario,
        "FAILURE_BOUNDARY_VERSION": FAILURE_BOUNDARY_VERSION,
    }


# =====================================================================
# 1. TestScenarioEvaluation
# =====================================================================

class TestScenarioEvaluation:
    def test_mild_depeg_survived(self, fb_module):
        """S1 (0.5% depeg) → survived (не failed)"""
        s1 = next(
            s for s in fb_module["SYNTHETIC_SCENARIOS"]
            if s.scenario_id == "S1_MILD_DEPEG"
        )
        result = fb_module["evaluate_scenario"](s1)
        assert result.outcome in ["survived", "alarm"], (
            f"S1 ожидаем survived/alarm, получили {result.outcome}"
        )

    def test_catastrophic_failed(self, fb_module):
        """S5 (UST-like 30% depeg) → failed"""
        s5 = next(
            s for s in fb_module["SYNTHETIC_SCENARIOS"]
            if s.scenario_id == "S5_CATASTROPHIC"
        )
        result = fb_module["evaluate_scenario"](s5)
        assert result.outcome == "failed", (
            f"S5 ожидаем failed, получили {result.outcome} "
            f"(drawdown={result.drawdown_pct:.4f})"
        )

    def test_gate_triggered_on_high_depeg(self, fb_module):
        """Депег > 0.6% (exit threshold) → gate_triggered=True"""
        s = fb_module["StressScenario"](
            scenario_id="TEST_GATE",
            label="Test gate",
            description="Test",
            depeg_pct=0.01,   # 1% > 0.6% exit threshold
            duration_days=3,
            tvl_drop_pct=0.15,
            funding_rate_drop=0.02,
            max_drawdown_pct=0.01,
        )
        result = fb_module["evaluate_scenario"](s)
        assert result.gate_triggered is True

    def test_small_depeg_gate_not_triggered(self, fb_module):
        """Депег < 0.6% exit threshold → gate_triggered=False (если нет TVL/funding breach)"""
        s = fb_module["StressScenario"](
            scenario_id="TEST_SMALL",
            label="Small depeg",
            description="Test",
            depeg_pct=0.003,  # < 0.6%
            duration_days=1,
            tvl_drop_pct=0.05,
            funding_rate_drop=0.005,
            max_drawdown_pct=0.005,
        )
        result = fb_module["evaluate_scenario"](s)
        assert result.gate_triggered is False

    def test_result_has_disclaimer(self, fb_module):
        """Каждый результат содержит непустой no_apy_disclaimer"""
        s1 = fb_module["SYNTHETIC_SCENARIOS"][0]
        result = fb_module["evaluate_scenario"](s1)
        assert result.no_apy_disclaimer, "no_apy_disclaimer не должен быть пустым"
        assert len(result.no_apy_disclaimer) > 10

    def test_no_apy_promise_in_policy_response(self, fb_module):
        """No APY promises в policy_response для первых 4 сценариев"""
        for scenario in fb_module["SYNTHETIC_SCENARIOS"][:4]:
            result = fb_module["evaluate_scenario"](scenario)
            resp = result.policy_response.lower()
            assert "will earn" not in resp, f"APY promise в {scenario.scenario_id}"
            assert "expected return" not in resp, f"APY promise в {scenario.scenario_id}"

    def test_all_scenarios_have_valid_outcome(self, fb_module):
        """Все 8 сценариев дают валидный outcome"""
        valid_outcomes = {"survived", "alarm", "failed"}
        for scenario in fb_module["SYNTHETIC_SCENARIOS"]:
            result = fb_module["evaluate_scenario"](scenario)
            assert result.outcome in valid_outcomes, (
                f"{scenario.scenario_id}: неожиданный outcome={result.outcome!r}"
            )
            assert isinstance(result.drawdown_pct, float)
            assert isinstance(result.gate_triggered, bool)

    def test_drawdown_non_negative(self, fb_module):
        """Drawdown всегда >= 0"""
        for scenario in fb_module["SYNTHETIC_SCENARIOS"]:
            result = fb_module["evaluate_scenario"](scenario)
            assert result.drawdown_pct >= 0.0, (
                f"{scenario.scenario_id}: drawdown={result.drawdown_pct} < 0"
            )

    def test_recovery_false_only_on_failed_kill(self, fb_module):
        """recovery_possible=False только для failed сценариев с большим drawdown"""
        for scenario in fb_module["SYNTHETIC_SCENARIOS"]:
            result = fb_module["evaluate_scenario"](scenario)
            if result.outcome == "failed" and result.drawdown_pct >= 0.08:
                assert result.recovery_possible is False, (
                    f"{scenario.scenario_id}: expected recovery_possible=False"
                )

    def test_scenario_ids_unique(self, fb_module):
        """Все scenario_id уникальны"""
        ids = [s.scenario_id for s in fb_module["SYNTHETIC_SCENARIOS"]]
        assert len(ids) == len(set(ids)), "Дублирующиеся scenario_id"

    def test_eight_synthetic_scenarios(self, fb_module):
        """Ровно 8 синтетических сценариев"""
        assert len(fb_module["SYNTHETIC_SCENARIOS"]) == 8

    def test_s1_has_scenario_id(self, fb_module):
        """ScenarioResult.scenario_id соответствует StressScenario.scenario_id"""
        s1 = fb_module["SYNTHETIC_SCENARIOS"][0]
        result = fb_module["evaluate_scenario"](s1)
        assert result.scenario_id == s1.scenario_id

    def test_policy_response_non_empty(self, fb_module):
        """policy_response не пустой для всех сценариев"""
        for scenario in fb_module["SYNTHETIC_SCENARIOS"]:
            result = fb_module["evaluate_scenario"](scenario)
            assert result.policy_response, (
                f"{scenario.scenario_id}: policy_response пустой"
            )

    def test_custom_policy_config(self, fb_module):
        """Кастомный policy_config влияет на результат"""
        strict_config = {
            "depeg_exit_threshold": 0.001,  # очень низкий порог → ловит даже 0.5% депег
            "drawdown_kill_pct": 0.08,
            "funding_rate_exit": 0.02,
            "min_tvl_usd": 100_000_000,
            "tvl_at_entry": 850_000_000,
            "cash_buffer": 0.10,
        }
        s1 = next(
            s for s in fb_module["SYNTHETIC_SCENARIOS"]
            if s.scenario_id == "S1_MILD_DEPEG"
        )
        result = fb_module["evaluate_scenario"](s1, policy_config=strict_config)
        # При очень строгом пороге (0.001 < 0.005) gate должен сработать
        assert result.gate_triggered is True

    def test_funding_gate(self, fb_module):
        """Большое падение фандинга вызывает gate"""
        s = fb_module["StressScenario"](
            scenario_id="TEST_FUNDING",
            label="Funding gate test",
            description="Test large funding drop",
            depeg_pct=0.001,
            duration_days=14,
            tvl_drop_pct=0.05,
            funding_rate_drop=0.08,   # baseline 0.085 - 0.08 = 0.005 < fr_exit 0.02
            max_drawdown_pct=0.01,
        )
        result = fb_module["evaluate_scenario"](s)
        assert result.gate_triggered is True

    def test_tvl_gate(self, fb_module):
        """Огромное падение TVL вызывает gate"""
        s = fb_module["StressScenario"](
            scenario_id="TEST_TVL",
            label="TVL gate test",
            description="Test massive TVL drop",
            depeg_pct=0.001,
            duration_days=3,
            tvl_drop_pct=0.99,   # 850M * 0.01 = 8.5M < min_tvl 100M
            funding_rate_drop=0.005,
            max_drawdown_pct=0.01,
        )
        result = fb_module["evaluate_scenario"](s)
        assert result.gate_triggered is True


# =====================================================================
# 2. TestFailureBoundary
# =====================================================================

class TestFailureBoundary:
    def test_boundary_returns_dict(self, fb_module):
        """find_failure_boundary возвращает dict"""
        result = fb_module["find_failure_boundary"](
            param_name="depeg_pct", lo=0.001, hi=0.5,
        )
        assert isinstance(result, dict)

    def test_boundary_has_required_keys(self, fb_module):
        """Результат содержит ключевые поля"""
        result = fb_module["find_failure_boundary"](
            param_name="depeg_pct", lo=0.001, hi=0.5,
        )
        for key in ("param_name", "boundary_value", "status", "LLM_FORBIDDEN"):
            assert key in result, f"Ключ {key!r} отсутствует"

    def test_boundary_found_status(self, fb_module):
        """Статус — один из ожидаемых"""
        result = fb_module["find_failure_boundary"](
            param_name="depeg_pct", lo=0.001, hi=0.5,
        )
        valid_statuses = {"found", "converging", "no_failure_in_range", "boundary_below_lo"}
        assert result["status"] in valid_statuses

    def test_boundary_value_in_range(self, fb_module):
        """Boundary value входит в [lo, hi]"""
        result = fb_module["find_failure_boundary"](
            param_name="depeg_pct", lo=0.001, hi=0.5,
        )
        if result["status"] in ("found", "converging"):
            assert 0.001 <= result["boundary_value"] <= 0.5

    def test_boundary_llm_forbidden_flag(self, fb_module):
        """LLM_FORBIDDEN=True в результате"""
        result = fb_module["find_failure_boundary"](
            param_name="depeg_pct", lo=0.001, hi=0.5,
        )
        assert result.get("LLM_FORBIDDEN") is True

    def test_boundary_convergence(self, fb_module):
        """Бинарный поиск сходится за разумное число итераций"""
        result = fb_module["find_failure_boundary"](
            param_name="depeg_pct", lo=0.001, hi=0.5,
            tolerance=0.001,
        )
        if result["status"] == "found":
            assert result.get("iterations", 0) <= 30

    def test_boundary_has_note(self, fb_module):
        """note поле присутствует"""
        result = fb_module["find_failure_boundary"](
            param_name="depeg_pct", lo=0.001, hi=0.5,
        )
        assert "note" in result


# =====================================================================
# 3. TestFullAnalysis
# =====================================================================

class TestFullAnalysis:
    def test_full_analysis_runs(self, fb_module, tmp_path):
        """run_full_failure_analysis завершается без ошибок"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert isinstance(result, dict)

    def test_total_scenarios_count(self, fb_module, tmp_path):
        """total_scenarios == 8"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert result["total_scenarios"] == len(fb_module["SYNTHETIC_SCENARIOS"])
        assert result["total_scenarios"] == 8

    def test_survived_alarmed_failed_keys(self, fb_module, tmp_path):
        """Ключи survived, alarmed, failed присутствуют"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        for key in ("survived", "alarmed", "failed"):
            assert key in result, f"Ключ {key!r} отсутствует"

    def test_llm_forbidden_in_output(self, fb_module, tmp_path):
        """LLM_FORBIDDEN=True в сводном результате"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert result["LLM_FORBIDDEN"] is True

    def test_output_json_created(self, fb_module, tmp_path):
        """failure_boundary.json создаётся в output_dir"""
        fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert (tmp_path / "failure_boundary.json").exists()

    def test_output_json_parseable(self, fb_module, tmp_path):
        """failure_boundary.json валидный JSON"""
        import json
        fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        data = json.loads((tmp_path / "failure_boundary.json").read_text())
        assert data.get("total_scenarios") == 8

    def test_survival_rate_valid(self, fb_module, tmp_path):
        """0 <= survival_rate <= 1"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert 0.0 <= result["survival_rate"] <= 1.0

    def test_scenarios_in_output(self, fb_module, tmp_path):
        """Все 8 сценариев присутствуют в scenarios-списке"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert len(result["scenarios"]) == 8

    def test_each_scenario_has_outcome(self, fb_module, tmp_path):
        """Каждый сценарий в scenarios имеет поле outcome"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        for s in result["scenarios"]:
            assert "outcome" in s
            assert s["outcome"] in ("survived", "alarm", "failed")

    def test_depeg_boundary_in_output(self, fb_module, tmp_path):
        """depeg_failure_boundary присутствует в результате"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert "depeg_failure_boundary" in result

    def test_s5_in_failed(self, fb_module, tmp_path):
        """S5_CATASTROPHIC в списке failed"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert "S5_CATASTROPHIC" in result["failed"], (
            f"S5 должен быть в failed; failed={result['failed']}"
        )

    def test_note_no_apy_promise(self, fb_module, tmp_path):
        """note не содержит APY promises"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        note = result.get("note", "").lower()
        assert "guarantee" not in note
        assert "will earn" not in note

    def test_version_field(self, fb_module, tmp_path):
        """failure_boundary_version присутствует"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        assert "failure_boundary_version" in result
        assert result["failure_boundary_version"].startswith("failure_boundary_")

    def test_run_at_field_is_utc(self, fb_module, tmp_path):
        """run_at — ISO-строка с Z-суффиксом"""
        result = fb_module["run_full_failure_analysis"](output_dir=tmp_path)
        run_at = result.get("run_at", "")
        assert run_at.endswith("Z"), f"run_at должен оканчиваться на Z: {run_at!r}"


# =====================================================================
# 4. TestLLMForbidden
# =====================================================================

class TestLLMForbidden:
    def test_file_has_llm_forbidden_marker(self, project_root):
        """# LLM_FORBIDDEN присутствует в файле"""
        content = (
            project_root / "spa_core" / "bee" / "failure_boundary.py"
        ).read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_ai_imports_in_file(self, project_root):
        """Нет импортов AI-библиотек"""
        content = (
            project_root / "spa_core" / "bee" / "failure_boundary.py"
        ).read_text().lower()
        forbidden = ["openai", "anthropic", "claude", "gpt", "langchain", "huggingface"]
        for term in forbidden:
            assert term not in content, f"Запрещённый термин {term!r} найден в файле"

    def test_no_apy_guarantee_in_disclaimer(self, fb_module):
        """Дисклеймер не содержит гарантий APY"""
        for scenario in fb_module["SYNTHETIC_SCENARIOS"]:
            result = fb_module["evaluate_scenario"](scenario)
            disc = result.no_apy_disclaimer.lower()
            assert "guarantee" not in disc, (
                f"{scenario.scenario_id}: 'guarantee' в disclaimer"
            )
            assert "will earn" not in disc, (
                f"{scenario.scenario_id}: 'will earn' в disclaimer"
            )

    def test_stdlib_only(self, project_root):
        """Только stdlib-импорты в failure_boundary.py"""
        content = (
            project_root / "spa_core" / "bee" / "failure_boundary.py"
        ).read_text()
        # Проверяем наличие только stdlib импортов
        import_lines = [
            line.strip() for line in content.splitlines()
            if line.strip().startswith("import ") or line.strip().startswith("from ")
        ]
        stdlib_allowed = {
            "dataclasses", "typing", "pathlib", "json", "datetime", "copy", "sys",
            "tempfile",
        }
        for line in import_lines:
            parts = line.replace("from ", "").replace("import ", "").split()
            if parts:
                module = parts[0].split(".")[0]
                assert module in stdlib_allowed or module.startswith("spa_core"), (
                    f"Запрещённый внешний импорт: {line!r}"
                )

    def test_version_constant_exists(self, fb_module):
        """FAILURE_BOUNDARY_VERSION определён"""
        assert fb_module["FAILURE_BOUNDARY_VERSION"].startswith("failure_boundary_")
