"""Форвардный paper-модуль рангового демоушена — ДВЕ РУКИ в одном модуле.

Решения владельца 2026-08-08:
  * **ADR-074 принят** (вариант A карточки `own-rnd-xsd-rank-demotion-allocator`) — демоушен по
    относительному рангу вместо абсолютного порога; вариант **C** той же карточки — построить
    advisory paper-модуль.
  * **Вариант 1** карточки `own-rnd-xvd-vol-rank-second-arm` — ранжирование по волатильности
    добавляется **второй рукой внутрь этого же модуля**, а НЕ третьим paper-треком и НЕ новым
    агентом. «Один модуль, две руки, ноль новых агентов, и через 30 дней форварда мы своими
    глазами увидим, какая рука лучше — вместо того чтобы спорить об этом по бэктесту.»

Правило (из ADR-074, буква в букву; параметры унаследованы от записей #40/#45, НЕ перетюнены):

    score(b, t) = признак книги b на причинном окне [t−L, t−1]
    демоушен    : score в k САМЫХ НИЗКИХ  ⇒ книга выключена
    возврат     : вне bottom-k M дней ПОДРЯД

Две руки различаются ТОЛЬКО признаком:
  * **drift** (#39/#40) — скользящая средняя доходности. Зрячий к доходности.
  * **vol**   (#45)     — минус стандартное отклонение: выключаются самые ШУМНЫЕ книги.
    Полуслепой: σ инвариантна к смене знака, поэтому рука не отличает книгу, зарабатывающую
    20 %/год, от её зеркала, теряющего столько же.

Почему признак зафиксирован, а не оставлен параметром: запись **#44 (2026-08-08)** опровергла
вывод #43 «признак — сноска». При ТОЧНО выровненной duty смена признака двигает ΔCalmar на
**4.07** (M=1) и **7.40** (M=20). Признак — предмет ADR, а не деталь реализации.

Почему k держится в области 2…5: замер **#46** (тоже 2026-08-08) показал, что при k ≥ 6 без
потолка раскладка вырождается в ОДНУ позицию (maxW = 100 %) — это не портфель. Там же: наш
лимит 20 % на имя в опорной ячейке НЕ БИНДИТ и стоит ноль.

═══════════════════════════════════════════════════════════════════════════════════════════
ЧЕСТНЫЕ ГРАНИЦЫ — переносятся из ADR-074 дословно, как условия принятия
═══════════════════════════════════════════════════════════════════════════════════════════
1. Это **бэктест-происхождение, evidence L0**. `IS_ADVISORY=True`, `OUTSIDE_RISKPOLICY=True`,
   капитал НЕ двигается, RiskPolicy v1.0 не затрагивается ни строкой.
2. **Ранговое правило по построению ВСЕГДА держит 100 % капитала в рынке.** Оно умеет отвернуть
   деньги от худшей книги и НЕ УМЕЕТ опустить портфель целиком. Против общего обвала по всем
   книгам оно беззащитно. Оно **не заменяет kill-switch** и не подаётся как защита.
3. Контроль на **сдвиг сигнала во времени** правило проходит СЛАБО: измерено «оно правильно
   выбирает КАКУЮ книгу», а не «оно правильно угадывает КОГДА». Продавать как timing-эдж
   запрещено.

Каждая рука пишет в лог **фактическую концентрацию** и **долю времени «выключено»** — требование
владельца 2026-08-08 (карточка `own-rnd-duty-is-concentration-adr055`). Без них через 30 дней
форварда результат неразличим: правило его дало или премия за размер позиций.

Деплой агента — ОТДЕЛЬНОЙ карточкой владельцу. Принятие ADR разрешением не является.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, pstdev
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.strategy_lab.swarm.common import append_daily_proof, apy_pct, max_drawdown_pct
from spa_core.strategy_lab.swarm.dwell_hysteresis_forward import (
    NOTIONAL_USD, CASH_DAILY_RETURN, load_panel,
    _duty_out_pct, _largest_position_pct,
)
from spa_core.utils.atomic import atomic_save

__all__ = [
    "run_forward_tick", "compute_arms", "rank_flags", "drift_scores", "vol_scores",
    "LOOKBACK", "RANK_K", "READMIT_M", "ARMS", "BOOK_NAME", "STATUS_NAME",
]

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

REPO_ROOT = Path(__file__).resolve().parents[3]
PANEL_DIR = REPO_ROOT / "data" / "aggressive_lab"
SWARM_DIR = REPO_ROOT / "data" / "swarm"
BOOK_NAME = "rank_demotion_book.jsonl"
STATUS_NAME = "rank_demotion_status.json"

# Унаследованы от #39/#40, здесь НЕ перетюнены. Изменение любого — НОВЫЙ эксперимент:
# запись в реестре + карточка владельцу, никогда молчаливая правка.
LOOKBACK = 60
RANK_K = 2
READMIT_M = 20

ARMS: Tuple[str, ...] = ("drift", "vol")

HONEST_LIMITS = (
    "форвардный paper поверх живых paper-плеч, НЕ реализованный капитал; правило проверено "
    "только на бэктесте (L0, #40/#45) — этот форвард и есть проверка, и он начинается с малого; "
    "ранговое правило ВСЕГДА держит 100% капитала в рынке и kill-switch НЕ ЗАМЕНЯЕТ; контроль на "
    "сдвиг сигнала пройден слабо — это эдж про РАСПРЕДЕЛЕНИЕ капитала, не про тайминг; сигнал "
    "обезоружен первые LOOKBACK дней (все руки равны — разогрев часть трека); если через ~30 "
    "вооружённых дней эффект не подтверждён, модуль ретайрится карточкой, а не оставляется спать"
)


# ── признаки (причинное окно [t−L, t−1] — сегодняшний день НИКОГДА не смотрит на себя) ────────
def _causal_window(rets: Sequence[float], i: int, lookback: int) -> List[float]:
    lo = max(0, i - lookback)
    return list(rets[lo:i])


def drift_scores(panel_rets: Dict[str, List[float]], lookback: int = LOOKBACK) -> Dict[str, List[Optional[float]]]:
    """#39/#40: средняя доходность на окне. Выше — лучше."""
    out: Dict[str, List[Optional[float]]] = {}
    for b, rets in panel_rets.items():
        out[b] = [(fmean(w) if (w := _causal_window(rets, i, lookback)) else None)
                  for i in range(len(rets))]
    return out


