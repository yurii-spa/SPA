# SPA Telegram Bot — Technical Architecture (v2 rebuild)

> **Status:** PROPOSAL for owner review. Do NOT build until approved.
> **Author:** Senior Architect · **Date:** 2026-06-26
> **Scope:** the technical half. The **UX half** (menu tree, button labels, copy,
> navigation flows, bilingual EN|RU strings) is the DESIGNER's `docs/TELEGRAM_BOT_UX.md`
> (or equivalent design doc). This document references the menu structure from there;
> it does not define button wording. Wherever the two overlap, the design doc owns
> *what the user sees* and this doc owns *how it is delivered, gated, and sourced*.

---

## 0. TL;DR

The chat is flooded because **~40 launchd agents each push their own Telegram
messages on their own schedule**, with per-module dedup that does not coordinate
across agents, plus **duplicate report senders** (three different "daily report"
modules) and **monitors that re-fire CRITICAL on every state read**. We replace
this with:

1. **One push policy module** (`push_policy.py`) — the *only* code path allowed to
   push unsolicited messages, enforcing a strict 3-tier severity gate.
2. **One interactive bot service** (extend the existing `spa_core/telegram/bot.py`
   long-poll loop) — everything non-critical becomes **pull-on-demand** via menus.
3. **Two scheduled digests** (daily + weekly) — single canonical builders; all the
   old per-event reports collapse into the daily digest as sections.
4. **A handful of real-time PUSH-NOW warnings** (kill-switch fired, cycle failed,
   critical health, peg break) — and *nothing else* is allowed to push.

Target: from the current peak (**67 messages in one day, 2026-06-26**, projecting
toward the owner-reported ~500/day under worse conditions) down to **≤ ~5
messages/day in the normal case** (1 daily digest + occasional warning), with all
detail available on demand.

---

## 1. AUDIT — where the flood comes from (grounded in live data)

### 1.1 Method

- Enumerated every launchd plist in `~/Library/LaunchAgents/com.spa.*` and
  `scripts/com.spa.*.plist` (~50 plists, ~42 loaded).
- Grepped `spa_core/ scripts/ launchd/` for `send_message` / `_post_message` /
  `sendMessage` / `api.telegram.org` / `flood_guard`.
- **Read the live audit trail** `data/alert_history.json` (ring buffer, cap 500,
  records every send outcome) — this is ground truth for *what actually fired*.

### 1.2 Live evidence (data/alert_history.json, 2026-06-26)

67 sends in a single day, all `ok=True`, broken down by actual previews:

| Count | Source (from preview) | Type tag |
|------:|------------------------|----------|
| 17 | `🚨 SPA Agent Health Alert · Status: CRITICAL` (re-fires) | agent_health_monitor |
| 16 | `🖥️ Dashboard Alert ⚠️` | dashboard_watcher |
| 9  | `🖥️ Dashboard Alert 🔴` | dashboard_watcher |
| 7  | `📊 SPA Daily Report — …` (plain) | a daily-report sender |
| 7  | `📊 SPA Daily Report — …` (HTML `<b>`) | a *different* daily-report sender |
| 6  | `⚠️ SPA — Cycle Gap Detected` | cycle_gap_monitor |
| 1  | `🖥️ Dashboard Alert 📉` | dashboard_watcher |
| 1  | `📊 SPA Daily Report — Day 17` | a *third* daily-report sender |
| 1  | `📊 *SPA Daily — …*` (Markdown) | a *fourth* daily-report variant |
| 1  | `⚠️ SPA Agent DOWN: com.spa.daily_cycle` | uptime/agent |
| 1  | `🚨 SPA — Важные события` (red flag) | risk/red-flag |

### 1.3 Root causes (quantified, in priority order)

