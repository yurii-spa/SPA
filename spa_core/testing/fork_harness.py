"""
spa_core/testing/fork_harness.py — E2E fork-harness (MP-401)

Два режима:
  dry-run  — всегда доступен; только читает JSON-файлы из data/,
             никаких сетевых вызовов и subprocess.
  live     — требует установленного anvil (Foundry) и RPC-URL (MP-017);
             запускает локальный EVM-форк mainnet.

CLI:
    python3 -m spa_core.testing.fork_harness --dry-run   # всегда работает
    python3 -m spa_core.testing.fork_harness --live      # требует anvil + RPC
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ForkConfig
# ---------------------------------------------------------------------------

@dataclass
class ForkConfig:
    """Конфигурация локального EVM-форка через Anvil."""

    rpc_url: str = ""
    """Mainnet RPC URL (например Alchemy/Infura). Пустая строка → dry-run."""

    fork_block_number: Optional[int] = None
    """Конкретный блок для форка. None → latest."""

    chain_id: int = 1
    """Chain ID форка (1 = Ethereum mainnet)."""

    anvil_port: int = 8545
    """Локальный порт, на котором слушает anvil."""

    anvil_bin: str = "anvil"
    """Путь / имя бинарного файла anvil."""

    startup_timeout_sec: float = 10.0
    """Таймаут ожидания старта процесса anvil."""

    @property
    def is_dry_run(self) -> bool:
        """True если rpc_url не задан или anvil недоступен."""
        return not self.rpc_url or not shutil.which(self.anvil_bin)


# ---------------------------------------------------------------------------
# AnvilProcess
# ---------------------------------------------------------------------------

class AnvilProcess:
    """Менеджер процесса anvil — запуск/остановка локального EVM-форка."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._config: Optional[ForkConfig] = None

    # ------------------------------------------------------------------
    def start(self, config: ForkConfig) -> bool:
        """Запускает anvil с форком mainnet.

        Returns:
            True  — процесс запущен успешно.
            False — dry-run (нет anvil или rpc_url) или ошибка запуска.
        """
        self._config = config

        if config.is_dry_run:
            reason = "rpc_url not set" if not config.rpc_url else "anvil binary not found"
            logger.warning("AnvilProcess.start: dry-run mode — %s", reason)
            return False

        cmd: List[str] = [
            config.anvil_bin,
            "--fork-url", config.rpc_url,
            "--port", str(config.anvil_port),
            "--chain-id", str(config.chain_id),
        ]
        if config.fork_block_number is not None:
            cmd += ["--fork-block-number", str(config.fork_block_number)]

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.warning("AnvilProcess.start: anvil binary not found at '%s'", config.anvil_bin)
            return False
        except OSError as exc:
            logger.warning("AnvilProcess.start: failed to start anvil — %s", exc)
            return False

        # Ждём, пока anvil начнёт принимать соединения
        deadline = time.monotonic() + config.startup_timeout_sec
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                # Процесс уже завершился
                logger.warning("AnvilProcess.start: anvil exited prematurely (code %s)", self._proc.returncode)
                return False
            # Простая проверка через /etc/hosts-style ping — не нужна;
            # достаточно что процесс жив через 1 секунду.
            time.sleep(0.5)
            if self._proc.poll() is None:
                logger.info("AnvilProcess.start: anvil running on port %d", config.anvil_port)
                return True

        logger.warning("AnvilProcess.start: timeout waiting for anvil to start")
        self.stop()
        return False

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Посылает SIGTERM и ждёт завершения процесса."""
        if self._proc is None:
            return
        try:
            self._proc.send_signal(signal.SIGTERM)
            self._proc.wait(timeout=5)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None

    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        """True если процесс anvil активен."""
        return self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------------
    def __enter__(self) -> "AnvilProcess":
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# ForkScenario — базовый класс
# ---------------------------------------------------------------------------

class ForkScenario:
    """Базовый класс E2E сценария.

    Subclasses должны переопределить `run_dry` и, опционально, `run_live`.
    """

    name: str = "base_scenario"
    description: str = "Base fork scenario"
    required_contracts: List[str] = []

    # ------------------------------------------------------------------
    def run_dry(self, data_dir: Path) -> Dict[str, Any]:
        """Offline проверка по JSON-файлам в data_dir.

        Returns dict с ключами:
            ok      — bool: True если сценарий прошёл без критических проблем
            checks  — list[dict]: каждая проверка {name, passed, detail}
            notes   — list[str]: информационные заметки
            scenario — str: имя сценария
        """
        return {
            "ok": True,
            "checks": [],
            "notes": ["base scenario — no checks defined"],
            "scenario": self.name,
        }

    # ------------------------------------------------------------------
    def run_live(self, data_dir: Path, rpc_url: str, port: int = 8545) -> Dict[str, Any]:
        """Live проверка против форка mainnet (anvil).

        По умолчанию делегирует в run_dry.
        Конкретные сценарии переопределяют после MP-017.
        """
        logger.info("run_live not implemented for '%s'; falling back to dry-run", self.name)
        return self.run_dry(data_dir)

    # ------------------------------------------------------------------
    @staticmethod
    def _check(name: str, passed: bool, detail: str = "") -> Dict[str, Any]:
        return {"name": name, "passed": passed, "detail": detail}

    # ------------------------------------------------------------------
    @staticmethod
    def _load_json(path: Path) -> Optional[Dict[str, Any]]:
        """Загружает JSON-файл или возвращает None если файл недоступен."""
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None


# ---------------------------------------------------------------------------
# AaveWithdrawScenario
# ---------------------------------------------------------------------------

class AaveWithdrawScenario(ForkScenario):
    """Проверяет готовность Aave V3 позиции к выводу средств.

    Dry-run:
    - Aave есть в adapter_orchestrator_status.json со статусом ok
    - TVL ≥ $5M (политика RiskPolicy)
    - Позиция в current_positions.json > 0
    """

    name = "aave_withdraw"
    description = "Verify Aave V3 position is liquid and ready for withdrawal"
    required_contracts = ["AaveV3Pool", "AaveV3DataProvider"]

    TVL_FLOOR_USD = 5_000_000.0

    def run_dry(self, data_dir: Path) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        notes: List[str] = []

        # --- 1. adapter_orchestrator_status.json ---
        orch_path = data_dir / "adapter_orchestrator_status.json"
        orch_data = self._load_json(orch_path)

        if orch_data is None:
            checks.append(self._check("orch_status_readable", False,
                                       f"file not found or invalid: {orch_path}"))
            return {"ok": False, "checks": checks, "notes": notes, "scenario": self.name}

        checks.append(self._check("orch_status_readable", True))

        # Найти Aave V3 в списке адаптеров
        adapters = orch_data.get("adapters", [])
        aave_entry = next(
            (a for a in adapters if a.get("protocol") == "aave_v3"),
            None,
        )

        if aave_entry is None:
            checks.append(self._check("aave_adapter_present", False,
                                       "aave_v3 not found in adapters list"))
            return {"ok": False, "checks": checks, "notes": notes, "scenario": self.name}

        checks.append(self._check("aave_adapter_present", True))

        # Status ok
        adapter_status = aave_entry.get("status", "unknown")
        status_ok = adapter_status == "ok"
        checks.append(self._check("aave_adapter_status_ok", status_ok,
                                   f"status={adapter_status}"))

        # TVL floor
        tvl = float(aave_entry.get("tvl_usd", 0))
        tvl_ok = tvl >= self.TVL_FLOOR_USD
        checks.append(self._check("aave_tvl_above_floor", tvl_ok,
                                   f"tvl=${tvl:,.0f} vs floor=${self.TVL_FLOOR_USD:,.0f}"))

        # --- 2. current_positions.json ---
        pos_path = data_dir / "current_positions.json"
        pos_data = self._load_json(pos_path)

        if pos_data is None:
            checks.append(self._check("positions_readable", False,
                                       f"file not found or invalid: {pos_path}"))
            return {"ok": False, "checks": checks, "notes": notes, "scenario": self.name}

        checks.append(self._check("positions_readable", True))

        positions = pos_data.get("positions", {})
        aave_pos = float(positions.get("aave_v3", 0))
        pos_positive = aave_pos > 0
        checks.append(self._check("aave_position_positive", pos_positive,
                                   f"aave_v3 position=${aave_pos:,.2f}"))

        if pos_positive:
            notes.append(f"Aave V3 position: ${aave_pos:,.2f} USD")

        # Exit latency note (dry-run: нет on-chain вызовов, предполагаем 0h)
        notes.append("exit_latency=0h (assumed; verify on-chain after MP-017)")

        ok = all(c["passed"] for c in checks)
        return {"ok": ok, "checks": checks, "notes": notes, "scenario": self.name}


# ---------------------------------------------------------------------------
# AllocationRebalanceScenario
# ---------------------------------------------------------------------------

class AllocationRebalanceScenario(ForkScenario):
    """Проверяет согласованность target_allocation.json с лимитами политики.

    Dry-run:
    - target_allocation.json читается без ошибок
    - cash_pct ≥ 5% (min buffer)
    - t2_pct ≤ 35%
    - allocated_pct ≤ 95% (оставляем буфер)
    - capital_usd > 0
    """

    name = "allocation_rebalance"
    description = "Verify target allocation is consistent with RiskPolicy limits"
    required_contracts = []  # dry-run не требует контрактов

    CASH_MIN_PCT = 0.05
    T2_CAP_PCT = 0.35
    ALLOC_MAX_PCT = 0.95

    def run_dry(self, data_dir: Path) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        notes: List[str] = []

        # --- target_allocation.json ---
        alloc_path = data_dir / "target_allocation.json"
        alloc_data = self._load_json(alloc_path)

        if alloc_data is None:
            checks.append(self._check("target_allocation_readable", False,
                                       f"file not found or invalid: {alloc_path}"))
            return {"ok": False, "checks": checks, "notes": notes, "scenario": self.name}

        checks.append(self._check("target_allocation_readable", True))

        # capital_usd > 0
        capital = float(alloc_data.get("capital_usd", 0))
        cap_ok = capital > 0
        checks.append(self._check("capital_positive", cap_ok, f"capital_usd={capital}"))

        # cash_pct ≥ 5%
        cash_pct = float(alloc_data.get("cash_pct", 0))
        cash_ok = cash_pct >= self.CASH_MIN_PCT
        checks.append(self._check("cash_pct_above_min", cash_ok,
                                   f"cash_pct={cash_pct:.2%} vs min={self.CASH_MIN_PCT:.0%}"))

        # t2_pct ≤ 35%
        t2_pct = float(alloc_data.get("t2_pct", 0))
        t2_ok = t2_pct <= self.T2_CAP_PCT
        checks.append(self._check("t2_pct_within_cap", t2_ok,
                                   f"t2_pct={t2_pct:.2%} vs cap={self.T2_CAP_PCT:.0%}"))

        # allocated_pct ≤ 95%
        alloc_pct = float(alloc_data.get("allocated_pct", 0))
        alloc_ok = alloc_pct <= self.ALLOC_MAX_PCT
        checks.append(self._check("allocated_pct_within_limit", alloc_ok,
                                   f"allocated_pct={alloc_pct:.2%} vs max={self.ALLOC_MAX_PCT:.0%}"))

        if cap_ok:
            notes.append(f"Capital: ${capital:,.0f} USD, allocated {alloc_pct:.1%}")

        # Проверяем target_weights присутствует
        weights = alloc_data.get("target_weights") or alloc_data.get("target_usd")
        weights_present = isinstance(weights, dict) and len(weights) > 0
        checks.append(self._check("target_weights_present", weights_present,
                                   f"keys: {list(weights.keys()) if isinstance(weights, dict) else 'missing'}"))

        ok = all(c["passed"] for c in checks)
        return {"ok": ok, "checks": checks, "notes": notes, "scenario": self.name}


# ---------------------------------------------------------------------------
# KillSwitchScenario
# ---------------------------------------------------------------------------

class KillSwitchScenario(ForkScenario):
    """Проверяет состояние kill switch и ликвидность позиций.

    Dry-run:
    - kill_switch_status.json читается
    - triggered=False → ok=True (штатный режим)
    - triggered=True  → warning, ok=False (портфель должен быть закрыт)
    - Если triggered, позиции должны быть пустые (все выведено)
    """

    name = "kill_switch"
    description = "Verify kill switch status and portfolio liquidity"
    required_contracts = []

    def run_dry(self, data_dir: Path) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        notes: List[str] = []

        # --- kill_switch_status.json ---
        ks_path = data_dir / "kill_switch_status.json"
        ks_data = self._load_json(ks_path)

        if ks_data is None:
            checks.append(self._check("kill_switch_readable", False,
                                       f"file not found or invalid: {ks_path}"))
            return {"ok": False, "checks": checks, "notes": notes, "scenario": self.name}

        checks.append(self._check("kill_switch_readable", True))

        triggered = bool(ks_data.get("triggered", False))
        reason = ks_data.get("reason", "no reason given")

        # Kill switch не должен быть активирован в штатном режиме
        ks_clear = not triggered
        checks.append(self._check("kill_switch_not_triggered", ks_clear,
                                   f"triggered={triggered}, reason={reason!r}"))

        if triggered:
            notes.append(f"WARNING: kill switch is ACTIVE — reason: {reason}")
            # Если ks активен — проверяем что позиции пусты
            pos_path = data_dir / "current_positions.json"
            pos_data = self._load_json(pos_path)
            if pos_data is not None:
                positions = pos_data.get("positions", {})
                non_zero = {k: v for k, v in positions.items() if float(v) > 0}
                positions_clear = len(non_zero) == 0
                checks.append(self._check("positions_cleared_after_ks", positions_clear,
                                           f"non-zero positions: {non_zero}"))
                if not positions_clear:
                    notes.append(f"WARNING: kill switch triggered but positions still open: {non_zero}")
            else:
                notes.append("current_positions.json unavailable — cannot verify position clearance")
        else:
            notes.append(f"Kill switch clear — reason: {reason}")

        # Проверяем метку времени (данные не должны быть слишком старыми — информационно)
        generated_at = ks_data.get("generated_at", "")
        checks.append(self._check("kill_switch_has_timestamp", bool(generated_at),
                                   f"generated_at={generated_at!r}"))

        ok = all(c["passed"] for c in checks)
        return {"ok": ok, "checks": checks, "notes": notes, "scenario": self.name}


# ---------------------------------------------------------------------------
# DEFAULT_SCENARIOS
# ---------------------------------------------------------------------------

DEFAULT_SCENARIOS: List[ForkScenario] = [
    AaveWithdrawScenario(),
    AllocationRebalanceScenario(),
    KillSwitchScenario(),
]


# ---------------------------------------------------------------------------
# run_e2e_dry
# ---------------------------------------------------------------------------

def run_e2e_dry(
    data_dir: Path,
    scenarios: Optional[List[ForkScenario]] = None,
) -> Dict[str, Any]:
    """Запускает все сценарии в dry-run режиме.

    Пишет результат в `data_dir / fork_harness_status.json` атомарно
    (tmp + os.replace). Никаких сетевых вызовов.

    Args:
        data_dir:  Путь к папке data/ с JSON-файлами состояния.
        scenarios: Список сценариев; None → DEFAULT_SCENARIOS.

    Returns:
        dict с ключами: ok, mode, run_at, scenarios (список результатов),
        summary (passed/total).
    """
    if scenarios is None:
        scenarios = DEFAULT_SCENARIOS

    data_dir = Path(data_dir)
    results: List[Dict[str, Any]] = []

    for scenario in scenarios:
        logger.info("Running dry-run scenario: %s", scenario.name)
        try:
            result = scenario.run_dry(data_dir)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Scenario '%s' raised an exception", scenario.name)
            result = {
                "ok": False,
                "checks": [],
                "notes": [f"exception: {exc}"],
                "scenario": scenario.name,
            }
        results.append(result)

    all_ok = all(r["ok"] for r in results)
    passed = sum(1 for r in results if r["ok"])
    total = len(results)

    output: Dict[str, Any] = {
        "ok": all_ok,
        "mode": "dry-run",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "scenarios": results,
        "summary": {"passed": passed, "total": total},
    }

    # Атомарная запись
    out_path = data_dir / "fork_harness_status.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, out_path)
        logger.info("fork_harness_status.json written: passed=%d/%d", passed, total)
    except OSError as exc:
        logger.warning("Failed to write fork_harness_status.json: %s", exc)
        # Убираем tmp если остался
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    return output


# ---------------------------------------------------------------------------
# run_e2e_live  (заглушка до MP-017)
# ---------------------------------------------------------------------------

def run_e2e_live(
    config: ForkConfig,
    data_dir: Path,
    scenarios: Optional[List[ForkScenario]] = None,
) -> Dict[str, Any]:
    """Запускает E2E тесты против локального форка mainnet (anvil).

    Требует: установленный anvil (Foundry) + config.rpc_url (MP-017).
    До получения RPC-ключей возвращает dry-run результат с предупреждением.
    """
    if config.is_dry_run:
        logger.warning(
            "run_e2e_live: live mode not available (%s) — falling back to dry-run",
            "rpc_url not set" if not config.rpc_url else "anvil not found",
        )
        result = run_e2e_dry(data_dir, scenarios)
        result["mode"] = "dry-run (live unavailable)"
        result["live_fallback_reason"] = (
            "rpc_url not configured" if not config.rpc_url else "anvil binary not found"
        )
        return result

    anvil = AnvilProcess()
    started = anvil.start(config)
    if not started:
        logger.warning("run_e2e_live: failed to start anvil — falling back to dry-run")
        result = run_e2e_dry(data_dir, scenarios)
        result["mode"] = "dry-run (anvil start failed)"
        return result

    try:
        if scenarios is None:
            scenarios = DEFAULT_SCENARIOS

        results: List[Dict[str, Any]] = []
        for scenario in scenarios:
            logger.info("Running live scenario: %s", scenario.name)
            try:
                res = scenario.run_live(data_dir, config.rpc_url, config.anvil_port)
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Live scenario '%s' raised an exception", scenario.name)
                res = {
                    "ok": False,
                    "checks": [],
                    "notes": [f"exception: {exc}"],
                    "scenario": scenario.name,
                }
            results.append(res)

        all_ok = all(r["ok"] for r in results)
        passed = sum(1 for r in results if r["ok"])
        total = len(results)

        output: Dict[str, Any] = {
            "ok": all_ok,
            "mode": "live",
            "run_at": datetime.now(timezone.utc).isoformat(),
            "scenarios": results,
            "summary": {"passed": passed, "total": total},
            "anvil_port": config.anvil_port,
            "fork_block": config.fork_block_number,
        }

        # Атомарная запись
        out_path = Path(data_dir) / "fork_harness_status.json"
        tmp_path = out_path.with_suffix(".json.tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, out_path)
        except OSError as exc:
            logger.warning("Failed to write fork_harness_status.json: %s", exc)
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        return output
    finally:
        anvil.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[List[str]] = None) -> int:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.testing.fork_harness",
        description="SPA E2E Fork Harness (MP-401)",
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--dry-run", action="store_true",
                            help="Offline dry-run (reads local JSON files only)")
    mode_group.add_argument("--live", action="store_true",
                            help="Live mode — requires anvil + RPC (MP-017)")
    parser.add_argument("--data-dir", default="data",
                        help="Path to data/ directory (default: data)")
    parser.add_argument("--rpc-url", default="",
                        help="Mainnet RPC URL (live mode only)")
    parser.add_argument("--fork-block", type=int, default=None,
                        help="Fork block number (live mode, default: latest)")
    parser.add_argument("--port", type=int, default=8545,
                        help="Anvil port (default: 8545)")

    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    if args.dry_run:
        result = run_e2e_dry(data_dir)
    else:
        config = ForkConfig(
            rpc_url=args.rpc_url,
            fork_block_number=args.fork_block,
            anvil_port=args.port,
        )
        result = run_e2e_live(config, data_dir)

    summary = result.get("summary", {})
    mode = result.get("mode", "unknown")
    ok_str = "PASS" if result.get("ok") else "FAIL"
    print(f"\n[fork-harness] mode={mode}  result={ok_str}  "
          f"passed={summary.get('passed', 0)}/{summary.get('total', 0)}")

    for sc in result.get("scenarios", []):
        sc_ok = "✓" if sc.get("ok") else "✗"
        print(f"  {sc_ok} {sc.get('scenario', '?')}")
        for check in sc.get("checks", []):
            chk_ok = "  ✓" if check["passed"] else "  ✗"
            detail = f" — {check['detail']}" if check.get("detail") else ""
            print(f"    {chk_ok} {check['name']}{detail}")
        for note in sc.get("notes", []):
            print(f"    ℹ {note}")

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_main())
