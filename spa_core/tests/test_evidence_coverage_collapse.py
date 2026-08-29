"""Обвал покрытия наблюдений — поломка производителя, а не сигнал бежать (ADR-169).

# LLM_FORBIDDEN

До этой проверки защита от массовой слепоты срабатывала только ниже ТРЁХ
наблюдаемых протоколов. При восемнадцати это значит: молчит вплоть до
шестнадцати ослепших. Промежуток — 4…16 ослепших — был самым опасным местом
money-path: гейт доказательств применялся, ослепшие протоколы получали цель 0,
и книга уезжала в оставшиеся два-три просто потому, что сломался НАШ файл.

Каждый тест ниже — это тот промежуток.
"""
from __future__ import annotations

import json
import math

import pytest

from spa_core.tests._freshness import ts
from spa_core.allocator import allocator as A


def _write(path, adapters: dict) -> None:
    # Отметка ОТНОСИТЕЛЬНАЯ (_freshness.ts): литеральная дата рядом с понятием
    # свежести — бомба замедленного действия, .claude/rules/deployment.md.
    # Часы сюда не инъектируются, поэтому вариант 2 из правила.
    path.write_text(json.dumps({"generated_at": ts(hours_ago=1),
                                "adapters": adapters}), encoding="utf-8")


# --- знаменатель ------------------------------------------------------------

def test_attempts_counts_listed_not_observed(tmp_path):
    """Перечисленный, но не опрошенный адаптер — это ПОПЫТКА."""
    st = tmp_path / "adapter_status.json"
    _write(st, {f"p{i}": {"live_apy": (4.0 if i < 5 else None)} for i in range(18)})
    assert A._observation_attempts(tmp_path / "нет.json", st) == 18, (
        "знаменатель посчитал наблюдения вместо попыток — тогда покрытие всегда "
        "100 % и правило доли не может сработать никогда")


def test_attempts_ignores_metadata_keys(tmp_path):
    st = tmp_path / "s.json"
    st.write_text(json.dumps({"generated_at": "x", "schema_version": 2,
                              "adapters": {"aave_v3": {}, "maple": {}}}),
                  encoding="utf-8")
    assert A._observation_attempts(st, None) == 2


def test_unreadable_source_contributes_zero_not_an_exception(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("не json", encoding="utf-8")
    assert A._observation_attempts(bad, None) == 0


def test_a_json_document_that_is_not_an_object_is_not_a_denominator(tmp_path):
    lst = tmp_path / "l.json"
    lst.write_text("[1, 2, 3]", encoding="utf-8")
    assert A._observation_attempts(lst, None) == 0


def test_both_producers_are_unioned_not_summed(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write(a, {"aave_v3": {}, "maple": {}})
    _write(b, {"maple": {}, "yearn_v3": {}})
    assert A._observation_attempts(a, b) == 3, "один протокол посчитан дважды"


def test_a_list_shaped_producer_is_read_by_name(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"adapters": [{"name": "aave_v3"}, {"protocol": "maple"}]}),
                 encoding="utf-8")
    assert A._observation_attempts(p, None) == 2


# --- само правило -----------------------------------------------------------

def _required(evidenced: int, attempted: int) -> int:
    """Зовём НАСТОЯЩЕЕ правило. Своя копия арифметики проверяла бы саму себя."""
    return A._required_coverage(attempted)


@pytest.mark.parametrize("evidenced", [3, 4, 6, 8])
def test_the_dangerous_gap_is_now_covered(evidenced):
    """Половина и меньше наблюдаемых из 18 — раньше гейт применялся и книга уезжала.

    Абсолютный порог молчал вплоть до 2 наблюдаемых; теперь требуется 9.
    """
    req = _required(evidenced, 18)
    assert evidenced < req, (
        f"{evidenced} из 18 наблюдаемых снова считается достаточным — вернулась "
        f"ровно та дыра, ради которой написан ADR-169")


@pytest.mark.parametrize("evidenced", [9, 10, 12, 16])
def test_what_this_rule_deliberately_does_NOT_cover(evidenced):
    """Честная граница: потеря трети наблюдений остаётся обычной слепотой.

    Правило владельца — «меньше половины обычного», и граница проходит СТРОГО:
    ровно половина (9 из 18) ещё проходит, защита включается на 8. 12 из 18
    значит, что ослепли шесть протоколов; это правдоподобно как состояние МИРА, и лечится оно
    гейтом ADR-061 и лестницей устаревания ADR-167, а не отключением гейта.
    Тест закреплён, чтобы никто не расширил защиту молча: расширение — это
    ослабление ADR-061 на money-path, и оно требует ADR, а не правки константы.
    """
    assert evidenced >= _required(evidenced, 18)


def test_normal_coverage_still_applies_the_gate():
    """Обратный контроль: сегодняшняя норма НЕ должна отключать гейт."""
    assert 23 >= _required(23, 34), (
        "правило доли гасит гейт доказательств в штатном состоянии — это уже не "
        "защита, а отключение ADR-061")


def test_the_absolute_floor_still_governs_a_tiny_universe():
    """Три из четырёх — доля хорошая, но абсолютного минимума всё равно нет."""
    assert _required(3, 4) == A._EVIDENCE_MIN_COVERAGE
    assert 2 < _required(2, 4), "два наблюдаемых протокола не могут быть достаточными"


def test_unknown_denominator_falls_back_to_the_absolute_floor():
    """Знаменатель не измерен ⇒ правило доли молчит, а не запрещает всё."""
    assert _required(5, 0) == A._EVIDENCE_MIN_COVERAGE


def test_the_fraction_is_a_half_not_a_quorum():
    """Число — предмет решения владельца, а не деталь реализации."""
    assert A._EVIDENCE_MIN_COVERAGE_FRACTION == 0.5
