"""Шаг 0-офис обязан печатать ТО, ЧТО В ФАЙЛАХ (ADR-066, Фаза 2).

`scripts/consume_office_reports.py` — обязательный вход протокола оркестратора:
он кладёт продукты инвест-офиса и отчёты сторожей в контекст сессии. Если ветка
выжимки читает поля, которых производитель не пишет, шаг честно отвечает на свой
вопрос («что лежит в полях, которые я читаю») и молчит утвердительно о нужном
(«что лежит в файле»). Это fail-OPEN, и в ЭТОМ файле он рецидивировал трижды:

  * `findings_bridge` — читала несуществующий файл и `counts.opened/pending`;
  * `house_view_gap` — читала `overall`/`counts.critical`/`findings`, а
    производитель пишет `gaps`/`counts.warn|info|unchecked`: обязательный шаг
    печатал «вердикт: None» при ДВУХ реальных расхождениях (замер цикла #176,
    воспроизведён обязательным прогоном того же цикла);
  * `_health` — читала `stale`/`failing`/`unknown` на верхнем уровне, где их
    нет: протухший аналитик не был бы назван вовсе.

Каждый тест ниже — положительный контроль: он краснеет на неисправленном файле
и воспроизводит настоящую аварию, а не воображаемую. Артефакты в фикстурах —
СНИМКИ ПРОДА (`data/house_view_gap.json`, `data/investment_os/_health.json` на
2026-08-09), а не выдуманная схема: тест, написанный по той же памяти, что и
дефект, повторил бы дефект.
"""
# FROZEN-DATE-OK: injected-clock — часы инъектируются (`now=NOW`) вместе с
# фиксированными отметками, взятыми из тех же снимков прода: обе стороны
# закреплены, тест бессмертен к календарю (преференция #1 в
# `.claude/rules/deployment.md`), и число возраста можно проверять точно.
from __future__ import annotations

import importlib.util
import io
import json
import os
import contextlib
from pathlib import Path

import pytest

from spa_core.tests._freshness import at

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "consume_office_reports.py"


