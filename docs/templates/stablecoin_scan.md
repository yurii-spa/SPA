# Stablecoin-Yield Candidate Scan — <SCAN_ID>

> SYE-002 template. A structured scan of stablecoin-yield candidates, organized by risk category. A row
> here is a **candidate**, not an approval ([`../35_strategy_discovery_engine.md`](../35_strategy_discovery_engine.md)).
> Fill-in; **no invented numbers** — every APY/TVL is `requires verification`; apparent yield is a raw
> feed value labelled unverified or a category. Cross-refs: [`../33_yield_thesis_map.md`](../33_yield_thesis_map.md)
> (Domain A), [`../35_screening_rubric.md`](../35_screening_rubric.md), [`../37_apy_realism_and_evidence_standard.md`](../37_apy_realism_and_evidence_standard.md),
> [`../adr/ADR-YL-008-unified-yield-lab-mandate.md`](../adr/ADR-YL-008-unified-yield-lab-mandate.md).

## Scan header
- **scan_id / date:** `<SCAN-XXXX>` / `<YYYY-MM-DD>`
- **analyst:** `<name>`
- **live RWA floor used (baseline):** `<pct> requires verification` · **source/as-of:** `data/rwa_feed.py` @ `<ts>`
- **spread rule (ADR-YL-008):** `spread = observed APY − floor`; unexplained spread → REJECT (record refusal).

---

For each candidate fill one block. Verdict ∈ `REJECT | HOLD | RED-TEAM | PASS`
([`../35_screening_rubric.md`](../35_screening_rubric.md) §4).

## A1 — Conservative lending (Aave / Spark / Compound / Euler)
| Field | Value |
|---|---|
| candidate / protocol / chain | `<>` / `<>` / `<>` |
| yield-source (bucket) | `borrow demand` |
| observed APY / TVL | `<> requires verification` / `<> requires verification` |
| spread over floor (bps) | `<>` · **fully explained?** `<true/false>` |
| risks | `exploit · oracle · withdrawal-freeze on utilization spike · governance` |
| evidence level | `L0–L6` |
| verdict / next_action | `<>` / `<>` |

## Curated vaults (Morpho / peer-matched)
| Field | Value |
|---|---|
| candidate / curator / underlying market | `<>` / `<>` / `<>` |
| yield-source (bucket) | `borrow demand (P2P-matched)` |
| observed APY / TVL | `<> requires verification` / `<> requires verification` |
| spread over floor (bps) | `<>` · **fully explained?** `<>` |
| risks | `curator misallocation · fallback-to-pool rate · underlying-market · contract` |
| evidence level / verdict | `<>` / `<>` (curator DD required before PASS) |

## Fixed carry (Pendle PT)
| Field | Value |
|---|---|
| candidate / market / maturity | `<>` / `<>` / `<>` |
| yield-source (bucket) | `fixed implied rate (locked at discount)` |
| observed implied APY | `<> requires verification` |
| spread over floor (bps) | `<>` · **fully explained?** `<>` |
| risks | `underlying-yield failure · thin exit liquidity · toxic underlying (LRT PT) · contract` |
| capacity (binding constraint) | `PT pool depth — thin; ~$1–2M edge-cliff` |
| evidence level / verdict | `<>` / `<>` (validated shape = FixedCarry, `rates_desk/`) |

## Basis / delta-neutral (sUSDe / funding-carry)
| Field | Value |
|---|---|
| candidate / venues | `<>` / `<Binance/Bybit/OKX/KuCoin/Hyperliquid>` |
| yield-source (bucket) | `basis/funding` |
| observed APY (regime-dependent) | `<> requires verification` |
| spread over floor (bps) | `<>` · **fully explained?** `<>` |
| risks | `funding reversal · CEX counterparty · collateral custody/depeg · regime shift` |
| red-team | **mandatory** (funding-kill logic required) |
| verdict / note | `<>` — CEX leg custody-gated; `rates_desk` BASIS_HEDGE = BLOCKED-NO-HEDGE |

## RWA (tokenized T-bills — the floor)
| Field | Value |
|---|---|
| candidate / issuer | `<>` / `<>` |
| yield-source (bucket) | `real economic yield (T-bill coupon)` |
| observed APY / TVL | `<> requires verification` / `<> requires verification` |
| spread over floor (bps) | `≈0 (this IS the baseline)` |
| risks | `issuer default · custody · redemption freeze · regulatory` |
| evidence level / verdict | `<>` / `<>` (the benchmark, not a spread play) |

## Synthetic / other (structured · LP · looping)
| Field | Value |
|---|---|
| candidate / mechanism | `<>` / `<stable LP / recursive loop / structured>` |
| yield-source (bucket) | `<basis/incentive/tail-comp — name it>` |
| observed APY | `<> requires verification` |
| spread over floor (bps) | `<>` · **fully explained?** `<>` |
| risks | `<depeg→permanent IL · liquidation · short-vol tail · incentive cliff>` |
| verdict | `REFUSE default unless spread fully explained` ([`../33`](../33_yield_thesis_map.md) A2/A9/A12) |

---

## Scan summary
| Verdict | Candidates |
|---|---|
| PASS (→ promotion gate) | `<>` |
| RED-TEAM | `<>` |
| HOLD | `<>` |
| REJECT (refusals logged) | `<>` |
