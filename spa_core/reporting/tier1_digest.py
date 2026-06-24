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
            lines.append(f"• {_esc(p['label'])}: <b>{p.get('blended_net_apy_pct')}%</b> net · "
                         f"{p.get('n_offered')} страт · worst DD {p.get('worst_dd_pct')}%")
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

    lines.append("\n<i>Tier-1: real data + net-of-cost + OOS + capacity. Параллельная модель, RiskPolicy не тронут.</i>")
    return "\n".join(lines)


def send() -> bool:
    try:
        from spa_core.alerts.telegram_client import send_message
        return send_message(build_message(), parse_mode="HTML")
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    if "--send" in sys.argv:
        print("sent:", send())
    else:
        print(build_message())
