"""
Тесты Risk Aggregator EPIC-3 S3.1
- fail-closed: CRITICAL engine → overall=CRITICAL → block
- GREEN when all engines healthy
- Weighted drawdown correct
- LLM_FORBIDDEN
"""
# LLM_FORBIDDEN
import pytest
from pathlib import Path


@pytest.fixture(scope="module")
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def agg_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from spa_core.risk.aggregator import (
        aggregate_risk,
        snapshot_engine,
        run_risk_check,
        load_live_drawdowns,
        EngineRiskLevel,
        OverallRiskLevel,
        ENGINE_KILL_THRESHOLDS,
        ENGINE_WEIGHTS,
        AGGREGATOR_VERSION,
    )
    return {
        "aggregate_risk": aggregate_risk,
        "snapshot_engine": snapshot_engine,
        "run_risk_check": run_risk_check,
        "load_live_drawdowns": load_live_drawdowns,
        "EngineRiskLevel": EngineRiskLevel,
        "OverallRiskLevel": OverallRiskLevel,
        "ENGINE_KILL_THRESHOLDS": ENGINE_KILL_THRESHOLDS,
        "ENGINE_WEIGHTS": ENGINE_WEIGHTS,
        "AGGREGATOR_VERSION": AGGREGATOR_VERSION,
    }


# ─────────────────────────────────────────────
# GREEN scenario
# ─────────────────────────────────────────────

class TestGreenScenario:
    def test_all_green_when_zero_drawdown(self, agg_module):
        """Все движки с 0 drawdown → GREEN, block=False"""
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": 0.0, "C": 0.0})
        assert result.overall_risk == agg_module["OverallRiskLevel"].GREEN
        assert result.block_new_positions is False
        assert result.any_critical is False
        assert result.any_red is False

    def test_small_drawdown_stays_green(self, agg_module):
        """Drawdown < 50% kill threshold → GREEN"""
        # A: -0.01 / 0.05 = 20% ratio → GREEN
        # B: -0.02 / 0.08 = 25% ratio → GREEN
        # C: -0.02 / 0.12 = 16% ratio → GREEN
        result = agg_module["aggregate_risk"]({"A": -0.01, "B": -0.02, "C": -0.02})
        assert result.overall_risk == agg_module["OverallRiskLevel"].GREEN
        assert result.any_critical is False
        assert result.any_red is False

    def test_positive_drawdown_treated_as_zero(self, agg_module):
        """Положительный P&L не вызывает риск"""
        result = agg_module["aggregate_risk"]({"A": 0.01, "B": 0.02, "C": 0.05})
        assert result.overall_risk == agg_module["OverallRiskLevel"].GREEN
        assert result.block_new_positions is False


# ─────────────────────────────────────────────
# CRITICAL scenario (fail-closed)
# ─────────────────────────────────────────────

class TestCriticalFailClosed:
    def test_engine_a_critical_blocks_all(self, agg_module):
        """Engine A пересекает kill 5% → CRITICAL → block"""
        result = agg_module["aggregate_risk"]({"A": -0.06, "B": 0.0, "C": 0.0})
        assert result.any_critical is True
        assert result.block_new_positions is True
        assert result.overall_risk == agg_module["OverallRiskLevel"].CRITICAL

    def test_engine_b_critical_blocks_all(self, agg_module):
        """Engine B пересекает kill 8% → CRITICAL → block"""
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": -0.09, "C": 0.0})
        assert result.any_critical is True
        assert result.block_new_positions is True
        assert result.overall_risk == agg_module["OverallRiskLevel"].CRITICAL

    def test_engine_c_critical_blocks_all(self, agg_module):
        """Engine C пересекает kill 12% → CRITICAL → block"""
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": 0.0, "C": -0.13})
        assert result.any_critical is True
        assert result.block_new_positions is True
        assert result.overall_risk == agg_module["OverallRiskLevel"].CRITICAL

    def test_exactly_at_kill_threshold_is_critical(self, agg_module):
        """Ровно на kill threshold → CRITICAL (fail-closed, ratio=1.0)"""
        result = agg_module["aggregate_risk"]({"A": -0.05, "B": 0.0, "C": 0.0})
        assert result.any_critical is True
        assert result.block_new_positions is True

    def test_one_critical_overrides_green_engines(self, agg_module):
        """1 CRITICAL + 2 GREEN → overall=CRITICAL (fail-closed)"""
        result = agg_module["aggregate_risk"]({"A": -0.06, "B": 0.0, "C": 0.0})
        assert result.overall_risk == agg_module["OverallRiskLevel"].CRITICAL
        # Engine B и C должны остаться GREEN
        assert result.engines["B"].risk_level == agg_module["EngineRiskLevel"].GREEN
        assert result.engines["C"].risk_level == agg_module["EngineRiskLevel"].GREEN


