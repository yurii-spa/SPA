# ADR-521: Telegram Owner Control Plane — SPA seams for the Bridge bot, SPA bot safety, paused ≠ down

- **Status:** ACCEPTED · 2026-09-30 · owner: @yurii (owner directive «Telegram / Owner Control Plane»,
  autonomous execution authorised in the same directive)
- **Scope:** Studio OS seams (`spa_core/studio_os/director_report.py`, `spa_core/owner_remote/cli.py`),
  the SPA Telegram bot's safety boundaries, and fleet health's reading of an owner pause. No money
  path, no RiskPolicy/kill-switch logic, no execution, no public-site numbers.

## Context

The owner runs two Telegram bots and asked for them to be mapped from evidence and given distinct
responsibilities: the **Bridge bot** (`com.studiobridge.telegram`, separate repo) as the Studio OS /
Owner control plane, the **SPA bot** (`com.spa.telegram_bot`) as the product surface. The audit of
2026-09-30 (after the reboot) found:

1. no Director view anywhere that answers «что происходит / что сломалось / что нужно от меня» from
   canonical sources; the Owner Remote GREEN answers read `studio_shell/read_model.json`, which the
   production tree does not carry — so they answered «✅ ничего не сломано» from an empty projection;
2. ADR-493's canonical intake seams (classifier, confirm-first task, idea home, decision draft, local
   whisper) were reachable only from a loopback web server an iPhone cannot reach;
3. SPA bot: `/resume` wrote `active:false` over ANY manual kill-switch latch, whoever armed it; the
   free-text classifier ran `claude -p … --dangerously-skip-permissions` inside the production tree;
   the liveness watchdog (240 s) killed the bot mid-voice-transcription (≤ 450 s) after the offset was
   already advanced, losing the voice note; replies over 4096 were refused silently; the ☰ menu
   advertised `/pause /resume /why /help`, which typed only opened the home panel;
4. the owner's pause of `com.spa.mission_tick` (`bootout` + `launchctl disable`) read as an outage:
   agent_health CRITICAL for the whole fleet, self_heal `bootstrap` every 5 min, reboot_verify at
   login — only launchd's refusal kept the paused workload from being revived.

## Decision

1. **Director report** (`python -m spa_core.studio_os.director_report`): one read-only builder over
   the canonical sources — trusted runtime + approved release, launchd, stale-aware agent_health,
   tracker cards + `status_trail`, origin/main history in the full mirror clone, paper-track status,
   disk. Sections СТАТУС · РАБОТАЕТ · СДЕЛАНО · В РАБОТЕ · ПРОБЛЕМЫ · НУЖНО ОТ ЮРИЯ, drill-downs
   system/work/product/owner/alerts. Every unreadable source is «не измерено» (inv. #17). `--mark`
   records the Owner's look (`data/director_report_state.json`) so «сделано с прошлого отчёта» has a
   real anchor.
2. **Intake CLI** (`python -m spa_core.owner_remote.cli plan|confirm|cancel|transcribe`) over the
   existing gateway: `plan` never writes; `confirm` writes exactly once per token (task → canonical
   inbox card, idea → `docs/ideas`, decision → PROPOSED draft); RED is refused at plan AND re-checked
   at confirm. The Bridge bot calls it as a subprocess and never writes canonical state itself.
3. **SPA bot safety:** `/resume` lifts only the stop Telegram armed (`reason == manual_telegram`),
   fail-closed on an unreadable file; the classifier runs with `--tools "" --strict-mcp-config` from
   a temp cwd (no built-in tools, no MCP servers — it can only read its prompt); voice declares a
   bounded busy window the watchdog honours; replies are fitted to 4096 UTF-16 units; the ☰ menu lists
   only commands that do what they say.
4. **Paused ≠ down:** `launchctl print-disabled` is read by agent_health (`OK` + note «intentionally
   disabled»), self_heal (never expected, never revived) and reboot_verify (not bootstrapped, reported
   separately). Unreadable override list ⇒ nothing is treated as paused (over-reports, never hides).

## Consequences

- The Owner gets a truthful one-screen report and confirm-first text/voice intake on the iPhone via
  the Bridge bot; SPA remains the single writer of cards/ideas/decision drafts.
- No scheduled report is added (the SPA daily digest already exists; Bridge b19.6.28 withdrew a
  misleading one).
- Tests: `test_owner_control_plane.py`, `test_spa_bot_safety_boundaries.py`,
  `test_launchd_disabled_is_not_down.py`; the `test_ask_router.py` fake accepts `cwd=` (journal).
