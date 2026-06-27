"""
spa_core/backtesting/acceptance_doc_generator.py

Generates the Owner Acceptance Document.
This is the formal document Yurii must review and sign before paper trading.

Generated document structure:
  # SPA Capital Owner Acceptance Document
  ## v1.0 | 2026-06-19

  ## 1. System Overview
  This document confirms that the owner (Yurii) has reviewed...

  ## 2. Strategy Summary
  RS-001 Anti-Crisis Strategy:
  - Target APY: 18.2% (RESEARCH phase)
  - Capital: $100,000 (initial)
  - Risk level: AGGRESSIVE (crypto-heavy)
  ...

  ## 3. Risk Disclosure
  ## 4. CPA Methodology Review
  ## 5. Gate Status Confirmation
  ## 6. Owner Signature

  ___________________________    _______________
  Signature                       Date

MP-1359 (v9.75) — stdlib only, atomic writes, no external dependencies.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional


# ── Constants ──────────────────────────────────────────────────────────────────

_VERSION = "v1.0"
_DOC_DATE = "2026-06-19"

_RISK_FACTORS = [
    ("Market Risk",         "Crypto price volatility can cause correlated drawdowns across strategy slots."),
    ("Liquidity Risk",      "Some positions may not exit within 24 hours without incurring >5% slippage."),
    ("Counterparty Risk",   "Protocol hack, rug pull, or admin-key exploit could result in permanent capital loss."),
    ("Smart Contract Risk", "Unaudited, recently deployed, or complex contracts carry elevated failure probability."),
    ("IL Risk",             "Impermanent loss (IL) for LP positions may erode nominal yield gains."),
    ("Source Quality Risk", "Strategies with no live historical data rely on model projections; actual returns may deviate."),
]

_CPA_NOTES = """
The Compounding Portfolio Analytics (CPA) methodology uses Point-In-Time (PIT) backtesting
to prevent look-ahead bias. Historical protocol APY data is only used as it would have been
available on each backtest date — no future data is incorporated.

Key methodology facts:
- **Cash drag**: 86.97% of the backtest period was spent in cash/USDC due to the conservative
  entry criteria of RS-001/RS-002. This is by design: the Anti-Crisis strategy holds cash
  during high-risk periods.
- **Look-ahead bias prevention**: PIT snapshots are taken at 00:00 UTC daily; no intra-day
  forward data is used.
- **Research exclusions**: Protocols with insufficient on-chain history (< 90 days at backtest
  start) are excluded from the strict strategy scope during the paper period.
- All results are paper/simulated; no real capital was deployed during the backtest phase.
"""


# ── Main class ─────────────────────────────────────────────────────────────────

class AcceptanceDocGenerator:
    """
    Generates the Owner Acceptance Document as a formal Markdown string.

    Usage::

        gen = AcceptanceDocGenerator(owner_name="Yurii", base_dir=".")
        doc = gen.generate()
        path = gen.save()
        print(f"Saved to: {path}")
    """

    def __init__(self, owner_name: str = "Yurii", base_dir: str = ".") -> None:
        """
        Args:
            owner_name: Display name of the owner.
            base_dir:   Repository root (used to locate data/ and docs/ directories).
        """
        self._owner = owner_name
        self._base_dir = Path(base_dir)

    # ── Sections ──────────────────────────────────────────────────────────────

    def system_overview_section(self) -> str:
        """Section 1: System overview."""
        return f"""## 1. System Overview

This document confirms that the owner ({self._owner}) has reviewed the SPA Capital
(Smart Passive Aggregator) automated yield-optimization system and accepts the terms
of the paper trading phase prior to any live capital deployment.

**System:** SPA Capital — Stablecoin Preservation Algorithm
**Version:** {_VERSION}
**Date:** {_DOC_DATE}
**Owner:** {self._owner}

SPA is an autonomous DeFi yield optimizer operating on virtual capital of **$100,000 USDC**.
Each daily cycle fetches live APY/TVL data from whitelisted protocols, runs strategies
S0–S10 through the Tournament evaluator, and rebalances the virtual portfolio subject to
the deterministic RiskPolicy (v1.0). No real funds are at risk during the paper period.

The system architecture:
- **Adapters (read-only):** Aave V3, Compound V3, Morpho Steakhouse, Morpho Blue,
  Yearn V3, Euler V2, Maple, Aave V3 Arbitrum, Pendle PT
- **Strategies (Tournament):** S0–S10, including S8 (Delta-Neutral sUSDe),
  S9 (E-Mode Looping), S10 (Pendle YT, advisory only per ADR-021)
- **RiskPolicy:** deterministic, version-locked at v1.0 for the entire paper period
- **GoLiveChecker:** 26 criteria; current status 16/26 PASS
- **Target go-live:** 2026-07-21 (ADR-002: 30 gap-free days + READY ≥ 7 days + manual review)

**LLM_FORBIDDEN_AGENTS policy:** LLM calls are prohibited in risk, execution, and
monitoring components. Prompt injection into capital decisions is a critical attack vector.
"""

    def strategy_summary_section(self) -> str:
        """Section 2: RS-001 + RS-002 summary."""
        return """## 2. Strategy Summary

