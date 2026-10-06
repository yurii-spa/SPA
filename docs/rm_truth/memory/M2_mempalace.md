# RM-TRUTH-01 · M2 · MemPalace benchmark (isolated, read-only, offline)

**Worker:** M2 (isolated MemPalace benchmark), strict isolation per brief — nothing installed into the
trusted runtime (`~/miniconda3`) or any repo; no paid API; no secret ingestion; writes only under
`scratchpad/rmtruth/M/`. **Exclusion list applied on top of `spa_core.studio_os.memory.sources` (ADR-527)
during the corpus copy:** filenames containing `keychain`, `.env`, `.pem`, `github_pat`, `openclaw`,
`secret`, `credential` were skipped outright (9 files, all legitimate *about*-secrets docs like
`GITHUB_CREDENTIALS.md`/`ADR-132-pat-rotation-keychain-identity.md`, not secrets themselves — the
underlying `sources.py` allow-list already excludes `.git/`, `data/`, `*.db`, `*.pem`, `*.key`, `.ssh/`
and drops any line matching a credential-shape regex; zero secret lines were dropped because none existed
in the allowed set). No Keychain, no `~/.openclaw`, no `.env` file was ever opened.

## Setup: reused, not reinstalled

Found the prior ADR-527 review's isolated MemPalace setup at
`/private/tmp/claude-501/.../4a80058d-bbff-490b-99f7-24901944c2f9/scratchpad/mempalace-eval/`
(venv + MemPalace 3.10.0 + cached `embeddinggemma-300m-ONNX` (629MB) and `all-MiniLM-L6-v2` (166MB) model
weights). **Nothing was installed or downloaded.** I copied that venv (312MB) and the two model caches
(796MB) into `M/venv` and `M/home/.cache` (both runs completed with zero HF download progress bars,
confirming the caches were reused, not re-fetched). The venv's Python is a separate `uv`-managed
CPython 3.12.13 at `~/.local/share/uv/python/...` — not the project's trusted miniconda env.

The old corpus snapshot (frozen 2026-10-01) was **not** reused for the main run: I rebuilt a fresh corpus
from the live roots using the mirror's own `spa_core.studio_os.memory.sources.iter_files()` +
`sanitize()` (read-only import, stdlib only) so MemPalace indexes **exactly the same allow-listed,
secret-sanitized source set the current memory system indexes** — same six roots (spa/bridge/earndefi/
company/claude/shadow), as of mirror commit `bbb127730` (2026-10-05). Result: 2243 files (vs M1's 2252 —
the 9-file gap is my extra name-hint exclusion above, not a scope difference in `sources.py`).

## Results on the shared 51-question set (`M/questions.json`), same rubric as M1

| | M1 (current stdlib memory) | M2 (MemPalace, embeddinggemma) |
|---|---|---|
| **Overall score** | **0.759** | **0.565** |
| correctness | 0.735 | 0.459 |
| completeness | 0.688 | 0.579 |
| temporal | 0.714 | 0.629 |
| supersession | 0.700 | 0.550 |
| provenance | 0.892 | 0.618 |
| expected source in top-5 | 31/51 | 12/51 |
| expected source anywhere (top-5 / top-10) | 38/51 | 20/51 |
| latency p50 | 0.543s | 0.929s |
| latency max | 0.974s | 0.961s (run1) / **2.126s** (run2) |

**Head-to-head on the identical 51 questions:** both hit top-5 on **10**, M1-only on **21**, MemPalace-only
on **2**, neither on **18**. The two MemPalace-only wins are H03e (Director OS, English) and H08 (roadmap
canon, Russian) — small, not evidence of a systematic edge. RU (0.511) vs EN (0.708) — MemPalace shows a
**much larger Russian penalty** than the current system (RU 0.753 vs EN 0.774, near parity). This
reproduces the ADR-527 finding again, independently and on a larger/fresher question set.

**This confirms the prior verdict (option C / HYBRID_BORROW) a third time** — now on 51 (not 12, not 39)
questions, a corpus rebuilt fresh against *today's* mirror state rather than reused from 10-01, and a
genuine delete+rebuild rather than a single build.

## Index build / size / recovery — the headline new finding

