# C1 · Canonical Trading Research lineage + BTC systems disposition (RM-TRUTH-01, CAPITAL)

Worker C1, read-only. Re-measured 2026-10-05 11:04–11:20Z. Builds on A1 (`A1_trading_lab.md`), REVIEW_1 and ADR-567 C7. Archaeology was not redone.

**Snapshot method.**
- `evidence.db` was copied to `c1/evidence.db` with a byte-identical sha256 (`51f4eb7d…`). The source is in journal_mode=delete, so there is no -wal or -shm. The copy was then opened `mode=ro`.
- `earn_defi.db` was also copied before reading.
- No repo tree, launchd job or DB was modified.
- One read-only GET was made to `127.0.0.1:8765/api/btc-engine*`.

Outcome labels: MEASURED · MEASURED-ZERO · NOT MEASURED · ESTIMATE · UNKNOWN.

---

## 1. Re-measure: Trading Research Engine v0 (MEASURED unless marked)

| Check | Result |
|---|---|
| Scheduler | `launchctl list`: `- 0 com.spa.trading_research` (not running between ticks; last exit 0). StartInterval 900 s |
| Ticks | **440** ticks: seq 1..440 contiguous, from 2026-09-30T21:22:52Z to **2026-10-05T11:04:41Z**. `ok=0`: 0. Max gap 15.51 min, none over 20 min. Code `d138baef` on seq 1–3, then `279cd91f` on 4–440 |
| status.json | generated 11:04:41Z, `ok:true`, `evidence_verified:true`, `breaks:[]`, release `bbb127730c94`, mode `PAPER_RESEARCH_ONLY`, `live_capital_usd 0` |
| Observations | **6,394** across 138 chains. `late` 0, `gap_bars` 0. Last 1h close 11:00Z, 4h close 08:00Z, 1D close 2026-10-05 00:00Z. 152 closed trades across *all* chains; **0** for the forward five |
| No-reset proof | 138 candidates with **1** distinct `registered_at_ms` (1790803372716 = 2026-09-30T21:22:52Z), unchanged since A1. All **8** append-only triggers (no UPDATE/DELETE × 4 tables) are present. My own `evidence.verify()` on the snapshot gave 138 chains, 6,394 obs, 0 breaks. The earliest observation opens 37 min after registration (2,227,284 ms), so nothing predates the clock. 419 lifecycle events, all at registration ts, all `actor=trading_research`. **0 stage changes in 5 days** |
| Stages | FORWARD_PAPER 5 · REJECTED 133 · ROBUST 0 · CHAMPION_CANDIDATE/SHADOW 0 · owner-decision events 0 |
| D1 `forward_bars` +1 | **STILL PRESENT.** status.json shows 5 and 27; real rows are 4 (1D) and 26 (4h). `forward_metrics()` prepends the seed `eq=[1.0]`, and `evaluate()` returns `bars=len(eq)`. It reaches **3 readers**: `director_report.py:769` ("за 5 бар."), `research_factory/scanners/trading_research.py:78`, and `investment_cio/sleeves.py:1120` (`n=min_bars` in the realized_return NOT_ENOUGH_HISTORY cell). Return and MDD are unaffected, because the seed is the true starting equity 1.0 |
| D2 OOS absorbs forward | **STILL PRESENT.** `backtest.json` manifest has `oos_start 2023-01-01` and no OOS end; `data_to` is 2026-10-04T21:00Z, so about 95 1h bars past forward_start sit inside OOS. The backtest refreshes daily and `_derive_stages` re-qualifies daily against it. Scores have drifted since qualification: supertrend 1D 0.8648→0.8738, st 4h 0.5209→0.5156, donchian 1D 0.7660→0.7758, st+ma 0.7681→0.7781, donchian 4h 0.8555→0.8542 |
| D3 market.db backup | **Not on origin/main.** Prod and mirror `scripts/daily_backup.py:71` hold only `evidence.db`. The integration branch `/tmp/spa_rmtruth01` (`rmtruth/candidate`, commit `1ab9bb74c`, ADR-567 C10) adds `trading_research/market.db` at line 77, **but that commit is NOT an ancestor of origin/main**. `evidence.db` is confirmed in `~/spa_offsite_backups/spa_state_2026-10-05.tar.gz` (05:30); the same disk, as REVIEW_1 #12 found. `backtest.json` is backed up nowhere and is overwritten daily |
| D6 (new) | Chains are **per-candidate with GENESIS roots and no external anchor**, and `ticks` is trigger-protected but **not hash-chained**. A whole-file swap to an older or truncated `evidence.db` (restore, copy) passes `verify()`. A1 itself used the prefix property to clear the `/tmp/spa_c771_*` copies. The fix is to publish per-chain `(count, head_hash)` in status.json and refuse any non-monotonic change. This is not a defect today, but it is a gap in the no-reset proof |
| D7 (new, representation) | The Director report prints `oos_max_drawdown` as "просадка" (−26…−42%), but the binding gate is the **full-history** MDD (−45…−55%). The owner sees the shallower number |
| D8 (new, readers) | `status.shortlist` is the *backtest* top-5 after correlation de-dup; it is **not** the forward set. Today they coincide (5 = 5). Readers (CIO, research_factory, Director) take forward state from the shortlist, so they will diverge once more than 5 candidates qualify or the de-dup drops one |

