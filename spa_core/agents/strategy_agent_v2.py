"""Strategy Agent v2 — еженедельные рекомендации селектору (SPA-V423 / MP-306).

ВАЖНО: это НЕ легаси ``strategy_agent.py`` (4h-цикл multi-strategy backtest с
LLM-объяснениями — он не тронут). Это новый агент Phase 3 поверх agent
runtime v1 (MP-301): запускается ТОЛЬКО через
:meth:`AgentRuntime.run_agent` с письменным мандатом ``strategy``
(``spa_core/agent_runtime/mandates/strategy.json``) — бюджет, forbidden-list
и деградация применяются guard'ом, обходов нет.

Что делает (KANBAN MP-306)
==========================
* Триггер: **weekly** (нет ни одной записи в
  ``data/strategy_recommendations.json`` либо >=7 дней с последней) —
  :func:`should_run` чистая, ``now`` инжектируется.
* Контекст: читает РЕАЛЬНЫЕ файлы ``data/``
  (``strategy_shadow_comparison.json`` — shadow S0-S5 от comparator,
  ``equity_curve_daily.json`` — historical data,
  ``strategy_comparison.json`` — v1/v2 paper-стратегии); отсутствие или
  битость файла — честная пометка в ``context.missing``, НЕ падение.
* Детерминированное ядро: :func:`rank_shadow_strategies` — ранжирование
  S0-S5 по реальным метрикам (sortino первичен, sharpe tiebreak, pnl_pct,
  max_drawdown — зеркалит детерминированный
  ``strategies/strategy_selector.py``, включая гейт минимум 7 дней истории);
  :func:`kelly_sizing` — Kelly-рекомендация размера деплоя: при импортируемом
  ``spa_core/optimization/`` используется ``dynamic_kelly_fraction``
  (variance-Kelly (μ−r_f)/σ²), иначе честная упрощённая stdlib-формула —
  та же математика, без новых зависимостей.
* Результат: :class:`StrategyRecommendation` — РЕКОМЕНДАЦИЯ селектору
  (``recommendation`` ∈ {recommend_strategy, keep_current} + strategy +
  kelly-параметры + ranking + reasoning). Агент НИЧЕГО не меняет сам:
  ни активную стратегию (её меняет только детерминированный селектор
  ``strategy_selector.py``), ни policy, ни risk-limits, ни сделки —
  ``advisory_only=True`` в каждой записи.
* Опциональный LLM: инжектируемый callable (дефолт None), ответ валидируется
  по enum И по списку реально существующих eligible-стратегий; мусор/падение
  → детерминированный fallback. **Kelly-sizing всегда детерминированный** —
  LLM никогда не сайзит капитал.
* Журнал: append в ``data/strategy_recommendations.json`` (единственный
  allowed_output мандата) — атомарно (tmp + ``os.replace``), ротация
  последних :data:`RECOMMENDATIONS_MAX_ENTRIES` записей.

КОНСТИТУЦИЯ (SPA-BL-011 / llm_forbidden_lint): LLM SDK здесь НЕ
импортируются — LLM-клиент инжектируется снаружи как callable (дефолт None).
Pure stdlib + опциональный импорт spa_core/optimization (тоже stdlib),
без сети.

CLI (офлайн, без LLM)::

    python3 -m spa_core.agents.strategy_agent_v2 --check  # should_run + контекст
    python3 -m spa_core.agents.strategy_agent_v2 --run    # детерминированный прогон
    python3 -m spa_core.agents.strategy_agent_v2 --run --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from spa_core.agent_runtime import AgentRuntime
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.agents.strategy_agent_v2")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
DEFAULT_RECOMMENDATIONS_PATH = DEFAULT_DATA_DIR / "strategy_recommendations.json"

SCHEMA_VERSION = 1
AGENT_NAME = "strategy"

# Входные файлы контекста (реальные имена в data/ этого репо).
INPUT_FILES: Dict[str, str] = {
    "shadow": "strategy_shadow_comparison.json",      # S0-S5 от comparator
    "equity": "equity_curve_daily.json",              # historical data
    "strategy_comparison": "strategy_comparison.json",  # v1/v2 paper
}

# Enum рекомендаций селектору (KANBAN MP-306). Всё вне списка — невалидно.
VALID_RECOMMENDATIONS: Tuple[str, ...] = (
    "recommend_strategy",
    "keep_current",
)

TRIGGER_WEEKLY = "weekly"
TRIGGER_FORCED = "forced"

WEEKLY_PERIOD_DAYS = 7
#: Минимум дней истории shadow-стратегии, чтобы быть кандидатом —
#: зеркалит MIN_DAYS_FOR_CANDIDATE детерминированного strategy_selector.py.
MIN_DAYS_FOR_CANDIDATE = 7
#: Risk-free hurdle (%), та же константа, что в optimization/markowitz.py
#: и paper_trading/engine.py — все подсистемы согласны о пороге.
RISK_FREE_RATE_PCT = 5.0
TRADING_DAYS_PER_YEAR = 365  # DeFi yield начисляется ежедневно
RECOMMENDATIONS_MAX_ENTRIES = 500   # ротация strategy_recommendations.json
STATUS_NOT_DUE = "not_due"          # run_strategy: триггер не сработал
_MAX_REASONING_LEN = 4000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _num(value: Any) -> Optional[float]:
    """float или None: bool/NaN/inf/мусор — None (битые метрики не валят ядро)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# ─── Чистое аналитическое ядро ───────────────────────────────────────────────


