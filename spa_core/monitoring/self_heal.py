"""
spa_core/monitoring/self_heal.py — active self-healing watchdog (MP-SELFHEAL).

The other monitors (agent_health, uptime_monitor) only DETECT + alert. This one
ACTS: it revives agents that should be running but aren't, restarts down servers,
and re-runs a missed daily cycle. Runs every 5 min via com.spa.self_heal.

Self-healing rules (deterministic, stdlib only, LLM FORBIDDEN):
  1. Expected agents = every ~/Library/LaunchAgents/com.spa.*.plist that is NOT
     *.disabled and NOT retired. An expected label missing from `launchctl list`
     is only revived when it should be RESIDENT — KeepAlive daemons and
     StartInterval guardians. Calendar/one-time agents (StartCalendarInterval +
     RunAtLoad:False) correctly EXIT between scheduled runs, so "not resident" is
     their normal idle state; bootstrapping them every 5 min is the chronic
     false-CRITICAL churn loop and is NOT done here (launchd fires them on
     schedule; their freshness is the agent_health monitor's job).
  2. Always-on servers (KeepAlive) that are loaded but have PID 0 → kickstart -k.
  3. Daily cycle gap: if paper_trading_status.last_cycle_ts is older than
     CYCLE_GAP_HOURS → run the deterministic gap recovery (cycle_runner) and
     kickstart com.spa.daily_cycle.
  4. Every action is logged to data/self_heal_status.json and (on action or repeated
     failure) sent to Telegram. Fail-safe: a heal attempt never crashes the watchdog.
  R6. telegram_bot with a LIVE pid but a STALE liveness beacon (long-poll wedged —
     rule 2 sees only PID 0) → kickstart -k, edge-triggered + circuit-broken
     (see the R6 constants below; owner mandate 2026-08-21).
  5. own-28 (вариант 1): the final «✅ восстановлено» for the ``core_agent_down``
     alert class is emitted HERE and only here — after a clean run whose own fleet
     check proves every residency-required agent is alive again (fail-CLOSED on
     empty/unreadable observations). watchdog/uptime_monitor keep entry-only rights.

Atomic writes (tmp + os.replace). Idempotent — safe to run every 5 min.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"
_LA = Path.home() / "Library" / "LaunchAgents"
_STATUS = _DATA / "self_heal_status.json"

CYCLE_GAP_HOURS = 28.0          # daily cadence; >28h since last cycle → recover
SUBPROC_TIMEOUT = 25

# R5 — apiserver DATA-staleness probe. The port-liveness probe below treats any
# HTTP response (even 200) as UP, so a hung-but-listening apiserver serving
# FROZEN data (the classic "stale API after a server.py edit") is invisible to
# it. This compares the cycle the apiserver SERVES against the cycle on disk: if
# disk is fresh (the cycle DID run) but the served status is stale past this
# threshold (daily cadence 24h + 6h buffer = one fully-missed cycle), the
# apiserver is serving frozen in-memory state → kickstart it ONCE. Edge-triggered
# + circuit-broken with the SAME revival discipline as agent revivals (keyed
# under the synthetic label below) so a wedged server is never kickstart-looped.
API_STALE_HOURS = 30.0
_API_STATUS_URL = "http://127.0.0.1:8765/api/health-public"
_API_STALE_LABEL = "com.spa.apiserver::stale_data"  # circuit-breaker key

# R6 — telegram_bot BEACON-staleness probe (мандат владельца 2026-08-21, карточка
# agent-telegram-bot-watchdog: бот завис ДВАЖДЫ за день, владелец дважды чинил руками).
# Та же болезнь, что R5, у другого долгожителя: процесс ЖИВ (PID есть — правило 2
# его не видит), а long-poll заклинил. Единственный наблюдаемый признак — маячок
# `telegram_bot_capabilities.json`, который живой бот обновляет каждый виток
# (~30 с; ADR-069). Пока маячок протух, отправители честно снимают кнопки с
# вопросов владельцу — путь его решений рвётся молча.
#   Порог 600 с = 2× BEACON_MAX_AGE_S alert_actions: «протух для кнопок» ещё не
#   значит «мёртв» (могла быть пауза сети) — kickstart только при двукратном.
#   Fail-safe как в R5: нет файла / не читается / нет отметки ⇒ None ⇒ БЕЗ
#   действия (старый бот без маячка не должен уходить в kickstart-петлю).
#   kickstart -k перезапускает ВНУТРИ существующего job — второго поллера
#   (409-инцидент 2026-08-08) этот путь не создаёт по построению.
BOT_BEACON_STALE_S = 600.0
_BOT_BEACON_FILE = "telegram_bot_capabilities.json"
_BOT_LABEL = "com.spa.telegram_bot"
_BOT_STALE_LABEL = "com.spa.telegram_bot::stale_beacon"  # circuit-breaker key

# Shared, single-source residency/classification judgement (same one
# agent_health uses) so self_heal's expected/loaded reconcile with the monitor.
from spa_core.monitoring.agent_health_monitor import (  # noqa: E402
    CYCLE_STALE_H,
    RETIRED_LABELS,
    classify_agent,
    requires_residency,
)

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода. Источник — запись, видимая в этом модуле,
#: и/или прямое утверждение автора в докстринге/константах модуля.
#: Сверка — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/self_heal_revivals.json",
    "data/self_heal_status.json",
)

# Always-on servers (KeepAlive) — if loaded but PID 0, kickstart them.
# bot_commands is RETIRED (replaced by com.spa.telegram_bot, identical module —
# two long-polls would 409-conflict); telegram_bot is the live KeepAlive bot.
_SERVERS = {
    "com.spa.apiserver", "com.spa.httpserver", "com.spa.familyfund",
    "com.spa.cloudflared", "com.spa.dashboard", "com.spa.telegram_bot",
}


def _uid() -> str:
    return str(os.getuid())


def _run(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=SUBPROC_TIMEOUT)


def _loaded_labels() -> Dict[str, int]:
    """label -> pid (0 if not running) for every loaded com.spa.* job."""
    out: Dict[str, int] = {}
    try:
        r = _run(["launchctl", "list"])
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2].startswith("com.spa."):
                pid = 0
                try:
                    pid = int(parts[0])
                except ValueError:
                    pid = 0
                out[parts[2]] = pid
    except Exception:
        pass
    return out


def _expected_labels() -> List[str]:
    """Every installed (non-disabled, non-retired) com.spa.*.plist label."""
    if not _LA.exists():
        return []
    return sorted(
        p.stem for p in _LA.glob("com.spa.*.plist")
        if p.suffix == ".plist"
        and not p.name.endswith(".disabled")
        and p.stem not in RETIRED_LABELS
    )


def _read_plist(label: str) -> dict | None:
    """Best-effort plist dict for ``label`` (for residency classification)."""
    import plistlib
    plist = _LA / f"{label}.plist"
    try:
        with open(plist, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return None


def _must_be_resident(label: str) -> bool:
    """True only for agents launchd keeps resident (KeepAlive / StartInterval).

    Calendar/one-time agents (StartCalendarInterval + RunAtLoad:False) exit
    between scheduled runs and must NOT be bootstrapped just for being idle.
    Uses the same shared judgement as agent_health so the two agree."""
    plist = _read_plist(label)
    return requires_residency(classify_agent(plist), plist)


def _bootstrap(label: str) -> bool:
    plist = _LA / f"{label}.plist"
    if not plist.exists():
        return False
    r = _run(["launchctl", "bootstrap", f"gui/{_uid()}", str(plist)])
    return r.returncode == 0


def _kickstart(label: str) -> bool:
    r = _run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{label}"])
    return r.returncode == 0


# Local liveness probes: URL → launchd label to kickstart if the port isn't listening.
_PROBES = {
    "http://127.0.0.1:8765/health": "com.spa.apiserver",
    "http://127.0.0.1:8766/": "com.spa.familyfund",
    "http://127.0.0.1:8767/": "com.spa.dashboard",
}


def _http_up(url: str) -> bool:
    """True if the port answers with ANY HTTP response (server is listening). False only on
    connection-refused / timeout (server down). 404/500 etc. count as UP."""
    import urllib.error
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=5)
        return True
    except urllib.error.HTTPError:
        return True   # got an HTTP response → listening
    except Exception:
        return False  # refused / timeout / DNS → not listening


def _last_cycle_age_hours() -> float | None:
    try:
        d = json.loads((_DATA / "paper_trading_status.json").read_text())
        ts = d.get("last_cycle_ts")
        if not ts:
            return None
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - t).total_seconds() / 3600.0
    except Exception:
        return None


def _served_cycle_age_hours(url: str = _API_STATUS_URL) -> float | None:
    """Age (hours) of the cycle timestamp the APISERVER SERVES, or None.

    Fetches the served status JSON and reads the freshest of the cycle/served
    timestamps it carries (``last_cycle_at`` / ``last_cycle_ts`` / ``generated_at``).
    None when the server is unreachable, the body is unparseable, or no usable
    timestamp is present — callers treat None as "can't prove staleness" and take
    NO action (fail-safe: a probe error must not trigger a kickstart loop)."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        d = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    youngest: float | None = None
    for key in ("last_cycle_at", "last_cycle_ts", "generated_at"):
        ts = d.get(key)
        if not ts or not isinstance(ts, str):
            continue
        try:
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        age = (now - t).total_seconds() / 3600.0
        if youngest is None or age < youngest:
            youngest = age
    return youngest


