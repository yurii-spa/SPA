"""
spa_core/adapters/gmx_research.py — GMX Fee Yield Adapter (RESEARCH ONLY)

Fetches GMX GLP/GM pool APY from DeFiLlama.
Status: RESEARCH_ONLY — not in strict evidence mode.

DeFiLlama endpoints:
  GET https://yields.llama.fi/pools → filter by project="gmx" or "gmx-v2"
  Pool IDs for GMX v1 GLP: varies by chain (arbitrum, avalanche)
  GMX v2 GM pools: multiple per asset pair

Что это:
  GLP holders earn: trading fees + liquidation fees + funding fees - trader PnL
  Risk: if traders profit consistently, GLP loses (counterparty risk)
  Historical APY range: 15-45% APY (highly volatile)

ВАЖНО: Это research adapter. APY волатилен и зависит от рыночного режима.
  Используется только для аналитики / advisory — не открывает позиций.

Правила (проектные):
  - Только stdlib Python (urllib.request, json, time, logging)
  - Timeout = 5s, graceful fallback при сбое сети → FALLBACK_APY_PCT
  - Не импортировать из execution / feed_health / risk
  - Атомарные записи не требуются (адаптер не пишет state-файлы)
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ── константы ────────────────────────────────────────────────────────────────

RESEARCH_ONLY: bool = True
SOURCE_ID: str = "gmx_research"

DEFI_LLAMA_POOLS_URL: str = "https://yields.llama.fi/pools"

# При сбое сети / отсутствии данных — плейсхолдер из исторического диапазона
FALLBACK_APY_PCT: float = 15.0

# Таймаут HTTP-запроса
REQUEST_TIMEOUT_S: int = 5

# TTL внутреннего кэша (секунды)
_CACHE_TTL_S: int = 300

# Ключи пулов, которые возвращает fetch_apy()
_KEY_GLP_ARB = "gmx_glp_arbitrum"
_KEY_GLP_AVAX = "gmx_glp_avalanche"
_KEY_V2_BTC = "gmx_v2_btc"
_KEY_V2_ETH = "gmx_v2_eth"

# Теги для поиска на DeFiLlama
_GMX_V1_PROJECT = "gmx"
_GMX_V2_PROJECT = "gmx-v2"


# ── адаптер ──────────────────────────────────────────────────────────────────

class GMXResearchAdapter:
    """Research-only адаптер GMX GLP/GM fee yield via DeFiLlama.

    Метод ``fetch_apy()`` возвращает словарь с APY в процентах (e.g. 25.3 ==
    25.3 %) для нескольких GMX пулов. При сбое сети возвращает словарь с
    плейсхолдерным APY ``FALLBACK_APY_PCT = 15.0`` — исключений не бросает.

    ``btc_exposure_apy()`` / ``eth_exposure_apy()`` возвращают APY для
    BTC- и ETH-коррелированного слота (RS-001 / RS-002).

    Флаг ``RESEARCH_ONLY = True`` — адаптер не открывает позиций и не
    модифицирует никакие state-файлы.
    """

    def __init__(self, chain: str = "arbitrum") -> None:
        self.chain = chain.lower()
        # Внутренний кэш: хранит (pools_list, timestamp)
        self._cache: Optional[list] = None
        self._cache_ts: float = 0.0

    # ── internal ─────────────────────────────────────────────────────────────

    def _fetch_pools(self) -> Optional[list]:
        """Загружает список пулов с DeFiLlama (с кэшом TTL 300 с).

        Возвращает список пулов или None при сбое сети / невалидном ответе.
        Никогда не бросает исключений.
        """
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < _CACHE_TTL_S:
            return self._cache

        try:
            req = urllib.request.Request(
                DEFI_LLAMA_POOLS_URL,
                headers={"Accept-Encoding": "gzip", "User-Agent": "SPA-Research/1.0"},
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                raw = resp.read()
            payload = json.loads(raw)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
            logger.warning("GMXResearchAdapter: network error fetching DeFiLlama: %s", exc)
            return None
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("GMXResearchAdapter: JSON parse error: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("GMXResearchAdapter: unexpected error: %s", exc)
            return None

        if not isinstance(payload, dict) or payload.get("status") != "success":
            logger.warning("GMXResearchAdapter: unexpected DeFiLlama payload shape")
            return None

        data = payload.get("data")
        if not isinstance(data, list):
            logger.warning("GMXResearchAdapter: DeFiLlama 'data' is not a list")
            return None

        self._cache = data
        self._cache_ts = now
        return data

    def _best_pool_apy(
        self, pools: list, project: str, chain: str, symbol_fragment: str = ""
    ) -> Optional[float]:
        """Находит лучший пул по project/chain и (опционально) символу.

        Возвращает APY в процентах (e.g. 25.3) или None, если пул не найден.
        Среди нескольких совпадений берёт пул с наибольшим TVL.
        """
        project_l = project.lower()
        chain_l = chain.lower()
        frag_u = symbol_fragment.upper() if symbol_fragment else ""

        best_apy: Optional[float] = None
        best_tvl: float = float("-inf")

        for pool in pools:
            if not isinstance(pool, dict):
                continue
            if str(pool.get("project", "")).lower() != project_l:
                continue
            if str(pool.get("chain", "")).lower() != chain_l:
                continue
            if frag_u and frag_u not in str(pool.get("symbol", "")).upper():
                continue

            apy_raw = pool.get("apy")
            if not isinstance(apy_raw, (int, float)):
                continue
            apy = float(apy_raw)
            if apy < 0 or apy > 500:  # sanity bound (GMX может давать очень высокий APY)
                continue

            tvl_raw = pool.get("tvlUsd", 0)
            tvl = float(tvl_raw) if isinstance(tvl_raw, (int, float)) else 0.0

            if tvl > best_tvl:
                best_tvl = tvl
                best_apy = apy

        return best_apy

    def _make_entry(
        self, apy: Optional[float], source: str = "defillama", fallback: bool = False
    ) -> dict:
        """Формирует запись для словаря результатов fetch_apy()."""
        effective_apy = apy if apy is not None else FALLBACK_APY_PCT
        return {
            "apy": effective_apy,
            "tvl_usd": None,  # TVL доступен через _best_pool_apy при необходимости
            "source": source,
            "fallback": fallback or apy is None,
        }

    # ── public API ────────────────────────────────────────────────────────────

    def fetch_apy(self) -> dict:
        """Возвращает словарь APY для GMX пулов (все значения в процентах).

        Структура:
            {
              "gmx_glp_arbitrum":  {"apy": float, "tvl_usd": None, "source": str, "fallback": bool},
              "gmx_glp_avalanche": {"apy": float, ...},
              "gmx_v2_btc":        {"apy": float, ...},
              "gmx_v2_eth":        {"apy": float, ...},
            }

        При сбое сети / пул не найден → apy = FALLBACK_APY_PCT = 15.0, fallback=True.
        Никогда не бросает исключений.
        """
        pools = self._fetch_pools()

        if pools is None:
            # Полный fallback: сеть недоступна
            logger.info("GMXResearchAdapter.fetch_apy: using full fallback (network error)")
            return {
                _KEY_GLP_ARB:  self._make_entry(None, source="fallback", fallback=True),
                _KEY_GLP_AVAX: self._make_entry(None, source="fallback", fallback=True),
                _KEY_V2_BTC:   self._make_entry(None, source="fallback", fallback=True),
                _KEY_V2_ETH:   self._make_entry(None, source="fallback", fallback=True),
            }

        # GLP v1: project="gmx", symbol содержит "GLP"
        glp_arb_apy  = self._best_pool_apy(pools, _GMX_V1_PROJECT, "arbitrum",  "GLP")
        glp_avax_apy = self._best_pool_apy(pools, _GMX_V1_PROJECT, "avalanche", "GLP")

        # GM v2: project="gmx-v2", различные символы вида "GM:BTC-USDC"
        v2_btc_apy = self._best_pool_apy(pools, _GMX_V2_PROJECT, "arbitrum", "BTC")
        v2_eth_apy = self._best_pool_apy(pools, _GMX_V2_PROJECT, "arbitrum", "ETH")

        return {
            _KEY_GLP_ARB:  self._make_entry(glp_arb_apy),
            _KEY_GLP_AVAX: self._make_entry(glp_avax_apy),
            _KEY_V2_BTC:   self._make_entry(v2_btc_apy),
            _KEY_V2_ETH:   self._make_entry(v2_eth_apy),
        }

    def btc_exposure_apy(self) -> float:
        """APY (%) для BTC-коррелированного слота GMX (для RS-001 gmx_btc).

        Приоритет: GMX v2 BTC/USD GM пул → GLP Arbitrum (BTC-exposed) → fallback.
        Возвращает значение > 0 всегда (минимум FALLBACK_APY_PCT).
        """
        data = self.fetch_apy()
        # Предпочитаем прямой BTC-пул v2
        v2_btc = data[_KEY_V2_BTC]["apy"]
        if v2_btc > 0:
            return v2_btc
        # Иначе GLP (широко диверсифицирован, BTC ~30% веса)
        glp_arb = data[_KEY_GLP_ARB]["apy"]
        if glp_arb > 0:
            return glp_arb
        return FALLBACK_APY_PCT

    def eth_exposure_apy(self) -> float:
        """APY (%) для ETH-коррелированного слота GMX (для RS-001 gmx_eth).

        Приоритет: GMX v2 ETH/USD GM пул → GLP Arbitrum → fallback.
        Возвращает значение > 0 всегда (минимум FALLBACK_APY_PCT).
        """
        data = self.fetch_apy()
        v2_eth = data[_KEY_V2_ETH]["apy"]
        if v2_eth > 0:
            return v2_eth
        glp_arb = data[_KEY_GLP_ARB]["apy"]
        if glp_arb > 0:
            return glp_arb
        return FALLBACK_APY_PCT

    def is_research_only(self) -> bool:
        """Всегда True — адаптер строго read-only / advisory."""
        return RESEARCH_ONLY

    def source_metadata(self) -> dict:
        """Возвращает метаданные источника для source_pipeline / аудита."""
        return {
            "source_id": SOURCE_ID,
            "adapter": "GMXResearchAdapter",
            "research_only": RESEARCH_ONLY,
            "chain": self.chain,
            "data_source": "DeFiLlama yields API",
            "endpoint": DEFI_LLAMA_POOLS_URL,
            "fallback_apy_pct": FALLBACK_APY_PCT,
            "timeout_s": REQUEST_TIMEOUT_S,
            "cache_ttl_s": _CACHE_TTL_S,
            "projects_queried": [_GMX_V1_PROJECT, _GMX_V2_PROJECT],
            "pool_keys": [_KEY_GLP_ARB, _KEY_GLP_AVAX, _KEY_V2_BTC, _KEY_V2_ETH],
            "risk_note": (
                "GLP counterparty risk: LP is short traders. "
                "APY highly volatile (15-45%+). RESEARCH_ONLY."
            ),
        }

    def invalidate_cache(self) -> None:
        """Сбрасывает внутренний кэш (полезно в тестах)."""
        self._cache = None
        self._cache_ts = 0.0