**Today's BTC signal (MEASURED, last target per candidate; the target is the position for the next bar)**

| Forward candidate | TF | as of bar close | BTC close | held | target | fwd obs | fwd net (paper MTM) | fwd MDD |
|---|---|---|---|---|---|---|---|---|
| supertrend n10 m2.0 | 1D | 10-05 00:00Z | 86,530 | long | **LONG** | 4 | +1.79% | −0.58% |
| supertrend_and_ma n10 m3.0 MA200 | 1D | 10-05 00:00Z | 86,530 | long | **LONG** | 4 | +1.79% | −0.58% |
| donchian 20/10 | 1D | 10-05 00:00Z | 86,530 | long | **LONG** | 4 | +1.79% | −0.58% |
| supertrend n20 m3.0 | 4h | 10-05 08:00Z | 86,252.76 | long | **LONG** | 26 | +0.72% | −2.44% |
| donchian 55/20 | 4h | 10-05 08:00Z | 86,252.76 | flat | **FLAT** | 26 | 0.00% | 0.00% |

- The forward set reads **4 LONG / 1 FLAT**.
- The three 1D candidates have an **identical** forward path: all bought the same bar. Today, 5 forward candidates are effectively 3 independent bets.
- Breadth across all 138, including rejected candidates, is diagnostic only and not a signal:

| TF | as of | long | flat | short |
|---|---|---|---|---|
| 1D | 00:00Z | 38 | 7 | 1 |
| 4h | 08:00Z | 40 | 5 | 1 |
| 1h | 11:00Z | 30 | 11 | 5 |

- Split by execution model, spot candidates are long or flat only, since they cannot short. The perp shorts are 1D 1, 4h 1 and 1h 5.

**Maturity.**
- The forward span is 3.0 days (1D) and 4.17 days (4h). 7d and 30d performance are **NOT_ENOUGH_HISTORY**.
- ROBUST day-criterion earliest dates: 1D 2026-11-01T00:00Z, 4h 2026-10-31T04:00Z.
- The ≥5 closed-trade criterion is an ESTIMATE from backtest trade frequency: st 4h ≈2.5 mo, donchian 4h ≈4.4 mo, st 1D ≈8.3 mo, donchian 1D ≈12.7 mo, st+ma 1D ≈17.7 mo. **The binding ROBUST constraint is trades, not days.**

**Marginal qualifications (auto-requalified daily, so a single bad data week can flip the stage):**
- Donchian 4h: full MDD −54.86%, 0.14 pp headroom on −55%.
- Supertrend 1D: −54.79%, 0.21 pp.
- Donchian 1D: −54.30%, 0.70 pp.
- Supertrend 4h: OOS@3× 0.5156 against a 0.5 floor.

Observation continues for every candidate whatever its stage, so a flip loses no evidence.

## 2. Canonical lineage decision (architecture)

**The ONE canonical active Trading Research lineage** for the Owner's "Indicator & Directional Trading Lab" is the **SPA Trading Research Engine v0**: ADR-525, `spa_core/trading_research/`, agent `com.spa.trading_research`, state in `data/trading_research/{evidence.db,market.db,backtest.json,status.json}`.

Why:
- It is the only system that runs an *indicator/directional candidate universe* through a lifecycle with a forward clock that is append-only and hash-chained.
- It runs now (440/440 ok ticks).
- It is in the repo with canonical delivery, and its owner directive is ADR-525.
- No other system in this list does indicator research.

