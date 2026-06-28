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


# ─── Run "Yield Capture" WS1.2 — constrained yield OPTIMIZER ────────────────────
# A REAL constrained optimizer that MAXIMIZES risk-adjusted expected yield SUBJECT
# TO the EXISTING RiskPolicy caps — replacing the old `apy×grade → normalize →
# T1-first water-fill` heuristic whose remainder-fill structurally dumped unfilled
# capital into low-yield T1 anchors (a market-rate ~4.45% drag).
#
# METHOD (stdlib-only — NO scipy/numpy): a deterministic GREEDY KNAPSACK-UNDER-CAPS.
# This is the exact-optimal greedy for the LP "maximize Σ wᵢ·scoreᵢ s.t. 0 ≤ wᵢ ≤
# capᵢ, Σwᵢ ≤ (1 − cash_floor), Σ_{T2} wᵢ ≤ t2_total_cap, |funded| ≤ max_protocols":
# with a single linear objective and box + two budget constraints, filling the
# highest risk-adjusted-score protocol up to its per-protocol cap before moving to
# the next is provably optimal (fractional-knapsack greedy). Unlike the heuristic,
# the deployable budget is poured into the HIGHEST-score headroom — never anchored
# T1-first — so it never leaves yield on the table to satisfy a structural bias.
#
# OBJECTIVE (owner-tunable dial — `objective`):
#   * "max_yield"  (dial=1.0): scoreᵢ = riskadj_apyᵢ                 — pure yield.
#   * "min_variance"(dial=0.0): scoreᵢ = riskadj_apyᵢ − λ·varproxyᵢ — heavy variance
#                               penalty; prefers safer (higher-grade/lower-vol) pools.
#   * "balanced"   (dial=0.5, DEFAULT): a blend — captures yield while penalising
#                               variance, the sane go-live default.
# `objective` may also be a float in [0,1] (the raw dial). The variance proxy is a
# deterministic, stdlib function of the SAME inputs already on the adapter dict
# (risk grade + APY level — higher grade ⇒ lower variance; a missing explicit
# `apy_vol`/`volatility` falls back to a grade-derived proxy). No LLM, no new feed.
#
# Caps are NOT hardcoded here — they are PASSED IN from the allocator, which reads
# them from RiskConfig (policy.py, owner-gated v1.0). This model NEVER mutates a cap.

# Owner-tunable objective dials. The string aliases map to a blend coefficient
# `alpha` ∈ [0,1] where score = riskadj_apy − (1−alpha)·VARIANCE_LAMBDA·varproxy.
# alpha=1 → pure yield; alpha=0 → max variance penalty. DEFAULT = balanced (0.5).
OBJECTIVE_DIALS: dict[str, float] = {
    "max_yield": 1.0,
    "balanced": 0.5,
    "min_variance": 0.0,
}
DEFAULT_OBJECTIVE = "balanced"  # OWNER-TUNABLE: see CLAUDE.md / docs — flag for owner.

# Variance penalty scale (pct·pct units, applied to the variance proxy). Kept
# modest so a strictly-higher yielding, similar-risk pool still wins under
# "balanced"; only a meaningfully riskier pool is penalised out of the lead.
VARIANCE_LAMBDA = 0.5

# Grade → variance proxy (higher grade ⇒ lower assumed APY variance). Used only
# when an adapter carries no explicit apy_vol/volatility. Deterministic, stdlib.
_GRADE_VAR_PROXY: dict[str, float] = {"A": 0.5, "B": 1.0, "C": 2.0, "D": 4.0}


def _resolve_alpha(objective) -> float:
    """Resolve the owner dial to a blend coefficient alpha ∈ [0,1]. Fail-CLOSED."""
    if isinstance(objective, (int, float)) and not isinstance(objective, bool):
        a = float(objective)
        if a != a:  # NaN
            return OBJECTIVE_DIALS[DEFAULT_OBJECTIVE]
        return 0.0 if a < 0.0 else (1.0 if a > 1.0 else a)
    if isinstance(objective, str):
        return OBJECTIVE_DIALS.get(objective.strip().lower(), OBJECTIVE_DIALS[DEFAULT_OBJECTIVE])
    return OBJECTIVE_DIALS[DEFAULT_OBJECTIVE]


def _variance_proxy(adapter: dict, grade: str) -> float:
    """Deterministic per-adapter variance proxy (stdlib, no feed, no LLM).

    Prefers an explicit ``apy_vol``/``volatility`` if the feed carries one; else
    derives it from the risk grade. Non-finite/negative → conservative grade proxy.
    """
    for key in ("apy_vol", "volatility", "vol"):
        v = adapter.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            import math as _m
            if _m.isfinite(v) and v >= 0.0:
                return float(v)
    return _GRADE_VAR_PROXY.get(str(grade).strip().upper(), _GRADE_VAR_PROXY["B"])