def annualized_volatility_pp(daily_returns_pct: List[Any]) -> Optional[float]:
    """Годовая волатильность (п.п.) из ряда дневных доходностей (%). Pure.

    Меньше 2 валидных точек → None (честно: σ не оценить). Нечисловые
    точки пропускаются молча.
    """
    points = [p for p in (_num(x) for x in (daily_returns_pct or [])) if p is not None]
    if len(points) < 2:
        return None
    return statistics.stdev(points) * math.sqrt(TRADING_DAYS_PER_YEAR)


def rank_shadow_strategies(
    strategies: Any,
    min_days: int = MIN_DAYS_FOR_CANDIDATE,
) -> List[Dict[str, Any]]:
    """Ранжировать shadow-стратегии S0-S5 по реальным метрикам. Pure.

    Порядок (зеркалит детерминированный ``strategy_selector.py``):
    **sortino** (первичный, убыв.) → **sharpe** (tiebreak, убыв.) →
    **pnl_pct** (убыв.) → **max_drawdown** (возр.) → name (стабильность).
    None-метрика ранжируется хуже любой числовой. ``eligible=True`` только
    при ``days_running >= min_days`` (статистический гейт селектора —
    агент не рекомендует шум первых дней).
    """
    rows: List[Dict[str, Any]] = []
    for st in (strategies if isinstance(strategies, list) else []):
        if not isinstance(st, dict):
            continue
        name = st.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        days = st.get("days_running")
        days_int = days if isinstance(days, int) and not isinstance(days, bool) else 0
        rows.append({
            "name": name,
            "label": st.get("label"),
            "sortino": _num(st.get("sortino")),
            "sharpe": _num(st.get("sharpe")),
            "pnl_pct": _num(st.get("pnl_pct")),
            "max_drawdown": _num(st.get("max_drawdown")),
            "days_running": days_int,
            "eligible": days_int >= min_days,
        })

    def _key(r: Dict[str, Any]) -> Tuple[float, float, float, float, str]:
        sortino = r["sortino"] if r["sortino"] is not None else -math.inf
        sharpe = r["sharpe"] if r["sharpe"] is not None else -math.inf
        pnl = r["pnl_pct"] if r["pnl_pct"] is not None else -math.inf
        dd = r["max_drawdown"] if r["max_drawdown"] is not None else math.inf
        return (-sortino, -sharpe, -pnl, dd, r["name"])

    rows.sort(key=_key)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def _optimization_kelly() -> Optional[Callable[..., float]]:
    """Импортировать ``dynamic_kelly_fraction`` из spa_core/optimization/,
    если модуль существует и импортируем. Иначе None (stdlib-fallback)."""
    try:
        from spa_core.optimization.dynamic_kelly import dynamic_kelly_fraction
        return dynamic_kelly_fraction
    except Exception as exc:  # отсутствует/битый — честный fallback
        log.info("spa_core.optimization недоступен (%s) — stdlib Kelly", exc)
        return None


