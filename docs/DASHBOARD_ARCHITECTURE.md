# Dashboard Architecture — Reconnecting the "Separate World"

**Author:** Senior Architect · **Date:** 2026-06-26 · **Status:** AUDIT + DESIGN (owner reviews before rebuild)
**Companion:** the DESIGNER's UX doc (layout/visual). This doc is the **data-flow / architecture** half.
**Mandate:** make the dashboard a TRUE LIVE MIRROR of the real system. Honesty-first. No fabricated/stale
numbers. The track just reset to an honest **5/30** — the dashboard MUST show 5/30, never a padded number.

---

## 0. TL;DR (for the owner)

The dashboard is a "separate world" for **five concrete, quantified reasons**:

1. **It shows the WRONG track number.** It renders ~**17/30** (raw `days_running`) instead of the honest
   **5/30** (`real_track_days`). The honesty reset is invisible on the dashboard.
2. **Go-Live reads a dead key** → it shows **`—/29`** even when the API is live, because it reads
   `golive.criteria_met` / `total_criteria` but the file ships `passed` (27) / `total` (29).
3. **The committed static fallback is the OLD worldview** — frozen at **2026-06-20, $100,118.91, a 31-bar
   curve starting 2026-05-21** (the pre-honesty-teardown era). When the API/tunnel is down, the dashboard
   silently shows that stale, pre-reset picture as if it were current.
4. **None of the new surfaces exist on the dashboard.** Grep for `rates-desk | refusal | rwa-safety |
   rwa-nav | strategy-lab` across `index.html` + `app.html` = **0 hits** — even though all the data files
   AND the API endpoints exist and are live. The dashboard is frozen on an old worldview.
5. **There is no single source of truth.** A canonical SSOT endpoint (`/api/ssot/facts`) already returns the
   honest headline (track 5, go-live 27/29, equity, NAV, reconciliation flag) — but the dashboard hero does
   NOT consume it; it re-derives each number from a different file with a different key.

**The fix:** ONE canonical truth (`/api/ssot/facts`) drives the hero; honest "stale / N h" badges replace the
silent old-worldview fallback; the new surfaces (rates desk, RWA backstop, structural/refusal, honesty meta)
get rendered from their already-live endpoints. **One dashboard renders the API. No divergent hardcoded
worldview.**

---

## 1. Audit — why it's a "separate world" (quantified)

### 1.1 The three frontends (current reality)

| File | Served at | Role | Data source |
|---|---|---|---|
| `index.html` (13,285 LOC) | `yurii-spa.github.io` (GitHub Pages) | Ops/owner dashboard | live API + `./data/` static fallback |
| `landing/public/app.html` (13,284 LOC) | `earn-defi.com/app` (CF Pages) | "the /app" | **byte-for-byte copy of index.html** |
| `investor_portal.html` (465 LOC) | offline / `file://` | Investor snapshot report | one pre-generated `investor_portal_data.json` |

`index.html` and `app.html` are **the same file in two places** (audit confirmed: identical head, tabs, fetch
logic, API routing). They are kept in manual sync — a divergence hazard, not a design. `investor_portal.html`
is a genuinely separate, honest, well-behaved third worldview (24h-stale banner, all-`—` on missing data).

### 1.2 The data path (what's actually wired)

```
Mac mini :8765  ── uvicorn spa_core.api.server:app (FastAPI, READ-ONLY) ──┐
   routers: live / misc / v1 / tier1 / tournament / strategy_lab / rates_desk
        │                                                                  │
        ├─ /api/live/ping        (probe; dashboard polls every 15s)        │
        ├─ /api/live/data/{f}    (verbatim data/*.json, traversal-safe)    │
        ├─ /api/live/health      (P4-2 freshness gate → status degraded)   │
        ├─ /api/ssot/facts       (CANONICAL headline — UNDERUSED)          │
        ├─ /api/v1/golive        (golive_status.json)                      │
        ├─ /api/health-public    (flat landing widget; reads RIGHT keys)   │
        ├─ /api/rates-desk/*     (surface/opps/decisions/proof/track)  ◄── NEW, unrendered
        ├─ /api/strategy-lab(+/promotion)                              ◄── NEW, unrendered
        ├─ /api/refusal          (SAFE/WATCH/REFUSE per underlying)    ◄── NEW, unrendered
        ├─ /api/rwa-safety-board /api/rwa-nav-curve                    ◄── NEW, unrendered
        └─ /api/tier1/* /api/governance /api/execution/readiness           │
                                                                           ▼
Cloudflare Tunnel  api.earn-defi.com ──────────────────────────► browser dashboard
                                                                  (polls dataBase + LIVE_API)
   fallback when tunnel down:  ./data/*.json  (COMMITTED snapshots → stale, old worldview)
```

