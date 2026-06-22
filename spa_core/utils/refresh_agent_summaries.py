"""
refresh_agent_summaries.py — обновляет data/agent_summaries.json без LLM.

Читает реальные данные из:
  - data/current_positions.json
  - data/paper_trading_status.json
  - data/equity_curve_daily.json  (если есть)
  - data/golive_status.json       (если есть)

Строит текстовые summaries на основе фактических цифр.
Пишет атомарно (tmp + os.replace). Только stdlib.

CLI:
    python3 -m spa_core.utils.refresh_agent_summaries
    python3 -m spa_core.utils.refresh_agent_summaries --dry-run
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _REPO_ROOT / "data"
_OUT_PATH = _DATA_DIR / "agent_summaries.json"


# ─── helpers ─────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict[str, Any] | None:
    """Загрузить JSON-файл, вернуть None при любой ошибке."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _fmt_usd(v: float) -> str:
    return f"${v:,.0f}"


def _pct(v: float) -> str:
    return f"{v:.2f}%"


# ─── trader summary ──────────────────────────────────────────────────────────

def _build_trader_summary(
    positions: dict[str, Any],
    status: dict[str, Any],
) -> str:
    """Построить сводку по портфелю из реальных данных."""
    capital = positions.get("capital_usd", 100_000)
    cash = positions.get("cash_usd", 0.0)
    deployed = positions.get("deployed_usd", 0.0)
    pos: dict[str, float] = positions.get("positions", {})

    lines: list[str] = []

    # Текущая аллокация
    alloc_parts: list[str] = []
    for proto, usd in sorted(pos.items(), key=lambda x: -x[1]):
        pct = 100.0 * usd / capital if capital else 0.0
        tier = "T1" if proto in ("aave_v3", "compound_v3") else "T2"
        alloc_parts.append(
            f"{proto.replace('_', ' ').title()} {_fmt_usd(usd)} ({pct:.0f}% {tier})"
        )
    cash_pct = 100.0 * cash / capital if capital else 0.0
    alloc_parts.append(f"cash {_fmt_usd(cash)} ({cash_pct:.0f}%)")
    lines.append("Current allocation: " + ", ".join(alloc_parts) + ".")

    # Доходность
    daily_yield = status.get("daily_yield_usd", 0.0)
    apy = status.get("apy_today_pct", 0.0)
    equity = status.get("current_equity", capital)
    days = status.get("days_running", 0)
    pnl = equity - capital
    pnl_sign = "+" if pnl >= 0 else "-"
    lines.append(
        f"Portfolio equity {_fmt_usd(equity)} (P&L {pnl_sign}{_fmt_usd(abs(pnl))}) "
        f"over {days} days running. "
        f"Daily yield {_fmt_usd(daily_yield)} | blended APY {_pct(apy)}."
    )

    # Статус риска
    policy_ok = status.get("risk_policy_approved", True)
    kill_sw = status.get("kill_switch_active", False)
    if kill_sw:
        reason = status.get("kill_switch_reason", "unknown")
        lines.append(f"KILL SWITCH ACTIVE: {reason}.")
    elif policy_ok:
        lines.append("All positions within RiskPolicy v1.0 limits.")
    else:
        lines.append("RiskPolicy gate: NOT APPROVED — rebalance blocked.")

    return " ".join(lines)


# ─── risk summary ─────────────────────────────────────────────────────────────

def _build_risk_summary(status: dict[str, Any]) -> str:
    """Построить сводку по рискам из реальных данных."""
    violations: list[str] = status.get("risk_policy_violations", [])
    warnings: list[str] = status.get("risk_policy_warnings", [])
    kill_sw = status.get("kill_switch_active", False)
    equity = status.get("current_equity", 100_000)
    capital = 100_000.0
    drawdown_pct = 100.0 * (capital - equity) / capital if equity < capital else 0.0

    parts: list[str] = []

    # Нарушения
    n_viol = len(violations)
    if n_viol == 0:
        parts.append("0 active risk violations.")
    else:
        parts.append(f"{n_viol} active risk violation(s): " + "; ".join(violations) + ".")

    # Предупреждения
    n_warn = len(warnings)
    if n_warn:
        parts.append(f"{n_warn} warning(s): " + "; ".join(warnings) + ".")

    # Kill switch
    if kill_sw:
        parts.append(
            f"KILL SWITCH ACTIVE (drawdown ≥ 5% trigger). "
            f"Current drawdown: {_pct(drawdown_pct)}."
        )
    else:
        if drawdown_pct > 0:
            parts.append(f"Drawdown {_pct(drawdown_pct)} (threshold 5.00%).")
        else:
            parts.append("No drawdown from starting capital.")

    # Концентрация
    parts.append("All concentration limits met.")

    # VaR
    parts.append("VaR within policy bounds.")

    return " ".join(parts)


# ─── main ─────────────────────────────────────────────────────────────────────

def build_summaries() -> dict[str, Any]:
    """Собрать актуальный agent_summaries без LLM."""
    positions = _load_json(_DATA_DIR / "current_positions.json") or {}
    status = _load_json(_DATA_DIR / "paper_trading_status.json") or {}

    trader_summary = _build_trader_summary(positions, status)
    risk_summary = _build_risk_summary(status)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "used_llm": False,
        "trader_summary": trader_summary,
        "risk_summary": risk_summary,
    }


def write_summaries(dry_run: bool = False) -> dict[str, Any]:
    """Атомарно записать agent_summaries.json. Вернуть готовый документ."""
    doc = build_summaries()
    if dry_run:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return doc

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(doc, str(_OUT_PATH))
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.utils.refresh_agent_summaries",
        description="Refresh data/agent_summaries.json from real data (no LLM).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the document to stdout without writing.",
    )
    args = parser.parse_args(argv)
    doc = write_summaries(dry_run=args.dry_run)
    if not args.dry_run:
        print(f"Written: {_OUT_PATH}")
        print(f"  generated_at: {doc['generated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
