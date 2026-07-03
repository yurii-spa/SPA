# ADR-YL-011 — Site Custodian (the public-site data-integrity guardian)

**Status:** ACCEPTED (2026-07-03, owner-directed)
**Owners:** owner + autonomous engine
**Relates:** ADR-YL-006 (evidence levels), ADR-YL-009 (canonical docs); the external-audit sprint (fix/audit)

## Context

A product that sells the honesty of its numbers cannot show wrong numbers. Precedent: for ~24h the live
site showed **"10 evidenced days · ~4.5% paper APY"** while the real state was **11 days · 3.67%** — the
site had drifted a deploy behind and *overstated* the yield. That is disqualifying. The site must never
present stale, divergent, or overstated figures, and must never invent a number to fill a gap.

## Decision — the **Site Custodian**

An autonomous, deterministic, kill-rules-as-code guardian (matching SPA's style) in four mechanisms:

1. **Auto-deploy after every cycle** (`scripts/deploy_site_snapshot.py`, wired into
   `scripts/run_daily_paper_cycle.sh` Step 3). After the daily cycle writes golive/equity/pts, it
   regenerates `landing/src/data/track_snapshot.json` and pushes it *only if changed* → the existing
   `deploy-landing.yml` (triggers on `landing/**`) rebuilds the site. **Fresh snapshot ⇒ fresh site,
   ≤30 min lag, no manual step.**

2. **Independent freshness monitor** (`scripts/site_freshness_monitor.py`,
   `.github/workflows/site_freshness.yml`, every 6h). Does **not** trust the pipeline — it fetches the
   live site + live API + repo snapshot from the outside and asserts the **triple agrees**, is **fresh**,
   is **available**, and **never overstates**. Pure `evaluate()` (tests mock all HTTP) + `run()`. Writes
   `data/site_freshness_report.json`; alerts on any FAIL.

3. **Degraded kill-rule** (refusal-first). If the monitor sees **OVERSTATED_METRIC**, or **staleness > 48h
   on two consecutive runs**, it flips the snapshot to `degraded: true` and deploys. The landing renders
   `degraded` as a plaque — *"live data temporarily unavailable — see the raw chain at api.earn-defi.com"* —
   **instead of a number**. Honest absence beats a false figure. The monitor **clears** it on a passing
   re-check. The generator **carries `degraded` forward** through routine rebuilds (only the monitor
   sets/clears it).

4. **Weekly content audit** (`scripts/site_content_audit.py`,
   `.github/workflows/site_content_audit.yml`, Mondays). No network: cross-page hardcoded-metric
   divergence, stale `2026-XX-XX` dates > 60d, broken internal links/anchors, sitemap↔pages mismatch,
   `_redirects` shadowing. → `data/site_audit_weekly.json`; alerts on NEW fails.

## Invariants (enforced)

- **The site never overstates a metric** — a shown APY higher than the live API is `OVERSTATED_METRIC`
  (CRITICAL) → degrade. (Under-showing or absence is allowed; overstating is not.)
- **Every number carries an as-of** — the freshness monitor fails `MISSING_ASOF` if a page shows a metric
  without an as-of label, or the label disagrees with the snapshot.
- **Missing/unsafe data is shown explicitly** — the degraded plaque, never a stale/placeholder number.
- **The verifier pin is honest** — `VERIFIER_PIN_MISMATCH` if the live `verify_spa.py` SHA ≠ the pin
  (backstops the P0-1 `test_verifier_pin` CI gate).

## Thresholds

| Knob | Value | Where |
|---|---|---|
| Staleness fail | as_of / last-bar > **30h** | `STALE_HOURS` |
| Degrade staleness | > **48h**, two consecutive runs | `DEGRADE_STALE_HOURS` |
| APY tolerance | **0.05 pp** | `APY_TOL_PP` |
| Deploy lag target | ≤ **30 min** after cycle | block 1 |
| Stale-date audit | hardcoded date > **60 d** | `_MAX_DATE_AGE_DAYS` |
| Freshness cadence | every **6h** | `site_freshness.yml` |
| Content-audit cadence | **weekly** (Mon) | `site_content_audit.yml` |

## Alert channels

- **Telegram** (SPA's channel) — token from Keychain (`TELEGRAM_BOT_TOKEN_SPA`) on the Mac; from GitHub
  **secrets** (env) in CI. Never in code.
- **GitHub Action red** — a monitor FAIL exits non-zero → the workflow fails → GitHub notifies watchers
  (a second, independent channel).
- **Report artifacts** — `data/site_freshness_report.json`, `data/site_audit_weekly.json` (uploaded).

## Runbook — what to do per FAIL

- **SITE_BEHIND_SNAPSHOT** — deploy lag. Check the last `deploy-landing.yml` run (re-run if a transient
  GH-Pages/CF failure); confirm the snapshot commit is on `main`.
- **SNAPSHOT_BEHIND_API** — the cycle ran but the snapshot wasn't regenerated/pushed. Check
  `run_daily_paper_cycle.sh` Step 3 in `logs/daily_cycle_*.log`; run `scripts/deploy_site_snapshot.py`.
- **STALE_SNAPSHOT / STALE_API** — the daily cycle didn't advance. Check `com.spa.daily_cycle`
  (`launchctl list | grep daily_cycle`) + `agent_health`; kickstart the cycle.
- **OVERSTATED_METRIC** — site auto-degrades. Root-cause the divergence (usually a stale deploy above a
  compressed live APY); once the fresh snapshot deploys and the monitor re-passes, degraded clears
  automatically. Do NOT hand-edit numbers.
- **UNAVAILABLE** — a page 4xx/5xx or unexpected redirect. Check CF Pages build + `_redirects`
  (`scripts/check_redirect_shadowing.py`).
- **VERIFIER_PIN_MISMATCH** — re-pin per ADR-YL-010/P0-1 (`tests/test_verifier_pin.py`) and re-tag.
- **METRIC_DIVERGENCE / BROKEN_LINK / SITEMAP_MISMATCH / STALE_HARDCODED_DATE** (content audit) — fix the
  source page; add the page to `sitemap.xml`; refresh or parameterize the aging date.

## Consequences

- The 24h-stale-overstated incident cannot recur silently: it would be caught within 6h (monitor),
  auto-degraded if overstated, and alerted. Fresh data reaches the site within 30 min of each cycle.
- New CI gates to keep green: `test_site_freshness_monitor`, `test_site_content_audit` (+ the P0 gates
  `test_verifier_pin`, `check_redirect_shadowing`, `check_snapshot_freshness`).

## Owner-gated

Add GitHub **secrets** `TELEGRAM_BOT_TOKEN_SPA`, `TELEGRAM_CHAT_ID_SPA`, `GITHUB_PAT_SPA` (the last so the
freshness workflow can push the degrade/recover snapshot). Without them the monitor still runs + writes the
report + fails the Action (GitHub-notification alert), but Telegram + auto-degrade-push are skipped.

*Research/ops-layer ADR; touches the public site + CI + the daily-cycle wrapper (owner-authorized site
custodianship). No RiskPolicy / go-live-track / execution change.*
