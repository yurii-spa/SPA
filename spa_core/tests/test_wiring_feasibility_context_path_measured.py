"""Контекст-путь стал ИЗМЕРИМЫМ — вечный вердикт «покрытие не измерено» снят.

Карточка `inbox-25-modulei-poluchili-vechnyi-verdikt-pok` (цикл #141 → #142).

**Что было.** Починка тавтологического `WIRABLE` (цикл #141) оставила 25 модулей
с честным, но НЕИЗМЕНЯЕМЫМ вердиктом `COVERAGE_UNMEASURED`: 3 из 3 бывших
`WIRABLE` в Tier-A (весь «пригодный» набор тира) и 22 в Tier-B. Движок на
контекст-пути ADR-031 спрашивает у переданной записи только ключ `protocol`, а
профиль берёт из `_protocol_facts` САМ:

    if _pf.is_protocol_context(params):
        _p = _pf.generic_profile_for(params["protocol"])   # своя запись, не наша

Вердикт правдив, но не менялся НИКОГДА — сколько инструмент ни перезапускай.
Это класс, который проект уже называл: необратимое «не измерено» морит очередь.
Его читают дважды, потом перестают читать вовсе — и в этой же графе однажды
окажется модуль, который действительно надо чинить.

**Что стало.** Источник фактов подменяется на записывающий РОВНО НА ВРЕМЯ
ВЫЗОВА движка (`record_facts_path`), и ключи, которые движок спрашивает у СВОЕЙ
записи, попадают в тот же учёт. Замер на живом реестре (sandbox, 2026-08-17):

    Tier A: COVERAGE_UNMEASURED 3 → 0   (все три → WIRABLE, покрытие 1.0)
    Tier B: COVERAGE_UNMEASURED 22 → 0  (21 → WIRABLE, 1 → UNCOVERED)
    Tier C: 0 → 0                        (радиус не расширился)

Приёмка в ОБЕ стороны, как требовала карточка, и обе подтверждены реальными
модулями: `defi_lending_protocol_bad_debt_monitor` (Tier-A) читает у своей
записи `bad_debt`, `tvl_usd`, `utilization_pct` и получает всё → `WIRABLE`;
`protocol_tvl_filter` (Tier-B) читает `tvl_trend_7d_pct`, которого
`generic_profile_for` НЕ отдаёт (он есть только в `facts_for`), → `UNCOVERED` с
поимённым ключом. Второе — настоящий дефект, а не артефакт инструмента: модуль
молча получает «изменение TVL за 7 дней = 0 %» для каждого протокола.

Каждый тест ниже — положительный контроль: на инструменте ДО цикла #142 первый
и второй краснеют (вердикт был бы `COVERAGE_UNMEASURED`), остальные держат
ловушки, названные карточкой.

Проверки герметичны — ни живого реестра, ни сети, ни `data/`. Понятия времени и
свежести в замере нет вовсе (покрытие ключей — не TTL), поэтому ни инъекции
`now`, ни метки FROZEN-DATE-OK здесь не требуется; стенных часов на уровне
модуля тоже нет.
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
    return _load("_test_wiring_feasibility_context_path",
                 "scripts/audit_tier_c_wiring_feasibility.py")


PROBES = ("aave_v3", "maple", "pendle")

#: Переданная инструментом запись: НЕСЁТ ключ-контекст, ровно как настоящий
#: `generic_profile_for` — из-за чего движок и уходит на контекст-путь.
PASSED = {p: {"protocol": p} for p in PROBES}

#: «Своя» запись движка — то, что отдаёт подменяемый `_protocol_facts`.
#: `utilization_pct` различается ⇒ различие score НАСТОЯЩЕЕ, и отказ (если он
#: будет) идёт от покрытия, а не от слепоты.
OWN_PROFILE = {
    "aave_v3": {"protocol": "aave_v3", "name": "aave_v3", "utilization_pct": 80.0},
    "maple": {"protocol": "maple", "name": "maple", "utilization_pct": 40.0},
    "pendle": {"protocol": "pendle", "name": "pendle", "utilization_pct": 10.0},
}

#: Структурная база, которую настоящий `generic_profile_for` читает ВНУТРИ себя.
#: Её чтения — вопросы БАЗЫ ФАКТОВ, не движка (ловушка 1 карточки).
DEEP_FACTS = {p: {"internal_kind": "lending", "internal_tier": "T1"} for p in PROBES}


class _FakeModule:
    def __init__(self, fn):
        self.analyze = fn


def _probe(feas, monkeypatch, fn, own=None, min_coverage=1.0,
           deep=True):
    """Прогнать движок так, как это делает инструмент, но герметично.

    `own` — то, что отдаёт подменяемый источник фактов (контекст-путь).
    `deep=True` — источник, как настоящий, лезет внутрь в `facts_for`.
    """
    own = OWN_PROFILE if own is None else own
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(fn))

    def _fake_facts(protocol):
        raw = DEEP_FACTS.get(protocol)
        return dict(raw) if raw is not None else None

    # Настоящий `facts_for` тоже подменяется рекордером — значит герметичная
    # база обязана стоять на его месте ДО входа, иначе тест полез бы в живую.
    monkeypatch.setattr(feas._pf, "facts_for", _fake_facts)

    def _facts_source(protocol):
        raw = own.get(protocol)
        if raw is None:
            return None
        if deep:
            # Настоящий `generic_profile_for` устроен именно так: он сам зовёт
            # `facts_for`. Эти чтения в учёт движка попадать НЕ ИМЕЮТ ПРАВА.
            inner = feas._pf.facts_for(protocol)
            if inner is not None:
                inner.get("internal_kind")
                inner.get("internal_tier")
                inner.get("__absent_inside_the_facts_base__")
        return dict(raw)

    def _passed(protocol):
        raw = PASSED.get(protocol)
        return dict(raw) if raw is not None else None

    return feas.probe_module({"module": "fake_mod"}, protocols=PROBES,
                             min_coverage=min_coverage, profile_for=_passed,
                             facts_source=_facts_source)


def _engine_reads(*keys):
    """Движок контекст-пути: у переданной записи спрашивает только `protocol`,
    профиль берёт из `_protocol_facts` сам и читает у НЕГО *keys*."""
    def analyze(records: list):
        from spa_core.analytics import _protocol_facts as _pf
        rec = records[0]
        own = _pf.generic_profile_for(rec["protocol"])
        total = 0.0
        for k in keys:
            v = own.get(k, 0.0)
            total += float(v) if isinstance(v, (int, float)) else 0.0
        return {"risk_score": total}
    return analyze


# ─── приёмка, сторона 1: фактов хватает ⇒ WIRABLE ────────────────────────────

def test_context_path_with_full_facts_becomes_wirable(feas, monkeypatch):
    """ГЛАВНЫЙ контроль. На инструменте до цикла #142 этот движок навсегда
    `COVERAGE_UNMEASURED`: он читает СВОЮ запись, а инструмент видел только
    свою. Реальный аналог — `defi_lending_protocol_bad_debt_monitor`."""
    out = _probe(feas, monkeypatch, _engine_reads("utilization_pct"))
    assert out["verdict"] == "WIRABLE", out
    assert out["coverage_basis"] == "context_path", out
    assert out["effective_coverage"] == 1.0, out
    assert out["effective_missing_keys"] == []
    # различие score НАСТОЯЩЕЕ — иначе вердиктом был бы BLIND, а не покрытие
    assert len(set(out["scores"].values())) == 3, out["scores"]


def test_context_path_read_keys_are_named_not_just_counted(feas, monkeypatch):
    """«Прочитано N ключей» и «прочитаны ВОТ ЭТИ ключи» — разные утверждения;
    без имён вердикт нечем перепроверить."""
    out = _probe(feas, monkeypatch, _engine_reads("utilization_pct"))
    # Ровно то, что движок спросил у СВОЕЙ записи. Ключ-контекст он спросил у
    # ПЕРЕДАННОЙ (см. `test_passed_record_accounting_stays_separate`) — два
    # учёта раздельны, и это здесь видно.
    assert out["context_path_read_keys"] == ["utilization_pct"]
    assert out["context_path_keys_read"] == 1


# ─── приёмка, сторона 2: фактов не хватает ⇒ UNCOVERED с ПОИМЁННЫМ списком ───

def test_context_path_missing_key_becomes_uncovered_and_names_it(feas, monkeypatch):
    """Обратная сторона приёмки: профиль не отдаёт спрошенный ключ ⇒ отказ, и
    ключ НАЗВАН. Реальный аналог — `protocol_tvl_filter` и
    `tvl_trend_7d_pct`."""
    out = _probe(feas, monkeypatch,
                 _engine_reads("utilization_pct", "tvl_trend_7d_pct"))
    assert out["verdict"] == "UNCOVERED", out
    assert out["coverage_basis"] == "context_path", out
    assert "tvl_trend_7d_pct" in out["effective_missing_keys"], out
    # и покрытие названо числом, а не «примерно плохо»
    assert 0.0 < out["effective_coverage"] < 1.0, out


def test_uncovered_on_context_path_reaches_the_markup(feas, monkeypatch, tmp_path):
    """Разметку, которую читает прод (`run_tier_b`), генератор обязан писать по
    ИЗМЕРЕННОМУ покрытию. Писал бы по переданной записи — в файл уехало бы
    тавтологическое `coverage=1.0` с пустым списком, то есть приговор без
    улики."""
    out = _probe(feas, monkeypatch,
                 _engine_reads("utilization_pct", "tvl_trend_7d_pct"))
    # Отметка — относительная (`_freshness.ts`), а не литеральная дата: она
    # здесь не предмет проверки, а обязательное поле отчёта, и литерал сделал бы
    # тест смертным от одного сдвига календаря.
    from spa_core.tests._freshness import ts

    report = {"generated_at": ts(),
              "probe_protocols": list(PROBES), "min_coverage": 1.0,
              "results": [out]}
    path = tmp_path / "_markup.py"
    feas.emit_markup(report, path)
    ns: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    detail = ns["UNSOURCED_DETAIL"]["fake_mod"]
    assert "tvl_trend_7d_pct" in detail["missing_keys"], detail
    assert detail["coverage"] < 1.0, detail


# ─── «не измерено» ОБЯЗАНО отличаться от «измерен ноль» ──────────────────────

def test_engine_that_asks_nobody_stays_unmeasured(feas, monkeypatch):
    """Движок, который не спросил ничего ни у переданной записи, ни у
    подменённого источника (например, связал `facts_for` при импорте — подмене
    такой недоступен), остаётся `COVERAGE_UNMEASURED`. Объявить его пригодным
    «раз возражений нет» — это fail-OPEN."""
    own_facts = dict(OWN_PROFILE)

    def analyze(records: list):
        # различает, но по своему внутреннему справочнику — никого не спросив
        return {"risk_score": own_facts[records[0]["protocol"]]["utilization_pct"]}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "COVERAGE_UNMEASURED", out
    assert out["coverage_basis"] is None, out
    assert out["effective_coverage"] is None, (
        "None значит «не измерено»; 0.0 значило бы «измерено и ноль» — это "
        "разные утверждения, и путать их нельзя")
    assert out["context_path_keys_read"] == 0
    assert out["context_path_coverage"] is None


def test_unmeasured_verdict_names_both_records(feas, monkeypatch):
    """Отказ обязан сказать, что не измерено НИ ТАМ, НИ ТАМ — иначе следующий
    исполнитель пойдёт искать несуществующее третье место."""
    def analyze(records: list):
        return {"risk_score": len(records[0]["protocol"])}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "COVERAGE_UNMEASURED", out
    assert feas.CONTEXT_KEY in out["detail"]
    assert "_protocol_facts" in out["detail"]
    assert "НЕ измерено" in out["detail"]


# ─── ловушка 1: реэнтерабельность — чтения БАЗЫ не чтения движка ─────────────

def test_facts_base_internal_reads_are_not_the_engines_reads(feas, monkeypatch):
    """Настоящий `generic_profile_for` сам зовёт `facts_for`. Записать эти
    чтения — значит выдать вопросы базы фактов за вопросы движка и получить
    покрытие, посчитанное по чужому списку.

    Контроль настоящий: `_facts_source` в фикстуре спрашивает у базы
    `__absent_inside_the_facts_base__`, которого там нет. Утечь этот ключ в
    учёт — и вердикт стал бы UNCOVERED по вине ИНСТРУМЕНТА."""
    out = _probe(feas, monkeypatch, _engine_reads("utilization_pct"), deep=True)
    assert out["verdict"] == "WIRABLE", out
    assert "__absent_inside_the_facts_base__" not in out["context_path_missing_keys"]
    assert "internal_kind" not in out["context_path_read_keys"], (
        "ключ, спрошенный ВНУТРИ базы фактов, попал в учёт движка")
    assert out["context_path_keys_missing"] == 0, out


def test_deep_and_shallow_sources_measure_the_same(feas, monkeypatch):
    """Тот же движок на источнике БЕЗ внутреннего захода даёт тот же замер —
    доказательство, что depth-guard ничего не съел и ничего не добавил."""
    shallow = _probe(feas, monkeypatch, _engine_reads("utilization_pct"),
                     deep=False)
    deep = _probe(feas, monkeypatch, _engine_reads("utilization_pct"),
                  deep=True)
    assert shallow["context_path_read_keys"] == deep["context_path_read_keys"]
    assert shallow["effective_coverage"] == deep["effective_coverage"]


# ─── ловушка 2: чтения ПОСЛЕ движка в счёт не идут ───────────────────────────

def test_patch_is_lifted_before_score_extraction(feas, monkeypatch):
    """`extract_protocol_score` читает запись, когда движок уже ответил; к
    вопросу «что спросил движок» это отношения не имеет. Подмена обязана быть
    снята ДО него — структурно, а не по договорённости."""
    seen: list = []
    real_extract = feas._pf.extract_protocol_score

    def spy(result, profile=None):
        seen.append(feas._FACTS_PATCH_ACTIVE[0])
        return real_extract(result, profile)

    monkeypatch.setattr(feas._pf, "extract_protocol_score", spy)
    out = _probe(feas, monkeypatch, _engine_reads("utilization_pct"))
    assert out["verdict"] == "WIRABLE", out
    assert seen and not any(seen), (
        "extract_protocol_score вызван при АКТИВНОЙ подмене — его чтения "
        "попали бы в покрытие, и оно снова стало бы тавтологическим")


def test_reads_after_the_engine_do_not_change_coverage(feas, monkeypatch):
    """Тот же контроль со стороны результата: `extract_protocol_score`,
    которому подсунули жадное чтение, покрытие не шевелит."""
    base = _probe(feas, monkeypatch, _engine_reads("utilization_pct"))

    real_extract = feas._pf.extract_protocol_score

    def greedy(result, profile=None):
        if isinstance(profile, dict):
            profile.get("__read_after_the_engine__")
        return real_extract(result, profile)

    monkeypatch.setattr(feas._pf, "extract_protocol_score", greedy)
    after = _probe(feas, monkeypatch, _engine_reads("utilization_pct"))
    assert after["context_path_read_keys"] == base["context_path_read_keys"]
    assert after["effective_coverage"] == base["effective_coverage"]
    assert after["verdict"] == base["verdict"] == "WIRABLE"


# ─── подмена глобальна: восстановление и запрет наложения ────────────────────

def test_source_is_restored_byte_for_byte(feas):
    """Подмена — атрибут модуля `_protocol_facts`, то есть видна ВСЕМ. Не
    вернуть её на место значит оставить прод-слой с рекордером внутри."""
    before_generic = feas._pf.generic_profile_for
    before_facts = feas._pf.facts_for
    with feas.record_facts_path([]):
        assert feas._pf.generic_profile_for is not before_generic
    assert feas._pf.generic_profile_for is before_generic
    assert feas._pf.facts_for is before_facts
    assert feas._FACTS_PATCH_ACTIVE[0] is False


def test_source_is_restored_even_when_the_engine_explodes(feas):
    """Исключение движка — обычное дело этого инструмента (вердикт RAISES).
    Оставить после него подмену — значит испортить все последующие замеры."""
    before = feas._pf.generic_profile_for
    with pytest.raises(ValueError):
        with feas.record_facts_path([]):
            raise ValueError("движок отверг вход")
    assert feas._pf.generic_profile_for is before
    assert feas._FACTS_PATCH_ACTIVE[0] is False


def test_nested_entry_is_refused_loudly(feas):
    """Наложение двух подмен смешало бы чтения двух движков — покрытие одного
    было бы выдано за покрытие другого. Это ровно тот класс, который весь
    инструмент и ловит, поэтому отказ громкий, а не «как-нибудь разберётся»."""
    with feas.record_facts_path([]):
        with pytest.raises(RuntimeError, match="уже активен"):
            with feas.record_facts_path([]):
                pass
    assert feas._FACTS_PATCH_ACTIVE[0] is False
    assert feas._pf.generic_profile_for is feas._pf.generic_profile_for


def test_raising_engine_on_context_path_still_raises(feas, monkeypatch):
    """Порядок плеч не поехал: отказ движка — находка о модуле, и она сильнее
    любых рассуждений о покрытии."""
    def analyze(records: list):
        from spa_core.analytics import _protocol_facts as _pf
        _pf.generic_profile_for(records[0]["protocol"])
        raise ValueError("движок отверг профиль")

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "RAISES", out


def test_constant_score_on_context_path_still_blind(feas, monkeypatch):
    """И слепота сильнее покрытия: одинаковый score — более сильное
    утверждение, назвать его обязан BLIND, а не WIRABLE по полному покрытию."""
    def analyze(records: list):
        from spa_core.analytics import _protocol_facts as _pf
        _pf.generic_profile_for(records[0]["protocol"])
        return {"risk_score": 42.0}

    out = _probe(feas, monkeypatch, analyze)
    assert out["verdict"] == "BLIND", out


# ─── учёт РАЗДЕЛЬНЫЙ: тавтология не смеет вернуться под другим именем ────────

def test_passed_record_accounting_stays_separate(feas, monkeypatch):
    """Если ссыпать оба учёта в одно множество, «инструмент положил ключ и сам
    его прочитал» станет неотличимо от «движок спросил ключ» — тавтология
    вернётся, только теперь её будет не видно."""
    out = _probe(feas, monkeypatch, _engine_reads("utilization_pct"))
    # переданная запись: спрошен РОВНО ключ-контекст, и это по-прежнему видно
    assert out["read_keys"] == [feas.CONTEXT_KEY]
    assert out["keys_read"] == 1
    assert out["coverage"] == 1.0, (
        "замер на переданной записи не удаляется — иначе прежний вердикт "
        "нечем перепроверить")
    # но вердикт вынесен НЕ по нему
    assert out["coverage_basis"] == "context_path"
    assert out["context_path_read_keys"] != out["read_keys"]


def test_passed_record_path_is_untouched(feas, monkeypatch):
    """Обратный контроль радиуса: движок, читающий ПЕРЕДАННУЮ запись, судится
    как раньше — по ней, а не по контекст-пути."""
    def analyze(records: list):
        rec = records[0]
        return {"risk_score": float(rec.get("utilization_rate_pct", 0.0))
                + len(rec["protocol"])}

    passed = {"aave_v3": {"protocol": "aave_v3", "utilization_rate_pct": 80.0},
              "maple": {"protocol": "maple", "utilization_rate_pct": 40.0},
              "pendle": {"protocol": "pendle", "utilization_rate_pct": 10.0}}
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(analyze))
    out = feas.probe_module(
        {"module": "fake_mod"}, protocols=PROBES, min_coverage=1.0,
        profile_for=lambda p: dict(passed[p]) if p in passed else None,
        facts_source=lambda p: None)
    assert out["verdict"] == "WIRABLE", out
    assert out["coverage_basis"] == "passed_record", out
    assert out["context_path_keys_read"] == 0


# ─── сторож сторожа: дефект, ради которого всё делалось, ЖИВОЙ ───────────────

def test_the_measured_defect_is_real_not_a_tool_artifact():
    """Находка `protocol_tvl_filter`: он читает `tvl_trend_7d_pct` у
    `generic_profile_for`, а тот его НЕ отдаёт (ключ есть только в `facts_for`)
    — значит модуль молча получает «изменение TVL за 7 дней = 0 %» для КАЖДОГО
    протокола. Вердикт UNCOVERED правдив, и держится он на этом факте о базе.
    Появится ключ в `generic_profile_for` — тест покраснеет и напомнит снять
    пометку, а не оставит её висеть вечно.
    """
    from spa_core.analytics import _protocol_facts as _pf

    generic = _pf.generic_profile_for("aave_v3")
    facts = _pf.facts_for("aave_v3")
    assert generic is not None and facts is not None
    assert "tvl_trend_7d_pct" in facts, (
        "структурная база потеряла ключ — находка перестала быть проверяемой")
    assert "tvl_trend_7d_pct" not in generic, (
        "`generic_profile_for` начал отдавать `tvl_trend_7d_pct` — "
        "перегенерировать разметку: `protocol_tvl_filter` больше не UNCOVERED")


def test_context_key_still_matches_protocol_facts(feas):
    """Отпечаток контекст-пути обязан совпадать с тем, по которому контекст
    опознаёт САМ `_protocol_facts`: разойдутся — и всё измерение выше начнёт
    молча меряться на заглушках."""
    from spa_core.analytics import _protocol_facts as _pf

    assert _pf.is_protocol_context({feas.CONTEXT_KEY: "aave_v3"}) is True
    assert _pf.is_protocol_context({"__not_the_context_key__": "x"}) is False


def test_method_string_states_that_the_context_path_is_measured(feas, monkeypatch,
                                                               tmp_path):
    """Критерий отчёта — машиночитаемый контракт: расширение замера обязано
    быть видно в самом отчёте, а не только в коде."""
    monkeypatch.setattr(feas.registry, "get_tier_modules",
                        lambda tier: [{"module": "fake_mod"}])
    monkeypatch.setattr(feas._ModuleAdapter, "_import_callable",
                        lambda self: _FakeModule(_engine_reads("utilization_pct")))
    monkeypatch.setattr(feas._pf, "generic_profile_for",
                        lambda p: dict(OWN_PROFILE[p]) if p in OWN_PROFILE else None)
    out = tmp_path / "feas.json"
    assert feas.main(["--out", str(out), "--tier", "C"]) == 0

    import json
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "record_facts_path" in report["method"], report["method"]
    assert "coverage_basis" in report["method"], report["method"]
    assert report["counts"] == {"WIRABLE": 1}, report["counts"]
    assert report["wirable"] == ["fake_mod"]
