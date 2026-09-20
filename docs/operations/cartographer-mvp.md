# Cartographer — Phase 0B System Map · Phase 0C Snapshot Diff

Read-only, rebuildable map of what SPA **declares** and what this Mac **actually** runs.
One manual run answers five questions and says plainly where the answer is UNKNOWN.
Phase 0C adds a second, **offline** step: compare two stored runs and say what really
changed, what merely became unobservable, and which source answers which kind of fact.

Phase 0A produced three artifacts (`snapshot.json`, `findings.json`, `summary.md`).
Phase 0B adds the graph (`system_map.json`, `system_map.md`), probes launchd **per
domain**, extracts the **entrypoint and its checkout**, and names the basis of every
comparison. It is derived state: the sources of truth stay where they are.

## Decision and boundaries

- **No second registry, scheduler or control plane.** `architecture/manifest.json` and
  `data/agent_registry.json` remain the declarations; the map only reads them.
- **Nothing in production is written.** Only `--output` is created, and it must be
  outside every observed repository and outside every launchd directory.
- **No existing writer is invoked** — in particular `scripts/code_sync_from_origin.sh` is
  never executed, only its scope (`CODE_PATHS`) is reused for the drift comparison.
- **Wrappers are never executed for analysis.** A dynamic target stays UNRESOLVED with a
  reason.
- **No inference is dressed up as execution.** Every edge carries `basis`:
  `declaration`, `observation` or `static_inference`.

## Run

```bash
cd ~/studio-os-scratch/cartographer-mvp
python3 scripts/cartographer/snapshot.py \
  --output ~/studio-os-snapshots/cartographer-phase0b-$(date +%Y%m%d-%H%M%S)
```

Optional: `--production <path>` (default `~/Documents/SPA_Claude`), repeatable `--repo
<path>` to observe an additional checkout. The output directory must not exist; snapshots
are never overwritten. Runtime on this Mac: ~9 s.

Five files are produced:

| File | Contents |
|---|---|
| `snapshot.json` | raw observations, per-stage flags, per-domain launchd state, drift |
| `system_map.json` | nodes, edges, `basis` + `evidence` per edge, `unresolved` list |
| `findings.json` | UNKNOWN / DRIFT / ORPHANED with stable ids and a reason each |
| `summary.md` | short summary, main divergences, coverage limits |
| `system_map.md` | grouped Mermaid overview (layers, checkouts, hot artifacts) |

## Contract

`snapshot.json` → `cartographer.snapshot/0.3`, `system_map.json` →
`cartographer.system_map/0.1`, `diff.json` → `cartographer.diff/0.1`,
`source_of_truth.json` → `cartographer.source_of_truth/0.2`. Referential integrity of the graph is validated before the
files are written (`system_map.validate`): a dangling edge, an unknown basis or an edge
without evidence aborts the run.

**Stages** are stored separately and never collapsed:
`DECLARED · REGISTERED · INSTALLED · LOADED · RUNNING · PRODUCING_OUTPUT · HEALTHY`.
`PRODUCING_OUTPUT` and `HEALTHY` are **always** null: a PID does not prove health and a
fresh file does not prove who wrote it (`producer_attribution: UNKNOWN`).

**Component statuses:** `LIVE · DEGRADED · STALE · LEGACY · DEAD · ORPHANED · UNKNOWN ·
DUPLICATED`. `DEAD` requires retirement evidence — absence of a PID is not it. Scheduled
idle is `LIVE`, not dead.

**Node types:** `launchd_job · plist_installed · plist_declared · entrypoint · checkout ·
artifact · document`.
**Edge types:** `declared_in_repo · installed_from · declares_entrypoint · resides_in ·
declares_target · produces · consumes · governed_by`.

## What Phase 0B hardened

