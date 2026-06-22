"""
Unit/integration tests для Paper Trading Engine — SPA M2.

Используют временную in-memory SQLite БД чтобы не портить production spa.db.

Запуск:
    cd spa_core
    python tests/test_paper_trading.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import init_database
from paper_trading.engine import PaperTrader, RiskPolicyViolation, INITIAL_CAPITAL
from risk.policy import RiskConfig
from spa_core.utils.errors import SPAError


# ─── Test helpers ─────────────────────────────────────────────────────────────

def make_trader(config: RiskConfig = None) -> tuple[PaperTrader, Path]:
    """Создать трейдера с изолированной временной БД."""
    tmp = tempfile.mktemp(suffix=".db")
    db_path = Path(tmp)
    init_database(db_path=db_path)
    trader = PaperTrader(db_path=db_path, config=config)
    return trader, db_path


AAVE_USDC  = "aave-v3-usdc-ethereum"
COMP_USDC  = "compound-v3-usdc-ethereum"
MAPLE_USDC = "maple-usdc-ethereum"
EULER_USDC = "euler-v2-usdc-ethereum"
YEARN_USDC = "yearn-v3-usdc-ethereum"

VALID_APY = 5.0
VALID_TVL = 50_000_000.0

# Позиции относительно INITIAL_CAPITAL (чтобы тесты не зависели от конкретной суммы)
PCT_30 = round(INITIAL_CAPITAL * 0.30, 2)  # 30% капитала
PCT_40 = round(INITIAL_CAPITAL * 0.40, 2)  # 40% капитала (T1 max)
PCT_20 = round(INITIAL_CAPITAL * 0.20, 2)  # 20% капитала (T2 max)
PCT_15 = round(INITIAL_CAPITAL * 0.15, 2)  # 15% капитала
PCT_10 = round(INITIAL_CAPITAL * 0.10, 2)  # 10% капитала
PCT_97 = round(INITIAL_CAPITAL * 0.97, 2)  # 97% (должен блокироваться — < 5% cash)
PCT_5  = round(INITIAL_CAPITAL * 0.05, 2)  # 5% (для теста T2 лимита)


# ─── Runner ───────────────────────────────────────────────────────────────────

PASS = FAIL = 0
_log = []

def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        _log.append(f"  ✅  {name}")
    except Exception as e:
        FAIL += 1
        _log.append(f"  ❌  {name}  →  {str(e)[:80]}")


# ─── Tests: Initialisation ────────────────────────────────────────────────────

def test_initial_capital():
    """Стартовый капитал = INITIAL_CAPITAL, всё в кэше."""
    trader, _ = make_trader()
    status = trader.get_status()
    p = status["portfolio"]
    assert p["total_capital_usd"] == INITIAL_CAPITAL
    assert p["deployed_usd"] == 0.0
    assert p["cash_usd"] == INITIAL_CAPITAL
    assert p["cash_pct"] == 1.0
run("Init::initial_capital", test_initial_capital)

def test_no_positions_at_start():
    trader, _ = make_trader()
    assert trader.get_status()["positions"] == []
run("Init::no_positions_at_start", test_no_positions_at_start)

def test_health_ok_empty():
    trader, _ = make_trader()
    assert trader.get_status()["risk"]["health_approved"] is True
run("Init::health_ok_on_empty_portfolio", test_health_ok_empty)

def test_paper_trading_clock_starts_at_zero():
    trader, _ = make_trader()
    pt = trader.get_status()["paper_trading"]
    assert pt["days_elapsed"] == 0
    assert pt["go_live_ready"] is False
run("Init::paper_trading_clock_zero", test_paper_trading_clock_starts_at_zero)


# ─── Tests: Open Position ─────────────────────────────────────────────────────

def test_open_valid_position_approved():
    """Стандартная позиция в T1 протоколе должна быть одобрена."""
    trader, _ = make_trader()
    result = trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)
    assert result.approved is True
run("Open::valid_position_approved", test_open_valid_position_approved)

def test_open_updates_portfolio():
    """После открытия позиции deployed_usd должен увеличиться."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)
    p = trader.get_status()["portfolio"]
    assert p["deployed_usd"] == PCT_30
    assert abs(p["cash_usd"] - (INITIAL_CAPITAL - PCT_30)) < 0.01
run("Open::updates_portfolio_balances", test_open_updates_portfolio)

def test_open_position_appears_in_status():
    """Открытая позиция должна появиться в списке positions."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)
    positions = trader.get_status()["positions"]
    assert len(positions) == 1
    assert positions[0]["protocol_key"] == AAVE_USDC
    assert positions[0]["amount_usd"] == PCT_30
run("Open::position_appears_in_status", test_open_position_appears_in_status)

def test_open_multiple_positions():
    """Можно открыть несколько позиций в разных протоколах."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC,  PCT_20, 4.6, VALID_TVL)
    trader.open_position(COMP_USDC,  PCT_20, 4.8, VALID_TVL)
    trader.open_position(MAPLE_USDC, PCT_10, 4.9, VALID_TVL)
    p = trader.get_status()["portfolio"]
    assert abs(p["deployed_usd"] - (PCT_20 + PCT_20 + PCT_10)) < 0.01
    assert len(trader.get_status()["positions"]) == 3
