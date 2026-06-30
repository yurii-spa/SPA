# SPA — Handoff to a parallel Claude Code instance
**As of 2026-06-30 · origin/main @ `dd5d7282c` · local in sync · suite green**

---

## 0. TL;DR — read this first
- The repo is at `/Users/yuriikulieshov/Documents/SPA_Claude`, branch `main`, **local HEAD == origin/main == `dd5d7282c`** (just synced, tracked-dirty 0).
- All work from the prior session is **already on `origin/main`** (it was pushed continuously). Nothing is unpushed.
- A backup of a divergent WIP commit is at branch **`backup/pre-merge-20260629-2335`** — ignore it unless you need to recover something.
- The desk is in **paper trading**, building an honest 30-day go-live track (currently **~8/30 evidenced**, target ~2026-07-21). **No real capital moves.** Read `CLAUDE.md` before touching anything.

---

## 1. ⚠️ GIT & PUSH WORKFLOW — the #1 operational gotcha
**Pushes go through `push_to_github_batch.py` (GitHub Git Data API), which commits DIRECTLY to `origin/main`'s tip and does NOT update local git.** Consequences:
- `git log` / `git status` locally look STALE even right after a successful push — that's expected, not a bug.
- To **push**: `python3 push_to_github_batch.py --files <ABSOLUTE paths…> --message "…"` (1 commit per call; ABSOLUTE paths only — relative collapse to basename). It returns `OK: 1 коммит <sha> со N файл(ами)`.
- To **delete a remote file**: GitHub Contents API DELETE (see the inline python used for the `monitor/`→`monitoring/` rename cleanup in session history) — `push_to_github_batch.py` cannot delete.
- **To sync local ↔ origin: `git fetch origin && git reset --hard origin/main`** (or `git pull`). **DO THIS AT SESSION START** — the local repo had drifted **15,450 commits** behind because nobody pulled while the autonomous fleet + API pushes advanced origin. If you `git add -A && git commit && git push`, it will be **rejected (non-fast-forward)** and a force would CLOBBER origin's real history. Never force-push `main`.
- The autonomous fleet (`com.spa.autopush` every 90 min, daily_cycle, strategy_registry auto-writer) **also** pushes to origin continuously — origin moves on its own.
- Secrets: PAT in Keychain `GITHUB_PAT_SPA` (read at runtime, NEVER hardcode — there was a leak incident). Telegram: `TELEGRAM_BOT_TOKEN_SPA` / `_CHAT_ID_SPA`. Python: `/Users/yuriikulieshov/miniconda3/bin/python3`.

---

## 2. What this session built (all on origin, newest first)
| Commit | What |
|---|---|
| `dd5d7282` | **Aggressive Lab Wave 2** — the annual-contrast SALES TOOL (below) |
| `3845c7d8` | **Aggressive Lab Wave 1** — parallel paper-test of the 10-15% strategies the desk refuses |
| `fd000b73` | **Edge-at-Scale month-program Week 2** — the CRUX answered |
| `437d14f0` | **Edge-at-Scale Week 1** — 3-lane scaffold (designed via Senior Investment Director + Senior Architect) |
| `0919c5e4`, `49126ef1`, `c9424f41`, … | **Round-2 "Prove the Edge"** (optimizer A/B, API security, exec backstop, de-bloat, fundable artifact) |
| earlier | **"Cutover-Bulletproof" 2-week program** + **6-domain total audit + all code fixes** + **GoLive blocker fixes** |

### The two big honest findings (these define the desk's strategy now)
1. **Edge-at-Scale verdict: the desk does NOT beat the ~3.4% RWA floor at fundable scale via YIELD.** The optimizer's +1.08pp@$100k goes **NEGATIVE past ~$1M** (small-TVL concentration). The refusal-gated PT carry alpha is **venue-capped at ~$1.5-1.7M** (all books share ONE Pendle/USDe exit rail → correlation haircut collapses them; "scale by COUNT" fails on today's universe). **The scalable path = the deep RWA+lending CHASSIS (beta, ~$50-100M, at/just-above floor) + measurement/underwriting-as-a-product (Layer-3, no capacity ceiling).** Target: floor+50-150bps@$5M, NOT floor+1000bps. (See `docs/FUNDABILITY.md`, `docs/CARRY_TRUTH.md`, `data/edge_at_scale.json`, the month-program in `spa_core/strategy_lab/rates_desk/{books,depth_at_size,realized_at_size,venues}.py` + `spa_core/strategy_lab/underwriting/`. Memory: `capital-scale-ceiling` — the $1M cliff is sleeve-specific, the deep core scales.)
2. **All 10-15% "yields" are risk-compensation (depeg/funding-flip/leverage/incentives), not alpha.** The live book holds ~4.1-4.5% in 7 plain stablecoin lenders and refuses the rest. That's deliberate.

