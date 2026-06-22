"""
APYAggregator — единая точка сбора и сравнения APY всех адаптеров SPA.

Читает data/adapter_status.json, строит нормализованные снимки (AdapterSnapshot)
по каждому адаптеру и предоставляет методы ранжирования, фильтрации и сравнения.

Источники данных в adapter_status.json:
  1. Массив ``adapters``     — основные протоколы (aave-v3, compound-v3, …)
  2. Ключ ``morpho_steakhouse`` — специальный vault Morpho Blue Steakhouse
  3. Ключ ``aave_arbitrum``  — Aave V3 Arbitrum (T1 L2-адаптер)
  4. Ключ ``pendle_pt``      — Pendle PT (дополнительные live-данные)

LLM ЗАПРЕЩЁН (LLM_FORBIDDEN_AGENTS). Только stdlib. Атомарные записи JSON.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Константы путей
# ---------------------------------------------------------------------------

# Корень репозитория — два уровня выше пакета adapters
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Имена файлов в data/
_ADAPTER_STATUS_FILE = "adapter_status.json"
_APY_RANKING_FILE = "apy_ranking.json"

# ---------------------------------------------------------------------------
# Таблицы рисков
# ---------------------------------------------------------------------------

# Тир → «вес риска» для risk-adjusted APY: risk_adj = apy / weight.
# Чем выше вес — тем жёстче «штраф» за риск, тем ниже risk-adjusted APY.
RISK_WEIGHTS: dict[str, float] = {
    "T1": 1.0,   # минимальный риск — крупные ликвидные протоколы
    "T2": 1.3,   # умеренный риск — проверенные протоколы с ограничением
    "T3": 2.0,   # высокий риск — экспериментальные / неаудированные
}

# Тир → числовой балл риска (хранится в снимке для внешних потребителей)
_TIER_RISK_SCORE: dict[str, float] = {
    "T1":             0.20,
    "T2":             0.50,
    "T2-conditional": 0.80,
    "T3":             0.90,
}

# Минимальный TVL для T1-протоколов ($100M) — используется в best_t1()
# когда TVL известен в снимке.
MIN_TVL_USD: float = 100_000_000.0


# ---------------------------------------------------------------------------
# Вспомогательные функции (приватные)
# ---------------------------------------------------------------------------

def _best_apy_from_mock(mock_apy: dict) -> float:
    """Извлекает лучший (USDC-приоритетный) APY из секции mock_apy.

    Порядок поиска:
      1. ethereum → USDC
      2. arbitrum → USDC
      3. base     → USDC
      4. любая сеть → USDC
      5. ethereum → первый актив
      6. любая сеть → первый актив
      7. 0.0 (нет данных)
    """
    if not mock_apy:
        return 0.0

    # Ищем USDC по приоритетным сетям
    for chain in ("ethereum", "arbitrum", "base"):
        chain_data = mock_apy.get(chain, {})
        if "USDC" in chain_data:
            return float(chain_data["USDC"])

    # Любая сеть с USDC
    for chain_data in mock_apy.values():
        if isinstance(chain_data, dict) and "USDC" in chain_data:
            return float(chain_data["USDC"])

    # Fallback: первый актив ethereum, потом первый вообще
    eth_data = mock_apy.get("ethereum", {})
    if eth_data and isinstance(eth_data, dict):
        return float(next(iter(eth_data.values())))

    for chain_data in mock_apy.values():
        if isinstance(chain_data, dict) and chain_data:
            return float(next(iter(chain_data.values())))

    return 0.0


def _primary_network(chains: list) -> str:
    """Определяет основную (приоритетную) сеть из списка сетей адаптера."""
    if not chains:
        return "unknown"
    for preferred in ("ethereum", "arbitrum", "base"):
        if preferred in chains:
            return preferred
    return str(chains[0])


def _risk_weight(tier: str) -> float:
    """Возвращает вес риска для тира; T3-вес как fallback для неизвестных."""
    return RISK_WEIGHTS.get(tier, RISK_WEIGHTS["T3"])


# ---------------------------------------------------------------------------
# AdapterSnapshot — нормализованный снимок одного адаптера
# ---------------------------------------------------------------------------

@dataclass
class AdapterSnapshot:
    """Нормализованный снимок состояния одного адаптера.

    Атрибуты:
        protocol      — уникальный ключ протокола (напр. «aave-v3»)
        tier          — «T1» / «T2» / «T2-conditional» / «T3»
        apy_pct       — APY в процентах (4.2 означает 4.2%)
        network       — основная сеть («ethereum», «arbitrum», …)
        tvl_usd       — TVL в USD (0.0 если неизвестно)
        last_updated  — ISO-строка времени обновления данных
        risk_score    — числовой балл риска (меньше = безопаснее)
    """

    protocol: str
    tier: str
    apy_pct: float
    network: str
    tvl_usd: float
    last_updated: str
    risk_score: float


# ---------------------------------------------------------------------------
# APYAggregator — основной класс
# ---------------------------------------------------------------------------

class APYAggregator:
    """Собирает APY от всех адаптеров, ранжирует и рекомендует.

    Пример быстрого использования:
        agg = APYAggregator.load(Path("data/"))
        print(agg.best_t1())
        print(agg.rank_by_risk_adjusted()[:3])
        agg.save_ranking(Path("data/apy_ranking.json"))
    """

    # Веса риска — копия модульной константы, доступна через класс
    RISK_WEIGHTS: dict[str, float] = RISK_WEIGHTS

    # Порог TVL для T1 (используется в best_t1)
    MIN_TVL_USD: float = MIN_TVL_USD

    # ---------------------------------------------------------------------------
    def __init__(self, snapshots: list[AdapterSnapshot]) -> None:
        # Защищённый список — не изменять снаружи напрямую
        self._snapshots: list[AdapterSnapshot] = list(snapshots)

    # ------------------------------------------------------------------ #
    #  Загрузка из adapter_status.json                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, data_dir: Path) -> "APYAggregator":
        """Читает adapter_status.json и строит список AdapterSnapshot.

        Если файл недоступен или повреждён — возвращает пустой агрегатор
        (не бросает исключение), чтобы вызывающий код мог продолжить работу.

        Args:
            data_dir: Директория с файлом adapter_status.json

        Returns:
            APYAggregator с загруженными снимками
        """
        status_path = Path(data_dir) / _ADAPTER_STATUS_FILE

        try:
            with open(status_path, "r", encoding="utf-8") as fh:
                raw: dict = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            # Файл недоступен или повреждён — возвращаем пустой агрегатор
            return cls([])

        generated_at: str = raw.get("generated_at", "unknown")
        snapshots: list[AdapterSnapshot] = []
        seen_protocols: set[str] = set()  # дедупликация по ключу протокола

        # ── 1. Основной массив / словарь адаптеров ────────────────────────
        # MP-1195: поддерживает оба формата:
        #   v1: adapters — список объектов с полем protocol_key
        #   v2: adapters — словарь {snake_key: {display_name, apy, tier, ...}}
        adapters_raw = raw.get("adapters", [])

        if isinstance(adapters_raw, dict):
            # ── v2 формат (schema_version 2) ──────────────────────────────
            for proto_key, entry in adapters_raw.items():
                if not isinstance(entry, dict):
                    continue
                if not entry.get("active", True):
                    continue
                tier_raw = entry.get("tier", 2)
                tier_str: str = (
                    f"T{tier_raw}" if isinstance(tier_raw, int) else str(tier_raw)
                )
                per_cap: float = float(entry.get("per_protocol_cap", 0.2))
                # Пропускаем адаптеры без аллокации (sky_susds tier=0 и т.п.)
                if per_cap <= 0.0:
                    continue
                # apy в v2 хранится в % (5.2 = 5.2%, не 0.052)
                apy_pct_v2: float = float(
                    entry.get("apy") or entry.get("fallback_apy") or 0.0
                )
                chain_v2: str = str(entry.get("chain", "ethereum"))
                tvl_v2: float = float(entry.get("tvl_usd", 0.0) or 0.0)
                updated_v2: str = str(entry.get("last_updated", generated_at))
                if proto_key not in seen_protocols:
                    snap = AdapterSnapshot(
                        protocol=proto_key,
                        tier=tier_str,
                        apy_pct=apy_pct_v2,
                        network=chain_v2,
                        tvl_usd=tvl_v2,
                        last_updated=updated_v2,
                        risk_score=_TIER_RISK_SCORE.get(tier_str, 1.0),
                    )
                    snapshots.append(snap)
                    seen_protocols.add(proto_key)
        else:
            # ── v1 формат (список объектов) ───────────────────────────────
            for entry in adapters_raw:
                protocol_key: str = entry.get("protocol_key", "")
                if not protocol_key:
                    continue  # пропускаем запись без ключа

                tier: str = str(entry.get("tier", "T2"))
                alloc_cap: float = float(entry.get("allocation_cap", 0.0))

                # Sky/sUSDS и другие адаптеры с allocation_cap=0 пропускаем:
                # они не участвуют в аллокации → не нужны в рейтинге
                if alloc_cap <= 0.0:
                    continue

                mock_apy: dict = entry.get("mock_apy", {})
                chains: list = entry.get("chains", [])

                snap = AdapterSnapshot(
                    protocol=protocol_key,
                    tier=tier,
                    apy_pct=_best_apy_from_mock(mock_apy),
                    network=_primary_network(chains),
                    tvl_usd=0.0,  # TVL не хранится в этой секции
                    last_updated=generated_at,
                    risk_score=_TIER_RISK_SCORE.get(tier, 1.0),
                )
                snapshots.append(snap)
                seen_protocols.add(protocol_key)

        # ── 2. Morpho Blue Steakhouse vault ───────────────────────────────
        # Специальный T1-vault с фиксированным APY; не входит в основной массив
        morpho: dict = raw.get("morpho_steakhouse", {})
        if morpho:
            # Приоритет: поле "apy" → baseline + bps_gain/100
            morpho_apy: float = float(morpho.get("apy", 0.0))
            if morpho_apy <= 0.0:
                # Вычисляем из bps_gain: Aave mainnet baseline 3.2% + gain
                bps_gain: float = float(morpho.get("bps_gain", 0))
                morpho_apy = 3.2 + bps_gain / 100.0

            # Строим уникальный ключ для Steakhouse vault
            base_key: str = morpho.get("protocol_key", "morpho-blue")
            morpho_key: str = base_key + "-steakhouse"

            if morpho_key not in seen_protocols:
                snap = AdapterSnapshot(
                    protocol=morpho_key,
                    tier="T1",  # TVL > $500M → классифицируется как T1
                    apy_pct=morpho_apy,
                    network="ethereum",
                    tvl_usd=0.0,
                    last_updated=generated_at,
                    risk_score=_TIER_RISK_SCORE.get("T1", 0.20),
                )
                snapshots.append(snap)
                seen_protocols.add(morpho_key)

        # ── 3. Aave V3 Arbitrum ────────────────────────────────────────────
        # Отдельный T1-адаптер на L2; хранится в собственном ключе
        arb: dict = raw.get("aave_arbitrum", {})
        if arb:
            arb_key = "aave-v3-arbitrum"
            if arb_key not in seen_protocols:
                tier = str(arb.get("tier", "T1"))
                snap = AdapterSnapshot(
                    protocol=arb_key,
                    tier=tier,
                    apy_pct=float(arb.get("apy", 4.1)),
                    network=str(arb.get("network", "arbitrum")),
                    tvl_usd=float(arb.get("tvl_usd", 0.0)),
                    last_updated=str(arb.get("added_at", generated_at)),
                    risk_score=_TIER_RISK_SCORE.get(tier, 0.20),
                )
                snapshots.append(snap)
                seen_protocols.add(arb_key)

        # ── 4. Pendle PT (live-данные из отдельного ключа) ─────────────────
        # Если pendle-pt уже добавлен через массив adapters — пропускаем,
        # иначе создаём снимок на основе top-level записи
        pendle: dict = raw.get("pendle_pt", {})
        if pendle:
            pendle_key: str = str(pendle.get("protocol_key", "pendle-pt"))
            if pendle_key not in seen_protocols:
                tier = str(pendle.get("tier", "T2"))
                snap = AdapterSnapshot(
                    protocol=pendle_key,
                    tier=tier,
                    apy_pct=float(pendle.get("apy", 8.0)),
                    network=str(pendle.get("chain", "ethereum")),
                    tvl_usd=0.0,
                    last_updated=str(pendle.get("updated_at", generated_at)),
                    risk_score=_TIER_RISK_SCORE.get(tier, 0.50),
                )
                snapshots.append(snap)
                seen_protocols.add(pendle_key)

        return cls(snapshots)

    # ------------------------------------------------------------------ #
    #  Доступ к снимкам                                                    #
    # ------------------------------------------------------------------ #

    def snapshots(self) -> list[AdapterSnapshot]:
        """Возвращает копию полного списка снимков."""
        return list(self._snapshots)

    # ------------------------------------------------------------------ #
    #  Ранжирование                                                        #
    # ------------------------------------------------------------------ #

    def rank_by_apy(self) -> list[AdapterSnapshot]:
        """Возвращает снимки, отсортированные по APY по убыванию.

        Лучший (наивысший) APY — первый в списке.
        """
        return sorted(self._snapshots, key=lambda s: s.apy_pct, reverse=True)

    def rank_by_risk_adjusted(self) -> list[AdapterSnapshot]:
        """Возвращает снимки, отсортированные по risk-adjusted APY по убыванию.

        risk_adjusted_apy = apy_pct / RISK_WEIGHTS[tier]

        Протоколы с неизвестным тиром получают вес T3 (2.0) — максимальный
        штраф за риск.
        """
        def _risk_adj(s: AdapterSnapshot) -> float:
            return s.apy_pct / _risk_weight(s.tier)

        return sorted(self._snapshots, key=_risk_adj, reverse=True)

    # ------------------------------------------------------------------ #
    #  Фильтрация                                                          #
    # ------------------------------------------------------------------ #

    def best_t1(self) -> Optional[AdapterSnapshot]:
        """Возвращает T1-адаптер с наивысшим APY (или None если T1 нет).

        Логика фильтрации:
          1. Отобрать все снимки с tier == "T1"
          2. Если хотя бы у одного известен TVL (tvl_usd > 0) — применить
             фильтр MIN_TVL_USD; снимки с tvl_usd == 0 сохраняются (TVL неизвестен)
          3. Из оставшихся вернуть максимум по apy_pct
        """
        t1: list[AdapterSnapshot] = [s for s in self._snapshots if s.tier == "T1"]
        if not t1:
            return None

        # Применяем TVL-фильтр только если TVL известен хотя бы у одного
        if any(s.tvl_usd > 0 for s in t1):
            t1 = [s for s in t1 if s.tvl_usd == 0.0 or s.tvl_usd >= MIN_TVL_USD]

        if not t1:
            return None

        return max(t1, key=lambda s: s.apy_pct)

    def top_n(
        self,
        n: int,
        tier_filter: Optional[str] = None,
    ) -> list[AdapterSnapshot]:
        """Возвращает топ-N адаптеров по APY с опциональным фильтром по тиру.

        Args:
            n:           Максимальное число адаптеров в результате
            tier_filter: Если задан — включаются только адаптеры этого тира

        Returns:
            Список (≤ n) адаптеров, отсортированных по apy_pct по убыванию.
            Пустой список если n ≤ 0 или нет подходящих адаптеров.
        """
        if n <= 0:
            return []

        candidates = self._snapshots
        if tier_filter is not None:
            candidates = [s for s in candidates if s.tier == tier_filter]

        ranked = sorted(candidates, key=lambda s: s.apy_pct, reverse=True)
        return ranked[:n]

    # ------------------------------------------------------------------ #
    #  Аналитика и сравнение                                               #
    # ------------------------------------------------------------------ #

    def apy_spread(self) -> float:
        """Разброс APY: max_apy - min_apy среди всех снимков.

        Возвращает 0.0 если снимков нет или один.
        """
        if len(self._snapshots) < 2:
            return 0.0
        apys = [s.apy_pct for s in self._snapshots]
        return max(apys) - min(apys)

    def vs_baseline(self, baseline_apy: float = 3.2) -> dict[str, float]:
        """Разница APY каждого адаптера относительно baseline.

        Args:
            baseline_apy: Базовый APY (по умолчанию 3.2% — Aave V3 mainnet)

        Returns:
            {protocol: delta} где delta = apy_pct - baseline_apy.
            Положительное delta → адаптер лучше baseline.
        """
        return {
            snap.protocol: round(snap.apy_pct - baseline_apy, 6)
            for snap in self._snapshots
        }

    def to_summary_dict(self) -> dict:
        """Компактный summary для дашборда.

        Returns:
            Словарь со следующими полями:
              best_adapter   — protocol адаптера с максимальным APY
              best_apy       — наивысший APY (%)
              worst_apy      — наименьший APY (%)
              spread         — разброс APY (max - min)
              count_adapters — число адаптеров в агрегаторе
              best_t1        — protocol лучшего T1-адаптера (None если нет T1)
              best_risk_adj  — protocol адаптера с лучшим risk-adjusted APY
        """
        if not self._snapshots:
            return {
                "best_adapter":   None,
                "best_apy":       None,
                "worst_apy":      None,
                "spread":         0.0,
                "count_adapters": 0,
                "best_t1":        None,
                "best_risk_adj":  None,
            }

        ranked = self.rank_by_apy()
        best_snap = ranked[0]
        worst_snap = ranked[-1]

        best_t1_snap = self.best_t1()
        risk_ranked = self.rank_by_risk_adjusted()

        return {
            "best_adapter":   best_snap.protocol,
            "best_apy":       round(best_snap.apy_pct, 4),
            "worst_apy":      round(worst_snap.apy_pct, 4),
            "spread":         round(self.apy_spread(), 4),
            "count_adapters": len(self._snapshots),
            "best_t1":        best_t1_snap.protocol if best_t1_snap else None,
            "best_risk_adj":  risk_ranked[0].protocol if risk_ranked else None,
        }

    # ------------------------------------------------------------------ #
    #  Сохранение                                                          #
    # ------------------------------------------------------------------ #

    def save_ranking(self, path: Path) -> None:
        """Атомарная запись рейтинга в JSON-файл (tmp + os.replace).

        Формат файла:
        {
          "generated_at": "<ISO 8601>Z",
          "count": <int>,
          "summary": { ... },          ← to_summary_dict()
          "by_apy": [ ... ],           ← rank_by_apy()
          "by_risk_adjusted": [ ... ]  ← rank_by_risk_adjusted()
        }

        Args:
            path: Абсолютный путь к выходному файлу (будет создан/перезаписан)
        """
        import datetime

        def _snap_to_dict(s: AdapterSnapshot) -> dict:
            w = _risk_weight(s.tier)
            return {
                "protocol":          s.protocol,
                "tier":              s.tier,
                "apy_pct":           round(s.apy_pct, 4),
                "risk_adjusted_apy": round(s.apy_pct / w, 4),
                "network":           s.network,
                "tvl_usd":           s.tvl_usd,
                "last_updated":      s.last_updated,
                "risk_score":        s.risk_score,
            }

        payload = {
            "generated_at":    datetime.datetime.utcnow().isoformat() + "Z",
            "count":           len(self._snapshots),
            "summary":         self.to_summary_dict(),
            "by_apy":          [_snap_to_dict(s) for s in self.rank_by_apy()],
            "by_risk_adjusted":[_snap_to_dict(s) for s in self.rank_by_risk_adjusted()],
        }

        atomic_save(payload, str(Path(path)))
