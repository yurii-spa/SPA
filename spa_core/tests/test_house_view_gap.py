"""Тесты сверки офис ↔ книга (ADR-066 C1, `spa_core/monitoring/house_view_gap.py`).

Каждый тест — **положительный контроль**: воспроизводит состояние живой системы
2026-08-05 (или ту аварию, ради которой проверка написана) и краснеет на модуле без
починки. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`).

Время здесь — ВХОД: `run_checks(..., now=)` получает фиксированный `now`, а отметки
входов задаются относительно него. Ни одна фикстура не протухнет от того, что сдвинулся
календарь.
"""
from __future__ import annotations

import datetime as dt

import pytest

from spa_core.monitoring import house_view_gap as H

NOW = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.timezone.utc)


def iso(hours_ago: float = 0.0) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


# ── фикстуры по образцу ЖИВЫХ артефактов 2026-08-05 ──────────────────────────

def house_view(opportunities=None, posture="YELLOW", age_h=3.0):
    return {
        "generated_at": iso(age_h),
        "house_view": {
            "overall_posture": posture,
            "conflicts": ["regime=YELLOW vs threat=NO_THREAT_OBSERVED diverge"],
            "top_opportunities": opportunities if opportunities is not None else [
                {"value": {"protocol": "aerodrome_usdc_lp", "apy_pct": 8.5, "tier": "T2"},
                 "evidence_level": "L3"},
                {"value": {"protocol": "pendle", "apy_pct": 8.0, "tier": "T2"},
                 "evidence_level": "L3"},
                {"value": {"protocol": "pendle_pt_susde", "apy_pct": 8.0, "tier": "T2"},
                 "evidence_level": "L3"},
            ],
            "threat_posture": "NO_THREAT_OBSERVED",
        },
    }


def positions(book=None, age_h=3.0):
    return {"generated_at": iso(age_h),
            "positions": book if book is not None else {
                "pendle": 20000.0, "maple": 20000.0,
                "morpho_steakhouse": 40000.0, "aave_v3": 5000.0}}


def rationale(unexplained=0.0, blocked=(), below_median=("morpho_steakhouse",),
              excess_pct=10.0):
    blocked_str = "blocked_protocols:" + repr(sorted(blocked))
    return {
        "cash": {"cash_pct": 15.0, "buffer_pct": 5.0, "excess_pct": excess_pct,
                 "attribution": [{"reason": blocked_str, "pct": 0.0}],
                 "unexplained_pct": unexplained, "status": "named_not_quantified"},
        "below_median_cap": [{"protocol": p, "apy_pct": 3.5} for p in below_median],
        "decision_shadow": {"decision": "HOLD", "reasons": ["no_material_legs"],
                            "evidence": {"unevidenced_held": []}},
    }


def signals(protocols=None):
    return {"generated_at": iso(3.0),
            "protocols": protocols if protocols is not None else {}}


def run(hv=None, pos=None, rat=None, sig=None, now=NOW, prev=None, red_team=None):
    return H.run_checks(hv, pos, rat, sig, now, prev_first_seen=prev, red_team_doc=red_team)


def keys(report):
    return {f["key"] for f in report["findings"]}


# ── G1: возможность офиса не в книге и отказ НЕ НАЗВАН ───────────────────────

def test_g1_unrefused_opportunity_is_a_finding():
    """Живой факт 2026-08-05: офис держит aerodrome_usdc_lp 8.5 % и pendle_pt_susde 8 %
    (evidence L3), книга их не держит, и ни в blocked_protocols, ни в below_median_cap
    их нет — то есть отказ никем не произнесён. Именно это никто не измерял."""
    r = run(house_view(), positions(), rationale(), signals())
    assert "G1:unrefused_opportunity:aerodrome_usdc_lp" in keys(r)
    assert "G1:unrefused_opportunity:pendle_pt_susde" in keys(r)
    assert r["overall"] == "WARN"


def test_g1_held_opportunity_is_not_a_finding():
    """pendle — тоже возможность офиса, но книга его ДЕРЖИТ. Контроль в обратную
    сторону: сверка не смеет краснеть на согласии."""
    r = run(house_view(), positions(), rationale(), signals())
    assert "G1:unrefused_opportunity:pendle" not in keys(r)


