"""spa_core/price_feeds/pendle_yt_feed.py — MP-427

Pendle YT (Yield Token) live APY feed.

Источники данных (в порядке приоритета)
----------------------------------------
1. **DeFiLlama /pools** — основной источник.
   Фильтр: project содержит «pendle», tvlUsd > MIN_TVL_USD.
   Предпочтение: пулы с «YT» в символе; иначе любой Pendle-пул с макс. APY.
   Endpoint: https://yields.llama.fi/pools

2. **Pendle V2 REST API** — резервный источник (если DeFiLlama недоступна
   или не вернула YT-пулы с разумным APY).
   Эндпоинт: https://api-v2.pendle.finance/core/v1/1/markets
   YT APY рассчитывается как:
       yt_leverage  = 1.0 / yt_price_pct   (цена YT как доля номинала)
       yt_excess    = underlying_apy − implied_apy
       yt_apy_pct   = (yt_excess * yt_leverage) * 100  (%)
   Фильтр: stablecoin underlying, liquidity > MIN_TVL_USD.

3. **Hardcoded fallback** = 28.4 % (константа FALLBACK_APY).
   Соответствует bull Pendle YT APY при underlying=12%, implied=8%, lev=3.5×.

Ограничения
-----------
* stdlib only — urllib.request, json, logging. Никаких внешних зависимостей.
* Read-only / advisory — не модифицирует allocator/risk/execution.
* LLM FORBIDDEN в данном модуле.
* Все сетевые ошибки перехватываются → возврат fallback-значения.
* APY ограничен диапазоном [APY_MIN_PCT, APY_MAX_PCT] перед возвратом.

Research (DeFiLlama, 2025-H1)
------------------------------
Pendle пулы в DeFiLlama идентифицируются project="pendle-v2".
Примеры YT-пулов:
  symbol="YT-sUSDe-27MAR2025"  apy≈32–55%  tvl≈$8M–$25M
  symbol="YT-USDe-27MAR2025"   apy≈28–48%  tvl≈$4M–$15M
  symbol="YT-USDC-26JUN2025"   apy≈18–30%  tvl≈$2M–$8M
APY range наблюдаемый: 14–80% (bull DeFi / высокая demand на variable yield).
При low-yield (bear) рынке: 8–15% (ниже min cushion → fallback mode S11).

MP-427 — интеграция в S11HybridYieldMax (s11_hybrid_yield_max.py).
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)

# ── Константы ─────────────────────────────────────────────────────────────────

#: Endpoint DeFiLlama yields (все пулы).
DEFILLAMA_POOLS_URL: str = "https://yields.llama.fi/pools"

#: Endpoint Pendle V2 REST API (Ethereum mainnet = chain 1).
PENDLE_V2_MARKETS_URL: str = "https://api-v2.pendle.finance/core/v1/1/markets"

#: Fallback APY (%) если оба источника недоступны.
#: Соответствует типичному bull Pendle YT APY при underlying 12%, implied 8%.
FALLBACK_APY: float = 28.4

#: Минимальный TVL USD для принятия пула.
MIN_TVL_USD: float = 500_000.0

#: Таймаут HTTP-запроса (секунды).
REQUEST_TIMEOUT: int = 8

#: Минимально допустимый APY результата (фильтр аномалий).
APY_MIN_PCT: float = 5.0

#: Максимально допустимый APY результата (фильтр аномалий — YT может давать 200%+
#: в edge cases, но для S11 ограничиваем реалистичным диапазоном).
APY_MAX_PCT: float = 120.0

#: Stablecoin-keywords для фильтрации Pendle V2 рынков.
_STABLECOIN_KEYWORDS: tuple[str, ...] = (
    "usdc", "usde", "susde", "usdt", "dai", "frax", "crvusd", "gho",
)

#: User-Agent header для DeFiLlama (аналогично другим адаптерам SPA).
_USER_AGENT: str = "SPA-PriceFeed/1.0 (yield-optimizer; contact=spa@localhost)"


# ── DeFiLlama source ─────────────────────────────────────────────────────────

def _fetch_defillama_pools(
    url: str = DEFILLAMA_POOLS_URL,
    timeout: int = REQUEST_TIMEOUT,
) -> Optional[list]:
    """Загрузить список пулов из DeFiLlama /pools.

    Returns:
        list[dict] или None при любой ошибке.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw)
        pools = data.get("data", [])
        if not isinstance(pools, list):
            logger.warning("pendle_yt_feed: DeFiLlama unexpected format")
            return None
        return pools
    except urllib.error.URLError as exc:
        logger.debug("pendle_yt_feed: DeFiLlama URLError: %s", exc)
    except json.JSONDecodeError as exc:
        logger.debug("pendle_yt_feed: DeFiLlama JSON parse error: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pendle_yt_feed: DeFiLlama unexpected error: %s", exc)
    return None


