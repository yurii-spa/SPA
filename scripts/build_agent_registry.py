#!/usr/bin/env python3
"""build_agent_registry — канонический авто-реестр ВСЕХ launchd-агентов SPA.

Owner-directive 2026-07-16: «знать каждого агента + система управления + визуальный дашборд».
Детерминированно собирает состояние флота из ЖИВЫХ источников (не руками — чтобы не дрейфовал):
  * `launchctl list | grep com.spa`  → загружен ли, last-exit, PID;
  * `~/Library/LaunchAgents/com.spa.*.plist` → расписание + program (reboot-safe = plist там есть);
  * `spa_core.monitoring.agent_health_monitor.RETIRED_LABELS` → что должно быть ретайрено;
  * role-map (ниже) → категория агента.
Выдаёт `data/agent_registry.json` — SSOT для памяти И для визуального дашборда. Флагает проблемы:
retired-но-загружен · загружен-но-не-reboot-safe · в-реестре-но-не-загружен (drift).

stdlib-only · read-only (ничего не деплоит) · атомарная запись.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_LAUNCH_DIR = Path.home() / "Library" / "LaunchAgents"

# Роли (из аудита WS-B 2026-07-16). Неизвестные → "other".
_ROLE = {
    # INFRA
    "apiserver": "infra", "cloudflared": "infra", "dashboard": "infra",
    "familyfund": "infra", "cc-kanban": "infra", "autopush": "infra", "inbox_watch": "infra",
    # ALLOCATION / paper books
    "daily_cycle": "allocation", "hy_cycle": "allocation", "lp_cycle": "allocation",
    "aggressive_lab": "allocation", "strategy_lab_paper": "allocation",
    "rates_desk_paper": "allocation", "swarm_blend": "allocation", "swarm_brain": "allocation",
    "swarm_regime": "allocation",
    # MONITORING
    "self_heal": "monitoring", "threat_reactor": "monitoring", "watchdog": "monitoring",
    "rules_watchdog": "monitoring", "cycle_gap_monitor": "monitoring", "cycle_health": "monitoring",
    "uptime_monitor": "monitoring", "agent_health": "monitoring", "governance_watcher": "monitoring",
    "portfolio_monitor": "monitoring", "peg_monitor": "monitoring", "red_flag_monitor": "monitoring",
    "base_gas_monitor": "monitoring", "sky_monitor": "monitoring", "bts-feed": "monitoring",
    "bts-monitor": "monitoring", "rtmr_sense": "monitoring", "resilience": "monitoring",
    "golive_freshness": "monitoring", "swarm_health": "monitoring", "swarm_guardian": "monitoring",
    "system_health_morning": "monitoring", "system_health_evening": "monitoring",
    "analytics_tier_b": "monitoring", "analytics_tier_c": "monitoring", "daily_backup": "monitoring",
    "checkpoint-7day": "monitoring", "tier1_governance": "monitoring", "cycle_gap": "monitoring",
    # REPORTING
    "digest_daily": "reporting", "telegram_bot": "reporting", "telegram_milestone": "reporting",
    "system_briefing": "reporting", "dashboard_watcher": "reporting", "work_digest": "reporting",
    # DEV / RESEARCH
    "orchestrator": "research", "novel_edge_rnd": "research", "mass_tournament": "research",
    "tournament_engine": "research", "refusal": "research", "rwa_safety_board": "research",
    "realized_at_size": "research", "dfb_capture": "research",
}


def _launchctl() -> dict[str, dict]:
    """label → {pid, last_exit} for loaded com.spa.* jobs."""
    out: dict[str, dict] = {}
    try:
        res = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=15)
        for line in res.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2].startswith("com.spa."):
                pid = None if parts[0] in ("-", "") else int(parts[0])
                try:
                    last = int(parts[1])
                except ValueError:
                    last = None
                out[parts[2]] = {"pid": pid, "last_exit": last}
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return out


# ── Код выхода дневного цикла: ВТОРОЙ читатель `last_exit` ──────────────────
# Карточка `inbox-otkaz-zamka-tsikla-neotlichim-ot-avarii`, пункт 1 дословно:
# «Измерить ВСЕХ читателей `last_exit`, прежде чем менять код возврата». Коды
# развели (#219, `cycle_exit.py`), читателя `agent_health` научили покупать
# тишину доказательством живого держателя (`judge_lock_refusal`, 08-17) — а этот
# реестр остался слепым к словарю целиком. Замер на этом дереве 18.08:
#
#     last_exit=1 → ['последний выход 1 (проверить)']   ← АВАРИЯ цикла
#     last_exit=2 → ['последний выход 2 (проверить)']   ← защита сработала
#     last_exit=3 → ['последний выход 3 (проверить)']   ← штатный отказ политики
#
# Три противоположных исхода — одна строка, и все три одинаково поднимают
# `problem_count`, который дашборд `/admin/agents` рисует красным KPI. То есть
# ровно то, ради чего карточка заведена, только этажом ниже: правильная работа
# системы неотличима от поломки, и настоящая авария тонет в этом шуме.
#
# Правится ЧТЕНИЕМ ТОГО ЖЕ СУДЬИ, а не второй копией правил:
#   * словарь исходов — `spa_core.paper_trading.cycle_exit` (импорт-free по
#     построению, money-path сюда не тянет — инвариант #6);
#   * законность отказа замка — `cycle_lock_watch.judge_lock_refusal`, тот самый,
#     которым судит `agent_health`. Тишина покупается ТОЛЬКО живым держателем.
#
# Fail-CLOSED дважды: словарь применяется ТОЛЬКО к метке дневного цикла (у чужого
# агента тройка означает что угодно), а если импорт не удался — поведение
# остаётся ПРЕЖНИМ, то есть громким. Молчания по недосмотру здесь быть не может.
_LAST_EXIT_CLEAN = (None, 0, -15)   # 0 — норма, -15 — SIGTERM (штатная остановка)


def judge_last_exit(label: str, le, *, lock_verdict=None) -> tuple:
    """``(проблема | None, заметка | None)`` для кода выхода агента.

    Заметка — это ИНФОРМАЦИЯ: она называет исход вслух, но не красит пульт.
    Проблема — прежний громкий сигнал. Один исход не может быть обоими сразу.
    """
    if le in _LAST_EXIT_CLEAN:
        return (None, None)

    try:
        from spa_core.paper_trading.cycle_exit import (
            CYCLE_AGENT_LABEL, describe_exit, is_by_design,
        )
    except Exception:       # noqa: BLE001 — словарь не прочитан ⇒ старая громкость
        return (f"последний выход {le} (проверить)", None)

    if label != CYCLE_AGENT_LABEL:
        # Словарь описывает исходы ОДНОГО агента. У любого другого те же цифры
        # означают что угодно, и трактовать их — значит замолчать чужую аварию.
        return (f"последний выход {le} (проверить)", None)

    words = describe_exit(le)

    if is_by_design(le):
        # Единственный исход, который словарь называет штатным: гейт отработал,
        # капитал не сдвинулся. 13.08 он держал агента в WARNING круглые сутки.
        return (None, f"последний выход {le} — {words} (штатно, не проблема)")

    try:
        from spa_core.monitoring.cycle_lock_watch import OK as _LOCK_OK, judge_lock_refusal
    except Exception:       # noqa: BLE001
        return (f"последний выход {le} — {words} (проверить)", None)

    refusal = judge_lock_refusal(lock_verdict, le)
    if refusal is not None and refusal[0] == _LOCK_OK:
        # By design ПО ДОКАЗАТЕЛЬСТВУ, а не по коду: держатель предъявлен.
        return (None, f"последний выход {le} — {words}; {refusal[1]}")
    if refusal is not None:
        # Отказ замка без предъявленного держателя: труп в дверях либо «не
        # измерено». Остаётся проблемой — но теперь названной, а не безымянной.
        return (f"последний выход {le} — {words}; {refusal[1]}", None)

    return (f"последний выход {le} — {words} (проверить)", None)


def _cycle_lock_verdict():
    """Вердикт замка дневного цикла или ``None`` («не измерено»).

    ``None`` — безопасная сторона: `judge_lock_refusal` трактует его как
    «законность отказа НЕ ДОКАЗАНА» и оставляет прежнюю громкость.
    """
    try:
        from spa_core.monitoring.cycle_lock_watch import check_cycle_lock
        return check_cycle_lock(_REPO / "data")
    except Exception:       # noqa: BLE001 — измерить не удалось ≠ «всё хорошо»
        return None


def _schedule(plist: dict) -> str:
    if "StartInterval" in plist:
        s = int(plist["StartInterval"])
        return f"каждые {s//3600}ч" if s % 3600 == 0 and s >= 3600 else f"каждые {s//60}м" if s % 60 == 0 else f"{s}с"
    if "StartCalendarInterval" in plist:
        ci = plist["StartCalendarInterval"]
        cis = ci if isinstance(ci, list) else [ci]
        def one(d):
            wd = {2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 1: "Пн", 0: "Вс"}
            w = wd.get(d.get("Weekday"), "") if "Weekday" in d else ""
            return f"{w} {d.get('Hour',0):02d}:{d.get('Minute',0):02d}".strip()
        return "расписание " + ", ".join(one(d) for d in cis)
    if plist.get("KeepAlive"):
        return "KeepAlive (демон)"
    if plist.get("WatchPaths"):
        return "по событию (WatchPaths)"
    return "—"


def _retired() -> set[str]:
    try:
        from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS
        return set(RETIRED_LABELS)
    except Exception:
        return set()


_LOCK_UNSET = object()


def build(*, lock_verdict=_LOCK_UNSET) -> dict:
    loaded = _launchctl()
    retired = _retired()
    installed = {p.stem: p for p in _LAUNCH_DIR.glob("com.spa.*.plist")} if _LAUNCH_DIR.is_dir() else {}
    labels = set(loaded) | set(installed) | retired
    # Замок читается ОДИН раз на сборку: все агенты судятся по одному снимку.
    # Вход, а не окружение: тест подаёт вердикт явно и не зависит от машины.
    if lock_verdict is _LOCK_UNSET:
        lock_verdict = _cycle_lock_verdict()

    agents = []
    for label in sorted(labels):
        short = label.replace("com.spa.", "")
        plist = {}
        if label in installed:
            try:
                plist = plistlib.loads(installed[label].read_bytes())
            except Exception:
                plist = {}
        is_loaded = label in loaded
        is_retired = label in retired
        reboot_safe = label in installed  # plist resident in ~/Library survives reboot
        problems = []
        notes: list[str] = []
        if is_retired and is_loaded:
            problems.append("RETIRED но ЗАГРУЖЕН (дубль/дрейф)")
        if is_loaded and not reboot_safe and not is_retired:
            problems.append("загружен, но НЕ переживёт reboot (нет plist в ~/Library)")
        if not is_loaded and not is_retired and label in installed:
            problems.append("в ~/Library, но НЕ загружен (drift)")
        le = loaded.get(label, {}).get("last_exit")
        _exit_problem, _exit_note = judge_last_exit(label, le, lock_verdict=lock_verdict)
        if _exit_problem:
            problems.append(_exit_problem)
        if _exit_note:
            notes.append(_exit_note)
        agents.append({
            "label": label,
            "short": short,
            "role": _ROLE.get(short, "other"),
            "schedule": _schedule(plist) if plist else ("—" if not is_loaded else "?"),
            "loaded": is_loaded,
            "pid": loaded.get(label, {}).get("pid"),
            "last_exit": le,
            "retired": is_retired,
            "reboot_safe": reboot_safe,
            "problems": problems,
            # Информация, а не тревога: исход назван вслух, `problem_count` не растёт.
            "notes": notes,
        })

    by_role: dict[str, int] = {}
    for a in agents:
        if not a["retired"]:
            by_role[a["role"]] = by_role.get(a["role"], 0) + 1
    problem_count = sum(1 for a in agents if a["problems"] and not a["retired"] or (a["retired"] and a["loaded"]))
    return {
        "model": "agent_registry",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_loaded": sum(1 for a in agents if a["loaded"]),
        "total_known": len(agents),
        "by_role": by_role,
        "problem_count": problem_count,
        "roles": ["infra", "allocation", "monitoring", "reporting", "research", "other"],
        "agents": agents,
    }


def main() -> int:
    reg = build()
    if "--print" in sys.argv:
        print(json.dumps(reg, ensure_ascii=False, indent=2)[:4000])
    dst = _REPO / "data" / "agent_registry.json"
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(reg, str(dst))
    except Exception:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"agent_registry: {reg['total_loaded']} loaded, {reg['problem_count']} problems → {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
