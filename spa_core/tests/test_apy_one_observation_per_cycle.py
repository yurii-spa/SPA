"""Один цикл — одно число про один пул, и у простоя есть ИМЯ.

Две карточки, один файл под проверкой (`spa_core/monitoring/capital_efficiency.py`):

1. `agent-dva-artefakta-odnogo-tsikla-raskhodyatsya-vtroe` — замер 2026-08-08:
   один цикл, два артефакта, одна строка простоя, разные числа.

   | | `capital_efficiency.json` | `allocation_rationale.json` |
   |---|---|---|
   | упущенная доходность | **451.1 б.п./год** | **132.4 б.п./год** |
   | `moonwell_base` | +$20 000 @ **22.56 %** | +$20 000 @ **6.62 %** |
   | `aave_v3` | +$35 000 @ **4.77 %** | +$40 000 @ **3.31 %** |

   Снимок адаптеров (`adapter_status.json`) подтверждал числа rationale. То есть
   `forgone_yield_bps_est` — число, по которому ВЛАДЕЛЕЦ решает, насколько срочно
   чинить простой, — было завышено в 3.4 раза. Причина класса: рейтинг читался как
   список наблюдений, хотя сам метит строки `fallback`/`unchecked` (ADR-063) и
   носит отметки времени, — их никто не спрашивал.

2. `inbox-adr-076-3-atributsiya-kesha-obyazana-naz` — та же функция печатала
   `UNEXPLAINED_CASH` и тут же перечисляла причину; строка дословно уезжала в
   `agent_health.system_issues` и `SYSTEM_BRIEFING`, и владелец читал «20 %
   капитала простаивает НЕПОНЯТНО ПОЧЕМУ», хотя причина измерена: книга упёрлась
   в лимит одной цепочки.

Каждый тест ниже — либо воспроизведение аварии (краснеет на коде до починки),
либо контроль в обратную сторону: тревога и её ЧИСЛО обязаны выживать, иначе это
будет не починка отчёта, а глушение сигнала (инвариант 16 по духу).

Время — ВХОД: `assess(now=...)` получает фиксированные часы, отметки в фикстурах
тоже фиксированы относительно них. Литеральных дат нет. Сети нет, LLM нет,
прод-`data/` не читается и не пишется (все пути перекрыты monkeypatch'ем).
Ни один порог RiskPolicy, kill-switch и целевой вес здесь не меняется: это
отчётный слой.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import spa_core.monitoring.capital_efficiency as ce

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: часы инъектированы, обе стороны закреплены
CAP = 100_000.0


def _ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


def _row(proto, apy, *, tier="T2", tvl=1_000_000_000.0, source="live", age_h=1.0):
    return {"protocol": proto, "tier": tier, "apy_pct": apy, "tvl_usd": tvl,
            "apy_source": source, "last_updated": _ago(age_h)}


def _ranking(rows, *, age_h=1.0):
    return {"generated_at": _ago(age_h), "by_apy": list(rows)}


def _positions(book: dict, cash_usd: float):
    return {"capital_usd": CAP, "cash_usd": cash_usd,
            "deployed_usd": CAP - cash_usd,
            "positions": [{"protocol": p, "usd": u} for p, u in book.items()]}


def _wire(monkeypatch, *, ranking, book, cash_usd, rationale=None, registry=None,
          history=None, tmp_path: Path | None = None):
    """Перекрываем ВСЕ входы модуля — прод-`data/` не участвует."""
    pos = _positions(book, cash_usd)

    def fake_load(p):
        s = str(p)
        if s.endswith("current_positions.json"):
            return pos
        if s.endswith("apy_ranking.json"):
            return ranking
        if s.endswith("allocation_rationale.json"):
            return rationale
        if s.endswith("adapter_registry.json"):
            return registry
        return None

    monkeypatch.setattr(ce, "_load", fake_load)
    hist_path = (tmp_path or Path("/nonexistent")) / "allocation_rationale_history.jsonl"
    if history is not None and tmp_path is not None:
        hist_path.write_text("\n".join(json.dumps(r) for r in history) + "\n",
                             encoding="utf-8")
    monkeypatch.setattr(ce, "_HISTORY", hist_path)


# ── 1. Карточка «расходятся втрое»: литерал не смеет оценивать простой ───────

def test_a_literal_apy_may_not_price_idle_capital(monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии 08.08 (краснеет на коде до починки).

    Строка `moonwell_base` с меткой `fallback` (число — литерал, не замер) стояла
    «лучшей доходностью» 22.56 % и давала 451 б.п. упущенной доходности. Живой
    `aave_v3` рядом платит 3.31 %. После починки лучшая доходность — живая, а
    литеральная комната НАЗВАНА, а не выкинута молча.
    """
    monkeypatch.setattr(ce, "_config", lambda: {
        "min_cash_pct": 0.05, "t1_cap": 0.4, "t2_cap": 0.2, "min_apy": 1.0,
        "min_tvl_usd": 5_000_000.0, "max_single_chain_pct": 0.9})
    _wire(monkeypatch,
          ranking=_ranking([_row("moonwell_base", 22.5558, source="fallback"),
                            _row("aave_v3", 3.3051, tier="T1")]),
          book={"aave_v3": 20_000.0}, cash_usd=20_000.0)
    r = ce.assess(now=NOW)

    assert r["best_qualifying_apy_pct"] == pytest.approx(3.3051)
    assert "moonwell_base" not in " ".join(r["headroom_contributors"])
    assert "moonwell_base" in r["headroom_apy_unobserved"]
    assert any("moonwell_base" in e and "apy_unobserved:fallback" in e
               for e in r["headroom_excluded"]), r["headroom_excluded"]
    # …и цена простоя больше не 3.4× — она считается по живому числу
    assert r["verdict"] == "WARNING"
    assert 0 < r["forgone_yield_bps_est"] < 100


