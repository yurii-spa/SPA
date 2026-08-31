"""Плечо coverage судит о ФАКТАХ протокола, а не о служебной проводке (цикл #441).

Каждый тест — положительный контроль на РЕАЛЬНОМ замере 31.08 по живой
популяции Tier-B (479 модулей), сделанном до правки:

    context/unannotated модулей: 32
    вердикты при наивном вызове: UNCOVERED 18 · COVERAGE_UNMEASURED 10 ·
                                 BLIND 2 · RAISES 1 · NO_SCORE 1
    отсутствующие ключи, по частоте:  19  data_dir        ← и БОЛЬШЕ НИКАКИХ

То есть у всех восемнадцати «непокрытых» модулей несошедшийся ключ был ОДИН
и тот же — `data_dir`, «где лежит состояние». Утверждением о протоколе он не
является, и в профиле `_protocol_facts` его нет по построению; движок
спрашивает его у КОНТЕКСТА. Считать его отсутствующим — значит краснеть на
собственном контракте вызова.

Цена бездействия перемерена отдельно и сошлась с тем, что владелец назвал в
карточке: ни один из этих 18 модулей не числится сегодня ни в
`UNSOURCED_MODULES`, ни в `PROTOCOL_BLIND_MODULES` — все 18 исполняются в
советующем сигнале ПРЯМО СЕЙЧАС. `UNCOVERED` уезжает в разметку
(`emit_markup`), а `signal_aggregator.run_tier_b` исключает размеченный модуль
из composite и из числителя confidence. Следующая перегенерация разметки
выключила бы восемнадцать работающих модулей МОЛЧА и по признаку, который мы
сами считаем не относящимся к делу.

Решение владельца 2026-08-31 13:32Z (карточка
`owner-decision-vse-82-izmereny-krome-odnogo-i-devyat-iz`, вариант 1):
«сначала научить проверку отличать факт протокола от служебной проводки, и
только потом звать те 29». Разбор — ADR-196.

**Обратные контроли обязательны и здесь.** Послабление плеча — это ослабление
сторожа, и тест обязан краснеть в ОБЕ стороны: ключ, которого в профиле нет,
но который является фактом, снимать НЕЛЬЗЯ; и ключ из `SERVICE_KEYS`, который
в профиле ЕСТЬ, — это факт, а не проводка, и в списке ему не место.

Проверки герметичны — ни живого реестра, ни сети, ни `data/`. Времени и
свежести в замере нет, литеральных дат тоже, поэтому метка FROZEN-DATE-OK
не нужна.
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
    return _load("_test_wiring_feasibility_service_keys",
                 "scripts/audit_tier_c_wiring_feasibility.py")


#: Профили-заглушки — как настоящий `generic_profile_for`: несут ключ-контекст
#: `protocol` и факты о протоколе, и НЕ несут `data_dir` (его там нет и быть
#: не должно — это не утверждение о протоколе).
PROFILES = {
    "aave_v3": {"protocol": "aave_v3", "utilization_rate_pct": 80.0},
    "maple": {"protocol": "maple", "utilization_rate_pct": 40.0},
    "pendle": {"protocol": "pendle", "utilization_rate_pct": 10.0},
}
PROBES = ("aave_v3", "maple", "pendle")

#: Факты, которые движок на контекст-пути ADR-031 берёт САМ, мимо записи.
_OWN_FACTS = {"aave_v3": 40.8, "maple": 62.5, "pendle": 48.9}


class _FakeModule:
    def __init__(self, fn):
        self.analyze = fn


def _probe(feas, monkeypatch, fn, table=PROFILES, min_coverage=1.0):
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(fn))

    def _get(protocol):
        raw = table.get(protocol)
        return dict(raw) if raw is not None else None

    return feas.probe_module({"module": "fake_mod"}, protocols=PROBES,
                             min_coverage=min_coverage, profile_for=_get)


def _ctx_plus_data_dir(records: list):
    """Дословный портрет тех 18 модулей: спросили `protocol`, спросили
    `data_dir` (которого в профиле нет), факты взяли из `_protocol_facts` сами.

    `read = {protocol, data_dir}`, `missing = {data_dir}` ⇒ до правки
    coverage = 0.5 < 1.0 ⇒ `UNCOVERED` ⇒ разметка ⇒ модуль выключен.
    """
    rec = records[0]
    rec.get("data_dir", "")
    return {"risk_score": _OWN_FACTS[rec["protocol"]]}


# ─── ГЛАВНЫЙ контроль: авария 31.08 воспроизведена ──────────────────────────

def test_service_key_alone_does_not_produce_uncovered(feas, monkeypatch):
    """На инструменте БЕЗ различения факта и проводки этот движок — `UNCOVERED`
    с coverage=0.5, и разметка выключает его. Это и есть те 18 модулей."""
    out = _probe(feas, monkeypatch, _ctx_plus_data_dir)
    assert out["verdict"] != "UNCOVERED", out
    assert out["verdict"] == "COVERAGE_UNMEASURED", out


def test_service_key_never_lands_in_markup(feas, monkeypatch):
    """Прямая проверка ПОСЛЕДСТВИЯ, а не только вердикта: в разметку уезжает
    ровно `UNCOVERED`, и модуль, споткнувшийся об `data_dir`, туда попасть
    не должен — иначе `run_tier_b` исключит его из composite."""
    out = _probe(feas, monkeypatch, _ctx_plus_data_dir)
    report = {"generated_at": "T", "probe_protocols": list(PROBES),
              "min_coverage": 1.0, "results": [out]}
    dest = Path(__import__("tempfile").mkdtemp()) / "_protocol_key_coverage.py"
    feas.emit_markup(report, dest)
    text = dest.read_text(encoding="utf-8")
    assert "fake_mod" not in text, text


def test_ignored_service_key_is_named_in_the_report(feas, monkeypatch):
    """Послабление плеча, о котором отчёт молчит, — тот самый дефект, который
    инструмент ловит у других. Снятое обязано быть НАЗВАНО."""
    out = _probe(feas, monkeypatch, _ctx_plus_data_dir)
    assert out["service_keys_ignored"] == ["data_dir"], out
    assert "data_dir" in out["detail"], out["detail"]


def test_service_key_is_not_counted_as_a_protocol_fact(feas, monkeypatch):
    """`data_dir` снят с ОБОИХ плеч: он не «прочитанный ключ» и не
    «отсутствующий». Иначе он вернулся бы в знаменатель другой дорогой."""
    out = _probe(feas, monkeypatch, _ctx_plus_data_dir)
    assert out["read_keys"] == [feas.CONTEXT_KEY], out
    assert out["missing_keys"] == [], out


def test_only_service_keys_read_is_unmeasured_not_uncovered(feas, monkeypatch):
    """Движок спросил ТОЛЬКО ключ проводки: набор фактов пуст. Пустое — это
    «не измерено», а не измеренный отрицательный вердикт. Проверка условия
    ПОДМНОЖЕСТВОМ, а не равенством: на равенстве этот случай проваливался
    ниже, в `coverage is None`, и печатал `UNCOVERED`."""
    calls = {"n": 0}

    def analyze(records: list):
        rec = records[0]
        rec.get("data_dir", "")
        calls["n"] += 1
        return {"risk_score": float(calls["n"])}   # различает

    out = _probe(feas, monkeypatch, analyze)
    assert out["read_keys"] == [], out
    assert out["verdict"] == "COVERAGE_UNMEASURED", out
    assert "ни одного ключа-факта" in out["detail"], out["detail"]


def test_report_names_the_service_key_set(feas, monkeypatch):
    """Читатель артефакта обязан видеть послабление, не открывая инструмент."""
    monkeypatch.setattr(feas.registry, "get_tier_modules", lambda tier: [])
    report = feas.run_audit("B")
    assert report["service_keys"] == ["data_dir"]
    assert "data_dir" in report["method"]


# ─── ОБРАТНЫЕ контроли: «всегда пропускает» за починку не сходит ────────────

def test_real_missing_fact_still_uncovered(feas, monkeypatch):
    """ГЛАВНЫЙ обратный контроль. Отсутствующий ключ-ФАКТ обязан краснеть
    по-прежнему — иначе правка не различила факт и проводку, а просто
    отключила плечо coverage."""
    def analyze(records: list):
        rec = records[0]
        rec.get("data_dir", "")                    # проводка — снимается
        rec.get("borrow_apy_pct", 0.0)             # ФАКТ, которого в профиле нет
        return {"risk_score": float(rec.get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "UNCOVERED", out
    assert out["missing_keys"] == ["borrow_apy_pct"], out
    assert out["service_keys_ignored"] == ["data_dir"], out


def test_full_coverage_module_stays_wirable(feas, monkeypatch):
    """Движок, читающий запись и получающий все факты, остаётся пригодным —
    и наличие ключа проводки этого не отменяет."""
    def analyze(records: list):
        rec = records[0]
        rec.get("data_dir", "")
        return {"risk_score": float(rec.get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "WIRABLE", out
    assert out["service_keys_ignored"] == ["data_dir"], out


def test_blind_module_stays_blind(feas, monkeypatch):
    """Слепота — утверждение сильнее покрытия, и порядок вердиктов правка
    не трогает."""
    def analyze(records: list):
        records[0].get("data_dir", "")
        return {"risk_score": 42.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "BLIND", out


def test_module_without_service_keys_reports_empty_list(feas, monkeypatch):
    """Пустой `service_keys_ignored` — тоже утверждение: у этого модуля с
    плеча не снято НИЧЕГО. Отсутствие поля читалось бы как «не смотрели»."""
    def analyze(records: list):
        return {"risk_score": float(records[0].get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["service_keys_ignored"] == [], out
    assert out["verdict"] == "WIRABLE", out


# ─── контроль состава списка: проводка ≠ факт ───────────────────────────────

def test_service_keys_are_absent_from_every_probe_profile(feas):
    """Условие внесения ключа в `SERVICE_KEYS`, закреплённое машинно: ключ,
    который в профиле протокола ЕСТЬ, — это ФАКТ, и снимать его с плеча
    нельзя. Иначе список однажды тихо начнёт прятать настоящие пробелы."""
    import spa_core.analytics._protocol_facts as pf

    seen = 0
    for proto in feas.PROBE_PROTOCOLS:
        profile = pf.generic_profile_for(proto)
        if profile is None:
            continue
        seen += 1
        for key in feas.SERVICE_KEYS:
            assert key not in profile, (
                f"`{key}` есть в профиле `{proto}` — это факт протокола, "
                "а не служебная проводка; из SERVICE_KEYS его надо убрать")
    assert seen > 0, "ни один пробный профиль не прочитан — проверка пуста"


def test_service_key_set_is_narrow(feas):
    """Каждый ключ здесь ослабляет плечо coverage. Рост списка — это решение,
    а не правка: он обязан быть замечен ревью, а не проехать молча."""
    assert feas.SERVICE_KEYS == frozenset({"data_dir"}), feas.SERVICE_KEYS
