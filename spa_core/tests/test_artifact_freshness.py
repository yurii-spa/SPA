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


# ── 2026-08-16: три fail-OPEN в модуле, который объявлял себя fail-CLOSED ──────────────
# Замер на неисправленном коде (все три возвращали FRESH):
#   • обрезанный JSON + свежий mtime           → FRESH
#   • generated_at на 400 дней в БУДУЩЕЕ       → FRESH (age = -9600h)
#   • paper_evidence.json                      → FRESH, age 1.27h, при том что
#     последний день трека внутри файла — 2026-08-02, то есть 14 суток назад.
# Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на коде до правки он краснеет.


def test_corrupt_json_is_never_rescued_by_mtime(tmp_path):
    """Обрезанный JSON — форма, которую оставляет умерший на записи производитель.

    Модуль обещал в докстроке «a read error is NEVER fresh», а код падал в mtime —
    и mtime свежий ровно потому, что его обновила та самая оборвавшаяся запись.
    """
    p = tmp_path / "x.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"generated_at": "2026-06-01T00:00:00+00:0', encoding="utf-8")
    import os
    os.utime(p, (NOW.timestamp(), NOW.timestamp()))  # свежий mtime — соблазн соврать
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg(allow_mtime=True))[0]
    assert r.status == af.UNCHECKED and not r.ok


def test_future_timestamp_is_unchecked_not_fresh(tmp_path):
    """Отметка в будущем даёт отрицательный возраст — он НИКОГДА не превысит порог.

    Сбитые часы или выдуманная запись маскировали бы протухание вечно.
    """
    _write(tmp_path / "x.json", {"generated_at": (NOW + timedelta(days=400)).isoformat()})
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg())[0]
    assert r.status == af.UNCHECKED and not r.ok


def test_small_clock_skew_is_still_fresh(tmp_path):
    """Контроль в обратную сторону: секунды рассинхронизации часов — не авария."""
    _write(tmp_path / "x.json", {"generated_at": (NOW + timedelta(minutes=5)).isoformat()})
    r = af.check_freshness(tmp_path, now=NOW, registry=_reg())[0]
    assert r.status == af.FRESH


def test_frozen_series_is_stale_despite_a_fresh_writer_stamp(tmp_path):
    """Сердце правки: производитель ЖИВ, а вывод ЗАМЁРЗ.

    Писатель штампует `generated_at` каждый прогон, но серия не двигается. Судить
    по штампу писателя (или по mtime) — значит вечно рапортовать FRESH о мёртвом
    треке. Маркер серии обязан перебивать оба.
    """
    p = tmp_path / "x.json"
    _write(p, {"generated_at": NOW.isoformat(),                      # писатель свеж
               "days": [{"date": (NOW - timedelta(days=14)).date().isoformat()}]})
    import os
    os.utime(p, (NOW.timestamp(), NOW.timestamp()))                  # и mtime свеж
    r = af.check_freshness(tmp_path, now=NOW,
                           registry=_reg(series_field="days"))[0]
    assert r.status == af.STALE and not r.ok
    # Маркер — ДАТА, то есть полночь: 14 суток назад от 12:00 даёт 348ч, а не 336ч.
    # Этот сдвиг внутри суток — ровно то, ради чего бюджет 36ч, а не 24ч.
    assert r.age_hours == pytest.approx(14 * 24 + NOW.hour, abs=0.01)


def test_configured_series_that_cannot_be_read_is_unchecked_not_mtime(tmp_path):
    """Настроенный маркер, которого нет, — отказ судить, а не откат к mtime."""
    p = tmp_path / "x.json"
    _write(p, {"days": []})
    import os
    os.utime(p, (NOW.timestamp(), NOW.timestamp()))
    r = af.check_freshness(tmp_path, now=NOW,
                           registry=_reg(series_field="days", allow_mtime=True))[0]
    assert r.status == af.UNCHECKED and not r.ok