1. **Agent-health CRITICAL re-fires — ~17/day, the single biggest contributor.**
   `agent_health_monitor.py` claims to dedup against the prior `agent_health.json`,
   but a *persistent* CRITICAL condition (e.g. one agent stuck down) produces a new
   alert each run because the dedup key set changes subtly or the condition keeps
   re-qualifying. A standing problem should alert **once**, then go quiet — not
   hourly. **This is a re-fire bug, not just policy.**

2. **dashboard_watcher — ~26/day.** Runs every 5 min (288×/day). Five check kinds
   (agents/portfolio/system/api/golive), each with an independent **/tmp 30-min
   cooldown**. `/tmp` cooldown files are **not durable** (cleared on reboot, and
   per-kind not global), so multiple kinds fire in the same window and re-fire after
   each cooldown lapse all day. This duplicates what `/agents`, `/status`, `/alerts`
   already answer on demand.

3. **Duplicate daily-report senders — ~16/day for ONE logical report.** At least
   **four** distinct daily-report code paths are live, in three different parse
   modes (plain / HTML / Markdown):
   - `spa_core/reporting/daily_telegram_report.py` (HTML, the good one)
   - `spa_core/paper_trading/daily_report.py`
   - `scripts/daily_paper_report.py` (supposedly merged, still firing)
   - `spa_core/analytics/telegram_daily_digest.py` / `daily_digest.py`
   - `spa_core/alerts/morning_digest.py`
   Multiple launchd agents (`telegram_daily`, `morning_digest`,
   `daily-paper-report`, `cpa_daily`, `analytics_tier_*`) each trigger their own.
   The owner sees the "same" report 4–7 times.

4. **cycle_gap_monitor — ~6/day.** Should be ≤1/day; re-fires because the
   once-per-calendar-day gate is not holding (or the gap is real and re-reported
   each 5-min run).

5. **~18 senders bypass the shared flood guard.** These POST directly to
   `api.telegram.org` with their own urllib instead of going through
   `telegram_client._post_message` (which enforces the 12-msg/min cross-process
   cap). Confirmed direct-POST modules:
   `alert_dispatcher`, `telegram_manager`, `telegram_sender`, `telegram_watcher`,
   `telegram_daily_digest`, `tournament_telegram`, `promotion_notifier`,
   `research_progress_telegram`, `telegram_research_alerts`,
   `telegram_protocols_reporter`, `family_fund/telegram_blast`,
   `family_fund/lead_tracker`, `devtools/auto_fixer`, plus the bot itself and
   3 scripts. Some call `flood_guard_ok()` first; **many do not**. The 12/min cap
   is the only backstop, and it is leaky — and 12/min still allows **17,280/day**.

### 1.4 The structural problem

The flood guard caps *rate* (12/min) but nothing caps *policy*: there is **no
single authority deciding whether an event deserves to interrupt the owner at
all.** Every agent is its own publisher. Dedup is per-module, per-`/tmp`, and
non-durable. The fix is architectural: **one push authority + pull-by-default.**

### 1.5 What already works (keep it)

- `spa_core/alerts/telegram_client.py` — Keychain creds, fail-safe send, 400→plain
  retry, the `alert_history.json` audit trail, `flood_guard_ok()`. **Keep as the
  transport layer.**
- `spa_core/telegram/bot.py` — already a stdlib long-poll bot with offset
  persistence, inline keyboards, callback routing, `setMyCommands`, kill-switch
  pause/resume, backoff. **This is the foundation of the new interactive service.**
- `daily_telegram_report.py` / `weekly_telegram_report.py` — clean,
  read-only, fail-safe builders. **Promote these to the canonical digest builders;
  retire the other three daily variants.**

---

## 2. NEW MODEL — three severity tiers

Every message is classified into exactly one tier. The tier decides *the channel
and the timing*, not the content.

### Tier 1 — PUSH-NOW (real-time interrupt). Whitelist only.

Pushed the instant the event is detected. **Closed whitelist** — if an event type
is not on this list, it is physically not allowed to push (the policy module drops
it to the digest).