def test_g1_named_refusal_is_not_a_finding():
    """Отказ НАЗВАН (протокол в blocked_protocols) — это честная работа аллокатора,
    а не расхождение. Если бы находка появлялась и здесь, мост завалил бы очередь
    карточками про каждое сознательное решение."""
    r = run(house_view(), positions(),
            rationale(blocked=("aerodrome_usdc_lp", "pendle_pt_susde")), signals())
    assert not any(k.startswith("G1:") for k in keys(r))


def test_g1_below_median_cap_counts_as_named():
    """below_median_cap — тоже названный отказ (ADR-060): протокол ограничен по
    доходности ниже медианы, и это записано."""
    hv = house_view([{"value": {"protocol": "sdai", "apy_pct": 5.0}, "evidence_level": "L4"}])
    r = run(hv, positions(), rationale(below_median=("sdai",)), signals())
    assert not any(k.startswith("G1:") for k in keys(r))


def test_g1_low_evidence_opportunity_is_ignored():
    """Ниже L3 — гипотеза, а не возможность: требовать по ней названного отказа
    значило бы плодить бумагу."""
    hv = house_view([{"value": {"protocol": "unknown_farm", "apy_pct": 40.0},
                      "evidence_level": "L1"}])
    r = run(hv, positions(), rationale(), signals())
    assert not any(k.startswith("G1:") for k in keys(r))


def test_g1_unparseable_evidence_is_unchecked_not_pass():
    """Неразобранный evidence_level — НЕ ИЗМЕРЕНО (инвариант 2), не «прошло»."""
    hv = house_view([{"value": {"protocol": "x_farm", "apy_pct": 9.0},
                      "evidence_level": "высокий"}])
    r = run(hv, positions(), rationale(), signals())
    assert any(u["check"] == "G1" for u in r["unchecked"])
    assert r["overall"] != "OK"


def test_g1_missing_rationale_is_unchecked_not_a_finding():
    """rationale не прочитан ⇒ вопрос «назван ли отказ» НЕ ИЗМЕРЕН. Молчание файла
    не равно «отказ не назван» — иначе каждый сбой чтения рождал бы ложные находки."""
    r = run(house_view(), positions(), None, signals())
    assert not any(k.startswith("G1:") for k in keys(r))
    assert any(u["check"] == "G1" for u in r["unchecked"])
    assert r["overall"] != "OK"


# ── G2: книга держит то, по чему офис негативен ──────────────────────────────

def test_g2_red_signal_on_held_protocol_is_critical():
    """Капитал-релевантно: книга держит $20k в протоколе, по которому аналитика даёт
    RED. Такое обязано доехать до владельца (мост C2: CRITICAL → needs-owner)."""
    r = run(house_view(), positions(), rationale(),
            signals({"maple": {"signal": "RED", "reason": "withdrawal_queue_risk=91"}}))
    assert "G2:held_red:maple" in keys(r)
    assert r["overall"] == "CRITICAL"
    assert r["exit_code"] == 2


def test_g2_warn_signal_is_weak_and_ages_out():
    """Живой факт: ВСЕ четыре удерживаемых протокола имеют жёлтый сигнал. Это
    информативно, но не адресует ничьё решение — сигнал weak и обязан состариться,
    иначе очередь навсегда забита неустранимыми «жёлтыми» (урок irreversible UNCHECKED)."""
    sig = signals({"maple": {"signal": "WARN", "reason": "admin_key_control=67.5"}})
    fresh = run(house_view(), positions(), rationale(), sig)
    assert "G2:held_warn:maple" in keys(fresh)
    assert next(f for f in fresh["findings"] if f["key"] == "G2:held_warn:maple")["class"] == "weak"

    old = run(house_view(), positions(), rationale(), sig,
              prev={"G2:held_warn:maple": iso(hours_ago=24 * (H.WEAK_AGE_DAYS + 1))})
    assert "G2:held_warn:maple" not in keys(old)
    assert any(f["key"] == "G2:held_warn:maple" for f in old["aged"])


