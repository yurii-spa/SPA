"""spa_core/paper_trading/sleeve_book.py — настоящая paper-книга рукавов B (HY) и C (LP).

Зачем этот модуль существует (замер #208, решение владельца 2026-08-21, ADR-103).
До него hy_cycle/lp_cycle начисляли МЕДИАННУЮ ставку полосы на весь капитал рукава,
а позиции не открывал никто: `positions_count == 0` в каждой строке истории при
растущем equity. Владелец 19.08 снял с сайта плашку «paper track running» ровно за
это («начисление — не трек») и разрешил вернуть её «только в день, когда
positions_count > 0 станет фактом». Этот модуль и делает его фактом: рукав держит
ПОИМЕНОВАННЫЕ paper-позиции в живых протоколах из data/apy_ranking.json и
начисляет доход КАЖДОЙ позиции по ЕЁ НАБЛЮДЁННОЙ ставке (ADR-292: строка
ранжирования допускается, только если её apy_source/tvl_source == "live", а TVL
проходит пол политики; ненаблюдаемая константа адаптера кандидатом не является).

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

# ── Наблюдаемость ставки (ADR-292, замер 2026-09-09) ─────────────────────────
# До этой правки строка ранжирования принималась целиком: `_dedup_best` смотрел
# только на `apy_pct` и не спрашивал, ОТКУДА он. В живом файле того дня восемь
# строк из тридцати несли `apy_source="fallback"` — константу адаптера, которую
# никто не наблюдал, — и все восемь стояли ВЫШЕ каждой наблюдённой ставки:
#
#   pendle_yt_susde 14.0 · ethena_susde 12.0 · aerodrome_usdc_lp 8.5 · pendle 8.0
#   (лучшая НАБЛЮДЁННАЯ ставка того дня — moonwell_base 11.97, затем maple 4.96)
#
# Сортировка по (−apy) поэтому гарантированно набирала книгу из литералов: обе
# книги были профинансированы на 100 % ненаблюдаемыми числами, а поле
# ACCRUAL_BASIS называлось `per_position_live_apy` и утверждало обратное. Слово
# «live» там значило «из файла ранжирования», а не «наблюдено» — претензия на
# провенанс, которую никто не проверял.
#
# Теперь провенанс — условие допуска, а не украшение. Строка становится
# кандидатом, только если ставку НАБЛЮДАЛИ (`apy_source == "live"`) и размер пула
# тоже наблюдали и он проходит пол (`tvl_source == "live"`, `tvl_usd >= MIN_TVL_USD`).
# Пол — тот же $5M, что у RiskPolicy v1.0: книга-рукав не смягчает границы политики.
OBSERVABLE_APY_SOURCE = "live"
OBSERVABLE_TVL_SOURCE = "live"
MIN_TVL_USD = 5_000_000.0

ACCRUAL_BASIS = "per_position_observed_apy"


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


def observable_rows(rows: Optional[List[dict]]) -> Tuple[List[dict], List[dict]]:
    """Разделить строки ранжирования на НАБЛЮДЁННЫЕ и отброшенные (с причиной).

    Возвращает ``(kept, dropped)``; каждая запись ``dropped`` несёт ``protocol``,
    ``apy_pct`` и ``reason`` — чтобы цикл мог записать в историю, ЧТО именно он не
    взял и почему, а не молча показать пустую книгу.

    Отсутствие поля — НЕ «наблюдено». Строка без ``apy_source`` отбрасывается с
    причиной ``apy_source_missing``: молчание провенанса читается как отказ, иначе
    старая фикстура или новый адаптер без поля тихо вернули бы прежнее поведение.
    """
    kept: List[dict] = []
    dropped: List[dict] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        proto = str(r.get("protocol") or "").strip()
        if not proto:
            continue
        rec = {"protocol": proto, "apy_pct": r.get("apy_pct")}
        a_src = r.get("apy_source")
        t_src = r.get("tvl_source")
        tvl = r.get("tvl_usd")
        if a_src is None:
            dropped.append({**rec, "reason": "apy_source_missing"}); continue
        if str(a_src) != OBSERVABLE_APY_SOURCE:
            dropped.append({**rec, "reason": f"apy_source={a_src}"}); continue
        if t_src is None:
            dropped.append({**rec, "reason": "tvl_source_missing"}); continue
        if str(t_src) != OBSERVABLE_TVL_SOURCE:
            dropped.append({**rec, "reason": f"tvl_source={t_src}"}); continue
        if not isinstance(tvl, (int, float)) or isinstance(tvl, bool):
            dropped.append({**rec, "reason": "tvl_usd_missing"}); continue
        if float(tvl) < MIN_TVL_USD:
            dropped.append({**rec, "reason": f"tvl_below_floor:{float(tvl):.0f}"}); continue
        kept.append(r)
    return kept, dropped


def _dedup_best(rows: List[dict]) -> List[dict]:
    """Один протокол — одна строка (лучший APY). Сортировка (−apy, name) = детерминизм."""
    best: dict[str, float] = {}
    # Провенанс — условие допуска (см. блок «Наблюдаемость ставки» выше): в набор
    # кандидатов попадают только строки, у которых ставку и размер пула НАБЛЮДАЛИ.
    observable, _dropped = observable_rows(rows)
    for r in observable:
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


def book_candidates(rows: Optional[List[dict]]) -> List[dict]:
    """Кандидаты книги рукава: ВСЕ наблюдённые имена, отсортированные по (−apy, name).

    Почему здесь НЕТ абсолютного порога доходности (ADR-292, замер 2026-09-09).
    ``HY_BAND_MIN``/``AGG_BAND_MIN`` = 6 % откалиброваны в мире, где полосу населяли
    константы адаптеров: в живом файле того дня четыре верхние строки (14.0 / 12.0 /
    8.5 / 8.0) несли ``apy_source="fallback"``. Как только провенанс стал условием
    допуска, полоса ≥ 6 % опустела ЦЕЛИКОМ — лучшая наблюдённая ставка, проходящая
    пол TVL, была 4.96 %. Книга с абсолютным порогом 6 % не открыла бы ни одной
    позиции никогда, а книга, которая ничего не держит, — не тест, а отказ.

    Поэтому «high-yield» здесь величина ОТНОСИТЕЛЬНАЯ: список отсортирован по
    доходности, а сколько имён из его начала взять и с каким потолком — решает
    профиль книги (``max_positions``/``cap_pct`` в ``rebalance_book``). Balanced
    берёт четыре имени с потолком 40 %, Aggressive — два с потолком 60 %.

    Порог не «ослаблен»: доступ к книге стал СТРОЖЕ (ненаблюдаемая ставка больше не
    кандидат вовсе), а число, которое книга покажет, — теперь измеренное. Ожидаемое
    следствие названо в ADR-292 ДО работы: обе книги дадут примерно столько же,
    сколько консервативная, потому что 12 % и 20 % в наблюдаемой вселенной нет.
    """
    return _dedup_best(rows or [])


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


# ── Издержки перекладок (ADR-292) ────────────────────────────────────────────
# Кривая, которой не с чего упасть, не может быть треком. У книги-рукава ДВЕ
# причины упасть: движение цены инструмента (переоценка) и издержки перекладки.
# Вторая дешевле и честнее первой — она возникает от собственных действий книги,
# и до сих пор не списывалась вовсе: `equity += dy`, и всё.
#
# Числа НЕ изобретаются: газ/слиппедж/мост берутся из ЕДИНСТВЕННОЙ модели костов
# дерева (spa_core/backtesting/tier1/cost_model.py) — той же, которой пользуется
# rebalance_economics для консервативной книги. Четвёртое число на этой оси
# заводить запрещено (замер «в дереве ТРИ числа 8/15/96 на одной оси»).
try:  # pragma: no cover — импорт-страж, книга обязана считаться и без модели
    from spa_core.backtesting.tier1.cost_model import (
        GAS_USD_PER_POSITION_CHANGE as _GAS_BY_CHAIN,
        SLIPPAGE_BPS_STABLE as _SLIPPAGE_BPS,
        BRIDGE_BPS as _BRIDGE_BPS,
    )
except Exception:  # noqa: BLE001
    _GAS_BY_CHAIN = {"ethereum": 12.0, "mainnet": 12.0, "arbitrum": 0.25,
                     "optimism": 0.25, "base": 0.15, "polygon": 0.05, "blended": 1.5}
    _SLIPPAGE_BPS = 8.0
    _BRIDGE_BPS = 5.0


def chains_from_rows(rows: Optional[List[dict]]) -> dict:
    """protocol → сеть из строк ранжирования (поле ``network``); нет поля ⇒ нет ключа.

    Отсутствующая сеть НЕ подменяется «blended» здесь: подстановка — решение
    потребителя (``book_move_cost``), и оно должно быть видно там, где считается газ.
    """
    out: dict = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        proto = str(r.get("protocol") or "").strip()
        net = r.get("network")
        if proto and net:
            out[proto] = str(net).strip().lower()
    return out


def book_move_cost(before: Optional[List[dict]], after: Optional[List[dict]],
                   chains: Optional[dict] = None) -> dict:
    """Стоимость перехода книги ``before`` → ``after`` в долларах.

    Оборот считается ОДНОСТОРОННЕ — ``max(куплено, продано)``: при обмене одной
    позиции на другую это половина валового, а при развёртывании кэша (продажи нет
    вовсе) — вся развёрнутая сумма. ``gross/2`` во втором случае занизил бы издержку
    ровно на том движении, которое книга делает чаще всего.

    Возвращает ``{"cost_usd", "turnover_usd", "gas_usd", "slippage_usd", "bridge_usd",
    "touched": [...], "chains": [...]}``. Ничего не меняет во входных списках.
    """
    chains = chains or {}

    def _flat(book):
        out: dict = {}
        for leg in book or []:
            if not isinstance(leg, dict):
                continue
            proto = str(leg.get("protocol") or "").strip()
            if not proto:
                continue
            out[proto] = out.get(proto, 0.0) + float(leg.get("notional_usd") or 0.0)
        return out

    b, a = _flat(before), _flat(after)
    inc = dec = 0.0
    touched: List[str] = []
    for proto in sorted(set(b) | set(a)):
        d = a.get(proto, 0.0) - b.get(proto, 0.0)
        if abs(d) <= 1e-9:
            continue
        touched.append(proto)
        if d > 0:
            inc += d
        else:
            dec += -d
    turnover = max(inc, dec)
    gas = 0.0
    seen_chains = set()
    for proto in touched:
        chain = chains.get(proto, "blended")
        seen_chains.add(chain)
        gas += float(_GAS_BY_CHAIN.get(chain, _GAS_BY_CHAIN.get("blended", 1.5)))
    slippage = turnover * (_SLIPPAGE_BPS / 10_000.0)
    bridge = turnover * (_BRIDGE_BPS / 10_000.0) if len(seen_chains) > 1 else 0.0
    return {
        "cost_usd": round(gas + slippage + bridge, 6),
        "turnover_usd": round(turnover, 2),
        "gas_usd": round(gas, 6),
        "slippage_usd": round(slippage, 6),
        "bridge_usd": round(bridge, 6),
        "touched": touched,
        "chains": sorted(seen_chains),
    }


# ── Переоценка позиций (ADR-292) ─────────────────────────────────────────────
# Главное отличие этих книг от консервативной. Консервативная даёт стейблы в долг:
# цена около единицы, меняются только проценты, поэтому её кривая по построению не
# падает — отсюда её «0.0 % просадки», и это свойство модели, а не устойчивость.
# Balanced и Aggressive держат инструменты, у которых цена ДВИЖЕТСЯ.
#
# Цену выдумывать нельзя. Поэтому переоценка здесь — ШОВ с третьим исходом: чего
# не наблюдали, то не переоценивается и честно попадает в непокрытую долю книги.
# Единственный живой источник цен в дереве на 2026-09-09 — монитор пега
# (data/peg_history.json), и он покрывает три адаптера из тридцати. Покрытие
# записывается числом в каждую строку истории, поэтому «переоценка не измерена»
# видно в самом треке, а не только в этом комментарии.
_PEG_HISTORY = _PROJECT_ROOT / "data" / "peg_history.json"


def observed_prices(path: Optional[Path] = None) -> dict:
    """protocol → наблюдённая цена из монитора пега. Нет файла/поля ⇒ ключа нет.

    Ключ строки монитора — ``adapter_id``; он совпадает с именем протокола в
    ранжировании не всегда, и несовпавшее имя просто остаётся непокрытым. Молча
    сопоставлять «похожие» имена запрещено: ошибка сопоставления здесь означала бы
    переоценку позиции по цене ЧУЖОГО инструмента.
    """
    p = path or _PEG_HISTORY
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: dict = {}
    for st in ((d.get("latest") or {}).get("statuses") or []):
        if not isinstance(st, dict):
            continue
        name = str(st.get("adapter_id") or "").strip()
        price = st.get("current_price")
        if name and isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
            out[name] = float(price)
    return out


def mark_to_market(positions: Optional[List[dict]], prices: Optional[dict]) -> dict:
    """Переоценить книгу по наблюдённым ценам. МУТИРУЕТ ``mark_price`` у покрытых ног.

    Возвращает ``{"pnl_usd", "covered_usd", "deployed_usd", "coverage_pct",
    "marked": [...], "unmarked": [...]}``.

    Первое наблюдение цены позиции даёт P&L 0 и запоминает отметку — движение
    считается только между ДВУМЯ наблюдениями. Нулевое покрытие возвращает
    ``coverage_pct = 0.0`` и ``pnl_usd = 0.0``: это «не измерено», а не «не двигалось»,
    и различить их обязан потребитель — поле ``coverage_pct`` для того и есть.
    """
    prices = prices or {}
    pnl = 0.0
    covered = 0.0
    deployed = 0.0
    marked: List[str] = []
    unmarked: List[str] = []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        notional = float(p.get("notional_usd") or 0.0)
        if notional <= 0:
            continue
        deployed += notional
        proto = str(p.get("protocol") or "").strip()
        px = prices.get(proto)
        if px is None:
            unmarked.append(proto)
            continue
        covered += notional
        marked.append(proto)
        prev = p.get("mark_price")
        if isinstance(prev, (int, float)) and not isinstance(prev, bool) and prev > 0:
            pnl += notional * (float(px) / float(prev) - 1.0)
        p["mark_price"] = float(px)
    return {
        "pnl_usd": round(pnl, 6),
        "covered_usd": round(covered, 2),
        "deployed_usd": round(deployed, 2),
        "coverage_pct": round(100.0 * covered / deployed, 4) if deployed > 0 else 0.0,
        "marked": sorted(marked),
        "unmarked": sorted(unmarked),
    }


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
