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

from spa_core.owner_queue import origin_view
from spa_core.owner_queue.queue import (TRACKER_DIR, Card, list_cards,
                                        load_card_text)
from spa_core.utils.atomic import atomic_save
from spa_core.utils.data_dir import own_data_dir

#: Карточка ещё НЕ взята в работу.
STARVING_STATUSES = ("new", "backlog")

#: Карточка ЧИСЛИТСЯ взятой. Это не то же самое, что «над ней работают»: статус ставит
#: сессия, а сессии здесь умирают регулярно, и снять статус за собой мёртвая не может.
#: Поэтому статус — не ответ, а вопрос: держит ли карточку кто-то ЖИВОЙ (см. `_claim_free`).
HELD_STATUSES = ("in-progress",)

#: Вердикты `check_card_claim`, при которых держателя НЕТ. `unchecked` сюда НЕ входит —
#: «не измерено» разбирается отдельно и fail-CLOSED (не измерили ⇒ считаем голодом,
#: назвав причину), потому что молчаливое «кто-то держит» — самое успокоительное из
#: возможных прочтений и ровно оно скрывало приказ владельца девять суток.
CLAIM_ABSENT = ("free", "stale")

DEFAULT_REF = "origin/main"
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


def cards_from_ref(tracker_dir=None, ref: str = DEFAULT_REF) -> list[Card]:
    """Карточки очереди в версии `ref` — с ТЕЛОМ и ПРИОРИТЕТОМ, а не только со статусом.

    Зачем вообще вторая копия: `nimbalyst-local/` в прод-дерево не возит НИКТО (автосинк
    берёт только `spa_core/` · `scripts/` · `tests/`), поэтому сторож, читающий очередь с
    диска, отвечает про КАТАЛОГ, а читается как ответ про ОЧЕРЕДЬ. Замер 04.09 на живом
    входе, `inbox-task-portfolio-cio-dynamic-capital-alloc`:

    | | прод-дерево | `origin/main` |
    |---|---|---|
    | `status` | `done` | `in-progress` |
    | `priority` | `high` | **`critical`** |
    | блок «УКАЗАНИЕ ВЛАДЕЛЬЦА … ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ» | **ОТСУТСТВУЕТ** | есть |

    Прод-копию закрыл 31.08 голый однострочник `python3 -c` в ходе массового закрытия;
    приказа владельца в ней нет ВООБЩЕ. Сторож, написанный РАДИ этой карточки, честно
    отвечал «голодающих приказов нет» — по своему контракту, читая ту копию, в которой
    приказа не существует.

    Разбор карточки не дублируется: тип, статус и приоритет резолвит единственный писатель
    этого правила — `queue.load_card_text`. `origin_view.OriginCard` здесь не годится, он
    несёт только статус и заголовок, а голод определяется ПРИОРИТЕТОМ и ТЕЛОМ.

    Ref не читается ⇒ ``origin_view.Unmeasured`` наружу: подставить пустой список значило бы
    сказать «на ref голода нет», не посмотрев, — тот самый fail-OPEN.
    """
    tdir = Path(tracker_dir) if tracker_dir else Path(TRACKER_DIR)
    root = origin_view.repo_root_of(tdir)
    rel = str(tdir.resolve().relative_to(root.resolve()))
    blobs = origin_view.snapshot(root, ref, rel)
    texts = origin_view.read_texts(root, blobs)
    return [load_card_text(text, f"{cid}.md", path=tdir / f"{cid}.md")
            for cid, text in sorted(texts.items())]


