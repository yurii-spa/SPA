"""Тесты dict-формы в `scripts/audit_tier_c_wiring_feasibility.py` (цикл #137).

**Реальная авария, которую воспроизводят эти тесты.** До 06.08 инструмент звал
ТОЛЬКО `list`-образные движки, а всякий иной вход получал `SHAPE_NOT_PROBED` с
формулировкой «не список записей — не выдумываем вызов». Формулировка читалась
как принципиальная осторожность, но под неё попала форма, для которой выдумывать
нечего: движок, объявивший `analyze(token: dict | None)`, ждёт РОВНО ту запись,
которой и является профиль протокола. Итог — 18 модулей Tier-C и 186 Tier-B ни
разу не были измерены, и их непроверенность выглядела как осознанный отказ.

Это тот же класс, что #29/#31/#35–#40, только этажом выше: сторож честно отвечал
на СВОЙ вопрос («пригоден ли к проводке движок, ждущий список»), а читался как
ответ на нужный («пригоден ли к проводке движок»).

Что дал замер после расширения: из 18 `dict`-модулей Tier-C **wirable = 0**
(10 BLIND, 6 RAISES, 1 UNCOVERED, 1 NO_SCORE) — вывод цикла #133 «Tier-C
wirable=0» устоял и на форме, которой он не видел. Среди них — оба модуля,
которые карточка `inbox-tier-c-pyat-nastoyaschih-otkazov-agregat` относила к
«двум чинящимся»: `protocol_defi_validator_slashing_exposure_analyzer` даёт
константу (BLIND, покрытие 0.27) и `protocol_defi_interest_rate_kink_proximity_analyzer`
различает побочными полями (UNCOVERED, покрытие 0.30, молчаливый дефолт у самого
`kink_utilization_pct`).

Обратные контроли обязательны: граница «не выдумываем вызов» осталась на месте —
`typed` (чужой доменный тип) и `unannotated` по-прежнему НЕ зовутся. Без них
«краснеет всегда» сошло бы за доказательство.

Время здесь не участвует (в замере нет понятия свежести), литеральных дат нет —
поэтому и метка FROZEN-DATE-OK не нужна.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def feas():
    return _load("_test_wiring_feasibility_dict_shape",
                 "scripts/audit_tier_c_wiring_feasibility.py")


#: Побочные поля есть у всех, предметного ключа `supply_apy_pct` нет ни у кого —
#: ровно то, что отдаёт настоящий `generic_profile_for`.
PARTIAL = {
    "aave_v3": {"utilization_rate_pct": 80.0, "tvl_usd": 1_000_000.0},
    "maple": {"utilization_rate_pct": 40.0, "tvl_usd": 200_000.0},
    "pendle": {"utilization_rate_pct": 10.0, "tvl_usd": 50_000.0},
}
#: Профиль отдаёт КАЖДЫЙ читаемый ключ.
FULL = {
    "aave_v3": {"utilization_rate_pct": 80.0, "supply_apy_pct": 4.0},
    "maple": {"utilization_rate_pct": 40.0, "supply_apy_pct": 9.0},
    "pendle": {"utilization_rate_pct": 10.0, "supply_apy_pct": 6.0},
}
PROBES = ("aave_v3", "maple", "pendle")


def _profile_source(table):
    def _get(protocol):
        raw = table.get(protocol)
        return dict(raw) if raw is not None else None
    return _get


class _FakeModule:
    def __init__(self, fn):
        self.analyze = fn


def _probe(feas, monkeypatch, fn, table=PARTIAL, min_coverage=1.0):
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(fn))
    return feas.probe_module({"module": "fake_mod"}, protocols=PROBES,
                             min_coverage=min_coverage,
                             profile_for=_profile_source(table))


# ─── положительные контроли: dict-форма теперь ИЗМЕРЯЕТСЯ ────────────────────

def test_dict_shaped_engine_is_probed_at_all(feas, monkeypatch):
    """Ядро аварии: dict-движок больше не уходит в SHAPE_NOT_PROBED."""
    def analyze(token: dict | None = None) -> dict:
        return {"risk_score": float(token["utilization_rate_pct"])}

    out = _probe(feas, monkeypatch, analyze, table=FULL)
    assert out["verdict"] != "SHAPE_NOT_PROBED", (
        "движок, объявивший `dict`, ждёт ровно профиль — измерять его "
        "нечему мешать")
    assert out["call_shape"] == "dict"


def test_dict_shaped_engine_is_called_with_the_record_itself(feas, monkeypatch):
    """Форма вызова — `fn(profile)`, а НЕ `fn([profile])`.

    Обёртывание записи в список дало бы падение по вине инструмента —
    ровно 268 ложных RAISES цикла #133, только в другую сторону.
    """
    seen: list[Any] = []

    def analyze(token: dict | None = None) -> dict:
        seen.append(token)
        return {"risk_score": float(token["utilization_rate_pct"])}

    out = _probe(feas, monkeypatch, analyze, table=FULL)
    assert seen, "движок обязан быть вызван"
    assert all(isinstance(x, dict) for x in seen), (
        "dict-движку подаётся запись, а не список записей: %r" % (seen[0],))
    assert out["call_form"] == "fn(profile)"


def test_dict_shaped_full_coverage_is_wirable(feas, monkeypatch):
    def analyze(token: dict | None = None) -> dict:
        return {"risk_score": token["utilization_rate_pct"] + token["supply_apy_pct"]}

    out = _probe(feas, monkeypatch, analyze, table=FULL)
    assert out["verdict"] == "WIRABLE"
    assert out["coverage"] == 1.0


def test_dict_shaped_constant_is_blind(feas, monkeypatch):
    """`protocol_defi_validator_slashing_exposure_analyzer` вживую: 0.0 на всех."""
    def analyze(token: dict | None = None) -> dict:
        token.get("num_validators")          # спрошено — и не отдано
        return {"risk_score": 0.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "BLIND", (
        "проводка константы = новая слепая константа, а не сигнал")


def test_dict_shaped_partial_coverage_is_uncovered_with_named_keys(feas, monkeypatch):
    """`protocol_defi_interest_rate_kink_proximity_analyzer` вживую: различает,
    но сам предмет (`kink_utilization_pct`) — молчаливый дефолт."""
    def analyze(token: dict | None = None) -> dict:
        util = token["utilization_rate_pct"]
        kink = token.get("kink_utilization_pct", 80.0)   # выдуманный дефолт
        return {"risk_score": util - kink * 0.0 + util}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "UNCOVERED"
    assert "kink_utilization_pct" in out["missing_keys"], (
        "отказ обязан назвать недостающие ключи поимённо, иначе он неисполним")


def test_dict_shaped_rejection_is_raises_with_verbatim_reason(feas, monkeypatch):
    """`protocol_adoption_scorer` вживую: KeyError: 'unique_users_30d'.

    Текст исключения обязан сохраниться дословно — по нему видно, какого
    ФАКТА не хватает, а значит и то, что дописать его = сочинить вход.
    """
    def analyze(token: dict | None = None) -> dict:
        return {"risk_score": token["unique_users_30d"]}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "RAISES"
    assert "unique_users_30d" in out["detail"]


# ─── обратные контроли: граница «не выдумываем вызов» на месте ───────────────

def test_typed_domain_input_is_still_not_probed(feas, monkeypatch):
    """Чужой доменный тип по-прежнему НЕ зовётся — урок #133/#136.

    ИНВ. #16, намеренная правка (цикл #440): охраняемое утверждение — вызова
    НЕТ (`raise` в теле движка) — стоит дословно на месте. Поправлено только
    имя вердикта: объявленный доменный вход даёт `DECLARED_INPUT_NOT_A_RECORD`
    («провести ЧЕРЕЗ ЭТОТ ВХОД нельзя») вместо `SHAPE_NOT_PROBED` («форма
    неизвестна»). Про способность модуля читать протокол ИНЫМ путём ни один
    из двух вердиктов не говорит — ADR-194 замерил 8 контрпримеров. Обоснование — ADR-195, журнал `docs/journal/2026-W36.md`."""
    class BasisTradeInput:  # noqa: D401 — доменный тип движка
        pass

    def analyze(inp: BasisTradeInput) -> dict:
        raise AssertionError("движок чужой формы не должен быть вызван")

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "DECLARED_INPUT_NOT_A_RECORD"
    assert out["call_shape"] == "typed"


def test_unannotated_input_is_still_not_probed(feas, monkeypatch):
    """Без аннотации форма неизвестна — измерять нечем, и это честный отказ."""
    def analyze(whatever=None):
        raise AssertionError("движок неизвестной формы не должен быть вызван")

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "SHAPE_NOT_PROBED"
    assert out["call_shape"] == "unannotated"


def test_list_shaped_engine_keeps_its_call_form(feas, monkeypatch):
    """Существующее плечо не тронуто: список зовётся как `fn([profile])`."""
    seen: list[Any] = []

    def analyze(records: list) -> dict:
        seen.append(records)
        rec = records[0]
        return {"risk_score": rec["utilization_rate_pct"] + rec["supply_apy_pct"]}

    out = _probe(feas, monkeypatch, analyze, table=FULL)
    assert all(isinstance(x, list) for x in seen), (
        "list-движку по-прежнему подаётся список: %r" % (seen[0],))
    assert out["call_form"] == "fn([profile])"
    assert out["verdict"] == "WIRABLE"