The wiring is **correct and capable**. The problem is the dashboard reads the wrong fields from it, ignores
the canonical endpoint, ignores the new endpoints, and falls back to a stale committed worldview.

### 1.3 DISCONNECT (a) — the honest 5/30 track is NOT shown

- **Live truth** (`/api/ssot/facts`, SYSTEM_BRIEFING): `real_track_days = 5`, anchor `2026-06-22`,
  target `2026-07-21`.
- **What the dashboard renders:** track progress is computed from `paper_trading_status.days_running`
  (`= 17`) and `META_TRACK_DAYS = 30` (`index.html:10089`, progress at `:5600`). The hero shows ~**17/30**.
- **Result:** the dashboard inflates the track by **12 days** and hides the honesty reset entirely.
  `golive_status.real_track_days` (the honest field) is **never read** by the hero.

### 1.4 DISCONNECT (b) — Go-Live shows `—/29` even when live (dead key)

- `index.html:5234` reads `golive.criteria_met` and `golive.total_criteria`.
- The live file ships **`passed: 27`, `total: 29`** (and `ready`, not `ready_for_live`). Keys
  `criteria_met` / `total_criteria` **do not exist** → the ternary falls to the em-dash → renders **`—/29`**.
- The flat `/api/health-public` endpoint already reads the RIGHT keys (`gl.passed`, `gl.total`) — the
  dashboard just doesn't use it. So the data is one fetch away; the dashboard looks at the wrong place.

### 1.5 DISCONNECT (c) — static-fallback drift = the OLD worldview, shown silently

- `.gitignore` (P3-3) gitignores `data/*.json` but **keeps three committed snapshots** the static fallback
  depends on: `golive_status.json`, `equity_curve_daily.json`, `paper_evidence_history.json`.
- Those committed snapshots are **stale and pre-reset**:
  - committed `equity_curve_daily.json`: **31 bars, 2026-05-21 → 2026-06-20, last $100,118.91**
    (the pre-honesty-teardown 05-20 worldview).
  - committed `golive_status.json`: `criteria_met: null`, `total: null` (older schema, generated 06-20).
  - live truth on disk: **37 bars ending 2026-06-26, $100,190.22, 17 raw / 5 evidenced days.**
- When the tunnel is down, the dashboard switches `dataBase` to `./data/` and **silently renders the 06-20,
  $100,118.91, pre-reset curve** with a small gray "Static" dot. That is a fabricated-feeling, **stale old
  worldview** masquerading as the dashboard — exactly the "separate world."

### 1.6 DISCONNECT (d) — none of the NEW surfaces are rendered

Grep `rates-desk|refusal|rwa-safety|rwa-nav|strategy-lab` over `index.html` + `app.html` → **0 hits.**
Yet every backing endpoint AND data file is live:

| Surface | Endpoint (live) | Data file (present on disk) | On dashboard? |
|---|---|---|---|
| Rates Desk surface/opps | `/api/rates-desk/{surface,opportunities}` | `data/rates_desk/rate_surface.json` | ❌ |
| Rates Desk decisions + PROOF chain | `/api/rates-desk/{decisions,proof}` | `data/rates_desk/decision_log.jsonl` (222 KB) | ❌ |
| Rates Desk paper track | `/api/rates-desk/track` | `data/rates_desk/paper/` | ❌ |
| Refusal engine (SAFE/WATCH/REFUSE) | `/api/refusal` | `data/refusal_status.json` | ❌ |
| RWA safety board | `/api/rwa-safety-board` | `data/rwa_safety_board.json` (14 KB) | ❌ |
| RWA NAV forward record | `/api/rwa-nav-curve` | `data/rwa_nav_curve.json` | ❌ |
| Strategy Lab comparison + promotion | `/api/strategy-lab(+/promotion)` | `data/strategy_lab_*.json` | ❌ |

