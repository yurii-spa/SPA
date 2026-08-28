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

Recovery (ADR-070 п.4, owner decision 2026-08-07): the reactor also declares the
``bad → ok`` transition of the ``kill_switch`` alert — the switch verifiably off AND
no standing threat. Without that exit the alert had an entry and no way back: in prod
it sat "bad" from 2026-07-04 onward, so push_policy's edge-trigger would have silenced
every FUTURE kill-switch firing. Thresholds (SOFT −5% / HARD −10%) and RiskPolicy are
untouched — this is the notification layer only.
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

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода. Источник — запись, видимая в этом модуле,
#: и/или прямое утверждение автора в докстринге/константах модуля.
#: Сверка — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/kill_switch_active.json",
    "data/threat_reactor_status.json",
)

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


KS_ACTIVE = "active"
KS_CLEAR = "clear"
KS_UNKNOWN = "unknown"


def _kill_switch_state() -> str:
    """Measure the kill-switch: ``active`` / ``clear`` / ``unknown``.

    Three answers, not two, because the two directions need DIFFERENT evidence:

    * to ACT (activate) it is enough to know the switch is not already on — an
      unreadable state file must not stop protection, so it counts as "not
      active" exactly as before;
    * to declare RECOVERY ("стоп-кран снят") we need a POSITIVE measurement that
      it is off. A file we failed to parse is not evidence of anything, and
      announcing "✅ всё хорошо" off an unreadable file is precisely the
      fail-OPEN shape this whole class of fix removes.

    ``clear`` therefore means measured-off: the checker said so, or the file is
    verifiably ABSENT (kill OFF = file absent, the same reading the daily cycle
    uses), or it parsed with ``active`` falsy. A file that exists but cannot be
    read/parsed — or whose very existence cannot be determined — is ``unknown``.
    Never raises.
    """
    try:
        from spa_core.governance.kill_switch import KillSwitchChecker
        res = KillSwitchChecker(data_dir=str(_DATA)).is_kill_switch_active()
        return KS_ACTIVE if bool(res[0] if isinstance(res, tuple) else res) else KS_CLEAR
    except Exception:
        pass
    path = _DATA / "kill_switch_active.json"
    try:
        if not path.exists():
            return KS_CLEAR          # absent file = off, measured
    except OSError:
        return KS_UNKNOWN            # cannot even stat it — we do not know
    try:
        d = json.loads(path.read_text())
    except Exception:
        return KS_UNKNOWN            # present but unreadable — we do not know
    if not isinstance(d, dict):
        return KS_UNKNOWN
    return KS_ACTIVE if bool(d.get("active", True)) else KS_CLEAR  # bare file == active


def _kill_switch_active() -> bool:
    """Authoritative: true only when the file exists AND active is truthy.
    (A manual /resume can leave the file present with active=false — file existence
    alone is NOT 'active', matching how the cycle reads it.)

    Unchanged behaviour: everything that is not a measured ``active`` is "not
    active" here, so an unreadable state file can never block an activation.
    """
    return _kill_switch_state() == KS_ACTIVE


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


def _send_telegram(msg: str, dedup_key: str | None = None) -> None:
    """Route the kill-switch alert through the SINGLE push authority (Tier-1).

    Phase-1 rewire: threat_reactor no longer calls send_message directly. The
    kill-switch firing is a genuine real-time interrupt (capital action taken),
    so it pushes the whitelisted ``kill_switch`` key via push_policy. It is
    edge-triggered, so a kill that stays active does not re-push every 5 min.
    Never raises.

    ``dedup_key`` — stable fingerprint of THIS activation (the threat list).
    Without it, a stale ``kill_switch`` bad-state from an old activation
    (measured in prod: stuck ``bad`` since 2026-07-04 with entry_pushed=false)
    silences every future, DIFFERENT kill-switch firing — the one alert that
    must never be eaten.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy.push_critical(
            "kill_switch",
            "CRITICAL",
            "SPA Threat Reactor — Kill Switch",
            msg,
            dedup_key=dedup_key,
        )
    except Exception:  # noqa: BLE001
        pass


def _pending_kill_switch_incident() -> dict | None:
    """The push_policy edge-record for ``kill_switch`` IFF it is still ``bad``.

    ``None`` when nothing is pending OR the state cannot be read — a state-read
    error must never manufacture a recovery (fail-CLOSED). Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        rec = push_policy.current_record("kill_switch")
        if rec.get("state") == "bad":
            return rec
    except Exception:  # noqa: BLE001
        pass
    return None