| Class | Before | Now |
|---|---|---|
| launchd domains | only `launchctl list` (current user); absence assumed system-wide | `launchctl print` parsed BY BLOCK per domain plus a targeted `launchctl print <domain>/<label>` probe as the proof; enable/disable overrides kept apart from registered services; `LOADED` stays null while any domain is unreadable |
| probe failure | non-zero exit was indistinguishable from empty output | `_exec` returns an error **class** (`timeout` / `oserror` / `exit_nonzero`); stderr is never serialized |
| entrypoint | not extracted at all | launch FORM parsed by semantics (executable · script · module), relative paths resolved against `WorkingDirectory`, one target + an argument **count**; no other argv element is stored |
| checkout | not attributed | nearest ancestor containing `.git`, as an observation |
| wrapper target | — | `# AGENT_MODULE:` read statically when present, otherwise UNRESOLVED with a reason; the wrapper is never run |
| comparison basis | `drift` did not say which ref it used | the ref is resolved to a commit **once** before any dependent read; `basis: pinned_commit` + the `reference_sha` actually used by every read, and an explicit note that it is not a live query; live `ls-remote` is recorded separately |
| `last_exit` | used as if current | `last_exit_basis` records that launchctl keeps the **previous** exit status; `RUNNING` is checked first |
| exit-code meaning | interpreted implicitly | production declares a per-label dictionary; the map records codes and says it does not interpret them |
| symlinks | `stat` followed them silently | `is_symlink` recorded; declared outputs resolving outside the repo are omitted and named; drift existence uses `lexists` |
| plist environment | not read | key **names** only, never values |

## Drift: three populations, one meaning each

Production can carry code the compared ref no longer has. The three cases are kept apart
because they mean different things, and none of them is corrected:

- `changed_or_missing_on_disk` — present in the ref, different or absent on disk;
- `production_only_tracked` — tracked on disk, absent from the ref;
- `production_only_untracked` — untracked on disk, absent from the ref.

**Untracked does not mean retired or unneeded**, and `production_only_*` only means
"absent from the commit we compared against". The comparison resolves the cached
remote-tracking ref to a **commit SHA once**, and all three populations plus the document
index are read at that SHA — never at the ref name again (see third round, defect 2). The
live remote SHA is fetched separately with `ls-remote` and a divergence between the two is
reported as its own finding. Nothing is deleted, nothing is fixed, and no `git fetch` is
performed.

## Corrections after ARB review (2026-09-19, second round)

Four confirmed defects were fixed. One of them means an earlier published conclusion was
**wrong**, and it is retracted here rather than quietly overwritten.

### 1. `com.spa.httpserver` was NOT orphaned — that finding was false

