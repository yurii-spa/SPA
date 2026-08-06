"""Тесты `scripts/audit_tier_c_wiring_feasibility.py` (цикл #133).

Каждый тест — положительный контроль: воспроизводит РЕАЛЬНУЮ ловушку, найденную
замером 2026-08-06, и краснеет на инструменте без соответствующего плеча.

Главная из них (`test_differs_but_uncovered_is_refused`) — это буквально
`defi_lending_rate_spread_analyzer`: движок отдал 60/51/36 на трёх протоколах
(по критерию слепоты — «работает»), при том что профиль не содержит ни
`supply_apy_pct`, ни `borrow_apy_pct`. Инструмент, у которого есть только
плечо variance, назвал бы его пригодным к проводке — и мы завели бы
правдоподобное число ни о чём.

Время здесь не участвует (в замере нет понятия свежести), литеральных дат нет —
поэтому и метка FROZEN-DATE-OK не нужна.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def feas():
    return _load("_test_tier_c_wiring_feasibility",
                 "scripts/audit_tier_c_wiring_feasibility.py")


# ─── профили-заглушки ────────────────────────────────────────────────────────

#: Что реально отдаёт `generic_profile_for`: побочные поля есть, предметных нет.
PROFILES = {
    "aave_v3": {"utilization_rate_pct": 80.0, "tvl_usd": 1_000_000.0},
    "maple": {"utilization_rate_pct": 40.0, "tvl_usd": 200_000.0},
    "pendle": {"utilization_rate_pct": 10.0, "tvl_usd": 50_000.0},
}
FULL_PROFILES = {
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
    """Подставной модуль: `probe_module` импортирует через `_ModuleAdapter`,
    поэтому в тестах подменяется сам импорт (см. `_probe`)."""

    def __init__(self, fn):
        self.analyze = fn


def _probe(feas, monkeypatch, fn, table=PROFILES, min_coverage=1.0):
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(fn))
    return feas.probe_module({"module": "fake_mod"}, protocols=PROBES,
                             min_coverage=min_coverage,
                             profile_for=_profile_source(table))


# ─── плечо 1: variance ───────────────────────────────────────────────────────

def test_constant_score_is_blind_not_wirable(feas, monkeypatch):
    """Одинаковый score на всех протоколах = проводка родит новую константу."""
    def analyze(records: list):
        records[0].get("utilization_rate_pct")
        return {"risk_score": 42.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "BLIND", out
    assert out["module"] == "fake_mod"


def test_no_score_is_not_wirable(feas, monkeypatch):
    """Выход, не коэрсимый в score, — dormant, а не «пригоден»."""
    def analyze(records: list):
        records[0].get("utilization_rate_pct")
        return {"note": "нет числа"}

    assert _probe(feas, monkeypatch, analyze)["verdict"] == "NO_SCORE"


def test_raising_engine_is_not_wirable(feas, monkeypatch):
    """Движок отверг профиль ⇒ RAISES, а не молчаливое «пригоден» (fail-CLOSED)."""
    def analyze(records: list):
        records[0]["supply_apy_pct"]          # ключа нет → KeyError
        return {"risk_score": 1.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "RAISES", out
    assert "KeyError" in out["detail"]
    # ключи, прочитанные ДО падения, не теряются — иначе диагноз неполон
    assert "supply_apy_pct" in out["missing_keys"]


# ─── плечо 2: покрытие ключей (то, чего не хватало) ──────────────────────────

def test_differs_but_uncovered_is_refused(feas, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — реальный `defi_lending_rate_spread_analyzer`.

    Движок читает предметные `supply_apy_pct`/`borrow_apy_pct` (их в профиле
    нет → 0.0) и побочный `utilization_rate_pct` (есть). Score различается —
    и различается ПОБОЧНЫМ полем. Инструмент обязан отказать.
    """
    def analyze(records: list):
        rec = records[0]
        supply = float(rec.get("supply_apy_pct", 0.0))
        borrow = float(rec.get("borrow_apy_pct", 0.0))
        util = float(rec.get("utilization_rate_pct", 0.0))
        return {"risk_score": (supply - borrow) + util}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "UNCOVERED", out
    assert len({v for v in out["scores"].values()}) > 1, "score обязан различаться"
    assert set(out["missing_keys"]) == {"supply_apy_pct", "borrow_apy_pct"}
    # покрытие округляется до 4 знаков (контракт отчёта), поэтому и сверка — с
    # тем же допуском: 1 из 3 прочитанных ключей профиль отдаёт
    assert out["coverage"] == pytest.approx(1 / 3, abs=1e-4)


