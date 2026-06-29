# Aggressive Strategy Paper Lab — SURFACE (Lane 3)

> **OUTSIDE RiskPolicy · ADVISORY · paper-only.** This is the public *surface* for the Aggressive
> Lab: the parallel paper-test of the 10–15% strategies the desk normally **REFUSES** (sUSDe
> delta-neutral, LRT carry, leverage loops, points/incentive farms), shown — like the tournament —
> **with the risk that comes with the yield**, so the owner can SEE them and CHOOSE later. These
> strategies are **NEVER live-allocated** and **NEVER touch the go-live $100k track**.

This document covers **Lane 3** only — the API + standing agent + dashboard view + owner-selection
flag that *surface* the outputs of Lane 1 (lab core / harness) and Lane 2 (risk / ranking). Lane 3
**computes nothing and ranks nothing**: it serves the producers' outputs verbatim, fail-CLOSED.

---

## Data contract (consumed, not produced, by Lane 3)

| Producer | File | Shape |
|---|---|---|
| Lane 1 | `data/aggressive_lab/<id>/realized_series.jsonl` | append-only, proof-chained; one JSON object per line: `{date, equity_usd, ret?, phase: "forward"\|"backtest", prev_hash, hash, risk_shape?}` |
| Lane 1 (sidecar) | `data/aggressive_lab/<id>/meta.json` | optional `{risk_shape, risk_class, name, mandate}` |
| Lane 2 | `data/aggressive_lab/scorecard.json` | honest multi-metric scorecard — per-strategy `{id, name, mandate, net_return_pct, sharpe, calmar, max_drawdown_pct, tail_loss_in_stress_pct, risk_class (A/B/C/D), risk_class_label, risk_shape, trustworthy, verdict, n_points}` plus top-level `{generated_at, rwa_floor_pct, trustworthy, strategies[]}` |

If Lane 1/2 producers are not built yet, the standing runner records `producer_not_available`
and the surface fail-closes to an honest **"unavailable"** envelope (never a fabricated leaderboard).

---

## 1. API (`spa_core/api/routers/aggressive_lab.py`, registered in `server.py`)

| Endpoint | Method | What |
|---|---|---|
| `/api/aggressive-lab/scorecard` | GET (public) | The honest multi-metric ranking — **return AND risk AND tail** side by side. Served verbatim from `scorecard.json`. |
| `/api/aggressive-lab/strategy/{id}` | GET (public) | A strategy's realized series (forward + backtest phases) + its risk shape / risk class + its scorecard row. |

- **Fail-CLOSED:** missing/corrupt scorecard → **200** with an honest unavailable envelope
  (`available:false`, empty `strategies`, advisory note). **Never 500, never a fabricated number.**
  NaN/inf in a corrupt file are scrubbed to `null`.
- **Forced advisory stamps:** every response carries `advisory:true`, `live_eligible:false`,
  `outside_riskpolicy:true`, `owner_selectable:true`, `owner_select_enabled:<flag>`, plus the
  OUTSIDE-RiskPolicy `note`. These are **forced on** even if a producer bug set `live_eligible:true`
  — the surface can never present an aggressive strategy as live-allocated.
- **id hardening:** `/strategy/{id}` rejects any non-slug id (path-traversal) to an empty series.
- WS2 posture: GET is public; CORS allow-list (SPA origins only) governs cross-origin; no secrets.

## 2. Dashboard view (`landing/src/components/DashboardLive.jsx`)

New tab **"Aggressive Lab"** → `AggressiveLabSection`:
- A red **OUTSIDE RISKPOLICY · ADVISORY · PAPER-ONLY** banner at the top (unmissable).
- The scorecard rendered like the tournament BUT with the **tail/risk columns prominent**:
  Net return · Sharpe (n/a where INSUFFICIENT_DATA — never a degenerate number) · **Max drawdown**
  · **Tail in stress** (the worst replayed loss through the 2024-26 stress windows) · **Risk class**
  (A/B/C/D + shape) · Verdict.
- EN | RU throughout; polls `/api/aggressive-lab/scorecard` every ~15s; offline / unavailable show
  honest states, never blank and never a fabricated leaderboard.

## 3. Standing daily agent (`com.spa.aggressive_lab`)

- Wrapper `scripts/agent_aggressive_lab.sh` → `agent_template.sh` (bash-wrapper, `/tmp` log — rule #11).
- Plist `scripts/com.spa.aggressive_lab.plist`: daily 08:20 + RunAtLoad, `/tmp` logs only.
- Runner `spa_core/strategy_lab/aggressive_lab_runner.py`: one tick = accrue (Lane 1) + re-rank
  (Lane 2), **idempotent per UTC day**, **fail-CLOSED** (a missing producer is recorded, exit 0),
  **never touches the go-live track**. Writes only under `data/aggressive_lab/`.
- **Deploy ONLY via the gate** (CLAUDE.md rule #11):
  `bash scripts/check_agent_before_deploy.sh aggressive_lab` — proves run-once exit 0, log written,
  and the canonical go-live track is **byte-unchanged**. (Not blindly `launchctl`-loaded.)

## 4. Owner-selection flag — `SPA_AGGRESSIVE_LAB_SELECT` (default **OFF**, OWNER-GATED)

- A **scaffold only.** When OFF (default), the surface is pure read-only advisory.
- When the owner sets `SPA_AGGRESSIVE_LAB_SELECT=1`, the surface reports `owner_select_enabled:true`
  so the owner *may later* mark a strategy "selected for consideration".
- **Selection does NOTHING to live allocation.** Promoting an aggressive strategy to real capital is
  **owner-gated AND custody-gated** — it requires an explicit owner decision plus custody/whitelisting
  off-code. The flag NEVER makes a strategy `live_eligible` and NEVER touches the go-live track.

---

## Red-team (what must always hold)

1. The surface **never** presents an aggressive strategy as live-allocated (`live_eligible` forced
   `false`; the flag cannot flip it).
2. The tail is **never hidden** — max-DD, tail-in-stress, and risk-class are mandatory columns.
3. A missing scorecard → honest **"unavailable"**, never a fabricated leaderboard.
4. The standing agent **never** mutates the go-live track (the pre-deploy gate hash-asserts this).

Tests: `spa_core/tests/test_api_aggressive_lab.py` (+ surface-snapshot route table in
`test_api_surface_snapshot.py`).