| Event | Source | Why it interrupts |
|---|---|---|
| Kill-switch FIRED (drawdown / threat / manual) | risk gate, `threat_reactor` | capital action taken |
| Daily cycle FAILED / did not run | `cycle_runner`, `cycle_gap_monitor` | track integrity at risk |
| CRITICAL system health (data corruption, all-feeds-down, NAV mismatch) | `system_health_monitor` | system may be lying about state |
| Stablecoin PEG BREAK on a **held** protocol | `peg_monitor` | live capital at risk |
| Red flag CRITICAL on a **held** protocol (hack/exploit) | `red_flag_monitor` | live capital at risk |
| Go-live state change: **NOT-READY → READY** (one-shot) | `golive_checker` | the milestone the owner waits for |

**Rules for Tier 1:**
- **Edge-triggered, not level-triggered.** Push on the *transition into* the bad
  state, and one "RESOLVED ✅" on the transition out. Never re-push while the
  condition merely persists (this is the agent-health 17×/day fix).
- **Held-protocol scoping.** Peg/red-flag alerts only push if the protocol is in
  `current_positions.json`. Advisory protocols → digest, never push.
- **Hard daily ceiling:** ≤ 10 Tier-1 pushes/day. The 11th is coalesced into a
  single "N more critical events — open /alerts" message. (Defense against a
  flapping detector.)

### Tier 2 — DIGEST (scheduled, batched).

Everything informational. Never pushed individually; **rolled into the next
scheduled digest** as a section. Two digests only:

- **Daily digest** (1×/day, ~08:10 UTC after the cycle): equity/P&L, APY, top
  positions, go-live progress, cycle health summary, *count* of red flags & peg
  warnings (not each one), best strategy, base-chain status. This subsumes
  morning_digest, daily_paper_report, tier1_digest, analytics digests.
- **Weekly digest** (1×/week, Sun ~10:00 UTC): 7-day performance, strategy
  ranking, rebalances, risk blocks, track-day progress, tournament movers.

### Tier 3 — ON-DEMAND (pull). The interactive bot.

Anything the owner might want but that should never interrupt: full portfolio,
per-protocol APY, agent health detail, tournament board, strategy lab, peg table,
governance, research progress, "why is agent X down". Delivered only when the
owner taps a button or types a command. **This is where the other ~35 senders go.**

### Decision rule (the one-liner every contributor follows)

> *Is live capital or track integrity at immediate risk, AND is this a NEW
> transition?* → Tier 1 PUSH. *Is it a daily/weekly fact?* → Tier 2 DIGEST
> contribution. *Else* → Tier 3, exposed as a menu view, pushed never.

---

## 3. THE INTERACTIVE BOT SERVICE

Built on the **existing** `spa_core/telegram/bot.py` (extended, not rewritten).

### 3.1 Service shape

- **One launchd agent** `com.spa.telegram_bot` (replaces `com.spa.bot_commands`),
  `KeepAlive=true`, `RunAtLoad=true`, `ThrottleInterval` so a crash-loop backs off.
  Runs `python3 -m spa_core.telegram.bot` (the `run_polling` loop).
- **Long-poll** `getUpdates` with `timeout=30`, persisted `offset` in
  `data/tg_bot_offset.json` (atomic). Capped exponential backoff on API failure
  (already implemented). Single instance — getUpdates offset semantics make a
  second poller fight over updates, so the launchd agent must be the sole poller.
- **Stdlib only** — urllib for `getUpdates` / `sendMessage` / `editMessageText` /
  `answerCallbackQuery`. No `python-telegram-bot`.

### 3.2 Update router

```
update → handle_update()
  ├─ callback_query?  → answerCallbackQuery (stop spinner)
  │                     → route(callback_data) → editMessageText (in-place nav)
  └─ message (text)?  → "/cmd"? → route(cmd) → sendMessage (new bubble)
                         bare text → main menu
```