def optimized_yield_breakdown(
    adapters: list[dict],
    risk_scores: dict[str, str],
    *,
    tier_caps: dict[str, float],
    t2_total_cap: float,
    cash_floor: float = 0.05,
    max_protocols: int = 8,
    objective=DEFAULT_OBJECTIVE,
    grade_multipliers: dict | None = None,
) -> dict:
    """Constrained yield optimizer (WS1.2) — greedy knapsack under RiskPolicy caps.

    MAXIMIZES Σ wᵢ·scoreᵢ where scoreᵢ is the owner-dialled risk-adjusted yield,
    SUBJECT TO: 0 ≤ wᵢ ≤ tier_cap(i); Σwᵢ ≤ 1 − cash_floor; Σ_{T2} wᵢ ≤ t2_total_cap;
    at most ``max_protocols`` funded (ALLOC-002). grade-D pools are excluded.

    Returns a dict mirroring :func:`risk_adjusted_breakdown` plus optimizer metadata::

        {"weights", "per_protocol", "excluded", "fallback_equal_weight",
         "objective", "alpha", "expected_riskadj_score", "funded"}

    The returned ``weights`` sum to ``min(deployable_budget, Σ caps of funded)`` —
    i.e. they MAY sum to < 1.0 (the honest cash remainder when caps bind). The
    allocator must therefore NOT run its T1-first ``_fill_remainder`` over this
    model's output — the greedy already poured the budget into the highest-score
    headroom, so any unfilled remainder is genuine, cap-bound cash, not a T1 drag.
    Caps still hold downstream (the allocator re-applies them idempotently).
    """
    empty = {
        "weights": {}, "per_protocol": {}, "excluded": [],
        "fallback_equal_weight": False, "objective": objective,
        "alpha": _resolve_alpha(objective), "expected_riskadj_score": 0.0, "funded": [],
    }
    if not adapters:
        return empty

    import math as _m

    alpha = _resolve_alpha(objective)
    mults = dict(GRADE_MULTIPLIERS_DEFAULT)
    if grade_multipliers:
        mults.update({str(k).strip().upper(): float(v) for k, v in grade_multipliers.items()})
    norm_scores = {
        _normalize_protocol_key(k): str(v).strip().upper()
        for k, v in (risk_scores or {}).items()
    }

    # 1. Build per-protocol risk-adjusted score + cap. grade-D (mult 0) excluded.
    per_protocol: dict[str, dict] = {}
    scored: list[tuple[str, float, float, bool]] = []  # (proto, score, cap, is_t2)
    excluded: list[str] = []
    for a in adapters:
        p = a["protocol"]
        grade = norm_scores.get(_normalize_protocol_key(p), DEFAULT_GRADE)
        if grade not in mults:
            grade = DEFAULT_GRADE
        mult = mults.get(grade, mults.get(DEFAULT_GRADE, 0.85))
        apy_raw = a.get("apy_pct", 0.0)
        # Fail-CLOSED: a non-finite / non-positive APY contributes ZERO score —
        # it can never win greedy priority (mirrors the live-feed band guard).
        apy = float(apy_raw) if isinstance(apy_raw, (int, float)) and not isinstance(apy_raw, bool) and _m.isfinite(apy_raw) else 0.0
        apy = max(apy, 0.0)
        riskadj = apy * mult
        varproxy = _variance_proxy(a, grade)
        score = riskadj - (1.0 - alpha) * VARIANCE_LAMBDA * varproxy
        cap = float(tier_caps.get(p, 0.0))
        is_t2 = str(a.get("tier", "T2")).upper() != "T1"
        per_protocol[p] = {
            "risk_grade": grade,
            "risk_multiplier": round(mult, 6),
            "riskadj_apy": round(riskadj, 6),
            "variance_proxy": round(varproxy, 6),
            "score": round(score, 6),
            "tier_cap": round(cap, 6),
        }
        if mult <= _EPS:
            excluded.append(p)
            continue
        # Only protocols with a POSITIVE score and POSITIVE cap can be funded —
        # a non-positive score (e.g. a low-yield pool the variance dial penalised
        # below 0) is never forced in; it stays cash. Fail-CLOSED.
        if score > _EPS and cap > _EPS:
            scored.append((p, score, cap, is_t2))

    if not scored:
        # All excluded / non-positive score → honest empty (allocator → cash).
        # NOT equal-weight: forcing yield-negative pools in would defeat the point.
        out = dict(empty)
        out["per_protocol"] = per_protocol
        out["excluded"] = excluded
        out["fallback_equal_weight"] = False
        return out

    # 2. GREEDY KNAPSACK: highest score first (deterministic tie-break on name),
    #    fill each up to its per-protocol cap, respecting the deployable budget,
    #    the T2-total cap, and the ALLOC-002 ≤ max_protocols funded count.
    scored.sort(key=lambda t: (-t[1], t[0]))
    deployable = max(0.0, 1.0 - max(0.0, cash_floor))
    weights: dict[str, float] = {}
    budget_left = deployable
    t2_left = max(0.0, float(t2_total_cap))
    funded: list[str] = []
    for proto, _score, cap, is_t2 in scored:
        if budget_left <= _EPS or len(funded) >= max_protocols:
            break
        room = min(cap, budget_left)
        if is_t2:
            room = min(room, t2_left)
        if room <= _EPS:
            continue
        weights[proto] = room
        budget_left -= room
        if is_t2:
            t2_left -= room
        funded.append(proto)

    # 3. Expected risk-adjusted score of the book (for A/B comparison / metadata).
    exp_score = sum(weights[p] * per_protocol[p]["riskadj_apy"] for p in weights)

    for p in per_protocol:
        per_protocol[p]["post_opt_weight"] = round(weights.get(p, 0.0), 6)

    return {
        "weights": weights,
        "per_protocol": per_protocol,
        "excluded": excluded,
        "fallback_equal_weight": False,
        "objective": objective,
        "alpha": alpha,
        "expected_riskadj_score": round(exp_score, 6),
        "funded": funded,
    }
