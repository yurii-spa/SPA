"""
spa_core/tests/test_fork_harness.py — Unit tests for MP-401 E2E fork-harness.

Coverage:
 - AnvilProcess dry-run mode (no anvil / no rpc_url → ok=False, no exceptions)
 - ForkScenario.run_dry() — структура вывода, обязательные ключи
 - AaveWithdrawScenario: нет файлов → graceful; корректные данные → проверки
 - AllocationRebalanceScenario: пустые данные, корректные данные, нарушения лимитов
 - KillSwitchScenario: triggered=False → ok; triggered=True → warning
 - run_e2e_dry: атомарная запись, нет tmp хвостов, структура вывода
 - Нет сетевых вызовов в тестах
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from spa_core.testing.fork_harness import (
    AaveWithdrawScenario,
    AllocationRebalanceScenario,
    AnvilProcess,
    ForkConfig,
    ForkScenario,
    KillSwitchScenario,
    run_e2e_dry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _sample_orch(aave_tvl: float = 200_000_000, aave_status: str = "ok") -> Dict:
    return {
        "generated_at": "2026-06-11T06:00:05Z",
        "adapters": [
            {
                "protocol": "aave_v3",
                "tier": "T1",
                "apy_pct": 3.2,
                "tvl_usd": aave_tvl,
                "status": aave_status,
            },
            {
                "protocol": "compound_v3",
                "tier": "T1",
                "apy_pct": 3.1,
                "tvl_usd": 48_000_000,
                "status": "ok",
            },
        ],
    }


def _sample_positions(aave_usd: float = 31_000.0) -> Dict:
    return {
        "generated_at": "2026-06-11T06:00:04Z",
        "is_demo": False,
        "capital_usd": 100_000.0,
        "positions": {"aave_v3": aave_usd, "compound_v3": 30_000.0},
    }


def _sample_allocation(
    cash_pct: float = 0.20,
    t2_pct: float = 0.30,
    allocated_pct: float = 0.80,
    capital: float = 100_000.0,
) -> Dict:
    return {
        "capital_usd": capital,
        "allocated_pct": allocated_pct,
        "cash_pct": cash_pct,
        "t2_pct": t2_pct,
        "t1_pct": allocated_pct - t2_pct,
        "target_weights": {"aave_v3": 0.40, "compound_v3": 0.40},
        "target_usd": {"aave_v3": 40_000, "compound_v3": 40_000},
        "model_used": "risk_adjusted",
        "timestamp": "2026-06-11T06:00:00Z",
    }


def _sample_kill_switch(triggered: bool = False) -> Dict:
    return {
        "generated_at": "2026-06-11T06:00:12Z",
        "triggered": triggered,
        "reason": "all triggers clear" if not triggered else "drawdown ≥ 5%",
        "allocation": {},
    }


# ===========================================================================
# 1. ForkConfig
# ===========================================================================

class TestForkConfig:
    def test_empty_rpc_url_is_dry_run(self):
        cfg = ForkConfig(rpc_url="")
        assert cfg.is_dry_run is True

    def test_rpc_set_but_no_anvil_is_dry_run(self):
        cfg = ForkConfig(rpc_url="https://mainnet.infura.io/v3/test",
                         anvil_bin="nonexistent_anvil_xyz_42")
        assert cfg.is_dry_run is True

    def test_defaults(self):
        cfg = ForkConfig()
        assert cfg.chain_id == 1
        assert cfg.anvil_port == 8545
        assert cfg.anvil_bin == "anvil"
        assert cfg.fork_block_number is None
        assert cfg.startup_timeout_sec == 10.0


# ===========================================================================
# 2. AnvilProcess — dry-run mode
# ===========================================================================

class TestAnvilProcessDryRun:
    """AnvilProcess с пустым rpc_url или отсутствующим anvil — dry-run."""

    def test_start_no_rpc_returns_false(self):
        """start() без rpc_url возвращает False, не бросает исключение."""
        proc = AnvilProcess()
        cfg = ForkConfig(rpc_url="")
        result = proc.start(cfg)
        assert result is False

    def test_start_no_anvil_binary_returns_false(self):
        """start() с несуществующим anvil_bin возвращает False."""
        proc = AnvilProcess()
        cfg = ForkConfig(rpc_url="https://mainnet.example.com",
                         anvil_bin="nonexistent_anvil_xyz_42")
        result = proc.start(cfg)
        assert result is False

    def test_is_running_false_before_start(self):
        """is_running() возвращает False до любого старта."""
        proc = AnvilProcess()
        assert proc.is_running() is False

    def test_stop_noop_if_not_started(self):
        """stop() без предварительного start() не бросает исключений."""
        proc = AnvilProcess()
        proc.stop()  # должно быть тихим

    def test_start_dry_run_does_not_spawn_process(self):
        """В dry-run режиме subprocess.Popen НЕ вызывается."""
        proc = AnvilProcess()
        cfg = ForkConfig(rpc_url="")
        with patch("subprocess.Popen") as mock_popen:
            proc.start(cfg)
        mock_popen.assert_not_called()

    def test_is_running_false_after_dry_run_start(self):
        """После dry-run start() is_running() остаётся False."""
        proc = AnvilProcess()
        cfg = ForkConfig(rpc_url="")
        proc.start(cfg)
        assert proc.is_running() is False

    def test_context_manager_stop_no_exception(self):
        """AnvilProcess как context manager не бросает исключений в dry-run."""
        cfg = ForkConfig(rpc_url="")
        with AnvilProcess() as proc:
            proc.start(cfg)
        # Если дошли сюда — тест прошёл

    def test_stop_after_dry_run_start_no_exception(self):
        """stop() после dry-run start() тихий."""
        proc = AnvilProcess()
        cfg = ForkConfig(rpc_url="")
        proc.start(cfg)
        proc.stop()
        assert proc.is_running() is False


# ===========================================================================
# 3. ForkScenario — базовый класс
# ===========================================================================

class TestForkScenarioBase:
    def _make_tmpdir(self):
        td = tempfile.mkdtemp()
        return Path(td)

    def test_run_dry_returns_dict(self):
        scenario = ForkScenario()
        result = scenario.run_dry(self._make_tmpdir())
        assert isinstance(result, dict)

    def test_run_dry_has_ok_key(self):
        scenario = ForkScenario()
        result = scenario.run_dry(self._make_tmpdir())
        assert "ok" in result

    def test_run_dry_has_checks_key(self):
        scenario = ForkScenario()
        result = scenario.run_dry(self._make_tmpdir())
        assert "checks" in result
        assert isinstance(result["checks"], list)

    def test_run_dry_has_notes_key(self):
        scenario = ForkScenario()
        result = scenario.run_dry(self._make_tmpdir())
        assert "notes" in result
        assert isinstance(result["notes"], list)

    def test_run_dry_has_scenario_key(self):
        scenario = ForkScenario()
        result = scenario.run_dry(self._make_tmpdir())
        assert "scenario" in result

    def test_base_scenario_ok_is_true(self):
        """Базовый сценарий без переопределения возвращает ok=True."""
        scenario = ForkScenario()
        result = scenario.run_dry(self._make_tmpdir())
        assert result["ok"] is True

    def test_check_helper_passed_true(self):
        check = ForkScenario._check("test_check", True, "all good")
        assert check["passed"] is True
        assert check["name"] == "test_check"
        assert check["detail"] == "all good"

    def test_check_helper_passed_false(self):
        check = ForkScenario._check("test_check", False)
        assert check["passed"] is False
        assert check["detail"] == ""

    def test_load_json_missing_file(self, tmp_path):
        result = ForkScenario._load_json(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_json_valid_file(self, tmp_path):
        p = tmp_path / "test.json"
        _write_json(p, {"key": "value"})
        result = ForkScenario._load_json(p)
        assert result == {"key": "value"}

    def test_load_json_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {{")
        result = ForkScenario._load_json(p)
        assert result is None


# ===========================================================================
# 4. AaveWithdrawScenario
# ===========================================================================

class TestAaveWithdrawScenario:
    def test_no_files_returns_ok_false(self, tmp_path):
        """Без файлов — graceful fail, ok=False, нет исключений."""
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False
        assert result["scenario"] == "aave_withdraw"

    def test_no_files_has_failed_check(self, tmp_path):
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        failed = [c for c in result["checks"] if not c["passed"]]
        assert len(failed) >= 1

    def test_healthy_data_ok_true(self, tmp_path):
        """Полные корректные данные → ok=True."""
        _write_json(tmp_path / "adapter_orchestrator_status.json", _sample_orch())
        _write_json(tmp_path / "current_positions.json", _sample_positions())
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is True

    def test_aave_status_error_fails(self, tmp_path):
        """Aave адаптер со status=error → ok=False."""
        _write_json(tmp_path / "adapter_orchestrator_status.json",
                    _sample_orch(aave_status="error"))
        _write_json(tmp_path / "current_positions.json", _sample_positions())
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_tvl_below_floor_fails(self, tmp_path):
        """TVL < $5M → ok=False."""
        _write_json(tmp_path / "adapter_orchestrator_status.json",
                    _sample_orch(aave_tvl=1_000_000))
        _write_json(tmp_path / "current_positions.json", _sample_positions())
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False
        tvl_check = next(c for c in result["checks"] if c["name"] == "aave_tvl_above_floor")
        assert tvl_check["passed"] is False

    def test_zero_position_fails(self, tmp_path):
        """Позиция aave_v3 = 0 → ok=False."""
        _write_json(tmp_path / "adapter_orchestrator_status.json", _sample_orch())
        _write_json(tmp_path / "current_positions.json", _sample_positions(aave_usd=0))
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_no_aave_in_adapters_fails(self, tmp_path):
        """Нет aave_v3 в adapters → ok=False."""
        orch = {"adapters": [{"protocol": "compound_v3", "tvl_usd": 1e7, "status": "ok"}]}
        _write_json(tmp_path / "adapter_orchestrator_status.json", orch)
        _write_json(tmp_path / "current_positions.json", _sample_positions())
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_result_has_required_keys(self, tmp_path):
        sc = AaveWithdrawScenario()
        result = sc.run_dry(tmp_path)
        assert {"ok", "checks", "notes", "scenario"} <= set(result.keys())


# ===========================================================================
# 5. AllocationRebalanceScenario
# ===========================================================================

class TestAllocationRebalanceScenario:
    def test_no_file_ok_false(self, tmp_path):
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_healthy_allocation_ok_true(self, tmp_path):
        _write_json(tmp_path / "target_allocation.json", _sample_allocation())
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is True

    def test_cash_below_min_fails(self, tmp_path):
        """cash_pct < 5% → ok=False."""
        _write_json(tmp_path / "target_allocation.json",
                    _sample_allocation(cash_pct=0.02))
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False
        cash_check = next(c for c in result["checks"] if c["name"] == "cash_pct_above_min")
        assert cash_check["passed"] is False

    def test_t2_above_cap_fails(self, tmp_path):
        """t2_pct > 35% → ok=False."""
        _write_json(tmp_path / "target_allocation.json",
                    _sample_allocation(t2_pct=0.50))
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False
        t2_check = next(c for c in result["checks"] if c["name"] == "t2_pct_within_cap")
        assert t2_check["passed"] is False

    def test_zero_capital_fails(self, tmp_path):
        _write_json(tmp_path / "target_allocation.json",
                    _sample_allocation(capital=0))
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_allocated_above_95_fails(self, tmp_path):
        _write_json(tmp_path / "target_allocation.json",
                    _sample_allocation(allocated_pct=0.97, cash_pct=0.03))
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_empty_target_weights_fails(self, tmp_path):
        data = _sample_allocation()
        data["target_weights"] = {}
        data["target_usd"] = {}
        _write_json(tmp_path / "target_allocation.json", data)
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_result_scenario_name(self, tmp_path):
        sc = AllocationRebalanceScenario()
        result = sc.run_dry(tmp_path)
        assert result["scenario"] == "allocation_rebalance"


# ===========================================================================
# 6. KillSwitchScenario
# ===========================================================================

class TestKillSwitchScenario:
    def test_no_file_ok_false(self, tmp_path):
        sc = KillSwitchScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_not_triggered_ok_true(self, tmp_path):
        _write_json(tmp_path / "kill_switch_status.json",
                    _sample_kill_switch(triggered=False))
        sc = KillSwitchScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is True

    def test_triggered_ok_false(self, tmp_path):
        """Kill switch активирован → ok=False."""
        _write_json(tmp_path / "kill_switch_status.json",
                    _sample_kill_switch(triggered=True))
        sc = KillSwitchScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False

    def test_triggered_adds_warning_note(self, tmp_path):
        """Активный kill switch → WARNING в notes."""
        _write_json(tmp_path / "kill_switch_status.json",
                    _sample_kill_switch(triggered=True))
        sc = KillSwitchScenario()
        result = sc.run_dry(tmp_path)
        warning_notes = [n for n in result["notes"] if "WARNING" in n]
        assert len(warning_notes) >= 1

    def test_triggered_with_open_positions_fail(self, tmp_path):
        """Kill switch активен + позиции не закрыты → positions_cleared check fails."""
        _write_json(tmp_path / "kill_switch_status.json",
                    _sample_kill_switch(triggered=True))
        _write_json(tmp_path / "current_positions.json",
                    _sample_positions(aave_usd=5000.0))
        sc = KillSwitchScenario()
        result = sc.run_dry(tmp_path)
        assert result["ok"] is False
        pos_check = next(
            (c for c in result["checks"] if c["name"] == "positions_cleared_after_ks"),
            None,
        )
        assert pos_check is not None
        assert pos_check["passed"] is False

    def test_triggered_with_cleared_positions(self, tmp_path):
        """Kill switch активен + все позиции 0 → positions_cleared check passes."""
        _write_json(tmp_path / "kill_switch_status.json",
                    _sample_kill_switch(triggered=True))
        positions_cleared = {
            "capital_usd": 100_000,
            "positions": {"aave_v3": 0, "compound_v3": 0},
        }
        _write_json(tmp_path / "current_positions.json", positions_cleared)
        sc = KillSwitchScenario()
        result = sc.run_dry(tmp_path)
        # Kill switch triggered → ks_not_triggered check fails → ok=False
        # но positions_cleared check должен пройти
        pos_check = next(
            (c for c in result["checks"] if c["name"] == "positions_cleared_after_ks"),
            None,
        )
        assert pos_check is not None
        assert pos_check["passed"] is True

    def test_timestamp_check_passes(self, tmp_path):
        _write_json(tmp_path / "kill_switch_status.json",
                    _sample_kill_switch(triggered=False))
        sc = KillSwitchScenario()
        result = sc.run_dry(tmp_path)
        ts_check = next(c for c in result["checks"] if c["name"] == "kill_switch_has_timestamp")
        assert ts_check["passed"] is True

    def test_scenario_name(self, tmp_path):
        sc = KillSwitchScenario()
        assert sc.name == "kill_switch"


# ===========================================================================
# 7. run_e2e_dry
# ===========================================================================

class TestRunE2eDry:
    def _full_data_dir(self, tmp_path: Path) -> Path:
        """Создаёт tmp_path с корректными JSON-файлами для всех сценариев."""
        _write_json(tmp_path / "adapter_orchestrator_status.json", _sample_orch())
        _write_json(tmp_path / "current_positions.json", _sample_positions())
        _write_json(tmp_path / "target_allocation.json", _sample_allocation())
        _write_json(tmp_path / "kill_switch_status.json", _sample_kill_switch())
        return tmp_path

    def test_returns_dict(self, tmp_path):
        result = run_e2e_dry(tmp_path)
        assert isinstance(result, dict)

    def test_has_ok_key(self, tmp_path):
        result = run_e2e_dry(tmp_path)
        assert "ok" in result

    def test_has_mode_key(self, tmp_path):
        result = run_e2e_dry(tmp_path)
        assert result.get("mode") == "dry-run"

    def test_has_run_at_key(self, tmp_path):
        result = run_e2e_dry(tmp_path)
        assert "run_at" in result

    def test_has_scenarios_key(self, tmp_path):
        result = run_e2e_dry(tmp_path)
        assert "scenarios" in result
        assert isinstance(result["scenarios"], list)

    def test_has_summary_key(self, tmp_path):
        result = run_e2e_dry(tmp_path)
        assert "summary" in result
        assert "passed" in result["summary"]
        assert "total" in result["summary"]

    def test_all_scenarios_run(self, tmp_path):
        """По умолчанию запускаются 3 DEFAULT сценария."""
        result = run_e2e_dry(tmp_path)
        assert result["summary"]["total"] == 3

    def test_writes_status_json(self, tmp_path):
        """Создаёт data/fork_harness_status.json."""
        run_e2e_dry(tmp_path)
        assert (tmp_path / "fork_harness_status.json").exists()

    def test_no_tmp_file_left_after_write(self, tmp_path):
        """Атомарная запись: нет .tmp хвостов после успешного run."""
        run_e2e_dry(tmp_path)
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_status_json_content_valid(self, tmp_path):
        """Написанный JSON корректен и содержит все ключи."""
        run_e2e_dry(tmp_path)
        with open(tmp_path / "fork_harness_status.json") as f:
            data = json.load(f)
        assert "ok" in data
        assert "mode" in data
        assert "scenarios" in data
        assert "summary" in data

    def test_full_data_all_pass(self, tmp_path):
        """Все корректные данные → ok=True и все сценарии прошли."""
        self._full_data_dir(tmp_path)
        result = run_e2e_dry(tmp_path)
        assert result["ok"] is True
        assert result["summary"]["passed"] == result["summary"]["total"]

    def test_empty_data_dir_ok_false(self, tmp_path):
        """Без файлов — все сценарии fail → ok=False."""
        result = run_e2e_dry(tmp_path)
        assert result["ok"] is False
        assert result["summary"]["passed"] == 0

    def test_custom_scenarios_list(self, tmp_path):
        """custom scenarios list используется вместо DEFAULT."""
        custom = [KillSwitchScenario()]
        _write_json(tmp_path / "kill_switch_status.json",
                    _sample_kill_switch(triggered=False))
        result = run_e2e_dry(tmp_path, scenarios=custom)
        assert result["summary"]["total"] == 1
        assert result["ok"] is True

    def test_scenario_exception_does_not_crash(self, tmp_path):
        """Исключение внутри сценария не падает run_e2e_dry."""
        class BrokenScenario(ForkScenario):
            name = "broken"
            def run_dry(self, data_dir):
                raise RuntimeError("intentional test failure")

        result = run_e2e_dry(tmp_path, scenarios=[BrokenScenario()])
        assert result["ok"] is False  # exception → ok=False для этого сценария
        sc_result = result["scenarios"][0]
        assert "exception" in sc_result["notes"][0]

    def test_no_network_calls_during_run(self, tmp_path):
        """run_e2e_dry не делает сетевых вызовов (socket.connect не вызывается)."""
        import socket
        original_connect = socket.socket.connect

        def mock_connect(self, *args, **kwargs):
            raise AssertionError("Network call detected in dry-run mode!")

        # Патчим только на время теста
        with patch.object(socket.socket, "connect", mock_connect):
            try:
                run_e2e_dry(tmp_path)
            except AssertionError:
                pytest.fail("run_e2e_dry made a network call!")