def vol_scores(panel_rets: Dict[str, List[float]], lookback: int = LOOKBACK) -> Dict[str, List[Optional[float]]]:
    """#45: МИНУС стандартное отклонение — «тихая» книга получает высокий score.

    Полуслепой признак: σ не различает знак. Книга, зарабатывающая 20 %/год, и её зеркало,
    теряющее столько же, для этой руки НЕРАЗЛИЧИМЫ — это её свойство, а не дефект, и именно
    поэтому она стоит в паре со зрячей рукой, а не вместо неё.
    """
    out: Dict[str, List[Optional[float]]] = {}
    for b, rets in panel_rets.items():
        out[b] = [(-pstdev(w) if len(w := _causal_window(rets, i, lookback)) >= 2 else None)
                  for i in range(len(rets))]
    return out


_SCORERS = {"drift": drift_scores, "vol": vol_scores}


# ── ранговая машина состояний (#40, одна подстановка признака) ────────────────────────────────
def rank_flags(scores: Dict[str, List[Optional[float]]], k: int = RANK_K,
               readmit_m: int = READMIT_M) -> Dict[str, List[bool]]:
    """{книга: [выключена ли в день i]}.

    Демоушен: score в k САМЫХ НИЗКИХ среди книг, у которых score вообще измерен.
    Возврат: книга вне bottom-k **M дней ПОДРЯД**. Один день вне — не возврат: без
    задержки правило начинает торговать шум, и именно отложенный возврат отличает #39/#40
    от наивного «переставляй каждый день».

    Fail-CLOSED: пока score не измерен (окно не набралось) — книга НЕ выключается. Выключить
    по неизмеренному значило бы принять решение о капитале на пустоте.
    """
    books = sorted(scores)
    n = len(scores[books[0]]) if books else 0
    out = {b: [False] * n for b in books}
    streak = {b: 0 for b in books}          # дней подряд вне bottom-k
    state = {b: False for b in books}       # выключена ли сейчас

    for i in range(n):
        measured = [(scores[b][i], b) for b in books if scores[b][i] is not None]
        if len(measured) <= k:
            # Измеренных не больше k — «худших k» не определить, никого не выключаем.
            for b in books:
                out[b][i] = state[b]
            continue
        measured.sort()
        worst = {b for _s, b in measured[:k]}
        for b in books:
            if b in worst:
                state[b] = True
                streak[b] = 0
            else:
                streak[b] += 1
                if state[b] and streak[b] >= readmit_m:
                    state[b] = False
            out[b][i] = state[b]
    return out


