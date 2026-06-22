"""
spa_core/alerts/daily_evidence_report.py

MP-1466 (v10.82): Daily evidence progress report sent to Telegram.

Sends a compact HTML summary of paper trading evidence accumulation:
  - Current score breakdown (daily_cycles / apy_tracking / risk_policy / bonus)
  - Days to target
  - ETA estimate

Called by launchd after the daily cycle completes, or manually via CLI.

Architecture:
  - Reads from EvidenceAutoCalculator (spa_core/analytics/evidence_auto_calculator)
  - Sends via TelegramManager (category="daily", 23h cooldown)
  - STDLIB ONLY — no external dependencies
  - LLM FORBIDDEN (monitoring domain)
  - Atomic writes only (via TelegramManager internals)

CLI:
    python3 -m spa_core.alerts.daily_evidence_report          # send if cooldown allows
    python3 -m spa_core.alerts.daily_evidence_report --dry-run # print message, no send
    python3 -m spa_core.alerts.daily_evidence_report --force   # bypass 23h cooldown
"""

from __future__ import annotations

import datetime
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("spa.alerts.daily_evidence_report")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ETA_DATE = "2026-07-18"
_REAL_TRACK_TARGET_DAYS = 30


# ── Helpers ────────────────────────────────────────────────────────────────────

def _html(text: str) -> str:
    """Escape HTML special chars for Telegram HTML parse_mode."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _progress_bar(value: float, total: float, width: int = 10) -> str:
    """Return an ASCII progress bar like ████░░░░░░ 40%"""
    if total <= 0:
        pct = 0.0
    else:
        pct = min(1.0, value / total)
    filled = int(round(pct * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {pct*100:.0f}%"


def _days_to_target(score_total: int, score_target: int) -> int:
    """Pessimistic estimate: 1 pt/day gap."""
    gap = max(0, score_target - score_total)
    return gap


# ── Core function ──────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    """Read JSON defensively; return {} on any error."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _compute_evidence_score(base_dir: str) -> dict:
    """
    Compute evidence score using the same logic as GoLiveReadinessReport.assess_evidence().
    Returns a plain dict with score, max_score, items_done, items_pending, notes.

    Reads:
      data/paper_evidence.json        → real_days count
      data/paper_evidence_history.json → seed_days (is_seed=True entries)
    """
    root = Path(base_dir)
    data_dir = root / "data"

    # Real days
    pe = _read_json(data_dir / "paper_evidence.json")
    real_days = len(pe.get("days", [])) if isinstance(pe, dict) else 0

    # Seed days
    hist = _read_json(data_dir / "paper_evidence_history.json")
    hist_days_raw = hist.get("days", [])
    seed_days = sum(1 for d in hist_days_raw if isinstance(d, dict) and d.get("is_seed"))

    effective = real_days + seed_days * 0.5

    # Tier bonuses (same as assess_evidence)
    CYCLE_TIERS = [(1, 2), (3, 3), (5, 5), (10, 5)]
    cycle_pts = sum(pts for threshold, pts in CYCLE_TIERS if effective >= threshold)
    cycle_pts = min(cycle_pts, 15)

    # Infrastructure pts
    calc_exists = (root / "spa_core" / "analytics" / "evidence_auto_calculator.py").exists()
    hist_init = bool(hist.get("schema_version"))
    infra_pts = (5 if calc_exists else 0) + (5 if hist_init else 0)

    score = infra_pts + cycle_pts

    # APY streak from history (consecutive days with apy_verified=True, most recent)
    apy_streak = 0
    for d in reversed(hist_days_raw):
        if isinstance(d, dict) and d.get("apy_verified"):
            apy_streak += 1
        else:
            break

    return {
        "score": score,
        "max_score": 25,
        "real_days": real_days,
        "seed_days": seed_days,
        "effective": effective,
        "cycle_pts": cycle_pts,
        "infra_pts": infra_pts,
        "apy_streak": apy_streak,
        "is_eligible": score >= _REAL_TRACK_TARGET_DAYS,
    }


