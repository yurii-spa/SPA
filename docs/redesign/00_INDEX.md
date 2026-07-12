# SITE REDESIGN — SPEC PACKAGE INDEX

> Detailed, executable specs for `docs/SITE_REDESIGN_MASTER_BRIEF.md` (v3). The brief is the
> strategy/priority layer; THESE files are the task layer. Where a spec and the brief conflict,
> the spec wins (it's newer and more concrete).

**Reading order for the executing session:**

1. `docs/SITE_REDESIGN_MASTER_BRIEF.md` — strategy, workstreams, phase order, protocol (§7b).
2. `01_PHASE0_SELL_SPRINT_SPEC.md` — **execute first.** Task-by-task: files, copy (EN+RU),
   data sources, acceptance, verification. Tasks N1→N2, M1–M12, U1–U3, F1–F2.
3. `02_PAGE_INVENTORY_DISPOSITION.md` — all 95 pages with keep/move/cut/redirect verdicts;
   drives Phase 3 (and the noindex judgment set).
4. `03_PHASE1_SHELL_SPEC.md` — DashboardShell component spec + `/dashboard` re-shell approach
   + `ui/` kit extension list.
5. `04_PHASE2_CONVERSION_SPEC.md` — Stablecoin Safety Snapshot quiz (exact questions),
   CHK-DEMO demo report, Checkup report rebuild, SEO page briefs (E1).

**Standing rules (apply to every task in every spec):**

- Protocol = brief §7b (PROJECT_CONTROL/16): partition by file, announce via
  `scripts/log_session_change.py`, SPA pushes ONLY via `push_to_github_batch.py` (ABS paths),
  checkup repo = normal git. `cd landing && npm run build` exit-0 before every push.
- Numbers floor: no fabricated numbers; paper/backtest never labeled live; `realized` vs
  `target` vocabulary; tails shown where targets are shown. Numbers come from canonical
  sources only (`landing/src/lib/tier_bands.json` + live APIs) — see N1.
- **EN|RU parity** on every user-facing string (site is bilingual via the existing lang
  mechanism). Specs include both; if a spec misses RU, translate in the same register.
- Every new interactive element gets a `data-track` attribute (the beacon auto-relays clicks).
- Owner-gated sub-items: file a Q-OWN block in `docs/OWNER_DECISIONS_NEEDED.md`, ship the
  non-gated part, DO NOT block.
- **Never put a failing check into the CF Pages prebuild** (a prebuild exit-1 silently froze
  the site for days once). CI-only for lints (N2).

*Package authored 2026-07-12 by the analyst session, commissioned by the owner.*
