"""Порог TVL — ОДНО определение на всех читателей (карточка 07.08, доставка 08.08).

Находка карточки `inbox-atributsiya-kesha-i-geit-riskpolicy-po-r`, перемеренная на
живых артефактах 2026-08-08 12:33Z:

* `capital_efficiency.json` печатал `aerodrome_usdc_lp(+20% @ 8.5%)` — при
  `tvl_usd = 0.0`, `tvl_source = "static"`, `live_apy = null`: ни доходности, ни
  размера, а комната стоит в списке «пригодной»;
* там же `moonwell_base` при TVL **$1 410 774** против порога RiskPolicy **$5M** —
  пул, который аллокатор ОТФИЛЬТРОВАЛ (`_filter_by_tvl`, MP-011), числился в
  комнате, которую аллокатору вменяют как лень.

Обе половины работают в одну сторону — ЗАВЫШАЮТ пригодную комнату, то есть завышают
`unexplained_deployable`, число, по которому `agent_health` обвиняет аллокатор.
Ложное обвинение обесценивает настоящее.

Каждый тест ниже — положительный контроль: он краснеет на коде ДО починки (проверено
мутациями, см. журнал 2026-W32). Пороги RiskPolicy здесь ВХОД, ни один тест их не
меняет; живой трек, kill-switch и гейт не тронуты.
"""
from __future__ import annotations

import json
import math

import pytest

from spa_core.allocator.allocator import StrategyAllocator
from spa_core.allocator.rebalance_economics import attribute_cash
from spa_core.tests._freshness import ts
from spa_core.risk.tvl_floor import (
    coerce_tvl,
    floor_is_resolved,
    floor_reason,
    passes_tvl_floor,
)

FLOOR = 5_000_000.0


# ── 1. само правило ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    (10_000_000.0, True),
    (FLOOR, True),            # РОВНО на пороге проходит — как у аллокатора и policy.py
    (FLOOR - 0.01, False),
    (1_410_774.0, False),     # живой moonwell_base 08.08
    (0.0, False),
    (None, False),            # «не измерено» никогда не значит «пригоден»
    (-1.0, False),
    ("не число", False),
    (float("nan"), False),
    (float("inf"), False),    # inf >= floor прошёл бы численно — и уехал бы в money-path
])
def test_floor_rule(raw, expected) -> None:
    assert passes_tvl_floor(raw, FLOOR) is expected


def test_unresolved_floor_never_passes_anything() -> None:
    """Порога нет ⇒ вопрос НЕ измерен. Не «пропустить на всякий случай»."""
    assert floor_is_resolved(None) is False
    assert passes_tvl_floor(10_000_000_000.0, None) is False
    ok, why = floor_reason(10_000_000_000.0, None)
    assert (ok, why) == (False, "tvl_floor_unresolved")


def test_reason_distinguishes_unmeasured_from_measured_and_small() -> None:
    """Две разные болезни: одну лечит фид, вторая — честный отказ по политике."""
    assert floor_reason(None, FLOOR) == (False, "tvl_unmeasured")
    assert floor_reason(0.0, FLOOR) == (False, "tvl_unmeasured")
    assert floor_reason(float("nan"), FLOOR) == (False, "tvl_non_finite")
    ok, why = floor_reason(1_410_774.0, FLOOR)
    assert ok is False
    assert why == "tvl_below_floor:$1,410,774<$5,000,000"
    assert floor_reason(6_000_000.0, FLOOR) == (True, "")


def test_coercion_matches_the_allocator_none_is_zero_junk_is_nan() -> None:
    assert coerce_tvl(None) == 0.0
    assert math.isnan(coerce_tvl(object()))
    assert coerce_tvl("7") == 7.0


# ── 2. КОНФОРМАНС: у аллокатора и у общего правила один и тот же вердикт ────
# Это и есть «один источник истины»: если кто-то тронет одну сторону, тест краснеет.

