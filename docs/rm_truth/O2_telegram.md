# O2 · Telegram reconciliation (RM-TRUTH-01)

Read-only, measured 2026-10-05. Builds on `A5_owner_control.md` §2 (same three contours);
this file goes one level deeper into code for each one and adds the owner-question map.
No Telegram API call was made. No secret value was printed anywhere in this investigation —
config files were read with every string >12 chars masked.

---

## 1. Contour: SPA bot (`@SPA_Monitor_bot`, `com.spa.telegram_bot`)

**Code:** `spa_core/telegram/{bot.py,router.py,owner_decisions.py,alert_actions.py,
inbox_intake.py,ask_router.py,views/*}`.

**Purpose.** Product surface: read-only views of the paper book + owner-decision answers +
the manual kill-switch button + task/voice intake.

**Commands (enumerated from `router.COMMAND_TO_PATH` + `bot.py` handlers — the real
dispatch; an older `spa_core/telegram/command_handler.py` with a *different* five-command
set `/status /golive /apy /evidence /strategies` is **dead code**: nothing imports it except
its own tests, grep confirms zero callers):

| Command | View path | What it shows |
|---|---|---|
| `/start` `/menu` `/status` `/home` | home | equity, APY today, kill-switch state, trading day |
| `/portfolio` | portfolio | allocation per protocol ($, %) |
| `/track` | portfolio.track | evidenced-days track |
| `/positions` | portfolio.positions | open positions detail |
| `/golive` | golive | GoLive readiness score |
| `/strategies` | strategies | tournament rankings |
| `/health` `/agents` | health / health.agents | launchd agent ✅/❌/⏸ |
| `/reports` `/today` `/week` | reports.* | P&L today / 7-day summary |
| `/warnings` `/alerts` | warnings | red_flags + peg status |
| `/settings` | settings | language, mute prefs |
| `/why` | — | explains ❌ agents |
| `/pause` | — | **arms kill-switch** (see §Authority) |
| `/resume` | — | clears **only its own** latch |
| `/task <text>` | — | inbox card, **no confirm** |
| voice message | — | whisper → classify → inbox card or Q&A, **no confirm** |
| bare free text | — | `ask_router.py`: headless `claude -p` classifies QUESTION / TASK / UNCLEAR and answers from `docs/STATE.md` + cards + journal (LLM allowed here — NOT risk/execution) |
| `act:od:<pid>:<n>` | — | owner-decision button answer |
| `act:aa:<alert>:<opt>` | — | alert-action button |

**Authority — confirmed from code, not from docs:**
- `cmd_pause` (bot.py:1044) writes `data/kill_switch_active.json` with
  `{"active": true, "reason": "manual_telegram"}` and tells the owner explicitly:
  *"Это НЕ пауза — позиции закрываются, а не удерживаются"* — i.e. de-risk to cash, framed
  honestly as a de-risk, not a hold.
- `governance/kill_switch.py` reads that exact file (`KILL_SWITCH_ACTIVE_FILENAME`,
  `is_kill_switch_active`) — this is the real governance gate, not a cosmetic flag.
