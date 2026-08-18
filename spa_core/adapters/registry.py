"""
spa_core/adapters/registry.py

Per-adapter METADATA (module, class, tier, chain, asset) keyed by adapter id.

MP-1380 (v9.96) introduced this dict alongside the canonical list in
``spa_core/adapters/__init__.py`` — and for three years BOTH objects were called
``ADAPTER_REGISTRY``.  Цикл #274 развёл имена: под одним именем не могут жить два
разных ответа на вопрос «есть ли у протокола адаптер?».

    ``spa_core.adapters.ADAPTER_REGISTRY``          — КАНОНИЧЕСКИЙ реестр
                                                      (список кортежей, 35 записей —
                                                      36 до ADR-070 п.17, снявшего `frax`;
                                                      `aave_v3`), инвариант CLAUDE.md;
    ``spa_core.adapters.registry.ADAPTER_METADATA`` — ЭТОТ объект: метаданные,
                                                      22 записи, СВОИ имена
                                                      (`aave_usdc`, не `aave_v3`);
    ``…adapter_orchestrator.POLLED_ADAPTERS``       — что цикл реально опрашивает (8).

Составы НЕ совпадают и совпадать не обязаны — но и путать их молча больше нельзя.
Храповик: ``spa_core/tests/test_adapter_registry_single_name.py``.

Stdlib only — no third-party imports.  Never write to execution or monitoring
domain from this module (read-only / advisory).

Usage:
    from spa_core.adapters.registry import ADAPTER_METADATA, get_adapter

    # Get all T1 adapters
    t1 = [a for a in ADAPTER_METADATA.values() if a["tier"] == "T1"]

    # Get adapter instance
    adapter = get_adapter("aave_usdc")
    print(adapter.current_apy())

    # Summary stats
    summary = registry_summary()
    # -> {"total": N, "t1_count": X, "t2_count": Y, "research_only_count": Z}
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class WithdrawnAdapterError(RuntimeError):
    """Адаптер выведен решением владельца и не может быть инстанцирован.

    Отдельный класс, а не ``KeyError``: «ключа нет» и «ключ выведен» — разные
    факты, и вызывающий вправе их различать.
    """

# ---------------------------------------------------------------------------
# Central registry  {adapter_id: metadata_dict}
# ---------------------------------------------------------------------------

ADAPTER_METADATA: Dict[str, Dict[str, Any]] = {
    # ------------------------------------------------------------------
    # T1 — Production adapters (CLEAN data, live trading eligible)
    # ------------------------------------------------------------------
    "aave_usdc": {
        "module": "spa_core.adapters.aave_v3",
        "class": "AaveV3Adapter",
        "tier": "T1",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 3.5,
    },
    "compound_usdc": {
        "module": "spa_core.adapters.compound_v3_adapter",
        "class": "CompoundV3Adapter",
        "tier": "T1",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 4.8,
    },
    "morpho_steakhouse": {
        "module": "spa_core.adapters.morpho_steakhouse_adapter",
        "class": "MorphoSteakhouseAdapter",
        "tier": "T1",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 6.5,
    },
    "aave_arbitrum": {
        "module": "spa_core.adapters.aave_arbitrum_adapter",
        "class": "AaveArbitrumAdapter",
        "tier": "T1",
        "research_only": False,
        "chain": "Arbitrum",
        "asset": "USDC",
        "fallback_apy": 4.6,
    },
    "spark_susds": {
        "module": "spa_core.adapters.spark_susds_adapter",
        "class": "SparkSusdsAdapter",
        "tier": "T1",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "sDAI",
        "fallback_apy": 5.5,
    },
    "aave_optimism": {
        "module": "spa_core.adapters.aave_v3_optimism_adapter",
        "class": "AaveV3OptimismAdapter",
        "tier": "T1",
        "research_only": False,
        "chain": "Optimism",
        "asset": "USDC",
        "fallback_apy": 4.0,
    },
    "aave_polygon": {
        "module": "spa_core.adapters.aave_v3_polygon_adapter",
        "class": "AaveV3PolygonAdapter",
        "tier": "T1",
        "research_only": False,
        "chain": "Polygon",
        "asset": "USDC.e",
        "fallback_apy": 4.2,
    },
    # ------------------------------------------------------------------
    # T2 — Active yield adapters (research-tracked, not yet live-trading)
    # ------------------------------------------------------------------
    "morpho_blue": {
        "module": "spa_core.adapters.morpho_blue",
        "class": "MorphoBlueAdapter",
        "tier": "T2",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 5.0,
    },
    "yearn_v3": {
        "module": "spa_core.adapters.yearn_v3",
        "class": "YearnV3Adapter",
        "tier": "T2",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 4.0,
    },
    "euler_v2": {
        "module": "spa_core.adapters.euler_v2",
        "class": "EulerV2Adapter",
        "tier": "T2",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 4.5,
    },
    "maple": {
        "module": "spa_core.adapters.maple",
        "class": "MapleAdapter",
        "tier": "T2",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 7.0,
    },
    "fluid_fusdc": {
        "module": "spa_core.adapters.fluid_fusdc_adapter",
        "class": "FluidFUSDCAdapter",
        "tier": "T2",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 5.5,
    },
    "wusdm": {
        "module": "spa_core.adapters.wusdm_adapter",
        "class": "WusdmAdapter",
        "tier": "T2",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "wUSDM",
        "fallback_apy": 5.0,
    },
    "sdai": {
        "module": "spa_core.adapters.sdai_adapter",
        "class": "SdaiAdapter",
        "tier": "T2",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "sDAI",
        "fallback_apy": 4.8,
    },
    # ------------------------------------------------------------------
    # T2 — Research adapters (data being sourced, research_only=True)
    # ------------------------------------------------------------------
    "gmx_btc_perp": {
        "module": "spa_core.adapters.gmx_research",
        "class": "GMXResearchAdapter",
        "tier": "T2",
        "research_only": True,
        "chain": "Arbitrum",
        "asset": "BTC-USD",
        "fallback_apy": 15.0,
    },
    "gold_proxy": {
        "module": "spa_core.adapters.gold_proxy_research",
        "class": "GoldProxyResearchAdapter",
        "tier": "T2",
        "research_only": True,
        "chain": "Ethereum",
        "asset": "PAXG",
        "fallback_apy": 8.0,
    },
    "rwa_conc_lp": {
        "module": "spa_core.adapters.rwa_conc_lp_research",
        "class": "RWAConcLPResearchAdapter",
        "tier": "T2",
        "research_only": True,
        "chain": "Ethereum",
        "asset": "OUSG-USDC",
        "fallback_apy": 6.5,
    },
    # ------------------------------------------------------------------
    # T2 — MP-1547: Fluid Protocol USDC/USDT + Notional V3 (research-only)
    # ------------------------------------------------------------------
    "fluid_usdc": {
        "module": "spa_core.adapters.fluid_adapter",
        "class": "FluidUSDCAdapter",
        "tier": "T2",
        "research_only": True,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 5.5,
    },
    "fluid_usdt": {
        "module": "spa_core.adapters.fluid_adapter",
        "class": "FluidUSDTAdapter",
        "tier": "T2",
        "research_only": True,
        "chain": "Ethereum",
        "asset": "USDT",
        "fallback_apy": 5.4,
    },
    # ADR-070 п.18 (решение владельца 2026-08-07): `notional_v3` ВЫВЕДЕН до
    # отдельного разбора — продукт не ERC-4626, поэтому обвязка депозита/выхода
    # ему не подходит. «Вывести» ≠ «удалить»: запись остаётся видимой (иначе
    # причина исчезнет вместе с ключом), но помечена ``withdrawn`` — её нельзя
    # инстанцировать через ``get_adapter`` и она не попадает в ``list_eligible``.
    # Возврат — только новым ADR после разбора.
    "notional_v3": {
        "module": "spa_core.adapters.notional_v3_adapter",
        "class": "NotionalV3Adapter",
        "tier": "T2",
        "research_only": True,
        "chain": "Ethereum",
        "asset": "USDC",
        "fallback_apy": 5.0,
        "withdrawn": True,
        "withdrawn_adr": "ADR-070 п.18",
        "withdrawn_reason": (
            "не ERC-4626 — выведен до отдельного разбора (решение владельца 2026-08-07)"
        ),
    },
    # ------------------------------------------------------------------
    # T3 — Speculative / advisory-only adapters
    # ------------------------------------------------------------------
    "susde": {
        "module": "spa_core.adapters.susde_adapter",
        "class": "SusdeAdapter",
        "tier": "T3",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "sUSDe",
        "fallback_apy": 10.0,
    },
    "pendle": {
        "module": "spa_core.adapters.pendle_adapter",
        "class": "PendleAdapter",
        "tier": "T3",
        "research_only": False,
        "chain": "Ethereum",
        "asset": "PT-USDC",
        "fallback_apy": 12.0,
    },
}

# Required keys that every registry entry must contain.
_REQUIRED_KEYS = {"module", "class", "tier", "research_only", "chain", "asset", "fallback_apy"}
# Valid tier values.
_VALID_TIERS = {"T1", "T2", "T3"}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_adapter(adapter_id: str) -> Any:
    """Instantiate and return an adapter by *adapter_id*.

    Raises
    ------
    KeyError
        If *adapter_id* is not in ADAPTER_METADATA.
    ImportError
        If the adapter module cannot be imported.
    """
    if adapter_id not in ADAPTER_METADATA:
        raise KeyError(f"Adapter '{adapter_id}' not found in ADAPTER_METADATA")

    meta = ADAPTER_METADATA[adapter_id]
    # Fail-CLOSED: выведенный адаптер не инстанцируется. Отказ ИМЕНОВАННЫЙ —
    # «нет такого» и «выведен решением владельца» это разные факты, и молчаливый
    # KeyError доложил бы их одинаково.
    if meta.get("withdrawn") is True:
        raise WithdrawnAdapterError(
            f"Adapter '{adapter_id}' withdrawn ({meta.get('withdrawn_adr', 'ADR')}): "
            f"{meta.get('withdrawn_reason', 'no reason recorded')}"
        )
    module_path: str = meta["module"]
    class_name: str = meta["class"]

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls()


def list_by_tier(tier: str) -> List[str]:
    """Return adapter IDs whose tier matches *tier* (e.g. ``"T1"``)."""
    return [
        adapter_id
        for adapter_id, meta in ADAPTER_METADATA.items()
        if meta.get("tier") == tier
    ]


def is_withdrawn(adapter_id: str) -> bool:
    """True, если адаптер ВЫВЕДЕН (снят до отдельного разбора, ADR-070 п.18).

    Неизвестный ключ — не выведенный, а отсутствующий: возвращаем False, звать
    ``get_adapter`` всё равно нельзя (там KeyError).
    """
    meta = ADAPTER_METADATA.get(adapter_id)
    return bool(meta and meta.get("withdrawn") is True)


def list_withdrawn() -> List[str]:
    """Return adapter IDs marked ``withdrawn=True`` (видимые, но не используемые)."""
    return [aid for aid in ADAPTER_METADATA if is_withdrawn(aid)]


def list_eligible() -> List[str]:
    """Return adapter IDs that may be considered at all — без выведенных.

    Это НЕ набор кандидатов на аллокацию (тот собирается из канонического
    ``spa_core.adapters.ADAPTER_REGISTRY`` и проходит RiskPolicy) — это просто
    «что в этих метаданных ещё живое».
    """
    return [aid for aid in ADAPTER_METADATA if not is_withdrawn(aid)]


def list_research_only() -> List[str]:
    """Return adapter IDs where ``research_only=True``."""
    return [
        adapter_id
        for adapter_id, meta in ADAPTER_METADATA.items()
        if meta.get("research_only") is True
    ]


def registry_summary() -> Dict[str, int]:
    """Return a dict summarising the registry contents.

    Returns
    -------
    dict
        ``{total, t1_count, t2_count, t3_count, research_only_count}``
    """
    total = len(ADAPTER_METADATA)
    t1_count = len(list_by_tier("T1"))
    t2_count = len(list_by_tier("T2"))
    t3_count = len(list_by_tier("T3"))
    research_only_count = len(list_research_only())
    return {
        "total": total,
        "t1_count": t1_count,
        "t2_count": t2_count,
        "t3_count": t3_count,
        "research_only_count": research_only_count,
        # ADR-070 п.18: выведенные записи ОСТАЮТСЯ в total (они видимы), но
        # считаются отдельно — иначе «сколько адаптеров» и «сколько живых»
        # снова становятся одним числом с двумя разными ответами.
        "withdrawn_count": len(list_withdrawn()),
    }


def validate_registry() -> List[str]:
    """Validate every entry in ADAPTER_METADATA.

    Checks:
    * All required keys are present.
    * ``tier`` is one of the valid values.
    * ``research_only`` is a bool.
    * ``fallback_apy`` is numeric (int or float) and non-negative.
    * ``module`` and ``class`` are non-empty strings.

    Returns
    -------
    list
        Validation error strings; empty list means no errors found.
    """
    errors: List[str] = []

    for adapter_id, meta in ADAPTER_METADATA.items():
        prefix = f"[{adapter_id}]"

        # 1. Required keys
        missing = _REQUIRED_KEYS - set(meta.keys())
        if missing:
            errors.append(f"{prefix} missing required keys: {sorted(missing)}")
            continue  # skip further checks if keys are absent

        # 2. tier validity
        tier = meta["tier"]
        if tier not in _VALID_TIERS:
            errors.append(
                f"{prefix} invalid tier '{tier}'; expected one of {_VALID_TIERS}"
            )

        # 3. research_only must be bool
        if not isinstance(meta["research_only"], bool):
            errors.append(
                f"{prefix} 'research_only' must be bool, got {type(meta['research_only']).__name__}"
            )

        # 4. fallback_apy must be numeric and >= 0
        fap = meta["fallback_apy"]
        if not isinstance(fap, (int, float)):
            errors.append(
                f"{prefix} 'fallback_apy' must be numeric, got {type(fap).__name__}"
            )
        elif fap < 0:
            errors.append(f"{prefix} 'fallback_apy' must be >= 0, got {fap}")

        # 5. module and class must be non-empty strings
        for key in ("module", "class"):
            val = meta[key]
            if not isinstance(val, str) or not val.strip():
                errors.append(f"{prefix} '{key}' must be a non-empty string")

    return errors