# ─────────────────────────────────────────────
# YELLOW / RED transitions
# ─────────────────────────────────────────────

class TestYellowRedTransitions:
    def test_yellow_at_50pct_kill(self, agg_module):
        """50–74% kill threshold → YELLOW"""
        # A: -0.026 / 0.05 = 52% → YELLOW
        result = agg_module["aggregate_risk"]({"A": -0.026, "B": 0.0, "C": 0.0})
        assert result.overall_risk in [
            agg_module["OverallRiskLevel"].YELLOW,
            agg_module["OverallRiskLevel"].RED,
        ]
        assert result.any_critical is False

    def test_red_at_75pct_kill(self, agg_module):
        """75–99% kill threshold → RED"""
        # A: -0.04 / 0.05 = 80% → RED
        result = agg_module["aggregate_risk"]({"A": -0.04, "B": 0.0, "C": 0.0})
        assert result.overall_risk in [
            agg_module["OverallRiskLevel"].RED,
            agg_module["OverallRiskLevel"].CRITICAL,
        ]
        assert result.any_critical is False

    def test_red_does_not_block_positions(self, agg_module):
        """RED → block_new_positions=False (только CRITICAL блокирует)"""
        result = agg_module["aggregate_risk"]({"A": -0.04, "B": 0.0, "C": 0.0})
        assert result.block_new_positions is False

    def test_engine_b_yellow(self, agg_module):
        """Engine B: -0.045 / 0.08 = 56% → YELLOW"""
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": -0.045, "C": 0.0})
        assert result.engines["B"].risk_level == agg_module["EngineRiskLevel"].YELLOW

    def test_engine_c_red(self, agg_module):
        """Engine C: -0.10 / 0.12 = 83% → RED"""
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": 0.0, "C": -0.10})
        assert result.engines["C"].risk_level == agg_module["EngineRiskLevel"].RED


# ─────────────────────────────────────────────
# Aggregation metrics
# ─────────────────────────────────────────────

class TestAggregationMetrics:
    def test_weighted_drawdown_correct(self, agg_module):
        """total_drawdown_pct = Σ(weight_i * dd_i)"""
        weights = agg_module["ENGINE_WEIGHTS"]
        dds = {"A": -0.02, "B": -0.04, "C": -0.06}
        result = agg_module["aggregate_risk"](dds)
        expected = sum(weights.get(e, 0.0) * dd for e, dd in dds.items())
        assert abs(result.total_drawdown_pct - expected) < 1e-9

    def test_weighted_drawdown_zero_when_healthy(self, agg_module):
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": 0.0, "C": 0.0})
        assert result.total_drawdown_pct == pytest.approx(0.0, abs=1e-9)

    def test_max_single_engine_dd(self, agg_module):
        """max_single_engine_dd = наихудший (минимальный) drawdown"""
        result = agg_module["aggregate_risk"]({"A": -0.01, "B": -0.05, "C": -0.02})
        assert result.max_single_engine_dd == pytest.approx(-0.05, abs=1e-9)

    def test_max_single_engine_dd_engine_c(self, agg_module):
        result = agg_module["aggregate_risk"]({"A": -0.01, "B": -0.02, "C": -0.11})
        assert result.max_single_engine_dd == pytest.approx(-0.11, abs=1e-9)

    def test_correlation_low_when_all_green(self, agg_module):
        """Все GREEN → correlation=low"""
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": 0.0, "C": 0.0})
        assert result.cross_engine_correlation == "low"

    def test_correlation_high_when_multiple_red(self, agg_module):
        """2+ RED/CRITICAL → correlation=high"""
        # A: -0.04 (80% kill=RED), B: -0.07 (87.5% kill=RED), C: 0
        result = agg_module["aggregate_risk"]({"A": -0.04, "B": -0.07, "C": 0.0})
        assert result.cross_engine_correlation == "high"

    def test_correlation_medium_single_red(self, agg_module):
        """1 RED, остальные GREEN → correlation=medium"""
        result = agg_module["aggregate_risk"]({"A": -0.04, "B": 0.0, "C": 0.0})
        assert result.cross_engine_correlation == "medium"

    def test_llm_forbidden_flag_in_result(self, agg_module):
        """LLM_FORBIDDEN=True в AggregatedRisk"""
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": 0.0, "C": 0.0})
        assert result.LLM_FORBIDDEN is True

    def test_aggregated_at_is_iso_timestamp(self, agg_module):
        result = agg_module["aggregate_risk"]({"A": 0.0, "B": 0.0, "C": 0.0})
        assert "T" in result.aggregated_at
        assert result.aggregated_at.endswith("Z")


