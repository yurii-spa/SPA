# EXECUTION PROTOCOL — how to work this package so NOTHING is missed

> For the executing Claude Code session. This is the operating manual over specs 00–04 +
> `STATUS.md`. It exists because multi-week backlogs die from silent drops, not from hard bugs.

## 0. The one invariant

**`docs/redesign/STATUS.md` is the single completion ledger.** Every task in every spec has a
row there. If you do work that has no row — add the row first. If a row says DONE, its spec's
acceptance criteria were EACH verified against the LIVE deploy (curl real content / screenshot
/ API response), never against "push succeeded" or HTTP 200. No exceptions — the 404-served-
as-200 and CF-prebuild-freeze incidents both happened because deploys were assumed, not read.

## 1. Per-task loop (run for EVERY task)

1. **Re-verify current state first.** The specs snapshot 2026-07-12; the site moves daily
   (half of Phase 0 was already live within hours of the spec landing). Before implementing:
   curl the live page / read the current source. If already shipped — do NOT redo; jump to
   step 4 and verify acceptance anyway (shipped ≠ correct: e.g. M4's evidenced-days cell was
   live but rendering "—").
2. **Claim files** (announce-log check per PROJECT_CONTROL/16 — no other session on them).
3. **Implement exactly to spec.** Copy EN+RU from the spec verbatim unless the live context
   demands adjustment — then keep the register and the vocabulary rules (realized/target/tail).
   Every interactive element gets `data-track`.
4. **Verify acceptance criteria one by one** — as a checklist, not a vibe. Build green
   (`cd landing && npm run build` / checkup: vitest + build). Push (SPA = API-push only).
   **After deploy: curl the LIVE page and confirm the actual content changed** (grep for your
   new string). For islands: content may be client-rendered — verify via the API the island
   reads + a browser check when possible, and state in STATUS which method you used.
5. **Update STATUS.md row** (status + date + how verified) and push it WITH the task.
6. **Announce** via `scripts/log_session_change.py`.

## 2. Anti-miss mechanisms (mandatory cadence)

- **Every working cycle:** re-read `docs/OWNER_DECISIONS_NEEDED.md` (execute filled ОТВЕТs) and
  `STATUS.md` top-to-bottom; pick the highest PENDING in spec order (01 §order → 03 → 04 → 02).
- **After finishing any spec section:** re-read that spec file end-to-end and diff against
  STATUS — every task ID present? Sub-bullets (RU parity! data-track! tests!) actually done?
  Sub-bullets are where drops happen.
- **Weekly sweep:** (a) grep all spec files for task IDs (`N[0-9]|M[0-9]+b?|U[0-9]|B[0-9]|A[12]|C[0-9]+|E[0-9]|F[0-9]|I1|CHK-DEMO`)
  and assert each has a STATUS row; (b) run the N1 numbers-grep across `landing/src` — number
  drift regresses silently as pages ship; (c) curl /, /packages/, /pilot/, checkup home and
  re-verify the LIVE-VERIFIED rows still hold (deploys can regress them); (d) check
  `/api/analytics` funnel counts are still flowing.
- **Known live discrepancies to clear FIRST** (found in the 2026-07-12 audit): evidenced-days
  shown three ways (/pilot "~19/30" vs SSOT track_days=21 vs homepage "—") — pick ONE source
  (SSOT `/api/ssot/facts` or golive gap-monitor — they measure different things; label
  whichever you show: "evidenced days" ≠ "track days") and wire all three surfaces to it;
  M4 hydration of the countdown cell; M7 backend source-field verification via pytest (do NOT
  test-POST to prod — every POST pings the owner's Telegram).

## 3. Judgment rules

- **Spec vs reality conflict:** reality wins; update the spec file in the same push (one-line
  edit + note), so specs never rot into fantasy.
- **Honesty floor is not negotiable, framing is:** never delete a fact; you may reorder,
  demote to expandable, reframe (M9b/M10 patterns). If a change would remove a fact — stop,
  make it a Q-OWN.
- **Anything owner-gated:** file Q-OWN, keep moving on non-gated work. Never idle on a gate.
- **Don't touch:** live paper track data/, RiskPolicy, execution/, launchd fleet, and the
  DashboardLive feed logic (Phase-1 shell wraps it, never rewrites it).
- **CF prebuild:** no new checks that can exit 1. CI lints live in GitHub Actions only.
- **Batch size:** small pushes (1 task or less), each independently verifiable. No mega-pushes.

## 4. Sequencing reminder

Phase 0 (finish remaining rows incl. M9b + N1 discrepancies + U2/U3/M8 + M6/M11 + N2 + F1
verify) → Phase 1 shell (03) → Phase 2 conversion (04) → Phase 3 IA (02; admin-auth
prerequisite) → Phase 4 gated. F2 targets doc after ~2 weeks of F1 data — set a reminder row.

## 5. Reporting to the owner

After each phase (and weekly): one short RU summary in the session — what shipped
(live-verified links), what's blocked on him (Q-OWN list), funnel numbers so far (views →
CTA clicks → early-access/pilot submits). He reads Russian; keep it outcome-first, no jargon.
