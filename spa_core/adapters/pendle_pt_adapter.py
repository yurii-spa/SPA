"""
Pendle PT Adapter — REST-only адаптер для Pendle Finance.

Читает данные рынков PT (Principal Token) через публичный Pendle API v2.
Никаких RPC-ключей, никаких внешних зависимостей — только stdlib.

Tier   : T2
Domain : READ-ONLY (paper trading) — никакого on-chain execution.
Source : https://api-v2.pendle.finance/core/v1/{chain_id}/markets
stdlib : urllib.request, json, datetime — NO external deps.

MP-354 — Pendle PT REST adapter (главный yield unlocker, 8–18% fixed APY).
"""
from __future__ import annotations

import datetime
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# ── Константы API ──────────────────────────────────────────────────────────────

PENDLE_API_BASE = "https://api-v2.pendle.finance/core/v1"

# Timeout и retry для всех HTTP-запросов
PENDLE_TIMEOUT = 10   # секунд
PENDLE_RETRIES = 2    # повторных попыток при ошибке

# Задержка между попытками
_RETRY_DELAY = 1.0    # секунд

# Fallback APY (%) — используется при недоступности API
FALLBACK_APY = 8.0

# ── Фильтры стейблкоинов ──────────────────────────────────────────────────────

# Ключевые слова для поиска USD-стейблкоинов (case-insensitive)
_STABLECOIN_KEYWORDS = frozenset(
    ["usdc", "usde", "susde", "usdt", "dai", "usd", "frax", "gho", "crvusd"]
)


def _is_stablecoin(symbol: str) -> bool:
    """Возвращает True, если символ актива — стейблкоин/USD-пег."""
    sym = symbol.lower()
    return any(kw in sym for kw in _STABLECOIN_KEYWORDS)


# ── HTTP-утилиты ──────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = PENDLE_TIMEOUT) -> dict:
    """
    GET-запрос с возвратом распарсенного JSON.

    Поднимает urllib.error.URLError / urllib.error.HTTPError / ValueError
    при ошибке сети или парсинга.
    """
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SPA-PendlePT-Adapter/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw)


def _http_get_with_retry(
    url: str,
    timeout: int = PENDLE_TIMEOUT,
    retries: int = PENDLE_RETRIES,
) -> dict:
    """
    GET с повторными попытками (retries раз) при сетевых ошибках.

    Поднимает последнее исключение, если все попытки исчерпаны.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return _http_get(url, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            last_exc = exc
            if attempt < retries:
                logger.debug(
                    "pendle_pt_adapter: попытка %d/%d не удалась (%s), ждём %.1fs",
                    attempt + 1, retries + 1, exc, _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)
    raise last_exc  # type: ignore[misc]


# ── Вспомогательные парсеры ───────────────────────────────────────────────────

def _safe_float(val: object, default: float = 0.0) -> float:
    """Безопасное приведение к float без исключений."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_maturity_date(expiry: str) -> Optional[datetime.date]:
    """
    Парсит строку expiry из Pendle API (ISO-8601 или plain date).

    Принимает "2025-09-25T00:00:00.000Z" или "2025-09-25".
    Возвращает None при ошибке.
    """
    if not expiry:
        return None
    try:
        return datetime.date.fromisoformat(expiry[:10])
    except (ValueError, TypeError):
        return None


def _days_to_maturity(maturity: Optional[datetime.date]) -> int:
    """Дней до погашения; 0 если дата в прошлом или None."""
    if maturity is None:
        return 0
    return max(0, (maturity - datetime.date.today()).days)


# ── Основной адаптер ──────────────────────────────────────────────────────────