@pytest.mark.parametrize("raw", [
    10_000_000.0, FLOOR, FLOOR - 1.0, 1_410_774.0, 402_000.0, 0.0, 100.0,
    None, "не число", float("nan"), float("inf"), -5.0,
])
def test_allocator_and_shared_rule_agree_pool_by_pool(raw) -> None:
    alloc = StrategyAllocator()
    assert alloc.TVL_FLOOR_USD == FLOOR, "порог аллокатора разошёлся с RiskPolicy"
    # ВАЖНО: в списке всегда есть заведомо проходной пул — иначе сработает
    # fallback «не возвращать пустую вселенную» и мы сравним не вердикты, а его.
    pools = [{"protocol": "probe", "tvl_usd": raw},
             {"protocol": "anchor", "tvl_usd": 8_000_000_000.0}]
    ok, rejected = alloc._filter_by_tvl(pools)
    allocator_says = "probe" in {p["protocol"] for p in ok}
    assert allocator_says is not ("probe" in rejected)
    assert passes_tvl_floor(raw, alloc.TVL_FLOOR_USD) is allocator_says, (
        "определение порога разошлось: аллокатор={} общее правило={}".format(
            allocator_says, passes_tvl_floor(raw, alloc.TVL_FLOOR_USD)))


# ── 3. атрибуция кэша: комната ниже порога больше не «пригодна сегодня» ────
# Книга — живая 08.08: aave_v3 40k / pendle 20k / maple 10k / morpho 5k, кэш 25k.

BOOK = {"aave_v3": 40_000.0, "pendle": 20_000.0,
        "maple": 10_000.0, "morpho_steakhouse": 5_000.0}
APY = {"aave_v3": 5.0, "pendle": 15.5, "maple": 4.9, "morpho_steakhouse": 3.4,
       "moonwell_base": 5.8969, "frax": 7.5}
SRC = {k: "live" for k in APY}
TIERS = {"aave_v3": "T1", "morpho_steakhouse": "T1", "pendle": "T2",
         "maple": "T2", "moonwell_base": "T2", "frax": "T2"}
CAPS = {p: (0.40 if t == "T1" else 0.20) for p, t in TIERS.items()}
# Размеры — живые: moonwell под порогом, frax над ним.
TVL = {"aave_v3": 8_000_000_000.0, "pendle": 500_000_000.0, "maple": 50_000_000.0,
       "morpho_steakhouse": 100_000_000.0, "moonwell_base": 1_410_774.0,
       "frax": 100_000_000.0}


def _attr(**kw):
    kw.setdefault("positions", BOOK)
    kw.setdefault("capital_usd", 100_000.0)
    kw.setdefault("min_cash_frac", 0.05)
    kw.setdefault("apy_pct", APY)
    kw.setdefault("apy_sources", SRC)
    kw.setdefault("tvl_live", set(APY))
    kw.setdefault("tier_caps", CAPS)
    kw.setdefault("tiers", TIERS)
    kw.setdefault("t2_total_cap", 0.50)
    kw.setdefault("t3_total_cap", 0.15)
    kw.setdefault("min_apy_pct", 1.0)
    kw.setdefault("tvl_usd", TVL)
    kw.setdefault("min_tvl_usd", FLOOR)
    return attribute_cash(**kw)


def _kinds(res):
    return {c["kind"]: c for c in res["components"]}


def _why(res, proto):
    return next((r["why"] for r in res["ineligible_rooms"]
                 if r["protocol"] == proto), None)


def test_below_floor_pool_leaves_fundable_and_is_named() -> None:
    res = _attr()
    fundable = " ".join(_kinds(res)["unexplained_deployable"].get("protocols", []))
    assert "moonwell_base" not in fundable, (
        "пул ниже порога снова числится пригодным сегодня")
    # …и ушёл НЕ молча: причина публикуется всегда, а не только когда до бакета
    # (г) дошли доллары (молчаливый ретайр — то, что карточка запрещает).
    assert _why(res, "moonwell_base") == ["tvl_below_floor:$1,410,774<$5,000,000"]


