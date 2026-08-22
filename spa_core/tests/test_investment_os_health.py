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


def _manifest(tmp_path, slo_hours: dict, *, name="manifest.json"):
    """Синтетическая конституция флота: только то, что читает `cadence_budgets`."""
    p = tmp_path / name
    p.write_text(json.dumps({"artifacts": [
        {"path": f"data/investment_os/{a}.json", "producer": f"com.spa.io_{a}",
         "slo_hours": h, "status": "active"}
        for a, h in slo_hours.items()]}))
    return p


def _daily_budgets(tmp_path):
    """Такт дом-вью ДО решения ADR-104 — суточный (`slo_hours: 26`), остальные по потолку.

    Такты #235 (`_HV` пишет раз в сутки) стали ВХОДОМ, а не окружением: до цикла #340 эти
    тесты читали живую `architecture/manifest.json`, поэтому решение владельца о такте
    красило их — по причине, к проверяемому поведению отношения не имеющей. Тот же приём и
    та же причина, что у `now=` (правило `.claude/rules/deployment.md`). Ни один ассерт
    ниже не ослаблен: они по-прежнему судят про СУТОЧНОГО производителя, просто суточность
    теперь написана в фикстуре, а не подразумевается.
    """
    return H.cadence_budgets(_manifest(tmp_path, {_HV: 30}))


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


def test_house_view_budget_is_the_agents_own_cadence_not_the_shared_ceiling(tmp_path):
    """Бюджет дом-вью — его СОБСТВЕННЫЙ такт, а не общий 48-часовой потолок (#235).

    ИНВ. #16 — почему тест изменён намеренно (цикл #340). Прежнее имя обещало
    `..._comes_from_measured_daily_cadence`, а ассерт был `== 30 * 3600`, то есть пиньковал
    ЛИТЕРАЛ, списанный рукой с такта 16.08. Такой тест — не свидетель, а сообщник: он
    краснел бы ровно тогда, когда литерал ПОЧИНИЛИ, и молчал, когда конституция ушла из-под
    него (ADR-104, 21.08: `86400s → 300s`, `slo_hours 26 → 1`) — что и произошло.
    Ни одно утверждение #235 не снято: бюджет дом-вью по-прежнему обязан отличаться от
    общего потолка и вмещать такт своего производителя. Проверяется теперь ПРОИСХОЖДЕНИЕ
    числа, а не само число.
    """
    assert H.HOUSE_VIEW == _HV
    b = _daily_budgets(tmp_path)
    assert H.budget_s(H.HOUSE_VIEW, b) == 30 * 3600      # то же число, что у #235...
    assert b[H.HOUSE_VIEW]["source"] == "manifest_slo"    # ...но ПРОЧИТАННОЕ, не списанное
    assert H.budget_s(H.HOUSE_VIEW, b) > 86400, "суточный такт обязан помещаться в бюджет"
    assert H.budget_s("market_regime", b) == H.FRESH_AGE_S, "остальные — общий потолок"


