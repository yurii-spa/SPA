# RTMR (ADR-053) — Integration Map: reuse existing, don't rebuild

**Generated:** 2026-07-05 · Step-0 of EPIC-10 · read-only analysis
**ADR number:** ADR-044 in the proposal is **already taken** (`ADR-044-bear-market-hedge-strategy.md`). RTMR is renumbered **ADR-053** (next free after 048–052).

> **Core directive (system invariant #1 — no duplication):** RTMR is a **unifying layer** over monitoring/reaction pieces that ALREADY exist. `sense_loop`/`reaction` must **wrap and reuse** these, emitting one `RiskSignal` model and one `risk_posture.json`. Building a second, parallel kill path would be a regression (two kill mechanisms drifting apart). Every RTMR sensor/trigger below names the existing module it must reuse.

---

## What already exists (verified 2026-07-05)

| Existing module | Does today | RTMR role it maps to |
|---|---|---|
| `spa_core/monitoring/peg_monitor.py` (MP-601 PegStabilityMonitor) | CRITICAL alert on any adapter depeg | **sensor `peg`** (§3) — wrap its detection into `RiskSignal(source="peg")` |
| `spa_core/alerts/red_flag_monitor.py` | `tvl_drop` > 15%/24h or > 30%/7d + APY/unlock warnings | **sensor `tvl`** (+ warn signals) — wrap into `RiskSignal(source="tvl")` |
| `spa_core/alerts/risk_monitor.py` | canonical depeg detector (red_flag extends it) | peg sensor's underlying detector — reuse, don't fork |
| `spa_core/monitoring/threat_reactor.py` | every 5 min reads peg/red_flag/emergency-breaker signals → on CRITICAL fires kill-switch (closes the ~24h gap to next 06:00 cycle) | **this IS the emergency-path prototype** (§2) — RTMR generalises it: same read-signals→act loop, faster interval, `reaction.evaluate()` ladder instead of a single kill |
| `spa_core/governance/kill_switch.py` (MP-108) | drawdown ≥ 10% peak → HARD all-cash; > 5 CRITICAL red-flags on **held** protocols → trigger | **reaction actions** `MARKET_EXIT` / systemic trigger (§5) — reuse; don't reimplement drawdown math |
| `spa_core/paper_trading/cycle_gates.py` | DailyLimits HALT, Emergency Breakers, kill-switch, **soft-derisk** gate (caps target→held) | **reaction ladder + rebalance-honors-posture** (§5, §7) — the SOFT_DERISK/HARD_KILL two-tier is the money-path enforcement RTMR posture feeds |
| two-tier kill (ADR-034/048) | SOFT −5% de-risk / HARD −10% all-cash | reaction severities `warn`→de-risk / `critical`→exit already exist deterministically |
| RS-003 funding gates (ADR-042) | funding/carry TWAP exit for Engine B | **sensor `funding`** + its exit trigger — reuse the RS-003 gate, don't rewrite |
| `sky_monitor`, `base_gas_monitor`, `governance_watcher` (launchd) | protocol-specific live monitors | feed `protocol_events` / specialised sensors |

**Genuinely new (RTMR adds):** `signal.py` (one `RiskSignal` model), `sense_loop.py` (continuous 30–60s poller vs today's 5-min agents), `reaction.py` (the unified deterministic ladder §5 that *composes* the above), `posture.py` + `risk_posture.json` (the single fast↔slow coordination file — today's pieces don't share one posture), `monitoring_config.json` (externalised thresholds — today they're hardcoded per module).

---

## The unification, in one line each

- **Sensors** = thin adapters that call the EXISTING detectors (`peg_monitor`, `red_flag_monitor`, RS-003) and normalise their output into `RiskSignal`. No new detection logic where a detector exists.
- **Reaction** = one deterministic ladder that *composes* the EXISTING kill-switch / cycle-gates / two-tier actions behind the `Action` types (§5.1), instead of each monitor calling kill independently.
- **Posture** = the NEW shared file both the fast path (writes) and `cycle_runner` rebalance (reads/honors) use — replaces today's implicit, uncoordinated state.
- **Sense-loop** = generalises `threat_reactor`'s read-signals→act pattern to a faster, config-driven, heartbeat-guarded service.

## Migration order (so nothing double-fires)

1. **S10.1 (now):** `signal.py` + `posture.py` + `monitoring_config.json` — additive, paper-only, no money-path, no external data. Nothing reacts yet.
2. **S10.3:** sensors WRAP existing detectors (peg→peg_monitor, tvl→red_flag_monitor). Emit signals only.
3. **S10.4:** `reaction.evaluate()` composes existing kill-switch/cycle-gates actions. **Retire `threat_reactor`'s ad-hoc kill** into the ladder in the SAME change (don't run both).
4. **S10.5:** `cycle_runner` reads `signals/latest.json` + honors `risk_posture.json`. The two-tier kill/cycle-gates become posture consumers.

