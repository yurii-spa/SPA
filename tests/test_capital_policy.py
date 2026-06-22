"""
Тесты EPIC-4 S4.1 — Capital Allocation Policy v2.0.

Покрытие:
  - GREEN mode: base targets 60/25/15, no blocks
  - CRITICAL mode: Defensive fail-closed, blocks B+C
  - RED mode: A↑, blocks B+C
  - YELLOW mode: A↑ (умеренно), C blocked
  - Rebalance detection: threshold 3%
  - allowed_engines matrix
  - validate_allocation_sum
  - LLM_FORBIDDEN guards
  - run_allocation_check end-to-end
"""
import pytest
from pathlib import Path


@pytest.fixture(scope="module")
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cap_module(project_root):
    import sys
    sys.path.insert(0, str(project_root))
    from spa_core.risk.capital_policy import (
        compute_allocation,
        validate_allocation_sum,
        get_allowed_engines,
        run_allocation_check,
        ENGINE_TARGETS,
        DEFENSIVE_ALLOCATION,
        CAPITAL_POLICY_VERSION,
    )
    return {
        "compute_allocation": compute_allocation,
        "validate_allocation_sum": validate_allocation_sum,
        "get_allowed_engines": get_allowed_engines,
        "run_allocation_check": run_allocation_check,
        "ENGINE_TARGETS": ENGINE_TARGETS,
        "DEFENSIVE_ALLOCATION": DEFENSIVE_ALLOCATION,
        "CAPITAL_POLICY_VERSION": CAPITAL_POLICY_VERSION,
    }


# ─── GREEN mode ──────────────────────────────────────────────────────────────

class TestGreenMode:
    def test_green_targets_60_25_15(self, cap_module):
        """GREEN: базовые targets 60/25/15"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        targets = result.target_allocations
        assert abs(targets.get("A", 0) - 0.60) < 0.02, f"A={targets.get('A')}"
        assert abs(targets.get("B", 0) - 0.25) < 0.02, f"B={targets.get('B')}"
        assert abs(targets.get("C", 0) - 0.15) < 0.02, f"C={targets.get('C')}"

    def test_green_no_blocking(self, cap_module):
        """GREEN: B и C не блокируются"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        assert result.block_new_engine_b is False
        assert result.block_new_engine_c is False

    def test_green_not_defensive(self, cap_module):
        """GREEN: не defensive mode"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        assert result.is_defensive_mode is False

    def test_green_targets_sum_to_one(self, cap_module):
        """GREEN: target аллокации суммируются в 1.0"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        targets = result.target_allocations
        # Фильтруем DEF (его в GREEN нет)
        engine_sum = sum(v for k, v in targets.items() if k != "DEF")
        assert abs(engine_sum - 1.0) < 0.005

    def test_green_policy_version(self, cap_module):
        """GREEN: policy_version присутствует"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        assert result.policy_version == cap_module["CAPITAL_POLICY_VERSION"]

    def test_green_computed_at_present(self, cap_module):
        """GREEN: computed_at заполнен"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        assert result.computed_at and result.computed_at.endswith("Z")


# ─── CRITICAL mode (fail-closed) ─────────────────────────────────────────────