- **Commands** (`/status`, `/portfolio`, …) send a **new** message.
- **Button taps** (callback_query) **edit the existing message** via
  `editMessageText` so drill-down feels like in-place navigation, not a wall of
  new bubbles. (The current bot sends a new message on every tap — UX fix.)
- **Auth:** only `TELEGRAM_CHAT_ID_SPA` (the owner) is served. Any other chat id →
  silent ignore. Fail-closed: if chat id can't be read from Keychain, serve nobody.

### 3.3 Menu-state model (drill-down via callback_data)

State lives entirely in **`callback_data`** (Telegram caps it at 64 bytes) — the
bot is stateless between taps, which is deterministic and restart-safe.

```
callback_data grammar:   "<view>:<arg>"     (max 64 bytes)
  examples:
    "menu:root"          → main menu
    "view:status"        → status screen
    "view:portfolio"     → portfolio screen
    "view:port_proto:aave_v3"   → drill into one protocol
    "view:agents"        → agent grid
    "view:agents_detail" → agent reference
    "view:why"           → diagnostics
    "nav:back:menu:root" → back button
```

- A **view registry** maps `<view>` → builder fn `(arg) -> (text, keyboard)`.
  Adding a screen = add one registry entry. No router edits. (Mirrors the
  strategy-lab pluggable pattern used elsewhere in the repo.)
- Every screen's keyboard ends with a **⬅️ Back** and **🏠 Menu** row
  (`callback_data` carries the parent view) so navigation is a tree, not a dead
  end. **The exact tree, labels, and ordering come from the DESIGNER's UX doc** —
  this layer just executes whatever tree the registry is populated with.
- `editMessageText` for in-tree navigation; new message only for `/start`.

### 3.4 Data sourcing (read-only, fail-closed)

Screens read from `data/*.json` directly (fast, no network) with the live HTTP API
(`spa_core/api`, port 8765) as an **optional** enrichment, never a hard dependency:

| Screen | Primary source | Fallback |
|---|---|---|
| status | `paper_trading_status.json` | "data unavailable" |
| portfolio | `current_positions.json` | — |
| today | `paper_trading_status.json` | — |
| week | `equity_curve_daily.json` | — |
| agents | `uptime_status.json` | — |
| alerts | `red_flags.json` + `peg_report.json` | — |
| golive | `golive_status.json` | — |
| tournament | `mass_tournament_results.json` | — |

- **Fail-closed UX:** a missing/corrupt file renders an explicit "⚠️ data
  unavailable (file X)" line — never a crash, never a stale silent value, never a
  fabricated number. (Matches the existing `_read_json(..., default)` pattern.)
- All reads via `spa_core/utils/atomic` helpers; no writes from read screens.
  The only writes the bot performs are **kill-switch pause/resume** (atomic) and
  the offset file.

### 3.5 Rate-limiting & dedup in the bot

- Bot replies are **solicited** (owner asked), so they are exempt from the digest
  policy — but they still pass through `flood_guard_ok()` so a callback loop can't
  flood (already wired at `bot.py:187`).
- **Idempotent taps:** repeated taps on the same button re-render the same screen
  via `editMessageText`; Telegram no-ops an identical edit, so double-taps are free.

---

## 4. REPORTS & WARNINGS

### 4.1 Daily digest — `spa_core/telegram/reports/daily.py`

- **Promote `spa_core/reporting/daily_telegram_report.py`** as the single builder
  (it is already the cleanest). Extend it to absorb the few unique fields from the
  retired variants (cycle-run count, tier-1 plane summary, peg/red-flag *counts*).
- Scheduled by **one** launchd agent `com.spa.digest_daily` at ~08:10 UTC (after
  the 08:00 cycle). Sends **exactly one** HTML message via `telegram_client`.
- Idempotency: writes `data/.last_daily_digest` (date stamp); refuses to send twice
  for the same UTC date even if the agent double-fires.

### 4.2 Weekly digest — `spa_core/telegram/reports/weekly.py`

