"""spa_core/tests/test_investment_os_health.py — product-layer health monitor (AAA Phase 2).

Proves the meta-monitor classifies each analyst artifact (present/fresh/status) and rolls up to
HEALTHY / STALE / DEGRADED honestly. PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from spa_core.investment_os import health as H


def _dt(day=17):
    return datetime(2026, 7, day, 12, 0, tzinfo=timezone.utc)


def _write(d, agent, status="ok", *, age_days=0.0):
    p = d / f"{agent}.json"
    p.write_text(json.dumps({"agent": agent, "status": status}))
    if age_days:
        t = _dt().timestamp() - age_days * 86400
        os.utime(p, (t, t))


def test_all_fresh_ok_is_healthy(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "HEALTHY"
    assert s["counts"]["healthy"] == len(H.ANALYSTS)


def test_missing_artifact_is_degraded(tmp_path):
    for a in H.ANALYSTS[1:]:
        _write(tmp_path, a, "ok")   # first analyst missing
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "DEGRADED"
    assert s["counts"]["missing"] == 1


def test_unknown_status_is_degraded(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, H.ANALYSTS[0], "UNKNOWN")
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "DEGRADED"
    assert s["counts"]["unknown_or_corrupt"] == 1


def test_stale_artifact_is_stale(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, H.ANALYSTS[0], "ok", age_days=5)   # older than the 2-day budget
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "STALE"
    assert s["counts"]["stale"] == 1


def test_corrupt_artifact_flagged(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    (tmp_path / f"{H.ANALYSTS[0]}.json").write_text("{ not json")
    s = H.scan(tmp_path, now=_dt())
    assert s["counts"]["unknown_or_corrupt"] == 1


def test_run_writes_health_artifact(tmp_path):
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    H.run(now=_dt(), data_dir=tmp_path)
    doc = json.loads((tmp_path / "_health.json").read_text())
    assert doc["overall"] == "HEALTHY" and doc["is_advisory"] is True
    assert (tmp_path / "_health_proof.jsonl").exists()


# ─────────────────────────────────────────────────────────────────────────────────────
# #235 — «у ГЛАВНОГО артефакта офиса нет срока годности»
#
# Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: он краснеет на неисправленном модуле,
# где бюджет был ОДИН на всех (48 ч) и дом-вью не имел отдельного вердикта.
#
# ОТКЛОНЕНИЕ ОТ ПРИЁМКИ КАРТОЧКИ — намеренное, с обоснованием (инв. #16).
# Карточка требовала: «тест на снимке 13.08 (17.0 ч) КРАСНЕЕТ». Такт производителя
# ИЗМЕРЕН (шаг 1 самой карточки: «срок годности назначать по факту, а не на глаз»):
# launchd/com.spa.io_chief_investment.plist StartInterval=86400 — раз в СУТКИ.
# Значит 17 ч для дневного агента — ШТАТНОЕ состояние, и сторож, краснеющий на нём,
# был бы ложной тревогой на верном состоянии (класс #183: ложный отказ опаснее
# пропуска). Поэтому проверяется настоящая авария — дом-вью ПРОПУСТИЛ свой суточный
# такт, — и контроль ставится в ОБЕ стороны: 17 ч обязаны остаться свежими.
# ─────────────────────────────────────────────────────────────────────────────────────

#: Имя дом-вью в СЕТАПЕ — литерал, не `H.HOUSE_VIEW` (урок #234): иначе на неисправленном
#: origin контроль падал бы на ОТСУТСТВИИ ИМЕНИ ещё до того, как дойдёт до сути.
#: Что имя модуля совпадает с этим литералом — отдельный ассерт ниже.
_HV = "chief_investment"


def test_house_view_budget_comes_from_measured_daily_cadence():
    """Бюджет дом-вью — из такта агента (86400 с + запас), а не общий 48-часовой."""
    assert H.HOUSE_VIEW == _HV
    assert H.budget_s(H.HOUSE_VIEW) == 30 * 3600
    assert H.budget_s(H.HOUSE_VIEW) > 86400, "суточный такт обязан помещаться в бюджет"
    assert H.budget_s("market_regime") == H.FRESH_AGE_S, "остальные — общий потолок"


def test_shared_office_ceiling_is_not_tightened():
    """Потолок офиса НЕ трогаем: на нём висит отказ house_view_gap судить (#212/#222).

    Ужать его ради одного производителя = сверка замолкает РАНЬШЕ, находки исчезают,
    мост закрывает их карточки как решённые (fail-OPEN #29) — прямой запрет карточки.
    """
    assert H.FRESH_AGE_S == 2 * 86400
    from spa_core.monitoring import house_view_gap as HVG
    assert HVG.MAX_INPUT_AGE_S == H.FRESH_AGE_S


def test_house_view_that_missed_its_daily_beat_goes_stale(tmp_path):
    """НАСТОЯЩАЯ авария: офис замолчал на сутки с лишним — 11/11 больше не 'здоровы'."""
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, _HV, "ok", age_days=1.5)   # 36 ч > 30 ч бюджета
    s = H.scan(tmp_path, now=_dt())
    # ПОВЕДЕНЧЕСКИЙ ассерт идёт ПЕРВЫМ намеренно (урок #234): на неисправленном модуле
    # 36 ч < 48 ч ⇒ 'HEALTHY' и 'протухли 0' — контроль обязан краснеть на СУТИ
    # («сутки офисного молчания считались здоровьем»), а не на отсутствии нового поля.
    assert s["overall"] == "STALE"
    assert s["counts"]["stale"] == 1
    assert s["house_view"]["status"] == "STALE"
    assert s["house_view_fresh"] is False


def test_normal_daily_age_stays_fresh_both_directions(tmp_path):
    """Обратный контроль: 17 ч у СУТОЧНОГО производителя — норма, а не находка."""
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, _HV, "ok", age_days=17.0 / 24.0)
    s = H.scan(tmp_path, now=_dt())
    assert s["house_view"]["status"] == "FRESH"
    assert s["house_view_fresh"] is True
    assert s["overall"] == "HEALTHY"


def test_house_view_is_answerable_separately_from_the_fleet(tmp_path):
    """Дом-вью свеж, а сосед протух: два вопроса перестали быть одним ответом."""
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    stale_neighbour = next(a for a in H.ANALYSTS if a != _HV)
    _write(tmp_path, stale_neighbour, "ok", age_days=5)
    s = H.scan(tmp_path, now=_dt())
    assert s["overall"] == "STALE"              # флот нездоров
    assert s["house_view"]["status"] == "FRESH"  # ...а дом-вью жив, и это ВИДНО
    assert s["house_view_fresh"] is True


def test_missing_house_view_is_never_fresh(tmp_path):
    """fail-CLOSED: файла дом-вью нет ⇒ MISSING, а не тихий пропуск."""
    for a in H.ANALYSTS:
        if a != _HV:
            _write(tmp_path, a, "ok")
    s = H.scan(tmp_path, now=_dt())
    assert s["house_view"]["status"] == "MISSING"
    assert s["house_view_fresh"] is False


def test_every_row_names_the_ceiling_it_was_judged_against(tmp_path):
    """Вердикт без названного бюджета нечитаем: max_age_s обязан лежать в каждой строке."""
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    s = H.scan(tmp_path, now=_dt())
    for r in s["analysts"]:
        assert r["max_age_s"] == H.budget_s(r["agent"])