def test_paper_evidence_is_judged_by_its_track_not_by_the_file(tmp_path):
    """Публичный артефакт трека обязан судиться по последнему дню трека."""
    art = next(a for a in af.ARTIFACT_REGISTRY if a.name == "paper_evidence")
    assert art.series_field == "days", "иначе свежесть меряется прикосновением к файлу"
    assert art.committed is True, "трек аудируется ИЗ репозитория — git-копию тоже судим"
    # бюджет обязан вмещать здоровый трек (маркер — дата, отсюда ~30ч на такте 24ч)
    assert art.max_age_hours >= 30.0
    # ...и обязан краснеть на ОДИН пропущенный цикл, а не молчать до второго
    assert art.max_age_hours < 48.0


def test_required_unchecked_reaches_the_headline(tmp_path):
    """«Не смогли проверить» и «всё хорошо» не имеют права выглядеть одинаково."""
    _write(tmp_path / "x.json", {"generated_at": "not-a-date"})
    rep = af.summarize(af.check_freshness(tmp_path, now=NOW,
                                          registry=_reg(required=True, allow_mtime=False)))
    assert rep["any_stale"] is True and rep["n_stale"] == 1


def test_optional_absent_stays_out_of_the_headline(tmp_path):
    """Обратный контроль: сторож, который НИКОГДА не бывает зелёным, не читается.

    Опциональный артефакт, которого просто нет, — верное состояние; он обязан
    остаться в `n_unchecked`, но не поднимать заголовок.
    """
    rep = af.summarize(af.check_freshness(tmp_path, now=NOW, registry=_reg(required=False)))
    assert rep["any_stale"] is False and rep["n_unchecked"] == 1


# ── git-копия трека (авария 2026-06-21) ───────────────────────────────────────────────

def _committed(payload, ok=True):
    """Подставной `git show`: описываем состояние репозитория, а не строим его."""
    return lambda rel: (ok, payload)


def _ev(**kw):
    base = dict(name="paper_evidence", path="paper_evidence.json", producer="daily_cycle",
                max_age_hours=36.0, series_field="days", committed=True)
    base.update(kw)
    return (af.Artifact(**base),)


def test_committed_copy_frozen_while_working_copy_is_fresh(tmp_path):
    """ТА САМАЯ авария: локально 44 дня, в git — 12, и все сторожа смотрели на диск.

    Проверяемость трека из репозитория (единственный источник правды по CLAUDE.md)
    ломалась молча. Проверка рабочей копии на этот вопрос не отвечает вовсе.
    """
    fresh_local = json.dumps({"days": [{"date": NOW.date().isoformat()}]})
    _write(tmp_path / "paper_evidence.json", json.loads(fresh_local))
    working = af.check_freshness(tmp_path, now=NOW, registry=_ev())[0]
    assert working.status == af.FRESH, "рабочая копия честно свежая — и это её вводит в заблуждение"

    stale_in_git = json.dumps({"days": [{"date": (NOW - timedelta(days=32)).date().isoformat()}]})
    committed = af.check_committed_freshness(tmp_path, now=NOW, registry=_ev(),
                                             git_show=_committed(stale_in_git))[0]
    assert committed.status == af.STALE and committed.scope == "committed"

    # и главное — обе области попадают в ОДИН заголовок, иначе замечать некому
    rep = af.summarize([working, committed])
    assert rep["any_stale"] is True
    assert [s["scope"] for s in rep["stale"]] == ["committed"]


def test_committed_copy_absent_from_git_is_missing_not_skipped(tmp_path):
    """fail-CLOSED: файла нет в git ⇒ КРАСНЫЙ, а не «проверять нечего»."""
    r = af.check_committed_freshness(tmp_path, now=NOW, registry=_ev(),
                                     git_show=lambda rel: (False, "path does not exist"))[0]
    assert r.status == af.MISSING and not r.ok


def test_committed_copy_corrupt_blob_is_unchecked(tmp_path):
    r = af.check_committed_freshness(tmp_path, now=NOW, registry=_ev(),
                                     git_show=_committed('{"days": [tru'))[0]
    assert r.status == af.UNCHECKED and not r.ok


def test_committed_scope_only_visits_committed_artifacts(tmp_path):
    """Не-committed артефакты не имеют git-копии — их нельзя судить по ней."""
    assert af.check_committed_freshness(tmp_path, now=NOW, registry=_reg(),
                                        git_show=_committed("{}")) == []