class TestCriticalMode:
    def test_critical_is_defensive(self, cap_module):
        """CRITICAL → Defensive mode (fail-closed)"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "CRITICAL"
        )
        assert result.is_defensive_mode is True

    def test_critical_blocks_b_and_c(self, cap_module):
        """CRITICAL: B и C заблокированы"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "CRITICAL"
        )
        assert result.block_new_engine_b is True
        assert result.block_new_engine_c is True

    def test_critical_defensive_includes_def(self, cap_module):
        """CRITICAL: target_allocations содержит DEF"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "CRITICAL"
        )
        assert "DEF" in result.target_allocations
        assert result.target_allocations["DEF"] > 0

    def test_critical_def_pct(self, cap_module):
        """CRITICAL: DEF allocation = 45% (DEFENSIVE_ALLOCATION)"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "CRITICAL"
        )
        expected_def = cap_module["DEFENSIVE_ALLOCATION"]["DEF"]
        assert abs(result.target_allocations["DEF"] - expected_def) < 0.001

    def test_critical_needs_rebalance(self, cap_module):
        """CRITICAL: всегда needs_rebalance (переход в defensive)"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "CRITICAL"
        )
        assert result.needs_rebalance is True

    def test_critical_a_reduced(self, cap_module):
        """CRITICAL: Engine A target ниже GREEN target"""
        green = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        crit = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "CRITICAL"
        )
        assert crit.target_allocations.get("A", 0) < green.target_allocations.get("A", 1)


# ─── RED mode ─────────────────────────────────────────────────────────────────

class TestRedMode:
    def test_red_blocks_b_and_c(self, cap_module):
        """RED: B и C заблокированы"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "RED"
        )
        assert result.block_new_engine_b is True
        assert result.block_new_engine_c is True

    def test_red_not_defensive(self, cap_module):
        """RED: не defensive mode (в отличие от CRITICAL)"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "RED"
        )
        assert result.is_defensive_mode is False

    def test_red_increases_a(self, cap_module):
        """RED: Engine A target >= GREEN target"""
        green = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        red = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "RED"
        )
        assert red.target_allocations.get("A", 0) >= green.target_allocations.get("A", 0)

    def test_red_decreases_b(self, cap_module):
        """RED: Engine B target <= GREEN target"""
        green = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        red = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "RED"
        )
        assert red.target_allocations.get("B", 1) <= green.target_allocations.get("B", 0)

    def test_red_decreases_c(self, cap_module):
        """RED: Engine C target <= GREEN target"""
        green = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        red = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "RED"
        )
        assert red.target_allocations.get("C", 1) <= green.target_allocations.get("C", 0)

    def test_red_targets_sum_to_one(self, cap_module):
        """RED: engine targets суммируются в 1.0 (без DEF)"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "RED"
        )
        engine_sum = sum(v for k, v in result.target_allocations.items() if k != "DEF")
        assert abs(engine_sum - 1.0) < 0.005

    def test_red_a_within_bounds(self, cap_module):
        """RED: Engine A target не выходит за max_pct=70%"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "RED"
        )
        max_a = cap_module["ENGINE_TARGETS"]["A"].max_pct
        # Нормализованный target может чуть отличаться
        assert result.target_allocations.get("A", 0) <= max_a + 0.01


# ─── YELLOW mode ──────────────────────────────────────────────────────────────

class TestYellowMode:
    def test_yellow_not_defensive(self, cap_module):
        """YELLOW: не defensive mode"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "YELLOW"
        )
        assert result.is_defensive_mode is False

    def test_yellow_blocks_c_not_b(self, cap_module):
        """YELLOW: по схеме C заблокирован в get_allowed_engines, но block_new_engine_b=False"""
        # compute_allocation блокирует B и C только при RED/CRITICAL
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "YELLOW"
        )
        assert result.block_new_engine_b is False
        assert result.block_new_engine_c is False

    def test_yellow_a_above_green(self, cap_module):
        """YELLOW: A target >= GREEN A target"""
        green = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        yellow = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "YELLOW"
        )
        assert yellow.target_allocations.get("A", 0) >= green.target_allocations.get("A", 0)

    def test_yellow_targets_sum_to_one(self, cap_module):
        """YELLOW: engine targets суммируются в 1.0"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "YELLOW"
        )
        engine_sum = sum(v for k, v in result.target_allocations.items() if k != "DEF")
        assert abs(engine_sum - 1.0) < 0.005


# ─── Rebalancing ──────────────────────────────────────────────────────────────

class TestRebalancing:
    def test_no_rebalance_at_target(self, cap_module):
        """При текущих = целевым → нет ребалансировки"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        assert result.needs_rebalance is False

    def test_rebalance_needed_when_drifted_a(self, cap_module):
        """Drift A > 3% → needs_rebalance=True"""
        # A отклонился на 10% (50% вместо 60%)
        result = cap_module["compute_allocation"](
            {"A": 0.50, "B": 0.30, "C": 0.20}, "GREEN"
        )
        assert result.needs_rebalance is True

    def test_no_rebalance_within_threshold(self, cap_module):
        """Drift < 3% → no rebalance"""
        # A отклонился на 1% — ниже threshold
        result = cap_module["compute_allocation"](
            {"A": 0.61, "B": 0.24, "C": 0.15}, "GREEN"
        )
        assert result.needs_rebalance is False

    def test_rebalance_direction_a_below(self, cap_module):
        """A ниже target → rebalance_action["A"] > 0"""
        result = cap_module["compute_allocation"](
            {"A": 0.50, "B": 0.30, "C": 0.20}, "GREEN"
        )
        assert result.rebalance_actions.get("A", 0) > 0

    def test_rebalance_direction_a_above(self, cap_module):
        """A выше target → rebalance_action["A"] < 0"""
        result = cap_module["compute_allocation"](
            {"A": 0.70, "B": 0.20, "C": 0.10}, "GREEN"
        )
        # A=70%, target=60% → delta=-10%
        assert result.rebalance_actions.get("A", 0) < 0

    def test_rebalance_actions_present_for_all_engines(self, cap_module):
        """rebalance_actions содержит ключи для всех движков"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        for engine in ("A", "B", "C"):
            assert engine in result.rebalance_actions


# ─── allowed_engines matrix ───────────────────────────────────────────────────

class TestAllowedEngines:
    def test_green_all_allowed(self, cap_module):
        """GREEN: A, B, C разрешены; DEF — нет"""
        allowed = cap_module["get_allowed_engines"]("GREEN")
        assert allowed["A"] is True
        assert allowed["B"] is True
        assert allowed["C"] is True
        assert allowed.get("DEF", True) is False

    def test_yellow_c_blocked(self, cap_module):
        """YELLOW: C заблокирован"""
        allowed = cap_module["get_allowed_engines"]("YELLOW")
        assert allowed["A"] is True
        assert allowed["B"] is True
        assert allowed["C"] is False

    def test_red_only_a_allowed(self, cap_module):
        """RED: только A разрешён"""
        allowed = cap_module["get_allowed_engines"]("RED")
        assert allowed["A"] is True
        assert allowed["B"] is False
        assert allowed["C"] is False
        assert allowed.get("DEF", False) is True

    def test_critical_none_allowed(self, cap_module):
        """CRITICAL: A, B, C заблокированы; DEF разрешён (fail-closed)"""
        allowed = cap_module["get_allowed_engines"]("CRITICAL")
        assert allowed["A"] is False
        assert allowed["B"] is False
        assert allowed["C"] is False
        assert allowed["DEF"] is True

    def test_allowed_engines_returns_dict(self, cap_module):
        """get_allowed_engines возвращает dict с ожидаемыми ключами"""
        for risk in ("GREEN", "YELLOW", "RED", "CRITICAL"):
            result = cap_module["get_allowed_engines"](risk)
            assert isinstance(result, dict)
            assert "A" in result and "B" in result and "C" in result


# ─── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_valid_sum_exact(self, cap_module):
        """60+25+15=100% → valid"""
        assert cap_module["validate_allocation_sum"]({"A": 0.6, "B": 0.25, "C": 0.15}) is True

    def test_valid_sum_with_tolerance(self, cap_module):
        """Допускается отклонение до 0.001"""
        assert cap_module["validate_allocation_sum"]({"A": 0.6, "B": 0.25, "C": 0.1505}) is True

    def test_invalid_sum_over(self, cap_module):
        """Сумма >1 → False"""
        assert cap_module["validate_allocation_sum"]({"A": 0.6, "B": 0.25, "C": 0.20}) is False

    def test_invalid_sum_under(self, cap_module):
        """Сумма <1 → False"""
        assert cap_module["validate_allocation_sum"]({"A": 0.4, "B": 0.25, "C": 0.10}) is False

    def test_defensive_sum_valid(self, cap_module):
        """DEFENSIVE_ALLOCATION суммируется в 1.0"""
        assert cap_module["validate_allocation_sum"](cap_module["DEFENSIVE_ALLOCATION"]) is True

    def test_policy_version_constant(self, cap_module):
        """CAPITAL_POLICY_VERSION содержит 'capital_policy'"""
        assert "capital_policy" in cap_module["CAPITAL_POLICY_VERSION"]

    def test_policy_version_in_result(self, cap_module):
        """AllocationResult.policy_version совпадает с CAPITAL_POLICY_VERSION"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        assert result.policy_version == cap_module["CAPITAL_POLICY_VERSION"]

    def test_llm_forbidden_in_result(self, cap_module):
        """AllocationResult.LLM_FORBIDDEN=True"""
        result = cap_module["compute_allocation"](
            {"A": 0.60, "B": 0.25, "C": 0.15}, "GREEN"
        )
        assert result.LLM_FORBIDDEN is True


