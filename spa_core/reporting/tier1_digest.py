"""
spa_core/reporting/tier1_digest.py — weekly Tier-1 validation digest to Telegram.

Reports the institutional view: which strategies are gate-eligible, the risk-tier packages
with their net APY, package diversification, and live-vs-backtest divergence. Deterministic,
stdlib only (sends via the canonical telegram_client), LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import html
import json
from pathlib import Path

_DATA = Path(__file__).resolve().parents[2] / "data"


def _load(name: str) -> dict:
    try:
        return json.loads((_DATA / name).read_text())
    except Exception:
        return {}


def _esc(s) -> str:
    return html.escape(str(s))


def build_message() -> str:
    pkgs = _load("tier1_packages.json")
    gate = _load("tier1_gate.json")
    corr = _load("tier1_correlation.json")

    lines = ["📐 <b>SPA — Tier-1 валидация (еженедельно)</b>"]
    lines.append(f"режим: <b>{_esc(pkgs.get('regime') or gate.get('regime') or '—')}</b>")

    # Packages
    lines.append("\n<b>Пакеты</b>")
    for key in ("conservative", "balanced", "aggressive"):
        p = (pkgs.get("packages") or {}).get(key, {})
        if not p:
            continue
        if p.get("status") == "available":
            lines.append(f"• {_esc(p['label'])}: <b>{p.get('blended_net_apy_pct')}%</b> net "
                         f"(risk-adj {p.get('blended_risk_adjusted_apy_pct')}%) · "
                         f"{p.get('n_offered')} страт · worst-case {p.get('stress_worst_case_pct')}%")
        else:
            lines.append(f"• {_esc(p['label'])}: ⏳ нет валидированных стратегий")

    # Gate
    elig = gate.get("eligible_count")
    blk = gate.get("blocked_count")
    if elig is not None:
        lines.append(f"\n<b>Gate</b>: {elig} eligible / {blk} blocked")

    # Diversification (conservative)
    c = (corr.get("packages") or {}).get("conservative", {})
    if c.get("avg_pairwise_corr") is not None:
        lines.append(f"<b>Диверсификация</b> (cons): avg corr {c.get('avg_pairwise_corr')}, "
                     f"ядро {c.get('diversified_subset_size')}/{c.get('n')}")

    # Live divergence
    lv = gate.get("live_vs_backtest", {})
    if lv.get("status"):
        emoji = "⚠️" if lv["status"] == "DIVERGENT" else "✅"
        lines.append(f"<b>Live vs backtest</b>: {emoji} {_esc(lv['status'])} "
                     f"(live {lv.get('live_apy_pct')}% / ожид {lv.get('expected_apy_pct')}%)")

    # ─── Institutional metrics (all best-effort, graceful fallback) ───────────

    # NAV / proof-of-reserves ← data/tier1_nav_proof.json
    nav = _load("tier1_nav_proof.json")
    if nav.get("computed_nav_usd") is not None:
        ok = nav.get("reconciliation_ok")
        emoji = "✅" if ok else "⚠️"
        lines.append(f"\n<b>NAV / proof-of-reserves</b>: ${_esc(nav.get('computed_nav_usd'))} "
                     f"· сверка {emoji}")

    # Risk (reverse stress) ← data/tier1_reverse_stress.json
    rstress = _load("tier1_reverse_stress.json")
    rs = ((rstress.get("strategies") or {}).get("live_portfolio") or {}).get("reverse_stress") or {}
    if rs:
        depeg = rs.get("depeg_breakpoint_pct")
        sleeves = rs.get("exploit_sleeves_to_breach")
        fragile = rs.get("most_fragile_scenario")
        depeg_txt = f"{_esc(depeg)}%" if depeg is not None else "—"
        sleeves_txt = _esc(sleeves) if sleeves is not None else "—"
        lines.append(f"<b>Risk (reverse stress)</b>: depeg breakpoint {depeg_txt}, "
                     f"exploit sleeves {sleeves_txt} · most-fragile {_esc(fragile or '—')}")

    # Execution readiness ← data/execution_readiness.json
    execr = _load("execution_readiness.json")
    if execr.get("posture"):
        ready = execr.get("ready_for_live")
        emoji = "✅" if ready else "⛔"
        n_blockers = len(execr.get("live_blockers") or [])
        lines.append(f"<b>Execution readiness</b>: {_esc(execr.get('posture'))} · "
                     f"ready-for-live {emoji} ({n_blockers} blockers)")

    # Anomalies ← data/anomaly_report.json
    anom = _load("anomaly_report.json")
    if anom.get("overall_status"):
        status = anom.get("overall_status")
        emoji = {"GREEN": "✅", "AMBER": "⚠️", "RED": "🔴"}.get(status, "•")
        lines.append(f"<b>Anomalies</b>: {emoji} {_esc(status)} ({_esc(anom.get('count', 0))})")

    # Governance ← data/governance_policy.json
    gov = _load("governance_policy.json")
    dc = gov.get("dual_control_posture") or {}
    if dc:
        enforced = dc.get("enforced")
        posture = "enforced ✅" if enforced else "advisory ⚠️"
        lines.append(f"<b>Governance</b>: dual-control {posture}")

    lines.append("\n<i>Tier-1: real data + net-of-cost + OOS + capacity. Параллельная модель, RiskPolicy не тронут.</i>")
    return "\n".join(lines)


def send() -> bool:
    """RETIRED as a Telegram push (Phase-1 Telegram rebuild).

    The Tier-1 plane summary is folded into the one daily digest (a section),
    not pushed on its own. build_message() is still produced for that consumer;
    here it routes to the digest queue. Always returns False. Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy.enqueue_digest(
            "tier1_digest", "Tier-1 digest", build_message(),
            reason="tier1_digest_retired_push",
        )
    except Exception:  # noqa: BLE001
        pass
    return False


if __name__ == "__main__":
    import sys
    if "--send" in sys.argv:
        print("sent:", send())
    else:
        print(build_message())
