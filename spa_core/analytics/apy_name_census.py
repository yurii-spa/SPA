"""Перепись: какое число, названное «APY», какой экономической величиной является.

Единственный читатель объявления `apy_kinds`. Отвечает на §5 приказа владельца
«Portfolio CIO» — «Не допускать использования одного названия APY для разных
экономических показателей» — и делает это КАЖДЫЙ ЦИКЛ, а не один раз: род
числа есть свойство кода, а вот СОСТАВ чисел и их расхождение меняются ежедневно.

Четыре оси, и каждая несёт СВОЙ бит
===================================
1. **НЕОБЪЯВЛЕННОЕ** — число с «apy» в имени, у которого рода нет (fail-CLOSED).
   Новое число обязано объявить свой род при рождении.
2. **ОДИН ПРЕДМЕТ — НЕСКОЛЬКО ЧИСЕЛ** — сколько разных ставок КНИГИ напечатано в
   одном цикле, каков разброс и ЧЕМ он объясняется (знаменатель · окно).
   Числа не «врут» — они отвечают на разные вопросы; незаконно то, что вопрос не
   назван рядом с ответом.
3. **ПАРИТЕТ С КНИГОЙ** — ставка, пересчитанная из позиций и наблюдённых ставок,
   против напечатанной. Ось ПЕРЕКРЁСТНАЯ: `apy_today` пишет цикл, а книгу —
   аналитика, и до этой переписи их никто не сверял.
4. **ОКНО И ОСНОВАНИЕ** — стоит ли среднее по времени на том населении, которое
   напечатано рядом с ним, и сколько в этом окне НЕдоказанных баров (ADR-580 C2:
   разогрев и бэктест не имеют права нести метку замера).

Три исхода различимы у каждой оси (инв. #17): измерено · измерено и равно нулю ·
НЕ ИЗМЕРЕНО с названной причиной. Ноль находок печатается ЧИСЛОМ, а не молчанием.

Прибор только ЧИТАЕТ: ни одного производителя не правит, капитал не двигает,
RiskPolicy не касается. stdlib-only, LLM FORBIDDEN.

Перемер руками::

    python3 -m spa_core.analytics.apy_name_census --data-dir <путь>/data

Коды возврата: 0 — находок нет · 1 — находки · 2 — НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import apy_kinds
from .apy_kinds import ApyKind

ENGINE = "apy_name_census"

#: Допуск сверки ставок, процентные пункты. Напечатанные числа округлены до 4-го
#: знака, а `apy_today` цикл считает через дневной доход, а не через Σ(вес×ставка)
#: — поэтому ноль здесь был бы требованием не к знаменателю, а к порядку
#: округления. 0.02 пп = 2 б.п.: меньше любой смены знаменателя (кэш 6.8 % книги
#: даёт 0.31 пп) и больше любого округления.
RATE_TOLERANCE_PP = 0.02


def _num(v: Any) -> Optional[float]:
    """float или None; bool и NaN/inf числами не считаются."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _is_apy_named(key: str) -> bool:
    return "apy" in key.lower()