run("Open::multiple_positions_different_protocols", test_open_multiple_positions)

def test_open_blocked_by_risk_policy_apy_too_high():
    """APY > 30% должен блокироваться."""
    trader, _ = make_trader()
    raised = False
    try:
        trader.open_position(AAVE_USDC, PCT_10, 35.0, VALID_TVL)
    except RiskPolicyViolation as e:
        raised = True
        assert any("exceeds maximum" in v for v in e.result.violations)
    assert raised, "Expected RiskPolicyViolation"
run("Open::blocked_apy_too_high", test_open_blocked_by_risk_policy_apy_too_high)

def test_open_blocked_by_risk_policy_tvl_too_low():
    """TVL < $5M должен блокироваться."""
    trader, _ = make_trader()
    raised = False
    try:
        trader.open_position(AAVE_USDC, PCT_10, VALID_APY, 1_000_000.0)
    except RiskPolicyViolation as e:
        raised = True
        assert any("TVL" in v for v in e.result.violations)
    assert raised
run("Open::blocked_tvl_too_low", test_open_blocked_by_risk_policy_tvl_too_low)

def test_open_blocked_concentration_breach():
    """Превышение концентрационного лимита T1 (40%) блокируется."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)  # 30%
    raised = False
    try:
        # Ещё 15% → итого 45% > 40% лимит T1
        trader.open_position(AAVE_USDC, PCT_15, VALID_APY, VALID_TVL)
    except RiskPolicyViolation as e:
        raised = True
        assert any("Concentration" in v for v in e.result.violations)
    assert raised
run("Open::blocked_concentration_breach", test_open_blocked_concentration_breach)

def test_open_blocked_cash_buffer():
    """Нельзя занять кэш ниже 5%-буфера."""
    trader, _ = make_trader()
    raised = False
    try:
        trader.open_position(AAVE_USDC, PCT_97, VALID_APY, VALID_TVL)  # оставит < 5%
    except RiskPolicyViolation as e:
        raised = True
        assert any("cash buffer" in v.lower() or "concentration" in v.lower()
                   for v in e.result.violations)
    assert raised
run("Open::blocked_cash_buffer", test_open_blocked_cash_buffer)

def test_open_blocked_unknown_protocol():
    """Неизвестный протокол должен вызвать ValueError."""
    trader, _ = make_trader()
    raised = False
    try:
        trader.open_position("unknown-protocol-xyz", PCT_10, VALID_APY, VALID_TVL)
    except (ValueError, SPAError):  # engine raises RegistryError (a SPAError)
        raised = True
    assert raised
run("Open::blocked_unknown_protocol", test_open_blocked_unknown_protocol)


# ─── Tests: Close Position ────────────────────────────────────────────────────

def test_close_open_position():
    """Закрытие открытой позиции должно убрать её из portfolio."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)
    result = trader.close_position(AAVE_USDC)
    assert result["protocol_key"] == AAVE_USDC
    assert trader.get_status()["portfolio"]["deployed_usd"] == 0.0
run("Close::position_removed_from_portfolio", test_close_open_position)

def test_close_returns_pnl():
    """close_position должен вернуть realized_pnl_usd."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)
    result = trader.close_position(AAVE_USDC)
    assert "realized_pnl_usd" in result
    assert isinstance(result["realized_pnl_usd"], float)
run("Close::returns_pnl", test_close_returns_pnl)

def test_close_frees_cash():
    """После закрытия deployed = 0."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)
    trader.close_position(AAVE_USDC)
    deployed = trader.get_status()["portfolio"]["deployed_usd"]
    assert deployed == 0.0
run("Close::frees_cash", test_close_frees_cash)

def test_close_nonexistent_raises():
    """Попытка закрыть несуществующую позицию — ValueError."""
    trader, _ = make_trader()
    raised = False
    try:
        trader.close_position(AAVE_USDC)
    except (ValueError, SPAError):  # engine raises SPAError("No open position ...")
        raised = True
    assert raised
run("Close::nonexistent_raises_value_error", test_close_nonexistent_raises)


# ─── Tests: Rebalance ─────────────────────────────────────────────────────────

