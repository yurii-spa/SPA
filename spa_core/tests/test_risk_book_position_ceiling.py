"""ADR-902 (решение владельца 02.11, ADR-901 п. 8, вариант A): проверка КНИГИ спрашивает потолок числа
профинансированных протоколов ``max_protocols`` (ALLOC-002, 8) — тот же единственный порог, что зеркалит тюнер.
Контроль в обе стороны: 9 протоколов — нарушение, 8 — нет; ответ — HALT_NEW, не распродажа."""
import math

from spa_core.risk.policy import (RESPONSE_ALL_CASH, RESPONSE_HALT_NEW, PortfolioState, Position, RiskConfig,
                                  RiskPolicy)

CEIL = "exceed ALLOC-002 limit"


def _book(n, amount=9_000.0, extra=()):
    pos = [Position(protocol_key=f"p{i}", tier="T1", asset="USDC", amount_usd=amount, apy_at_open=5.0,
                    current_apy=5.0) for i in range(n)]
    return PortfolioState(total_capital_usd=100_000.0, positions=pos + list(extra))


def _ceiling(res):
    return [v for v in res.violations if CEIL in v]


def test_the_threshold_is_the_single_config_field():
    assert RiskConfig().max_protocols == 8


def test_nine_funded_protocols_violate_eight_do_not():
    pol = RiskPolicy()
    nine = pol.check_portfolio_health(_book(9))
    eight = pol.check_portfolio_health(_book(8))
    assert _ceiling(nine) == ["Funded protocols 9 exceed ALLOC-002 limit 8"]
    assert _ceiling(eight) == []
    assert nine.approved is False and nine.required_response == RESPONSE_HALT_NEW   # не распродажа
    assert nine.required_response != RESPONSE_ALL_CASH


def test_zero_positions_do_not_count_and_unmeasured_amounts_do():
    pol = RiskPolicy()
    zero = Position(protocol_key="closed", tier="T1", asset="USDC", amount_usd=0.0, apy_at_open=5.0, current_apy=5.0)
    assert _ceiling(pol.check_portfolio_health(_book(8, extra=[zero]))) == []
    nan = Position(protocol_key="unknown", tier="T1", asset="USDC", amount_usd=math.nan, apy_at_open=5.0,
                   current_apy=5.0)
    assert _ceiling(pol.check_portfolio_health(_book(8, extra=[nan]))) != []          # «не измерено» ≠ «нет позиции»


def test_two_lots_of_one_protocol_are_one_protocol():
    pol = RiskPolicy()
    dup = Position(protocol_key="p0", tier="T1", asset="USDC", amount_usd=1_000.0, apy_at_open=5.0, current_apy=5.0)
    assert _ceiling(pol.check_portfolio_health(_book(8, extra=[dup]))) == []


def test_the_threshold_is_read_from_the_config_not_a_copy():
    pol = RiskPolicy(RiskConfig(max_protocols=9))
    assert _ceiling(pol.check_portfolio_health(_book(9))) == []
