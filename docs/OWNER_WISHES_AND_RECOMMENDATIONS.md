# OWNER WISHES × AI RECOMMENDATIONS — for external audit

> **Purpose:** a clean, reviewable summary of (1) what the owner asked for, in his own words, and
> (2) the AI's recommended backlog + reasoning. Hand this to an external analyst for a sanity check.
> Full technical plan: `docs/PRODUCT_REDESIGN_ROADMAP_H2_2026.md` (v2). Live decision log:
> `docs/OWNER_DECISIONS_NEEDED.md`. Date: 2026-07-12.
>
> **Context for the auditor:** SPA (earn-defi.com) is an honest, **paper-stage**, **non-custodial**
> DeFi stablecoin-yield desk (~3.3% realized in paper trading, research-stage, **not yet taking
> external capital** — legal review pending). DeFi Checkup (checkup.earn-defi.com) is a free
> wallet-risk report tool. The redesign must be Tier-1 but cannot cross honesty/legal lines.

---

## PART 1 — What the owner asked for (his words → clarified)

| # | Owner said (paraphrased from chat) | Clarified intent |
|---|---|---|
| W1 | "Всё узким полотном на длинную страницу — пересобери вёрстку как DeBank" | Kill the narrow single-column long-scroll; rebuild app surfaces as a modern **dashboard-shell** (DeBank/Zapper/Zerion class). |
| W2 | "Checkup должен быть продающим слоем наших стратегий по доходности" | Make Checkup the **conversion layer** for the yield product. |
| W3 | "Человек без кошелька, просто с USDT, должен захотеть с нами связаться" | Build a path that converts **non-technical USDT holders with no wallet to scan** → contact. |
| W4 | "Перенести board в Checkup" | Migrate the DFB risk-screener (`/board`) into Checkup (its natural home). **Later, legal-gated.** |
| W5 | "Отдельная страница для Checkup без проверки, по типу дашборда" | A **no-scan Checkup demo** page (dashboard-style) so people see the product before committing. |
| W6 | "Возможно дашборд — это вход в Checkup" | Use the **public dashboard as the entrance/showroom** to Checkup. |
| W7 | "Убрать всё лишнее с сайта в админку" | **Consolidate operator cruft** (cockpit/board) off the public site into `/admin`. |
| W8 | "Запусти исследования по каждому вопросу, большой годовой бэклог, документация, самопроверка" | Research → phased 6–12mo backlog → docs → **adversarial self-audit** (this package). |
| W9 | (later) "Managed funds / recommendations — отдельный слой, юр.вопросы, потом" | The true selling/advisory layer is **owner + legal-gated, deferred**. |

---

## PART 2 — What was done to answer W8

- **3 parallel research agents** (2026-07-12): modern DeFi-dashboard UX teardown (DeBank/Zapper/
  Zerion/DeFiLlama/De.Fi) · Checkup-as-conversion-layer strategy · code-level audit of the current
  site.
- **Code-verified the core complaint:** 36 pages, **34/36 narrow `max-w-3xl…5xl` columns**, no
  dashboard-shell anywhere, no shared component kit, two drifting CSS systems. **W1 is objectively
  true, not a matter of taste.**
- **Synthesized** into a phased roadmap, then ran a **hostile Tier-1 self-review** which graded the
  first draft **B−** and found 4 real holes (below). v2 fixes them.

---

## PART 3 — AI recommendations (executive level)

### R1 — The layout fix is a *structural mode-switch*, not "make it prettier"
Marketing pages **stay single-column** (correct for long-form). Only **app surfaces**
(`/dashboard`, `/monitoring`, `/aggressive-lab`, `/packages`, `/admin`, Checkup report) move to
**sidebar + sticky topbar + 12-col grid + KPI strip + sortable sticky tables + detail drawers**.
*Why:* that's the shared DNA of every Tier-1 DeFi app; it makes dense financial data scannable
instead of a scroll.