def test_ineligibility_is_published_even_when_the_waterfall_never_reaches_it() -> None:
    """Положительный контроль на само это свойство.

    Пригодной комнаты хватает с избытком, поэтому все доллары уходят в (д) и
    компонент `insufficient_eligible_live` не появляется вовсе — а причина
    непригодности всё равно обязана быть на виду.
    """
    res = _attr()
    assert "insufficient_eligible_live" not in _kinds(res)
    assert any(r["protocol"] == "moonwell_base" for r in res["ineligible_rooms"])
    assert res["ineligible_rooms"][0]["room_usd"] > 0


def test_the_real_alarm_survives_positive_control() -> None:
    """Главный контроль: это НЕ глушение сигнала.

    frax (TVL $100M, APY 7.5 %) остаётся пригодным, поэтому простой по-прежнему
    UNEXPLAINED_CASH. Починка убирает ЛОЖНЫЕ строки, а не тревогу.
    """
    res = _attr()
    assert res["status"] == "UNEXPLAINED_CASH"
    comp = _kinds(res)["unexplained_deployable"]
    assert comp["usd"] > 0
    assert any(p.startswith("frax") for p in comp["protocols"])
    assert comp["forgone_bps_yr"] > 0, "цена простоя обязана считаться и показываться"


def test_pool_exactly_at_the_floor_stays_fundable() -> None:
    """Контроль в обратную сторону: порог не «сползает» вверх."""
    res = _attr(tvl_usd={**TVL, "frax": FLOOR})
    assert any(p.startswith("frax")
               for p in _kinds(res)["unexplained_deployable"]["protocols"])


def test_unmeasured_tvl_is_not_eligible_by_default() -> None:
    res = _attr(tvl_usd={**TVL, "frax": None})
    assert _why(res, "frax") == ["tvl_unmeasured"]
    assert not any(p.startswith("frax")
                   for p in _kinds(res)["unexplained_deployable"]["protocols"])


# ── 4. fail-CLOSED: нет порога / нет размеров ⇒ UNCHECKED, а не «объяснено» ──

@pytest.mark.parametrize("missing", [{"min_tvl_usd": None}, {"tvl_usd": None}])
def test_missing_floor_inputs_are_unchecked_never_silently_explained(missing) -> None:
    res = _attr(**missing)
    assert res["status"] == "attribution_incomplete"
    assert "tvl_floor_unresolved" in res["unchecked"]
    assert res["unexplained_pct"] is None, "честно неизвестно — это НЕ ноль"
    # и обратная сторона: молчания не случилось — простой не выглядит объяснённым
    assert res["status"] != "explained"


def test_missing_inputs_do_not_empty_the_fundable_set_silently() -> None:
    """Почему проверка функциональная, а не только по-протокольная.

    Если бы «нет размера» решалось только по-протокольно, пропавшая карта TVL
    опустошила бы fundable, простой стал бы «объяснён» и тревога ЗАМОЛЧАЛА бы от
    потери входа, а не от улучшения книги. Такое тут запрещено.
    """
    res = _attr(tvl_usd=None)
    assert res["status"] != "explained"
    assert any(c["status"] == "UNCHECKED" for c in res["components"])


# ── 5. проводка, а не только детали (урок цикла #144) ──────────────────────
# Каждый тест выше проверяет ДЕТАЛЬ. 07.08 удаление ОДНОЙ строки проводки
# оставило 22 своих и 1342 соседних теста зелёными, пока фича была мертва в
# проде. Поэтому размер TVL проверяется ещё и НА ВСЁМ ПУТИ: аллокатор → отчёт
# фидов → цикл → атрибуция.

