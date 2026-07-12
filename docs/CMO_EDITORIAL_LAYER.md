# CMO Editorial Layer — spec (owner-directed 2026-07-12)

> Owner idea: the raw auto-journal (Q2-14) is DRY. Add a "CMO / marketer" layer that rewrites each
> entry into engaging, selling, interesting copy — **but only within the honesty floor.** Owner chose
> **flow B: draft → owner approves → publish** (NOT auto-publish). Approval surface starts simple;
> **later becomes a Kanban board** where the owner reads + approves drafts ("канбан доски для моих
> апрувов и там я буду читать").

## Flow

```
Raw journal (deterministic facts)  →  CMO editorial rewrite  →  HONESTY-GATE  →  DRAFT
   (Q2-14, real track/refusal          (LLM, marketing copy)     (deterministic)     ↓
    numbers, no fabrication)                                                    owner approves
                                                                                     ↓
                                                                                  PUBLISH (/blog)
```

## Layers

1. **Raw journal** (built — `scripts/generate_research_changelog.py`): the FACTS, real numbers.
2. **CMO editorial rewrite** (NEW): turns facts → engaging copy. May use an LLM — **allowed**: this
   is MARKETING content, NOT risk/execution/monitoring/kill (where LLM is FORBIDDEN). The LLM only
   REWORDS the provided facts; it is never given latitude to invent numbers or make claims.
3. **HONESTY-GATE** (NEW — the critical safety, deterministic/stdlib/fail-CLOSED, NO LLM): before a
   draft is allowed, it MUST pass:
   - **Numbers match** — every number in the copy appears in the source facts; no new/changed figure.
   - **Disclaimers present** — paper · not-a-guarantee · tail-shown · evidence-tagged all still there.
   - **No promissory language** — blocklist ("guaranteed", "will earn", "risk-free", "guaranteed
     returns", "гарантирован", "заработаете", …) → reject.
   - **No live/offer framing** — never presents paper as live or as a solicitation.
   - Fail → the draft is REJECTED (fall back to the dry version, or hold). A honesty-first product
     cannot let a "make it sell" rewrite overstate — that is legal risk + kills the differentiator.
4. **Draft store + approval** (flow B): passing drafts land in a reviewable store (`data/cmo_drafts/`,
   status `draft`), surfaced for the owner. **NOW:** simple review surface (e.g., `/admin` list, or a
   Telegram ping with the draft). **LATER (owner ask):** a **Kanban board** (columns: draft → approved
   → published) on `/admin` where the owner reads + drags to approve. On approval → publish to `/blog`
   + it becomes the site's fresh heartbeat.

## Constraints (hard)
- LLM allowed ONLY in the editorial-rewrite step (marketing). The honesty-gate + publish pipeline are
  deterministic + stdlib + fail-CLOSED. No LLM anywhere near risk/exec/monitoring/kill.
- **No fabricated numbers / APY** (evidence L0-L6). Tail always shown. Never present paper as live.
- **Publish ONLY after owner approval** (flow B). No auto-publish of selling copy.
- Non-custodial, RiskPolicy untouched, no secrets in files.

## Build order
1. **Honesty-gate** (deterministic) — build + test FIRST (it's the safety; reusable even for the dry version).
2. **CMO editorial rewrite** step (LLM behind the gate).
3. **Draft store** (`data/cmo_drafts/`, status field) + a minimal review surface.
4. **Kanban approval board** on `/admin` (owner's ask) — LATER.
5. Publish-on-approval → `/blog`.

## Open (owner)
- Which LLM/provider for the rewrite (needs a key — owner infra). Until then, build the gate + store +
  a template-based "richer than dry" rewrite (deterministic, no LLM) so the pipeline works end-to-end
  and the LLM rewrite drops in later.
