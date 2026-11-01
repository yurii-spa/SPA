"""S3 E6.3 (TRP-02/03): совокупный допуск набора намерений против действующих лимитов RiskConfig v1.0.

Каждый тест — отказ, который ОБЯЗАН случиться: контрольная пара показывает, что то же намерение в одиночку
допускается, т.е. отказ вызван именно совокупностью / остатком / сменой, а не дефектом заявки."""
from datetime import datetime, timedelta, timezone

from spa_core.capital_shadow import aggregate as ag
from spa_core.capital_shadow import contract
from spa_core.risk.policy import RiskConfig

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — admit(now=NOW), TTL derives from NOW
CFG = RiskConfig()


def _intent(iid, proto, usd, *, action=contract.ACTION_SUPPLY, strategy=None, ttl_h=6, policy="v1.0", digest="d1"):
    return {"intent_id": iid, "sleeve_id": "conservative", "strategy_id": strategy or iid, "action_type": action,
            "network_or_venue": proto, "notional": usd, "expires_at": (NOW + timedelta(hours=ttl_h)).isoformat(),
            "policy_version": policy, "risk_snapshot": {"book_state_digest": {"value": digest}}}


def _book(cash=50_000.0, positions=None):
    return ag.Book(nav_usd=100_000.0, cash_usd=cash, positions_usd=dict(positions or {}), policy_version="v1.0",
                   book_state_digest="d1")


def test_existing_limits_are_the_ones_used():
    assert (CFG.min_cash_pct, CFG.max_single_protocol) == (0.05, 0.40)


def test_two_individually_valid_buys_together_breach_the_cash_buffer():
    a, b = _intent("a", "aave", 30_000), _intent("b", "morpho", 20_000)
    for one in (a, b):
        assert ag.admit(_book(), [one], now=NOW)[one["intent_id"]]["verdict"] == ag.ADMIT
    v = ag.admit(_book(), [a, b], now=NOW)
    assert v["a"]["verdict"] == ag.ADMIT
    assert v["b"]["verdict"] == ag.REFUSE and "буфера" in v["b"]["why"]


def test_two_individually_valid_buys_together_breach_the_protocol_cap():
    a, b = _intent("a", "aave", 25_000), _intent("b", "aave", 20_000, strategy="other")
    book = _book(positions={"aave": 0.0})
    assert ag.admit(_book(), [b], now=NOW)["b"]["verdict"] == ag.ADMIT
    v = ag.admit(book, [a, b], now=NOW)
    assert v["a"]["verdict"] == ag.ADMIT and v["b"]["verdict"] == ag.REFUSE and "потолка" in v["b"]["why"]


def test_partial_fill_keeps_the_unfilled_remainder_reserved():
    book = _book()
    a = _intent("a", "aave", 30_000)
    assert ag.admit(book, [a], now=NOW)["a"]["verdict"] == ag.ADMIT
    assert ag.apply_fill(book, "a", 10_000)["remaining_reserved"] == 20_000
    assert (book.cash_usd, book.positions_usd["aave"]) == (40_000, 10_000)
    b = _intent("b", "morpho", 20_000)
    assert ag.admit(_book(cash=40_000, positions={"aave": 10_000}), [b], now=NOW)["b"]["verdict"] == ag.ADMIT
    assert ag.admit(book, [b], now=NOW)["b"]["verdict"] == ag.REFUSE        # остаток 20k держит кэш


def test_expiry_and_cancel_release_the_reservation():
    book = _book()
    ag.admit(book, [_intent("a", "aave", 30_000, ttl_h=1)], now=NOW)
    b = _intent("b", "morpho", 20_000, ttl_h=8)
    assert ag.admit(book, [b], now=NOW)["b"]["verdict"] == ag.REFUSE
    later = NOW + timedelta(hours=2)
    v = ag.admit(book, [b], now=later)
    assert v["b"]["verdict"] == ag.ADMIT and v["_released"]["ids"] == ["a"]
    book2 = _book()
    ag.admit(book2, [_intent("a", "aave", 30_000)], now=NOW)
    assert ag.admit(book2, [b], now=NOW, cancelled=("a",))["b"]["verdict"] == ag.ADMIT


def test_changed_intent_supersedes_the_old_reservation_instead_of_adding_to_it():
    book = _book()
    ag.admit(book, [_intent("a1", "aave", 30_000, strategy="s")], now=NOW)
    v = ag.admit(book, [_intent("a2", "aave", 35_000, strategy="s")], now=NOW)
    assert v["a2"]["verdict"] == ag.ADMIT and list(book.reservations) == ["a2"]


def test_changed_policy_or_book_refuses_reservations_built_on_the_old_one():
    for kw in ({"policy": "v1.1"}, {"digest": "d2"}):
        one = _intent("a", "aave", 1_000, **kw)
        v = ag.admit(_book(), [one], now=NOW)["a"]
        assert v["verdict"] == ag.REFUSE and v["state"] == contract.S_RISK_BLOCKED
    assert ag.admit(_book(), [_intent("a", "aave", 1_000)], now=NOW)["a"]["verdict"] == ag.ADMIT


def test_expired_intent_is_refused_even_alone():
    v = ag.admit(_book(), [_intent("a", "aave", 1_000, ttl_h=-1)], now=NOW)["a"]
    assert v["verdict"] == ag.REFUSE and v["state"] == contract.S_EXPIRED


def test_unobserved_book_state_refuses_everything_not_zero():
    book = ag.Book(nav_usd=None, cash_usd=50_000.0, positions_usd={}, policy_version="v1.0", book_state_digest="d1")
    assert ag.admit(book, [_intent("a", "aave", 1)], now=NOW)["a"]["verdict"] == ag.REFUSE


def test_withdraw_beyond_position_plus_reserves_is_refused():
    book = _book(positions={"aave": 10_000})
    v = ag.admit(book, [_intent("w1", "aave", 6_000, action=contract.ACTION_WITHDRAW),
                        _intent("w2", "aave", 6_000, action=contract.ACTION_WITHDRAW, strategy="o")], now=NOW)
    assert v["w1"]["verdict"] == ag.ADMIT and v["w2"]["verdict"] == ag.REFUSE


def test_order_of_arrival_does_not_change_the_verdict():
    a, b = _intent("a", "aave", 30_000), _intent("b", "morpho", 20_000)
    assert ag.admit(_book(), [a, b], now=NOW) == ag.admit(_book(), [b, a], now=NOW)
