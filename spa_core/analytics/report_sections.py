"""Секции пост-циклового аналитического отчёта (задача A4, поток 2 плана
docs/analytics_relocation_plan_2026-08-04.md).

Подключает 9 трекеров/отчётников слоя «что произошло / состояние книги»
СЕКЦИЯМИ в выход analytics_runner (MP-104, data/analytics_summary.json):

    adapter_health_scorecard, chain_fee_tracker, governance_token_value_tracker,
    lp_position_tracker, portfolio_stats, portfolio_volatility_tracker,
    defi_protocol_market_share_tracker, staking_reward_tracker,
    yield_attribution_tracker.

Принципы (те же, что у самого runner'а):
* СЕКЦИЯ, а не риск-скор: никакая секция не гейтит и не двигает капитал.
* НИКАКОЙ ФАБРИКАЦИИ. Если входы трекера не собираемы из data/ честно —
  секция ``{"status": "SKIPPED", "reason": ...}``, а не выдуманные значения.
  В частности:
    - chain_fee_tracker: в data/ нет per-chain gas-фида и цены ETH — константа
      $3000 (как в analytics_pipeline) была бы фабрикацией → SKIPPED;
    - defi_protocol_market_share_tracker: 30д-история TVL / объёмы / fees /
      пользователи недоступны → отдаём ТОЛЬКО текущие TVL-доли и HHI, поля
      share_change/stickiness/volume честно опускаются;
    - adapter_health_scorecard: фидов protocol_risk_score / slippage нет →
      компоненты safety+slippage помечаются UNCHECKED, композит — частичный
      (по доступным весам), grade/recommendation НЕ выводятся;
    - yield_attribution_tracker: позиции берутся ТОЛЬКО из
      current_positions.json (симулированный fallback трекера не используется).
* Fail-safe per секция: исключение внутри любого билдера → WARNING +
  ``{"status": "ERROR"}``; остальные секции и сам runner живут.
* Read-only по отношению к data/ (единственное исключение — ring-buffer лог
  StakingRewardTracker, и тот пишется только если в data/ появится файл
  staking_positions.json с реальными позициями).
* stdlib-only, LLM FORBIDDEN, без импортов execution-домена.
"""
from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("spa.analytics_runner.sections")

CURRENT_POSITIONS_FILE = "current_positions.json"
ADAPTER_STATUS_FILE = "adapter_status.json"
LP_POSITIONS_FILE = "lp_positions.json"
STAKING_POSITIONS_FILE = "staking_positions.json"
BASE_GAS_HISTORY_FILE = "base_gas_history.json"

# Метаданные-ключи верхнего уровня adapter_status.json — не адаптеры.
_STATUS_META_KEYS = frozenset({
    "schema_version", "generated_at", "generated_by", "live_apy_enabled",
    "live_count", "adapters", "execution_mode", "mev_protection",
})


# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------

def _skip(engine: str, reason: str) -> Dict[str, Any]:
    return {"status": "SKIPPED", "engine": engine, "reason": reason}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _num(v: Any) -> Optional[float]:
    """float или None; bool и NaN/inf — не числа."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _equity_bars(equity_doc: dict) -> List[dict]:
    bars = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
    return [b for b in (bars or []) if isinstance(b, dict)]


def _equity_curve(bars: List[dict]) -> List[dict]:
    """Бары → [{"date", "total_capital"}] для portfolio_stats (пропуская бары
    без числового equity/close_equity — как _extract_series в runner)."""
    out: List[dict] = []
    for b in bars:
        v = _num(b.get("equity", b.get("close_equity")))
        if v is None:
            continue
        out.append({"date": str(b.get("date", "")), "total_capital": v})
    return out


def _positions(data_dir: Path) -> Dict[str, float]:
    """{adapter_id: usd>0} из current_positions.json; {} если нет/пусто."""
    raw = _load_json(data_dir / CURRENT_POSITIONS_FILE)
    if not isinstance(raw, dict):
        return {}
    pos = raw.get("positions")
    if not isinstance(pos, dict):
        return {}
    out: Dict[str, float] = {}
    for k, v in pos.items():
        f = _num(v)
        if f is not None and f > 0:
            out[str(k)] = f
    return out


def _adapter_map(data_dir: Path) -> Dict[str, dict]:
    """{adapter_id: entry} из adapter_status.json.

    Живой файл держит адаптеры в ДВУХ местах: dict ``adapters`` (основной,
    текущая схема) и остаточные записи верхнего уровня с полем ``tier``.
    Метаданные пропускаются. Ничего не выдумываем: entry отдаётся как есть.
    """
    raw = _load_json(data_dir / ADAPTER_STATUS_FILE)
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, dict] = {}
    adapters = raw.get("adapters")
    if isinstance(adapters, dict):
        for k, v in adapters.items():
            if isinstance(v, dict):
                out[str(k)] = v
    elif isinstance(adapters, list):  # старая схема — список записей
        for item in adapters:
            if isinstance(item, dict):
                key = item.get("protocol_key") or item.get("adapter_id")
                if isinstance(key, str) and key and key not in out:
                    out[key] = item
    for k, v in raw.items():
        if k in _STATUS_META_KEYS or not isinstance(v, dict) or "tier" not in v:
            continue
        out.setdefault(str(k), v)
    return out


# ---------------------------------------------------------------------------
# Секции
# ---------------------------------------------------------------------------

def _section_portfolio_stats(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Расширенная статистика книги по equity-ряду (sortino/ulcer/VaR/ES...)."""
    from .portfolio_stats import portfolio_summary

    curve = _equity_curve(_equity_bars(equity_doc))
    if len(curve) < 2:
        return _skip("portfolio_stats",
                     "equity-ряд короче 2 точек — статистике не по чему считаться")
    section = {"status": "OK", "engine": "portfolio_stats",
               "first_date": curve[0]["date"], "last_date": curve[-1]["date"],
               "note": ("sortino_ratio движок считает при rf=4% годовых — "
                        "не сравнивать напрямую с sharpe из metrics (rf=0)")}
    section.update(portfolio_summary(curve))
    return section


