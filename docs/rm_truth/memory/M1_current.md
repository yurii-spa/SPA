# RM-TRUTH-01 · M1 · Current memory (Studio OS memory v1, ADR-527) benchmark

**Worker:** M1 (current-memory benchmark), read-only against `~/Documents/SPA_mirror`.
**System under test:** `spa_core.studio_os.memory` (`assembler.assemble(q, budget_chars=12000, measure_host=False)`),
index relocated into scratch via `SPA_MEMORY_INDEX` (confirmed env hook: `spa_core/studio_os/memory/index.py:184`).
**Questions:** `M/questions.json` — 51 total (39 reused/adapted from `rmtruth/A6_memory_benchmark.json`'s
verified question bank + 12 newly phrased: N01–N12). All `ground_truth_sources` are mirror-relative paths,
individually verified to exist and asserted at build time (`build_questions.py`); every `ground_truth` string
was checked by hand against the cited file (ADR text, `architecture/roles.json`, `docs/ROADMAP.md`, `CLAUDE.md`,
`.claude/rules/*`). Scoring script: `M/run_bench.py` (self-contained, no pytest).

## Index build / recovery

| | value |
|---|---|
| First build | 5.758 s · 2252 files · 20475 chunks |
| Rebuild after deleting the index | 5.253 s · identical `sources_digest` (`43c192122d790c04`) |
| Recovery check | **identical answers** (same `top5_refs`, `verdict`, `coverage_ratio` for all 51 questions) |
| Roots indexed | spa, bridge, earndefi, company, claude, shadow (6; all present on this host) |

## Aggregate score (0–1, mean of 0/1/2 dims ÷2; `null` dims excluded)

| Scope | n | score | correctness | completeness | temporal | supersession | provenance | top5 | anywhere | p50 lat | max lat |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **All** | 51 | **0.759** | 0.735 | 0.688 | 0.714 | 0.700 | 0.892 | 31 | 38 | 0.543s | 0.974s |
| RU | 38 | 0.753 | 0.724 | 0.690 | 0.680 | 0.714 | 0.895 | 22 | 28 | 0.546s | 0.974s |
| EN | 13 | 0.774 | 0.769 | 0.682 | 0.800 | 0.667 | 0.885 | 9 | 10 | 0.532s | 0.614s |

RU vs EN is close (≤0.02 overall); EN looks slightly stronger on correctness/temporal but the EN subset is
small (n=13) and skews toward questions with cleaner English-labelled entities (ADR numbers, `com.spa.*`
labels) — not conclusive evidence of an RU penalty. Verdict distribution: **32 SUFFICIENT · 18 PARTIAL ·
1 INSUFFICIENT**.

## By class

| class | n | score | top5 | anywhere |
|---|---|---|---|---|
| product_profile_decisions | 3 | 0.955 | 3 | 3 |
| strategy_naming_old_vs_new | 2 | 1.000 | 2 | 2 |
| indicator_trading_origin | 1 | 1.000 | 1 | 1 |
| superseded_decisions | 6 | 0.865 | 4 | 6 |
| roadmap_decisions | 5 | 0.861 | 4 | 5 |
| owner_domains_risk | 1 | 0.833 | 0 | 1 |
| agent_purpose | 6 | 0.810 | 4 | 5 |
| director_os_intent | 4 | 0.765 | 3 | 3 |
| telegram_intent | 5 | 0.750 | 3 | 4 |
| three_owner_domains | 1 | 0.750 | 1 | 1 |
| sherlock_origin | 2 | 0.688 | 1 | 1 |
| trap | 2 | 0.667 | 0 | 0 |
| memory_decision | 1 | 0.625 | 0 | 0 |
| old_btc_experiments | 2 | 0.600 | 2 | 2 |
| repeated_incidents | 5 | 0.500 | 1 | 2 |
| **oracle_origin** | 3 | **0.458** | 0 | 0 |

**Weakest classes: `oracle_origin` (0.458) and `repeated_incidents` (0.500).** Both share a cause (see
Failure analysis): the search index ranks a flood of unrelated `ADR-NNN-<slug>` chunks above the real
answer because `.claude/rules/deployment.md` and `architecture/roles.json`/`ADR-554` are large, dense,
multi-topic files that lose to a shorter chunk with a lucky keyword overlap.

## False-"SUFFICIENT" (verdict claims enough evidence, but the real source never surfaces)

`H03e, H14, H15, H18, H18e(impl.), H19, H22, H24, H30(trap), N05` — **10 of 51 (20%)**.

