#!/usr/bin/env python3
"""One-shot KANBAN sync for autonomous session -> sprint v12.80.
Reloads from disk, mutates, writes atomically (tmp + os.replace).
Concurrent hourly writer-safe."""
import json, os, sys, tempfile

PATH = os.path.join(os.path.dirname(__file__), "..", "KANBAN.json")
PATH = os.path.abspath(PATH)

SPRINT = "v12.80"

# New session tickets -> done
NEW = [
    ("MP-1590", "S22-S25 strategies (Ethena yield-max, Pendle PT fixed, Base-chain max, yield ladder)", "spa_core/strategies/s22_ethena_yield_max.py"),
    ("MP-1591", "S26-S30 exotic strategies (vol harvester, stablecoin carry, momentum yield, barbell+, all-weather)", "spa_core/strategies/s26_volatility_harvester.py"),
    ("MP-1592", "S31-S32 bear hedge strategies (bear-market hedge, market neutral)", "spa_core/strategies/s31_bear_market_hedge.py"),
    ("MP-1593", "S34-S37 Arbitrum strategies (arb yield, gmx carry, cross-chain optimizer, radiant concentrated)", "spa_core/strategies/s34_arbitrum_yield.py"),
    ("MP-1594", "S38-S39 Morpho max strategies (morpho max, morpho max plus)", "spa_core/strategies/s38_morpho_max.py"),
    ("MP-1595", "S41-S45 AMM + spike strategies (amm stable, crisis refuge, vol-adjusted, spike harvester, mean reversion)", "spa_core/strategies/s41_amm_stable_yield.py"),
    ("MP-1596", "S46-S55 income + tournament strategies (safe harbor, monthly income, util-aware, diversified max, tournament champion, etc.)", "spa_core/strategies/s50_tournament_champion.py"),
    ("MP-1597", "Kelly sizing + parameter optimizer (advisory allocation)", "spa_core/allocator/kelly_sizer.py"),
    ("MP-1598", "Real-data 365-day backtest runner", "scripts/run_backtest_real.py"),
    ("MP-1599", "Risk analytics v2 (VaR, stress tester, correlation tracker)", "spa_core/risk/stress_tester.py"),
    ("MP-1600", "Historical APY data pipeline", "spa_core/data_pipeline/"),
    ("MP-1601", "Security audit + CF tunnel token finding (cf_install_token.command)", "scripts/cf_install_token.command"),
    ("MP-1602", "Compliance reporting + monthly statement", "spa_core/reporting/"),
    ("MP-1603", "GoLive 27/29 honest fix", "spa_core/paper_trading/golive_checker.py"),
    ("MP-1604", "Telegram crons (daily + weekly + milestone)", "spa_core/reporting/"),
    ("MP-1605", "ADR-042 through ADR-050", "docs/adr/"),
    ("MP-1606", "Portfolio optimizer (optimal 4.48% APY)", "spa_core/analytics/portfolio_optimizer.py"),
    ("MP-1607", "DeFiLlama yield research report", "docs/"),
    ("WEB-026", "Site: emergency-withdrawal page + trust.astro fixes", "landing/src/pages/emergency-withdrawal.astro"),
    ("WEB-027", "CURRENT_STATE.md honest GoLive update", "CURRENT_STATE.md"),
    ("MP-1608", "APY spike monitor wiring (req MP-1581)", "spa_core/alerts/apy_spike_monitor.py"),
    ("MP-1609", "Governance watcher v2", "spa_core/alerts/governance_watcher_v2.py"),
    ("MP-1610", "Benchmark tracker (alpha vs Aave)", "spa_core/analytics/benchmark_tracker.py"),
]

# Stragglers to close out of in_progress/backlog. Mark superseded where folded.
CLOSE = {
    "MP-1555": ("in_progress", None),                 # Ethena sUSDe adapter -> verified present
    "MP-1562": ("in_progress", "MP-1590"),            # S22-S25 -> superseded
    "MP-1563": ("backlog", "MP-1591"),                # S26-S30 -> superseded
    "SITE-030": ("backlog", "WEB-026"),               # emergency withdrawal -> done via WEB-026
}

def main():
    with open(PATH) as f:
        d = json.load(f)

    cols = d["columns"]
    existing = set()
    for items in cols.values():
        for t in items:
            if isinstance(t, dict) and t.get("id"):
                existing.add(t["id"])

    added = []
    for tid, title, module in NEW:
        if tid in existing:
            print(f"SKIP (exists): {tid}")
            continue
        cols["done"].append({
            "id": tid, "title": title, "status": "done",
            "module": module, "sprint": SPRINT,
        })
        added.append(tid)

    # Move/close stragglers
    moved = []
    for tid, (src, supersedes) in CLOSE.items():
        srclist = cols.get(src, [])
        for i, t in enumerate(list(srclist)):
            if isinstance(t, dict) and t.get("id") == tid:
                item = srclist.pop(i)
                item["status"] = "done"
                item["sprint"] = SPRINT
                if supersedes:
                    item["superseded_by"] = supersedes
                cols["done"].append(item)
                moved.append(tid)
                break

    # done_count: count only genuinely-new done items (avoid superseded double-count)
    superseded = sum(1 for v in CLOSE.values() if v[1] and v[1].startswith("MP"))
    inc = len(added) + (len(moved) - superseded)
    old = d.get("done_count", 0)
    d["done_count"] = old + inc

    # Top-level bookkeeping
    d["sprint_current"] = SPRINT
    d["current_sprint"] = SPRINT
    d["sprint_completed"] = SPRINT
    d["version"] = "12.80.0"
    d["last_updated"] = "2026-06-21T00:00:00Z"
    d["updated_by"] = "AGENT_v1280"
    d["last_checked"] = "2026-06-21"
    d["last_completed"] = "2026-06-21"
    if isinstance(d.get("meta"), dict):
        d["meta"]["done_count"] = d["done_count"]
        d["meta"]["sprint_completed"] = SPRINT
        d["meta"]["last_updated"] = "2026-06-21"
    if isinstance(d.get("sprint_log"), list):
        d["sprint_log"].append({
            "sprint": SPRINT, "date": "2026-06-21",
            "summary": f"Autonomous session sync: +{len(added)} tickets (S22-S65 strategies, "
                       "adapters Ethena/Fluid/Usual/Silo/Dolomite/Aerodrome/Velodrome/Pendle PT, "
                       "Kelly+optimizer, risk v2, backtest, compliance, ADR-042..050, "
                       "GoLive 27/29, Telegram crons, benchmark tracker).",
            "done_count": d["done_count"],
        })

    # Atomic write
    dirn = os.path.dirname(PATH)
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    except Exception:
        os.unlink(tmp)
        raise

    print(f"\nadded ({len(added)}): {added}")
    print(f"moved/closed ({len(moved)}): {moved}")
    print(f"superseded (not counted): {superseded}")
    print(f"done_count: {old} -> {d['done_count']} (+{inc})")
    print(f"sprint: {SPRINT}  version: {d['version']}")
    print(f"columns.done now: {len(cols['done'])}")
    print(f"in_progress now: {len(cols['in_progress'])}  backlog now: {len(cols['backlog'])}")

if __name__ == "__main__":
    main()
