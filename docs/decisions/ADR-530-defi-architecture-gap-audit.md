# ADR-530: DeFi Architecture Gap Audit — findings, priorities and the vNext input

- **Status:** ACCEPTED · 2026-10-01 · owner: @yurii (owner directive «DEFI ARCHITECTURE GAP AUDIT», autonomous
  execution authorised in it)
- **Scope:** an evidence audit only. New canonical document `docs/DEFI_ARCHITECTURE_GAP_AUDIT.md`, working
  evidence `docs/audits/defi_gap_2026-10-01/`, facts in `architecture/memory_truth.json`, roadmap status.
  **No implementation:** RiskPolicy v1.0, limits, kill switch, books, allocator, site and fleet untouched.

## Context

The owner asked what the DeFi system ACTUALLY does today versus what exists only in documents, chats,
prototypes or stale concepts, classified from evidence (code on a running path + live artifacts), before
DeFi Engine vNext is designed. Code audited at origin/main `e6204fd23`; runtime = live `data/` on 2026-10-01.

## Decision

1. **The three packages are, from live evidence:** Conservative = main `cycle_runner` book under RiskPolicy
   v1.0 (T1 45 % / T2 50 %, 100 evidenced days); Balanced = `hy_cycle` sleeve, Aggressive = `lp_cycle` sleeve —
   both **outside RiskPolicy**, own kills −8 % / −25 %. All three hold only single-asset stablecoin lending /
   savings; «aggressive» = concentration + wider stop, not riskier protocols or complex mechanics. Every complex
   mechanic (loops, PT/YT, LP, delta-neutral, basis, points) runs only in advisory labs.
2. **Classification** of 56 capabilities is recorded in the audit document §C and is the reference for vNext.
3. **P0 (correctness / safety), to be fixed first in vNext:**
   P0-1 sleeve books charge full Ethereum gas on daily accrual drift (Balanced $48.03 vs $13.77 yield a day,
   Aggressive $24.01 vs $14.34) — their tracks are wrong by construction;
   P0-2 the kill switch's red-flag trigger ignores every flag when the document says `fallback_used=true` and
   reads a missing file as «not triggered» (inv. #2, #17);
   P0-3 `peg_monitor` returns price 1.0 when no price exists, watches non-held adapters, and its GREEN feeds the
   intraday `threat_reactor`;
   P0-4 public package pages contradict the books and canon — «Tier 1 only» vs 50 % T2, «No lock-up / T+1 / no
   withdrawal fee» (solicitation, inv. #8), «L6 live evidenced» for paper, leverage and kill-switch claims that
   do not match the books. P0-4 is owner subject №2 and ships only through `safe_site_push.py` with an owner card.
4. **Protocol risk and strategy (mechanic) risk are one dimension today**; vNext adds a mechanic axis, advisory
   until an ADR changes RiskPolicy (v1.0 stays frozen for the paper period).
5. **No new agents:** all eight target roles exist under other names; vNext extends them (RTMR sensors, one
   supervisor contract) and creates no duplicate source of truth.
6. **Superseded assumptions recorded:** CLAUDE.md snapshot «GoLive 27/29 · track 13/30» (live: 29/29, 100
   evidenced days, `ready_for_live=false`); `docs/LOOPING_STRATEGY.md` «no code»; «HY 2 : LP 1»; the Aggressive
   book as an LP / leverage book; `MATURITY_REGISTER.md` (2026-08-22) as current.

## Consequences

- Roadmap item 2 is closed; item 3 **DeFi Engine vNext** is next and starts from §K of the audit document.
- Restating or resetting the Balanced/Aggressive tracks, and every public-number or wording fix, is owner subject
  №2. Leverage activation stays RED (owner only).
- Open UNKNOWNs are listed in §N of the audit document; none blocks vNext design.
