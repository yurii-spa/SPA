"""
Portfolio Heat Map Generator (MP-597).
Генерирует data/heat_map.json для dashboard отображения.
Структура: сетка адаптеров, сгруппированных по chain + tier.

Каждая ячейка (HeatMapCell) = один адаптер:
  - цвет    = APY bucket (low/medium/high/very_high)
  - размер  = TVL bucket (small/medium/large)
  - группа  = chain × tier (T1_ethereum, T2_base, ...)

CLI:
    python3 -m spa_core.analytics.portfolio_heat_map --check   # вычислить + вывести
    python3 -m spa_core.analytics.portfolio_heat_map --run     # + записать в data/

Только stdlib. Read-only advisory модуль. MP-597.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.base import BaseAnalytics

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Ключи верхнего уровня adapter_status.json, которые не являются записями адаптеров
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode",
    "live_apy_enabled", "mev_protection", "adapters", "base_gas_monitor",
})

#: Псевдонимы chain → канонические имена
_CHAIN_ALIASES: Dict[str, str] = {
    "ethereum": "ethereum", "mainnet": "ethereum", "eth": "ethereum",
    "arbitrum": "arbitrum", "arb": "arbitrum",
    "arbitrum-one": "arbitrum", "arbitrum one": "arbitrum",
    "base": "base",
    "optimism": "optimism", "opt": "optimism", "op": "optimism",
    "op mainnet": "optimism", "op-mainnet": "optimism",
    "polygon": "polygon", "matic": "polygon", "polygon-mainnet": "polygon",
}

#: Поддерживаемые chains (в порядке вывода)
SUPPORTED_CHAINS: List[str] = ["ethereum", "arbitrum", "base", "optimism", "polygon"]

#: Порядок chain для сортировки групп
CHAIN_ORDER: List[str] = ["ethereum", "arbitrum", "base", "optimism", "polygon"]

#: Дефолтный risk_score по tier (если поле отсутствует)
_TIER_DEFAULT_RISK: Dict[str, float] = {
    "T1": 0.20,
    "T2": 0.35,
    "T3": 0.55,
    "T2-conditional": 0.40,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_chain(raw: str) -> str:
    """Нормализует строку chain в каноническое имя."""
    return _CHAIN_ALIASES.get(raw.lower().strip(), raw.lower().strip())


def _normalize_id(adapter_id: str) -> str:
    """Нормализует adapter_id для дедупликации: lowercase, «-» → «_»."""
    return adapter_id.lower().replace("-", "_").replace(" ", "_")


def _extract_apy(entry: dict, chain: Optional[str] = None) -> float:
    """Извлекает APY (%) из словаря entry.

    Приоритет: ``apy_pct`` → ``apy`` → ``mock_apy[chain]["USDC"]`` → 0.0.
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


def _extract_risk(entry: dict) -> float:
    """Извлекает risk_score. Fallback по tier."""
    rs = entry.get("risk_score")
    if isinstance(rs, (int, float)) and not isinstance(rs, bool):
        return float(rs)
    tier = str(entry.get("tier", ""))
    return _TIER_DEFAULT_RISK.get(tier, 0.30)


def _extract_tvl(entry: dict) -> float:
    """Извлекает tvl_usd."""
    tvl = entry.get("tvl_usd")
    if isinstance(tvl, (int, float)) and not isinstance(tvl, bool):
        return max(0.0, float(tvl))
    return 0.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class HeatMapCell:
    """Одна ячейка heat map — один адаптер на одном chain."""
    adapter_id: str
    chain: str
    tier: str            # T1 / T2 / T3 / T2-conditional
    apy_pct: float
    risk_score: float
    tvl_usd: float
    tvl_formatted: str   # "$1.2B", "$800.0M", "$350K"
    color_bucket: str    # "low" / "medium" / "high" / "very_high"
    size_bucket: str     # "small" / "medium" / "large"
    label: str           # "Aave V3 Base"
    chain_emoji: str     # "⚪" Eth, "🔵" Arb/Base, "🔴" Opt, "🟣" Poly
    tooltip: str         # hover-текст для dashboard
    is_eligible: bool    # APY ∈ [1%,30%] AND TVL ≥ $5M


