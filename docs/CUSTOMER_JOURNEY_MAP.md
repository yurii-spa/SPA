# Customer Journey Map — earn-defi.com + DeFi Checkup

> Owner-requested (2026-07-12). The thought-through map of how a real user moves from "never heard of us"
> to "talking to us" — across the TWO products, with the current gaps and the fix list. This is the
> source-of-truth for navigation + funnel work. Edit this first, then make the site match it.

---

## 0. The two products (users confuse them — the map must not)

| Product | URL | One-line | What the user does |
|---|---|---|---|
| **Yield desk** (SPA) | `earn-defi.com` + **`/dashboard`** | "A stablecoin yield desk that proves every number" | Sees what the desk earns, the track, the refusals, the honest capacity |
| **DeFi Checkup** | `checkup.earn-defi.com` + **`/sample-report`** / **`/check`** | "Your wallet's risk, at exit prices — no wallet connection" | Analyses THEIR (or any) wallet → sees risk → is routed to the desk |

**They are ONE funnel:** Checkup is the free top-of-funnel hook → the desk is the product. The site must
make that flow obvious. Today it does not (see §3 gaps).

---

## 1. Personas (who arrives)

- **P1 — Non-technical USDT/USDC holder** (owner's #1 target). Holds stables on a CEX or a wallet, earns ~0%.
  Not a DeFi native. Wants: "is there a safe way to earn more, and can I trust you?" May have NO on-chain
  wallet to scan → for them the Checkup is a *demonstration*, and the real CTA is the yield packages + a human.
- **P2 — DeFi user with a wallet** — has on-chain positions, worried about risk. Wants: "check my wallet, show
  me what's exposed." The Checkup is directly useful → then upsell the desk.
- **P3 — Allocator / fund** — evaluating the desk for capital. Wants: proof (track, refusals, fundability,
  verifier), not a rate. Lands on /fundability, /refusals, /track-record, /verify.

---

## 2. The intended journey (what SHOULD happen)

```
                      ┌─────────────── earn-defi.com (home) ───────────────┐
   ad / referral →    │  HERO: lead with the ASPIRATION (up to ~20% target,│
   search / social    │  paper, tail shown) + the PROOF floor (~3.3% real). │
                      │  Two clear doors:  [ Check my wallet ]  [ Dashboard ]│
                      └───────┬───────────────────────────┬─────────────────┘
                              │                           │
            P1/P2: "check"    ▼                           ▼   P1/P3: "show me it works"
              checkup.earn-defi.com/check          earn-defi.com/dashboard
                   (public addr, no connect)        (live paper track, APY, positions)
                              │                           │
                              ▼                           ▼
                 REPORT → risk + idle-yield gap      Track / Refusals / Fundability
                 "your $X idle at 0% could earn…"    (proof: $49k avoided, capacity curve)
                              │                           │
                              └──────────┬────────────────┘
                                         ▼
                              earn-defi.com/packages   (the 3 honest tiers)
                                         ▼
                              earn-defi.com/pilot      (talk to a human — the terminal)
```

**Guiding rule (owner directive):** the site must SELL — lead with the maximum aspiration (up-to-20%
target), with the honesty floor intact (labelled target/paper, tail always shown, never presented as
realized). The ~3.3% realized is the PROOF that the machine is real, not the headline.

---

## 3. CURRENT STATE vs INTENDED — the gaps (this is the fix backlog)

| # | Gap (what's broken in the journey today) | Where | Fix | Status |
|---|---|---|---|---|
| **J1** | **No `/dashboard` link in the top nav** — the yield dashboard is only in the FOOTER. A user can't find "show me the desk working". | `SiteHeader.astro` header-right | Add a persistent **Dashboard ↗** link/CTA in the header. | ✅ **LIVE** (commit 5bd4fd1d) |
| **J2** | **"Checkup" nav item → `/#analyze`** (a homepage anchor), NOT the full Checkup product. Confusing: the flagship free tool is hidden behind a scroll-anchor. | `SiteHeader.astro` groups[checkup] | Point "Checkup" at the real product entry (homepage widget is fine as the *inline* start, but also expose **Sample report** + **Check a wallet** so a user can SEE an example without scanning). | ⏳ TODO |
| **J3** | **Homepage leads with 3.3% (conservative)**, owner wants the **maximum** aspiration to lead. | `index.astro` hero + comparison | Hero now LEADS with "Target up to ~20%/yr" (paper, tail shown) on the proven ~3.3% floor. | ✅ **LIVE** (5bd4fd1d) |
| **J4** | **Checkup site header still reads "foreign"** — colours/fonts were aligned (indigo + Inter, commit 03e4913) but the header STRUCTURE differs from earn-defi's grouped nav, so it still feels like a different site. | checkup `(site)/layout.tsx` | Header now ties to earn-defi.com + a **Yield desk ↗** link back to the desk. | ✅ **LIVE** (Railway 1b07026); further brand-shape polish optional |
| **J5** | **No easy "see an example" path** — a first-timer with no wallet can't preview the analysis without knowing the `/sample-report` URL. | home + checkup nav | Put a **"See a sample analysis →"** link next to every "Check my wallet" CTA, pointing at `checkup.earn-defi.com/sample-report`. | ⏳ TODO |
| **J6** | **Checkup → desk connection is only in the footer + report CTA** — the top of the checkup doesn't say "this is the free tool of the earn-defi yield desk". | checkup layout | Header 'part of earn-defi.com — the yield desk ↗' (linked). | ✅ **LIVE** (Railway 1b07026) |

---

## 4. ✅ RESOLVED (2026-07-12) — CF Pages deploy blocker (owner unblocked; all landing fixes now LIVE)

_History (kept for the runbook):_ CF Pages had stopped deploying after `88a081bc`; the owner unblocked it via the Cloudflare dashboard and the full backlog (J1, J3, moat surfaces) deployed. Original diagnosis below.

### ⚠️ BLOCKER (historical) — CF Pages not deploying

**The single most important operational fact:** landing changes I push to `origin/main` are **NOT appearing
on earn-defi.com**. The last deployed commit is `88a081bc`; everything after it (the moat surfaces, and any
J1–J6 nav fix) is on origin but **Cloudflare Pages has not built/deployed it** (see `Q-OWN-18`). Diagnosed:
not a CDN cache, not the freshness guard (`|| true`), commits confirmed on origin HEAD — the stall is
**on Cloudflare's side** (likely a build-quota cap after many pushes, or a stalled/failed CF build),
invisible from this machine.

**→ Until the owner unblocks CF (Cloudflare Pages dashboard → earn-defi → Deployments → Retry / check
quota), NONE of the J1–J6 landing fixes will show on the live site, no matter how many I push.** The
Checkup fixes (J4/J6) deploy via **Railway** (separate, NOT blocked) and CAN go live.

---

## 5. Immediate answer — how a user reaches each thing TODAY (direct URLs)

- **Yield dashboard:** `https://earn-defi.com/dashboard`
- **Sample wallet analysis (no scan):** `https://checkup.earn-defi.com/sample-report`
- **Check a real wallet (public address only):** `https://checkup.earn-defi.com/check`
- **The 3 packages:** `https://earn-defi.com/packages`
- **Talk to a human:** `https://earn-defi.com/pilot`

(These work directly; the journey work J1–J6 is about making them *discoverable from the nav*, not just via URL.)

---

## 6. Sequencing

1. **Now (Railway, not CF-blocked):** J4 + J6 — checkup header coherence + desk-tie.
2. **Ready-on-origin, deploys when CF unblocks:** J1 (Dashboard in nav), J2 (Checkup entry), J3 (hero max-first), J5 (sample link).
3. **Owner:** unblock CF (Q-OWN-18); sign off the hero max-first framing (J3 touches the public headline number framing — owner-gated on *how aggressive* the aspiration reads, though all numbers stay honest/tail-shown).

*Owner-gated in here: the exact hero framing (J3) and any public tier-name/number change — flagged, not invented.*
