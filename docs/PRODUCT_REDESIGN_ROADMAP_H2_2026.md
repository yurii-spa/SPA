# PRODUCT & UX REDESIGN ROADMAP — H2 2026 → H1 2027 (v2)

> **Owner directive (2026-07-12):** stop shipping small fixes; make earn-defi.com + DeFi Checkup a
> **Tier-1 product**. (1) Move off "everything crammed into a narrow column on one long page" to a
> **modern dashboard-shell** (DeBank/Zapper/Zerion class). (2) Make **Checkup the conversion layer**
> for the yield strategies — a non-technical USDT holder with no wallet should still want to
> **contact us**. (3) **Use the public dashboard as the ENTRANCE to Checkup**; add a **Checkup
> "demo" dashboard page that needs no wallet scan**. (4) **Move all operator cruft off the public
> site into /admin.** Board → Checkup is a separate later project (legal-gated).
>
> **v2 = v1 + a hostile Tier-1 self-review** (graded v1 **B−**) that found: the conversion plan had
> no top-of-funnel and no post-lead handling; the timeline was ~2× under-scoped; the Definition of
> Done was unmeasurable; and "selling layer" contradicts "can't legally sell yet." v2 fixes all
> four. **The owner's "dashboard = entrance to Checkup" idea directly closes the missing
> top-of-funnel the review flagged.**

---

## 0. Verified finding

Owner's complaint is **100% accurate** (code-checked): 36 pages, **34/36 in a `max-w-3xl…5xl`
centered column**; `Layout.astro` is header→body→footer stack with **no shell**; `/dashboard`,
`/cockpit`, and the Checkup report are all **long-scroll, not glanceable**; no shared component kit
(inline styles; `SITE_DESIGN_SYSTEM.md` is SPEC-only; two drifting CSS systems).

**Fix = structural mode-switch, not "prettier":** marketing pages stay single-column (correct);
**app surfaces** (`/dashboard`, `/monitoring`, `/aggressive-lab`, `/packages`, `/admin`, Checkup
report) move to **sidebar + sticky topbar + 12-col grid + KPI strip + grouped sortable tables +
detail drawers** (near-black surfaces, one accent, P&L-only green/red, tabular-nums).

---

## 1. The customer journey (the spine everything hangs on)

The owner's product insight — **dashboard is the entrance to Checkup** — turns our own honest track
record into the top-of-funnel. Two doors, one destination:

```
            ┌── SEO / "is my USDT safe?" content (Workstream E) ──┐
            ▼                                                      ▼
  [ PUBLIC DASHBOARD ]  ← our live, honest track (~3.3% paper, verdicts, refusals)
       the showroom: "this is how we work — transparent, non-custodial"
            │  hook: "want to check YOUR portfolio the same way?"
            ▼
  ┌─────────────────── DeFi CHECKUP ───────────────────┐
  │  Door A (has wallet):   paste address → risk report │
  │  Door B (no wallet):    Stablecoin Safety Snapshot  │
  │  Demo view (no scan):   sample dashboard "what you'd get"  ← NEW (owner)
  └───────────────────────────┬────────────────────────┘
            │  bridge: "here's your risk → here's how an honest desk earns on stablecoins"
            ▼
  [ /pilot CONTACT ]  → owner Telegram + admin (built 2026-07-12)
            ▼
  [ post-lead handling ]  → qualify, human reaches out (Workstream I)
```

