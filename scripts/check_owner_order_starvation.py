#!/usr/bin/env python3
"""scripts/check_owner_order_starvation.py — «критическая карточка с прямым приказом
владельца стоит `new`/`backlog` дольше суток».

**Зачем.** Замер 26.08 (карточка `inbox-critical-kartochka-goloda-et-4-dnya-pri-40-tsiklah`):
`inbox-task-portfolio-cio-dynamic-capital-alloc` несёт явное «УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-22:
ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ», приоритет `critical` — и простояла `new` четвёртый день при
40+ прошедших циклах. Причина структурная: шаг 0a (подъём осиротевшей работы) и поток находок
исполняются КАЖДЫМ циклом ПЕРЕД выбором из очереди, а при постоянной смертности сессий верх
очереди в порядке FIFO/приоритета не наступает никогда — и ни один сторож голодание не называл.

**Кому он это говорит — и почему одного адресата мало (цикл #422).** Единственным читателем
вердикта была САМА сессия цикла: обёртка `agent_orchestrator.sh` вклеивает вывод в промпт.
То есть сторож голодания очереди говорил ровно в тот механизм, который очередь и голодит, —
и ни во что больше. Сессии этого репозитория умирают регулярно (29.08 подряд #419, #421:
работа сделана, пуша нет), а мёртвая сессия промпт не читает: находка исчезала вместе с ней,
не оставив следа НИГДЕ. Поэтому вердикт теперь ещё и ЗАПИСЫВАЕТСЯ (`owner_order_starvation.json`),
а дневной дайджест несёт его владельцу — каналу, который смерть сессии не выключает.

**Что делает.** Детерминированно, только stdlib, без сети (единственная запись — свой отчёт,
атомарно):

1. Сканирует трекер (`spa_core.owner_queue.queue.list_cards`) на карточки с
   `priority: critical`, статусом из `STARVING_STATUSES` (`new`, `backlog` — то есть ещё не
   взятые в работу) и явным маркером прямого приказа владельца в теле: заголовок вида
   ``## УКАЗАНИЕ ВЛАДЕЛЬЦА <YYYY-MM-DD>`` или ``## ПРИКАЗ ВЛАДЕЛЬЦА <YYYY-MM-DD>``.
2. Считает возраст маркера от полуночи UTC той даты до `now` (UTC).
3. Карточка старше `--min-hours` (по умолчанию 24) — находка.
4. Считает, СКОЛЬКО ЦИКЛОВ прошло мимо этой карточки (карточка просила эту величину дословно:
   «N циклов мимо»): различимые ярлыки сессий в журнале объявлений `session_changes.jsonl`
   с момента приказа. Часы и циклы — РАЗНЫЕ величины: сутки простоя при одном прошедшем цикле
   и сутки при сорока — это две разные аварии, и вторую видно только по циклам.
   Журнала нет / не читается ⇒ `None` = НЕ ИЗМЕРЕНО, а не ноль (fail-CLOSED: «мимо не прошёл
   никто» — самое успокоительное из возможных значений, и выдумывать его запрещено).
5. Пишет отчёт `<data>/owner_order_starvation.json` — и при находке, и при её отсутствии.
   Пустой отчёт нужен не меньше: по его СВЕЖЕСТИ читатель отличает «голода нет» от
   «измерять было некому».

Не «критично + не взято» вообще: сигнал узкий и по объявленному владельцем приказу, а не по
любой critical-карточке (это отдельный, гораздо более шумный вопрос очерёдности приоритетов).

**Как это встроено в протокол (docs/ORCHESTRATOR_PROTOCOL.md, шаг 0a-голод):** проверка
идёт ДО шага 0a (подъём осиротевшей работы) и до разбора очереди — находка обязывает взять
голодающую карточку первой, кроме случая активной аварии/стоп-крана (это решает сам цикл,
скрипт такого не знает и не должна знать).

Код возврата: **0** — голодающих карточек нет; **1** — есть находки (fail-CLOSED — по
умолчанию считается голодом, если возраст не удалось измерить как заведомо свежий).
Запись отчёта на код возврата НЕ влияет: сорванная запись не имеет права превратить
находку в её отсутствие (и наоборот) — она сообщается отдельной строкой в stderr.
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
from spa_core.utils.atomic import atomic_save
from spa_core.utils.data_dir import own_data_dir

STARVING_STATUSES = ("new", "backlog")
DEFAULT_MIN_HOURS = 24.0

#: Отчёт сторожа. Имя фиксировано: его читает дневной дайджест (владелец) — единственный
#: канал, который смерть сессии не выключает.
REPORT_NAME = "owner_order_starvation.json"

#: Журнал объявлений — по нему меряется «сколько циклов прошло мимо».
ANNOUNCE_NAME = "session_changes.jsonl"

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


def cycles_since(marker_date: str, now: datetime, announce_path) -> int | None:
    """Сколько РАЗЛИЧИМЫХ сессий объявляли работу с полуночи UTC даты приказа.

    Это и есть «N циклов мимо» из карточки-заказчика. Величина считается по журналу
    объявлений, а не по журналу цикла: объявление обязан оставить КАЖДЫЙ цикл (§3.4), и
    это единственный след, который переживает смерть сессии.

    ``None`` — измерить не удалось (журнала нет, не читается, дата приказа не разбирается).
    Ноль возвращается ТОЛЬКО когда журнал прочитан и в нём действительно никого нет:
    «мимо не прошёл никто» — самое успокоительное из значений, и подставлять его вместо
    неизмеренного запрещено (тот же fail-OPEN, из-за которого приказ простоял четверо суток).
    """
    try:
        since = datetime.strptime(marker_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    try:
        text = Path(announce_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    labels: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # Битая строка — не повод объявить неизмеримым весь журнал; она просто
            # не даёт свидетельства о цикле, и счёт от этого только занижается.
            continue
        if not isinstance(rec, dict):
            continue
        ts = str(rec.get("ts") or "")
        label = str(rec.get("session") or "").strip()
        if not label:
            continue
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= since and when <= now:
            labels.add(label)
    return len(labels)


def build_report(findings: list[dict], min_hours: float, now: datetime) -> dict:
    """Отчёт для читателя, который в момент замера не работал (владелец через дайджест)."""
    return {
        "generated_at": now.isoformat(),
        "min_hours": min_hours,
        "starving_count": len(findings),
        "findings": findings,
    }


def write_report(report: dict, data_dir=None) -> str | None:
    """Записать отчёт атомарно (инв. #5). Возвращает путь либо None, если запись сорвалась.

    Отказ записи НЕ меняет вердикт: сторож, у которого не получилось оставить след, обязан
    сказать об этом отдельно, а не превратить находку в её отсутствие.
    """
    base = Path(data_dir) if data_dir else own_data_dir(Path(_REPO_ROOT) / "data")
    path = base / REPORT_NAME
    try:
        atomic_save(report, str(path))
    except (OSError, ValueError, TypeError):
        return None
    return str(path)


def starving_owner_orders(
    cards: list[Card], now: datetime, min_hours: float = DEFAULT_MIN_HOURS,
    announce_path=None,
) -> list[dict]:
    """Critical-карточки с приказом владельца старше `min_hours`, отсортированные от старейшей.

    ``announce_path`` — журнал объявлений для замера «сколько циклов прошло мимо».
    Не передан ⇒ поле `cycles_passed` равно ``None`` и читается как НЕ ИЗМЕРЕНО: параметр
    необязателен, потому что величина не является условием находки — голод определяется
    возрастом приказа, а циклы лишь показывают, НАСКОЛЬКО плотно мимо него ходили.
    """
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
            # «N циклов мимо» — дословное требование карточки-заказчика.
            # None = НЕ ИЗМЕРЕНО и печатается именно так, а не нулём.
            "cycles_passed": (cycles_since(marker_date, now, announce_path)
                              if announce_path is not None else None),
        })
    out.sort(key=lambda r: r["age_hours"], reverse=True)
    return out


def render(findings: list[dict], min_hours: float) -> str:
    if not findings:
        return f"✅ голодающих critical-приказов владельца (>{min_hours:g}ч) не найдено"
    lines = [f"🚨 ГОЛОДАЮЩИЙ ПРИКАЗ ВЛАДЕЛЬЦА (critical, старше {min_hours:g}ч, "
             f"взять ПЕРВОЙ — до шага 0a, кроме активной аварии/стоп-крана):"]
    for f in findings:
        cycles = f.get("cycles_passed")
        # Ноль циклов и НЕ ИЗМЕРЕНО — разные утверждения, и склеивать их нельзя:
        # «мимо никто не проходил» оправдывает простой, «мерить было нечем» — нет.
        tail = (f", мимо прошло циклов: {cycles}" if isinstance(cycles, int)
                else ", циклов мимо: НЕ ИЗМЕРЕНО")
        lines.append(f"  - {f['title']} ({f['path']}): приказ от {f['marker_date']}, "
                      f"стоит {f['status']} уже {f['age_hours']:.1f}ч{tail}")
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
    ap.add_argument("--data-dir", default=None,
                    help="каталог состояния для отчёта (по умолчанию — SPA_DATA_DIR либо data/)")
    ap.add_argument("--no-write", action="store_true",
                    help="не писать отчёт (вердикт только в stdout)")
    args = ap.parse_args(argv)

    cards = list_cards(tracker_dir=args.tracker_dir)
    now = datetime.now(timezone.utc)
    data_base = (Path(args.data_dir) if args.data_dir
                 else own_data_dir(Path(_REPO_ROOT) / "data"))
    findings = starving_owner_orders(cards, now=now, min_hours=args.min_hours,
                                     announce_path=data_base / ANNOUNCE_NAME)

    if not args.no_write:
        # Пустой отчёт пишется наравне с находкой: по его свежести читатель отличает
        # «голода нет» от «измерять было некому» — без него тишина означала бы и то, и другое.
        written = write_report(build_report(findings, args.min_hours, now), data_base)
        if written is None:
            print("⚠️ отчёт сторожа голодания НЕ ЗАПИСАН — вердикт ниже верен, но следа "
                  "для владельца (дайджест) не осталось", file=sys.stderr)

    if args.json:
        print(json.dumps({"min_hours": args.min_hours, "findings": findings},
                          ensure_ascii=False, indent=2))
    else:
        print(render(findings, args.min_hours))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
