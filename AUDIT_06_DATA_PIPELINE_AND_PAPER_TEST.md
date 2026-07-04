# AUDIT_06 — DATA PIPELINE & PAPER TEST

**Generated:** 2026-07-04 · read-only · PHASE 6 · no data-logic changes

---

## The full pipeline (traced)

```
1. RAW SOURCES (live, keyless):
   DeFiLlama (APY/TVL, TTL 300s) · 5-venue funding feed (Binance/Bybit/OKX/KuCoin/Hyperliquid)
   · live tokenized-T-bill RWA feed (~3.4% floor) · Pendle/lending rate surface
        │
2. PRODUCT AGENTS write outputs → data/*.json:
   daily_cycle → data/trades.json, data/equity_curve_daily.json, data/golive_status.json,
                 data/current_positions.json, paper evidence
   tournament/sleeves/rates_desk → their own data/*.json
        │
3. PAPER-TEST SOURCE OF TRUTH:
   data/golive_status.json → real_track_days (evidenced days; anchor 2026-06-22)
   data/equity_curve_daily.json → daily equity (ring-buffer 365)
   → paper day is DATE-DERIVED from the evidenced anchor, NOT a hand-set counter
        │
4. WEBSITE-VISIBLE DATA (two channels):
   (a) BUILD-TIME STATIC: scripts/generate_track_snapshot.py + deploy_site_snapshot.py
       → landing/src/data/track_snapshot.json  (committed to main, built into the site)
   (b) RUNTIME LIVE: DashboardLive.jsx island polls api.earn-defi.com (~15s), overrides static
        │
5. PRODUCTION: Cloudflare Pages builds landing/ on push to main → earn-defi.com
```

## Source-of-truth table

| Concept | Canonical file | Notes |
|---|---|---|
| **Paper-test day** | `data/golive_status.json` → `real_track_days` (=13 at audit) | DATE-DERIVED from evidenced anchor 2026-06-22; NOT a manual counter |
| **Daily equity** | `data/equity_curve_daily.json` | ring-buffer 365 |
| **Site-visible track (static)** | `landing/src/data/track_snapshot.json` | regenerated post-cycle, committed to main |
| **Site-visible track (live)** | `api.earn-defi.com` (FastAPI) | JS overrides the static snapshot |
| **Live-op state** | `docs/SYSTEM_BRIEFING.md` (auto, 30 min) | freshest human-readable state |

## WHY internal data can show a newer day than the live site (the recurring complaint)

Two independent lag points, both real:
1. **Snapshot not yet regenerated/pushed** — if the cycle ran but `deploy_site_snapshot.py` (Step 3 of `run_daily_paper_cycle.sh`) didn't push a fresh `track_snapshot.json`, `main` still holds an old snapshot. → `SNAPSHOT_BEHIND_API`.
2. **CF Pages build lag** — `main` has a fresh snapshot but Cloudflare Pages hasn't rebuilt (opaque git-integration). → `SITE_BEHIND_SNAPSHOT`. **This is the dominant cause** and is owner-gated (CF dashboard), not fixable in-repo.
3. **API vs static** — the LIVE dashboard reads the API (fresh) via JS; a crawler/no-JS view reads the static snapshot (can lag). So "the site" can look fresh OR stale depending on whether JS ran.

## "Current day" / "day N" scattered across files (duplication risk)

`real_track_days` appears (as a mirrored number) in: `golive_status.json` (canonical), `track_snapshot.json` (site static), `paper_trading_status.json`, `docs/SYSTEM_BRIEFING.md`, and hardcoded in several docs (`CLAUDE.md`, `CURRENT_STATE.md`, `README.md`) — the docs are **pinned to `golive_status.json` by `spa_core/tests/test_doc_drift.py`** (a good existing control). **Recommendation: never hand-edit the day in docs; the drift test is the guard.**

## Stale-data risks / broken sync points

- Opaque CF build (dominant) — mitigated by the **Site Custodian** freshness monitor (every 6h) which degrades an OVERSTATED snapshot to a plaque.
- `SPA_PAT` CI secret is **401/invalid** → the freshness monitor's auto-degrade push fails (owner must set a valid token).
- Committed volatile `data/*.json` (owner-gated: `equity_curve_daily.json`, `golive_status.json`, `paper_evidence_history.json`) — historical, safe to untrack now that the legacy dashboard fallback is gone (owner decision).

## Recommended canonical + verification

- **Canonical paper-day = `data/golive_status.json:real_track_days`.**
- **Site freshness check (the daily "can I trust the site?" command):**
```bash
LIVE=$(curl -s https://earn-defi.com/status/ | grep -oE 'st-days"[^>]*>[0-9]+' | grep -oE '[0-9]+$')
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w)
MAIN=$(curl -s -H "Authorization: token $PAT" \
  "https://api.github.com/repos/yurii-spa/SPA/contents/landing/src/data/track_snapshot.json?ref=main" \
  | python3 -c "import sys,json,base64;print(json.loads(base64.b64decode(json.load(sys.stdin)['content']))['real_track_days'])")
echo "live=$LIVE  main-snapshot=$MAIN  (equal ⇒ site fresh; live<main >30min ⇒ CF build lag)"
```
- Automated equivalent: `data/site_freshness_report.json` (committed to main by the Site Custodian).

**At audit time: live=13 == main-snapshot=13 ⇒ SITE FRESH.**
