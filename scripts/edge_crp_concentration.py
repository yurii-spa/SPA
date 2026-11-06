"""
scripts/edge_crp_concentration.py — #155 CRPC: CRP-Concentration Attribution.

ИСПОЛНЕНИЕ ЗАКАЗА #153 п. 2 дословно: «Если CRP применить к ДВУМ лучшим книгам
(susde_dn + points_farm) с прямой концентрацией 50/50, превысит ли APY [bt] 3.4 %?
(Проверка, что преимущество CRP идёт от ОТБОРА, а не только от снижения веса variant_d.)»

ДВА ВОПРОСА, и они РАЗНЫЕ — поэтому мерятся раздельно:

  (1) ПОРОГ. Превышает ли концентрированная раскладка пол RWA? Ответ — число рядом с
      хвостом, на TRAIN и на TEST отдельно; «превысила на TRAIN» ответом не является.

  (2) АТРИБУЦИЯ. Откуда взялось преимущество CRP над равным весом: из ИСКЛЮЧЕНИЯ плохой
      книги или из ОТБОРА среди остальных? Вопрос разрешается ДВУМЯ контрольными
      раскладками, которых у #153 не было:
        EW4  — равный вес по четырём книгам БЕЗ `variant_d` ⇒ «просто выкинуть плохую»;
        CRP4 — веса CRP по тем же четырём ⇒ «отбор СРЕДИ выживших».
      CRP5 ≈ EW4 означает, что всё преимущество было исключением, и отбора в нём нет.
      Разность CRP4 − EW4 и есть вклад ОТБОРА, измеренный отдельно от исключения.

ЧЕСТНАЯ РАМКА. Все числа [bt] — детерминированная фикстура (`aggressive_lab/fixtures.py`),
НЕ реализованный P&L. Хвост (maxDD) печатается рядом с каждой ставкой. Пошлина входа 96 bp
[конвенция #149] берётся у прибора #153, а не переобъявляется здесь. Пол RWA ЧИТАЕТСЯ из
существующей константы, а не вводится третьей копией — расхождение «3.4 %» заказа с
измеренным полом НАЗВАНО вслух, а не сглажено.

Третий исход (инв. #17): фикстура не материализована · ряд книги пуст · прибор #153 не
ввезён — всё это ОТКАЗ кодом 2 с названной причиной, никогда не ноль и не «порог не взят».
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_MODULE_ROOT = Path(__file__).resolve().parents[1]

# Пол RWA ЧИТАЕТСЯ, а не объявляется: вторая копия числа — это как рукав дрейфует от
# ставки, которая его обосновывает. Заказ #153 назвал «3.4 %»; измеренная константа
# соседнего прибора — своя, и обе печатаются рядом.
ORDER_FLOOR_PCT = 3.4            # то, что НАЗВАЛ заказ #153 п. 2 (его мерка, дословно)

TOP2 = ("susde_dn", "points_farm")
EXCLUDED_IN_ATTRIBUTION = "variant_d"


class Unmeasured(Exception):
    """Прибор не смог ответить. Не подменяется нулём и не выдаётся за «порог не взят»."""


def _import_root() -> None:
    if str(_MODULE_ROOT) not in sys.path:
        sys.path.insert(0, str(_MODULE_ROOT))


def load_crp_module():
    """Прибор #153 ввозится ЦЕЛИКОМ: его шов, пошлина и симулятор — одна копия."""
    path = _MODULE_ROOT / "scripts" / "edge_crisis_recovery_profile.py"
    if not path.is_file():
        raise Unmeasured(f"прибор #153 не найден: {path}")
    spec = importlib.util.spec_from_file_location("edge_crisis_recovery_profile", path)
    if spec is None or spec.loader is None:
        raise Unmeasured(f"прибор #153 не загружается: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        raise Unmeasured(f"прибор #153 не исполнен: {type(exc).__name__}: {exc}") from exc
    return mod


def measured_rwa_floor_pct() -> Tuple[Optional[float], str]:
    """Пол RWA из существующей константы. Нечитаемость — третий исход, а не 3.4."""
    path = _MODULE_ROOT / "scripts" / "edge_cash_sleeve_frontier.py"
    if not path.is_file():
        return None, f"НЕ ИЗМЕРЕНО: {path} отсутствует"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("RWA_FLOOR"):
                return float(line.split("=", 1)[1].split("#")[0].strip()) * 100.0, str(path)
    except (OSError, ValueError, IndexError) as exc:
        return None, f"НЕ ИЗМЕРЕНО: {type(exc).__name__}: {exc}"
    return None, f"НЕ ИЗМЕРЕНО: имени RWA_FLOOR в {path} нет"


# ── раскладки ─────────────────────────────────────────────────────────────────────────────

def build_allocations(CRP, crp_weights: Dict[str, float],
                      books: List[str]) -> Dict[str, Dict[str, float]]:
    """Пять раскладок на одной панели. Каждая отвечает на СВОЙ вопрос."""
    surviving = [b for b in books if b != EXCLUDED_IN_ATTRIBUTION]
    crp4_raw = {b: crp_weights.get(b, 0.0) for b in surviving}
    total4 = sum(crp4_raw.values())
    return {
        "EW-5": {b: 1.0 / len(books) for b in books},
        "CRP-5": dict(crp_weights),
        "TOP2-50/50": {b: 0.5 for b in TOP2},
        f"EW-4 (без {EXCLUDED_IN_ATTRIBUTION})": {b: 1.0 / len(surviving) for b in surviving},
        f"CRP-4 (без {EXCLUDED_IN_ATTRIBUTION})": (
            {b: w / total4 for b, w in crp4_raw.items()} if total4 > 0 else {}),
    }


def all_pairs_sweep(CRP, series_map: Dict[str, list], books: List[str],
                    periods: Dict[str, Tuple[datetime.date, datetime.date]]) -> List[dict]:
    """ВСЕ пары книг 50/50, с рангом каждой пары по TRAIN-скорости восстановления.

    Контроль против черри-пика: пара заказа — ОДНА из десяти, и без остальных девяти
    нельзя сказать, работает ли ОТБОР или просто КОНЦЕНТРАЦИЯ. Ранг считается на TRAIN,
    результат печатается на TEST: если лучшая по TRAIN пара не лучшая на TEST, это
    сказано вслух, а не сглажено."""
    import itertools
    out = []
    for a, b in itertools.combinations(sorted(books), 2):
        w = {a: 0.5, b: 0.5}
        row = {"pair": [a, b]}
        for pname, (s0, s1) in periods.items():
            row[pname] = CRP.run_portfolio(series_map, w, s0, s1)
        out.append(row)
    return out


def top2_by_train_velocity(summary: dict) -> List[str]:
    """Две лучшие книги ПО ЗАМЕРУ TRAIN, а не по памяти заказа. Расхождение печатается."""
    ranked = sorted(summary.items(),
                    key=lambda kv: (kv[1]["velocity"] if kv[1]["velocity"] != float("inf")
                                    else float("1e18")),
                    reverse=True)
    return [k for k, _ in ranked[:2]]


# ── отчёт ─────────────────────────────────────────────────────────────────────────────────

def build_report(data_dir: Path) -> dict:
    CRP = load_crp_module()
    # Нечитаемая панель — ТРЕТИЙ ИСХОД с названной причиной, а не трассировка наружу:
    # прибор #153 поднимает FileNotFoundError, и выпущенная наружу она неотличима для
    # вызывающего от поломки самого прибора (инв. #17).
    try:
        base = CRP.crp_report(data_dir)
        books = list(base["books"])
        series_map = {b: CRP.load_backtest_series(data_dir, b) for b in books}
    except (OSError, ValueError, KeyError) as exc:
        raise Unmeasured(
            f"панель {data_dir} не прочитана прибором #153 — "
            f"{type(exc).__name__}: {exc}") from exc
    empty = [b for b, s in series_map.items() if not s]
    if empty:
        raise Unmeasured(f"ряды пусты у книг {empty} — ответ о панели НЕ ВЫДАЁТСЯ")
    missing_top2 = [b for b in TOP2 if b not in series_map]
    if missing_top2:
        raise Unmeasured(f"книг заказа нет на панели: {missing_top2}")

    allocs = build_allocations(CRP, base["crp_weights"], books)
    bt_end = datetime.date(2026, 5, 31)
    bt_start = datetime.date(2024, 7, 1)
    periods = {
        "TRAIN 2024-07..2025-06": (bt_start, CRP.TRAIN_END),
        "TEST 2025-07..2026-05": (CRP.TEST_START, bt_end),
        "FULL 843 дня": (bt_start, bt_end),
    }
    results: Dict[str, Dict[str, Tuple[float, float, float]]] = {}
    for pname, (a, b) in periods.items():
        results[pname] = {an: CRP.run_portfolio(series_map, w, a, b)
                          for an, w in allocs.items() if w}

    pairs = all_pairs_sweep(CRP, series_map, books, periods)
    floor_measured, floor_src = measured_rwa_floor_pct()
    return {
        "idea": "CRPC — CRP-Concentration Attribution",
        "order": "#153 п. 2",
        "data_dir": str(data_dir),
        "books": books,
        "allocations": allocs,
        "crp_weights_train": base["crp_weights"],
        "top2_order": list(TOP2),
        "top2_measured": top2_by_train_velocity(base["recovery_summary"]),
        "results": results,
        "pairs": pairs,
        "velocity_rank": [k for k, _ in sorted(
            base["recovery_summary"].items(),
            key=lambda kv: (kv[1]["velocity"] if kv[1]["velocity"] != float("inf")
                            else float("1e18")), reverse=True)],
        "toll_bps": CRP.ENTRY_TOLL_BPS,
        "floor_order_pct": ORDER_FLOOR_PCT,
        "floor_measured_pct": floor_measured,
        "floor_measured_source": floor_src,
        "evidence_level": "L0 — детерминированная фикстура [bt], НЕ реализованный P&L",
    }


def print_report(r: dict) -> None:
    print("=" * 92)
    print("  #155 CRPC — CRP-Concentration Attribution   [bt — все числа бэктестовые]")
    print(f"  ИСПОЛНЕНИЕ ЗАКАЗА {r['order']}: берёт ли концентрация пол RWA, и от ОТБОРА ли")
    print(f"  преимущество CRP — или только от снижения веса `{EXCLUDED_IN_ATTRIBUTION}`")
    print("=" * 92)
    print(f"  панель: {len(r['books'])} книг · пошлина входа {r['toll_bps']} bp [#149]")
    print(f"  пол заказа: {r['floor_order_pct']:.2f} %/год · пол ИЗМЕРЕННЫЙ: "
          f"{('%.2f %%/год' % r['floor_measured_pct']) if r['floor_measured_pct'] is not None else r['floor_measured_source']}")
    print(f"  источник измеренного пола: {r['floor_measured_source']}")
    print()
    print("  две лучшие книги: заказ назвал " + str(r["top2_order"])
          + " · замер TRAIN даёт " + str(r["top2_measured"])
          + ("  (СОВПАЛИ)" if sorted(r["top2_order"]) == sorted(r["top2_measured"])
             else "  ⚠️ РАСХОДЯТСЯ — вердикт считается по ЗАКАЗУ, расхождение названо"))
    print()
    print("── Веса раскладок [bt] ────────────────────────────────────────────────────────────")
    for an, w in r["allocations"].items():
        if not w:
            continue
        print(f"  {an:<26} " + "  ".join(f"{k} {v*100:.1f}%" for k, v in sorted(w.items())))
    print()
    for pname, res in r["results"].items():
        print(f"── {pname} [bt] ───────────────────────────────────────────────────────")
        print(f"  {'раскладка':<26}{'APY %':>9}{'maxDD %':>10}{'Calmar':>9}   против пола")
        print(f"  {'-'*26}{'-'*9:>9}{'-'*10:>10}{'-'*9:>9}   {'-'*18}")
        for an, (apy, dd, cal) in res.items():
            cal_s = f"{cal:9.3f}" if cal == cal else "     NONE"
            fl = r["floor_order_pct"]
            verd = "ВЫШЕ" if apy > fl else "НИЖЕ"
            print(f"  {an:<26}{apy:9.2f}{dd:10.2f}{cal_s}   {verd} {fl:.2f} %")
        print()

    # атрибуция
    test = r["results"].get("TEST 2025-07..2026-05") or {}
    full = r["results"].get("FULL 843 дня") or {}
    ew4k = f"EW-4 (без {EXCLUDED_IN_ATTRIBUTION})"
    crp4k = f"CRP-4 (без {EXCLUDED_IN_ATTRIBUTION})"
    print("── АТРИБУЦИЯ: исключение против отбора [bt] ───────────────────────────────────────")
    for label, res in (("TEST", test), ("FULL", full)):
        if not all(k in res for k in ("EW-5", "CRP-5", ew4k, crp4k)):
            print(f"  {label}: НЕ ИЗМЕРЕНО — не все контрольные раскладки посчитаны")
            continue
        ew5, crp5, ew4, crp4 = (res["EW-5"][0], res["CRP-5"][0], res[ew4k][0], res[crp4k][0])
        print(f"  {label}:  CRP-5 − EW-5 = {crp5-ew5:+.2f} pp   (всё преимущество CRP)")
        print(f"         EW-4 − EW-5 = {ew4-ew5:+.2f} pp   (вклад ИСКЛЮЧЕНИЯ "
              f"`{EXCLUDED_IN_ATTRIBUTION}`)")
        print(f"         CRP-4 − EW-4 = {crp4-ew4:+.2f} pp   (вклад ОТБОРА среди выживших)")
    print()
    print("── КОНТРОЛЬ ПРОТИВ ЧЕРРИ-ПИКА: ВСЕ 50/50-пары ─────────────────────────────────────")
    print(f"  ранг книг по TRAIN-скорости восстановления: {r['velocity_rank']}")
    tkey = "TEST 2025-07..2026-05"
    fl = r["floor_order_pct"]
    rows = sorted(r.get("pairs") or [], key=lambda x: -x[tkey][0])
    print(f"  {'пара':<30}{'TEST APY %':>12}{'TEST maxDD %':>14}{'Calmar':>9}  порог")
    print(f"  {'-'*30}{'-'*12:>12}{'-'*14:>14}{'-'*9:>9}  {'-'*6}")
    order_pair = sorted(r["top2_order"])
    for row in rows:
        apy, dd, cal = row[tkey]
        cal_s = f"{cal:9.3f}" if cal == cal else "     NONE"
        mark = "  ← пара ЗАКАЗА" if sorted(row["pair"]) == order_pair else ""
        print(f"  {'+'.join(row['pair']):<30}{apy:12.2f}{dd:14.2f}{cal_s}"
              f"  {'ВЫШЕ' if apy > fl else 'НИЖЕ'}{mark}")
    above = [row for row in rows if row[tkey][0] > fl]
    print(f"  пар выше пола {fl:.2f} % на TEST: {len(above)} из {len(rows)}")
    if rows:
        best = rows[0]
        print(f"  лучшая на TEST: {'+'.join(best['pair'])} ({best[tkey][0]:.2f} %) — "
              + ("ЭТО пара заказа" if sorted(best["pair"]) == order_pair
                 else "НЕ пара заказа (значит выбор по TRAIN оптимумом TEST не является)"))
    print()
    print("  ЧЕСТНЫЕ ОГОВОРКИ:")
    print("  (а) [L0] детерминированная фикстура, НЕ реализованный P&L; хвост рядом со ставкой.")
    print("  (б) Веса CRP выбраны на TRAIN (кризисы 2024-08 и 2025-10); TEST содержит третий")
    print("      кризис (rsETH 2026-04) — это честный OOS, но ОДИН, а не распределение.")
    print("  (в) Пол RWA — конвенция, одинаково льстящая ВСЕМ раскладкам; абсолютные APY она")
    print("      завышает, сравнение между раскладками не портит.")
    print("  (г) Две лучшие книги названы ЗАКАЗОМ; замер TRAIN печатается рядом, чтобы выбор")
    print("      не выглядел подогнанным под результат.")
    print("  (д) `points_farm` — класс D, форма риска `incentive_decay`: сам ростер называет")
    print("      его «DECAYS — not a durable edge». Вес 50 % в нём есть концентрация в")
    print("      затухающем стимуле, и продавать её как низкий риск ЗАПРЕЩЕНО, сколько бы")
    print("      ни был мал её хвост на фикстуре. Вторая половина — хвост, напечатанный рядом.")
    print("  (е) IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · RiskPolicy v1.0 не тронута ·")
    print("      живой трек не открывался · сайзер на ЖИВЫХ марках НЕ предлагается (запрет #152).")
    print("  (ж) Пара заказа — ОДНА из 10; таблица всех пар напечатана выше именно поэтому.")
    print("=" * 92)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#155 CRPC — исполнение заказа #153 п. 2")
    ap.add_argument("--data-dir", default=None,
                    help="каталог панели; без него материализуется фикстура во временный каталог")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    _import_root()
    try:
        if a.data_dir:
            rep = build_report(Path(a.data_dir))
        else:
            try:
                from spa_core.strategy_lab.aggressive_lab.fixtures import materialize
            except Exception as exc:  # noqa: BLE001
                print(f"НЕ ИЗМЕРЕНО: фикстура не ввезена: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                return 2
            with tempfile.TemporaryDirectory() as tmp:
                rep = build_report(materialize(Path(tmp)))
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        print_report(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
