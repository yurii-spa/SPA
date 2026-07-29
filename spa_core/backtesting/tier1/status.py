"""
spa_core/backtesting/tier1/status.py — one-glance Tier-1 rollup + problem alerting.

PARALLEL MODEL. Pure stdlib, deterministic, LLM-forbidden. Aggregates the Tier-1 JSONs
(verdict / gate / packages / correlation / data-integrity) into a compact
data/tier1_status.json for the dashboard & briefing, and sends a Telegram alert ONLY when
something is wrong: live-vs-backtest DIVERGENT or data-integrity ISSUES. Quiet when healthy.

REFUSAL-FIRST (invariant #2): "OK" here means *both detectors ran and cleared* — never
"neither detector fired". A detector whose input is absent/corrupt, or which answers with a
non-verdict of its own (`NO_DATA` from the integrity audit, `insufficient_data` from the
gate's divergence check, any unrecognised value), is reported as NOT CHECKED: it lands in
`unchecked`, is mirrored into `problems` so the Telegram alert actually says it, and forces
`health: "ATTENTION"`. Rationale: `run_backtest_tier1.sh` runs under `set +e`, so a step that
dies leaves its artifact stale or missing and the run continues — the previous `== BAD_VALUE`
comparisons turned that into a confident green light on `/api/tier1/status` plus silence.

Scope note: per-artifact PRESENCE and AGE are owned by `pipeline_health.py` (per-artifact
freshness SLOs, core-flag escalation); this module does not duplicate them. `regime`,
`packages` and `diversification_conservative` are reported values, not detectors — a green
`health` says nothing about them beyond what the two detectors cover.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path

from spa_core.utils.atomic import atomic_save

_DATA = Path(__file__).resolve().parents[3] / "data"
_OUT = _DATA / "tier1_status.json"

# Detector vocabularies. A value that is neither the CLEAR nor the PROBLEM word is treated
# as "not measured" — guessing in favour of OK is exactly the fail-OPEN this module had.
_INTEGRITY_CLEAR, _INTEGRITY_PROBLEM = "CLEAN", "ISSUES"
_DIVERGENCE_CLEAR, _DIVERGENCE_PROBLEM = "ok", "DIVERGENT"


def _load(name: str) -> dict | None:
    """A Tier-1 input, or None when it could NOT be read.

    Absent, truncated/corrupt, and valid-JSON-but-not-an-object all return None: the caller
    must be able to tell "read it, nothing wrong" from "never read it". The old version
    returned `{}` for both, which is what made an unreadable input look healthy.
    """
    try:
        data = json.loads((_DATA / name).read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def build(write: bool = True, alert: bool = False) -> dict:
    verdict = _load("tier1_verdict.json")
    gate = _load("tier1_gate.json")
    pkgs = _load("tier1_packages.json")
    integ = _load("tier1_data_integrity.json")
    corr = _load("tier1_correlation.json")

    pkg_summary = {}
    for k, p in ((pkgs or {}).get("packages") or {}).items():
        pkg_summary[k] = {
            "status": p.get("status"),
            "net_apy_pct": p.get("blended_net_apy_pct"),
            "risk_adjusted_apy_pct": p.get("blended_risk_adjusted_apy_pct"),
            "worst_case_pct": p.get("stress_worst_case_pct"),
            "n": p.get("n_offered"),
        }

    problems: list[str] = []
    unchecked: list[str] = []

    # --- detector 1: live-vs-backtest divergence (published by gate.py) -------------------
    lv_status = None
    if gate is None:
        unchecked.append("NOT CHECKED live-vs-backtest: "
                         "data/tier1_gate.json is missing or unreadable")
    else:
        lv = gate.get("live_vs_backtest")
        lv_status = lv.get("status") if isinstance(lv, dict) else None
        if lv_status == _DIVERGENCE_PROBLEM:
            problems.append("live-vs-backtest DIVERGENT")
        elif lv_status != _DIVERGENCE_CLEAR:
            # e.g. "insufficient_data" (no live APY / no validated net APY), or the block is
            # absent entirely — the divergence question was NOT answered.
            unchecked.append("NOT CHECKED live-vs-backtest: "
                             f"the gate returned no verdict ({lv_status!r})")

    # --- detector 2: data integrity (published by data_integrity.py) ---------------------
    integ_status = None
    if integ is None:
        unchecked.append("NOT CHECKED data integrity: "
                         "data/tier1_data_integrity.json is missing or unreadable")
    else:
        integ_status = integ.get("status")
        if integ_status == _INTEGRITY_PROBLEM:
            problems.append(f"data integrity: {integ.get('total_issues')} issue(s)")
        elif integ_status != _INTEGRITY_CLEAR:
            # e.g. "NO_DATA" — the audit itself raised and reported no verdict.
            unchecked.append("NOT CHECKED data integrity: "
                             f"the audit returned no verdict ({integ_status!r})")

    status = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_status",
        "llm_forbidden": True,
        "regime": (verdict or {}).get("regime"),
        "eligible_count": (gate or {}).get("eligible_count"),
        "blocked_count": (gate or {}).get("blocked_count"),
        "data_integrity": integ_status,
        "live_vs_backtest": lv_status,
        "diversification_conservative": (((corr or {}).get("packages") or {}).get("conservative") or {}).get("diversified_subset_size"),
        "packages": pkg_summary,
        # `unchecked` is mirrored into `problems` on purpose: the Telegram alert below and
        # every existing consumer read `problems` only, so an unchecked detector must be
        # visible there or the refusal would be silent.
        "problems": problems + unchecked,
        "unchecked": unchecked,
        "health": "OK" if not problems and not unchecked else "ATTENTION",
    }
    if write:
        atomic_save(status, str(_OUT))
    if alert and status["problems"]:
        try:
            from spa_core.alerts.telegram_client import send_message
            send_message("⚠️ <b>SPA Tier-1 — внимание</b>\n"
                         + "\n".join("• " + p for p in status["problems"]),
                         parse_mode="HTML")
        except Exception:
            pass
    return status


if __name__ == "__main__":
    import sys
    s = build(alert="--alert" in sys.argv)
    print(json.dumps({"health": s["health"], "regime": s["regime"],
                      "eligible": s["eligible_count"], "problems": s["problems"],
                      "unchecked": s["unchecked"],
                      "packages": {k: v["status"] for k, v in s["packages"].items()}},
                     indent=2, ensure_ascii=False))
