"""Разметка Tier-C: правило построения, численная инертность, ярлык.

Положительный контроль (правило `.claude/rules/deployment.md` — «у каждой новой
проверки обязан быть тест, воспроизводящий реальную аварию»): аварией здесь
является цикл #136, когда первая версия разделения модулей ПОГАСИЛА рабочий
модуль Tier-A. Поэтому главный тест файла — не «пометка применилась», а
«пометка НЕ применяется к модулю, который сегодня даёт число», и «применённая
пометка не сдвинула ни modules_ok, ни avg_score».

Никаких литеральных дат: время здесь не предмет, отметки замеров — данные.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from spa_core.analytics import _module_registry as registry
from spa_core.analytics import _tier_c_key_coverage as markup
from spa_core.analytics import signal_aggregator as sa

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load("_test_tier_c_markup_tool",
              "scripts/audit_tier_c_wiring_feasibility.py")


# ── 1. Правило построения разметки держится на закоммиченном файле ──────────

def test_every_unsourced_module_is_failed_today_and_names_what_is_missing():
    """Оба условия правила, поимённо, на живой разметке.

    Условие «blindness == failed» — это и есть доказательство инертности:
    агрегатор зовёт модуль и не получает числа. Условие «названо, чего не
    хватает» — fail-CLOSED: не смогли назвать ⇒ модуль остаётся громким
    `failed`, а не получает успокаивающий ярлык.
    """
    assert markup.UNSOURCED_MODULES, "разметка пуста — измерять нечего"
    for name in sorted(markup.UNSOURCED_MODULES):
        row = markup.TIER_C_DISPOSITION[name]
        assert row["blindness"] == "failed", (
            f"{name}: помечен, но сегодня его классификация {row['blindness']!r} "
            "— пометка перестала быть численно инертной")
        keys = markup.UNSOURCED_DETAIL[name]["missing_keys"]
        assert keys, f"{name}: помечен, но не названо, чего не хватает"
        assert all(isinstance(k, str) and k for k in keys)


def test_no_module_that_yields_a_number_today_is_marked():
    """Обратная сторона: девять константных модулей дают публикуемый
    `avg_score` — пометить их значило бы молча изменить опубликованное число
    под видом починки ярлыка. Это решение владельца, а не генератора."""
    scoring = {n for n, row in markup.TIER_C_DISPOSITION.items()
               if row["blindness"] == "blind_constant"}
    assert scoring, "в диспозиции нет ни одного отвечающего модуля — замер сломан"
    assert not (scoring & markup.UNSOURCED_MODULES)


def test_disposition_covers_the_whole_live_tier_c_registry():
    """Списание — записью, а не удалением (пункт 4 родительской карточки):
    реестр обязан продолжать знать про КАЖДЫЙ модуль тира."""
    live = {m["module"] for m in registry.get_tier_modules("C")}
    recorded = set(markup.TIER_C_DISPOSITION)
    assert not live - recorded, (
        "в реестре есть модули, которых нет в диспозиции: %s"
        % sorted(live - recorded)[:5])
    assert not recorded - live, (
        "в диспозиции есть модули, которых нет в реестре: %s"
        % sorted(recorded - live)[:5])
    assert markup.MODULE_COUNT == len(recorded)


def test_unchecked_row_means_we_do_not_know_not_a_measured_zero():
    """`unchecked` — это «не измерено», и оно обязано отличаться от нуля:
    у такой строки не может быть выдуманного покрытия 0.0 при пустом списке
    недостающего (это выглядело бы как «измерили и там ничего не нужно»)."""
    for name, row in markup.TIER_C_DISPOSITION.items():
        if row["coverage"] is None:
            continue
        assert isinstance(row["coverage"], float)
        if row["coverage"] < 1.0:
            # покрытие измерено и неполно ⇒ недостающее обязано быть названо
            assert row["missing_keys"], (
                f"{name}: покрытие {row['coverage']} < 1.0, но не названо ни "
                "одного недостающего ключа — вердикт и улика разошлись")


# ── 2. Численная инертность пометки (синтетические модули) ──────────────────

def _install_fake_module(name: str, fn) -> None:
    mod = types.ModuleType("spa_core.analytics." + name)
    mod.analyze = fn
    sys.modules["spa_core.analytics." + name] = mod


@pytest.fixture()
def fake_tier_c(monkeypatch):
    """Два синтетических модуля: один падает, второй считает."""
    def raiser(ctx):
        raise ValueError("Missing required fields: ['audit_count', 'chain_count']")

    def scorer(ctx):
        return {"risk_score": 70.0}

    _install_fake_module("zz_fake_raiser", raiser)
    _install_fake_module("zz_fake_scorer", scorer)
    yield [
        {"module": "zz_fake_raiser", "weight": 0.1, "category": "background"},
        {"module": "zz_fake_scorer", "weight": 0.1, "category": "background"},
    ]
    for n in ("zz_fake_raiser", "zz_fake_scorer"):
        sys.modules.pop("spa_core.analytics." + n, None)


def _pass(monkeypatch, modules, marked, detail, tmp_path, silent=False):
    monkeypatch.setattr(sa, "TIER_C_UNSOURCED_MODULES", frozenset(marked))
    monkeypatch.setattr(sa, "TIER_C_UNSOURCED_DETAIL", detail)
    agg = sa.SignalAggregator(data_dir=str(tmp_path))
    out = agg._tier_c_pass(modules, "aave_v3", {"protocol": "aave_v3"},
                           silent=silent)
    return out, agg


def test_marking_a_scoreless_module_changes_nothing_numerically(
        monkeypatch, fake_tier_c, tmp_path):
    """Главная проверка: с пометкой и без неё — байт-в-байт одно и то же."""
    before, _ = _pass(monkeypatch, fake_tier_c, set(), {}, tmp_path)
    after, _ = _pass(
        monkeypatch, fake_tier_c, {"zz_fake_raiser"},
        {"zz_fake_raiser": {"coverage": 0.5,
                            "missing_keys": ("audit_count", "chain_count")}},
        tmp_path)
    assert before == after
    assert before["modules_ok"] == 1
    assert before["avg_score"] == 70.0


def test_label_changes_from_failed_to_unsourced_and_names_the_missing_facts(
        monkeypatch, fake_tier_c, tmp_path):
    """Ради чего всё: ярлык перестаёт отправлять чинить код, в котором нечего."""
    _, agg_before = _pass(monkeypatch, fake_tier_c, set(), {}, tmp_path)
    assert agg_before._module_status["zz_fake_raiser"] == "failed"

    _, agg_after = _pass(
        monkeypatch, fake_tier_c, {"zz_fake_raiser"},
        {"zz_fake_raiser": {"coverage": 0.5,
                            "missing_keys": ("audit_count", "chain_count")}},
        tmp_path)
    assert agg_after._module_status["zz_fake_raiser"] == "unsourced"
    entry = [e for e in agg_after._log if e["module"] == "zz_fake_raiser"][-1]
    assert "audit_count" in entry["detail"]
    assert "chain_count" in entry["detail"]


def test_marking_a_scoring_module_WOULD_change_the_number(
        monkeypatch, fake_tier_c, tmp_path):
    """Отрицательный контроль — авария, которую правило запрещает.

    Пометь модуль, который СЕГОДНЯ даёт число, — и опубликованный avg_score
    поедет. Тест фиксирует цену ошибки; правило построения разметки
    (`blindness == failed`) ровно её и предотвращает."""
    before, _ = _pass(monkeypatch, fake_tier_c, set(), {}, tmp_path)
    after, _ = _pass(
        monkeypatch, fake_tier_c, {"zz_fake_scorer"},
        {"zz_fake_scorer": {"coverage": 0.5, "missing_keys": ("x",)}},
        tmp_path)
    assert before != after
    assert after["modules_ok"] == 0 and after["avg_score"] is None


def test_control_pass_does_not_record_status(monkeypatch, fake_tier_c, tmp_path):
    """Контрольный прогон описывает несуществующий протокол — в module_status
    он попадать не вправе (иначе счётчик пригодности лжёт в другую сторону)."""
    _, agg = _pass(
        monkeypatch, fake_tier_c, {"zz_fake_raiser"},
        {"zz_fake_raiser": {"coverage": 0.5, "missing_keys": ("audit_count",)}},
        tmp_path, silent=True)
    assert "zz_fake_raiser" not in agg._module_status


# ── 3. Генератор: правило, fail-CLOSED, отказы CLI ─────────────────────────

def _reports(blind_class, feas_extra=None, detail=None):
    feas = {"module": "m1", "verdict": "RAISES", "coverage": 0.5,
            "missing_keys": ["a", "b"], "detail": detail or ""}
    feas.update(feas_extra or {})
    return (
        {"tier": "C", "generated_at": "G-FEAS", "min_coverage": 1.0,
         "module_count": 1, "counts": {"RAISES": 1}, "results": [feas]},
        {"tier": "C", "generated_at": "G-BLIND", "counts": {blind_class: 1},
         "results": [{"module": "m1", "classification": blind_class}]},
    )


def test_generator_marks_only_failed_with_named_keys(tmp_path):
    feas, blind = _reports("failed")
    out = tmp_path / "gen.py"
    audit.emit_tier_c_markup(feas, blind, out)
    text = out.read_text(encoding="utf-8")
    assert "UNSOURCED_DETAIL" in text
    ns = {}
    exec(compile(text, str(out), "exec"), ns)
    assert ns["UNSOURCED_MODULES"] == frozenset({"m1"})
    assert set(ns["TIER_C_DISPOSITION"]) == {"m1"}


@pytest.mark.parametrize("blind_class", ["unchecked", "dormant", "blind_constant"])
def test_generator_refuses_to_mark_a_module_that_is_not_failing_today(
        blind_class, tmp_path):
    feas, blind = _reports(blind_class)
    out = tmp_path / "gen.py"
    audit.emit_tier_c_markup(feas, blind, out)
    ns = {}
    exec(compile(out.read_text(encoding="utf-8"), str(out), "exec"), ns)
    assert ns["UNSOURCED_MODULES"] == frozenset()
    # но ЗАПИСЬ остаётся — списание записью, а не удалением
    assert ns["TIER_C_DISPOSITION"]["m1"]["blindness"] == blind_class


def test_generator_fails_closed_when_nothing_can_be_named(tmp_path):
    feas, blind = _reports(
        "failed", feas_extra={"missing_keys": [], "coverage": None})
    out = tmp_path / "gen.py"
    audit.emit_tier_c_markup(feas, blind, out)
    ns = {}
    exec(compile(out.read_text(encoding="utf-8"), str(out), "exec"), ns)
    assert ns["UNSOURCED_MODULES"] == frozenset(), (
        "нечего назвать ⇒ модуль обязан остаться громким failed")


def test_generator_refuses_to_stitch_reports_from_different_trees(tmp_path):
    feas, blind = _reports("failed")
    blind["results"] = []
    with pytest.raises(AssertionError, match="аудит слепоты не знает"):
        audit.emit_tier_c_markup(feas, blind, tmp_path / "gen.py")


def test_generator_refuses_to_stitch_reports_of_different_tiers(tmp_path):
    feas, blind = _reports("failed")
    blind["tier"] = "B"
    with pytest.raises(AssertionError, match="тиры отчётов не совпадают"):
        audit.emit_tier_c_markup(feas, blind, tmp_path / "gen.py")


# ── 4. named_missing_keys: назвать «и ещё что-то» — это не назвать ──────────

def test_named_missing_keys_prefers_measured_over_exception_text():
    r = {"effective_missing_keys": ["b", "a"], "missing_keys": ["z"],
         "detail": "ValueError: Missing required fields: ['q']"}
    assert audit.named_missing_keys(r) == ("a", "b")


def test_named_missing_keys_reads_the_exception_when_nothing_was_measured():
    r = {"missing_keys": [], "detail":
         "ValueError: Missing required fields: ['audit_count', 'chain_count']"}
    assert audit.named_missing_keys(r) == ("audit_count", "chain_count")


@pytest.mark.parametrize("detail", [
    "ValueError: Missing required fields: ['audit_count', …]",
    "ValueError: Missing required fields: ['audit_count', ...]",
    "ValueError: Missing required fields: []",
    "TypeError: analyze() got an unexpected keyword argument 'context'",
])
def test_named_missing_keys_refuses_a_truncated_or_absent_list(detail):
    assert audit.named_missing_keys({"missing_keys": [], "detail": detail}) == ()


def test_cli_refuses_tier_c_markup_without_the_blindness_report(
        monkeypatch, tmp_path):
    """fail-CLOSED в CLI: без ответа «даёт ли модуль число сегодня» разметку
    строить нечем, а построить её на одном покрытии — погасить работающее."""
    feas, _blind = _reports("failed")
    monkeypatch.setattr(audit, "run_audit", lambda *a, **k: feas)
    rc = audit.main(["--tier", "C", "--out", str(tmp_path / "r.json"),
                     "--emit-markup"])
    assert rc == 2


def test_cli_refuses_blindness_report_for_tier_b(monkeypatch, tmp_path):
    feas, _blind = _reports("failed")
    feas["tier"] = "B"
    monkeypatch.setattr(audit, "run_audit", lambda *a, **k: feas)
    rc = audit.main(["--tier", "B", "--out", str(tmp_path / "r.json"),
                     "--emit-markup", "--blindness", str(tmp_path / "b.json")])
    assert rc == 2