def test_allocator_publishes_the_tvl_it_filters_on(tmp_path) -> None:
    """Аллокатор обязан ОТДАВАТЬ наружу тот же размер, на котором сам фильтрует.

    Иначе читателю снова придётся заводить вторую копию определения — ровно то,
    из-за чего пул ниже порога числился «пригодным».
    """
    snap = tmp_path / "adapter_orchestrator_status.json"
    # отметка ОТНОСИТЕЛЬНАЯ (правило .claude/rules/deployment.md, предпочтение №2):
    # снимок судят по свежести, а литеральная дата в такой фикстуре — бомба
    # замедленного действия, падающая от сдвига календаря, а не от поведения.
    snap.write_text(json.dumps({"generated_at": ts(hours_ago=1), "adapters": [
        {"protocol": "aave_v3", "apy_pct": 5.0, "tvl_usd": 8_000_000_000.0,
         "tvl_source": "live", "tier": "T1", "status": "ok"},
        {"protocol": "moonwell_base", "apy_pct": 5.9, "tvl_usd": 1_410_774.0,
         "tvl_source": "live", "tier": "T2", "status": "ok"},
    ]}), encoding="utf-8")
    a = StrategyAllocator(status_path=snap, registry_path=tmp_path / "_no_reg.json",
                          strategy_loop_enabled=False, live_apy_provider={})
    cov = a.allocate(model="equal_weight").feed_coverage

    assert "tvl_usd" in cov, "аллокатор снова не публикует РАЗМЕР TVL"
    assert cov["tvl_usd"]["moonwell_base"] == 1_410_774.0
    assert cov["tvl_usd"]["aave_v3"] == 8_000_000_000.0
    # и опубликованный размер согласуется с собственным фильтром аллокатора
    for proto, tvl in cov["tvl_usd"].items():
        pools = [{"protocol": proto, "tvl_usd": tvl},
                 {"protocol": "anchor", "tvl_usd": 8e9}]
        ok, _ = a._filter_by_tvl(pools)
        assert (proto in {p["protocol"] for p in ok}) is passes_tvl_floor(
            tvl, a.TVL_FLOOR_USD)


def test_cycle_carries_the_tvl_size_all_the_way_into_the_artifact(tmp_path) -> None:
    """Сборка целиком: убери строку `tvl_usd=` в cycle_runner — тест краснеет.

    Проверяется ЭФФЕКТ, а не наличие строки: атрибуция в артефакте не имеет права
    сказать «порог не измерен», когда аллокатор размер отдал.
    """
    from types import SimpleNamespace

    from spa_core.paper_trading import cycle_runner as _cr
    from spa_core.telegram import push_policy

    # транспорт Telegram заглушён (песочница не пишет владельцу); ни один гейт
    # при этом не ослаблен — как в test_cash_attribution_policy_refusals.py
    _sent: list = []
    push_policy._send, _orig = (lambda text: _sent.append(text) or True), push_policy._send
    try:
        universe = [
            {"protocol": "aave_v3", "id": "aave_v3", "apy_pct": 5.0,
             "tvl_usd": 65_727_775.0, "tvl_source": "live", "tier": "T1",
             "status": "ok", "chain": "ethereum"},
            {"protocol": "moonwell_base", "id": "moonwell_base", "apy_pct": 5.8969,
             "tvl_usd": 1_410_774.0, "tvl_source": "live", "tier": "T2",
             "status": "ok", "chain": "base"},
        ]
        target = {"aave_v3": 40_000.0}
        (tmp_path / "current_positions.json").write_text(
            json.dumps({"positions": {}, "cash_usd": 100_000.0}), encoding="utf-8")

        # feed_coverage живёт на РЕЗУЛЬТАТЕ аллокации (AllocationResult), а не на
        # аллокаторе — цикл читает именно его; форма скопирована с прода.
        _cov = {"tvl_sources": {p["protocol"]: "live" for p in universe},
                "tvl_usd": {p["protocol"]: p["tvl_usd"] for p in universe}}

        class _Alloc:
            def allocate(self):
                return SimpleNamespace(
                    target_usd=dict(target),
                    target_weights={p: v / 100_000.0 for p, v in target.items()},
                    expected_apy_pct=5.0, model_used="optimized_yield",
                    strategy_loop_active=False, feed_coverage=dict(_cov),
                    apy_sources={p["protocol"]: "live" for p in universe},
                    apy_used={p["protocol"]: p["apy_pct"] for p in universe})

        _cr.run_cycle(
            data_dir=str(tmp_path),
            orchestrator_fn=lambda _d: SimpleNamespace(
                adapters=universe, status="ok", data_freshness="live"),
            allocator=_Alloc(),
            risk_scorer_fn=lambda d: None,
            track_persister_fn=lambda d: None,
            write=True,
            allow_live_write=False,
        )
    finally:
        push_policy._send = _orig

    cash = json.loads((tmp_path / "allocation_rationale.json").read_text())["cash"]
    assert "tvl_floor_unresolved" not in (cash.get("unchecked") or []), (
        "размер TVL не доехал через цикл до атрибуции — проводка порвана")
    # и порог реально применился по дороге, а не «доехал и лёг»
    assert any(r["protocol"] == "moonwell_base"
               and any(w.startswith("tvl_below_floor") for w in r["why"])
               for r in cash.get("ineligible_rooms") or []), cash.get("ineligible_rooms")