- Promote `spa_core/reporting/weekly_telegram_report.py`. One launchd agent
  `com.spa.digest_weekly`, Sundays ~10:00 UTC, one message, same date-stamp guard.

### 4.3 Warnings — `spa_core/telegram/push_policy.py`

The **only** module allowed to emit a Tier-1 push. Public API:

```python
def push_critical(event_key: str, severity: str, title: str,
                  body: str, *, held_protocol: bool = False) -> bool:
    """Emit a Tier-1 warning IFF it passes the policy gate. Returns sent?."""
```

Gate logic (all must pass):
1. `event_key` is on the **Tier-1 whitelist** (§2 table) — else demote to a digest
   contribution (append to `data/digest_queue.json`) and return False.
2. **Edge-trigger:** durable state in `data/push_state.json`
   (`{event_key: {state, last_ts, msg_id}}`, atomic). Push only on
   `ok→bad` transition; on `bad→ok` send one "RESOLVED ✅" editing the original
   message id; suppress while state is unchanged.
3. **Held-protocol filter** for peg/red-flag keys.
4. **Daily ceiling** (≤10); 11th+ coalesced.
5. Send via `telegram_client._post_message` (honors flood guard + audit trail).

This replaces the ad-hoc `send_message` calls scattered across ~18 monitors with
one call site each: `push_policy.push_critical(...)`.

---

## 5. MIGRATION — collapsing ~40 senders

Principle: **monitors keep detecting and keep writing their JSON state; they stop
sending Telegram directly.** They either (a) call `push_policy.push_critical` for a
whitelisted critical, or (b) do nothing (their data is picked up by the digest
builder and/or the on-demand screens).

| Current sender | Fate | New path |
|---|---|---|
| `agent_health_monitor` | **PUSH (edge) only on all-down/critical** | `push_policy` (`agent_health_critical`), once per episode |
| `dashboard_watcher` | **RETIRE Telegram** | data already in `/status` `/agents` `/alerts`; kill the 5-min push entirely |
| `uptime_monitor` | **PUSH only on cycle-critical agent down (edge)** | `push_policy` (`core_agent_down`); rest → `/agents` |
| `peg_monitor` | **PUSH only on held-protocol break (edge)** | `push_policy` (`peg_break`); warnings → digest count + `/alerts` |
| `red_flag_monitor` | already writes JSON only | `push_policy` for held-protocol CRITICAL; rest → `/alerts` |
| `threat_reactor` | **PUSH (edge)** kill-switch fired | `push_policy` (`kill_switch`) |
| `cycle_gap_monitor` | **PUSH (edge, ≤1/day)** cycle missed | `push_policy` (`cycle_gap`) |
| `system_health_monitor` (morning/evening) | **PUSH only CRITICAL**; summary → digest | `push_policy` (`system_critical`) + digest section |
| `rules_watchdog` | **PUSH only on CRITICAL rule breach** | `push_policy` (`rules_critical`) |
| `daily_telegram_report` | **KEEP — promote to canonical daily** | `com.spa.digest_daily` |
| `weekly_telegram_report` | **KEEP — promote to canonical weekly** | `com.spa.digest_weekly` |
| `paper_trading/daily_report.py` | **RETIRE** (dup) | folded into daily digest |
| `scripts/daily_paper_report.py` | **RETIRE** (dup) | folded into daily digest |
| `analytics/telegram_daily_digest.py`, `daily_digest.py` | **RETIRE Telegram** | metrics → digest section / `/menu` analytics view |
| `morning_digest.py` | **RETIRE** (dup of daily) | folded into daily digest |
| `tier1_digest.py` | **RETIRE Telegram** | tier-1 summary → daily digest section |
| `milestone_alert` / `reporting/alert_on_milestone` | **PUSH (edge, one-shot)** | `push_policy` (`golive_ready`, `equity_milestone`) |
| `tournament_telegram` / `promotion_notifier` | **RETIRE push** | tournament view in `/menu` + weekly digest movers |
| `research_progress_telegram`, `telegram_research_alerts`, `telegram_protocols_reporter` | **RETIRE push** | on-demand `/research` view |
| `family_fund/telegram_blast`, `lead_tracker` | **OUT OF SCOPE** (investor channel, separate chat) | leave as-is, not the owner's ops chat |
| `devtools/auto_fixer` Telegram | **RETIRE** (dev noise) | log only |
| `bot_commands` (old) | **RETIRE** | superseded by `telegram/bot.py` service |
| `telegram_manager`, `telegram_sender`, `telegram_watcher` | **RETIRE** | superseded by `telegram_client` + `push_policy` |