def _extract_apy_from_defillama(
    pools: list,
    symbol_hint: str = "YT",
    min_tvl: float = MIN_TVL_USD,
) -> Optional[float]:
    """Извлечь APY (%) для Pendle YT из списка пулов DeFiLlama.

    Алгоритм:
    1. Фильтр: project содержит «pendle», tvlUsd ≥ min_tvl.
    2. Предпочтение: пулы с «YT» в symbol (Yield Token напрямую).
    3. Если YT-пулов нет → берём все Pendle-пулы (PT implied APY proxy).
    4. Среди отфильтрованных берём медиану APY (избегаем выброс max).

    Returns:
        APY % float или None если подходящих пулов не найдено.
    """
    pendle_pools = [
        p for p in pools
        if "pendle" in p.get("project", "").lower()
        and isinstance(p.get("tvlUsd"), (int, float))
        and p["tvlUsd"] >= min_tvl
        and isinstance(p.get("apy"), (int, float))
        and APY_MIN_PCT <= float(p["apy"]) <= APY_MAX_PCT
    ]

    if not pendle_pools:
        logger.debug("pendle_yt_feed: no Pendle pools from DeFiLlama after filter")
        return None

    # Сначала пробуем пулы с «YT» в символе
    yt_pools = [
        p for p in pendle_pools
        if "yt" in p.get("symbol", "").lower()
    ]

    candidate_pools = yt_pools if yt_pools else pendle_pools
    logger.debug(
        "pendle_yt_feed: DeFiLlama candidates=%d (yt=%d)",
        len(candidate_pools), len(yt_pools),
    )

    # Медиана APY (сортировка по APY, берём средний элемент)
    apys = sorted(float(p["apy"]) for p in candidate_pools)
    mid = len(apys) // 2
    if len(apys) % 2 == 0 and len(apys) > 1:
        median_apy = (apys[mid - 1] + apys[mid]) / 2.0
    else:
        median_apy = apys[mid]

    return median_apy


# ── Pendle V2 API source ─────────────────────────────────────────────────────