def test_the_alarm_and_its_price_survive_on_a_clean_feed(monkeypatch):
    """Контроль в обратную сторону: наблюдение свежее и согласованное ⇒ тревога цела.

    Без этого теста «починкой» можно было бы объявить вечное UNKNOWN.
    """
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 7.5), _row("compound_v3", 6.5, tier="T1")]),
          book={"aave_v3": 40_000.0, "pendle": 20_000.0}, cash_usd=20_000.0)
    r = ce.assess(now=NOW)
    assert r["verdict"] == "WARNING"
    assert r["best_qualifying_apy_pct"] == pytest.approx(7.5)
    assert r["forgone_yield_bps_est"] > 0


def test_a_stale_row_is_not_an_observation_of_today(monkeypatch):
    """Строка с живым провенансом, но недельной отметкой, — не сегодняшний замер."""
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 22.5, age_h=170.0)]),
          book={"aave_v3": 40_000.0, "pendle": 40_000.0}, cash_usd=20_000.0)
    r = ce.assess(now=NOW)
    assert r["verdict"] == "UNKNOWN", r          # не OK: вход потерян, книга не улучшилась
    assert "frax" in r["headroom_apy_unobserved"]
    assert r["best_qualifying_apy_pct"] == 0.0
    assert r["forgone_yield_bps_est"] == 0


def test_a_stale_ranking_file_cannot_describe_todays_book(monkeypatch):
    """Рейтинг собран трое суток назад ⇒ он не про сегодняшнюю книгу (fail-CLOSED)."""
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 7.5, age_h=72.0)], age_h=72.0),
          book={"aave_v3": 40_000.0, "pendle": 40_000.0}, cash_usd=20_000.0)
    r = ce.assess(now=NOW)
    assert r["verdict"] == "UNKNOWN", r
    assert r["apy_feed_fresh"] is False
    assert "72h" in r["reason"] or "undated" in r["reason"]


def test_an_undated_ranking_cannot_vouch(monkeypatch):
    _wire(monkeypatch,
          ranking={"by_apy": [_row("frax", 7.5)]},
          book={"aave_v3": 40_000.0, "pendle": 40_000.0}, cash_usd=20_000.0)
    r = ce.assess(now=NOW)
    assert r["verdict"] == "UNKNOWN", r
    assert r["apy_feed_age_h"] is None


# ── 2. Очная ставка двух артефактов одного цикла ─────────────────────────────

