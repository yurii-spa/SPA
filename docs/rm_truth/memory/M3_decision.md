# RM-TRUTH-01 · M3 · Independent memory-architecture decision

**Reviewer:** M3, independent. I wrote neither M1 nor M2, nor the question set. Everything was read-only: no installs, no pytest, no repo writes.
**Inputs:**
- `M/questions.json` (51 questions)
- `M1_current*`, `M2_mempalace*`, `M2_run{1,2}_results.json`
- `A6_roadmap_memory.md`
- mirror `bbb127730` (2026-10-05): ADR-527, `spa_core/studio_os/memory/*`, `architecture/memory_truth.json` and `memory_benchmark.json`

**Re-measurement artifacts** (outside `rmtruth/`, scratch only): `scratchpad/m3_work/`, containing
- `rescore_m1.py` → `m1_rescore.json` (fresh index; reproduces M1 exactly, digest `43c192122d790c04`)
- `rescore_live.py` → `m1_live_index.json` (the real prod index, opened read-only)
- `rescore_m2.py` → `m2_rescore.json`

## DECISION: **HYBRID_BORROW_COMPONENTS**

Keep the stdlib FTS5 memory (ADR-527) as the only runtime. Borrow ideas from MemPalace, not code or dependencies, and repair the defects named below.

KEEP_CURRENT "as is" is rejected. The live system confidently misleads today: on the real prod index 25 % of answers are falsely SUFFICIENT. INTEGRATE_MEMPALACE is rejected on every axis that protects company memory:
- worse retrieval: top-5 hits 12/51 vs 31/51;
- larger Russian penalty;
- non-reproducible recovery;
- 81 dependencies, which violates invariant #4.

## 1. Audit of benchmark rigor (before trusting either number)

### Ground-truth spot check: 14 questions against the cited files

Twelve are exactly right: H06, H07, H09/ADR-292, H11, H13, H18, H19, H22, H25, H28, H29, N05, N10, N01 (all against ROADMAP.md rows 4–9). The other two have defects:
- **N04 is partly wrong.** The note «Штирлиц until 2026-10-04» lives in `docs/ROADMAP.md:26`, not in `architecture/roles.json`. roles.json only carries `display_name: "Oracle"` (grep finds 0 hits for Штирлиц there).
- **H24 is incomplete.** CLAUDE.md's "5 collisions" is correct for cross-registry numbers (029/030/048/050/053). But there are also duplicates inside each registry: `docs/decisions` 067/073/145 and `docs/adr` 002/021. That makes **10 colliding numbers**, not 5 and not A6's "16+".

Neither defect changes the verdict.

### Scoring asymmetries found

| Issue | Who it favours | Measured effect |
|---|---|---|
| M1 matches fact, temporal and supersession regexes against `json.dumps(pkg)`. That text includes `pkg.task` (the **question echoed back**), the sufficiency concept lists and `generated_at`. 16/51 questions have a fact regex that matches the question text itself. 7/51 have a temporal regex that matches the question or today's timestamp (e.g. N01 `2026-10-0[1-5]`, H19 `2026-10-0[45]`). | M1 | Evidence-only rescore: overall **0.759 → 0.744**; temporal 0.714 → 0.686; supersession 0.700 → 0.650; RU 0.753 → 0.733 |
| M2 compares the expected base `"spa:CLAUDE.md"` with the cited base `"CLAUDE.md"`, so root-level files can never match. | M1 | Fixed: M2 0.565 → **0.567**; any10 20 → 21; top-5 unchanged (12) |
| M2's corpus excluded `GITHUB_CREDENTIALS.md` (an H14 source) through an extra filename filter. | M1 | 1 question |
| Traps are `null` for M2 and earn a fiat provenance of 2 for M1. | mixed | Scoring traps as "no refusal = 0" for M2 gives 0.566. Negligible |
| M2 provenance uses a basename proxy, and its "anywhere" is top-10 vs M1's whole package. | M1 | Real, but the **top-5 basename hit** is computed identically on both sides and is the clean comparator: **31 vs 12** |
| N01–N12 have no `_facts`, so they are scored on source retrieval only and completeness is null. | neutral | 12/51 questions are effectively retrieval-only |