def test_differs_and_fully_covered_is_wirable(feas, monkeypatch):
    """Обратный контроль: полное покрытие + различие ⇒ WIRABLE.

    Без него «краснеет всегда» сошло бы за доказательство строгости.
    """
    def analyze(records: list):
        rec = records[0]
        return {"risk_score": float(rec.get("supply_apy_pct", 0.0))
                + float(rec.get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze, table=FULL_PROFILES)
    assert out["verdict"] == "WIRABLE", out
    assert out["missing_keys"] == []
    assert out["coverage"] == 1.0


def test_membership_test_counts_as_a_question_to_the_record(feas, monkeypatch):
    """`if "k" in rec` — тоже вопрос: молчаливое «нет» уводит в ветку-дефолт
    ровно так же, как `get(k, 0)`, и обязано попадать в missing_keys."""
    def analyze(records: list):
        rec = records[0]
        base = float(rec.get("utilization_rate_pct", 0.0))
        if "early_exit_penalty_pct" in rec:      # ключа нет
            base += 100.0
        return {"risk_score": base}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "UNCOVERED", out
    assert "early_exit_penalty_pct" in out["missing_keys"]


def test_missing_keys_are_unioned_across_protocols(feas, monkeypatch):
    """Замер по ОДНОМУ протоколу занизил бы список отсутствующих ключей:
    движок уходит в другую ветку и спрашивает там новое поле."""
    def analyze(records: list):
        rec = records[0]
        util = float(rec.get("utilization_rate_pct", 0.0))
        if util < 50.0:                                   # только maple/pendle
            rec.get("liquid_alternative_apy_pct")
        return {"risk_score": util}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "UNCOVERED", out
    assert "liquid_alternative_apy_pct" in out["missing_keys"], (
        "ключ, спрошенный только на части протоколов, потерян — "
        "замер по одному протоколу лжёт в пользу пригодности")


def test_min_coverage_is_explicit_not_hidden(feas, monkeypatch):
    """Порог покрытия — ЯВНЫЙ параметр: ослабление видно в отчёте, а не в коде."""
    def analyze(records: list):
        rec = records[0]
        rec.get("supply_apy_pct")
        return {"risk_score": float(rec.get("utilization_rate_pct", 0.0))}

    strict = _probe(feas, monkeypatch, analyze)
    loose = _probe(feas, monkeypatch, analyze, min_coverage=0.4)
    assert strict["verdict"] == "UNCOVERED"
    assert loose["verdict"] == "WIRABLE", "порог обязан быть управляемым"
    assert strict["coverage"] == loose["coverage"], "замер не зависит от порога"


# ─── контракт отчёта / CLI ───────────────────────────────────────────────────

# ─── форма вызова: не выдумывать падение по своей вине ───────────────────────

def test_dict_taking_engine_is_not_miscalled_as_a_list(feas, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ кросс-прогона по Tier-B (цикл #133).

    Движок, объявивший вход как `dict`, при вызове `fn([profile])` упал бы —
    но по вине ИНСТРУМЕНТА, а не модуля, и попал бы в отчёт как «падает».
    Так набралось 268 ложных RAISES на Tier-B.

    **Изменено намеренно, цикл #137 (инв. #16), — проверка УСИЛЕНА, а не снята.**
    Опасность здесь — вызов ЧУЖОЙ формой, и она никуда не делась; менялось
    средство защиты. #133 защищался отказом смотреть вовсе, и цена оказалась
    велика: 18 модулей Tier-C и 186 Tier-B ни разу не были измерены, а их
    непроверенность читалась как осознанный отказ (тот же класс #29/#31/#35–#40 —
    честный ответ на СВОЙ вопрос, читаемый как ответ на нужный). Между тем для
    `dict`-формы выдумывать нечего: движок ждёт РОВНО ту запись, которой и
    является профиль, — правильное средство не «не звать», а «звать верной
    формой». Поэтому тест теперь пиннит саму опасность напрямую: запись
    подаётся как запись, ложного RAISES нет. Что вызов НЕ обёрнут в список —
    отдельный контроль
    `test_wiring_feasibility_dict_shape.py::test_dict_shaped_engine_is_called_with_the_record_itself`.
    Граница осталась: `typed` по-прежнему не зовётся (тест ниже).
    """
    seen = []

    def analyze(context: dict):
        seen.append(context)
        return {"risk_score": float(context.get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["call_shape"] == "dict"
    assert seen and all(isinstance(x, dict) for x in seen), (
        "dict-движок обязан получить ЗАПИСЬ, а не список записей: %r" % (seen[:1],))
    assert out["verdict"] != "RAISES", (
        "ложный RAISES по вине инструмента — ровно та авария #133: %r" % (out,))
    assert out["call_form"] == "fn(profile)"


def test_typed_input_engine_is_not_probed(feas, monkeypatch):
    """Движок с типизированным входом (dataclass) — тоже не наша форма."""
    class BasisTradeInput:
        pass

    def analyze(inp: BasisTradeInput):
        return {"risk_score": 1.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "SHAPE_NOT_PROBED", out
    assert out["call_shape"] == "typed"
    assert out["annotation"] == "BasisTradeInput"


def test_list_shape_is_probed(feas, monkeypatch):
    """Обратный контроль: список-образный вход ПРОБУЕТСЯ (иначе «не пробуем
    никогда» сошло бы за осторожность)."""
    def analyze(markets: list):
        return {"risk_score": float(markets[0].get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] != "SHAPE_NOT_PROBED", out
    assert out["call_shape"] == "list"


def test_unannotated_input_is_not_probed(feas, monkeypatch):
    """Без аннотации форма НЕИЗВЕСТНА ⇒ не пробуем (fail-CLOSED), а не
    «наверное список». Аннотации здесь нет НАМЕРЕННО — в этом весь тест."""
    def analyze(records):          # noqa: ANN001 — отсутствие аннотации проверяем
        return {"risk_score": 1.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "SHAPE_NOT_PROBED", out
    assert out["call_shape"] == "unannotated"


def test_no_entry_is_named_not_silently_ok(feas, monkeypatch):
    class _NoEntry:
        pass

    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _NoEntry())
    out = feas.probe_module({"module": "m"}, protocols=PROBES,
                            profile_for=_profile_source(PROFILES))
    assert out["verdict"] == "NO_ENTRY"


def test_import_error_is_named_not_silently_ok(feas, monkeypatch):
    def _boom(self):
        raise ModuleNotFoundError("нет такого модуля")

    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable", _boom)
    out = feas.probe_module({"module": "m"}, protocols=PROBES,
                            profile_for=_profile_source(PROFILES))
    assert out["verdict"] == "IMPORT_ERR"
    assert "ModuleNotFoundError" in out["detail"]


def test_unknown_protocol_is_skipped_not_counted_as_module_failure(feas, monkeypatch):
    """Протокол вне базы фактов — пробел БАЗЫ, а не поломка модуля."""
    def analyze(records: list):
        return {"risk_score": float(records[0].get("utilization_rate_pct", 0.0))}

    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(analyze))
    out = feas.probe_module({"module": "m"},
                            protocols=PROBES + ("__no_such_protocol__",),
                            profile_for=_profile_source(PROFILES))
    assert "__no_such_protocol__" not in out["scores"]
    assert out["verdict"] in ("WIRABLE", "UNCOVERED")


def test_empty_scan_is_a_finding_not_a_clean_pass(feas, monkeypatch, tmp_path):
    """«Модулей не найдено» = код 2. Пустой скан, отрапортовавший успех, —
    это украшение, а не проверка (правило .claude/rules/deployment.md)."""
    monkeypatch.setattr(feas.registry, "get_tier_modules", lambda tier: [])
    out = tmp_path / "feas.json"
    assert feas.main(["--out", str(out), "--tier", "C"]) == 2


def test_cli_writes_report_and_counts(feas, monkeypatch, tmp_path):
    def analyze(records: list):
        return {"risk_score": float(records[0].get("utilization_rate_pct", 0.0))}

    monkeypatch.setattr(feas.registry, "get_tier_modules",
                        lambda tier: [{"module": "fake_mod"}])
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(analyze))
    monkeypatch.setattr(feas._pf, "generic_profile_for", _profile_source(PROFILES))
    out = tmp_path / "feas.json"
    assert feas.main(["--out", str(out), "--tier", "C"]) == 0

    import json
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["module_count"] == 1
    assert sum(report["counts"].values()) == 1
    assert report["min_coverage"] == 1.0
    assert report["results"][0]["module"] == "fake_mod"
