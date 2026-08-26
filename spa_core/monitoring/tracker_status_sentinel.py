#!/usr/bin/env python3
"""Сторож переходов статусов в трекере — «этот переход кто-нибудь объяснил?».

Авария, ради которой он написан (карточка ``inbox-statusy-kartochek-vladeltsa-perepisalis``,
цикл #171, 2026-08-09 00:25 UTC): три карточки owner-gate сайта одновременно сменили
``status:`` сами. Живой вопрос владельцу (``…owner-gat-3``) стал ``ingested`` — то есть
**закрылся без ответа владельца** и исчез из очереди ``needs-owner``; уже разобранный
ответ (``…-2``) зеркально вернулся в очередь как неотвеченный. Тела карточек целы,
переписаны ровно строки ``status:``. Ни один сторож не сказал ни слова.

Вопрос, на который отвечает ИМЕННО этот сторож
------------------------------------------------------------------------------
| Вопрос | Кто отвечает | Что НЕ проверяет |
|---|---|---|
| Совпадает ли трекер дерева с origin? | ``scripts/check_tracker_drift.py`` | КТО и КОГДА менял |
| Кто перевёл карточку? | ``owner_queue.status_audit`` | писателей вне нашего кода |
| **Этот переход кто-нибудь объяснил?** | **этот модуль** | причину и правоту перехода |

Журнал аудита знает имя писателя, но только своего. Сторож имени не знает — зато видит
ЛЮБОГО: он сравнивает снимок статусов с предыдущим и требует, чтобы каждый переход был
покрыт записью журнала. Переход без записи — **неатрибутированный**, и это находка,
а не фон. Немоту (её карточка и называет главной опасностью) это закрывает по построению:
неизвестный писатель журнал не ведёт, значит его работа видна именно как «необъяснённое».

Тяжесть перехода — по цене ошибки, а не по частоте
------------------------------------------------------------------------------
* ``needs-owner`` → что угодно, кроме owner-only статусов — **CRITICAL**: так вопрос
  владельцу исчезает из очереди, ровно та потеря, что случилась 09.08;
* → ``owner-done`` / ``owner-accepted`` без записи — **CRITICAL**: инвариант #14
  (закрывает только владелец) проверяется в писателе, и обход писателя обязан быть
  слышен для ОБОИХ статусов, а не только для терминального;
* остальные неатрибутированные — **WARN**: подозрительно, но вопрос владельца не теряется.

Два источника объяснения, и второй нужен по построению
------------------------------------------------------------------------------
Журнал аудита живёт в ``data/`` и в git НЕ ПОПАДАЕТ (``.gitignore``: ``data/**/*.jsonl``),
а карточки — попадают. Протокол §3.4 требует работать из ОТДЕЛЬНОГО рабочего дерева,
поэтому законное закрытие вопроса владельца приезжало в прод-дерево без записи о себе,
и сторож называл его ``CRITICAL: неатрибутированный уход из needs-owner`` — теми самыми
словами, которые означают «вопрос владельца закрыли без владельца». Каждый раз, а не
иногда: ровно так сторожа глохнут (замер 17.08 воспроизведён дословно).

Решение владельца 2026-08-23, вариант 1 (ADR-129): **след перехода едет в самой
карточке**. Поэтому объяснений два, и порядок их таков:

1. запись журнала этого дерева (знает pid, команду, дерево — для разбора);
2. след во frontmatter карточки (``status_trail``) — то, что пережило доставку.

Чего это НЕ лечит и сказано вслух: тот, кто правит ``status:`` руками, может дописать
и след. Файловый сторож такой подделки не различит НИКОГДА — предмет и доказательство
лежат в одном файле. Немого писателя БЕЗ следа он ловит по-прежнему, и обе стороны
закреплены тестом ``test_status_trail_travels_with_card.py``.

Fail-CLOSED: нет предыдущего снимка / трекер не прочитан ⇒ вердикт ``UNCHECKED`` (код 2),
а не «нарушений не найдено». «Не измерено» никогда не значит «в порядке».

Коды возврата: 0 — OK · 1 — WARN-находки · 2 — CRITICAL либо не измерено.
Только stdlib. LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Optional

from spa_core.owner_queue.queue import ATTRIBUTION_CRITICAL_STATUSES, OWNER_ONLY_STATUSES
from spa_core.owner_queue.status_audit import read_audit, read_status, trail_explains
from spa_core.utils.atomic import atomic_save

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRACKER_REL = os.path.join("nimbalyst-local", "tracker")
SNAPSHOT_REL = os.path.join("data", "tracker_status_snapshot.json")
REPORT_REL = os.path.join("data", "tracker_status_sentinel.json")

#: Запас на рассинхрон часов и на запись, сделанную за секунды до снимка. Больше запас —
#: больше шанс, что СТАРАЯ запись журнала «объяснит» новый переход, поэтому он мал.
SLACK = dt.timedelta(minutes=5)

#: Статус, из которого молчаливый уход = потерянный вопрос владельцу.
OWNER_WAITING = "needs-owner"
#: Статус, который по инварианту #14 ставит только владелец.
OWNER_ONLY = "owner-done"
#: ВСЕ статусы, которые вправе поставить только владелец. С #350 их два: к `owner-done`
#: добавился НЕтерминальный `owner-accepted` («принято — беру в работу»).
#:
#: Импорт ЖЁСТКИЙ, без страховки `try/except`, и это осознанно: страховка молча свела бы
#: перечень к одному члену — то есть сторож перестал бы кричать ровно о НОВОМ статусе,
#: сохранив зелёный вид. Ронять модуль тут нечем: `status_audit` из того же пакета уже
#: импортируется жёстко строкой выше, и если пакет недоступен, сторож не работает вовсе.

VERDICT_OK = "OK"
VERDICT_FINDINGS = "FINDINGS"
VERDICT_UNCHECKED = "UNCHECKED"

MISSING = "(нет)"  # карточки нет либо в ней нет строки status:


def snapshot_statuses(tracker_dir: str | Path) -> tuple[dict, list[str]]:
    """Статусы всех карточек каталога + список нечитаемых файлов.

    Нечитаемый файл — НЕ пустое значение: подменять его на ``(нет)`` значило бы выдать
    «не смогли прочитать» за «статуса не было» и родить фантомный переход.
    """
    d = Path(tracker_dir)
    if not d.is_dir():
        return {}, [f"каталог трекера не найден: {d}"]
    statuses: dict = {}
    unreadable: list[str] = []
    for p in sorted(d.glob("*.md")):
        try:
            p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{p.name}: {exc}")
            continue
        statuses[p.name] = read_status(p) or MISSING
    return statuses, unreadable


def _parse_ts(value) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def _severity(old: str, new: str) -> str:
    # Приход в ЛЮБОЙ закрывающий статус МИМО ПИСАТЕЛЯ обязан быть слышен одинаково громко.
    #
    # Читается ATTRIBUTION_CRITICAL_STATUSES, а не OWNER_ONLY_STATUSES: после ADR-144 второй
    # сузился до одного имени (агенту разрешено ЗАКРЫВАТЬ карточки), и сторож, оставшийся на
    # нём, замолчал бы ровно о `owner-done` — самом терминальном из всех. Вопрос сторожа не
    # «кому МОЖНО», а «ОСТАЛАСЬ ЛИ ЗАПИСЬ»: след — единственное, чем закрытие отличается от
    # пропажи вопроса, и рука тут ни при чём (авария #350 была рукой ВЛАДЕЛЬЦА).
    if new in ATTRIBUTION_CRITICAL_STATUSES:
        return "CRITICAL"
    # Уход из ожидания владельца куда угодно, кроме закрытия, — вопрос выбыл из очереди,
    # не будучи закрытым. Тот же набор по той же причине.
    if old == OWNER_WAITING and new not in ATTRIBUTION_CRITICAL_STATUSES:
        return "CRITICAL"
    return "WARN"


def attribute(card: str, old: str, new: str, records: list[dict],
              since: Optional[dt.datetime], until: dt.datetime,
              card_text: Optional[str] = None) -> dict:
    """Объясняет ли журнал переход ``old -> new`` этой карточки.

    Записи берутся только из окна между снимками: старая запись про тот же переход
    не имеет права оправдать НОВЫЙ (иначе одна законная правка выдавала бы индульгенцию
    всем последующим молчаливым). Цепочка ``a -> b -> c`` объяснена, если её начало
    совпало со старым статусом, а конец — с новым.
    """
    lo = (since - SLACK) if since else None
    hi = until + SLACK
    mine = []
    for r in records:
        if r.get("card") != card:
            continue
        ts = _parse_ts(r.get("ts"))
        if ts is None:
            continue
        if lo is not None and ts < lo:
            continue
        if ts > hi:
            continue
        mine.append((ts, r))
    mine.sort(key=lambda item: item[0])
    if not mine:
        # Журнал молчит — спрашиваем САМУ карточку. Решение владельца 2026-08-23,
        # вариант 1 (ADR-129): журнал живёт в `data/` и в git не попадает, поэтому
        # законный переход, сделанный в рабочем дереве (а §3.4 требует именно его),
        # приезжает в прод немым. След едет вместе с карточкой и отвечает ровно на
        # тот вопрос, который здесь и задаётся: «этот переход кто-нибудь объяснил?»
        via_card = trail_explains(card_text, old, new) if card_text else None
        if via_card:
            who = f"{via_card['source']} · след карточки"
            if via_card.get("session"):
                who += f" · {via_card['session']}"
            return {"attributed": True, "reason": "card_trail", "writer": who,
                    "trail_ts": via_card["ts"], "records": via_card["records"]}
        return {"attributed": False, "reason": "no_record",
                "detail": "в журнале аудита нет ни одной записи об этом переходе, "
                          "и след перехода в самой карточке его не объясняет"}
    first, last = mine[0][1], mine[-1][1]
    got_old = str(first.get("old") or MISSING)
    got_new = str(last.get("new") or MISSING)
    who = f"{last.get('source')} · pid {last.get('pid')} · {last.get('argv')}"
    if got_old == old and got_new == new:
        return {"attributed": True, "reason": "chain_matches", "writer": who,
                "records": [r for _, r in mine]}
    # Журнал есть, но он про ДРУГОЙ переход: у прод-дерева бывает своя старая запись
    # об этой же карточке, а приехавший переход сделан в чужом дереве. Спрашиваем след.
    via_card = trail_explains(card_text, old, new) if card_text else None
    if via_card:
        trail_who = f"{via_card['source']} · след карточки"
        if via_card.get("session"):
            trail_who += f" · {via_card['session']}"
        return {"attributed": True, "reason": "card_trail", "writer": trail_who,
                "trail_ts": via_card["ts"], "records": via_card["records"]}
    return {"attributed": False, "reason": "chain_mismatch", "writer": who,
            "detail": f"журнал объясняет переход {got_old!r} -> {got_new!r}, "
                      f"а в трекере произошёл {old!r} -> {new!r}",
            "records": [r for _, r in mine]}


def run(root: str | Path = REPO_ROOT, now: Optional[dt.datetime] = None,
        write: bool = True) -> dict:
    """Один прогон сторожа: снять статусы, сверить переходы с журналом, доложить."""
    root = Path(root)
    stamp = now or dt.datetime.now(dt.timezone.utc)
    tracker = root / TRACKER_REL
    snap_path = root / SNAPSHOT_REL
    report_path = root / REPORT_REL

    statuses, unreadable = snapshot_statuses(tracker)
    records, broken = read_audit(root)

    prev: dict = {}
    prev_at: Optional[dt.datetime] = None
    prev_error: Optional[str] = None
    if snap_path.is_file():
        try:
            prev_raw = json.loads(snap_path.read_text(encoding="utf-8"))
            prev = prev_raw.get("statuses") or {}
            prev_at = _parse_ts(prev_raw.get("generated_at"))
        except (OSError, ValueError) as exc:
            prev_error = f"предыдущий снимок не прочитан: {exc}"
    else:
        prev_error = "предыдущего снимка нет — переходы измерить не с чем (первый прогон)"

    findings: list[dict] = []
    attributed: list[dict] = []
    appeared = sorted(set(statuses) - set(prev))
    vanished = sorted(set(prev) - set(statuses))

    for card in sorted(set(prev) & set(statuses)):
        old, new = str(prev[card]), str(statuses[card])
        if old == new:
            continue
        # Текст карточки читаем ТОЛЬКО у изменившихся: след живёт в ней самой
        # (ADR-129), а платить чтением за все 500 карточек ради десятка переходов
        # незачем. Нечитаемые сюда не доходят — они уже в `unreadable`.
        try:
            card_text = (tracker / card).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            card_text = None
        verdict = attribute(card, old, new, records, prev_at, stamp,
                            card_text=card_text)
        item = {"card": card, "from": old, "to": new, **verdict}
        if verdict["attributed"]:
            attributed.append(item)
        else:
            item["severity"] = _severity(old, new)
            findings.append(item)

    critical = [f for f in findings if f["severity"] == "CRITICAL"]
    warn = [f for f in findings if f["severity"] == "WARN"]
    unchecked: list[str] = []
    unchecked += ([prev_error] if prev_error else [])
    unchecked += [f"нечитаемая карточка — {u}" for u in unreadable]
    unchecked += [f"нечитаемая запись журнала — {b}" for b in broken]

    if unchecked:
        verdict = VERDICT_UNCHECKED
    elif findings:
        verdict = VERDICT_FINDINGS
    else:
        verdict = VERDICT_OK

    report = {
        "generated_at": stamp.isoformat(),
        "root": str(root),
        "verdict": verdict,
        "cards_seen": len(statuses),
        "transitions": len(findings) + len(attributed),
        "unattributed": findings,
        "attributed": attributed,
        "critical": len(critical),
        "warn": len(warn),
        "unchecked": unchecked,
        "appeared": appeared,
        "vanished": vanished,
        "previous_snapshot_at": prev_at.isoformat() if prev_at else None,
    }
    if write:
        atomic_save(report, str(report_path))
        atomic_save({"generated_at": stamp.isoformat(), "statuses": statuses},
                    str(snap_path))
    return report


def exit_code(report: dict) -> int:
    """0 — норма · 1 — WARN-находки · 2 — CRITICAL либо не измерено (fail-CLOSED)."""
    if report.get("critical") or report.get("unchecked"):
        return 2
    return 1 if report.get("unattributed") else 0


def _print(report: dict) -> None:
    print(f"— сторож переходов статусов: {report['verdict']} "
          f"(карточек {report['cards_seen']}, переходов {report['transitions']}) —")
    for f in report["unattributed"]:
        print(f"  [{f['severity']}] {f['card']}: {f['from']} -> {f['to']} — "
              f"НЕАТРИБУТИРОВАН ({f.get('detail') or f.get('reason')})")
        if f.get("writer"):
            print(f"      ближайшая запись журнала: {f['writer']}")
    for a in report["attributed"]:
        line = f"  [ok] {a['card']}: {a['from']} -> {a['to']} — {a.get('writer')}"
        # Возраст следа НАЗЫВАЕТСЯ, а не прячется: карточка приезжает с задержкой
        # доставки, и читатель имеет право видеть, насколько давним объяснением
        # закрыт переход (ADR-129, «времени тут не проверяем осознанно»).
        if a.get("trail_ts"):
            line += f" (след от {a['trail_ts']})"
        print(line)
    for u in report["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    if report["verdict"] == VERDICT_OK:
        print("  всё, что менялось, объяснено журналом аудита.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT,
                    help="рабочее дерево, чей трекер проверяем "
                         "(по умолчанию — дерево запущенного кода)")
    ap.add_argument("--json", action="store_true", help="отчёт машинной формой")
    ap.add_argument("--no-write", action="store_true",
                    help="не обновлять снимок и отчёт (сухой прогон)")
    args = ap.parse_args(argv)

    report = run(root=args.root, write=not args.no_write)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print(report)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
