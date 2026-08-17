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

import argparse
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACKER = REPO / "nimbalyst-local" / "tracker"
OUT = TRACKER / "_BOARD.md"

# Один читатель типа карточки на оба инструмента. Вызванный как `python3 scripts/...`,
# скрипт получает sys.path[0] = scripts/ и корня репозитория на пути НЕТ (ровно так в CI
# умер перевод алертов, цикл #111) — поэтому корень СВОЕГО дерева добавляем явно.
# Импорт намеренно НЕ обёрнут в try: своя копия правила расхождения типов — это и есть
# дефект, который здесь чинится (доска знала обе формы, CLI только вложенную ⇒ три вопроса
# владельцу были невидимы в его же очереди). Сломанный импорт обязан быть слышен.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from spa_core.owner_queue.queue import load_card_text, resolve_tracker_type  # noqa: E402

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
# статусы, при которых работа закрыта ⇒ забытый claimed_by не считается занятостью
# (та же таблица, что в scripts/check_card_claim.py — карточку никто не «держит» после done)
TERMINAL_STATUSES = {"done", "ingested", "owner-done"}


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
    """Тип карточки — через ОБЩИЙ с CLI резолвер (см. `resolve_tracker_type`).

    `parse_frontmatter` выше уже сводит `trackerStatus.type` в плоский `type`, поэтому
    резолверу приходит форма, которую он понимает наравне с вложенной.
    """
    return resolve_tracker_type(meta, name) or "other"


def card_title(text: str, path: Path) -> str:
    """Название карточки — общим с CLI разбором; имя файла только как последний рубеж."""
    try:
        return load_card_text(text, path.name, path=path).title or path.stem
    except Exception:  # noqa: BLE001 — битая карточка не имеет права уронить всю доску
        return path.stem


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


def collect_cards(tracker: Path, out_name: str = "_BOARD.md") -> list[dict]:
    """Карточки на диске — ЕДИНСТВЕННЫЙ источник правды доски.

    Вынесено из `main()`, чтобы у сверки (`--check`) и у сборки был ОДИН читатель диска:
    вторая копия правила «как читается статус» — ровно тот дефект, из-за которого доска
    и разъехалась с карточками (замер 17.08: три расхождения на 508 карточек).
    """
    cards = []
    for p in sorted(tracker.glob("*.md")):
        if p.name == out_name:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        meta = parse_frontmatter(text)
        status = meta.get("status", "?")
        holder = (meta.get("claimed_by") or "").strip()
        cards.append({
            "file": p.name,
            "type": card_type(meta, p.name),
            # Название — через ОБЩИЙ с CLI разбор (`load_card_text` → `resolve_card_title`):
            # у карточек, объявленных плоской формой, названия во frontmatter нет — оно стоит
            # `#`-заголовком тела, и доска печатала слаг файла (замер #183). Отдельной копии
            # «где лежит название» здесь намеренно НЕТ: вторая копия правила разбора — это и
            # есть дефект, за который проект уже платил вопросами владельца (#143–#145).
            "title": card_title(text, p),
            "status": status,
            "created": meta.get("created", ""),
            "priority": meta.get("priority", ""),
            # Занятость видна прямо на доске: две сессии 30.07 взяли одну карточку, потому что
            # «кто её держит» не было видно нигде (карточка agent-card-claim-collision-guard).
            "claimed_by": holder if status not in TERMINAL_STATUSES else "",
            "claimed_at": (meta.get("claimed_at", "") or "").strip(),
        })
    return cards


def render_board(cards: list[dict], now: datetime | None = None) -> str:
    """Текст доски. `now` — ВХОД, а не окружение (правило про время в тестах).

    Доска ОБЯЗАНА называть свою дату: она производна и может отстать от карточек, а §1
    `CLAUDE.md` велит читать её ПЕРВОЙ. Читатель, который не видит отметки сборки, не может
    отличить свежий индекс от вчерашнего — ровно так дважды 17.08 брались закрытые карточки.
    """
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    by_type: dict[str, list] = {}
    for c in cards:
        by_type.setdefault(c["type"], []).append(c)

    waiting = [c for c in cards if c["status"] in WAITING_OWNER]
    claimed = [c for c in cards if c["claimed_by"]]

    lines = []
    lines.append("# 📋 TRACKER BOARD — все карточки одним взглядом")
    lines.append("")
    lines.append("> Авто-генерится `scripts/build_tracker_board.py` из `nimbalyst-local/tracker/*.md`. "
                 "НЕ править вручную — правь карточки. Источник правды — карточки, это индекс (bootstrap).")
    lines.append(">")
    lines.append(f"> {BUILT_AT_PREFIX}{stamp} · сверка с карточками: "
                 "`python3 scripts/build_tracker_board.py --check` (сторож "
                 "`spa_core/tests/test_tracker_board_matches_cards.py`).")
    lines.append(">")
    lines.append(f"> Всего карточек: **{len(cards)}** · "
                 f"ждёт владельца: **{len(waiting)}** · занято сессиями: **{len(claimed)}**.")
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

    # занятые карточки — чтобы «эту уже кто-то взял» было видно ДО начала работы.
    # Ниже секции владельца: его очередь всегда первая, занятость — служебный слой агентов.
    if claimed:
        lines.append("## 🔒 ЗАНЯТЫ СЕССИЯМИ (claimed_by)")
        lines.append("")
        lines.append("> Ставится `scripts/check_card_claim.py claim`, снимается `release` "
                     "(и не действует после `done`/`ingested`). Перед взятием карточки — "
                     "`check_card_claim.py check <карточка>`.")
        lines.append("")
        for c in sorted(claimed, key=lambda x: x["file"]):
            when = f" · с {c['claimed_at']}" if c["claimed_at"] else ""
            lines.append(f"- **{c['title']}** — держит `{c['claimed_by']}`{when}  ·  `{c['file']}`")
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
            lock = f" · 🔒 `{c['claimed_by']}`" if c["claimed_by"] else ""
            lines.append(f"- {c['title']}  ·  `{c['file']}`{when}{lock}")
        lines.append("")

    return "\n".join(lines) + "\n"


