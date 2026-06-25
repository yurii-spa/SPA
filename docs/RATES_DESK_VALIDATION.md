# Rates Desk — Phase-1 Validation

_Deterministic, pure (f(inputs, as_of)), stdlib, LLM-forbidden, fail-CLOSED. Re-runnable via `python3 -m spa_core.strategy_lab.rates_desk.validation`._

## Assertion 1 — REFUSAL fired early  →  **PASS**

The refusal-first gate must REFUSE each toxic book BEFORE its stress event, with economics never reached (a huge quoted rate must NOT rescue a tail-vetoed book).

| event | underlying | quoted % | verdict | reason | total haircut % | max % | structural? |
|---|---|---:|---|---|---:|---:|:--:|
| 2024-08 ETH crash / carry-unwind | ezeth | 35.0 | REFUSED | tail_veto | 19.067 | 12.0 | yes |
| 2025-10 restaking de-risk regime | weeth | 28.0 | REFUSED | tail_veto | 17.433 | 12.0 | yes |
| 2026-04 KelpDAO rsETH depeg | rseth | 45.0 | REFUSED | tail_veto | 22.3 | 12.0 | yes |

- all toxic books refused before event: **True**
- refusals were structural (not economic): **True**
- legacy full-history scorer (retro test 1): toxic flagged before = `3/3`, safe stayed low = `1/2`, separation = `0.0799`, substantive = `True`

## Assertion 2 — Survivor book beats the floor (deflated Sharpe)  →  **DATA-GAPPED**

RWA floor: **3.4%/yr**. Pendle PT max history: **69 days** (pooled approved-carry days: **321**).

| market | expiry | days | carry days | avg net carry %/yr |
|---|---|---:|---:|---:|
| USDe | 2026-08-13T00:00:00.000Z | 69 | 69 | 11.515 |
| jrUSDe | 2026-10-22T00:00:00.000Z | 21 | 21 | 9.0 |
| sUSDS | 2026-11-26T00:00:00.000Z | 42 | 42 | 8.459 |
| sUSDe | 2026-08-13T00:00:00.000Z | 69 | 69 | 7.83 |
| srUSDe | 2026-10-22T00:00:00.000Z | 21 | 21 | 9.662 |
| superUSDC | 2026-11-26T00:00:00.000Z | 60 | 60 | 7.755 |
| tmvUSDC | 2026-10-29T00:00:00.000Z | 39 | 39 | 9.491 |

- Sharpe (annual, vs floor): `58.842`  ·  deflated Sharpe: `1.0` (passes 0.95: `True`)  ·  minTRL: `2.1` obs

> **Pendle's keyless API exposes only LIVE markets, so PT implied-yield history is ~69 days (needs >=180 for a credible deflated-Sharpe verdict, and minTRL is typically longer). The carry MECHANISM and net-of-cost edge are demonstrated on the live window; the multi-year OOS / deflated-Sharpe verdict requires expired-market PT history we do NOT have. Assertion 2 is therefore DATA-GAPPED, not passed/failed.**

> Verdict is intentionally **null** (DATA-GAPPED), not a fabricated pass/fail.