def _walk(node: Any, path: str, numbers: Dict[str, List[float]],
          non_numeric: Dict[str, str]) -> None:
    """Собрать все apy-именованные листья. Индексы списков → «[]»."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}/{k}"
            if _is_apy_named(k):
                n = _num(v)
                if n is not None:
                    numbers.setdefault(p, []).append(n)
                elif v is None:
                    # «наблюдения нет» — ЗАКОННАЯ форма (инв. #17), и числом
                    # она не является: судить её родом нечего.
                    non_numeric.setdefault(p, "None (наблюдения нет)")
                else:
                    non_numeric.setdefault(p, type(v).__name__)
            _walk(v, p, numbers, non_numeric)
    elif isinstance(node, list):
        for item in node:
            _walk(item, f"{path}[]", numbers, non_numeric)


def _book_from_attribution(section: Any) -> Tuple[Optional[float], Optional[float], str]:
    """(Σ размещено, Σ годовой доход, причина-отказа) из секции атрибуции."""
    if not isinstance(section, dict) or section.get("status") != "OK":
        got = section.get("status") if isinstance(section, dict) else type(section).__name__
        return None, None, f"секция атрибуции не OK (status={got!r})"
    rows = section.get("contributions")
    if not isinstance(rows, list) or not rows:
        return None, None, "в секции атрибуции нет ни одной позиции"
    deployed = 0.0
    annual = 0.0
    for r in rows:
        if not isinstance(r, dict):
            return None, None, "строка атрибуции не является записью"
        usd = _num(r.get("allocated_usd"))
        rate = _num(r.get("apy_pct"))
        if usd is None or rate is None:
            return None, None, (f"у позиции {r.get('adapter_id')!r} нет числа "
                                "allocated_usd или apy_pct")
        deployed += usd
        annual += usd * rate / 100.0
    if deployed <= 0:
        return None, None, "размещено $0 — ставки у нуля не существует"
    return deployed, annual, ""


def _nav(equity_doc: Any) -> Tuple[Optional[float], str]:
    bars = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
    bars = [b for b in (bars or []) if isinstance(b, dict)]
    if not bars:
        return None, "в equity-ряде нет ни одного бара"
    v = _num(bars[-1].get("equity", bars[-1].get("close_equity")))
    if v is None or v <= 0:
        return None, "у последнего бара нет положительного equity"
    return v, ""


def _ring_size() -> Tuple[Optional[int], str]:
    """Размер кольца у ПРОИЗВОДИТЕЛЯ среднего — через импорт, не литералом.

    Своя копия числа означала бы, что перепись сверяет окно с СОБСТВЕННЫМ
    представлением о нём, а не с тем, на котором стои́т среднее.
    """
    try:
        from .portfolio_volatility_tracker import RING_BUFFER_SIZE
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return None, f"производитель среднего не ввезён: {type(exc).__name__}: {exc}"
    n = _num(RING_BUFFER_SIZE)
    if n is None or n <= 0:
        return None, f"RING_BUFFER_SIZE={RING_BUFFER_SIZE!r} окном не является"
    return int(n), ""


def _evidenced_tail(equity_doc: Any, window: int) -> Tuple[Optional[int], Optional[int], str]:
    """(баров в окне, из них НЕдоказанных, причина-отказа) по хвосту трека."""
    bars = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
    bars = [b for b in (bars or []) if isinstance(b, dict)
            and _num(b.get("apy_today")) is not None]
    if not bars:
        return None, None, "в equity-ряде нет баров с apy_today"
    tail = bars[-window:]
    unevidenced = sum(1 for b in tail if b.get("evidenced") is not True)
    return len(tail), unevidenced, ""


def measure(equity_doc: Any, sections: Any) -> Dict[str, Any]:
    """Перепись по ОДНОМУ циклу: трек + уже собранные секции того же прогона.

    Сверять числа РАЗНЫХ циклов было бы другим вопросом (и ответ на него
    смешивал бы расхождение производителей с возрастом артефакта), поэтому
    секции принимаются ВХОДОМ, а не читаются с диска.
    """
    rep: Dict[str, Any] = {"status": "OK", "engine": ENGINE}

    broken = apy_kinds.validate()
    if broken:
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = ["объявление родов не выдерживает своего контракта: "
                             + "; ".join(broken)]
        rep["headline"] = "НЕ ИЗМЕРЕНО: сломано само объявление родов"
        return rep

    numbers: Dict[str, List[float]] = {}
    non_numeric: Dict[str, str] = {}
    _walk(sections, "sections", numbers, non_numeric)
    bars = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
    bars = [b for b in (bars or []) if isinstance(b, dict)]
    if bars:
        _walk(bars[-1], "equity_curve_daily/daily[]", numbers, non_numeric)

    unmeasured: List[str] = []
    findings: List[str] = []

    # ── ось 1: необъявленное ────────────────────────────────────────────────
    declared: Dict[str, Tuple[ApyKind, List[float]]] = {}
    undeclared: List[Dict[str, Any]] = []
    for path, vals in sorted(numbers.items()):
        k = apy_kinds.kind_of(path)
        if k is None:
            undeclared.append({"path": path, "n": len(vals), "sample": vals[0]})
        else:
            declared[path] = (k, vals)
    rep["numbers_found"] = sum(len(v) for v in numbers.values())
    rep["paths_found"] = len(numbers)
    rep["paths_declared"] = len(declared)
    rep["undeclared"] = undeclared
    if not numbers:
        unmeasured.append("ни одного apy-именованного числа не найдено ВОВСЕ — "
                          "перепись не о нуле, а о непрочитанном входе")
    if undeclared:
        findings.append(f"НЕОБЪЯВЛЕННЫХ путей {len(undeclared)}: "
                        + ", ".join(u["path"] for u in undeclared))

    # Имена, НЕ являющиеся числом, перепись родом не судит — и говорит это вслух.
    rep["non_numeric_names"] = [{"path": p, "type": t}
                                for p, t in sorted(non_numeric.items())]

    # ── ось 2: один предмет — несколько чисел ───────────────────────────────
    book_rates: List[Dict[str, Any]] = []
    for path, (k, vals) in sorted(declared.items()):
        if k.subject == "portfolio" and k.is_rate:
            for v in vals:
                book_rates.append({"path": path, "kind": k.kind, "value_pct": v,
                                   "denominator": k.denominator, "window": k.window,
                                   "owner_term": k.owner_term})
    rep["book_rates"] = book_rates
    distinct = sorted({round(r["value_pct"], 4) for r in book_rates})
    rep["book_rate_values"] = distinct
    if len(distinct) >= 2:
        spread = max(distinct) - min(distinct)
        rep["book_rate_spread_pp"] = round(spread, 4)
        reasons = sorted({f"{r['denominator']}/{r['window']}" for r in book_rates})
        rep["book_rate_spread_reason"] = ("разные знаменатель/окно: "
                                          + ", ".join(reasons))
        findings.append(
            f"ОДИН ПРЕДМЕТ — {len(distinct)} ЧИСЛА: ставка книги напечатана как "
            + " · ".join(f"{v:.4f} %" for v in distinct)
            + f" (разброс {spread:.4f} пп); объясняется знаменателем и окном, "
              "но рядом с числами это не напечатано"
        )
    elif len(distinct) == 1:
        rep["book_rate_spread_pp"] = 0.0
    else:
        unmeasured.append("ни одной ставки КНИГИ не найдено — разброс у пустого "
                          "набора не существует")

    # ── ось 3: паритет с книгой ─────────────────────────────────────────────
    parity: Dict[str, Any] = {}
    attribution = sections.get("yield_attribution_tracker") if isinstance(sections, dict) else None
    deployed, annual, why = _book_from_attribution(attribution)
    nav, why_nav = _nav(equity_doc)
    if deployed is None:
        parity["unmeasured"] = f"книга не прочитана: {why}"
        unmeasured.append(f"паритет не измерен: {why}")
    else:
        parity["deployed_usd"] = round(deployed, 2)
        parity["annual_yield_usd"] = round(annual, 4)
        recomputed_deployed = annual / deployed * 100.0
        parity["recomputed_on_deployed_pct"] = round(recomputed_deployed, 4)
        for path, (k, vals) in sorted(declared.items()):
            if k.kind != "portfolio_rate_on_deployed":
                continue
            for v in vals:
                d = abs(v - recomputed_deployed)
                parity.setdefault("checks", []).append(
                    {"path": path, "printed_pct": v,
                     "recomputed_pct": round(recomputed_deployed, 4),
                     "delta_pp": round(d, 4),
                     "verdict": "ok" if d <= RATE_TOLERANCE_PP else "MISMATCH"})
                if d > RATE_TOLERANCE_PP:
                    findings.append(f"ПАРИТЕТ: {path} печатает {v:.4f} %, "
                                    f"пересчёт из книги даёт "
                                    f"{recomputed_deployed:.4f} % "
                                    f"(расхождение {d:.4f} пп)")
        if nav is None:
            parity["nav_unmeasured"] = why_nav
            unmeasured.append(f"ставка на NAV не сверена: {why_nav}")
        else:
            parity["nav_usd"] = round(nav, 2)
            recomputed_nav = annual / nav * 100.0
            parity["recomputed_on_nav_pct"] = round(recomputed_nav, 4)
            parity["cash_drag_pp"] = round(recomputed_deployed - recomputed_nav, 4)
            for path, (k, vals) in sorted(declared.items()):
                if k.kind != "portfolio_rate_on_nav":
                    continue
                for v in vals:
                    d = abs(v - recomputed_nav)
                    parity.setdefault("checks", []).append(
                        {"path": path, "printed_pct": v,
                         "recomputed_pct": round(recomputed_nav, 4),
                         "delta_pp": round(d, 4),
                         "verdict": "ok" if d <= RATE_TOLERANCE_PP else "MISMATCH"})
                    if d > RATE_TOLERANCE_PP:
                        findings.append(
                            f"ПАРИТЕТ: {path} печатает {v:.4f} %, пересчёт из "
                            f"книги по NAV даёт {recomputed_nav:.4f} % "
                            f"(расхождение {d:.4f} пп)")
    rep["parity"] = parity

    # ── ось 4: окно и основание доказанности ────────────────────────────────
    window_rep: Dict[str, Any] = {}
    mean_paths = [p for p, (k, _) in declared.items()
                  if k.kind == "portfolio_rate_time_mean"]
    if not mean_paths:
        window_rep["unmeasured"] = ("среднего по времени в этом цикле не "
                                    "напечатано — окно у отсутствующего числа "
                                    "не существует")
    else:
        ring, why_ring = _ring_size()
        if ring is None:
            window_rep["unmeasured"] = why_ring
            unmeasured.append(f"окно среднего не измерено: {why_ring}")
        else:
            window_rep["window_bars"] = ring
            vol = sections.get("portfolio_volatility_tracker") if isinstance(sections, dict) else None
            offered = _num((vol or {}).get("n_readings")) if isinstance(vol, dict) else None
            if offered is None:
                window_rep["offered_unmeasured"] = ("производитель не печатает "
                                                    "n_readings — население рядом "
                                                    "с числом не названо вовсе")
                unmeasured.append("население среднего не измерено: нет n_readings")
            else:
                window_rep["offered_readings"] = int(offered)
                if int(offered) > ring:
                    findings.append(
                        f"ОКНО НЕ НАЗВАНО: рядом со средним напечатано "
                        f"n_readings={int(offered)}, а само среднее стои́т на "
                        f"ПОСЛЕДНИХ {ring} чтениях (кольцо производителя) — "
                        "число и его население описывают разные множества")
                window_rep["population_matches_window"] = int(offered) <= ring
            n_tail, unev, why_tail = _evidenced_tail(equity_doc, ring)
            if n_tail is None:
                window_rep["evidence_unmeasured"] = why_tail
                unmeasured.append(f"основание среднего не измерено: {why_tail}")
            else:
                window_rep["bars_in_window"] = n_tail
                window_rep["unevidenced_in_window"] = unev
                if unev:
                    findings.append(
                        f"ОСНОВАНИЕ: в окне среднего {unev} из {n_tail} баров "
                        "НЕ доказаны (разогрев/реконструкция) — ADR-580 C2 "
                        "запрещает им нести метку замера")
    rep["window"] = window_rep

    rep["findings"] = findings
    rep["unmeasured"] = unmeasured
    if unmeasured and not findings:
        rep["verdict"] = "UNMEASURED"
        rep["headline"] = f"НЕ ИЗМЕРЕНО ({len(unmeasured)}): " + unmeasured[0]
    elif findings:
        rep["verdict"] = "FINDINGS"
        rep["headline"] = (f"находок {len(findings)}, не измерено "
                           f"{len(unmeasured)}: {findings[0]}")
    else:
        rep["verdict"] = "clean"
        rep["headline"] = (f"родов {len(apy_kinds.KINDS)}, путей "
                           f"{rep['paths_declared']}, необъявленных 0, "
                           "расхождений 0 — измерено и равно нулю")
    return rep


def _load(path: Path) -> Tuple[Any, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: {type(exc).__name__}: {exc}"


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ or "")
    ap.add_argument("--data-dir", required=True,
                    help="каталог data/ (прод или песочница)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    args = ap.parse_args(argv)

    d = Path(args.data_dir)
    equity, why_e = _load(d / "equity_curve_daily.json")
    summary, why_s = _load(d / "analytics_summary.json")
    if equity is None or summary is None:
        print(f"НЕ ИЗМЕРЕНО: {why_e or why_s}", file=sys.stderr)
        return 2
    sections = summary.get("sections") if isinstance(summary, dict) else None
    if not isinstance(sections, dict):
        print("НЕ ИЗМЕРЕНО: в analytics_summary.json нет раздела sections",
              file=sys.stderr)
        return 2
    # Вне цикла секции и трек читаются с ДИСКА, то есть могут быть из разных
    # прогонов. Смешать их значило бы выдать возраст артефакта за расхождение
    # производителей — поэтому моменты сверяются, и расхождение есть ОТКАЗ.
    stamp_s = (summary or {}).get("generated_at")
    stamp_e = (equity or {}).get("generated_at")
    if stamp_s and stamp_e and str(stamp_s)[:10] != str(stamp_e)[:10]:
        print(f"НЕ ИЗМЕРЕНО: сводка снята {stamp_s}, трек {stamp_e} — "
              "это разные прогоны, и их расхождение не о именах",
              file=sys.stderr)
        return 2

    rep = measure(equity, sections)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"ПЕРЕПИСЬ ИМЁН APY ({d}) — {rep['verdict']}")
        print(f"  {rep['headline']}")
        for key in ("findings", "unmeasured"):
            for line in rep.get(key) or []:
                print(f"  · {line}")
        br = rep.get("book_rates") or []
        if br:
            print("  ставки КНИГИ этого цикла:")
            for r in br:
                print(f"    {r['value_pct']:>9.4f} %  {r['kind']:28s}"
                      f" знаменатель={r['denominator']} окно={r['window']}"
                      f"  ← {r['path']}")
        p = rep.get("parity") or {}
        if "cash_drag_pp" in p:
            print(f"  цена кэша: {p['cash_drag_pp']:.4f} пп "
                  f"(размещено ${p['deployed_usd']:,.0f} из NAV ${p['nav_usd']:,.0f})")
    if rep["verdict"] == "UNMEASURED":
        return 2
    return 1 if rep.get("findings") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