# ─────────────────────────────────────────────
# snapshot_engine
# ─────────────────────────────────────────────

class TestSnapshotEngine:
    def test_snapshot_green_zero_dd(self, agg_module):
        snap = agg_module["snapshot_engine"]("A", 0.0)
        assert snap.risk_level == agg_module["EngineRiskLevel"].GREEN
        assert snap.drawdown_to_kill_pct == pytest.approx(0.0, abs=1e-9)

    def test_snapshot_green_small_dd(self, agg_module):
        snap = agg_module["snapshot_engine"]("A", -0.01)
        assert snap.risk_level == agg_module["EngineRiskLevel"].GREEN

    def test_snapshot_critical_engine_a(self, agg_module):
        snap = agg_module["snapshot_engine"]("A", -0.06)
        assert snap.risk_level == agg_module["EngineRiskLevel"].CRITICAL

    def test_snapshot_critical_engine_b(self, agg_module):
        snap = agg_module["snapshot_engine"]("B", -0.09)
        assert snap.risk_level == agg_module["EngineRiskLevel"].CRITICAL

    def test_snapshot_critical_engine_c(self, agg_module):
        snap = agg_module["snapshot_engine"]("C", -0.13)
        assert snap.risk_level == agg_module["EngineRiskLevel"].CRITICAL

    def test_all_engines_have_positive_thresholds(self, agg_module):
        """У всех движков валидные kill thresholds"""
        for engine in ["A", "B", "C"]:
            snap = agg_module["snapshot_engine"](engine, 0.0)
            assert snap.kill_threshold_pct > 0

    def test_snapshot_drawdown_to_kill_ratio(self, agg_module):
        """drawdown_to_kill_pct = abs(dd) / kill"""
        snap = agg_module["snapshot_engine"]("A", -0.025)  # 0.025/0.05 = 0.5
        assert snap.drawdown_to_kill_pct == pytest.approx(0.5, abs=1e-9)

    def test_snapshot_engine_names(self, agg_module):
        """Все движки имеют нормальные имена"""
        for engine in ["A", "B", "C"]:
            snap = agg_module["snapshot_engine"](engine, 0.0)
            assert len(snap.engine_name) > 0

    def test_snapshot_details_default_empty_dict(self, agg_module):
        snap = agg_module["snapshot_engine"]("A", 0.0)
        assert snap.details == {}

    def test_snapshot_details_passed_through(self, agg_module):
        snap = agg_module["snapshot_engine"]("A", -0.01, details={"source": "test"})
        assert snap.details == {"source": "test"}


# ─────────────────────────────────────────────
# run_risk_check (end-to-end)
# ─────────────────────────────────────────────