def _beacon_age_seconds() -> float | None:
    """Возраст (сек) маячка живости telegram_bot, или None.

    None — когда файла нет, он не читается или отметка неразборчива: «не смогли
    измерить» НЕ доказательство зависания и действия не вызывает (fail-safe,
    ровно как у ``_served_cycle_age_hours``: ошибка пробы не имеет права
    запускать kickstart-петлю)."""
    try:
        d = json.loads((_DATA / _BOT_BEACON_FILE).read_text())
        ts = d.get("updated_at")
        if not ts or not isinstance(ts, str):
            return None
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
    except Exception:
        return None


def _recover_cycle() -> bool:
    """Run the deterministic, file-locked gap recovery (idempotent 1/day)."""
    try:
        r = _run([
            "/Users/yuriikulieshov/miniconda3/bin/python3",
            "-m", "spa_core.paper_trading.gap_monitor", "--recover",
        ])
        ok = r.returncode == 0
    except Exception:
        ok = False
    # Also kickstart the scheduled agent so the next run is on track.
    _kickstart("com.spa.daily_cycle")
    return ok


def _send_telegram(msg: str, dedup_key: str | None = None) -> None:
    """Route self-heal action through the SINGLE push authority (Tier-1).

    Phase-1 rewire: a dead core agent being revived is a genuine real-time
    interrupt → push_policy ``core_agent_down`` (edge-triggered, so a flapping
    agent does not re-push every 5 min). Never raises.

    ``dedup_key`` — stable fingerprint of the concrete incident (the sorted
    labels acted on). Without it, the shared ``core_agent_down`` class stays
    "bad" after the FIRST incident forever (no sender resolves it) and every
    LATER, different incident is silently refused by the edge-trigger —
    measured 2026-08-05: watchdog booked alerts_undelivered
    [self_heal, threat_reactor] with refused_by_push_policy.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy.push_critical(
            "core_agent_down", "CRITICAL", "SPA Self-Heal", msg,
            dedup_key=dedup_key,
        )
    except Exception:  # noqa: BLE001
        pass


def _pending_core_incident() -> dict | None:
    """The push_policy edge-record for ``core_agent_down`` IFF it is 'bad'.

    Returns None when nothing is pending OR the state cannot be read (a state
    read error must never produce a resolve — fail-CLOSED). Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        rec = push_policy.current_record("core_agent_down")
        if rec.get("state") == "bad":
            return rec
    except Exception:  # noqa: BLE001
        pass
    return None


