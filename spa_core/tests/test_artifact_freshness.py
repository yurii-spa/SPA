# LLM_FORBIDDEN
"""Hermetic tests for the artifact freshness registry (no wall-clock, no live network)."""
# LLM_FORBIDDEN

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import artifact_freshness as af

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
    # такт ИЗМЕРЕН по launchd: StartInterval=86400 ⇒ бюджет обязан вмещать сутки + запас
    assert art.max_age_hours > 24.0, "бюджет меньше такта = ложная тревога на верном состоянии"
    assert art.max_age_hours == 30.0
    assert art.producer == "com.spa.io_chief_investment"


def test_house_view_budget_agrees_with_the_office_health_monitor():
    """Два определения одного срока годности разошлись бы молча — сверяем их вслух."""
    from spa_core.investment_os import health as H
    art = next(a for a in af.ARTIFACT_REGISTRY
               if a.path == "investment_os/chief_investment.json")
    assert art.max_age_hours * 3600 == H.budget_s(H.HOUSE_VIEW)
