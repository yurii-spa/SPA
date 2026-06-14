"""
Multi-chain monitor — агрегирует APY, health, gas savings по L2/multi-chain адаптерам.
Поддерживаемые chains: ethereum (L1), arbitrum, base, optimism, polygon.
Только stdlib. Читает data/adapter_status.json.

CLI:
    python3 -m spa_core.analytics.multi_chain_monitor --check   # вывод без записи (дефолт)
    python3 -m spa_core.analytics.multi_chain_monitor --run     # вычислить + записать

MP-590.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_CHAINS: List[str] = ["ethereum", "arbitrum", "base", "optimism", "polygon"]
L2_CHAINS: List[str] = ["arbitrum", "base", "optimism", "polygon"]

# Chain name aliases → canonical name
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

# Default gas savings % vs Ethereum mainnet (used when not present in status JSON)
_CHAIN_GAS_SAVINGS_DEFAULT: Dict[str, float] = {
    "ethereum": 0.0,
    "arbitrum": 90.0,
    "base": 95.0,
    "optimism": 95.0,
    "polygon": 80.0,
}

# Default risk score by tier (fallback when risk_score field absent)
_TIER_DEFAULT_RISK: Dict[str, float] = {
    "T1": 0.20,
    "T2": 0.35,
    "T3": 0.55,
    "T2-conditional": 0.40,
}

# USDC peg tolerance for peg_healthy check
_PEG_TOLERANCE: float = 0.005

# Gas mainnet reference price (USD per tx)
_GAS_MAINNET_USD: float = 0.10

# Keys to skip when iterating top-level adapter_status.json
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode",
    "live_apy_enabled", "mev_protection", "adapters",
    "base_gas_monitor",
})

# Ring-buffer size for save_report
_RING_BUFFER_SIZE: int = 30


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChainSnapshot:
    """Агрегированный снапшот по одному chain."""
    chain: str
    adapter_count: int
    avg_apy_pct: float
    best_apy_pct: float
    best_adapter: str
    avg_risk_score: float
    total_tvl_usd: float
    avg_gas_savings_pct: float  # vs mainnet (0.0 для L1 ethereum)
    healthy_count: int          # adapters where USDC peg OK
    timestamp: str


@dataclass
class MultiChainReport:
    """Сводный отчёт по всем поддерживаемым chains."""
    generated_at: str
    chains: Dict[str, ChainSnapshot]    # chain → snapshot
    best_chain: str                     # chain с наибольшим avg_apy_pct
    best_adapter_overall: str           # адаптер с наибольшим APY
    best_apy_overall: float
    total_adapters: int
    total_tvl_usd: float
    l2_premium_pct: float               # avg(L2 APY) - ethereum avg_apy


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_chain(raw: str) -> str:
    """Нормализует строку chain в каноническое имя из SUPPORTED_CHAINS.

    Неизвестные значения возвращаются lowercase как есть (не вызывает исключений).
    """
    key = raw.lower().strip()
    return _CHAIN_ALIASES.get(key, key)


def _extract_apy(entry: dict, chain: Optional[str] = None) -> float:
    """Извлекает APY (%) из словаря entry.

    Приоритет: ``apy_pct`` → ``apy`` → ``mock_apy[chain]["USDC"]`` → 0.0
    Отклоняет bool, нечисловые значения, ≤ 0.
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


def _extract_risk_score(entry: dict) -> float:
    """Извлекает risk_score из entry. Fallback по tier."""
    rs = entry.get("risk_score")
    if isinstance(rs, (int, float)) and not isinstance(rs, bool):
        return float(rs)
    tier = str(entry.get("tier", ""))
    return _TIER_DEFAULT_RISK.get(tier, 0.30)


def _extract_tvl(entry: dict) -> float:
    """Извлекает tvl_usd из entry."""
    tvl = entry.get("tvl_usd")
    if isinstance(tvl, (int, float)) and not isinstance(tvl, bool):
        return float(tvl)
    return 0.0


