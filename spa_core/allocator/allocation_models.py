"""Модели аллокации капитала (SPA-V388 — Strategy Allocator).

Три детерминированные advisory-модели, которые превращают список адаптеров в
веса портфеля. Всё read-only / dry-run: ни один вызов не трогает execution и не
двигает реальные деньги — это только рекомендации.

Контракт каждой модели:
    вход  — ``list[dict]`` с ключами
            ``{"protocol": str, "apy_pct": float, "tvl_usd": float, "tier": str}``
    выход — ``dict[str, float]`` ``{protocol: weight_fraction}`` с суммой == 1.0
            (для непустого входа). На пустом входе возвращается ``{}``.

Кап'ы по тирам (T1 ≤ 40%, T2 ≤ 20%) применяются НЕ здесь, а в
:class:`spa_core.allocator.allocator.StrategyAllocator`, чтобы модели оставались
чистыми «сырыми» распределениями.
"""
from __future__ import annotations

_EPS = 1e-12


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    """Нормализует веса так, чтобы сумма == 1.0. Пустой/нулевой вход → как есть."""
    total = sum(weights.values())
    if total <= _EPS:
        return dict(weights)
    return {p: w / total for p, w in weights.items()}


def equal_weight(adapters: list[dict]) -> dict[str, float]:
    """Равные веса между всеми активными адаптерами.

    n адаптеров → каждый получает 1/n. Пустой список → ``{}``.
    """
    if not adapters:
        return {}
    n = len(adapters)
    share = 1.0 / n
    return {a["protocol"]: share for a in adapters}


def best_apy_weight(adapters: list[dict], top_n: int = 3) -> dict[str, float]:
    """Концентрация в top-N протоколах по APY, остальные — 0.

    Выбираются ``top_n`` адаптеров с наибольшим ``apy_pct`` и делятся поровну.
    Если адаптеров меньше ``top_n`` — берутся все. Пустой список → ``{}``.
    """
    if not adapters or top_n <= 0:
        return {}
    ranked = sorted(adapters, key=lambda a: a.get("apy_pct", 0.0), reverse=True)
    chosen = ranked[:top_n]
    share = 1.0 / len(chosen)
    return {a["protocol"]: share for a in chosen}


def risk_parity_weight(adapters: list[dict]) -> dict[str, float]:
    """Risk-parity: веса обратно пропорциональны риску.

    Если у адаптеров есть оценка волатильности APY (ключ ``apy_vol`` или
    ``volatility``) — вес ∝ 1/vol. Иначе используется TVL-proxy: больший TVL
    трактуется как меньший риск, поэтому вес ∝ TVL. Если TVL недоступен или
    у всех нулевой (типично для paper-данных) — честный fallback на равные веса,
    чтобы НИКОГДА не делить на ноль.
    """
    if not adapters:
        return {}

    def _vol(a: dict) -> float | None:
        for key in ("apy_vol", "volatility", "vol"):
            if key in a and a[key] is not None:
                return float(a[key])
        return None

    vols = [_vol(a) for a in adapters]
    if all(v is not None and v > _EPS for v in vols):
        inv = {a["protocol"]: 1.0 / v for a, v in zip(adapters, vols)}
        return _normalize(inv)

    # TVL-proxy: вес ∝ TVL (низкий TVL ⇒ выше риск ⇒ меньше вес).
    tvls = {a["protocol"]: max(float(a.get("tvl_usd", 0.0)), 0.0) for a in adapters}
    if sum(tvls.values()) > _EPS:
        return _normalize(tvls)

    # Fallback: ни волатильности, ни TVL — равные веса.
    return equal_weight(adapters)


# ─── Risk-aware модель (SPA-V406) ──────────────────────────────────────────────
# Подключает оценки risk scoring engine (data/risk_scores.json) к аллокации:
# вес ∝ apy_pct × grade_multiplier. Протоколы grade D исключаются (множитель 0),
# протоколы без оценки трактуются консервативно как B.

# Дефолтные множители по буквенной оценке риска.
GRADE_MULTIPLIERS_DEFAULT: dict[str, float] = {
    "A": 1.0,
    "B": 0.85,
    "C": 0.60,
    "D": 0.0,   # grade D → исключается из распределения
}

# Консервативный дефолт для протокола, отсутствующего в risk_scores.
DEFAULT_GRADE = "B"


