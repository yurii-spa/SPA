# SPA Family Fund — Risk Disclosure Statement

**Version:** 1.0  
**Effective Date:** 2026-06-20  
**Maintained by:** Fund Manager (Yurii Kulieshov)

---

## Important Notice

**READ THIS DOCUMENT CAREFULLY BEFORE INVESTING.**

Investment in DeFi (Decentralised Finance) strategies carries significant risks,
including the possible total loss of invested capital. This document outlines the
principal risks associated with participation in SPA Family Fund. It is not
exhaustive. By signing the investment agreement you confirm that you have read,
understood, and accepted these risks.

This is a private family fund, not a regulated investment vehicle. It is not
supervised by any financial regulatory authority. There is no investor protection
scheme (e.g. FSCS, SIPC) that would cover losses in the event of fund failure.

---

## Market Risk

DeFi protocol yields (APY) are variable and not guaranteed. APY rates can
decline rapidly in response to:

- Changes in supply and demand for lending/borrowing on DeFi protocols.
- Broader crypto market downturns reducing total value locked (TVL).
- Protocol governance decisions that alter yield parameters.
- Macro-economic events affecting risk appetite in crypto markets.

Historical APY values shown in the dashboard are past performance only and are
**not indicative of future results.**

---

## Smart Contract Risk

All DeFi protocols used by SPA (Aave V3, Compound V3, Morpho, Yearn, Euler, etc.)
operate via smart contracts deployed on public blockchains. Smart contracts may
contain bugs, vulnerabilities, or logic errors that are exploited by malicious
actors. Such exploits can result in partial or total loss of funds deposited
in the protocol.

Mitigation: SPA only allocates to protocols with published audits and TVL ≥ $5M
(T1 minimum). However, audits do not guarantee security.

---

## Liquidity Risk

Under normal conditions, positions in T1 protocols can be exited within hours.
Under stressed market conditions:

- Protocols may pause withdrawals (e.g. during a liquidity crisis or governance
  emergency).
- High demand for exits may delay withdrawal processing.
- A sudden large exit may incur unfavourable slippage.

SPA maintains a minimum cash buffer of 5% (RiskPolicy v1.0) to handle
operational needs, but this buffer does not guarantee full liquidity in a
market-wide crisis.

---

## Concentration Risk

During the paper-trading period, the SPA portfolio may concentrate significant
capital in a small number of protocols (particularly T1). The system enforces
per-protocol caps (40% for T1, 20% for T2) and a T2 total cap of 50%, but a
single large T1 protocol may still represent 35–40% of portfolio value.

A failure of a single dominant protocol at this allocation level would result in
a loss of up to 40% of total portfolio value.

---

## Regulatory Risk

The regulatory treatment of DeFi is evolving rapidly in all major jurisdictions.
Future regulation may:

- Restrict or prohibit certain DeFi activities.
- Impose reporting requirements on fund managers.
- Classify yield-bearing DeFi positions as securities, creating compliance
  obligations.

SPA Family Fund does not provide legal or tax advice. Investors are responsible
for their own tax obligations arising from participation in the fund.

---

## Technology and Operational Risk

SPA is a software system. Risks include:

- **Software bugs:** Errors in cycle_runner, allocator, or adapter code may
  cause incorrect trades or missed cycles.
- **Data source failures:** If DeFiLlama is unavailable, the system uses
  fallback APY estimates that may not reflect current market conditions.
- **Infrastructure failures:** launchd daemon failures, power outages, or
  network disruptions may cause missed daily cycles, affecting the 30-day
  continuity requirement.
- **Key loss:** Loss of the GitHub PAT or Telegram bot credentials could
  interrupt monitoring and reporting.

The fund manager has documented disaster recovery procedures in
`DR_PROCEDURE_v2.md`. However, operational risk cannot be fully eliminated.

---

## Counterparty Risk

SPA interacts with DeFi protocols in a non-custodial manner: the fund manager's
wallet retains control of assets. However:

- DeFi front-ends (Aave, Compound, etc.) may introduce counterparty risk at the
  UI layer.
- Oracle failures (price oracles used by lending protocols) can trigger
  erroneous liquidations.
- Stablecoin de-pegging (e.g. USDC, USDT) would reduce the USD-denominated
  value of positions.

SPA currently allocates 0% to algorithmic stablecoins. USDC (Circle) is used
as the base denomination due to its regulatory oversight and reserve backing,
but this does not guarantee a permanent 1:1 peg.

---

## Track Record Risk

SPA is a new system. The track record:

- Started: 2026-06-10 (paper trading only; no real capital deployed yet).
- Target go-live: 2026-08-01.
- Historical track record prior to 2026-06-10 is demo/simulation data and
  should not be relied upon.

A short live track record means that performance statistics (Sharpe ratio,
drawdown, APY) are not statistically significant. Do not extrapolate past
paper-trading performance as a reliable indicator of live performance.

---

## No Guarantee of Returns

The fund targets positive returns above a benchmark DeFi lending rate, but:

- Returns are not guaranteed.
- The fund may return less than the amount invested.
- The fund may suffer periods of zero or negative returns.

The fund manager does not provide any guarantee, warranty, or assurance of
profit.

---

## Acknowledgement

By signing the investment agreement, the investor confirms that:

1. They have read and understood this risk disclosure.
2. They can afford to lose the entirety of their invested capital.
3. They have sought independent financial and legal advice if needed.
4. They understand that this fund is not regulated and investor protection
   schemes do not apply.

---

*Compliance policy: `docs/COMPLIANCE_POLICY.md`*  
*Investment agreement: `docs/legal/`*  
*Disaster recovery: `DR_PROCEDURE_v2.md`*