# ── плечи ─────────────────────────────────────────────────────────────────────────────────────
def _weights_from_flags(flags: Dict[str, List[bool]], n: int) -> Dict[str, List[float]]:
    """Выключенные книги отдают долю оставшимся поровну (аллокатор #38/#39).

    Все выключены ⇒ всё в кэш (fail-CLOSED: единственное состояние, в котором правило НЕ ДОЛЖНО
    выдумывать назначение).
    """
    books = sorted(flags)
    out = {b: [0.0] * n for b in books}
    for i in range(n):
        live = [b for b in books if not flags[b][i]]
        if not live:
            continue
        share = 1.0 / len(live)
        for b in live:
            out[b][i] = share
    return out


def _equity(dates: Sequence[str], panel: Dict[str, Dict[str, float]],
            w: Dict[str, List[float]]) -> List[float]:
    books = sorted(panel)
    eq = [NOTIONAL_USD]
    for i in range(len(dates)):
        r = sum(w[b][i] * panel[b][dates[i]] for b in books)
        deployed = sum(w[b][i] for b in books)
        eq.append(eq[-1] * (1.0 + r + (1.0 - deployed) * CASH_DAILY_RETURN))
    return eq


def compute_arms(dates: Sequence[str], panel: Dict[str, Dict[str, float]]) -> dict:
    """raw (равные веса) + по одной руке на признак."""
    books = sorted(panel)
    n = len(dates)
    panel_rets = {b: [panel[b][d] for d in dates] for b in books}

    def view(w: Dict[str, List[float]]) -> dict:
        eq = _equity(dates, panel, w)
        return {
            "equity_usd": round(eq[-1], 2),
            "apy_pct": apy_pct(eq, n),
            "max_dd_pct": max_drawdown_pct(eq),
            "books_out_today": sorted(b for b in books if w[b][-1] == 0.0),
            # Требование владельца 2026-08-08: обе величины КАЖДЫЙ ДЕНЬ.
            "concentration_pct": _largest_position_pct(w, books, -1),
            "duty_out_pct": _duty_out_pct(w, books, n),
        }

    equal = {b: [1.0 / len(books)] * n for b in books}
    arms: dict = {"raw": view(equal)}
    arms["raw"].pop("books_out_today")            # raw по определению никогда не вне рынка

    for arm in ARMS:
        flags = rank_flags(_SCORERS[arm](panel_rets))
        arms[arm] = view(_weights_from_flags(flags, n))

    # Прямое сравнение рук — то, ради чего владелец выбрал «две руки в одном модуле»
    # вместо спора по бэктесту.
    arms["arm_contrast"] = {
        "apy_delta_pp": (None if arms["drift"]["apy_pct"] is None or arms["vol"]["apy_pct"] is None
                         else round(arms["drift"]["apy_pct"] - arms["vol"]["apy_pct"], 4)),
        "dd_delta_pp": (None if arms["drift"]["max_dd_pct"] is None or arms["vol"]["max_dd_pct"] is None
                        else round(arms["drift"]["max_dd_pct"] - arms["vol"]["max_dd_pct"], 4)),
        "note": ("drift минус vol. Читать ВМЕСТЕ с concentration_pct и duty_out_pct обеих рук: "
                 "при разной концентрации разница доходности не является разницей правил (#46)."),
    }
    return arms