class TestRunRiskCheck:
    def test_returns_dict_with_required_keys(self, agg_module, tmp_path):
        result = agg_module["run_risk_check"](output_path=tmp_path / "risk.json")
        for key in [
            "aggregator_version", "overall_risk", "block_new_positions",
            "any_critical", "any_red", "total_drawdown_pct",
            "max_single_engine_dd", "cross_engine_correlation",
            "engines", "policy_versions", "LLM_FORBIDDEN",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_output_file_created(self, agg_module, tmp_path):
        agg_module["run_risk_check"](output_path=tmp_path / "risk.json")
        assert (tmp_path / "risk.json").exists()

    def test_output_file_valid_json(self, agg_module, tmp_path):
        import json
        out_path = tmp_path / "risk.json"
        agg_module["run_risk_check"](output_path=out_path)
        data = json.loads(out_path.read_text())
        assert "overall_risk" in data

    def test_llm_forbidden_in_output(self, agg_module, tmp_path):
        result = agg_module["run_risk_check"](output_path=tmp_path / "risk.json")
        assert result["LLM_FORBIDDEN"] is True

    def test_aggregator_version_in_output(self, agg_module, tmp_path):
        result = agg_module["run_risk_check"](output_path=tmp_path / "risk.json")
        assert result["aggregator_version"] == agg_module["AGGREGATOR_VERSION"]

    def test_engines_dict_has_all_three(self, agg_module, tmp_path):
        result = agg_module["run_risk_check"](output_path=tmp_path / "risk.json")
        for engine in ["A", "B", "C"]:
            assert engine in result["engines"]


# ─────────────────────────────────────────────
# load_live_drawdowns
# ─────────────────────────────────────────────

class TestLoadLiveDrawdowns:
    def test_returns_dict_with_abc_keys(self, agg_module):
        dds = agg_module["load_live_drawdowns"]()
        assert "A" in dds
        assert "B" in dds
        assert "C" in dds

    def test_drawdowns_are_floats(self, agg_module):
        dds = agg_module["load_live_drawdowns"]()
        for engine, dd in dds.items():
            assert isinstance(dd, float), f"Engine {engine} drawdown must be float"

    def test_drawdowns_non_positive(self, agg_module):
        """Drawdown всегда ≤ 0 (за исключением float precision issues)"""
        dds = agg_module["load_live_drawdowns"]()
        for engine, dd in dds.items():
            assert dd <= 1e-9, f"Engine {engine} drawdown {dd} must be ≤ 0"


# ─────────────────────────────────────────────
# Engine constants validation
# ─────────────────────────────────────────────

class TestEngineConstants:
    def test_kill_thresholds_defined_for_all_engines(self, agg_module):
        for engine in ["A", "B", "C"]:
            assert engine in agg_module["ENGINE_KILL_THRESHOLDS"]
            assert agg_module["ENGINE_KILL_THRESHOLDS"][engine] > 0

    def test_engine_weights_sum_to_one(self, agg_module):
        """Веса должны суммироваться в 1.0"""
        total = sum(agg_module["ENGINE_WEIGHTS"].values())
        assert abs(total - 1.0) < 1e-9, f"Weights sum {total} ≠ 1.0"

    def test_engine_weights_defined_for_all_engines(self, agg_module):
        for engine in ["A", "B", "C"]:
            assert engine in agg_module["ENGINE_WEIGHTS"]
            assert agg_module["ENGINE_WEIGHTS"][engine] > 0

    def test_kill_thresholds_order(self, agg_module):
        """Engine C (LP) имеет самый высокий kill threshold (наибольшая волатильность)"""
        kts = agg_module["ENGINE_KILL_THRESHOLDS"]
        assert kts["C"] > kts["B"] > kts["A"]

    def test_aggregator_version_format(self, agg_module):
        assert "v1.0" in agg_module["AGGREGATOR_VERSION"]


# ─────────────────────────────────────────────
# LLM_FORBIDDEN compliance
# ─────────────────────────────────────────────

class TestLLMForbiddenCompliance:
    def test_llm_forbidden_comment_in_source(self, project_root):
        """# LLM_FORBIDDEN присутствует в aggregator.py"""
        content = (project_root / "spa_core" / "risk" / "aggregator.py").read_text()
        assert "# LLM_FORBIDDEN" in content

    def test_llm_forbidden_docstring_in_source(self, project_root):
        """LLM_FORBIDDEN упоминается в docstring"""
        content = (project_root / "spa_core" / "risk" / "aggregator.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_no_ai_imports_in_aggregator(self, project_root):
        """Нет импортов AI/LLM библиотек"""
        content = (
            project_root / "spa_core" / "risk" / "aggregator.py"
        ).read_text().lower()
        for term in ["openai", "anthropic", "gpt", "langchain", "llama", "mistral"]:
            assert term not in content, f"Found forbidden AI import: {term}"

    def test_only_stdlib_imports(self, project_root):
        """Только stdlib импорты (dataclasses, typing, enum, pathlib, json, datetime)"""
        content = (project_root / "spa_core" / "risk" / "aggregator.py").read_text()
        lines = [
            line.strip() for line in content.splitlines()
            if line.strip().startswith("import ") or line.strip().startswith("from ")
        ]
        allowed_modules = {
            "dataclasses", "typing", "enum", "pathlib",
            "datetime", "json", "tempfile", "os", "sys",
        }
        for line in lines:
            # Берём первый токен модуля
            if line.startswith("from "):
                mod = line.split()[1].split(".")[0]
            else:
                mod = line.split()[1].split(".")[0]
            assert mod in allowed_modules or mod.startswith("spa_core") or mod == "__future__", (
                f"Non-stdlib import found: {line}"
            )