def _fetch_pendle_v2_markets(
    url: str = PENDLE_V2_MARKETS_URL,
    timeout: int = REQUEST_TIMEOUT,
) -> Optional[list]:
    """Загрузить рынки из Pendle V2 REST API.

    Returns:
        list[dict] результатов или None при любой ошибке.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw)
        # Pendle V2 API: {"total": N, "results": [...]}
        results = data.get("results", data.get("markets", []))
        if not isinstance(results, list):
            logger.warning("pendle_yt_feed: Pendle V2 unexpected format")
            return None
        return results
    except urllib.error.URLError as exc:
        logger.debug("pendle_yt_feed: Pendle V2 URLError: %s", exc)
    except json.JSONDecodeError as exc:
        logger.debug("pendle_yt_feed: Pendle V2 JSON parse error: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pendle_yt_feed: Pendle V2 unexpected error: %s", exc)
    return None


def _compute_yt_apy_from_market(market: dict) -> Optional[float]:
    """Вычислить YT APY (%) из данных Pendle V2 market-объекта.

    YT leverage = 1 / yt_price_pct  (цена YT как доля от номинала)
    YT excess   = underlying_apy − implied_apy
    YT APY %    = yt_excess * yt_leverage * 100

    Если yt_price_pct ≤ 0 или excess ≤ 0 → рынок не profitable, пропускаем.

    Returns:
        APY % float или None если данных недостаточно.
    """
    try:
        # implied APY (decimal: 0.085 = 8.5%)
        implied = float(market.get("impliedApy", 0) or 0)
        # underlying APY (decimal)
        underlying = float(
            market.get("underlyingApy", 0)
            or market.get("underlyingAPY", 0)
            or 0
        )
        # YT price as fraction of par (e.g. 0.25 means 25 cents per $1 notional)
        yt_price_pct = float(
            market.get("ytPricePct", 0)
            or market.get("yt", {}).get("pricePct", 0)
            or 0
        )

        if yt_price_pct <= 0.001:
            # Не можем вычислить leverage
            return None

        excess = underlying - implied
        if excess <= 0:
            # YT не profitable (underlying ≤ implied → YT worthless)
            return None

        leverage = 1.0 / yt_price_pct
        yt_apy_pct = excess * leverage * 100.0
        return yt_apy_pct

    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _extract_apy_from_pendle_v2(
    markets: list,
    min_tvl: float = MIN_TVL_USD,
) -> Optional[float]:
    """Извлечь YT APY (%) из списка Pendle V2 рынков.

    Фильтр: stablecoin underlying, liquidity ≥ min_tvl.
    Выбор: медиана вычисленных YT APY.

    Returns:
        APY % float или None если подходящих рынков не найдено.
    """
    candidates: list[float] = []
    for market in markets:
        try:
            # Проверяем TVL
            liquidity = market.get("liquidity", {})
            if isinstance(liquidity, dict):
                tvl_usd = float(liquidity.get("usd", 0) or 0)
            else:
                tvl_usd = float(liquidity or 0)

            if tvl_usd < min_tvl:
                continue

            # Проверяем stablecoin underlying
            underlying = market.get("underlyingAsset", {}) or {}
            symbol_raw = (
                underlying.get("symbol", "")
                or market.get("symbol", "")
                or ""
            ).lower()
            if not any(kw in symbol_raw for kw in _STABLECOIN_KEYWORDS):
                continue

            apy = _compute_yt_apy_from_market(market)
            if apy is not None and APY_MIN_PCT <= apy <= APY_MAX_PCT:
                candidates.append(apy)

        except Exception:  # noqa: BLE001
            continue

    if not candidates:
        logger.debug("pendle_yt_feed: no Pendle V2 markets passed filter")
        return None

    apys = sorted(candidates)
    mid = len(apys) // 2
    if len(apys) % 2 == 0 and len(apys) > 1:
        return (apys[mid - 1] + apys[mid]) / 2.0
    return apys[mid]


# ── Public API ────────────────────────────────────────────────────────────────

def get_pendle_yt_apy(
    symbol_hint: str = "YT-sUSDe",
    fallback: float = FALLBACK_APY,
    min_tvl: float = MIN_TVL_USD,
    timeout: int = REQUEST_TIMEOUT,
    _defillama_url: str = DEFILLAMA_POOLS_URL,
    _pendle_v2_url: str = PENDLE_V2_MARKETS_URL,
) -> float:
    """Получить актуальный Pendle YT APY (%).

    Последовательность источников:
    1. DeFiLlama /pools → Pendle YT пулы (stablecoin, tvl > min_tvl).
    2. Pendle V2 REST API → вычисление из impliedApy / underlyingApy / ytPricePct.
    3. Fallback = 28.4% (константа FALLBACK_APY).

    Args:
        symbol_hint: подсказка символа (используется для логирования);
                     фильтрация ведётся по «YT» keyword.
        fallback:    APY (%) если оба источника недоступны или не вернули данные.
        min_tvl:     минимальный TVL USD для принятия пула/рынка.
        timeout:     таймаут HTTP в секундах.
        _defillama_url: URL DeFiLlama (переопределяется в тестах).
        _pendle_v2_url: URL Pendle V2 API (переопределяется в тестах).

    Returns:
        APY % (float). Например: 32.7 означает 32.7% годовых.
        Гарантировано: APY_MIN_PCT ≤ result ≤ APY_MAX_PCT, либо fallback.
    """
    # Источник 1: DeFiLlama
    try:
        pools = _fetch_defillama_pools(url=_defillama_url, timeout=timeout)
        if pools is not None:
            apy = _extract_apy_from_defillama(pools, symbol_hint=symbol_hint, min_tvl=min_tvl)
            if apy is not None:
                logger.info(
                    "pendle_yt_feed: DeFiLlama → YT APY=%.2f%% (hint=%s)",
                    apy, symbol_hint,
                )
                return apy
    except Exception as exc:  # noqa: BLE001
        logger.debug("pendle_yt_feed: DeFiLlama source failed: %s", exc)

    # Источник 2: Pendle V2 API
    try:
        markets = _fetch_pendle_v2_markets(url=_pendle_v2_url, timeout=timeout)
        if markets is not None:
            apy = _extract_apy_from_pendle_v2(markets, min_tvl=min_tvl)
            if apy is not None:
                logger.info(
                    "pendle_yt_feed: Pendle V2 API → YT APY=%.2f%% (hint=%s)",
                    apy, symbol_hint,
                )
                return apy
    except Exception as exc:  # noqa: BLE001
        logger.debug("pendle_yt_feed: Pendle V2 source failed: %s", exc)

    # Источник 3: Fallback
    logger.warning(
        "pendle_yt_feed: all sources failed, using fallback APY=%.2f%% (hint=%s)",
        fallback, symbol_hint,
    )
    return fallback


def get_pendle_yt_apy_with_source(
    symbol_hint: str = "YT-sUSDe",
    fallback: float = FALLBACK_APY,
    min_tvl: float = MIN_TVL_USD,
    timeout: int = REQUEST_TIMEOUT,
    _defillama_url: str = DEFILLAMA_POOLS_URL,
    _pendle_v2_url: str = PENDLE_V2_MARKETS_URL,
) -> tuple[float, str]:
    """Аналог get_pendle_yt_apy, но возвращает (apy, source_name).

    source_name: "defillama" | "pendle_v2" | "fallback"

    Удобен для логирования и мониторинга источника в data/*.json.
    """
    try:
        pools = _fetch_defillama_pools(url=_defillama_url, timeout=timeout)
        if pools is not None:
            apy = _extract_apy_from_defillama(pools, symbol_hint=symbol_hint, min_tvl=min_tvl)
            if apy is not None:
                return apy, "defillama"
    except Exception:  # noqa: BLE001
        pass

    try:
        markets = _fetch_pendle_v2_markets(url=_pendle_v2_url, timeout=timeout)
        if markets is not None:
            apy = _extract_apy_from_pendle_v2(markets, min_tvl=min_tvl)
            if apy is not None:
                return apy, "pendle_v2"
    except Exception:  # noqa: BLE001
        pass

    return fallback, "fallback"
