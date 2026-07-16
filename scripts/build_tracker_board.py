#!/usr/bin/env python3
"""build_tracker_board.py — единый обзор ВСЕХ карточек одним файлом (bootstrap).

Сканирует nimbalyst-local/tracker/*.md, парсит frontmatter (type/title/status/…) и пишет
nimbalyst-local/tracker/_BOARD.md: доска всех карточек со статусами + секция «ЖДЁТ ВЛАДЕЛЬЦА»
вверху. Чтобы любая сессия (и владелец в Nimbalyst) видела всё разом, не открывая 56 файлов —
директива owner 2026-07-16 «карточки все в одном месте, чтобы новое окно не было новым сотрудником».

Источник правды — сами карточки; _BOARD.md — производный индекс (регенерится оркестратором/по требованию).
Stdlib-only. Атомарная запись.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACKER = REPO / "nimbalyst-local" / "tracker"
OUT = TRACKER / "_BOARD.md"

# порядок и человекочитаемые имена типов
TYPE_ORDER = ["owner-decision", "inbox", "agent-task"]
TYPE_LABEL = {
    "owner-decision": "🧑‍⚖️ Owner Decisions (что нужно от владельца)",
    "inbox": "📥 Inbox (задания: Telegram / заметки / голос)",
    "agent-task": "🤖 Agent Tasks (что делает агент)",
}
# порядок статусов внутри типа (неизвестные — в конец)
STATUS_ORDER = [
    "needs-owner", "blocked", "in-progress", "backlog",
    "open", "ingested", "done", "owner-done",
]
# статусы, означающие «ждёт владельца» — выносим наверх
WAITING_OWNER = {"needs-owner"}


def parse_frontmatter(text: str) -> dict:
    """Минимальный парс YAML-frontmatter (плоские key: value + вложенный trackerStatus.type)."""
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    block = text[3:end]
    cur_top = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if indent == 0:
            cur_top = key
            if val:
                meta[key] = val
        elif cur_top == "trackerStatus":
            # trackerStatus.type → type
            meta[key] = val
    return meta


def card_type(meta: dict, name: str) -> str:
    t = meta.get("type")
    if t:
        return t
    # fallback по префиксу имени файла
    if name.startswith("owner-decision") or name.startswith("own-"):
        return "owner-decision"
    if name.startswith("inbox-"):
        return "inbox"
    if name.startswith("agent-"):
        return "agent-task"
    return "other"


def status_rank(s: str) -> int:
    try:
        return STATUS_ORDER.index(s)
    except ValueError:
        return len(STATUS_ORDER)


def atomic_write(path: Path, content: str) -> None:
    d = path.parent
    fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main() -> int:
    cards = []
    for p in sorted(TRACKER.glob("*.md")):
        if p.name == OUT.name:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        meta = parse_frontmatter(text)
        cards.append({
            "file": p.name,
            "type": card_type(meta, p.name),
            "title": meta.get("title", p.stem),
            "status": meta.get("status", "?"),
            "created": meta.get("created", ""),
            "priority": meta.get("priority", ""),
        })

    by_type: dict[str, list] = {}
    for c in cards:
        by_type.setdefault(c["type"], []).append(c)

    waiting = [c for c in cards if c["status"] in WAITING_OWNER]

    lines = []
    lines.append("# 📋 TRACKER BOARD — все карточки одним взглядом")
    lines.append("")
    lines.append("> Авто-генерится `scripts/build_tracker_board.py` из `nimbalyst-local/tracker/*.md`. "
                 "НЕ править вручную — правь карточки. Источник правды — карточки, это индекс (bootstrap).")
    lines.append(f">")
    lines.append(f"> Всего карточек: **{len(cards)}** · "
                 f"ждёт владельца: **{len(waiting)}**.")
    lines.append("")

    # секция «ждёт владельца» наверх
    lines.append("## 🔴 ЖДЁТ ВЛАДЕЛЬЦА (needs-owner)")
    lines.append("")
    if waiting:
        for c in sorted(waiting, key=lambda x: x["file"]):
            pr = f" · _{c['priority']}_" if c["priority"] else ""
            lines.append(f"- **{c['title']}**{pr}  ·  `{c['file']}`")
    else:
        lines.append("_Пусто — открытых решений на владельце нет._")
    lines.append("")

    # по типам
    ordered_types = TYPE_ORDER + [t for t in by_type if t not in TYPE_ORDER]
    for t in ordered_types:
        group = by_type.get(t)
        if not group:
            continue
        lines.append(f"## {TYPE_LABEL.get(t, t)}  ({len(group)})")
        lines.append("")
        group.sort(key=lambda x: (status_rank(x["status"]), x["file"]))
        cur_status = None
        for c in group:
            if c["status"] != cur_status:
                cur_status = c["status"]
                lines.append(f"### · {cur_status}")
            when = f" · {c['created']}" if c["created"] else ""
            lines.append(f"- {c['title']}  ·  `{c['file']}`{when}")
        lines.append("")

    content = "\n".join(lines) + "\n"
    atomic_write(OUT, content)
    print(f"wrote {OUT.relative_to(REPO)} — {len(cards)} cards, {len(waiting)} waiting-owner")
    return 0


if __name__ == "__main__":
    sys.exit(main())
