"""Protection Lab — детерминированный replay: benchmark против защищённой книги.

# LLM_FORBIDDEN

Два прогона одного сценария на одной книге:

* **benchmark** — пассивный держатель: никаких решений, все шоки принимаются.
* **protected** — дневной цикл SPA: решения принимает НАСТОЯЩИЙ governance-слой
  (`classify_drawdown_pct` — лестница ADR-034/048) и НАСТОЯЩИЙ депег-гейт
  (`RiskPolicy.check_stablecoin_depeg` → `PriceFeedFetcher.detect_depeg`,
  один и тот же исходный классификатор). Пороги в этом модуле не живут.

Хронология дня d (no look-ahead, консервативно):
  1. утренний цикл: решения ТОЛЬКО по рынку конца дня d-1 (день 0 — без решений);
  2. рыночные шоки дня d применяются к держимым позициям (обесценения, пеги, доходность);
  3. запланированные выходы исполняются В КОНЦЕ дня d по ценам дня d
     (выход «в падение», а не до него); замороженный протокол → execution failure,
     повтор на следующий день;
  4. фиксируется дневной бар NAV.

Верное решение, которое не исполнилось, — это отказ исполнения, а не защита.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

from spa_core.governance.kill_switch import (
    LOOKBACK_DAYS,
    TIER_HARD_KILL,
    TIER_NONE,
    TIER_SOFT_DERISK,
    classify_drawdown_pct,
)
from spa_core.data_pipeline.price_feeds import PriceFeedFetcher

from .schema import ReplaySpec, Scenario

# Базовые условия рынка вне шоков (сценарий может переопределить через replay.base).
DEFAULT_BASE_APY_PCT = 4.0
DEFAULT_BASE_TVL_USD = 1_000_000_000.0

CASH_SYMBOL = "USDC"  # виртуальный капитал SPA — USDC; кэш не убегает от депега USDC


@dataclass
class BookPosition:
    """Позиция книги на входе в сценарий."""

    protocol: str
    weight: float                 # доля капитала (0..1)
    tier: str = "T2"
    exposure_symbol: str = "USDC"  # символ, в котором живёт принципал


# Книга по docs/STATE.md на 2026-08-16 (aave 40 / pendle 20 / maple 15 / morpho 15,
# кэш 10% — остаток от суммы весов). Символ pendle — PT_USDC: PT-дисконт к пару
# моделируется peg-путём этого символа.
DEFAULT_BOOK: List[BookPosition] = [
    BookPosition("aave_v3", 0.40, tier="T1", exposure_symbol="USDC"),
    BookPosition("pendle", 0.20, tier="T2", exposure_symbol="PT_USDC"),
    BookPosition("maple", 0.15, tier="T2", exposure_symbol="USDC"),
    BookPosition("morpho_steakhouse", 0.15, tier="T2", exposure_symbol="USDC"),
]


@dataclass
class _ProtoDay:
    apy_pct: float
    tvl_usd: float
    withdrawable: bool = True
    accruing: bool = True
    capital_loss_pct: float = 0.0
    exit_haircut_pct: float = 0.0  # добавка к глобальному haircut


@dataclass
class _MarketDay:
    pegs: Dict[str, float]
    protocols: Dict[str, _ProtoDay]
    exit_haircut_pct: float = 0.0
    gas_cost_usd: float = 0.0

    def peg(self, symbol: str) -> float:
        return self.pegs.get(symbol, 1.0)


def _interp_peg_path(path: List[List[float]], day: int) -> float:
    """Кусочно-линейный peg-путь: до первой точки 1.0, после последней — её значение."""
    if not path:
        return 1.0
    if day < path[0][0]:
        return 1.0
    for (d0, p0), (d1, p1) in zip(path, path[1:]):
        if d0 <= day <= d1:
            if d1 == d0:
                return float(p1)
            frac = (day - d0) / (d1 - d0)
            return float(p0 + (p1 - p0) * frac)
    return float(path[-1][1])


def expand_market(spec: ReplaySpec, protocols: List[str]) -> List[_MarketDay]:
    """Детерминированно развернуть шоки сценария в состояние рынка по дням."""
    days: List[_MarketDay] = []
    peg_shocks = [s for s in spec.shocks if s.kind == "peg"]

    for d in range(spec.duration_days):
        pegs: Dict[str, float] = {}
        for shock in peg_shocks:
            sym = str(shock.params["symbol"])
            pegs[sym] = _interp_peg_path(shock.params.get("path", []), d)

        proto_state: Dict[str, _ProtoDay] = {}
        for p in protocols:
            base = spec.base.get(p, {})
            proto_state[p] = _ProtoDay(
                apy_pct=float(base.get("apy_pct", DEFAULT_BASE_APY_PCT)),
                tvl_usd=float(base.get("tvl_usd", DEFAULT_BASE_TVL_USD)),
            )

        exit_haircut = 0.0
        gas_cost = 0.0
        for shock in spec.shocks:
            k, prm = shock.kind, shock.params
            if k == "peg":
                continue
            frm = int(prm.get("from_day", prm.get("day", 0)))
            to = int(prm.get("to_day", prm.get("day", frm)))
            in_window = frm <= d <= to
            if k == "liquidity" and in_window:
                target = prm.get("protocol")
                if target:
                    if target in proto_state:
                        proto_state[target].exit_haircut_pct = max(
                            proto_state[target].exit_haircut_pct,
                            float(prm.get("exit_haircut_pct", 0.0)))
                else:
                    exit_haircut = max(exit_haircut, float(prm.get("exit_haircut_pct", 0.0)))
                gas_cost = max(gas_cost, float(prm.get("gas_cost_usd", 0.0)))
            elif k in ("apy", "tvl", "freeze", "halt") and in_window:
                p = str(prm.get("protocol"))
                if p not in proto_state:
                    continue  # шок по протоколу вне книги — законен, просто не влияет
                if k == "apy":
                    proto_state[p].apy_pct = float(prm.get("apy_pct", 0.0))
                elif k == "tvl":
                    proto_state[p].tvl_usd = float(prm.get("tvl_usd", 0.0))
                elif k == "freeze":
                    proto_state[p].withdrawable = False
                elif k == "halt":
                    proto_state[p].withdrawable = False
                    proto_state[p].accruing = False
            elif k == "capital_loss" and int(prm.get("day", -1)) == d:
                p = str(prm.get("protocol"))
                if p in proto_state:
                    proto_state[p].capital_loss_pct = float(prm.get("loss_pct", 0.0))

        days.append(_MarketDay(pegs=pegs, protocols=proto_state,
                               exit_haircut_pct=exit_haircut, gas_cost_usd=gas_cost))
    return days


# ─── Результаты ───────────────────────────────────────────────────────────────


@dataclass
class ReplayRun:
    """Итог одного прогона (benchmark или protected)."""

    label: str
    bars: List[dict] = field(default_factory=list)
    final_equity: float = 0.0
    min_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    yield_earned_usd: float = 0.0
    impairment_usd: float = 0.0
    haircut_usd: float = 0.0
    gas_usd: float = 0.0
    actions: List[dict] = field(default_factory=list)
    execution_failures: List[dict] = field(default_factory=list)
    tier_by_day: List[str] = field(default_factory=list)
    positions_end_usd: Dict[str, float] = field(default_factory=dict)
    cash_end_usd: float = 0.0


@dataclass
class ProtectionReport:
    """Сводка сценария: пассивная книга против защищённой + находки по архитектуре."""

    scenario_id: str
    scenario_name: str
    capital_usd: float
    benchmark: ReplayRun
    protected: ReplayRun
    capital_saved_usd: float = 0.0
    benchmark_loss_usd: float = 0.0
    protected_loss_usd: float = 0.0
    protection_efficiency_pct: Optional[float] = None
    detection_day: Optional[int] = None
    first_action_day: Optional[int] = None
    findings: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)


# ─── Движок ───────────────────────────────────────────────────────────────────


def _trailing_drawdown_pct(closes: List[float]) -> Optional[float]:
    """Peak-to-current по хвосту LOOKBACK_DAYS — та же семантика, что у governance."""
    window = closes[-LOOKBACK_DAYS:]
    window = [c for c in window if math.isfinite(c) and c > 0]
    if len(window) < 2:
        return None
    peak = max(window)
    if peak <= 0:
        return None
    return (peak - window[-1]) / peak * 100.0


def _run_book(
    scenario: Scenario,
    book: List[BookPosition],
    capital_usd: float,
    protect: bool,
) -> ReplayRun:
    spec = scenario.replay
    assert spec is not None, "у сценария нет replay-спеки"

    protocols = [pos.protocol for pos in book]
    market = expand_market(spec, protocols)
    start = date.fromisoformat(spec.start_date)

    symbol_of = {pos.protocol: spec.exposure_symbols.get(pos.protocol, pos.exposure_symbol)
                 for pos in book}

    # units: принципал в единицах своего символа (value_usd = units × peg).
    units: Dict[str, float] = {pos.protocol: capital_usd * pos.weight for pos in book}
    cash_units = capital_usd * max(0.0, 1.0 - sum(pos.weight for pos in book))

    run = ReplayRun(label="protected" if protect else "benchmark")
    closes: List[float] = []
    scheduled_exits: Set[str] = set()
    soft_episode_open = False
    hard_killed = False
    detector = PriceFeedFetcher()

    for d in range(spec.duration_days):
        m = market[d]
        day_date = (start + timedelta(days=d)).isoformat()
        tier_today = TIER_NONE

        # ── 1. Утренний цикл: решения по рынку дня d-1 ─────────────────────
        if protect and d > 0:
            visible = market[d - 1]

            dd = _trailing_drawdown_pct(closes)
            tier_today, tier_reason = classify_drawdown_pct(dd)

            if tier_today == TIER_HARD_KILL and not hard_killed:
                hard_killed = True
                for p, u in units.items():
                    if u > 0:
                        scheduled_exits.add(p)
                run.actions.append({
                    "day": d, "date": day_date, "kind": "hard_kill",
                    "detail": tier_reason,
                })
            elif tier_today == TIER_SOFT_DERISK and not soft_episode_open:
                soft_episode_open = True
                run.actions.append({
                    "day": d, "date": day_date, "kind": "soft_derisk",
                    "detail": tier_reason + " — новые размещения остановлены",
                })
            if tier_today == TIER_NONE:
                soft_episode_open = False

            # Депег-гейт: цены всех символов экспозиции книги + кэша, какими их
            # видел вчерашний рынок. Классификация — той же detect_depeg,
            # которую вызывает RiskPolicy.check_stablecoin_depeg.
            watched = sorted({CASH_SYMBOL, *symbol_of.values()})
            prices = {sym: visible.peg(sym) for sym in watched}
            for ev in detector.detect_depeg(prices):
                if ev["severity"] != "CRITICAL":
                    continue
                sym = ev["symbol"]
                exposed = [p for p, u in units.items()
                           if u > 0 and symbol_of[p] == sym and p not in scheduled_exits]
                if exposed:
                    scheduled_exits.update(exposed)
                    run.actions.append({
                        "day": d, "date": day_date, "kind": "depeg_exit",
                        "detail": (f"{sym} по ${ev['price']:.4f} "
                                   f"({ev['deviation_pct']:+.2f}%) CRITICAL — "
                                   f"выход из {', '.join(sorted(exposed))}"),
                    })
                if sym == CASH_SYMBOL:
                    note = ("канал НЕ ЗАЩИЩЁН: кэш системы — USDC; выход из "
                            "USDC-позиций в USDC-кэш не снижает peg-экспозицию")
                    if note not in [a.get("finding") for a in run.actions]:
                        run.actions.append({
                            "day": d, "date": day_date,
                            "kind": "architecture_finding", "finding": note,
                            "detail": note,
                        })

        # ── 2. Рыночные шоки дня d по держимым позициям ────────────────────
        for p in units:
            if units[p] <= 0:
                continue
            proto = m.protocols[p]
            if proto.capital_loss_pct > 0:
                lost_units = units[p] * proto.capital_loss_pct
                run.impairment_usd += lost_units * m.peg(symbol_of[p])
                units[p] -= lost_units
            if proto.accruing and proto.apy_pct > 0:
                gained = units[p] * (proto.apy_pct / 100.0) / 365.0
                units[p] += gained
                run.yield_earned_usd += gained * m.peg(symbol_of[p])

        # ── 3. Исполнение выходов в конце дня d по ценам дня d ─────────────
        if protect and scheduled_exits:
            for p in sorted(scheduled_exits):
                if units[p] <= 0:
                    scheduled_exits.discard(p)
                    continue
                proto = m.protocols[p]
                if not proto.withdrawable:
                    run.execution_failures.append({
                        "day": d, "date": day_date, "protocol": p,
                        "reason": "вывод заморожен — решение верное, исполнить нельзя",
                    })
                    continue  # повтор завтра
                value_usd = units[p] * m.peg(symbol_of[p])
                haircut = value_usd * (m.exit_haircut_pct + proto.exit_haircut_pct)
                gas = m.gas_cost_usd
                proceeds = max(0.0, value_usd - haircut - gas)
                run.haircut_usd += haircut
                run.gas_usd += min(gas, value_usd)
                peg_cash = m.peg(CASH_SYMBOL)
                cash_units += proceeds / peg_cash if peg_cash > 0 else 0.0
                units[p] = 0.0
                scheduled_exits.discard(p)
                run.actions.append({
                    "day": d, "date": day_date, "kind": "exit_executed",
                    "detail": (f"{p}: ${value_usd:,.0f} → кэш, haircut "
                               f"${haircut:,.0f}, gas ${gas:,.0f}"),
                })

        # ── 4. Дневной бар NAV ─────────────────────────────────────────────
        nav = cash_units * m.peg(CASH_SYMBOL) + sum(
            units[p] * m.peg(symbol_of[p]) for p in units)
        closes.append(nav)
        run.bars.append({
            "day": d, "date": day_date, "close_equity": round(nav, 4),
            "evidenced": True, "source": "protection_lab_replay",
        })
        run.tier_by_day.append(tier_today)

    # Итоги.
    peak = -math.inf
    max_dd = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            max_dd = max(max_dd, (peak - c) / peak * 100.0)
    last_m = market[-1]
    run.final_equity = round(closes[-1], 4)
    run.min_equity = round(min(closes), 4)
    run.max_drawdown_pct = round(max_dd, 4)
    run.positions_end_usd = {
        p: round(units[p] * last_m.peg(symbol_of[p]), 2) for p in units if units[p] > 0}
    run.cash_end_usd = round(cash_units * last_m.peg(CASH_SYMBOL), 2)
    for key in ("yield_earned_usd", "impairment_usd", "haircut_usd", "gas_usd"):
        setattr(run, key, round(getattr(run, key), 4))
    return run


def run_replay(
    scenario: Scenario,
    book: Optional[List[BookPosition]] = None,
    capital_usd: float = 100_000.0,
) -> ProtectionReport:
    """Прогнать сценарий: benchmark + protected, собрать метрики защиты."""
    if scenario.replay is None:
        raise ValueError(f"{scenario.id}: у сценария нет replay-спеки — только датасет")
    if book is None:
        book = DEFAULT_BOOK

    benchmark = _run_book(scenario, book, capital_usd, protect=False)
    protected = _run_book(scenario, book, capital_usd, protect=True)

    report = ProtectionReport(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        capital_usd=capital_usd,
        benchmark=benchmark,
        protected=protected,
    )
    report.capital_saved_usd = round(protected.final_equity - benchmark.final_equity, 2)
    report.benchmark_loss_usd = round(max(0.0, capital_usd - benchmark.final_equity), 2)
    report.protected_loss_usd = round(max(0.0, capital_usd - protected.final_equity), 2)
    # Efficiency осмысленна только при заметной потере бенчмарка: деление на
    # копеечный знаменатель печатает «-18000%» и врёт масштабом. Порог 0.5%.
    if report.benchmark_loss_usd >= 0.005 * capital_usd:
        report.protection_efficiency_pct = round(
            (report.benchmark_loss_usd - report.protected_loss_usd)
            / report.benchmark_loss_usd * 100.0, 2)

    for i, tier in enumerate(protected.tier_by_day):
        if tier != TIER_NONE:
            report.detection_day = i
            break
    depeg_days = [a["day"] for a in protected.actions if a["kind"] == "depeg_exit"]
    if depeg_days:
        report.detection_day = (min(depeg_days) if report.detection_day is None
                                else min(report.detection_day, min(depeg_days)))
    action_days = [a["day"] for a in protected.actions
                   if a["kind"] in ("hard_kill", "soft_derisk", "depeg_exit")]
    if action_days:
        report.first_action_day = min(action_days)

    # Находки по архитектуре — автоматически, из фактов прогона.
    for a in protected.actions:
        if a["kind"] == "architecture_finding" and a["detail"] not in report.findings:
            report.findings.append(a["detail"])
    if protected.execution_failures:
        frozen = sorted({f["protocol"] for f in protected.execution_failures})
        report.findings.append(
            f"отказ исполнения: {', '.join(frozen)} — решение о выходе было, "
            f"вывод был заморожен ({len(protected.execution_failures)} попыток)")
    if (report.benchmark_loss_usd > 0.02 * capital_usd
            and report.detection_day is None):
        report.findings.append(
            "защита НЕ СРАБОТАЛА: benchmark потерял "
            f"${report.benchmark_loss_usd:,.0f}, а ни лестница дроудауна, ни "
            "депег-гейт сигнала не дали — канал потерь не покрыт политикой v1.0")
    if scenario.replay.assumptions:
        report.assumptions = list(scenario.replay.assumptions)
    return report
