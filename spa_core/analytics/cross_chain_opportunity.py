"""
Cross-chain opportunity analyzer.
Отвечает на вопрос: стоит ли перемещать капитал с цепи A на цепь B,
учитывая bridge cost и yield differential?

Формула breakeven:
    daily_gain      = capital_usd * (apy_diff_pct / 100) / 365
    breakeven_days  = total_bridge_cost_usd / daily_gain
    is_profitable   = breakeven_days < MAX_BREAKEVEN_DAYS (90)

Recommendation:
    MOVE     — breakeven_days < 30
    MONITOR  — 30 ≤ breakeven_days < 90
    HOLD     — breakeven_days ≥ 90 или apy_diff ≤ 0

CLI:
    python3 -m spa_core.analytics.cross_chain_opportunity --check   # вывод без записи (дефолт)
    python3 -m spa_core.analytics.cross_chain_opportunity --run     # вычислить + записать

MP-594.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Module-level constants (also exposed as class variables)
# ---------------------------------------------------------------------------
_DEFAULT_CAPITAL_USD: float = 100_000.0
_MIN_APY_DIFF_PCT: float = 0.5
_MAX_BREAKEVEN_DAYS: float = 90.0
_RING_BUFFER_SIZE: int = 30

_CHAIN_ALIASES: Dict[str, str] = {
    # Ethereum mainnet
    "ethereum": "ethereum", "mainnet": "ethereum", "eth": "ethereum",
    # Arbitrum
    "arbitrum": "arbitrum", "arb": "arbitrum",
    "arbitrum-one": "arbitrum", "arbitrum one": "arbitrum",
    # Base (Coinbase L2)
    "base": "base",
    # Optimism
    "optimism": "optimism", "opt": "optimism", "op": "optimism",
    "op mainnet": "optimism", "op-mainnet": "optimism",
    # Polygon
    "polygon": "polygon", "matic": "polygon", "polygon-mainnet": "polygon",
}

_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode",
    "live_apy_enabled", "mev_protection", "adapters",
    "base_gas_monitor",
})

_TIER_DEFAULT_RISK: Dict[str, float] = {
    "T1": 0.20,
    "T2": 0.35,
    "T3": 0.55,
    "T2-conditional": 0.40,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BridgeCost:
    """Стоимость bridge с chain_from на chain_to."""

    chain_from: str
    chain_to: str
    gas_cost_usd: float      # gas + bridge fee в USD
    slippage_pct: float      # ожидаемый slippage (fraction, e.g. 0.001 = 0.1%)
    time_hours: float        # время до финализации (informational)

    def total_cost_usd(self, capital_usd: float) -> float:
        """Суммарная стоимость bridge: gas_cost + slippage * capital."""
        return self.gas_cost_usd + self.slippage_pct * capital_usd


@dataclass
class CrossChainOpportunity:
    """Одна конкретная возможность арбитража между цепями."""

    from_chain: str
    to_chain: str
    from_adapter: str
    to_adapter: str
    from_apy_pct: float
    to_apy_pct: float
    apy_diff_pct: float           # to_apy - from_apy
    bridge_cost: BridgeCost
    breakeven_days: float         # сколько дней нужно чтобы окупить bridge cost
    is_profitable: bool           # breakeven_days < MAX_BREAKEVEN_DAYS
    annual_gain_usd: float        # на DEFAULT_CAPITAL_USD в год
    recommendation: str           # "MOVE", "HOLD", "MONITOR"


# ---------------------------------------------------------------------------
# CrossChainOpportunityAnalyzer
# ---------------------------------------------------------------------------

class CrossChainOpportunityAnalyzer:
    """Анализирует cross-chain возможности перемещения капитала.

    Читает ``data/adapter_status.json``, строит матрицу APY по chain/adapter
    и сравнивает yield differential с bridge cost для каждой пары цепей.

    Параметры
    ---------
    data_path : str | None
        Путь к adapter_status.json. По умолчанию — data/ от корня репо.

    Пример
    ------
    analyzer = CrossChainOpportunityAnalyzer()
    top = analyzer.get_top_opportunity()
    path = analyzer.save_analysis()
    """

    # Threshold constants (also used as default params via class-body scoping)
    MIN_APY_DIFF_PCT: float = _MIN_APY_DIFF_PCT
    MAX_BREAKEVEN_DAYS: float = _MAX_BREAKEVEN_DAYS
    DEFAULT_CAPITAL_USD: float = _DEFAULT_CAPITAL_USD

    # Bridge costs matrix: (from_chain, to_chain) → BridgeCost
    # gas_cost_usd: gas + bridge protocol fee
    # slippage_pct: fraction of capital (e.g. 0.001 = 0.1%)
    # time_hours: finalization time
    BRIDGE_COSTS: Dict[Tuple[str, str], BridgeCost] = {
        # Ethereum → L2 (fast, cheap)
        ("ethereum", "polygon"):  BridgeCost("ethereum", "polygon",  3.5, 0.001,   0.50),
        ("ethereum", "arbitrum"): BridgeCost("ethereum", "arbitrum", 2.0, 0.0005,  0.10),
        ("ethereum", "base"):     BridgeCost("ethereum", "base",     1.5, 0.0005,  0.05),
        ("ethereum", "optimism"): BridgeCost("ethereum", "optimism", 1.5, 0.0005,  0.05),
        # L2 → Ethereum (7-day optimistic challenge period)
        ("polygon",  "ethereum"): BridgeCost("polygon",  "ethereum", 0.5, 0.001,  168.0),
        ("arbitrum", "ethereum"): BridgeCost("arbitrum", "ethereum", 0.8, 0.001,  168.0),
        ("base",     "ethereum"): BridgeCost("base",     "ethereum", 0.8, 0.001,  168.0),
        ("optimism", "ethereum"): BridgeCost("optimism", "ethereum", 0.8, 0.001,  168.0),
        # L2 → L2 via 3rd-party bridges (higher cost, shorter wait)
        ("polygon",  "arbitrum"): BridgeCost("polygon",  "arbitrum", 5.0, 0.002,   1.0),
        ("polygon",  "base"):     BridgeCost("polygon",  "base",     5.0, 0.002,   1.0),
        ("arbitrum", "base"):     BridgeCost("arbitrum", "base",     4.0, 0.002,   0.5),
        ("arbitrum", "optimism"): BridgeCost("arbitrum", "optimism", 4.0, 0.002,   0.5),
        ("base",     "optimism"): BridgeCost("base",     "optimism", 3.5, 0.001,   0.3),
        ("optimism", "base"):     BridgeCost("optimism", "base",     3.5, 0.001,   0.3),
    }

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self._data_path = _DEFAULT_DATA_DIR / "adapter_status.json"
        else:
            self._data_path = Path(data_path)
        self._output_dir = self._data_path.parent

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_chain(raw: str) -> str:
        """Нормализует строку chain в каноническое имя."""
        key = raw.lower().strip()
        return _CHAIN_ALIASES.get(key, key)

    @staticmethod
    def _extract_apy(entry: dict, chain: str = "") -> float:
        """Извлекает APY (%) из entry.

        Приоритет: apy_pct → apy → mock_apy[chain][USDC] → 0.0
        Отклоняет bool и нечисловые значения.
        """
        for key in ("apy_pct", "apy"):
            val = entry.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
                return float(val)
        if chain:
            mock = entry.get("mock_apy")
            if isinstance(mock, dict):
                chain_mock = mock.get(chain, {})
                if isinstance(chain_mock, dict):
                    usdc = chain_mock.get("USDC")
                    if isinstance(usdc, (int, float)) and not isinstance(usdc, bool) and usdc > 0:
                        return float(usdc)
        return 0.0

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_chain_data(self) -> Dict[str, Dict[str, dict]]:
        """Читает adapter_status.json, группирует адаптеры по chain.

        Возвращает
        ----------
        dict
            {chain: {adapter_id: {"apy_pct": float, "tier": str,
                                   "risk_score": float, "tvl_usd": float}}}

        Два источника (источник 1 имеет приоритет):
        1. Protocol-level словари с явным полем chain/network.
        2. Список adapters[] — раскрывается по chains[].

        Никогда не бросает исключений — fail-safe: при любой ошибке возвращает {}.
        """
        try:
            with open(self._data_path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
        except Exception:
            return {}

        result: Dict[str, Dict[str, dict]] = {}

        # ── Источник 1: protocol-level entries с явным полем chain ─────────
        for key, val in data.items():
            if key in _SKIP_KEYS or key.startswith("_"):
                continue
            if not isinstance(val, dict):
                continue
            raw_chain = val.get("chain") or val.get("network", "")
            if not raw_chain:
                continue
            chain = self._normalize_chain(str(raw_chain))
            adapter_id = (
                val.get("adapter_id") or val.get("protocol_id")
                or val.get("protocol") or key
            )
            tier = str(val.get("tier", "T2"))
            risk_score = _TIER_DEFAULT_RISK.get(tier, 0.30)
            tvl_raw = val.get("tvl_usd", 0.0)
            tvl = float(tvl_raw) if isinstance(tvl_raw, (int, float)) and not isinstance(tvl_raw, bool) else 0.0
            apy = self._extract_apy(val, chain)

            result.setdefault(chain, {})[str(adapter_id)] = {
                "apy_pct": apy,
                "tier": tier,
                "risk_score": risk_score,
                "tvl_usd": tvl,
            }

        # ── Источник 2: adapters[] list (заполняет пробелы) ────────────────
        for adapter in data.get("adapters", []):
            if not isinstance(adapter, dict):
                continue
            pkey = str(adapter.get("protocol_key", "unknown"))
            tier = str(adapter.get("tier", "T2"))
            risk_score = _TIER_DEFAULT_RISK.get(tier, 0.30)

            for chain_raw in adapter.get("chains", []):
                chain = self._normalize_chain(str(chain_raw))
                apy = self._extract_apy(adapter, chain)

                chain_dict = result.setdefault(chain, {})
                if pkey not in chain_dict:  # не перезаписывать source-1 данные
                    chain_dict[pkey] = {
                        "apy_pct": apy,
                        "tier": tier,
                        "risk_score": risk_score,
                        "tvl_usd": 0.0,
                    }

        return result

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    def get_bridge_cost(self, from_chain: str, to_chain: str) -> Optional[BridgeCost]:
        """Lookup bridge cost по паре (from_chain, to_chain).

        Возвращает None если прямая пара не известна.
        """
        return self.BRIDGE_COSTS.get((from_chain, to_chain))

    def compute_breakeven(
        self,
        apy_diff_pct: float,
        bridge_cost_usd: float,
        capital_usd: float = _DEFAULT_CAPITAL_USD,
    ) -> float:
        """Вычисляет дни до окупаемости bridge cost.

        breakeven_days = bridge_cost_usd / (capital_usd * apy_diff_pct/100 / 365)

        Параметры
        ---------
        apy_diff_pct : float
            Разница APY (to - from), в процентах.
        bridge_cost_usd : float
            Суммарная стоимость bridge в USD.
        capital_usd : float
            Размер капитала для перемещения.

        Возвращает float('inf') при apy_diff_pct ≤ 0 или нулевом capital.
        """
        if apy_diff_pct <= 0:
            return float("inf")
        if capital_usd <= 0:
            return float("inf")
        daily_gain = capital_usd * (apy_diff_pct / 100.0) / 365.0
        if daily_gain <= 0:
            return float("inf")
        return bridge_cost_usd / daily_gain

    def analyze_pair(
        self,
        from_chain: str,
        to_chain: str,
        capital_usd: float = _DEFAULT_CAPITAL_USD,
    ) -> Optional[CrossChainOpportunity]:
        """Анализирует пару chain→chain.

        Находит лучший адаптер (по APY) на каждой цепи, вычисляет
        yield differential, bridge cost и breakeven.

        Возвращает None если:
        - нет адаптеров на одной из цепей
        - bridge cost для пары не известен

        Параметры
        ---------
        from_chain : str
            Цепь-источник (например, "ethereum").
        to_chain : str
            Цепь-назначение (например, "arbitrum").
        capital_usd : float
            Размер капитала для анализа.
        """
        chain_data = self.load_chain_data()

        from_adapters = chain_data.get(from_chain, {})
        to_adapters = chain_data.get(to_chain, {})

        if not from_adapters or not to_adapters:
            return None

        bridge = self.get_bridge_cost(from_chain, to_chain)
        if bridge is None:
            return None

        # Best adapter = highest APY
        best_from_id, best_from_info = max(
            from_adapters.items(), key=lambda kv: kv[1]["apy_pct"]
        )
        best_to_id, best_to_info = max(
            to_adapters.items(), key=lambda kv: kv[1]["apy_pct"]
        )

        from_apy = best_from_info["apy_pct"]
        to_apy = best_to_info["apy_pct"]
        apy_diff = round(to_apy - from_apy, 4)

        total_bridge_cost = bridge.total_cost_usd(capital_usd)
        breakeven = self.compute_breakeven(apy_diff, total_bridge_cost, capital_usd)
        if breakeven != float("inf"):
            breakeven = round(breakeven, 2)

        is_profitable = breakeven < self.MAX_BREAKEVEN_DAYS

        annual_gain = round(capital_usd * apy_diff / 100.0, 2) if apy_diff > 0 else 0.0

        # Recommendation
        if apy_diff <= 0:
            recommendation = "HOLD"
        elif breakeven < 30.0:
            recommendation = "MOVE"
        elif breakeven < self.MAX_BREAKEVEN_DAYS:
            recommendation = "MONITOR"
        else:
            recommendation = "HOLD"

        return CrossChainOpportunity(
            from_chain=from_chain,
            to_chain=to_chain,
            from_adapter=best_from_id,
            to_adapter=best_to_id,
            from_apy_pct=round(from_apy, 4),
            to_apy_pct=round(to_apy, 4),
            apy_diff_pct=apy_diff,
            bridge_cost=bridge,
            breakeven_days=breakeven,
            is_profitable=is_profitable,
            annual_gain_usd=annual_gain,
            recommendation=recommendation,
        )

    def get_all_opportunities(
        self,
        capital_usd: float = _DEFAULT_CAPITAL_USD,
        min_diff_pct: float = _MIN_APY_DIFF_PCT,
    ) -> List[CrossChainOpportunity]:
        """Анализирует все пары chains из BRIDGE_COSTS.

        Фильтрует по min_diff_pct, сортирует по breakeven_days (наименьший первый).

        Параметры
        ---------
        capital_usd : float
            Размер капитала для расчётов.
        min_diff_pct : float
            Минимальный yield differential для включения в результат.
        """
        results: List[CrossChainOpportunity] = []
        for from_chain, to_chain in self.BRIDGE_COSTS:
            opp = self.analyze_pair(from_chain, to_chain, capital_usd)
            if opp is None:
                continue
            if opp.apy_diff_pct >= min_diff_pct:
                results.append(opp)
        results.sort(key=lambda o: (o.breakeven_days, -o.apy_diff_pct))
        return results

    def get_top_opportunity(
        self, capital_usd: float = _DEFAULT_CAPITAL_USD
    ) -> Optional[CrossChainOpportunity]:
        """Лучшая возможность (наименьший breakeven среди is_profitable=True).

        Возвращает None если нет выгодных возможностей.
        """
        opps = self.get_all_opportunities(capital_usd)
        profitable = [o for o in opps if o.is_profitable]
        if not profitable:
            return None
        return profitable[0]  # уже отсортированы по breakeven_days

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def format_report(self, capital_usd: float = _DEFAULT_CAPITAL_USD) -> str:
        """Текстовый отчёт для логов/Telegram (≤ 2000 chars)."""
        opps = self.get_all_opportunities(capital_usd)
        top = self.get_top_opportunity(capital_usd)

        lines = [
            "=== CrossChainOpportunityAnalyzer ===",
            (f"Capital: ${capital_usd:,.0f}  |  Min diff: {self.MIN_APY_DIFF_PCT}%"
             f"  |  Max breakeven: {self.MAX_BREAKEVEN_DAYS:.0f}d"),
            "",
        ]

        if top:
            lines += [
                f"Top: {top.from_chain} → {top.to_chain}"
                f"  +{top.apy_diff_pct:.2f}%  breakeven={top.breakeven_days:.1f}d"
                f"  [{top.recommendation}]",
                "",
            ]
        else:
            lines += ["No profitable opportunities found.", ""]

        profitable_count = sum(1 for o in opps if o.is_profitable)
        lines.append(
            f"Opportunities: {len(opps)} found, {profitable_count} profitable"
        )
        lines.append("")

        for o in opps[:10]:  # top-10 in report to stay under 2000 chars
            be_str = f"{o.breakeven_days:.1f}d" if o.breakeven_days != float("inf") else "∞"
            lines.append(
                f"  {o.from_chain:10s}→{o.to_chain:10s}"
                f"  diff=+{o.apy_diff_pct:.2f}%"
                f"  be={be_str:>8s}"
                f"  [{o.recommendation}]"
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _opportunity_to_dict(opp: CrossChainOpportunity) -> dict:
        """Конвертирует CrossChainOpportunity в JSON-совместимый dict."""
        b = opp.bridge_cost
        return {
            "from_chain": opp.from_chain,
            "to_chain": opp.to_chain,
            "from_adapter": opp.from_adapter,
            "to_adapter": opp.to_adapter,
            "from_apy_pct": opp.from_apy_pct,
            "to_apy_pct": opp.to_apy_pct,
            "apy_diff_pct": opp.apy_diff_pct,
            "bridge_cost": {
                "chain_from": b.chain_from,
                "chain_to": b.chain_to,
                "gas_cost_usd": b.gas_cost_usd,
                "slippage_pct": b.slippage_pct,
                "time_hours": b.time_hours,
            },
            "breakeven_days": (
                opp.breakeven_days
                if opp.breakeven_days != float("inf")
                else None
            ),
            "is_profitable": opp.is_profitable,
            "annual_gain_usd": opp.annual_gain_usd,
            "recommendation": opp.recommendation,
        }

    def to_dict(self) -> dict:
        """Полный анализ в виде dict для JSON-сериализации."""
        capital = self.DEFAULT_CAPITAL_USD
        opps = self.get_all_opportunities(capital)
        top = self.get_top_opportunity(capital)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "capital_usd": capital,
            "min_apy_diff_pct": self.MIN_APY_DIFF_PCT,
            "max_breakeven_days": self.MAX_BREAKEVEN_DAYS,
            "top_opportunity": self._opportunity_to_dict(top) if top else None,
            "opportunities": [self._opportunity_to_dict(o) for o in opps],
            "total_opportunities": len(opps),
            "profitable_count": sum(1 for o in opps if o.is_profitable),
        }

    def save_analysis(self, output_path: Optional[str] = None) -> str:
        """Сохраняет data/cross_chain_analysis.json атомарно (tmp + os.replace).

        Хранит кольцевой буфер из последних 30 снапшотов.

        Параметры
        ---------
        output_path : str | None
            Путь к выходному файлу. По умолчанию:
            ``{data_dir}/cross_chain_analysis.json``.

        Возвращает
        ----------
        str
            Абсолютный путь к сохранённому файлу.
        """
        if output_path is None:
            out_path = self._output_dir / "cross_chain_analysis.json"
        else:
            out_path = Path(output_path)

        new_snapshot = self.to_dict()

        # Загружаем существующий ring-buffer
        snapshots: List[dict] = []
        try:
            with open(out_path, encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict) and "snapshots" in existing:
                raw = existing.get("snapshots", [])
                if isinstance(raw, list):
                    snapshots = raw
            elif isinstance(existing, list):
                snapshots = existing
        except Exception:
            snapshots = []

        snapshots.append(new_snapshot)
        snapshots = snapshots[-_RING_BUFFER_SIZE:]

        output = {
            "schema_version": 1,
            "generated_at": new_snapshot["generated_at"],
            "latest": new_snapshot,
            "snapshots": snapshots,
        }

        # Атомарная запись: tmp + os.replace
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(out_path) + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(output, fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(out_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return str(out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[List[str]] = None) -> int:
    """CLI entry-point.

    Usage:
        python3 -m spa_core.analytics.cross_chain_opportunity [--check | --run]

    --check (default): вычислить и вывести без записи на диск.
    --run:             вычислить, вывести и атомарно записать в data/.
    """
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv

    analyzer = CrossChainOpportunityAnalyzer()
    print(analyzer.format_report())

    top = analyzer.get_top_opportunity()
    if top:
        print("\nTop opportunity details:")
        print(f"  {top.from_chain} → {top.to_chain}")
        print(f"  from_adapter : {top.from_adapter} @ {top.from_apy_pct:.2f}%")
        print(f"  to_adapter   : {top.to_adapter} @ {top.to_apy_pct:.2f}%")
        print(f"  APY diff     : +{top.apy_diff_pct:.2f}%")
        be_str = f"{top.breakeven_days:.1f}" if top.breakeven_days != float("inf") else "∞"
        print(f"  Breakeven    : {be_str} days")
        print(f"  Annual gain  : ${top.annual_gain_usd:,.2f} on ${analyzer.DEFAULT_CAPITAL_USD:,.0f}")
        print(f"  Bridge cost  : ${top.bridge_cost.total_cost_usd(analyzer.DEFAULT_CAPITAL_USD):,.2f}")
        print(f"  Rec          : {top.recommendation}")

    if run_mode:
        path = analyzer.save_analysis()
        print(f"\n✅ Analysis saved → {path}")
    else:
        print("\n(dry-run: use --run to save to data/cross_chain_analysis.json)")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
