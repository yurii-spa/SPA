#!/usr/bin/env python3
"""scripts/check_owner_order_starvation.py — «критическая карточка с прямым приказом
владельца стоит `new`/`backlog` дольше суток».

**Зачем.** Замер 26.08 (карточка `inbox-critical-kartochka-goloda-et-4-dnya-pri-40-tsiklah`):
`inbox-task-portfolio-cio-dynamic-capital-alloc` несёт явное «УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-22:
ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ», приоритет `critical` — и простояла `new` четвёртый день при
40+ прошедших циклах. Причина структурная: шаг 0a (подъём осиротевшей работы) и поток находок
исполняются КАЖДЫМ циклом ПЕРЕД выбором из очереди, а при постоянной смертности сессий верх
очереди в порядке FIFO/приоритета не наступает никогда — и ни один сторож голодание не называл.

**Что делает.** Детерминированно, read-only, только stdlib, без сети:

1. Сканирует трекер (`spa_core.owner_queue.queue.list_cards`) на карточки с
   `priority: critical`, статусом из `STARVING_STATUSES` (`new`, `backlog` — то есть ещё не
   взятые в работу) и явным маркером прямого приказа владельца в теле: заголовок вида
   ``## УКАЗАНИЕ ВЛАДЕЛЬЦА <YYYY-MM-DD>`` или ``## ПРИКАЗ ВЛАДЕЛЬЦА <YYYY-MM-DD>``.
2. Считает возраст маркера от полуночи UTC той даты до `now` (UTC).
3. Карточка старше `--min-hours` (по умолчанию 24) — находка.

Не «критично + не взято» вообще: сигнал узкий и по объявленному владельцем приказу, а не по
любой critical-карточке (это отдельный, гораздо более шумный вопрос очерёдности приоритетов).

**Как это встроено в протокол (docs/ORCHESTRATOR_PROTOCOL.md, шаг 0a-голод):** проверка
идёт ДО шага 0a (подъём осиротевшей работы) и до разбора очереди — находка обязывает взять
голодающую карточку первой, кроме случая активной аварии/стоп-крана (это решает сам цикл,
скрипт такого не знает и не должна знать).

Код возврата: **0** — голодающих карточек нет; **1** — есть находки (fail-CLOSED — по
умолчанию считается голодом, если возраст не удалось измерить как заведомо свежий).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.owner_queue.queue import Card, list_cards

STARVING_STATUSES = ("new", "backlog")
DEFAULT_MIN_HOURS = 24.0

# Заголовок вида "## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-22 ...` или "## ПРИКАЗ ВЛАДЕЛЬЦА ...".
_ORDER_MARKER_RE = re.compile(
    r"^\s*#{1,3}\s*(?:УКАЗАНИЕ|ПРИКАЗ)\s+ВЛАДЕЛЬЦА\b.*?(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE | re.MULTILINE,
)


def find_order_marker(body: str) -> str | None:
    """Дата (YYYY-MM-DD) первого маркера прямого приказа владельца в теле карточки, либо None."""
    m = _ORDER_MARKER_RE.search(body or "")
    return m.group(1) if m else None


def age_hours(marker_date: str, now: datetime) -> float | None:
    """Часы от полуночи UTC даты маркера до `now`. None — дата не разбирается (fail-CLOSED
    на стороне вызывающего: недоступный возраст не должен читаться как «свежий»)."""
    try:
        marker = datetime.strptime(marker_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (now - marker).total_seconds() / 3600.0


def starving_owner_orders(
    cards: list[Card], now: datetime, min_hours: float = DEFAULT_MIN_HOURS,
) -> list[dict]:
    """Critical-карточки с приказом владельца старше `min_hours`, отсортированные от старейшей."""
    out: list[dict] = []
    for c in cards:
        if (c.priority or "").strip().lower() != "critical":
            continue
        if (c.status or "").strip().lower() not in STARVING_STATUSES:
            continue
        marker_date = find_order_marker(c.body)
        if marker_date is None:
            continue
        hours = age_hours(marker_date, now)
        if hours is None or hours < min_hours:
            continue
        out.append({
            "path": str(c.path),
            "title": c.title,
            "status": c.status,
            "marker_date": marker_date,
            "age_hours": round(hours, 1),
        })
    out.sort(key=lambda r: r["age_hours"], reverse=True)
    return out


def render(findings: list[dict], min_hours: float) -> str:
    if not findings:
        return f"✅ голодающих critical-приказов владельца (>{min_hours:g}ч) не найдено"
    lines = [f"🚨 ГОЛОДАЮЩИЙ ПРИКАЗ ВЛАДЕЛЬЦА (critical, старше {min_hours:g}ч, "
             f"взять ПЕРВОЙ — до шага 0a, кроме активной аварии/стоп-крана):"]
    for f in findings:
        lines.append(f"  - {f['title']} ({f['path']}): приказ от {f['marker_date']}, "
                      f"стоит {f['status']} уже {f['age_hours']:.1f}ч")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only проверка: критическая карточка с явным приказом владельца, "
                    "не взятая в работу дольше --min-hours. Сети не касается.")
    ap.add_argument("--tracker-dir", default=None, help="каталог трекера (по умолчанию — "
                    "разрешаемый queue.TRACKER_DIR)")
    ap.add_argument("--min-hours", type=float, default=DEFAULT_MIN_HOURS,
                    help=f"порог голодания в часах (по умолчанию {DEFAULT_MIN_HOURS:g})")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    cards = list_cards(tracker_dir=args.tracker_dir)
    now = datetime.now(timezone.utc)
    findings = starving_owner_orders(cards, now=now, min_hours=args.min_hours)

    if args.json:
        print(json.dumps({"min_hours": args.min_hours, "findings": findings},
                          ensure_ascii=False, indent=2))
    else:
        print(render(findings, args.min_hours))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