def _extract_gas_savings(entry: dict, chain: str) -> float:
    """Извлекает или вычисляет gas_savings_pct.

    Приоритет:
    1. Явное поле ``gas_savings_pct``
    2. Вычисление: gas_advantage_usd / (gas_base_usd + gas_advantage_usd) * 100
    3. Вычисление из gas_l2_usd: (mainnet - l2) / mainnet * 100
    4. Дефолт по chain из _CHAIN_GAS_SAVINGS_DEFAULT
    """
    gs = entry.get("gas_savings_pct")
    if isinstance(gs, (int, float)) and not isinstance(gs, bool):
        return float(gs)
    adv = entry.get("gas_advantage_usd")
    base_gas = entry.get("gas_base_usd")
    if (isinstance(adv, (int, float)) and not isinstance(adv, bool) and
            isinstance(base_gas, (int, float)) and not isinstance(base_gas, bool)):
        total = float(base_gas) + float(adv)
        if total > 0:
            return round(float(adv) / total * 100.0, 1)
    l2 = entry.get("gas_l2_usd")
    if isinstance(l2, (int, float)) and not isinstance(l2, bool):
        savings = (_GAS_MAINNET_USD - float(l2)) / _GAS_MAINNET_USD * 100.0
        return max(0.0, round(savings, 1))
    return _CHAIN_GAS_SAVINGS_DEFAULT.get(chain, 0.0)


def _extract_peg_healthy(entry: dict) -> bool:
    """Определяет peg_healthy. Default-safe (отсутствие usdc_price → True)."""
    price = entry.get("usdc_price")
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        return abs(float(price) - 1.0) <= _PEG_TOLERANCE
    return True


def _resolve_chain_from_entry(entry: dict) -> Optional[str]:
    """Извлекает chain/network из словаря, возвращает нормализованное имя или None."""
    raw = entry.get("chain") or entry.get("network", "")
    if not raw:
        return None
    normalized = _normalize_chain(str(raw))
    return normalized if normalized in SUPPORTED_CHAINS else None


# ---------------------------------------------------------------------------
# MultiChainMonitor
# ---------------------------------------------------------------------------

