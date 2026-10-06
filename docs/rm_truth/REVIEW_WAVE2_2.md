# REVIEW_WAVE2_2 — independent re-review, RM-TRUTH-01 Wave 2 (round 2)

Subject: `rmtruth/w2fixD` HEAD `12ce51f83` (origin/main `72cacb6b2` is an ancestor).
Method:
- Ran tests in my own detached worktree `/tmp/spa_rmt_rw2b` (now removed) with `SPA_ENV=ci PYTHONHASHSEED=0` and a private TMPDIR.
- Built the REAL model read-only against the prod tree with branch code (`mc.build(MCInputs(repo=~/Documents/SPA_Claude))`). Saved as `rw2b_model.json`. The prod `git status` md5 was identical before and after.
- Compared the real `truth` against `fixtures/mission_truth_scene.json`, key by key, and against the fields `app.js` reads.

## VERDICT: CHANGES_REQUIRED

The round-1 P1s are closed. The seam check fails on the Studio and Product tabs: the real producer and the UI disagree on field names.

## 1. Round-1 findings: CLOSED
- **385 passed, 0 failed.** Files: company_truth_import_ratchet, company_truth_unknown, decisions_triage, memory_in_git, mission_control_contract, mission_no_money_action, mission_rebuild_from_canon, mission_server, mission_ui_static, scoped_readiness, backups_three_facts, trading_research_read_model, every_adr_is_in_a_registry, adr_number_allocator, memory_wave2, memory_trap.
- **P1-a fixed:** the XMLHttpRequest literal is gone. `test_no_non_get_fetch_or_xhr` is green.
- **P1-b fixed:** `_redact()` is applied to the lab reason. `test_no_secret_path...` is green on the Mac.
- **Leak scan of the real truth:** 0 × `/Users/`, 0 × `/private/`, 0 × `/tmp/`, 0 × 40-hex.
- **`com.spa.` still appears in 14 places:** decision-card titles/reasons (tracker text, verbatim), `studio.problems.value.open[]` keys, and the lab evidence `source`. P3.
- **`.json` appears on first-level text in 10 places:** all inside decision-card reason/done_when/title text, which is authored card text. P3.
- **Other round-1 P2s:**
  - STALE wording is fixed (`_stale_or_absent`).
  - Scope reasons now go through `_FILENAME_RE`.
  - `forward_candidates` is read with `isinstance(list)` and no longer falls back to `shortlist`.

## 2. Seam: real model ≠ fixture ≠ app.js — P1
Fields read by app.js and missing in the real model (all cards are MEASURED live):
- **studio.memory (P1, false-good):**
  - Real: `value.lag=30`, so `cell.lag` is undefined.
  - `renderMemory` prints «индекс отстаёт на 30 решений» AND «индекс знает все решения» on the same card.
- **studio.backups (P1, false absence, inv #17 feature):**
  - Real keys: `local_backup`, `off_host_backup`, `recovery_tested`. UI reads `b.local`, `b.off_host`, `b.recovery`.
  - Result: all three rows show «не измерено», although local backup is MEASURED (8 h) and off-host is MEASURED_ZERO.
- **studio.decisions_summary (P1, «undeclared visible everywhere» fails on Studio):**
  - Real: `value.{owner,undeclared,answered}`. UI reads `ds.own`, `ds.undeclared`, `ds.answered`.
  - Result: «ваших вопросов: » and «тема не объявлена:  (ждут вашего решения)» print with blank numbers.
- **Home and Decisions are OK:**
  - The needs tile has `own/undeclared/answered/waiting` at top level and reads «ждёт решения: 11 (у 11 тема не объявлена)».
  - Decisions `groups.undeclared` (11 cards) is headed «ждёт вашего решения».
  - Attention lists 3 old owner items → #decisions.
- **studio.tasks, problems, incidents, releases (P2):**
  - Fields sit under `value` and are not bare, so chips render empty («в очереди: », «открыто: »). The composed `display_ru` above them is correct.
  - releases: `in_prod_ok` is undefined and always renders «drift». It is right today only by coincidence.
- **studio.machine (P2):** absent from the real model, so the card always says «не измерено».
- **product.public_metrics (P2):** the real value is a cell dict, but the UI expects an array, so it says «нет чисел» while 5 are measured.
- **Minor gaps (P3):**
  - `product.backlog.top_titles_*` and `truth_incidents.open` are missing.
  - `home.strip[].link_area` is missing (the UI does not use it).
  - Product `unknown_en` strings are Russian.
- **Not new:** the same `studio_*` shapes already existed at `0de2d1e9a`. dad35fba5 conformed home/capital/decisions only. Capital matches the fixture fully.
- **Fix:**
  - Conform the `studio_*`/product producers to the fixture field names: bare fields next to `state`, with `local/off_host/recovery`, `own`, and `lag`.
  - Add a seam test that builds `company_truth` on a scene and asserts every path `app.js` reads (the fixture key set) exists in the real output.
- **No falsely-MEASURED card found:**
  - `treasury_rwa` is MEASURED with 0 reference periods and cash shown, which is honest.
  - NOT_ENOUGH_HISTORY books render "accumulating N days"; their `unknown_ru` «Книга не прочитана» is wrong wording but is not displayed (P3).

## 3. C4 / safety: OK
- No non-test importer of `company_truth` except `mission_control.py`. `read_model.py` mentions it in a comment only.
- No agent or gate reads it.
- No POST/XHR in mission_ui.
- `plain()` only feeds text nodes through kvPlain, so there is no new sink.

## 4. perl alarm: correct
- `/usr/bin/perl` exists, and all paths are absolute, so the launchd PATH does not matter.
- Measured:
  - env passes through exec;
  - the child's exit code passes through (3 → 3);
  - the alarm fires after exec (rc 142);
  - `|| true` swallows the alarm;
  - `bash -n` is OK, and the mode is 100755.
- A killed build leaves a `.building` file, which the next `build()` unlinks.
- Residual P3: git children with their own timeouts may outlive the alarm.
- The round-1 P2 about the shared `.building` path under concurrent builders remains.

## 5. Renumber: OK
- ADR-590..593 files and headings match their INDEX rows.
- No stale `ADR-58[2-4]` references remain in code, architecture, tests, INDEX or the 59x files.
- `ADR-581` and `test_other_road_verdict.py` show zero diff vs origin.
- `adr_number.py check --files ADR-59*.md INDEX.md` gives ✅, rc 0. Without INDEX in `--files` it compares against origin's INDEX, which is the expected pre-push behaviour.

## 6. New P0/P1
- No P0.
- The P1s are the three seam defects in §2: memory false-good, backups false absence, and blank Studio decision counts.
