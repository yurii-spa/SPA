"""Protection Lab — параметризованный генератор синтетических сценариев.

# LLM_FORBIDDEN

Синтетика строит ТЕ ЖЕ структуры (`Scenario` + `ReplaySpec`), что и историческая
библиотека, и гоняется ТЕМ ЖЕ движком `replay.run_replay` — двух математик нет.

Детерминизм: никакой случайности; один `SyntheticSpec` → всегда один сценарий.
(Monte-Carlo уже существует отдельно — `spa_core/backtesting/tier1/monte_carlo.py`;
здесь его не дублируем.)

AI-слой (фаза 6 задания владельца) сюда НЕ входит и не войдёт: LLM может лишь
ПРЕДЛОЖИТЬ параметры `SyntheticSpec` снаружи; превращение спеки в цифры P&L —
только этот детерминированный код.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .schema import ReplaySpec, Scenario, Shock

# Номинальная дата синтетики — заведомо вымышленная, wall clock не читается.
SYNTHETIC_START_DATE = "2030-01-01"


@dataclass
class DepegSpec:
    """Депег одного символа: линейно вниз к trough, линейно вверх к recovery."""

    symbol: str
    min_price: float
    start_day: int = 0
    trough_day: int = 1
    recovery_day: Optional[int] = None  # None = не восстанавливается до конца окна


@dataclass
class SyntheticSpec:
    """Параметры пользовательского/adversarial стресса (фазы 5/7 задания)."""

    name: str
    description: str
    duration_days: int = 30
    depegs: List[DepegSpec] = field(default_factory=list)
    # [{protocol, from_day, to_day, halt?}] — halt=True гасит и начисление доходности
    freezes: List[dict] = field(default_factory=list)
    # [{protocol, day, loss_pct}]
    capital_losses: List[dict] = field(default_factory=list)
    # [{protocol, apy_pct, from_day, to_day}]
    apy_shocks: List[dict] = field(default_factory=list)
    # [{protocol, tvl_usd, from_day, to_day}]
    tvl_shocks: List[dict] = field(default_factory=list)
    # {from_day, to_day, exit_haircut_pct, gas_cost_usd[, protocol]}
    liquidity: Optional[dict] = None
    base: Dict[str, Dict[str, float]] = field(default_factory=dict)
    assumptions: List[str] = field(default_factory=list)
    # Контекст рынка (не влияет на книгу напрямую — книга стейблкоиновая;
    # хранится для отчёта и будущих книг с направленной экспозицией).
    market_context: Dict[str, str] = field(default_factory=dict)


def _depeg_to_path(dp: DepegSpec) -> List[List[float]]:
    path: List[List[float]] = [[dp.start_day, 1.0], [dp.trough_day, dp.min_price]]
    if dp.recovery_day is not None and dp.recovery_day > dp.trough_day:
        path.append([dp.recovery_day, 1.0])
    return path


def build_synthetic_scenario(spec: SyntheticSpec) -> Scenario:
    """Развернуть SyntheticSpec в полноценный Scenario (synthetic=True)."""
    shocks: List[Shock] = []
    timeline: List[dict] = []

    for dp in spec.depegs:
        shocks.append(Shock(kind="peg", params={
            "symbol": dp.symbol, "path": _depeg_to_path(dp)}))
        timeline.append({
            "ts": f"day {dp.trough_day}",
            "event": f"{dp.symbol} до ${dp.min_price:.2f}"
                     + (f", восстановление к дню {dp.recovery_day}"
                        if dp.recovery_day is not None else ", без восстановления"),
            "observed": False,
        })
    for fz in spec.freezes:
        shocks.append(Shock(kind="halt" if fz.get("halt") else "freeze", params={
            "protocol": fz["protocol"],
            "from_day": int(fz["from_day"]), "to_day": int(fz["to_day"])}))
        timeline.append({
            "ts": f"day {fz['from_day']}",
            "event": f"{fz['protocol']}: вывод недоступен до дня {fz['to_day']}",
            "observed": False,
        })
    for cl in spec.capital_losses:
        shocks.append(Shock(kind="capital_loss", params={
            "protocol": cl["protocol"], "day": int(cl["day"]),
            "loss_pct": float(cl["loss_pct"])}))
        timeline.append({
            "ts": f"day {cl['day']}",
            "event": f"{cl['protocol']}: обесценение {cl['loss_pct']:.0%}",
            "observed": False,
        })
    for sh in spec.apy_shocks:
        shocks.append(Shock(kind="apy", params=dict(sh)))
    for sh in spec.tvl_shocks:
        shocks.append(Shock(kind="tvl", params=dict(sh)))
    if spec.liquidity:
        shocks.append(Shock(kind="liquidity", params=dict(spec.liquidity)))
        timeline.append({
            "ts": f"day {spec.liquidity.get('from_day', 0)}",
            "event": (f"ликвидность: haircut выхода "
                      f"{spec.liquidity.get('exit_haircut_pct', 0):.1%}, "
                      f"gas ${spec.liquidity.get('gas_cost_usd', 0):,.0f}"),
            "observed": False,
        })

    timeline.sort(key=lambda e: int(str(e["ts"]).split()[-1]))

    sid = spec.name if spec.name.startswith("SYN_") else f"SYN_{spec.name}"
    return Scenario(
        id=sid,
        name=spec.name,
        event_class=["systemic_contagion"],
        window_utc={"start": SYNTHETIC_START_DATE, "end": SYNTHETIC_START_DATE},
        speed=f"синтетика, {spec.duration_days}д",
        summary=spec.description,
        timeline=timeline or [{"ts": "day 0", "event": "пустой сценарий", "observed": False}],
        market_impact={"context": dict(spec.market_context)},
        stablecoins=[{"symbol": dp.symbol, "min_price_usd": dp.min_price,
                      "when": f"day {dp.trough_day}"} for dp in spec.depegs],
        defi_impact={},
        causes={"primary": "синтетический стресс (параметры пользователя/adversarial)"},
        contagion=[],
        recovery={},
        sources=[],
        confidence_notes="синтетика: не факты, а параметры; провенанс не применим",
        replay=ReplaySpec(
            duration_days=spec.duration_days,
            start_date=SYNTHETIC_START_DATE,
            shocks=shocks,
            base={k: dict(v) for k, v in spec.base.items()},
            assumptions=list(spec.assumptions),
        ),
        synthetic=True,
    )


# ─── Adversarial-набор (фаза 7, v1 — рукописные семейства) ───────────────────
#
# Каждая спека бьёт в ОТДЕЛЬНЫЙ канал уязвимости текущей книги. Это не
# «тысячи комбинаций» (перебор — следующая итерация), а по одному
# представителю на семейство отказов, включая семейства, где защита
# ЗАВЕДОМО бессильна или ЗАВЕДОМО вредит — их результат обязан быть виден.

ADVERSARIAL_SPECS: List[SyntheticSpec] = [
    SyntheticSpec(
        name="SYN_S01_stablecoin_contagion",
        description="Каскадный депег: USDC до $0.78 (день 3), PT-дисконт до 0.88; "
                    "восстановление USDC к дню 12. Кэш системы — USDC: бежать некуда.",
        duration_days=21,
        depegs=[
            DepegSpec("USDC", 0.78, start_day=1, trough_day=3, recovery_day=12),
            DepegSpec("PT_USDC", 0.88, start_day=2, trough_day=4, recovery_day=15),
        ],
        liquidity={"from_day": 1, "to_day": 8, "exit_haircut_pct": 0.02,
                   "gas_cost_usd": 250.0},
    ),
    SyntheticSpec(
        name="SYN_S02_private_credit_default",
        description="Дефолт заёмщика Maple: −35% принципала днём 3 БЕЗ рыночного "
                    "сигнала накануне, пул заморожен до дня 20 (стиль Orthogonal 2022).",
        duration_days=30,
        capital_losses=[{"protocol": "maple", "day": 3, "loss_pct": 0.35}],
        freezes=[{"protocol": "maple", "from_day": 3, "to_day": 20}],
    ),
    SyntheticSpec(
        name="SYN_S03_lending_death_spiral",
        description="Спираль lending-протоколов: morpho −12% (bad debt), Aave "
                    "utilization 100% — вывод недоступен 3 дня, haircut выхода 2%.",
        duration_days=21,
        capital_losses=[{"protocol": "morpho_steakhouse", "day": 2, "loss_pct": 0.12}],
        freezes=[{"protocol": "aave_v3", "from_day": 2, "to_day": 4}],
        liquidity={"from_day": 2, "to_day": 7, "exit_haircut_pct": 0.02,
                   "gas_cost_usd": 150.0},
    ),
    SyntheticSpec(
        name="SYN_S04_double_shock",
        description="Двойной удар: USDC до $0.85 + Aave полностью встал на 3 дня "
                    "(halt: ни вывода, ни начисления), gas ×20.",
        duration_days=14,
        depegs=[DepegSpec("USDC", 0.85, start_day=0, trough_day=2, recovery_day=8)],
        freezes=[{"protocol": "aave_v3", "from_day": 1, "to_day": 3, "halt": True}],
        liquidity={"from_day": 0, "to_day": 5, "exit_haircut_pct": 0.015,
                   "gas_cost_usd": 400.0},
    ),
    SyntheticSpec(
        name="SYN_S05_pt_dislocation",
        description="PT-дислокация БЕЗ дефолта: PT_USDC торгуется 0.85 десять дней "
                    "(шок ставок), к дню 25 возвращается к пару. Ловушка для защиты: "
                    "выход по 0.85 фиксирует убыток, которого не было бы при "
                    "удержании до погашения.",
        duration_days=30,
        depegs=[DepegSpec("PT_USDC", 0.85, start_day=2, trough_day=5, recovery_day=25)],
        liquidity={"from_day": 2, "to_day": 15, "exit_haircut_pct": 0.03,
                   "gas_cost_usd": 100.0, "protocol": "pendle"},
    ),
    SyntheticSpec(
        name="SYN_S07_utilization_pin",
        description="Utilization-пин БЕЗ взлома (аудит полноты, дыра №4): borrow-спрос "
                    "пинит Aave к 100% — вывод недоступен 3 дня, supply APY 18%, NAV "
                    "не падает ни на цент. Вопрос сценария: видит ли защита v1.0 "
                    "недоступность вывода, когда ни дроудауна, ни депега нет.",
        duration_days=10,
        freezes=[{"protocol": "aave_v3", "from_day": 1, "to_day": 3}],
        apy_shocks=[{"protocol": "aave_v3", "apy_pct": 18.0,
                     "from_day": 1, "to_day": 3}],
        assumptions=["Исторические шаблоны: FTX-неделя (стейблы), Mar-2023 "
                     "(шорт депега пинит USDC-utilization ровно когда книге нужен "
                     "выход), Nov-2025 (кураторный кризис Morpho)."],
    ),
    SyntheticSpec(
        name="SYN_S06_oct10_x2",
        description="10.10.2025 × 2: двухдневный каскад ликвидаций вдвое сильнее — "
                    "PT-дисконт до 0.80, morpho −4% (ADL/оракульные метки), haircut "
                    "выхода 5%, gas ×15; восстановление ликвидности к дню 6.",
        duration_days=14,
        depegs=[
            DepegSpec("PT_USDC", 0.80, start_day=0, trough_day=1, recovery_day=6),
            DepegSpec("USDC", 0.985, start_day=0, trough_day=1, recovery_day=2),
        ],
        capital_losses=[{"protocol": "morpho_steakhouse", "day": 1, "loss_pct": 0.04}],
        liquidity={"from_day": 0, "to_day": 5, "exit_haircut_pct": 0.05,
                   "gas_cost_usd": 300.0},
        market_context={"btc": "−24% за 2 дня (10.10.2025 было −12%+)",
                        "alts": "−60…−90% intraday"},
    ),
]
