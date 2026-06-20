"""
spa_core/reporting/backtest_report.py

MP-1498 (v11.14) — Comprehensive backtesting report generator.

Aggregates results from:
  - WalkForwardValidator  (data/walk_forward_{strategy_id}.json)
  - MonteCarloSimulator   (data/monte_carlo_{strategy_id}.json)
  - BacktestPaperCorrelation (data/backtest_paper_correlation.json)
  - BacktestGate          (data/backtest_gate_status.json)

Produces a unified JSON summary + Markdown report per strategy.

Rules (stdlib-only, read-only domain):
  - No external dependencies
  - Never modifies allocator / risk / execution domains
  - Atomic saves via BaseReport

Output paths:
  JSON:     data/backtest_report_{strategy_id}.json
  Markdown: data/backtest_report_{strategy_id}.md

Usage:
    from spa_core.reporting.backtest_report import BacktestReport

    report = BacktestReport(strategy_id="S0")
    summary = report.generate()
    report.save()
    report.save_markdown()
"""

import datetime
import os
from spa_core.base import BaseReport
from spa_core.utils.atomic import atomic_load


_GATE_STATES = ("BACKTEST_PASS", "PRE_PAPER_PASS", "PAPER_IN_PROGRESS", "LIVE_LOCKED")


class BacktestReport(BaseReport):
    """
    Generates a comprehensive backtesting report for a SPA strategy.

    Reads data files produced by:
      - WalkForwardValidator
      - MonteCarloSimulator
      - BacktestPaperCorrelation
      - BacktestGate (optional)

    and consolidates them into a single JSON + Markdown artefact.
    """

    def __init__(self, strategy_id: str, base_dir: str = "."):
        super().__init__(base_dir)
        self.strategy_id = strategy_id
        strategy_safe = strategy_id.replace("/", "_").replace(" ", "_")
        self.OUTPUT_PATH = f"data/backtest_report_{strategy_safe}.json"
        self._report: dict = {}

    # ── public API ────────────────────────────────────────────────────────────

    def generate(self) -> dict:
        """
        Generates the full backtesting report for the strategy.

        Returns:
            Comprehensive report dict.
        """
        self._report = {
            "strategy": self.strategy_id,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "summary": self._build_summary(),
            "walk_forward": self._load_walk_forward(),
            "monte_carlo": self._load_monte_carlo(),
            "backtest_paper_correlation": self._load_correlation(),
            "gate_status": self._load_gate_status(),
            "recommendation": self._build_recommendation(),
        }
        return self._report

    def to_dict(self) -> dict:
        return self._report

    def to_markdown(self) -> str:
        """Renders the report as a Markdown string."""
        if not self._report:
            self.generate()

        r = self._report
        wf = r.get("walk_forward", {})
        mc = r.get("monte_carlo", {})
        corr = r.get("backtest_paper_correlation", {})
        rec = r.get("recommendation", {})

        lines = [
            f"# Backtest Report — Strategy {r['strategy']}",
            f"\n_Generated: {r['generated_at']}_",
            "",
            "## Summary",
            "",
        ]

        summary = r.get("summary", {})
        lines += [
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Annualised Return | {summary.get('annualized_return', 'N/A')} |",
            f"| Volatility (ann.) | {summary.get('volatility', 'N/A')} |",
            f"| Sharpe Ratio      | {summary.get('sharpe_ratio', 'N/A')} |",
            f"| Max Drawdown      | {summary.get('max_drawdown', 'N/A')} |",
            f"| Calmar Ratio      | {summary.get('calmar_ratio', 'N/A')} |",
            "",
            "## Walk-Forward Validation",
            "",
        ]

        if wf.get("error"):
            lines.append(f"_Data not available: {wf['error']}_")
        else:
            lines += [
                f"- Windows: {wf.get('n_windows', 'N/A')}",
                f"- IS Sharpe avg: {wf.get('is_sharpe_avg', 'N/A')}",
                f"- OOS Sharpe avg: {wf.get('oos_sharpe_avg', 'N/A')}",
                f"- Degradation ratio: {wf.get('degradation_ratio', 'N/A')}",
                f"- Verdict: **{wf.get('verdict', 'N/A')}**",
            ]

        lines += ["", "## Monte Carlo Simulation", ""]

        if mc.get("error"):
            lines.append(f"_Data not available: {mc['error']}_")
        else:
            lines += [
                f"- Simulations: {mc.get('simulations', 'N/A')}",
                f"- P5 / P50 / P95: {mc.get('p5', 'N/A')} / {mc.get('p50', 'N/A')} / {mc.get('p95', 'N/A')}",
                f"- Prob. profitable: {mc.get('prob_profitable', 'N/A')}",
                f"- Prob. drawdown >20%: {mc.get('prob_drawdown_20pct', 'N/A')}",
                f"- Verdict: **{mc.get('verdict', 'N/A')}**",
            ]

        lines += ["", "## Backtest vs Paper Correlation", ""]

        if corr.get("error"):
            lines.append(f"_Data not available: {corr['error']}_")
        else:
            lines += [
                f"- Days tracked: {corr.get('days_tracked', 'N/A')}",
                f"- Spearman ρ: {corr.get('spearman_correlation', 'N/A')}",
                f"- MAE: {corr.get('mean_absolute_error', 'N/A')}",
                f"- Passes GoLive threshold (ρ ≥ 0.70): {corr.get('passes_threshold', 'N/A')}",
                f"- GoLive ready (30 days + threshold): {corr.get('golive_ready', 'N/A')}",
            ]

        gate = r.get("gate_status", {})
        lines += ["", "## Gate Status", ""]
        if gate.get("error"):
            lines.append(f"_Gate data not available: {gate['error']}_")
        else:
            lines.append(f"- 4-State Gate: **{gate.get('state', 'N/A')}**")
            lines.append(f"- Paper trading allowed: {gate.get('paper_trading_allowed', 'N/A')}")

        lines += [
            "",
            "## Recommendation",
            "",
            f"**{rec.get('action', 'N/A')}** — {rec.get('rationale', '')}",
            "",
        ]

        return "\n".join(lines)

    # ── private loaders ───────────────────────────────────────────────────────

    def _build_summary(self) -> dict:
        """
        Returns high-level performance summary.

        Loads equity_curve_daily.json to compute return, volatility,
        Sharpe, max drawdown, Calmar. Falls back to zeros if unavailable.
        """
        try:
            equity = atomic_load(self._path("data/equity_curve_daily.json"))
            if not equity or not isinstance(equity, list):
                return self._zero_summary()
            values = [e.get("equity", 0.0) for e in equity if "equity" in e]
            if len(values) < 2:
                return self._zero_summary()
            return self._compute_summary(values)
        except Exception:
            return self._zero_summary()

    def _compute_summary(self, values: list) -> dict:
        """Computes summary stats from a list of equity values."""
        import statistics

        # Daily returns
        returns = [
            (values[i] - values[i - 1]) / values[i - 1]
            for i in range(1, len(values))
            if values[i - 1] != 0
        ]
        if not returns:
            return self._zero_summary()

        ann_return = ((values[-1] / values[0]) ** (252.0 / len(returns)) - 1.0)
        volatility = statistics.stdev(returns) * (252 ** 0.5) if len(returns) > 1 else 0.0
        sharpe = (ann_return - 0.05) / volatility if volatility > 0 else 0.0

        # Max drawdown
        peak = values[0]
        max_dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        calmar = abs(ann_return / max_dd) if max_dd > 0 else 0.0

        return {
            "annualized_return": round(ann_return, 4),
            "volatility": round(volatility, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_dd, 4),
            "calmar_ratio": round(calmar, 4),
        }

    @staticmethod
    def _zero_summary() -> dict:
        return {
            "annualized_return": 0.0,
            "volatility": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
        }

    def _load_walk_forward(self) -> dict:
        strategy_safe = self.strategy_id.replace("/", "_").replace(" ", "_")
        path = self._path(f"data/walk_forward_{strategy_safe}.json")
        try:
            data = atomic_load(path)
            return data if data else {"error": "empty file"}
        except FileNotFoundError:
            return {"error": "file not found", "path": path}
        except Exception as exc:
            return {"error": str(exc)}

    def _load_monte_carlo(self) -> dict:
        strategy_safe = self.strategy_id.replace("/", "_").replace(" ", "_")
        path = self._path(f"data/monte_carlo_{strategy_safe}.json")
        try:
            data = atomic_load(path)
            if not data:
                return {"error": "empty file"}
            # Extract this strategy's result if nested
            results = data.get("results", {})
            return results.get(self.strategy_id, data)
        except FileNotFoundError:
            return {"error": "file not found", "path": path}
        except Exception as exc:
            return {"error": str(exc)}

    def _load_correlation(self) -> dict:
        path = self._path("data/backtest_paper_correlation.json")
        try:
            data = atomic_load(path)
            return data if data else {"error": "empty file"}
        except FileNotFoundError:
            return {"error": "file not found", "path": path}
        except Exception as exc:
            return {"error": str(exc)}

    def _load_gate_status(self) -> dict:
        path = self._path("data/backtest_gate_status.json")
        try:
            data = atomic_load(path)
            return data if data else {"error": "empty file"}
        except FileNotFoundError:
            return {"error": "file not found", "path": path}
        except Exception as exc:
            return {"error": str(exc)}

    # ── recommendation ────────────────────────────────────────────────────────

    def _build_recommendation(self) -> dict:
        """
        Derives a go/no-go recommendation from the aggregated report.

        Logic:
          - If walk_forward verdict is STRONG or MODERATE → positive signal
          - If Monte Carlo verdict is ROBUST or MODERATE → positive signal
          - If backtest-paper correlation passes_threshold → positive signal
          - 3 positive signals → PROCEED_TO_LIVE
          - 2 positive signals → PROCEED_TO_PAPER
          - < 2               → REVISE_STRATEGY
        """
        wf = self._report.get("walk_forward", {})
        mc = self._report.get("monte_carlo", {})
        corr = self._report.get("backtest_paper_correlation", {})

        signals = 0
        notes = []

        wf_verdict = wf.get("verdict", "")
        if wf_verdict in ("STRONG", "MODERATE"):
            signals += 1
            notes.append(f"Walk-forward: {wf_verdict}")

        mc_verdict = mc.get("verdict", "")
        if mc_verdict in ("ROBUST", "MODERATE"):
            signals += 1
            notes.append(f"Monte Carlo: {mc_verdict}")

        if corr.get("passes_threshold", False):
            signals += 1
            notes.append("Backtest-paper correlation ≥ 0.70")

        if signals >= 3:
            action = "PROCEED_TO_LIVE"
        elif signals >= 2:
            action = "PROCEED_TO_PAPER"
        else:
            action = "REVISE_STRATEGY"

        return {
            "action": action,
            "positive_signals": signals,
            "rationale": "; ".join(notes) if notes else "Insufficient evidence",
        }
