"""Форвардный paper-модуль рангового демоушена (ADR-074) — две руки в одном модуле.

Решения владельца 2026-08-08: ADR-074 принят (вариант A + C карточки
`own-rnd-xsd-rank-demotion-allocator`), вторая рука по волатильности — вариант 1 карточки
`own-rnd-xvd-vol-rank-second-arm` («один модуль, две руки, ноль новых агентов»).

Проверяется то, что легко сломать молча:
  * причинность окна (сегодняшний день не смотрит на себя);
  * отложенный возврат — без него правило торгует шум;
  * fail-CLOSED там, где нечего измерять;
  * разница РУК: зрячая к доходности выключает убыточную книгу, полуслепая — нет
    (это её свойство, закреплённое тестом, а не дефект);
  * обе руки пишут концентрацию и долю «выключено» — иначе через 30 дней форварда
    результат неразличим (требование владельца, замер #46).
"""
# FROZEN-DATE-OK: injected-clock — модуль принимает время ВХОДОМ (`run_forward_tick(as_of=)`),
# и тесты передают фиксированный `as_of` вместе с фиксированными датами панели. Обе стороны
# закреплены от одного якоря, поэтому сдвиг календаря на тест не влияет — это преференция №1
# `.claude/rules/deployment.md`, а не литеральная дата по недосмотру. Остальные даты в файле —
# синтетическая ось `_dates()`: подписи к ряду доходностей, никакого понятия свежести в модуле
# нет (он сравнивает даты между собой, а не с «сегодня»).
from __future__ import annotations

import json

import pytest

from spa_core.strategy_lab.swarm import rank_demotion_forward as rd