def _history(apys: dict, *, age_h=1.0):
    return [{"schema": "shadow-hist-v1", "cycle_date": "2026-08-08",
             "generated_at": _ago(age_h), "apy_evidenced_pct": apys}]


def test_two_artifacts_of_one_cycle_must_agree_about_a_pool(monkeypatch, tmp_path):
    """Дословные числа карточки: 4.77 % в нашем артефакте против 3.31 % у цикла.

    Обе оценки верны быть не могут. Разошлись ⇒ рейтинг описывает не тот снимок,
    и цена простоя по нему — выдумка. Комната остаётся, но НАЗВАНА расходящейся.
    """
    _wire(monkeypatch,
          ranking=_ranking([_row("aave_v3", 4.77, tier="T1")]),
          book={"pendle": 20_000.0}, cash_usd=20_000.0,
          history=_history({"aave_v3": 3.3051}), tmp_path=tmp_path)
    r = ce.assess(now=NOW)
    assert r["apy_diverging_from_cycle"] == ["aave_v3"]
    assert "aave_v3" in r["headroom_apy_unobserved"]
    assert r["verdict"] == "UNKNOWN", r
    assert any("apy_diverges_from_cycle:4.77%vs3.31%" in e
               for e in r["headroom_excluded"]), r["headroom_excluded"]


def test_agreement_within_rounding_noise_is_not_a_divergence(monkeypatch, tmp_path):
    """Контроль в обратную сторону: секундный лаг фида — не расхождение."""
    _wire(monkeypatch,
          ranking=_ranking([_row("aave_v3", 3.31, tier="T1")]),
          book={"pendle": 20_000.0}, cash_usd=20_000.0,
          history=_history({"aave_v3": 3.3051}), tmp_path=tmp_path)
    r = ce.assess(now=NOW)
    assert r["apy_diverging_from_cycle"] == []
    assert r["verdict"] == "WARNING"
    assert r["best_qualifying_apy_pct"] == pytest.approx(3.31)


def test_a_stale_history_line_does_not_veto_a_fresh_ranking(monkeypatch, tmp_path):
    """Вчерашняя запись цикла не имеет права объявить сегодняшний замер ложным."""
    _wire(monkeypatch,
          ranking=_ranking([_row("aave_v3", 4.77, tier="T1")]),
          book={"pendle": 20_000.0}, cash_usd=20_000.0,
          history=_history({"aave_v3": 3.3051}, age_h=200.0), tmp_path=tmp_path)
    r = ce.assess(now=NOW)
    assert r["apy_diverging_from_cycle"] == []
    assert r["verdict"] == "WARNING"


def test_end_to_end_one_snapshot_gives_both_artifacts_the_same_number(monkeypatch,
                                                                      tmp_path):
    """Сквозная проводка: `adapter_status` → рейтинг → тревога о простое.

    Проверяется ровно то, чего не было 08.08: число, которое печатает
    `capital_efficiency`, совпадает с доказанным APY того же снимка — тем самым,
    по которому цикл строит `allocation_rationale`.
    """
    from spa_core.adapters.apy_aggregator import APYAggregator

    # `save_ranking` датирует файл РЕАЛЬНЫМИ часами, поэтому и снимок, и суд над
    # ним живут в тех же часах: обе стороны закреплены относительно `now`.
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(minutes=30)).isoformat()
    (tmp_path / "adapter_status.json").write_text(json.dumps({
        "schema_version": 2, "generated_at": stamp,
        "adapters": {
            "aave_v3": {"apy": 3.3051, "live_apy": 3.3051, "fallback_apy": 3.5,
                        "tvl_usd": 2e8, "tvl_source": "live", "tier": 1,
                        "chain": "ethereum", "per_protocol_cap": 0.4,
                        "active": True, "last_updated": stamp},
            "moonwell_base": {"apy": 6.6223, "live_apy": 6.6223,
                              "fallback_apy": 22.5558, "tvl_usd": 2e8,
                              "tvl_source": "live", "tier": 2, "chain": "base",
                              "per_protocol_cap": 0.2, "active": True,
                              "last_updated": stamp},
        }}), encoding="utf-8")
    out = tmp_path / "apy_ranking.json"
    APYAggregator.load(tmp_path).save_ranking(out)
    ranking = json.loads(out.read_text())
    rows = {r["protocol"]: r for r in ranking["by_apy"]}
    monkeypatch.setattr(ce, "_load",
                        lambda p: (_positions({"aave_v3": 20_000.0}, 20_000.0)
                                   if str(p).endswith("current_positions.json")
                                   else (ranking if str(p).endswith("apy_ranking.json")
                                         else None)))
    monkeypatch.setattr(ce, "_HISTORY", tmp_path / "nonexistent.jsonl")
    r = ce.assess(now=now)
    # оба пула — наблюдения снимка; лучший = 6.6223 (а не литерал 22.5558)
    assert rows["moonwell_base"]["apy_pct"] == pytest.approx(6.6223)
    assert r["best_qualifying_apy_pct"] == pytest.approx(6.6223)
    assert r["forgone_yield_bps_est"] == round(
        min(r["deployable_headroom_pct"], r["idle_excess_pct"]) * 6.6223 * 100)


