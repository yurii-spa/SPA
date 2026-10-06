# REVIEW_WAVE2_1 — independent integration review, RM-TRUTH-01 Wave 2

Subject: `rmtruth/wave2` HEAD `0de2d1e9a` vs `origin/main` `96a935fda` (59 files, +9904/−564).
Reviewer wrote none of it. Method: read the diff; ran 148+180+276 targeted tests in my own detached worktree
`/tmp/spa_rmt_rw2` (`SPA_ENV=ci PYTHONHASHSEED=0`, TMPDIR outside git; worktree since removed); copied the live
`market.db`/`evidence.db` with sqlite backup from a `mode=ro` URI and replayed qualification there. Prod tree and mirror were not written to.

## VERDICT: CHANGES_REQUIRED (two red tests the branch itself introduced; both are small fixes)

### P1-a · RED on every host: `test_mission_no_money_action.py::TestUiNeverActs::test_no_non_get_fetch_or_xhr`
`spa_core/studio_os/mission_ui/app.js:28`, the header comment, contains the literal `XMLHttpRequest`
("no fetch()/XMLHttpRequest with a non-GET method"). The test asserts `"XMLHttpRequest" not in js`, so it fails.
This comes from commit d12156b06. Fix: reword the comment, e.g. "no XHR". Do not weaken the test (inv. #16).

### P1-b · Absolute filesystem path reaches the model and the first-level card: `test_mission_control_contract.py::test_no_secret_path_or_email_reaches_the_model` is RED on the Mac
- Path of the leak: `company_truth.capital_trading_lab`, around line 566, takes `why = core.get("reason")` from
  `read_model._open_ro`/`_read_json`. That reason contains `f"… не найден по пути {p}"` with the full absolute path.
- The text lands in `truth.capital.trading_lab.display_ru/display_en/unknown_ru`. In prod it would print
  `/Users/yuriikulieshov/Documents/SPA_Claude/data/...` on the Capital tab.
- `_ABS_PATH_RE` → `<path>` redaction already exists in the same module (line 157, scopes). It is simply not applied here.
- On ubuntu CI the tmp path is `/tmp/...`, so the test is green there. That is why this can pass CI and still leak on the owner's host.
- Fix: apply `_ABS_PATH_RE.sub("<path>", …)` (or `safe_text`) to the lab reason. The same treatment is advisable for every `reason` that company_truth re-projects.

## Checks requested
1. **C7, Trading Lab: SAFE.**
   - `observations`, `candidates` and `lifecycle_events` stay protected by the UPDATE/DELETE triggers. All writes are INSERT or INSERT OR IGNORE.
   - `registered_at_ms` cannot move: a test covers it and the trigger refuses the UPDATE.
   - Backfill bars before registration are never stored.
   - The OOS freeze changes methodology, but it does not change stage transitions. I measured this on the live snapshot (138 candidates, single
     registration 1790803372716): the qualified set with the open-ended OOS equals the set with the frozen OOS, and both equal the prod
     backtest.json. All three are the same 5 candidates, so the first tick after deploy will append no REJECTED/QUALIFIED events.
     The ADR does not record this measurement. Add one line to ADR-581 (P2).
   - Any future flip would only append lifecycle events, never rewrite one.
2. **C4 import ratchet: real for its scope.**
   - Only `mission_control.py` imports it. It runs inside `com.spa.mission_control`/`mission_build`, the designated server.
   - The positive control is good.
   - Gaps (P3): it does not scan `tests/`, `research/` or top-level files; it misses `importlib.import_module("…company_truth")`; and the `test_mission_` prefix is broad.
3. **Director UI: OK apart from P1-b.**
   - No POST, no `<form>`, no act:/kill verbs. Hrefs are only `#…` or `https://t.me/`.
   - STALE, NOT_MEASURED and NOT_ENOUGH_HISTORY render `unknown_ru` instead of the value.
   - P2: when the yield tile is STALE it says «Доходность не измерена», which is wrong — it was measured and is now stale.
   - P2: the scopes card re-projects readiness_scopes reasons that name `*.json` files.
   - P2: Sherlock falls back to showing the `candidate_id` hash when `instrument` is missing.
   - Legacy v1 dead code (two blocks labelled "kept verbatim, unused"): acceptable as P3, with a removal card.
4. **Memory ensure-fresh: does not break briefing, but has P2s.**
   - It is wrapped in `|| true`, logs to `/tmp`, and the CLI catches every exception.
   - The index stays where it already was (prod `data/memory/index.db`, disposable, built with tmp+`os.replace`), and nothing is written into the repo tree.
   - `SPA_MEMORY_ROOT_SPA=$_MIRROR` is redundant: the default root is already the mirror. So there is no corpus ping-pong.
   - P2: there is no timeout. A hung rebuild would block the 30-min briefing agent indefinitely. Wrap it in `timeout 120`.
   - P2: `assemble()` now auto-rebuilds by default and shares the fixed `.building` tmp path with the briefing step. Two concurrent builders can unlink each other's tmp file (a failed or empty build, not data loss).
   - The new memory tests isolate the index with `SPA_MEMORY_INDEX`.
5. **Safety: clean.**
   - Nothing under risk/, governance/, execution/, landing/**, .github/, and no baseline files are touched.
   - No secret patterns and no LLM or network calls in the added code.
   - ADR-584 is a doc-only backfill of an existing owner decision.
6. **Other P2s.**
   - `save_versioned` adds about 4.7 MB per backtest refresh to `data/trading_research/backtest_history/` with no retention: roughly 1.7 GB a year. Its backup coverage is unknown.
   - The readers use `forward_candidates or shortlist`. An empty `forward_candidates` (measured zero) silently falls back to `shortlist` (inv. #17). Use `observed(...) is None` instead.

Tests run (own worktree): trading_research, read_model, company_truth_*, mission_* (except one), memory wave2/trap, typed_fleet,
backups, decisions_triage, claude_work, scoped_readiness, investment_cio_sleeves, research_factory_scanners,
mission_control_contract, mission_server, owner_remote, director_*, architecture_manifest. Result: 602 passed, 2 failed (P1-a, P1-b).