### R2 — The owner's "dashboard = entrance to Checkup" (W6) is the strategic keystone
The self-review's biggest hole was **"the conversion funnel has no top" (no traffic source).** W6
solves it: the **public dashboard = the showroom** (our honest live track), whose hook is *"check
YOUR portfolio the same honest way → Checkup."* This turns our transparency into the top-of-funnel.
**Recommendation: adopt W6 as the spine of the whole journey** (dashboard → Checkup [scan / no-wallet
snapshot / no-scan demo] → honest bridge → one `/pilot` contact → human handoff).

### R3 — Reframe "selling layer" → "credibility/relationship layer" (the honesty↔legal fix)
**You cannot legally "sell" yield yet, so Checkup cannot be a literal selling layer today.** The
honest, legal version: the conversion event is *"this person trusts our honest risk measurement and
wants to stay in contact,"* not "deposit." Volume then comes from **content/SEO distribution**, not a
pushier CTA. *Auditor: please pressure-test this reframe — it is the load-bearing assumption.*

### R4 — Build order matters more than feature list
1. **Instrument first** (capture the current funnel numbers) — else "Tier-1 converted better" is
   unprovable. 2. **Prove the shell on ONE live page** (`/dashboard`) before extracting a shared kit.
3. **Ship the no-wallet snapshot + no-scan demo + dashboard-entrance early** — that's the actual
   product for the W3 audience. 4. **Board/dashboard→Checkup migration + true selling layer LAST**
   (owner/legal-gated).

### R5 — Honest scope: the "quick" phase is ~6–8 weeks, not 2–4
Rebuilding the live, polling `/dashboard` island + unifying tokens across two repos is L-effort. A
Tier-1 result needs added tracks the first draft skipped: **SEO/acquisition, measurement,
performance, accessibility, post-lead ops, legal review, QA/visual-regression.**

### R6 — W4/W5/W7 verdicts
- **W5 (no-scan demo):** ✅ high-value, do early (Phase 1). Doubles as the sample-report upgrade.
- **W7 (cruft → /admin):** ✅ do the safe part (remove `/cockpit` from public sitemap + footer,
  redirect old URLs) — low risk, cleans the journey. `/board` waits for W4.
- **W4 (board → Checkup):** ✅ right destination, but a **weeks-long cross-repo migration**
  (Astro → Next.js) + **legal-gated** → deferred to Phase 3, done as its own careful project.
- **W6/W2 true selling layer:** deferred until legal clears managed/advisory (W9).

---

## PART 4 — Already shipped (2026-07-12, before this roadmap)
Honest numbering unified ("up to X%"), homepage leads with the real working tier, aggressive-page
liquidation-risk contradiction fixed, **/pilot contact form → owner Telegram + admin count**, FAQ
rewritten to honest paper-stage, "SPA" de-expanded to a proper name, **honest per-sleeve verdicts
published on /fundability (incl. flagship below the floor)**. So the **conversion terminal (/pilot)
and honesty posture already exist**; the roadmap builds the funnel that feeds them.

---

## PART 5 — Open questions the auditor should probe
1. **Is R3 (credibility not selling) legally sufficient**, or does even a `/pilot` "contact us" +
   holdings-band capture already constitute pre-solicitation of an unregistered fund? *(There is a
   live `WaitlistForm` on Checkup flagged as the most exposed artifact — needs legal review NOW.)*
2. **Will W3 (no-wallet USDT holder) actually convert**, or is it a thin audience with no trust
   reason to contact a not-yet-live desk? What's the realistic top-of-funnel volume?
3. **Is the 6–8 week Phase-0 estimate realistic** for a solo/AI-assisted build, or still optimistic?
4. **Is "dashboard = entrance" (W6) the right bet**, or does mixing our-track-record (SPA) with
   your-wallet-risk (Checkup) confuse two different value props?
5. **Measurement:** are the proposed numeric DoD gates the right ones, and is the existing analytics
   beacon enough to capture them?

---

*Prepared for external audit. AI (Claude) authored the recommendations from 3 research agents + a
hostile self-review. Nothing here is legal/financial advice; the managed-capital and solicitation
questions are explicitly owner + legal territory.*
