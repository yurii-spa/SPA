"""RT-05 сравнивает книгу только с тем, что гейт МОЖЕТ профинансировать (ADR-274).

Положительный контроль — замер 2026-09-08: `data/rebalance_trigger.json` каждый день
показывал `rt05.triggered=true, best_protocol=moonwell_base, best_apy_pct=14.0284`
при TVL этого пула $78 192 и поле RiskPolicy $5 000 000. Пул, который гейт не пропустит
никогда, делал вердикт REBALANCE ежедневным, и настоящий сигнал (RT-01 дрейф) был неразличим.

Второй замер, 09.09: живой TVL нельзя брать из `adapter_status.json` — два артефакта
ОДНОГО прогона расходятся о происхождении одного числа (`aave_v3`: там 12 000 000 000
«static», у оркестратора 146 775 249 «live»). Гейт по ADR-053 читает снимок ОРКЕСТРАТОРА,
и фильтр по локальному полю отбросил бы девять пулов, включая проходимый, — отказ в
неверную сторону, прячущий сигнал.

# FROZEN-DATE-OK: historical-incident — числа и даты 08–09.09 и есть предмет теста
# (воспроизведение конкретного ложного сигнала); часов в файле нет.
"""
from __future__ import annotations

from spa_core.paper_trading.rebalance_trigger import (
    RebalanceTrigger,
    _live_tvl_by_protocol,
    _observed_apys,
)

FLOOR = 5_000_000.0

# Срез `data/adapter_status.json` 2026-09-08 17:27 UTC: ставка наблюдалась у трёх из четырёх.
STATUS = {"adapters": {
    "moonwell_base": {"live_apy": 14.0284, "live_apy_fresh": True},
    "pendle_pt_susde": {"live_apy": 4.86, "live_apy_fresh": True},
    "compound_v3": {"live_apy": 4.6454, "live_apy_fresh": True},
    "pendle": {"live_apy": None, "live_apy_fresh": False, "fallback_apy": 8.0},
}}
# Снимок оркестратора того же прогона: живой TVL есть только у compound_v3 и moonwell_base,
# и у второго он ниже пола. pendle_pt_susde оркестратор не опрашивал вовсе.
ORCH = {"adapters": [
    {"protocol": "compound_v3", "tvl_usd": 35_931_234.0, "tvl_source": "live"},
    {"protocol": "moonwell_base", "tvl_usd": 78_192.0, "tvl_source": "live"},
    {"protocol": "aave_v3", "tvl_usd": 146_775_249.0, "tvl_source": "live"},
]}


def test_pools_below_the_floor_are_not_part_of_the_universe():
    dropped: list = []
    got = _observed_apys(STATUS, tvl_floor_usd=FLOOR,
                         live_tvl_by_protocol=_live_tvl_by_protocol(ORCH), dropped=dropped)
    assert got == {"compound_v3": 4.6454}
    assert sorted(dropped) == ["moonwell_base", "pendle_pt_susde"]


def test_a_protocol_the_orchestrator_never_measured_is_not_an_alternative():
    """ADR-053 fail-CLOSED: живого TVL не измерял никто ⇒ пул не альтернатива."""
    got = _observed_apys(STATUS, tvl_floor_usd=FLOOR,
                         live_tvl_by_protocol=_live_tvl_by_protocol(ORCH))
    assert "pendle_pt_susde" not in got


def test_static_tvl_never_passes_the_floor():
    """Замер 09.09: `adapter_status` зовёт литерал 12 млрд «static» — в карту он не попадает."""
    orch = {"adapters": [{"protocol": "aave_v3", "tvl_usd": 12_000_000_000.0,
                          "tvl_source": "static"}]}
    assert _live_tvl_by_protocol(orch) == {}


def test_the_orchestrator_is_the_source_of_the_floor_not_adapter_status():
    """Контроль на отказ в НЕВЕРНУЮ сторону: пул, чей локальный TVL «static», но у
    оркестратора живой и выше пола, ОСТАЁТСЯ в наборе — иначе фильтр спрятал бы сигнал."""
    status = {"adapters": {"aave_v3": {"live_apy": 3.61, "live_apy_fresh": True,
                                       "tvl_usd": 12_000_000_000.0, "tvl_source": "static"}}}
    got = _observed_apys(status, tvl_floor_usd=FLOOR,
                         live_tvl_by_protocol=_live_tvl_by_protocol(ORCH))
    assert got == {"aave_v3": 3.61}


def test_without_the_map_the_floor_is_not_applied_and_the_caller_must_say_so():
    """Карты нет ⇒ пол не применяется молча внутри — назвать это обязан вызывающий."""
    got = _observed_apys(STATUS, tvl_floor_usd=FLOOR)
    assert set(got) == {"moonwell_base", "pendle_pt_susde", "compound_v3"}


def test_rt05_no_longer_fires_on_the_2026_09_08_universe():
    """Тот же день, та же книга (5.0586 %) — с полом сигнала нет."""
    t = RebalanceTrigger()
    before = t.check_rt05_apy_spread(5.0586, _observed_apys(STATUS))
    after = t.check_rt05_apy_spread(
        5.0586, _observed_apys(STATUS, tvl_floor_usd=FLOOR,
                               live_tvl_by_protocol=_live_tvl_by_protocol(ORCH)))
    assert before["triggered"] is True and before["best_protocol"] == "moonwell_base"
    assert after["triggered"] is False, after


def test_rt05_still_fires_on_a_pool_that_actually_passes_the_gate():
    """Контроль неослабления: проходимый пул, реально доходнее книги, срабатывает."""
    status = {"adapters": dict(STATUS["adapters"],
                               big_and_rich={"live_apy": 9.5, "live_apy_fresh": True})}
    orch = {"adapters": ORCH["adapters"] + [
        {"protocol": "big_and_rich", "tvl_usd": 200_000_000.0, "tvl_source": "live"}]}
    r = RebalanceTrigger().check_rt05_apy_spread(
        5.0586, _observed_apys(status, tvl_floor_usd=FLOOR,
                               live_tvl_by_protocol=_live_tvl_by_protocol(orch)))
    assert r["triggered"] is True and r["best_protocol"] == "big_and_rich"
    assert r["spread_pct"] > 1.5


def test_an_empty_universe_is_not_a_silent_pass():
    """Пустая вселенная не имеет права выглядеть как «сравнили и всё в порядке»."""
    orch = {"adapters": [{"protocol": "only_small", "tvl_usd": 1_000.0, "tvl_source": "live"}]}
    status = {"adapters": {"only_small": {"live_apy": 12.0, "live_apy_fresh": True}}}
    dropped: list = []
    got = _observed_apys(status, tvl_floor_usd=FLOOR,
                         live_tvl_by_protocol=_live_tvl_by_protocol(orch), dropped=dropped)
    assert got == {} and dropped == ["only_small"]
    r = RebalanceTrigger().check_rt05_apy_spread(5.0586, got)
    assert r["triggered"] is False
    assert r.get("measured") is False or r.get("unmeasured_reason"), r