> Note: the Astro **marketing** pages exist (`landing/src/pages/rates-desk.astro`, `rwa-backstop.astro`,
> `structural-desk.astro`) — but those are static narrative pages, NOT the live operational dashboard. The
> live dashboard is frozen on the old portfolio/tournament/go-live worldview.

### 1.7 DISCONNECT (e) — honesty meta carried by the API is dropped by the UI

The API already attaches honest labels the dashboard ignores:
- `_shared.backtest_meta()` stamps `is_backtest / is_realized / basis / disclaimer` on every research
  endpoint; `sleeve_yield_basis()` distinguishes `assumed | live_feed | realized`.
- `/api/live/*` stamps `_fetched_at`; `/api/live/health` returns `status: degraded` + `track` block from the
  P4-2 gate (SLA = 30 h).
- The dashboard renders a single top-level green/gray Live/Static dot, but **drops per-metric honesty
  labels** (no "assumed", no "backtest, not realized", no "advisory", no per-card stale-age). So a realized
  paper number and an assumed/backtest number look identical on screen.

### 1.8 Fabricated / hardcoded numbers (lower severity, but present)

Mostly benign display fallbacks, but they ARE a hardcoded worldview that should yield to the API:
- `$100,000` initial capital baked in (`index.html` 1910, 4913, 5186, 5411, …) — used for P&L math when
  `equity_now` is null. Acceptable as a known constant, but should come from `capital_config.json`.
- `META_TRACK_DAYS = 30`, `META_GOLIVE = 2026-07-21`, `META_PAPER_START = 2026-05-20`,
  `META_TRACK_START = 2026-06-10` (`:10086–10089`) — hardcoded; should be SSOT-driven.
- "Day — of 56" (`:3938`) and `7.30%` APY target (`:2828`) — hardcoded labels.
- **The genuinely dangerous ones are the committed stale fallbacks (1.5), not these constants.**

### 1.9 Infra notes confirmed from memory

- **Port-8765 dual-bind:** FastAPI (IPv4) vs a stdlib server (IPv6) on the same port → bind to `127.0.0.1`.
- **apiserver staleness:** uvicorn must be kickstarted after `server.py` edits; the P4-2 freshness gate now
  surfaces a stale track as `status: degraded` in `/api/live/health` — the dashboard must consume that.

---

## 2. Canonical-dashboard decision

**Decision: ONE canonical operational dashboard, ONE canonical source of truth, two consumer surfaces.**

1. **Source of truth = the API, headlined by `/api/ssot/facts`.** Every number on the hero/headline comes
   from SSOT `key_facts()` (already returns track 5, go-live 27/29, equity, return, APY, NAV,
   `nav_reconciliation_ok`). No re-derivation from per-file raw fields, no `days_running` for the track.

2. **Canonical dashboard = `index.html`, with `app.html` as a BUILD ARTIFACT, never a hand-copy.**
   - Kill the two-copies-kept-in-sync hazard. `landing/public/app.html` becomes a generated copy of
     `index.html` at deploy time (one-line build step), or `/app` is repointed to serve the same file. There
     is exactly **one editable dashboard source**.

3. **Two consumer surfaces, ONE truth feed (not two worldviews):**
   - **Ops/owner view** (full): all tabs incl. system/agents/ops/decisions (the existing hidden tabs).
   - **Investor view** (curated): track-record, go-live, positions, honesty disclaimers, proof-of-reserves —
     a filtered render of the SAME `/api/ssot/facts` + endpoints. `investor_portal.html` is folded into this
     as the "snapshot/export" mode (its honest 24h-stale + all-`—` behavior is the model to copy upward).
   - Both views render the identical canonical data; the difference is **which panels are shown**, never a
     different number.

> Rationale: the "separate world" is not solved by another dashboard — it is solved by deleting divergence.
> One source (`/api/ssot/facts` + the typed endpoints), one renderer, role-filtered panels.

---

## 3. The reconnection design

### 3.1 Hero / headline — pull from SSOT, period

