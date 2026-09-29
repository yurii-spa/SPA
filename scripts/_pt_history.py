#!/usr/bin/env python3
"""
Shared READ-ONLY loader for `data/rates_desk/pendle_pt_history.json` (ideas #117, #118).

Advisory-only research support. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution, never writes anything, stdlib-only, LLM FORBIDDEN.

ЧТО В РЯДЕ, И ЧЕГО В НЁМ НЕТ (проверено перед первым использованием, 2026-09-29)
────────────────────────────────────────────────────────────────────────────────
42 рынка Pendle PT, 6276 строк, 1245 дат 2023-02-07…2026-07-05, семь базовых активов
(USDe, sUSDe, sUSDS, eETH, ezETH, rsETH, wstETH). У строки: `implied_yield` (годовая
ставка PT), `tvl_usd`, `underlying_yield` (плавающая ставка базового актива) и через
рынок — `maturity`.

**`pt_price` равен `null` во ВСЕХ 6276 строках.** Цена не наблюдается — она ВЫВОДИТСЯ
из ставки по соглашению Pendle `P = (1 + implied_yield) ** (−τ/365)`, где τ — дней до
погашения. Это заявление о конвенции, а не замер: любой вывод, опирающийся на цену,
обязан называть её выведенной. Третий исход (`unmeasured`) возвращается, когда ряда нет
или он пуст, — ноль и «чисто» здесь запрещены (инв. #17).

`underlying_yield` = 0 на ВСЕХ 859 датах USDe: USDe сам по себе не накапливает доход,
и это не пропуск данных, а свойство актива. Потребитель обязан отличать «0 = нет ставки
по построению» от «нет наблюдения»: `float_rates()` возвращает дату ТОЛЬКО когда хотя бы
один рынок дал ненулевое значение, а `has_float` говорит, есть ли у актива этот ряд вообще.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import statistics as st
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

HISTORY = ("rates_desk", "pendle_pt_history.json")


class Unmeasured(RuntimeError):
    """Третий исход: ряд не прочитан. Не ноль, не пустота, не успех (инв. #17)."""


def days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def shift(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def pt_price(implied_yield: float, tau_days: float) -> float:
    """Конвенция Pendle: PT гасится в 1, цена = (1+y)^(-tau/365). ВЫВЕДЕНА, не наблюдена."""
    return (1.0 + implied_yield) ** (-tau_days / 365.0)


class Underlying:
    """Один базовый актив: по дате — живые рынки (tau, implied_yield, tvl) и плавающая ставка."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.obs: Dict[str, Dict[str, Tuple[int, float, Optional[float]]]] = {}
        self._float_raw: Dict[str, List[float]] = {}
        self.maturity: Dict[str, str] = {}

    def add(self, market: str, maturity: str, row: dict) -> None:
        day = row["date"]
        tau = days(day, maturity)
        self.maturity[market] = maturity
        self.obs.setdefault(day, {})[market] = (tau, row["implied_yield"], row.get("tvl_usd"))
        uy = row.get("underlying_yield")
        if uy:  # 0 у USDe = «ставки нет по построению», не наблюдение
            self._float_raw.setdefault(day, []).append(uy)

    @property
    def dates(self) -> List[str]:
        return sorted(self.obs)

    @property
    def has_float(self) -> bool:
        return bool(self._float_raw)

    def float_rates(self) -> Dict[str, float]:
        """Плавающая ставка по дате. Рынки одной даты иногда расходятся — берём медиану
        и число расхождений возвращаем отдельно (`float_disagreement`)."""
        return {d: st.median(v) for d, v in self._float_raw.items()}

    def float_disagreement(self) -> int:
        return sum(1 for v in self._float_raw.values() if len(v) > 1 and max(v) - min(v) > 1e-12)

    def legs(self, day: str) -> List[Tuple[int, float, Optional[float], str]]:
        """Живые ноги дня, от короткой к длинной: (tau, implied_yield, tvl, market)."""
        return sorted((t, y, tvl, k) for k, (t, y, tvl) in self.obs[day].items())


def load(data_dir: Path) -> Dict[str, Underlying]:
    path = data_dir.joinpath(*HISTORY)
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Unmeasured(f"{path}: {exc}") from exc
    markets = raw.get("markets")
    if not markets:
        raise Unmeasured(f"{path}: markets empty — НЕ ИЗМЕРЕНО, а не «нет рынков»")
    out: Dict[str, Underlying] = {}
    n_px = 0
    for key, m in markets.items():
        u = out.setdefault(m["underlying"], Underlying(m["underlying"]))
        for row in m["series"]:
            if row.get("pt_price") is not None:
                n_px += 1
            u.add(key, m["maturity"], row)
    if n_px:  # конвенция перестала быть единственным источником цены — сказать вслух
        print(f"  NOTE: {n_px} строк несут наблюдённый pt_price; скрипты всё ещё считают по конвенции")
    return out


def sign_test_p(n_pos: int, n: int) -> Optional[float]:
    """Двусторонний биномиальный знаковый тест при p0=0.5. n=0 ⇒ None (не измерено)."""
    if n <= 0:
        return None
    from fractions import Fraction
    from math import comb

    k = min(n_pos, n - n_pos)
    # целочисленно: 2**n при n ~ 1600 не влезает в float, а Fraction влезает точно
    tail = Fraction(sum(comb(n, i) for i in range(0, k + 1)), 1 << n)
    return min(1.0, float(2 * tail))


def non_overlapping(records: List[dict], day_key: str = "date", span_key: str = "tau") -> List[dict]:
    """Оставить винтажи, чьи сроки не пересекаются: иначе соседние наблюдения — одно и то же."""
    out: List[dict] = []
    last: Optional[dict] = None
    for r in sorted(records, key=lambda x: x[day_key]):
        if last is None or days(last[day_key], r[day_key]) >= last[span_key]:
            out.append(r)
            last = r
    return out