def test_g2_signal_on_protocol_we_do_not_hold_is_not_a_finding():
    """Плохой сигнал по чужому протоколу — не наше расхождение."""
    r = run(house_view(), positions(), rationale(),
            signals({"some_other": {"signal": "RED", "reason": "x"}}))
    assert not any(k.startswith("G2:") for k in keys(r))


def test_g2_red_team_threat_on_held_protocol_is_critical():
    """Угроза red-team по удерживаемому протоколу — сильный сигнал того же класса."""
    red = {"threat_posture": {"value": {"threats": [
        {"protocol": "morpho_steakhouse", "description": "oracle manipulation observed"}]}}}
    r = run(house_view(), positions(), rationale(), signals(), red_team=red)
    assert "G2:held_red:morpho_steakhouse" in keys(r)


def test_g2_strong_signal_is_not_masked_by_weak_one():
    """Если по одному протоколу пришли и жёлтый, и красный — побеждает красный."""
    red = {"threat_posture": {"value": {"threats": [{"protocol": "maple", "description": "x"}]}}}
    r = run(house_view(), positions(), rationale(),
            signals({"maple": {"signal": "WARN", "reason": "y"}}), red_team=red)
    assert "G2:held_red:maple" in keys(r)
    assert "G2:held_warn:maple" not in keys(r)


def test_g2_unread_signals_are_unchecked():
    r = run(house_view(), positions(), rationale(), None)
    assert any(u["check"] == "G2" for u in r["unchecked"])


# ── G3 / G4: постура и объяснённость простоя ─────────────────────────────────

def test_g3_red_posture_without_headroom_is_a_finding():
    r = run(house_view(posture="RED"), positions(), rationale(excess_pct=0.0), signals())
    assert "G3:red_posture_no_headroom" in keys(r)


def test_g3_red_posture_with_headroom_is_not_a_finding():
    """Постура RED при живом запасе кэша — не расхождение: книга уже несёт запас."""
    r = run(house_view(posture="RED"), positions(), rationale(excess_pct=10.0), signals())
    assert "G3:red_posture_no_headroom" not in keys(r)


def test_g3_red_posture_without_cash_data_is_unchecked():
    rat = rationale()
    rat["cash"].pop("excess_pct")
    r = run(house_view(posture="RED"), positions(), rat, signals())
    assert any(u["check"] == "G3" for u in r["unchecked"])


def test_g4_unexplained_cash_is_a_finding():
    """Живой факт 2026-08-05: unexplained_pct = 10 %, status=named_not_quantified —
    ровно то, что agent_health зовёт «capital-efficiency LAZY: 10 % простаивает».
    ADR-055 требует объяснять простой КАЖДЫЙ цикл; до сих пор это никуда не приводило."""
    r = run(house_view(), positions(), rationale(unexplained=10.0), signals())
    f = next(f for f in r["findings"] if f["key"] == "G4:unexplained_cash")
    assert "10%" in f["message"]
    assert "ADR-055" in f["message"]


def test_g4_explained_cash_is_not_a_finding():
    r = run(house_view(), positions(), rationale(unexplained=0.0), signals())
    assert "G4:unexplained_cash" not in keys(r)


def test_g4_missing_rationale_is_unchecked():
    r = run(house_view(), positions(), None, signals())
    assert any(u["check"] == "G4" for u in r["unchecked"])


# ── честность вердикта: протухшие входы не дают «OK» ─────────────────────────

def test_stale_house_view_is_unchecked_not_ok():
    """Сверка по протухшему офису — сверка с прошлым. Она обязана называться
    НЕ ИЗМЕРЕНО, а не молча выдавать зелёный."""
    r = run(house_view(age_h=H.HOUSE_VIEW_SLO_H + 1), positions(), rationale(), signals())
    assert r["overall"] != "OK"
    assert any(u["check"] == "house_view" for u in r["unchecked"])
    assert not any(k.startswith("G1:") for k in keys(r))