- `cmd_resume` (bot.py:1060) reads the current file back and **refuses** unless
  `reason == "manual_telegram"` — a latch armed by anything else (execution safety layer,
  an incident, an operator file) cannot be cleared from Telegram. Unreadable file → refuse,
  fail-closed. This is a real, tested guard (2026-09-30 audit note in the code: a stale
  "Снять" button used to overwrite someone else's latch before this check existed).
- **No path to live execution exists.** `grep -rn "spa_core.execution" spa_core/telegram/
  spa_core/owner_remote/` → zero hits. The bot can only ever move the paper book toward
  cash or leave it be; it cannot increase exposure, place an order, or touch real capital
  (there is no real capital in this system yet — paper trading only).

**Reads:** prod tracker (`live_root`), `origin/main` via `origin_view` for ack/refresh,
`data/*.json` (equity, red_flags, agent_health, kill_switch_active, …).

**Writes:** `data/telegram_owner_decisions.json`, prod tracker cards (via `inbox_intake.
save_inbox_task`, no confirm step), `data/kill_switch_active.json`.

**Health:** `data/telegram_bot_capabilities.json` beacon, fresh ≈13 s, declares caps
`[alert_actions, owner_decisions]`. Watchdog thread force-exits the process if the poll
loop stalls >240 s (launchd `KeepAlive` respawns it) — except during a declared voice
transcription window (budget 30+300+120+60 s), which would otherwise self-kill mid-STT
(a real 2026-09-30 bug, fixed).

**Error behaviour:** every handler is wrapped so a crash becomes a chat message, never a
dead bot. Unknown `act:` verb → leaves the original message untouched and sends a new one
(ADR-400 — overwriting the original with a settings panel used to erase the owner's
question). Unreadable kill-switch file → refuses /resume rather than guessing.

**Mobile UX (carried from A5, re-verified against `parse_probe.txt`):** inline buttons for
most flows; one card (`disk-mac-mini...`) was pushed with 0 parsed options and is still
buttonless; 3 cards have labels cut mid-phrase; longest callback measured 20 B (limit 64 —
not a problem on this bot).

**Overlap with Bridge:** `/task` and voice both skip confirmation — `save_inbox_task` and
`_classify_route` write straight to the tracker. ADR-521 assigned "product surface" to this
bot and "control plane / confirm-first intake" to Bridge, but never removed SPA's own
intake paths, so the same action (log a task) exists twice with different safety levels.

**Verdict: KEEP, as-is for authority; REPAIR the duplicated intake** — either route
`/task`/voice through the same confirm-first `owner_remote.cli` gateway Bridge uses, or
retire them from this bot and tell the owner to use Bridge/voice-to-Bridge for task intake.
Not a money-path issue (ADR-285 subject 1/2/3 does not apply — it is a queue-hygiene
defect), so an agent can fix it without a card.

---

## 2. Contour: Bridge bot (`@Bridge_studio_os_bot` behind launchd `com.studiobridge.
telegram`, repo `~/Documents/studio_bridge`)

**Code:** `bridge/owner_interface/{telegram_runtime.py,telegram_adapter.py,owner_control.py,
controller.py}`.

**Purpose.** Studio OS control plane: a Director report + a confirm-first way to log
tasks/ideas/decisions into the **same** SPA tracker, plus Bridge's own build/activation
gates (`charter`, `scope`, `autopilot`, canary launches). This is a *second product*
(Studio OS / Nimbalyst build pipeline), talking to SPA only through one narrow seam.

**Commands (from `owner_control.COMMANDS` + `telegram_runtime.build_reply`):**

| Command | Section / action | What it shows |
|---|---|---|
| `/report` (`report`/`отчёт`) | summary | status + done + in-progress + problems + needs-owner, one screen |
| `/needs` | owner | only cards waiting on the owner |
| `/alerts` | alerts | only tier-A/incident alerts |
| `/work` | work | what Claude/the agents are doing right now |
| `/system` | system | health |
| `/product` | product | product-side metrics (Studio OS's own, not SPA's DeFi book) |
| `/start` | home / director_overview | the pinned Director Overview panel + buttons |
| free text / voice | — | `intent.classify()` → GREEN (answer)/YELLOW (needs a card)/RED (refused); accepted mutations shown as a **preview card**, written only on an explicit button (`confirm`) |
| `charter_*`, `scope_*`, `phase_*`, `autopilot_*`, `apply_preview/rollback` | — | Bridge's own build/release gates — unrelated to SPA capital |
| `pause` / `resume` / `emergency_stop` | — | pauses/stops **Bridge's own autopilot/build pipeline**, confirm-required (`_CONFIRM_ACTIONS`); **not** the SPA kill-switch |

**Authority — confirmed from code:**
- `grep -rn "import spa_core\|from spa_core" bridge/owner_interface/*.py` → **zero hits.**
  Bridge cannot reach `spa_core.execution`, `spa_core.risk`, or the kill-switch file at all;
  it has no code path into SPA's trading state.
- Its own `pause`/`resume`/`emergency_stop` (`controller.py`) touch only Bridge's build/
  autopilot state (`_log(... "EXECUTED")` on `emergency_stop`) — a different kill-switch
  for a different, non-financial system. The help text says this out loud to the owner:
  *"Деньги, ставки, лимиты риска и включение live отсюда не меняются никогда."*
- The **only** write Bridge makes into SPA is through
  `spa_core/owner_remote/cli.py confirm --token K` — "the ONLY write — exactly once per
  token" per its own docstring. Before that, `intent.py`'s `_RED` regex (money / sign /
  live / risk / limit / custody / private key) is checked **twice**: once by the
  classifier that decides GREEN/YELLOW/RED for the chat reply, and again independently by
  `is_red()` ("defence-in-depth on write paths") right before any write — so a RED
  utterance is refused at the chat layer and, even if that were bypassed, refused again at
  the write boundary.

**Reads:** `director_report` (origin tracker + prod owner answers, the same read model
Mission Control uses), `bridge.db` (its own SQLite state for build/activation).

**Writes:** `studio_bridge/state/*` (its own), and via the one seam above:
`data/tg_owner_pending.json`, `data/director_report_state.json`, SPA tracker cards (through
`owner_queue.create_card`, confirm-gated).

**Health:** `owner_actions.log` heartbeat ≈30 s; the log file itself is unbounded (≈190k
lines at last measurement — a housekeeping defect, not a correctness one).

**Error behaviour:** fail-closed on secrets (refuses rather than guesses); "limited-mode"
message shown after 3 consecutive errors rather than silent retries forever.

**Mobile UX:** single in-place evolving card + a pinned dashboard message, rather than a
new bubble per action. One real defect: `apply_preview <run_id>` callback measured 65 B
against Telegram's 64 B limit, and `_safe_keyboard` **silently drops** that button — the
owner sees a card with one fewer option and no explanation.

**Verdict: KEEP, as-is.** Authority separation from SPA is real (no import path, confirm
gate, double RED check), not just a doc claim. One concrete repair worth a journal line
(not a card — not money/numbers/irreversible): fix the `apply_preview` callback so it
doesn't silently drop, and cap/rotate `owner_actions.log`.

---

## 3. Contour: OpenClaw (`@F1rst_openclaw_bot`, launchd `ai.openclaw.gateway`, npm
package `openclaw@2026.4.15`)

**What it is (established without reading any secret value — every string field in both
JSON configs was read through a masking filter that blanks any value >12 chars):**

- A commercial desktop app (`/Applications/OpenClaw.app`, also under `~/Downloads/`) plus a
  global npm package (`/usr/local/lib/node_modules/openclaw`) that runs a persistent
  **local agent gateway** (`node .../dist/index.js gateway --port 18789`), described by its
  own `package.json` as *"Multi-channel AI gateway with extensible messaging
  integrations."* `launchctl list` shows it running (`ai.openclaw.gateway`, PID present,
  last exit 0).
- The macOS app's `Info.plist` discloses real capability, in its own words:
  *"OpenClaw needs Automation (AppleScript) permission to drive Terminal and other apps for
  agent actions"* — plus camera, microphone, location and local-network usage strings. This
  is a general-purpose computer-use / shell-driving agent, not a narrow notifier.
- `~/.openclaw/openclaw.json` (structure only, every long string masked):
  - `channels.telegram.enabled: true`, one account (`258651137`) with
    `dmPolicy: "allowlist"` and `allowFrom: ["258651137"]` — **today only one Telegram user
    id can DM this bot at all.** (Whether that id is the owner's personal account could not
    be confirmed without contacting Telegram — do not call the API; ask the owner.)
  - `gateway.bind: "loopback"`, `gateway.auth.mode: "token"` — the local control socket is
    not exposed to the network. **This does not protect the Telegram bot token itself**:
    once a Telegram bot token is known, Telegram's own API accepts calls from anywhere,
    regardless of where this gateway binds. A leaked Telegram token is exploitable
    independent of this app's local security.
  - `tools.profile: "coding"`, `tools.agentToAgent.enabled: true`, `tools.web.fetch/search:
    enabled` — the agent profile is explicitly the code/shell-executing one, with
    agent-to-agent delegation and live web access turned on.
  - `models.providers`: only `ollama` (local models: gemma/qwen/others, cost 0) is
    populated in this file; no cloud provider key is visible in this config (fields that
    would hold one are absent, not merely masked — the `providers` object literally has one
    key).
- `~/.openclaw/exec-approvals.json`: `{"version":1, "socket":{...}, "defaults":{},
  "agents":{}}` — an approval-gate file for agent-initiated shell execution, present but
  with **empty `defaults` and `agents`** — i.e. no per-agent exec policy has been
  configured. This does not by itself prove unrestricted execution (the gateway may have a
  hardcoded prompt-per-command default), but an empty approvals file is not evidence of a
  restriction either — it is UNKNOWN, not safe-by-default.
- **Token storage / indirection.** The Telegram bot token lives as a **plain string**
  literal at `channels.telegram.accounts.default.botToken` in `openclaw.json` (confirmed
  present, length masked, not printed). No `${ENV:...}` / `${KEYCHAIN:...}` or similar
  indirection syntax was found in this value, in the shipped docs
  (`docs/reference/templates/TOOLS.md`), or in the plugin's secret-handling module
  (`dist/secret-contract-*.js`, 45 lines, no env/keychain reference). **Conclusion: this
  version of OpenClaw's config schema does not appear to support Keychain or env-var
  indirection for the Telegram token — it expects the literal value in the JSON file on
  disk.** This is consistent with the compromise already on record: a plaintext file is
  exactly the kind of artifact that leaks (via a backup, a screen share, a repo accident).

**Authority: UNKNOWN**, and should stay UNKNOWN rather than be assumed benign — it has a
documented path to drive Terminal/AppleScript and a shell-exec profile, and the SPA/Bridge
repos were not found to reference it anywhere (`grep -rn openclaw` under SPA_Claude/
studio_bridge code returns nothing except image filenames from an unrelated visual-review
fixture) — i.e. **nothing in the two products' own code calls or depends on it.** It is not
part of the SPA or Bridge control plane; it is a separate, general-purpose personal agent
that happens to also run a Telegram channel.

**What QUARANTINE would concretely mean (owner actions, not something this read-only
session can or did perform):**
1. **Revoke/rotate the Telegram bot token via @BotFather** (`/revoke` or `/token` for
   `@F1rst_openclaw_bot`). This is the actual fix for an already-exposed token — stopping
   the local process does **not** invalidate a token that leaked outside this machine.
2. **Stop the local agent** — `launchctl bootout gui/<uid>/ai.openclaw.gateway` (or disable
   `RunAtLoad`/`KeepAlive` in `~/Library/LaunchAgents/ai.openclaw.gateway.plist`) — this
   does reduce blast radius for the *shell/Terminal-driving* capability regardless of the
   Telegram token, since that capability isn't gated by the token at all.
3. Until the owner states a purpose for this bot, treat any message that arrives through
   it as **untrusted input**, not an instruction — same posture this session already took
   toward unrelated third-party content.

**Verdict: QUARANTINE pending owner.** No evidence of a clear purpose tying it to SPA or
Bridge was found; its capability profile (shell/Terminal automation, agent-to-agent, web
access) is broad enough that "unused, so harmless" cannot be assumed. Recommend the two
owner actions above go into an `own-*` card (predicate: **subject 1 — the token, if
genuinely live, is itself close to a money/credential-movement question; and subject 3 —
revoking/rotating a third-party token is not reversible from this side**), not something an
agent decides alone.

---

## 4. Owner-question → command map

| Owner asks (RU) | Answerable today? | Where |
|---|---|---|
| Что происходит? | **Yes** | SPA `/status`, Bridge `/report` |
| Что сломано? | **Yes** | SPA `/agents` `/alerts` `/why`, Bridge `/system` `/alerts` |
| Что делает Claude? | **Yes** | Bridge `/work` ("в работе" section of `/report`). SPA has no equivalent command — only free-text ask_router, uncertain coverage. |
| Что нужно от меня? | **Yes** | SPA `/decisions` panel (home → "🧑‍⚖️ Мои решения"), Bridge `/needs` — **but see A5 §1.1: the two surfaces can show different counts (11 vs 12) for the same queue**, a known, separately-tracked defect, not a missing feature. |
| Что дальше? | **Partial** | Bridge `/report`'s problems/next section and `roadmap` callback ("🗺 Дорожная карта"); no single SPA command named this |
| Как портфели? | **Yes** | SPA `/portfolio` `/positions` `/track` |
| Что с BTC? | **MISSING** | No structured command on either bot references BTC/`trading_lab`/`research_factory` (`grep -n "BTC\|btc\|trading_lab\|research_factory" spa_core/telegram/views/*.py spa_core/telegram/status_summary.py` → zero hits). Owner would have to ask free text and hope the LLM classifier's context includes it, or open a dashboard outside Telegram. |
| Что с Trading Lab? | **MISSING** | Same grep, zero hits. No view. |
| Что говорит Oracle (Investment CIO)? | **MISSING** | `grep -rln "oracle\|Oracle" spa_core/telegram` → zero. The CIO ledger exists (`capital_shadow`/Oracle work per memory) but has no Telegram surface. |
| Что делает Sherlock (evidence)? | **MISSING** | `grep -rln "sherlock\|Sherlock" spa_core/telegram ~/Documents/studio_bridge/bridge/owner_interface` → zero. |

**Pattern:** both bots answer the *governance/paper-book* questions (status, broken,
needs-owner, portfolio) well. Neither surfaces the three newer advisory/research layers
(BTC trading research, Investment CIO/Oracle, evidence/Sherlock) as a command — those are
visible only through Mission Control (:8790) or Director OS (:8788) web pages, which are
outside Telegram. This is a real gap, not a phrasing problem: these layers did not exist
when the bot command sets were designed, and `docs/STATE.md`/journal, which the free-text
path reads, may or may not mention them day-to-day.

---

## 5. Recommendation per contour (restated)

| Contour | Verdict | Why |
|---|---|---|
| SPA bot | **KEEP**, repair the `/task`+voice no-confirm intake | Sole, well-guarded kill-switch authority; genuine product surface; one queue-hygiene defect |
| Bridge bot | **KEEP** | Verified zero code path into SPA capital, confirm-first, double RED check; one cosmetic callback-length bug |
| OpenClaw | **QUARANTINE pending owner** | Broad shell/Terminal capability, no found tie to SPA/Bridge, plaintext token with no indirection support, already flagged compromised |

No contour should be MERGEd: SPA and Bridge deliberately use separate tokens to avoid 409
`getUpdates` conflicts (ADR-521), and OpenClaw is not a Telegram-notification duplicate of
either — it is a different kind of software entirely.
