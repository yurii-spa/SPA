# LLM_FORBIDDEN
"""
SPA Mass Strategy Tournament v1.0
spa_core/backtesting/mass_tournament.py

Discovers every strategy file in spa_core/strategies/s*.py, extracts its
allocation vector, runs a full 4-year backtest (2022-2025) via
ProfessionalBacktest.run_strategy(), and builds a Sharpe-sorted leaderboard.

LLM_FORBIDDEN: no LLM calls. All logic is deterministic.

Constraints
-----------
* stdlib only — zero external dependencies
* Atomic writes: write to <path>.tmp then shutil.move
* Advisory / read-only — never imports execution/, feed_health/, or risk agents
* approved=False from RiskPolicy cannot be overridden anywhere here
"""
# LLM_FORBIDDEN

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.backtesting.professional_backtest import (
    ProfessionalBacktest,
    _load_bee_apy_history,
    _get_fallback_bee_data,
    _resolve_protocol_source,
)
from spa_core.strategies.mock_provenance import is_mock_fed, mock_provenance

_log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STRATEGIES_DIR = _PROJECT_ROOT / "spa_core" / "strategies"
_DATA_DIR = _PROJECT_ROOT / "data"

VERSION = "v1.0"

# ─────────────────────────────────────────────────────────────────────────────
# Protocol universe
# ─────────────────────────────────────────────────────────────────────────────

# Protocols that ProfessionalBacktest has APY history for. The higher-yield additions
# (2026-06-24) now have REAL DeFiLlama series in data/bee/defillama_apy_history.json, so
# they are wired through instead of being dropped — to honestly test whether any strategy
# can validate into the Balanced/Aggressive packages on real higher-yield data.
KNOWN_PROTOCOLS = frozenset({
    "aave_v3",
    "compound_v3",
    "morpho_steakhouse",
    "spark_susds",
    "maple",
    "euler_v2",
    "yearn_v3",
    # higher-yield, real-series protocols (keys match the new bee-cache keys)
    "ethena_susde",
    "fluid_usdc_eth",
    "maple_syrup_usdc",
    "morpho_bbq_usdc",
    "pendle_pt_susde",
    "aave_v3_arbitrum",
    "aave_v3_polygon",
})

# Map strategy-specific protocol keys → backtest engine keys.
# None means "drop this protocol" (contributes 0 % yield, not included in weights).
PROTOCOL_ALIAS: Dict[str, Optional[str]] = {
    # Variants of known protocols
    "morpho_blue":          "morpho_steakhouse",
    "morpho_blue_base":     "morpho_steakhouse",
    "morpho_base":          "morpho_steakhouse",
    "morpho":               "morpho_steakhouse",
    "sky_susds":            "spark_susds",
    "sky_dai":              "spark_susds",
    "sky":                  "spark_susds",
    # L2 aave now has its own REAL per-chain series → use it (not the ETH proxy).
    "aave_v3_arbitrum":     "aave_v3_arbitrum",
    "aave_v3_polygon":      "aave_v3_polygon",
    "aave_arbitrum":        "aave_v3_arbitrum",
    "aave_v3_base":         "aave_v3",   # base series ≈ eth-tracked; keep as aave_v3
    "aave_v3_optimism":     "aave_v3",
    "aave_base":            "aave_v3",
    "aave_mainnet":         "aave_v3",
    "aave_usdc":            "aave_v3",
    "aave":                 "aave_v3",
    "compound_usdc":        "compound_v3",
    "compound":             "compound_v3",
    # Fluid now has a REAL higher-yield series → wire it through (was proxied to euler).
    "fluid":                "fluid_usdc_eth",
    "fluid_adapter":        "fluid_usdc_eth",
    "fluid_fusdc":          "fluid_usdc_eth",
    "fluid_lending":        "fluid_usdc_eth",
    "moonwell_base":        "euler_v2",   # closest T2 lending proxy (no real series)
    "radiant_arbitrum":     "euler_v2",   # T2 lending proxy
    "yearn":                "yearn_v3",
    "maple_usdc":           "maple",
    # Ethena sUSDe + Pendle PT now have REAL series → wire through (were dropped).
    "ethena_susde":         "ethena_susde",
    "susde":                "ethena_susde",
    "susde_spot":           "ethena_susde",
    "pendle_pt":            "pendle_pt_susde",
    "pendle_pt_live":       "pendle_pt_susde",
    # Explicitly dropped (no reliable historical series / unhedged-leg / T3-SPEC).
    # pendle_yt is the leveraged-yield leg with no standalone safe series → still dropped.
    "cash":                 None,
    "pendle_yt":            None,
    "perp_short_hedge":     None,
    "aerodrome":            None,
    "aerodrome_base":       None,
    "velodrome":            None,
    "velodrome_optimism":   None,
    "gmx_glp":              None,
    "glp":                  None,
    "sushi_stable":         None,
    "crv":                  None,
    "cvx":                  None,
    "convex":               None,
    "curve":                None,
    "radiant":              None,
}

# Mock APY snapshot used when a strategy's get_allocation() needs live rates.
# Values in decimal (0.035 = 3.5 %).
MOCK_APY: Dict[str, float] = {
    "aave_v3":           0.035,
    "compound_v3":       0.052,
    "morpho_steakhouse": 0.058,
    "morpho_blue":       0.058,
    "spark_susds":       0.055,
    "sky_susds":         0.055,
    "maple":             0.068,
    "euler_v2":          0.062,
    "yearn_v3":          0.048,
    "pendle_pt":         0.072,
    "aave_v3_arbitrum":  0.046,
    "fluid":             0.062,
    "fluid_adapter":     0.062,
    # Higher-yield real-series protocols (must cover every KNOWN_PROTOCOLS key).
    "ethena_susde":      0.085,
    "fluid_usdc_eth":    0.062,
    "maple_syrup_usdc":  0.070,
    "morpho_bbq_usdc":   0.060,
    "pendle_pt_susde":   0.072,
    "aave_v3_polygon":   0.044,
}

