# REVIEW_INTEGRATION_2 — RM-TRUTH-01 `rmtruth/candidate` HEAD 5e0c122fa (base bbb127730)

Reviewer: independent re-reviewer, round 2. Read-only.

- Not touched: /tmp/spa_rmtruth01, prod, the mirror. Nothing was pushed and no agents were touched.
- Own disposable worktree: /tmp/spa_rmt_rr2. Reproductions read prod only, or ran on copies in `scratchpad/rr2/`.
- Date: 2026-10-05.

## Verdict: **CLOSED**

All 18 round-1 findings are closed, except F10, which is closed apart from its two minor sub-items. F18 is pre-existing and out of scope. No P0 or P1 findings were found. One new **P2** was introduced by the fixes (N1, the symlinked stand), plus three P2/info notes. None of them blocks the merge. N1 should be fixed in a follow-up (or before the merge, if cheap).

## Per-finding table

| id | verdict | own evidence |
|---|---|---|
| F1 | **CLOSED** | Ran `_push_via_policy` four times with the real `push_policy`, transport mocked, on a temp data dir. Input: prod `agent_health.json` forced to CRITICAL, every number in the issue texts drifting by +0.1 per run. Result: **pushed / silent / silent / silent**; a new failing agent → pushed. Keys are now `label::cause_code` (e.g. `com.spa.novel_edge_rnd::stale_log`). One re-push on first deploy (`fingerprint: null`) is documented in the docstring. |
| F2 | **CLOSED** (residual note N3) | Ran `build_owner_decisions` against the prod tracker, read-only. **Base:** the 12 tracker needs-owner cards split into 2 OWNER and 10 **SYSTEM** ("queue defect"). **Candidate:** all 12 are `UNKNOWN`/`UNDECLARED` and **none is SYSTEM**. `render_studio` lists them in a "предмет не определён: 12" section. The 4 OWNER items from KANBAN/gates are unchanged, so the headline is not empty. Mission Control selects by status (`needs-owner`/`owner-accepted`), not by class, so all 12 stay visible there. |
| F3 | **CLOSED** | `test_data_dir_env_ratchet.py` is green. The default is resolved at call time via `live_paths.live_data_dir`. |
| F6 | **CLOSED** | Catches `(OSError, ValueError)`. `test_owner_answer_delivery -k TreeUnderJudgement` with harness-shaped env (`SPA_SANDBOX=1` + `SPA_LIVE_ROOT`): 8 passed. Marker alone still refuses at import, which is the correct fail-closed behaviour. |
| F7 | **CLOSED** | Fixed by `ensure_faithful_stand`, which introduces N1. |
| F8 | **CLOSED** | Marker plus `SPA_DATA_DIR`/`SPA_LIVE_ROOT` added in `list_identity_census`, `green_by_construction_census` (root = `cp -Rc` disposable copy) and `run_identity_key_price._run_http_probe` (temp stands). The new AST ratchet is green. See N2 on its allow-list. |
| F9 | **CLOSED** | SAME_HOST has its own wording in agent_health ("drills ARE passing…"). The briefing header and the section now share `_RESILIENCE_ICON`, so SAME_HOST shows 🟡 in both. |
| F10 | **CLOSED (partial)** | Per-agent `retired_but_loaded` is folded into the single fleet Problem, and the card text no longer claims it silences Telegram. **Not done:** (b) the duplicate card if `save_store` fails after `create_card`, and (c) INCIDENT records are still never pruned. Both are P2 and acceptable to defer. |
| F11 | **CLOSED** | READY now requires `ready_for_live` and no open owner gates; otherwise NOT_READY with the count. |
| F12 | **CLOSED** | C013 now reads the content's `last_updated`/`generated_at`; a missing stamp gives SKIP (not measured). Prod `KANBAN.json` has `last_updated` 2026-06-22, so C013 now reads FAIL (stale), as the C3 criterion intends. This does not touch `ready_for_live`. |
| F13 | **CLOSED** | `updated_at` added. Naive stamps and files with no stamp are listed in `unchecked_files` with a named reason, not guessed as UTC. |
| F14 | **CLOSED** | A failed fetch now gives `unmeasured:fetch_failed:…`, not `measured`. |
| F15 | **CLOSED** | The repo root is put on `sys.path` from `__file__`. An `ImportError` now gives NOT_MEASURED, with no heuristic fallback. |
| F16 | **CLOSED** | The only `ADR-566` left in added lines is the journal's explanation of the renumbering. |
| F17 | **CLOSED** | The journal (`docs/journal/2026-W40.md`) lists every changed test with its rationale, including (a)–(c). |
| F4 | **CLOSED** | `git diff bbb127730..HEAD -- landing/` is empty. Compared `key_facts`, `get_health_public`, `/api/live/books`, `/books/brief` and `/portfolio`, base vs candidate, on a copy of prod data. In `/api/ssot/facts` and `/api/health-public`: **no existing key changed value**; only new keys were added (`paper_apy_canonical`, `max_drawdown_track_pct*`, `apy_today_pct_metric_type/window_days`). `paper_apy_pct` is absent as before, so DashboardSPAApp still falls back to `apy_today_pct`. `max_drawdown_pct` is back on `tear_sheet`. The only text change is `ytd_apy_pct_note`, which no landing file reads (grep). The new `test_landing_read_fields_frozen.py` is green. |
| F5 | **CLOSED** | Ran the base parser (`git show bbb127730`) and the candidate parser over all **747** real cards (12 needs-owner). 15 differ: **13 are label-only** (markdown stripped from button text; one needs-owner card, `zakryt-tri-chernovyh-pr`, same options, numbering and ⭐). **2 are structural** (`disk-mac-mini` needs-owner and `monitor-depega` ingested): base had no buttons and no MQ code; candidate has no buttons with MQ `multi_step_section`. **Zero cards get buttons for a different question than base; zero cards gain buttons.** |
| F18 | PRE_EXISTING | Out of scope. |

