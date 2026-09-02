"""spa_core/paper_trading/sleeve_book.py — настоящая paper-книга рукавов B (HY) и C (LP).

Зачем этот модуль существует (замер #208, решение владельца 2026-08-21, ADR-103).
До него hy_cycle/lp_cycle начисляли МЕДИАННУЮ ставку полосы на весь капитал рукава,
а позиции не открывал никто: `positions_count == 0` в каждой строке истории при
растущем equity. Владелец 19.08 снял с сайта плашку «paper track running» ровно за
это («начисление — не трек») и разрешил вернуть её «только в день, когда
positions_count > 0 станет фактом». Этот модуль и делает его фактом: рукав держит
ПОИМЕНОВАННЫЕ paper-позиции в живых протоколах из data/apy_ranking.json и
начисляет доход КАЖДОЙ позиции по ЕЁ живому APY.

Правила (те же, что у всего paper-слоя):
  • Детерминизм: кандидаты сортируются по (−apy, protocol) — одинаковый вход даёт
    одинаковую книгу. Никакого времени и случайности внутри.
  • Fail-closed: нет живого ранжирования — существующие позиции ДЕРЖАТСЯ, но
    начисляют 0 (нет данных ⇒ нет дохода, не выдумываем); новые не открываются.
    Протокол, выпавший из живого ранжирования, в тот же день начисляет 0 и
    закрывается в кэш при следующей перестройке.
  • Потолки зеркалят RiskPolicy v1.0 по смыслу: ≤ MAX_POSITIONS позиций,
    ≤ PER_PROTOCOL_CAP_PCT капитала на протокол, APY выше APY_CAP не начисляется
    (границы самой политики НЕ трогаются — это paper-рукав, инвариант #9).
  • LLM_FORBIDDEN. Только stdlib. Модуль ничего не пишет на диск — state пишут
    сами циклы (атомарно).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APY_RANKING = _PROJECT_ROOT / "data" / "apy_ranking.json"

# Границы книги рукава. Cap на протокол зеркалит T1-cap RiskPolicy (40%).
MAX_POSITIONS = 4
PER_PROTOCOL_CAP_PCT = 40.0
APY_CAP = 30.0          # выше потолка политики доход не начисляется (не берём)
HY_BAND_MIN = 6.0       # полоса high-yield (та же, что была в sleeve_yield)
_LP_NAME_HINTS = ("lp", "aerodrome", "velodrome", "curve", "uniswap", "pool")

# Мандат владельца 2026-08 (решение «Гоу B»): три пакета — Conservative / Balanced /
# Aggressive — должны быть СОПОСТАВИМЫ по капиталу. Каждый рукав засевается одним и
# тем же виртуальным $100k, чтобы доходность и просадку можно было честно сравнивать.
PACKAGE_SEED_USD = 100_000.0

# Aggressive-профиль (пакет Max-Yield, рукав C). Отличается от Balanced НЕ вселенной
# (whitelist один и тот же — стейблы), а КОНЦЕНТРАЦИЕЙ и бюджетом просадки: держим
# только top-2 самых доходных имени с потолком 60% и терпим просадку до -25%
# (owner: «стоп под 25% просадки»). Настоящая directional/leveraged агрессия требует
# расширения whitelist (owner/legal) — вынесено отдельной задачей, здесь НЕ выдаётся.
AGG_BAND_MIN = 6.0          # тот же порог входа, что у Balanced — не простаивать
AGG_MAX_POSITIONS = 2       # концентрация: две самые доходные позиции
AGG_PER_PROTOCOL_CAP_PCT = 60.0

ACCRUAL_BASIS = "per_position_live_apy"


def load_ranking_rows(path: Optional[Path] = None) -> List[dict]:
    """Живое ранжирование APY (пишет cycle_runner). Ошибка чтения → [] (fail-closed)."""
    p = path or _APY_RANKING
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        rows = d.get("by_apy") or []
        return [r for r in rows if isinstance(r, dict)]
    except Exception:  # noqa: BLE001
        return []


def apy_provenance_from_rows(
    rows: Optional[List[dict]],
) -> Tuple[dict, dict, dict, dict]:
    """Сырые строки ``by_apy`` → (apy_pct, apy_sources, tvl_sources, tvl_usd).

    Питает ``allocation_rationale.write_shadow_rationale``'s ``apy_pct`` /
    ``apy_sources`` / ``tvl_sources`` / ``tvl_usd`` для Balanced/Aggressive:
    у этих циклов нет объекта-аллокатора с провенансом, как у Conservative
    (``cycle_runner.py``) — единственный источник провенанса на этом пути —
    сами строки ранжирования, которые пишет ``apy_aggregator.py`` с полями
    ``apy_source``/``tvl_source`` (ADR-053/061/063, «live» = наблюдение).
    ``load_ranking_rows``/``_dedup_best`` этот провенанс не несут — они режут
    строку до ``{"protocol", "apy_pct"}`` для отбора кандидатов, поэтому
    читать нужно СЫРЫЕ строки, до дедупа.

    Fail-closed по построению: поле, которого в строке нет (в том числе у
    старой/замороженной фикстуры без ``apy_source``/``tvl_source`` вовсе),
    просто не попадает в соответствующую карту — протокол не засчитывается
    «живым» по умолчанию, «нет провенанса» никогда не читается как «live».
    """
    apy_pct: dict = {}
    apy_sources: dict = {}
    tvl_sources: dict = {}
    tvl_usd: dict = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        proto = str(r.get("protocol") or "").strip()
        if not proto:
            continue
        if r.get("apy_pct") is not None:
            apy_pct[proto] = float(r["apy_pct"])
        if r.get("apy_source"):
            apy_sources[proto] = str(r["apy_source"])
        if r.get("tvl_source"):
            tvl_sources[proto] = str(r["tvl_source"])
        if r.get("tvl_usd") is not None:
            tvl_usd[proto] = r["tvl_usd"]
    return apy_pct, apy_sources, tvl_sources, tvl_usd


def _dedup_best(rows: List[dict]) -> List[dict]:
    """Один протокол — одна строка (лучший APY). Сортировка (−apy, name) = детерминизм."""
    best: dict[str, float] = {}
    for r in rows:
        name = str(r.get("protocol") or "").strip()
        apy = r.get("apy_pct")
        if not name or not isinstance(apy, (int, float)) or isinstance(apy, bool):
            continue
        apy = float(apy)
        if apy <= 0 or apy > APY_CAP:
            continue  # вне (0, APY_CAP] — не кандидат (полисный потолок)
        if name not in best or apy > best[name]:
            best[name] = apy
    return [{"protocol": n, "apy_pct": a}
            for n, a in sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))]


def hy_candidates(rows: List[dict]) -> List[dict]:
    """Кандидаты полосы high-yield: живой APY ∈ [HY_BAND_MIN, APY_CAP]."""
    return [c for c in _dedup_best(rows) if c["apy_pct"] >= HY_BAND_MIN]


def lp_candidates(rows: List[dict]) -> List[dict]:
    """Кандидаты LP-полосы: протоколы с LP-признаком в имени, APY ∈ (0, APY_CAP].

    Историческая функция рукава C, пока он был delta-neutral LP-книгой. С «Гоу B»
    (2026-08) рукав C стал Aggressive-книгой и опрашивает band_candidates, а не имена
    LP: в живом whitelist LP-имён нет, и этот фильтр возвращал ПУСТО — рукав простаивал
    (замер: 929 циклов вхолостую). Оставлена для совместимости/тестов.
    """
    lp_rows = [r for r in rows
               if any(h in str(r.get("protocol", "")).lower() for h in _LP_NAME_HINTS)]
    return _dedup_best(lp_rows)


def band_candidates(rows: List[dict], min_apy: float,
                    max_apy: float = APY_CAP) -> List[dict]:
    """Кандидаты произвольной полосы доходности: живой APY ∈ [min_apy, max_apy].

    Обобщение hy_candidates: Balanced берёт [6, cap], Aggressive — ту же полосу, но
    затем концентрируется через max_positions/cap_pct в rebalance_book. Список уже
    отсортирован по (−apy, name), поэтому «взять top-N» = взять самые доходные.
    """
    return [c for c in _dedup_best(rows)
            if min_apy <= c["apy_pct"] <= max_apy]


def rebalance_book(positions: List[dict], candidates: List[dict], equity: float,
                   *, today: str, allow_new: bool = True,
                   max_positions: int = MAX_POSITIONS,
                   cap_pct: float = PER_PROTOCOL_CAP_PCT,
                   ) -> Tuple[List[dict], List[str], List[str]]:
    """Перестроить книгу под сегодняшних кандидатов. Возвращает (book, opened, closed).

    • candidates ПУСТЫ → данных нет: держим что есть, не открываем, не закрываем
      (закрытие по отсутствию данных — действие, а нейтральность — удержание).
    • Протокол позиции выпал из кандидатов → позиция закрывается в кэш (данные
      ЕСТЬ и говорят «полоса его больше не содержит»).
    • Свободные слоты добираются сверху списка кандидатов — только при allow_new
      (CIO-постура RED запрещает НОВОЕ, ADR-103; удержание не запрещает).
    • Веса: равный сплит по книге, но ≤ cap_pct капитала на протокол; остаток —
      кэш (начисляет 0, и это видно в deployed_usd).
    """
    equity = max(0.0, float(equity or 0.0))
    held = [dict(p) for p in (positions or []) if str(p.get("protocol") or "").strip()]
    if not candidates:
        return held, [], []

    cand_by_name = {c["protocol"]: c["apy_pct"] for c in candidates}
    kept = [p for p in held if p["protocol"] in cand_by_name]
    closed = sorted(p["protocol"] for p in held if p["protocol"] not in cand_by_name)

    opened: List[str] = []
    if allow_new:
        held_names = {p["protocol"] for p in kept}
        for c in candidates:
            if len(kept) >= max_positions:
                break
            if c["protocol"] in held_names:
                continue
            kept.append({"protocol": c["protocol"], "opened": today,
                         "is_delta_neutral": True})
            opened.append(c["protocol"])

    kept = kept[:max_positions]
    n = len(kept)
    if n and equity > 0:
        weight = min(1.0 / n, cap_pct / 100.0)
        for p in kept:
            p["apy_pct"] = round(float(cand_by_name[p["protocol"]]), 4)
            p["notional_usd"] = round(equity * weight, 2)
            p["stale"] = False
    return kept, opened, closed


def accrue_book(positions: List[dict], candidates: List[dict]) -> Tuple[float, float]:
    """Дневной доход книги: КАЖДАЯ позиция по ЕЁ живому APY из сегодняшних кандидатов.

    Протокола нет среди кандидатов (данные пропали) → его позиция начисляет 0 и
    помечается stale=True — отсутствие данных наблюдаемо, доход не выдуман.
    Возвращает (daily_yield_usd, deployed_usd).
    """
    cand_by_name = {c["protocol"]: c["apy_pct"] for c in candidates}
    total = 0.0
    deployed = 0.0
    for p in positions or []:
        notional = float(p.get("notional_usd") or 0.0)
        if notional <= 0:
            continue
        deployed += notional
        apy = cand_by_name.get(p.get("protocol"))
        if apy is None or apy <= 0:
            p["stale"] = True
            continue
        p["stale"] = False
        total += notional * (min(float(apy), APY_CAP) / 100.0) / 365.0
    return round(total, 6), round(deployed, 2)


def book_weighted_apy_pct(positions: List[dict]) -> float:
    """Честный APY книги: взвешен по deployed-нотионалам, stale-позиции дают 0."""
    num = 0.0
    den = 0.0
    for p in positions or []:
        notional = float(p.get("notional_usd") or 0.0)
        if notional <= 0:
            continue
        den += notional
        if not p.get("stale"):
            num += notional * float(p.get("apy_pct") or 0.0)
    return round(num / den, 4) if den > 0 else 0.0


def collapse_legs_to_flat(positions: Optional[List[dict]]) -> dict:
    """Ногу-список книги ({"protocol", "notional_usd", ...}) → {protocol: usd}.

    Balanced/Aggressive держат книгу списком ног (эта форма), а
    ``allocation_rationale.write_shadow_rationale`` / ``build_history_record``
    ждут плоский словарь (та же форма, что и у Conservative-аллокатора) —
    единственный вход, который у них есть. Конвертация живёт здесь, а не в
    самом ``allocation_rationale``, чтобы не заводить вторую форму входа в
    писателе ради одного из трёх вызывающих.

    Один протокол может встретиться в книге дважды (двух циклов подряд не
    бывает, но защититься дёшево) — суммируем, не перезаписываем. Ноги без
    ``protocol`` или с нулевым/отсутствующим ``notional_usd`` пропускаются
    (кэш-остаток книги, а не позиция).
    """
    flat: dict = {}
    for leg in positions or []:
        if not isinstance(leg, dict):
            continue
        proto = str(leg.get("protocol") or "").strip()
        notional = leg.get("notional_usd")
        if not proto or notional is None:
            continue
        flat[proto] = round(flat.get(proto, 0.0) + float(notional), 2)
    return flat