def _load():
    spec = importlib.util.spec_from_file_location("_consume_office_reports", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

# Инъектируемые часы: якорь и все отметки ниже взяты из одного снимка прода.
NOW = at("2026-08-09T05:44:00+00:00")

# ── снимки прода (verbatim, сокращены по длине списков) ──────────────────────

# data/house_view_gap.json, 2026-08-09T01:02:56Z — ДВА реальных расхождения.
HOUSE_VIEW_GAP_REAL = {
    "generated_at": "2026-08-09T01:02:56.583791+00:00",
    "adr": "ADR-066",
    "gaps": [
        {"key": "gap:opportunity_no_adapter:aerodrome_usdc_lp",
         "type": "opportunity_unheld", "severity": "INFO",
         "message": "возможность aerodrome_usdc_lp 8.5% (evidence L3) вне реестра адаптеров "
                    "— входа технически нет (адаптер + промоушен)",
         "protocol": "aerodrome_usdc_lp", "apy_pct": 8.5, "evidence_level": "L3"},
        {"key": "gap:opportunity_no_adapter:pendle-pt",
         "type": "opportunity_unheld", "severity": "INFO",
         "message": "возможность pendle-pt 8.0% (evidence L3) вне реестра адаптеров "
                    "— входа технически нет (адаптер + промоушен)",
         "protocol": "pendle-pt", "apy_pct": 8.0, "evidence_level": "L3"},
    ],
    "unchecked": [],
    "counts": {"warn": 0, "info": 2, "unchecked": 0},
}

# data/investment_os/_health.json, 2026-08-08T19:00:07Z (список аналитиков урезан).
HEALTH_REAL = {
    "model": "investment_os_health", "is_advisory": True,
    "generated_at": "2026-08-08T19:00:07.228317+00:00",
    "overall": "HEALTHY",
    "counts": {"total": 11, "healthy": 11, "stale": 0, "missing": 0,
               "unknown_or_corrupt": 0},
    "analysts": [
        {"agent": "stablecoin_yield", "present": True, "fresh": True,
         "status": "ok", "age_s": 69420},
        {"agent": "market_regime", "present": True, "fresh": True,
         "status": "ok", "age_s": 69240},
    ],
}

# data/investment_os/chief_investment.json, 2026-08-08T09:11:47Z — 19.4 ч на момент
# замера: артефакт, который ехал в контекст БЕЗ единого признака возраста.
CHIEF_REAL = {
    "agent": "chief_investment", "status": "ok", "is_advisory": True,
    "generated_at": "2026-08-08T09:11:47.733075+00:00",
    "house_view": {
        "overall_posture": "YELLOW",
        "conflicts": ["regime=YELLOW vs threat=NO_THREAT_OBSERVED diverge — "
                      "surfaced, not averaged"],
        "top_opportunities": [
            {"evidence_level": "L3",
             "value": {"protocol": "aerodrome_usdc_lp", "apy_pct": 8.5}},
        ],
    },
}


def _text(lines) -> str:
    return "\n".join(lines)


# ── 1. house_view_gap: расхождения ВИДНЫ, `None` не печатается ───────────────

def test_house_view_gap_prints_the_real_gaps_not_none() -> None:
    """Авария #176 дословно: два реальных расхождения печатались как «None».

    Мутация «вернуть чтение `findings`» обязана красить этот тест: у настоящего
    артефакта поля `findings` нет вовсе, и цикл по нему даёт пустой вывод.
    """
    out = _text(MOD._summarize_json("data/house_view_gap.json",
                                    HOUSE_VIEW_GAP_REAL, now=NOW))
    assert "aerodrome_usdc_lp" in out, out
    assert "pendle-pt" in out, out
    assert "расхождений house_view↔факт: 2" in out, out
    assert "None" not in out, (
        "«None» в выводе читается глазом как «пусто, всё в порядке» — "
        "это ровно тот fail-OPEN, который чинили:\n" + out)


def test_house_view_gap_counts_come_from_the_real_keys() -> None:
    """Счётчики производителя — warn/info/unchecked, а не critical/warn/aged."""
    out = _text(MOD._summarize_json("data/house_view_gap.json",
                                    HOUSE_VIEW_GAP_REAL, now=NOW))
    assert "warn=0" in out and "info=2" in out and "unchecked=0" in out, out


def test_missing_counter_is_named_unmeasured_never_none() -> None:
    """Отсутствующий счётчик — НЕ ноль и не `None`, а «НЕ ИЗМЕРЕНО» (fail-CLOSED)."""
    broken = dict(HOUSE_VIEW_GAP_REAL, counts={"warn": 0})  # info/unchecked пропали
    out = _text(MOD._summarize_json("data/house_view_gap.json", broken, now=NOW))
    assert "info=НЕ ИЗМЕРЕНО" in out, out
    assert "unchecked=НЕ ИЗМЕРЕНО" in out, out
    assert "None" not in out, out


# ── 2. возраст — у КАЖДОГО артефакта ─────────────────────────────────────────

def test_chief_investment_carries_its_age() -> None:
    """house_view ехал в контекст без возраста; замер #176 — 19.4 ч.

    Часы и отметка закреплены обе, поэтому число проверяется точно.
    """
    out = _text(MOD._summarize_json("data/investment_os/chief_investment.json",
                                    CHIEF_REAL, now=NOW))
    assert "возраст 20.5ч" in out, out
    assert "старше суток" not in out, out
    assert "постура: YELLOW" in out, out


def test_age_marker_speaks_when_older_than_a_day() -> None:
    """Возраст должен ГОВОРИТЬ, а не только печататься: сутки — порог метки."""
    old = dict(CHIEF_REAL, generated_at="2026-08-07T05:00:00+00:00")
    out = _text(MOD._summarize_json("data/investment_os/chief_investment.json",
                                    old, now=NOW))
    assert "старше суток" in out, out


def test_missing_generated_at_is_named_not_silent() -> None:
    """Нет отметки времени ⇒ так и сказать; молчание тут неотличимо от свежести."""
    noden = {k: v for k, v in HOUSE_VIEW_GAP_REAL.items() if k != "generated_at"}
    out = _text(MOD._summarize_json("data/house_view_gap.json", noden, now=NOW))
    assert "возраст НЕ ИЗМЕРЕН" in out, out


def test_unparseable_generated_at_is_named_not_crashed() -> None:
    """Мусор в отметке — находка, а не исключение посреди обязательного шага."""
    bad = dict(HOUSE_VIEW_GAP_REAL, generated_at="вчера")
    out = _text(MOD._summarize_json("data/house_view_gap.json", bad, now=NOW))
    assert "возраст НЕ ИЗМЕРЕН" in out, out


# ── 3. _health: протухший аналитик обязан быть НАЗВАН ────────────────────────

def test_health_counters_come_from_counts_not_top_level() -> None:
    """Прежняя ветка читала stale/failing/unknown на верхнем уровне — их там нет."""
    out = _text(MOD._summarize_json("data/investment_os/_health.json",
                                    HEALTH_REAL, now=NOW))
    assert "статус офиса: HEALTHY" in out, out
    assert "всего 11" in out and "здоровы 11" in out and "протухли 0" in out, out


def test_health_names_a_stale_analyst() -> None:
    """Настоящая авария: протухший аналитик не был назван шагом 0-офис ВООБЩЕ."""
    degraded = json.loads(json.dumps(HEALTH_REAL))
    degraded["overall"] = "STALE"
    degraded["counts"]["healthy"] = 10
    degraded["counts"]["stale"] = 1
    degraded["analysts"][1] = {"agent": "market_regime", "present": True,
                               "fresh": False, "status": "ok", "age_s": 999999}
    out = _text(MOD._summarize_json("data/investment_os/_health.json",
                                    degraded, now=NOW))
    assert "market_regime" in out, out
    assert "протухли 1" in out, out


# ── 4. сторож сторожа: расхождение схемы измеряется, а не выглядывается ──────

def test_schema_drift_is_measured_and_spoken() -> None:
    """Класс проверяется не веткой, а ФАЙЛОМ: ушло поле — сказано вслух.

    Именно этого не было три раза подряд: производитель уезжал, ветка молча
    печатала пустоту, и находили это глазами месяцы спустя.
    """
    drifted = {k: v for k, v in HOUSE_VIEW_GAP_REAL.items() if k != "gaps"}
    out = _text(MOD._summarize_json("data/house_view_gap.json", drifted, now=NOW))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out
    assert "gaps" in out, out


def test_schema_drift_sees_nested_fields() -> None:
    """У house_view всё интересное на втором уровне — проверка верхнего слепа."""
    drifted = json.loads(json.dumps(CHIEF_REAL))
    del drifted["house_view"]["top_opportunities"]
    out = _text(MOD._summarize_json("data/investment_os/chief_investment.json",
                                    drifted, now=NOW))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out
    assert "house_view.top_opportunities" in out, out


def test_no_schema_drift_on_the_real_artifacts() -> None:
    """На НАСТОЯЩИХ снимках прода тревоги быть не должно — иначе это волк."""
    for rel, doc in (("data/house_view_gap.json", HOUSE_VIEW_GAP_REAL),
                     ("data/investment_os/_health.json", HEALTH_REAL),
                     ("data/investment_os/chief_investment.json", CHIEF_REAL)):
        out = _text(MOD._summarize_json(rel, doc, now=NOW))
        assert "СХЕМА РАЗОШЛАСЬ" not in out, f"{rel}:\n{out}"


@pytest.mark.parametrize("name", sorted(MOD._READ_SCHEMA))
def test_declared_schema_matches_the_live_producer(name: str) -> None:
    """Объявленная схема сверяется с ЖИВЫМ артефактом, если он на диске.

    Фикстуры выше — снимки; этот тест ловит дрейф производителя, случившийся
    ПОСЛЕ снимка. Файла нет (`data/` частично вне git) ⇒ skip, а не молчаливый
    зелёный: пропуск назван.
    """
    data_dir = _REPO / "data"
    live = next((p for p in sorted(data_dir.rglob(name)) if p.is_file()), None) \
        if data_dir.is_dir() else None
    if live is None:
        pytest.skip(f"{name} нет на диске в этом дереве — сверять нечего")
    try:
        doc = json.loads(live.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"{live} не разобран как JSON ({e}) — не предмет этого теста")
    missing = [p for p in MOD._READ_SCHEMA[name] if not MOD._has_path(doc, p)]
    assert not missing, (
        f"выжимка шага 0-офис читает у {live} поля, которых производитель не "
        f"пишет: {missing} — ветка мертва, как уже бывало трижды")


# ── 5. проводка целиком: не деталь, а весь обязательный шаг ──────────────────

def test_main_end_to_end_prints_ages_and_real_gaps(tmp_path) -> None:
    """Мутировать проводку, а не только детали: гоняем main() над манифестом.

    Проверка ветки в отрыве уже была зелёной при мёртвой проводке (урок #144),
    поэтому обязательный шаг проверяется тем же путём, каким его зовёт протокол.
    """
    root = tmp_path
    (root / "architecture").mkdir()
    (root / "data" / "investment_os").mkdir(parents=True)
    (root / "architecture" / "manifest.json").write_text(json.dumps({"artifacts": [
        {"path": "data/house_view_gap.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
        {"path": "data/investment_os/chief_investment.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
        {"path": "data/investment_os/_health.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
    ]}), encoding="utf-8")
    (root / "data" / "house_view_gap.json").write_text(
        json.dumps(HOUSE_VIEW_GAP_REAL), encoding="utf-8")
    (root / "data" / "investment_os" / "chief_investment.json").write_text(
        json.dumps(CHIEF_REAL), encoding="utf-8")
    (root / "data" / "investment_os" / "_health.json").write_text(
        json.dumps(HEALTH_REAL), encoding="utf-8")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(root), "--no-receipts"], now=NOW)
    out = buf.getvalue()

    assert rc == 0, out
    assert "прочитано 3, не прочитано 0" in out, out
    assert "aerodrome_usdc_lp" in out, out          # расхождения видны
    assert out.count("возраст ") >= 3, out          # возраст у КАЖДОГО
    assert "None" not in out, out                   # ни одного молчаливого None


def test_main_still_names_a_missing_file(tmp_path) -> None:
    """Fail-CLOSED осталась fail-CLOSED: файла нет ⇒ «НЕ ПРОЧИТАН», не тишина."""
    root = tmp_path
    (root / "architecture").mkdir()
    (root / "architecture" / "manifest.json").write_text(json.dumps({"artifacts": [
        {"path": "data/house_view_gap.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
    ]}), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(root), "--no-receipts"], now=NOW)
    out = buf.getvalue()
    assert rc == 0, out
    assert "НЕ ПРОЧИТАН" in out, out
    assert "прочитано 0, не прочитано 1" in out, out


def test_old_positional_call_still_works() -> None:
    """Соседний тест (`test_card_delivery`) зовёт выжимку двумя аргументами."""
    out = _text(MOD._summarize_json("data/findings_bridge_report.json", {
        "generated_at": "2026-08-09T01:02:56.598582+00:00",
        "created": [], "closed": [], "deferred": [], "waiting_hysteresis": [],
        "escalated": [], "sources_unread": [], "open_cards": 0,
        "delivery": {"status": "IDLE", "delivered": []},
    }))
    assert "мост находка→карточка" in out, out
    assert "доставка карточек: IDLE" in out, out