## New findings

| id | sev | origin | file | evidence | fix |
|---|---|---|---|---|---|
| N1 | **P2** | INTRODUCED (vs round-1 candidate; base had no isolation at all) | `spa_core/monitoring/run_identity_key_price.py::ensure_faithful_stand` (used by `python_reader_clock_doors.run_arm`, `list_identity_census.run_probe`, `_run_http_probe`) | It symlinks **every** non-`data` top-level entry of `tree_root` (including `nimbalyst-local/`, `.git`, `landing/`, `docs/`) into the stand, which children then get as `SPA_LIVE_ROOT`. `tree_root` defaults to `_ROOT`. The stage runs in prod (`com.spa.decision_loop` → findings_bridge, ADR-414), so there **tree_root is the LIVE tree**. **Reproduced** (my worktree standing in for prod): a child with `SPA_SANDBOX=1 SPA_LIVE_ROOT=<stand>` resolves `owner_queue.queue.TRACKER_DIR` → realpath `<tree_root>/nimbalyst-local/tracker`, writable, and `live_root()` does **not** refuse (stand ≠ `DEFAULT_LIVE_ROOT`). The INC-1 guard therefore covers `data/` only: any reader that writes a card via `live_root()` would write into the prod tracker. Before the fix, that path pointed at a non-existent location inside the temp stand. No current writer was observed doing this; the docstring's "all three only read" is a claim, not a measurement. Cleanup is safe (`rmtree`/`rm -rf` unlink symlinks; verified the worktree is intact). | Link read-only what is needed (code dirs). **Copy** state-bearing dirs (`nimbalyst-local/`), or set `SPA_TRACKER_DIR` to a stand-local copy. Or refuse `ensure_faithful_stand` when `tree_root.resolve() == DEFAULT_LIVE_ROOT.resolve()`. Add a positive-control test: a child writing via `queue.TRACKER_DIR` must not land in `tree_root`. |
| N2 | P2 | INTRODUCED (ratchet rationale) | `spa_core/tests/test_sandbox_wiring_ratchet.py` ALLOWLIST entry `decision_reproducibility._default_runner` | The rationale says the marker "would raise SandboxLeakError on EVERY prod run", but it argues against `SPA_LIVE_ROOT=root`, a configuration nobody needs. **Measured:** both real subjects (allocator, tuner) run rc=0 with `SPA_SANDBOX=1` + `SPA_DATA_DIR=<sandbox>` and write **nothing** to the tree. The real residual leak doors are `live_root()` callers (tracker) and the modules in the `data_dir_env` baseline that bypass `SPA_DATA_DIR`; the subject-side detector only watches the sandbox. It is not an active INC-1 leak today: the subjects are fixed code and the observed writes are nil. | Set `env["SPA_SANDBOX"]="1"` (optionally `SPA_LIVE_ROOT=<tmp>/run{i}`) and drop the allow-list entry. Or correct the rationale text. |
| N3 | P2 | INTRODUCED (F2 fix shape) | `scripts/cartographer/director_shell.py` with UNDECLARED → `CLASS_UNKNOWN` | The 2 tracker cards that base surfaced in the top "decide" block (`earn-defi-kanal-telegram`, `dva-mesta-zovut-odin-protokol`) are now only inside the collapsed "предмет не определён" list. The stats row has no count for that class. 10 cards that were hidden as "queue defects" are now visible, so the net effect is better visibility, but prominence dropped for those 2. | Backfill `subject:` on the 12 open needs-owner cards, and/or add the UNKNOWN count to `_stats`, rendering it as "ждёт решения, тема не объявлена". |
| N4 | info | INTRODUCED | `problem_store.cause_from_agent_issue` (used for the F1 fingerprint) | The fallback key is truncated to 40 characters, so a new cause that appears only in the tail of a long *system* issue (e.g. a growing agent list) keeps the same fingerprint. New *agent* rows are keyed by label and still alert (verified). Acceptable. | Optional: hash the full number-stripped text instead of truncating. |