**launchd changes:**
- **Add:** `com.spa.telegram_bot` (KeepAlive), `com.spa.digest_daily`,
  `com.spa.digest_weekly`.
- **Unload/remove:** `com.spa.bot_commands`, `com.spa.morning_digest`,
  `com.spa.daily-paper-report`, `com.spa.cpa_daily`, `com.spa.tier1_digest`,
  `com.spa.telegram_daily` (replaced by digest_daily), `com.spa.telegram_weekly`
  (replaced by digest_weekly), `com.spa.telegram_milestone` (→ push_policy),
  `com.spa.dashboard_watcher` Telegram role (keep the JSON-writing role if used by
  screens, else unload).
- **Keep but rewire to push_policy:** `peg_monitor`, `red_flag_monitor`,
  `uptime_monitor`, `agent_health`, `cycle_gap_monitor`, `threat_reactor`,
  `rules_watchdog`, `system_health_morning/evening`.

**Enforcement guard (prevents regression):** add a lint test
`test_telegram_single_authority.py` that greps `spa_core/` for direct
`api.telegram.org` POSTs and direct `telegram_client.send_message`/`_post_message`
calls, and **fails** unless the caller is on an allowlist (`telegram_client`,
`push_policy`, the two digest builders, the bot). This makes "one push authority"
a CI-enforced invariant, killing the flood permanently.

---

## 6. MODULE STRUCTURE

```
spa_core/telegram/
├── bot.py                 # EXISTS — extend: editMessageText nav, view registry, owner-auth
├── router.py              # NEW — command + callback_data router, view registry
├── views/                 # NEW — one builder per on-demand screen (Tier 3)
│   ├── __init__.py        #       VIEW_REGISTRY: {view_key: builder_fn}
│   ├── status.py
│   ├── portfolio.py
│   ├── agents.py
│   ├── alerts.py
│   ├── tournament.py
│   └── ...                #       (tree/labels driven by DESIGNER UX doc)
├── menus.py               # NEW — keyboard builders (consumes UX-doc tree)
├── push_policy.py         # NEW — THE push authority (Tier-1 gate, edge-trigger, ceiling)
├── reports/               # NEW — scheduled digests (Tier 2)
│   ├── daily.py           #       promotes reporting/daily_telegram_report.py
│   └── weekly.py          #       promotes reporting/weekly_telegram_report.py
└── (command_handler.py)   # EXISTS — fold into views/, then retire

spa_core/alerts/
└── telegram_client.py     # EXISTS — KEEP as transport (creds, send, flood guard, audit)

data/
├── tg_bot_offset.json     # bot long-poll offset (atomic)
├── push_state.json        # NEW — per-event edge-trigger state for push_policy
├── digest_queue.json      # NEW — demoted non-critical events awaiting next digest
├── .last_daily_digest     # date-stamp idempotency guard
├── .last_weekly_digest    # date-stamp idempotency guard
├── alert_history.json     # EXISTS — audit trail (keep)
└── .telegram_rate.json    # EXISTS — flood-guard counter (keep)

launchd/  (+ scripts/com.spa.*.plist)
├── com.spa.telegram_bot.plist     # NEW (KeepAlive) — replaces bot_commands
├── com.spa.digest_daily.plist     # NEW — 08:10 UTC
└── com.spa.digest_weekly.plist    # NEW — Sun 10:00 UTC

spa_core/tests/
└── test_telegram_single_authority.py  # NEW — CI guard: no rogue senders
```