# --- сверка «доска ↔ карточки» --------------------------------------------------------
# Доска — производный индекс, но §1 CLAUDE.md велит читать её ПЕРВОЙ и «не открывать 56
# файлов». Значит она обязана СОВПАДАТЬ с frontmatter карточек; расхождение — не косметика,
# а неверный вход каждой сессии. 17.08 замерено 3 расхождения на 508 карточек (одна карточка
# `done` числилась `new`, две отсутствовали вовсе) — и по ним дважды бралась закрытая работа.

BUILT_AT_PREFIX = "Собрана: "
_BOARD_ROW = re.compile(r"^- .*?`([^`]+\.md)`")
_BOARD_STATUS_HEADING = re.compile(r"^### · (.+)$")


def board_status_map(board_text: str) -> dict[str, str]:
    """Что доска УТВЕРЖДАЕТ о статусе каждой карточки: {имя файла: статус}.

    Читается ровно то, что видит человек — строки под заголовками `### · <статус>`.
    Секции «ждёт владельца» / «заняты сессиями» — дубликаты тех же карточек без своего
    заголовка статуса; они намеренно пропускаются (`cur = None` на любом `## `).
    """
    out: dict[str, str] = {}
    cur: str | None = None
    for line in board_text.splitlines():
        if line.startswith("## "):
            cur = None
            continue
        m = _BOARD_STATUS_HEADING.match(line)
        if m:
            cur = m.group(1).strip()
            continue
        if cur is None:
            continue
        m = _BOARD_ROW.match(line)
        if m:
            out[m.group(1)] = cur
    return out


def board_drift(tracker: Path, out_name: str = "_BOARD.md") -> list[tuple[str, str, str]]:
    """Расхождения доски с карточками: [(файл, статус на доске, статус в frontmatter)].

    Fail-CLOSED: отсутствующая доска — расхождение по КАЖДОЙ карточке, а не «нечего сверять».
    """
    board_path = tracker / out_name
    claimed = board_status_map(board_path.read_text(encoding="utf-8")) if board_path.exists() else {}
    actual = {c["file"]: c["status"] for c in collect_cards(tracker, out_name)}
    drift = []
    for name in sorted(set(claimed) | set(actual)):
        said = claimed.get(name, "<НЕТ НА ДОСКЕ>")
        real = actual.get(name, "<НЕТ КАРТОЧКИ>")
        if said != real:
            drift.append((name, said, real))
    return drift


def main(argv=None) -> int:
    # argv=None ⇒ пустой список, а НЕ sys.argv: `main()` вызывают из кода
    # (`orchestrator_queue._rebuild_board`, тесты), где sys.argv принадлежит чужой программе.
    args = _parse(argv)

    tracker = Path(args.tracker_dir) if args.tracker_dir else TRACKER
    out = tracker / OUT.name if args.tracker_dir else OUT

    if args.check:
        drift = board_drift(tracker, out.name)
        if drift:
            print(f"ДОСКА РАСХОДИТСЯ С КАРТОЧКАМИ: {len(drift)}", file=sys.stderr)
            for name, said, real in drift:
                print(f"  {name}: доска={said!r} · карточка={real!r}", file=sys.stderr)
            print("Починка: python3 scripts/build_tracker_board.py "
                  "(статусы карточек НЕ трогать — инвариант 14).", file=sys.stderr)
            return 1
        print(f"OK: доска совпадает с карточками ({len(collect_cards(tracker, out.name))} карточек)")
        return 0

    cards = collect_cards(tracker, out.name)
    content = render_board(cards)
    atomic_write(out, content)
    # Доска может быть перенацелена на другой каталог (`--tracker-dir`, песочница теста) —
    # тогда её пути нет внутри репозитория. Статусная СТРОКА не имеет права ронять сборку:
    # файл уже записан, и падение здесь выглядело бы как «доска не собралась».
    try:
        where = out.relative_to(REPO)
    except ValueError:
        where = out
    waiting = [c for c in cards if c["status"] in WAITING_OWNER]
    claimed = [c for c in cards if c["claimed_by"]]
    print(f"wrote {where} — {len(cards)} cards, "
          f"{len(waiting)} waiting-owner, {len(claimed)} claimed")
    return 0


def _parse(argv):
    p = argparse.ArgumentParser(description="Собрать/сверить _BOARD.md из карточек трекера.")
    p.add_argument("--tracker-dir", default=None,
                   help="каталог карточек (по умолчанию — трекер СВОЕГО дерева)")
    p.add_argument("--check", action="store_true",
                   help="не писать, а СВЕРИТЬ доску с frontmatter карточек; расхождение ⇒ код 1")
    return p.parse_args([] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
