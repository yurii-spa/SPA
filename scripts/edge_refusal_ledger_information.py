#!/usr/bin/env python3
"""#161 RLI — Refusal-Ledger Information: сколько информации несёт публичный журнал отказов десков.

Предмет. `data/rates_desk/decision_log.jsonl` объявлен в `spa_core/strategy_lab/rates_desk/proof_chain.py`
как «публичный артефакт, который посторонний скачивает и проверяет», а отказы — как «доказательство
первого класса» (refusals are first-class evidence). В реестре `docs/DYNAMIC_LEVERAGE_GUARDIAN.md`
слово `decision_log` встречается **0 раз**: ни одна из 160 записей этот ряд не читала. Директива
владельца прямо называет «refusal-логи rates_desk» сырьём для идей — отсюда и прибор.

Вопрос, на который прибор отвечает ЧИСЛОМ, а не прозой: **можно ли на этом журнале построить хоть
один эдж** — ротацию между underlying'ами по отказу, тайминг по движению net_edge, захват
«отказанной доходности»? У всех трёх предпосылка одна: журнал обязан НЕСТИ НАБЛЮДЕНИЯ. Прибор
меряет, сколько их там.

Три независимых вопроса — три секции, и зелёный ответ одной НИКОГДА не есть ответ на другие:

  `--section chain`        цела ли хэш-цепь (это вопрос о ПОДЛИННОСТИ окна, не о содержании чисел)
  `--section information`  сколько РАЗЛИЧНЫХ значений несёт каждая сторона журнала (одобрение/отказ)
  `--section economics`    сколько стоит «отказанная доходность» в долларах и где её break-even

Инвариант #17 соблюдён буквально: у каждого числа три исхода — ИЗМЕРЕНО · ИЗМЕРЕНО И РАВНО НУЛЮ ·
НЕ ИЗМЕРЕНО (с названной причиной). Отсутствующее поле НИКОГДА не подставляется нулём: строка без
`exit_cap` не есть строка с нулевой ёмкостью выхода.

Коды возврата: **0** — измерено · **1** — находка о подлинности (цепь разорвана) · **2** — НЕ
ИЗМЕРЕНО (файла нет, не разбирается, ни одной строки объявленной формы) — fail-CLOSED.

Только stdlib. `data/` открывается ТОЛЬКО НА ЧТЕНИЕ: прибор не пишет ни одного байта.
IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import collections
import datetime
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_LOG = _ROOT / "data" / "rates_desk" / "decision_log.jsonl"

# Пределы объявлены здесь ОДИН раз: цитировать их числом в тексте вердикта запрещено — печатается
# то, что прочитано у журнала (`min_tradeable_size_usd` лежит в самой строке отказа).
_ZERO = Decimal(0)


# ── чтение наблюдения: отсутствие отличимо от нуля (инв. #17) ────────────────────────────────────
def _dec(row: Any, key: str) -> Optional[Decimal]:
    """Десятичное наблюдение `key` из строки журнала — или ``None``, если наблюдения НЕТ.

    Журнал хранит деньги и ставки СТРОКАМИ произвольной точности (`"7634.688260190530500"`),
    поэтому `float` здесь был бы потерей, а `or 0` — подстановкой. Нечисло, пустая строка и
    отсутствие ключа — одинаково «наблюдения нет», и это НЕ ноль.
    """
    if not isinstance(row, dict) or key not in row:
        return None
    raw = row[key]
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


class Unmeasured(Exception):
    """Предпосылка замера НЕ ОБЕСПЕЧЕНА. Причина называется, код возврата 2."""


def load_rows(path: Path) -> List[dict]:
    """Строки журнала. Нечитаемый файл / ни одной строки объявленной формы ⇒ ``Unmeasured``.

    Пустая строка файла пропускается молча (это разделитель, не наблюдение), а строка, которая
    не разбирается как JSON-объект, ОТКАЗЫВАЕТ целиком: журнал, половина которого не читается,
    не является «журналом с половиной наблюдений».
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Unmeasured(f"журнала нет по пути {path}")
    except OSError as exc:
        raise Unmeasured(f"журнал {path} не прочитан: {exc.__class__.__name__}")
    rows: List[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Unmeasured(f"строка {lineno} журнала не разбирается как JSON: {exc.msg}")
        if not isinstance(row, dict):
            raise Unmeasured(f"строка {lineno} журнала — не объект, а {type(row).__name__}")
        rows.append(row)
    if not rows:
        raise Unmeasured(f"в журнале {path} нет ни одной строки — это НЕ ИЗМЕРЕНО, а не «нет отказов»")
    return rows


# ── §1 подлинность окна: хэш-цепь и непрерывность номеров ───────────────────────────────────────
def check_chain(rows: List[dict]) -> dict:
    """Цела ли цепь `prev_hash → entry_hash` и непрерывны ли `seq`.

    Что этот вопрос НЕ решает: журнал — RING-BUFFER (`LOG_CAP = 2000`,
    `spa_core/strategy_lab/rates_desk/anchors.py`), и писатель ПЕРЕХЭШИРУЕТ окно при каждом
    добавлении. Поэтому целая цепь говорит о связности ОКНА, а не о том, что до окна ничего не
    стирали, и уж точно ничего не говорит о том, наблюдения ли внутри.
    """
    breaks: List[dict] = []
    missing = 0
    for i, row in enumerate(rows):
        entry_hash = row.get("entry_hash")
        prev_hash = row.get("prev_hash")
        if not isinstance(entry_hash, str) or not isinstance(prev_hash, str):
            missing += 1
            continue
        if i == 0:
            continue
        expected = rows[i - 1].get("entry_hash")
        if not isinstance(expected, str):
            continue
        if prev_hash != expected:
            breaks.append({"index": i, "seq": row.get("seq"),
                           "prev_hash": prev_hash[:12], "expected": expected[:12]})
    seqs = [row.get("seq") for row in rows]
    numeric = [s for s in seqs if isinstance(s, int) and not isinstance(s, bool)]
    if len(numeric) != len(rows):
        seq_verdict = "НЕ ИЗМЕРЕНО: не у каждой строки есть целый `seq`"
        contiguous: Optional[bool] = None
    else:
        contiguous = (len(set(numeric)) == len(numeric)
                      and max(numeric) - min(numeric) == len(numeric) - 1)
        seq_verdict = f"{min(numeric)}…{max(numeric)}, непрерывны: {'да' if contiguous else 'НЕТ'}"
    return {
        "rows": len(rows),
        "hash_fields_missing": missing,
        "breaks": breaks,
        "seq_verdict": seq_verdict,
        "seq_contiguous": contiguous,
        "intact": not breaks and missing == 0,
    }


# ── §2 информация: сколько РАЗЛИЧНЫХ значений несёт каждая сторона ──────────────────────────────
def _side(row: dict) -> str:
    """Сторона строки: `ENTRY` (одобрено) · `REFUSAL` (отказано) · `OTHER`.

    Сторона берётся из поля `kind`, а НЕ из `approved`: род записи объявляется полем рода, и
    выводить его из соседнего признака значило бы подменить объявление догадкой.
    """
    kind = row.get("kind")
    return kind if kind in ("ENTRY", "REFUSAL") else "OTHER"


def _ticks(rows: List[dict]) -> Tuple[List[datetime.datetime], List[str]]:
    """Отметки времени (отсортированные, различные) и причины непрочитанных."""
    stamps: Dict[str, datetime.datetime] = {}
    bad: List[str] = []
    for row in rows:
        raw = row.get("ts")
        if not isinstance(raw, str):
            bad.append(f"seq={row.get('seq')}: отметки `ts` нет")
            continue
        if raw in stamps:
            continue
        try:
            stamps[raw] = datetime.datetime.fromisoformat(raw)
        except ValueError:
            bad.append(f"seq={row.get('seq')}: `ts`={raw!r} не разбирается")
    return sorted(stamps.values()), bad


def measure_information(rows: List[dict]) -> dict:
    """Сколько различных значений несёт каждая сторона — и сколько РАЗ повторён каждый кортеж.

    Мера выбрана так, чтобы её нельзя было выдать за содержание: для эджа по ротации нужно, чтобы
    ОДОБРЕННАЯ сторона двигалась (иначе нечего таймить), а для эджа по отказу — чтобы у отказа
    было больше одной причины (иначе нечего различать).
    """
    sides = collections.Counter(_side(row) for row in rows)
    out: Dict[str, Any] = {"sides": dict(sides)}

    reasons = collections.Counter(
        row.get("reason") if isinstance(row.get("reason"), str) else "НЕ ИЗМЕРЕНО"
        for row in rows if _side(row) == "REFUSAL")
    out["refusal_reasons"] = dict(reasons)
    out["refusal_underlyings"] = dict(collections.Counter(
        row.get("underlying") if isinstance(row.get("underlying"), str) else "НЕ ИЗМЕРЕНО"
        for row in rows if _side(row) == "REFUSAL"))

    per_side: Dict[str, Any] = {}
    for side in ("ENTRY", "REFUSAL"):
        subset = [row for row in rows if _side(row) == side]
        if not subset:
            per_side[side] = {"rows": 0, "verdict": "НЕ ИЗМЕРЕНО: строк этой стороны в окне нет"}
            continue
        edges = [_dec(row, "net_edge") for row in subset]
        sizes = [_dec(row, "approved_size_usd") for row in subset]
        tuples = collections.Counter(
            (row.get("underlying"),
             str(_dec(row, "net_edge")),
             str(_dec(row, "approved_size_usd")))
            for row in subset)
        # Разложение ставки (`decomposition`: fair_yield + haircut'ы) — это ВХОД решения, а не его
        # исход. Если он не двигается, то не двигается и решение, и спрашивать «почему решение
        # постоянно» дальше незачем: вопрос переносится на производителя входа.
        decomps = []
        decomp_unmeasured = 0
        for row in subset:
            doc = row.get("decomposition")
            if not isinstance(doc, dict):
                decomp_unmeasured += 1
                continue
            decomps.append(tuple(sorted((k, str(v)) for k, v in doc.items() if k != "as_of")))
        per_side[side] = {
            "rows": len(subset),
            "decomposition_distinct": len(set(decomps)),
            "decomposition_unmeasured": decomp_unmeasured,
            "net_edge_distinct": len({e for e in edges if e is not None}),
            "net_edge_unmeasured": sum(1 for e in edges if e is None),
            "size_distinct": len({s for s in sizes if s is not None}),
            "size_unmeasured": sum(1 for s in sizes if s is None),
            "distinct_tuples": len(tuples),
            "most_repeated": tuples.most_common(6),
        }
    out["per_side"] = per_side

    stamps, bad = _ticks(rows)
    if len(stamps) < 2:
        out["cadence"] = {"ticks": len(stamps),
                          "verdict": "НЕ ИЗМЕРЕНО: для шага нужно ≥ 2 различных отметки"}
    else:
        gaps = [(stamps[i] - stamps[i - 1]).total_seconds() for i in range(1, len(stamps))]
        gaps.sort()
        out["cadence"] = {
            "ticks": len(stamps),
            "span_days": round((stamps[-1] - stamps[0]).total_seconds() / 86400.0, 2),
            "gap_median_s": round(gaps[len(gaps) // 2], 2),
            "gap_max_s": round(gaps[-1], 2),
            "rows_per_tick": dict(collections.Counter(
                collections.Counter(row.get("ts") for row in rows).values())),
            "first": stamps[0].isoformat(),
            "last": stamps[-1].isoformat(),
        }
    out["ts_unreadable"] = bad[:5]
    out["ts_unreadable_count"] = len(bad)
    return out


# ── §3 экономика отказа: что стоит «отказанная доходность» ──────────────────────────────────────
def measure_economics(rows: List[dict]) -> dict:
    """Доллары, а не риторика: сколько приносила бы отказанная нога, если бы её пустили.

    Механизм отказа объявлен в самой строке: `exit_cap` (сколько РЕАЛЬНО можно вывести) против
    `min_tradeable_size_usd` (пол размера). Годовая величина отказанного эджа = `exit_cap` ×
    `net_edge`; это ПОТОЛОК захвата — больше ёмкости выхода не взять по построению.

    Строка без `exit_cap`, без пола или без `net_edge` в замер НЕ ВХОДИТ и считается отдельно:
    её отсутствие не есть нулевая ёмкость.
    """
    refusals = [row for row in rows if _side(row) == "REFUSAL"]
    if not refusals:
        return {"refusals": 0,
                "verdict": "НЕ ИЗМЕРЕНО: в окне нет ни одной строки отказа"}
    caps: List[Decimal] = []
    floors: List[Decimal] = []
    annual: List[Decimal] = []
    incomplete = 0
    passable = 0
    for row in refusals:
        cap = _dec(row.get("detail", {}), "exit_cap")
        floor = _dec(row.get("detail", {}), "min_tradeable_size_usd")
        edge = _dec(row, "net_edge")
        if cap is None or floor is None or edge is None:
            incomplete += 1
            continue
        caps.append(cap)
        floors.append(floor)
        annual.append(cap * edge)
        if cap >= floor:
            passable += 1
    if not caps:
        return {"refusals": len(refusals), "incomplete": incomplete,
                "verdict": "НЕ ИЗМЕРЕНО: ни у одной строки отказа нет тройки "
                           "(exit_cap · min_tradeable_size_usd · net_edge)"}
    caps_sorted = sorted(caps)
    annual_sorted = sorted(annual)
    floor_set = sorted({str(f) for f in floors})
    return {
        "refusals": len(refusals),
        "measured": len(caps),
        "incomplete": incomplete,
        "exit_cap_min": str(caps_sorted[0].quantize(Decimal("0.01"))),
        "exit_cap_median": str(caps_sorted[len(caps_sorted) // 2].quantize(Decimal("0.01"))),
        "exit_cap_max": str(caps_sorted[-1].quantize(Decimal("0.01"))),
        "floors": floor_set,
        "rows_at_or_above_floor": passable,
        "shortfall_best_case_x": (
            str((max(floors) / caps_sorted[-1]).quantize(Decimal("0.01")))
            if caps_sorted[-1] > _ZERO else "НЕ ИЗМЕРЕНО: лучшая ёмкость равна нулю"),
        "annual_edge_usd_median": str(annual_sorted[len(annual_sorted) // 2].quantize(Decimal("0.01"))),
        "annual_edge_usd_max": str(annual_sorted[-1].quantize(Decimal("0.01"))),
    }


# ── печать ──────────────────────────────────────────────────────────────────────────────────────
def _print_chain(res: dict) -> None:
    print("§1 ПОДЛИННОСТЬ ОКНА (хэш-цепь) — вопрос о связности, НЕ о содержании чисел")
    print(f"   строк в окне: {res['rows']}")
    print(f"   разрывов `prev_hash → entry_hash`: {len(res['breaks'])}")
    for b in res["breaks"][:5]:
        print(f"     • index={b['index']} seq={b['seq']} prev={b['prev_hash']} "
              f"ожидался {b['expected']}")
    print(f"   строк без хэш-полей: {res['hash_fields_missing']}")
    print(f"   `seq`: {res['seq_verdict']}")
    print(f"   ⇒ цепь {'ЦЕЛА' if res['intact'] else 'РАЗОРВАНА'}")
    print("   ⚠️  журнал — RING-BUFFER (LOG_CAP=2000) и ПЕРЕХЭШИРУЕТСЯ при каждом добавлении:")
    print("       целая цепь НЕ означает, что до окна ничего не стиралось (anchors.py, 2026-07-10).")


def _print_information(res: dict) -> None:
    print("§2 ИНФОРМАЦИЯ — сколько РАЗЛИЧНЫХ значений несёт каждая сторона журнала")
    print(f"   стороны: {res['sides']}")
    print(f"   причины отказа: {res['refusal_reasons']}")
    print(f"   отказанные underlying: {res['refusal_underlyings']}")
    for side, info in res["per_side"].items():
        if info.get("verdict"):
            print(f"   {side}: {info['verdict']}")
            continue
        print(f"   {side}: различных ВХОДОВ решения (decomposition) "
              f"{info['decomposition_distinct']} (НЕ ИЗМЕРЕНО "
              f"{info['decomposition_unmeasured']})")
        print(f"   {side}: строк {info['rows']} · различных net_edge "
              f"{info['net_edge_distinct']} (НЕ ИЗМЕРЕНО {info['net_edge_unmeasured']}) · "
              f"различных размеров {info['size_distinct']} "
              f"(НЕ ИЗМЕРЕНО {info['size_unmeasured']}) · различных кортежей "
              f"{info['distinct_tuples']}")
        for tup, cnt in info["most_repeated"]:
            print(f"      {cnt:>5}× {tup[0]} net_edge={tup[1][:12]} size={tup[2][:12]}")
    cad = res["cadence"]
    if cad.get("verdict"):
        print(f"   такт: {cad['verdict']}")
    else:
        print(f"   такт: тиков {cad['ticks']} · окно {cad['span_days']} дн "
              f"({cad['first'][:19]} … {cad['last'][:19]}) · медианный зазор "
              f"{cad['gap_median_s']} с · максимальный {cad['gap_max_s']} с · "
              f"строк на тик {cad['rows_per_tick']}")
    if res["ts_unreadable_count"]:
        print(f"   НЕ ИЗМЕРЕНО отметок: {res['ts_unreadable_count']} — {res['ts_unreadable']}")


def _print_economics(res: dict) -> None:
    print("§3 ЭКОНОМИКА ОТКАЗА — что стоила бы «отказанная доходность», если бы её пустили")
    if res.get("verdict"):
        print(f"   {res['verdict']}")
        return
    print(f"   строк отказа: {res['refusals']} · с полной тройкой: {res['measured']} · "
          f"неполных: {res['incomplete']}")
    print(f"   ёмкость выхода, $: мин {res['exit_cap_min']} · медиана {res['exit_cap_median']} · "
          f"макс {res['exit_cap_max']}")
    print(f"   пол размера, $: {res['floors']}")
    print(f"   строк, где ёмкость ДОСТАЛА до пола: {res['rows_at_or_above_floor']}")
    print(f"   недобор в ЛУЧШИЙ момент окна: ×{res['shortfall_best_case_x']}")
    print(f"   годовой эдж на всю ёмкость, $: медиана {res['annual_edge_usd_median']} · "
          f"максимум {res['annual_edge_usd_max']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#161 RLI — информация публичного журнала отказов десков")
    ap.add_argument("--log", default=str(_DEFAULT_LOG),
                    help="путь к decision_log.jsonl (по умолчанию — журнал этого дерева)")
    ap.add_argument("--section", default="all",
                    choices=("all", "chain", "information", "economics"))
    ap.add_argument("--json", action="store_true", help="машинный вывод вместо текста")
    args = ap.parse_args(argv)

    path = Path(args.log)
    try:
        rows = load_rows(path)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2

    out: Dict[str, Any] = {"log": str(path)}
    rc = 0
    if args.section in ("all", "chain"):
        out["chain"] = check_chain(rows)
        if not out["chain"]["intact"]:
            rc = 1
    if args.section in ("all", "information"):
        out["information"] = measure_information(rows)
    if args.section in ("all", "economics"):
        out["economics"] = measure_economics(rows)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return rc

    print(f"#161 RLI — журнал {path}")
    print("=" * 96)
    if "chain" in out:
        _print_chain(out["chain"])
        print()
    if "information" in out:
        _print_information(out["information"])
        print()
    if "economics" in out:
        _print_economics(out["economics"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
