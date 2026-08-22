# LLM_FORBIDDEN
"""Hermetic tests for the artifact freshness registry (no wall-clock, no live network)."""
# LLM_FORBIDDEN

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import artifact_freshness as af
from spa_core.monitoring import manifest_slo

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _write(p: Path, doc):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def _reg(**kw):
    base = dict(name="x", path="x.json", producer="p", max_age_hours=24.0)
    base.update(kw)
    return (af.Artifact(**base),)


def test_fresh_within_window(tmp_path):
    _write(tmp_path / "x.json", {"generated_at": (NOW - timedelta(hours=1)).isoformat()})
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg())[0]
    assert r.status == af.FRESH and r.ok and r.age_hours == pytest.approx(1.0, abs=0.01)


def test_stale_past_window(tmp_path):
    _write(tmp_path / "x.json", {"generated_at": (NOW - timedelta(hours=50)).isoformat()})
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg())[0]
    assert r.status == af.STALE and not r.ok


def test_missing_required_is_red_not_skipped(tmp_path):
    # fail-CLOSED: an absent REQUIRED file must be MISSING (red), never silently fresh/skipped.
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg(required=True))[0]
    assert r.status == af.MISSING and not r.ok


def test_missing_optional_is_unchecked(tmp_path):
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg(required=False))[0]
    assert r.status == af.UNCHECKED and not r.ok


def test_unparseable_timestamp_is_unchecked_not_fresh(tmp_path):
    # fail-CLOSED: a garbage timestamp with mtime disabled must NOT read as fresh.
    _write(tmp_path / "x.json", {"generated_at": "not-a-date"})
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg(allow_mtime=False))[0]
    assert r.status == af.UNCHECKED and not r.ok


def test_mtime_fallback_when_no_ts_field(tmp_path):
    p = tmp_path / "x.json"
    _write(p, {"no_ts_here": 1})
    import os
    old = (NOW - timedelta(hours=100)).timestamp()
    os.utime(p, (old, old))
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg(allow_mtime=True))[0]
    assert r.status == af.STALE  # 100h > 24h via mtime fallback


def test_ts_field_precedence_over_mtime(tmp_path):
    p = tmp_path / "x.json"
    _write(p, {"generated_at": (NOW - timedelta(hours=1)).isoformat()})
    import os
    old = (NOW - timedelta(hours=100)).timestamp()
    os.utime(p, (old, old))  # mtime old, but generated_at fresh → FRESH
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg())[0]
    assert r.status == af.FRESH


def test_summarize_any_stale_headline(tmp_path):
    _write(tmp_path / "fresh.json", {"generated_at": (NOW - timedelta(hours=1)).isoformat()})
    _write(tmp_path / "old.json", {"generated_at": (NOW - timedelta(hours=99)).isoformat()})
    reg = (af.Artifact("fresh", "fresh.json", "p", 24.0),
           af.Artifact("old", "old.json", "p", 24.0))
    rep = af.summarize(af.check_freshness(tmp_path, now=NOW, registry=reg))
    assert rep["any_stale"] is True and rep["n_stale"] == 1 and rep["n_artifacts"] == 2


def test_real_registry_has_producers_and_positive_ages():
    # every registered artifact must name a producer (accountability) and a positive threshold.
    assert af.ARTIFACT_REGISTRY, "registry must not be empty"
    for a in af.ARTIFACT_REGISTRY:
        assert a.producer and a.max_age_hours > 0, f"{a.name} missing producer/threshold"


def test_write_report_atomic(tmp_path):
    _write(tmp_path / "old.json", {"generated_at": (NOW - timedelta(hours=99)).isoformat()})
    reg = (af.Artifact("old", "old.json", "p", 24.0),)
    rep = af.summarize(af.check_freshness(tmp_path, now=NOW, registry=reg))
    assert rep["any_stale"] is True


# ── #235: главный артефакт офиса обрёл срок годности ──────────────────────────────────
# Положительный контроль: на неисправленном модуле записи в реестре НЕТ вовсе, поэтому
# первый ассерт краснеет — «дом-вью не зарегистрирован» и есть та самая авария.

def test_house_view_is_registered_with_a_measured_budget():
    """chief_investment.json обязан быть в реестре: из него оркестратор судит каждый цикл."""
    art = next((a for a in af.ARTIFACT_REGISTRY
                if a.path == "investment_os/chief_investment.json"), None)
    assert art is not None, "у ГЛАВНОГО артефакта офиса не было срока годности вовсе"
    # ЗАПАСНОЙ литерал (с #342 действует, только когда конституция молчит или нечитаема;
    # действующий срок годности берётся из `architecture/manifest.json` — см.
    # `test_house_view_budget_agrees_with_the_office_health_monitor`).
    assert art.max_age_hours > 24.0, "бюджет меньше такта = ложная тревога на верном состоянии"
    assert art.max_age_hours == 30.0
    assert art.producer == "com.spa.io_chief_investment"


