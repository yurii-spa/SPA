"""
spa_core/strategy_lab/report.py — comparative markdown report for the Strategy Lab backtest.

Renders the run_backtest() result dict into a clean markdown document:
  - run manifest (window, capital, seed, n_snapshots, equal-capital note),
  - LOUD window_warnings (if the window under-tests Variant D/N),
  - the comparative TABLE of all strategies (reusing metrics.compare_table) with the RWA floor
    highlighted as the benchmark row and non-passers flagged,
  - a kill summary (which strategies were killed, when, why).

Strategies are ordered: candidates (variant_n, variant_d) → engines (a/b/c) → RWA floor last
(the benchmark all others must beat). Within that, the RWA floor row is explicitly labelled.

stdlib only. LLM FORBIDDEN. Atomic writes (tmp + shutil.move).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.base import StrategyMetrics
from spa_core.strategy_lab.metrics import compare_table

# Display order: candidates first, baselines, benchmark (RWA floor) last.
_ORDER = (
    "variant_n", "variant_d", "eth_lst_neutral", "eth_lst_staking",
    "btc_neutral", "btc_lending_sleeve",
    "engine_a", "engine_b", "engine_c", "rwa_sleeve", "rwa_floor",
)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        shutil.move(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _to_metrics(d: dict) -> StrategyMetrics:
    """Rebuild a StrategyMetrics from the serialized per-strategy metrics dict so we can reuse
    metrics.compare_table for the core table."""
    return StrategyMetrics(
        net_apy_pct=d.get("net_apy_pct"),
        max_drawdown_pct=d.get("max_drawdown_pct"),
        sharpe=d.get("sharpe"),
        sortino=d.get("sortino"),
        volatility_pct=d.get("volatility_pct"),
        beta_to_eth=d.get("beta_to_eth"),
        funding_drag_pct=d.get("funding_drag_pct"),
        corr_to_stable_blend=d.get("corr_to_stable_blend"),
        tail_eth_down20_funding_flip_pct=d.get("tail_eth_down20_funding_flip_pct"),
        beats_rwa_floor=d.get("beats_rwa_floor"),
        extra=d.get("extra", {}),
    )


def _ordered_ids(strategies: Dict[str, dict]) -> List[str]:
    known = [sid for sid in _ORDER if sid in strategies]
    extra = [sid for sid in strategies if sid not in _ORDER]
    return known + sorted(extra)


def comparative_report(result: dict) -> str:
    """Render the backtest result into a markdown comparative report (string)."""
    manifest = result.get("manifest", {})
    strategies = result.get("strategies", {})
    warnings = result.get("window_warnings", []) or []
    kills = result.get("kills", {}) or {}

    floor = float(manifest.get("rwa_floor_apy_pct", 0.0))
    ids = _ordered_ids(strategies)

    lines: List[str] = []
    lines.append("# Strategy Lab — Comparative Backtest Report")
    lines.append("")
    lines.append(
        f"- **Window:** `{manifest.get('window_start')}` → `{manifest.get('window_end')}` "
        f"({manifest.get('n_snapshots')} snapshots)"
    )
    lines.append(f"- **Initial capital (ALL strategies):** ${manifest.get('initial_capital'):,.0f}")
    lines.append(f"- **RWA floor:** {floor:.2f}% APY (the row every strategy must beat)")
    lines.append(f"- **Seed:** {manifest.get('seed')}  ·  **Generated:** {manifest.get('generated_at')}")
    if manifest.get("injected_snapshots"):
        lines.append("- **Data:** injected synthetic snapshots (deterministic test path)")
    lines.append("")
    lines.append(f"> _Equal-capital note: {manifest.get('equal_capital_note', '')}_")
    lines.append("")

    # — window warnings (LOUD) —
    lines.append("## Window validation")
    if warnings:
        lines.append("")
        lines.append("⚠️ **WINDOW WARNINGS — the window under-tests one or more variants:**")
        lines.append("")
        for w in warnings:
            lines.append(f"- ⚠️ {w}")
    else:
        lines.append("")
        lines.append("✅ Window contains a notable ETH drawdown AND a funding flip to negative "
                     "— Variant D/N stress paths are exercised.")
    lines.append("")

    # — comparative table (reuse metrics.compare_table) —
    lines.append("## Comparative table (risk-adjusted, vs RWA floor)")
    lines.append("")
    metric_map = {sid: _to_metrics(strategies[sid]["metrics"]) for sid in ids}
    # compare_table iterates dict insertion order → already ordered by _ordered_ids.
    lines.append(compare_table(metric_map, floor_apy_pct=floor))
    lines.append("")
    lines.append(
        "_Columns: Net APY (annualised from equity), MaxDD (peak-to-trough), Sharpe, Sortino, "
        "annualised Vol, β to ETH (~0 neutral / ~1 directional), cumulative funding drag, "
        "correlation to the stable blend, tail P&L under ETH −20% + funding flip, and the "
        "risk-adjusted beats-RWA-floor decision. Rows flagged `⚠ below floor` do not clear the "
        "floor on a risk-adjusted basis._"
    )
    lines.append("")
    lines.append(f"_Benchmark row: `rwa_floor` ({floor:.2f}% APY, zero drawdown/vol)._")
    lines.append("")

    # — kill summary —
    lines.append("## Kill summary")
    lines.append("")
    if kills:
        for sid in ids:
            ev = kills.get(sid)
            if ev:
                lines.append(
                    f"- 🛑 **{sid}** killed on `{ev.get('date')}` — {ev.get('reason')} "
                    f"(equity at kill: ${ev.get('equity_at_kill'):,.2f})"
                )
    else:
        lines.append("- No strategy hit a kill condition in this window.")
    lines.append("")

    return "\n".join(lines)


def write_report(result: dict, path: str) -> str:
    """Atomically write the markdown report to `path`. Returns the path written."""
    text = comparative_report(result)
    _atomic_write_text(Path(path), text)
    return str(path)
