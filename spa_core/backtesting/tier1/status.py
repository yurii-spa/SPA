"""
spa_core/backtesting/tier1/status.py — one-glance Tier-1 rollup + problem alerting.

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. Aggregates the Tier-1 JSONs
(verdict / gate / packages / correlation / data-integrity) into a compact
data/tier1_status.json for the dashboard & briefing, and sends a Telegram alert ONLY when
something is wrong: live-vs-backtest DIVERGENT or data-integrity ISSUES. Quiet when healthy.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path

_DATA = Path(__file__).resolve().parents[3] / "data"
_OUT = _DATA / "tier1_status.json"


def _load(name: str) -> dict:
    try:
        return json.loads((_DATA / name).read_text())
    except Exception:
        return {}


def build(write: bool = True, alert: bool = False) -> dict:
    verdict = _load("tier1_verdict.json")
    gate = _load("tier1_gate.json")
    pkgs = _load("tier1_packages.json")
    integ = _load("tier1_data_integrity.json")
    corr = _load("tier1_correlation.json")

    lv = gate.get("live_vs_backtest", {})
    pkg_summary = {}
    for k, p in (pkgs.get("packages") or {}).items():
        pkg_summary[k] = {
            "status": p.get("status"),
            "net_apy_pct": p.get("blended_net_apy_pct"),
            "risk_adjusted_apy_pct": p.get("blended_risk_adjusted_apy_pct"),
            "worst_case_pct": p.get("stress_worst_case_pct"),
            "n": p.get("n_offered"),
        }

    problems = []
    if lv.get("status") == "DIVERGENT":
        problems.append("live-vs-backtest DIVERGENT")
    if integ.get("status") == "ISSUES":
        problems.append(f"data integrity: {integ.get('total_issues')} issue(s)")

    status = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_status",
        "llm_forbidden": True,
        "regime": verdict.get("regime"),
        "eligible_count": gate.get("eligible_count"),
        "blocked_count": gate.get("blocked_count"),
        "data_integrity": integ.get("status"),
        "live_vs_backtest": lv.get("status"),
        "diversification_conservative": (corr.get("packages", {}).get("conservative", {}) or {}).get("diversified_subset_size"),
        "packages": pkg_summary,
        "problems": problems,
        "health": "OK" if not problems else "ATTENTION",
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1status_")
        with os.fdopen(fd, "w") as f:
            json.dump(status, f, indent=2)
        os.replace(tmp, _OUT)
    if alert and problems:
        try:
            from spa_core.alerts.telegram_client import send_message
            send_message("⚠️ <b>SPA Tier-1 — внимание</b>\n" + "\n".join("• " + p for p in problems),
                         parse_mode="HTML")
        except Exception:
            pass
    return status


if __name__ == "__main__":
    import sys
    s = build(alert="--alert" in sys.argv)
    print(json.dumps({"health": s["health"], "regime": s["regime"],
                      "eligible": s["eligible_count"], "problems": s["problems"],
                      "packages": {k: v["status"] for k, v in s["packages"].items()}}, indent=2))