**Composition with existing pieces:**
- `telegram_client.py` stays the **only transport**. `push_policy` and the digests
  call `_post_message`; the bot calls its own `_api_call` (it needs
  `editMessageText`/`answerCallbackQuery`, which the client doesn't expose) but
  still honors `flood_guard_ok()`.
- The flood guard + `alert_history.json` remain the safety net *under* the new
  policy layer — belt and suspenders.

---

## 7. FAIL-CLOSED / DETERMINISM / SECRETS (invariants)

- **Secrets:** creds only from Keychain `TELEGRAM_BOT_TOKEN_SPA` /
  `TELEGRAM_CHAT_ID_SPA`, never in files/env-committed. Owner-auth derives from
  `TELEGRAM_CHAT_ID_SPA`. Missing creds → bot serves nobody, push sends nothing
  (fail-closed), both log a WARNING.
- **Deterministic:** no LLM anywhere in the bot, policy, or reports (RULES.md §5).
  Every screen is a pure function of `data/*.json`. `callback_data` is the only
  state. Same inputs → same render.
- **Atomic writes:** offset, push_state, digest_queue, kill-switch all via
  `atomic_save` (tmp + replace). No direct `open(...,"w")` on state files.
- **Never raises:** every handler/builder catches all exceptions → friendly
  message or skipped section, never a crashed loop (existing pattern).
- **stdlib only:** urllib for all Telegram I/O.

---

## 8. BUILD PHASES

**Phase 1 — Stop the flood (highest ROI, low risk).**
- Build `push_policy.py` (whitelist + edge-trigger + ceiling + push_state).
- Rewire the ~8 critical monitors to call `push_policy` instead of `send_message`;
  delete the Telegram calls from the retire-list monitors (dashboard_watcher,
  analytics digests, tournament/research/promotion pushers).
- Unload the duplicate report launchd agents; keep one `digest_daily`.
- Add `test_telegram_single_authority.py` CI guard.
- *Outcome: ~67/day → ~5/day immediately.*

**Phase 2 — Consolidate reports.**
- Promote daily/weekly builders into `spa_core/telegram/reports/`, absorb unique
  fields from retired variants, add date-stamp idempotency, wire the two new
  digest launchd agents.

**Phase 3 — Interactive bot upgrade.**
- Add `router.py` + `views/` registry + `menus.py`; switch button taps to
  `editMessageText` drill-down; add owner-auth; populate the menu tree from the
  DESIGNER's UX doc. Replace `com.spa.bot_commands` with `com.spa.telegram_bot`.
- Fold `command_handler.py` into `views/` and retire it.

**Phase 4 — Cleanup & harden.**
- Delete retired sender modules + their plists; update `install_all_agents.sh`;
  update CLAUDE.md / SYSTEM_BRIEFING agent tables; verify the CI guard is green.

---

## 9. OPEN QUESTIONS FOR THE OWNER

1. **Daily ceiling = 10 Tier-1 pushes/day** — acceptable, or stricter (e.g. 5)?
2. **Go-live READY** as a Tier-1 push (one-shot) — yes? Any other milestones you
   want interrupted for (e.g. first profitable week, equity crossing $101k)?
3. **Family-fund / investor blasts** — confirmed a *separate channel*, out of
   scope for the ops-chat rebuild?
4. **Digest time** — 08:10 UTC daily ok, or local-time preference?
5. **Quiet hours** — suppress non-critical (digest) during a window, or always
   deliver the daily at the fixed time?

---

*Coordinate with `docs/TELEGRAM_BOT_UX.md` (DESIGNER) for the menu tree, button
labels, bilingual copy, and navigation flows. This document is the technical
contract; the UX doc is the surface.*