def _dates(n: int) -> list[str]:
    return [f"2026-{6 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]


def _flat_panel(n: int, books=("a", "b", "c", "d", "e"), r: float = 0.01):
    ds = _dates(n)
    return ds, {b: {d: r for d in ds} for b in books}


# ── причинность и fail-CLOSED ────────────────────────────────────────────────

def test_scores_never_look_at_today():
    """Окно [t−L, t−1]. День, глядящий на себя, — это подглядывание в будущее."""
    rets = {"a": [0.0] * 5 + [99.0]}
    s = rd.drift_scores(rets, lookback=3)
    assert s["a"][5] == pytest.approx(0.0), "сегодняшний выброс попал в собственный score"


def test_first_day_has_no_score():
    assert rd.drift_scores({"a": [0.1, 0.2]}, lookback=3)["a"][0] is None


def test_nothing_is_demoted_while_scores_are_unmeasured():
    """Выключить книгу по неизмеренному значило бы решать о капитале на пустоте."""
    scores = {b: [None] * 4 for b in "abcde"}
    flags = rd.rank_flags(scores, k=2, readmit_m=1)
    assert not any(any(v) for v in flags.values())


def test_no_demotion_when_measured_count_not_greater_than_k():
    """«Худших k» из k книг не определить — выключать некого."""
    scores = {"a": [1.0], "b": [2.0]}
    assert not any(any(v) for v in rd.rank_flags(scores, k=2, readmit_m=1).values())


# ── ранговая машина состояний ────────────────────────────────────────────────

def test_worst_k_are_demoted():
    scores = {"a": [5.0], "b": [4.0], "c": [3.0], "d": [2.0], "e": [1.0]}
    flags = rd.rank_flags(scores, k=2, readmit_m=1)
    assert flags["e"][0] is True and flags["d"][0] is True
    assert flags["a"][0] is False and flags["b"][0] is False


def test_readmission_is_delayed_not_immediate():
    """Один день вне bottom-k — НЕ возврат. Иначе правило начинает торговать шум."""
    n = 6
    scores = {"a": [5.0] * n, "b": [4.0] * n, "c": [3.0] * n,
              "d": [2.0] * n, "e": [1.0] + [9.0] * (n - 1)}
    flags = rd.rank_flags(scores, k=2, readmit_m=3)
    assert flags["e"][0] is True
    assert flags["e"][1] is True, "вернулась в тот же день — отложенного возврата нет"
    assert flags["e"][2] is True
    assert flags["e"][3] is False, "не вернулась после M дней подряд вне bottom-k"


def test_streak_resets_on_re_entry():
    n = 6
    scores = {"a": [5.0] * n, "b": [4.0] * n, "c": [3.0] * n, "d": [2.0] * n,
              "e": [1.0, 9.0, 9.0, 1.0, 9.0, 9.0]}
    flags = rd.rank_flags(scores, k=2, readmit_m=3)
    assert flags["e"][5] is True, "счётчик подряд не сбросился при повторном попадании"


# ── ДВЕ РУКИ: в этом и была суть решения владельца ───────────────────────────

def test_drift_arm_demotes_the_losing_book():
    ds = _dates(80)
    panel = {b: {d: 0.01 for d in ds} for b in ("a", "b", "c", "d")}
    panel["e"] = {d: -0.02 for d in ds}
    arms = rd.compute_arms(ds, panel)
    assert "e" in arms["drift"]["books_out_today"]


def test_vol_arm_is_blind_to_sign_by_design():
    """σ инвариантна к знаку: зеркальная книга для этой руки НЕОТЛИЧИМА от прибыльной.

    Это ЗАКРЕПЛЁННОЕ свойство #45, а не дефект — и именно поэтому вторая рука стоит
    РЯДОМ со зрячей, а не вместо неё. Тест ловит попытку «улучшить» руку так, что
    она втихую станет второй копией первой.
    """
    ds = _dates(80)
    up = [0.02 if i % 3 else -0.01 for i in range(len(ds))]
    panel = {"a": {d: 0.005 for d in ds}, "b": {d: 0.005 for d in ds},
             "c": {d: 0.005 for d in ds},
             "gain": {d: v for d, v in zip(ds, up)},
             "mirror": {d: -v for d, v in zip(ds, up)}}
    rets = {b: [panel[b][d] for d in ds] for b in panel}
    s = rd.vol_scores(rets)
    assert s["gain"][-1] == pytest.approx(s["mirror"][-1]), \
        "рука по волатильности начала различать знак — это уже другой признак"


def test_two_arms_are_reported_side_by_side():
    ds, panel = _flat_panel(80)
    arms = rd.compute_arms(ds, panel)
    assert set(rd.ARMS) <= set(arms)
    assert "arm_contrast" in arms, "владелец выбрал две руки ради ПРЯМОГО сравнения"


# ── требование владельца: концентрация и duty каждый день ────────────────────

@pytest.mark.parametrize("arm", ["raw", "drift", "vol"])
def test_every_arm_logs_concentration_and_duty(arm):
    ds, panel = _flat_panel(80)
    view = rd.compute_arms(ds, panel)[arm]
    assert "concentration_pct" in view and "duty_out_pct" in view


def test_raw_arm_is_never_out():
    ds, panel = _flat_panel(40)
    assert rd.compute_arms(ds, panel)["raw"]["duty_out_pct"] == 0.0


# ── структурное ограничение, записанное в ADR как условие принятия ───────────

def test_rule_always_stays_fully_in_the_market():
    """Ранговое правило НЕ УМЕЕТ опустить портфель — оно только переставляет.

    Это и есть причина, по которой ADR-074 требует ОТДЕЛЬНЫЙ абсолютный kill-путь.
    Тест ловит молчаливое превращение правила в «защиту».
    """
    ds = _dates(80)
    panel = {b: {d: -0.05 for d in ds} for b in "abcde"}   # обвал по ВСЕМ книгам
    arms = rd.compute_arms(ds, panel)
    for arm in rd.ARMS:
        assert arms[arm]["duty_out_pct"] < 100.0
        assert arms[arm]["concentration_pct"] is not None, \
            "правило ушло в кэш целиком — значит оно уже не ранговое"


def test_all_flagged_means_all_cash_fail_closed():
    """Единственное состояние, где правило НЕ ДОЛЖНО выдумывать назначение."""
    w = rd._weights_from_flags({"a": [True], "b": [True]}, 1)
    assert w["a"][0] == 0.0 and w["b"][0] == 0.0


# ── тик: append-only по дате, идемпотентность, честный NO_DATA ───────────────

def test_tick_records_no_data_when_panel_is_missing(tmp_path):
    doc = rd.run_forward_tick(panel_dir=tmp_path / "нет", out_dir=tmp_path / "out",
                              as_of="2026-08-08")
    assert doc["state"] == "NO_DATA"
    assert doc["is_advisory"] is True and doc["outside_riskpolicy"] is True


def test_tick_refuses_to_write_behind_the_book(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / rd.BOOK_NAME).write_text(json.dumps({"date": "2026-08-08"}) + "\n", encoding="utf-8")
    doc = rd.run_forward_tick(panel_dir=tmp_path / "нет", out_dir=out, as_of="2026-08-01")
    assert doc["state"] == "REFUSED_OUT_OF_ORDER"
    assert doc["book_appended"] is False


def test_module_declares_its_honest_limits():
    """Ограничения ADR-074 обязаны ехать вместе с модулем, а не остаться в документе."""
    for token in ("kill-switch НЕ ЗАМЕНЯЕТ", "не про тайминг", "L0"):
        assert token in rd.HONEST_LIMITS
