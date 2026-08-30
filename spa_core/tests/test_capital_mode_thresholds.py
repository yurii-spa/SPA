"""Колонка порогов «реальный пилот» имеет путь в код — и по умолчанию не включена.

# LLM_FORBIDDEN

ADR-060 §3 описывает две колонки порогов: paper и реальный пилот. До 2026-08-29
вторая существовала ТОЛЬКО в тексте: применить её можно было «передачей явного
экземпляра», но ни один вызывающий этого не делал и переключателя не было.
На живых деньгах система поехала бы на бумажных порогах, если бы никто не вспомнил.

Здесь сторожатся три вещи: колонки не перепутаны, по умолчанию остаётся paper
(построить ≠ включить), и **опечатка в режиме даёт СТРОГУЮ колонку, а не мягкую**.
"""
from __future__ import annotations

import pytest

from spa_core.allocator.rebalance_economics import TriggerParams

# Колонки ADR-060 §3, выписанные ЗДЕСЬ как независимая копия: тест обязан ловить
# правку числа в модуле, а не сверять модуль сам с собой.
PAPER = dict(min_gain_pp=0.50, max_payback_days=30.0, min_hold_days=3,
             act_cooldown_days=3, max_turnover_per_move=0.15,
             max_turnover_per_week=0.25, min_leg_frac=0.005,
             reversal_window_days=14, reversal_escalation=1.5)
PILOT = dict(min_gain_pp=0.75, max_payback_days=45.0, min_hold_days=7,
             act_cooldown_days=7, max_turnover_per_move=0.10,
             max_turnover_per_week=0.15, min_leg_frac=0.01,
             reversal_window_days=21, reversal_escalation=2.0)


@pytest.mark.parametrize("field,expect", sorted(PAPER.items()))
def test_paper_column_matches_the_adr(field, expect):
    assert getattr(TriggerParams.for_mode("paper"), field) == pytest.approx(expect)


@pytest.mark.parametrize("field,expect", sorted(PILOT.items()))
def test_pilot_column_matches_the_adr(field, expect):
    assert getattr(TriggerParams.for_mode("pilot"), field) == pytest.approx(expect)


# ── CIO oversight phase E: the contract is NAMED, not just numeric ─────────
#
# Phase E's job (docs/ideas/2026-08-29-cio-oversight-layer.md) is not to invent
# new dials — it is to give the already-accepted ADR-060 §3 mandate a version
# an artifact can carry. These tests pin that identity, independent of the
# numeric thresholds pinned above.


def test_both_columns_carry_the_same_accepted_policy_version():
    """paper vs pilot is a COLUMN choice, not a different accepted policy."""
    paper, pilot = TriggerParams.for_mode("paper"), TriggerParams.for_mode("pilot")
    assert paper.version == pilot.version == "v1.0"
    assert paper.version_date == pilot.version_date == "2026-08-02"  # ADR-060 header


def test_mode_names_which_column_was_resolved():
    assert TriggerParams.for_mode("paper").mode == "paper"
    assert TriggerParams.for_mode("pilot").mode == "pilot"
    # A typo still gets the strict column (see test above) AND is honestly
    # labelled as such — "mode" must never claim "paper" for a pilot column.
    assert TriggerParams.for_mode("piolt").mode == "pilot"


def test_pilot_is_stricter_on_every_dial_that_differs():
    """Смысловая проверка поверх чисел: пилот нигде не мягче бумаги."""
    p, q = TriggerParams.for_mode("paper"), TriggerParams.for_mode("pilot")
    assert q.min_gain_pp > p.min_gain_pp                 # выше планка выгоды
    assert q.min_hold_days > p.min_hold_days             # дольше держим
    assert q.act_cooldown_days > p.act_cooldown_days     # реже ходим
    assert q.max_turnover_per_move < p.max_turnover_per_move   # меньше за раз
    assert q.max_turnover_per_week < p.max_turnover_per_week   # меньше за неделю
    assert q.min_leg_frac > p.min_leg_frac               # шире мёртвая зона
    assert q.reversal_escalation > p.reversal_escalation  # дороже разворот
    # Единственная ручка, одинаковая в обеих колонках, — и это НАМЕРЕННО.
    assert q.below_median_cap_factor == p.below_median_cap_factor == 0.5
    # Окупаемость — единственная «мягче» цифра: на пилоте ход окупается дольше
    # просто потому, что суммы меньше, а газ тот же. Это не послабление.
    assert q.max_payback_days > p.max_payback_days


def test_default_is_paper_building_is_not_enabling(monkeypatch):
    monkeypatch.delenv("SPA_CAPITAL_MODE", raising=False)
    assert TriggerParams.for_mode() == TriggerParams()


@pytest.mark.parametrize("value", ["", "  ", "paper", "PAPER", " Paper "])
def test_paper_spellings_stay_paper(monkeypatch, value):
    monkeypatch.setenv("SPA_CAPITAL_MODE", value)
    assert TriggerParams.for_mode().min_gain_pp == pytest.approx(0.50)


@pytest.mark.parametrize("value", ["pilot", "PILOT", " live ", "real"])
def test_known_real_money_spellings_get_the_strict_column(monkeypatch, value):
    monkeypatch.setenv("SPA_CAPITAL_MODE", value)
    assert TriggerParams.for_mode().min_gain_pp == pytest.approx(0.75)


@pytest.mark.parametrize("typo", ["piolt", "prod", "pilo", "1", "yes"])
def test_a_typo_gets_the_STRICT_column_never_the_lenient_one(monkeypatch, typo, caplog):
    """Сердце этого файла.

    Опечатка в имени режима не имеет права сделать систему снисходительнее.
    Обратное поведение (неизвестное → paper) — это ровно тот тихий провал,
    ради которого переключатель и написан.
    """
    monkeypatch.setenv("SPA_CAPITAL_MODE", typo)
    with caplog.at_level("WARNING"):
        p = TriggerParams.for_mode()
    assert p.min_gain_pp == pytest.approx(0.75), f"{typo!r} получил мягкую колонку"
    assert p.min_hold_days == 7
    assert any("не распознан" in r.getMessage() for r in caplog.records), \
        "молчаливый выбор режима недопустим"


def test_the_explicit_argument_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("SPA_CAPITAL_MODE", "pilot")
    assert TriggerParams.for_mode("paper").min_gain_pp == pytest.approx(0.50)


def test_evaluate_uses_the_mode_not_a_hardcoded_column(monkeypatch):
    """Проводка: переключатель обязан доходить до решения, а не только до класса."""
    import ast
    from pathlib import Path
    from spa_core.allocator import rebalance_economics as re_mod
    src = Path(re_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    bare = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "TriggerParams" and not n.keywords]
    assert not bare, (
        "остался вызов TriggerParams() без выбора колонки — режим до него не дойдёт")
    assert "TriggerParams.for_mode()" in src