def _resolve_core_agent_down(msg: str) -> bool:
    """Emit the ONE ``bad → ok`` "✅ восстановлено" push for ``core_agent_down``.

    Owner decision own-28 (вариант 1): the FINAL word on the core_agent_down
    alert class belongs to self_heal alone — the only sender that VERIFIES the
    fleet is actually alive again (watchdog/uptime_monitor only detect DOWN and
    keep entry-only rights). Callers gate this on that verification. Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        return bool(push_policy.resolve(
            "core_agent_down",
            "SPA Self-Heal — агенты восстановлены",
            msg,
        ))
    except Exception:  # noqa: BLE001
        return False


def _save(report: dict) -> None:
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".self_heal_")
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, _STATUS)
    except Exception:
        pass


_REVIVAL_LOG = _DATA / "self_heal_revivals.json"
MAX_REVIVALS_PER_HOUR = 5  # circuit-breaker: stop reviving a crash-looping agent


def _revival_history() -> dict:
    try:
        d = json.loads(_REVIVAL_LOG.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _record_revival(hist: dict, label: str, now_epoch: float) -> None:
    hist.setdefault(label, [])
    hist[label] = [t for t in hist[label] if isinstance(t, (int, float)) and now_epoch - t < 3600.0]
    hist[label].append(now_epoch)


def _save_revival_history(hist: dict) -> None:
    try:
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".revivals_")
        with os.fdopen(fd, "w") as f:
            json.dump(hist, f)
        os.replace(tmp, _REVIVAL_LOG)
    except Exception:
        pass


def run_self_heal(dry_run: bool = False) -> dict:
    import time as _t
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    now_epoch = _t.time()
    actions: List[str] = []
    failures: List[str] = []
    breakers: List[str] = []
    # Stable identity of THIS incident (labels acted on / broken) — becomes the
    # push_policy dedup fingerprint so a NEW incident is never silenced by an
    # older one that shares the same event class.
    involved: set[str] = set()

    loaded = _loaded_labels()
    expected = _expected_labels()
    hist = _revival_history()

    # 1) Revive expected agents that are NOT loaded — but ONLY those that should be
    #    RESIDENT (KeepAlive daemons / StartInterval guardians). A calendar /
    #    one-time agent (RunAtLoad:False) that isn't resident has simply exited
    #    between scheduled runs — bootstrapping it every 5 min is the chronic churn
    #    loop, so it is skipped (launchd fires it on schedule). CIRCUIT BREAKER: an
    #    agent revived > MAX_REVIVALS_PER_HOUR is crash-looping; reviving it again
    #    only makes things worse (e.g. a flooding bot) — stop and alert instead.
    resident_expected = [lbl for lbl in expected if _must_be_resident(lbl)]
    skipped_calendar = 0
    for label in expected:
        if label in loaded:
            continue
        if not _must_be_resident(label):
            # correctly-idle calendar/one-time agent → not a fault, don't bootstrap
            skipped_calendar += 1
            continue
        recent = [t for t in hist.get(label, []) if now_epoch - t < 3600.0]
        if len(recent) >= MAX_REVIVALS_PER_HOUR:
            breakers.append(f"circuit-breaker: {label} crash-looping ({len(recent)}/h) — NOT revived")
            involved.add(label)
            continue
        if dry_run:
            actions.append(f"would bootstrap {label}")
        elif _bootstrap(label):
            actions.append(f"revived (bootstrap) {label}")
            _record_revival(hist, label, now_epoch)
            involved.add(label)
        else:
            failures.append(f"bootstrap failed {label}")
            involved.add(label)

    # 2) Always-on servers loaded but with PID 0 → kickstart.
    for label in _SERVERS:
        if label in loaded and loaded[label] == 0:
            if dry_run:
                actions.append(f"would kickstart down server {label}")
            elif _kickstart(label):
                actions.append(f"restarted down server {label}")
                involved.add(label)
            else:
                failures.append(f"kickstart failed {label}")
                involved.add(label)

    # 2b) Active liveness probes — a server can be "loaded" with a PID yet not actually
    # listening (hung/half-dead). Probe the local ports; connection refused → kickstart.
    for url, label in _PROBES.items():
        if _http_up(url):
            continue
        if dry_run:
            actions.append(f"would kickstart unreachable {label} ({url})")
        elif _kickstart(label):
            actions.append(f"restarted unreachable {label} ({url})")
            involved.add(label)
        else:
            failures.append(f"kickstart failed (unreachable) {label}")
            involved.add(label)

    # 2c) R5 — apiserver DATA-staleness probe. The 2b liveness probe only proves
    # the port is LISTENING; a hung-but-listening apiserver serving FROZEN data
    # answers 200 and looks healthy there. Cross-check what it SERVES against the
    # cycle on disk: disk fresh (cycle ran) + served-status stale past
    # API_STALE_HOURS ⇒ frozen in-memory state ⇒ kickstart apiserver ONCE.
    #   - Edge-triggered: only when disk is fresh but the SERVED data is stale.
    #     A fresh API (or a genuinely-stale cycle, handled by step 3) → no action.
    #   - Circuit-broken: shares the revival-history breaker (keyed under
    #     _API_STALE_LABEL) so a server that stays wedged is kickstarted at most
    #     MAX_REVIVALS_PER_HOUR/h — never a kickstart loop.
    disk_age = _last_cycle_age_hours()
    if disk_age is not None and disk_age <= CYCLE_GAP_HOURS:
        served_age = _served_cycle_age_hours()
        if served_age is not None and served_age > API_STALE_HOURS:
            recent = [t for t in hist.get(_API_STALE_LABEL, []) if now_epoch - t < 3600.0]
            if len(recent) >= MAX_REVIVALS_PER_HOUR:
                breakers.append(
                    f"circuit-breaker: apiserver stale-data kickstart "
                    f"suppressed ({len(recent)}/h) — served cycle {served_age:.1f}h "
                    f"old while disk {disk_age:.1f}h"
                )
                involved.add(_API_STALE_LABEL)
            elif dry_run:
                actions.append(
                    f"would kickstart apiserver (serving STALE data: "
                    f"{served_age:.1f}h old vs disk {disk_age:.1f}h)"
                )
            elif _kickstart("com.spa.apiserver"):
                actions.append(
                    f"restarted apiserver serving STALE data "
                    f"(served {served_age:.1f}h old vs disk {disk_age:.1f}h)"
                )
                _record_revival(hist, _API_STALE_LABEL, now_epoch)
                involved.add(_API_STALE_LABEL)
            else:
                failures.append("kickstart failed (stale-data) com.spa.apiserver")
                involved.add(_API_STALE_LABEL)

    # 2d) R6 — telegram_bot beacon-staleness probe. Правило 2 видит только PID 0;
    # зависший бот держит PID и молчит — единственный признак это протухший маячок
    # (см. константы R6 выше). Гейт СНАЧАЛА по loaded (вне Мака/в CI loaded пуст ⇒
    # правило полностью инертно, ни одного чтения диска), потом по маячку.
    # Edge-triggered + circuit-broken той же историей revival, ключ _BOT_STALE_LABEL:
    # заклинивший намертво бот перезапускается не чаще MAX_REVIVALS_PER_HOUR/ч,
    # дальше — предохранитель и тревога (лечим симптом, называем болезнь).
    if loaded.get(_BOT_LABEL, 0) != 0:
        beacon_age = _beacon_age_seconds()
        if beacon_age is not None and beacon_age > BOT_BEACON_STALE_S:
            recent = [t for t in hist.get(_BOT_STALE_LABEL, []) if now_epoch - t < 3600.0]
            if len(recent) >= MAX_REVIVALS_PER_HOUR:
                breakers.append(
                    f"circuit-breaker: telegram_bot stale-beacon kickstart "
                    f"suppressed ({len(recent)}/h) — beacon {beacon_age:.0f}s old"
                )
                involved.add(_BOT_STALE_LABEL)
            elif dry_run:
                actions.append(
                    f"would kickstart telegram_bot (beacon STALE: {beacon_age:.0f}s "
                    f"> {BOT_BEACON_STALE_S:.0f}s, pid alive)"
                )
            elif _kickstart(_BOT_LABEL):
                actions.append(
                    f"restarted hung telegram_bot (beacon {beacon_age:.0f}s stale, "
                    f"pid was alive — long-poll wedged)"
                )
                _record_revival(hist, _BOT_STALE_LABEL, now_epoch)
                involved.add(_BOT_STALE_LABEL)
            else:
                failures.append("kickstart failed (stale-beacon) com.spa.telegram_bot")
                involved.add(_BOT_STALE_LABEL)

    # 3) Daily cycle gap → recover.
    age = _last_cycle_age_hours()
    if age is not None and age > CYCLE_GAP_HOURS:
        if dry_run:
            actions.append(f"would recover cycle (last {age:.1f}h ago)")
        else:
            ok = _recover_cycle()
            (actions if ok else failures).append(
                f"cycle recovery {'ok' if ok else 'attempted/failed'} (was {age:.1f}h)"
            )
            involved.add("com.spa.daily_cycle")

    if not dry_run:
        _save_revival_history(hist)

    # Reconcile counts with the CORRECTED judgement so self_heal_status agrees
    # with live reality (no more "expected==loaded healthy:true" while a dry-run
    # shows 5 calendar agents "missing"). The meaningful invariant is over the
    # RESIDENCY-REQUIRED set: every agent that MUST be resident actually is.
    resident_loaded = sum(1 for lbl in resident_expected if lbl in loaded)
    resident_missing = sorted(lbl for lbl in resident_expected if lbl not in loaded)
    # A cycle age past the system-wide staleness contract (CYCLE_STALE_H = 26h,
    # the SAME threshold agent_health CRITICALs on) can never report healthy —
    # even though ACTION (gap recovery) only fires past CYCLE_GAP_HOURS (28h).
    # 2026-08-05 fail-OPEN: cycle_age_h 27.05 sat in the 26..28 window and this
    # file said healthy:true — a breached threshold reported as health.
    cycle_stale = age is not None and age > CYCLE_STALE_H
    report = {
        "ts": now,
        "expected": len(expected),               # all installed (non-retired)
        "loaded": len(loaded),                    # raw launchctl residents
        "expected_resident": len(resident_expected),
        "loaded_resident": resident_loaded,
        "missing_resident": resident_missing,     # genuinely-down residents (real outage)
        "idle_calendar_skipped": skipped_calendar,  # correctly-idle, NOT churned
        "actions": actions,
        "failures": failures,
        "circuit_breakers": breakers,
        "cycle_age_h": round(age, 2) if age is not None else None,
        "cycle_stale": cycle_stale,
        "cycle_stale_threshold_h": CYCLE_STALE_H,
        # Healthy = no failures/breakers AND every residency-required agent is
        # resident AND the daily cycle is within its staleness SLA. Calendar
        # agents being idle does NOT make us unhealthy.
        "healthy": (not failures and not breakers and not resident_missing
                    and not cycle_stale),
        "LLM_FORBIDDEN": True,
    }
    if not dry_run:
        # ── own-28 (вариант 1): финальное «✅ восстановлено» по core_agent_down ──
        # Гасит ТОЛЬКО self_heal, и ТОЛЬКО когда его СОБСТВЕННАЯ проверка флота
        # этим прогоном доказывает «все агенты снова живы» (те же критерии
        # живости, что и выше — residency + cycle SLA). Fail-CLOSED:
        #   * прогон НИЧЕГО не чинил (actions/failures/breakers пусты) — прогон,
        #     только что реанимировавший агента, доказывает лишь что тот был
        #     мёртв на снимке `loaded`; резолвит СЛЕДУЮЩИЙ чистый прогон;
        #   * данные наблюдения РЕАЛЬНЫ: launchctl ответил (loaded непуст),
        #     плисты видны (expected/resident_expected непусты), возраст цикла
        #     читается (age is not None). Пустой/нечитаемый вход недоказуем →
        #     НЕ гасим (см. `_expected_labels()==[]` при недоступном ~/Library);
        #   * push_policy реально держит 'bad' по core_agent_down — иначе тишина
        #     (и никакой записи состояния каждые 5 минут).
        # watchdog / uptime_monitor прав гасить НЕ получили — их entry-пути
        # не тронуты (закреплено тестом в test_self_heal.py).
        if not (actions or failures or breakers):
            fleet_verified = (
                bool(expected)
                and bool(loaded)
                and bool(resident_expected)
                and not resident_missing
                and age is not None
                and not cycle_stale
            )
            if fleet_verified:
                pending = _pending_core_incident()
                if pending is not None:
                    was = str(pending.get("fingerprint") or "").replace("|", ", ")
                    msg = (
                        f"Все резидентные агенты снова живы "
                        f"({resident_loaded}/{len(resident_expected)}), "
                        f"дневной цикл свежий ({age:.1f} ч назад, "
                        f"порог {CYCLE_STALE_H:.0f} ч).\n"
                        f"Что было: {was or 'инцидент без записанных деталей'}"
                    )
                    report["core_agent_down_resolved"] = bool(
                        _resolve_core_agent_down(msg)
                    )
        _save(report)
        if actions or failures or breakers:
            lines = ["🔧 <b>SPA Self-Heal</b>"]
            for a in actions:
                lines.append(f"✅ {a}")
            for f in failures:
                lines.append(f"❌ {f}")
            for b in breakers:
                lines.append(f"🛑 {b}")
            _send_telegram("\n".join(lines),
                           dedup_key="|".join(sorted(involved)) or None)
    return report


if __name__ == "__main__":
    import sys
    res = run_self_heal(dry_run="--dry-run" in sys.argv)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    raise SystemExit(0 if not res["failures"] else 1)
