"""Plain-language system status summary for the Telegram /status command.

Gathers, defensively (each block fail-safe), a human-readable snapshot:
  1. Агенты — сколько LaunchAgent'ов загружено + CRITICAL из agent_health.
  2. Автономные сессии — сколько живых claude-процессов.
  3. Карточки-очереди — счётчики по статусам (Owner Decisions + Inbox).
  4. Свежесть памяти — когда обновлялись STATE.md и SYSTEM_BRIEFING.md.

stdlib-only + owner_queue. Returns HTML (для parse_mode=HTML). Никогда не бросает.
"""

from __future__ import annotations

import html
import json
import subprocess
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _age(path: Path) -> str:
    try:
        h = (time.time() - path.stat().st_mtime) / 3600.0
        if h < 1:
            return f"{int(h * 60)}м назад"
        if h < 48:
            return f"{h:.0f}ч назад"
        return f"{h / 24:.0f}д назад"
    except Exception:
        return "?"


def _agents_block() -> str:
    try:
        out = subprocess.run(
            ["bash", "-lc", "launchctl list | grep -c com.spa"],
            capture_output=True, text=True, timeout=10,
        )
        loaded = out.stdout.strip() or "?"
    except Exception:
        loaded = "?"
    crit = None
    try:
        d = json.loads((_REPO / "data" / "agent_health.json").read_text(encoding="utf-8"))
        crit = d.get("critical_count")
        if crit is None:
            agents = d.get("agents") or d.get("checks") or []
            if isinstance(agents, list):
                crit = sum(1 for a in agents if str(a.get("status", "")).upper() in ("CRIT", "CRITICAL"))
    except Exception:
        crit = None
    icon = "✅" if crit == 0 else ("⚠️" if crit else "❔")
    crit_txt = f", CRITICAL: {crit}" if crit is not None else ""
    return f"{icon} <b>Агенты:</b> загружено {html.escape(str(loaded))}{crit_txt}"


def _sessions_block() -> str:
    try:
        out = subprocess.run(
            ["bash", "-lc", "ps -Ao command | grep -iE 'claude(\\.exe)? (--resume|-p |Выполни)' | grep -v grep | wc -l"],
            capture_output=True, text=True, timeout=10,
        )
        n = out.stdout.strip() or "?"
    except Exception:
        n = "?"
    return f"🧠 <b>Живые claude-сессии:</b> {html.escape(str(n))}"


def _cards_block() -> str:
    try:
        from spa_core.owner_queue.queue import list_cards

        od = list_cards(tracker_type="owner-decision")
        inb = list_cards(tracker_type="inbox")

        def counts(cards):
            c: dict = {}
            for card in cards:
                c[card.status] = c.get(card.status, 0) + 1
            return c

        oc, ic = counts(od), counts(inb)
        od_txt = " · ".join(f"{k}:{v}" for k, v in sorted(oc.items())) or "нет"
        ic_txt = " · ".join(f"{k}:{v}" for k, v in sorted(ic.items())) or "нет"
        return f"🗂 <b>Owner Decisions:</b> {html.escape(od_txt)}\n📥 <b>Inbox:</b> {html.escape(ic_txt)}"
    except Exception:
        return "🗂 <b>Карточки:</b> (не удалось прочитать)"


def _freshness_block() -> str:
    state = _age(_REPO / "docs" / "STATE.md")
    brief = _age(_REPO / "docs" / "SYSTEM_BRIEFING.md")
    return f"🕒 <b>STATE.md:</b> {state} · <b>SYSTEM_BRIEFING:</b> {brief}"


def build_status_summary() -> str:
    """Assemble the full /status message (HTML). Each block is independently fail-safe."""
    blocks = []
    for fn in (_agents_block, _sessions_block, _cards_block, _freshness_block):
        try:
            blocks.append(fn())
        except Exception:
            blocks.append("(блок недоступен)")
    return "📊 <b>Статус SPA</b>\n" + "\n".join(blocks)