# ── 6. capital_efficiency: то, что читает ВЛАДЕЛЕЦ ─────────────────────────
# Замер 08.08 на живых артефактах: в headroom стояли aerodrome_usdc_lp
# (tvl_usd 0.0, tvl_source "static", live_apy null — фид мёртв целиком, а 8.5 %
# печатается как возможность) и moonwell_base (TVL $1.41M против порога $5M).

def _ce(monkeypatch, rows, *, cash_pct=0.25, positions=None):
    import spa_core.monitoring.capital_efficiency as ce
    pos = {"capital_usd": 100_000.0, "cash_usd": cash_pct * 100_000.0,
           "deployed_usd": (1 - cash_pct) * 100_000.0,
           "positions": positions or [{"protocol": "aave_v3", "usd": 40_000}]}

    def fake_load(p):
        s_ = str(p)
        if s_.endswith("current_positions.json"):
            return pos
        if s_.endswith("apy_ranking.json"):
            return {"by_apy": rows}
        return None   # нет свежей атрибуции ⇒ работает легаси-эвристика

    monkeypatch.setattr(ce, "_load", fake_load)
    return ce


AERODROME = {"protocol": "aerodrome_usdc_lp", "tier": "T2", "apy_pct": 8.5,
             "tvl_usd": 0.0}
MOONWELL = {"protocol": "moonwell_base", "tier": "T2", "apy_pct": 5.8969,
            "tvl_usd": 1_410_774.0}
FRAX = {"protocol": "frax", "tier": "T2", "apy_pct": 7.5, "tvl_usd": 100_000_000.0}


def test_dead_feed_and_below_floor_leave_headroom_with_the_reason_named(
        monkeypatch) -> None:
    ce = _ce(monkeypatch, [AERODROME, MOONWELL, FRAX])
    r = ce.assess()
    joined = " ".join(r["headroom_contributors"])
    assert "aerodrome_usdc_lp" not in joined, "мёртвый фид снова в пригодной комнате"
    assert "moonwell_base" not in joined, "пул ниже порога снова в пригодной комнате"
    assert "frax" in joined, "живой пул выше порога обязан остаться"
    excl = " ".join(r["headroom_excluded"])
    assert "aerodrome_usdc_lp" in excl and "tvl_unmeasured" in excl
    assert "moonwell_base(+20% @ 5.9%): tvl_below_floor:$1,410,774<$5,000,000" in excl
    assert r["min_tvl_usd"] == FLOOR


def test_the_alarm_and_its_price_survive(monkeypatch) -> None:
    """Положительный контроль: тревога и цена простоя остаются."""
    r = _ce(monkeypatch, [AERODROME, MOONWELL, FRAX]).assess()
    assert r["verdict"] == "WARNING"
    assert r["forgone_yield_bps_est"] > 0
    # …и считается по ЖИВОЙ доходности (7.5 frax), а не по мёртвой (8.5 aerodrome)
    assert r["best_qualifying_apy_pct"] == pytest.approx(7.5)