INITIAL_CAPITAL = 100_000.0

# ─────────────────────────────────────────────────────────────────────────────
# Что считается ИЗМЕРЕННЫМ рядом доходности
# ─────────────────────────────────────────────────────────────────────────────
# Мок в АЛЛОКАЦИИ (MOCK_APY) и мок в РЯДЕ ДОХОДНОСТИ — два разных входа, и
# пометка первого не отвечает за второй. Замер 2026-08-18 на 63 строках: 7 строк
# помечены как mock-fed, а НЕ помеченными остались 30 строк, часть веса которых
# бэктест обслуживал НЕ наблюдением:
#   * ``modeled_proxy``      — встроенный смоделированный ряд (euler_v2, maple);
#   * ``defillama_fallback`` — литеральный снимок в коде (spa_core.bee);
#   * ``none``               — ряда нет вовсе ⇒ протокол молча даёт РОВНО 0 %
#     годовых (`professional_backtest._build_protocol_daily_apy`: `annual_clean =
#     0.0`), то есть успокаивающая константа вместо отказа.
# При этом весь файл штамповался одной оптимистичной меткой `data_source =
# defillama_pit_real` — «лучший из обслуживших», а не «тот, что обслужил ЭТУ
# строку». Поэтому мера — ПОСТРОЧНАЯ: доля веса, обслуженная наблюдением.
MEASURED_SERIES_SOURCES = frozenset({"defillama_pit_real", "defillama_real"})

# Files to skip (not actual strategy implementations)
_SKIP_FILES = frozenset({
    "strategy_registry.py",
    "strategy_selector.py",
    "strategy_config.py",
})

# Module name prefix for strategy imports
_MODULE_PREFIX = "spa_core.strategies"


# ─────────────────────────────────────────────────────────────────────────────
# Atomic write helper
# ─────────────────────────────────────────────────────────────────────────────

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + shutil.move)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    shutil.move(tmp, str(path))


def series_provenance(
    allocation: Dict[str, float],
    bee_data: Dict,
    fallback_bee: Dict,
) -> Dict[str, Any]:
    """Чем обслужен ряд доходности КАЖДОГО протокола этой строки рейтинга.

    Возвращает
    ----------
    ``{apy_series_sources, measured_series_weight_pct, unmeasured_protocols,
    unserved_protocols, series_tainted}``

    ``measured_series_weight_pct`` — доля веса книги, доходность которой пришла
    из наблюдения (``defillama_pit_real`` / ``defillama_real``). Всё остальное —
    смоделированный ряд, литеральный снимок в коде или молчаливый ноль.

    Ничего не подставляет и не «дотягивает» до 100 %: пустая аллокация даёт
    ``measured_series_weight_pct = 0.0`` и ``series_tainted = True``
    (fail-CLOSED — недоказанное не выглядит доказанным).
    """
    alloc = {k: float(v) for k, v in (allocation or {}).items()
             if isinstance(v, (int, float)) and v > 0}
    total = sum(alloc.values())
    by_source: Dict[str, float] = {}
    unmeasured: List[str] = []
    unserved: List[str] = []
    for proto, weight in alloc.items():
        src = _resolve_protocol_source(proto, bee_data or {}, fallback_bee or {})
        by_source[src] = by_source.get(src, 0.0) + weight
        if src not in MEASURED_SERIES_SOURCES:
            unmeasured.append(f"{proto}:{src}")
        if src == "none":
            unserved.append(proto)
    measured = sum(w for s, w in by_source.items() if s in MEASURED_SERIES_SOURCES)
    frac = (measured / total) if total > 0 else 0.0
    return {
        "apy_series_sources": {
            s: round(w / total, 6) if total > 0 else 0.0
            for s, w in sorted(by_source.items())
        },
        "measured_series_weight_pct": round(100.0 * frac, 4),
        "unmeasured_protocols": sorted(unmeasured),
        "unserved_protocols": sorted(unserved),
        # Строгий порог: доверяем строке, только если ВЕСЬ её вес — наблюдение.
        "series_tainted": frac < 0.999999,
    }


def return_metrics_refusal(series_prov: Dict[str, Any]) -> Optional[str]:
    """Причина отказа от метрик доходности этой строки, либо ``None``.

    ОДНО место, где живёт правило «отсутствие ряда ≠ ноль». Отказ наступает
    ровно тогда, когда у какого-то протокола книги ряда доходности НЕТ ВОВСЕ
    (``_resolve_protocol_source`` → ``"none"``): бэктест оценил бы такой протокол
    в 0 % годовых (`professional_backtest._build_protocol_daily_apy`:
    ``annual_clean = 0.0``), а «ноль-по-незнанию» доходностью не является.

    Смоделированный ряд и литеральный снимок (`modeled_proxy`,
    `defillama_fallback`) под отказ НЕ подпадают — там ряд есть, и он не ноль;
    такая строка, как и раньше, помечена ``series_tainted`` и не попадает в
    ``trusted_leaderboard``. Третьей копии правила «что считается измеренным»
    здесь не заводится: вход — готовый результат :func:`series_provenance`.
    """
    missing = sorted((series_prov or {}).get("unserved_protocols") or [])
    if not missing:
        return None
    return "apy_series_missing:" + ",".join(missing)


# ─────────────────────────────────────────────────────────────────────────────
# MassTournament
# ─────────────────────────────────────────────────────────────────────────────

