"""Плечо coverage вырождается, когда движок переданную запись не читает (цикл #141).

Каждый тест — положительный контроль на РЕАЛЬНОЙ находке замера 2026-08-07:
из 25 модулей Tier-B, объявленных `WIRABLE`, **22** спрашивали у переданной
записи ровно один ключ — `protocol`, — после чего брали профиль из
`_protocol_facts` САМ (контекст-путь ADR-031):

    if _pf.is_protocol_context(params):
        _p = _pf.generic_profile_for(params["protocol"])

Инструмент при этом честно писал `keys_read=1, keys_missing=0, coverage=1.0`
и выдавал вердикт «пригоден к проводке». Плечо coverage не измеряло ничего:
единственный спрошенный ключ инструмент сам же и положил в запись. В Tier-A
таких было 3 из 3 — то есть ВЕСЬ «пригодный» набор тира.

Класс — #29/#31/#35–#40 в третий раз (карточка
`inbox-verdikt-wirable-poddelyvaem-22-iz-23-pri`): сторож честно отвечает на
СВОЙ вопрос («отданы ли все прочитанные ключи»), а читается как ответ на нужный
(«измеряет ли модуль протокол по фактам»).

Проверки герметичны — ни живого реестра, ни сети, ни `data/`. Времени и
свежести в замере нет, литеральных дат тоже, поэтому метка FROZEN-DATE-OK не
нужна.
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
    return _load("_test_wiring_feasibility_context_only",
                 "scripts/audit_tier_c_wiring_feasibility.py")


#: Профили-заглушки НЕСУТ ключ-контекст `protocol` — ровно как настоящий
#: `generic_profile_for`, из-за чего движок и уходит на контекст-путь.
PROFILES = {
    "aave_v3": {"protocol": "aave_v3", "utilization_rate_pct": 80.0},
    "maple": {"protocol": "maple", "utilization_rate_pct": 40.0},
    "pendle": {"protocol": "pendle", "utilization_rate_pct": 10.0},
}
PROBES = ("aave_v3", "maple", "pendle")

#: Факты, которые «модуль берёт сам», мимо переданной записи.
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


def _context_path(records: list):
    """Точная копия контекст-пути ADR-031: спросили `protocol`, факты взяли сами."""
    rec = records[0]
    return {"risk_score": _OWN_FACTS[rec["protocol"]]}


# ─── находка: тавтологический WIRABLE ────────────────────────────────────────

def test_context_only_read_is_not_wirable(feas, monkeypatch):
    """ГЛАВНЫЙ контроль. На инструменте без третьего плеча этот движок —
    `WIRABLE` с `coverage=1.0`, хотя переданную запись он не читал."""
    out = _probe(feas, monkeypatch, _context_path)
    assert out["verdict"] == "COVERAGE_UNMEASURED", out
    assert out["verdict"] != "WIRABLE"
    # различие score НАСТОЯЩЕЕ — отказ идёт не от слепоты, а от неизмеримости
    assert len({v for v in out["scores"].values()}) == 3, out["scores"]


def test_context_only_verdict_names_the_reason(feas, monkeypatch):
    """Отказ обязан быть назван поимённо, иначе следующий исполнитель
    прочитает его как «инструмент капризничает»."""
    out = _probe(feas, monkeypatch, _context_path)
    assert feas.CONTEXT_KEY in out["detail"]
    assert "НЕ измерено" in out["detail"]


def test_context_only_still_reports_the_tautological_coverage(feas, monkeypatch):
    """Число, которое ввело в заблуждение, НЕ удаляется из отчёта — иначе
    перепроверить прежний вердикт станет нечем. Меняется вердикт, не замер."""
    out = _probe(feas, monkeypatch, _context_path)
    assert out["coverage"] == 1.0
    assert out["keys_read"] == 1
    assert out["missing_keys"] == []


def test_report_names_the_read_keys(feas, monkeypatch):
    """«Прочитан 1 ключ» и «прочитан ключ-контекст» — разные утверждения,
    и по счётчику их не различить. Имена обязаны быть в отчёте."""
    out = _probe(feas, monkeypatch, _context_path)
    assert out["read_keys"] == [feas.CONTEXT_KEY]


# ─── обратные контроли: «краснеет всегда» за доказательство не сходит ────────

def test_domain_keys_with_full_coverage_stay_wirable(feas, monkeypatch):
    """Движок, который ЧИТАЕТ переданную запись и получает все ключи, обязан
    остаться пригодным — иначе третье плечо просто запретило бы всё."""
    def analyze(records: list):
        return {"risk_score": float(records[0].get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "WIRABLE", out


def test_context_plus_one_domain_key_is_measured(feas, monkeypatch):
    """Граница правила — набор прочитанных ключей РАВЕН {protocol}, а не
    «protocol среди прочитанных». Спрошен хоть один предметный ключ ⇒ плечо
    coverage что-то измерило, и вердикт остаётся обычным."""
    def analyze(records: list):
        rec = records[0]
        rec["protocol"]
        return {"risk_score": float(rec.get("utilization_rate_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "WIRABLE", out
    assert out["read_keys"] == ["protocol", "utilization_rate_pct"]


def test_context_only_with_missing_domain_key_stays_uncovered(feas, monkeypatch):
    """Отказ по покрытию СИЛЬНЕЕ и обязан сохраниться: спрошен ключ, которого
    в записи нет ⇒ UNCOVERED, а не «покрытие не измерено»."""
    def analyze(records: list):
        rec = records[0]
        rec["protocol"]
        return {"risk_score": _OWN_FACTS[rec["protocol"]]
                + float(rec.get("supply_apy_pct", 0.0))}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "UNCOVERED", out
    assert "supply_apy_pct" in out["missing_keys"]


def test_constant_score_on_context_path_stays_blind(feas, monkeypatch):
    """Порядок плеч: одинаковый score — более сильное утверждение, и назвать
    его обязан BLIND. Иначе слепая константа спряталась бы за «не измерено»."""
    def analyze(records: list):
        records[0]["protocol"]
        return {"risk_score": 42.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "BLIND", out


def test_raising_engine_on_context_path_stays_raises(feas, monkeypatch):
    """Отказ движка тоже сильнее: контракт не удовлетворён — это находка
    о модуле, а не о неизмеримости покрытия."""
    def analyze(records: list):
        records[0]["protocol"]
        raise ValueError("движок отверг вход")

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "RAISES", out


# ─── сторож сторожа ──────────────────────────────────────────────────────────

def test_context_key_matches_protocol_facts(feas):
    """Отпечаток контекст-пути обязан совпадать с тем ключом, по которому
    контекст опознаёт САМ `_protocol_facts`. Разойдутся — и тавтологический
    `WIRABLE` вернётся молча, а тесты выше останутся зелёными на своих
    заглушках."""
    from spa_core.analytics import _protocol_facts as _pf

    assert _pf.is_protocol_context({feas.CONTEXT_KEY: "aave_v3"}) is True
    assert _pf.is_protocol_context({"__not_the_context_key__": "aave_v3"}) is False


def test_method_string_states_the_third_arm(feas, monkeypatch, tmp_path):
    """Критерий отчёта — машиночитаемый контракт: ужесточение обязано быть
    видно в самом отчёте, а не только в коде."""
    monkeypatch.setattr(feas.registry, "get_tier_modules",
                        lambda tier: [{"module": "fake_mod"}])
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(_context_path))
    monkeypatch.setattr(feas._pf, "generic_profile_for",
                        lambda p: dict(PROFILES[p]) if p in PROFILES else None)
    out = tmp_path / "feas.json"
    assert feas.main(["--out", str(out), "--tier", "C"]) == 0

    import json
    report = json.loads(out.read_text(encoding="utf-8"))
    assert feas.CONTEXT_KEY in report["method"]
    assert report["counts"] == {"COVERAGE_UNMEASURED": 1}
    # и главное: тавтологический модуль НЕ попал в список пригодных
    assert report["wirable"] == []