# ── 3. ADR-076.3: у простоя есть имя ─────────────────────────────────────────

REGISTRY = {"adapters": {
    "aave_v3": {"chain": "ethereum"}, "pendle": {"chain": "ethereum"},
    "maple": {"chain": "ethereum"}, "moonwell_base": {"chain": "base"},
}}


def _rationale(*, candidates: list[str], unexplained_pct=5.0, age_h=2.0):
    return {"generated_at": _ago(age_h), "cash": {
        "status": "UNEXPLAINED_CASH", "unexplained_pct": unexplained_pct,
        "components": [{
            "kind": "unexplained_deployable", "usd": unexplained_pct / 100.0 * CAP,
            "pct": unexplained_pct, "forgone_bps_yr": 132.4, "status": "OK",
            "protocols": ["{}(+$10,000 @ 6.62%)".format(p) for p in candidates],
        }]}}


# книга, упёршаяся в 90 %-лимит одной цепочки: 90 % на ethereum, 10 % кэша
BOUND_BOOK = {"aave_v3": 40_000.0, "pendle": 20_000.0, "maple": 30_000.0}


def test_a_chain_bound_book_names_the_limit_instead_of_unexplained(monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ карточки ADR-076.3 (краснеет на коде до починки).

    Причина измерена: все кандидаты — на ethereum, а он уже держит 90 % капитала
    при потолке 90 %. Отчёт обязан НАЗВАТЬ лимит.
    """
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 7.5)]),
          book=BOUND_BOOK, cash_usd=10_000.0,
          rationale=_rationale(candidates=["aave_v3", "maple"]),
          registry=REGISTRY)
    r = ce.assess(now=NOW)

    assert r["attribution_status"] == ce.CAP_BOUND_CHAIN
    assert r["attribution_status_source"] == "UNEXPLAINED_CASH"
    assert "UNEXPLAINED" not in r["reason"]
    assert "single-chain cap" in r["reason"] and "ethereum" in r["reason"]
    assert r["cash_bound_by"]["chains_at_cap"] == ["ethereum"]
    assert r["cash_bound_by"]["chain_cap_pct"] == 90.0
    # ЧИСЛО и уровень тревоги не двигаются — это цена диверсификации, её видно
    assert r["verdict"] == "WARNING"
    assert r["forgone_yield_bps_est"] == 132
    assert r["cash_unexplained_pct"] == pytest.approx(5.0)


def test_a_genuinely_unnamed_idle_still_reads_unexplained(monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ в обратную сторону (карточка требует его дословно).

    Кандидат стоит на `base`, лимит той цепочки не выбран — деньги разместить
    БЫЛО куда. Это настоящий безымянный простой, и он обязан таковым остаться,
    иначе мы не починили отчёт, а заглушили сигнал.
    """
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 7.5)]),
          book=BOUND_BOOK, cash_usd=10_000.0,
          rationale=_rationale(candidates=["aave_v3", "moonwell_base"]),
          registry=REGISTRY)
    r = ce.assess(now=NOW)
    assert r["attribution_status"] == "UNEXPLAINED_CASH"
    assert r["cash_bound_by"] is None
    assert "UNEXPLAINED" in r["reason"]
    assert r["verdict"] == "WARNING"