### Bias in question selection

- The question set is **not independent of the system under test**. A6 wrote 39 questions while benchmarking current memory, and M1 wrote 12 while scoring current memory.
- The set is heavy on ADR numbers and exact identifiers, where a lexical index is strong. It barely tests paraphrase recall, which is MemPalace's theoretical edge.
- **The verdict survives the bias anyway.** MemPalace also loses on its best subset, English (0.708 vs 0.774). It wins top-5 on only 2 questions (H03e, H08) against M1's 21. The ADR-527 held-out set reached the same conclusion.
- **Consequence for acceptance:** repairs must be accepted on a **held-out set written by an agent that never saw memory output** (§3, A9). questions.json alone would invite tuning to the test.

### The finding neither benchmark measured: production runs a stale index

Both workers built a **fresh** index. The index that every fresh session actually queries is different:
- `SPA_Claude/data/memory/index.db` was built **2026-10-03 18:38**, about 44 h before this review.
- Its digest `991429632a2cd723` ≠ the current `43c192122d790c04`.
- It has **0 chunks for ADR-552, 554, 556, 560, 563 and 564**.

Scored read-only against it:

| | fresh index (benchmark) | **live prod index (reality)** |
|---|---|---|
| overall (evidence-only) | 0.744 | **0.668** |
| top-5 / anywhere | 31 / 38 | **24 / 32** |
| false-SUFFICIENT | 10/51 (20 %) | **13/51 (25 %)**; adds H11, H25, N09 and N10: SUFFICIENT on decisions whose ADR is **not in the index at all** |
| oracle_origin / sherlock_origin | 0.458 / 0.562 | **0.208 / 0.125** |

Nothing rebuilds the index, and `search()` never compares the digest. This is the biggest risk to company memory, and it is a freshness defect, not a retrieval-technology one.

### Scope blind spot that M1 misattributed to ranking

`architecture/roles.json` is **not in the allow-list**. It is the ground-truth source for H18, H18e, H19, H19e, N04 and N05, and N05 (Шурик) is answerable *only* from it. So the N05 false-SUFFICIENT is a scope defect: the file cannot surface. `docs/decisions/INDEX.md` (H24) and `TOURNAMENT_VERDICT` (H21) are also unindexed.

## 2. Comparison (after corrections)

| Axis | Current (stdlib FTS5, ADR-527) | MemPalace 3.10.0 (embeddinggemma) | Winner |
|---|---|---|---|
| Correctness | 0.725 (evidence-only) | 0.459 | current |
| Completeness | 0.675 | 0.579 | current |
| Temporal | 0.686 | 0.629 | current (narrow) |
| Supersession | 0.650; explicit SUPERSEDED status from `memory_truth.json` | 0.550; no status concept | current |
| Source attribution | full `repo:path` + layer + status; top-5 31/51 | `room:basename` only; top-5 12/51 | current |
| Russian queries | RU 0.733 vs EN 0.774. Proper-noun gaps: H15/H15e, H19/H19e, H03/H03e, H08/H08e differ by language | RU 0.514 vs EN 0.708 | current; alias layer needed |
| Cross-file retrieval | 38/51 anywhere; fails on dense multi-topic files (deployment.md) | 21/51 | current |
| Latency | p50 0.54 s, max 0.97 s | p50 0.93 s, max 2.1 s | current |
| Trap / "no evidence" | Has a verdict, but **H30 → SUFFICIENT**; N03 PARTIAL by luck | No sufficiency concept at all | neither; current is fixable |
| Local-first | in-process SQLite, no model | offline OK, but ~800 MB model + 400 MB palace | current |
| Recovery | delete + rebuild 5.3 s, **bit-identical** (digest and 51/51 answers) | 34 min, **32/51 identical top-5**; score 0.565 → 0.539 | current, decisively |
| Operational complexity | 0 deps, invariant #4 kept | 81 PyPI deps, separate Python 3.12 venv, chromadb, onnxruntime, HNSW | current |
| Freshness in production | **44 h stale, no rebuild trigger** | would be worse (34-min rebuild) | neither; fix required |