def _stdlib_kelly_fraction(
    apy_pct: float,
    volatility_pp: float,
    risk_free_rate_pct: float = RISK_FREE_RATE_PCT,
) -> float:
    """Честная упрощённая Kelly-формула на stdlib: f* = (μ − r_f) / σ².

    Та же continuous-Kelly математика, что в
    ``optimization/dynamic_kelly._variance_kelly_fraction`` (входы в %,
    переводятся в доли). Деградированные входы → 0.0 («не деплоить»).
    """
    if apy_pct <= 0 or volatility_pp <= 0:
        return 0.0
    excess_f = (apy_pct - risk_free_rate_pct) / 100.0
    if excess_f <= 0:
        return 0.0
    sigma_f = volatility_pp / 100.0
    return max(0.0, min(1.0, excess_f / (sigma_f * sigma_f)))


def kelly_sizing(
    apy_pct: Optional[float],
    volatility_pp: Optional[float],
    risk_free_rate_pct: float = RISK_FREE_RATE_PCT,
    kelly_fn: Optional[Callable[..., float]] = None,
) -> Dict[str, Any]:
    """Kelly-sizing рекомендация уровня стратегии. Детерминированная.

    Интеграция ``spa_core/optimization/`` (MP-306): если модуль импортируем —
    используется его ``dynamic_kelly_fraction`` (variance-ветка, tier/TVL
    не задействованы — у стратегии есть σ, а не протокольный TVL); иначе
    :func:`_stdlib_kelly_fraction` с той же математикой. Рекомендуемый
    деплой = **half-Kelly** (стандарт live-практики: −50% просадки за −25%
    роста). Нет данных (apy/σ None) → fraction 0.0 + честная note.
    """
    apy = _num(apy_pct)
    vol = _num(volatility_pp)
    result: Dict[str, Any] = {
        "apy_pct": apy,
        "volatility_pp": vol,
        "risk_free_rate_pct": risk_free_rate_pct,
        "kelly_fraction": 0.0,
        "half_kelly": 0.0,
        "recommended_deployment_pct": 0.0,
        "source": None,
        "note": "",
    }
    if apy is None or vol is None or vol <= 0:
        result["source"] = "insufficient_data"
        result["note"] = ("недостаточно данных для Kelly (нужны APY и >=2 дневных "
                          "доходностей) — рекомендация: не наращивать деплой")
        return result

    fn = kelly_fn if kelly_fn is not None else _optimization_kelly()
    if fn is not None:
        try:
            # variance-ветка dynamic_kelly_fraction: tier/tvl игнорируются
            # при volatility_pp>0 — передаём нейтральные значения.
            fraction = float(fn(apy, "T1", 1.0, volatility_pp=vol,
                                risk_free_rate_pct=risk_free_rate_pct))
            result["source"] = "spa_core.optimization.dynamic_kelly"
        except Exception as exc:  # битая интеграция == отсутствующая
            log.warning("optimization kelly raised %s — stdlib fallback", exc)
            fraction = _stdlib_kelly_fraction(apy, vol, risk_free_rate_pct)
            result["source"] = "stdlib_fallback"
            result["note"] = f"optimization/ упал ({type(exc).__name__}) — stdlib-формула"
    else:
        fraction = _stdlib_kelly_fraction(apy, vol, risk_free_rate_pct)
        result["source"] = "stdlib_fallback"
        result["note"] = "spa_core/optimization недоступен — честная stdlib Kelly-формула"

    fraction = max(0.0, min(1.0, fraction))
    result["kelly_fraction"] = round(fraction, 6)
    result["half_kelly"] = round(fraction / 2.0, 6)
    result["recommended_deployment_pct"] = round(fraction / 2.0 * 100.0, 4)
    if fraction == 0.0 and not result["note"]:
        result["note"] = (f"APY {apy:.2f}% не превышает risk-free "
                          f"{risk_free_rate_pct:.2f}% с учётом σ — Kelly=0, "
                          "наращивание деплоя не рекомендуется")
    return result


def should_run(
    context: Dict[str, Any],
    recommendations: List[Dict[str, Any]],
    now: datetime,
) -> Tuple[bool, Optional[str]]:
    """Надо ли запускать Strategy Agent. Чистая функция, ``now`` инжектируется.

    Триггер **weekly**: нет ни одной записи в strategy_recommendations.json,
    битый ts последней записи, либо прошло >= 7 дней.
    """
    last_ts: Optional[datetime] = None
    if recommendations:
        raw_ts = recommendations[-1].get("ts") \
            if isinstance(recommendations[-1], dict) else None
        if isinstance(raw_ts, str):
            try:
                last_ts = datetime.fromisoformat(raw_ts)
            except ValueError:
                last_ts = None
        if last_ts is not None and last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)

    if last_ts is None:
        return True, TRIGGER_WEEKLY  # ни одной записи (или битый ts) — пора
    if now - last_ts >= timedelta(days=WEEKLY_PERIOD_DAYS):
        return True, TRIGGER_WEEKLY
    return False, None


