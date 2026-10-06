# REVIEW_WAVE2_3 — independent re-review, RM-TRUTH-01 Wave 2 (round 3)

Subject: `rmtruth/w2fixD` HEAD `a23999119`. The fixes reviewed are 6cee4e922, 8050cab8a and a23999119.

Method:
- Ran tests in my own detached worktree `/tmp/spa_rmt_rw3`, which is now removed, with a private TMPDIR, `SPA_ENV=ci` and `PYTHONHASHSEED=0`.
- Built the real model read-only against the prod tree, using the branch code: `mc.build(MCInputs(repo=~/Documents/SPA_Claude))`. Saved as `rw3_model.json`.
- **Prod writes during the build:** 42 prod files changed in that window. All of them are live-agent outputs (swarm/monitoring/*_log). None is under memory/, mission or tracker.
- The producer opens sqlite with `mode=ro`, and `mc.build` writes nothing; only `--out` writes.

## VERDICT: CLOSED

There is no P0 and no P1. Every round-2 finding is closed on real data. Two cheap P2s remain; I recommend fixing them before merge, or right after it.

## 1. Round-2 findings, checked on the real model and against `app.js`

| Card | Before (round 2) | Now (real model) | Status |
|---|---|---|---|
| studio.memory | `lag` sat only inside `value`; the card said "lagging" and "knows all decisions" at once | bare `lag=31`, `display_ru=None` → «индекс отстаёт на 31» only | OK |
| studio.backups | keys did not match the UI | keys `local/off_host/recovery`; local MEASURED, `age_ru` «11 ч назад»; off_host MEASURED_ZERO, `is_real_remote=False` (amber); recovery `drill_result=OK` | OK |
| studio.decisions_summary | blank counts | `own=0`, `undeclared=11`, `answered=3` | OK |
| tasks / problems / incidents / releases | chips rendered empty | bare fields present (338/38/33/1; open 4 + items[4]; open 0; today 14, `in_prod_ok=False`) | OK |
| studio.machine | absent | MEASURED, `disk_free_gb=26.2` | OK |
| product.public_metrics | a cell wrapping an array | plain array of 5 rows, each with label/value/date/metric_type | OK |

## 2. Generic seam test (`test_company_truth_matches_ui_contract.py`)

**It has teeth.** I mutated my worktree twice and reverted both times; `git status` was clean afterwards.
- **Mutation 1, bare `lag` removed:** 4 failed. The scene test, the real-tree test and both memory tests went red with «missing key: studio.memory.lag».
- **Mutation 2, bare `in_prod_ok` removed:** the scene test went red with «missing key: studio.releases.in_prod_ok». The real-tree test stayed green.
  - **Why it stayed green:** with `measure_host=False`, releases are NOT_MEASURED on prod, so the walk checks only the envelope.
  - **Consequence:** the real-tree variant is blind to host-derived cards. The scene test covers them. P3, but state it in the docstring.

**The real-tree variant is safe.**
- It is read-only (measure_host=False, sqlite ro, no writes).
- It skips when the tree is absent. On a Mac it takes about 2 minutes, which is slow but there is no `--timeout` in CI.
- A card that is not measured relaxes to the envelope only, so live data cannot redden it falsely.

**P2 — structural hole.** `_assert_walk` treats `null` as compatible with any fixture kind. `i18n.tf()` turns null into "". Together, any MEASURED card with a null bare field renders BLANK, and the test stays green. My scan of the real model finds two such cards:
- **capital.sherlock** (MEASURED): `total=None` and `awaiting_review=None` after 8050cab8a.
  - The UI prints «фактов пригодно: 1 из » and «ждут независимой проверки: ».
  - The producer fix (bool → None) is right, but `renderSherlock` was not taught to show «не измерено». Absence rendered as blank is an inv #17 representation defect.
- **product.next_release** (MEASURED): `gate_ru/en=None` is hard-coded, so the UI prints «проверка типов чисел: » blank. This predates this round.

**Fix for the P2:** either render null as `t("state.NOT_MEASURED")` in those renderers (or inside `tf`), or forbid null on MEASURED cards in the walk, except where the fixture leaf is itself null.

## 3. Memory index tmp handling: OK

- **Unique tmp name:** the tmp file is `<name>.building.<pid>.<uuid8>`, and `os.replace` happens within the same directory, so it is atomic. When two builders race, the last complete index wins; a half-written one never does.
- **The sweep:** it removes only siblings whose mtime is more than 10 minutes old, and never its own tmp file.
  - If a stalled live sibling did lose its tmp, it would keep writing to the unlinked inode, and its own `os.replace` would raise loudly. Nothing is corrupted.
  - The glob also catches `-journal` files of old orphans, which is fine.
- **P3:** the legacy fixed-name `index.db.building` file left by old code is never swept. It is a one-time leftover.

## 4. No regressions

- **Targeted tests:** 237 passed, 0 failed, with the slow real-tree test deselected. It was green before my mutations.
  - Files: backups_three_facts, company_truth_import_ratchet (C4), company_truth_unknown, decisions_triage, injected_clock_claim, memory_architecture, memory_in_git, mission_control_contract, mission_no_money_action, mission_rebuild_from_canon, mission_ui_static, scoped_readiness, and the seam test.
- **Leak scan of the real truth:** 0 × `/Users/`, `/private/`, `/tmp/`, 40-hex or token prefixes in the model.
  - The 20-hex candidate ids appear only inside `capital.sherlock.value`.
  - First-level text has 0 hits.
- **Owner-card visibility (unchanged):**
  - The Home needs tile reads «ждёт решения: 11 (у 11 тема не объявлена)».
  - The Decisions tab has 11 cards in `groups.undeclared`.
  - The 3 old owner items in attention link to #decisions.
- **Other P3s:** `recovery.date` is a raw ISO string, where the fixture uses «20.09». `unknown_en` is still Russian on several cards.