def test_rebalance_healthy_portfolio_noop():
    """На здоровом портфеле rebalance не должен ничего закрывать."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_20, VALID_APY, VALID_TVL)
    actions = trader.rebalance()
    assert any(a.get("action") == "NO_OP" for a in actions)
run("Rebalance::healthy_noop", test_rebalance_healthy_portfolio_noop)

def test_rebalance_empty_portfolio_noop():
    """На пустом портфеле rebalance = NO_OP."""
    trader, _ = make_trader()
    actions = trader.rebalance()
    assert any(a.get("action") == "NO_OP" for a in actions)
run("Rebalance::empty_noop", test_rebalance_empty_portfolio_noop)


# ─── Tests: Max Safe Size ─────────────────────────────────────────────────────

def test_max_safe_size_t1():
    """Max safe size для T1 на пустом портфеле = min(40% капитала, кэш - 5%)."""
    trader, _ = make_trader()
    size = trader.max_safe_size(AAVE_USDC)
    expected = PCT_40  # min(40%, 95%) = 40%
    assert abs(size - expected) < 0.01, f"Expected ~{expected}, got {size}"
run("MaxSafe::t1_empty_portfolio", test_max_safe_size_t1)

def test_max_safe_size_decreases_with_position():
    """После открытия позиции max_safe_size должен уменьшиться."""
    trader, _ = make_trader()
    before = trader.max_safe_size(AAVE_USDC)
    trader.open_position(AAVE_USDC, PCT_20, VALID_APY, VALID_TVL)
    after = trader.max_safe_size(AAVE_USDC)
    assert after < before
run("MaxSafe::decreases_after_open", test_max_safe_size_decreases_with_position)

def test_max_safe_size_zero_at_limit():
    """max_safe_size = 0 когда достигнут концентрационный лимит."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_40, VALID_APY, VALID_TVL)  # ровно 40%
    size = trader.max_safe_size(AAVE_USDC)
    assert size == 0.0
run("MaxSafe::zero_at_limit", test_max_safe_size_zero_at_limit)


# ─── Tests: Status ────────────────────────────────────────────────────────────

def test_status_has_required_keys():
    """get_status() должен содержать все обязательные секции."""
    trader, _ = make_trader()
    s = trader.get_status()
    for key in ["timestamp", "portfolio", "positions", "risk", "paper_trading"]:
        assert key in s, f"Missing key: {key}"
run("Status::has_required_keys", test_status_has_required_keys)

def test_status_var_zero_on_empty():
    """VaR = 0 на пустом портфеле."""
    trader, _ = make_trader()
    r = trader.get_status()["risk"]
    assert r["var_usd"] == 0.0
    assert r["var_breach"] is False
run("Status::var_zero_on_empty", test_status_var_zero_on_empty)

def test_status_var_positive_with_position():
    """VaR > 0 когда есть позиции."""
    trader, _ = make_trader()
    trader.open_position(AAVE_USDC, PCT_30, VALID_APY, VALID_TVL)
    r = trader.get_status()["risk"]
    assert r["var_usd"] > 0.0
run("Status::var_positive_with_position", test_status_var_positive_with_position)


# ─── Tests: Risk policy integration ──────────────────────────────────────────

def test_t2_total_limit_enforced():
    """Суммарный лимит T2 (50%, ADR-019) должен блокировать новые T2 позиции."""
    trader, _ = make_trader()
    trader.open_position(MAPLE_USDC, PCT_20, VALID_APY, VALID_TVL)   # 20% T2
    trader.open_position(EULER_USDC, PCT_15, VALID_APY, VALID_TVL)   # 35% T2
    raised = False
    try:
        trader.open_position(YEARN_USDC, PCT_20, VALID_APY, VALID_TVL)  # +20% = 55% > 50% cap (ADR-019)
    except RiskPolicyViolation as e:
        raised = True
        assert any("T2 allocation" in v for v in e.result.violations)
    assert raised
run("RiskIntegration::t2_total_limit_enforced", test_t2_total_limit_enforced)

def test_blocked_trade_does_not_affect_portfolio():
    """Заблокированная сделка не должна изменять состояние портфеля."""
    trader, _ = make_trader()
    before = trader.get_status()["portfolio"]
    try:
        trader.open_position(AAVE_USDC, PCT_10, 50.0, VALID_TVL)  # APY слишком высокий
    except RiskPolicyViolation:
        pass
    after = trader.get_status()["portfolio"]
    assert after["deployed_usd"] == before["deployed_usd"]
    assert after["cash_usd"] == before["cash_usd"]
run("RiskIntegration::blocked_trade_no_state_change", test_blocked_trade_does_not_affect_portfolio)


# ─── Tests: Auto Allocate ─────────────────────────────────────────────────────

def test_auto_allocate_no_data_returns_no_op():
    """auto_allocate без данных APY возвращает NO_OP."""
    trader, _ = make_trader()
    actions = trader.auto_allocate()
    assert len(actions) == 1
    assert actions[0]["action"] == "NO_OP"
    assert "no_fresh_data" in actions[0]["reason"] or "no_suitable_protocol" in actions[0]["reason"]
run("AutoAllocate::no_data_returns_no_op", test_auto_allocate_no_data_returns_no_op)


# ─── Report ───────────────────────────────────────────────────────────────────

print(f"\n{'═'*62}")
print("  SPA Paper Trading — Test Suite")
print(f"{'═'*62}")
for line in _log:
    print(line)
print(f"{'─'*62}")
total = PASS + FAIL
pct = "100%" if FAIL == 0 else f"{int(PASS/total*100)}%"
print(f"  {total} tests  |  {PASS} passed  |  {FAIL} failed  |  {pct} green")
print(f"{'═'*62}\n")

if __name__ == "__main__":
    pass  # tests run at import time above