# ─── Сбор контекста из data/ (read-only) ─────────────────────────────────────


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _shadow_summary(raw: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]]:
    """Сводка strategy_shadow_comparison.json → (summary, strategies, best)."""
    summary: Dict[str, Any] = {}
    strategies: List[Dict[str, Any]] = []
    best: Optional[str] = None
    if isinstance(raw, dict):
        summary["updated_at"] = raw.get("updated_at")
        summary["days_running"] = raw.get("days_running")
        best = raw.get("best_strategy") if isinstance(raw.get("best_strategy"), str) else None
        summary["best_strategy"] = best
        if isinstance(raw.get("strategies"), list):
            strategies = [s for s in raw["strategies"] if isinstance(s, dict)]
        summary["num_strategies"] = len(strategies)
    return summary, strategies, best


def _equity_summary(raw: Any) -> Tuple[Dict[str, Any], List[Any], Optional[float]]:
    """Сводка equity_curve_daily.json → (summary, daily_returns_pct, apy)."""
    summary: Dict[str, Any] = {}
    daily_returns: List[Any] = []
    apy: Optional[float] = None
    if isinstance(raw, dict):
        summary["generated_at"] = raw.get("generated_at")
        daily = raw.get("daily")
        if isinstance(daily, list):
            for row in daily:
                if not isinstance(row, dict):
                    continue
                daily_returns.append(row.get("daily_return_pct"))
                row_apy = _num(row.get("apy_today"))
                if row_apy is not None:
                    apy = row_apy  # последняя валидная точка
        summary["num_days"] = len(daily_returns)
        summary["last_apy_pct"] = apy
    return summary, daily_returns, apy