- **7 of these 10 IDs reproduce exactly A6's own independent `false_sufficient` list** (`H03e, H14, H15, H18,
  H19, H22, H24` — see `rmtruth/A6_memory_benchmark.json`'s `summary.false_sufficient` /
  `sufficient_but_expected_missing`), run on the same mirror state 4 commits earlier (`b36acda46`) with a
  differently-built index. Same questions, independently re-derived scoring code, same failures — this is
  **reproducible**, not a scoring artifact of one run.
- **H30** is the inherited trap ("result of our Solana mainnet launch in 2024" — never happened): the
  assembler still reports `SUFFICIENT` (ratio 1.0) instead of refusing. A6 found the same thing. The
  assembler's `evidence_sufficiency` only measures *lexical concept coverage* of the question against
  retrieved chunks — it has no mechanism to notice "the retrieved chunks are irrelevant/off-topic," so a
  rare term match on 5 random ADR chunks is enough to call the package sufficient.
- **N05 is a newly-found instance of the same class**, not previously tested by A6: "Кто такой Шурик
  (COO role, `architecture/roles.json`, `implemented:false`) и реализована ли эта роль?" — top-5 pulled
  ADR-554/158/371/214 and `architecture/provenance.json`, never the actual `roles.json` entry, yet verdict
  = SUFFICIENT (ratio 1.0). The question's distinguishing term ("Шурик") never appears outside
  `roles.json`, so a healthy retriever should either surface that file or score low coverage; instead
  generic terms ("роль", "реализова-") matched broadly and the real source was crowded out.

## Failure analysis (why these fail)

1. **FTS5 ranking loses specific low-frequency Russian/named-entity terms to generic ADR boilerplate.**
   `oracle_origin`/`sherlock_origin`/`repeated_incidents` all ask about a specific proper noun
   (Оракул/Штирлиц, Шерлок, "ADR registry collision") whose best source is one dense file
   (`ADR-554`, `ADR-564`, `.claude/rules/deployment.md`). The BM25-style FTS5 ranking surfaces five
   *different*, topically-unrelated `ADR-NNN-*` chunks instead, because those files are long and this
   repo has hundreds of similarly-titled `docs/decisions/ADR-*` files that share generic vocabulary
   ("owner", "ADR", "two", "question", "door" — this corpus's ADR titles are unusually abstract/metaphoric,
   e.g. "ADR-429-a-door-that-counts-the-command-is-not-a-door.md"). Short, information-dense named-entity
   queries are exactly the case where a pure lexical index (no embeddings, no reranking) underperforms.
2. **`evidence_sufficiency.verdict` measures coverage of the *question's own terms*, not whether the
   *retrieved sources* are the right ones.** This produces the false-SUFFICIENT pattern and is the single
   most load-bearing finding of this benchmark (confirmed independently by A6 and by M1): a confident
   "SUFFICIENT" badge next to a wrong source list is more dangerous than an honest "PARTIAL/INSUFFICIENT",
   because it invites a reader to stop checking.
3. **Trap questions are not caught by construction.** Nothing in `assemble()` asks "does any retrieved
   chunk actually corroborate this claim," so a fabricated historical event (Solana mainnet launch,
   MiCA license) gets graded by the same lexical-coverage heuristic as a real one. N03 (MiCA) happened to
   score PARTIAL (0.78 coverage, correctly not SUFFICIENT) only because "license"/"EU" terms are rarer in
   this corpus than Solana-adjacent terms are in H30's corpus — a fragile distinction, not a real defense.
4. **Recovery is solid.** Deleting and rebuilding the index from scratch in ~5.3–5.8s reproduced the exact
   same `sources_digest` and every question's answer bit-for-bit (`top5_refs`, `verdict`, `coverage_ratio`).
   No determinism risk found.
5. **Latency is good and uniform** (p50 0.543s, max 0.974s, in-process) — not a bottleneck; the problem is
   retrieval precision/ranking and the sufficiency heuristic, not speed.

## Caveats / scope

- Scoring is **package-level** (what a downstream model would *see* in the JSON context package), via
  regex fact-matching and basename containment against `ground_truth_sources` — not an LLM-graded answer.
  This can slightly over- or under-credit (e.g. a fact regex matching inside an irrelevant chunk).
- `oracle_origin`/`sherlock_origin`/some `agent_purpose`/`telegram_intent` rows also pull chunks from
  `bridge:`/`shadow:`/`earndefi:` roots that are indexed but outside `~/Documents/SPA_mirror` — per task
  scope, `ground_truth_sources` in `questions.json` were restricted to **mirror-only, existence-verified**
  paths; cross-repo refs are visible in `top5_refs` but not scored as "expected."
- No MemPalace comparison is included here by design — that is the independent MemPalace worker's job
  against the same shared `M/questions.json`.

## Files

- `M/questions.json` — the shared 51-question set (schema: id, lang, question, ground_truth,
  ground_truth_sources, class, plus internal `_facts`/`_temporal_regex`/`_supersession_regex`/`_trap`
  grading aids reused from A6's methodology).
- `M/build_questions.py` — builds `questions.json` from the A6 base + 12 new questions, asserting every
  `ground_truth_sources` path exists in the mirror.
- `M/run_bench.py` — builds the index fresh into scratch, scores all 51 questions, runs the delete+rebuild
  recovery check, writes `M1_current_results.json`.
- `M/M1_current_results.json` — full per-question rows + aggregate summary (by lang, by class, false-
  sufficient list, verdict counts, index-build/recovery report).
