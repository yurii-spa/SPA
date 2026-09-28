# Studio OS Shell — read-only bilingual cockpit (v0 vertical slice)

A premium, bilingual (RU/EN), mobile-friendly operational interface for Earn DeFi Studio OS.
Two complementary modes over the **same** canonical-derived state:

- **Mission Control** — dense operational view (Overview · Work · Decisions · Roles · System).
- **Studio View** — DOM/CSS 2.5D "living studio": zones with agent/task tokens bound to real ledger state.

This is the **read-only** first phase (ADR-492, ADR-469 Phase-9 doctrine: v0 ships zero action buttons).

## Architecture (why it is safe)

```
Canonical sources (files/git/ledger — SOURCE OF TRUTH)
  ├─ ~/studio-os-scratch/mission-state/v04/ledger.json   (missions, items, work_graph, dispatch)
  ├─ architecture/*.json (ownership ai_roles, owner_settings, health_contracts)
  ├─ data/*.json (golive_status, risk_alerts, agent_health)   ← freshness-labelled
  ├─ nimbalyst-local/tracker/_BOARD.md (owner decisions)
  ├─ /tmp/spa_studio_{provider,worker}_runner.out.log (plane activity, non-privileged)
  └─ git status/log
        │  (READ ONLY)
        ▼
build_read_model.py  → read_model.json   (DERIVED, disposable, rebuildable; per-entity `source`)
        │
        ▼
serve.py (127.0.0.1 only) ──HTTP──► index.html + app.js + i18n.js + styles.css
        │                                    │  fetch(read_model.json)
        ▼                                    ▼
   Mission Control  ◄────── same state ──────►  Studio View
```

- **UI ≠ canonical state.** `read_model.json` is a derived projection; every entity carries a `source` pointer back to canon. The UI never writes.
- **No second workflow engine.** The projector only reads. There are **no** action endpoints in v0.
- **No secrets.** The projector never reads credential files; provider/candidate come from `/tmp` logs (no token values). Live launchd state is labelled "needs privilege", not faked.
- **Honest freshness.** Every timed source is labelled `LIVE / RECENT / STALE / UNKNOWN`. Stale sources (e.g. `golive_status.json`, `agent_registry.json`) show a stale badge instead of pretending to be current.
- **stdlib only** (repo invariant #4); loopback-only bind (deployment rule #8).

## Run

```bash
python3 studio_shell/serve.py --port 8778 --live       # http://127.0.0.1:8778/  (rebuilds read model on each fetch)
python3 studio_shell/build_read_model.py               # rebuild read_model.json once
python3 studio_shell/build_snapshot.py --lang en --mode studio --page work --out snapshot.html   # offline capture artifact
python3 -m pytest studio_shell/test_read_model.py -q   # contract/smoke test
```

## Files

| File | Role |
|---|---|
| `build_read_model.py` | Projector: canonical sources → `read_model.json` (with provenance + freshness) |
| `read_model.json` | Derived shared state consumed by both UI modes (regenerable) |
| `index.html` / `app.js` / `i18n.js` / `styles.css` | No-build vanilla Shell (Mission Control + Studio View) |
| `serve.py` | Loopback-only static server + read-model rebuild |
| `build_snapshot.py` / `snapshot.html` | Self-contained offline capture artifact (screenshots) — not the product |
| `test_read_model.py` | Read-only contract test (shape, provenance, honest freshness, no secrets) |

## State normalization (backend → UI)

Documented in `build_read_model.py` (`STATE_TO_UI`, `UI_TO_ZONE`) and echoed into `read_model.json`
(`ui_state_map`, `zone_map`) so the mapping is visible, not hidden in components.

## Not in v0 (by design)

Action controls (Approve/Reject/Retry/Pause), realtime push (SSE/WS), local read-model DB,
Investment Engine bridge. Each is a later, separately-audited step (see ADR-492 §Consequences).
