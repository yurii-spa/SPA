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
    результат неразличим (требование владельца, замер #46);
  * ВЕТКА «ОТМЕТКА НЕ ПРИШЛА» (карточка `agent-rnd51-stale-branch-for-demotion-arm`,
    записи #51/#52) — каждый тест ниже с пометкой ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ краснеет
    на поведении, которое код держал ДО правки (политика `open`: тёмный фид ЗАЩИЩАЛ
    книгу и возвращал ей вес);
  * ТРЕТЬЯ РУКА — причинная СТАТИКА (карточка `inbox-modul-39-tretei-rukoi-obyazana-byt-prich`,
    записи #47/#48): контроль «тайминг или недовес», и подмена его ОРАКУЛОМ (средним по
    будущему окну) ловится тестом; оборот считается по Σ|Δw|; руки НЕ сливаются в один вес.
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


# ═══════════════════════════════════════════════════════════════════════════════
# ВЕТКА «ОТМЕТКА НЕ ПРИШЛА» — #52 SFP, карточка agent-rnd51-stale-branch-for-demotion-arm
# ═══════════════════════════════════════════════════════════════════════════════

def _dark_after(day0_scores: dict, n: int, dark_book: str) -> dict:
    """Панель скоров, где у `dark_book` фид тёмный со дня 1 и до конца окна."""
    out = {b: [v] * n for b, v in day0_scores.items()}
    out[dark_book] = [day0_scores[dark_book]] + [None] * (n - 1)
    return out


def test_carry_records_the_age_of_every_mark():
    """Возраст отметки — величина, а не догадка: 0 на свежей, +1 за каждый тёмный день."""
    carried, ages = rd.carry_scores({"a": [1.0, None, None, 2.0, None]})
    assert carried["a"] == [1.0, 1.0, 1.0, 2.0, 2.0]
    assert ages["a"] == [0, 1, 2, 0, 1]


def test_never_measured_book_has_no_age_not_age_zero():
    """`None` и `0` — разные утверждения, и на них расходятся разные ветки правила."""
    _carried, ages = rd.carry_scores({"a": [None, None, 0.5]})
    assert ages["a"] == [None, None, 0]


def test_dark_feed_no_longer_earns_a_readmission_credit():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ дефекта #52 (политика `open`).

    Книга выключена в день 0, дальше её фид тёмный. ДО правки она копила «дней подряд вне
    bottom-k» просто потому, что её нечем было измерить, и через M дней ВОЗВРАЩАЛАСЬ —
    авария фида возвращала книге вес. Под `carry` вчерашний скор продолжает работать,
    книга остаётся худшей и остаётся выключенной.
    """
    n = 8                                   # M=3, тёмных дней заведомо больше M
    scores = _dark_after({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}, n, "e")
    flags = rd.rank_flags(scores, k=2, readmit_m=3, max_age_days=n)
    assert all(flags["e"]), (
        "тёмный фид вернул книге вес — это политика `open`, худшая находка #52")


def test_dark_feed_can_still_be_demoted_under_carry():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: под `open` тёмную книгу было НЕВОЗМОЖНО выключить.

    Здесь книга `e` измерена как худшая один раз, потом фид гаснет — и демоушен
    происходит по вчерашнему скору, а не отменяется из-за пустой ячейки.
    """
    n = 4
    scores = _dark_after({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}, n, "e")
    flags = rd.rank_flags(scores, k=1, readmit_m=1, max_age_days=n)
    assert flags["e"][1] is True and flags["e"][3] is True


def test_age_ceiling_closes_the_panel_instead_of_judging_by_last_year():
    """За потолком возраста правило ОТКАЗЫВАЕТСЯ судить: `closed_panel`, а не тихое carry."""
    n = 6
    scores = _dark_after({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}, n, "e")
    dec = rd.rank_decisions(scores, k=2, readmit_m=20, max_age_days=2)
    assert dec["day_states"] == [rd.DAY_MEASURED, rd.DAY_CARRIED, rd.DAY_CARRIED,
                                 rd.DAY_CLOSED_PANEL, rd.DAY_CLOSED_PANEL,
                                 rd.DAY_CLOSED_PANEL]


def test_closed_panel_freezes_the_readmission_counters():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ той же аварии, но с потолком.

    Если в дни `closed_panel` счётчики продолжат тикать, тёмный фид снова начнёт
    возвращать книгам вес — дефект #52 просто отложится на `max_age_days` дней.
    Книга `e` выключена в день 0 и обязана остаться выключенной все 30 тёмных дней,
    хотя M=3.
    """
    n = 30
    scores = _dark_after({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}, n, "e")
    dec = rd.rank_decisions(scores, k=2, readmit_m=3, max_age_days=2)
    assert all(dec["flags"]["e"]), "счётчики возврата тикали в закрытый день"
    assert dec["day_states"].count(rd.DAY_CLOSED_PANEL) == n - 3


def test_closed_book_policy_is_deliberately_unreachable():
    """«Не измерено ⇒ демоушен» — худшая из четырёх политик #52 (netAPY 25.94 % → −0.49 %).

    Её нельзя получить НИ ОДНИМ значением параметров: тёмная книга либо ранжируется по
    вчерашнему скору, либо день закрывается целиком — но никогда не выключается ЗА ТО,
    что её не измерили. Money-path — отдельный контур: там непомеренное обязано
    отказываться, и это правило здесь не ослабляется, а просто не воспроизводится.
    """
    n = 3
    scores = _dark_after({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 9.0}, n, "e")
    for ceiling in (0, 1, 2, 5):
        flags = rd.rank_flags(scores, k=2, readmit_m=1, max_age_days=ceiling)
        assert not any(flags["e"]), (
            f"тёмная ЛУЧШАЯ книга выключена при max_age_days={ceiling} — это closed_book")


def test_negative_age_ceiling_is_refused():
    with pytest.raises(ValueError):
        rd.rank_decisions({"a": [1.0], "b": [2.0], "c": [3.0]}, max_age_days=-1)


# ── бюджет свежести у рук РАЗНЫЙ (#51 SLT) ───────────────────────────────────

def test_vol_arm_skips_instead_of_deciding_on_a_stale_mark():
    """У #45 бюджет свежести НУЛЕВОЙ: сутки несвежести — и ΔCalmar +2.96 → −0.21.

    Поэтому рука пишет `SKIPPED` — признанный пропуск, а НЕ решение по вчерашнему.
    """
    n = 4
    scores = _dark_after({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}, n, "e")
    dec = rd.rank_decisions(scores, k=2, readmit_m=1, fresh_only=True)
    assert dec["day_states"] == [rd.DAY_MEASURED] + [rd.DAY_SKIPPED] * 3
    assert dec["max_age_days"] == 0, "нулевой бюджет свежести подменён общим потолком"


def test_skipped_day_holds_yesterdays_state_and_freezes_counters():
    n = 10
    scores = _dark_after({"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}, n, "e")
    dec = rd.rank_decisions(scores, k=2, readmit_m=2, fresh_only=True)
    assert all(dec["flags"]["e"]), "пропущенный день двинул счётчик возврата"


def test_vol_arm_is_the_fresh_only_arm_and_drift_is_not():
    """Бюджеты рук РАЗНЫЕ по замеру, а не по вкусу: #40 равнодушен до ~5 дней, #45 — нет."""
    assert rd.FRESH_ONLY_ARMS == ("vol",)
    assert rd.MAX_SCORE_AGE_DAYS == 5


def test_every_arm_logs_the_age_of_every_book_next_to_its_decision():
    """Без возраста форвардный трек не интерпретируем: «ошиблось» ≠ «судило по вчерашнему»."""
    ds, panel = _flat_panel(80)
    arms = rd.compute_arms(ds, panel)
    for arm in rd.ARMS:
        assert set(arms[arm]["score_age_days"]) == set(panel), \
            f"рука {arm} не пишет возраст отметки каждой книги"
        assert arms[arm]["day_state"] in {rd.DAY_MEASURED, rd.DAY_CARRIED, rd.DAY_SKIPPED,
                                          rd.DAY_CLOSED_PANEL, rd.DAY_UNRANKABLE}
        assert arms[arm]["stale_policy"]["policy"] == "carry"


def test_stale_policy_is_named_in_the_daily_line(tmp_path):
    """Политика обязана ехать в КАЖДОЙ строке книги, а не жить в докстринге."""
    doc = rd.run_forward_tick(panel_dir=tmp_path / "нет", out_dir=tmp_path / "out",
                              as_of="2026-08-14")
    params = doc["params"]
    assert params["stale_policy"] == "carry"
    assert params["max_score_age_days"] == rd.MAX_SCORE_AGE_DAYS
    assert params["fresh_only_arms"] == ["vol"]
    line = json.loads((tmp_path / "out" / rd.BOOK_NAME).read_text(encoding="utf-8").strip())
    assert line["params"]["stale_policy"] == "carry"


def test_honest_limits_name_the_dark_feed_policy():
    """Находка #52 нигде не была записана — теперь она обязана ехать вместе с модулем."""
    for token in ("carry", "SKIPPED", "fail-CLOSED на money-path", "СИНТЕТИЧЕСКОЙ"):
        assert token in rd.HONEST_LIMITS, f"ограничение «{token}» не заявлено модулем"


# ═══════════════════════════════════════════════════════════════════════════════
# ТРЕТЬЯ РУКА — ПРИЧИННАЯ СТАТИКА (#47/#48)
# ═══════════════════════════════════════════════════════════════════════════════

def _panel_with_one_loser(n: int):
    ds = _dates(n)
    panel = {b: {d: 0.01 for d in ds} for b in ("a", "b", "c", "d")}
    panel["e"] = {d: -0.02 for d in ds}
    return ds, panel


def test_static_arm_exists_and_is_declared_a_control():
    """Она отвечает на вопрос «тайминг или недовес» и кандидатом на доставку не является."""
    ds, panel = _panel_with_one_loser(rd.STATIC_FIT_DAYS + 30)
    arms = rd.compute_arms(ds, panel)
    assert arms["static"]["role"] == "control"
    assert rd.CONTROL_ARMS == ("static",) and "static" in rd.ALL_ARMS


def test_static_arm_is_causal_the_future_cannot_move_its_weights():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ подмены причинной статики ОРАКУЛОМ.

    В #47 «статический двойник» считался как среднее ТЕСТОВОГО периода — то есть по
    будущему. Здесь окно фиксации это ПРЕФИКС: доходности после `fit_days` не имеют
    права двигать ни один вес. Оракульная реализация (среднее по всему окну) на этом
    тесте краснеет — её веса поедут вместе с хвостом.
    """
    n = rd.STATIC_FIT_DAYS + 60
    books = ("a", "b", "c", "d", "e")
    base = {b: [0.01] * n for b in books}
    base["e"] = [-0.02] * n
    flipped = {b: list(v) for b, v in base.items()}
    for b in books:                                   # переписываем ВСЁ будущее
        flipped[b][rd.STATIC_FIT_DAYS:] = [(0.09 if b == "e" else -0.09)] * 60
    w_base = rd.static_weights(base, n)
    w_flip = rd.static_weights(flipped, n)
    assert w_base == w_flip, "статика поехала за будущим — это оракул, а не контроль"


def test_static_arm_holds_a_constant_after_the_fit_window():
    n = rd.STATIC_FIT_DAYS + 40
    ds, panel = _panel_with_one_loser(n)
    rets = {b: [panel[b][d] for d in ds] for b in panel}
    w = rd.static_weights(rets, n)
    for b in panel:
        tail = w[b][rd.STATIC_FIT_DAYS:]
        assert len(set(tail)) == 1, f"вес книги {b} двигался после окна фиксации"


def test_static_arm_is_equal_weight_while_nothing_is_fixed_yet():
    """Разогрев — честная часть трека: фиксировать ещё нечего, и рука это признаёт."""
    n = rd.STATIC_FIT_DAYS
    ds, panel = _flat_panel(n)
    rets = {b: [panel[b][d] for d in ds] for b in panel}
    w = rd.static_weights(rets, n)
    assert all(v == pytest.approx(1.0 / len(panel)) for b in panel for v in w[b])


def test_static_arm_is_not_a_copy_of_raw():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ вырождения #47.

    Если усреднять ВЕСЬ префикс (включая необезоруженный разогрев), статика становится
    тождеством `raw`, и совпадение с ней не говорит о тайминге НИЧЕГО — ровно та ловушка,
    в которую попал двойник #45 (оборот 0.00 из 370 дней).
    """
    n = rd.STATIC_FIT_DAYS + 20
    ds, panel = _panel_with_one_loser(n)
    arms = rd.compute_arms(ds, panel)
    equal = 100.0 / len(panel)
    assert arms["static"]["concentration_pct"] != pytest.approx(equal, abs=1e-6), \
        "статика выродилась в равные веса — это raw, а не контроль"


def test_static_arm_turns_over_exactly_zero_after_the_fit_window():
    """Оборот статики после фиксации — РОВНО ноль: она держит, а не переставляет.

    Сравнивать её оборот с оборотом правила напрямую нельзя: на однородной фикстуре у
    правила тоже одно переключение за окно, и числа совпадают. Проверяемое свойство —
    не «меньше», а «после фиксации не двигается вовсе».
    """
    n = rd.STATIC_FIT_DAYS + 40
    ds, panel = _panel_with_one_loser(n)
    rets = {b: [panel[b][d] for d in ds] for b in panel}
    w = rd.static_weights(rets, n)
    tail = {b: w[b][rd.STATIC_FIT_DAYS:] for b in panel}
    assert rd.turnover_per_year(tail, sorted(panel), n - rd.STATIC_FIT_DAYS) == 0.0


def test_static_contrast_is_the_timing_or_underweight_number():
    ds, panel = _panel_with_one_loser(rd.STATIC_FIT_DAYS + 30)
    contrast = rd.compute_arms(ds, panel)["static_contrast"]
    assert "drift_minus_static_apy_pp" in contrast
    assert "vol_minus_static_apy_pp" in contrast


def test_static_weights_refuse_an_empty_fit_window():
    with pytest.raises(ValueError):
        rd.static_weights({"a": [0.01] * 10}, 10, fit_days=0)


# ── оборот считается по Σ|Δw|, а не по числу переключений (#48) ───────────────

def test_turnover_counts_moved_capital_not_switches():
    """Половина капитала, переставленная один раз за 365 дней, = 0.5 оборота/год."""
    w = {"a": [1.0] + [0.5] * 364, "b": [0.0] + [0.5] * 364}
    assert rd.turnover_per_year(w, ["a", "b"], 365) == pytest.approx(1.0, abs=1e-6)


def test_turnover_needs_two_days_to_exist():
    assert rd.turnover_per_year({"a": [1.0]}, ["a"], 1) is None


@pytest.mark.parametrize("arm", ["raw", "drift", "vol", "static"])
def test_every_arm_logs_turnover_per_year(arm):
    ds, panel = _panel_with_one_loser(rd.STATIC_FIT_DAYS + 20)
    assert "turnover_per_year" in rd.compute_arms(ds, panel)[arm]


# ── руки НЕ сливаются в один вес (#48) ───────────────────────────────────────

def test_arms_are_never_blended_into_one_weight():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ансамбль наследует оборот шумнейшей руки, а сигнал усредняет.

    Порядок книг меняется у σ в 3.5 % дней, у drift в 31.7 %, у слияния в 30.3 % —
    net-of-cost слияние проигрывает и инкумбенту #40, и своей же причинной статике.
    Тест краснеет, если кто-нибудь добавит склеенное плечо.
    """
    ds, panel = _panel_with_one_loser(rd.STATIC_FIT_DAYS + 20)
    arms = rd.compute_arms(ds, panel)
    assert set(arms) == {"raw", "drift", "vol", "static", "arm_contrast", "static_contrast"}, \
        "в модуле появилось плечо, которого решение владельца не предусматривало"


def test_the_daily_line_declares_that_arms_are_not_blended(tmp_path):
    doc = rd.run_forward_tick(panel_dir=tmp_path / "нет", out_dir=tmp_path / "out",
                              as_of="2026-08-14")
    assert doc["params"]["arms_blended"] is False
    assert doc["params"]["control_arms"] == ["static"]


# ── сквозная проверка: всё новое обязано ДОЕХАТЬ до строки книги ──────────────

def _write_live_panel(panel_dir, dates, mtm_pct=0.02):
    """Панель из ровно тех книг, которые модуль ожидает (форвардные строки)."""
    for book in _expected_books():
        path = panel_dir / book / "realized_series.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for d in dates:
                fh.write(json.dumps({"date": d, "mtm_today_pct": mtm_pct,
                                     "phase": "forward", "equity_usd": 100_000.0}) + "\n")


def _expected_books():
    from spa_core.strategy_lab.swarm import dwell_hysteresis_forward as dh
    return dh.EXPECTED_BOOKS


def test_tick_carries_ages_states_and_turnover_into_the_book_line(tmp_path):
    """Величина, не доехавшая до строки книги, через 30 дней не существует."""
    dates = [f"2026-06-{d:02d}" for d in range(1, 26)]
    panel_dir = tmp_path / "aggressive_lab"
    _write_live_panel(panel_dir, dates)
    out = tmp_path / "swarm"
    doc = rd.run_forward_tick(panel_dir=panel_dir, out_dir=out, as_of=dates[-1])
    assert doc["state"] == "TRACKING" and doc["book_appended"] is True
    line = json.loads((out / rd.BOOK_NAME).read_text(encoding="utf-8").strip())
    for arm in rd.ARMS:
        view = line["arms"][arm]
        assert set(view["score_age_days"]) == set(_expected_books())
        assert view["day_state"] in {rd.DAY_MEASURED, rd.DAY_CARRIED, rd.DAY_SKIPPED,
                                     rd.DAY_CLOSED_PANEL, rd.DAY_UNRANKABLE}
        assert "turnover_per_year" in view and "concentration_pct" in view
        assert "duty_out_pct" in view
    assert line["arms"]["static"]["role"] == "control"
    assert line["params"]["arms_blended"] is False