class MassTournament:
    """
    Discovers all strategy files, extracts allocation vectors, runs each
    through ProfessionalBacktest, and builds a Sharpe-sorted leaderboard.

    Usage
    -----
    mt = MassTournament()
    result = mt.run()      # returns dict; also saves data/mass_tournament_results.json
    """

    def __init__(
        self,
        strategies_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        add_noise: bool = True,
    ) -> None:
        self._strategies_dir = Path(strategies_dir) if strategies_dir else _STRATEGIES_DIR
        self._data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self._add_noise = add_noise
        self._backtest = ProfessionalBacktest(
            data_dir=self._data_dir,
            add_noise=add_noise,
        )
        # Провенанс подстановок по стратегиям: {module_path: mock_provenance-дикт}.
        # Заполняется в extract_allocation, читается в run() — чтобы подставленное
        # ехало в лидерборд С ИМЕНЕМ, а не растворялось в «стратегия заработала».
        self.last_strategy_provenance: Dict[str, Dict[str, Any]] = {}
        # Какие вызовы получили литеральный MOCK_APY (см. _label_fed_mock).
        self.last_mock_fed_labels: Dict[str, bool] = {}

    # ── Strategy file discovery ───────────────────────────────────────────────

    def discover_strategy_files(self) -> List[Path]:
        """Return all s*.py strategy files, excluding registry/config helpers."""
        return sorted([
            p for p in self._strategies_dir.glob("s*.py")
            if p.name not in _SKIP_FILES
        ])

    # ── Source-code analysis ──────────────────────────────────────────────────

    @staticmethod
    def detect_leverage(content: str) -> bool:
        """Return True if source code shows leverage / looping constructs."""
        patterns = [
            r'\bborrow_amount\s*[:=]',      # dataclass field or assignment
            r'\bLOOP_FACTOR\b',             # loop factor constant
            r'\bMAX_LOOPS\b',               # loop count constant
            r'\bloop_factor\b',             # runtime variable
            r'deposit.*borrow.*re.?deposit', # textual description
            r'recursive.*borrow',
        ]
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def detect_amm_lp(content: str) -> bool:
        """Return True if strategy is an AMM LP (not pure lending)."""
        patterns = [
            r'\b_is_lp_pool\b',
            r'\bimpermanent_loss\b',
            r'\badd_liquidity\b',
            r'\blp_stable\b',
        ]
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def find_primary_class(content: str) -> Optional[str]:
        """Return the best strategy class name found in *content*.

        Priority:
        1. Class that has ``def get_allocation`` in its body
        2. Class whose name ends with 'Strategy' or matches the S<number> pattern
        3. First public class that is not a config/mixin/helper
        """
        # Find all public class names
        all_classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
        skip_names = {"AdapterAPYMixin", "AdapterMixin"}
        config_suffixes = ("Config", "Mixin", "Helper", "Error", "Exception")
        public = [c for c in all_classes
                  if not c.startswith("_") and c not in skip_names]
        if not public:
            return None

        # Prefer the class that defines get_allocation
        # Parse class bodies (rough: find class X:...class Y: boundaries)
        class_body_re = re.compile(
            r"^class (\w+)[^\n]*:\n((?:(?!^class ).*\n)*)",
            re.MULTILINE,
        )
        for m in class_body_re.finditer(content):
            cls_name, body = m.group(1), m.group(2)
            if cls_name in public and "def get_allocation" in body:
                return cls_name
        # Also check get_target_weights
        for m in class_body_re.finditer(content):
            cls_name, body = m.group(1), m.group(2)
            if cls_name in public and "def get_target_weights" in body:
                return cls_name

        # Fall back: skip config/mixin classes, prefer strategy-named ones
        strategy_classes = [
            c for c in public
            if not any(c.endswith(s) for s in config_suffixes)
        ]
        if strategy_classes:
            return strategy_classes[0]

        return public[0] if public else None

    # ── Allocation normalization ──────────────────────────────────────────────

    @staticmethod
    def normalize_allocation(raw: Dict[str, Any]) -> Dict[str, float]:
        """
        Convert a raw strategy allocation dict to ``{known_protocol: weight}``.

        Handles two output formats:
        * **Dollars**: values ≫ 1.0 (e.g. 40000.0) — divides by INITIAL_CAPITAL
        * **Weights**: values ≤ 1.0 each — used directly

        Protocol aliases are applied; protocols with alias=None are dropped.
        Unknown protocols (no alias) are also dropped.
        Merged weights are then renormalised to sum ≤ 1.0.
        """
        if not raw or not isinstance(raw, dict):
            return {}

        # Detect dollar vs weight format
        pos_vals = [v for v in raw.values() if isinstance(v, (int, float)) and v > 0]
        if not pos_vals:
            return {}
        total_raw = sum(pos_vals)
        is_dollars = total_raw > 1.5  # dollar totals are always >> 1.5

        merged: Dict[str, float] = {}
        for proto, val in raw.items():
            if not isinstance(val, (int, float)) or val <= 0:
                continue
            w = (val / INITIAL_CAPITAL) if is_dollars else float(val)

            # Resolve alias
            if proto in PROTOCOL_ALIAS:
                mapped = PROTOCOL_ALIAS[proto]
            elif proto in KNOWN_PROTOCOLS:
                mapped = proto
            else:
                # Unknown protocol — skip
                continue

            if mapped is None:
                continue  # explicitly dropped

            merged[mapped] = merged.get(mapped, 0.0) + w

        if not merged:
            return {}

        # Cap total at 1.0 (renormalise if overcrowded due to aliasing)
        total_w = sum(merged.values())
        if total_w > 1.0:
            merged = {k: v / total_w for k, v in merged.items()}

        return {k: round(v, 8) for k, v in merged.items() if v > 0}

    # ── Allocation extraction ─────────────────────────────────────────────────

    def extract_allocation(
        self,
        module_path: str,
        class_name: str,
        content: str,
    ) -> Tuple[Optional[Dict[str, float]], str]:
        """
        Try to extract and normalise an allocation from a strategy class.

        Returns
        -------
        (normalised_weights, method_label) on success.
        (None, skip_reason) on failure.

        Attempts in order:
          1. get_allocation()  — no args
          2. get_allocation(capital_usd=CAPITAL)
          3. get_allocation(capital_usd=CAPITAL, apy_map=MOCK_APY)
          4. get_allocation(portfolio_value=CAPITAL, apy_data=MOCK_APY)
          5. get_target_weights()
          6. Module-level ALLOCATION constant
        """
        # Import module
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:
            return None, f"import_error: {exc}"

        module_alloc = getattr(mod, "ALLOCATION", None)

        # Get class
        cls = getattr(mod, class_name, None)
        if cls is None:
            if isinstance(module_alloc, dict):
                norm = self.normalize_allocation(module_alloc)
                return (norm, "ALLOCATION_constant") if norm else (None, "empty_after_normalize")
            return None, f"class_not_found:{class_name}"

        # Instantiate
        try:
            instance = cls()
            # Провенанс снимается СРАЗУ после конструктора: именно он грузит
            # адаптеры и именно там S23 молча садился на mock-7%.
            try:
                self.last_strategy_provenance[module_path] = mock_provenance(
                    instance, module=mod)
            except Exception as prov_exc:  # noqa: BLE001 — провенанс не роняет турнир
                self.last_strategy_provenance[module_path] = {
                    "strategy_id": class_name,
                    "provenance_error": str(prov_exc),
                    "fully_live": None,
                }
        except Exception as exc:
            if isinstance(module_alloc, dict):
                norm = self.normalize_allocation(module_alloc)
                return (norm, "ALLOCATION_constant_fallback") if norm else (None, "empty_after_normalize")
            return None, f"instantiation_error:{exc}"

        # Try get_target_weights (s12 pattern)
        if hasattr(instance, "get_target_weights") and not hasattr(instance, "get_allocation"):
            try:
                raw = instance.get_target_weights()
                norm = self.normalize_allocation(raw)
                return (norm, "get_target_weights") if norm else (None, "empty_after_normalize")
            except Exception:
                pass

        # Accept get_allocation() OR allocate() (s7x-style) as the allocation method —
        # recovers strategies that expose allocate() instead of get_allocation().
        _alloc_fn = getattr(instance, "get_allocation", None) or getattr(instance, "allocate", None)
        if _alloc_fn is None:
            if isinstance(module_alloc, dict):
                norm = self.normalize_allocation(module_alloc)
                return (norm, "ALLOCATION_constant") if norm else (None, "empty_after_normalize")
            return None, "no_get_allocation_method"

        # Try various call signatures
        attempts: List[Tuple[Dict, str]] = [
            ({}, "get_allocation()"),
            ({"capital_usd": INITIAL_CAPITAL}, "get_allocation(capital_usd)"),
            ({"capital_usd": INITIAL_CAPITAL, "apy_map": MOCK_APY},
             "get_allocation(capital_usd,apy_map)"),
            ({"apy_map": MOCK_APY}, "get_allocation(apy_map)"),
            ({"portfolio_value": INITIAL_CAPITAL, "apy_data": MOCK_APY},
             "get_allocation(portfolio_value,apy_data)"),
            ({"capital_usd": INITIAL_CAPITAL, "current_apys": MOCK_APY},
             "get_allocation(capital_usd,current_apys)"),
            # s11-style: mode string argument
            ({"mode": "bull"}, "get_allocation(mode=bull)"),
            # s44-style: regime string argument
            ({"regime": "normal"}, "get_allocation(regime=normal)"),
            ({"regime": "normal", "spiking_protocol": "aave_v3"},
             "get_allocation(regime,spiking_protocol)"),
            # allocate()-style signatures (s7x / research strategies)
            ({"apy_data": MOCK_APY}, "allocate(apy_data)"),
            ({"capital": INITIAL_CAPITAL, "live_apy": MOCK_APY}, "allocate(capital,live_apy)"),
            ({"capital": INITIAL_CAPITAL}, "allocate(capital)"),
        ]

        for kwargs, label in attempts:
            try:
                raw = _alloc_fn(**kwargs)
                if isinstance(raw, dict) and raw:
                    norm = self.normalize_allocation(raw)
                    if norm:
                        # ИДЕНТИЧНОСТЬ, а не разбор строки-метки: победивший вызов
                        # либо получил ТОТ САМЫЙ литеральный MOCK_APY, либо нет.
                        self.last_mock_fed_labels[module_path] = any(
                            v is MOCK_APY for v in kwargs.values())
                        return norm, label
            except TypeError:
                continue  # wrong signature — try next
            except Exception as exc:
                _log.debug("get_allocation attempt '%s' raised %s", label, exc)
                continue

        # Last resort: module ALLOCATION constant
        if isinstance(module_alloc, dict):
            norm = self.normalize_allocation(module_alloc)
            return (norm, "ALLOCATION_constant_last_resort") if norm else (None, "empty_after_normalize")

        return None, "all_call_attempts_failed"

    # ── Single-strategy backtest ──────────────────────────────────────────────

    def _run_one(
        self,
        strategy_id: str,
        allocation: Dict[str, float],
    ) -> Dict[str, Any]:
        """Run ProfessionalBacktest for one allocation. Returns metrics dict."""
        try:
            metrics = self._backtest.run_strategy(allocation, strategy_name=strategy_id)
            return metrics
        except Exception as exc:
            _log.warning("Backtest failed for %s: %s", strategy_id, exc)
            raise

    # ── Main run ─────────────────────────────────────────────────────────────

    def run(self, data_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Discover all strategies, run each through the backtest, build leaderboard.

        Parameters
        ----------
        data_dir:
            Override output directory (for testing).

        Returns
        -------
        Full result dict.  Also atomically saves
        ``data/mass_tournament_results.json``.
        """
        out_dir = Path(data_dir) if data_dir else self._data_dir
        out_path = out_dir / "mass_tournament_results.json"

        strategy_files = self.discover_strategy_files()
        _log.info("MassTournament: discovered %d strategy files", len(strategy_files))

        # Источники рядов доходности читаются ОДИН раз и используются построчно
        # (раньше читались только в конце — для одной общей оптимистичной метки).
        bee_data, _bee_tag = _load_bee_apy_history()
        fallback_bee = _get_fallback_bee_data()

        leaderboard: List[Dict[str, Any]] = []
        skip_reasons: Dict[str, str] = {}
        strategies_skipped = 0
        strategies_tested = 0

        for fpath in strategy_files:
            sid = fpath.stem  # e.g. "s46_safe_harbor"
            try:
                with open(fpath, encoding="utf-8") as fh:
                    content = fh.read()
            except Exception as exc:
                skip_reasons[sid] = f"read_error:{exc}"
                strategies_skipped += 1
                continue

            # ── Skip checks ───────────────────────────────────────────────────
            if self.detect_leverage(content):
                skip_reasons[sid] = "leverage_detected"
                strategies_skipped += 1
                _log.debug("Skipping %s: leverage detected", sid)
                continue

            if self.detect_amm_lp(content):
                skip_reasons[sid] = "amm_lp_strategy"
                strategies_skipped += 1
                _log.debug("Skipping %s: AMM LP strategy", sid)
                continue

            primary_class = self.find_primary_class(content)
            if primary_class is None:
                skip_reasons[sid] = "no_class_found"
                strategies_skipped += 1
                continue

            module_path = f"{_MODULE_PREFIX}.{sid}"

            # ── Extract allocation ────────────────────────────────────────────
            allocation, method_used = self.extract_allocation(
                module_path, primary_class, content
            )

            if allocation is None:
                skip_reasons[sid] = method_used  # method_used carries reason
                strategies_skipped += 1
                _log.debug("Skipping %s: %s", sid, method_used)
                continue

            if not allocation:
                skip_reasons[sid] = "empty_allocation"
                strategies_skipped += 1
                continue

            # ── Run backtest ──────────────────────────────────────────────────
            try:
                metrics = self._run_one(sid, allocation)
            except Exception as exc:
                skip_reasons[sid] = f"backtest_error:{exc}"
                strategies_skipped += 1
                continue

            strategies_tested += 1
            # ── Провенанс подстановок рядом со строкой рейтинга ────────────────
            # Два РАЗНЫХ вопроса, и один не заменяет другого:
            #   1. кормил ли турнир стратегию литеральным MOCK_APY (вход турнира);
            #   2. заявляет ли САМА стратегия подстановку внутри (S23-класс).
            prov = dict(self.last_strategy_provenance.get(module_path) or {})
            fed_mock = bool(self.last_mock_fed_labels.get(module_path, False))
            strategy_mock = is_mock_fed(prov)
            # 3-й, независимый вопрос: чем обслужен РЯД ДОХОДНОСТИ этой книги.
            sprov = series_provenance(allocation, bee_data or {}, fallback_bee or {})
            # ── ОТСУТСТВИЕ РЯДА ОБЯЗАНО БЫТЬ ОТЛИЧИМО ОТ НУЛЯ ─────────────────
            # Протокол, у которого ряда доходности НЕТ ВОВСЕ (`_resolve_protocol_source`
            # → "none"), молча оценивается бэктестом ровно в 0 % годовых
            # (`professional_backtest._build_protocol_daily_apy`: `annual_clean = 0.0`).
            # «Мы измерили ноль» и «мы не измеряли» — разные факты, и число,
            # полученное из их смеси, не имеет права занимать место в рейтинге.
            #
            # Замер 2026-08-19 своим прогоном (63 стратегии): 22 строки получали
            # место по такому числу, причём место ЗАНИЖЕННОЕ — выдуманный ноль
            # тянет вниз. Крайний случай `s14_arbitrum_radiant`: 80 % веса книги
            # (`aave_v3_arbitrum`) без ряда вообще, а строка стояла 44-й с
            # «3.03 % годовых». Пометка `series_tainted` (16–18.08) этот случай
            # НАЗЫВАЛА, но число оставляла — то есть отсутствие ряда по-прежнему
            # выглядело как измеренная доходность.
            #
            # Fail-CLOSED: метрики, выведенные из ряда, ОТКАЗАНЫ (``None``) с
            # названной причиной. Строка не удаляется из `leaderboard` —
            # провенанс обязан быть виден — но уезжает в хвост как `rank_unknown`
            # (`_rank_key` уже так устроен). Посчитанные значения сохраняются под
            # `zero_filled_metrics`: видно, ЧТО именно отказано, и видно, что это
            # не наблюдение. Правило «что считается измеренным рядом» здесь НЕ
            # переписывается — берётся у `series_provenance` (одно определение).
            #
            # Обслуженный смоделированным рядом / литеральным снимком
            # (`modeled_proxy`, `defillama_fallback`) под отказ НЕ попадает: там
            # ряд есть и он не ноль. Такая строка, как и раньше, названа
            # `series_tainted` и вне `trusted_leaderboard`.
            _refusal = return_metrics_refusal(sprov)
            series_missing = sorted(sprov.get("unserved_protocols") or [])
            _refused = _refusal is not None

            def _m(key: str) -> Optional[float]:
                """Значение метрики или ``None``, когда ряда под ней не существует."""
                return None if _refused else metrics[key]

            leaderboard.append({
                "id":                sid,
                # Вход: литеральный снимок MOCK_APY или собственные числа стратегии.
                "apy_input":         "mock_apy_snapshot" if fed_mock else "strategy_internal",
                "mock_apy_fed":      fed_mock,
                "strategy_declares_mock": strategy_mock,
                "mock_provenance":   prov,
                # Итог: строка НЕ доверяема для рейтинга, если в неё вошла подстановка.
                "mock_tainted":      fed_mock or strategy_mock,
                # ── Провенанс РЯДА ДОХОДНОСТИ (не путать с входом аллокации) ──
                **sprov,
                # ── Отказ вместо выдуманного нуля (см. комментарий выше) ──────
                "series_missing_protocols": sorted(series_missing),
                "return_metrics_refused":   _refused,
                "return_refusal_reason":    _refusal,
                # Что дал бы бэктест, если бы отсутствующий ряд считать нулём.
                # Хранится ПОД СВОИМ ИМЕНЕМ, чтобы никогда не быть прочитанным
                # как доходность (`zero_filled` — это и есть предупреждение).
                "zero_filled_metrics": (
                    {
                        "annual_return_pct": metrics["annualized_return_pct"],
                        "sharpe":            metrics["sharpe_ratio"],
                        "max_dd_pct":        metrics["max_drawdown_pct"],
                        "note": (
                            "Считано с ряда, которого нет: отсутствующий ряд "
                            "оценён в 0 % годовых. НЕ доходность."
                        ),
                    }
                    if _refused else None
                ),
                "class":             primary_class,
                "method_used":       method_used,
                "sharpe":            _m("sharpe_ratio"),
                "sortino":           _m("sortino_ratio"),
                "calmar":            _m("calmar_ratio"),
                "annual_return_pct": _m("annualized_return_pct"),
                "total_return_pct":  _m("total_return_pct"),
                "max_dd_pct":        _m("max_drawdown_pct"),
                "volatility_pct":    _m("annualized_volatility_pct"),
                "win_rate_pct":      _m("win_rate_pct"),
                "final_equity_usd":  _m("final_equity_usd"),
                "allocation":        allocation,
            })
            if _refused:
                _log.info(
                    "Tested %s: метрики ОТКАЗАНЫ — ряда нет у %s (0 %% был бы выдумкой)",
                    sid, ",".join(sorted(series_missing)),
                )
            else:
                _log.info(
                    "Tested %s: Sharpe=%.3f  APY=%.2f%%  MaxDD=%.3f%%",
                    sid,
                    metrics["sharpe_ratio"],
                    metrics["annualized_return_pct"],
                    metrics["max_drawdown_pct"],
                )

        # ── Sort by NET RETURN (OWNER DECISION 2026-06-27) ────────────────────
        # PRIMARY rank key is realized net-of-cost annual return (`annual_return_pct`,
        # already net of TX_COST_BPS in the backtest), NOT Sharpe. Sharpe is
        # DEGENERATE for locked-vol / fixed-rate stablecoin strategies (near-zero
        # vol → Sharpe explodes to 451M/1.2B artifacts), so a Sharpe-ranked board is
        # untrustworthy. Net return is the honest economic-quality metric. Sharpe is
        # demoted to a SECONDARY tiebreaker + a displayed-but-flagged metric.
        # A strategy with insufficient data (no finite net return) ranks LAST
        # (UNKNOWN), never a fabricated number.
        DEGENERATE_SHARPE_ABS = 100.0  # |Sharpe| > this → "n/a (locked-vol)" on display

        def _rank_key(x: Dict[str, Any]):
            napy = x.get("annual_return_pct")
            has_napy = isinstance(napy, (int, float)) and math.isfinite(napy)
            # Sort key: (has-net-return first, net return desc, sharpe desc tiebreak).
            # `not has_napy` is False (0) for valid rows so they sort ahead of UNKNOWNs.
            sh = x.get("sharpe")
            sh = sh if isinstance(sh, (int, float)) and math.isfinite(sh) else float("-inf")
            return (not has_napy, -(napy if has_napy else 0.0), -sh)

        leaderboard.sort(key=_rank_key)
        for i, entry in enumerate(leaderboard, 1):
            entry["rank"] = i
            # Explicit net-return rank metric (does NOT reorder — it IS the order now).
            entry["net_annual_return_pct"] = entry.get("annual_return_pct")
            # Flag a degenerate Sharpe so the display can show "n/a (locked-vol)"
            # instead of a meaningless 451M artifact. Sharpe value is kept verbatim
            # for provenance; the flag is advisory and never affects ranking.
            sh = entry.get("sharpe")
            sh_finite = isinstance(sh, (int, float)) and math.isfinite(sh)
            entry["sharpe_degenerate"] = (not sh_finite) or abs(sh) > DEGENERATE_SHARPE_ABS
            # Отказ по отсутствующему ряду и вырожденная Sharpe — РАЗНЫЕ причины
            # «нет числа», и подпись обязана их различать: «n/a (locked-vol)» на
            # строке, у которой ряда нет вовсе, читалась бы как свойство рынка.
            entry["sharpe_display"] = (
                "n/a (ряд не измерен)" if entry.get("return_metrics_refused")
                else "n/a (locked-vol)" if entry["sharpe_degenerate"]
                else round(float(sh), 4)
            )
            # UNKNOWN rank for a strategy with no finite net return (insufficient data).
            napy = entry.get("annual_return_pct")
            entry["rank_unknown"] = not (isinstance(napy, (int, float)) and math.isfinite(napy))

        # ── Доверяемый лидерборд: строки БЕЗ подстановок ───────────────────────
        # Карточка `agent-guard-no-silent-mock-in-tournament.md` п.3: стратегия с
        # подставленным числом не ранжируется как живая. Не удаляем её из
        # `leaderboard` (провенанс обязан быть виден), а выносим отдельный список
        # доверяемых — и помечаем каждую строку `trusted_for_ranking`.
        # Дополнение 2026-08-18: подстановка бывает не только на входе аллокации,
        # но и в РЯДЕ ДОХОДНОСТИ (`series_tainted`). Строка, часть книги которой
        # обслужена смоделированным рядом, литеральным снимком или молчаливым
        # нулём, ранжируется НЕ как измеренная — она остаётся в `leaderboard`
        # (провенанс обязан быть виден) с ИМЕНОВАННОЙ причиной, но не попадает в
        # `trusted_leaderboard`. Причины перечисляются, а не сворачиваются в bool.
        for entry in leaderboard:
            reasons: List[str] = []
            if entry.get("mock_apy_fed"):
                reasons.append("fed_literal_mock_apy_snapshot")
            if entry.get("strategy_declares_mock"):
                reasons.append("strategy_declares_substituted_source")
            # Отказ по отсутствующему ряду называется ОТДЕЛЬНО и ПЕРВЫМ: он
            # объясняет, ПОЧЕМУ числа нет, тогда как `no_finite_net_return` —
            # только факт его отсутствия.
            if entry.get("return_metrics_refused"):
                reasons.append(str(entry.get("return_refusal_reason")))
            if entry.get("rank_unknown"):
                reasons.append("no_finite_net_return")
            if entry.get("series_tainted"):
                named = entry.get("unmeasured_protocols") or [
                    "measured_weight_pct=%s" % entry.get("measured_series_weight_pct")
                ]
                reasons.append("apy_series_not_fully_measured:" + ",".join(named))
            entry["untrusted_reasons"] = reasons
            entry["trusted_for_ranking"] = not reasons
        trusted_leaderboard = [e for e in leaderboard if e["trusted_for_ranking"]]
        for i, entry in enumerate(trusted_leaderboard, 1):
            entry["trusted_rank"] = i
        mock_tainted_ids = sorted(
            str(e.get("id")) for e in leaderboard if e.get("mock_tainted")
        )
        series_tainted_ids = sorted(
            str(e.get("id")) for e in leaderboard if e.get("series_tainted")
        )
        return_refused_ids = sorted(
            str(e.get("id")) for e in leaderboard if e.get("return_metrics_refused")
        )
        # Какие именно протоколы не имеют ряда — по имени, а не числом строк.
        series_missing_protocols = sorted({
            p
            for e in leaderboard
            for p in (e.get("series_missing_protocols") or [])
        })

        top_5 = leaderboard[:5]
        bottom_5 = leaderboard[-5:] if len(leaderboard) >= 5 else leaderboard[:]

        # ── Honest provenance: which source ACTUALLY served each protocol ──────
        used_protocols: set = set()
        for entry in leaderboard:
            used_protocols.update((entry.get("allocation") or {}).keys())
        protocol_data_sources = {
            proto: _resolve_protocol_source(proto, bee_data or {}, fallback_bee or {})
            for proto in sorted(used_protocols)
        }
        _served = set(protocol_data_sources.values())
        if "defillama_pit_real" in _served:
            # Real point-in-time historical series (data/historical_apy/), date-aligned.
            data_source_label = "defillama_pit_real"
        elif "defillama_real" in _served:
            data_source_label = "defillama_real"
        elif "defillama_fallback" in _served:
            data_source_label = "defillama_fallback"
        elif "modeled_proxy" in _served:
            data_source_label = "modeled_proxy"
        else:
            data_source_label = "none"

        # ── HONESTY GATE: stamp trustworthy + data-source regime ───────────────
        # The Sharpe-ranked leaderboard is only a trustworthy LIVE ranking when the
        # underlying returns are NOT near-constant (degenerate). Stablecoin yield is
        # near-deterministic → Sharpe degenerate by asset class → NOT trustworthy.
        # Reuses the Tier-1 evaluator's degeneracy detector so producer/API/site agree.
        # Fail-CLOSED: any failure → trustworthy=False (never present mock as live).
        try:
            from spa_core.backtesting.tier1.evaluator import assess_tournament_trust
            trust = assess_tournament_trust({"leaderboard": leaderboard})
        except Exception as exc:  # pragma: no cover — defensive, fail-closed
            _log.warning("assess_tournament_trust failed: %s", exc)
            trust = {
                "trustworthy": False,
                "data_source": "unknown",
                "data_source_regime": "DEGENERATE_MOCK",
                "data_quality": {"status": "ERROR", "trustworthy": False, "reason": str(exc)},
                "reason": f"trust assessment failed ({exc}) — fail-closed",
            }

        meta: Dict[str, Any] = {
            "is_backtest": True,
            "data_source": data_source_label,
            # Honesty stamp: a Sharpe ranking on near-constant returns is NOT a live result.
            "trustworthy": trust["trustworthy"],
            "data_source_regime": trust["data_source_regime"],
            "trust_reason": trust["reason"],
            "data_quality": trust["data_quality"],
            "period": "2022-01-01 to 2025-12-31",
            # OWNER DECISION 2026-06-27: rank by realized net-of-cost annual return.
            # Sharpe demoted to a secondary/displayed metric (degenerate for
            # locked-vol books). `secondary_rank_metric` is the tiebreaker.
            "rank_metric": "net_annual_return_pct",
            "rank_metric_owner_gated": False,
            "secondary_rank_metric": "sharpe_ratio",
            "alt_rank_metric": "sharpe_ratio",
            "sharpe_degenerate_abs_threshold": 100.0,
            "protocol_data_sources": protocol_data_sources,
            # ── Подстановки НАЗВАНЫ (не запрещены) ─────────────────────────────
            # MOCK_APY — литеральный снимок в коде турнира, а не наблюдение.
            # Кто на нём стоял и кто заявил mock внутри себя — здесь по именам.
            "mock_apy_snapshot_is_literal": True,
            # Единицы снимка НАЗВАНЫ: он в ДОЛЯХ (0.035 = 3.5 %), тогда как часть
            # стратегий документирует вход как `apy_pct` и сравнивает с порогами в
            # процентах (`s74_rwa_yield`: `maple_apy > 7.0`). Расхождение единиц —
            # стократное; поэтому НИ ОДНА строка, получившая снимок, не считается
            # измеренной (см. `mock_apy_fed` → `untrusted_reasons`). Единицы здесь
            # не «чинятся» умножением: подгонка числа без источника — та же
            # подстановка, только незаметная.
            "mock_apy_snapshot_units": "decimal",
            "mock_apy_units_hazard": (
                "MOCK_APY is decimal (0.035 = 3.5%) while several strategies document "
                "apy_data/apy_map as apy_pct and compare against percent thresholds "
                "(e.g. maple_apy > 7.0). Any row fed the snapshot is excluded from "
                "trusted_leaderboard rather than rescaled."
            ),
            "mock_tainted_strategies": mock_tainted_ids,
            "mock_tainted_count":     len(mock_tainted_ids),
            # ── Ряд доходности: измеренное отделено от смоделированного ─────────
            "measured_series_sources": sorted(MEASURED_SERIES_SOURCES),
            "series_tainted_strategies": series_tainted_ids,
            "series_tainted_count":   len(series_tainted_ids),
            "unserved_protocols": sorted({
                p for e in leaderboard for p in (e.get("unserved_protocols") or [])
            }),
            # ── Отсутствие ряда ≠ ноль ────────────────────────────────────────
            # Строки, у которых хотя бы один протокол книги не имеет ряда вовсе:
            # метрики доходности им ОТКАЗАНЫ (None), место в рейтинге — хвост.
            "return_refused_strategies": return_refused_ids,
            "return_refused_count":      len(return_refused_ids),
            "series_missing_protocols":  series_missing_protocols,
            "return_refusal_note": (
                "Протокол без ряда доходности молча стоил бы 0 % годовых "
                "(professional_backtest._build_protocol_daily_apy: annual_clean = 0.0). "
                "Ноль-по-незнанию не доходность: такие строки получают "
                "annual_return_pct = null с причиной return_refusal_reason, а "
                "посчитанное значение лежит отдельно в zero_filled_metrics."
            ),
            # Честная оговорка: издержки в бэктесте — МОДЕЛЬ, не замер.
            "net_of_cost_basis": (
                "«net-of-cost» = минус TX_COST_BPS=5 bps на депонированный капитал "
                "при ежемесячном ребалансе (professional_backtest.py:69,640-643). Это "
                "ЛИТЕРАЛЬНАЯ КОНСТАНТА, а не замеренные газ/проскальзывание: "
                "измеренной стоимости переключения в репозитории нет."
            ),
            "measured_switching_cost_available": False,
            # `data_source` выше — ЛУЧШИЙ из обслуживших, а не общий для всех строк.
            "data_source_is_best_of_served": True,
            "data_source_note": (
                "meta.data_source is the BEST source that served ANY protocol, not a "
                "per-row guarantee. Per-row truth: leaderboard[].apy_series_sources / "
                "measured_series_weight_pct."
            ),
            "trusted_leaderboard_size": len(trusted_leaderboard),
            "sharpe_note": (
                "OWNER DECISION (2026-06-27): leaderboard is ranked by net-of-cost "
                "annual return (net_annual_return_pct), NOT Sharpe. Stablecoin Sharpe "
                "is degenerate by construction (near-zero vol → Sharpe explodes to "
                "millions/billions), so it is shown as a secondary metric and flagged "
                "'n/a (locked-vol)' per row when |Sharpe| > 100 (sharpe_degenerate). "
                "Sharpe is only a tiebreaker between equal net returns. Strategies "
                "with no finite net return rank last (rank_unknown=True)."
            ),
            "llm_forbidden": True,
        }

        result: Dict[str, Any] = {
            "generated_at":       datetime.now(timezone.utc).isoformat(),
            "version":            VERSION,
            "llm_forbidden":      True,
            # Top-level honesty flags (mirror meta) so API/site can gate without digging.
            "trustworthy":        trust["trustworthy"],
            "data_source":        data_source_label,
            "data_source_regime": trust["data_source_regime"],
            "meta":               meta,
            "simulation_period":  "2022-01-01 to 2025-12-31",
            "initial_capital_usd": INITIAL_CAPITAL,
            "strategies_tested":  strategies_tested,
            "strategies_skipped": strategies_skipped,
            "total_files_scanned": len(strategy_files),
            "skip_reasons":       skip_reasons,
            "leaderboard":        leaderboard,
            # Рейтинг БЕЗ подстановок. Пустой список — законный честный ответ
            # («доверяемых строк нет»), а не признак поломки.
            "trusted_leaderboard": trusted_leaderboard,
            "top_5":              top_5,
            "bottom_5":           bottom_5,
        }

        _atomic_write_json(out_path, result)
        _log.info(
            "MassTournament complete: %d tested, %d skipped → %s",
            strategies_tested, strategies_skipped, out_path,
        )
        return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run mass tournament from command line."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="SPA Mass Strategy Tournament — runs all strategies through backtest"
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Override output data directory (default: project data/)"
    )
    parser.add_argument(
        "--no-noise", action="store_true",
        help="Disable APY noise (deterministic but unrealistically smooth Sharpe)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Debug logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    mt = MassTournament(add_noise=not args.no_noise)
    result = mt.run(data_dir=args.data_dir)

    print(f"\n{'='*60}")
    print(f"Mass Tournament Results")
    print(f"{'='*60}")
    print(f"Strategies tested : {result['strategies_tested']}")
    print(f"Strategies skipped: {result['strategies_skipped']}")
    def _line(e: Dict[str, Any]) -> str:
        # Отказанная метрика печатается как ОТКАЗ С ПРИЧИНОЙ, а не как 0.00 —
        # ровно тот дефект, ради которого метрики и стали ``None``.
        if e.get("return_metrics_refused"):
            return (
                f"  #{e['rank']:2d}  {e['id']:<38s}  "
                f"ОТКАЗ: {e.get('return_refusal_reason')}"
            )
        return (
            f"  #{e['rank']:2d}  {e['id']:<38s}  "
            f"Sharpe={e['sharpe']:7.3f}  APY={e['annual_return_pct']:5.2f}%  "
            f"MaxDD={e['max_dd_pct']:.4f}%"
        )

    print(f"\nTop 5 by net-of-cost annual return:")
    for e in result["top_5"]:
        print(_line(e))
    print(f"\nBottom 5 by net-of-cost annual return:")
    for e in result["bottom_5"]:
        print(_line(e))
    print(f"\nSkipped strategies ({result['strategies_skipped']}):")
    for sid, reason in sorted(result["skip_reasons"].items()):
        print(f"  {sid:<38s}  {reason}")
    print(f"\nSaved → data/mass_tournament_results.json")


if __name__ == "__main__":
    main()