@dataclass
class HeatMapGroup:
    """Группа ячеек: один chain × один tier."""
    group_id: str        # "T1_ethereum", "T2_base"
    chain: str
    tier: str
    cells: List[HeatMapCell]
    avg_apy_pct: float
    total_tvl_usd: float
    count: int           # == len(cells)


@dataclass
class HeatMapData:
    """Полный dataset для heat map dashboard."""
    generated_at: str
    total_adapters: int
    groups: List[HeatMapGroup]
    apy_range: Dict[str, float]   # {min, max, avg}
    tvl_total_usd: float
    color_legend: Dict[str, str]  # {low: "<4%", medium: "4–7%", …}
    chain_summary: Dict[str, dict]  # {ethereum: {count, avg_apy}, …}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class PortfolioHeatMapGenerator(BaseAnalytics):
    """Генерирует структурированные данные для heat map визуализации.

    Читает ``data/adapter_status.json`` (read-only), строит HeatMapCell
    для каждого адаптера, группирует по chain × tier и записывает
    ``data/heat_map.json``.

    Пример использования
    --------------------
    gen  = PortfolioHeatMapGenerator()
    hm   = gen.generate()
    path = gen.save()
    d    = gen.to_dict()
    """

    OUTPUT_PATH = "data/heat_map.json"

    #: APY bucket диапазоны — (имя, нижняя включительно, верхняя не включительно)
    APY_BUCKETS: List[Tuple[str, float, float]] = [
        ("low",       0.0,           4.0),
        ("medium",    4.0,           7.0),
        ("high",      7.0,          10.0),
        ("very_high", 10.0, float("inf")),
    ]

    #: TVL bucket диапазоны (USD)
    TVL_BUCKETS: List[Tuple[str, float, float]] = [
        ("small",    0.0,             100_000_000.0),
        ("medium",   100_000_000.0,  1_000_000_000.0),
        ("large",   1_000_000_000.0, float("inf")),
    ]

    #: Эмодзи по chain
    CHAIN_EMOJIS: Dict[str, str] = {
        "ethereum": "⚪",
        "arbitrum": "🔵",
        "base":     "🔵",
        "optimism": "🔴",
        "polygon":  "🟣",
    }

    _MIN_ELIGIBLE_TVL: float = 5_000_000.0
    _MIN_ELIGIBLE_APY: float = 1.0
    _MAX_ELIGIBLE_APY: float = 30.0

    def __init__(self, data_path: Optional[str] = None) -> None:
        """
        Parameters
        ----------
        data_path : str | None
            Путь к ``adapter_status.json``. По умолчанию — ``data/`` в корне репо.
        """
        super().__init__()
        if data_path is None:
            self._data_path = _DEFAULT_DATA_DIR / "adapter_status.json"
        else:
            self._data_path = Path(data_path)
        self._output_dir = self._data_path.parent

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_adapter_data(self) -> dict:
        """Загружает adapter_status.json. Возвращает {} при любой ошибке."""
        try:
            with open(self._data_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Bucket helpers
    # ------------------------------------------------------------------

    def format_tvl(self, tvl_usd: float) -> str:
        """Форматирует TVL: ``"$1.2B"``, ``"$800.0M"``, ``"$350K"``."""
        if tvl_usd >= 1_000_000_000.0:
            return f"${tvl_usd / 1_000_000_000.0:.1f}B"
        if tvl_usd >= 1_000_000.0:
            return f"${tvl_usd / 1_000_000.0:.1f}M"
        return f"${tvl_usd / 1_000.0:.0f}K"

    def get_color_bucket(self, apy_pct: float) -> str:
        """APY bucket: ``"low"`` / ``"medium"`` / ``"high"`` / ``"very_high"``."""
        for name, lo, hi in self.APY_BUCKETS:
            if lo <= apy_pct < hi:
                return name
        # apy_pct < 0 или NaN — считаем low
        return "low"

    def get_size_bucket(self, tvl_usd: float) -> str:
        """TVL bucket: ``"small"`` / ``"medium"`` / ``"large"``."""
        for name, lo, hi in self.TVL_BUCKETS:
            if lo <= tvl_usd < hi:
                return name
        return "small"

    # ------------------------------------------------------------------
    # Cell builder
    # ------------------------------------------------------------------

    def make_cell(self, adapter_id: str, data: dict) -> HeatMapCell:
        """Строит HeatMapCell из предобработанного словаря данных адаптера.

        Parameters
        ----------
        adapter_id : str
            Идентификатор адаптера (используется для label и adapter_id поля).
        data : dict
            Ожидаемые ключи: chain, tier, apy_pct, risk_score, tvl_usd.
        """
        chain = str(data.get("chain", "ethereum"))
        tier = str(data.get("tier", "T2"))
        apy_pct = float(data.get("apy_pct", 0.0))
        risk_score = float(data.get("risk_score", 0.30))
        tvl_usd = float(data.get("tvl_usd", 0.0))

        # label: "aave_v3_base" → "Aave V3 Base"; поддержка дефисов
        label = adapter_id.replace("_", " ").replace("-", " ").title()

        chain_emoji = self.CHAIN_EMOJIS.get(chain.lower(), "⚫")
        tvl_formatted = self.format_tvl(tvl_usd)
        color_bucket = self.get_color_bucket(apy_pct)
        size_bucket = self.get_size_bucket(tvl_usd)

        tooltip = (
            f"APY: {apy_pct:.1f}% | TVL: {tvl_formatted} | "
            f"Risk: {risk_score:.2f} | Chain: {chain}"
        )

        is_eligible = (
            self._MIN_ELIGIBLE_APY <= apy_pct <= self._MAX_ELIGIBLE_APY
            and tvl_usd >= self._MIN_ELIGIBLE_TVL
        )

        return HeatMapCell(
            adapter_id=adapter_id,
            chain=chain,
            tier=tier,
            apy_pct=apy_pct,
            risk_score=risk_score,
            tvl_usd=tvl_usd,
            tvl_formatted=tvl_formatted,
            color_bucket=color_bucket,
            size_bucket=size_bucket,
            label=label,
            chain_emoji=chain_emoji,
            tooltip=tooltip,
            is_eligible=is_eligible,
        )

    # ------------------------------------------------------------------
    # Internal: parse raw entries from adapter_status.json
    # ------------------------------------------------------------------

    def _parse_raw_entries(self) -> List[dict]:
        """Парсит adapter_status.json в список сырых записей для построения ячеек.

        Каждая запись: {adapter_id, chain, tier, apy_pct, risk_score, tvl_usd}.

        Два источника с приоритетом Source 1 > Source 2:
        1. Protocol-level dict-записи с полем ``chain``/``network``.
        2. Список ``adapters[]`` — для chain/протоколов, не охваченных Source 1.

        Дедупликация: (canonical_chain, normalized_adapter_id).
        """
        data = self.load_adapter_data()
        raw_entries: List[dict] = []
        seen: set = set()  # (chain, normalized_id)

        # ── Source 1: protocol-level dicts ──────────────────────────────────
        for key, val in data.items():
            if key in _SKIP_KEYS or key.startswith("_"):
                continue
            if not isinstance(val, dict):
                continue

            chain_raw = val.get("chain") or val.get("network", "")
            if not chain_raw:
                continue
            chain = _normalize_chain(str(chain_raw))

            adapter_id = str(
                val.get("adapter_id") or val.get("protocol_id") or key
            )
            norm_id = _normalize_id(adapter_id)
            seen_key = (chain, norm_id)
            if seen_key in seen:
                continue
            seen.add(seen_key)

            raw_entries.append({
                "adapter_id": adapter_id,
                "chain": chain,
                "tier": str(val.get("tier", "T2")),
                "apy_pct": _extract_apy(val),
                "risk_score": _extract_risk(val),
                "tvl_usd": _extract_tvl(val),
            })

        # ── Source 2: adapters[] list (заполняет пробелы) ────────────────────
        for adapter in data.get("adapters", []):
            if not isinstance(adapter, dict):
                continue
            pkey = str(adapter.get("protocol_key", "unknown"))
            tier = str(adapter.get("tier", "T2"))
            norm_pkey = _normalize_id(pkey)
            chains_list = adapter.get("chains", [])

            for chain_raw in chains_list:
                chain = _normalize_chain(str(chain_raw))
                if chain not in SUPPORTED_CHAINS:
                    continue
                seen_key = (chain, norm_pkey)
                if seen_key in seen:
                    continue
                seen.add(seen_key)

                # adapter_id: "pkey_chain" для multi-chain адаптеров
                adapter_id = (
                    f"{norm_pkey}_{chain}"
                    if len(chains_list) > 1
                    else norm_pkey
                )

                raw_entries.append({
                    "adapter_id": adapter_id,
                    "chain": chain,
                    "tier": tier,
                    "apy_pct": _extract_apy(adapter, chain),
                    "risk_score": _TIER_DEFAULT_RISK.get(tier, 0.30),
                    "tvl_usd": 0.0,
                })

        return raw_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> HeatMapData:
        """Читает адаптеры, строит cells, группирует по chain × tier.

        Возвращает
        ----------
        HeatMapData
            Полный dataset heat map: groups, apy_range, chain_summary, …
        """
        raw_entries = self._parse_raw_entries()
        cells: List[HeatMapCell] = [
            self.make_cell(e["adapter_id"], e) for e in raw_entries
        ]

        # ── Группировка по tier×chain ────────────────────────────────────────
        groups_dict: Dict[str, dict] = {}
        for cell in cells:
            group_id = f"{cell.tier}_{cell.chain}"
            if group_id not in groups_dict:
                groups_dict[group_id] = {
                    "chain": cell.chain,
                    "tier": cell.tier,
                    "cells": [],
                }
            groups_dict[group_id]["cells"].append(cell)

        groups: List[HeatMapGroup] = []
        for group_id, gdata in groups_dict.items():
            gcells: List[HeatMapCell] = gdata["cells"]
            # Ячейки внутри группы: APY по убыванию
            gcells.sort(key=lambda c: c.apy_pct, reverse=True)
            n = len(gcells)
            avg_apy = sum(c.apy_pct for c in gcells) / n if n else 0.0
            total_tvl = sum(c.tvl_usd for c in gcells)
            groups.append(HeatMapGroup(
                group_id=group_id,
                chain=gdata["chain"],
                tier=gdata["tier"],
                cells=gcells,
                avg_apy_pct=round(avg_apy, 4),
                total_tvl_usd=round(total_tvl, 2),
                count=n,
            ))

        # Сортировка групп: по chain-порядку, затем по tier
        def _sort_key(g: HeatMapGroup) -> Tuple[int, str]:
            idx = CHAIN_ORDER.index(g.chain) if g.chain in CHAIN_ORDER else 99
            return (idx, g.tier)

        groups.sort(key=_sort_key)

        # ── APY range ────────────────────────────────────────────────────────
        all_apys = [c.apy_pct for c in cells if c.apy_pct > 0]
        if all_apys:
            apy_range: Dict[str, float] = {
                "min": round(min(all_apys), 4),
                "max": round(max(all_apys), 4),
                "avg": round(sum(all_apys) / len(all_apys), 4),
            }
        else:
            apy_range = {"min": 0.0, "max": 0.0, "avg": 0.0}

        # ── TVL total ────────────────────────────────────────────────────────
        tvl_total = round(sum(c.tvl_usd for c in cells), 2)

        # ── Chain summary ────────────────────────────────────────────────────
        chain_summary: Dict[str, dict] = {}
        for chain in CHAIN_ORDER:
            chain_cells = [c for c in cells if c.chain == chain]
            if not chain_cells:
                continue
            apys = [c.apy_pct for c in chain_cells if c.apy_pct > 0]
            chain_summary[chain] = {
                "count": len(chain_cells),
                "avg_apy": round(sum(apys) / len(apys), 4) if apys else 0.0,
            }

        return HeatMapData(
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_adapters=len(cells),
            groups=groups,
            apy_range=apy_range,
            tvl_total_usd=tvl_total,
            color_legend={
                "low":       "<4%",
                "medium":    "4–7%",   # 4–7% (en-dash)
                "high":      "7–10%",  # 7–10%
                "very_high": ">10%",
            },
            chain_summary=chain_summary,
        )

    def to_dict(self) -> dict:
        """Возвращает полный HeatMapData в виде JSON-serializable dict."""
        hm = self.generate()

        groups_list = []
        for g in hm.groups:
            cells_list = [
                {
                    "adapter_id": c.adapter_id,
                    "chain":      c.chain,
                    "tier":       c.tier,
                    "apy_pct":    c.apy_pct,
                    "risk_score": c.risk_score,
                    "tvl_usd":    c.tvl_usd,
                    "tvl_formatted": c.tvl_formatted,
                    "color_bucket":  c.color_bucket,
                    "size_bucket":   c.size_bucket,
                    "label":         c.label,
                    "chain_emoji":   c.chain_emoji,
                    "tooltip":       c.tooltip,
                    "is_eligible":   c.is_eligible,
                }
                for c in g.cells
            ]
            groups_list.append({
                "group_id":      g.group_id,
                "chain":         g.chain,
                "tier":          g.tier,
                "cells":         cells_list,
                "avg_apy_pct":   g.avg_apy_pct,
                "total_tvl_usd": g.total_tvl_usd,
                "count":         g.count,
            })

        return {
            "generated_at":    hm.generated_at,
            "total_adapters":  hm.total_adapters,
            "groups":          groups_list,
            "apy_range":       hm.apy_range,
            "tvl_total_usd":   hm.tvl_total_usd,
            "color_legend":    hm.color_legend,
            "chain_summary":   hm.chain_summary,
        }

    def save(self, output_path: Optional[str] = None) -> str:
        """Сохраняет data/heat_map.json атомарно (tmp + os.replace).

        Ring-buffer НЕ применяется — heat_map.json всегда «живые» данные.

        Parameters
        ----------
        output_path : str | None
            Путь к выходному файлу. По умолчанию: ``{data_dir}/heat_map.json``.

        Возвращает
        ----------
        str
            Абсолютный путь к сохранённому файлу.
        """
        if output_path is None:
            out_path = self._output_dir / "heat_map.json"
        else:
            out_path = Path(output_path)

        data = self.to_dict()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(out_path) + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
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
        python3 -m spa_core.analytics.portfolio_heat_map [--check | --run]

    --check (default): вычислить и вывести, без записи.
    --run:             вычислить, вывести и записать в data/heat_map.json.
    """
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv
    gen = PortfolioHeatMapGenerator()
    hm = gen.generate()

    print("=== PortfolioHeatMapGenerator Report ===")
    print(f"Generated:       {hm.generated_at}")
    print(f"Total adapters:  {hm.total_adapters}")
    print(f"APY range:       {hm.apy_range['min']:.2f}% – {hm.apy_range['max']:.2f}%"
          f"  avg={hm.apy_range['avg']:.2f}%")
    print(f"TVL total:       ${hm.tvl_total_usd:,.0f}")
    print(f"Groups:          {len(hm.groups)}")
    print()

    print("Groups breakdown:")
    for g in hm.groups:
        eligible = sum(1 for c in g.cells if c.is_eligible)
        print(
            f"  {g.group_id:25s}  count={g.count:2d}  "
            f"avg_apy={g.avg_apy_pct:.2f}%  "
            f"tvl=${g.total_tvl_usd:>15,.0f}  "
            f"eligible={eligible}"
        )

    print()
    print("Chain summary:")
    for chain, info in hm.chain_summary.items():
        emoji = PortfolioHeatMapGenerator.CHAIN_EMOJIS.get(chain, "⚫")
        print(f"  {emoji} {chain:10s}  count={info['count']:2d}  "
              f"avg_apy={info['avg_apy']:.2f}%")

    if run_mode:
        path = gen.save()
        print(f"\n✅ heat_map.json saved → {path}")
    else:
        print("\n(dry-run: use --run to save to data/heat_map.json)")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
