# Weekly Investment Report — Week of <YYYY-MM-DD>

> Fill-in weekly report (§38 reporting set). Research/decision-support artifact — advisory only; does
> not move capital (ADR-YL-005) and never overrides the deterministic RiskPolicy or kill-switch.
> **Never invent APY/TVL. Unknown = `TBD — requires verification`; illustrative figures labelled
> "illustrative".** Cross-refs: `docs/37_apy_realism_and_evidence_standard.md` (APY evidence L0–L6),
> `docs/07_yield_lab_architecture.md`, `docs/11_strategy_card_system.md`, `docs/34_capital_tiers_strategy.md`.

- **report_id:** `WIR-XXXX`  ·  **week_ending:** `<ISO date>`  ·  **author:** `<name>`  ·  **status:** `<draft|final>`

## 1. Executive summary
_3–6 bullets: what changed this week, what matters, what needs a decision._

## 2. Portfolio state (paper track)
| Field | Value | Source |
|---|---|---|
| Evidenced track days | `TBD — requires verification` | `data/golive_status.json` |
| Current equity | `TBD — requires verification` | `data/paper_trading_status.json` |
| Active positions | `TBD — requires verification` | `data/current_positions.json` |
| Peak-to-current drawdown | `TBD — requires verification` | `spa_core/governance/kill_switch.py` |
> Numbers pulled live from state files — do not hardcode; label anything not directly sourced.

## 3. APY overview (with evidence levels)
| Line / strategy | APY | Kind | Evidence level (L0–L6) | Source | Last verified |
|---|---|---|---|---|---|
| Core book | `TBD — requires verification` | observed | | | |
| <candidate> | `TBD — requires verification` | | `L0` | | |

## 4. Risk overview
- Advisory Risk Scoring v2 highlights (docs/14): `<...>`  — advisory only (ADR-YL-004).
- Kill-switch state (SOFT −5% / HARD −10%): `<...>`  ·  concentration / caps status: `<...>`

## 5. Active candidates (Yield Lab pipeline)
| strategy_id | name | lifecycle_status | product_line | next gate |
|---|---|---|---|---|
| `SC-XXXX` | | `<research|paper_testing|...>` | | |

## 6. Rejected strategies (this week)
| strategy_id | name | reason rejected |
|---|---|---|
| `SC-XXXX` | | `<yield-source failed / red-team failed / capacity too thin / ...>` |

## 7. Protocol / stablecoin risk changes
- `<peg moves, TVL shifts, incident reports, governance actions — cite sources; requires verification>`

## 8. BTC cycle view (decision-support only)
_Regime / cycle read. Decision-support, NOT auto-trading (ADR-YL-007). No guaranteed calls._
- `<...>`

## 9. ETH yield view (decision-support only)
_Staking / LST-LRT / basis commentary. Decision-support only (ADR-YL-007)._
- `<...>`

## 10. Alerts & incidents
- `<agent-health, cycle gaps, feed outages, depegs, exploits touching held protocols>`

## 11. Decisions needed
- `<explicit list of owner/IC decisions required, each with the artifact backing it (IM-XXXX / RV-XXXX / RT-XXXX)>`

## 12. Next actions
- `<owner-assigned next steps for the coming week>`

## 13. Data sources
- `<every feed/file cited above, with last-verified timestamp>`