def _resolve_kill_switch(rec: dict) -> bool:
    """Emit the ONE ``bad → ok`` "✅ стоп-кран снят" push. Never raises.

    ADR-070 п.4 (owner decision 2026-08-07, variant A). Until this existed the
    ``kill_switch`` key had an entry path and no exit: measured in prod it sat
    ``bad`` since 2026-07-04 with ``entry_pushed: false``, which means the owner
    never received that alarm AND — because push_policy is edge-triggered — would
    never receive the NEXT one either. The one alert that must never be eaten was
    the one being eaten.

    The final word belongs to this reactor because it is the only component that
    measures BOTH halves of "recovered": the switch is verifiably off AND no
    CRITICAL threat is standing. The other sender (``monitoring/intraday_equity``)
    only ever fires the switch, so it keeps entry-only rights — the same split
    owner decision own-28 drew for ``core_agent_down``.

    The message says out loud when the original alarm was never delivered:
    "система уверена, что сообщила, а сообщения не было" is the defect being
    closed here, so the recovery must not quietly imply the owner saw the entry.
    """
    stuck_since = str(rec.get("last_ts") or "")[:19].replace("T", " ")
    body = ["Стоп-кран сейчас снят, CRITICAL-угроз не видно — тревога закрыта."]
    if stuck_since:
        body.append(f"Событие висело в состоянии «плохо» с {stuck_since} UTC.")
    if not bool(rec.get("entry_pushed", True)):
        body.append(
            "Внимание: то, ПЕРВОЕ сообщение о срабатывании до тебя тогда не дошло "
            "(доставка не подтверждена). Пока событие висело, следующая тревога "
            "тоже была бы беззвучной — теперь снова прозвучит."
        )
    try:
        from spa_core.telegram import push_policy
        return bool(push_policy.resolve(
            "kill_switch",
            "SPA Threat Reactor — стоп-кран снят",
            "\n".join(body),
        ))
    except Exception:  # noqa: BLE001
        return False


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
    # Two reads on purpose. ``_kill_switch_active`` stays the seam the ACTIVATION
    # decision hangs on (and the seam the chaos tests inject at — moving it would
    # have silently un-tested re-activation storms); ``_kill_switch_state`` adds the
    # third answer, "unknown", that only the RECOVERY decision needs. They can
    # disagree only under injection, and then the "on" reading wins: any sign of the
    # switch being up blocks a recovery announcement.
    already = _kill_switch_active()
    ks_state = KS_ACTIVE if already else _kill_switch_state()
    acted = False
    activation_failed = False

    if threats and not already and not dry_run:
        reason = "threat_reactor: " + "; ".join(threats)
        threat_fp = "threat_reactor:" + "|".join(sorted(threats))
        if _activate(reason):
            acted = True
            _kickstart_cycle()
            _send_telegram(
                "🚨 <b>SPA THREAT REACTOR — KILL-SWITCH ACTIVATED</b>\n"
                + "\n".join("• " + t for t in threats)
                + "\n→ портфель уходит в кэш на ближайшем цикле (запущен принудительно).",
                dedup_key=threat_fp,
            )
        else:
            activation_failed = True
            _send_telegram(
                "⛔ <b>SPA THREAT REACTOR — НЕ СМОГ активировать kill-switch!</b>\n"
                + "\n".join("• " + t for t in threats)
                + "\n→ ТРЕБУЕТСЯ РУЧНОЕ ВМЕШАТЕЛЬСТВО.",
                dedup_key="activation_failed:" + threat_fp,
            )

    # ── Recovery: the exit the ``kill_switch`` alert never had (ADR-070 п.4) ──
    # Only when BOTH halves are measured: the switch is verifiably off AND no
    # CRITICAL threat is standing. Anything else (unknown state, threats still
    # up) holds the alert bad and SAYS SO in the report — a recovery we cannot
    # measure is not announced, and a hold-back we cannot see is not a hold-back.
    resolved_alert = False
    recovery_held_back = None
    pending = None if dry_run else _pending_kill_switch_incident()
    if pending is not None:
        if ks_state == KS_CLEAR and not threats:
            resolved_alert = _resolve_kill_switch(pending)
            if not resolved_alert:
                recovery_held_back = "resolve_not_delivered"
        elif ks_state != KS_CLEAR:
            recovery_held_back = f"kill_switch_state_{ks_state}"
        else:
            recovery_held_back = "threats_still_present"

    report = {
        "ts": now,
        "threats": threats,
        "kill_switch_state": ks_state,
        "kill_switch_already_active": already,
        "acted": acted,
        "activation_failed": activation_failed,
        "alert_pending_before_run": pending is not None,
        "alert_resolved": resolved_alert,
        "recovery_held_back": recovery_held_back,
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