def build_evidence_message(base_dir: str = ".") -> str:
    """
    Build the Telegram HTML message for today's evidence update.

    Reads data/paper_evidence_history.json and data/paper_evidence.json directly
    using the same scoring logic as GoLiveReadinessReport.assess_evidence().
    Falls back gracefully if files are missing.

    Returns
    -------
    str
        Telegram HTML-formatted string, ≤ 4 000 chars.
    """
    today = datetime.date.today().isoformat()

    try:
        ev = _compute_evidence_score(base_dir)
    except Exception as exc:
        log.warning("build_evidence_message: score computation failed: %s", exc)
        return (
            f"📊 <b>Evidence Update — {today}</b>\n\n"
            f"⚠️ Score computation error: {_html(str(exc))}"
        )

    score = ev["score"]
    max_score = ev["max_score"]
    real_days = ev["real_days"]
    seed_days = ev["seed_days"]
    effective = ev["effective"]
    cycle_pts = ev["cycle_pts"]
    infra_pts = ev["infra_pts"]
    apy_streak = ev["apy_streak"]
    is_eligible = ev["is_eligible"]

    days_to_go = _days_to_target(score, _REAL_TRACK_TARGET_DAYS)
    bar = _progress_bar(score, max_score, width=10)
    status_icon = "✅" if is_eligible else "⏳"
    streak_icon = "🔥" if apy_streak >= 7 else "📈"

    lines = [
        f"📊 <b>Evidence Update — {today}</b>",
        "",
        f"{status_icon} <b>Score: {score} / {max_score} pts</b>",
        f"<code>{bar}</code>",
        "",
        "📋 <b>Breakdown</b>",
        f"  Infrastructure : <code>{infra_pts:>2} / 10 pts</code>  (calc + history init)",
        f"  Daily cycles   : <code>{cycle_pts:>2} / 15 pts</code>  ({effective:.1f} effective)",
        "",
        f"{streak_icon} <b>APY verified streak:</b> {apy_streak} day(s)",
        f"🌱 <b>Days logged:</b> {real_days} real + {seed_days} seed = {effective:.1f} effective",
        "",
        f"📅 <b>Days to GoLive target (30 pts):</b> {days_to_go}",
        f"🎯 <b>ETA:</b> ~{_ETA_DATE}",
    ]

    if is_eligible:
        lines.append("")
        lines.append("🚀 <b>ELIGIBLE for Pre-Paper review!</b>")

    return "\n".join(lines)


def send_evidence_update(base_dir: str = ".", force: bool = False) -> bool:
    """
    Build and send the daily evidence report via TelegramManager.

    Parameters
    ----------
    base_dir : str
        Repository root (default ".").
    force : bool
        If True, bypass the 23-hour cooldown.

    Returns
    -------
    bool
        True if message was actually sent to Telegram.
    """
    from spa_core.alerts.telegram_manager import TelegramManager

    try:
        message = build_evidence_message(base_dir=base_dir)
    except Exception as exc:
        log.error("daily_evidence_report: build failed: %s", exc, exc_info=True)
        today = datetime.date.today().isoformat()
        message = (
            f"📊 <b>Evidence Update — {today}</b>\n\n"
            f"⚠️ Report generation error: {_html(str(exc))}"
        )

    mgr = TelegramManager(base_dir=base_dir)
    cooldown_override = 0.0 if force else None  # 0h = no cooldown when forced

    sent = mgr.send(
        message,
        title="daily_evidence_report",
        category="daily",
        cooldown_override_hours=cooldown_override,
        parse_mode="HTML",
    )
    if sent:
        log.info("daily_evidence_report: sent ✓")
    else:
        log.debug("daily_evidence_report: suppressed by cooldown or error")
    return sent


# ── CLI ────────────────────────────────────────────────────────────────────────

def _usage() -> None:
    print(
        "Usage:\n"
        "  python3 -m spa_core.alerts.daily_evidence_report            # send (23h cooldown)\n"
        "  python3 -m spa_core.alerts.daily_evidence_report --dry-run  # print, no send\n"
        "  python3 -m spa_core.alerts.daily_evidence_report --force    # bypass cooldown\n"
    )


def main() -> None:  # pragma: no cover
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        _usage()
        sys.exit(0)

    dry_run = "--dry-run" in args
    force = "--force" in args

    base_dir_idx = args.index("--base-dir") if "--base-dir" in args else -1
    base_dir = args[base_dir_idx + 1] if base_dir_idx >= 0 else "."

    if dry_run:
        msg = build_evidence_message(base_dir=base_dir)
        print(msg)
        sys.exit(0)

    sent = send_evidence_update(base_dir=base_dir, force=force)
    sys.exit(0 if sent else 0)  # always exit 0 (non-blocking)


if __name__ == "__main__":
    main()