def _normalize_protocol_key(name: str) -> str:
    """Приводит идентификатор протокола к канону для сопоставления.

    Снимает регистр и разделители, чтобы ``euler_v2`` (адаптер) совпал с
    ``euler-v2`` (slug в risk_scores). Возвращает строку без ``-``/``_``/пробелов.
    """
    return str(name).strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def risk_adjusted_breakdown(
    adapters: list[dict],
    risk_scores: dict[str, str],
    grade_multipliers: dict | None = None,
) -> dict:
    """Детальная risk-aware аллокация с разбивкой по протоколам.

    Возвращает dict::

        {
          "weights":               {protocol: weight_fraction},   # сумма == 1.0
          "per_protocol":          {protocol: {risk_grade, risk_multiplier,
                                               pre_risk_weight, post_risk_weight}},
          "excluded":              [protocol, ...],   # вес=0 из-за grade D
          "fallback_equal_weight": bool,              # True → все исключены/0 APY
        }

    Логика весов: ``raw = max(apy_pct, 0) × grade_multiplier``, нормализованные
    до 1.0. ``pre_risk_weight`` — apy-пропорциональный вес БЕЗ множителя (для
    сравнения «до/после риска»). Если суммарный risk-adjusted вес ≈ 0 (все grade
    D или нулевой APY) — честный fallback на :func:`equal_weight`.
    """
    if not adapters:
        return {
            "weights": {},
            "per_protocol": {},
            "excluded": [],
            "fallback_equal_weight": False,
        }

    mults = dict(GRADE_MULTIPLIERS_DEFAULT)
    if grade_multipliers:
        mults.update(
            {str(k).strip().upper(): float(v) for k, v in grade_multipliers.items()}
        )

    norm_scores = {
        _normalize_protocol_key(k): str(v).strip().upper()
        for k, v in (risk_scores or {}).items()
    }

    per_protocol: dict[str, dict] = {}
    raw_apy: dict[str, float] = {}
    raw_adj: dict[str, float] = {}
    excluded: list[str] = []

    for a in adapters:
        p = a["protocol"]
        grade = norm_scores.get(_normalize_protocol_key(p), DEFAULT_GRADE)
        if grade not in mults:                 # неизвестная буква → консервативно B
            grade = DEFAULT_GRADE
        mult = mults.get(grade, mults.get(DEFAULT_GRADE, 0.85))
        apy = max(float(a.get("apy_pct", 0.0)), 0.0)
        raw_apy[p] = apy
        raw_adj[p] = apy * mult
        per_protocol[p] = {"risk_grade": grade, "risk_multiplier": round(mult, 6)}
        if mult <= _EPS:
            excluded.append(p)

    total_adj = sum(raw_adj.values())
    fallback = False
    if total_adj <= _EPS:
        # все исключены (grade D) или нулевой APY → равные веса, без деления на ноль
        fallback = True
        weights = equal_weight(adapters)
    else:
        weights = {p: v / total_adj for p, v in raw_adj.items()}

    total_apy = sum(raw_apy.values())
    n = len(adapters)
    for p in per_protocol:
        pre = raw_apy[p] / total_apy if total_apy > _EPS else (1.0 / n)
        per_protocol[p]["pre_risk_weight"] = round(pre, 6)
        per_protocol[p]["post_risk_weight"] = round(weights.get(p, 0.0), 6)

    return {
        "weights": weights,
        "per_protocol": per_protocol,
        "excluded": excluded,
        "fallback_equal_weight": fallback,
    }


def risk_adjusted_weight(
    adapters: list[dict],
    risk_scores: dict[str, str],
    grade_multipliers: dict | None = None,
) -> dict[str, float]:
    """Risk-aware веса портфеля (см. :func:`risk_adjusted_breakdown`).

    Веса = ``apy_pct × grade_multiplier``, нормализованные до 1.0. Протоколы
    grade D исключаются (вес 0); протоколы без оценки трактуются как B. Если все
    исключены — fallback на равные веса. Контракт совпадает с прочими моделями:
    ``dict[str, float]`` с суммой == 1.0 (для непустого входа), ``{}`` на пустом.
    """
    return risk_adjusted_breakdown(adapters, risk_scores, grade_multipliers)["weights"]