| System | Disposition | Evidence |
|---|---|---|
| SPA Trading Research Engine v0 | **CANONICAL_ACTIVE** | §1; ADR-525 §2–4; manifest `intent: active` |
| **earn-defi BTC Signal Engine** (`~/Documents/earn-defi`, config v0.3 live, v0.4 shadow, v0.5 pinned) | **SEPARATE_PRODUCT**. **Not superseded** and not part of the Lab lineage. It is its own product line (MVRV / realized-price / SMA200 / M2 cycle allocator), owner decision D-01 2026-09-04, and ADR-525 §5 says "earn-defi stays a separate product engine under Trading → Crypto Spot". The Lab may show it as an *external reference row* and never sums it with Lab numbers (it carries the same BTC beta) | `nav_daily` has 33 rows (09-02..10-04, written 10-05 10:10Z): NAV 108,059.49, +8.06%, MDD −4.73%, BTC weight 0.70. **system_mode=INCIDENT since 2026-09-19 (incident #2 state OPEN)**. Lifting it is owner-reserved (earn-defi ADR-006). New finding: SPA `GET /api/btc-engine/track.json` returns 200 locally, and **neither it nor any `earn-defi/site/*.json` carries `system_mode`/INCIDENT**. A reader of the published track cannot see the incident |
| research/btc_cycle (ADR-102; v0.1 champion external, v0.2/v0.3 rejected) | **SUPERSEDED_HISTORY**, kept as **archive-as-evidence**. The cycle idea lives on as the earn-defi product. Its numbers are the only record of the owner's original cycle results, so they must not be deleted | README: "архив замера"; the v0.1 `backtest.py` and datasets were never delivered, so it is unreproducible |
| SPA `btc_nav` (ADR-118) | **SUPERSEDED_HISTORY** (never ran). The owner's "separate BTC NAV" choice is fulfilled by earn-defi | plist never installed; `data/btc_paper_trading.json` absent (MEASURED-ZERO); ADR-525 §5. **Manifest drift:** `architecture/manifest.json:309` still says `intent: "designed"`, on both prod and the integration branch |
| LOGOS desk (Polymarket semantic arb, `~/Documents/Claude/Projects/LOGOS/logos-desk`, no git) | **BROKEN** (zombie), outside the Lab's scope: prediction markets, slot "Volatility/Options" | 5,299 scans; last with `markets>0` was **2026-07-29T06:10:55Z**; last scan 10:54:52Z today shows `markets:0`, `SKIPPED_DEGRADED`; logs are 117 MB each. Two launchd processes are alive (1742, 1695). KILL or REPAIR is an owner decision (preserves the A1 recommendation) |
| strategy_lab BTC/ETH sleeves (btc_neutral, btc_lending, eth_lst_*) | **LEGACY_REFERENCE**. Not directional; they belong to Market-Neutral/Basis, not the Lab | frozen 2026-06-25/26; "net APY 0.0%" is likely unmeasured, not zero (A1 U5) |
| gold_proxy_research / s20_anticrisis_research | **UNKNOWN_PURPOSE** (research placeholders; readers unknown, A1 U7) | placeholder APYs plus `FALLBACK_APY_PCT=8.0` fake fallback, which contradicts `adapters.md` |

**Version-name collision.** `btc_cycle v0.3` is a **rejected** rule variant (`backtest_v03.py`). `earn-defi v0.3` is the **live** product config (`config/btc_engine_v0.3.json`, `active.json`). Every register and card must namespace them as `btc_cycle:v0.3` and `earn-defi:btc_engine@0.3`. The Lab's own versioning is different again: `family@vN` + `def_hash` + `exec_model vN`.

## 3. Experiment passports

Passports are in `C1_passports.json`:
- **5 individual forward candidates**, each with the requested fields: return typed `BACKTEST_RETURN` separately from `REALIZED_PAPER_RETURN` (MTM), drawdown typed the same way, qualification margins, a ROBUST ETA, D1/D2/D3/D6 gaps, and supersession.
- **The rejected universe** summarised by family: count, exec/TF split, reasons, best OOS, and 3 drawdown-only near misses.
- **External and historical rows** for earn-defi, btc_cycle and btc_nav.

All 5 forward candidates are spot long-only trend/breakout; 0 of 63 perp candidates qualified.

## 4. ADR draft

`C1_ADR_DRAFT.md`. None of its fixes touch money. The only owner-reserved items are lifting the earn-defi INCIDENT (which stays outside this ADR) and the LOGOS KILL or REPAIR.

## 5. Director OS "Trading Lab" read model

`C1_tradinglab_readmodel.json` defines 21 fields. Each has a source path, a query, a `metric_type`, the rule and today's value. Key rules:
- Read the forward set from `lifecycle_events`, not from `shortlist`.
- Count forward periods with `COUNT(*)`, not `forward_bars`.
- 7d and 30d windows are shown only once the span reaches 7 or 30 days.
- Show the full and the OOS MDD side by side.
- earn-defi appears only as a labeled external row that must show `system_mode`.
