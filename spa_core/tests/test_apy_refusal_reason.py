"""«Фид не ответил» и «политика не пропустила» печатались ОДНИМ именем.

**Авария, которую воспроизводит этот файл** (замерена циклом #808 живым зондом с хоста,
2026-10-08, в исполнение пункта **G1** приказа владельца «Portfolio CIO» —
`docs/research/RS-portfolio-cio-diagnosis.md`, строка «живые фиды вне Ethereum +
расхождение pendle-фидов; только с хоста»).

`adapter_orchestrator._probe_adapter` ставил на ЛЮБУЮ пустую ставку один литерал::

    if not isinstance(raw_apy, (int, float)):
        record["status"] = "error"
        record["error"] = "live_feed_unavailable"

У пустой ставки истоков как минимум три, и они требуют ПРОТИВОПОЛОЖНЫХ действий:

====================================  ==========================================
исток                                 что надо делать
====================================  ==========================================
фид не ответил                        чинить фид
фид ответил, допуск не пропустил      НИЧЕГО: отказ верный, fail-CLOSED
опроса не было                        мерить (третий исход, инв. #17)
====================================  ==========================================

Живой замер 08.10 с хоста. Pendle API **ответил** — три подходящих стейблкоин-PT-рынка, —
и фильтр ADR-332 верно отбросил все три (`PT-USD3` 15.08 %, `PT-reUSD` 11.79 %,
`PT-siUSD` 10.14 %: базовые активы вне белого списка допустимых стейблов). Снимок при этом
нёс `status=error`, `error=live_feed_unavailable`, `health_score=0.0`, а сводка флота —
`grade A` при `error_count=1`.

**Вред — fail-OPEN, и он дороже красного.** Настоящий отказ фида Pendle выглядел бы в
точности как этот здоровый день: единственный сигнал «фид сломался» уже горит по
политической причине, поэтому действовать по нему нельзя, и отличить одно от другого было
НЕЧЕМ. Различие при этом адаптер ЗНАЛ: комментарий ADR-332 прямо говорит «пустой набор
из-за фильтра и пустой набор из-за сети — разные исходы», и печатал его в лог. Лога не
читает ни один артефакт, поэтому за границей адаптера оба исхода снова сливались в один.

**Поведение не меняется, меняется представление** (инвариант #17): `apy` остаётся `None`,
`status` — `error`, `live_data` — `False`, протокол по-прежнему не финансируется. Новое —
поле `apy_refused` (словарь-близнец `pool_id_refused`, ADR-239) и отдельное число сводки
`refused_by_policy_count`, которое НЕ сдвигает ни один существующий порог.

Сеть здесь не трогается ни одним тестом: оба исхода подаются ВХОДОМ (подменённый
`_pt.get_top_markets`), поэтому тест не зависит ни от живого фида, ни от его настроения.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spa_core.adapters.base_adapter import YieldInfo
from spa_core.adapters.pendle_adapter import PendleAdapter
from spa_core.adapters.pendle_pt import PendleMarketData
from spa_core.orchestrator import adapter_orchestrator as orch
from spa_core.orchestrator.health_score import compute_overall_health

#: Часы — ВХОД: `_probe_adapter(now=...)` и `compute_overall_health(now=...)` получают его
#: явно, поэтому календарь хоста на вердикт не влияет.
# FROZEN-DATE-OK: injected-clock — якорь `NOW` связан с именем, уезжает аргументом
# `now=` в `_probe_adapter`/`compute_overall_health`, и все отметки записей происходят
# от него (`RUN_TS`).
NOW = datetime(2026, 10, 8, 19, 0, tzinfo=timezone.utc)
RUN_TS = NOW.isoformat()


def _market(name, underlying, apy_pct, tvl):
    """Рынок Pendle в той форме, в которой его отдаёт низкоуровневый клиент."""
    return PendleMarketData(
        market_address="0x" + "a" * 40,
        name=name,
        underlying_asset=underlying,
        pt_apy=apy_pct,
        underlying_apy=apy_pct,
        maturity_date="2026-12-17",
        days_to_maturity=70,
        tvl_usd=tvl,
        is_expired=False,
        liquidity_usd=tvl / 10.0,
        implied_apy=apy_pct,
    )


#: Ровно те три рынка, которые живой Pendle API отдал 08.10 — и все три вне белого списка.
LIVE_INADMISSIBLE = [
    _market("PT-USD3-17DEC2026", "USD3", 15.08, 120_000_000.0),
    _market("PT-reUSD-10DEC2026", "reUSD", 11.79, 110_000_000.0),
    _market("PT-siUSD-7JAN2027", "siUSD", 10.14, 105_000_000.0),
]
ADMISSIBLE = [_market("PT-sUSDC-17DEC2026", "USDC", 6.5, 150_000_000.0)]


class _FakeLlama:
    """Второй фид (крест имён) ИНЪЕКТИРОВАН: живой DeFiLlama офлайн падает, и правило
    `.claude/rules/adapters.md` прямо требует подменять его в тестах. Пустой снимок —
    законный вход: личность пула тогда НЕ ИЗМЕРЕНА с названной причиной, а ставка от
    этого не меняется (она наблюдена своим источником)."""

    def get_pools(self, *_a, **_kw):
        return []

    def fetch_pools(self, *_a, **_kw):
        return []


def _adapter_returning(markets=None, raises=None):
    """Адаптер, чей низкоуровневый клиент подменён — сети в тесте нет вовсе."""
    a = PendleAdapter(_defillama_feed=_FakeLlama())
    a._cache = []

    def fake(**_kw):
        if raises is not None:
            raise raises
        return list(markets or [])

    a._pt.get_top_markets = fake            # type: ignore[method-assign]
    return a


class TestTheAdapterNamesWhyItsApyIsEmpty:
    def test_policy_refusal_is_named_not_called_a_dead_feed(self):
        """Сцена 08.10: фид ответил, ADR-332 отбросил всё ⇒ причина НАЗВАНА."""
        info = _adapter_returning(LIVE_INADMISSIBLE).get_yield_info()

        assert info.apy is None, "отказ должен остаться отказом — поведение не меняется"
        assert info.apy_refused == "no_admissible_underlying", info.apy_refused

    def test_unreachable_feed_is_still_named_unreachable(self):
        """Обратное направление: фид недоступен ⇒ причина ДРУГАЯ, и это не политика."""
        info = _adapter_returning(raises=OSError("connection reset")).get_yield_info()

        assert info.apy is None
        assert info.apy_refused == "feed_unreachable", info.apy_refused

    def test_feed_answered_with_nothing_is_a_third_reason(self):
        """Фид ответил пустым набором — это ни недоступность, ни политика допуска."""
        info = _adapter_returning([]).get_yield_info()

        assert info.apy_refused == "no_eligible_market", info.apy_refused

    def test_below_own_tier_floor_is_a_fourth_reason(self):
        """Допустимый рынок есть, но ниже собственного порога тира Pendle ($20M)."""
        small = [_market("PT-sUSDC-17DEC2026", "USDC", 6.5, 6_000_000.0)]
        info = _adapter_returning(small).get_yield_info()

        assert info.apy is None
        assert info.apy_refused == "below_own_tier_floor", info.apy_refused

    def test_a_live_apy_carries_no_refusal(self):
        """Положительный контроль в обратную сторону: ставка есть ⇒ причины нет."""
        info = _adapter_returning(ADMISSIBLE).get_yield_info()

        assert info.apy is not None and info.apy_refused is None

    def test_the_four_reasons_are_distinguishable_from_one_another(self):
        """Сцена несёт РАЗЛИЧИМОСТЬ, а не только исход: четыре причины — четыре имени.

        Мутант, подставляющий одно имя на все пути, прошёл бы любой тест выше по
        отдельности, если бы ожидаемое имя совпало. Здесь сравниваются ВСЕ четыре.
        """
        names = {
            "policy": _adapter_returning(LIVE_INADMISSIBLE).get_yield_info().apy_refused,
            "network": _adapter_returning(raises=OSError("x")).get_yield_info().apy_refused,
            "empty": _adapter_returning([]).get_yield_info().apy_refused,
            "tier": _adapter_returning(
                [_market("PT-sUSDC-17DEC2026", "USDC", 6.5, 6_000_000.0)]
            ).get_yield_info().apy_refused,
        }
        assert len(set(names.values())) == 4, names
        assert all(names.values()), names


class _Stub:
    """Адаптер-заглушка для оркестратора: он создаёт класс сам (`adapter_cls()`)."""

    __name__ = "StubAdapter"
    _INFO: YieldInfo | None = None

    def __init__(self):
        pass

    def get_yield_info(self):
        return type(self)._INFO


def _probe(info):
    cls = type("StubAdapter", (_Stub,), {"_INFO": info})
    return orch._run_one_adapter("stub", "T2", cls, RUN_TS, NOW)


def _info(**kw):
    base = dict(protocol="stub", asset="USDC", apy=None, tvl_usd=None, tier="T2",
                risk_score=0.4)
    base.update(kw)
    return YieldInfo(**base)


class TestTheSnapshotCarriesTheReason:
    def test_named_refusal_replaces_the_blanket_literal(self):
        rec = _probe(_info(apy_refused="no_admissible_underlying"))

        assert rec["error"] == "no_admissible_underlying", rec["error"]
        assert rec["apy_refused"] == "no_admissible_underlying"
        # Поведение money-path то же: отказ остаётся отказом.
        assert rec["status"] == "error" and rec["live_data"] is False
        assert rec["apy_pct"] is None

    def test_an_adapter_that_names_nothing_keeps_the_honest_old_name(self):
        """«Причина не названа» — тоже ответ, и он не выдумывается за адаптер."""
        rec = _probe(_info())

        assert rec["error"] == "live_feed_unavailable"
        assert rec["apy_refused"] is None, (
            "пустая причина должна остаться пустой: выдуманная причина хуже отсутствия")

    def test_the_field_is_present_on_the_happy_path_too(self):
        """Поле есть ВСЕГДА: читателю не приходится отличать «нет ключа» от «нет причины»."""
        rec = _probe(_info(apy=0.065, tvl_usd=150_000_000.0, tvl_source="live"))

        assert "apy_refused" in rec and rec["apy_refused"] is None
        assert rec["status"] == "ok" and rec["apy_pct"] == 6.5

    def test_empty_string_reason_is_not_a_reason(self):
        """Пустая строка — не причина: иначе `error` стал бы пустым и нечитаемым."""
        rec = _probe(_info(apy_refused=""))

        assert rec["apy_refused"] is None
        assert rec["error"] == "live_feed_unavailable"


class TestTheFleetSummaryHasAReader:
    """Без читателя поле — producer без потребителя, то есть прежний дефект в новой форме."""

    def test_policy_refusals_are_counted_separately(self):
        rows = [_probe(_info(apy=0.04, tvl_usd=9e7, tvl_source="live")),
                _probe(_info(apy_refused="no_admissible_underlying")),
                _probe(_info())]
        for r, name in zip(rows, ("ok_one", "pendle_like", "dead_feed")):
            r["protocol"] = name

        s = compute_overall_health(rows, now=NOW)

        assert s["error_count"] == 2, "существующее число сдвинулось — порог бы поехал"
        assert s["refused_by_policy_count"] == 1
        assert s["refused_by_policy"] == ["pendle_like"]

    def test_an_unreachable_feed_is_not_counted_as_a_policy_refusal(self):
        """Обратное направление: отказ БЕЗ названной причины в новое число не попадает."""
        rec = _probe(_info())
        rec["protocol"] = "dead_feed"

        s = compute_overall_health([rec], now=NOW)

        assert s["error_count"] == 1
        assert s["refused_by_policy_count"] == 0 and s["refused_by_policy"] == []

    def test_the_two_numbers_answer_different_questions(self):
        """`error_count` и `refused_by_policy_count` не обязаны совпадать — и это предмет.

        Мутант, считающий новое число по тому же признаку, что `error_count` (или
        равняющий их), ломает именно это утверждение.
        """
        rows = []
        for i, kw in enumerate(({"apy_refused": "no_admissible_underlying"},
                                {"apy_refused": "below_own_tier_floor"},
                                {}, {})):
            r = _probe(_info(**kw))
            r["protocol"] = f"p{i}"
            rows.append(r)

        s = compute_overall_health(rows, now=NOW)

        assert s["error_count"] == 4
        assert s["refused_by_policy_count"] == 2
        assert s["refused_by_policy"] == ["p0", "p1"]
