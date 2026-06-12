#!/usr/bin/env python3
"""
Kill-Switch Drill — MP-312
Проверяет что система корректно реагирует на 5% drawdown.
Только симуляция — НЕ трогает реальные позиции.

Использование:
    python3 scripts/kill_switch_drill.py
    python3 scripts/kill_switch_drill.py --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import datetime
import inspect
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))


def run_drill(data_dir: str | None = None) -> dict:
    """Запускает kill-switch drill. Возвращает dict с результатами.

    Только симуляция — НЕ трогает реальные позиции и state-файлы.
    """
    ddir = Path(data_dir) if data_dir else _REPO_ROOT / "data"

    results: dict = {
        "drill_timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "mp": "MP-312",
        "steps": [],
        "passed": False,
        "total_time_ms": 0.0,
        "verdict": "",
        "note": "",
    }

    t0 = time.time()

    # ── Step 1: Импорт RiskPolicy ─────────────────────────────────────────────
    try:
        from spa_core.risk.policy import (  # noqa: PLC0415
            PortfolioState,
            Position,
            RiskPolicy,
            RiskConfig,
        )
        results["steps"].append({
            "step": "import_risk_policy",
            "ok": True,
            "detail": "spa_core.risk.policy imported (RiskPolicy, PortfolioState, Position, RiskConfig)",
        })
    except Exception as exc:
        results["steps"].append({
            "step": "import_risk_policy",
            "ok": False,
            "error": str(exc),
        })
        results["total_time_ms"] = round((time.time() - t0) * 1000, 1)
        results["verdict"] = "FAIL ❌"
        results["note"] = f"Cannot import RiskPolicy: {exc}"
        return results

    # ── Step 2: Симуляция 5% drawdown через check_portfolio_health ────────────
    try:
        policy = RiskPolicy()

        # Строим PortfolioState с total_drawdown_pct == 5%:
        #   total_capital_usd = 100_000
        #   positions: одна позиция с unrealized_pnl = -5000 → drawdown = 5000/100000 = 5%
        sim_position = Position(
            protocol_key="sim_test_protocol",
            tier="T1",
            asset="USDC",
            amount_usd=95_000.0,
            apy_at_open=5.0,
            current_apy=5.0,
            unrealized_pnl_usd=-5_000.0,  # -$5,000 → 5% portfolio drawdown
        )
        sim_state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[sim_position],
        )

        # Убеждаемся что мы действительно получили 5% drawdown
        actual_drawdown = sim_state.total_drawdown_pct
        assert abs(actual_drawdown - 0.05) < 1e-9, (
            f"Expected 5% drawdown, got {actual_drawdown:.4%}"
        )

        result = policy.check_portfolio_health(sim_state)
        kill_switch_triggered = not result.approved
        violations_with_kill = [
            v for v in result.violations
            if "KILL SWITCH" in v or "drawdown" in v.lower()
        ]

        results["steps"].append({
            "step": "simulate_5pct_drawdown",
            "ok": kill_switch_triggered and len(violations_with_kill) > 0,
            "drawdown_pct": round(actual_drawdown * 100, 4),
            "kill_switch_triggered": kill_switch_triggered,
            "violations_detected": result.violations,
            "detail": (
                f"check_portfolio_health → approved={result.approved}, "
                f"{len(result.violations)} violation(s)"
            ),
        })
    except Exception as exc:
        results["steps"].append({
            "step": "simulate_5pct_drawdown",
            "ok": False,
            "error": str(exc),
        })

    # ── Step 3: Проверить наличие risk gate в cycle_runner ───────────────────
    try:
        from spa_core.paper_trading import cycle_runner  # noqa: PLC0415

        source = inspect.getsource(cycle_runner)
        has_risk_policy = "RiskPolicy" in source
        has_risk_check = "_apply_risk_policy_gate" in source or "check_new_position" in source
        has_kill_switch = "kill_switch" in source.lower()
        gate_ok = has_risk_policy and has_risk_check and has_kill_switch

        results["steps"].append({
            "step": "verify_risk_gate_in_cycle_runner",
            "ok": gate_ok,
            "has_RiskPolicy": has_risk_policy,
            "has_risk_check_call": has_risk_check,
            "has_kill_switch": has_kill_switch,
            "detail": (
                "RiskPolicy gate + kill-switch found in cycle_runner"
                if gate_ok
                else "WARNING: risk gate and/or kill-switch missing from cycle_runner"
            ),
        })
    except Exception as exc:
        results["steps"].append({
            "step": "verify_risk_gate_in_cycle_runner",
            "ok": False,
            "error": str(exc),
        })

    # ── Step 4: Текущий drawdown из реальных данных ───────────────────────────
    try:
        status_path = ddir / "paper_trading_status.json"
        pts = json.loads(status_path.read_text(encoding="utf-8"))
        equity = float(pts.get("current_equity", 100_000.0))
        initial_capital = 100_000.0
        drawdown_pct = max(0.0, (initial_capital - equity) / initial_capital * 100.0)
        would_trigger = drawdown_pct >= 5.0

        results["steps"].append({
            "step": "check_current_drawdown",
            "ok": True,
            "current_equity": equity,
            "initial_capital": initial_capital,
            "drawdown_pct": round(drawdown_pct, 4),
            "kill_switch_would_trigger": would_trigger,
            "detail": (
                f"equity=${equity:,.2f}, drawdown={drawdown_pct:.4f}% "
                f"({'≥' if would_trigger else '<'} 5% threshold)"
            ),
        })
    except Exception as exc:
        results["steps"].append({
            "step": "check_current_drawdown",
            "ok": False,
            "error": str(exc),
        })

    # ── Step 5: Проверить RiskConfig версию v1.0 ─────────────────────────────
    try:
        cfg = RiskConfig()
        version_ok = cfg.version == "v1.0"
        drawdown_threshold_ok = abs(cfg.max_drawdown_stop - 0.05) < 1e-9

        results["steps"].append({
            "step": "verify_risk_config",
            "ok": version_ok and drawdown_threshold_ok,
            "version": cfg.version,
            "max_drawdown_stop": cfg.max_drawdown_stop,
            "detail": (
                f"RiskConfig v={cfg.version}, max_drawdown_stop={cfg.max_drawdown_stop:.0%}"
            ),
        })
    except Exception as exc:
        results["steps"].append({
            "step": "verify_risk_config",
            "ok": False,
            "error": str(exc),
        })

    # ── Итог ─────────────────────────────────────────────────────────────────
    total_ms = round((time.time() - t0) * 1000, 1)
    results["total_time_ms"] = total_ms

    all_ok = all(s.get("ok", False) for s in results["steps"])
    results["passed"] = all_ok and total_ms < 1000
    results["verdict"] = "PASS ✅" if results["passed"] else "FAIL ❌"
    results["note"] = (
        f"Kill-switch gate verified in {total_ms}ms (limit: 1000ms). "
        f"{len(results['steps'])} steps, all_ok={all_ok}."
    )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Kill-Switch Drill MP-312")
    parser.add_argument("--data-dir", default=None, help="Path to data/ directory")
    args = parser.parse_args()

    result = run_drill(data_dir=args.data_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
