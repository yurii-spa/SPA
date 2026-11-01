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


# ── находки ревью S3 (каждая — сценарий ревьюера, воспроизведённый на настоящих admit/apply_fill) ──

def test_two_versions_of_one_intent_in_one_set_cannot_both_be_admitted():
    book = _book(cash=100_000.0)
    v = ag.admit(book, [_intent("a", "p1", 30_000, strategy="s"), _intent("b", "p2", 30_000, strategy="s")], now=NOW)
    assert v["a"]["verdict"] == ag.ADMIT and v["b"]["verdict"] == ag.REFUSE
    assert list(book.reservations) == ["a"]                  # допущенное держит свой резерв
    assert ag.apply_fill(book, "a", 30_000)["remaining_reserved"] == 0.0


def test_unobserved_policy_or_book_state_is_not_a_match():
    book = ag.Book(nav_usd=100_000.0, cash_usd=50_000.0, positions_usd={}, policy_version=None, book_state_digest=None)
    one = _intent("a", "aave", 1_000, policy=None, digest=None)
    assert ag.admit(book, [one], now=NOW)["a"]["verdict"] == ag.REFUSE


def test_pending_withdraw_does_not_free_room_under_the_protocol_cap():
    book = _book(cash=60_000.0, positions={"aave": 40_000})
    v = ag.admit(book, [_intent("a_w", "aave", 10_000, action=contract.ACTION_WITHDRAW),
                        _intent("b_buy", "aave", 10_000, strategy="o")], now=NOW)
    assert v["a_w"]["verdict"] == ag.ADMIT and v["b_buy"]["verdict"] == ag.REFUSE   # 50% > 40%, если вывод отменят


def test_withdraw_is_not_admitted_against_an_unfilled_buy():
    book = _book()
    ag.admit(book, [_intent("buy", "aave", 10_000)], now=NOW)
    v = ag.admit(book, [_intent("w", "aave", 10_000, action=contract.ACTION_WITHDRAW, strategy="o")], now=NOW)
    assert v["w"]["verdict"] == ag.REFUSE


def test_fill_amount_must_be_positive():
    book = _book()
    ag.admit(book, [_intent("a", "aave", 10_000)], now=NOW)
    for bad in (-5_000, 0):
        try:
            ag.apply_fill(book, "a", bad)
        except ValueError:
            continue
        raise AssertionError(f"исполнение {bad} принято")
    assert book.reservations["a"]["usd"] == 10_000 and book.cash_usd == 50_000