class PendlePTAdapter:
    """
    Read-only REST-адаптер для рынков Pendle PT (Principal Token).

    Использует только публичный Pendle API v2 — без RPC-ключей.
    Все сетевые вызовы обёрнуты в try/except → fallback данные.

    Tier: T2  |  Network: ethereum  |  Assets: USDC, sUSDe, DAI

    MP-354: главный yield unlocker (8–18% fixed APY).
    """

    def __init__(
        self,
        chain_id: int = 1,
        timeout: int = PENDLE_TIMEOUT,
        retries: int = PENDLE_RETRIES,
    ) -> None:
        # chain_id: 1 = Ethereum mainnet
        self.chain_id = chain_id
        self.timeout = timeout
        self.retries = retries

        # Кэш последнего успешного ответа API (список raw market dict)
        self._raw_cache: list[dict] = []
        # Метка времени последнего успешного фетча (monotonic)
        self._cache_ts: float = 0.0

    # ── Публичный интерфейс ───────────────────────────────────────────────────

    def fetch_markets(self, chain_id: Optional[int] = None) -> list[dict]:
        """
        GET /chains/{chain_id}/markets — список всех рынков.

        Параметры
        ---------
        chain_id : int | None
            Если указан — переопределяет self.chain_id для этого вызова.

        Возвращает список raw market dicts от Pendle API.
        При ошибке сети — возвращает [] (fallback) и логирует warning.
        """
        cid = chain_id if chain_id is not None else self.chain_id
        url = f"{PENDLE_API_BASE}/chains/{cid}/markets?limit=50"
        try:
            data = _http_get_with_retry(url, timeout=self.timeout, retries=self.retries)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pendle_pt_adapter: fetch_markets ошибка: %s", exc)
            return []

        # Pendle API: {"results": [...]} или {"data": [...]} или list
        if isinstance(data, dict):
            markets = data.get("results") or data.get("data") or []
        elif isinstance(data, list):
            markets = data
        else:
            markets = []

        if isinstance(markets, list):
            # Обновляем кэш при успехе
            self._raw_cache = markets
            self._cache_ts = time.monotonic()
            return markets

        logger.warning("pendle_pt_adapter: неожиданный тип results: %s", type(markets))
        return []

    def find_best_usdc_market(self) -> Optional[dict]:
        """
        Находит лучший USDC/sUSDe/DAI рынок по максимальному fixedApy.

        Алгоритм:
        1. Вызывает fetch_markets().
        2. Фильтрует: не истёкшие, stablecoin underlying.
        3. Выбирает рынок с максимальным fixedApy (или impliedApy как запасной).

        Возвращает raw market dict или None если рынков нет.
        """
        markets = self.fetch_markets()
        if not markets:
            # Пробуем кэш при отсутствии свежих данных
            markets = self._raw_cache

        candidates = []
        for m in markets:
            # Фильтр: не истёкший
            if m.get("isExpired") or m.get("is_expired"):
                continue

            # Определяем underlying asset
            underlying_info = m.get("underlyingAsset") or {}
            if isinstance(underlying_info, dict):
                underlying_sym = underlying_info.get("symbol") or ""
            else:
                underlying_sym = str(underlying_info)

            pt_info = m.get("pt") or {}
            pt_sym = (pt_info.get("symbol") or m.get("name") or "")

            # Stablecoin-фильтр: по underlying или названию PT
            if not (_is_stablecoin(underlying_sym) or _is_stablecoin(pt_sym)):
                continue

            # Получаем APY (API возвращает десятичные: 0.089 = 8.9%)
            fixed_apy = _safe_float(m.get("fixedApy") or m.get("impliedApy"), 0.0)
            if fixed_apy <= 0:
                continue

            candidates.append((fixed_apy, m))

        if not candidates:
            return None

        # Сортируем по убыванию APY, берём лучший
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def get_apy(self) -> float:
        """
        Возвращает fixedApy лучшего USDC/sUSDe рынка в процентах (%).

        Например: 0.089 из API → 8.9%.
        При ошибке сети или пустом результате → FALLBACK_APY (8.0%).
        """
        try:
            best = self.find_best_usdc_market()
            if best is None:
                logger.info("pendle_pt_adapter: нет подходящих рынков, fallback APY=%.1f%%", FALLBACK_APY)
                return FALLBACK_APY

            # Pendle API возвращает десятичные (0.089 → 8.9%)
            raw_apy = _safe_float(best.get("fixedApy") or best.get("impliedApy"), 0.0)
            if raw_apy <= 0:
                return FALLBACK_APY

            # Конвертируем: если значение < 1.0 — это десятичная форма
            apy_pct = raw_apy * 100.0 if raw_apy < 1.0 else raw_apy
            return round(apy_pct, 4)

        except Exception as exc:  # noqa: BLE001
            logger.warning("pendle_pt_adapter: get_apy ошибка: %s, fallback=%.1f%%", exc, FALLBACK_APY)
            return FALLBACK_APY

    def get_maturity(self) -> str:
        """
        Возвращает дату истечения лучшего PT в формате ISO (YYYY-MM-DD).

        Возвращает "" если рынок не найден или дата не распарсится.
        """
        try:
            best = self.find_best_usdc_market()
            if best is None:
                return ""
            expiry = best.get("expiry") or best.get("maturity") or ""
            maturity = _parse_maturity_date(expiry)
            return maturity.isoformat() if maturity else ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("pendle_pt_adapter: get_maturity ошибка: %s", exc)
            return ""

    def allocate(self, capital: float) -> dict:
        """
        Виртуальное выделение капитала в позицию Pendle PT.

        Параметры
        ---------
        capital : float
            Сумма в USD для выделения.

        Возвращает словарь с деталями операции (paper trading — не real).
        """
        if capital <= 0:
            raise ValueError(f"capital должен быть > 0, получено: {capital}")

        apy = self.get_apy()
        maturity = self.get_maturity()

        # Ежедневный yield = capital * apy% / 365
        daily_yield = round(capital * (apy / 100.0) / 365.0, 6)

        return {
            "protocol": "pendle-pt",
            "action": "allocate",
            "capital_usd": capital,
            "apy_pct": apy,
            "daily_yield_usd": daily_yield,
            "maturity_date": maturity,
            "tier": "T2",
            "network": "ethereum",
            "is_paper": True,
            "status": "ALLOCATED",
        }

    def withdraw(self, amount: float) -> dict:
        """
        Виртуальное изъятие средств из позиции Pendle PT.

        Параметры
        ---------
        amount : float
            Сумма в USD для изъятия.

        Возвращает словарь с деталями операции (paper trading — не real).
        """
        if amount <= 0:
            raise ValueError(f"amount должен быть > 0, получено: {amount}")

        maturity = self.get_maturity()
        now = datetime.date.today()
        maturity_date = _parse_maturity_date(maturity)
        is_matured = (maturity_date is not None) and (now >= maturity_date)

        return {
            "protocol": "pendle-pt",
            "action": "withdraw",
            "amount_usd": amount,
            "maturity_date": maturity,
            "is_matured": is_matured,
            "tier": "T2",
            "network": "ethereum",
            "is_paper": True,
            "status": "WITHDRAWN",
        }

    def health_check(self) -> bool:
        """
        Проверяет доступность Pendle API.

        Делает лёгкий запрос (limit=1) к /chains/{chain_id}/markets.
        Возвращает True при успехе, False при любой ошибке.
        """
        url = f"{PENDLE_API_BASE}/chains/{self.chain_id}/markets?limit=1"
        try:
            _http_get(url, timeout=self.timeout)
            return True
        except Exception:  # noqa: BLE001
            return False

    def to_dict(self) -> dict:
        """
        Возвращает снапшот адаптера в стандартном формате SPA.

        Поля:
          market_name      — название лучшего PT рынка
          fixed_apy        — fixedApy (%) или FALLBACK_APY
          maturity_date    — дата погашения (ISO) или ""
          days_to_maturity — дней до погашения
          pt_price         — условная цена PT (< 1.0 для дисконтных)
          implied_apy      — implied APY с AMM (%) или FALLBACK_APY
          tier             — "T2"
          network          — "ethereum"
        """
        try:
            best = self.find_best_usdc_market()
        except Exception:  # noqa: BLE001
            best = None

        if best is None:
            return {
                "market_name": "Pendle PT (fallback)",
                "fixed_apy": FALLBACK_APY,
                "maturity_date": "",
                "days_to_maturity": 0,
                "pt_price": 0.0,
                "implied_apy": FALLBACK_APY,
                "tier": "T2",
                "network": "ethereum",
                "source": "fallback",
            }

        # Имя рынка
        pt_info = best.get("pt") or {}
        market_name = pt_info.get("symbol") or best.get("name") or "Pendle PT"

        # APY
        raw_fixed = _safe_float(best.get("fixedApy") or best.get("impliedApy"), 0.0)
        raw_implied = _safe_float(best.get("impliedApy") or best.get("fixedApy"), 0.0)

        # Конвертируем decimal → percent если нужно
        def _to_pct(v: float) -> float:
            return round(v * 100.0 if v < 1.0 else v, 4)

        fixed_apy = _to_pct(raw_fixed) if raw_fixed > 0 else FALLBACK_APY
        implied_apy = _to_pct(raw_implied) if raw_implied > 0 else FALLBACK_APY

        # Maturity
        expiry = best.get("expiry") or best.get("maturity") or ""
        mat_date = _parse_maturity_date(expiry)
        maturity_str = mat_date.isoformat() if mat_date else ""
        days_left = _days_to_maturity(mat_date)

        # PT price (из AMM данных или расчётно из APY/days)
        pt_price_raw = _safe_float(
            (best.get("pt") or {}).get("price")
            or best.get("ptPrice")
            or 0.0
        )
        if pt_price_raw <= 0 and fixed_apy > 0 and days_left > 0:
            # Расчётная цена: discount = APY * days/365
            discount = (fixed_apy / 100.0) * (days_left / 365.0)
            pt_price_raw = round(1.0 - discount, 6)

        return {
            "market_name": market_name,
            "fixed_apy": fixed_apy,
            "maturity_date": maturity_str,
            "days_to_maturity": days_left,
            "pt_price": pt_price_raw,
            "implied_apy": implied_apy,
            "tier": "T2",
            "network": "ethereum",
            "source": "pendle_rest_api",
        }