def test_headroom_only_in_size_unmeasured_pools_is_unknown_not_ok(monkeypatch) -> None:
    """Дыра в наблюдении ≠ структурная причина.

    Комната осталась только у пулов с ненаблюдённым размером. Тихое «headroom=0
    ⇒ OK» объявило бы непомеренное правильным решением держать кэш — это и есть
    гашение тревоги потерей входа.
    """
    r = _ce(monkeypatch, [AERODROME]).assess()
    assert r["verdict"] == "UNKNOWN", r
    assert "aerodrome_usdc_lp" in r["headroom_size_unmeasured"]
    assert "never observed" in r["reason"]


def test_measured_and_small_is_structural_and_stays_honest_ok(monkeypatch) -> None:
    """Контроль в обратную сторону: измеренный маленький пул — честный отказ.

    Тут держать кэш ПРАВИЛЬНО, и вердикт обязан это сказать, а не UNKNOWN —
    иначе мы бы просто заменили ложную тревогу на вечное «не знаю».
    """
    r = _ce(monkeypatch, [MOONWELL]).assess()
    assert r["verdict"] == "OK", r
    assert r["headroom_size_unmeasured"] == []


def test_unresolved_floor_is_unknown_never_ok(monkeypatch) -> None:
    ce = _ce(monkeypatch, [FRAX])
    monkeypatch.setattr(ce, "_config", lambda: {
        "min_cash_pct": 0.05, "t1_cap": 0.4, "t2_cap": 0.2, "min_apy": 1.0,
        "min_tvl_usd": None})
    r = ce.assess()
    assert r["verdict"] == "UNKNOWN", r
    assert "TVL floor unresolved" in r["reason"]


def test_empty_tvl_map_over_a_real_universe_is_unchecked_not_explained() -> None:
    """Пустая карта размеров — это «посмотреть не смогли», а не «ничего не годится».

    Оставь её как есть — и КАЖДЫЙ пул станет непригодным, простой станет
    «объяснённым», а тревога замолчит. Тишина, купленная потерей входа.
    """
    res = _attr(tvl_usd={})
    assert res["status"] == "attribution_incomplete"
    assert "tvl_floor_unresolved" in res["unchecked"]
    assert res["unexplained_pct"] is None


def test_empty_allocator_map_does_not_fall_back_to_the_snapshot(tmp_path) -> None:
    """Пустая карта аллокатора НЕ отправляет писателя ко второму определению.

    Снимок здесь СУЩЕСТВУЕТ и говорит «$8 млрд» — если писатель уйдёт к нему,
    пул станет пригодным по источнику, которого аллокатор не подтверждал. Это и
    есть та вторая копия определения, из-за которой карточка была заведена.
    Запасной путь остаётся только для «карты не дали вовсе» (None).
    """
    from spa_core.paper_trading.allocation_rationale import write_shadow_rationale

    (tmp_path / "adapter_orchestrator_status.json").write_text(json.dumps({
        "generated_at": ts(hours_ago=1),
        "adapters": [{"protocol": "aave_v3", "tvl_usd": 8_000_000_000.0}],
    }), encoding="utf-8")

    doc = write_shadow_rationale(
        data_dir=tmp_path,
        current_positions={"aave_v3": 10_000.0}, target_positions={"aave_v3": 10_000.0},
        apy_pct={"aave_v3": 5.0}, apy_sources={"aave_v3": "live"},
        tvl_sources={"aave_v3": "live"},
        tvl_usd={},                       # аллокатор: «размеров не наблюдал»
        capital_usd=100_000.0, cycle_date="2026-08-08",  # FROZEN-DATE-OK: ярлык цикла, не свежесть
        run_ts=ts(hours_ago=0.0), write=False,
    )
    assert doc["cash"]["status"] == "attribution_incomplete", doc["cash"]["status"]
    assert "tvl_floor_unresolved" in doc["cash"]["unchecked"]
