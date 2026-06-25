# Rates Desk — Phase-1 Validation

_Deterministic, pure (f(inputs, as_of)), stdlib, LLM-forbidden, fail-CLOSED. Re-runnable via `python3 -m spa_core.strategy_lab.rates_desk.validation`._

## Data-gap fix (the blocker, solved)

The keyless Pendle `/markets/active` endpoint returns only LIVE markets (~69d of PT implied-yield history, no in-sample stress). FIX: `pendle_pt_history.py` reaches the EXPIRED markets via `/markets?expired=true` (470 markets incl. 2024-02→date) and pulls each market's FULL daily implied-APY series via `/markets/{addr}/historical-data?time_frame=day` (the underscore form returns the whole life of the market; the `timeframe=daily` form is silently capped to ~60d hourly). This is the DIRECT method — Pendle exposes implied APY per day, so deriving from PT price is unnecessary (an `implied_yield_from_price` cross-check is provided + tested). Depth achieved: **849 survivor days** across **25 stable-synth markets** + 7 toxic LRT books, spanning 2024→2026 with all three stress events in-sample. Stored atomically in `data/rates_desk/pendle_pt_history.json`.

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

### Assertion 1 (deep) — toxic PT books refused across REAL history  →  **PASS**

Walking the REAL daily implied-yield history of every toxic restaking PT (ezETH / rsETH) through the Decimal gate — the desk must REFUSE essentially every day, so it never holds them into the depegs.

| toxic market | maturity | days | refused | approved | refuse rate % |
|---|---|---:|---:|---:|---:|
| PT-ezETH-25APR2024 | 2024-04-25 | 84 | 84 | 0 | 100.0 |
| PT-ezETH-26DEC2024 | 2024-12-26 | 247 | 247 | 0 | 100.0 |
| PT-ezETH-26SEP2024 | 2024-09-26 | 133 | 133 | 0 | 100.0 |
| PT-rsETH-26DEC2024 | 2024-12-26 | 126 | 126 | 0 | 100.0 |
| PT-rsETH-26JUN2025 | 2025-06-26 | 230 | 230 | 0 | 100.0 |
| PT-rsETH-26SEP2024 | 2024-09-26 | 127 | 127 | 0 | 100.0 |
| PT-rsETH-27JUN2024 | 2024-06-27 | 154 | 154 | 0 | 100.0 |

- all toxic books refused EVERY day: **True**  ·  any toxic day approved: **False**

## Assertion 2 — Survivor book beats the floor (deflated Sharpe)  →  **GO (carry leg real → fundable)**

RWA floor: **3.4%/yr**. DEEP Pendle PT history: **849 survivor days** (pooled approved-carry days: **2927**, source: expired+live markets 2024→2026, all 3 stress events in-sample).

| market | maturity | days | carry days | avg net carry %/yr |
|---|---|---:|---:|---:|
| PT-USDe-4APR2024 | 2024-04-04 | 34 | 34 | 160.04 |
| PT-sUSDE-25APR2024 | 2024-04-25 | 49 | 49 | 54.124 |
| PT-USDe-25JUL2024 | 2024-07-25 | 112 | 112 | 36.209 |
| PT-sUSDE-25JUL2024 | 2024-07-25 | 91 | 91 | 21.951 |
| PT-sUSDE-26SEP2024 | 2024-09-26 | 127 | 127 | 12.413 |
| PT-USDe-24OCT2024 | 2024-10-24 | 97 | 97 | 16.843 |
| PT-sUSDE-24OCT2024 | 2024-10-24 | 97 | 97 | 10.848 |
| PT-USDe-26DEC2024 | 2024-12-26 | 160 | 160 | 19.294 |
| PT-sUSDE-26DEC2024 | 2024-12-26 | 160 | 160 | 9.893 |
| PT-sUSDE-27FEB2025 | 2025-02-27 | 77 | 77 | 9.48 |
| PT-USDe-27MAR2025 | 2025-03-27 | 188 | 188 | 19.998 |
| PT-sUSDE-27MAR2025 | 2025-03-27 | 189 | 189 | 8.576 |
| PT-sUSDE-29MAY2025 | 2025-05-29 | 195 | 195 | 7.442 |
| PT-USDe-31JUL2025 | 2025-07-31 | 153 | 153 | 14.441 |
| PT-sUSDE-31JUL2025 | 2025-07-31 | 126 | 126 | 10.439 |
| PT-USDe-25SEP2025 | 2025-09-25 | 133 | 133 | 15.204 |
| PT-sUSDE-25SEP2025 | 2025-09-25 | 133 | 133 | 7.69 |
| PT-USDe-27NOV2025 | 2025-11-27 | 105 | 105 | 11.165 |
| PT-sUSDE-27NOV2025 | 2025-11-27 | 125 | 125 | 4.429 |
| PT-USDe-5FEB2026 | 2026-02-05 | 102 | 102 | 12.303 |
| PT-sUSDE-5FEB2026 | 2026-02-05 | 102 | 102 | 8.296 |
| PT-USDe-7MAY2026 | 2026-05-07 | 117 | 117 | 10.962 |
| PT-sUSDE-7MAY2026 | 2026-05-07 | 117 | 117 | 7.622 |
| PT-USDe-13AUG2026 | 2026-08-13 | 69 | 69 | 11.515 |
| PT-sUSDE-13AUG2026 | 2026-08-13 | 69 | 69 | 7.83 |

- mean survivor book APY: `23.816%`  vs floor `3.4%`
- Sharpe (annual, vs floor): `16.039`  ·  PSR vs floor: `1.0`  ·  deflated Sharpe: `1.0` (passes 0.95: `True`)
- minTRL: `1.5` obs (have `849`, satisfied: `True`)
- OOS (carry yield): in-sample `29.145%` → out-of-sample `11.403%` (decay `17.742%`; beats floor OOS: `True`, no-decay: `False`)

Stress-window survival (book mean APY must beat the floor THROUGH each event):

| stress window | days | mean book APY % | beats floor |
|---|---:|---:|:--:|
| 2024-08 ETH crash / carry-unwind | 39 | 11.743 | yes |
| 2025-10 restaking de-risk regime | 48 | 9.948 | yes |
| 2026-04 KelpDAO rsETH depeg | 43 | 11.303 | yes |

> _Note on Sharpe: Locked held-to-maturity carry has near-zero downside variance by construction, so its Sharpe is structurally inflated (degenerate) — it is reported as a not-noise check only; the verdict rests on the realized book APY beating the floor in-sample, out-of-sample, and in every stress window._

> **GO — the survivor carry book beats the RWA floor risk-adjusted across the full deep window (real stress + multiple maturities). Carry leg is real → fundable.**
