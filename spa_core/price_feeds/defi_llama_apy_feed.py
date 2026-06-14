"""spa_core/price_feeds/defi_llama_apy_feed.py — унифицированный APY-фид.

Получает live APY по whitelisted SPA-протоколам через DeFiLlama /pools.
Если сеть недоступна или пул не найден — возвращает hardcoded fallback.

Дизайн-принципы
---------------
* **stdlib only** — urllib.request, json, time, logging. Ноль внешних зависимостей.
* **Never raises** — все исключения перехватываются; функции всегда возвращают значение.
* **Read-only / advisory** — не модифицирует allocator/risk/execution.
* **LLM FORBIDDEN** в данном модуле (CLAUDE.md: LLM_FORBIDDEN_AGENTS).

PROTOCOL_POOL_MAP
-----------------
Ключ адаптера → (project, chain, fallback_apy_%):
  - project/chain — ключи для поиска пула в DeFiLlama /pools
  - fallback_apy  — % APY, возвращаемый если DeFiLlama недоступна

DeFiLlama matching: project.lower() содержит keyword И chain.lower() == chain_key.
Среди совпадающих пулов выбирается пул с максимальным tvlUsd (highest-liquidity).
APY возвращается в процентах (e.g. 4.8 означает 4.8% годовых).

Публичное API
-------------
fetch_apy_map(timeout_seconds=10) -> dict[str, float]
    Возвращает {adapter_id: apy%} для всех ключей PROTOCOL_POOL_MAP.
    Никогда не поднимает исключение. При любой ошибке — fallback.

get_adapter_apy(adapter_id, timeout_seconds=5) -> float
    APY% для одного адаптера; fallback если недоступен.

_fetch_all_pools(url, timeout) -> list | None
    Внутренняя: скачать /pools, вернуть list или None при ошибке.

_best_pool_apy(pools, project_key, chain_key, min_tvl) -> float | None
    Внутренняя: найти лучший пул и вернуть APY%.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)

# ── Endpoint ──────────────────────────────────────────────────────────────────

DEFILLAMA_POOLS_URL: str = "https://yields.llama.fi/pools"

# Таймаут по умолчанию для полного маппинга (сеть медленная — даём запас).
DEFAULT_TIMEOUT: int = 10

# Минимальный TVL (USD) пула чтобы считать его живым (не spam/dead).
MIN_TVL_USD: float = 1_000_000.0

# APY-аномалии: меньше нижней границы или больше верхней — не принимаем.
APY_MIN_PCT: float = 0.1
APY_MAX_PCT: float = 100.0

_USER_AGENT: str = "SPA-PriceFeed/1.0 (defi-llama-apy-feed; contact=spa@localhost)"

# ── Protocol → DeFiLlama mapping ─────────────────────────────────────────────

# Формат: adapter_id → (project_keyword, chain_keyword, fallback_apy_pct)
#
# project_keyword — ищется как подстрока в pool["project"].lower()
# chain_keyword   — сравнивается с pool["chain"].lower() (точное совпадение)
# fallback_apy    — % APY при недоступности DeFiLlama
#
# Источники fallback (2026-Q2 средние):
#   Aave V3 Eth ~3.5%, Compound V3 ~4.0%, Morpho Blue ~4.8%,
#   Spark sUSDS ~4.6%, Yearn V3 ~5.5%, Euler V2 ~5.2%, Maple ~6.5%,
#   Pendle ~8.5%, Aave V3 Base ~3.8%, Morpho Blue Base ~5.0%,
#   Extra Finance Base ~8.0%

PROTOCOL_POOL_MAP: dict[str, tuple[str, str, float]] = {
    # T1 — Ethereum mainnet lending
    "aave_v3":        ("aave-v3",      "ethereum", 3.5),
    "compound_v3":    ("compound-v3",  "ethereum", 4.0),
    "morpho_blue":    ("morpho-blue",  "ethereum", 4.8),
    "spark_susds":    ("spark",        "ethereum", 4.6),
    # T2 — Ethereum mainnet (higher APY, lower TVL)
    "yearn_v3":       ("yearn-v3",     "ethereum", 5.5),
    "euler_v2":       ("euler-v2",     "ethereum", 5.2),
    "maple":          ("maple",        "ethereum", 6.5),
    # T3-SPEC — Pendle (Ethereum)
    "pendle":         ("pendle",       "ethereum", 8.5),
    # Base chain adapters
    "aave_v3_base":         ("aave-v3",       "base", 3.8),
    "morpho_blue_base":     ("morpho-blue",   "base", 5.0),
    "extra_finance_base":   ("extra-finance", "base", 8.0),
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_all_pools(
    url: str = DEFILLAMA_POOLS_URL,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[list]:
    """Скачать /pools DeFiLlama и вернуть список пулов.

    Returns:
        list[dict] при успехе; None при любой ошибке (сеть, JSON, структура).
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            logger.warning("defi_llama_apy_feed: payload is not a dict")
            return None
        data = payload.get("data")
        if not isinstance(data, list):
            logger.warning("defi_llama_apy_feed: payload['data'] is not a list")
            return None
        return data
    except urllib.error.URLError as exc:
        logger.debug("defi_llama_apy_feed: URLError: %s", exc)
    except json.JSONDecodeError as exc:
        logger.debug("defi_llama_apy_feed: JSON decode error: %s", exc)
    except OSError as exc:
        logger.debug("defi_llama_apy_feed: OSError: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("defi_llama_apy_feed: unexpected error: %s", exc)
    return None


def _best_pool_apy(
    pools: list,
    project_key: str,
    chain_key: str,
    min_tvl: float = MIN_TVL_USD,
) -> Optional[float]:
    """Найти лучший пул для протокола и вернуть его APY%.

    Критерии:
    - pool["project"].lower() содержит project_key
    - pool["chain"].lower() == chain_key
    - pool["tvlUsd"] >= min_tvl
    - APY_MIN_PCT <= pool["apy"] <= APY_MAX_PCT

    Выбор: пул с максимальным tvlUsd (наиболее ликвидный = наиболее достоверный).

    Returns:
        APY % float или None если ни один пул не прошёл фильтр.
    """
    best_pool: Optional[dict] = None
    best_tvl: float = -1.0

    project_key_l = project_key.lower()
    chain_key_l = chain_key.lower()

    for pool in pools:
        try:
            project = pool.get("project", "")
            chain = pool.get("chain", "")
            tvl = pool.get("tvlUsd")
            apy = pool.get("apy")

            if not isinstance(project, str) or project_key_l not in project.lower():
                continue
            if not isinstance(chain, str) or chain.lower() != chain_key_l:
                continue
            if not isinstance(tvl, (int, float)) or float(tvl) < min_tvl:
                continue
            if not isinstance(apy, (int, float)):
                continue
            apy_f = float(apy)
            if apy_f < APY_MIN_PCT or apy_f > APY_MAX_PCT:
                continue

            if float(tvl) > best_tvl:
                best_tvl = float(tvl)
                best_pool = pool

        except Exception:  # noqa: BLE001
            continue

    if best_pool is None:
        return None
    return float(best_pool["apy"])


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_apy_map(
    timeout_seconds: int = DEFAULT_TIMEOUT,
    _url: str = DEFILLAMA_POOLS_URL,
    _min_tvl: float = MIN_TVL_USD,
) -> dict[str, float]:
    """Получить APY% для всех адаптеров из PROTOCOL_POOL_MAP.

    Делает один HTTP-запрос к DeFiLlama /pools и разрешает все ключи
    маппинга одновременно (экономия сети).

    При недоступности DeFiLlama (любая ошибка) — все значения из fallback.
    Если DeFiLlama доступна, но конкретный пул не найден — fallback для него.

    Args:
        timeout_seconds: таймаут HTTP-запроса (секунды).
        _url: переопределить URL (используется в тестах).
        _min_tvl: минимальный TVL пула.

    Returns:
        dict[adapter_id → apy_float] — гарантировано содержит все ключи
        PROTOCOL_POOL_MAP. Значение — APY в процентах (4.8 = 4.8% годовых).
        Никогда не поднимает исключение.
    """
    # Сначала заполняем fallback-значениями
    result: dict[str, float] = {
        adapter_id: fallback
        for adapter_id, (_, _, fallback) in PROTOCOL_POOL_MAP.items()
    }

    try:
        t0 = time.monotonic()
        pools = _fetch_all_pools(url=_url, timeout=timeout_seconds)
        elapsed = time.monotonic() - t0

        if pools is None:
            logger.warning(
                "defi_llama_apy_feed: fetch_apy_map — DeFiLlama unavailable, "
                "using all fallbacks"
            )
            return result

        logger.debug(
            "defi_llama_apy_feed: fetched %d pools in %.2fs",
            len(pools), elapsed,
        )

        # Разрешаем каждый адаптер
        live_count = 0
        for adapter_id, (project_key, chain_key, fallback) in PROTOCOL_POOL_MAP.items():
            apy = _best_pool_apy(
                pools,
                project_key=project_key,
                chain_key=chain_key,
                min_tvl=_min_tvl,
            )
            if apy is not None:
                result[adapter_id] = apy
                live_count += 1
                logger.debug(
                    "defi_llama_apy_feed: %s → %.2f%% (live)",
                    adapter_id, apy,
                )
            else:
                logger.debug(
                    "defi_llama_apy_feed: %s → %.2f%% (fallback, pool not found)",
                    adapter_id, fallback,
                )

        logger.info(
            "defi_llama_apy_feed: fetch_apy_map complete — %d/%d live, %d fallback",
            live_count, len(PROTOCOL_POOL_MAP),
            len(PROTOCOL_POOL_MAP) - live_count,
        )

    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders
        logger.warning("defi_llama_apy_feed: fetch_apy_map unexpected error: %s", exc)

    return result


def get_adapter_apy(
    adapter_id: str,
    timeout_seconds: int = 5,
    _url: str = DEFILLAMA_POOLS_URL,
    _min_tvl: float = MIN_TVL_USD,
) -> float:
    """Получить APY% для одного адаптера.

    Делает запрос к DeFiLlama /pools и ищет пул для adapter_id.
    При любой ошибке или если пул не найден — возвращает fallback из маппинга.

    Args:
        adapter_id: ключ из PROTOCOL_POOL_MAP (напр. "aave_v3", "extra_finance_base").
        timeout_seconds: таймаут HTTP-запроса.
        _url: переопределить URL (используется в тестах).
        _min_tvl: минимальный TVL пула.

    Returns:
        APY % float. Если adapter_id неизвестен — возвращает 0.0.
        Никогда не поднимает исключение.
    """
    entry = PROTOCOL_POOL_MAP.get(adapter_id)
    if entry is None:
        logger.warning(
            "defi_llama_apy_feed: unknown adapter_id=%r, returning 0.0",
            adapter_id,
        )
        return 0.0

    project_key, chain_key, fallback = entry

    try:
        pools = _fetch_all_pools(url=_url, timeout=timeout_seconds)
        if pools is not None:
            apy = _best_pool_apy(
                pools,
                project_key=project_key,
                chain_key=chain_key,
                min_tvl=_min_tvl,
            )
            if apy is not None:
                logger.debug(
                    "defi_llama_apy_feed: get_adapter_apy(%s) → %.2f%% (live)",
                    adapter_id, apy,
                )
                return apy
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "defi_llama_apy_feed: get_adapter_apy(%s) error: %s, using fallback",
            adapter_id, exc,
        )

    logger.debug(
        "defi_llama_apy_feed: get_adapter_apy(%s) → %.2f%% (fallback)",
        adapter_id, fallback,
    )
    return fallback