def _section_portfolio_volatility(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Волатильность ДНЕВНОГО APY книги (apy_today из equity-ряда, проценты)."""
    from .portfolio_volatility_tracker import PortfolioVolatilityTracker

    # apy_today в барах цикла — ПРОЦЕНТЫ (3.28 = 3.28%); движок классифицирует
    # режим по ДОЛЯМ (0.005 = 0.5 п.п.) → делим на 100.
    readings = [a / 100.0 for a in
                (_num(b.get("apy_today")) for b in _equity_bars(equity_doc))
                if a is not None]
    if len(readings) < 2:
        return _skip("portfolio_volatility_tracker",
                     "в equity-ряде меньше 2 баров с apy_today — "
                     "волатильность APY не измерить")
    tracker = PortfolioVolatilityTracker(data_file=data_dir / "portfolio_volatility.json")
    for r in readings:
        tracker.add_reading(r)
    snap = tracker.compute_snapshot()  # только in-memory, save_snapshot НЕ зовём
    return {
        "status": "OK",
        "engine": "portfolio_volatility_tracker",
        "n_readings": len(readings),
        "mean_apy_pct": round(snap.mean_apy * 100.0, 4),
        "vol_7d_pp": round(snap.vol_7d * 100.0, 4),
        "vol_30d_pp": round(snap.vol_30d * 100.0, 4),
        "vol_90d_pp": round(snap.vol_90d * 100.0, 4),
        "regime": snap.regime,
        "trend": snap.trend,
        "cv": snap.cv,
        "units": "vol_*_pp — процентные пункты APY",
    }


def _section_yield_attribution(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Разбивка доходности по адаптерам/чейнам/тирам: позиции × APY."""
    from .yield_attribution_tracker import YieldAttributionTracker

    positions = _positions(data_dir)
    if not positions:
        return _skip("yield_attribution_tracker",
                     "нет позиций в current_positions.json — атрибуцию строить не по чему "
                     "(симулированные позиции трекера сознательно НЕ используются)")
    tracker = YieldAttributionTracker(data_path=str(data_dir))
    report = tracker.generate_report(positions=positions)  # позиции ЯВНО — без симуляции
    d = report.to_dict()
    apy_unknown = sorted(c.adapter_id for c in report.contributions if c.apy_pct <= 0)
    section: Dict[str, Any] = {"status": "OK", "engine": "yield_attribution_tracker"}
    section.update(d)
    section["apy_unknown"] = apy_unknown
    if apy_unknown:
        section["note"] = ("у этих позиций нет APY в adapter_status.json — их вклад "
                           "учтён как 0, effective_apy_pct занижен")
    return section


def _section_market_share(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Доли TVL внутри вселенной whitelisted-адаптеров SPA (только текущие)."""
    from .defi_protocol_market_share_tracker import DeFiProtocolMarketShareTracker

    amap = _adapter_map(data_dir)
    universe = [(aid, t) for aid, e in sorted(amap.items())
                for t in [_num(e.get("tvl_usd"))] if t is not None and t > 0]
    if len(universe) < 2:
        return _skip("defi_protocol_market_share_tracker",
                     "в adapter_status.json меньше 2 адаптеров с TVL — "
                     "доли рынка не имеют смысла")
    tracker = DeFiProtocolMarketShareTracker()
    raw = tracker.track(
        [{"name": aid, "category": "yield", "tvl_current_usd": tvl}
         for aid, tvl in universe],
        {"write_log": False},
    )
    # Честная выборка: 30д-истории TVL/объёмов/fees/пользователей в data/ нет,
    # поэтому share_change/volume/stickiness/fastest_* НЕ публикуем.
    protocols = [
        {
            "name": p["name"],
            "tvl_current_usd": p["tvl_current_usd"],
            "tvl_market_share_pct": p["tvl_market_share_pct"],
            "market_position": p["market_position"],
            "category_leader": "CATEGORY_LEADER" in p.get("flags", []),
        }
        for p in sorted(raw.get("protocols", []),
                        key=lambda x: x["tvl_market_share_pct"], reverse=True)
    ]
    summary = (raw.get("category_summary") or {}).get("yield", {})
    return {
        "status": "OK",
        "engine": "defi_protocol_market_share_tracker",
        "universe": "whitelisted-адаптеры SPA (adapter_status.json, tvl_usd)",
        "protocol_count": len(protocols),
        "total_tvl_usd": summary.get("total_category_tvl"),
        "hhi_concentration": summary.get("hhi_concentration"),
        "category_leader": summary.get("category_leader"),
        "protocols": protocols,
        "omitted_metrics": ("share_change_30d / volume / fees / stickiness — "
                            "нет 30д-истории TVL, объёмов и пользователей в data/"),
    }


def _section_adapter_health(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Частичный health-композит адаптеров: apy + stability + liquidity.

    Компоненты safety (protocol_risk_score) и slippage не имеют фидов в
    data/ → UNCHECKED; композит нормируется по ДОСТУПНЫМ весам, grade и
    recommendation движка сознательно не выводятся (это была бы оценка по
    65% входов, выданная за полную).
    """
    from . import _apy_series
    from .adapter_health_scorecard import WEIGHTS, AdapterHealthScorecard

    amap = _adapter_map(data_dir)
    if not amap:
        return _skip("adapter_health_scorecard",
                     "adapter_status.json пуст/нечитаем — скорить нечего")
    sc = AdapterHealthScorecard(data_file=data_dir / "adapter_health_scorecard.json")
    rows: List[Dict[str, Any]] = []
    for aid, e in sorted(amap.items()):
        if e.get("active") is False:
            continue
        apy_pct = _num(e.get("apy"))
        if apy_pct is None:
            apy_pct = _num(e.get("live_apy"))
        tvl = _num(e.get("tvl_usd"))
        if apy_pct is None and tvl is None:
            continue  # ни одного живого входа — строке не из чего родиться

        components: Dict[str, float] = {}
        unchecked: List[str] = ["safety", "slippage"]  # фидов нет — всегда UNCHECKED
        if apy_pct is not None:
            components["apy"] = round(sc._score_apy(apy_pct / 100.0), 2)
        else:
            unchecked.append("apy")
        if tvl is not None:
            components["liquidity"] = round(sc._score_liquidity(tvl), 2)
        else:
            unchecked.append("liquidity")

        series = _apy_series.get_series(aid, data_dir=data_dir) or []
        tail = [v for _, v in series[-7:]]
        vol_pp: Optional[float] = None
        if len(tail) >= 2:
            vol_pp = statistics.stdev(tail)  # проценты → п.п.
            components["stability"] = round(sc._score_stability(vol_pp / 100.0), 2)
        else:
            unchecked.append("stability")

        weight_covered = sum(WEIGHTS[c] for c in components)
        composite_partial = (
            round(sum(score * WEIGHTS[c] for c, score in components.items())
                  / weight_covered, 2)
            if weight_covered > 0 else None
        )
        rows.append({
            "adapter_id": aid,
            "apy_pct": apy_pct,
            "tvl_usd": tvl,
            "apy_vol_7d_pp": round(vol_pp, 4) if vol_pp is not None else None,
            "components": components,
            "composite_partial": composite_partial,
            "weight_coverage": round(weight_covered, 2),
            "unchecked_components": sorted(unchecked),
        })
    if not rows:
        return _skip("adapter_health_scorecard",
                     "ни у одного адаптера нет ни APY, ни TVL в adapter_status.json")
    rows.sort(key=lambda r: (r["composite_partial"] is not None,
                             r["composite_partial"] or 0.0), reverse=True)
    return {
        "status": "OK",
        "engine": "adapter_health_scorecard",
        "n_adapters": len(rows),
        "adapters": rows,
        "note": ("композит ЧАСТИЧНЫЙ (нормирован по доступным весам); "
                 "safety/slippage UNCHECKED — фидов protocol_risk_score и "
                 "slippage в data/ нет; grade/recommendation не выводятся"),
    }


def _section_lp_positions(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Сводка LP-позиций — если они вообще есть (paper-книга держит lending)."""
    from dataclasses import asdict

    from .lp_position_tracker import LPPositionTracker

    path = data_dir / LP_POSITIONS_FILE
    if not path.exists():
        return _skip("lp_position_tracker",
                     "LP-позиций нет (data/lp_positions.json отсутствует) — "
                     "книга paper-трека держит lending-позиции, не LP")
    tracker = LPPositionTracker(data_file=path)
    positions = tracker.load_positions()
    if not positions:
        return _skip("lp_position_tracker",
                     "data/lp_positions.json есть, но позиций в нём нет")
    section: Dict[str, Any] = {"status": "OK", "engine": "lp_position_tracker"}
    section.update(asdict(tracker.get_summary(positions)))
    return section


def _section_staking_rewards(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Стейкинг-награды — только если появится файл реальных стейкинг-позиций."""
    from .staking_reward_tracker import StakingRewardTracker

    path = data_dir / STAKING_POSITIONS_FILE
    raw = _load_json(path) if path.exists() else None
    entries = [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
    if not entries:
        return _skip("staking_reward_tracker",
                     "в data/ нет стейкинг-позиций с параметрами reward_rate/lock/"
                     "penalty (staking_positions.json отсутствует или пуст) — "
                     "lending-позиции книги стейкингом не являются")
    tracker = StakingRewardTracker(data_dir=str(data_dir))
    results, rejected = [], []
    for e in entries:
        try:
            results.append(tracker.track(e))
        except (ValueError, TypeError) as exc:
            rejected.append({"protocol": e.get("protocol", "unknown"), "error": str(exc)})
    if not results:
        return _skip("staking_reward_tracker",
                     f"все {len(entries)} записей staking_positions.json невалидны "
                     "для трекера")
    return {"status": "OK", "engine": "staking_reward_tracker",
            "positions": results, "rejected": rejected}


def _section_chain_fees(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    """Стоимость транзакций по чейнам — входов в data/ нет → честный SKIPPED."""
    has_base_gas = (data_dir / BASE_GAS_HISTORY_FILE).exists()
    reason = ("в data/ нет per-chain gas-фида и цены ETH — USD-стоимость "
              "транзакции без фабрикации не вычислить"
              + ("; base_gas_history.json покрывает только Base-gwei "
                 "и не содержит цену ETH" if has_base_gas else ""))
    return _skip("chain_fee_tracker", reason)


def _section_governance_tokens(data_dir: Path, equity_doc: dict) -> Dict[str, Any]:
    return _skip("governance_token_value_tracker",
                 "в data/ нет фида токеномики (цена токена, circulating supply, "
                 "эмиссия, выручка протокола) — оценка ценности governance-токенов "
                 "не собираема без фабрикации")


# Порядок фиксирован (детерминированный отчёт); имена = имена модулей плана.
_SECTION_BUILDERS: List[Tuple[str, Callable[[Path, dict], Dict[str, Any]]]] = [
    ("portfolio_stats", _section_portfolio_stats),
    ("portfolio_volatility_tracker", _section_portfolio_volatility),
    ("yield_attribution_tracker", _section_yield_attribution),
    ("defi_protocol_market_share_tracker", _section_market_share),
    ("adapter_health_scorecard", _section_adapter_health),
    ("lp_position_tracker", _section_lp_positions),
    ("staking_reward_tracker", _section_staking_rewards),
    ("chain_fee_tracker", _section_chain_fees),
    ("governance_token_value_tracker", _section_governance_tokens),
]

SECTION_NAMES: List[str] = [name for name, _ in _SECTION_BUILDERS]


def build_report_sections(data_dir: Path, equity_doc: dict) -> Dict[str, Dict[str, Any]]:
    """Построить все 9 секций. Провал одного трекера НЕ ломает остальные:
    исключение → WARNING + секция ``{"status": "ERROR", "error": ...}``."""
    data_dir = Path(data_dir)
    sections: Dict[str, Dict[str, Any]] = {}
    for name, builder in _SECTION_BUILDERS:
        try:
            sections[name] = builder(data_dir, equity_doc)
        except Exception as exc:  # noqa: BLE001 — fail-safe по образцу цикла
            log.warning("analytics section %r failed: %s", name, exc)
            sections[name] = {
                "status": "ERROR",
                "engine": name,
                "error": f"{type(exc).__name__}: {exc}",
            }
    return sections
