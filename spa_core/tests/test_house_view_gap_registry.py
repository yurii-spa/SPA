"""Классификация возможности по реестру адаптеров — ЖИВОЙ `house_view_gap` (цикл #206).

Авария, которую эти тесты воспроизводят (прод, 2026-08-12, шаг 0-офис цикла #205):

    [INFO] возможность moonwell_base 8.3346% (evidence L3) вне реестра адаптеров —
           входа технически нет (адаптер + промоушен)
    [INFO] возможность fluid_fusdc 4.85% (evidence L3) вне реестра адаптеров —
           входа технически нет (адаптер + промоушен)

Оба утверждения ЛОЖНЫ: адаптеры у обоих протоколов есть. Причина —
`registry_keys = {_norm(k) for k in ADAPTER_REGISTRY}` при реестре из КОРТЕЖЕЙ
`(имя, тир, класс)`: множество наполнялось строковыми представлениями кортежей, и
`proto not in registry_keys` было истинным ВСЕГДА. Мертвы были обе ветки сразу —
и «вне реестра», и «доступна книге, простой не назван» (WARN), — а отчёт при этом
выглядел рабочим: он всегда возвращал непустой список INFO.

Почему проверок не было раньше: у живого `spa_core/monitoring/house_view_gap.py`
не было своего тест-файла — `test_house_view_gap.py` проверяет ТЕНЕВУЮ реализацию
`house_view_gap_c125.py` (столкновение двух реализаций Фазы 3, 06.08).

Каждый тест — положительный контроль: судит ЭФФЕКТ (какая находка родилась) на
РЕАЛЬНОМ `ADAPTER_REGISTRY`, а не читает исходник. Возврат старой однострочной формы
краснит `test_real_adapter_is_not_declared_technically_unreachable`,
`test_protocol_with_an_adapter_is_the_unnamed_idle_branch` и
`test_registry_keys_are_names_not_tuple_repr`.

Время здесь не участвует: ни одна проверка не зависит от календаря.
LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt

import pytest

from spa_core.monitoring import house_view_gap as H

NOW = dt.datetime(2026, 8, 12, 12, 0, tzinfo=dt.timezone.utc)

#: Протоколы, у которых адаптер РЕАЛЬНО есть; ровно те, о которых прод соврал 12.08.
REAL_ADAPTERS = ("moonwell_base", "fluid_fusdc")

#: Имени нет ни в одном реестре — «вне реестра» про него обязано звучать по-прежнему.
NO_SUCH_PROTOCOL = "protocol_that_has_no_adapter_anywhere"


def chief(protocol: str, apy: float = 8.3346) -> dict:
    """house_view офиса с ОДНОЙ возможностью — снимок прода 12.08 по форме."""
    return {"house_view": {"overall_posture": "YELLOW",
                           "top_opportunities": [{"evidence_level": "L3", "source": "defillama",
                                                  "value": {"protocol": protocol, "apy_pct": apy}}]}}


def book_without(protocol: str) -> dict:
    """Книга, которая этот протокол НЕ держит (иначе гэпа нет по построению)."""
    return {"capital_usd": 100000.0, "cash_usd": 10000.0,
            "positions": {"aave_v3": {"usd": 40000.0}, "maple": {"usd": 50000.0}}}


#: Отказ НЕ назван — иначе сработает ветка `opportunity_explained` и до реестра дело не дойдёт.
RATIONALE_SILENT = {"below_median_cap": [], "decision_shadow": {"warnings": []}}


def gap_keys(report: dict) -> set[str]:
    return {g["key"] for g in report["gaps"]}


def run_for(protocol: str, registry_keys) -> dict:
    return H.compute_gaps(chief(protocol), book_without(protocol), RATIONALE_SILENT,
                          registry_keys, {}, NOW)


# ── 1. Сам извлекатель имён ──────────────────────────────────────────────────

def test_registry_keys_are_names_not_tuple_repr():
    """Ключи — ИМЕНА протоколов. Старая форма клала сюда `("moonwell_base", "t2", <class ...>)`."""
    keys = H.registry_protocol_keys()
    assert keys, "реестр не прочитан — дальнейшие проверки бессмысленны"
    assert all(isinstance(k, str) for k in keys)
    assert not [k for k in keys if k.startswith("(") or "<class" in k], \
        "в множество попало строковое представление кортежа, а не имя протокола"


@pytest.mark.parametrize("protocol", REAL_ADAPTERS)
def test_protocols_the_office_called_unreachable_are_in_the_registry(protocol):
    """Замер прода: у обоих «недостижимых» протоколов адаптер есть."""
    assert protocol in H.registry_protocol_keys()


def test_dict_shaped_registry_is_read_as_names(monkeypatch):
    """Под именем ADAPTER_REGISTRY в репо живут ДВЕ формы; читаем форму, а не предполагаем её."""
    import spa_core.adapters as adapters_mod
    monkeypatch.setattr(adapters_mod, "ADAPTER_REGISTRY",
                        {"aave_usdc": {"tier": "T1"}, "notional_v3": {"tier": "T2"}}, raising=False)
    assert H.registry_protocol_keys() == {"aave_usdc", "notional_v3"}


def test_plain_names_registry_still_works(monkeypatch):
    import spa_core.adapters as adapters_mod
    monkeypatch.setattr(adapters_mod, "ADAPTER_REGISTRY", ["aave_v3", "maple"], raising=False)
    assert H.registry_protocol_keys() == {"aave_v3", "maple"}


# ── 2. Fail-CLOSED: «не измерено» ≠ «ни у кого нет адаптера» ─────────────────

def test_empty_registry_is_unmeasured_not_all_missing(monkeypatch):
    """Пустой реестр ⇒ None. Пустое множество означало бы ту же ложь, только тише."""
    import spa_core.adapters as adapters_mod
    monkeypatch.setattr(adapters_mod, "ADAPTER_REGISTRY", [], raising=False)
    assert H.registry_protocol_keys() is None


def test_malformed_registry_is_unmeasured(monkeypatch):
    import spa_core.adapters as adapters_mod

    class Explodes:
        def __iter__(self):
            raise RuntimeError("реестр нечитаем")

    monkeypatch.setattr(adapters_mod, "ADAPTER_REGISTRY", Explodes(), raising=False)
    assert H.registry_protocol_keys() is None


def test_unmeasured_registry_does_not_claim_no_adapter():
    """`None` обязан вести в ветку «классификация не измерима», а не в приговор «входа нет»."""
    report = run_for("moonwell_base", None)
    assert "gap:opportunity_unclassified:moonwell_base" in gap_keys(report)
    assert "gap:opportunity_no_adapter:moonwell_base" not in gap_keys(report)


# ── 3. ЭФФЕКТ на реальном реестре — то, ради чего всё написано ───────────────

@pytest.mark.parametrize("protocol", REAL_ADAPTERS)
def test_real_adapter_is_not_declared_technically_unreachable(protocol):
    """Прод печатал это про оба протокола ежедневно. Больше не должен."""
    report = run_for(protocol, H.registry_protocol_keys())
    assert f"gap:opportunity_no_adapter:{protocol}" not in gap_keys(report)
    assert not [g for g in report["gaps"] if "вне реестра" in g["message"]], \
        "офис снова объявляет достижимую возможность технически недостижимой"


@pytest.mark.parametrize("protocol", REAL_ADAPTERS)
def test_protocol_with_an_adapter_is_the_unnamed_idle_branch(protocol):
    """Вторая мёртвая ветка: возможность доступна, не держится, отказ не назван ⇒ WARN.

    До починки эта ветка не срабатывала НИКОГДА — сигнал, ради которого сверка и заведена
    (дух ADR-055: простой капитала обязан быть НАЗВАН), не рождался ни разу.
    """
    report = run_for(protocol, H.registry_protocol_keys())
    assert f"gap:opportunity_unnamed:{protocol}" in gap_keys(report)
    assert report["counts"]["warn"] >= 1


def test_protocol_without_an_adapter_is_still_reported():
    """Контроль в ОБРАТНУЮ сторону: починка не должна погасить настоящую находку."""
    report = run_for(NO_SUCH_PROTOCOL, H.registry_protocol_keys())
    assert f"gap:opportunity_no_adapter:{NO_SUCH_PROTOCOL}" in gap_keys(report)


def test_named_refusal_still_wins_over_registry_classification():
    """Порядок веток не изменён: названный отказ закрывает вопрос раньше реестра."""
    report = H.compute_gaps(chief("moonwell_base"), book_without("moonwell_base"),
                            {"below_median_cap": [{"protocol": "moonwell_base"}],
                             "decision_shadow": {"warnings": []}},
                            H.registry_protocol_keys(), {}, NOW)
    assert "gap:opportunity_explained:moonwell_base" in gap_keys(report)


def test_held_protocol_is_not_a_gap_at_all():
    """Держим — гэпа нет; реестр к этому вопросу отношения не имеет."""
    report = H.compute_gaps(chief("aave_v3"), book_without("x"), RATIONALE_SILENT,
                            H.registry_protocol_keys(), {}, NOW)
    assert not [k for k in gap_keys(report) if k.endswith(":aave_v3")]


def test_module_still_moves_no_capital():
    """Advisory-слой: сверка ничего не гейтит и капитал не двигает."""
    src = open(H.__file__, encoding="utf-8").read()
    assert "spa_core.execution" not in src
    assert "LLM_FORBIDDEN" in src