def _strategy_comparison_summary(raw: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    if isinstance(raw, dict):
        summary["generated_at"] = raw.get("generated_at")
        strategies = raw.get("strategies")
        if isinstance(strategies, dict):
            summary["strategies"] = {
                name: (st.get("total_return_pct") if isinstance(st, dict) else None)
                for name, st in strategies.items()
            }
    return summary


def gather_context(data_dir: Union[str, Path] = DEFAULT_DATA_DIR) -> Dict[str, Any]:
    """Собрать контекст Strategy Agent из РЕАЛЬНЫХ файлов data/. Read-only.

    Отсутствующий/битый файл → честная пометка в ``context["missing"]``,
    соответствующий вход — None, НЕ падение. Детерминированное ядро
    (:func:`rank_shadow_strategies` + :func:`kelly_sizing`) вычисляется
    прямо здесь — ranking и kelly входят в ``inputs_digest`` (sha256
    канонического JSON) и ``snapshot_id``.
    """
    root = Path(data_dir)
    inputs: Dict[str, Any] = {}
    missing: List[str] = []
    shadow_strategies: List[Dict[str, Any]] = []
    current_strategy: Optional[str] = None
    daily_returns: List[Any] = []
    apy_pct: Optional[float] = None

    for key, filename in INPUT_FILES.items():
        path = root / filename
        if not path.is_file():
            inputs[key] = None
            missing.append(f"{key}: файл {filename} не найден")
            continue
        try:
            raw = _load_json(path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            inputs[key] = None
            missing.append(f"{key}: {filename} не читается ({type(exc).__name__}: {exc})")
            continue
        if key == "shadow":
            inputs[key], shadow_strategies, current_strategy = _shadow_summary(raw)
        elif key == "equity":
            inputs[key], daily_returns, apy_pct = _equity_summary(raw)
        else:
            inputs[key] = _strategy_comparison_summary(raw)

    ranking = rank_shadow_strategies(shadow_strategies)
    volatility_pp = annualized_volatility_pp(daily_returns)
    kelly = kelly_sizing(apy_pct, volatility_pp)

    digest_payload = json.dumps(
        {"inputs": inputs, "missing": missing, "ranking": ranking,
         "kelly": kelly, "current_strategy": current_strategy},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()

    return {
        "generated_at": _utc_now().isoformat(),
        "data_dir": str(root),
        "inputs": inputs,
        "missing": missing,
        "ranking": ranking,
        "current_strategy": current_strategy,
        "kelly": kelly,
        "snapshot_id": f"snap-{digest[:12]}",
        "inputs_digest": digest[:16],
    }


# ─── Рекомендация ────────────────────────────────────────────────────────────


@dataclass
class StrategyRecommendation:
    """Одна рекомендация селектору — ровно то, что пишется в
    data/strategy_recommendations.json. ADVISORY: активную стратегию меняет
    только детерминированный селектор (strategy_selector.py)."""

    ts: str
    snapshot_id: str
    trigger: str
    recommendation: str    # ∈ VALID_RECOMMENDATIONS (валидируется в decide())
    strategy: Optional[str]            # кого рекомендуем (или текущая)
    kelly: Dict[str, Any] = field(default_factory=dict)  # детерминированный sizing
    ranking_top3: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    inputs_digest: str = ""
    degraded: bool = False  # True — рекомендация без LLM (детерминистика)
    advisory_only: bool = True  # агент НИЧЕГО не меняет сам

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return d


def _ranking_brief(ranking: List[Dict[str, Any]], limit: int = 3) -> str:
    parts = []
    for r in ranking[:limit]:
        parts.append(
            f"{r.get('rank')}. {r.get('name')} (sortino={r.get('sortino')}, "
            f"sharpe={r.get('sharpe')}, pnl={r.get('pnl_pct')}%, "
            f"days={r.get('days_running')}, eligible={r.get('eligible')})"
        )
    return "; ".join(parts) if parts else "нет данных по shadow-стратегиям"


def _deterministic_recommendation(
    context: Dict[str, Any], note: str = ""
) -> Tuple[str, Optional[str], str]:
    """Детерминированное ядро рекомендации (llm=None / fallback). Pure.

    Лидер рейтинга среди **eligible** (>=7 дней истории) отличается от
    текущей → recommend_strategy; совпадает либо eligible-кандидатов нет →
    keep_current. Возвращает (recommendation, strategy, reasoning).
    """
    prefix = "[degraded=true] " + (f"{note} " if note else "")
    ranking = [r for r in (context.get("ranking") or []) if isinstance(r, dict)]
    eligible = [r for r in ranking if r.get("eligible")]
    current = context.get("current_strategy")
    kelly = context.get("kelly") or {}
    deploy = kelly.get("recommended_deployment_pct")
    kelly_text = (f" Kelly-sizing (детерминированный, source={kelly.get('source')}): "
                  f"half-Kelly деплой {deploy}%.")
    extra = f" Отсутствуют входы: {'; '.join(context.get('missing', []))}." \
        if context.get("missing") else ""

    if not eligible:
        return "keep_current", current, (
            f"{prefix}Детерминированное ядро: ни одна shadow-стратегия не набрала "
            f"{MIN_DAYS_FOR_CANDIDATE} дней истории (гейт селектора) — рекомендация "
            f"keep_current, активную стратегию менять не на чем. "
            f"Рейтинг: {_ranking_brief(ranking)}.{kelly_text}{extra}"
        )
    top = eligible[0]
    if top.get("name") == current:
        return "keep_current", current, (
            f"{prefix}Детерминированное ядро: лидер рейтинга {top.get('name')} "
            f"совпадает с текущей ({current}) — keep_current. "
            f"Рейтинг: {_ranking_brief(ranking)}.{kelly_text}{extra}"
        )
    return "recommend_strategy", top.get("name"), (
        f"{prefix}Детерминированное ядро: {top.get('name')} обгоняет текущую "
        f"({current}) по sortino/sharpe при {top.get('days_running')} днях истории — "
        f"рекомендация селектору сменить стратегию (решение за детерминированным "
        f"селектором). Рейтинг: {_ranking_brief(ranking)}.{kelly_text}{extra}"
    )


def build_prompt(context: Dict[str, Any], trigger: str) -> str:
    """Промпт для инжектированного LLM-callable (текст, без SDK)."""
    return (
        "Ты — Strategy Agent DeFi yield-оптимизатора SPA. Триггер запуска: "
        f"{trigger}. Контекст (shadow S0-S5 ranking / equity / kelly):\n"
        + json.dumps(context, ensure_ascii=False, indent=2, default=str)
        + "\n\nВыбери РОВНО одну рекомендацию из "
        + json.dumps(list(VALID_RECOMMENDATIONS))
        + " и ответь СТРОГО JSON-объектом: "
        '{"recommendation": "<...>", "strategy": "<имя eligible-стратегии или null>", '
        '"reasoning": "<краткое обоснование>"}. '
        "Ты только советуешь селектору: активную стратегию меняет ТОЛЬКО "
        "детерминированный селектор; policy, risk-limits и транзакции вне "
        "твоего мандата. Kelly-sizing уже посчитан детерминированно — не меняй его."
    )


def _parse_llm_response(
    resp: Any, eligible_names: List[str]
) -> Optional[Tuple[str, Optional[str], str]]:
    """Распарсить и ПРОВАЛИДИРОВАТЬ ответ LLM. Невалидно → None (fallback).

    Валидация: ``recommendation`` ∈ enum; для recommend_strategy ``strategy``
    обязана быть в списке реально существующих eligible-стратегий (LLM не
    может порекомендовать выдуманную).
    """
    obj = resp
    if isinstance(resp, str):
        try:
            obj = json.loads(resp)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(obj, dict):
        return None
    recommendation = obj.get("recommendation")
    if recommendation not in VALID_RECOMMENDATIONS:
        return None
    strategy = obj.get("strategy")
    if recommendation == "recommend_strategy":
        if not isinstance(strategy, str) or strategy not in eligible_names:
            return None
    else:
        strategy = strategy if isinstance(strategy, str) else None
    reasoning = obj.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        reasoning = f"LLM выбрал {recommendation} (reasoning не предоставлен)"
    return recommendation, strategy, reasoning.strip()[:_MAX_REASONING_LEN]


def decide(
    context: Dict[str, Any],
    trigger: str,
    llm: Optional[Callable[..., Any]] = None,
    now_fn: Callable[[], datetime] = _utc_now,
) -> StrategyRecommendation:
    """Сформировать рекомендацию селектору по контексту.

    ``llm=None`` (офлайн/деградация) → детерминированное ядро с пометкой
    ``[degraded=true]``. С LLM — recommendation/strategy валидируются
    (:data:`VALID_RECOMMENDATIONS` + список eligible); исключение LLM или
    невалидный ответ → детерминированный fallback. Kelly-sizing ВСЕГДА
    детерминированный (из context, LLM его не трогает).
    """
    eligible_names = [
        r.get("name") for r in (context.get("ranking") or [])
        if isinstance(r, dict) and r.get("eligible") and isinstance(r.get("name"), str)
    ]
    degraded = True
    if llm is None:
        recommendation, strategy, reasoning = _deterministic_recommendation(context)
    else:
        try:
            resp = llm(build_prompt(context, trigger))
        except Exception as exc:  # битый клиент == отсутствующий клиент
            log.warning("strategy llm callable raised %s — deterministic fallback", exc)
            recommendation, strategy, reasoning = _deterministic_recommendation(
                context, note=f"(LLM упал: {type(exc).__name__} — fallback)"
            )
        else:
            parsed = _parse_llm_response(resp, eligible_names)
            if parsed is None:
                recommendation, strategy, reasoning = _deterministic_recommendation(
                    context, note="(ответ LLM не прошёл валидацию enum/eligible — fallback)"
                )
            else:
                recommendation, strategy, reasoning = parsed
                degraded = False
                if recommendation == "keep_current" and strategy is None:
                    strategy = context.get("current_strategy")

    ranking = [r for r in (context.get("ranking") or []) if isinstance(r, dict)]
    return StrategyRecommendation(
        ts=now_fn().isoformat(),
        snapshot_id=str(context.get("snapshot_id", "snap-unknown")),
        trigger=trigger,
        recommendation=recommendation,
        strategy=strategy,
        kelly=dict(context.get("kelly") or {}),
        ranking_top3=ranking[:3],
        reasoning=reasoning,
        inputs_digest=str(context.get("inputs_digest", "")),
        degraded=degraded,
        advisory_only=True,
    )


# ─── Журнал рекомендаций (атомарно, ротация) ─────────────────────────────────


def load_recommendations(
    path: Union[str, Path] = DEFAULT_RECOMMENDATIONS_PATH,
) -> List[Dict[str, Any]]:
    """Прочитать список рекомендаций. Битый/отсутствующий файл → []. Терпит
    и обёртку ``{"recommendations": [...]}``, и голый JSON-список."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if isinstance(raw, dict) and isinstance(raw.get("recommendations"), list):
        return [d for d in raw["recommendations"] if isinstance(d, dict)]
    if isinstance(raw, list):
        return [d for d in raw if isinstance(d, dict)]
    return []


def append_recommendation(
    recommendation: Dict[str, Any],
    path: Union[str, Path] = DEFAULT_RECOMMENDATIONS_PATH,
) -> List[Dict[str, Any]]:
    """Append рекомендации в журнал: атомарно (tmp+os.replace), ротация
    последних :data:`RECOMMENDATIONS_MAX_ENTRIES`. Возвращает итоговый список."""
    recommendations = load_recommendations(path)
    recommendations.append(recommendation)
    recommendations = recommendations[-RECOMMENDATIONS_MAX_ENTRIES:]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _utc_now().isoformat(),
        "max_entries": RECOMMENDATIONS_MAX_ENTRIES,
        "advisory_only": True,
        "recommendations": recommendations,
    }
    atomic_save(payload, str(path))
    return recommendations


# ─── Запуск ТОЛЬКО через AgentRuntime (мандат strategy) ──────────────────────


def run_strategy_agent(
    runtime: AgentRuntime,
    data_dir: Union[str, Path] = DEFAULT_DATA_DIR,
    recommendations_path: Union[str, Path] = DEFAULT_RECOMMENDATIONS_PATH,
    now_fn: Callable[[], datetime] = _utc_now,
    force: bool = False,
    tokens: int = 0,
) -> Dict[str, Any]:
    """Один цикл Strategy Agent через guard :meth:`AgentRuntime.run_agent`
    (мандат ``strategy``): бюджет/деградация/журнал runtime — БЕЗ обходов.

    Триггер не сработал и ``force=False`` → ``status=not_due``, агент не
    запускается и токены не списываются. Рекомендация пишется в
    ``recommendations_path`` (дефолт — единственный allowed_output мандата).
    """
    context = gather_context(data_dir)
    recommendations = load_recommendations(recommendations_path)
    due, trigger = should_run(context, recommendations, now=now_fn())
    if not due:
        if not force:
            return {
                "agent": AGENT_NAME,
                "status": STATUS_NOT_DUE,
                "result": None,
                "reason": "weekly-триггер не сработал (см. --force)",
                "trigger": None,
                "ts": now_fn().isoformat(),
            }
        trigger = TRIGGER_FORCED

    def _fn(llm: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
        recommendation = decide(context, trigger, llm=llm, now_fn=now_fn)
        append_recommendation(recommendation.to_dict(), recommendations_path)
        return recommendation.to_dict()

    result = runtime.run_agent(AGENT_NAME, _fn, tokens=tokens)
    result["trigger"] = trigger
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.agents.strategy_agent_v2",
        description="Strategy Agent v2 (MP-306): weekly ранжирование shadow "
                    "S0-S5 + Kelly-sizing → рекомендации селектору в "
                    "data/strategy_recommendations.json. Офлайн, без LLM.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="показать should_run и собранный контекст")
    mode.add_argument("--run", action="store_true",
                      help="офлайн-прогон (детерминистика, llm=None) через AgentRuntime")
    parser.add_argument("--force", action="store_true",
                        help="с --run: запустить, даже если триггер не сработал")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                        help="директория с входными файлами (default: data/)")
    parser.add_argument("--recommendations", default=str(DEFAULT_RECOMMENDATIONS_PATH),
                        help="путь журнала рекомендаций "
                             "(default: data/strategy_recommendations.json)")
    args = parser.parse_args(argv)

    if args.check:
        context = gather_context(args.data_dir)
        recommendations = load_recommendations(args.recommendations)
        due, trigger = should_run(context, recommendations, now=_utc_now())
        print(json.dumps(
            {"should_run": due, "trigger": trigger,
             "recommendations_logged": len(recommendations), "context": context},
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0

    # Офлайн-CLI: мандат strategy имеет degradation_mode=deterministic-only —
    # дефолтный runtime (llm=None, probe «недоступен») честно выполняет
    # детерминированное ядро через guard, токены не списываются.
    result = run_strategy_agent(
        AgentRuntime(),
        data_dir=args.data_dir,
        recommendations_path=args.recommendations,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
