"""Morpho Blue Steakhouse USDC vault adapter (T2) — MP-355 + own-29 live feed.

Конкретный адаптер для хранилища Steakhouse USDC на Morpho Blue Mainnet.
Vault address: 0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB.

own-29 (2026-08-05): добавлен ЖИВОЙ путь TVL/APY через DeFiLlama
(``project="morpho-blue"``, ``symbol="STEAKUSDC"``, chain Ethereum — после
реструктуризации DeFiLlama vault-пулы Morpho Blue живут под vault-символами,
не под «USDC»). ``get_yield_info()`` теперь отдаёт живые apy/tvl_usd с
``tvl_source="live"`` (ADR-053) и fail-CLOSED ``None`` без живых данных —
константа НИКОГДА не подставляется в TVL-floor.

Ключевые характеристики:
- Tier T2 — лимит 20% портфеля (ADR-070 п.6: один vault — один риск, оценка 0.30)
- APY (``get_apy_pct`` / ``get_apy``): живой фид → data/adapter_status.json
  (поле morpho_steakhouse.apy) → **None**. Подстановка 6.5 % удалена 2026-08-08
  решением владельца (ADR-063 п.3 доведён до конца); ``switch_recommended()``
  без наблюдения отвечает False (fail-CLOSED)
- Quick Win #1: +200 bps vs Aave mainnet (3.2%) → рекомендует switch при
  превышении порога 50 bps над Aave
- Модуль строго read-only / advisory: никогда не трогает живой капитал

Правила:
- Только stdlib Python (без внешних зависимостей)
- Атомарные записи не нужны: адаптер не пишет state-файлы
- Не импортировать из execution / feed_health / risk
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from spa_core.utils.errors import safe_call
from spa_core.utils.data_dir import own_data_dir
from spa_core.adapters._pool_identity import resolved_pool_id

logger = logging.getLogger(__name__)

# Корень репо — два уровня выше пакета adapters
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class MorphoSteakhouseAdapter(BaseAdapter):
    """Read-only advisory адаптер для Morpho Blue Steakhouse USDC vault (T2).

    APY берётся из живого DeFiLlama-фида, затем из ``data/adapter_status.json``
    → ``morpho_steakhouse.apy`` (значение в процентах). При отсутствии обоих
    источников возвращается ``None`` — подстановки НЕТ (ADR-063 п.3).

    Метод ``switch_recommended()`` возвращает True, если
    ``morpho_apy_pct > aave_apy_pct + SWITCH_THRESHOLD_BPS / 100``.
    """

    # ── идентичность ─────────────────────────────────────────────────────
    PROTOCOL = "morpho_steakhouse"
    VAULT_ADDRESS = "0xBEEF01735c132Ada46AA9aA4c54623cAA92A64CB"
    VAULT_NAME = "Steakhouse USDC"

    # ── тир / риск ───────────────────────────────────────────────────────
    # ИСПРАВЛЕНО 2026-08-29: здесь стояло TIER="T1", T1_CAP=0.40, RISK_SCORE=0.22.
    #
    # Решение владельца **ADR-070 п.6** (07.08): «morpho_steakhouse риск-оценка =
    # оценка morpho_blue — один vault, один риск». Оценка morpho_blue = 0.30, а по
    # контракту тиров (`protocol_risk_map.TIER_BANDS`: T1 < 0.25) это обязывает T2.
    #
    # Решение доехало до ТРЁХ источников из четырёх — `PROTOCOL_RISK_SCORES`,
    # `ADAPTER_REGISTRY`, `tier_map` — и не доехало сюда. А снимок оркестратора
    # берёт тир именно отсюда, аллокатор строит из снимка свои потолки, и
    # `validation_summary` дневного цикла печатал T1 55 % / T2 35 % вместо
    # T1 40 % / T2 **50 %**: цикл видел 15 пунктов запаса в T2, которых нет.
    #
    # Числа НЕ выбраны здесь: они читаются из канона (`PROTOCOL_RISK_SCORES`),
    # чтобы четвёртая копия не завелась заново. Тир объявляется в одном месте —
    # `docs/tier_criteria.md` §2.
    TIER = "T2"
    RISK_SCORE = 0.30      # = оценка morpho_blue (ADR-070 п.6)
    # Совместимость: часть кода читает `T1_CAP` как «потолок этого протокола».
    # Имя историческое и теперь вводит в заблуждение, поэтому значение —
    # потолок T2, а не T1.
    T1_CAP = 0.20          # потолок T2 (RiskConfig.max_concentration_t2)

    # SPA-V412: instant exit — позиция ликвидна на уровне Morpho Blue lending
    EXIT_LATENCY_HOURS = 0.0

    # ── APY параметры ────────────────────────────────────────────────────
    # FALLBACK_APY_PCT УДАЛЁН 2026-08-08 (решение владельца, вариант 1 карточки
    # owner-decision-morfo-40-knigi-pri-propazhe-dannyh-podst). Атрибута больше
    # НЕТ намеренно: пока он существует, его легко «вернуть на минутку».
    # Нет наблюдения ⇒ None (ADR-063 п.3).
    AAVE_MAINNET_APY_PCT: float = 3.2   # % (benchmark для switch-рекомендации)
    SWITCH_THRESHOLD_BPS: int = 50      # минимальный отрыв (bps) для рекомендации switch

    # ── quick win метаданные ─────────────────────────────────────────────
    QUICK_WIN: bool = True
    BPS_GAIN: int = 200    # vs Aave mainnet 3.2%

    # ВНИМАНИЕ: это ИСТОРИЧЕСКАЯ заметка от 2026-06, а не текущее утверждение.
    # Её «6.5 %» — тот же самый удалённый литерал. Новое число сюда НЕ вписано
    # намеренно: живой APY читается методами адаптера, а не константой в тексте.
    STRATEGY_NOTE: str = (
        "Quick Win #1 (историческая заметка 2026-06, НЕ живое число): switch $50K"
        " from Aave mainnet (3.2%) to Morpho Steakhouse (тогда 6.5%) = +$1,650/yr"
        " on $50K. Актуальную доходность брать из get_apy_pct(), не отсюда."
    )

    # ── DeFiLlama пул (own-29: живая интеграция) ─────────────────────────
    DEFILLAMA_PROJECT = "morpho-blue"
    # DeFiLlama-символ vault-пула Steakhouse USDC (точное совпадение; среди
    # дублей выигрывает пул с максимальным TVL — конвенция фида).
    DEFILLAMA_SYMBOL = "STEAKUSDC"
    DEFILLAMA_CHAIN = "Ethereum"
    # Метаданные: адрес vault-контракта (НЕ DeFiLlama uuid, НЕ источник TVL).
    DEFILLAMA_POOL_ID = "BEEF01735c132Ada46AA9aA4c54623cAA92A64CB"

    def __init__(
        self,
        asset: str = "USDC",
        data_dir: Optional[Path | str] = None,
        feed: Optional[DeFiLlamaFeed] = None,
    ) -> None:
        super().__init__(asset)
        self.tier = self.TIER
        self._data_dir = Path(data_dir) if data_dir is not None else own_data_dir(_DEFAULT_DATA_DIR)
        # own-29: живой DeFiLlama-фид. Контракт как у аллокатора (ADR-061):
        # дефолтный фид НЕ ходит в сеть под pytest — тесты обязаны инжектить
        # FakeFeed явно (DeFiLlama gzip офлайн падает; правило adapters.md).
        if feed is not None:
            self.feed = feed
        else:
            self.feed = DeFiLlamaFeed(
                enabled=not os.environ.get("PYTEST_CURRENT_TEST")
            )
        # Виртуальная аллокация (только для paper trading учёта)
        self._allocated: float = 0.0

    # ── внутреннее чтение JSON ───────────────────────────────────────────

    def _read_apy_from_status(self) -> Optional[float]:
        """Читает APY (%) из data/adapter_status.json → morpho_steakhouse.apy.

        Возвращает float в процентах (например 6.5) или None при любой ошибке
        / отсутствии поля. Никогда не бросает исключений.
        """
        try:
            path = self._data_dir / "adapter_status.json"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            ms = data.get("morpho_steakhouse", {})
            apy = ms.get("apy")
            if isinstance(apy, (int, float)) and not isinstance(apy, bool):
                return float(apy)
        except Exception as exc:  # noqa: BLE001 — graceful fallback
            logger.debug("morpho_steakhouse: не удалось прочитать APY из JSON: %s", exc)
        return None

    # ── own-29: живой DeFiLlama-фид ──────────────────────────────────────

    def fetch_live(self) -> dict:
        """Живые APY/TVL пула STEAKUSDC из DeFiLlama. Никогда не бросает.

        Возвращает плоский dict в конвенции live-адаптеров (aave_v3 и т.п.):
        ``apy`` — decimal (0.035 = 3.5%), ``tvl`` — USD. Любой сбой фида /
        отсутствие пула → ``status="error"``, ``apy=None``, ``tvl=None``,
        ``live_data=False`` — НИКОГДА не константа (fail-CLOSED).
        """
        record: dict = {
            "pool_id": self.PROTOCOL,
            "protocol": self.PROTOCOL,
            "tier": self.tier,
            "apy": None,
            "tvl": None,
            "status": "error",
            "error": "live_feed_unavailable",
            "live_data": False,
            "source": "defillama",
            "ts": time.time(),
        }
        apy = safe_call(
            self.feed.get_apy,
            self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
            default=None, log_error=True, logger_name=f"spa.{self.PROTOCOL}",
        )
        tvl = safe_call(
            self.feed.get_tvl,
            self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
            default=None, log_error=False,
        )
        # ADR-233: какой ИМЕННО пул выиграл отбор — тем же снимком и тем же
        # правилом, что apy/tvl выше. `pool_id` рядом — рукописный слаг.
        record["resolved_pool_id"] = resolved_pool_id(
            self.feed,
            self.DEFILLAMA_PROJECT, self.DEFILLAMA_SYMBOL, self.DEFILLAMA_CHAIN,
        )

        record["tvl"] = float(tvl) if isinstance(tvl, (int, float)) else None
        if not isinstance(apy, (int, float)):
            logger.warning(
                "%s: DeFiLlama APY unavailable — reporting no live data",
                self.PROTOCOL,
            )
            return record

        record["apy"] = float(apy)
        record["status"] = "ok"
        record["error"] = None
        record["live_data"] = True
        return record

    # ── публичный APY API ────────────────────────────────────────────────

    def get_apy_pct(self) -> Optional[float]:
        """Возвращает APY в процентах (3.47, а не 0.0347) либо ``None``.

        Приоритет источников (own-29):
          1. живой DeFiLlama-фид (STEAKUSDC vault);
          2. data/adapter_status.json → morpho_steakhouse.apy;
          3. **ничего** — наблюдения нет ⇒ ``None``.

        ADR-063 п.3 / `.claude/rules/adapters.md`: «нет данных ⇒ None».
        Прежняя подстановка ``FALLBACK_APY_PCT = 6.5`` УДАЛЕНА решением
        владельца 2026-08-08 (вариант 1 карточки
        `owner-decision-morfo-40-knigi-pri-propazhe-dannyh-podst`): выдуманное
        число почти вдвое превышало живое (6.5 % против наблюдённых 3.47 %) и
        вытекало наружу через ``switch_recommended()`` и ``allocate()``.
        """
        live = self.fetch_live()
        live_apy = live.get("apy")
        if isinstance(live_apy, (int, float)):
            return float(live_apy) * 100.0
        return self._read_apy_from_status()

    def get_apy(self) -> Optional[float]:
        """Возвращает APY как десятичную дробь (0.0347 = 3.47 %) либо ``None``.

        Реализует контракт ``BaseAdapter.get_apy() -> Optional[float]``:
        наблюдения нет ⇒ ``None``, НИКОГДА не константа.
        """
        apy_pct = self.get_apy_pct()
        return None if apy_pct is None else apy_pct / 100.0

    def get_yield_info(self) -> YieldInfo:
        """Возвращает нормализованный YieldInfo для оркестратора.

        own-29 / ADR-053: это поверхность оркестратора → она обязана быть
        честной о происхождении данных. Живой фид доступен → живые apy/tvl_usd
        и ``tvl_source="live"``. Живого фида НЕТ → ``apy=None``/``tvl_usd=None``
        (оркестратор запишет ``live_feed_unavailable``), НИКОГДА не 6.5%-константа
        и не число из статик-файла без метки происхождения. Never stamp "live"
        on a constant.
        """
        live = self.fetch_live()
        tvl = live.get("tvl")
        _tvl_live = isinstance(tvl, (int, float))
        return YieldInfo(
            protocol=self.PROTOCOL,
            asset=self.asset,
            apy=live.get("apy"),
            tvl_usd=float(tvl) if _tvl_live else None,
            tier=self.tier,
            risk_score=self.RISK_SCORE,
            exit_latency_hours=self.EXIT_LATENCY_HOURS,
            tvl_source="live" if _tvl_live else None,
            pool_id=live.get("resolved_pool_id"),
        )

    # ── switch-рекомендация ──────────────────────────────────────────────

    def switch_recommended(self, aave_apy_pct: Optional[float] = None) -> bool:
        """True если Morpho APY > Aave APY + SWITCH_THRESHOLD_BPS / 100.

        **Fail-CLOSED:** наблюдения APY нет ⇒ ``False``. Рекомендация
        переложиться — это утверждение о превосходстве доходности; без
        наблюдения такого утверждения не существует. До 2026-08-08 здесь
        сравнивалась подставная константа 6.5 %, и метод отвечал ``True``
        РОВНО ТОГДА, когда данных не было.

        Args:
            aave_apy_pct: Текущий Aave APY в процентах. Если None — используется
                          AAVE_MAINNET_APY_PCT (3.2%).
        """
        apy_pct = self.get_apy_pct()
        if apy_pct is None:
            return False
        aave = aave_apy_pct if aave_apy_pct is not None else self.AAVE_MAINNET_APY_PCT
        threshold = aave + self.SWITCH_THRESHOLD_BPS / 100.0
        return apy_pct > threshold

    def switch_gain_pct(self, aave_apy_pct: Optional[float] = None) -> Optional[float]:
        """Разница APY в процентах (Morpho - Aave), либо ``None`` без наблюдения.

        Args:
            aave_apy_pct: Текущий Aave APY в процентах. Если None — используется
                          AAVE_MAINNET_APY_PCT (3.2%).
        """
        apy_pct = self.get_apy_pct()
        if apy_pct is None:
            return None
        aave = aave_apy_pct if aave_apy_pct is not None else self.AAVE_MAINNET_APY_PCT
        return round(apy_pct - aave, 10)

    # ── виртуальный paper trading API ────────────────────────────────────

    def allocate(self, capital: float) -> dict:
        """Виртуальная аллокация капитала (только для paper trading).

        Returns:
            dict со статусом операции.
        """
        if capital <= 0:
            return {
                "status": "error",
                "reason": "capital must be positive",
                "requested": capital,
                "allocated": self._allocated,
                "protocol": self.PROTOCOL,
            }
        self._allocated += capital
        return {
            "status": "ok",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "amount": capital,
            "allocated_total": self._allocated,
            "apy_pct": self.get_apy_pct(),
            "ts": time.time(),
        }

    def withdraw(self, amount: float) -> dict:
        """Виртуальный вывод средств из vault (только для paper trading).

        Returns:
            dict со статусом операции.
        """
        if amount <= 0:
            return {
                "status": "error",
                "reason": "amount must be positive",
                "requested": amount,
                "allocated": self._allocated,
                "protocol": self.PROTOCOL,
            }
        if amount > self._allocated:
            return {
                "status": "error",
                "reason": "insufficient_balance",
                "requested": amount,
                "available": self._allocated,
                "protocol": self.PROTOCOL,
            }
        self._allocated -= amount
        return {
            "status": "ok",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "amount": amount,
            "allocated_remaining": self._allocated,
            "ts": time.time(),
        }

    # ── health check ─────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Проверяет работоспособность адаптера.

        Статус «ok» если APY — числовое значение в разумном диапазоне (0–50%).
        Статус «degraded» если APY за пределами диапазона или не числовое.

        Returns:
            dict с полями status, protocol, vault, tier, apy_pct и рекомендацией.
        """
        apy_pct = self.get_apy_pct()
        healthy = isinstance(apy_pct, float) and 0 < apy_pct < 50
        return {
            "status": "ok" if healthy else "degraded",
            "protocol": self.PROTOCOL,
            "vault": self.VAULT_ADDRESS,
            "tier": self.tier,
            "apy_pct": apy_pct,
            # 2026-08-08: подстановки больше нет, поэтому ключ означает ровно
            # «наблюдения нет» (раньше — «в status-файле пусто, взял 6.5 %»).
            "apy_observed": apy_pct is not None,
            "fallback_used": apy_pct is None,
            "quick_win": self.QUICK_WIN,
            "switch_recommended": self.switch_recommended(),
            "ts": time.time(),
        }

    # ── сериализация ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Полное представление адаптера (для дашборда / логов / тестов).

        Returns:
            dict с ключами:
            protocol, vault_address, vault_name, tier, t1_cap, asset,
            apy_pct, apy_decimal, risk_score, exit_latency_hours,
            quick_win, bps_gain, switch_recommended, switch_gain_pct,
            aave_benchmark_apy_pct, strategy_note, allocated.
        """
        return {
            "protocol": self.PROTOCOL,
            "vault_address": self.VAULT_ADDRESS,
            "vault_name": self.VAULT_NAME,
            "tier": self.tier,
            "t1_cap": self.T1_CAP,
            "asset": self.asset,
            "apy_pct": self.get_apy_pct(),
            "apy_decimal": self.get_apy(),
            "risk_score": self.RISK_SCORE,
            "exit_latency_hours": self.EXIT_LATENCY_HOURS,
            "quick_win": self.QUICK_WIN,
            "bps_gain": self.BPS_GAIN,
            "switch_recommended": self.switch_recommended(),
            "switch_gain_pct": self.switch_gain_pct(),
            "aave_benchmark_apy_pct": self.AAVE_MAINNET_APY_PCT,
            "strategy_note": self.STRATEGY_NOTE,
            "allocated": self._allocated,
        }

    # end of class