## 3. What to borrow, with acceptance criteria

All criteria are measured with the **evidence-only scorer** on `questions.json` **and** on a new held-out set. Baselines are the current numbers on the fresh index unless marked "live".

**A1 · Freshness gate + rebuild on source change** (source: A6 (a); MemPalace's "mine on change", without the daemon)
- `assemble()` recomputes the cheap source digest (or mtime manifest) and compares it with the index manifest. On mismatch it rebuilds (≈6 s), or returns `verdict: STALE`, never SUFFICIENT.
- A scheduled rebuild runs after each mirror sync (every 30 min).
- **Accept:**
  - live index age vs mirror HEAD ≤ **60 min** (now 44 h);
  - a positive control adds a new ADR file after build, and the next `assemble` either finds it or says STALE (0 SUFFICIENT from a stale index);
  - live-index score equals fresh-index score (now 0.668 vs 0.744).

**A2 · Answer-level sufficiency: named entities must be in top-ranked canonical text** (source: A6 (b))
- SUFFICIENT requires every named entity of the question to occur in a **top-3** chunk that is CANONICAL/SEMANTIC and not superseded. Named entities are identifiers, ADR/role/agent ids, Latin or Cyrillic proper nouns, and years.
- Any missing entity ⇒ PARTIAL, and the missing entity is named.
- **Accept:**
  - false-SUFFICIENT **20 % → ≤ 5 %** (≤ 2/51 fresh; live now 25 %);
  - **0** traps SUFFICIENT;
  - SUFFICIENT with expected source in top-5 stays **≥ 18** (now 20), so the gate does not simply refuse everything.

**A3 · Trap questions in CI**
- At least **12** fabricated-event questions (RU and EN; for example Solana 2024, MiCA licence, a non-existent ADR-999, a renamed agent that never existed).
- Pinned as a stdlib test over a fixture or spa-only index.
- **Accept:** 100 % of traps INSUFFICIENT or PARTIAL. Any regression is red, and the test is not weakened (invariant #16).

**A4 · Allow-list expansion** (source: A6 (d) plus this review)
- **Add as CANONICAL:**
  - `architecture/roles.json`, one chunk per role;
  - `docs/decisions/INDEX.md`;
  - `docs/SYSTEM_MAP.md`;
  - `PROJECT_CONTROL/00_START_HERE.md`.
- **Add as history** (authority ≤ 1, status taken from `memory_truth.json`):
  - `docs/adr/*.md` (56 files), with a registry prefix so colliding numbers are disambiguated;
  - `MASTER_PLAN_v1.md`;
  - `docs/OWNER_BACKLOG_*.md`;
  - `docs/NN_*.md` (45 files, carrying their L-level);
  - `TOURNAMENT_VERDICT`.
- **Accept:**
  - un-indexed ground-truth sources in questions.json go from **3 files / 8 refs to 0**;
  - N05 has its source in the top-5;
  - **oracle_origin ≥ 0.80** (now 0.458; top-5 0/3 → 3/3);
  - **sherlock_origin ≥ 0.85** (now 0.562);
  - build ≤ 30 s;
  - the secret sanitizer stays clean (counted, not masked).

**A5 · Alias / entity layer** (MemPalace `entities` idea as a file-backed JSON, stdlib query expansion)
- Each alias carries an evidence ref and `valid_from`/`valid_to`. Seed entries:
  - Oracle ↔ Оракул ↔ Штирлиц (until 2026-10-04) ↔ СИО/CIO ↔ chief_investment_officer;
  - Sherlock ↔ Шерлок ↔ head_of_research;
  - Шурик ↔ chief_operating_officer;
  - Bridge ↔ Мост/Бридж ↔ com.studiobridge.telegram;
  - Director ↔ Директор ↔ director_server;
  - Mission Control ↔ Мишн Контрол;
  - Preserve/Core/Max Yield ↔ Conservative/Balanced/Aggressive;
  - Телеграм ↔ Telegram.
- **Accept:**
  - top-5 agreement in every RU/EN pair (now 4 mismatched pairs: H15, H19, H03, H08);
  - telegram_intent ≥ 0.85 (now 0.75);
  - RU score within 0.02 of EN.

**A6 · Temporal validity on facts and names** (MemPalace's temporal knowledge-graph idea, in `memory_truth.json`)
- `valid_from`/`valid_to` on facts and aliases. The package prints "ex-name / valid until" whenever a superseded name matches.
- **Accept:** supersession **0.65 → ≥ 0.85**, temporal **0.686 → ≥ 0.80** (evidence-only).

**A7 · Git first-seen / rename layer** (source: A6 (e); stdlib `git log --diff-filter=A --follow`)
- Records a first-seen date and rename chain per indexed path.
- **Accept:** for 10 sampled ADRs, `first_seen` is within ±1 day of the ADR's own date line; "when did X first appear" questions cite a commit.

**A8 · Keep deterministic recovery (regression guard)**
- **Accept:** delete + rebuild gives an identical `sources_digest` and identical top-5 and verdict on **51/51** (holds today).

**A9 · Benchmark hygiene**
- The scorer must exclude `task`, `generated_at`, `truth_policy` and the concept lists from fact matching.
- Every question needs `_facts`; N01–N12 have none today.
- Add a **held-out set of ≥ 30 questions written by an agent that has not seen memory output**.
- **Accept:** held-out evidence-only score **≥ 0.80** and held-out false-SUFFICIENT **≤ 5 %**.

**Do NOT borrow:**
- embeddings, chromadb or HNSW: non-deterministic rebuild (63 % reproducibility), 81 deps, invariant #4, 34-min build;
- the MemPalace daemon;
- any LLM-dependent mining.

Semantic recall stays optional later, and only via a stdlib-compatible path.

## 4. Memory blind spots for the "fresh-session proof" (30 questions from canonical sources)

1. **Stale prod index.** It is fatal for any decision from the last ~2 days: ADR-552…564 (Mission Control, Oracle, capital_shadow, Research Factory, rounding-down, Sherlock).
2. **Overconfident verdict.** 13/51 are falsely SUFFICIENT on the live index, including the trap and decisions absent from the index. A fresh session is told to stop checking exactly when it should not.
3. **Canonical sources that CLAUDE.md orders a session to read are not in memory:** SYSTEM_MAP, decisions/INDEX, OWNER_BACKLOG, PROJECT_CONTROL/00_START_HERE, the numbered architecture docs (ADR_004, 08, 10, CMO), SYSTEM_BRIEFING and roles.json. Of the session-bootstrap list, memory indexes only STATE.md and CLAUDE.md.
4. **Second ADR registry (`docs/adr`, 56 files) is invisible.** Number collisions are also undocumented in memory: 10 numbers, not 5.
5. **Proper-noun and alias questions in Russian** (Оракул, Шерлок, Мост, Директор, Шурик).
6. **Renames and history:** «как раньше называлось», «когда впервые появилось». There is no git first-seen layer, and ADR titles lag the registry (ADR-554 still says Штирлиц).
7. **Live-state numbers** (GoLive 29/29 inventory, 100 evidenced days, NAV, drawdown, which agents are alive). `data/` is excluded by design (correctly), so memory must answer UNKNOWN and **route** to `SYSTEM_BRIEFING.md`, `track_snapshot.json` or `launchctl`. The proof must score that routing, not a number.
8. **Wrong-tree trap.** The prod-tree `docs/STATE.md` is a stale 09-02 file (A6). A session must read the mirror or origin, and memory already indexes the mirror.

**Can current memory serve the proof after the fixes?**
- **Yes** for decision, canon, history, naming and supersession questions, once A1, A2, A4 and A5 are done. Those four are the gate: A1 is the precondition, because without it every other improvement is invisible to a fresh session.
- **No, by design,** for live-state numbers. Those questions must be answered by explicit routing to live artifacts, and the proof should count a correct routing plus UNKNOWN as a pass.
- **Before the fixes, the current memory must not be used as evidence for the proof:**
  - live index: 0.668 and 25 % false-SUFFICIENT;
  - oracle_origin and sherlock_origin: ≤ 0.21.