### RS-001 — Anti-Crisis Strategy

| Parameter              | Value                            |
|------------------------|----------------------------------|
| Target APY             | 18.2% (RESEARCH phase estimate)  |
| Capital                | $100,000 USDC (initial, virtual) |
| Risk Level             | AGGRESSIVE (crypto-heavy)        |
| Phase                  | Paper Trading                    |
| Strategy Scope         | S0–S7 (strict); S8/S9 advisory   |

**Slot allocation (RS-001):**
- GMX BTC Exposure — 20%
- GMX ETH Exposure — 10%
- BTC Stable Pool — 35%
- ETH Aggressive Pool — 5%
- Gold Proxy — 15%
- Stablecoin T1 — 15%

The RS-001 Anti-Crisis strategy holds cash during elevated market-risk periods,
resulting in a measured **86.97% cash drag** in the PIT backtest (see §4).

---

### RS-002 — Cashflow Diversification Strategy

| Parameter              | Value                            |
|------------------------|----------------------------------|
| Target APY             | 20.0% (midpoint of 12–28% net range) |
| Capital                | Subset of $100,000 USDC virtual  |
| Risk Level             | MODERATE–AGGRESSIVE              |
| Phase                  | Paper Trading (advisory slots)   |

**Strategy purpose:** diversify yield sources beyond crypto-correlated slots,
incorporating stablecoin lending, liquid staking, and structured yield products.

---

### Tournament Evaluator (S0–S10)

All strategies compete daily via the Tournament evaluator using four metrics:
**Sharpe Ratio, Calmar Ratio, Ulcer Index, Rachev Ratio**. The winning
allocation is forwarded to `StrategyAllocator`, which enforces T1/T2 caps,
TVL floor ($5M minimum per pool), and the RiskPolicy gate before any
virtual rebalance trade is recorded.

> **Note:** S10 (Pendle YT) operates in T3-SPEC advisory mode per ADR-021.
> It generates signals but does not open positions automatically.
"""

    def risk_disclosure_section(self) -> str:
        """Section 3: Risk factors (6 types from research_risk_attribution)."""
        lines = ["## 3. Risk Disclosure\n"]
        lines.append(
            "The owner acknowledges the following six risk categories as defined in "
            "`spa_core/analytics/research_risk_attribution.py`:\n"
        )
        for i, (name, description) in enumerate(_RISK_FACTORS, 1):
            lines.append(f"### 3.{i} {name}\n")
            lines.append(f"{description}\n")

        lines.append(
            "\n> **Impermanent loss (IL)** is a non-recoverable loss that occurs when the "
            "relative price of assets in an LP position diverges from the entry price. "
            "IL is distinct from price risk and is not captured by simple APY metrics.\n"
        )
        lines.append(
            "\n**General disclaimer:** Paper trading uses virtual capital only. "
            "Historical backtest results do not guarantee future performance. "
            "RiskPolicy `approved=False` cannot be overridden by any agent or strategy. "
            "The 30-day gap-free paper track required by ADR-002 must be completed "
            "before any live trading decision.\n"
        )
        return "\n".join(lines)

    def cpa_methodology_section(self) -> str:
        """Section 4: PIT backtest, 86.97% cash drag, look-ahead bias explanation."""
        return f"""## 4. CPA Methodology Review
{_CPA_NOTES}
### Cash Drag Detail

The **86.97%** cash drag figure reflects that for ~87% of backtest trading days,
the RS-001 strategy held USDC rather than deploying to yield protocols. This is
intentional: the Anti-Crisis gating logic requires specific conditions (TVL health,
APY within 1–30% range, drawdown < 5%, T1/T2 cap compliance) before entering a position.

A high cash drag is NOT a defect — it demonstrates the RiskPolicy is functioning
correctly by withholding capital during sub-optimal conditions.

### Look-Ahead Bias Prevention

Each PIT backtest snapshot is constructed exclusively from data available at or before
the snapshot timestamp. The `pit_engine.py` module enforces this constraint. Protocol
APY feeds from DeFiLlama are cached with a 300-second TTL and labeled with their
retrieval timestamp, ensuring no future rates contaminate historical snapshots.

### Research Exclusions Scope

Protocols excluded from the strict paper period scope are listed in
`data/backtest/pre_paper_backtest_gate.json` under `research_exclusions`.
The owner explicitly acknowledges all listed exclusions by signing this document.
"""

    def gate_status_section(self) -> str:
        """Section 5: Current gate status."""
        golive_path = self._base_dir / "data" / "golive_status.json"
        gate_path = self._base_dir / "data" / "backtest" / "pre_paper_backtest_gate.json"

        # Try to load live gate data
        golive_pass = "16/26"
        golive_ready = "NOT READY"
        try:
            with open(golive_path, encoding="utf-8") as fh:
                gd = json.load(fh)
                passed = gd.get("passed", 0)
                total = gd.get("total", 26)
                golive_pass = f"{passed}/{total}"
                golive_ready = "READY" if gd.get("ready", False) else "NOT READY"
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

        pre_paper_status = "UNKNOWN"
        try:
            with open(gate_path, encoding="utf-8") as fh:
                gd = json.load(fh)
                pre_paper_status = gd.get("status", "UNKNOWN")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

        return f"""## 5. Gate Status Confirmation