| Hero field | OLD (wrong) source | NEW (canonical) source |
|---|---|---|
| Track days | `paper_trading_status.days_running` (=17) | `ssot.track_days` / `golive.real_track_days` (=**5**) /30 |
| Go-Live | `golive.criteria_met` / `.total_criteria` (→ `—/29`) | `ssot.golive_passed` / `ssot.golive_total` (=**27/29**) |
| Equity | mixed files + `$100,000` fallback | `ssot.current_equity` |
| Return % | re-derived | `ssot.total_return_pct` |
| APY today | `paper_trading_status.apy_today_pct` | `ssot.apy_today_pct` (+ "annualized, not daily" note) |
| NAV / reconciliation | not shown | `ssot.nav` + `ssot.nav_reconciliation_ok` (show ⚠ if false) |
| Go-live target / anchor | hardcoded `2026-07-21` | `ssot.go_live_target` / `ssot.evidenced_anchor` |

Single fetch (`/api/ssot/facts`) drives the entire headline → impossible for the hero to drift from SSOT.

### 3.2 Honest staleness — replace the silent old-worldview fallback

**Policy: NEVER silently render a stale committed snapshot as if current. Stale = labeled, not hidden.**

1. **Primary freshness = `/api/live/health`** (P4-2 gate, SLA 30 h). The dashboard reads `status`
   (`ok|degraded`), `track_fresh`, and `track.age_hours` and shows a **first-class banner**:
   - `ok` → green "Live · updated Ns ago".
   - `degraded` → amber "Track stale — last evidenced bar N h ago (SLA 30 h)".
   - tunnel unreachable → red "Live API unreachable — data may be stale".
2. **Per-panel age:** every `/api/live/*` payload carries `_fetched_at`; render "N min/h ago" per card.
   Beyond a panel SLA → grey the numbers + show "data unavailable / N h stale". **No fabricated value.**
3. **Static-fallback policy (the key change):**
   - When the tunnel is down, the dashboard may load `./data/` **only to show a clearly-labeled "OFFLINE
     SNAPSHOT — as of <generated_at>"** card, never the live hero.
   - **Stop committing live track snapshots** as silent fallbacks. Two options (owner picks):
     - **(A) Preferred:** publish a tiny `data/_dashboard_snapshot.json` from `/api/ssot/facts` on each
       deploy (a real, dated snapshot), and show it ONLY with an "as-of" stamp. Remove the stale 06-20
       `equity_curve_daily.json` / `golive_status.json` from git tracking.
     - **(B) Minimum:** keep the committed files but the renderer MUST gate them behind the "OFFLINE
       SNAPSHOT as-of <date>" label and refuse to present them as the live hero.
4. **Self-heal tie-in:** `/api/live/health` `degraded` is the same signal the agent-health monitor /
   self-heal already act on; the dashboard simply mirrors it. No new backend needed.

### 3.3 New surfaces — render what already exists

Add panels/tabs, each a thin render of an existing endpoint (all graceful, never 500):

| New panel | Endpoint(s) | Honesty framing to show |
|---|---|---|
| **Rates Desk** | `/api/rates-desk/{surface,opportunities,track}` | "research, not realized" `meta.basis`; `is_advisory` |
| **Decision log + PROOF** | `/api/rates-desk/{decisions,proof}` | `verified` chain badge, ENTRY/REFUSAL counts |
| **Refusal engine** | `/api/refusal` | per-underlying SAFE/WATCH/REFUSE; "ADVISORY only" |
| **RWA backstop** | `/api/rwa-safety-board`, `/api/rwa-nav-curve` | LIQUID/THIN/UNSAFE; "advisory / research only" |
| **Strategy Lab** | `/api/strategy-lab(+/promotion)` | per-sleeve `yield_basis` assumed/live_feed/realized |
| **Structural desk** | `/api/strategy-lab/promotion` (rates_desk section) | `is_advisory=True`, `live_eligible=False` always |

### 3.4 Honesty meta — render the labels the API already sends

