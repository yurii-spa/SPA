# ADR-047: Site Privacy Hardening (earn-defi.com)

## Status

Accepted (2026-06-21)

## Context

The public site (earn-defi.com — `landing/`, plus `index.html`,
`investor_portal.html`, `family_fund_landing.html`) carried language and UI that
overstated the project's status and invited capital:

- Marketing framed SPA as **"built for family offices"** — soliciting language
  that implies an open, operating fund.
- The site exposed **active withdrawal / entry forms** (e.g.
  `emergency-withdrawal`), presenting a live mechanism of entry/exit.

SPA is in **paper validation** — virtual $100k, real track started 2026-06-10,
go-live not before ~2026-08-01, GoLiveChecker not yet READY. Publicly presenting
it as an operating fund that accepts capital is both inaccurate and a regulatory/
liability exposure. The correct posture is a **private, non-soliciting research
project**, not a discoverable, investable product.

## Decision

Full reframe of the site to **"personal research project, paper validation"**:

1. **Reframe copy.** Remove "built for family offices" and any
   fund-solicitation language. Present SPA as a personal research / paper-trading
   validation project with explicit disclaimers (no offer, no solicitation, not
   investment advice, paper/virtual capital).
2. **Remove the mechanism of entry.** Strip active withdrawal/entry forms;
   convert `emergency-withdrawal` and related flows from interactive money-moving
   forms to informational/disabled content. No page should present a live way to
   deposit or withdraw.
3. **`noindex` all pages.** Apply `noindex` (meta robots + headers) across the
   site and tighten `robots.txt` so the site is not indexed or surfaced by search
   engines — privacy by default for a project that is not seeking the public.

Affected surfaces include `landing/` (Astro pages: index, fees, methodology,
risk-disclosure, due-diligence, emergency-withdrawal; components: Hero,
TrustSignals, Disclaimer, Footer, CompetitorTable, HowItWorks; `Layout.astro`),
`landing/public/_headers`, `landing/public/robots.txt`,
`landing/public/sitemap.xml`, and the standalone `index.html`,
`investor_portal.html`, `family_fund_landing.html`.

## Consequences

- **Positive:** Site accurately reflects reality (paper validation, not an open
  fund); removes solicitation language and the appearance of accepting capital.
- **Positive:** `noindex` + tightened robots keeps the project out of search
  results — appropriate for a private research effort pre-go-live.
- **Positive:** Removing live withdrawal/entry forms eliminates a class of
  liability (someone acting on a form that should not exist yet).
- **Negative:** Loses public/marketing reach and SEO; intentional given the
  pre-go-live posture. Reversible by removing `noindex` after go-live + legal
  review.
- **Neutral:** Family-fund onboarding for *actual* participants moves entirely to
  the gated investor cabinet / Family Fund API and legal docs (`docs/legal/`),
  not the public site.

### Security / secrets note

This change set must **not** include `scripts/cf_install_token.command` in any
push — it relates to Cloudflare token install and is excluded from all commits
per the secrets policy (never push tokens/credential-bearing scripts).

## References

- [ADR-011](./ADR-011-go-live-security-checklist.md): Go-live security checklist
- [ADR-002](./ADR-002-golive-transfer-rule.md): Go-live transfer rule (pre-go-live posture)
- `landing/public/_headers`, `landing/public/robots.txt`, `landing/public/sitemap.xml`
- `docs/legal/` (investor onboarding — gated, not public)
- PAT-leak incident & secrets policy (CLAUDE.md § SECRETS POLICY)
