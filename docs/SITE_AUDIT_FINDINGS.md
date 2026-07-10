# SPA Astro Landing Site — Audit Findings

**Scope:** READ-ONLY audit of `landing/src/` (95-page Astro site → `landing/dist/`), covering four dimensions:
SPA-8 bilingual parity, SPA-9 performance, SPA-10 accessibility, SPA-12 OpenGraph/JSON-LD.
**Method:** source inspection + a scan of the built `dist/` HTML (the actual shipped output) + JS bundle sizing.
All file:line references verified against the real files. Admin pages (`/admin/*`) excluded per instructions.

---

## Executive summary

| Dimension | State | Verdict |
|---|---|---|
| **SPA-8 Bilingual parity** | Mostly healthy | The global chrome (header/footer/paper-strip/disclaimer) and all primary user-facing pages (index, packages, faq, methodology, trust, security, disclaimer, research, strategies) are **fully translated**. Total untranslated visible-text nodes across the whole site ≈ **133**, and the large majority sit on **operator-depth pages** (cockpit/*, verify, board/*, status, dashboard) that are not in the public nav and are mostly live/JS-rendered numbers. **Two real bugs**: `packages.astro` and `monitoring.astro` ship their own inline i18n scripts that (a) **default to Russian** and (b) use `textContent` instead of the global runtime's `innerHTML`. |
| **SPA-9 Performance** | Good, one soft spot | Images are a non-issue (only 2 `<img>` total, no oversized PNGs — `public/` is SVG + a correct 1200×630 3.3 KB `og-image.png`). Homepage correctly defers its island with `client:visible`. **One real cost:** `/dashboard` ships **~265 KB JS** (`DashboardLive` 133 KB + React runtime 132 KB) via `client:load`; `/annual-contrast` also uses `client:load` for a below-the-fold island. |
| **SPA-10 Accessibility** | Needs work (contrast) | Alt text, form labels (`aria-label` present), keyboard nav (full dropdown a11y in header), focus-visible ring, and `<html lang>` sync are all **done well**. **The systemic problem is contrast:** `text-white/30` (252×) and `text-white/40` (227×) on the near-black `#0A0C10` background fall **below WCAG AA 4.5:1** and are used on real caption/label/footnote copy. A couple of pages also have heading-order jumps. |
| **SPA-12 OpenGraph / JSON-LD** | Weakest dimension | OG tags, Twitter card, canonical, and per-page `title`/`description` are all correctly wired in `Layout.astro`. **But: zero of 95 pages set a page-specific `ogImage`** (all share one generic image), and **JSON-LD is a single generic `WebSite` type on all 92 pages** — no `Organization`, no `BreadcrumbList`, and no `FAQPage` despite `faq.astro` having perfect Q&A structure (a missed rich-result). |

**Bottom line:** The site is in solid shape. The highest-leverage work is (1) fixing the two RU-defaulting inline scripts, (2) a contrast pass on `text-white/30/40` small text, and (3) enriching structured data (FAQPage + Organization + a few page-specific OG images).

---

## SPA-8 — Bilingual parity (EN | RU)

The i18n mechanism (`Layout.astro` inlined runtime, lines 165–215): any `[data-ru]` element gets its EN cached in `data-en-orig`, and the toggle swaps `innerHTML` ↔ `data-ru`. Default is **EN** (`getLang()` returns `"en"`). Header/footer/paper-strip/disclaimer are fully tagged. Most "low count" pages store translations in JS arrays (faq, research, disclaimer, strategies/*) — they are actually well-translated; the raw `data-ru=` count understates coverage.

| Finding | File:line | Value | Effort | Fix |
|---|---|---|---|---|
| **`packages.astro` inline i18n defaults to RU** — `(localStorage.getItem('spa_lang') \|\| 'ru')` makes a first-time (English-default site) visitor see Russian. Also uses `textContent`, conflicting with the global `innerHTML` runtime. | `landing/src/pages/packages.astro:114-127` (esp. `:117`) | High | S | Delete the page's own `<script>`; rely on the global Layout runtime (all copy already carries `data-ru`). If kept, change `\|\| 'ru'` → `\|\| 'en'` and `textContent` → `innerHTML`. |
| **`monitoring.astro` inline i18n defaults to RU** — same `\|\| 'ru'` pattern, same `textContent` conflict. | `landing/src/pages/monitoring.astro:34` | High | S | Same fix as packages: default to `'en'` or drop the local script in favor of the global runtime. |
| **React islands default to RU pre-hydration** — `getLang()` fallback returns `'ru'` when `<html lang>` isn't `'en'`; `useState('ru')`. Brief RU flash / RU-first if lang not yet applied. | `WalletCheck.jsx:18,44`; `RtmrMonitor.jsx:26` | Med | S | Make the fallback `'en'` to match the site default, or read `localStorage.spa_lang` first (already partly done) and default EN. |
| **Operator-depth pages carry the bulk of untranslated visible text** (not in public nav, mostly live JS numbers, but indexable): cockpit-kit (43 nodes), cockpit/risk (18), verify (12), cockpit/backtest (10), cockpit (9), status (9). | `dist/cockpit-kit/`, `dist/cockpit/*`, `dist/verify/`, `dist/status/` | Med | M | Tag the static labels/eyebrows with `data-ru` (the numbers themselves need no translation). Lower priority than public pages. |
| **`dashboard.astro` has ~7 untranslated static labels** (e.g. "Evidenced track days", "Deterministic checks (ADR-002)…"). Public and in-footer-reachable. | `dist/dashboard/index.html` (rendered by `dashboard.astro`) | Med | S | Add `data-ru` to the static section labels/captions. |
| **`annual-contrast.astro` intro strings untranslated** ("A year, dated · advisory · paper-only", "What chasing 15% actually costs…"). | `dist/annual-contrast/index.html` | Med | S | Add `data-ru` to the static intro (island is separate). |
| Minor: badge/eyebrow labels like `ADVISORY · READ-ONLY`, `TIER T2`, `NOT LIVE-ALLOCATED` untranslated on strategies pages. | `strategies/btc.astro:71-73` (ui `Badge`) | Low | S | Add `ru=` prop / `data-ru` to Badge labels if desired (borderline — these read as codes). |

**Quantification:** ~133 untranslated visible-text nodes site-wide; ~90 of them are on 6 operator/cockpit pages. Public primary pages are effectively 100% translated. **Worst offenders:** `cockpit-kit.astro` (43), `cockpit/risk.astro` (18), `verify.astro` (12). The two RU-default script bugs are the only issues that actively **break** the intended EN-first experience.

---

## SPA-9 — Performance

Images and static weight are genuinely fine — this section is short by design.

| Finding | File:line | Value | Effort | Fix |
|---|---|---|---|---|
| **`/dashboard` ships ~265 KB JS eagerly** — `DashboardLive.P5hlPmN-.js` (133 KB) + React `client.DrE9CFQR.js` (132 KB), mounted `client:load`. It is the primary live surface, so it must hydrate — but `client:load` blocks earlier than needed. | `landing/src/pages/dashboard.astro:75`; bundles `dist/_assets/DashboardLive.*.js`, `dist/_assets/client.*.js` | Med | S | Consider `client:idle` (still mounts, just after main thread is free) since first paint is the static header/stats, not the island. RtmrMonitor is already `client:visible` (good). |
| **`/annual-contrast` island uses `client:load` for a below-the-fold widget** — the static intro + comparison render first; the polling island can defer. | `landing/src/pages/annual-contrast.astro:90` | Med | S | Switch `client:load` → `client:visible` (or `client:idle`). |
| Positive: homepage `WalletCheck` is `client:visible` (`index.astro:54`) and `LiveStats` is `client:visible` — LCP not JS-blocked. No action. | `index.astro:54`, `components/LiveStats.astro:3` | — | — | Keep as-is. |
| Positive: **no oversized images.** `public/` = `favicon.svg`, `og-image.png` (3.3 KB, correct 1200×630), and text assets. Only 2 `<img>` in the entire site (favicon in header). | `landing/public/` | — | — | None. |
| Minor: heaviest static HTML is `cockpit-kit/index.html` (149 KB) — a component-kit reference page (operator). Content, not a perf bug, but large for a single doc. | `dist/cockpit-kit/index.html` | Low | M | Optional: split or lazy sections if it ever goes public. |
| Minor: render-blocking Google Fonts `<link rel="stylesheet">` (Inter + JetBrains Mono) in `<head>`. `display=swap` is set (good), `preconnect` present (good). | `Layout.astro:71-76` | Low | S | Acceptable as-is; could self-host or `preload` the CSS to shave a round-trip. |

**Summary:** No image or bundle-bloat crisis. The only concrete win is deferring the two `client:load` islands (`dashboard`, `annual-contrast`).

---

## SPA-10 — Accessibility

Strong foundations: global `:focus-visible` ring (`Layout.astro:120-122`), `prefers-reduced-motion` handling (`:124-126`), full keyboard dropdown nav in the header (`SiteHeader.astro:215-242`), `<html lang>` kept in sync on toggle and observed by React islands, decorative images correctly `alt=""`/`aria-hidden`, and the one text input has an `aria-label` (`WalletCheck.jsx:78`). The real issue is **contrast**.

| Finding | File:line | Value | Effort | Fix |
|---|---|---|---|---|
| **Low-contrast small text is systemic** — `text-white/30` used **252×** and `text-white/40` **227×** on `#0A0C10`. `white/30` ≈ 2.3:1 and `white/40` ≈ 3.2:1, both **below WCAG AA 4.5:1** for normal text; used on real captions/labels/footnotes. | e.g. `track-record.astro:63,83,87,88`; `faq.astro:152,174,201`; pervasive across `pages/*` | High | M | Raise small body/label text to at least `text-white/55`–`/60` (the design system already bumped `--text-faint` to `#565E6D` for AA — extend that discipline to the raw `text-white/30–40` utilities, or map them to `--text-muted`/`--text-secondary`). |
| **Heading-order jump on `/track-record`** — `h1 → h2 → h5` (skips h3/h4), which AT users rely on for structure. | `dist/track-record/index.html` (from `track-record.astro`) | Med | S | Reassign the `h5`-styled labels to the correct level (h3) or make them non-heading `<p>` with utility classes. |
| **React island language fallback defaults to RU** (also a11y-adjacent: `<html lang>` may momentarily disagree with rendered text). | `WalletCheck.jsx:18,44`; `RtmrMonitor.jsx:26` | Low | S | Default fallback to `'en'` to match `<html lang="en">` initial state. |
| Positive: form inputs — the public text input has `aria-label`; DfB/academy inputs are operator/interactive widgets. No unlabeled public form fields found. | `WalletCheck.jsx:72-81` | — | — | Optional: add a visually-hidden `<label>` for belt-and-suspenders. |
| Positive: no `<img>` missing `alt` (2/2 have it); buttons carry text or `aria-label` (hamburger `SiteHeader.astro:109`, lang toggle `:105-108`). | `SiteHeader.astro` | — | — | None. |

**Summary:** One systemic, high-value fix (contrast on `text-white/30–40` small text). Everything else in a11y is already handled well.

---

## SPA-12 — OpenGraph / JSON-LD / structured data

`Layout.astro` (lines 26–79) sets OG (`og:type/url/title/description/image/site_name`), Twitter `summary_large_image`, canonical (auto-derived from `Astro.url.pathname` when not passed), and a JSON-LD block. Per-page `title` + `description` are supplied on all 32 top-level pages (0 missing). The gaps are in **image specificity** and **schema richness**.

| Finding | File:line | Value | Effort | Fix |
|---|---|---|---|---|
| **All 95 pages share one generic OG image** — no page sets the `ogImage` prop (0 hits repo-wide); every share card is the default `/og-image.png`. High-value pages (`/packages`, `/track-record`, `/rates-desk`, `/fundability`) deserve their own. | `Layout.astro:9,24,61` (default); no page overrides | Med | M | Author 3–5 page-specific OG images and pass `ogImage="/og/<page>.png"` on the flagship pages. Low effort per page once images exist. |
| **JSON-LD is a single generic `WebSite` type on all 92 pages** — no `Organization`, no `BreadcrumbList`, no per-type schema. `@type` never varies (only `description` does). | `Layout.astro:26-32,79` | Med | M | Add an `Organization` node (name, url, logo) to the site-wide graph; optionally emit `BreadcrumbList` on nested pages (`/strategies/*`, `/academy/*`, `/cockpit/*`). |
| **`/faq` has perfect Q&A structure but emits no `FAQPage` schema** — a free Google rich-result is left on the table. | `faq.astro:4-105` (the `faqs` array) + `Layout.astro:79` | High | S | Emit `@type: FAQPage` with `mainEntity` (Question/acceptedAnswer) built from the existing `faqs` array — data is already structured, just not marked up. |
| **Blog posts get no `BlogPosting`/`Article` schema** — `/blog/*` and field notes are plain WebSite. | `research.astro:6-16`, `dist/blog/*` | Low | M | Add `Article`/`BlogPosting` JSON-LD to blog post pages (headline, datePublished, author). |
| Positive: canonical URLs are correct — set explicitly on most content pages, auto-derived elsewhere; no duplicate/incorrect canonicals found. `og-image.png` is the correct 1200×630. | `Layout.astro:22-24,51`; `public/og-image.png` | — | — | None. |

**Summary:** The plumbing is right; the content is generic. Best ROI: `FAQPage` schema (data already exists), then `Organization` node, then a handful of page-specific OG images.

---

## Top quick-wins (highest value-to-effort, do first)

1. **[SPA-8, High/S]** Fix the two RU-defaulting inline i18n scripts — `packages.astro:117` and `monitoring.astro:34` (`|| 'ru'` → `|| 'en'`, and prefer deleting the local script so the global `innerHTML` runtime handles it). This is an active bug that shows Russian to English-first visitors.
2. **[SPA-12, High/S]** Add `FAQPage` JSON-LD to `faq.astro` from the existing `faqs` array — near-zero data work, unlocks a Google rich result.
3. **[SPA-10, High/M]** Contrast pass: promote `text-white/30` and `text-white/40` small copy (479 combined uses) to `≥ text-white/55` or map them onto the AA-safe `--text-muted`/`--text-secondary` tokens.
4. **[SPA-9, Med/S]** Defer the two eager islands: `dashboard.astro:75` and `annual-contrast.astro:90` → `client:idle` / `client:visible` (saves ~265 KB from blocking on the dashboard).
5. **[SPA-12, Med/M]** Add an `Organization` node to the site-wide JSON-LD graph in `Layout.astro`, and page-specific `ogImage` on the 4–5 flagship pages.
6. **[SPA-8, Med/S]** Tag the static labels on `dashboard.astro` and `annual-contrast.astro`, then the operator cockpit pages, with `data-ru`.
7. **[SPA-10, Med/S]** Fix the `h1→h2→h5` heading jump on `track-record.astro`.

*Written by a read-only audit pass. No source files were modified.*