The owner confirms awareness of the following gate statuses at time of signing:

| Gate                     | Status          | Notes                                   |
|--------------------------|-----------------|------------------------------------------|
| Pre-Paper Backtest Gate  | {pre_paper_status:<15} | `data/backtest/pre_paper_backtest_gate.json` |
| GoLiveChecker (26 criteria) | {golive_pass} {golive_ready} | `data/golive_status.json`       |
| Gap Monitor              | Active          | 30-day continuity required (ADR-002)     |
| RiskPolicy               | v1.0 LOCKED     | No changes permitted during paper period |
| ADR-002 Go-Live Rule     | IN PROGRESS     | Target: 2026-07-21                       |

### Backtest Gate Requirements

Before paper trading may begin, the Pre-Paper Backtest gate (`gate.py`) must show
status **PASS**. The gate validates:
1. Source pipeline readiness (`paper_test_can_be_designed = True`)
2. Minimum historical data coverage
3. RiskPolicy snapshot current and version-locked
4. Research exclusions acknowledged

### Pre-Paper Period Constraints

During the paper period:
- Strategy scope is restricted to the `strategy_scope` list in `owner_paper_acceptance.json`
- No live capital deployment without ADR-002 completion and manual Owner review
- All rebalances are virtual (`is_demo: false` flag is set; no on-chain transactions)
- Kill switch: portfolio drawdown ≥ 5% → all positions closed immediately
"""

    def signature_section(self) -> str:
        """Section 6: Signature block."""
        return f"""## 6. Owner Signature

By signing below, the owner ({self._owner}) confirms that they have:

1. ✅ Read and understood the System Overview (§1)
2. ✅ Reviewed the Strategy Summary for RS-001 and RS-002 (§2)
3. ✅ Acknowledged all six risk disclosure categories (§3)
4. ✅ Reviewed the CPA Methodology including the 86.97% cash drag explanation (§4)
5. ✅ Noted the current Gate Status and GoLiveChecker results (§5)
6. ✅ Understood that no real capital is at risk during the paper period
7. ✅ Understood that `RiskPolicy approved=False` cannot be overridden
8. ✅ Accepted that ADR-002 requires 30 gap-free paper days before live trading
9. ✅ Confirmed awareness of the LLM_FORBIDDEN_AGENTS policy
10. ✅ Agreed that any material strategy scope change requires re-signing

---

**Signing date:** {_DOC_DATE}

&nbsp;

___________________________    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;    _______________
**Signature**                  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;    **Date**

&nbsp;

___________________________
**Printed Name: {self._owner}**

&nbsp;

> *This document is generated by `spa_core/backtesting/acceptance_doc_generator.py`.*
> *It is a reference document; the binding acceptance record is stored in*
> *`data/backtest/owner_paper_acceptance.json` (written by `owner_acceptance.py`).*
> *Document version: {_VERSION} | Generated: {date.today().isoformat()}*
"""

    # ── Composite methods ──────────────────────────────────────────────────────

    def generate(self) -> str:
        """Full document as Markdown string."""
        header = (
            f"# SPA Capital Owner Acceptance Document\n\n"
            f"## {_VERSION} | {_DOC_DATE}\n\n"
            f"---\n\n"
        )
        sections = [
            self.system_overview_section(),
            self.strategy_summary_section(),
            self.risk_disclosure_section(),
            self.cpa_methodology_section(),
            self.gate_status_section(),
            self.signature_section(),
        ]
        return header + "\n---\n\n".join(sections)

    def save(self, output_path: Optional[str] = None) -> str:
        """
        Saves the document to docs/OWNER_ACCEPTANCE_DOCUMENT.md atomically.

        Args:
            output_path: Override destination path. Defaults to
                         ``<base_dir>/docs/OWNER_ACCEPTANCE_DOCUMENT.md``.

        Returns:
            Absolute path to the saved file.
        """
        if output_path is None:
            dest = self._base_dir / "docs" / "OWNER_ACCEPTANCE_DOCUMENT.md"
        else:
            dest = Path(output_path)

        dest.parent.mkdir(parents=True, exist_ok=True)
        content = self.generate()

        tmp = dest.with_suffix(".md.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(dest))

        return str(dest.resolve())


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Owner Acceptance Document",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--owner", default="Yurii", help="Owner name")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--output", default=None, help="Override output path")
    parser.add_argument("--print", action="store_true", help="Print to stdout instead of saving")
    args = parser.parse_args()

    gen = AcceptanceDocGenerator(owner_name=args.owner, base_dir=args.base_dir)
    if args.print:
        print(gen.generate())
    else:
        path = gen.save(output_path=args.output)
        print(f"Saved: {path}")