class MultiChainMonitor:
    """Агрегирует APY, TVL и gas savings по L2/multi-chain адаптерам.

    Читает ``data/adapter_status.json``, строит ChainSnapshot для каждого
    поддерживаемого chain и возвращает MultiChainReport.

    Параметры
    ---------
    data_path : str | None
        Путь к ``adapter_status.json``. По умолчанию — ``data/`` относительно
        корня репозитория.

    Пример использования
    --------------------
    monitor = MultiChainMonitor()
    report  = monitor.get_report()
    opps    = monitor.get_l2_opportunities(min_apy_pct=5.0)
    path    = monitor.save_report()
    """

    SUPPORTED_CHAINS = SUPPORTED_CHAINS
    L2_CHAINS = L2_CHAINS

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self._data_path = _DEFAULT_DATA_DIR / "adapter_status.json"
        else:
            self._data_path = Path(data_path)
        self._output_dir = self._data_path.parent

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_adapter_status(self) -> dict:
        """Загружает adapter_status.json. Возвращает {} при любой ошибке.

        Никогда не бросает исключений — fail-safe.
        """
        try:
            with open(self._data_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Internal: parse all adapter entries from the status file
    # ------------------------------------------------------------------

    def _parse_adapter_entries(self) -> List[dict]:
        """Разбирает adapter_status.json в единый список записей.

        Каждая запись имеет поля:
            chain, adapter, apy_pct, risk_score, tvl_usd, gas_savings_pct,
            peg_healthy, tier

        Два источника:
        1. Protocol-level dict записи с полем ``chain``/``network``
           (более точные — имеют приоритет).
        2. Список ``adapters[]`` — разворачивается по ``chains[]``
           (только для цепочек, не охваченных protocol-level записями).
        """
        data = self.load_adapter_status()
        entries: List[dict] = []
        seen: set = set()  # (chain, adapter) — уже добавлены

        # ── Источник 1: protocol-level entries (приоритетные) ──────────────
        for key, val in data.items():
            if key in _SKIP_KEYS or key.startswith("_"):
                continue
            if not isinstance(val, dict):
                continue
            chain = _resolve_chain_from_entry(val)
            if chain is None:
                continue
            adapter_name = (
                val.get("adapter_id")
                or val.get("protocol_id")
                or val.get("protocol")
                or key
            )
            entries.append({
                "chain": chain,
                "adapter": str(adapter_name),
                "apy_pct": _extract_apy(val),
                "risk_score": _extract_risk_score(val),
                "tvl_usd": _extract_tvl(val),
                "gas_savings_pct": _extract_gas_savings(val, chain),
                "peg_healthy": _extract_peg_healthy(val),
                "tier": str(val.get("tier", "T2")),
            })
            seen.add((chain, str(adapter_name)))

        # ── Источник 2: adapters[] list (заполняет пробелы) ────────────────
        for adapter in data.get("adapters", []):
            if not isinstance(adapter, dict):
                continue
            pkey = str(adapter.get("protocol_key", "unknown"))
            tier = str(adapter.get("tier", "T2"))
            for chain_raw in adapter.get("chains", []):
                chain = _normalize_chain(str(chain_raw))
                if chain not in SUPPORTED_CHAINS:
                    continue
                if (chain, pkey) in seen:
                    continue  # уже покрыто protocol-level записью
                entries.append({
                    "chain": chain,
                    "adapter": pkey,
                    "apy_pct": _extract_apy(adapter, chain),
                    "risk_score": _TIER_DEFAULT_RISK.get(tier, 0.30),
                    "tvl_usd": 0.0,
                    "gas_savings_pct": _CHAIN_GAS_SAVINGS_DEFAULT.get(chain, 0.0),
                    "peg_healthy": True,
                    "tier": tier,
                })
                seen.add((chain, pkey))

        return entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_chain_snapshot(self, chain: str) -> ChainSnapshot:
        """Создаёт ChainSnapshot для заданного chain.

        Если в данных нет адаптеров для этого chain — возвращает пустой
        snapshot с нулевыми метриками. Никогда не бросает исключений.

        Параметры
        ---------
        chain : str
            Имя chain (нормализуется автоматически — принимает псевдонимы).
        """
        now = datetime.now(timezone.utc).isoformat()
        chain_canon = _normalize_chain(chain)
        entries = [e for e in self._parse_adapter_entries() if e["chain"] == chain_canon]

        if not entries:
            return ChainSnapshot(
                chain=chain_canon,
                adapter_count=0,
                avg_apy_pct=0.0,
                best_apy_pct=0.0,
                best_adapter="",
                avg_risk_score=0.0,
                total_tvl_usd=0.0,
                avg_gas_savings_pct=_CHAIN_GAS_SAVINGS_DEFAULT.get(chain_canon, 0.0),
                healthy_count=0,
                timestamp=now,
            )

        n = len(entries)
        avg_apy = sum(e["apy_pct"] for e in entries) / n
        best = max(entries, key=lambda e: e["apy_pct"])
        avg_risk = sum(e["risk_score"] for e in entries) / n
        total_tvl = sum(e["tvl_usd"] for e in entries)
        avg_gas = sum(e["gas_savings_pct"] for e in entries) / n
        healthy_count = sum(1 for e in entries if e["peg_healthy"])

        return ChainSnapshot(
            chain=chain_canon,
            adapter_count=n,
            avg_apy_pct=round(avg_apy, 4),
            best_apy_pct=round(best["apy_pct"], 4),
            best_adapter=best["adapter"],
            avg_risk_score=round(avg_risk, 4),
            total_tvl_usd=round(total_tvl, 2),
            avg_gas_savings_pct=round(avg_gas, 2),
            healthy_count=healthy_count,
            timestamp=now,
        )

    def get_report(self) -> MultiChainReport:
        """Создаёт полный MultiChainReport по всем поддерживаемым chains.

        Возвращает
        ----------
        MultiChainReport
            Содержит ChainSnapshot для каждого chain, best_chain,
            best_adapter_overall, l2_premium_pct и агрегированные метрики.
        """
        now = datetime.now(timezone.utc).isoformat()
        snapshots: Dict[str, ChainSnapshot] = {}
        for chain in SUPPORTED_CHAINS:
            snapshots[chain] = self.get_chain_snapshot(chain)

        # best_chain: chain с наибольшим avg_apy_pct (только непустые)
        non_empty = {c: s for c, s in snapshots.items() if s.adapter_count > 0}
        if non_empty:
            best_chain = max(non_empty, key=lambda c: non_empty[c].avg_apy_pct)
        else:
            best_chain = "ethereum"

        # best_adapter_overall + best_apy_overall
        all_entries = self._parse_adapter_entries()
        if all_entries:
            best_entry = max(all_entries, key=lambda e: e["apy_pct"])
            best_adapter_overall = best_entry["adapter"]
            best_apy_overall = round(best_entry["apy_pct"], 4)
        else:
            best_adapter_overall = ""
            best_apy_overall = 0.0

        total_adapters = sum(s.adapter_count for s in snapshots.values())
        total_tvl = sum(s.total_tvl_usd for s in snapshots.values())

        # l2_premium_pct = avg(L2 chains avg_apy) - ethereum avg_apy
        l2_apys = [
            snapshots[c].avg_apy_pct
            for c in L2_CHAINS
            if snapshots[c].adapter_count > 0
        ]
        eth_avg = snapshots["ethereum"].avg_apy_pct
        if l2_apys and eth_avg > 0:
            l2_premium = round(sum(l2_apys) / len(l2_apys) - eth_avg, 4)
        elif l2_apys:
            l2_premium = round(sum(l2_apys) / len(l2_apys), 4)
        else:
            l2_premium = 0.0

        return MultiChainReport(
            generated_at=now,
            chains=snapshots,
            best_chain=best_chain,
            best_adapter_overall=best_adapter_overall,
            best_apy_overall=best_apy_overall,
            total_adapters=total_adapters,
            total_tvl_usd=round(total_tvl, 2),
            l2_premium_pct=l2_premium,
        )

    def get_l2_opportunities(self, min_apy_pct: float = 5.0) -> List[dict]:
        """Возвращает L2 адаптеры с APY >= min_apy_pct, отсортированные по APY desc.

        Параметры
        ---------
        min_apy_pct : float
            Минимальный порог APY (%). По умолчанию 5.0%.

        Возвращает
        ----------
        list[dict]
            Список записей: {chain, adapter, apy_pct, risk_score,
            tvl_usd, gas_savings_pct}.
        """
        entries = self._parse_adapter_entries()
        l2_entries = [
            e for e in entries
            if e["chain"] in L2_CHAINS and e["apy_pct"] >= min_apy_pct
        ]
        l2_entries.sort(key=lambda e: e["apy_pct"], reverse=True)
        return [
            {
                "chain": e["chain"],
                "adapter": e["adapter"],
                "apy_pct": e["apy_pct"],
                "risk_score": e["risk_score"],
                "tvl_usd": e["tvl_usd"],
                "gas_savings_pct": e["gas_savings_pct"],
            }
            for e in l2_entries
        ]

    def get_best_per_chain(self) -> Dict[str, dict]:
        """Для каждого chain — лучший адаптер по APY.

        Возвращает
        ----------
        dict[str, dict]
            {chain: {adapter, apy_pct, risk_score}}.
            Chains без адаптеров в словарь не включаются.
        """
        entries = self._parse_adapter_entries()
        result: Dict[str, dict] = {}
        for chain in SUPPORTED_CHAINS:
            chain_entries = [e for e in entries if e["chain"] == chain]
            if not chain_entries:
                continue
            best = max(chain_entries, key=lambda e: e["apy_pct"])
            result[chain] = {
                "adapter": best["adapter"],
                "apy_pct": best["apy_pct"],
                "risk_score": best["risk_score"],
            }
        return result

    def to_dict(self) -> dict:
        """Возвращает полный отчёт в виде dict, пригодного для JSON-сериализации."""
        report = self.get_report()
        chains_dict: Dict[str, dict] = {}
        for chain, snap in report.chains.items():
            chains_dict[chain] = {
                "chain": snap.chain,
                "adapter_count": snap.adapter_count,
                "avg_apy_pct": snap.avg_apy_pct,
                "best_apy_pct": snap.best_apy_pct,
                "best_adapter": snap.best_adapter,
                "avg_risk_score": snap.avg_risk_score,
                "total_tvl_usd": snap.total_tvl_usd,
                "avg_gas_savings_pct": snap.avg_gas_savings_pct,
                "healthy_count": snap.healthy_count,
                "timestamp": snap.timestamp,
            }
        return {
            "generated_at": report.generated_at,
            "chains": chains_dict,
            "best_chain": report.best_chain,
            "best_adapter_overall": report.best_adapter_overall,
            "best_apy_overall": report.best_apy_overall,
            "total_adapters": report.total_adapters,
            "total_tvl_usd": report.total_tvl_usd,
            "l2_premium_pct": report.l2_premium_pct,
        }

    def save_report(self, output_path: Optional[str] = None) -> str:
        """Сохраняет отчёт в data/multi_chain_report.json атомарно (tmp + os.replace).

        Хранит кольцевой буфер из последних 30 снапшотов.

        Параметры
        ---------
        output_path : str | None
            Путь к выходному файлу. По умолчанию:
            ``{data_dir}/multi_chain_report.json``.

        Возвращает
        ----------
        str
            Абсолютный путь к сохранённому файлу.
        """
        if output_path is None:
            out_path = self._output_dir / "multi_chain_report.json"
        else:
            out_path = Path(output_path)

        new_snapshot = self.to_dict()

        # Загружаем существующий ring-buffer
        snapshots: List[dict] = []
        try:
            with open(out_path, encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict) and "snapshots" in existing:
                raw_snaps = existing.get("snapshots", [])
                if isinstance(raw_snaps, list):
                    snapshots = raw_snaps
            elif isinstance(existing, list):
                snapshots = existing
        except Exception:
            snapshots = []

        # Добавляем новый snapshot, ограничиваем ring-buffer
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
        python3 -m spa_core.analytics.multi_chain_monitor [--check | --run]

    --check (default): вычислить и вывести, без записи на диск.
    --run:             вычислить, вывести и атомарно записать в data/.
    """
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv

    monitor = MultiChainMonitor()
    report_dict = monitor.to_dict()

    print("=== MultiChainMonitor Report ===")
    print(f"Generated: {report_dict['generated_at']}")
    print(f"Best chain:   {report_dict['best_chain']}")
    print(f"Best adapter: {report_dict['best_adapter_overall']} "
          f"({report_dict['best_apy_overall']:.2f}%)")
    print(f"Total adapters: {report_dict['total_adapters']}")
    print(f"Total TVL: ${report_dict['total_tvl_usd']:,.0f}")
    print(f"L2 premium vs L1: {report_dict['l2_premium_pct']:+.2f}%")
    print()

    print("Chain breakdown:")
    for chain in SUPPORTED_CHAINS:
        snap = report_dict["chains"].get(chain, {})
        if snap.get("adapter_count", 0) == 0:
            print(f"  {chain:12s}  — no adapters")
            continue
        print(
            f"  {chain:12s}  adapters={snap['adapter_count']:2d} "
            f"avg_apy={snap['avg_apy_pct']:.2f}%  "
            f"best={snap['best_adapter']}({snap['best_apy_pct']:.2f}%)  "
            f"gas_savings={snap['avg_gas_savings_pct']:.0f}%"
        )

    if run_mode:
        path = monitor.save_report()
        print(f"\n✅ Report saved → {path}")
    else:
        print("\n(dry-run: use --run to save to data/multi_chain_report.json)")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
