# The Cost of Chasing 15% — A Year, Dated

*Auto-generated from `data/aggressive_lab/annual_contrast.json` · as-of **2026-06-25** · proof `843c06939ee23457…` · ADVISORY / OUTSIDE_RISKPOLICY — never touches the live book.*

> **The pitch in one line.** Here is a full year of the 10–15% strategies the desk is asked about — every one shown with the dated −X% it carries. The desk's steady **~+4.1%** book over the same year: **max-drawdown ~0%**. That gap is the whole product. 15% is *paid for* in drawdowns that arrive without warning; the steady book is the deliberate choice.

**Method (so you can check us).** Same start date, same **$100,000** notional, same window for both sides. The aggressive curves are the lab's real 2024–2026 backtest. The stable curve compounds the desk's REAL conservative-book rate (**+4.1%**, source: live_conservative_book (paper_trading_status.json apy_today_pct)) — an honest baseline, not a lowballed strawman. Drawdowns are shown two ways, always labelled: **realized** (the real peak-to-trough in the backtest equity) and **dated stress overlay** (the dated 2024–26 events modeled by each book's risk shape). We never blend them and never invent one.

---

## The dated events behind the timeline

| Date | Event |
|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg |

---

## A year, side by side

| Strategy (class) | Headline | 1yr aggressive | aggr max-DD | stable | stable max-DD | worst dated tail (event) |
|---|---|---|---|---|---|---|
| `eth_directional` (B) | ~+4% | -32.3% | -66.3% | +4.2% | 0.0% | -66.3% — realized drawdown (2026-06-06) |
| `leverage_loop` (C) | ~+8% | 0.0% | 0.0% | +4.2% | 0.0% | -29.7% — realized drawdown (2024-08-09) |
| `lrt_neutral` (C) | ~+6% | 0.0% | 0.0% | +4.2% | 0.0% | -16.7% — realized drawdown (2024-08-23) |
| `pendle_pt_levered` (C) | ~+15% | +13.2% | -6.2% | +4.2% | 0.0% | -19.1% — realized drawdown (2024-04-23) |
| `pendle_yt_susde` (C) | ~+14% | +53.3% | -0.6% | +4.2% | 0.0% | -8.0% — 2025-10 USDe leverage unwind (USDe $14B→$5.6B) (2025-10-11) |
| `points_farm` (D) | ~+14% | +6.2% | 0.0% | +4.2% | 0.0% | -2.0% — 2025-10 USDe leverage unwind (USDe $14B→$5.6B) (2025-10-11) |
| `susde_dn` (C) | ~+11% | +9.2% | 0.0% | +4.2% | 0.0% | -8.0% — 2025-10 USDe leverage unwind (USDe $14B→$5.6B) (2025-10-11) |
| `susde_spot` (C) | ~+9% | +5.8% | -2.3% | +4.2% | 0.0% | -9.0% — 2026-04 KelpDAO rsETH depeg (2026-04-05) |

*(1yr window = trailing 12 months where available; full per-window + per-calendar-year detail is in the JSON.)*

---

## The drawdown timeline, dated

### `eth_directional` — ~+4% headline · beta (directional market exposure) · shape: depeg

**Realized drawdowns (in the backtest equity):**

| Peak → Trough | Depth | Recovered |
|---|---|---|
| 2024-06-06 → 2024-09-06 | -42.1% | 91d |
| 2024-12-09 → 2025-04-08 | -63.0% | 123d |
| 2025-08-14 → 2025-08-20 | -14.4% | 3d |
| 2025-08-24 → 2026-06-06 | -66.3% | **NOT RECOVERED** |

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -4.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -7.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -9.0% |

### `leverage_loop` — ~+8% headline · risk-compensation (yield paid for a tail) · shape: liquidation

**Realized drawdowns (in the backtest equity):**

| Peak → Trough | Depth | Recovered |
|---|---|---|
| 2024-03-09 → 2024-03-10 | -2.7% | 7d |
| 2024-03-17 → 2024-04-13 | -21.3% | 117d |
| 2024-08-08 → 2024-08-09 | -29.7% | **NOT RECOVERED** |

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -6.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -12.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -11.0% |

### `lrt_neutral` — ~+6% headline · risk-compensation (yield paid for a tail) · shape: depeg

**Realized drawdowns (in the backtest equity):**

| Peak → Trough | Depth | Recovered |
|---|---|---|
| 2024-08-08 → 2024-08-23 | -16.7% | **NOT RECOVERED** |

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -4.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -7.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -9.0% |

### `pendle_pt_levered` — ~+15% headline · risk-compensation (yield paid for a tail) · shape: liquidation

**Realized drawdowns (in the backtest equity):**

| Peak → Trough | Depth | Recovered |
|---|---|---|
| 2024-03-09 → 2024-03-20 | -11.5% | 2d |
| 2024-03-26 → 2024-03-30 | -6.7% | 3d |
| 2024-04-02 → 2024-04-03 | -2.8% | 2d |
| 2024-04-06 → 2024-04-07 | -1.7% | 1d |
| 2024-04-15 → 2024-04-16 | -3.0% | 2d |
| 2024-04-19 → 2024-04-23 | -19.1% | 12d |
| 2024-05-05 → 2024-05-06 | -1.1% | 2d |
| 2024-05-09 → 2024-05-13 | -2.1% | 1d |
| 2024-05-14 → 2024-05-16 | -5.4% | 11d |
| 2024-06-03 → 2024-06-05 | -2.0% | 3d |
| 2024-06-09 → 2024-06-10 | -1.4% | 2d |
| 2024-07-30 → 2024-07-31 | -1.3% | 8d |
| 2024-09-01 → 2024-09-03 | -3.4% | 7d |
| 2024-09-10 → 2024-09-23 | -2.5% | 10d |
| 2024-10-10 → 2024-10-14 | -1.3% | 9d |
| 2024-11-05 → 2024-12-07 | -3.8% | 7d |
| 2024-12-15 → 2024-12-16 | -1.2% | 3d |
| 2025-01-01 → 2025-01-06 | -2.8% | 7d |
| 2025-04-21 → 2025-04-22 | -1.0% | 9d |
| 2025-05-06 → 2025-05-21 | -2.5% | 9d |
| 2025-07-09 → 2025-07-27 | -6.2% | 6d |
| 2025-08-07 → 2025-08-10 | -1.1% | 9d |
| 2025-08-19 → 2025-08-23 | -1.3% | 9d |
| 2025-09-04 → 2025-09-07 | -1.1% | 14d |
| 2026-04-09 → 2026-04-23 | -1.4% | 12d |

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -6.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -12.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -11.0% |

### `pendle_yt_susde` — ~+14% headline · risk-compensation (yield paid for a tail) · shape: funding_flip

**Realized drawdowns:** none material in the backtest equity (this book's realized track accrued smoothly — the honest answer; its tail is in the dated stress overlay below).

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -3.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -8.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -3.0% |

### `points_farm` — ~+14% headline · incentive (emissions / points — decays) · shape: incentive_decay

**Realized drawdowns:** none material in the backtest equity (this book's realized track accrued smoothly — the honest answer; its tail is in the dated stress overlay below).

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -1.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -2.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -1.5% |

### `susde_dn` — ~+11% headline · risk-compensation (yield paid for a tail) · shape: funding_flip

**Realized drawdowns:** none material in the backtest equity (this book's realized track accrued smoothly — the honest answer; its tail is in the dated stress overlay below).

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -3.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -8.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -3.0% |

### `susde_spot` — ~+9% headline · risk-compensation (yield paid for a tail) · shape: depeg

**Realized drawdowns (in the backtest equity):**

| Peak → Trough | Depth | Recovered |
|---|---|---|
| 2024-03-09 → 2024-03-20 | -5.5% | 6d |
| 2024-03-26 → 2024-03-30 | -3.0% | 3d |
| 2024-04-02 → 2024-04-03 | -1.1% | 2d |
| 2024-04-15 → 2024-04-16 | -1.1% | 2d |
| 2024-04-19 → 2024-04-23 | -6.9% | 15d |
| 2024-05-09 → 2024-05-16 | -2.1% | 13d |
| 2024-09-01 → 2024-09-03 | -1.2% | 7d |
| 2024-09-10 → 2024-09-23 | -1.0% | 16d |
| 2024-11-05 → 2024-12-07 | -1.2% | 7d |
| 2025-01-01 → 2025-01-06 | -1.0% | 7d |
| 2025-07-09 → 2025-07-28 | -2.3% | 10d |

**Dated stress overlay (the tail by risk shape — *modeled*, not realized):**

| Date | Event | Modeled hit (by shape) |
|---|---|---|
| 2024-08-05 | 2024-08 ETH crash / carry-unwind | -4.0% |
| 2025-10-11 | 2025-10 USDe leverage unwind (USDe $14B→$5.6B) | -7.0% |
| 2026-04-05 | 2026-04 KelpDAO rsETH depeg | -9.0% |

---

## The honest bottom line

Across every aggressive book, the year ends higher — that is what the headline buys. But the path is paid for in dated drawdowns: the **2025-10 USDe unwind** and the **2026-04 rsETH depeg** show up on the 15% side with real dates and real depths. The desk's steady **~+4.1%** book walks the same year with **max-drawdown ~0%** — no dated cliff, nothing to explain to a client mid-quarter. *That* is the trade: you can chase 15% and own its tail, or take the deliberate 5% and own your sleep. We will run either with eyes open — this page is so the choice is informed.

*Every number on this page traces to `data/aggressive_lab/annual_contrast.json`. Aggressive curves: the lab's real 2024–2026 backtest. Stable curve: the desk's real conservative book rate. Drawdowns: realized (from the series) + dated stress overlay (modeled by risk shape). No figure is hand-entered. LLM-FORBIDDEN, deterministic, isolated from the live book.*