A shared `<HonestyBadge>` component reads each payload's `meta` / `is_advisory` / `is_realized` /
`yield_basis` and renders the right chip next to the number:
- `realized` → no chip (it's the live paper track).
- `assumed` → amber "ASSUMED — not realized".
- `live_feed` → blue "live feed".
- `is_backtest` / `is_advisory` → grey "BACKTEST / ADVISORY — not a track record" (+ tooltip = `meta.basis`).
This makes a backtest number visually impossible to confuse with the realized track — the honesty-first rule
becomes structural, not editorial.

### 3.5 A thin canonical client (kill divergence at the code level)

Introduce **one** small JS module (`dashboard/spa_api.js`, vanilla, no deps) that both the ops and investor
views import:
- `getFacts()` → `/api/ssot/facts` (hero truth).
- `getHealth()` → `/api/live/health` (freshness/banner).
- `getLive(file)` → `/api/live/data/{file}` (verbatim panels, with `_fetched_at`).
- typed getters for each new endpoint (`getRatesDesk`, `getRefusal`, `getRwaBoard`, `getStrategyLab`, …).
- centralized base-URL detection (localhost:8765 ↔ api.earn-defi.com), `127.0.0.1` not `localhost`,
  no-store fetch, and the ONE staleness/fallback policy from 3.2.
No panel fetches raw files with ad-hoc keys anymore → the dead-key and wrong-field bugs (1.3, 1.4) cannot
recur because there is one place that maps API → view model.

---

## 4. Build plan (phased — owner reviews this doc before any code)

**Phase 0 — Truth correctness (highest impact, smallest change).** Fix the two lies first.
- Hero track → `real_track_days` (5/30); Go-Live → `passed`/`total` (27/29), via `/api/ssot/facts`.
- Net effect after Phase 0: the dashboard tells the truth even before the rebuild.

**Phase 1 — Honest staleness.** Wire `/api/live/health`; first-class fresh/degraded/offline banner;
per-panel `_fetched_at` age; implement the static-fallback policy (3.2) and stop committing stale track
snapshots (or gate them behind "OFFLINE SNAPSHOT as-of").

**Phase 2 — Canonical client.** Extract `dashboard/spa_api.js`; route every existing panel through it;
delete per-panel ad-hoc fetch+key logic. This is the structural cure for the "separate world."

**Phase 3 — New surfaces.** Add Rates Desk, Refusal, RWA backstop, Strategy Lab, Structural panels +
`<HonestyBadge>` (3.3–3.4). Coordinate panel layout with the DESIGNER's UX doc.

**Phase 4 — De-duplicate the frontends.** Make `app.html` a build artifact of `index.html` (one source);
fold `investor_portal.html` into the canonical dashboard's role-filtered "investor / snapshot" mode.

**Phase 5 — Deploy + verify.** GitHub Pages (`deploy-pages.yml`) for `index.html`; CF Pages
(`deploy-landing.yml`) for the Astro site + `/app`; tunnel `api.earn-defi.com → 127.0.0.1:8765`. Add a
smoke check: dashboard hero numbers must equal `/api/ssot/facts` (catch future drift in CI).

### Module / file plan

| Path | Action |
|---|---|
| `index.html` | Repoint hero to `/api/ssot/facts`; fix go-live keys; wire `/api/live/health` banner; add new panels |
| `dashboard/spa_api.js` (new) | The one canonical client + base-URL/staleness/fallback policy |
| `landing/public/app.html` | Become a generated copy of `index.html` (build step), not a hand-maintained twin |
| `investor_portal.html` | Folded into canonical dashboard "investor / snapshot" mode |
| `.gitignore` / `data/golive_status.json` `equity_curve_daily.json` | Stop committing stale track snapshots; publish dated `_dashboard_snapshot.json` instead |
| `.github/workflows/{deploy-pages,deploy-landing}.yml` | Add hero == SSOT smoke check; generate `app.html` from `index.html` |

---

## 5. Acceptance criteria (definition of "no longer a separate world")

1. Hero shows **5/30 track** and **27/29 go-live** (matches `/api/ssot/facts` + SYSTEM_BRIEFING), live.
2. When the tunnel is down, the dashboard shows **"OFFLINE SNAPSHOT as-of <date>" / "N h stale"** — never a
   silent pre-reset 06-20 / $100,118.91 worldview.
3. No hero number is re-derived from a raw file with a divergent key; every headline number traces to SSOT.
4. Rates Desk, Refusal, RWA backstop, Strategy Lab, Structural surfaces are rendered from their live
   endpoints, each carrying its honesty label (advisory / backtest / assumed / realized).
5. There is exactly **one editable dashboard source**; `app.html` is generated; investor view is a filtered
   render of the same truth.
6. A CI smoke check fails if the dashboard hero diverges from `/api/ssot/facts`.

---

*This is the architecture/data-flow half. The DESIGNER's UX doc owns layout/visual; the two are designed to
compose: this doc says WHICH endpoint each number comes from and HOW staleness/honesty is signaled, the UX
doc says WHERE on the page it lives and how it looks. Owner reviews before rebuild.*
