"""
spa_core/monitoring/threat_reactor.py — intraday protective reactor (MP-REACT).

The 5-minute monitors (peg_monitor, red_flag_monitor, emergency_breakers) only
DETECT + write JSON + Telegram. Between daily cycles the portfolio was static — a
depeg at 14:00 had NO protective action until the next 06:00 cycle (~24h gap).

This reactor closes that gap: every 5 min it reads those signals and, on a CRITICAL
threat to a protocol we actually HOLD, it ACTS deterministically:
  1. activate the kill-switch (writes data/kill_switch_active.json) → the cycle's
     all-cash override honours it on the next run;
  2. kickstart com.spa.daily_cycle so the de-risk executes within minutes, not ~24h;
  3. send a loud Telegram alert.

Triggers (deterministic, stdlib only, LLM FORBIDDEN; LIVE data only — bootstrap/
fallback red-flags are ignored):
  - peg_report.json: any monitored stablecoin in CRITICAL peg state (critical > 0),
    or worst deviation beyond DEPEG_BAND_PCT;
  - red_flags.json (fallback_used == False): a CRITICAL flag on a HELD protocol;
  - emergency_status.json: state HALT or PAUSE.

Fail-SAFE: the activation write is retried and, if it can't be written, alerts loudly
(a swallowed error here would mean no protection). Idempotent — won't re-fire while
the kill-switch is already active.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_STATUS = _DATA / "threat_reactor_status.json"

DEPEG_BAND_PCT = 1.5            # worst stablecoin deviation > 1.5% → threat
SUBPROC_TIMEOUT = 20


def _load(name: str, default):
    try:
        return json.loads((_DATA / name).read_text())
    except Exception:
        return default


def _held_protocols() -> set:
    pos = _load("current_positions.json", {})
    p = pos.get("positions") if isinstance(pos, dict) else None
    return {str(k).lower() for k in (p or {})} if isinstance(p, dict) else set()


def _norm(s: str) -> str:
    return str(s or "").lower().replace("-", "_")


def _detect_threats() -> List[str]:
    """Return a list of human-readable CRITICAL threats (empty = all clear)."""
    threats: List[str] = []
    held = _held_protocols()

    # 1) Stablecoin depeg (peg_monitor monitors the stables underlying our positions).
    peg = _load("peg_report.json", {})
    if isinstance(peg, dict):
        if int(peg.get("critical", 0) or 0) > 0:
            threats.append(
                f"depeg CRITICAL: {peg.get('worst_adapter','?')} "
                f"dev {peg.get('worst_deviation_pct','?')}%"
            )
        else:
            try:
                if abs(float(peg.get("worst_deviation_pct", 0) or 0)) > DEPEG_BAND_PCT:
                    threats.append(
                        f"depeg {peg.get('worst_adapter','?')} "
                        f"{peg.get('worst_deviation_pct')}% > {DEPEG_BAND_PCT}%"
                    )
            except (TypeError, ValueError):
                pass

    # 2) Red flags — LIVE only, CRITICAL, on a HELD protocol.
    rf = _load("red_flags.json", {})
    if isinstance(rf, dict) and not rf.get("fallback_used", False):
        for f in rf.get("red_flags", []):
            if not isinstance(f, dict):
                continue
            if str(f.get("severity", "")).upper() not in ("CRITICAL", "CRIT"):
                continue
            proto = _norm(f.get("protocol"))
            if any(h and (h in proto or proto in h) for h in held):
                threats.append(
                    f"red flag CRITICAL on HELD {f.get('protocol')}: {f.get('category')}"
                )

    # 3) Emergency breakers HALT/PAUSE.
    emg = _load("emergency_status.json", {})
    if isinstance(emg, dict):
        st = str(emg.get("status") or emg.get("state") or "").upper()
        if st in ("HALT", "PAUSE", "HALTED", "PAUSED"):
            threats.append(f"emergency breaker: {st}")

    return threats


def _kill_switch_active() -> bool:
    """Authoritative: true only when the file exists AND active is truthy.
    (A manual /resume can leave the file present with active=false — file existence
    alone is NOT 'active', matching how the cycle reads it.)"""
    try:
        from spa_core.governance.kill_switch import KillSwitchChecker
        res = KillSwitchChecker(data_dir=str(_DATA)).is_kill_switch_active()
        return bool(res[0] if isinstance(res, tuple) else res)  # API returns (bool, reason)
    except Exception:
        d = _load("kill_switch_active.json", None)
        if d is None:
            return False
        return bool(d.get("active", True))  # legacy: bare file == active


def _activate(reason: str) -> bool:
    """Fail-safe activation: try the API, retry, return success."""
    for _ in range(3):
        try:
            from spa_core.governance.kill_switch import KillSwitchChecker
            KillSwitchChecker(data_dir=str(_DATA)).activate_kill_switch(reason)
            if _kill_switch_active():
                return True
        except Exception:
            pass
    # Last-resort direct write so protection is never silently lost.
    try:
        payload = {
            "active": True, "reason": reason, "source": "threat_reactor",
            "activated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".ks_")
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, _DATA / "kill_switch_active.json")
        return _kill_switch_active()
    except Exception:
        return False


def _kickstart_cycle() -> None:
    try:
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.spa.daily_cycle"],
            capture_output=True, text=True, timeout=SUBPROC_TIMEOUT,
        )
    except Exception:
        pass


def _send_telegram(msg: str) -> None:
    """Route the kill-switch alert through the SINGLE push authority (Tier-1).

    Phase-1 rewire: threat_reactor no longer calls send_message directly. The
    kill-switch firing is a genuine real-time interrupt (capital action taken),
    so it pushes the whitelisted ``kill_switch`` key via push_policy. It is
    edge-triggered, so a kill that stays active does not re-push every 5 min.
    Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy.push_critical(
            "kill_switch",
            "CRITICAL",
            "SPA Threat Reactor — Kill Switch",
            msg,
        )
    except Exception:  # noqa: BLE001
        pass


def _save(report: dict) -> None:
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".threat_")
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, _STATUS)
    except Exception:
        pass


def run_reactor(dry_run: bool = False) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    threats = _detect_threats()
    already = _kill_switch_active()
    acted = False
    activation_failed = False

    if threats and not already and not dry_run:
        reason = "threat_reactor: " + "; ".join(threats)
        if _activate(reason):
            acted = True
            _kickstart_cycle()
            _send_telegram(
                "🚨 <b>SPA THREAT REACTOR — KILL-SWITCH ACTIVATED</b>\n"
                + "\n".join("• " + t for t in threats)
                + "\n→ портфель уходит в кэш на ближайшем цикле (запущен принудительно)."
            )
        else:
            activation_failed = True
            _send_telegram(
                "⛔ <b>SPA THREAT REACTOR — НЕ СМОГ активировать kill-switch!</b>\n"
                + "\n".join("• " + t for t in threats)
                + "\n→ ТРЕБУЕТСЯ РУЧНОЕ ВМЕШАТЕЛЬСТВО."
            )

    report = {
        "ts": now,
        "threats": threats,
        "kill_switch_already_active": already,
        "acted": acted,
        "activation_failed": activation_failed,
        "clear": not threats,
        "LLM_FORBIDDEN": True,
    }
    if not dry_run:
        _save(report)
    return report


if __name__ == "__main__":
    import sys
    res = run_reactor(dry_run="--dry-run" in sys.argv)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    raise SystemExit(2 if res.get("activation_failed") else 0)
