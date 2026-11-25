#!/usr/bin/env python3
"""Инжест ответа владельца — НЕ состоявшееся действие (ADR-1103).

Карточка, у которой действие остаётся за ВЛАДЕЛЬЦЕМ (включить агента флота),
после инжеста ответа уходит в ``ingested`` / ``owner-done`` и перестаёт
спрашиваться. «Ответ получен» и «действие состоялось» — РАЗНЫЕ наблюдения
(инв. #17), и до ADR-1103 второе не спрашивал никто.

Замер 2026-11-25 (цикл #1248, живой флот, 658 ярлыков): карточек в
``ingested``/``owner-done``, просящих включить НАЗВАННОГО агента, — 37; агентов
они называют 30; действие состоялось у 17; **НЕ состоялось у 2**; retired 1;
**НЕ ИЗМЕРЕНО 10**. Худший член — ``com.spa.decision_loop``: его называют ПЯТЬ
карточек, ДВЕ из них в ``owner-done`` (этот статус ставит только владелец,
инв. #14), а во флоте его нет, и ступень моста ``findings_bridge`` молчит с
2026-10-29 11:19.

Дверь к состоянию флота — ОДНА (``fleet_labels``), и это ЖИВОЙ ``launchctl
list``, а не снимок ``data/agent_registry.json``: снимок производит агент,
которого в этом же классе может не быть во флоте, то есть он отвечал бы о себе.
Снимок зовётся ВТОРЫМ вопросом — «что про агента объявлено» (``retired``), —
и спорить с живой дверью о НАЛИЧИИ не вправе.

Исходы различимы (инв. #17):

* ``acted``      — ярлык есть во флоте: действие состоялось;
* ``pending``    — ярлыка во флоте нет, и агент НЕ объявлен retired: **находка**;
* ``retired``    — ярлыка нет, но агент объявлен отставным: вопрос снят, не находка;
* ``unmeasured`` — ярлыка нет ни во флоте, ни в реестре: НЕ ИЗМЕРЕНО с названной
  причиной. Нулём это не считается и находкой тоже: «агента нет» и «агента не
  включили» — разные утверждения, а имя в прозе карточки могло быть и опечаткой.

Код возврата: 0 — находок нет · 1 — находки названы · 2 — НЕ ИЗМЕРЕНО
(дверь флота не ответила, трекер не прочитан, ни одной карточки в объявленной
форме). «Ноль карточек в форме» — именно ``unmeasured``, а не «чисто»: неизвестно,
по какому полю судить.

Трекер — ВХОД (``--tracker-dir``), и ВЫБОР ПЕЧАТАЕТСЯ: читатель очереди,
молча померивший прод-трекер из worktree, отвечает о ЧУЖОМ дереве (урок
ADR-1080). Прибор только ЧИТАЕТ: он ничего не включает и ни одной карточки не
двигает — включение агента флота есть действие владельца
(``.claude/rules/deployment.md`` п. 6), а статусы карточек агент не правит
(инв. #14).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Статусы, про которые и задаётся вопрос: ответ владельца УЖЕ инжестирован либо
# карточка закрыта самим владельцем. Именно здесь очередь перестаёт спрашивать.
ANSWERED_STATUSES = ("ingested", "owner-done", "owner-accepted")

# Грубо в сторону НАХОДКИ (метод `.claude/rules/deployment.md`): просьба
# «включить/загрузить» ловится широко. Узкая форма пропустила бы карточку,
# написанную человеческим языком, — а правило §2.4 требует именно его.
_ASK_RE = re.compile(r"включ|загруз|launchctl|bootstrap|поднят|запуст", re.I)
_LABEL_RE = re.compile(r"com\.spa\.[a-z_0-9]+")
_STATUS_RE = re.compile(r"^status:\s*(\S+)", re.M)

# Тело карточки читается не целиком: карточка-приказ бывает многомегабайтной
# (прод-копия голодающего приказа — 2,88 МБ), и дочитывать её до конца, чтобы
# найти ярлык агента, значит платить за вопрос, которого не задавали.
_HEAD_BYTES = 40_000

UNMEASURED_EXIT = 2
FINDINGS_EXIT = 1


def fleet_labels() -> set[str] | None:
    """ЕДИНСТВЕННАЯ дверь к ЖИВОМУ состоянию флота.

    ``None`` = дверь НЕ ОТВЕТИЛА (инструмента нет, ненулевой код, пустой
    вывод). Это третий исход, а не пустое множество: пустое множество
    означало бы «во флоте нет НИКОГО», и тогда прибор объявил бы находкой
    каждого названного агента — то есть выдумал бы класс из своей немоты.
    """
    try:
        proc = subprocess.run(["launchctl", "list"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    labels: set[str] = set()
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3:
            label = parts[2].strip()
            if label:
                labels.add(label)
    # Пустой разбор при коде 0 — тоже «не ответила»: формат вывода не тот,
        # о котором прибор знает, и молчать об этом было бы fail-OPEN.
    return labels or None


def declared_retired(registry_path: str) -> tuple[dict[str, bool] | None, str]:
    """ВТОРОЙ вопрос: что про агента ОБЪЯВЛЕНО (отставной он или нет).

    Возвращает (объявление, ПРОВЕНАНС). ``None`` = объявления нет (реестр не
    прочитан); тогда «не во флоте» остаётся находкой: отсутствие объявления не
    есть объявление отставки.

    **Провенанс печатается всегда, и это несущая половина.** Реестр живёт в
    ``data/``, а канон ``data/`` в git ЗАМОРОЖЕН — в любом worktree он
    четырёхмесячной давности. Замер 2026-11-25: дерево доставки отдаёт **80**
    записей от ``2026-07-17``, прод — **99** от того же дня; `decision_loop` в
    замороженном реестре ОТСУТСТВУЕТ, то есть находка о нём из worktree
    превращается в «НЕ ИЗМЕРЕНО», а на её место приходит ЛОЖНАЯ находка о
    `governance_watcher` — агенте, которого сегодня нет вовсе. Молча ответить о
    замороженной копии хуже ошибки: читатель не узнает, о чьём реестре ему
    ответили (тот же порядок, что у `--data-dir` шагов 0д/0е).
    """
    try:
        with open(registry_path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f"{registry_path}: НЕ ПРОЧИТАН ({exc})"
    agents = doc.get("agents") if isinstance(doc, dict) else doc
    if not isinstance(agents, list):
        return None, f"{registry_path}: формат не разобран (нет списка `agents`)"
    stamp = doc.get("generated_at") if isinstance(doc, dict) else None
    out: dict[str, bool] = {}
    for item in agents:
        if isinstance(item, dict) and item.get("label"):
            out[str(item["label"])] = bool(item.get("retired"))
    provenance = (f"{registry_path}: записей {len(out)}, generated_at "
                  f"{stamp or 'НЕ ИЗМЕРЕНО (поля нет)'}")
    return (out or None), provenance


def cards_asking_to_enable(tracker_dir: str) -> tuple[dict[str, list[tuple[str, str]]], list[str]]:
    """Ярлык агента → список (файл карточки, статус), плюс список непрочитанных.

    Непрочитанный файл НАЗЫВАЕТСЯ, а не пропускается молча: «карточек в форме
    нет» и «карточку не удалось прочитать» — разные наблюдения.
    """
    named: dict[str, list[tuple[str, str]]] = {}
    unread: list[str] = []
    try:
        entries = sorted(os.listdir(tracker_dir))
    except OSError as exc:
        raise FileNotFoundError(f"{tracker_dir}: {exc}") from exc
    for name in entries:
        if not name.endswith(".md"):
            continue
        path = os.path.join(tracker_dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read(_HEAD_BYTES)
        except OSError as exc:
            unread.append(f"{name}: {exc}")
            continue
        match = _STATUS_RE.search(head)
        if not match or match.group(1) not in ANSWERED_STATUSES:
            continue
        if not _ASK_RE.search(head):
            continue
        for label in set(_LABEL_RE.findall(head)):
            named.setdefault(label, []).append((name, match.group(1)))
    return named, unread


def census(*, tracker_dir: str, registry_path: str,
           labels: set[str] | None) -> dict:
    """Свести три двери в один вердикт. Чистая функция: доступ к ОС — у звавшего."""
    if labels is None:
        return {"outcome": "unmeasured",
                "reason": "дверь флота не ответила: launchctl list недоступен, "
                          "вернул ненулевой код или вывод не разобран",
                "fleet_size": None, "tracker_dir": tracker_dir}
    try:
        named, unread = cards_asking_to_enable(tracker_dir)
    except FileNotFoundError as exc:
        return {"outcome": "unmeasured",
                "reason": f"трекер не прочитан: {exc}",
                "fleet_size": len(labels), "tracker_dir": tracker_dir}
    if not named:
        return {"outcome": "unmeasured",
                "reason": "ни одной карточки в объявленной форме "
                          f"(status ∈ {list(ANSWERED_STATUSES)} + просьба включить "
                          "+ названный ярлык com.spa.*) — неизвестно, по какому "
                          "полю судить",
                "fleet_size": len(labels), "tracker_dir": tracker_dir,
                "cards_unread": unread}
    retired, registry_provenance = declared_retired(registry_path)
    acted, pending, retired_hits, unmeasured = [], [], [], []
    for label in sorted(named):
        row = {"label": label,
               "cards": [{"card": c, "status": s} for c, s in sorted(named[label])]}
        if label in labels:
            acted.append(row)
        elif retired is None:
            # Объявления нет вовсе ⇒ отставку никто не объявлял ⇒ находка.
            pending.append(row)
        elif retired.get(label) is True:
            retired_hits.append(row)
        elif label in retired:
            pending.append(row)
        else:
            row["reason"] = "ярлыка нет ни во флоте, ни в реестре агентов"
            unmeasured.append(row)
    return {"outcome": "findings" if pending else "clean",
            "fleet_size": len(labels),
            "tracker_dir": tracker_dir,
            "registry_provenance": registry_provenance,
            "cards_unread": unread,
            "agents_named": len(named),
            "acted": acted,
            "pending": pending,
            "retired": retired_hits,
            "unmeasured_labels": unmeasured}


def report_lines(result: dict) -> list[str]:
    out = [f"трекер: {result['tracker_dir']}  (ВЫБОР НАПЕЧАТАН, не угадан)"]
    if result["outcome"] == "unmeasured":
        out.append(f"[НЕ ИЗМЕРЕНО] {result['reason']}")
        return out
    out.append(f"живых ярлыков во флоте: {result['fleet_size']} "
               f"(дверь: launchctl list)")
    # Провенанс реестра — НАПЕЧАТАН, а не подразумеваем: канон `data/` в git
    # заморожен, и в worktree реестр четырёхмесячный (см. `declared_retired`).
    out.append(f"реестр (ВТОРОЙ вопрос «что ОБЪЯВЛЕНО»): "
               f"{result['registry_provenance']}")
    out.append(f"агентов названо карточками с инжестированным ответом: "
               f"{result['agents_named']}")
    out.append(f"  ✅ действие СОСТОЯЛОСЬ: {len(result['acted'])}")
    out.append(f"  🚨 НЕ СОСТОЯЛОСЬ: {len(result['pending'])}")
    for row in result["pending"]:
        cards = ", ".join(f"{c['card']}[{c['status']}]" for c in row["cards"])
        out.append(f"       {row['label']} — карточки: {cards}")
    out.append(f"  ⬜ объявлен retired (вопрос снят): {len(result['retired'])}")
    out.append(f"  [НЕ ИЗМЕРЕНО] {len(result['unmeasured_labels'])} ярлык(ов) нет "
               f"ни во флоте, ни в реестре — это НЕ ноль и НЕ находка")
    for row in result["unmeasured_labels"]:
        out.append(f"       {row['label']}: {row['reason']}")
    if result["cards_unread"]:
        out.append(f"  [НЕ ИЗМЕРЕНО] карточек не прочитано: "
                   f"{len(result['cards_unread'])}")
        for item in result["cards_unread"]:
            out.append(f"       {item}")
    if result["pending"]:
        out.append("— включение агента флота есть действие ВЛАДЕЛЬЦА "
                   "(.claude/rules/deployment.md п. 6): прибор только читает, "
                   "карточку заводит сессия —")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--tracker-dir", default=None,
                    help="каталог карточек; умолчание — nimbalyst-local/tracker "
                         "рядом с прибором, и выбор ПЕЧАТАЕТСЯ")
    ap.add_argument("--registry", default=None,
                    help="data/agent_registry.json — ВТОРОЙ вопрос «что объявлено»")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tracker = args.tracker_dir or os.path.join(root, "nimbalyst-local", "tracker")
    registry = args.registry or os.path.join(root, "data", "agent_registry.json")

    result = census(tracker_dir=os.path.abspath(tracker),
                    registry_path=registry,
                    labels=fleet_labels())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for line in report_lines(result):
            print(line)
    if result["outcome"] == "unmeasured":
        return UNMEASURED_EXIT
    return FINDINGS_EXIT if result["pending"] else 0


if __name__ == "__main__":
    sys.exit(main())