**Status:** S10.1 scaffold DONE (2026-07-05, commit 6cb18a03) — `signal.py` + `posture.py` + `monitoring_config.json` + 17 tests. **Paused here at owner's request** pending §13 answers.

**§13 — RESOLVED by owner (2026-07-05):**
1. **Data sources = FREE / keyless, 5–10 in PARALLEL** with quorum/median cross-validation. Concrete set: CoinGecko + DeFiLlama + public RPC + Chainlink on-chain oracles + DEX/CEX public price endpoints (Binance/Coinbase). No API keys (fits the keyless design). **Design consequence:** build `sensors/_multisource.py` (quorum/median helper, **fail-closed on disagreement** — diverge beyond tolerance OR < min-quorum fresh ⇒ `critical`, never an averaged-away number) BEFORE the individual sensors; peg/tvl/oracle each consume it.
2. **Incident sensor = DEFERRED.** Start with the deterministic core only (peg / tvl / oracle / liquidity) — it already catches most degradation (exploits usually surface as depeg / TVL-collapse / dead-oracle). Add `incident`/`protocol_events` later with a trusted source.
3. **Reaction actions = LOG + Telegram alert (paper, human-in-the-loop).** `actions.py` writes `reaction_log.json` ("would EXIT X") AND sends the owner a Telegram alert. **Never moves capital.** Live execution is a separate, explicitly-authorised, later step (execution layer). Reuse the existing Telegram client (Keychain creds; `send` needs `title=`, returns False on cooldown — see memory).
4. **news.py (advisory-LLM) = DEFERRED.** Deterministic core first; no LLM anywhere in the system for now.

**Resulting build plan (unblocked):**
- **S10.2** — `sense_loop.py` (persistent poller, interval from config, heartbeat, sensor-death ⇒ `stale_signal`/critical; writes `signals/latest.json` + append `signal_log.json`).
- **S10.3a** — `sensors/_multisource.py` (keyless quorum/median across the 5 providers above, fail-closed).
- **S10.3b** — `sensors/peg.py` (wraps existing `peg_monitor`), `sensors/tvl.py` (wraps `red_flag_monitor`), `sensors/oracle.py`, `sensors/liquidity.py` — each emits `RiskSignal` via the multisource helper.
- **S10.4** — `reaction.py` ladder composing existing kill_switch/cycle_gates; `actions.py` = log + Telegram (paper). Retire `threat_reactor`'s ad-hoc kill into the ladder in the SAME change.
- **S10.5 ACTIVE (owner-approved 2026-07-05)** — `cycle_runner` Step 2e calls `apply_rtmr_posture_gate`: the daily cycle now HONORS `risk_posture.json` (de-risk-only, no-op on NORMAL). RTMR loop closed: sense→signal→reaction→posture→cycle.
- Deferred: incident sensor, news.py.
