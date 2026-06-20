"""
MP-414: Paper Trading Evidence Tracker

Накапливает ежедневные paper trading данные для подтверждения:
1. 30-дневный минимальный период (ADR-023)
2. Sharpe Ratio >= 0.80
3. Max Drawdown >= -5%
4. APY >= 7.0% net

Usage:
    tracker = PaperEvidenceTracker()
    tracker.record_day(date, apy_pct, equity_value, strategy_id)
    status = tracker.get_golive_status()

CLI:
    python3 -m spa_core.paper_trading.paper_evidence_tracker --check
    python3 -m spa_core.paper_trading.paper_evidence_tracker --run
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ─── Constants ───────────────────────────────────────────────────────────────

PAPER_START_DATE = date(2026, 6, 12)
MIN_DAYS_REQUIRED = 30
MIN_APY_PCT = 7.0
MIN_SHARPE = 0.80
MAX_DRAWDOWN_PCT = -5.0   # Kill switch: drawdown >= -5% halts rebalance
GOLIVE_TARGET_DATE = date(2026, 8, 1)
EVIDENCE_FILE = "data/paper_evidence.json"
SUMMARY_FILE = "data/paper_evidence_summary.json"
BASE_CAPITAL = 100_000.0

# Minimum days before Sharpe is considered meaningful
MIN_SHARPE_DAYS = 14


class PaperEvidenceTracker:
    """
    Накапливает и анализирует 30-дневные данные paper trading.

    Все записи на диск — атомарные: mkstemp + os.replace.
    Только stdlib. Read-only адрес к allocator/risk/execution запрещён.
    """

    def __init__(self, evidence_file: str = EVIDENCE_FILE):
        self.evidence_file = evidence_file
        self._data = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        """Загружает данные из файла или возвращает пустую структуру."""
        try:
            with open(self.evidence_file) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return self._empty_state()

    def _empty_state(self) -> dict:
        return {
            "schema_version": "1.0",
            "start_date": PAPER_START_DATE.isoformat(),
            "min_days_required": MIN_DAYS_REQUIRED,
            "golive_target": GOLIVE_TARGET_DATE.isoformat(),
            "base_capital": BASE_CAPITAL,
            "days": [],
            "strategies": {},
        }

    def _save(self) -> None:
        """Атомарная запись через mkstemp + os.replace."""
        path = Path(self.evidence_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(self._data, str(self.evidence_file))

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_day(
        self,
        trade_date: date,
        apy_pct: float,
        equity_value: float,
        strategy_id: str = "S7",
        notes: str = "",
    ) -> dict:
        """
        Записывает один день paper trading.

        Returns:
            Запись за этот день (новая или существующая если дубликат).
        """
        day_iso = trade_date.isoformat()

        # Идемпотентность: пропускаем дубликат
        existing = next((d for d in self._data["days"] if d["date"] == day_iso), None)
        if existing is not None:
            return existing

        # Equity предыдущего дня (или базовый капитал для первого дня)
        if self._data["days"]:
            prev_equity = self._data["days"][-1]["equity_value"]
        else:
            prev_equity = BASE_CAPITAL

        day_return_pct = (
            (equity_value - prev_equity) / prev_equity * 100
            if prev_equity > 0 else 0.0
        )

        entry = {
            "date": day_iso,
            "strategy_id": strategy_id,
            "apy_pct": round(float(apy_pct), 4),
            "equity_value": round(float(equity_value), 2),
            "day_return_pct": round(day_return_pct, 6),
            "notes": notes,
        }

        self._data["days"].append(entry)

        # Обновляем per-strategy stats
        stats = self._data["strategies"].setdefault(
            strategy_id, {"day_count": 0, "total_apy": 0.0, "first_date": day_iso}
        )
        stats["day_count"] += 1
        stats["total_apy"] = round(stats["total_apy"] + float(apy_pct), 6)
        stats["last_date"] = day_iso

        self._save()
        return entry

    # ── Metrics ───────────────────────────────────────────────────────────────

    def get_days_elapsed(self) -> int:
        """Количество записанных дней."""
        return len(self._data["days"])

    def get_avg_apy(self) -> float:
        """Средний APY по всем записанным дням."""
        days = self._data["days"]
        if not days:
            return 0.0
        return round(sum(d["apy_pct"] for d in days) / len(days), 6)

    def get_max_drawdown(self) -> float:
        """
        Максимальная просадка в % (отрицательное число или 0.0).

        Алгоритм: peak-to-trough от базового капитала.
        """
        days = self._data["days"]
        if not days:
            return 0.0
        peak = BASE_CAPITAL
        max_dd = 0.0
        for day in days:
            eq = day["equity_value"]
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (eq - peak) / peak * 100
                if dd < max_dd:
                    max_dd = dd
        return round(max_dd, 6)

    def get_sharpe_ratio(self) -> float:
        """
        Приближённый аннуализированный Sharpe (без risk-free rate).

        Формула: (mean_daily_return / std_daily_return) * sqrt(365)
        Требует >= 2 дней для вычисления std.
        """
        days = self._data["days"]
        if len(days) < 2:
            return 0.0
        returns = [d["day_return_pct"] for d in days]
        n = len(returns)
        mean = sum(returns) / n
        # Несмещённая дисперсия
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = variance ** 0.5
        if std == 0.0:
            return 0.0
        annualized = (mean / std) * (365 ** 0.5)
        return round(annualized, 6)

    def get_latest_equity(self) -> float:
        """Последнее значение equity. BASE_CAPITAL если нет данных."""
        if not self._data["days"]:
            return BASE_CAPITAL
        return self._data["days"][-1]["equity_value"]

    def get_total_return_pct(self) -> float:
        """Суммарный доход в % от базового капитала."""
        equity = self.get_latest_equity()
        return round((equity - BASE_CAPITAL) / BASE_CAPITAL * 100, 6)

    def get_days_list(self) -> list:
        """Возвращает список всех записанных дней (копия)."""
        return list(self._data["days"])

    def get_strategy_stats(self) -> dict:
        """Статистика по стратегиям."""
        return dict(self._data["strategies"])

    # ── Go-Live Status ────────────────────────────────────────────────────────

    def get_golive_status(self) -> dict:
        """
        Полный статус готовности к go-live.

        Checks:
          - min_days:    >= 30 recorded days
          - avg_apy:     >= 7.0%
          - max_drawdown: >= -5.0% (не хуже kill-switch)
          - sharpe:      >= 0.80 (требует >= 14 дней)
        """
        days_elapsed = self.get_days_elapsed()
        avg_apy = self.get_avg_apy()
        max_dd = self.get_max_drawdown()
        sharpe = self.get_sharpe_ratio()

        days_needed = max(0, MIN_DAYS_REQUIRED - days_elapsed)
        ready_date = PAPER_START_DATE + timedelta(days=MIN_DAYS_REQUIRED)
        today = date.today()
        days_to_target = (GOLIVE_TARGET_DATE - today).days

        checks = {
            "min_days": {
                "required": MIN_DAYS_REQUIRED,
                "actual": days_elapsed,
                "pass": days_elapsed >= MIN_DAYS_REQUIRED,
                "note": f"30-day window closes {ready_date.isoformat()}",
            },
            "avg_apy": {
                "required": MIN_APY_PCT,
                "actual": round(avg_apy, 4),
                "pass": avg_apy >= MIN_APY_PCT,
                "note": "Net APY across all recorded days",
            },
            "max_drawdown": {
                "required": MAX_DRAWDOWN_PCT,
                "actual": round(max_dd, 4),
                "pass": max_dd >= MAX_DRAWDOWN_PCT,
                "note": f"Kill-switch threshold {MAX_DRAWDOWN_PCT}%",
            },
            "sharpe": {
                "required": MIN_SHARPE,
                "actual": round(sharpe, 4),
                "pass": days_elapsed >= MIN_SHARPE_DAYS and sharpe >= MIN_SHARPE,
                "note": f"Requires >= {MIN_SHARPE_DAYS} days; annualised approx",
            },
        }

        passes = sum(1 for c in checks.values() if c["pass"])
        all_pass = passes == len(checks)

        blockers = [k for k, c in checks.items() if not c["pass"]]

        return {
            "as_of": today.isoformat(),
            "schema_version": "1.0",
            "days_elapsed": days_elapsed,
            "days_remaining": days_needed,
            "ready_date": ready_date.isoformat(),
            "golive_target": GOLIVE_TARGET_DATE.isoformat(),
            "days_to_golive": days_to_target,
            "buffer_days": (GOLIVE_TARGET_DATE - ready_date).days,
            "ready_for_golive": all_pass,
            "checks_passed": passes,
            "checks_total": len(checks),
            "blockers": blockers,
            "checks": checks,
            "latest_equity": self.get_latest_equity(),
            "total_return_pct": self.get_total_return_pct(),
            "avg_apy_pct": round(avg_apy, 4),
            "max_drawdown_pct": round(max_dd, 4),
            "sharpe_ratio": round(sharpe, 4),
        }

    # ── Export ────────────────────────────────────────────────────────────────

    def export_summary(self, output_file: str = SUMMARY_FILE) -> dict:
        """
        Экспортирует сводку go-live статуса для дашборда.

        Атомарная запись. Returns status dict.
        """
        status = self.get_golive_status()
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(status, str(output_file))
        return status


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_status(status: dict) -> None:
    """Human-readable output для CLI."""
    print("=" * 60)
    print("MP-414 Paper Evidence Tracker — Go-Live Readiness")
    print("=" * 60)
    print(f"As of:          {status['as_of']}")
    print(f"Days elapsed:   {status['days_elapsed']} / {MIN_DAYS_REQUIRED}")
    print(f"Days remaining: {status['days_remaining']}")
    print(f"Ready date:     {status['ready_date']}")
    print(f"Go-live target: {status['golive_target']}  (buffer: {status['buffer_days']}d)")
    print(f"Days to target: {status['days_to_golive']}")
    print()
    print(f"Latest equity:  ${status['latest_equity']:,.2f}")
    print(f"Total return:   {status['total_return_pct']:+.4f}%")
    print(f"Avg APY:        {status['avg_apy_pct']:.4f}%")
    print(f"Max drawdown:   {status['max_drawdown_pct']:.4f}%")
    print(f"Sharpe (approx):{status['sharpe_ratio']:.4f}")
    print()
    print(f"Checks: {status['checks_passed']}/{status['checks_total']}")
    for name, check in status["checks"].items():
        icon = "✅" if check["pass"] else "❌"
        note = check.get("note", "")
        print(
            f"  {icon} {name:15s}  required={check['required']}  "
            f"actual={check['actual']}  {note}"
        )
    print()
    if status["ready_for_golive"]:
        print("✅ READY FOR GO-LIVE")
    else:
        print(f"❌ NOT READY — blockers: {', '.join(status['blockers'])}")
    print("=" * 60)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MP-414 Paper Evidence Tracker — check go-live readiness"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print status (default, no write)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute, print, and write summary to data/paper_evidence_summary.json",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override base directory for data files",
    )
    args = parser.parse_args()

    evidence_file = EVIDENCE_FILE
    summary_file = SUMMARY_FILE
    if args.data_dir:
        base = args.data_dir.rstrip("/")
        evidence_file = f"{base}/paper_evidence.json"
        summary_file = f"{base}/paper_evidence_summary.json"

    tracker = PaperEvidenceTracker(evidence_file)

    if args.run:
        status = tracker.export_summary(summary_file)
        _print_status(status)
        print(f"\nSummary written → {summary_file}")
    else:
        status = tracker.get_golive_status()
        _print_status(status)

    sys.exit(0)


if __name__ == "__main__":
    main()
