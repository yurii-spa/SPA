"""
spa_core/analytics/investment_memo_generator.py

Generates the SPA Investment Memo — a public-facing document for Family Fund investors.

Sections:
  1. Executive Summary (180 words max)
  2. Strategy Overview
  3. Historical Performance (PIT backtest, honest about cash drag)
  4. Risk Factors
  5. Fee Structure (1.5% management, 20% performance — configurable)
  6. Minimum Investment & Terms
  7. Process & Timeline
  8. Contact

MP-1360 (v9.76) — stdlib only, atomic writes, no external dependencies.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Tuple

from spa_core.base import BaseAnalytics


# ── Configuration dataclass ───────────────────────────────────────────────────

@dataclass
class InvestmentMemoConfig:
    """
    Configuration for fee structure and investment terms.

    All fields are overridable; defaults reflect the Family Fund baseline.
    """
    mgmt_fee_pct: float = 1.5
    perf_fee_pct: float = 20.0
    min_investment_usd: float = 10_000.0
    lock_up_days: int = 90
    strategy_name: str = "SPA (Stablecoin Preservation Algorithm)"
    target_apy_range: Tuple[float, float] = field(default_factory=lambda: (8.0, 25.0))


# ── Main class ────────────────────────────────────────────────────────────────

class InvestmentMemoGenerator(BaseAnalytics):
    """
    Generates a professional investment memo in Markdown format.

    Intended audience: potential Family Fund investors who need a clear,
    plain-language overview of SPA's strategy, performance, and terms.

    Usage::

        config = InvestmentMemoConfig(mgmt_fee_pct=1.5, perf_fee_pct=20.0)
        gen = InvestmentMemoGenerator(config=config, base_dir=".")
        doc = gen.generate()
        path = gen.save()
    """

    OUTPUT_PATH = "docs/INVESTMENT_MEMO.md"

    def __init__(
        self,
        config: Optional[InvestmentMemoConfig] = None,
        base_dir: str = ".",
    ) -> None:
        """
        Args:
            config:   Fee and terms configuration. Defaults to InvestmentMemoConfig().
            base_dir: Repository root (for locating the docs/ output directory).
        """
        super().__init__(base_dir)
        self._config = config if config is not None else InvestmentMemoConfig()
        self._base_dir = Path(base_dir)
        self._doc_date = date.today().isoformat()

    def to_dict(self) -> dict:
        """Returns memo metadata as JSON-serializable dict."""
        return {
            "doc_date": self._doc_date,
            "mgmt_fee_pct": self._config.mgmt_fee_pct,
            "perf_fee_pct": self._config.perf_fee_pct,
            "output_path": self.OUTPUT_PATH,
        }

    # ── Sections ──────────────────────────────────────────────────────────────

    def executive_summary(self) -> str:
        """
        180 words max executive summary of SPA for Family Fund investors.
        """
        cfg = self._config
        apy_low, apy_high = cfg.target_apy_range
        return (
            f"## 1. Executive Summary\n\n"
            f"SPA Capital manages a diversified stablecoin yield strategy "
            f"targeting **{apy_low:.0f}–{apy_high:.0f}% net APY** for qualified investors. "
            f"The fund deploys capital across audited DeFi lending protocols "
            f"(Aave, Compound, Morpho) and selectively captures structured yield "
            f"through stablecoin liquidity pools and liquid-staking instruments.\n\n"
            f"The strategy is designed for capital preservation first and yield "
            f"optimisation second. A deterministic risk policy gates every allocation: "
            f"minimum pool TVL of $5M, per-protocol concentration limits, and an "
            f"automatic kill-switch that closes all positions if portfolio drawdown "
            f"reaches 5%. No LLM or AI model is permitted in risk or execution "
            f"decisions — all rules are hard-coded and auditable.\n\n"
            f"SPA is currently in a **paper-trading phase** using $100,000 USDC "
            f"of virtual capital to build a verified 30-day track record before "
            f"any investor capital is accepted. Management fee: {cfg.mgmt_fee_pct}%. "
            f"Performance fee: {cfg.perf_fee_pct:.0f}% above hurdle. "
            f"Minimum investment: ${cfg.min_investment_usd:,.0f}. "
            f"Lock-up period: {cfg.lock_up_days} days."
        )

    def strategy_overview(self) -> str:
        """RS-001/RS-002 in plain language (no jargon)."""
        return (
            "## 2. Strategy Overview\n\n"
            "SPA deploys two complementary strategies across major stablecoin protocols:\n\n"
            "### RS-001 — Anti-Crisis / Capital Preservation\n\n"
            "This strategy holds USD-denominated stablecoins in lending markets "
            "during calm periods and moves to cash during elevated-risk conditions. "
            "Think of it as a money-market fund that actively avoids stress events. "
            "It targets approximately 18% annualised return during deployed periods, "
            "but spends significant time in cash when conditions are unfavourable "
            "(see Historical Performance §3 for cash drag details).\n\n"
            "**Eligible protocols:** Aave V3 (Ethereum and Arbitrum), "
            "Compound V3, Morpho Steakhouse. All protocols are T1-tier — "
            "large, audited, long-lived lending markets with a combined TVL of "
            "several billion dollars.\n\n"
            "### RS-002 — Cashflow Diversification\n\n"
            "This strategy broadens the yield base by adding structured stablecoin "
            "products and selective liquid-staking exposure. It targets a net yield "
            "range of 12–28%, depending on market conditions.\n\n"
            "Both strategies run simultaneously in the Tournament system, which "
            "competes S0–S10 strategy variants daily and allocates capital to the "
            "highest risk-adjusted performer. All trades are gated by the same "
            "deterministic RiskPolicy before execution.\n\n"
            "**What SPA does NOT do:**\n"
            "- No leverage trading or derivatives speculation\n"
            "- No algorithmic token swaps (yield only from lending/LP fees)\n"
            "- No assets outside of established stablecoin and liquid-staking categories\n"
            "- No discretionary overrides of the risk policy\n"
        )

    def historical_performance(self) -> str:
        """Honest: shows PIT backtest with 86.97% cash drag noted."""
        return (
            "## 3. Historical Performance\n\n"
            "> **Important:** All figures below are from a simulated Point-In-Time (PIT) "
            "backtest. No real capital has been deployed. Past simulated performance "
            "does not guarantee future results.\n\n"
            "### Backtest Methodology\n\n"
            "The PIT backtest reconstructs what the strategy would have done "
            "on each historical date using only data available at that date. "
            "This prevents 'look-ahead bias' — a common flaw where backtests "
            "use future information to inflate historical returns.\n\n"
            "### Key Results\n\n"
            "| Metric                 | RS-001         | RS-002         |\n"
            "|------------------------|----------------|----------------|\n"
            "| Gross Backtest APY     | ~18.2%         | ~20.0%         |\n"
            "| Cash Drag              | **86.97%**     | ~60–70%        |\n"
            "| Net Deployed APY       | ~18.2%*        | ~20.0%*        |\n"
            "| Max Drawdown           | < 5% (gate)    | < 5% (gate)    |\n"
            "\n"
            "*Net deployed APY applies only to periods when capital was not in cash.\n\n"
            "### Understanding the 86% Cash Drag\n\n"
            "The RS-001 strategy held cash (USDC) for **86.97%** of backtest days. "
            "This is by design: when the risk policy cannot find a pool that meets "
            "all criteria (TVL ≥ $5M, APY 1–30%, drawdown < 5%), the strategy "
            "stays flat rather than taking a bad trade.\n\n"
            "In plain terms: the strategy earned its target rate during the 13% "
            "of the time it was deployed, and earned ~0% (stablecoin rate) "
            "the rest of the time. The effective portfolio-level APY is therefore "
            "lower than 18.2%. We report this figure transparently rather than "
            "showing only the deployed-period rate.\n\n"
            "### Current Paper Track\n\n"
            "Paper trading with $100,000 virtual USDC began 2026-06-10. "
            "A minimum of 30 consecutive gap-free days is required before "
            "accepting investor capital (ADR-002). Equity curve data is "
            "available on request from the owner.\n"
        )

    def risk_factors(self) -> str:
        """Plain language risks: smart contract, IL, market, liquidity."""
        return (
            "## 4. Risk Factors\n\n"
            "Investing in DeFi yield strategies carries risks that differ from "
            "traditional fixed-income products. The following risks apply to SPA:\n\n"
            "### Smart Contract Risk\n\n"
            "The protocols SPA uses are software programs running on public blockchains. "
            "Despite professional security audits, bugs or exploits can result in "
            "permanent loss of funds deposited in those protocols. SPA mitigates "
            "this by restricting allocation to large, well-audited protocols with "
            "multi-year track records.\n\n"
            "### Liquidity Risk\n\n"
            "Some positions may require 24–48 hours to exit without incurring "
            "significant slippage. In a market crisis, this window could extend "
            "further. SPA maintains a minimum 5% cash buffer and uses TVL-based "
            "filters to avoid illiquid positions.\n\n"
            "### Market Risk\n\n"
            "Stablecoin yields are linked to DeFi market activity. If borrowing "
            "demand drops sharply, yields compress. Periods of very low yield "
            "may result in the strategy remaining in cash for extended periods.\n\n"
            "### Stablecoin Depeg Risk\n\n"
            "USDC and other stablecoins can temporarily or permanently lose their "
            "1:1 USD peg. SPA uses only large-cap stablecoins (USDC, USDT, DAI/USDS) "
            "but cannot fully eliminate depeg risk.\n\n"
            "### Protocol Counterparty Risk\n\n"
            "Governance attacks, admin key compromises, or economic attacks on "
            "lending markets can result in bad debt that is socialised across "
            "depositors. SPA's concentration limits (40% max per T1 protocol) "
            "reduce but do not eliminate this risk.\n\n"
            "### Regulatory Risk\n\n"
            "DeFi regulation is evolving. Future legal or regulatory changes "
            "could restrict access to certain protocols or assets.\n\n"
            "### No Capital Guarantee\n\n"
            "SPA does not offer capital guarantees. Investors may receive less "
            "than their initial investment. The 5% drawdown kill-switch limits "
            "losses in a single event but does not prevent smaller cumulative losses.\n"
        )

    def fee_structure(self) -> str:
        """From InvestmentMemoConfig."""
        cfg = self._config
        return (
            f"## 5. Fee Structure\n\n"
            f"| Fee Type            | Rate                                      |\n"
            f"|---------------------|-------------------------------------------|\n"
            f"| Management Fee      | **{cfg.mgmt_fee_pct}%** per annum (charged monthly on AUM) |\n"
            f"| Performance Fee     | **{cfg.perf_fee_pct:.0f}%** of net profits above hurdle rate |\n"
            f"| Hurdle Rate         | 5% annualised (risk-free proxy)           |\n"
            f"| Entry Fee           | None                                      |\n"
            f"| Exit Fee            | None (after lock-up period)               |\n"
            f"\n"
            f"### Fee Calculation Examples\n\n"
            f"**Example A — $50,000 invested, 15% gross return:**\n"
            f"- Gross profit: $7,500\n"
            f"- Management fee: {cfg.mgmt_fee_pct}% × $50,000 = ${50_000 * cfg.mgmt_fee_pct / 100:,.0f}\n"
            f"- Performance fee base: $7,500 − hurdle ($2,500) = $5,000\n"
            f"- Performance fee: {cfg.perf_fee_pct:.0f}% × $5,000 = ${5_000 * cfg.perf_fee_pct / 100:,.0f}\n"
            f"- Net to investor: $7,500 − ${50_000 * cfg.mgmt_fee_pct / 100:,.0f} − "
            f"${5_000 * cfg.perf_fee_pct / 100:,.0f} = "
            f"${7_500 - 50_000 * cfg.mgmt_fee_pct / 100 - 5_000 * cfg.perf_fee_pct / 100:,.0f}\n\n"
            f"> Fees are subject to change with 30-day written notice to investors.\n"
        )

    def terms_section(self) -> str:
        """Min investment, lock-up, withdrawal terms."""
        cfg = self._config
        return (
            f"## 6. Minimum Investment & Terms\n\n"
            f"| Term                   | Detail                                        |\n"
            f"|------------------------|-----------------------------------------------|\n"
            f"| Minimum Investment     | **${cfg.min_investment_usd:,.0f} USDC**                     |\n"
            f"| Lock-up Period         | **{cfg.lock_up_days} days** from initial deposit             |\n"
            f"| Withdrawal Notice      | 7 business days written notice required       |\n"
            f"| Withdrawal Frequency   | Monthly (first business day of each month)    |\n"
            f"| Currency               | USDC (Ethereum mainnet or Arbitrum)           |\n"
            f"| Eligible Investors     | Family Fund members; accredited status required |\n"
            f"| AUM Capacity           | $500,000 USDC (current paper phase limit)     |\n"
            f"\n"
            f"### Important Conditions\n\n"
            f"- Investments are accepted **only after** the 30-day paper track record "
            f"is complete and the GoLiveChecker shows READY status.\n"
            f"- Investor onboarding requires completion of the Family Fund Investor "
            f"Agreement (`docs/legal/`) and KYC verification.\n"
            f"- Early withdrawal during the lock-up period is not permitted "
            f"except in documented emergency circumstances at the manager's discretion.\n"
        )

    def process_and_timeline(self) -> str:
        """Process and timeline section."""
        return (
            "## 7. Process & Timeline\n\n"
            "| Milestone                      | Target Date        |\n"
            "|--------------------------------|--------------------|\n"
            "| Paper trading start            | 2026-06-10 ✅      |\n"
            "| 30-day gap-free track complete | ~2026-07-10        |\n"
            "| GoLiveChecker READY (all 26)   | ~2026-07-21        |\n"
            "| Manual owner review (ADR-002)  | ~2026-07-20        |\n"
            "| Live capital accepted          | **~2026-08-01**    |\n"
            "| First investor statement       | 2026-09-01         |\n"
            "\n"
            "**Onboarding process:**\n"
            "1. Investor receives this memo and Family Fund Investor Agreement\n"
            "2. KYC / accredited investor verification\n"
            "3. Investor Agreement signed and returned\n"
            "4. USDC transfer to designated fund wallet (provided post-signing)\n"
            "5. Confirmation email with position summary within 24 hours\n"
            "6. Monthly performance reports via Telegram and email\n"
        )

    def contact_section(self) -> str:
        """Contact information section."""
        return (
            "## 8. Contact\n\n"
            "**Fund Manager:** Yurii (Owner, SPA Capital)\n\n"
            "For investment enquiries, onboarding documents, and performance reports:\n\n"
            "- **Email:** yuriycooleshov@gmail.com\n"
            "- **Telegram:** Contact via Family Fund group channel\n\n"
            "> *This document is for informational purposes only and does not constitute "
            "a solicitation or offer to invest. Investments in DeFi protocols involve "
            "significant risk. Please review all risk factors (§4) carefully before investing.*\n"
        )

    # ── Composite methods ──────────────────────────────────────────────────────

    def generate(self) -> str:
        """Full memo as Markdown."""
        cfg = self._config
        apy_low, apy_high = cfg.target_apy_range
        header = (
            f"# SPA Capital — Investment Memo\n\n"
            f"**{cfg.strategy_name}**\n\n"
            f"*Date: {self._doc_date} | Target APY: {apy_low:.0f}–{apy_high:.0f}% | "
            f"Status: Paper Trading Phase*\n\n"
            f"---\n\n"
            f"> **Confidential — Family Fund Investors Only**\n\n"
            f"---\n\n"
        )
        sections = [
            self.executive_summary(),
            self.strategy_overview(),
            self.historical_performance(),
            self.risk_factors(),
            self.fee_structure(),
            self.terms_section(),
            self.process_and_timeline(),
            self.contact_section(),
        ]
        return header + "\n\n---\n\n".join(sections)

    def save(self, output_path: Optional[str] = None) -> str:
        """
        Saves the memo to docs/INVESTMENT_MEMO.md atomically.

        Args:
            output_path: Override destination path. Defaults to
                         ``<base_dir>/docs/INVESTMENT_MEMO.md``.

        Returns:
            Absolute path to the saved file.
        """
        if output_path is None:
            dest = self._base_dir / "docs" / "INVESTMENT_MEMO.md"
        else:
            dest = Path(output_path)

        dest.parent.mkdir(parents=True, exist_ok=True)
        content = self.generate()

        tmp = dest.with_suffix(".md.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(dest))

        return str(dest.resolve())

    def word_count_ok(self) -> bool:
        """
        Checks that executive_summary() contains at most 180 words.

        Returns:
            True if word count <= 180, False otherwise.
        """
        text = self.executive_summary()
        # Strip markdown header line before counting
        lines = text.splitlines()
        body_lines = [ln for ln in lines if not ln.startswith("#")]
        body = " ".join(body_lines)
        words = body.split()
        return len(words) <= 180


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate SPA Investment Memo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--output", default=None, help="Override output path")
    parser.add_argument("--mgmt-fee", type=float, default=1.5, help="Management fee %%")
    parser.add_argument("--perf-fee", type=float, default=20.0, help="Performance fee %%")
    parser.add_argument("--min-investment", type=float, default=10_000.0, help="Minimum investment USD")
    parser.add_argument("--lock-up", type=int, default=90, help="Lock-up period in days")
    parser.add_argument("--print", action="store_true", help="Print to stdout instead of saving")
    args = parser.parse_args()

    cfg = InvestmentMemoConfig(
        mgmt_fee_pct=args.mgmt_fee,
        perf_fee_pct=args.perf_fee,
        min_investment_usd=args.min_investment,
        lock_up_days=args.lock_up,
    )
    gen = InvestmentMemoGenerator(config=cfg, base_dir=args.base_dir)

    if args.print:
        print(gen.generate())
    else:
        path = gen.save(output_path=args.output)
        print(f"Saved: {path}")
        print(f"Word count OK: {gen.word_count_ok()}")
