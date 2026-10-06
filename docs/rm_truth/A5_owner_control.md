# A5 · Owner Control: decisions, Telegram, Director OS / Mission Control

RM-TRUTH-01 Phase 1 (read-only) · measured 2026-10-05 ~08:15Z · origin/main = `b36acda46` (mirror HEAD = prod tree's local `origin/main`).
The machine-readable register is in `A5_register.json` (16 components, 17 owner gates, 3 Telegram contours).

---

## 1. Owner decision flow

### 1.1 Five copies of the queue, three different answers

| Surface | Reads | needs-owner shown | Evidence |
|---|---|---|---|
| origin/main tracker (canonical) | git | **11** | frontmatter parse of `SPA_mirror/nimbalyst-local/tracker` and `_BOARD.md` "ждёт владельца: 11" |
| prod tree tracker | disk | **12**: the 11 + `owner-decision-utochnenie-po-zametke-prikaz-vladeltsa-u` | untracked `??`, created 2026-10-03 by intake |
| SPA bot "что на мне?" and pushes | prod tree (`queue._resolve_tracker_dir` → `live_root`; `owner_decisions.pending_decisions`) | **12** open pushes, all `choice=None` | `data/telegram_owner_decisions.json`: 11 pushed in one batch 2026-10-01 07:01Z, 1 on 2026-10-03 09:49Z |
| Mission Control :8790 | origin cards + prod answers (`director_report.py:~349`, `mission_control.decision_item`) | **11** + 1 ACCEPTED (mission_tick) | `mission.json` `decisions.counts` |
| Bridge bot `/needs` | `director_report` (same overlay as MC) | 11 | ADR-521, `director_report.py` |
| Director OS :8788 | prod tree + `data/owner_blockers.json`, `live_trading_gate.json`, `gate_status.json`, `KANBAN.json` | **6 "ждёт ВАШЕГО решения"** · **11 "дефекты очереди"** · 1 to re-measure | rendered page text |

The diff:
- **The prod-only intake card is invisible to Mission Control, the board and Bridge `/needs`.** The SPA bot still pushed it to the owner, with ack buttons.
- **Each surface assigns ADR-285 subjects with its own heuristic, and the two heuristics disagree.**
  - Mission Control's `risk_class()` (`mission_control.py:286-301`) takes the first keyword hit. It gives every card a subject, and "Закрыть три PR" gets "1 · real money" because the card contains "ключ".
  - Director's `owner_decisions.SUBJECT_HINTS` calls 10 of the 12 cards queue defects.
  - So the same owner sees 11, 12 or 6 depending on the screen.
- **Mission Control has a second "owner decisions pending" number.** `capital.live_readiness.owner_decisions_pending = 4` sits on the same page as decisions = 11. The 4 come from `capital_shadow/read.py:88`: four go-live preconditions that have no card.

### 1.2 Worktrees (43 `/tmp/spa_*` trackers plus 12 `.claude/worktrees`, scratchpad and Bridge worktree trackers)

- 56 distinct needs-owner card ids appear across all worktrees. Every worktree-only one is a **stale snapshot**: the card exists on origin as `ingested` or `owner-accepted` (`no_union_status.txt`).
- **No orphaned owner question was found in a worktree.** Three cards (`sait-*`, `tri-bumazhnyh-portfelya`) exist only on origin and in worktrees, not in prod; they are already `ingested`.

### 1.3 Prod ↔ origin drift (`scripts/check_tracker_drift.py --tracker-dir <prod>`, rc=1)

- Counts: hidden 494 · diverged 170 · **undelivered 47** · stale 5. The prod tree has 746 cards, origin 1193.
- The undelivered 47 are:
  - 44 intake cards `done` from 2026-08-11
  - 1 `ingested` card
  - the needs-owner `prikaz` card
  - 1 `new` inbox card from today
- **13 owner closures exist only in prod.** They are `owner-done` or `owner-accepted` in prod and `ingested` on origin, e.g. `gde-granitsa-reshai-sam`, `tier-steakhouse-2026-08-29`, `sait-pokazyvaet-chisla-ot-20-sentyabrya`.
  - Mission Control overlays these correctly.
  - Origin-only readers (the board, `check_owner_order_starvation`) do not.
- **Root cause.** Both Telegram intakes (`inbox_intake.create_card`, and Bridge → `owner_remote.cli confirm`) and the bot's answer writer write into the prod tree. Nothing carries prod-only cards to origin: `first_delivery.py` only moves cards origin → prod.

### 1.4 Options that cannot render as phone buttons

I ran the bot's own parser (`owner_decisions.parse_options` / `build_keyboard`) on every pending card (`parse_probe.txt`).

- **`owner-decision-disk-mac-mini-zabit-pod-nol-odin-zhurnal`: 0 options parsed, `has_unparsed_options=True`.** It was pushed with `buttons=False` on 2026-10-01 and has not been healed.
  - The variants are written as "(а)(б)(в)" inside "Шаг 2", and the card bundles three questions.
- **Labels cut mid-phrase:**
  - `dva-mesta` A: "…в соответствие с уже"
  - `potolok-base` A: "Главное — `spa_core/risk/policy.py`: это"
  - `stoimost-perekladki` 1: "Объявить допуск расхождения «заряжено ↔"
- **Raw `**markdown**` and a URL appear in button labels** on `zakryt-tri-PR`.
- **Callback size is not the problem on the SPA bot.** The longest is 20 B (`act:od:<pid>:<n>`), limit 64.
- **The Bridge bot does hit the limit.** `apply_preview <run_id>` measured 65 B, and `_safe_keyboard` silently drops that button.

### 1.5 Active gates vs ADR-285 (full table in the register's `owner_gates`)

**Belongs to the three subjects (or the "physically can't" category):**

| Card | Subject | Notes |
|---|---|---|
| earn-defi channel | 3 + physical | Owner already chose variant 1 on 2026-09-16. Only the owner's action (create the channel, send the chat_id) is pending, 26 days now. It is for the separate earn-defi product. |
| tier labels (`dva-mesta`) | 2 | The morpho half is already decided by ADR-173. Only pendle T2/T3 is genuinely open. |
| pre-trade re-check thresholds | 1 (future live) | Option Б (defer) is legitimate. |
| close 3 PRs | physical | PAT lacks PR scope. |
| disk | partial 3 | Step 2 is worktree deletion. The premise is stale: `df /` shows **73 GiB free** now. Step 3 (log caps) belongs to the agent. |

**Queue defects (do not belong):**
- Base-cap canonical copy: the value does not change.
- 5% cash: one rule or two.
- The `prikaz` intake clarification.
- Four paper-allocator logic cards (optimum, persistence, move cost, oscillation): contested. They cite the owner's CIO spec §22/§49, but no real money moves. Optimum option 1 is explicitly advisory-only.

**Latent go-live gates with no card** (correctly not asked during the paper stage): custody, audit, legal (`data/owner_blockers.json`), live_trading_gate owner_acceptance, and the four capital_shadow preconditions.
- Director renders "приёмка… не получена 107 дней" from `data/gate_status.json`, a file frozen since 2026-06-20 with `paper_trading_day_count: 2`. That is a dead source shown as a live gate.

---

## 2. Telegram — three contours, not two

| | SPA bot | Bridge bot | OpenClaw (found) |
|---|---|---|---|
| Bot / launchd | id 8898892185 `com.spa.telegram_bot` | id 8830839383 `com.studiobridge.telegram` b19.6.33 | @F1rst_openclaw_bot id 8723894167 `ai.openclaw.gateway` :18789 |
| Token | Keychain `TELEGRAM_BOT_TOKEN_SPA` | Keychain `STUDIO_BRIDGE_TELEGRAM_TOKEN` (SPA token deliberately not used as fallback) | **plaintext `~/.openclaw/openclaw.json`** |
| Purpose | Product surface: alerts, views, owner-decision buttons, kill switch, `/task` + voice intake | Studio OS control plane: `/report /needs /alerts /work /system /product`, confirm-first intake, Bridge gates | UNKNOWN; has exec-approvals |
| Authority | Arms the kill switch (paper → cash). `/resume` only clears the `manual_telegram` latch (`bot.py:1044-1090`). No execution, no increase. Owner-chat fail-closed (`router.is_owner`). | No money. RED text is refused twice. SPA writes only through `owner_remote.cli`. | UNKNOWN |
| Health | Beacon fresh (~13 s), caps [alert_actions, owner_decisions] | `owner_actions.log` heartbeat ~30 s; the log is unbounded at 190k lines | Running since 09-30 |

- **Overlap.** Both bots offer status and both have text/voice intake into the same tracker.
  - The SPA bot writes cards directly with no confirm step.
  - The Bridge bot confirms first.
  - ADR-521 assigned roles (Bridge = control plane, SPA = product surface), but the SPA bot's `/task` and voice intake were never removed.
- **`docs/TELEGRAM_AUDIT.md` is from 2026-06-18** and covers only notification spam. It is superseded in substance by ADR-521.
- **Recommendation: KEEP_SEPARATE.** Token isolation avoids 409 conflicts, and authority stays split: decisions and the kill switch live only in the SPA bot. REPAIR the duplicated intake by routing SPA `/task` and voice through `owner_remote.cli` confirm-first, or retiring them. OpenClaw: UNKNOWN_PURPOSE, owner to confirm.

---

## 3. Owner cockpits

**Doctrine** (`SPA_control_plane_audit/16-…ARCHITECTURE.md:305-308`): "Director OS reads. It derives… never becomes a second backlog, a second memory or a second source of truth."
- Problems: "INCIDENT против PROBLEM_CANDIDATE решает доказательство" (`docs/operations/director-os-phase4-reliability.md`).
- The phrase "Problems lifecycle" appears nowhere.
- The doctrine ADR "ADR-469" cited by ADR-492/552 is now an unrelated ADR (renumbering). The doctrine was never promoted under its own number.

| Surface | Live? | Data source | Verdict |
|---|---|---|---|
| Mission Control :8790 (ADR-552) | yes, bundle every 5 min, healthz 381 s | one `mission.json`; origin cards + prod answers | **REPAIR**: subject labelling, prod-only cards, two "pending" numbers |
| Director OS :8788 (Cartographer) | yes, hourly; publish frozen 09-20; RU only | prod tree + data | **MERGE** into MC (ADR-552 itself says it "DUPLICATES"). Its provenance and subject triage is more honest. No retirement decision exists. Bundle work dir is 4.8 GB. |
| director_report (Telegram `/report`) | yes | canonical read model | KEEP |
| studio_shell :8778 | not running; absent from prod | `read_model.json` | SUPERSEDED (answered GREEN from an empty projection, ADR-521) |
| dashboard :8767 | yes | **repo-root listing incl `.git/` (`/.git/config` → 200)**, loopback | SUPERSEDED / retire |
| familyfund :8766, landing `/admin/*`, `/dashboard`, `/cockpit*`, cc-kanban :4455, Nimbalyst board | various | — | DEFER (not owner cockpits / backup monitors). Board: KEEP. |
| logos :8777 | yes | separate project | out of scope |

**Mission Control and UNKNOWN.** Mostly honest:
- 30 contract rows each declare their unknown form (`NOT_MEASURED`, null vs [], "UNKNOWN (never 0 by default)").
- Every decision shows `evidence: UNKNOWN`.
- Real capital is fixed at `LIVE_NOT_APPROVED $0`.
- Backups say "offsite is on the same disk".

There are two dishonest spots:
1. `risk_class` turns a keyword guess into a subject label and never yields UNKNOWN for these cards, so queue defects are hidden. Director shows the opposite verdict.
2. `decisions._meta.state=HEALTHY` while the prod tree holds a needs-owner card that Mission Control cannot see.

**Today's state:** system CRITICAL (`com.spa.novel_edge_rnd`), 89 agents (84 ok / 4 warning / 1 critical), disk 70.9 GB free.

---

## 4. Recommended actions (Phase 2 candidates)

1. RECONNECT the prod tree to origin for owner cards: a carrier for `undelivered` owner-decision and inbox cards plus owner-done closures. Or make every intake write straight to origin.
2. Use ONE ADR-285 subject classifier, shared by Mission Control, Director and the bot. A card should declare `subject:` in frontmatter, and a missing declaration should show as UNKNOWN / queue defect.
3. Re-triage the 6 non-belonging cards back to the agent. Convert earn-defi into an owner-action item. Split the disk card and re-measure it (73 GiB free).
4. Fix the option grammar: parse "(а)(б)(в)", strip markdown, cut labels at word boundaries; add a pre-push lint.
5. Write a supersede ADR for Director OS → Mission Control, carrying its provenance and triage over. Retire :8767 and studio_shell.

## Evidence files (scratchpad/rmtruth/)

`no_SPA_mirror.txt`, `no_SPA_Claude.txt`, `no_worktrees.tsv`, `no_union_status.txt`, `parse_probe.txt`, `mc_mission.json`, `tracker_drift_prod.json`, `build_a5.py`.