The first Phase 0B run reported `com.spa.httpserver` as **ORPHANED** ("loaded in a launchd
domain without an installed plist"). **That conclusion was incorrect.** `launchd_domains()`
applied a label regex to the whole `launchctl print` output, including the
`disabled services = { … }` block, which lists enable/disable **overrides**. The label
appears there as `"com.spa.httpserver" => enabled` — a setting, not a registered service —
while `launchctl print gui/501/com.spa.httpserver` answers *could not find service*.

Now: the print output is parsed **by block** (registered services kept apart from
overrides), and LOADED rests on a **targeted** `launchctl print <domain>/<label>` probe
(~3 ms each). The label is reported as `LOADED=False` with its own rule,
`ENABLE_OVERRIDE_WITHOUT_SERVICE`, and the ORPHANED count is **0**. A difference between
domains is no longer framed as "probes disagree" — different domains answering differently
is normal, not a contradiction.

### 2. Entrypoint was chosen by "first argv element that exists"

Reproduced: `["/bin/bash", "/nonexistent/agent.sh", "/tmp"]` yielded **`/tmp`** as the
entrypoint, and `bash -c <cmd> /tmp` did too. The launch FORM is now parsed by semantics —
`Program`, a direct executable, `bash <script>`, `python -m <module>`, `python <script>` —
with relative paths resolved against `WorkingDirectory`. A declared script that is missing
is reported as missing and **never** replaced by a later argument; `-c` inline commands and
`env VAR=…` are unsupported forms and stay UNKNOWN with a reason.

### 3. Document resolution covered only ADR ids under two directories

`governed_by` carries both kinds: in production, **30 ADR identifiers and 12 plain
repo-relative paths**. The old index keyed ADR ids only, over `docs/decisions` +
`docs/adr`, so every path reference — including `docs/CMO_EDITORIAL_LAYER.md` and
`docs/08_ai_investment_os_architecture.md`, both present at the pinned SHA — was falsely
"unresolved". The index is now built from `docs/**` at **one pinned SHA** and answers three
distinct outcomes: `resolved` · `absent` (looked up in a complete index) ·
`index_unavailable` (UNKNOWN — no coverage, which is not the same as no document).

A second, self-inflicted bug surfaced while checking this fix: the ADR key pattern
`ADR-[A-Za-z0-9-]*\d+` was greedy and swallowed whole filenames, so
`ADR-129-owner-decisions-2026-08-23-batch4.md` was keyed as
`ADR-129-owner-decisions-2026-08-23-batch4` and a real `ADR-129` reference came out
"absent" although the file exists. The pattern is now anchored (`ADR-129`, `ADR-YL-004`,
`ADR-AI1-004`) and has its own regression test.

### 4. Findings ids were not unique

`findings.json` carried `DRIFT:com.spa.httpserver` **twice**, for two different
observations, because the id was `kind:subject` and the only real discriminator was the
mutable `reason` text. Every finding now has a stable `rule_code`, and the id is
`rule_code:subject[:context]`. Uniqueness is **validated** in `collect()` — a collision
raises instead of shipping.

## Corrections after ARB review (2026-09-19, third round)

Two further defects were confirmed and fixed. Both were leaks of a different kind: one of
data out of the parser, one of *time* into a comparison.

### 1. argv leaked into the diagnostic fields

Reproduced: `entrypoint_from_plist({"ProgramArguments": ["/usr/bin/python3",
"--api-key=<secret>"]})` put the **argument value** into `unknown_reason`, because the
reason was an f-string over the offending argument. The same interpolation existed for
unsupported shell options. The parser deliberately stores no argv — and then described the
argv it refused to store.

Now every unresolved branch returns a **code from a closed vocabulary**
(`ENTRYPOINT_REASONS`, 9 entries) and the human text is a **constant** belonging to that
code; the offending option text is never stored. Two plists carrying two different secrets
produce byte-identical reasons. `unknown_code` is the machine-readable field,
`unknown_reason` its fixed description.

Kept by design, and stated so it is not mistaken for a leak: for `python -m <module>` the
**module name** and for a script form the **script path** are stored — they are the
entrypoint target, which is the whole point of the parse. Only non-target argv is dropped.

The regression does not check one field: it plants a sentinel in `ProgramArguments`, runs a
full `collect()`, builds the graph and renders both Markdown files, then asserts the
sentinel is absent from **all five artifacts** — snapshot, map, findings, `summary.md` and
`system_map.md`. Positive control: re-introducing the f-string turns it red.

### 2. The Git comparison baseline was named, not pinned

`document_index()` called `rev-parse(ref)` and then `ls-tree(ref)`; `drift()` read the ref
name three more times. Every read therefore resolved the ref **again**, so a
remote-tracking ref moving mid-run (a concurrent `git fetch` — normal on this Mac) would
silently mix two commits inside one "comparison", and the stored `reference_sha` would not
be the SHA the numbers came from.

Now `resolve_baseline()` resolves `<ref>^{commit}` **once** per repository, validates it as
40 hex, and the SHA is threaded into `document_index()` and `drift()`; every dependent read
takes the SHA. `basis` is `pinned_commit` and `reference_sha` is the SHA actually used. If
the baseline cannot be resolved, the run yields **UNKNOWN** with a `BASELINE_UNRESOLVED`
finding instead of a plausible-looking result. Positive control: making one read take the
ref name again turns the "ref moves between operations" test red.

## Live run of 2026-09-19 (final set, third round)

`~/studio-os-snapshots/cartographer-phase0b-r3-20260919-174243/`

101 components · 614 processes · **569 nodes** · **548 edges**
(`observation` 289, `declaration` 255, `static_inference` 4) · graph integrity validated,
and the graph **rebuilt from the stored `snapshot.json`** reproduces the saved
`system_map.json` node-for-node and edge-for-edge.
Statuses: `LIVE 76 · LEGACY 13 · UNKNOWN 7 · DEGRADED 4 · STALE 1` — **ORPHANED 0**.
Findings: **109, all 109 ids unique**, across 9 rules — `UNKNOWN 87 · DRIFT 22`.
Documents: **42 of 42 references resolved** against pinned `0d1e662c2386`; the document
index carries the **same** SHA as the drift comparison, which is now a checked property.
Entrypoints: 81 of 81 installed plists resolved (0 unresolved codes in live data — the
closed vocabulary is exercised by tests, not by this Mac). Unresolved claims: **77**, all
of one kind — a wrapper whose target is dynamic and which is deliberately never executed.
Drift: `changed_or_missing_on_disk` **0** · `production_only_tracked` 15 ·
`production_only_untracked` 2.

**Why `changed_or_missing_on_disk` fell 6 → 0 between the two sets, and why it is not
credit for the fix.** Both runs compared against the *same* commit `0d1e662c2386`. The six
files (`copy_independence_probe`, `vacuous_guard_census`, `vacuous_guard_probe` and their
three tests) converged **on disk** in the nine minutes between the runs — that is
`code_sync_from_origin.sh` doing its job, not the parser changing its mind. The pinning fix
changes *which commit* the numbers belong to and makes it recorded; it cannot change the
contents of the working tree.

Earlier artifact sets are kept for comparison and are **not** authoritative: `…-170235` and
`…-171905` contain the false ORPHANED finding and the duplicate finding id; `…-173352`
predates the two fixes above and reports `basis: cached_ref`.

## Acceptance and tests

```bash
cd ~/studio-os-scratch/cartographer-mvp
python3 -m pytest tests/cartographer/ -q -p no:randomly
```

186 tests (`test_snapshot.py`, `test_system_map.py`, `test_diff.py`,
`test_source_of_truth.py`). Each hardened and each corrected class has its own control,
including: an unreadable domain keeps
`LOADED` null; a label present only in the `system` domain still counts as loaded; a plist
whose argv and environment contain a token leaks neither into the output; a declared output
that symlinks out of the repository is omitted **and named**; drift detects all three
populations **without touching the git index**; a dangling graph edge aborts validation;
the Mermaid overview stays readable with 60 jobs; an enable override without a service is not LOADED; a missing script is not replaced by a later argument; a plain doc path and an ADR id both resolve while a truly missing path is `absent` and a missing index is UNKNOWN; two rules on one entity get two ids; every unresolved entrypoint branch yields a fixed code and two different secrets produce identical reason text; a sentinel planted in argv is absent from all five artifacts; dependent git reads carry the SHA and not the ref name, a ref moving between operations does not change the answer, and an unresolvable baseline is UNKNOWN rather than a number.

## Phase 0C — comparing two snapshots, offline

Two stored runs in, one short answer out. The comparison opens the two artifact sets and
**nothing else**: no launchd, no git, no network, no production read. `diff.py` imports
neither `subprocess` nor `socket` nor `urllib`, and a behavioural control runs the whole
comparison with those doors patched to raise.

```bash
cd ~/studio-os-scratch/cartographer-mvp
# 1. take a snapshot (five files, as in Phase 0B)
python3 scripts/cartographer/snapshot.py \
  --output ~/studio-os-snapshots/cartographer-$(date +%Y%m%d-%H%M%S)
# 2. compare two stored sets — offline, inputs are never modified
python3 scripts/cartographer/diff.py \
  --old  <earlier artifact dir> \
  --new  <later artifact dir> \
  --output ~/studio-os-snapshots/cartographer-compare-$(date +%Y%m%d-%H%M%S)
```

Four files are produced, mode 0600 in a 0700 directory that must not already exist:

| File | Contents |
|---|---|
| `diff.json` | every change with a stable id, class, materiality and evidence; findings split into new / persisting / resolved / not_rechecked; input hashes |
| `changes.md` | the short report: material · observation quality · persisting · owner's desk · unknown |
| `source_of_truth.json` | which source answers which kind of fact, and where sources disagree |
| `source_of_truth.md` | the same, readable |

### The hard part is refusing to invent a change

Spotting differences is easy; six of them would be lies. Each rule below has a test that
goes red when the rule is removed.

| Situation | Naive answer | What is reported |
|---|---|---|
| `LOADED` true → null | "the service stopped" | `STAGE_OBSERVATION_LOST` — loss of knowledge, materiality `observation_quality` |
| a component is missing while its source failed | "it was removed" | `COMPONENT_ABSENT_UNVERIFIABLE`; removal needs every source that placed it to be readable again |
| a finding is absent from the new array | "it was fixed" | `RESOLVED` only when the rule's coverage requirements held in the new run; otherwise `NOT_RECHECKED` |
| a drift list got shorter under a moved baseline | "production was fixed" | `BASELINE_CHANGED` + materiality `not_comparable`; the yardstick moved, not the tree |
| a different PID | "it restarted / it crashed" | `PID_CHANGED`, materiality `informational`, with the reason spelled out |
| a scheduled job is idle now and ran before | "an incident" | materiality `expected_schedule` |
| a file got older | "stale" | nothing at all; only crossing the **declared** SLO is `ARTIFACT_SLO_CROSSED` |
| a field exists on one side only | "it became false" | `SCHEMA_FIELD_ABSENT`, never read as a value |

Timestamps, file ages, sizes and the ORDER of every array are ignored by construction:
comparison is by whitelist and keys by identity (label, plist path, artifact relpath,
reference), never by list position. The process table is not compared row by row — only
its size is reported.

### A finding is resolved by evidence, not by silence

`RECHECK_SPECS` says, per `rule_code`, what must be true of the new run before absence may
be called a fix, and a global coverage flag is never enough on its own (see round 2 below):

1. the **coverage** the rule depends on held;
2. the rule's **subject** is still in comparable scope — the same component, the same
   repository, the same domain, under the same declared observation scope;
3. the specific inputs the rule's own condition reads were **observed for that subject** —
   `STATUS_STALE` needs the artifact metadata to have been obtained, a launchd status needs
   the *targeted probe for that label* to have answered (a readable domain is not a probed
   label), a `DRIFT_*` rule needs the same pinned baseline **and** its own path to have left
   its own category.

A rule that is not in the table is deliberately **not** resolvable: an unknown rule means an
unknown probe. When the object a rule spoke about is gone — the plist uninstalled, the
`governed_by` reference withdrawn, the declared output removed, the component out of scope —
the verdict is `APPLICABILITY_CHANGED`, reported separately and never as a fix.

### Source-of-truth map

`source_of_truth.py` holds ten fact types as data — a table of interpretation rules, not a
second registry: **no agent is listed there**, the manifest remains the only place that
enumerates agents. Each fact type states its source, its observation method, what it
proves, **what it does not prove**, its scope and observation window, its freshness rule
*only where a threshold already exists in the repository* (registry 26 h, code_sync 1 h,
artifacts per declared `slo_hours`; everything else `POLICY_UNDEFINED`), its limits and how
unavailability is marked.

No source is authoritative in general. Where statements differ, **both** are kept with
`resolution_policy: POLICY_UNDEFINED` — the repository declares no resolution policy and the
map does not invent one, rewrite a source or correct anything. Each difference carries a
`kind`, because a difference is not automatically a contradiction:

| kind | meaning |
|---|---|
| `contradiction` | incompatible claims about **one** fact under comparable conditions |
| `declaration_vs_observation` | intention against observation — different questions, both answers can be true |
| `declaration_difference` | two declarations differ and no rule requires them to agree |
| `scope_difference` | both true, different scope or different moment |
| `different_subject` | the statements are not about the same thing at all |

`validate()` refuses a `contradiction` that spans more than one fact type: two different
questions cannot be incompatible.

Owner-decision candidates are derived only from rules that already exist in writing
(`.claude/rules/deployment.md` п. 6 and п. 4, `CLAUDE.md` инв. 12), each quoting where the
rule lives, and every one carries `severity: POLICY_UNDEFINED` and
`action_taken: NONE`.

### Schema 0.3 and what happens to an accepted 0.2 set

`snapshot.json` moves to `cartographer.snapshot/0.3`, which adds exactly two blocks:

- `coverage` — what the run was ABLE to observe (each source readable, each domain,
  drift measurable per repository, the baseline SHA used). Without it, "the finding is
  gone" cannot be told from "the probe that saw it did not run".
- `reference_documents` — ten governance documents already in the repository, resolved
  **twice** and kept apart: present in the pinned commit's `docs/**` index, and present in
  the production tree. Those are different facts, so they are not merged.

An accepted 0.2 set is still comparable. Its coverage is **inferred** from the finding
vocabulary of the producer that wrote it (that producer emits `SOURCE_UNREADABLE` whenever
the manifest is unreadable, so the absence of that finding is evidence, not silence), the
diff records `coverage_basis: inferred_from_findings`, and anything resolved on that basis
carries `recheck_basis` so a reader can discount it. A missing field is a schema gap, never
`False`. An unsupported schema, a corrupt file or a missing `snapshot.json` **raises** and
writes nothing — "INCOMPATIBLE INPUT … This is NOT 'no changes'."

## Live verification of 2026-09-19 (Phase 0C)

Two fresh snapshots, thirteen seconds apart, and one comparison against the accepted
Phase 0B set. Nothing in production was changed to manufacture a difference.

**Two current snapshots** — `~/studio-os-snapshots/cartographer-phase0c-A-20260919-232311` → `~/studio-os-snapshots/cartographer-phase0c-B-20260919-232324`
compared into `~/studio-os-snapshots/cartographer-phase0c-compare-current-20260919-232619`:
**no changes at all** (`counts: {}`). That is the correct result, and the report says so
in words rather than showing an empty page; 108 findings are reported as *persisting*,
grouped by rule (77 wrapper UNKNOWNs are one line, not 77).

**Accepted Phase 0B set → current** — `…-r3-20260919-174243` (schema 0.2) → the new set,
compared into `~/studio-os-snapshots/cartographer-phase0c-compare-historical-20260919-232619`:
6 material · 2 observation-quality · 2 informational. The real events it found:

- `com.spa.daily_cycle`: `last_exit` 3 → 0 and status `DEGRADED` → `LIVE`, with the
  `STATUS_DEGRADED` finding **resolved on evidence** — the probes that produce it ran
  again over a comparable scope;
- two declared artifacts of `com.spa.decision_loop` appeared (`exists` false → true), and
  their freshness moved from UNKNOWN to true — reported as observation quality, because
  "we could not judge" becoming "fresh" is not the same event as "stale" becoming "fresh";
- `BASELINE_CHANGED` `0d1e662c2386` → `968adf0e3c19`: `origin/main` advanced between the
  two runs, and the report states that any drift difference under it would **not** be
  evidence that production was fixed. (The three drift populations happened to be
  identical against both commits, so no drift change was reported at all.)

The source-of-truth map found three divergences and resolved none. After round 2 they are
classified, and **none of them is a contradiction** (`contradiction_count: 0`): 5 labels in
the registry but not the manifest against 13 the other way is a `declaration_difference`
(nothing requires the two to agree); `code_sync` reporting `IN_SYNC` at 21:19 beside 17
production-only files against the pinned commit is a `scope_difference` (different scope,
different moment); `com.spa.httpserver` holding an enable override with no registered
service is a `different_subject` (a setting is not a registration).

**A defect the live run found in my own work.** The owner-decision condition
`installed_but_not_loaded` was first derived from the `STATUS_DEGRADED` label. On this Mac
all three DEGRADED components were `LOADED=True`, degraded only by a historical non-zero
`last_exit` — so the report filed them under a name that was not true of them. The
condition now reads the STAGES (`intent=active` ∧ `INSTALLED` ∧ ¬`LOADED`), and a component
degraded by an exit code produces **no** owner item: the map does not interpret exit codes,
and no written rule makes "last outcome non-zero" the owner's decision. Three regressions
hold that line.

## Corrections after ARB review (Phase 0C, round 2)

Two defects were reproduced and fixed, and one classification was overstating its evidence.

### 1. RESOLVED rested on global flags, not on this rule and this object

Reproduced on the accepted live snapshot: making `com.spa.analytics_tier_b`'s declared
outputs unobservable (`exists: null`, `fresh: null`), dropping the `STATUS_STALE` finding
that is no longer computed from such data, and leaving `manifest_readable` true made the
comparison announce **STATUS_STALE RESOLVED** — a claim that a file is fresh when nobody
managed to stat it.

`RECHECK_REQUIREMENTS` (a list of global coverage flags) is replaced by `RECHECK_SPECS`,
which additionally pins the SUBJECT and the rule's own condition. Reviewed across the whole
rule set, the substantive changes are:

- `STATUS_STALE` — needs the SPECIFIC outputs that were overdue to be shown fresh again
  (see round 3 below);
- every launchd-derived status — needs the **targeted probe for that label** to have
  answered in each domain, not merely the domain to have been readable;
- `REMOTE_UNAVAILABLE` and `CACHED_VS_REMOTE_DIVERGED` — the old `always` proved nothing
  about *this* repository; they now need a successful live remote probe for it;
- `DRIFT_*` — same repository, same pinned baseline, **and** the path gone from its own
  category; a repository that left the observed set resolves nothing;
- a plist uninstalled, a `governed_by` reference withdrawn, a declared output removed or a
  component gone from scope → `APPLICABILITY_CHANGED`, reported separately.

This is deliberately **not** a blanket ban on RESOLVED: with the artifacts observed and
fresh the same scene still resolves, and the live historical comparison still resolves
`STATUS_DEGRADED:com.spa.daily_cycle` — now listing the evidence it rested on
(`coverage:launchctl_list_ok`, `coverage:installed_scan_complete`,
`stages:INSTALLED,LOADED,RUNNING`, `domains_probed`).

### 2. The input contract was not checked

Reproduced: `{"schema_version": "cartographer.snapshot/0.3", "entities": []}` was accepted,
fell back to the 0.2 coverage inference — thereby *assuming* every source had been readable —
and produced a report with material changes out of a truncated file.

`validate_snapshot()` now runs before any comparison and checks required fields and their
types, the coverage block **as the version requires it**, entity and finding structure,
vocabularies, referenced identifiers and id uniqueness. A 0.3 snapshot without a recorded
`coverage` block is refused rather than inferred — inheriting an assumption about which
sources were readable is exactly how a truncated file became "everything was observed". An
empty result is still legal when the rest of the contract is present, so a quiet machine and
a truncated file no longer look alike.

0.2 is supported only within the contract it can prove: `rule_code` on every finding and
unique ids. That excludes precisely the pre-round-2 artifact sets (`…-170235`, `…-171905`
and the two `cartographer/0.1` sets), which are the ones carrying the duplicate-id defect;
the accepted `…-r3-…` set and both 0.3 sets load unchanged, and a test asserts that.

### 3. "Conflict" overstated what had been shown

The map called three things proven conflicts. None of them is: `IN_SYNC` beside
production-only files compares different scopes at different moments; an enable override
without a service is a setting next to a registration, not two answers to one question; and
manifest membership differing from registry membership is two declarations with **no
established requirement that they agree**. The key is now `divergences`, every entry carries
a `kind` from a fixed vocabulary, `contradiction_count` is reported separately, and
`validate()` rejects a `contradiction` spanning more than one fact type. A genuine
contradiction is still recognised — the domain's `services` block listing a label while the
targeted probe for that same domain answers "absent" — and on this Mac it does not occur.

### Live re-runs after the fixes

Two current sets → `~/studio-os-snapshots/cartographer-phase0c-r2-compare-current-20260920-000957`: still no changes at all.
Accepted 0.2 set → current 0.3 → `~/studio-os-snapshots/cartographer-phase0c-r2-compare-historical-20260920-000957`: 6 material, 2 observation-quality,
2 informational, one finding resolved **with its evidence listed**, nothing
not-rechecked and nothing applicability-changed. Both maps: 3 divergences, 0 contradictions.
Earlier artifact sets are kept untouched.

## Corrections after ARB review (Phase 0C, round 3)

One blocker: `STATUS_STALE` was resolved on the wrong evidence.

Reproduced on the accepted live snapshot, where `com.spa.analytics_tier_b` declares
`data/analytics_report_full.json` (`exists: true`, `fresh: false`) and
`data/analytics_signals_advisory.json` (`exists: true`, `fresh: true`). Three independent
edits, each removing the `STATUS_STALE` finding, **all three produced RESOLVED**:

1. the overdue file disappears (`exists: false`, `fresh: null`);
2. the overdue output alone is withdrawn from `declared_outputs`;
3. the overdue output keeps its place but loses `slo_hours` (`fresh: null`).

The predicate asked only "is artifact metadata available now" and noticed a change of
applicability only when the whole output list vanished. None of the three is evidence that
the overdue artifact recovered — one is a file disappearing, one a declaration being
withdrawn, one the yardstick being removed.

The rule's cause is now **reconstructed from the old snapshot**: the specific outputs that
were `fresh: false`. Each is matched by its stable `relpath`, and resolution requires

- the same output still declared, with the **same** `slo_hours` — otherwise freshness is
  not comparable with the condition that fired (`APPLICABILITY_CHANGED`);
- positive evidence of freshness for it: `exists: true` **and** `fresh: true`. An absent
  artifact is reported explicitly as absent — "a file disappearing is not a recovery" — and
  is NOT_RECHECKED, not a fix;
- no stale condition persisting anywhere in the component, and no output whose staleness is
  **undetermined** (an SLO declared but the metadata not obtained), because the absence of a
  stale condition has to be established rather than assumed.

With several overdue outputs, partial evidence never resolves the aggregate finding, and
missing evidence outranks lost applicability: not knowing is weaker than knowing the rule
moved. If the old snapshot does not record WHICH output was overdue, the verdict is
NOT_RECHECKED rather than a guess.

Twelve regressions cover the three reproduced cases, an SLO changed rather than removed,
two overdue outputs with one recovered, partial evidence, an unobserved neighbour, a
neighbour that became stale, an unreconstructable cause — and a positive control where a
genuine recovery still resolves. Six mutations were verified red, including a full
restoration of the previous check (11 failures).

**Live re-runs after the fix** — `~/studio-os-snapshots/cartographer-phase0c-r3-compare-current-20260920-002148` (two current sets:
still no changes) and `~/studio-os-snapshots/cartographer-phase0c-r3-compare-historical-20260920-002148` (accepted 0.2 →
current 0.3: 6 material, 2 observation-quality, 2 informational, one finding resolved with
its evidence listed). Both semantic digests are **identical to the previous round**: these
sets contain no `STATUS_STALE` transition, so the correction does not perturb them — which
is the expected result, not an absence of effect. Earlier artifact sets are kept.

## Still UNKNOWN (by construction, not by omission)

- `HEALTHY` and `PRODUCING_OUTPUT` for every component — no semantic probe exists.
- Which process wrote a given artifact — freshness is not attribution.
- The target of the 77 wrappers (measured, not estimated) whose entrypoint is a shell
  script with a dynamic target.
- Anything in a launchd domain we cannot read (both are readable on this Mac today, and
  that is recorded per run rather than assumed).
- Whether a non-zero `last_exit` is a fault or normal for that label — production has a
  per-label dictionary that the map deliberately does not apply.
- What a stored snapshot did not record: the comparison never reconstructs the past from
  the machine as it is today, so an unrecorded fact stays UNKNOWN rather than being
  back-filled from the present.
- Whether a change happened at one instant: neither snapshot is atomic, so a difference
  may straddle the two observation windows rather than a single moment.
