#!/usr/bin/env python3
"""Tournament 30-day paper simulation.

Run: python scripts/run_tournament_30d.py

Симулирует 30 дней турнира с MultiStrategyRunner, загружает APY из
data/adapter_status.json, сохраняет результаты в data/tournament_30d_results.json.

Правила:
  - ТОЛЬКО stdlib (no external deps)
  - Атомарные записи (mkstemp + os.replace)
  - Advisory / read-only — не вызывает execution/ или risk-агентов
  - Graceful import fallback для MultiStrategyRunner и StrategyConfig
"""

import json
import math
import os
import pathlib
import sys
import tempfile
import datetime

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ─── Fallback-классы на случай проблем с импортом ────────────────────────────

class _FallbackStrategyConfig:
    """Mock StrategyConfig — используется если основной импорт недоступен."""

    def __init__(self, id, name, description, allocations,
                 tier="T1", target_apy_min=2.0, target_apy_max=8.0,
                 kill_drawdown_pct=0.05, status="active"):
        alloc_sum = sum(allocations.values())
        if alloc_sum > 1.0 + 1e-9:
            raise ValueError(f"Strategy {id}: allocations sum {alloc_sum:.4f} > 1.0")
        self.id = id
        self.name = name
        self.description = description
        self.allocations = allocations
        self.tier = tier
        self.target_apy_min = target_apy_min
        self.target_apy_max = target_apy_max
        self.kill_drawdown_pct = kill_drawdown_pct
        self.status = status
        self.gate_condition = None
        self.strategy_class = None

    @property
    def cash_pct(self):
        return max(0.0, 1.0 - sum(self.allocations.values()))


class _MockVPortfolio:
    """Упрощённый VPortfolio для fallback-режима."""

    def __init__(self, strategy_id, capital_usd, allocations):
        self.strategy_id = strategy_id
        self.capital_usd = capital_usd
        self.positions = {
            k: capital_usd * v for k, v in allocations.items()
            if k not in _SKIP_PROTOCOLS
        }
        positions_total = sum(self.positions.values())
        self.cash_usd = max(0.0, capital_usd - positions_total)
        self.peak_equity = capital_usd
        self.equity_history = []
        self.daily_returns = []
        self.days_simulated = 0
        self.status = "active"

    @property
    def current_equity(self):
        return sum(self.positions.values()) + self.cash_usd

    @property
    def total_return_pct(self):
        eq = self.current_equity
        if self.capital_usd == 0:
            return 0.0
        return (eq - self.capital_usd) / self.capital_usd * 100.0

    @property
    def drawdown_pct(self):
        eq = self.current_equity
        if self.peak_equity == 0:
            return 0.0
        dd = (self.peak_equity - eq) / self.peak_equity
        return max(0.0, dd)

    def simulate_day(self, apy_data):
        """Простое начисление дневного yield по позициям."""
        daily_yield = 0.0
        for protocol, usd_val in self.positions.items():
            apy_pct = apy_data.get(protocol, 0.0)
            daily_factor = apy_pct / 100.0 / 365.0
            earned = usd_val * daily_factor
            self.positions[protocol] = usd_val + earned
            daily_yield += earned

        prev_equity = self.current_equity - daily_yield
        if prev_equity > 0:
            daily_ret = daily_yield / prev_equity
        else:
            daily_ret = 0.0

        self.daily_returns.append(daily_ret)
        self.days_simulated += 1

        eq = self.current_equity
        if eq > self.peak_equity:
            self.peak_equity = eq

        self.equity_history.append({
            "day": self.days_simulated,
            "equity": round(eq, 6),
        })
        return daily_yield


class _MockMultiStrategyRunner:
    """Fallback-раннер когда основной MultiStrategyRunner недоступен."""

    def __init__(self, strategies, capital=100_000.0):
        self.capital = float(capital)
        self._strategies = {s.id: s for s in strategies}
        self._portfolios = {
            s.id: _MockVPortfolio(s.id, self.capital, s.allocations)
            for s in strategies
        }
        self._last_day_yields = {}

    def run_day(self, apy_map):
        results = {}
        for sid, vp in self._portfolios.items():
            if vp.status in ("killed", "paused"):
                continue
            daily_yield = vp.simulate_day(apy_map)
            results[sid] = daily_yield
        self._last_day_yields = results
        return results

    def get_rankings(self):
        ranked = []
        for sid, vp in self._portfolios.items():
            cfg = self._strategies[sid]
            returns = vp.daily_returns
            net_apy = (vp.total_return_pct / max(vp.days_simulated, 1) * 365 / 100.0
                       if vp.days_simulated > 0 else 0.0)
            score = net_apy  # упрощённая оценка для fallback

            ranked.append({
                "strategy_id": sid,
                "composite_score": score,
                "net_apy": net_apy,
                "is_active": vp.status in ("active", "promoted"),
                "days_running": vp.days_simulated,
            })

        ranked.sort(key=lambda r: r["composite_score"], reverse=True)
        for i, r in enumerate(ranked):
            r["rank"] = i + 1
        return ranked