Key moves: **dashboard = showroom/entrance**; **Checkup = the mirror** ("check yourself the same
honest way"); **no-scan demo** lets the curious see the product before committing; everything funnels
to **one honest `/pilot`**. Operator tools (cockpit/board) leave the public path entirely (§ Workstream J).

---

## 2. Workstreams

| # | Workstream | Goal | Gated? |
|---|---|---|---|
| **A** | Design-system + component kit (incl. empty/error/loading states) | one shared language across both repos | No |
| **B** | Dashboard-shell redesign | app surfaces → modern shell | No |
| **C** | Checkup conversion/credibility layer | convert both doors → `/pilot` | copy/legal = flag |
| **D** | Board → Checkup migration | DFB risk-screener becomes a Checkup feature | **Yes (legal, LATER)** |
| **E** | **Acquisition / distribution / SEO** *(added v2)* | the actual top-of-funnel | No |
| **F** | **Measurement / instrumentation** *(added v2)* | know if any of this worked | No |
| **G** | **Performance / Core Web Vitals** *(added v2)* | the redesign must not get slower | No |
| **H** | **Accessibility as a track** *(added v2)* | keep the existing a11y investment, extend to new primitives | No |
| **I** | **Post-lead ops / CRM** *(added v2)* | what happens after `/pilot` | Partial (owner) |
| **J** | **Consolidation: cruft → /admin** *(added v2, owner)* | one clean public path | light owner call |

Honesty is a HARD constraint on C/D/I (see §6).

---

## 3. Phased plan

### Phase −1 — Baseline instrumentation (FIRST, ~3–5 days) · you can't prove Tier-1 without a before-number
- **F1** Wire the existing analytics beacon (`spaTrack` / `/api/analytics/event`) to capture the current funnel: door → report/snapshot view → CTA click → `/pilot` submit. Capture bounce/scroll-depth on the narrow-column pages we're about to replace. `[P0][S]`
- **F2** Define the numeric targets that replace "looks like DeBank": door→`/pilot` conversion %, snapshot completion %, LCP/CLS budget, WCAG-AA pass count, lead-quality definition. `[P0][S]`
- **LEGAL-0** Compliance review of the **already-live** `WaitlistForm` + "Aggressive up to 20%" table for solicitation risk, BEFORE scaling C. `[P0][S, owner-gated]`

### Phase 0 — Foundation (~6–8 wks, honestly) · prove the shell on ONE live surface
- **B1** Build `DashboardShell` (256/64px collapsible sidebar + sticky topbar + fluid `max-w-[1440px]` 12-col grid). `[P0][M]`
- **B2** Rebuild **`/dashboard`** on the shell — **hardcoded/inline first, NOT generalized** (it's a live React island polling 6 endpoints @15s with live/offline honesty states; re-shelling it safely is L, not a layout swap): KPI strip + hero equity chart w/ time-range toggle + DeBank-style protocol-grouped sortable positions table + right context rail (RTMR/funding/refusals). `[P0][L]`
- **Gate:** ship `/dashboard`, validate against the F2 baseline, THEN extract the kit. (Review correction: don't build 7 reusable components before the shell survives contact with the live island.)
- **A1** Extract the shared kit AFTER the gate: `StatCard / DataTable(sort/sticky/dense) / FilterChips / Drawer / Tabs / SectionHeader / Badge` **+ empty/error/loading/offline state kit** (the honesty differentiator, first-class not ad-hoc). Doc in `SITE_DESIGN_SYSTEM.md` (SPEC → built). `[P0][L]`
- **A2** Consolidate tokens (color/space/type/radius/shadow) into one source; sync Astro ↔ Checkup; kill the 5 near-black bg + 5 header treatments. (Cross-repo = L.) `[P0][L]`

### Phase 1 — Conversion layer + the entrance (Q3 2026) · highest business value
- **B-ENTRY** Wire **dashboard → Checkup** as the entrance: on `/dashboard`, a prominent honest hook "check YOUR portfolio the same way → Checkup." Make the dashboard the showroom. `[P0][S]` *(owner idea)*
- **C2** **Stablecoin Safety Snapshot** — the no-wallet micro-quiz (band / where / stables / goal) → ungated personalized result. **Pulled to Phase 1 week 1, standalone cheap HTML, NOT gated behind the kit** (review correction: this is the actual product for the stated audience). `[P0][M]`
- **CHK-DEMO** **Checkup demo page (no wallet scan)** — a dashboard-style "here's what your report looks like," modeled on `/dashboard`'s shell, for the curious to see value before committing. `[P0][M]` *(owner idea; doubles as the sample-report upgrade)*
- **C1** Persistent "No wallet to scan? →" door on Checkup home + result. `[P0][S]`
- **C3** First report NEVER gated by email/login (protect value-first aha). `[P0][S]`
- **C4** `/pilot` copy: "real person reaches out, no obligation, not an offer" + source + holdings-band fields (form + Telegram already built). `[P0][S]`
- **C10 / LEGAL** Reusable "not financial advice / not an offer / not accepting external capital yet" disclaimer on every conversion surface; enforce with an artifact-level checklist (would a regulator read this as solicitation?). `[P0][S]`
- **E1** No-wallet acquisition content: 3–5 SEO/answer-engine pages ("is USDT safe," "what is a depeg," "stablecoin risk checklist") feeding the snapshot — the missing top-of-funnel. `[P0][M]`
- **C5** Every report/snapshot ends on a "what to do about this" panel naming the un-fixable gap → bridges to the SPA approach (no promised returns). `[P1][M]`
- **C6** "How we think about stablecoin yield (honestly)" bridge page. `[P1][M]`
- **C7** Dual-CTA everywhere (self-serve result + "talk to a human"). `[P1][S]`
- **C8** Trust-signal band (non-custodial / honest-first / public track / "we show the bad news") on both doors. `[P1][S]`
- **E3** Shareable result artifact (share card) — the referral lift, actually built. `[P1][M]`
- **I1** Post-`/pilot` handling: response SLA + qualification flow + "what is a good lead" definition. `[P1][S, partial owner]`

### Phase 2 — Roll out the shell + rebuild the conversion surface (Q4 2026)
- **B6** **Rebuild Checkup report FIRST in this phase** (it's the conversion vehicle C5/C7/C8 attach to — don't wire conversion onto the old shell twice): tabbed panels (Overview/Approvals/Positions/Risk/History) + Wallet-Health-Score KPI strip + TanStack sortable tables + detail drawer; condense the 400px hero to ~120px. `[P1][L]`
- **B3** Convert `/monitoring`, `/aggressive-lab`, `/packages` onto the shell. `[P1][L]`
- **B4** Row-click slide-over detail drawer. `[P1][M]`
- **B5** Filter-chip + sortable sticky table for every long list (35 adapters, 60 strategies, tournament) + per-row sparklines. `[P1][M]`
- **B7** "Risk Health" scorecard as a first-class dashboard citizen. `[P1][S]`
- **B8** Sticky quick-access metric bar (NAV/APY/equity/kill-switch). `[P1][S]`
- **G1** Performance budget: LCP/CLS/bundle targets; audit the 6-island polling + dual-font cost the redesign will inflate. `[P1][S]`
- **H1** Accessibility track: keyboard/SR support for the NEW drawer + sortable-table primitives; WCAG-AA gate on DoD. `[P1][M]`
- **QA1** Visual-regression + cross-repo token-drift test (so the two CSS systems can't re-diverge). `[P1][S]`
- **F3** Funnel analytics dashboard: door (scan/snapshot/demo) → bridge → `/pilot`, segmented by holdings band (owner needs to know *who's big*). `[P1][M]`
- **B9/B10** Financial token pass + responsive shell (sidebar→icons→mobile bar; tables→accordion+FAB). `[P2][S/M]`

### Phase 3 — Selling layer + migrations (H1 2027, several owner/legal-gated)
- **J1** **Consolidate: move `/cockpit/*` + operator surfaces off the public site into `/admin`; drop from public sitemap; old URLs → 301/308, not 404.** One clean public path. `[P1][M]` *(owner idea; do the safe sitemap/footer part earlier if owner confirms)*
- **D1** **Board → Checkup migration**: port DFB (Astro → Next.js) + rewire data; position as Checkup "Risk Screener" (pick a safe pool *before* entry). **Owner + legal-gated, separate project.** `[gated][L]`
- **D2 / DASH→CHK** **Dashboard → Checkup**: fold the public showroom-dashboard concept into the Checkup product so the entrance and the mirror live in one place (owner: "maybe the dashboard IS the way into Checkup"). Product-design + migration. `[gated][L]` *(owner idea)*
- **C11** Checkup as the true **yield selling layer** (USDT holder → contact → owner decides offer) — once legal clears the managed/advisory layer. **Owner + legal-gated.** `[gated][L]`
- **B11** Composable widget-grid / saved-views for `/admin` + Checkup-pro. `[P2][L]`
- **C9** Nurture sequence (education-led, no return promises) — reuses email infra. `[P2][M, infra owner-gated]`
- **C13** EN|RU parity on the whole no-wallet path. `[P2][S]`

---

## 4. Definition of Done (Tier-1 bar — now measurable)
- App surfaces use the **shell** (not a narrow column); financial data = **sortable sticky tables, tabular-nums**.
- **One documented component kit + token set** shared across both repos; zero near-black/header drift (QA1 enforces).
- Journey works **end-to-end**: dashboard-showroom → Checkup (scan / snapshot / demo) → bridge → one honest `/pilot` → qualified handoff.
- **Numeric gates met** (F2): door→`/pilot` conversion % ≥ target, snapshot completion % ≥ target, LCP/CLS within budget, WCAG-AA pass, lead-quality defined and tracked.
- **Every number carries an evidence level + honesty framing**; nothing reads as a live offer or solicitation (LEGAL checklist passes).
- Responsive + a11y pass on the new primitives.

## 5. Honesty-vs-selling — RESOLVED (was the review's #4 hole)
**You cannot have a "selling layer" for a product that legally cannot sell yet. What you build now is
a CREDIBILITY & RELATIONSHIP layer.** The conversion event is not "deposit" — it's *"this person now
trusts that we measure risk honestly and wants to stay in contact."* That is legal and legitimate.
- Kill/legal-review any **waitlist framing that implies a queue for an offering** (the live
  `WaitlistForm` is the most exposed artifact) — reframe as "follow our research."
- The `/pilot` "a real person reaches out" is the honest maximum. Then the metric is **qualified
  relationships, not lead volume** — and volume comes from **distribution/content (E)**, not a
  punchier CTA.
- **Rule:** every conversion surface must survive *"would a regulator read this as solicitation of an
  unregistered fund?"* — enforced by the C10/LEGAL checklist, not just stated as a principle.

## 6. Honesty guardrails (HARD)
Non-custodial everywhere. Paper-stage, not taking external capital — stated plainly. Never present
~3.3% as live/offered/guaranteed (label realized-in-paper / research-stage + last-verified). Never
"invest / deposit / returns / APY you'll earn / join the fund / allocate." Only ask: "contact us /
walkthrough / follow progress." No fabricated risk/APY/depeg numbers. No false urgency.
Personalization educates on risk & approach, never a tailored allocation. Managed/advisory layer =
off-page, human, legally-gated, owner-initiated.

## 7. Sequencing logic (review-corrected)
**Instrument first (Phase −1)** — no redesign ships without a before-number. **Shell on ONE live
surface, inline, before extracting the kit** (don't pay the abstraction tax on speculation).
**No-wallet snapshot + demo + dashboard-entrance early in Phase 1** — that's the actual top-of-funnel
for the stated audience. **Rebuild the Checkup report before wiring conversion onto it** (don't build
twice). **Board/dashboard migration + true selling layer LAST** — owner/legal-gated; do not start
until the managed-capital legal questions are answered.

---

*v2 created 2026-07-12: v1 (3 research agents) + hostile Tier-1 self-review (graded B−, all 4 holes
fixed) + owner additions (dashboard=entrance, no-scan Checkup demo, cruft→/admin). Authoritative
product/UX backlog. Owner/legal-gated: D1, D2, C11, C9/F/I infra, LEGAL-0, J1 — flagged, not started
without sign-off.*