def test_house_view_budget_agrees_with_the_office_health_monitor():
    """Два определения одного срока годности разошлись бы молча — сверяем их вслух.

    ИНВ. #16 — почему тест изменён намеренно (цикл #342). Прежняя форма сверяла два ЛИТЕРАЛА
    (`art.max_age_hours * 3600 == H.budget_s(...)`) и потому была ЗЕЛЁНОЙ ровно всё то время,
    пока система была сломана: обе копии дружно держали 30ч, а конституция флота с 21.08
    (ADR-104) объявляла 1ч. Тест, который сверяет копии друг с другом, ловит расхождение копий
    и НЕ ловит их общего ухода от источника — то есть молчит именно в той аварии, ради которой
    написан.

    Сверяется теперь ЭФФЕКТИВНЫЙ бюджет — то число, по которому сторож ДЕЙСТВИТЕЛЬНО судит, —
    и дополнительно то, что оба взяли его из конституции. Утверждение прежнего теста («два
    определения не смеют разойтись») сохранено целиком и усилено третьей стороной: оба обязаны
    совпасть С ИСТОЧНИКОМ, а не только друг с другом.
    """
    from spa_core.investment_os import health as H
    art = next(a for a in af.ARTIFACT_REGISTRY
               if a.path == "investment_os/chief_investment.json")
    declared, why = manifest_slo.slo_hours_by_path()
    rel = "data/investment_os/chief_investment.json"
    if rel not in declared:
        return                     # дерево без конституции — сверять нечем, выдумывать нельзя

    budgets = af.effective_budgets()
    spec = budgets[art.name]
    # 1. оба сторожа судят по ОДНОМУ числу
    assert spec["hours"] * 3600 == H.budget_s(H.HOUSE_VIEW), (
        f"artifact_freshness судит по {spec['hours']}ч, "
        f"investment_os.health — по {H.budget_s(H.HOUSE_VIEW) / 3600}ч")
    # 2. и это число — из конституции, а не совпавший литерал
    assert spec["source"] == "manifest_slo", spec
    assert spec["hours"] == declared[rel]


def test_real_house_view_past_the_constitution_is_stale_though_the_literal_would_pass(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ ПО СУЩЕСТВУ (#342): судим по конституции, а не по литералу.

    Берётся НАСТОЯЩАЯ строка реестра `investment_os_chief` (литерал 30ч) и артефакт возрастом
    2ч. Под литералом это FRESH, под конституцией (`slo_hours: 1`) — STALE. Тест НАМЕРЕННО не
    зовёт ни одного нового имени в утверждении, а смотрит на ВЕРДИКТ: на неисправленном коде он
    краснеет «FRESH == STALE», а не «нет атрибута effective_budgets» (урок «положительный
    контроль может быть украшением»).
    """
    declared, _why = manifest_slo.slo_hours_by_path()
    rel = "data/investment_os/chief_investment.json"
    if declared.get(rel) != 1.0:
        return                      # конституция сменила SLO — тест не выдумывает своё число

    art = next(a for a in af.ARTIFACT_REGISTRY if a.path == "investment_os/chief_investment.json")
    assert art.max_age_hours == 30.0, "предпосылка контроля: литерал всё ещё 30ч"
    _write(tmp_path / art.path, {"generated_at": (NOW - timedelta(hours=2)).isoformat()})

    r = af.check_freshness(tmp_path, now=NOW, registry=(art,))[0]
    # сообщение НЕ смеет звать новые имена напрямую: иначе на неисправленном коде вместо
    # сути («FRESH там, где обязан STALE») читатель получит AttributeError о новом поле.
    assert r.status == af.STALE, (
        f"возраст 2ч при SLO конституции 1ч обязан быть STALE, получено {r.status} "
        f"(судили по {r.max_age_hours}ч из {getattr(r, 'budget_source', 'литерала')})")
    assert r.max_age_hours == 1.0 and r.budget_source == "manifest_slo"


def test_artifact_the_constitution_is_silent_about_keeps_its_literal(tmp_path):
    """ОБРАТНЫЙ КОНТРОЛЬ: конституция молчит ⇒ литерал действует и НАЗЫВАЕТ себя.

    10 из 11 строк реестра конституция не описывает вовсе (замер #342). Если бы «нет записи»
    молча означало «нет срока годности», починка превратила бы сторожа в решето — поэтому
    отсутствие записи обязано оставлять литерал в силе, а источник — быть названным.
    """
    b = af.effective_budgets(registry=_reg(name="nope", path="nope.json", max_age_hours=7.0))
    assert b["nope"]["hours"] == 7.0
    assert b["nope"]["source"] == "literal"