# ─── Протоколы которые пропускаем при симуляции ───────────────────────────────

_SKIP_PROTOCOLS = frozenset({
    "pendle_pt",
    "sky_susds",
    "pendle_yt",
    "susde_spot",
    "perp_short_hedge",
})

# ─── Дефолтные APY если adapter_status.json недоступен ──────────────────────

_DEFAULT_APY_MAP = {
    "aave_v3":          4.2,
    "compound_v3":      4.8,
    "morpho_blue":      6.5,
    "morpho_steakhouse": 6.5,
    "yearn_v3":         6.8,
    "euler_v2":         7.4,
    "maple":            5.6,
    "pendle_pt":        8.0,
    "aave_v3_arbitrum": 4.1,
    "aave_arbitrum":    4.1,
}


# ─── Функции ──────────────────────────────────────────────────────────────────

def load_apy_map(data_dir=None):
    """Читает data/adapter_status.json → dict {protocol_key_underscore: apy_float}.

    Конвертирует дефисы в подчёркивания (aave-v3 → aave_v3) чтобы ключи
    совпадали с protocol_key из StrategyConfig.allocations.

    Добавляет специальный маппинг morpho_steakhouse → morpho_blue для
    совместимости со стратегиями S0/S1 которые используют morpho_blue.

    Args:
        data_dir: путь к директории data/ (Path или str). None → ROOT/data.

    Returns:
        dict {protocol_key: float} с годовыми APY в процентах.
        При ошибке чтения возвращает _DEFAULT_APY_MAP.
    """
    if data_dir is None:
        data_dir = ROOT / "data"

    adapter_path = pathlib.Path(data_dir) / "adapter_status.json"

    result = {}

    try:
        with open(adapter_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # Файл недоступен — возвращаем дефолты
        return dict(_DEFAULT_APY_MAP)

    # 1. Обходим список adapters: protocol_key дефис → underscore, берём ethereum USDC
    adapters_list = raw.get("adapters", [])
    for adapter in adapters_list:
        pk_raw = adapter.get("protocol_key", "")
        if not pk_raw:
            continue
        # Нормализуем: дефис → underscore, убираем лишние символы
        pk = pk_raw.replace("-", "_").lower()

        mock_apy = adapter.get("mock_apy", {})
        eth_apy = mock_apy.get("ethereum", {})
        # Предпочитаем USDC, fallback → USDT → первое доступное
        apy_val = (eth_apy.get("USDC")
                   or eth_apy.get("USDT")
                   or (next(iter(eth_apy.values()), None) if eth_apy else None))

        if apy_val is not None:
            try:
                result[pk] = float(apy_val)
            except (TypeError, ValueError):
                pass

    # 2. Верхнеуровневые ключи (morpho_steakhouse, compound_v3, aave_arbitrum, pendle_pt)
    for top_key in ("morpho_steakhouse", "compound_v3", "aave_arbitrum", "pendle_pt"):
        entry = raw.get(top_key)
        if isinstance(entry, dict):
            apy_val = entry.get("apy")
            if apy_val is not None:
                try:
                    result[top_key] = float(apy_val)
                except (TypeError, ValueError):
                    pass

    # 3. Специальные алиасы для совместимости со стратегиями
    # morpho-steakhouse → morpho_blue (S0/S1 используют morpho_blue)
    if "morpho_steakhouse" in result and "morpho_blue" not in result:
        result["morpho_blue"] = result["morpho_steakhouse"]
    elif "morpho_blue" not in result and "morpho_steakhouse" not in result:
        result["morpho_blue"] = _DEFAULT_APY_MAP["morpho_blue"]

    # aave_v3_arbitrum алиас для aave_arbitrum
    if "aave_arbitrum" in result and "aave_v3_arbitrum" not in result:
        result["aave_v3_arbitrum"] = result["aave_arbitrum"]

    # 4. Гарантируем наличие базовых протоколов (fallback дефолты)
    for key, default_apy in _DEFAULT_APY_MAP.items():
        if key not in result:
            result[key] = default_apy

    return result


def _compute_sharpe(daily_returns):
    """Упрощённый Sharpe Ratio из дневных доходностей (annualised, rf=0).

    Args:
        daily_returns: list[float] — дневные доходности как доли (не %)

    Returns:
        float — annualised Sharpe Ratio, 0.0 если данных недостаточно.
    """
    n = len(daily_returns)
    if n < 2:
        return 0.0
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    std = math.sqrt(variance)
    if std < 1e-12:
        return 0.0
    return round((mean / std) * math.sqrt(252), 4)


def make_aave_baseline():
    """Создаёт mock стратегию S_aave_baseline: 95% Aave mainnet, ~3.2% APY.

    Используется как консервативный benchmark в симуляции турнира.

    Returns:
        StrategyConfig (реальный или fallback) с конфигурацией Aave Baseline.
    """
    try:
        from spa_core.paper_trading.strategy_registry import StrategyConfig
    except ImportError:
        StrategyConfig = _FallbackStrategyConfig

    return StrategyConfig(
        id="S_aave_baseline",
        name="Aave Baseline",
        description=(
            "Conservative baseline: 95% Aave V3 mainnet USDC (~3.2% APY). "
            "5% cash buffer. Reference point for tournament comparison."
        ),
        allocations={"aave_v3": 0.95},
        tier="T1",
        target_apy_min=2.5,
        target_apy_max=4.5,
        kill_drawdown_pct=0.05,
        status="active",
    )


def _load_strategies():
    """Загружает стратегии S0, S1 и S_aave_baseline для симуляции.

    Пробует реальные импорты, при неудаче создаёт mock-конфиги.

    Returns:
        list[StrategyConfig] — [S0, S1, S_aave_baseline]
    """
    strategies = []

    # S0 — Conservative T1
    try:
        from spa_core.paper_trading.strategy_registry import S0_CONSERVATIVE_T1
        strategies.append(S0_CONSERVATIVE_T1)
    except ImportError:
        strategies.append(_FallbackStrategyConfig(
            id="S0",
            name="Conservative T1",
            description="T1-only: Aave V3 50%, Morpho Blue 30%, Cash 20%.",
            allocations={"aave_v3": 0.50, "morpho_blue": 0.30},
            tier="T1",
            target_apy_min=2.0,
            target_apy_max=4.5,
        ))

    # S1 — Balanced T1+T2
    try:
        from spa_core.paper_trading.strategy_registry import S1_BALANCED
        strategies.append(S1_BALANCED)
    except ImportError:
        strategies.append(_FallbackStrategyConfig(
            id="S1",
            name="Balanced T1+T2",
            description="Aave 30%, Morpho 20%, Yearn 25%, Euler 20%, Cash 5%.",
            allocations={
                "aave_v3":    0.30,
                "morpho_blue": 0.20,
                "yearn_v3":   0.25,
                "euler_v2":   0.20,
            },
            tier="T1+T2",
            target_apy_min=5.0,
            target_apy_max=8.0,
        ))

    # S_aave_baseline — mock benchmark
    strategies.append(make_aave_baseline())

    return strategies


def _load_runner_class():
    """Возвращает MultiStrategyRunner (реальный или mock).

    Returns:
        class — MultiStrategyRunner или _MockMultiStrategyRunner
    """
    try:
        from spa_core.paper_trading.multi_strategy_runner import MultiStrategyRunner
        return MultiStrategyRunner
    except ImportError:
        return _MockMultiStrategyRunner


def run_simulation(strategies, capital_usd, n_days, apy_map):
    """Запускает n_days симуляцию с MultiStrategyRunner.

    Создаёт раннер со списком стратегий, прогоняет n_days итераций,
    собирает финальные метрики по каждой стратегии.

    Args:
        strategies:  list[StrategyConfig] — стратегии для симуляции
        capital_usd: float — начальный капитал на каждую стратегию
        n_days:      int — количество симулируемых дней
        apy_map:     dict {protocol_key: apy_pct} — APY данные

    Returns:
        dict — структура tournament_30d_results.json:
            simulation_date, capital_usd, n_days, strategies, winner, generated_by
    """
    if not strategies:
        raise ValueError("strategies list is empty")
    if capital_usd < 0:
        raise ValueError(f"capital_usd must be non-negative, got {capital_usd}")
    if n_days < 0:
        raise ValueError(f"n_days must be non-negative, got {n_days}")

    RunnerClass = _load_runner_class()
    runner = RunnerClass(strategies, capital=float(capital_usd))

    # Симуляция n_days дней
    for _day in range(n_days):
        runner.run_day(apy_map)

    # Собираем результаты из portfolios
    rankings = runner.get_rankings()

    strategies_out = []
    for r in rankings:
        sid = r["strategy_id"]
        vp = runner._portfolios[sid]
        cfg = runner._strategies[sid]

        final_balance = vp.current_equity
        total_return_pct = vp.total_return_pct

        if n_days > 0:
            annualized_apy_pct = total_return_pct / n_days * 365
        else:
            annualized_apy_pct = 0.0

        sharpe_approx = _compute_sharpe(vp.daily_returns)

        strategies_out.append({
            "rank":               r["rank"],
            "strategy_id":        sid,
            "strategy_name":      cfg.name,
            "final_balance":      round(final_balance, 2),
            "total_return_pct":   round(total_return_pct, 4),
            "annualized_apy_pct": round(annualized_apy_pct, 2),
            "sharpe_approx":      sharpe_approx,
        })

    winner = strategies_out[0]["strategy_id"] if strategies_out else None

    return {
        "simulation_date": datetime.date.today().isoformat(),
        "capital_usd":     capital_usd,
        "n_days":          n_days,
        "strategies":      strategies_out,
        "winner":          winner,
        "generated_by":    "run_tournament_30d.py",
    }


def save_results(results, path):
    """Атомарная запись результатов в JSON (mkstemp + os.replace).

    Никогда не пишет напрямую в целевой файл — гарантирует консистентность
    при аварийном завершении.

    Args:
        results: dict — структура результатов симуляции
        path:    str или Path — путь к выходному файлу
    """
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_tournament_30d_",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def print_table(results):
    """Выводит ASCII таблицу ранжирования стратегий.

    Columns: rank | strategy_id | strategy_name | APY% | Sharpe | total_return%

    Args:
        results: dict — структура tournament_30d_results.json

    Returns:
        list[str] — строки таблицы (также выводятся на stdout)
    """
    strategies = results.get("strategies", [])
    n_days     = results.get("n_days", 0)
    capital    = results.get("capital_usd", 0)
    sim_date   = results.get("simulation_date", "?")
    winner     = results.get("winner", "?")

    lines = []

    header = (
        f"\n{'='*72}\n"
        f"  Tournament 30-Day Simulation  |  {sim_date}  |  "
        f"Capital: ${capital:,.0f}  |  Days: {n_days}\n"
        f"{'='*72}"
    )
    lines.append(header)
    print(header)

    col_header = (
        f"{'Rank':>4}  {'ID':<18}  {'Name':<22}  "
        f"{'APY%':>7}  {'Sharpe':>7}  {'Return%':>8}"
    )
    separator = "-" * 72
    lines.append(col_header)
    lines.append(separator)
    print(col_header)
    print(separator)

    for s in strategies:
        rank   = s.get("rank", "?")
        sid    = s.get("strategy_id", "?")
        name   = s.get("strategy_name", "?")
        apy    = s.get("annualized_apy_pct", 0.0)
        sharpe = s.get("sharpe_approx", 0.0)
        ret    = s.get("total_return_pct", 0.0)

        marker = "  ←WINNER" if sid == winner else ""
        row = (
            f"{rank:>4}  {sid:<18}  {name:<22}  "
            f"{apy:>6.2f}%  {sharpe:>7.4f}  {ret:>7.4f}%{marker}"
        )
        lines.append(row)
        print(row)

    footer = f"\n  Winner: {winner}\n{'='*72}"
    lines.append(footer)
    print(footer)

    return lines


# ─── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DATA_DIR   = ROOT / "data"
    OUTPUT     = DATA_DIR / "tournament_30d_results.json"
    CAPITAL    = 100_000.0
    N_DAYS     = 30

    print(f"[run_tournament_30d] Loading APY map from {DATA_DIR}/adapter_status.json …")
    apy_map = load_apy_map(DATA_DIR)
    print(f"[run_tournament_30d] APY map: {apy_map}")

    print("\n[run_tournament_30d] Loading strategies …")
    strategies = _load_strategies()
    for s in strategies:
        print(f"  • {s.id}: {s.name}  allocations={list(s.allocations.keys())}")

    print(f"\n[run_tournament_30d] Running {N_DAYS}-day simulation …")
    results = run_simulation(strategies, CAPITAL, N_DAYS, apy_map)

    print_table(results)

    save_results(results, OUTPUT)
    print(f"\n[run_tournament_30d] Results saved → {OUTPUT}")