## Safety invariants (item 3)

- `git diff bbb127730..HEAD --stat -- spa_core/risk spa_core/governance/kill_switch.py spa_core/execution`: **empty**.
- No changed file touches tiers, the allocator, cycle_gates or adapters. `paper_trading/sleeve_track.py` is a new pure read-model, imported only by `reporting/books_summary.py` and `api/routers/live.py`.
- `push_policy`: only the new whitelisted key `site_publisher_stuck` was added. `kill_switch` stays ceiling-exempt.
- No `spa_core.execution` imports and no LLM SDK imports in added lines. No token or secret patterns in added lines.
- `git diff bbb127730..HEAD --stat -- '*baseline*'`: **empty**, so no baseline padding.
- Tests run in my worktree (`SPA_ENV=ci PYTHONHASHSEED=0 -p no:randomly`): 86 passed (ratchets, subject, option grammar, landing-fields, live_paths, readiness_scopes) and 220 passed / 25 subtests (problem_store, future_stamp, readiness_checker, fetch-failure, SAME_HOST icon, resilience, paper_apy_staleness, python_reader_clock_doors). The full suite was not run, per instructions.

## Owner-surface semantics (item 4)

Measured on a copy of prod data, base → candidate:

- **`/api/live/books`** (read by `/admin/portfolio-summary` → "Годовых (реализовано)"):
  - Conservative: **+4.15% → +4.90%**. Linear whole-life replaced by compound over evidenced bars, equal to the public hero 4.9.
  - Balanced: **−4.36% → "—"**. Value is null; `status: accumulating`, 4 valid days, maturity 30.
  - Aggressive: **+1.42% → "—"**. Same as Balanced.
  - NAV and return are unchanged. New typed `annualized_apy_pct_rate`, `days_with_positions` and `maturity_days` fields were added.
- **Telegram 📚 Пакеты:**
  - Conservative: "~4.1% год." → "**~4.9% год.**"
  - Balanced/Aggressive: "~-4.4% год." / "~1.4% год." → "**статистика текущей версии накапливается (валидных дн.: 4)**"
  - NAV, return and Σ are unchanged.
- **`/api/live/books/brief`** and **`/api/live/portfolio`**: no value change.

These follow ADR-531 (v2-only sleeve economics), ADR-533 (current experiment only) and ADR-548 row 8b (owner-approved: "Balanced/Aggressive «accumulating»", report at 30 valid days; `REPORTABLE_AFTER = 30`). They are maturity-gated corrections that align the owner surfaces with the already-public hero. None of them reaches a public landing page.

## Artefacts

`scratchpad/rr2/`: `f1sim.py`, `f2.py`, `f4.py` (with `f4_base.json`/`f4_cand.json`), `tg.py`, `cmp_od.py`, `old_od.py`, `f5.txt`, and `data/` (a copy of prod top-level JSON).
