#!/usr/bin/env python3
"""Население класса «карточка-тетрадь»: ДОЛЯ хроники в карточке, а не её вес.

Предмет — заказ G1055 п. 3 и карточка
`inbox-izmerit-naselenie-klassa-kartochka-tetra`. Цикл #1209 (ADR-1066) закрыл дверь
«карточка дорастает до нечитаемости» на ОДНОМ файле — стоячем приказе владельца
(3 273 543 символа, 374 записи цикла, сжат 77,2×). **Население класса за пределами
этой карточки нулём не считалось: закрыта одна дверь.**

## Почему ВЕС ответом не является

Замер 19.11 по весу давал распределение, а не ответ: самая тяжёлая карточка трекера
(`agent-audit-2026-08-02-fix-tracks.md`, 174 982 символа) может быть и честной
карточкой долгой работы, и тем же дефектом на меньшем масштабе. Предмет приказа назвало
ОТНОШЕНИЕ «хроника / содержание» (98.97 % против 1.03 %), а не килобайты.

## Две оси, и класс есть их ПЕРЕСЕЧЕНИЕ

| ось | порог | почему именно он |
|---|---|---|
| ДОЛЯ хроники | `--share` (умолчание 0.50) | выше половины файла содержание вытеснено |
| НЕЧИТАЕМОСТЬ | `--chars` (умолчание 30 000) | это объявленный предел `docs/STATE.md` (ADR-837) — единственное число в проекте, которым уже назван «читается в один приём» |

Одна доля класса не образует: карточка на 6 записей и 17 тысяч символов читается
целиком, и назвать её тетрадью значило бы покрасить честную работу. Один вес — тоже:
см. выше. Поэтому печатаются ОБА списка, а классом объявлено их пересечение.

## Двери

* **Запись цикла опознаёт ЕДИНСТВЕННАЯ дверь** — `push_to_github.CYCLE_RECORD_RE` и
  `entry_blocks` (ввозятся из дерева запущенного прибора). Своей копии нет намеренно:
  разойдись она с дверью ДОСТАВКИ — прибор считал бы тетрадью то, чего гейт не видит,
  и наоборот. Наивный греп `^## Цикл #` на том же приказе дал 266 против 374 (−29 %).
* **Символы, не байты.** Кириллица в UTF-8 весит два байта, и доля по байтам ответила
  бы о кодировке, а не о содержании.
* **Дерево — ВХОД и ПЕЧАТАЕТСЯ.** Прод-копия трекера для этого вопроса не годится:
  в ней 354 inbox-карточки против 1668 на `origin/main`, и ответ по ней был бы
  утверждением ОБ ЭТОМ ДЕРЕВЕ, а не о проекте.

## Исходы (инв. #17)

* `measured` — записи цикла есть, доля посчитана;
* **`not_applicable`** — записей цикла нет ВОВСЕ. Это НЕ «0 %»: у карточки без хроники
  доли хроники не существует, и ноль здесь был бы вычисленным числом там, где величины
  нет;
* `unmeasured` — файл не прочитан, причина названа.

## Коды возврата

* **0** — класс (пересечение осей) ПУСТ.
* **1** — члены класса НАЗВАНЫ поимённо.
* **2** — переписи нет вовсе (`unmeasured`): каталог не прочитан либо дверь не ввезена.
  Выдать это за «тетрадей нет» нельзя.

ADVISORY: только читает.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

MEASURED = "measured"
NOT_APPLICABLE = "not_applicable"
UNMEASURED = "unmeasured"

TRACKER_REL = os.path.join("nimbalyst-local", "tracker")

#: Предел `docs/STATE.md` (ADR-837) — объявленное число «читается в один приём».
DEFAULT_CHARS_CEILING = 30000
DEFAULT_SHARE_FLOOR = 0.50


class NotMeasured(Exception):
    """Переписи нет вовсе: причина названа, нулём это не считается."""


#: Дерево ЗАПУЩЕННОГО прибора — оттуда и только оттуда берётся дверь.
INSTRUMENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def chronicle_door():
    """ЕДИНСТВЕННАЯ дверь опознания записи цикла — из дерева ЗАПУЩЕННОГО прибора.

    Дверь берётся НЕ из измеряемого дерева: `--repo-root` называет, чьи КАРТОЧКИ
    мерить, а чем опознаётся запись — свойство прибора (тот же порядок, что у
    гейта доски, ADR-1060: разбор ввозится из дерева запущенного CLI). Своей
    копии разбора нет намеренно — разойдись она с дверью ДОСТАВКИ, прибор считал
    бы тетрадью то, чего гейт не видит.

    Отсутствие двери — :class:`NotMeasured`, а не свой разбор и не пустой класс.
    """
    if INSTRUMENT_ROOT not in sys.path:
        sys.path.insert(0, INSTRUMENT_ROOT)
    try:
        import push_to_github as door  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover — сцена «двери нет»
        raise NotMeasured(f"дверь записи цикла не ввезена: {exc!r}") from exc
    for name in ("CYCLE_RECORD_RE", "entry_blocks"):
        if not hasattr(door, name):
            raise NotMeasured(f"дверь записи цикла не объявляет {name}")
    return door


def card_row(path: str, door) -> dict:
    """Одна карточка: доля хроники либо названный третий исход."""
    name = os.path.basename(path)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"card": name, "outcome": UNMEASURED, "reason": repr(exc)}
    blocks = door.entry_blocks(raw, door.CYCLE_RECORD_RE)
    chars = len(text)
    if not blocks:
        return {"card": name, "outcome": NOT_APPLICABLE, "chars": chars, "records": 0}
    chronicle_bytes = sum(len(header) + len(body) for header, body in blocks)
    # Доля считается в СИМВОЛАХ: тело записи декодируется тем же кодеком, что файл.
    chronicle_chars = sum(
        len(header.decode("utf-8", "replace")) + len(body.decode("utf-8", "replace"))
        for header, body in blocks
    )
    return {
        "card": name,
        "outcome": MEASURED,
        "chars": chars,
        "records": len(blocks),
        "chronicle_chars": chronicle_chars,
        "chronicle_bytes": chronicle_bytes,
        "share": chronicle_chars / chars if chars else 0.0,
    }


def census(root: str, share_floor: float, chars_ceiling: int) -> dict:
    door = chronicle_door()
    tracker = os.path.join(root, TRACKER_REL)
    try:
        names = sorted(n for n in os.listdir(tracker) if n.endswith(".md"))
    except OSError as exc:
        raise NotMeasured(f"каталог трекера не прочитан: {exc}") from exc
    if not names:
        raise NotMeasured(f"в {TRACKER_REL} нет ни одной карточки — населения нет")

    # `_BOARD.md` — ПРОИЗВОДНЫЙ индекс очереди (ADR-1060), а не карточка: у него нет
    # ни содержания, ни хроники, и держать его в населении значило бы объявить
    # «самой тяжёлой карточкой» генератор. Исключение ПЕЧАТАЕТСЯ — молчаливое
    # сужение поверхности и есть тот дефект, против которого прибор написан.
    excluded = [name for name in names if name.startswith("_")]
    names = [name for name in names if not name.startswith("_")]

    rows = [card_row(os.path.join(tracker, name), door) for name in names]
    measured = [row for row in rows if row["outcome"] == MEASURED]
    above_share = sorted(
        (row for row in measured if row["share"] >= share_floor),
        key=lambda row: row["share"], reverse=True,
    )
    above_chars = sorted(
        (row for row in rows if row.get("chars", 0) > chars_ceiling),
        key=lambda row: row["chars"], reverse=True,
    )
    members = [row for row in above_share if row["chars"] > chars_ceiling]
    heaviest = max((row for row in rows if "chars" in row),
                   key=lambda row: row["chars"], default=None)
    return {
        "measured": True,
        "repo_root": root,
        "door_tree": INSTRUMENT_ROOT,
        "share_floor": share_floor,
        "chars_ceiling": chars_ceiling,
        "population": len(rows),
        "excluded_not_cards": excluded,
        "with_records": len(measured),
        "not_applicable": sum(1 for row in rows if row["outcome"] == NOT_APPLICABLE),
        "unmeasured": [row for row in rows if row["outcome"] == UNMEASURED],
        "above_share": above_share,
        "above_chars": above_chars,
        "members": members,
        "heaviest": heaviest,
    }


def render(report: dict) -> str:
    lines = [
        f"дерево КАРТОЧЕК: {report['repo_root']}",
        f"дерево ДВЕРИ (разбор записи цикла): {report['door_tree']}",
        "НАСЕЛЕНИЕ КЛАССА «карточка-тетрадь» — ДОЛЯ хроники × НЕЧИТАЕМОСТЬ",
        f"  карточек: {report['population']}  ·  с записями цикла: {report['with_records']}"
        f"  ·  записей нет ВОВСЕ (не «0 %»): {report['not_applicable']}"
        f"  ·  НЕ ИЗМЕРЕНО: {len(report['unmeasured'])}",
        f"  пороги: доля ≥ {report['share_floor']:.0%}  ·  символов > {report['chars_ceiling']}",
        "  вне населения (производный индекс, не карточка): "
        + (", ".join(report["excluded_not_cards"]) or "ничего"),
    ]
    lines.append(f"  выше порога ДОЛИ: {len(report['above_share'])}")
    for row in report["above_share"]:
        lines.append(
            f"     {row['share']:6.1%}  записей {row['records']:4d}  "
            f"{row['chars']:8d} симв.  {row['card']}"
        )
    lines.append(f"  выше порога НЕЧИТАЕМОСТИ: {len(report['above_chars'])}")
    for row in report["above_chars"][:10]:
        lines.append(
            f"     {row['chars']:8d} симв.  записей {row.get('records', 0):4d}  {row['card']}"
        )
    heaviest = report["heaviest"]
    if heaviest is not None:
        lines.append(
            f"  самая тяжёлая карточка: {heaviest['card']} — {heaviest['chars']} симв., "
            f"записей цикла {heaviest.get('records', 0)}"
            + ("  ⇒ оси РАСХОДЯТСЯ: вес есть, хроники нет"
               if not heaviest.get("records") else "")
        )
    for row in report["unmeasured"]:
        lines.append(f"  ⚠️ НЕ ИЗМЕРЕНО {row['card']}: {row['reason']}")
    lines.append(
        f"  ✅ КЛАСС ПУСТ по пересечению осей" if not report["members"]
        else f"  🔎 ЧЛЕНЫ КЛАССА ({len(report['members'])}):"
    )
    for row in report["members"]:
        lines.append(
            f"     {row['share']:6.1%}  записей {row['records']:4d}  "
            f"{row['chars']:8d} симв.  {row['card']}"
        )
    lines.append(
        "  ⚠️ «класс пуст» есть утверждение О ЭТОМ ДЕРЕВЕ и ОБ ЭТИХ ДВУХ ПОРОГАХ; "
        "тетрадь ниже обоих порогов прибор не назовёт, и это сказано вслух"
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="население класса «карточка-тетрадь»: доля хроники × нечитаемость"
    )
    parser.add_argument(
        "--repo-root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="дерево, о котором отвечает перепись (умолчание — дерево этого файла; "
             "выбор ПЕЧАТАЕТСЯ). Прод-копия трекера для этого вопроса не годится",
    )
    parser.add_argument("--share", type=float, default=DEFAULT_SHARE_FLOOR)
    parser.add_argument("--chars", type=int, default=DEFAULT_CHARS_CEILING)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.repo_root)
    try:
        report = census(root, args.share, args.chars)
    except NotMeasured as exc:
        payload = {"measured": False, "reason": str(exc), "repo_root": root}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"❌ НЕ ИЗМЕРЕНО ({root}): {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 1 if report["members"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