@pytest.mark.parametrize("registry,label", [
    (None, "карты сетей нет вовсе"),
    ({"adapters": {"aave_v3": {"chain": "ethereum"}}}, "сеть известна не для всех"),
])
def test_without_a_measurement_the_limit_is_not_named(monkeypatch, registry, label):
    """Fail-CLOSED: «связан лимитом» — вывод ИЗ ИЗМЕРЕНИЯ, а не умолчание."""
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 7.5)]),
          book=BOUND_BOOK, cash_usd=10_000.0,
          rationale=_rationale(candidates=["aave_v3", "maple"]),
          registry=registry)
    r = ce.assess(now=NOW)
    assert r["attribution_status"] == "UNEXPLAINED_CASH", label
    assert r["cash_bound_by"] is None


def test_the_chain_cap_comes_from_riskpolicy_not_from_a_local_literal(monkeypatch):
    """Порог берётся из того же объекта, что читает гейт (ADR-062), а не из копии."""
    from spa_core.risk.policy import RiskConfig
    assert ce._config()["max_single_chain_pct"] == RiskConfig().max_single_chain_allocation
    monkeypatch.setattr(ce, "_config", lambda: {
        "min_cash_pct": 0.05, "t1_cap": 0.4, "t2_cap": 0.2, "min_apy": 1.0,
        "min_tvl_usd": 5_000_000.0, "max_single_chain_pct": None})
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 7.5)]),
          book=BOUND_BOOK, cash_usd=10_000.0,
          rationale=_rationale(candidates=["aave_v3", "maple"]),
          registry=REGISTRY)
    r = ce.assess(now=NOW)
    assert r["attribution_status"] == "UNEXPLAINED_CASH"   # порог не прочитан ⇒ не называем


# ── 4. То, что доезжает до владельца ─────────────────────────────────────────

def test_the_artifact_hands_the_owner_a_named_cause(monkeypatch):
    """Артефакт готов к печати: причина названа, «UNEXPLAINED» из строки ушло.

    `agent_health` и `SYSTEM_BRIEFING` читают ИМЕННО эти поля
    (`attribution_status` + `reason` из `data/capital_efficiency.json`), поэтому
    контракт закрепляется здесь, у производителя.

    ОСТАЁТСЯ (не в этом заходе): `agent_health_monitor.check_system` пока
    склеивает свою строку сам и на `CAP_BOUND_CHAIN` печатает общий текст
    «idle UNEXPLAINED after attribution». Файл в этой волне закреплён за другим
    агентом — нужна одна ветка, отдающая `reason` дословно; до неё владелец
    видит названную причину в артефакте, но не в брифинге.
    """
    _wire(monkeypatch,
          ranking=_ranking([_row("frax", 7.5)]),
          book=BOUND_BOOK, cash_usd=10_000.0,
          rationale=_rationale(candidates=["aave_v3", "maple"]),
          registry=REGISTRY)
    r = ce.assess(now=NOW)
    assert r["attribution_status"] == ce.CAP_BOUND_CHAIN
    assert "UNEXPLAINED" not in r["reason"]
    assert "single-chain cap" in r["reason"]
    # число, которое владелец читает как срочность, на месте
    assert r["forgone_yield_bps_est"] == 132


def test_agent_health_still_shouts_when_the_cause_is_unnamed(tmp_path):
    """Контроль в обратную сторону: безымянный простой доезжает до владельца.

    Проверяется существующее поведение потребителя (файл не менялся): тревога
    про необъяснённый простой обязана остаться слышимой.
    """
    from spa_core.monitoring.agent_health_monitor import check_system

    (tmp_path / "capital_efficiency.json").write_text(json.dumps({
        "verdict": "WARNING", "attribution_status": "UNEXPLAINED_CASH",
        "cash_unexplained_pct": 20.0, "forgone_yield_bps_est": 451,
        "deployable_now_pct": 0.2, "reason": "LAZY: 20.0% of capital idle UNEXPLAINED",
    }), encoding="utf-8")
    _checks, _status, issues = check_system(
        tmp_path, datetime.now(timezone.utc), autopush_log="/nonexistent")
    assert any("UNEXPLAINED" in i for i in issues), issues