def test_house_view_without_timestamp_is_unchecked():
    hv = house_view()
    hv.pop("generated_at")
    r = run(hv, positions(), rationale(), signals())
    assert any(u["check"] == "house_view" for u in r["unchecked"])


def test_stale_book_is_unchecked():
    r = run(house_view(), positions(age_h=H.POSITIONS_SLO_H + 1), rationale(), signals())
    assert any(u["check"] == "book" for u in r["unchecked"])
    assert r["held_protocols"] is None


def test_missing_book_is_unchecked_not_empty_book():
    """Нет позиций — это НЕ «книга пуста»: иначе каждая возможность офиса стала бы
    находкой на ровном месте."""
    r = run(house_view(), None, rationale(), signals())
    assert any(u["check"] == "book" for u in r["unchecked"])
    assert not any(k.startswith("G1:") for k in keys(r))


def test_all_clean_is_ok_with_exit_zero():
    """Контроль в зелёную сторону: когда всё вычислено и сошлось — именно OK и 0,
    иначе сторож бесполезен (вечно красный = выключенный)."""
    hv = house_view([{"value": {"protocol": "pendle", "apy_pct": 8.0}, "evidence_level": "L3"}])
    r = run(hv, positions(), rationale(unexplained=0.0), signals())
    assert r["overall"] == "OK"
    assert r["exit_code"] == 0
    assert r["counts"] == {"critical": 0, "warn": 0, "aged": 0, "unchecked": 0}


# ── разбор названных отказов ─────────────────────────────────────────────────

def test_names_in_reason_parses_the_real_blocked_protocols_string():
    """Строка из живого allocation_rationale.json 2026-08-05, слово в слово."""
    reason = ("blocked_protocols:['aave_v3_optimism', 'extra_finance_base', 'fluid_fusdc', "
              "'frax', 'scrvusd', 'sdai', 'sfrax', 'spark_susds', 'stusd', 'susde', 'wusdm']")
    names = H._names_in_reason(reason)
    assert "spark_susds" in names and "wusdm" in names and len(names) == 11


def test_refusal_vocabulary_none_when_rationale_unread():
    assert H.refusal_vocabulary(None) is None
    assert H.refusal_vocabulary({}) == set()


def test_evidence_rank_refuses_to_guess():
    assert H._evidence_rank("L6") == 6
    assert H._evidence_rank("high") is None
    assert H._evidence_rank(None) is None


@pytest.mark.parametrize("overall,code", [("OK", 0), ("WARN", 1), ("UNCHECKED", 1),
                                          ("CRITICAL", 2)])
def test_exit_code_table_matches_conformance(overall, code):
    """Мост C2 читает оба отчёта одним кодом — семантика вердикта обязана совпадать
    с architecture_conformance побуквенно."""
    from spa_core.monitoring import architecture_conformance as A
    assert H.EXIT_BY_OVERALL[overall] == code == A.EXIT_BY_OVERALL[overall]


def test_finding_shape_matches_conformance():
    """Мост потребляет оба источника ОДНИМ кодом: набор полей находки — контракт."""
    r = run(house_view(), positions(), rationale(unexplained=10.0), signals())
    f = r["findings"][0]
    assert set(f) >= {"key", "check", "severity", "class", "message", "first_seen"}


def test_first_seen_is_carried_over_between_runs():
    """Давность находки не должна обнуляться каждым прогоном — на ней держится
    и старение слабых, и порядок очереди в мосте."""
    prev = {"G4:unexplained_cash": iso(hours_ago=72)}
    r = run(house_view(), positions(), rationale(unexplained=10.0), signals(), prev=prev)
    f = next(f for f in r["findings"] if f["key"] == "G4:unexplained_cash")
    assert f["first_seen"] == prev["G4:unexplained_cash"]


def test_module_moves_no_capital():
    """P5: в модуле не может быть ни импорта исполнения, ни импорта RiskPolicy —
    он только сверяет. Проверяем текстом, а не намерением."""
    import inspect
    src = inspect.getsource(H)
    assert "spa_core.execution" not in src
    assert "spa_core.risk" not in src
    assert "LLM_FORBIDDEN" in src
