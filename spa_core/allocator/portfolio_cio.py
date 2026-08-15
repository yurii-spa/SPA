#!/usr/bin/env python3
"""Portfolio CIO — слой решения «двигать капитал или оставить» (ADVISORY).

Задание владельца 13.08 (`inbox-task-portfolio-cio-dynamic-capital-alloc`, §1…§52).
План — `docs/PORTFOLIO_CIO_PLAN.md`. Диагностика — `docs/PORTFOLIO_CIO_DIAGNOSIS.md`.

Почему это ТОНКИЙ слой, а не новый аллокатор
------------------------------------------------------------------------------
§3 задания запрещает начинать с нового агента и дублировать существующие механизмы.
Диагностика показала, что почти всё уже есть и работает:

* целевые веса под потолками — ``allocator.StrategyAllocator`` (greedy knapsack);
* стоимость перехода, окупаемость, гистерезис, cooldown, лимиты оборота —
  ``rebalance_economics.evaluate`` (ADR-060);
* устойчивость APY — ``analytics.apy_persistence_scorer.analyze``.

Не хватало ровно четырёх вещей, и этот модуль добавляет ТОЛЬКО их:

1. **Conservative Expected APY** (§11) — наблюдённый APY, взвешенный устойчивостью и
   уменьшенный на haircut неопределённости. Витринное число ≠ ожидаемое.
2. **Marginal APY** (§12) — 8 % в витрине не означает 8 % на наши $40k: свой же
   депозит разбавляет пул.
3. **Yield Gap** (§33) — сколько доходности теряет текущая раскладка против
   оптимальной policy-compliant.
4. **Третий вердикт DEFER** (§37, тесты 8–9) — «сделка хороша, но СЕЙЧАС её съедает
   газ». Сегодня экономика знает только ACT/HOLD, и «дорого сейчас» неотличимо от
   «не нужно вовсе»: первое обязано вернуться на пересчёт, второе — нет.

Инварианты, которые модуль соблюдает
------------------------------------------------------------------------------
* **Ничего не исполняет и не двигает капитал.** ``IS_ADVISORY = True``; вызов из
  money-path не добавлен намеренно (§50: ступени diagnosis → shadow → owner → auto).
* **RiskPolicy v1.0 — единственный hard-гейт** (инв. 1). Здесь нет ни одного порога
  политики: допустимость решена выше по потоку, тут только «стоит ли того».
* **Fail-CLOSED** (инв. 2): нечего наблюдать — ``None`` и названная причина, никогда
  не подставленное число. Отсутствие истории — тоже отказ, а не «сойдёт и так».
* **LLM запрещён** (инв. 3), только stdlib (инв. 4), атомарная запись (инв. 5).
* Детерминизм: один и тот же снимок даёт побитово один и тот же вывод (§37 тест 15).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.allocator.rebalance_economics import (
    Decision as EconomicsDecision,
    TriggerParams,
    evaluate as evaluate_economics,
)
from spa_core.utils.atomic import atomic_save

#: Слой advisory: не гейтит исполнение и не двигает капитал (инв. 9).
IS_ADVISORY = True

_EPS = 1e-9

#: Три возможных вердикта. KEEP — полноценное решение, а не отсутствие работы (§52).
KEEP = "KEEP"
REBALANCE = "REBALANCE"
DEFER = "DEFER"


@dataclass(frozen=True)
class CioParams:
    """Ручки CIO. НЕ пороги RiskPolicy — они не могут расширить ни один потолок.

    Отделены от :class:`TriggerParams` намеренно: те решают «оправдан ли переход»,
    эти — «каким числам мы вообще верим».
    """

    #: Минимум точек истории, ниже которого устойчивость не считается (отказ).
    min_history_points: int = 4
    #: Максимальный haircut неопределённости, доля наблюдённого APY.
    max_uncertainty_haircut: float = 0.50
    #: Haircut для APY, пришедшего не из живого наблюдения (stale-фид).
    stale_haircut: float = 1.00  # 1.0 ⇒ несвежее не приносит ожидаемого дохода вовсе
    #: Во сколько раз окупаемость может превысить потолок, оставаясь DEFER, а не KEEP.
    defer_payback_factor: float = 3.0


@dataclass
class ProtocolView:
    """Что CIO знает об одном протоколе после обработки наблюдений."""

    protocol: str
    displayed_apy_pct: Optional[float] = None
    conservative_apy_pct: Optional[float] = None
    marginal_apy_pct: Optional[float] = None
    persistence: Optional[float] = None
    haircut_pp: float = 0.0
    refusals: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CioDecision:
    """Вердикт CIO + все числа за ним. Сериализуется в артефакт целиком (§30)."""

    decision: str = KEEP
    reasons: List[str] = field(default_factory=list)
    current_expected_apy_pp: float = 0.0
    optimal_expected_apy_pp: float = 0.0
    yield_gap_pp: float = 0.0
    switching_cost_usd: float = 0.0
    payback_days: Optional[float] = None
    turnover_usd: float = 0.0
    legs: List[dict] = field(default_factory=list)
    views: Dict[str, dict] = field(default_factory=dict)
    economics: Dict[str, object] = field(default_factory=dict)
    refusals: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# §11 Conservative Expected APY
# ──────────────────────────────────────────────────────────────────────────────

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _clean(history: Sequence[float]) -> List[float]:
    return [float(x) for x in (history or [])
            if isinstance(x, (int, float)) and not isinstance(x, bool)
            and math.isfinite(float(x))]


def _excess_credit_share(xs: Sequence[float], current: float) -> float:
    """Какую долю НАДБАВКИ над базой мы соглашаемся засчитать (0…1).

    Два прозрачных сигнала, без непрозрачного ML (§10 запрещает его в v1):
    как часто верхний уровень вообще наблюдался, и насколько ряд стабилен
    (обратный коэффициент вариации).

    Почему шкалируется ИМЕННО надбавка, а не весь APY. Первая редакция множила
    на устойчивость всё число — и растущая ставка получала 1.16 вместо 8.0:
    доля «времени на текущем уровне» у монотонного роста всегда 1/N, поэтому
    улучшение штрафовалось как нестабильность. Базовая ставка не исчезает
    оттого, что рынок пошёл вверх; неуверены мы только в НАДБАВКЕ над ней.
    Дефект нашёлся мутацией собственного теста, а не в проде.
    """
    if not xs:
        return 0.0
    m = _mean(xs)
    if m <= _EPS:
        return 0.0
    seen_at_top = sum(1 for x in xs if x >= current - _EPS) / len(xs)
    stability = 1.0 / (1.0 + _stdev(xs) / m)
    return max(0.0, min(1.0, seen_at_top * stability))


def conservative_expected_apy(
    *,
    protocol: str,
    displayed_apy_pct: Optional[float],
    history: Optional[Sequence[float]] = None,
    apy_source: str = "live",
    params: Optional[CioParams] = None,
) -> ProtocolView:
    """Ожидаемый APY: наблюдённый × устойчивость − haircut неопределённости (§11).

    Fail-CLOSED в трёх местах, и все три — намеренно:

    * нет наблюдения (``None``) ⇒ отказ, не ноль и не литерал;
    * APY не из живого фида ⇒ ожидаемый доход 0 при ``stale_haircut = 1.0``.
      «Что не наблюдаем — того не заработали»: иначе непрозрачный пул защищал бы
      себя от перехода в наблюдаемый, то есть ровно наоборот;
    * истории меньше ``min_history_points`` ⇒ устойчивость НЕ измерена, отказ.
      Один замер не отличает уровень от спайка, а притвориться, что отличает, —
      это и есть тот класс ошибки, на котором систему уже ловили.
    """
    p = params or CioParams()
    view = ProtocolView(protocol=protocol, displayed_apy_pct=displayed_apy_pct)

    if displayed_apy_pct is None or not isinstance(displayed_apy_pct, (int, float)) \
            or isinstance(displayed_apy_pct, bool) or not math.isfinite(float(displayed_apy_pct)):
        view.refusals.append("apy_not_observed")
        return view
    displayed = float(displayed_apy_pct)
    if displayed <= 0:
        view.conservative_apy_pct = 0.0
        view.refusals.append("apy_non_positive")
        return view

    if str(apy_source).lower() != "live":
        view.refusals.append(f"apy_source_not_live:{apy_source}")
        view.conservative_apy_pct = round(displayed * (1.0 - p.stale_haircut), 6)
        return view

    xs = _clean(history)
    if len(xs) < p.min_history_points:
        view.refusals.append(
            "persistence_unmeasured:{}<{}".format(len(xs), p.min_history_points)
        )
        return view

    # §11: Expected Base APY + Expected Incentive APY × Persistence − Haircut.
    # Отдельного фида «сколько из ставки — стимулы» у нас нет, и выдумывать его
    # нельзя. Наблюдаемая замена: базой считается медиана ряда (уровень, который
    # рынок держал), надбавкой — превышение текущего над ней.
    base = _median(xs)
    excess = max(0.0, displayed - base)
    share = _excess_credit_share(xs, displayed)
    mean = _mean(xs)
    cv = _stdev(xs) / mean if mean > _EPS else 1.0
    view.haircut_pp = round(base * min(p.max_uncertainty_haircut, max(0.0, cv)), 6)
    credited = base + excess * share - view.haircut_pp
    view.conservative_apy_pct = round(credited, 6)
    # Публикуемая устойчивость = как часто ставка держалась на КРЕДИТУЕМОМ уровне.
    # Это единственная интерпретация, которую можно проверить по ряду, не гадая.
    view.persistence = round(sum(1 for x in xs if x >= credited - _EPS) / len(xs), 6)
    return view


# ──────────────────────────────────────────────────────────────────────────────
# §12 Marginal APY — наш собственный размер разбавляет пул
# ──────────────────────────────────────────────────────────────────────────────

def marginal_apy_pct(
    *,
    apy_pct: Optional[float],
    tvl_usd: Optional[float],
    size_usd: float,
    tvl_evidenced: bool = True,
) -> Tuple[Optional[float], Optional[str]]:
    """APY, который достанется нам ПОСЛЕ входа размером ``size_usd``.

    Модель разбавления — самая консервативная из честных: доход пула считается
    заданным, а наш депозит увеличивает знаменатель, поэтому
    ``apy_after = apy × TVL / (TVL + size)``. Это не претендует на точность
    кривой утилизации конкретного протокола; это нижняя граница, которая никогда
    не завышает ожидание.

    Возвращает ``(значение, причина_отказа)``. TVL не подтверждён живым
    наблюдением ⇒ отказ (ADR-053/064: литерал не является доказательством, а
    подставить $20M «чтобы посчиталось» — ровно запрещённое поведение).
    """
    if apy_pct is None or not math.isfinite(float(apy_pct)):
        return None, "apy_not_observed"
    if not tvl_evidenced:
        return None, "tvl_not_evidenced"
    if tvl_usd is None or not math.isfinite(float(tvl_usd)) or float(tvl_usd) <= 0:
        return None, "tvl_not_observed"
    size = max(0.0, float(size_usd))
    tvl = float(tvl_usd)
    return round(float(apy_pct) * tvl / (tvl + size), 6), None


# ──────────────────────────────────────────────────────────────────────────────
# §33 Yield Gap
# ──────────────────────────────────────────────────────────────────────────────

def blended_apy_pp(
    positions: Dict[str, float],
    apy_pct: Dict[str, Optional[float]],
    capital_usd: float,
) -> float:
    """Доходность книги в пунктах ОТ ВСЕГО КАПИТАЛА (кэш честно разбавляет).

    База — весь капитал, а не только размещённый: на базе «только размещённое»
    перевод простаивающего кэша в пул выглядел бы нулевым улучшением, то есть
    самое важное изменение не было бы видно вовсе.
    """
    if capital_usd <= 0:
        return 0.0
    total = 0.0
    for proto, usd in (positions or {}).items():
        amount = float(usd or 0.0)
        if amount <= 0:
            continue
        apy = apy_pct.get(proto)
        if apy is None:
            continue  # не наблюдаем ⇒ не засчитываем (fail-CLOSED)
        total += (amount / capital_usd) * float(apy)
    return round(total, 6)


def yield_gap_pp(
    *,
    current_positions: Dict[str, float],
    target_positions: Dict[str, float],
    apy_pct: Dict[str, Optional[float]],
    capital_usd: float,
) -> float:
    """Сколько доходности теряет текущая раскладка против оптимальной (§33)."""
    now = blended_apy_pp(current_positions, apy_pct, capital_usd)
    opt = blended_apy_pp(target_positions, apy_pct, capital_usd)
    return round(opt - now, 6)


# ──────────────────────────────────────────────────────────────────────────────
# Решение: KEEP / REBALANCE / DEFER
# ──────────────────────────────────────────────────────────────────────────────

def decide(
    *,
    current_positions: Dict[str, float],
    target_positions: Dict[str, float],
    displayed_apy_pct: Dict[str, Optional[float]],
    apy_history: Optional[Dict[str, Sequence[float]]] = None,
    apy_sources: Optional[Dict[str, str]] = None,
    tvl_usd: Optional[Dict[str, Optional[float]]] = None,
    tvl_evidenced: Optional[set] = None,
    evidenced: Optional[set] = None,
    chains: Optional[Dict[str, str]] = None,
    capital_usd: float,
    expected_persistence_days: Optional[Dict[str, float]] = None,
    derisk_active: bool = False,
    params: Optional[CioParams] = None,
    trigger_params: Optional[TriggerParams] = None,
    **economics_kwargs,
) -> CioDecision:
    """Полный контур решения на ОДНОМ снимке. Ничего не исполняет.

    Порядок намеренный: сначала консервативный APY (§11), затем разбавление нашим
    размером (§12), и только потом экономика перехода (ADR-060). Обратный порядок
    считал бы окупаемость по витринному числу, которого мы не получим.
    """
    p = params or CioParams()
    tp = trigger_params or TriggerParams()
    apy_history = apy_history or {}
    apy_sources = apy_sources or {}
    tvl_usd = tvl_usd or {}
    chains = chains or {}
    d = CioDecision()

    if capital_usd <= 0:
        d.refusals.append("invalid_capital")
        d.reasons.append("отказ: капитал не положителен")
        return d

    # ── §11 + §12: чему мы верим по каждому протоколу ──────────────────────
    effective: Dict[str, Optional[float]] = {}
    universe = sorted(set(current_positions) | set(target_positions) | set(displayed_apy_pct))
    for proto in universe:
        view = conservative_expected_apy(
            protocol=proto,
            displayed_apy_pct=displayed_apy_pct.get(proto),
            history=apy_history.get(proto),
            apy_source=apy_sources.get(proto, "live"),
            params=p,
        )
        target_size = float(target_positions.get(proto, 0.0) or 0.0)
        held_size = float(current_positions.get(proto, 0.0) or 0.0)
        added = max(0.0, target_size - held_size)
        if view.conservative_apy_pct is not None and added > 0:
            marginal, why = marginal_apy_pct(
                apy_pct=view.conservative_apy_pct,
                tvl_usd=tvl_usd.get(proto),
                size_usd=added,
                tvl_evidenced=(tvl_evidenced is None or proto in tvl_evidenced),
            )
            view.marginal_apy_pct = marginal
            if marginal is None:
                view.refusals.append(f"marginal_unmeasured:{why}")
        d.views[proto] = view.to_dict()
        if view.refusals:
            d.refusals.extend(f"{proto}:{r}" for r in view.refusals)
        # Наращиваем позицию ⇒ считаем по разбавленному числу; держим или режем ⇒
        # по консервативному. Иначе вход выглядел бы выгоднее, чем он есть.
        if added > 0 and view.marginal_apy_pct is not None:
            effective[proto] = view.marginal_apy_pct
        elif added > 0 and view.conservative_apy_pct is not None:
            # marginal не измерен ⇒ финансировать вслепую нельзя (fail-CLOSED)
            effective[proto] = None
        else:
            effective[proto] = view.conservative_apy_pct

    d.current_expected_apy_pp = blended_apy_pp(current_positions, effective, capital_usd)
    d.optimal_expected_apy_pp = blended_apy_pp(target_positions, effective, capital_usd)
    d.yield_gap_pp = round(d.optimal_expected_apy_pp - d.current_expected_apy_pp, 6)

    # Отдельного «порога устойчивости» здесь СОЗНАТЕЛЬНО нет. Он был, и мутация
    # показала, что он не способен сработать ни на одном входе: устойчивость уже
    # зашита в кредитуемый APY (§11), поэтому неустойчивое преимущество не доходит
    # до экономики — оно обнуляется раньше. Проверка, которая не может покраснеть,
    # хуже отсутствующей: она создаёт ложное чувство второго рубежа.

    # ── ADR-060: существующая экономика перехода. НЕ дублируем её ───────────
    econ: EconomicsDecision = evaluate_economics(
        current_positions=current_positions,
        target_positions=target_positions,
        apy_pct={k: (v if v is not None else 0.0) for k, v in effective.items()},
        evidenced=(evidenced if evidenced is not None
                   else {k for k, v in effective.items() if v is not None}),
        chains=chains,
        capital_usd=capital_usd,
        params=tp,
        tvl_evidenced=tvl_evidenced,
        **economics_kwargs,
    )
    d.economics = econ.to_dict()
    d.switching_cost_usd = econ.cost_usd
    d.payback_days = econ.payback_days
    d.turnover_usd = econ.turnover_usd
    d.legs = econ.legs
    d.warnings.extend(econ.warnings)

    # ── Риск имеет приоритет над оптимизацией доходности (§37 тест 14) ──────
    # SOFT-ступень запрещает наращивание; предлагать переход в такой момент —
    # значит спорить с защитой. CIO advisory, но и советовать этого не должен.
    if derisk_active:
        d.decision = KEEP
        d.reasons.append("активен режим снижения риска — доходность не оптимизируем")
        return d

    # ── Окупаемость длиннее, чем живёт само преимущество (§31, тест 3) ──────
    # Сделка, которая окупается за 20 дней при ожидаемой жизни ставки в 5, —
    # это оплаченный переход в исчезающую доходность, а не улучшение.
    short_lived: List[str] = []
    for proto, days in (expected_persistence_days or {}).items():
        if float(target_positions.get(proto, 0.0) or 0.0) <= float(
                current_positions.get(proto, 0.0) or 0.0):
            continue
        if econ.payback_days is not None and float(days) < float(econ.payback_days):
            short_lived.append(proto)
    if short_lived:
        d.decision = KEEP
        d.reasons.append(
            "окупаемость {} дн. дольше ожидаемой жизни преимущества: {}".format(
                round(econ.payback_days or 0.0, 1), sorted(short_lived))
        )
        return d

    # ── Три вердикта вместо двух ───────────────────────────────────────────
    if econ.decision == "ACT":
        d.decision = REBALANCE
        d.reasons.append(
            "выгода {:.2f} pp окупает стоимость ${:,.0f} за {} дн.".format(
                econ.gain_pp, econ.cost_usd,
                "?" if econ.payback_days is None else round(econ.payback_days, 1))
        )
        return d

    # DEFER ⇔ отказала РОВНО окупаемость, а все остальные ворота открыты.
    # Это единственное отличие «дорого сейчас» от «не нужно вовсе»: первое обязано
    # вернуться на пересчёт, когда газ упадёт (§37 тесты 8–9), второе — нет.
    # Судим по ГЕЙТАМ, а не по разбору строк причин: строка — человеческий текст,
    # она меняется при правке формулировки и утащила бы вердикт за собой.
    gates = dict(econ.gates or {})
    cost_bound = (
        gates.get("has_legs") is True
        and gates.get("gain_above_band") is True
        and gates.get("payback_within_horizon") is False
        and all(v for k, v in gates.items()
                if k not in ("payback_within_horizon",))
    )
    if cost_bound and econ.payback_days is not None \
            and econ.payback_days <= tp.max_payback_days * p.defer_payback_factor:
        d.decision = DEFER
        d.reasons.append(
            "выгода есть ({:.2f} pp), но окупаемость {} дн. > потолка {} дн. — "
            "пересчитать при снижении издержек".format(
                econ.gain_pp, round(econ.payback_days, 1), tp.max_payback_days)
        )
        return d

    d.decision = KEEP
    d.reasons.extend(econ.reasons or ["нет перехода, превышающего порог чистой выгоды"])
    return d


# ──────────────────────────────────────────────────────────────────────────────
# §34 Owner-экран и §30 аудит
# ──────────────────────────────────────────────────────────────────────────────

_DECISION_RU = {
    KEEP: "ОСТАВЛЯЕМ",
    REBALANCE: "ПЕРЕКЛАДЫВАЕМ",
    DEFER: "ЖДЁМ УДЕШЕВЛЕНИЯ",
}


def render_owner_section(d: CioDecision, *, capital_usd: float) -> str:
    """Секция для дневного отчёта. Внутренностей оптимизатора здесь нет (§36).

    Владелец видит девять вещей из §36 и ни одного JSON, хэша или пути.
    """
    lines = ["🧠 Portfolio CIO"]
    lines.append("Сейчас ожидаем: {:.2f}%".format(d.current_expected_apy_pp))
    lines.append("Можно ожидать:  {:.2f}%".format(d.optimal_expected_apy_pp))
    lines.append("Разрыв: {:.2f} pp".format(d.yield_gap_pp))
    lines.append("")
    lines.append("Решение: {}".format(_DECISION_RU.get(d.decision, d.decision)))
    for r in d.reasons[:3]:
        lines.append("  • {}".format(r))
    if d.decision in (REBALANCE, DEFER) and d.legs:
        lines.append("")
        lines.append("Что предлагается:")
        for leg in d.legs[:5]:
            delta = float(leg.get("delta_usd", 0.0))
            lines.append("  {} {} ${:,.0f}".format(
                leg.get("protocol", "?"), "+" if delta > 0 else "−", abs(delta)))
        lines.append("Стоимость перехода: ${:,.0f}".format(d.switching_cost_usd))
        if d.payback_days is not None:
            lines.append("Окупится за: {:.0f} дн.".format(d.payback_days))
    if d.refusals:
        lines.append("")
        lines.append("Не посчитано честно ({}): {}".format(
            len(d.refusals), ", ".join(d.refusals[:3])))
    return "\n".join(lines)


def save_snapshot(d: CioDecision, path: str, *, generated_at: str) -> None:
    """Снимок решения целиком — каждое решение обязано иметь след (§30, инв. 5).

    Время — ВХОД, а не окружение: иначе снимок нельзя воспроизвести, а тест
    пришлось бы привязать к календарю (правило доставки, «время в тестах»).
    """
    payload = dict(d.to_dict())
    payload["generated_at"] = generated_at
    payload["is_advisory"] = IS_ADVISORY
    atomic_save(payload, path)
