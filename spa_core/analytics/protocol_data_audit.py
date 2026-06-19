"""
spa_core/analytics/protocol_data_audit.py

Comprehensive audit of protocol data availability across all strategies.

Analyzes:
  1. Which protocols are in production strategies (S0-S19)
  2. Which protocols are in research strategies (S20-S21)
  3. Data quality for each protocol (CLEAN/PENDING/RESEARCH/NEEDED)
  4. Priority score for data acquisition

Priority formula:
  base_priority = sum of weights across all strategies where protocol appears
  priority_boost = +5 if RESEARCH strategy, +10 if PRODUCTION strategy
                   (cumulative: add per each strategy the protocol appears in)
  data_gap_penalty = +20 if SOURCE_NEEDED (high priority to fix)
  final_priority = base_priority * priority_boost + data_gap_penalty

Output:
  {
    "by_protocol": {
      "aave_v3_usdc": {
        "source_state": "CLEAN_INCLUDED",
        "strategies": ["S3"],
        "total_weight_across_strategies": 0.15,
        "priority_score": 1.5,
        "action_needed": None
      },
      "gmx_btc_exposure": {
        "source_state": "SOURCE_NEEDED",
        "strategies": ["S20"],
        "total_weight_across_strategies": 0.20,
        "priority_score": 21.0,
        "action_needed": "Find DeFiLlama pool ID for GMX v2 BTC/USDC on Arbitrum"
      }
    },
    "summary": {
      "total_protocols": N,
      "clean": N,
      "pending": N,
      "research_only": N,
      "source_needed": N,
      "acquisition_backlog": N,
    },
    "top_10_priorities": [...],
    "estimated_days_to_full_coverage": 180
  }

Stdlib only. LLM FORBIDDEN. Atomic writes: mkstemp + os.replace.
Date: 2026-06-19 (MP-1331, Sprint v9.47)
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.base import BaseAnalytics

# ─── Source state constants ───────────────────────────────────────────────────

# Local fallback (avoids hard import dependency for standalone runs)
class _FallbackSourceState:
    CLEAN_INCLUDED = "clean_included"
    PENDING        = "pending"
    RESEARCH_ONLY  = "research_only"
    MANUAL_PROXY   = "manual_proxy"
    REVIEW         = "review"
    SOURCE_NEEDED  = "source_needed"


try:
    from spa_core.backtesting.source_pipeline import SourceState
except Exception:  # pragma: no cover — import path varies by run context
    SourceState = _FallbackSourceState  # type: ignore[assignment]

# ─── Static protocol registry ─────────────────────────────────────────────────
# Keyed by protocol_id used across strategies and the source pipeline.
# Fields: state (SourceState constant), placeholder_apy (%), action (str|None),
#         effort ("LOW"|"MEDIUM"|"HIGH")

_PROTOCOL_REGISTRY: Dict[str, dict] = {
    # ── CLEAN_INCLUDED — strict-backtest eligible ─────────────────────────────
    "aave_v2_usdc":        {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 3.0,
        "action": None, "effort": "LOW",
    },
    "compound_v2_usdc":    {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 3.5,
        "action": None, "effort": "LOW",
    },
    "aave_v3_usdc":        {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 3.5,
        "action": None, "effort": "LOW",
    },
    "compound_v3_usdc":    {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 4.8,
        "action": None, "effort": "LOW",
    },
    "aave_v3_base":        {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 4.5,
        "action": None, "effort": "LOW",
    },
    "morpho_blue":         {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 6.5,
        "action": None, "effort": "LOW",
    },
    "sky_susds":           {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 5.0,
        "action": None, "effort": "LOW",
    },
    "sfrax":               {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 5.2,
        "action": None, "effort": "LOW",
    },
    # Strategy-level aliases → map to clean sources
    "aave_mainnet":        {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 3.2,
        "action": None, "effort": "LOW",
    },
    "compound_v3":         {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 4.8,
        "action": None, "effort": "LOW",
    },
    "spark_susds":         {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 5.5,
        "action": None, "effort": "LOW",
    },
    "aave_arbitrum":       {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 4.6,
        "action": None, "effort": "LOW",
    },
    "sdai":                {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 5.0,
        "action": None, "effort": "LOW",
    },
    "stablecoin_t1":       {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 3.5,
        "action": None, "effort": "LOW",
    },
    "stablecoin_deposit":  {
        "state": SourceState.CLEAN_INCLUDED, "placeholder_apy": 4.0,
        "action": None, "effort": "LOW",
    },
    # ── PENDING — under review, excluded from strict ───────────────────────────
    "morpho_steakhouse":   {
        "state": SourceState.PENDING, "placeholder_apy": 6.5,
        "action": "Complete pending review of Morpho Steakhouse vault; promote to clean_included",
        "effort": "LOW",
    },
    "morpho_blue_base":    {
        "state": SourceState.PENDING, "placeholder_apy": 6.2,
        "action": "Verify Morpho Blue Base chain APY feed; promote to clean_included",
        "effort": "LOW",
    },
    "yearn_v3_yvusdc":     {
        "state": SourceState.PENDING, "placeholder_apy": 5.8,
        "action": "Review Yearn V3 yvUSDC APY feed accuracy; promote or reject",
        "effort": "MEDIUM",
    },
    "euler_v2_usdc":       {
        "state": SourceState.PENDING, "placeholder_apy": 5.5,
        "action": "Audit Euler V2 USDC pool; verify point-in-time data",
        "effort": "MEDIUM",
    },
    "wusdm":               {
        "state": SourceState.PENDING, "placeholder_apy": 5.0,
        "action": "Verify wUSDM source and APY data; promote or reject",
        "effort": "LOW",
    },
    "fluid_fusdc":         {
        "state": SourceState.PENDING, "placeholder_apy": 6.5,
        "action": "Find DeFiLlama pool ID for Fluid fUSDC; add adapter",
        "effort": "LOW",
    },
    # ── REVIEW — needs owner/analyst verification ─────────────────────────────
    "maple_syrupusdc":     {
        "state": SourceState.REVIEW, "placeholder_apy": 8.0,
        "action": "Owner review required: Maple syrupUSDC credit risk terms",
        "effort": "HIGH",
    },
    # ── MANUAL_PROXY — proxy exists, not clean point-in-time ──────────────────
    "pendle_pt_susde":     {
        "state": SourceState.MANUAL_PROXY, "placeholder_apy": 8.5,
        "action": "Replace MANUAL_PROXY with direct DeFiLlama Pendle PT historical series",
        "effort": "MEDIUM",
    },
    "pendle_pt":           {
        "state": SourceState.MANUAL_PROXY, "placeholder_apy": 8.5,
        "action": "Replace proxy APY with direct DeFiLlama Pendle PT pool data",
        "effort": "MEDIUM",
    },
    "ethena_usde":         {
        "state": SourceState.MANUAL_PROXY, "placeholder_apy": 12.0,
        "action": "Replace proxy with direct Ethena sUSDe historical APY feed",
        "effort": "MEDIUM",
    },
    # ── RESEARCH_ONLY — modeled/estimated, no clean history ───────────────────
    "delta_neutral":       {
        "state": SourceState.RESEARCH_ONLY, "placeholder_apy": 27.5,
        "action": "Build point-in-time APY series for delta-neutral sUSDe strategy",
        "effort": "HIGH",
    },
    # ── SOURCE_NEEDED — no data source connected yet ──────────────────────────
    "btc_yield":           {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 4.0,
        "action": "Specify BTC yield source (Babylon/tBTC lending); add APY feed",
        "effort": "HIGH",
    },
    "eth_staking":         {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 3.5,
        "action": "Map to ETH staking rate; add Lido or Rocket Pool DeFiLlama feed",
        "effort": "MEDIUM",
    },
    "gmx_btc":             {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 15.0,
        "action": "Find DeFiLlama pool ID for GMX v2 BTC/USD pool on Arbitrum",
        "effort": "LOW",
    },
    "gmx_eth":             {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 15.0,
        "action": "Find DeFiLlama pool ID for GMX v2 ETH/USD pool on Arbitrum",
        "effort": "LOW",
    },
    "gold_proxy":          {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 15.0,
        "action": "Confirm product identity (PAXG or synthetic gold); find APY source",
        "effort": "HIGH",
    },
    "btc_stable_pool":     {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 25.0,
        "action": "Specify venue (e.g., Curve BTC pool); find DeFiLlama pool slug",
        "effort": "MEDIUM",
    },
    "btc_usd_conc_liq":    {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 40.0,
        "action": "Identify venue (Uniswap V3/Aerodrome BTC/USD) and DeFiLlama pool ID",
        "effort": "MEDIUM",
    },
    "rwa_conc_liq":        {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 18.0,
        "action": "Specify RWA venue and product; find DeFiLlama yield pool",
        "effort": "HIGH",
    },
    "trader_losses_vault": {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 20.0,
        "action": "Map to GMX GLP or Hyperliquid vault; find historical PnL series",
        "effort": "HIGH",
    },
    "pendle_yt":           {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 28.0,
        "action": "Map Pendle YT token to DeFiLlama pool; verify point-in-time APY series",
        "effort": "MEDIUM",
    },
    "gmx_btc_exposure":    {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 15.0,
        "action": "Find DeFiLlama pool ID for GMX v2 BTC/USDC on Arbitrum",
        "effort": "LOW",
    },
    "gmx_eth_exposure":    {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 15.0,
        "action": "Find DeFiLlama pool ID for GMX v2 ETH/USDC on Arbitrum",
        "effort": "LOW",
    },
    "eth_aggressive_pool": {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 45.0,
        "action": "Specify pool (e.g., Convex/Curve ETH); find DeFiLlama yield source",
        "effort": "HIGH",
    },
    "radiant_arbitrum":    {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 8.0,
        "action": "Find DeFiLlama pool ID for Radiant USDC on Arbitrum",
        "effort": "LOW",
    },
    "aave_v3_polygon":     {
        "state": SourceState.SOURCE_NEEDED, "placeholder_apy": 5.1,
        "action": "Find DeFiLlama pool ID for Aave V3 USDC on Polygon",
        "effort": "LOW",
    },
}

# ─── Strategy-protocol appearances ───────────────────────────────────────────
# Each entry: (strategy_id, weight_in_strategy, is_research_strategy)
# Production = S0-S19 (is_research=False), Research = S20-S21 (is_research=True)

_STRATEGY_APPEARANCES: Dict[str, List[Tuple[str, float, bool]]] = {
    # ── Legacy / standalone (no current active strategy) ──────────────────────
    "aave_v2_usdc":        [],
    "compound_v2_usdc":    [],
    "compound_v3_usdc":    [],  # covered by "compound_v3" alias
    "sky_susds":           [],  # covered by "spark_susds" alias
    "pendle_pt_susde":     [],  # covered by "pendle_pt" alias
    "yearn_v3_yvusdc":     [],
    "euler_v2_usdc":       [],
    "maple_syrupusdc":     [],
    "btc_yield":           [],
    "eth_staking":         [],
    "gmx_btc":             [],  # source ID variant (not strategy-level)
    "gmx_eth":             [],  # source ID variant
    # ── Production strategies (S0-S19) ───────────────────────────────────────
    # S2 (Pendle-Morpho): pendle_pt / morpho_steakhouse / compound_v3
    "pendle_pt":           [
        ("S2",  0.50, False),
        ("S5",  0.65, False),
        ("S6",  0.40, False),
        ("S7",  0.35, False),
    ],
    "morpho_steakhouse":   [
        ("S2",  0.35, False),
        ("S3",  0.30, False),
        ("S4",  0.15, False),
        ("S5",  0.25, False),
        ("S6",  0.30, False),
        ("S7",  0.20, False),
        ("S14", 0.20, False),
    ],
    "compound_v3":         [
        ("S2",  0.15, False),
        ("S5",  0.10, False),
        ("S6",  0.10, False),
        ("S7",  0.05, False),
        ("S13", 0.30, False),
        ("S18", 0.30, False),
    ],
    # S3 (Aave-Arb-Morpho): aave_arbitrum / morpho_steakhouse / aave_mainnet
    "aave_arbitrum":       [
        ("S3",  0.55, False),
        ("S6",  0.05, False),
        ("S14", 0.45, False),
    ],
    "aave_mainnet":        [("S3", 0.15, False)],
    "aave_v3_usdc":        [("S3", 0.15, False)],  # explicit alias used in some strategies
    # S4 (Spark-Fluid): spark_susds / fluid_fusdc / morpho_steakhouse
    "spark_susds":         [("S4", 0.60, False)],
    "fluid_fusdc":         [("S4", 0.25, False), ("S6", 0.15, False)],
    # S7 (Pendle-YT-Aggressive): pendle_yt added to production
    "pendle_yt":           [("S7", 0.40, False)],
    # S8 (Delta-Neutral sUSDe): delta_neutral / ethena_usde
    "delta_neutral":       [("S8", 0.80, False)],
    "ethena_usde":         [("S8", 0.20, False)],
    # S12 (Base Layer Yield): morpho_blue_base / aave_v3_base
    "morpho_blue_base":    [("S12", 0.50, False), ("S13", 0.25, False)],
    "aave_v3_base":        [("S12", 0.30, False), ("S13", 0.25, False)],
    # S13 (Multi-Chain Arb): aave_v3 / compound_v3 / morpho_blue (ETH) + Base
    "morpho_blue":         [("S13", 0.30, False)],
    # S14 (Arbitrum Radiant): aave_arbitrum / radiant_arbitrum / morpho_steakhouse
    "radiant_arbitrum":    [("S14", 0.35, False)],
    # S17 (Polygon): aave_v3_polygon
    "aave_v3_polygon":     [("S17", 0.60, False)],
    # S18 (High-Yield T2): compound_v3 / sfrax / sdai / wusdm
    "sfrax":               [("S18", 0.35, False)],
    "sdai":                [("S18", 0.25, False)],
    "wusdm":               [("S18", 0.10, False)],
    # ── Research strategies (S20-S21) ────────────────────────────────────────
    # S20 (RS-001 Anti-Crisis Research)
    "gmx_btc_exposure":    [("S20", 0.20, True)],
    "gmx_eth_exposure":    [("S20", 0.10, True)],
    "btc_stable_pool":     [("S20", 0.35, True)],
    "eth_aggressive_pool": [("S20", 0.05, True)],
    "gold_proxy":          [("S20", 0.15, True)],
    "stablecoin_t1":       [("S20", 0.15, True)],
    # S21 (RS-002 Cashflow Research)
    "btc_usd_conc_liq":    [("S21", 0.60, True)],
    "rwa_conc_liq":        [("S21", 0.10, True)],
    "trader_losses_vault": [("S21", 0.14, True)],
    "stablecoin_deposit":  [("S21", 0.16, True)],
}

# ─── Effort → days mapping ────────────────────────────────────────────────────

_EFFORT_DAYS: Dict[str, int] = {"LOW": 7, "MEDIUM": 14, "HIGH": 21}


# ══════════════════════════════════════════════════════════════════════════════
# ProtocolDataAudit
# ══════════════════════════════════════════════════════════════════════════════

class ProtocolDataAudit(BaseAnalytics):
    """
    Audits protocol data availability across all SPA strategies.

    Usage:
        audit = ProtocolDataAudit()
        result = audit.run_audit()
        audit.save()
        print(audit.to_markdown())
    """

    OUTPUT_PATH = "data/research/protocol_data_audit.json"

    def __init__(self, base_dir: str = ".") -> None:
        super().__init__(base_dir)
        self._base_dir = base_dir
        self._audit_result: Optional[dict] = None

    def to_dict(self) -> dict:
        """Returns last audit result as JSON-serializable dict."""
        return dict(self._audit_result) if self._audit_result else {}

    # ── Priority computation ──────────────────────────────────────────────────

    def priority_score(self, protocol_id: str) -> float:
        """
        Priority score for data acquisition.

        formula:
          base = sum(weight for each strategy appearance)
          boost = sum(5 if research else 10 for each strategy appearance)
          penalty = 20 if SOURCE_NEEDED else 0
          final = base * boost + penalty
        """
        appearances = _STRATEGY_APPEARANCES.get(protocol_id, [])
        base = sum(w for _, w, _ in appearances)
        boost = sum(5 if is_res else 10 for _, _, is_res in appearances)
        state = _PROTOCOL_REGISTRY.get(protocol_id, {}).get("state", "")
        penalty = 20.0 if state == SourceState.SOURCE_NEEDED else 0.0
        raw = base * boost + penalty
        return round(raw, 4)

    # ── Full audit ────────────────────────────────────────────────────────────

    def run_audit(self) -> dict:
        """Runs full audit across all strategies. Returns structured audit dict."""
        by_protocol: dict = {}

        for protocol_id, reg in _PROTOCOL_REGISTRY.items():
            appearances = _STRATEGY_APPEARANCES.get(protocol_id, [])
            strategies = [sid for sid, _, _ in appearances]
            total_weight = round(sum(w for _, w, _ in appearances), 4)
            state = reg["state"]
            score = self.priority_score(protocol_id)

            by_protocol[protocol_id] = {
                "source_state": state.upper(),          # e.g. "CLEAN_INCLUDED"
                "strategies": strategies,
                "total_weight_across_strategies": total_weight,
                "priority_score": score,
                "action_needed": reg["action"],
            }

        # ── State counts ──────────────────────────────────────────────────────
        state_counts: Dict[str, int] = {}
        for entry in by_protocol.values():
            s = entry["source_state"]
            state_counts[s] = state_counts.get(s, 0) + 1

        clean_n    = state_counts.get("CLEAN_INCLUDED", 0)
        pending_n  = (state_counts.get("PENDING", 0)
                      + state_counts.get("REVIEW", 0)
                      + state_counts.get("MANUAL_PROXY", 0))
        research_n = state_counts.get("RESEARCH_ONLY", 0)
        needed_n   = state_counts.get("SOURCE_NEEDED", 0)
        backlog_n  = pending_n + research_n + needed_n
        total_n    = len(by_protocol)

        summary = {
            "total_protocols":    total_n,
            "clean":              clean_n,
            "pending":            pending_n,
            "research_only":      research_n,
            "source_needed":      needed_n,
            "acquisition_backlog": backlog_n,
        }

        # ── Top 10 by priority score ──────────────────────────────────────────
        sorted_entries = sorted(
            by_protocol.items(),
            key=lambda kv: kv[1]["priority_score"],
            reverse=True,
        )[:10]

        top_10: List[dict] = [
            {
                "protocol_id":   pid,
                "source_state":  data["source_state"],
                "priority_score": data["priority_score"],
                "strategies":    data["strategies"],
                "action_needed": data["action_needed"],
            }
            for pid, data in sorted_entries
        ]

        # ── Estimated days to full data coverage ──────────────────────────────
        days = sum(
            _EFFORT_DAYS.get(reg["effort"], 14)
            for reg in _PROTOCOL_REGISTRY.values()
            if reg["state"] == SourceState.SOURCE_NEEDED
        )
        estimated_days = min(days, 365)

        result = {
            "by_protocol":                    by_protocol,
            "summary":                        summary,
            "top_10_priorities":              top_10,
            "estimated_days_to_full_coverage": estimated_days,
            "generated_at":                   datetime.now(timezone.utc).isoformat(),
        }
        self._audit_result = result
        return result

    # ── top_priorities convenience ────────────────────────────────────────────

    def top_priorities(self, n: int = 10) -> List[dict]:
        """Top N protocols by priority score."""
        result = self._audit_result or self.run_audit()
        return result["top_10_priorities"][:n]

    # ── Acquisition roadmap ───────────────────────────────────────────────────

    def acquisition_roadmap(self) -> List[dict]:
        """
        Ordered list of data acquisition tasks — only protocols that need work.

        Returns:
          [
            {
              "priority": 1,
              "protocol_id": str,
              "action": str,
              "effort": "LOW" | "MEDIUM" | "HIGH",
              "impact": float,  # APY unlocked (placeholder_apy) if done
            },
            ...
          ]
        """
        _SKIP_STATES = {
            SourceState.CLEAN_INCLUDED.upper(),  # "CLEAN_INCLUDED"
        }
        result = self._audit_result or self.run_audit()

        actionable = [
            (pid, data)
            for pid, data in result["by_protocol"].items()
            if data["source_state"] not in _SKIP_STATES
               and data["action_needed"] is not None
        ]

        # Sort by priority_score descending
        actionable.sort(key=lambda x: x[1]["priority_score"], reverse=True)

        roadmap: List[dict] = []
        for rank, (pid, data) in enumerate(actionable, start=1):
            reg = _PROTOCOL_REGISTRY.get(pid, {})
            roadmap.append({
                "priority":    rank,
                "protocol_id": pid,
                "action":      data["action_needed"],
                "effort":      reg.get("effort", "MEDIUM"),
                "impact":      float(reg.get("placeholder_apy", 0.0)),
            })
        return roadmap

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str = "data/research/protocol_data_audit.json") -> None:
        """Atomic save to path (mkstemp + os.replace)."""
        result = self._audit_result or self.run_audit()

        # Resolve relative to base_dir
        target = Path(self._base_dir) / path if not Path(path).is_absolute() else Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            dir=str(target.parent), prefix=".tmp_protocol_audit_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(target))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── Markdown report ───────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """Formatted audit report as Markdown string."""
        result = self._audit_result or self.run_audit()
        summary = result["summary"]
        top_10  = result["top_10_priorities"]
        roadmap = self.acquisition_roadmap()

        lines: List[str] = [
            "# Protocol Data Audit Report",
            "",
            f"**Generated:** {result.get('generated_at', 'N/A')}",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|---|---|",
            f"| Total protocols audited | {summary['total_protocols']} |",
            f"| Clean (strict-eligible) | {summary['clean']} |",
            f"| Pending / Review / Proxy | {summary['pending']} |",
            f"| Research-only | {summary['research_only']} |",
            f"| Source needed | {summary['source_needed']} |",
            f"| Acquisition backlog | {summary['acquisition_backlog']} |",
            f"| Estimated days to full coverage | {result['estimated_days_to_full_coverage']} |",
            "",
            "## Top 10 Priority Protocols",
            "",
            "| # | Protocol | State | Score | Strategies | Action |",
            "|---|---|---|---|---|---|",
        ]
        for i, entry in enumerate(top_10, 1):
            strats = ", ".join(entry["strategies"]) if entry["strategies"] else "—"
            action = entry["action_needed"] or "—"
            lines.append(
                f"| {i} | `{entry['protocol_id']}` | {entry['source_state']} "
                f"| {entry['priority_score']:.1f} | {strats} | {action} |"
            )

        lines += [
            "",
            "## Acquisition Roadmap",
            "",
            "| Priority | Protocol | Effort | Impact (APY%) | Action |",
            "|---|---|---|---|---|",
        ]
        for item in roadmap:
            lines.append(
                f"| {item['priority']} | `{item['protocol_id']}` "
                f"| {item['effort']} | {item['impact']:.1f}% | {item['action']} |"
            )

        lines += [
            "",
            "## Protocol Detail",
            "",
            "| Protocol | State | Strategies | Weight | Score |",
            "|---|---|---|---|---|",
        ]
        by_p = result["by_protocol"]
        for pid in sorted(by_p.keys()):
            entry = by_p[pid]
            strats = ", ".join(entry["strategies"]) if entry["strategies"] else "—"
            lines.append(
                f"| `{pid}` | {entry['source_state']} "
                f"| {strats} | {entry['total_weight_across_strategies']:.4f} "
                f"| {entry['priority_score']:.2f} |"
            )

        return "\n".join(lines)


# ─── CLI entrypoint ───────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Protocol data audit — MP-1331"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Run audit and save to data/research/protocol_data_audit.json"
    )
    parser.add_argument(
        "--check", action="store_true", default=True,
        help="Run audit and print summary (default)"
    )
    parser.add_argument("--data-dir", default=".", help="Base directory")
    args = parser.parse_args()

    audit = ProtocolDataAudit(base_dir=args.data_dir)
    result = audit.run_audit()
    summary = result["summary"]

    print("Protocol Data Audit — MP-1331 (v9.47)")
    print(f"  Total protocols : {summary['total_protocols']}")
    print(f"  Clean           : {summary['clean']}")
    print(f"  Pending/Review  : {summary['pending']}")
    print(f"  Research-only   : {summary['research_only']}")
    print(f"  Source needed   : {summary['source_needed']}")
    print(f"  Acq. backlog    : {summary['acquisition_backlog']}")
    print(f"  Est. coverage   : {result['estimated_days_to_full_coverage']} days")
    print()
    print("Top 5 priorities:")
    for entry in result["top_10_priorities"][:5]:
        print(
            f"  [{entry['source_state'][:10]:10s}] "
            f"{entry['protocol_id']:25s}  score={entry['priority_score']:.1f}"
        )

    if args.run:
        audit.save(path="data/research/protocol_data_audit.json")
        print("\nSaved → data/research/protocol_data_audit.json")


if __name__ == "__main__":
    main()