# ─── ENGINE_TARGETS constants ─────────────────────────────────────────────────

class TestEngineTargets:
    def test_engine_targets_a_60(self, cap_module):
        """ENGINE_TARGETS["A"].target_pct == 0.60"""
        assert cap_module["ENGINE_TARGETS"]["A"].target_pct == 0.60

    def test_engine_targets_b_25(self, cap_module):
        """ENGINE_TARGETS["B"].target_pct == 0.25"""
        assert cap_module["ENGINE_TARGETS"]["B"].target_pct == 0.25

    def test_engine_targets_c_15(self, cap_module):
        """ENGINE_TARGETS["C"].target_pct == 0.15"""
        assert cap_module["ENGINE_TARGETS"]["C"].target_pct == 0.15

    def test_rebalance_threshold_3pct(self, cap_module):
        """Порог ребалансировки для всех движков = 3%"""
        for engine, target in cap_module["ENGINE_TARGETS"].items():
            assert target.rebalance_threshold == 0.03, f"Engine {engine}: threshold={target.rebalance_threshold}"

    def test_targets_sum_to_one(self, cap_module):
        """Базовые targets суммируются в 1.0"""
        total = sum(t.target_pct for t in cap_module["ENGINE_TARGETS"].values())
        assert abs(total - 1.0) < 0.001