def test_budget_follows_the_constitution_when_the_owner_changes_a_cadence(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ ADR-104: решение владельца меняет бюджет БЕЗ правки кода.

    Живой замер 22.08, из-за которого это появилось: конституция объявляла дом-вью
    `slo_hours: 1`, а health судил по литералу 30ч и печатал «FRESH, 12.4ч при сроке 30ч»
    про артефакт, который по действующему решению протух 11 часов назад.
    На неисправленном модуле обе ветки дают 108000 — ручка не подключена вовсе.
    """
    daily = H.cadence_budgets(_manifest(tmp_path, {_HV: 26}, name="before.json"))
    adr104 = H.cadence_budgets(_manifest(tmp_path, {_HV: 1}, name="after.json"))
    assert daily[_HV]["seconds"] == 26 * 3600
    assert adr104[_HV]["seconds"] == 3600
    assert adr104[_HV]["source"] == "manifest_slo"


def test_unreadable_constitution_falls_back_and_says_so(tmp_path):
    """fail-CLOSED в том, что УТВЕРЖДАЕТСЯ: нечитаемая конституция не даёт измеренный бюджет.

    Откат на литерал разрешён (модуль fail-SAFE по контракту), молчание об откате — нет:
    «не измерено» обязано быть сказано вслух, иначе оно неотличимо от замера.
    """
    b = H.cadence_budgets(tmp_path / "no-such-manifest.json")
    assert b[_HV]["seconds"] == 30 * 3600          # не строже и не слабее прежнего
    assert b[_HV]["source"] == "fallback"          # ...но помечено как НЕ замер
    assert "not read" in b[_HV]["why"]
    assert b["market_regime"]["source"] == "ceiling"


def _live_slo_hours():
    """`slo_hours` активных артефактов офиса из ЖИВОЙ конституции. Нет файла ⇒ {}.

    Литерала здесь намеренно НЕТ: срок годности — решение владельца (ADR-104 сменил его
    21.08), и тест, приколотивший число, ровно этим решением и красился бы. Проверяем не
    ЗНАЧЕНИЕ, а СОГЛАСИЕ двух сторожей с одним источником.
    """
    import json as _json
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(H.__file__))))
    path = _os.path.join(root, "architecture", "manifest.json")
    if not _os.path.exists(path):
        return {}
    try:
        doc = _json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return {}
    return {_os.path.basename(a["path"])[:-5]: a.get("slo_hours")
            for a in doc.get("artifacts", []) or []
            if a.get("status") == "active" and str(a.get("path", "")).startswith(
                "data/investment_os/") and a.get("slo_hours")}


def test_health_and_conformance_judge_one_artifact_by_one_number():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ ПО СУЩЕСТВУ: два сторожа, один файл — одно число.

    Авария #340 и была расхождением вердиктов об ОДНОМ артефакте: `architecture_conformance`
    (B2) судил по `slo_hours` конституции («возраст 18.8ч > SLO 1ч»), а health — по литералу
    в своём коде («FRESH, 12.4ч при сроке 30ч»). Разница в 30 раз.

    Тест НАМЕРЕННО зовёт только СТАРУЮ однопараметрическую форму `budget_s(agent)` и живую
    конституцию: на неисправленном origin он обязан краснеть на СУТИ (108000 против 3600),
    а не на отсутствии нового имени (урок «положительный контроль может быть украшением»).
    """
    declared = _live_slo_hours()
    if not declared:
        return                                     # дерево без конституции — нечем сверять
    for agent, slo in declared.items():
        if agent not in H.ANALYSTS:
            continue
        assert H.budget_s(agent) == int(slo * 3600), (
            f"{agent}: health судит по {H.budget_s(agent)}с, конституция объявила {slo}ч")


def test_live_house_view_verdict_obeys_the_constitution(tmp_path):
    """Та же суть на уровне ВЕРДИКТА, тоже по старому API (`scan` без `budgets=`).

    Артефакту дают возраст ровно вдвое больше объявленного срока годности: по конституции
    это STALE при любом её значении. На неисправленном модуле бюджет — литерал 30ч, и при
    сроке 1ч возраст 2ч читается как `FRESH` / `HEALTHY` — ровно то, что шаг 0-офис
    печатал владельцу 22.08.
    """
    declared = _live_slo_hours()
    slo = declared.get(_HV)
    if not slo or slo * 2 >= H.FRESH_AGE_S / 3600:
        return          # объявленный срок не отличим от общего потолка — контроль бессилен
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, _HV, "ok", age_days=(slo * 2) / 24.0)
    s = H.scan(tmp_path, now=_dt())
    assert s["house_view"]["status"] == "STALE"
    assert s["house_view_fresh"] is False
    assert s["house_view"]["max_age_s"] == int(slo * 3600)


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
    s = H.scan(tmp_path, now=_dt(), budgets=_daily_budgets(tmp_path))
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
    s = H.scan(tmp_path, now=_dt(), budgets=_daily_budgets(tmp_path))
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
    """Вердикт без названного бюджета нечитаем: max_age_s обязан лежать в каждой строке.

    Цикл #340 добавил вторую половину того же требования: мало назвать ЧИСЛО, надо назвать
    и его ПРОИСХОЖДЕНИЕ — иначе замер неотличим от отката на литерал.
    """
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    b = _daily_budgets(tmp_path)
    s = H.scan(tmp_path, now=_dt(), budgets=b)
    for r in s["analysts"]:
        assert r["max_age_s"] == H.budget_s(r["agent"], b)
        assert r["budget_source"] in ("manifest_slo", "fallback", "ceiling")
        assert r["budget_why"]


def test_step0_office_stops_testifying_for_a_house_view_the_constitution_calls_stale(tmp_path):
    """ЖИВАЯ АВАРИЯ 22.08 целиком, на уровне вердикта, который читает шаг 0-офис.

    Конституция (ADR-104) объявила дом-вью срок годности 1ч; артефакту 12.4ч. Шаг 0-офис —
    ПЕРВОЕ, что оркестратор читает каждый цикл, — печатал `дом-вью: FRESH · возраст 12.4ч
    при сроке годности 30ч`, свидетельствуя В ПОЛЬЗУ здоровья артефакта, который по
    действующему решению владельца протух 11 часов назад.

    На неисправленном модуле бюджет = литерал 108000с ⇒ `FRESH` / `HEALTHY` / `протухли 0`
    — контроль краснеет на СУТИ, а не на отсутствии нового поля (урок #234), поэтому
    поведенческие ассерты идут ПЕРВЫМИ.
    """
    for a in H.ANALYSTS:
        _write(tmp_path, a, "ok")
    _write(tmp_path, _HV, "ok", age_days=12.4 / 24.0)
    s = H.scan(tmp_path, now=_dt(),
               budgets=H.cadence_budgets(_manifest(tmp_path, {_HV: 1})))
    assert s["house_view"]["status"] == "STALE"
    assert s["house_view_fresh"] is False
    assert s["overall"] == "STALE"
    assert s["counts"]["stale"] == 1
    assert s["house_view"]["max_age_s"] == 3600
    assert s["house_view"]["budget_source"] == "manifest_slo"