---

## 3. The Aggressive Lab + Annual-Contrast SALES TOOL (the most recent work — owner's active interest)
**Purpose (owner's words):** a parallel paper-test of the 10-15% strategies the desk refuses, so the owner can (a) choose later if needed, and (b) **show a prospect a year of a 15% strategy with its DATED drawdowns to make selling the steady ~5% easier** ("here's what 15% really costs").

- Package: `spa_core/strategy_lab/aggressive_lab/` — **isolated, advisory, OUTSIDE-RiskPolicy, real-data, NEVER touches the go-live track or live allocation** (3-layer isolation guard: protected-path refusal + md5 witness + domain stamp).
- 8-strategy roster (`roster.py`): susde_dn, susde_spot, pendle_yt_susde, pendle_pt_levered, lrt_neutral, eth_directional (flagged B/beta), leverage_loop, points_farm. Each declares yield SOURCE + risk SHAPE + RiskClass A/B/C/D.
- **Mark-to-market** (`harness.py`/`roster.py`): the backtest equity curve marks each strategy to its REAL historical price/funding path → it ACTUALLY dips on real event dates (eth_directional −66% real ETH bear; leverage_loop −29.7%@2024-08-09 liquidated; lrt_neutral −16.7%@2024-08-23 depeg-killed). Honest `mtm_source` label (realized vs `modeled_stress_overlay`); the stable ~5% baseline stays FLAT (max-DD 0%, verified).
- **Annual contrast** (`annual_contrast.py`): trailing-12m + per-calendar-year, 15% equity vs the REAL stable-book ~5% baseline, dated drawdown timeline, contrast metrics (CAGR/maxDD/days-underwater/cost-of-chasing). Auto one-pager: **`docs/ANNUAL_CONTRAST.md`**.
- **Surfaces:** `/api/aggressive-lab/{scorecard,strategy/{id},annual-contrast}` (fail-closed) + a dashboard "Aggressive Lab" tab + a **shareable page `landing/src/pages/annual-contrast.astro`** the owner can open in front of a prospect.
- Standing agent `com.spa.aggressive_lab`: the plist + wrapper exist in `scripts/` and PASSED the pre-deploy gate (CHECK_ONLY), but it is **NOT loaded** (advisory sales tool — the 843-day backtest already gives the full year-view; daily forward accrual is optional). Deploy by owner choice via `scripts/check_agent_before_deploy.sh aggressive_lab` if a live forward track is wanted. (Contrast: `com.spa.realized_at_size`, the edge-at-scale measurement spine, IS loaded + now persisted in `~/Library/LaunchAgents` + `install_all_agents.sh` so it survives reboot.) Owner flag `SPA_AGGRESSIVE_LAB_SELECT` (default OFF — does NOTHING to live allocation even when ON; promotion to real capital is owner+custody-gated).
- **Honest caveat to preserve:** the realized drawdowns are real where a per-day price/funding path exists; where only event magnitude is known they're `modeled_stress_overlay` (labeled). Don't pass modeled off as realized. Don't fabricate a baseline.

---

## 4. NON-NEGOTIABLE conventions & guardrails (from CLAUDE.md — follow exactly)
1. **Read `docs/SYSTEM_BRIEFING.md` first** before claiming anything about system state (auto-updated every 30 min).
2. **NEVER run the production cycle against live `data/`** in dev/QA — it corrupts the go-live evidenced track (the track-corruption hazard). Use a sandbox / tmp dir. All new analytics open the go-live track READ-ONLY.
3. **stdlib-only** in runtime code (FastAPI/uvicorn/bcrypt are the documented API exceptions). **No LLM** in risk/execution/monitoring/kill. **No `execution/` import** from read-only/paper code.
4. **Atomic writes** via `spa_core.utils.atomic.atomic_save` (same-dir tmp + `os.replace`) — never raw `open(...,'w')` on state files.
5. **Deploy agents ONLY through `scripts/check_agent_before_deploy.sh <name>`** (manual run → exit 0 → log written → then load; ≤3/batch). Every agent runs via a **bash-wrapper** (`scripts/agent_<name>.sh`) with `/tmp` logs — NEVER direct `python3 -m` or `~/Documents` logs (→ launchd exit-78).
6. **RiskPolicy is owner-gated v1.0** — caps (40% T1 / 20% T2 / cash≥5% / TVL≥$5M) and kill-switch VALUES (SOFT 5% / HARD 10%, ADR-048/049) must NOT change without an ADR. Aggressive Lab strategies run OUTSIDE RiskPolicy ON PURPOSE but are fenced (advisory, can never reach live allocation).
7. **All new advisory strategies/sleeves `IS_ADVISORY=True`.** Owner-gated flags ship default-OFF.
8. **The honesty mandate is the product.** Every published number must be realized-or-labeled (INSUFFICIENT_DATA / modeled / backtest), reproducible via `scripts/verify_spa.py` ("don't trust us, check us"). No fabricated APYs/Sharpe (there's a no-unsourced-number guard + the verifier + a doc-drift guard).
9. **Process pattern that's been working:** senior-architect agent plans → execute with parallel sub-agents → a rotating adversarial red-team on every workstream (it has caught a real flaw EVERY time — non-negotiable) → push continuously. Owner-only items get flagged + skipped.

---

## 5. Open owner-gated items (do NOT action — flag only)
- Set **`SPA_API_KEY` in Keychain** so the dashboard/agent write/LLM POSTs authenticate (the WS2 API auth is default-ON for writes; GET/proof endpoints stay public). Until set, writes 401 (fail-closed by design).
- Real **`SPA_OFFSITE_DEST`** (current offsite is a local stand-in → single-host SPOF) + standby host/HA.
- Promote optimizer to cycle default (`SPA_OPTIMIZER_CYCLE_DEFAULT`); flip any sleeve to real capital; the risk-appetite dial; `SPA_RATES_MULTICHAIN`, `SPA_UNDERWRITING_PUBLISH`, `SPA_AGGRESSIVE_LAB_SELECT`, `SPA_EXEC_ARMED` (= the go-live cutover arming flag — stays OFF the whole paper period).
- Custody/MPC, external audit, public competitor-naming, git-tag/GPG-sign the verifier, un-ignoring `data/` ledgers.

---

## 6. Verify / run
```bash
PY=/Users/yuriikulieshov/miniconda3/bin/python3
# full suite (~100k tests, ~9 min): $PY -m pytest spa_core/tests/ tests/ -p no:randomly -q
# scoped example:                    $PY -m pytest spa_core/tests/ -k aggressive_lab -p no:randomly -q
$PY scripts/verify_spa.py data/                    # proof reproduction, exit 0 = OK
$PY -m spa_core.paper_trading.golive_checker       # GoLive criteria (~27/29, 2 time-gated)
bash scripts/verify_fleet_after_reboot.sh          # fleet health (45/45, exit78=0)
cd landing && npm run build                        # site (0 errors expected)
```
Known: full suite has had ~0-2 environmental flakes from tests reading live mutable `data/` (the hermeticity sweep fixed most; if `test_anchor_matches_producer_head` flakes, it's the concurrent fleet rewriting `data/rates_desk/` mid-run, not a code bug). architecture_audit `violation_count` is 0.

---

## 7. Suggested next steps (if continuing)
- The Edge-at-Scale month-program is Weeks 1-2 done; Weeks 3-4 (productize the measurement-moat report + final honest verdict) are **time-gated** — the standing agents (`com.spa.realized_at_size`, `com.spa.aggressive_lab`) accrue the forward track daily; the verdict matures past the 30-day bar AFTER the program. Don't rush it with code; let the track mature.
- If the owner wants the Aggressive Lab polished further: richer real per-day paths for the strategies still on `modeled_stress_overlay`, or a printable PDF of `docs/ANNUAL_CONTRAST.md`.
- Always `git fetch && git reset --hard origin/main` at start; push via `push_to_github_batch.py`.