| | value |
|---|---|
| First build (`mine`, 2243 files, embeddinggemma) | **2040.3s ≈ 34.0 min**, 31969 drawers |
| Palace size | 397 MB |
| Rebuild after deleting the palace (identical corpus) | 2031.4s ≈ 33.9 min, 31969 drawers, 391 MB |
| **Recovery — identical top-5 answers?** | **NO — only 32/51 (63%).** 19 questions got a *different*
top-5 ref list on the rebuild; several (H14, H17, H19, H22) swapped in genuinely different documents, not
just reordered the same five. Aggregate score moved 0.565 → 0.539 between the two runs. |

**This is the one result M1 could not produce a comparator for.** The current stdlib memory system
(`spa_core.studio_os.memory`, SQLite FTS5) rebuilds **byte-identical** after delete+rebuild (M1: same
`sources_digest`, same `top5_refs`/`verdict`/`coverage_ratio` for all 51 questions). MemPalace, mining the
*exact same* 2243-file corpus with the *exact same* `embeddinggemma` config, does not: same file count,
same drawer count, same model — but different nearest-neighbor results on 37% of questions. This points
to order-dependent floating-point accumulation in batched embedding and/or HNSW graph-construction order,
not a corpus or config drift (both runs' `mempalace_embedder.json` and file lists are identical). For a
system meant to be "the source of truth that doesn't need re-checking," non-reproducible recovery is a
structural defect independent of retrieval quality.

## Operational complexity

| | current memory (spa_core.studio_os.memory) | MemPalace |
|---|---|---|
| Runtime deps | 0 (stdlib only — CLAUDE.md invariant #4) | **81** distinct PyPI packages (chromadb, onnxruntime, huggingface_hub, grpcio, opentelemetry-*, numpy, …) |
| Python | any stdlib-capable interpreter | 3.12 (needs a dedicated venv; no system-site-packages) |
| Background services | none — in-process call | none *required* for the CLI path used here (`--direct`); an **optional** long-lived `mempalace daemon` exists for async mining/sync |
| Network calls at query time | none (local SQLite) | none observed — chromadb telemetry is **hardcoded off** in `mempalace/__init__.py` and `mempalace/backends/chroma.py` (`Settings(anonymized_telemetry=False)`), independent of env vars; `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` set as a second guard |
| Model downloads | none — no model | **~800MB** (embeddinggemma 629MB + minilm 166MB) one-time, offline-cacheable; zero on this run (cache reused) |
| Build time (2243 files) | 5.5–5.8s | **~34 min** |
| Index size | small SQLite file | **~400MB** |

## Caveats on the 0–2 scoring (read before citing a single number)

- **Trap questions (H30, N03) could not be scored on correctness/completeness.** MemPalace's `search`
  has no equivalent to the current system's `evidence_sufficiency.verdict` — there is nothing to check
  "did it correctly refuse/claim SUFFICIENT." I scored those two dims `null` (not 0) rather than invent a
  pass/fail the tool doesn't attempt, per the same no-evidence-is-not-zero discipline M1 and the project's
  own invariant #17 use. Only provenance (did it avoid citing anything for the fabricated event — it did,
  on both) was scored for traps.
- **Provenance is weaker evidence for MemPalace than for M1.** M1's provenance dimension can check a full
  citation path (`spa:docs/decisions/...`); MemPalace's CLI only prints `room:basename`, so the provenance
  heuristic falls back to "basename looks like an ADR or a named rule file" — a strictly weaker proxy,
  biasing this one dimension pessimistically for MemPalace. Not adjusted for; noted instead.
- **"Anywhere" is top-10 for MemPalace vs the full ~12000-char assembled package for M1** (which can cite
  well past 5 sources via `semantic_facts.evidence`). This narrows MemPalace's "anywhere" credit relative
  to M1's; widening `--results` further did not materially change the picture in spot checks.
- Package-level grading (regex/basename matching), not an LLM-graded answer — same limitation M1 states.

## Files

- `M/build_corpus.py` — copies the live allow-listed, sanitized source set (6 roots, 2243 files) from
  `sources.py` into `M/corpus/`; report in `M/corpus_build_report.json`.
- `M/score_mempalace.py` — runs all 51 questions through `mempalace search --results 10` (offline venv),
  parses hit blocks, scores with the adapted M1 rubric.
- `M/M2_mempalace_results.json` — full per-question rows (run1) + summary (all/ru/en/by_class) +
  `index_build` (build/rebuild timings, sizes, the 19 recovery diffs) + `operational_complexity`.
- `M/venv/`, `M/home/`, `M/palace/` (run1), `M/palace2/` (run2, recovery test), `M/corpus/` — the reused
  offline install and the two independently-built palaces, kept for inspection.
