#!/usr/bin/env python3
"""Portfolio CIO — shadow-прогон и исторический replay (НИЧЕГО НЕ ИСПОЛНЯЕТ).

Две команды, обе read-only по отношению к деньгам:

``shadow``
    Собирает вход из живых артефактов (`data/current_positions.json`,
    `data/adapter_status.json`, `data/historical_apy/`), прогоняет
    ``portfolio_cio.decide`` и пишет `data/portfolio_cio.json` + печатает секцию
    владельца. Ни одна позиция не двигается: ступень «shadow» из §39–§50.

``replay``
    Прогоняет решение на исторических рядах БЕЗ заглядывания вперёд: на каждый
    день видны только замеры по этот день включительно. Сравнивает две книги —
    статическую (равные веса, как сегодня «раз выставили и держим») и книгу под
    управлением CIO — по чистой доходности ПОСЛЕ издержек, обороту и числу
    переходов. Главная цель §38 — не максимум APY на бумаге, а улучшение
    risk-adjusted realized net return.

Ограничения названы честно: исторических рядов в репозитории пять (data/historical_apy),
значит replay судит о пяти пулах, а не обо всей вселенной. Это узкий, но настоящий
замер; расширение — вопрос данных, а не кода.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.allocator.portfolio_cio import (  # noqa: E402
    DEFER,
    REBALANCE,
    decide,
    render_owner_section,
    save_snapshot,
)
from spa_core.allocator.rebalance_economics import TriggerParams  # noqa: E402

DATA = ROOT / "data"
HIST = DATA / "historical_apy"
SNAPSHOT = DATA / "portfolio_cio.json"

#: Ряд истории → имя протокола в книге. Явное соответствие, без угадывания по имени.
HIST_TO_PROTOCOL = {
    "aave_v3_usdc.json": "aave_v3",
    "compound_v3_usdc.json": "compound_v3",
    "morpho_blue_usdc.json": "morpho_blue",
    "sky_susds.json": "spark_susds",
    "yearn_v3_usdc.json": "yearn_v3",
}


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _history_map(window: int = 14) -> dict:
    """Последние ``window`` замеров APY по каждому ряду (percent)."""
    out: dict = {}
    for fname, proto in HIST_TO_PROTOCOL.items():
        rows = _load(HIST / fname, [])
        if isinstance(rows, list) and rows:
            out[proto] = [float(r["apy"]) for r in rows[-window:]
                          if isinstance(r, dict) and isinstance(r.get("apy"), (int, float))]
    return out


def cmd_shadow(args) -> int:
    pos_doc = _load(DATA / "current_positions.json", {})
    positions = {k: float(v["usd"]) for k, v in (pos_doc.get("positions_detail") or {}).items()
                 if isinstance(v, dict) and isinstance(v.get("usd"), (int, float))}
    if not positions:
        print("отказ: не из чего строить книгу — data/current_positions.json пуст")
        return 2

    coverage = pos_doc.get("feed_coverage") or {}
    apy_used = {k: float(v) for k, v in (coverage.get("apy_used_pct") or {}).items()
                if isinstance(v, (int, float))}
    apy_sources = dict(coverage.get("apy_sources") or {})
    capital = float(pos_doc.get("capital_usd") or 0.0)

    # Цель = уже одобренная аллокация (её считает существующий StrategyAllocator).
    # CIO НЕ считает целевые веса заново: это была бы вторая модель аллокации,
    # ровно то, что §3 задания запрещает.
    target_doc = _load(DATA / "last_approved_allocation.json", {})
    target = {k: float(v) for k, v in (target_doc.get("positions") or {}).items()
              if isinstance(v, (int, float))}
    if not target:
        print("отказ: нет одобренной цели (data/last_approved_allocation.json)")
        return 2

    d = decide(
        current_positions=positions,
        target_positions=target,
        displayed_apy_pct={**{p: apy_used.get(p) for p in set(positions) | set(target)}},
        apy_history=_history_map(),
        apy_sources=apy_sources,
        tvl_usd={},                 # живой TVL здесь не читаем ⇒ вход не финансируется
        tvl_evidenced=set(),        # fail-CLOSED: ни один вход не считается доказанным
        chains={},
        capital_usd=capital or sum(positions.values()),
        trigger_params=TriggerParams(),
    )
    generated_at = args.now or datetime.now(timezone.utc).isoformat()
    save_snapshot(d, str(SNAPSHOT), generated_at=generated_at)
    print(render_owner_section(d, capital_usd=capital))
    print()
    print(f"снимок: {SNAPSHOT.relative_to(ROOT)}  ·  отказов: {len(d.refusals)}")
    return 0


def _replay_series() -> tuple[list, dict]:
    """Общие даты по всем рядам + карта protocol → {date: apy}."""
    series: dict = {}
    for fname, proto in HIST_TO_PROTOCOL.items():
        rows = _load(HIST / fname, [])
        if isinstance(rows, list) and rows:
            series[proto] = {r["date"]: float(r["apy"]) for r in rows
                             if isinstance(r, dict) and isinstance(r.get("apy"), (int, float))}
    if not series:
        return [], {}
    common = sorted(set.intersection(*(set(v) for v in series.values())))
    return common, series


def cmd_replay(args) -> int:
    dates, series = _replay_series()
    if len(dates) < 60:
        print(f"отказ: истории слишком мало ({len(dates)} общих дней) — судить не о чем")
        return 2

    protos = sorted(series)
    capital = float(args.capital)
    equal = capital / len(protos)
    static_book = {p: equal for p in protos}       # «выставили раз и держим»
    cio_book = dict(static_book)

    static_yield = cio_yield = 0.0
    cio_costs = 0.0
    moves = deferred = 0
    turnover = 0.0
    # Ноль переходов — это ответ, только если названо ПОЧЕМУ. Копим лучший
    # наблюдённый выигрыш и причину отказа, иначе «0 сделок» неотличимо от
    # сломанного прогона.
    best_gain_pp = 0.0
    refusal_counts: dict = {}
    warmup = args.window

    for i, date in enumerate(dates):
        today = {p: series[p][date] for p in protos}
        # Доход за день начисляется по КНИГЕ НА НАЧАЛО дня — иначе решение
        # зарабатывало бы на ставке, которую ещё не видело (look-ahead).
        static_yield += sum(usd * today[p] / 100.0 / 365.0 for p, usd in static_book.items())
        cio_yield += sum(usd * today[p] / 100.0 / 365.0 for p, usd in cio_book.items())

        if i < warmup:
            continue
        history = {p: [series[p][d] for d in dates[max(0, i - warmup):i + 1]] for p in protos}
        # Цель на день: весь капитал в лучший наблюдаемый пул под потолком 40 %
        # (потолок берётся как ДАННОСТЬ политики, CIO его не выбирает).
        best = max(protos, key=lambda p: today[p])
        target = dict(cio_book)
        # Шаг к цели ограничен бюджетом оборота ЗА ОДИН переход (14 % < потолка 15 %).
        # Прыжок сразу на полный потолок концентрации упирался бы в анти-churn
        # каждый день — и «ноль сделок» означал бы кривую цель, а не разумный отказ.
        room = min(capital * 0.40,
                   sum(cio_book.values()),
                   cio_book.get(best, 0.0) + capital * 0.14)
        target[best] = room
        rest = sum(cio_book.values()) - room
        others = [p for p in protos if p != best]
        for p in others:
            target[p] = rest / len(others) if others else 0.0

        d = decide(
            current_positions=cio_book,
            target_positions=target,
            displayed_apy_pct=today,
            apy_history=history,
            apy_sources={p: "live" for p in protos},
            tvl_usd={p: 500_000_000.0 for p in protos},
            tvl_evidenced=set(protos),
            chains={p: args.chain for p in protos},
            capital_usd=capital,
            trigger_params=TriggerParams(),
        )
        if d.decision == REBALANCE:
            moves += 1
            cio_costs += d.switching_cost_usd
            turnover += d.turnover_usd
            cio_book = {p: float(target.get(p, 0.0)) for p in protos}
        elif d.decision == DEFER:
            deferred += 1
        gain = float(d.economics.get("gain_pp") or 0.0)
        best_gain_pp = max(best_gain_pp, gain)
        for r in (d.economics.get("reasons") or []):
            key = str(r).split(":")[0]
            refusal_counts[key] = refusal_counts.get(key, 0) + 1

    years = len(dates) / 365.0
    out = {
        "days": len(dates),
        "protocols": protos,
        "static_net_apy_pct": round(100.0 * static_yield / capital / years, 4),
        "cio_net_apy_pct": round(100.0 * (cio_yield - cio_costs) / capital / years, 4),
        "cio_gross_apy_pct": round(100.0 * cio_yield / capital / years, 4),
        "cio_costs_usd": round(cio_costs, 2),
        "moves": moves,
        "deferred": deferred,
        "turnover_usd": round(turnover, 2),
        "turnover_per_year": round(turnover / capital / years, 4),
        "best_gain_pp_seen": round(best_gain_pp, 4),
        "why_no_move": dict(sorted(refusal_counts.items(), key=lambda kv: -kv[1])),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    delta = out["cio_net_apy_pct"] - out["static_net_apy_pct"]
    print(f"\nразница ЧИСТОЙ доходности: {delta:+.2f} pp/год "
          f"(издержки ${out['cio_costs_usd']:,.0f} уже вычтены)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("shadow", help="решение на сегодняшнем снимке (ничего не двигает)")
    s.add_argument("--now", default=None, help="штамп времени снимка (ISO), по умолчанию — сейчас")
    s.set_defaults(func=cmd_shadow)
    r = sub.add_parser("replay", help="исторический прогон без look-ahead")
    r.add_argument("--capital", type=float, default=100_000.0)
    r.add_argument("--window", type=int, default=14, help="окно истории для устойчивости")
    r.add_argument("--chain", default="ethereum",
                   help="цепочка исполнения: она задаёт стоимость газа, а газ решает, "
                        "окупается ли переход вообще")
    r.set_defaults(func=cmd_replay)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