# ─── LLM_FORBIDDEN guards ─────────────────────────────────────────────────────

class TestLLMForbidden:
    def test_file_has_llm_forbidden_comment(self, project_root):
        """capital_policy.py содержит маркер LLM_FORBIDDEN"""
        content = (project_root / "spa_core" / "risk" / "capital_policy.py").read_text()
        assert "LLM_FORBIDDEN" in content

    def test_llm_forbidden_in_compute_fn(self, project_root):
        """compute_allocation содержит LLM_FORBIDDEN в теле функции"""
        content = (project_root / "spa_core" / "risk" / "capital_policy.py").read_text()
        # Проверяем что маркер есть внутри функции
        assert content.count("# LLM_FORBIDDEN") >= 3

    def test_no_openai_import(self, project_root):
        """Нет импортов openai"""
        content = (project_root / "spa_core" / "risk" / "capital_policy.py").read_text().lower()
        assert "openai" not in content

    def test_no_anthropic_import(self, project_root):
        """Нет импортов anthropic"""
        content = (project_root / "spa_core" / "risk" / "capital_policy.py").read_text().lower()
        assert "anthropic" not in content

    def test_no_langchain_import(self, project_root):
        """Нет импортов langchain"""
        content = (project_root / "spa_core" / "risk" / "capital_policy.py").read_text().lower()
        assert "langchain" not in content

    def test_stdlib_only(self, project_root):
        """Только stdlib: dataclasses, typing, pathlib, datetime, json"""
        content = (project_root / "spa_core" / "risk" / "capital_policy.py").read_text()
        for bad in ["import numpy", "import pandas", "import requests", "import aiohttp"]:
            assert bad not in content


# ─── run_allocation_check end-to-end ──────────────────────────────────────────

class TestRunAllocationCheck:
    def test_returns_dict(self, cap_module, tmp_path):
        """run_allocation_check возвращает dict"""
        result = cap_module["run_allocation_check"](output_path=tmp_path / "alloc.json")
        assert isinstance(result, dict)

    def test_output_has_version(self, cap_module, tmp_path):
        """Вывод содержит capital_policy_version"""
        result = cap_module["run_allocation_check"](output_path=tmp_path / "alloc.json")
        assert "capital_policy_version" in result

    def test_output_llm_forbidden(self, cap_module, tmp_path):
        """Вывод содержит LLM_FORBIDDEN=True"""
        result = cap_module["run_allocation_check"](output_path=tmp_path / "alloc.json")
        assert result["LLM_FORBIDDEN"] is True

    def test_output_file_created(self, cap_module, tmp_path):
        """JSON файл создаётся атомарно"""
        out = tmp_path / "alloc.json"
        cap_module["run_allocation_check"](output_path=out)
        assert out.exists()
        import json
        data = json.loads(out.read_text())
        assert "overall_risk" in data

    def test_output_has_allowed_engines(self, cap_module, tmp_path):
        """Вывод содержит allowed_engines"""
        result = cap_module["run_allocation_check"](output_path=tmp_path / "alloc.json")
        assert "allowed_engines" in result
        assert isinstance(result["allowed_engines"], dict)

    def test_output_has_target_allocations(self, cap_module, tmp_path):
        """Вывод содержит target_allocations"""
        result = cap_module["run_allocation_check"](output_path=tmp_path / "alloc.json")
        assert "target_allocations" in result

    def test_output_has_rebalance_actions(self, cap_module, tmp_path):
        """Вывод содержит rebalance_actions"""
        result = cap_module["run_allocation_check"](output_path=tmp_path / "alloc.json")
        assert "rebalance_actions" in result