# ── дневной форвардный тик ────────────────────────────────────────────────────────────────────
def _last_book_day(book_path: Path) -> Optional[str]:
    last = None
    try:
        with book_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("date", last)
                except ValueError:
                    continue
    except OSError:
        return None
    return last


def run_forward_tick(panel_dir: Path = PANEL_DIR, out_dir: Path = SWARM_DIR,
                     as_of: Optional[str] = None) -> dict:
    """Один форвардный тик за один UTC-день. Дописывает ОДНУ hash-chained строку (идемпотентно
    по дню, append-only ПО ДАТЕ) + пишет статус. Капитал не двигает."""
    now = datetime.now(timezone.utc)
    day = as_of or now.date().isoformat()
    panel, missing = load_panel(panel_dir)

    doc: dict = {
        "module": "swarm.rank_demotion_forward",
        "adr": "ADR-074",
        "is_advisory": IS_ADVISORY,
        "outside_riskpolicy": OUTSIDE_RISKPOLICY,
        "generated_at": now.isoformat(),
        "day": day,
        "params": {"lookback": LOOKBACK, "k": RANK_K, "readmit_m": READMIT_M, "arms": list(ARMS),
                   "provenance": ("docs/DYNAMIC_LEVERAGE_GUARDIAN.md #40 (drift) + #45 (vol); "
                                  "параметры унаследованы, НЕ перетюнены")},
        "honest_limits": HONEST_LIMITS,
    }

    common = sorted(d for d in set.intersection(*(set(s) for s in panel.values()))
                    if d <= day) if panel and not missing else []

    payload: dict = {"phase": "forward", "is_advisory": True, "outside_riskpolicy": True,
                     "adr": "ADR-074",
                     "params": {"lookback": LOOKBACK, "k": RANK_K, "readmit_m": READMIT_M}}
    if missing:
        doc.update({"state": "NO_DATA", "missing_books": missing, "common_days": 0,
                    "reason": f"книги без живых форвардных строк: {missing}"})
        payload.update({"status": "no_data", "reason": doc["reason"]})
    elif not common or common[-1] != day:
        last_feed = common[-1] if common else None
        doc.update({"state": "NO_DATA", "last_feed_date": last_feed, "common_days": len(common),
                    "reason": (f"нет живого форвардного фида за {day} по панели "
                               f"(свежайшая общая дата: {last_feed})")})
        payload.update({"status": "no_data", "reason": doc["reason"]})
    else:
        arms = compute_arms(common, panel)
        # Пока окно не набралось, все руки равны raw — это разогрев, и он ЧАСТЬ трека.
        signal_armed = len(common) > LOOKBACK
        doc.update({"state": "TRACKING", "common_days": len(common),
                    "window": {"start": common[0], "end": common[-1]},
                    "signal_armed": signal_armed, "arms": arms})
        payload.update({"status": "tracking", "days": len(common), "window": doc["window"],
                        "signal_armed": signal_armed, "arms": arms})

    book_path = out_dir / BOOK_NAME
    last_day = _last_book_day(book_path)
    if last_day is not None and day < last_day:
        doc.update({"state": "REFUSED_OUT_OF_ORDER",
                    "reason": f"тик за {day} предшествует последнему дню книги {last_day}"})
        doc["book_appended"] = False
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        doc["book_appended"] = append_daily_proof(payload, book_path, day=day)

    atomic_save(doc, str(out_dir / STATUS_NAME))
    return doc


def main() -> int:
    doc = run_forward_tick()
    print(f"swarm.rank_demotion_forward: state={doc['state']} "
          f"days={doc.get('common_days')} armed={doc.get('signal_armed')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
