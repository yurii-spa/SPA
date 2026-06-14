"""
SPA Strategy Agent
==================

Агент который каждые 4 часа:
  1. Загружает исторические данные из data/historical_apy.json или генерирует синтетические
  2. Запускает multi-strategy backtest для всех зарегистрированных стратегий
  3. Вычисляет Sharpe, max_dd, calmar, risk_adjusted_score
  4. Выбирает "winner" по риск-скорректированной доходности
  5. Генерирует рекомендацию по аллокации (как распределить $100K между стратегиями)
  6. Сохраняет результаты в:
       data/strategy_comparison.json    — таблица сравнения стратегий
       data/strategy_agent_report.json  — winner + рекомендация + объяснение

LLM: используется Claude Sonnet 4.6 для генерации объяснений и рекомендаций.
Бэктест: СТРОГО ДЕТЕРМИНИРОВАННЫЙ (MultiStrategyBacktest — без LLM).

Использование:
    python -m spa_core.agents.strategy_agent
    python -m spa_core.agents.strategy_agent --dry-run   # без записи файлов
    python -m spa_core.agents.strategy_agent --no-llm    # без LLM объяснений
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Добавляем spa_core в путь
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

log = logging.getLogger(__name__)

# ─── Пути к данным ────────────────────────────────────────────────────────────

_DATA_DIR = _ROOT.parent / "data"

OUTPUT_COMPARISON_PATH   = _DATA_DIR / "strategy_comparison.json"
OUTPUT_AGENT_REPORT_PATH = _DATA_DIR / "strategy_agent_report.json"

# ─── Константы ────────────────────────────────────────────────────────────────

INITIAL_CAPITAL    = 100_000.0
BACKTEST_DAYS      = 90
WALK_FORWARD_TRAIN = 60
WALK_FORWARD_TEST  = 30


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def _load_historical_data(days: int = BACKTEST_DAYS) -> list[dict]:
    """
    Загружает исторические данные.
    Приоритет: data/historical_apy.json → синтетические данные.
    """
    hist_path = _DATA_DIR / "historical_apy.json"
    if hist_path.exists():
        try:
            raw = json.loads(hist_path.read_text())
            flat: list[dict] = []
            if isinstance(raw, list):
                flat = raw
            elif isinstance(raw, dict):
                for protocol_key, records in raw.items():
                    if isinstance(records, list):
                        for rec in records:
                            if isinstance(rec, dict) and "date" in rec:
                                flat.append({
                                    "timestamp":    rec["date"],
                                    "protocol_key": protocol_key,
                                    "apy":          float(rec.get("apy", 0.0)),
                                    "tvl_usd":      float(rec.get("tvl_usd", 10_000_000)),
                                    "tier":         rec.get("tier", "T1"),
                                })
            if flat:
                all_dates = sorted({r["timestamp"][:10] for r in flat})
                cutoff = all_dates[-days] if len(all_dates) >= days else all_dates[0]
                flat = [r for r in flat if r["timestamp"][:10] >= cutoff]
                log.info("Loaded %d records from historical_apy.json (%d days)", len(flat), days)
                return flat
        except Exception as exc:
            log.warning("Could not parse historical_apy.json: %s — using synthetic", exc)

    log.info("Using synthetic historical data (%d days)", days)
    try:
        from backtesting.data_loader import generate_synthetic_history
        return generate_synthetic_history(days=days)
    except Exception as exc:
        log.error("Could not generate synthetic data: %s", exc)
        return []


def _build_allocation_recommendation(
    leaderboard: list[dict],
    total_capital: float = INITIAL_CAPITAL,
) -> dict:
    """
    Строит детерминированную рекомендацию по аллокации капитала
    между стратегиями на основе их risk_adjusted_score.

    T3 стратегии кепированы на 20% (высокий риск / плечо).
    """
    valid = [r for r in leaderboard if not r.get("error") and r.get("risk_adjusted_score", 0) > 0]
    if not valid:
        return {"allocations": [], "total_capital": total_capital,
                "expected_apy": 0.0, "reasoning": "No valid strategies",
                "generated_at": datetime.now(timezone.utc).isoformat()}

    T3_CAP    = 0.20
    raw_scores = {r["strategy_id"]: r["risk_adjusted_score"] for r in valid}
    total_score = sum(raw_scores.values())
    if total_score == 0:
        return {"allocations": [], "total_capital": total_capital,
                "expected_apy": 0.0, "reasoning": "All scores are 0",
                "generated_at": datetime.now(timezone.utc).isoformat()}

    raw_weights = {sid: score / total_score for sid, score in raw_scores.items()}
    t3_ids      = {r["strategy_id"] for r in valid if r.get("risk_tier") == "T3"}
    excess = 0.0
    capped: dict[str, float] = {}
    free_ids: list[str] = []

    for sid, w in raw_weights.items():
        if sid in t3_ids and w > T3_CAP:
            capped[sid] = T3_CAP
            excess += w - T3_CAP
        else:
            free_ids.append(sid)

    if excess > 0 and free_ids:
        free_total = sum(raw_weights[sid] for sid in free_ids)
        for sid in free_ids:
            bump = excess * (raw_weights[sid] / free_total) if free_total > 0 else 0.0
            capped[sid] = raw_weights.get(sid, 0.0) + bump
    else:
        for sid in free_ids:
            capped[sid] = raw_weights[sid]

    total_w    = sum(capped.values())
    normalized = {sid: w / total_w for sid, w in capped.items()}

    allocations = []
    for r in valid:
        sid    = r["strategy_id"]
        weight = normalized.get(sid, 0.0)
        amount = round(total_capital * weight, 2)
        allocations.append({
            "strategy_id":           sid,
            "strategy_name":         r.get("strategy_name", sid),
            "risk_tier":             r.get("risk_tier", "?"),
            "weight_pct":            round(weight * 100, 2),
            "amount_usd":            amount,
            "target_apy_range":      r.get("target_apy_range", "?"),
            "risk_adjusted_score":   r.get("risk_adjusted_score", 0.0),
        })
    allocations.sort(key=lambda a: a["weight_pct"], reverse=True)

    # Ожидаемый APY
    expected_apy = 0.0
    for a in allocations:
        try:
            parts = a.get("target_apy_range", "0–0%").replace("%", "").split("–")
            mid   = (float(parts[0]) + float(parts[1])) / 2.0
            expected_apy += mid * (a["weight_pct"] / 100.0)
        except Exception:
            pass

    return {
        "allocations":    allocations,
        "total_capital":  total_capital,
        "expected_apy":   round(expected_apy, 2),
        "t3_cap_pct":     T3_CAP * 100,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
    }


def _generate_explanation(winner: dict, leaderboard: list[dict], allocation: dict, use_llm: bool) -> str:
    """
    Генерирует объяснение выбора winner.
    Если use_llm=True — пробует LLM, фоллбэк на детерминированный текст.
    """
    if use_llm:
        try:
            import anthropic
            from agents.model_config import get_model_for_agent
            client  = anthropic.Anthropic()
            model   = get_model_for_agent("strategy")
            prompt  = (
                f"You are the SPA Strategy Agent. Briefly explain (3 paragraphs max) why "
                f"'{winner.get('strategy_id')}' won the backtest leaderboard and why the "
                f"allocation recommendation is sensible.\n\n"
                f"Leaderboard (top 5):\n{json.dumps(leaderboard[:5], indent=2)}\n\n"
                f"Allocation:\n{json.dumps(allocation, indent=2)}"
            )
            resp = client.messages.create(
                model=model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as exc:
            log.info("LLM explanation unavailable (%s), using fallback", exc)

    # Детерминированный фоллбэк
    wid    = winner.get("strategy_id", "unknown")
    wscore = winner.get("risk_adjusted_score", 0.0)
    wret   = winner.get("annualised_return_pct", 0.0)
    wsh    = winner.get("sharpe_ratio", 0.0)
    wdd    = winner.get("max_drawdown_pct", 0.0)
    exp    = allocation.get("expected_apy", 0.0)

    lines = [
        f"'{wid}' leads with risk-adjusted score {wscore:.3f}: {wret:.1f}% annualised return, "
        f"Sharpe {wsh:.2f}, max drawdown {wdd:.2f}%.",
        "",
        "Leaderboard (top 3):",
    ]
    for i, r in enumerate(leaderboard[:3], 1):
        lines.append(
            f"  #{i} {r.get('strategy_id','?'):28s} "
            f"APY={r.get('annualised_return_pct',0):5.1f}%  "
            f"Sharpe={r.get('sharpe_ratio',0):4.2f}  "
            f"Score={r.get('risk_adjusted_score',0):.3f}"
        )
    lines.append(
        f"\nAllocation blends {len(allocation.get('allocations',[]))} strategies "
        f"for ~{exp:.1f}% expected APY."
    )
    t3_in = any(a.get("risk_tier") == "T3" for a in allocation.get("allocations", []))
    if t3_in:
        lines.append("T3 yield-loop capped at 20% (leverage risk; paper trading only).")
    return "\n".join(lines)


# ─── Главный класс агента ─────────────────────────────────────────────────────

class StrategyAgent:
    """
    Strategy Agent — периодически запускает multi-strategy backtest
    и формирует рекомендацию по аллокации.

    LLM-OK: использует Claude Sonnet 4.6 только для объяснений.
    Бэктест: строго детерминированный.
    """

    def __init__(
        self,
        dry_run: bool = False,
        use_llm: bool = True,
        initial_capital: float = INITIAL_CAPITAL,
    ) -> None:
        self.dry_run        = dry_run
        self.use_llm        = use_llm
        self.initial_capital = initial_capital

    def run(self) -> dict:
        """
        Основной цикл:
        1. Загрузить данные → 2. Backtest → 3. Рекомендация → 4. LLM → 5. Сохранить
        """
        log.info("[StrategyAgent] Starting strategy evaluation cycle")
        started_at = datetime.now(timezone.utc)

        # 1. Данные
        hist_data = _load_historical_data(days=BACKTEST_DAYS)
        if not hist_data:
            return {"error": "no_historical_data"}

        # 2. Multi-strategy backtest
        from backtesting.multi_strategy_backtest import MultiStrategyBacktest
        bt           = MultiStrategyBacktest(initial_capital=self.initial_capital)
        full_results = bt.run_all(hist_data)
        if not full_results:
            return {"error": "no_results"}

        leaderboard = bt.leaderboard(full_results)
        winner_obj  = bt.winner(full_results)
        winner_dict = winner_obj.to_summary() if winner_obj else {}

        # 3. Walk-forward
        log.info("[StrategyAgent] Walk-forward validation")
        wf_slices  = bt.walk_forward(hist_data, WALK_FORWARD_TRAIN, WALK_FORWARD_TEST)
        wf_summary = bt.walk_forward_summary(wf_slices)

        # 4. Аллокация
        allocation = _build_allocation_recommendation(leaderboard, self.initial_capital)

        # 5. Объяснение
        explanation = _generate_explanation(winner_dict, leaderboard, allocation, self.use_llm)

        finished_at   = datetime.now(timezone.utc)
        duration_s    = (finished_at - started_at).total_seconds()

        comparison_doc = {
            "generated_at":       finished_at.isoformat(),
            "backtest_days":      BACKTEST_DAYS,
            "strategies_tested":  len(full_results),
            "leaderboard":        leaderboard,
            "winner":             winner_dict,
            "walk_forward":       wf_summary,
            "duration_seconds":   round(duration_s, 2),
        }

        agent_report = {
            "generated_at":           finished_at.isoformat(),
            "agent":                  "StrategyAgent",
            "model":                  self._get_model(),
            "winner":                 winner_dict,
            "why_winner":             explanation,
            "allocation_recommendation": allocation,
            "walk_forward_hit_rate":  wf_summary.get("hit_rate", 0.0),
            "walk_forward_windows":   wf_summary.get("windows", 0),
            "leaderboard_snapshot":   leaderboard[:5],
            "duration_seconds":       round(duration_s, 2),
            "dry_run":                self.dry_run,
        }

        # 6. Сохраняем
        if not self.dry_run:
            self._save(comparison_doc, OUTPUT_COMPARISON_PATH)
            self._save(agent_report,   OUTPUT_AGENT_REPORT_PATH)
        else:
            log.info("[StrategyAgent] DRY RUN — skipping file writes")

        log.info(
            "[StrategyAgent] Done in %.1fs. Winner: %s (score=%.3f)",
            duration_s,
            winner_dict.get("strategy_id", "none"),
            winner_dict.get("risk_adjusted_score", 0.0),
        )
        return agent_report

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _save(self, data: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
        log.info("Saved: %s", path)

    def _get_model(self) -> str:
        try:
            from agents.model_config import get_model_for_agent
            return get_model_for_agent("strategy")
        except Exception:
            return "claude-sonnet-4-6"

    def print_report(self, report: dict) -> None:
        """ASCII-отчёт в stdout."""
        w     = report.get("winner", {})
        alloc = report.get("allocation_recommendation", {})
        print("\n" + "=" * 65)
        print(f"  SPA STRATEGY AGENT REPORT  [{report.get('generated_at','')[:19]}]")
        print("=" * 65)
        print(f"\n🏆  WINNER: {w.get('strategy_id','N/A')}")
        print(f"    Risk Tier  : {w.get('risk_tier','?')}")
        print(f"    Ann. Return: {w.get('annualised_return_pct',0):.2f}%")
        print(f"    Sharpe     : {w.get('sharpe_ratio',0):.3f}")
        print(f"    Max DD     : {w.get('max_drawdown_pct',0):.2f}%")
        print(f"    Score      : {w.get('risk_adjusted_score',0):.4f}")
        print(f"\n💡  WHY:\n  {report.get('why_winner','').replace(chr(10), chr(10)+'  ')}")
        print(f"\n📊  ALLOCATION (${alloc.get('total_capital',0):,.0f}, "
              f"expected ~{alloc.get('expected_apy',0):.1f}% APY):")
        for a in alloc.get("allocations", []):
            print(
                f"    {a.get('strategy_id',''):28s}  "
                f"{a['weight_pct']:5.1f}%  "
                f"${a['amount_usd']:>10,.0f}  "
                f"[{a.get('risk_tier','?')}]  "
                f"{a.get('target_apy_range','?')}"
            )
        wf_rate = report.get("walk_forward_hit_rate", 0)
        print(f"\n🔄  Walk-forward hit rate: {wf_rate:.1%} "
              f"({report.get('walk_forward_windows',0)} windows)")
        print(f"⏱   Duration: {report.get('duration_seconds',0):.1f}s")
        print("=" * 65 + "\n")


# ─── CLI точка входа ──────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="SPA Strategy Agent — backtest all strategies and recommend allocation"
    )
    parser.add_argument("--dry-run",  action="store_true", help="Don't write output files")
    parser.add_argument("--no-llm",   action="store_true", help="Skip LLM explanation")
    parser.add_argument("--capital",  type=float, default=INITIAL_CAPITAL,
                        help=f"Initial capital (default: ${INITIAL_CAPITAL:,.0f})")
    args = parser.parse_args()

    agent  = StrategyAgent(dry_run=args.dry_run, use_llm=not args.no_llm,
                           initial_capital=args.capital)
    report = agent.run()
    if "error" in report:
        print(f"ERROR: {report['error']}")
        sys.exit(1)
    agent.print_report(report)


if __name__ == "__main__":
    main()
