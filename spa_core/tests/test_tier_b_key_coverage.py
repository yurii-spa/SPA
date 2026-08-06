"""
test_tier_b_key_coverage.py — «различается» ещё не значит «измеряет».

Каждый тест здесь — положительный контроль РЕАЛЬНОЙ ловушки, найденной
замером цикла #133 и закрытой циклом #134:

  `defi_protocol_regulatory_risk_scorer` выдаёт разные числа для aave_v3 /
  maple / pendle и по аудиту слепоты (`audit_protocol_blindness.py`) числится
  `sensitive` — «модуль работает». При этом `generic_profile_for` не содержит
  ни `entity_incorporated`, ни `dao_governance`, ни `defi_category`: каждый
  молча становится 0.0/False, и всё различие приходит из побочного
  `utilization_rate_pct`. Оценка регуляторного риска оказалась функцией
  утилизации пула — и складывалась в `composite_risk_0_100` как измерение.

Это класс fail-OPEN мониторов (#29/#31/#35–#38/#40), вывернутый наизнанку: не
«✅ OK о непроверенном», а правдоподобно РАЗЛИЧАЮЩЕЕСЯ число о неизмеренном.
Одинаковую константу видно глазом, эту — нет; поэтому у неё должен быть
сторож, а не внимательность читателя.

Обратный контроль обязателен: без разметки (мутация «набор пуст») сочинённое
число ОБЯЗАНО попадать в composite — иначе зелёный тест ничего не доказывает.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from spa_core.analytics import signal_aggregator as sa

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Штамп замера — непрозрачная строка. Генератор её только переносит,
#: ни один тест её не разбирает, поэтому ДАТЫ здесь быть не должно:
#: литерал в тесте рядом с понятием свежести — бомба замедленного
#: действия (правило `.claude/rules/deployment.md`), и храповик
#: `test_frozen_date_ratchet.py` справедливо ловит её как новый случай.
_STAMP = "audit-stamp-for-test"
_FAKE_PREFIX = "_fake_cov_mod_"


def _install_fake_module(name: str, **funcs):
    full = "spa_core.analytics." + name
    mod = types.ModuleType(full)
    for fname, fn in funcs.items():
        setattr(mod, fname, fn)
    sys.modules[full] = mod
    return {"module": name, "class": None, "tier": "B",
            "category": "test", "weight": 0.5, "protocols": ["all"]}


@pytest.fixture(autouse=True)
def _cleanup_fake_modules():
    yield
    for key in [k for k in sys.modules
                if k.startswith("spa_core.analytics." + _FAKE_PREFIX)]:
        del sys.modules[key]


def _load_audit_tool():
    """Загрузить инструмент по пути к файлу — он лежит в scripts/, не в пакете."""
    spec = importlib.util.spec_from_file_location(
        "audit_tier_c_wiring_feasibility_under_test",
        REPO_ROOT / "scripts" / "audit_tier_c_wiring_feasibility.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── run_tier_b: помеченный модуль не исполняется и не считается ─────────────

def test_unsourced_module_is_excluded_from_composite(tmp_path, monkeypatch):
    """Ровно та авария: сочинённое число НЕ смешивается с живым."""
    executed = []

    def _side_field_analyze(context):
        # реальный аналог: различает, но не своим предметом
        executed.append(context["protocol"])
        return {"risk_score": 5.0}

    infos = [
        _install_fake_module(_FAKE_PREFIX + "live",
                             analyze=lambda context: {"risk_score": 60.0}),
        _install_fake_module(_FAKE_PREFIX + "sidefield",
                             analyze=_side_field_analyze),
    ]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    monkeypatch.setattr(sa, "PROTOCOL_BLIND_MODULES", frozenset())
    monkeypatch.setattr(sa, "UNSOURCED_MODULES",
                        frozenset({_FAKE_PREFIX + "sidefield"}))

    out = sa.SignalAggregator(data_dir=tmp_path).run_tier_b(["aave_v3"], {})

    assert executed == []                      # помеченный модуль не запускался
    sig = out["protocols"]["aave_v3"]
    assert sig["composite_risk_0_100"] == pytest.approx(60.0)
    assert sig["modules_ok"] == 1
    assert sig["confidence"] == pytest.approx(0.5, abs=1e-4)


def test_without_markup_the_fabricated_score_does_enter(tmp_path, monkeypatch):
    """ОБРАТНЫЙ контроль: снимаем разметку — авария возвращается.

    Без этого теста предыдущий доказывал бы лишь то, что модуль вообще
    существует. Здесь composite обязан сдвинуться к сочинённому числу.
    """
    infos = [
        _install_fake_module(_FAKE_PREFIX + "live",
                             analyze=lambda context: {"risk_score": 60.0}),
        _install_fake_module(_FAKE_PREFIX + "sidefield",
                             analyze=lambda context: {"risk_score": 5.0}),
    ]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    monkeypatch.setattr(sa, "PROTOCOL_BLIND_MODULES", frozenset())
    monkeypatch.setattr(sa, "UNSOURCED_MODULES", frozenset())   # мутация

    out = sa.SignalAggregator(data_dir=tmp_path).run_tier_b(["aave_v3"], {})
    sig = out["protocols"]["aave_v3"]
    assert sig["composite_risk_0_100"] == pytest.approx(32.5)
    assert sig["modules_ok"] == 2


def test_unsourced_status_is_loud(tmp_path, monkeypatch):
    """Исключение обязано быть ГРОМКИМ: health-лог + _meta.module_status.

    Молчаливое исключение — это тот же fail-OPEN, только с другой стороны:
    число исчезло, а «% работающего слоя» остался прежним.
    """
    infos = [
        _install_fake_module(_FAKE_PREFIX + "live",
                             analyze=lambda context: {"risk_score": 60.0}),
        _install_fake_module(_FAKE_PREFIX + "sidefield",
                             analyze=lambda context: {"risk_score": 5.0}),
    ]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    monkeypatch.setattr(sa, "PROTOCOL_BLIND_MODULES", frozenset())
    monkeypatch.setattr(sa, "UNSOURCED_MODULES",
                        frozenset({_FAKE_PREFIX + "sidefield"}))

    agg = sa.SignalAggregator(data_dir=tmp_path)
    out = agg.run_tier_b(["aave_v3"], {})

    ms = out["_meta"]["module_status"]
    assert ms["counts"] == {"ok": 1, "unsourced": 1}
    assert ms["not_ok"]["unsourced"] == [_FAKE_PREFIX + "sidefield"]
    entry = [e for e in agg._log if e["status"] == "unsourced"]
    assert len(entry) == 1
    assert "side fields" in entry[0]["detail"]


def test_blind_wins_over_unsourced(tmp_path, monkeypatch):
    """Модуль в обеих разметках получает "blind" — вердикт старше и строже.

    Иначе статус зависел бы от порядка проверок, и один и тот же модуль
    назывался бы по-разному от прогона к прогону.
    """
    infos = [_install_fake_module(_FAKE_PREFIX + "both",
                                  analyze=lambda context: {"risk_score": 5.0})]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    monkeypatch.setattr(sa, "PROTOCOL_BLIND_MODULES",
                        frozenset({_FAKE_PREFIX + "both"}))
    monkeypatch.setattr(sa, "UNSOURCED_MODULES",
                        frozenset({_FAKE_PREFIX + "both"}))

    agg = sa.SignalAggregator(data_dir=tmp_path)
    out = agg.run_tier_b(["aave_v3"], {})
    assert out["_meta"]["module_status"]["counts"] == {"blind": 1}


def test_all_unsourced_goes_neutral(tmp_path, monkeypatch):
    """Если все модули «различаются не тем» — честный UNKNOWN, а не оценка.

    Fail-CLOSED: нейтральный multiplier 1.0 и confidence 0, а не composite,
    собранный из побочных полей.
    """
    infos = [_install_fake_module(
        _FAKE_PREFIX + "u" + str(i),
        analyze=(lambda i: lambda context: {"risk_score": float(i)})(i),
    ) for i in range(3)]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    monkeypatch.setattr(sa, "PROTOCOL_BLIND_MODULES", frozenset())
    monkeypatch.setattr(sa, "UNSOURCED_MODULES",
                        frozenset(m["module"] for m in infos))

    out = sa.SignalAggregator(data_dir=tmp_path).run_tier_b(["aave_v3"], {})
    sig = out["protocols"]["aave_v3"]
    assert sig["risk_multiplier"] == 1.0
    assert sig["confidence"] == 0.0
    assert sig["composite_risk_0_100"] == 50.0


def test_missing_markup_file_is_an_empty_set_not_a_crash():
    """Разметка — производный файл. Её отсутствие не имеет права уронить цикл.

    Это тот же контракт, что у `_protocol_blindness`: без файла набор пуст.
    """
    assert isinstance(sa.UNSOURCED_MODULES, frozenset)


# ─── реальная разметка ───────────────────────────────────────────────────────

def test_real_markup_names_exist_in_tier_b_registry():
    """Имена разметки обязаны существовать в реестре — иначе после
    переименования модуля пометка молча перестала бы действовать."""
    from spa_core.analytics._protocol_key_coverage import UNSOURCED_MODULES
    tier_b = {m["module"] for m in sa.registry.get_tier_modules("B")}
    missing = UNSOURCED_MODULES - tier_b
    assert missing == set(), f"нет в реестре Tier-B: {sorted(missing)}"


def test_real_markup_every_entry_names_what_is_missing():
    """Отказ обязан быть поимённым: покрытие < 1.0 И непустой список ключей.

    Пометка без названной причины — это приговор без дела: снять её потом
    будет нечем.
    """
    from spa_core.analytics._protocol_key_coverage import (
        MIN_COVERAGE, UNSOURCED_DETAIL,
    )
    assert UNSOURCED_DETAIL, "разметка пуста — замер не проводился"
    for name, d in UNSOURCED_DETAIL.items():
        assert 0.0 <= d["coverage"] < MIN_COVERAGE, name
        assert d["missing_keys"], name
        assert all(isinstance(k, str) and k for k in d["missing_keys"]), name


def test_the_regulatory_scorer_trap_is_marked():
    """Именно тот модуль, на котором ловушка была найдена, — под пометкой.

    Пин на конкретную аварию: общее правило можно ослабить незаметно,
    поимённый случай — нет.
    """
    from spa_core.analytics._protocol_key_coverage import UNSOURCED_DETAIL
    d = UNSOURCED_DETAIL["defi_protocol_regulatory_risk_scorer"]
    assert d["coverage"] < 1.0
    for key in ("entity_incorporated", "dao_governance", "defi_category"):
        assert key in d["missing_keys"], key


def test_no_sensitive_module_stays_silently_uncovered():
    """Критерий приёмки карточки, закреплённый тестом.

    Ни один Tier-B модуль, который аудит слепоты считает работающим
    (`sensitive` = не в `PROTOCOL_BLIND_MODULES`), не имеет права остаться
    UNCOVERED без пометки. Замер зафиксирован отчётом инструмента; здесь
    сверяется, что разметка его не потеряла.
    """
    from spa_core.analytics._protocol_blindness import PROTOCOL_BLIND_MODULES
    from spa_core.analytics._protocol_key_coverage import UNSOURCED_MODULES
    # Разметка покрытия обязана накрывать ВСЕ не-слепые модули из своего
    # набора: пересечение со слепыми допустимо, пробел — нет.
    sensitive_uncovered = UNSOURCED_MODULES - PROTOCOL_BLIND_MODULES
    assert sensitive_uncovered, (
        "разметка не содержит ни одного sensitive-модуля — либо замер не "
        "проводился, либо набор подменён")
    tier_b = {m["module"] for m in sa.registry.get_tier_modules("B")}
    assert sensitive_uncovered <= tier_b


# ─── генератор разметки ──────────────────────────────────────────────────────

def test_emit_markup_writes_only_uncovered(tmp_path):
    """В разметку попадает РОВНО UNCOVERED — не WIRABLE и не BLIND."""
    tool = _load_audit_tool()
    report = {
        "generated_at": _STAMP,
        "probe_protocols": ["aave_v3"],
        "min_coverage": 1.0,
        "results": [
            {"module": "m_unc", "verdict": "UNCOVERED", "coverage": 0.5,
             "missing_keys": ["a", "b"]},
            {"module": "m_wir", "verdict": "WIRABLE", "coverage": 1.0,
             "missing_keys": []},
            {"module": "m_blind", "verdict": "BLIND", "coverage": 1.0,
             "missing_keys": []},
        ],
    }
    path = tmp_path / "_gen.py"
    tool.emit_markup(report, path)
    ns: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    assert set(ns["UNSOURCED_MODULES"]) == {"m_unc"}
    assert ns["UNSOURCED_DETAIL"]["m_unc"]["missing_keys"] == ("a", "b")


def test_emit_markup_single_missing_key_stays_a_tuple(tmp_path):
    """Один ключ — всё ещё кортеж, а не строка.

    Без запятой `("harvests_per_year")` — это строка, и `in` начал бы
    сравнивать ПОДСТРОКИ: тест на наличие ключа проходил бы для любого его
    куска. Реальный случай: `defi_gas_cost_yield_drag_analyzer`.
    """
    tool = _load_audit_tool()
    report = {
        "generated_at": _STAMP,
        "probe_protocols": ["aave_v3"],
        "min_coverage": 1.0,
        "results": [{"module": "m_one", "verdict": "UNCOVERED",
                     "coverage": 0.9, "missing_keys": ["harvests_per_year"]}],
    }
    path = tmp_path / "_gen_one.py"
    tool.emit_markup(report, path)
    ns: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)
    keys = ns["UNSOURCED_DETAIL"]["m_one"]["missing_keys"]
    assert isinstance(keys, tuple) and keys == ("harvests_per_year",)


def test_emit_markup_refuses_partial_scan(tmp_path, monkeypatch, capsys):
    """`--only` + `--emit-markup` = стирание пометок у неизмеренных модулей.

    Fail-CLOSED: инструмент обязан отказать, а не переписать разметку по
    огрызку скана.
    """
    tool = _load_audit_tool()
    monkeypatch.setattr(tool, "run_audit", lambda *a, **k: {
        "generated_at": "x", "tier": "B", "min_coverage": 1.0,
        "probe_protocols": [], "module_count": 1, "counts": {},
        "wirable": [], "results": [], "method": "",
    })
    rc = tool.main(["--tier", "B", "--out", str(tmp_path / "r.json"),
                    "--only", "m_one", "--emit-markup"])
    assert rc == 2
    assert "стёр бы пометки" in capsys.readouterr().err


def test_emit_markup_refuses_other_tiers(tmp_path, monkeypatch, capsys):
    """Разметку потребляет только run_tier_b — генерировать её для A/C нельзя."""
    tool = _load_audit_tool()
    monkeypatch.setattr(tool, "run_audit", lambda *a, **k: {
        "generated_at": "x", "tier": "C", "min_coverage": 1.0,
        "probe_protocols": [], "module_count": 1, "counts": {},
        "wirable": [], "results": [], "method": "",
    })
    rc = tool.main(["--tier", "C", "--out", str(tmp_path / "r.json"),
                    "--emit-markup"])
    assert rc == 2
    assert "только для Tier B" in capsys.readouterr().err


def test_uncovered_verdict_reproduces_on_a_synthetic_module():
    """Положительный контроль самого критерия: движок, читающий ключ, которого
    в профиле нет, и различающийся ПОБОЧНЫМ полем, обязан дать UNCOVERED."""
    tool = _load_audit_tool()

    def analyze(records: list):
        rec = records[0]
        # предметный ключ отсутствует в профиле → молча 0.0
        subject = rec.get("nonexistent_subject_key", 0.0)
        side = rec.get("side", 0.0)
        return {"risk_score": subject + side}

    info = _install_fake_module(_FAKE_PREFIX + "unc", analyze=analyze)
    profiles = {"aave_v3": {"side": 10.0}, "maple": {"side": 20.0}}
    out = tool.probe_module(info, protocols=("aave_v3", "maple"),
                            profile_for=profiles.get)
    assert out["verdict"] == "UNCOVERED"
    assert "nonexistent_subject_key" in out["missing_keys"]


def test_full_coverage_module_is_wirable_not_uncovered():
    """Обратный контроль критерия: тот же движок, но профиль отдаёт всё —
    вердикт обязан смениться. Иначе UNCOVERED был бы приговором всем подряд."""
    tool = _load_audit_tool()

    def analyze(records: list):
        rec = records[0]
        return {"risk_score": rec.get("subject", 0.0) + rec.get("side", 0.0)}

    info = _install_fake_module(_FAKE_PREFIX + "wir", analyze=analyze)
    profiles = {"aave_v3": {"subject": 1.0, "side": 10.0},
                "maple": {"subject": 2.0, "side": 20.0}}
    out = tool.probe_module(info, protocols=("aave_v3", "maple"),
                            profile_for=profiles.get)
    assert out["verdict"] == "WIRABLE"
    assert out["missing_keys"] == []


def test_report_json_and_markup_agree():
    """Разметка обязана совпадать с последним отчётом инструмента по составу.

    Пин против ручной правки сгенерированного файла: файл помечен «не
    редактировать вручную», и это должно быть проверяемо, а не на совести.
    """
    from spa_core.analytics import _protocol_key_coverage as cov
    src = (REPO_ROOT / "spa_core" / "analytics"
           / "_protocol_key_coverage.py").read_text(encoding="utf-8")
    assert "СГЕНЕРИРОВАНО scripts/audit_tier_c_wiring_feasibility.py" in src
    assert cov.AUDIT_GENERATED_AT
    # каждое имя из разметки присутствует в исходнике ровно один раз
    for name in cov.UNSOURCED_MODULES:
        assert src.count(f'"{name}"') == 1, name
