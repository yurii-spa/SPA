#!/usr/bin/env python3
"""Сколько доходности стоит наш лимит 20 % на одно имя — и что за это платит хвост.

Решение владельца 2026-08-08, **вариант A** карточки
`own-rnd-duty-is-concentration-adr055`:

    «Признать, что главная ручка — концентрация, и следующим шагом честно измерить ЕЁ САМУ:
     сколько доходности стоит наш лимит 20 % на одно имя, и что происходит с хвостом
     (просадкой), если его поднять до 25 % или 30 % на T2.»

Владелец назвал вариант, но не назвал сетку уровней. Взята сетка из примера в самой карточке:
**20 / 25 / 30 %**, плюс «без потолка» как верхняя опорная точка. 20 % — сегодняшний лимит T2
RiskPolicy v1.0.

═══════════════════════════════════════════════════════════════════════════════════════════
ЧТО ЭТОТ ЗАМЕР НЕ ДЕЛАЕТ
═══════════════════════════════════════════════════════════════════════════════════════════
* `IS_ADVISORY=True`, `OUTSIDE_RISKPOLICY=True`, evidence **L0** (бэктест на реальной истории,
  не живые деньги). Капитал не двигается, RiskPolicy v1.0 не меняется ни строкой.
* Изменение порогов RiskPolicy возможно ТОЛЬКО отдельным ADR и ТОЛЬКО отдельным решением
  владельца. Этот файл считает цену вопроса, он ничего не предлагает включить.

═══════════════════════════════════════════════════════════════════════════════════════════
ПРЕМИССА КАРТОЧКИ ИЗМЕНИЛАСЬ, ПОКА ОНА ЖДАЛА ОТВЕТА — И ЭТО НАДО ЧИТАТЬ ПЕРЕД ТАБЛИЦЕЙ
═══════════════════════════════════════════════════════════════════════════════════════════
Карточка опиралась на вывод записи #43: «признак демоушена — сноска (разброс 1.29), работает
доля времени (4.72)». **2026-08-08 запись #44 этот вывод ОПРОВЕРГЛА:** при ТОЧНО выровненной
duty 18.6 % смена одного лишь признака двигает ΔCalmar на **4.07** (M=1) и на **7.40** (M=20).
1.29 у #43 оказался разбросом между тремя разновидностями ОДНОГО признака (доходности книги),
а не между признаками.

Что это меняет для настоящего замера: тезис «все семь правил крутят ОДНУ ручку» больше не
верен — ручек как минимум две, и обе значимые. Сам вопрос владельца от этого не обесценился,
а стал ТОЧНЕЕ: теперь мы меряем вклад концентрации, ЗНАЯ, что признак — не сноска, и потому
обязаны показать цену потолка при НЕСКОЛЬКИХ признаках, а не при одном.

Поэтому таблица считается для четырёх правил сразу (raw / #40 XSD / #39 CDR / #45 XVD).
Если бы вывод #43 был верен, строки правил внутри одного потолка почти совпали бы.

═══════════════════════════════════════════════════════════════════════════════════════════
ЧТО ИМЕННО СЧИТАЕТСЯ
═══════════════════════════════════════════════════════════════════════════════════════════
Панель, длина истории, окно L=60, модель издержек по обороту, аллокатор перераспределения —
всё унаследовано от #39/#40 буква в букву (`edge_capital_recycling`, `edge_cross_sectional_
demotion`, `edge_drift_gated_overlay`). Здесь меняется РОВНО ОДИН параметр — `cap`, потолок
на одно имя в `alloc_recycle`. Это и есть смысл замера: одна ручка, всё остальное закреплено.

Рядом с каждой строкой печатается `maxDD` (хвост) и `maxW` — фактическая самая крупная
позиция, которую раскладка реально держала. Требование карточки «хвост рядом с доходностью»
выполняется структурно: колонки соседние, разнести их нельзя.

Контроль `static-matched` печатается для каждого потолка: это тот же средний профиль экспозиции,
удержанный константой. Разница дынамики с ним — тайминг; всё, чего нет над ним, было статическим
наклоном, то есть КОНЦЕНТРАЦИЕЙ, а не умом правила. Именно эта пара строк и отвечает на вопрос
владельца по существу.

Запуск:
    python3 scripts/edge_concentration_price.py                 # полная таблица
    python3 scripts/edge_concentration_price.py --caps 20 25 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edge_capital_recycling as ecr            # noqa: E402  аллокатор/издержки/метрики #38/#39
import edge_cross_sectional_demotion as xsd     # noqa: E402  ранговая машина состояний #40
import edge_drift_gated_overlay as dgo          # noqa: E402  панель #35/#36/#37

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

LOOKBACK = xsd.LOOKBACK
REF_K, REF_M = 2, 20
POLICY_CAP = ecr.CONC_CAP                       # 0.20 — сегодняшний лимит T2 RiskPolicy v1.0
DEFAULT_CAPS: Tuple[Optional[float], ...] = (0.20, 0.25, 0.30, None)


def _rule_flags(panel: "dgo.Panel") -> List[Tuple[str, Optional[Dict[str, List[bool]]]]]:
    """Правила, для которых считается цена потолка. Ни одно не изобретается здесь."""
    import edge_redundancy_demotion as erd      # noqa: WPS433 — общий загрузчик признаков #40/#45

    rules: List[Tuple[str, Optional[Dict[str, List[bool]]]]] = [
        ("raw (без правила)", None),
        (f"#40 XSD дрейф k={REF_K} M={REF_M}",
         xsd.rank_demotion_flags(erd.panel_scores(panel, "drift"), REF_K, REF_M)),
        ("#39 CDR абсолютный M=20",
         xsd.absolute_flags(panel, xsd.HURDLE, LOOKBACK, 20)),
        (f"#45 XVD волатильность k={REF_K} M={REF_M}",
         xsd.rank_demotion_flags(erd.panel_scores(panel, "volatility"), REF_K, REF_M)),
    ]
    return rules


def _weights(panel: "dgo.Panel", flags: Optional[Dict[str, List[bool]]],
             cap: Optional[float]) -> Dict[str, List[float]]:
    if flags is None:                            # raw: равные веса, ничего не выключается
        flags = {b: [False] * panel.n for b in panel.books}
    return ecr.alloc_recycle(panel.books, flags, panel.n, cap=cap)


def concentration_price(subset: Optional[Sequence[str]] = None,
                        label: str = "all 10 real books",
                        caps: Sequence[Optional[float]] = DEFAULT_CAPS,
                        ) -> Dict[str, Dict[str, float]]:
    panel = dgo.Panel(subset, None, None)
    base = ecr._raw_metrics(panel)
    ecr._header(f"ЦЕНА ЛИМИТА КОНЦЕНТРАЦИИ (вариант A владельца 2026-08-08) — {label}",
                panel, base)

    import edge_redundancy_demotion as erd      # noqa: WPS433
    results: Dict[str, Dict[str, float]] = {}
    n_books = len(panel.books)

    # ── ЧАСТЬ 1 · опорная ячейка реестра (k=2, M=20) при разных потолках ────────
    print("-" * 110)
    print("ЧАСТЬ 1 — опорная ячейка реестра k=2 M=20: сколько стоит потолок ЗДЕСЬ")
    for cap in caps:
        cap_name = "без потолка" if cap is None else f"потолок {int(cap*100)}%"
        mark = "  ← сегодняшний лимит T2" if cap == POLICY_CAP else ""
        print(f"  {cap_name}{mark}")
        for rule_name, flags in _rule_flags(panel):
            w = _weights(panel, flags, cap)
            m = ecr.portfolio_metrics(panel, w)
            results[f"k=2 · {cap_name} · {rule_name}"] = m
            ecr._row(f"    {rule_name}", m, base)

    # ── ЧАСТЬ 2 · где ручка на самом деле — доля выключенных книг ──────────────
    # Карточка утверждала, что лимит 20% стоит ровно там, где прибавка начинает
    # расти. Проверяется это НЕ сменой потолка при фиксированном k (там потолок
    # не биндит вовсе), а свипом k: чем больше книг выключено, тем крупнее
    # обязана быть каждая оставшаяся позиция. Потолок начинает стоить деньги
    # ровно с того k, где 1/(N−k) превышает потолок.
    print("-" * 110)
    print(f"ЧАСТЬ 2 — свип доли выключенных книг (N={n_books}); равновесная доля = 1/(N−k)")
    print("            k   1/(N-k)   потолок     APY    maxDD   Calmar  ΔCalmar   maxW   netAPY")
    drift = erd.panel_scores(panel, "drift")
    for k in range(1, n_books - 1):
        equal_share = 1.0 / (n_books - k)
        flags = xsd.rank_demotion_flags(drift, k, REF_M)
        for cap in caps:
            cap_name = "нет" if cap is None else f"{int(cap*100)}%"
            binds = "" if cap is None or equal_share <= cap + 1e-9 else "  ← ПОТОЛОК БИНДИТ"
            m = ecr.portfolio_metrics(panel, ecr.alloc_recycle(panel.books, flags, panel.n, cap=cap))
            results[f"#40 k={k} · cap={cap_name}"] = m
            print(f"  #40 XSD  {k:3d}   {equal_share*100:6.1f}%   {cap_name:>6s}"
                  f" {m['apy']*100:7.2f}% {m['maxdd']*100:7.2f}% {m['calmar']:8.2f}"
                  f" {m['calmar']-base['calmar']:8.2f} {m['max_weight']*100:5.0f}%"
                  f" {m['net_apy_after_cost']*100:7.2f}%{binds}")

    print("-" * 110)
    print("КАК ЧИТАТЬ. Разница между строкой правила и его static-matched двойником — это ТАЙМИНГ.")
    print("Всё, чего у правила НЕТ над двойником, было статическим наклоном, то есть платой за")
    print("концентрацию, а не умом правила. Колонка maxW — фактическая самая крупная позиция:")
    print("если она не дотягивает до потолка, потолок в этой строке НЕ БИНДИТ и её прибавка")
    print("концентрацией не куплена.")
    print()
    print("ХВОСТ ОБЯЗАН ЧИТАТЬСЯ ВМЕСТЕ С ДОХОДНОСТЬЮ: колонки apy и maxDD стоят рядом намеренно.")
    print("Строка с лучшим apy и худшим maxDD — не победитель, а другой размен.")
    print()
    print("ГРАНИЦЫ: evidence L0 (бэктест), IS_ADVISORY, OUTSIDE_RISKPOLICY. Проскальзывание не")
    print("моделируется, L=60 и M унаследованы от #39/#40 и здесь НЕ перетюнены. Поднятие")
    print("потолка выше 20% — предмет ОТДЕЛЬНОГО ADR и ОТДЕЛЬНОГО решения владельца.")
    return results


def main(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--caps", nargs="*", type=float, default=None,
                    help="потолки на имя в ПРОЦЕНТАХ, например: --caps 20 25 30")
    ap.add_argument("--no-uncapped", action="store_true",
                    help="не печатать строку «без потолка»")
    a = ap.parse_args(argv)
    caps: List[Optional[float]] = ([c / 100.0 for c in a.caps] if a.caps
                                   else list(DEFAULT_CAPS[:-1]))
    if not a.no_uncapped:
        caps.append(None)
    concentration_price(caps=caps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
