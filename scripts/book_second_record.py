#!/usr/bin/env python3
"""Вторая запись о деньгах: сходится ли книга с журналом ходов (двойная запись).

Шаг 3 из трёх до повторного вопроса о go-live ([ADR-286](../docs/decisions/ADR-286-owner-decisions-2026-09-09.md) §1),
вторая его половина. Первая — независимое наблюдение — упирается в ключи владельца
(ADR-257) и здесь НЕ решается и не изображается решённой.

**Почему это не то же самое, что сверка ADR-255.** Та сравнивала величину с самой собой:
обе стороны происходили из одного намерения, и расхождение было недостижимо по построению
(ADR-349 снял это утверждение). Здесь стороны РАЗНЫЕ по писателю и по времени: журнал
ходов пишется в момент решения, файл позиций — в конце цикла. Совпасть они обязаны, а
разойтись могут только от дефекта. Это двойная запись, а не наблюдение: источник по-прежнему
наш, и выдавать её за независимость было бы уверенным неверным ответом.

## Что меряется

1. **Непрерывность цепи.** `from_allocation` каждого хода обязан совпасть с
   `to_allocation` предыдущего. Разрыв означает, что состояние книги менялось МИМО
   журнала.
2. **Схождение конца.** `to_allocation` последнего хода обязан совпасть с развёрнутой
   книгой `current_positions.json`.

Разрывы РАЗДЕЛЕНЫ по природе, и это главное в приборе:

| род | признак | что означает |
|---|---|---|
| `renamed_key` | суммы совпали, множества ключей разошлись | переименование/слияние ключа пула (замер 12.09: T034, `fluid_usdc` → `fluid_fusdc`, слияние ADR-331/335) |
| `money_gap` | суммы НЕ совпали | деньги сменили состояние без записи (замер 12.09: T008, $94 999.88 → $80 000.00 — журнал пуст с 20.06 по 23.08) |

Сваливать их в один счёт нельзя: первое — дефект ИМЕНИ и лечится реестром ключей, второе —
дыра в записи о деньгах. Молчаливое прощение первого («суммы же сошлись») ослепило бы прибор
ровно на том классе, ради которого он написан.

## Третий исход

Нет каталога данных, нет файла, файл не разобран, журнал пуст ⇒ **«НЕ ИЗМЕРЕНО»** с
названной причиной и кодом 2 (инв. #17). Отсутствие `data/` в рабочем дереве — штатно
и НЕ является находкой: там его нет по построению.

Коды возврата: 0 — сходится · 1 — расхождения названы · 2 — НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Допуск в долларах. Книга ведётся в центах, поэтому копейка — шум округления,
#: а не расхождение; больше центра брать нельзя: T034 разошёлся на НОЛЬ долларов
#: и всё равно обязан быть назван.
TOLERANCE_USD = 0.01


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


def data_dir(explicit: str | None = None) -> Path:
    d = Path(explicit or os.environ.get("SPA_DATA_DIR") or (ROOT / "data"))
    if not d.is_dir():
        raise NotMeasured(f"каталога данных нет ({d}) — в рабочем дереве это ШТАТНО "
                          f"и находкой не является")
    return d


def _load(path: Path) -> object:
    if not path.is_file():
        raise NotMeasured(f"{path.name} не найден — сверять нечего")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"{path.name} не разобран ({exc})") from exc


def _norm(d: object) -> dict:
    """Аллокация в сравнимом виде: нули выброшены, суммы округлены до цента."""
    out = {}
    for k, v in (d or {}).items() if isinstance(d, dict) else ():
        try:
            val = round(float(v or 0.0), 2)
        except (TypeError, ValueError):
            continue
        if val:
            out[str(k)] = val
    return out


def chain_breaks(trades: list) -> list[dict]:
    """Разрывы цепи ходов, каждый С НАЗВАННЫМ РОДОМ."""
    breaks = []
    for i in range(1, len(trades)):
        prev_to = _norm(trades[i - 1].get("to_allocation"))
        cur_from = _norm(trades[i].get("from_allocation"))
        if prev_to == cur_from:
            continue
        gap = round(sum(cur_from.values()) - sum(prev_to.values()), 2)
        breaks.append({
            "trade_id": trades[i].get("trade_id"),
            "ts": trades[i].get("ts"),
            "kind": "money_gap" if abs(gap) > TOLERANCE_USD else "renamed_key",
            "sum_before": round(sum(prev_to.values()), 2),
            "sum_after": round(sum(cur_from.values()), 2),
            "gap_usd": gap,
            "keys_only_before": sorted(set(prev_to) - set(cur_from)),
            "keys_only_after": sorted(set(cur_from) - set(prev_to)),
        })
    return breaks


def terminal_divergence(trades: list, positions: dict) -> dict | None:
    """Расхождение последнего хода с развёрнутой книгой, либо None."""
    book = positions.get("positions")
    if not isinstance(book, dict):
        raise NotMeasured("в current_positions.json нет объекта `positions` — "
                          "разворот книги не прочитан")
    last_to = _norm(trades[-1].get("to_allocation"))
    book = _norm(book)
    keys = set(last_to) | set(book)
    diff = {k: [last_to.get(k, 0.0), book.get(k, 0.0)] for k in keys
            if abs(last_to.get(k, 0.0) - book.get(k, 0.0)) > TOLERANCE_USD}
    if not diff:
        return None
    return {"last_trade_id": trades[-1].get("trade_id"),
            "sum_journal": round(sum(last_to.values()), 2),
            "sum_book": round(sum(book.values()), 2),
            "per_key": dict(sorted(diff.items()))}


def measure(ddir: str | None = None) -> dict:
    d = data_dir(ddir)
    trades = _load(d / "trades.json")
    if not isinstance(trades, list) or not trades:
        raise NotMeasured("журнал ходов пуст или не список — цепь не строится")
    positions = _load(d / "current_positions.json")
    if not isinstance(positions, dict):
        raise NotMeasured("current_positions.json не объект")
    breaks = chain_breaks(trades)
    terminal = terminal_divergence(trades, positions)
    return {
        # КАКОЕ ДЕРЕВО измерено — часть ответа, а не украшение: канон `data/` в git
        # заморожен (замер 12.09: на origin журнал несёт 7 ходов, живой — 34), поэтому
        # один и тот же прибор из прода и из worktree отвечает РАЗНОЕ, и вердикт без
        # названного каталога был бы вердиктом об окружении.
        "data_dir": str(d),
        "trades": len(trades),
        "chain_breaks": breaks,
        "money_gaps": [b for b in breaks if b["kind"] == "money_gap"],
        "renamed_keys": [b for b in breaks if b["kind"] == "renamed_key"],
        "terminal_divergence": terminal,
        "reconciles": not breaks and terminal is None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=None, help="каталог данных (умолчание — SPA_DATA_DIR или data/)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)
    try:
        r = measure(args.data_dir)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        return 2
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    if r["reconciles"]:
        print(f"Вторая запись сходится: {r['trades']} ходов, цепь непрерывна, "
              f"конец совпал с книгой. Каталог: {r['data_dir']}")
        return 0
    print(f"РАСХОЖДЕНИЯ второй записи ({r['trades']} ходов, каталог {r['data_dir']}):")
    for b in r["money_gaps"]:
        print(f"  ДЫРА В ЗАПИСИ  {b['trade_id']} {str(b['ts'])[:19]}: "
              f"${b['sum_before']:,.2f} → ${b['sum_after']:,.2f} "
              f"(${b['gap_usd']:+,.2f}) — деньги сменили состояние без записи")
    for b in r["renamed_keys"]:
        print(f"  ПЕРЕИМЕНОВАНИЕ {b['trade_id']} {str(b['ts'])[:19]}: суммы равны, "
              f"ключи {b['keys_only_before']} → {b['keys_only_after']}")
    if r["terminal_divergence"]:
        t = r["terminal_divergence"]
        print(f"  КОНЕЦ НЕ СОШЁЛСЯ после {t['last_trade_id']}: "
              f"журнал ${t['sum_journal']:,.2f} · книга ${t['sum_book']:,.2f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