def _claim_verdict(card_id: str, tracker_dir=None, announce_path=None) -> tuple[str, str]:
    """Вердикт занятости карточки — ТЕМ ЖЕ кодом, что шаги 0a/0b (`check_card_claim`).

    → (`free` · `claimed` · `stale` · `unchecked`, причина словами).

    Второй экземпляр мерки живости разошёлся бы с первым молча (ADR-220, и проект уже
    трижды за это платил, #143–#145). Поэтому здесь не измерение, а ВЫЗОВ.

    ``announce_path`` передаётся ЯВНО и тем же значением, которым сторож пользуется сам.
    Без этого `check_card_claim` берёт журнал от СВОЕГО `data/`, а `data/` в git-worktree
    нет ПО ПОСТРОЕНИЮ (gitignore) — измеритель честно отвечает «журнала объявлений нет,
    занятость НЕ проверена», и весь ответ вырождается в `unchecked`. Замерено на этой же
    правке: из worktree вердикт был `unchecked`, из прод-дерева — `free`.

    Сбой самого измерителя — тоже `unchecked`, но с НАЗВАННОЙ причиной: «не измерено» без
    причины неотличимо от «нечем проверить сегодня» и глохнет ровно так же, как молчание.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ccc_for_starvation", Path(_REPO_ROOT) / "scripts" / "check_card_claim.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        kwargs = {}
        if tracker_dir:
            kwargs["tracker_dir"] = Path(tracker_dir)
        if announce_path is not None:
            kwargs["log"] = Path(announce_path)
        report = mod.gather(card_id, **kwargs)
        verdict = str(report["verdict"])
        why = "; ".join(str(u.get("reason") or "") for u in report.get("unmeasured") or [])
        return verdict, why
    except Exception as exc:  # noqa: BLE001 — измеритель мог упасть как угодно
        return "unchecked", f"измеритель занятости не отработал: {exc.__class__.__name__}: {exc}"


def _held_but_free(card: Card, claim_verdict) -> tuple[bool, str]:
    """Карточка ЧИСЛИТСЯ взятой — держит ли её кто-то живой? → (голод?, причина словами).

    Статус `in-progress` выводил карточку из-под сторожа НАВСЕГДА: достаточно один раз её
    «взять» и умереть. Замер 04.09: `inbox-task-portfolio-cio-dynamic-capital-alloc` стоит
    `in-progress` с 26.08 (`cycle-96657`), а вердикт занятости — `free`, «захватов не
    найдено, всё измерено». То есть статус говорит «в работе», а работать некому девять
    суток, и это ровно голод, просто под другим именем.
    """
    verdict, why = claim_verdict(Path(str(card.path)).stem)
    if verdict in CLAIM_ABSENT:
        return True, (f"статус `{card.status}` говорит «в работе», а держателя НЕТ: вердикт "
                      f"занятости `{verdict}` (измерен тем же кодом, что шаги 0a/0b)")
    if verdict == "unchecked":
        tail = f" — {why}" if why else ""
        return True, ("статус говорит «в работе», а занятость НЕ ИЗМЕРЕНА — fail-CLOSED: "
                      "молчаливое «кто-то держит» и есть то прочтение, которым приказ "
                      f"владельца скрывался девять суток{tail}")
    return False, ""


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
    announce_path=None, claim_verdict=None, source: str = "дерево",
) -> list[dict]:
    """Critical-карточки с приказом владельца старше `min_hours`, отсортированные от старейшей.

    ``announce_path`` — журнал объявлений для замера «сколько циклов прошло мимо».
    Не передан ⇒ поле `cycles_passed` равно ``None`` и читается как НЕ ИЗМЕРЕНО: параметр
    необязателен, потому что величина не является условием находки — голод определяется
    возрастом приказа, а циклы лишь показывают, НАСКОЛЬКО плотно мимо него ходили.

    ``claim_verdict`` — измеритель занятости (`card_id -> free|claimed|stale|unchecked`),
    ВХОД, а не окружение: без него статус `in-progress` голодом не считается вовсе, и это
    сказано в отчёте полем `held_check`, а не додумывается читателем. Умолчание в `main()` —
    `check_card_claim`, тот же код, что у шагов 0a/0b.

    ``source`` — из какой копии очереди пришла карточка («дерево» / `origin/main`). Едет в
    находку: у одного и того же приказа две копии могут расходиться по статусу, приоритету
    и наличию самого приказа, и «где мы это увидели» — часть ответа, а не украшение.
    """
    out: list[dict] = []
    for c in cards:
        if (c.priority or "").strip().lower() != "critical":
            continue
        status = (c.status or "").strip().lower()
        held_reason = ""
        if status in STARVING_STATUSES:
            pass                                   # ещё не взята — прежнее условие
        elif status in HELD_STATUSES and claim_verdict is not None:
            starving, held_reason = _held_but_free(c, claim_verdict)
            if not starving:
                continue
        else:
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
            "source": source,
            # Пустая строка = «карточка вообще не взята», а не «держателя проверяли и не нашли».
            "held_check": held_reason,
            "marker_date": marker_date,
            "age_hours": round(hours, 1),
            # «N циклов мимо» — дословное требование карточки-заказчика.
            # None = НЕ ИЗМЕРЕНО и печатается именно так, а не нулём.
            "cycles_passed": (cycles_since(marker_date, now, announce_path)
                              if announce_path is not None else None),
        })
    out.sort(key=lambda r: r["age_hours"], reverse=True)
    return out


def merge_findings(tree: list[dict], ref: list[dict]) -> list[dict]:
    """Находки двух копий очереди в один список — fail-CLOSED, по идентификатору карточки.

    Молчание требует, чтобы голода не увидела НИ ОДНА копия. Если одна копия голодает, а
    вторая нет, берётся ГОЛОДАЮЩАЯ: «в другом дереве эта карточка закрыта» приказ владельца
    не отменяет — ровно так он и пропал (закрытие 31.08 в прод-дереве, откуда на origin оно
    не уедет ничем).
    """
    by_id: dict[str, dict] = {}
    # Порядок значим: при находке в ОБЕИХ копиях побеждает версия с ref. Именно она несёт
    # приказ владельца и его приоритет; прод-копия того же приказа 04.09 не несла ВООБЩЕ.
    for f in [*ref, *tree]:
        by_id.setdefault(Path(f["path"]).stem, f)
    merged = list(by_id.values())
    merged.sort(key=lambda r: r["age_hours"], reverse=True)
    return merged


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
        # Копия НАЗЫВАЕТСЯ: у одного приказа две копии расходятся по статусу, приоритету и
        # наличию самого приказа — без источника читатель не найдёт то, что ему показали.
        src = f.get("source")
        where = f" [копия: {src}]" if src else ""
        lines.append(f"  - {f['title']} ({f['path']}): приказ от {f['marker_date']}, "
                      f"стоит {f['status']} уже {f['age_hours']:.1f}ч{tail}{where}")
        if f.get("held_check"):
            lines.append(f"      ↳ {f['held_check']}")
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
    ap.add_argument("--ref", default=DEFAULT_REF,
                    help=f"ref для сверки очереди (по умолчанию {DEFAULT_REF}); "
                         f"пустая строка — читать ТОЛЬКО дерево")
    args = ap.parse_args(argv)

    cards = list_cards(tracker_dir=args.tracker_dir)
    now = datetime.now(timezone.utc)
    data_base = (Path(args.data_dir) if args.data_dir
                 else own_data_dir(Path(_REPO_ROOT) / "data"))
    announce = data_base / ANNOUNCE_NAME

    def claim_verdict(card_id: str) -> tuple[str, str]:
        # Журнал объявлений — ТОТ ЖЕ, которым сторож меряет «сколько циклов мимо».
        # Два разных `data/` у двух половин одного ответа и есть способ получить
        # «не измерено» на измеримом.
        return _claim_verdict(card_id, tracker_dir=args.tracker_dir, announce_path=announce)

    tree_findings = starving_owner_orders(cards, now=now, min_hours=args.min_hours,
                                          announce_path=announce,
                                          claim_verdict=claim_verdict, source="дерево")
    ref_findings: list[dict] = []
    ref_error = None
    if args.ref:
        try:
            ref_cards = cards_from_ref(args.tracker_dir, ref=args.ref)
        except origin_view.Unmeasured as exc:
            ref_error = str(exc)
        else:
            ref_findings = starving_owner_orders(
                ref_cards, now=now, min_hours=args.min_hours, announce_path=announce,
                claim_verdict=claim_verdict, source=args.ref)
    findings = merge_findings(tree_findings, ref_findings)

    if not args.no_write:
        # Пустой отчёт пишется наравне с находкой: по его свежести читатель отличает
        # «голода нет» от «измерять было некому» — без него тишина означала бы и то, и другое.
        report = build_report(findings, args.min_hours, now)
        report["ref"] = args.ref or None
        # Третий исход отдельным полем: «ref не прочитан» ≠ «на ref голода нет».
        report["ref_unmeasured"] = ref_error
        written = write_report(report, data_base)
        if written is None:
            print("⚠️ отчёт сторожа голодания НЕ ЗАПИСАН — вердикт ниже верен, но следа "
                  "для владельца (дайджест) не осталось", file=sys.stderr)

    if ref_error is not None:
        print(f"❓ ОЧЕРЕДЬ НА `{args.ref}` НЕ ПРОЧИТАНА ({ref_error}) — вердикт ниже верен "
              f"про КАТАЛОГ этого дерева и НЕ верен про очередь: карточки, которых здесь "
              f"нет, не проверены ничем", file=sys.stderr)

    if args.json:
        print(json.dumps({"min_hours": args.min_hours, "ref": args.ref or None,
                          "ref_unmeasured": ref_error, "findings": findings},
                          ensure_ascii=False, indent=2))
    else:
        print(render(findings, args.min_hours))
    if findings:
        return 1
    # Голода не увидели — но если вторую копию очереди прочитать не удалось, «не найдено»
    # означает «не искали там, где приказ и живёт». Это не 0.
    return 2 if ref_error is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
