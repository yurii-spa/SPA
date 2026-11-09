#!/usr/bin/env python3
"""Батарея прибора §21 «Частота работы» (`spa_core/analytics/cadence_census.py`).

Каждая проверка — положительный контроль: сцена, в которой прибор ОБЯЗАН
ответить иначе, чем на живом дереве. Проба, никогда не видевшая другого мира, —
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

Отдельно стои́т :func:`test_every_declared_kind_is_reachable_by_some_scene` —
это та проба, которая в §20 нашла ЧЕТЫРЕ ошибки замера подряд: род, объявленный
в шкале и не достигаемый ни одной сценой, есть ровно дефект
``named_but_unreachable``, найденный §19 у потолка T3. Прибор, повторяющий
собой находку, хуже отсутствия прибора.

Время и дерево — ВХОДЫ: ни одной литеральной даты и ни одного литерального pid
здесь нет, сцены строятся в ``tmp_path``.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from spa_core.analytics import cadence_census as cc


# ---------------------------------------------------------------------------
# Сцены: минимальное объявление, в котором все поля НАЗВАНЫ явно
# ---------------------------------------------------------------------------

def _agent(label, schedule, role, produces=(), intent="active"):
    return {"label": label, "schedule": schedule, "role": role,
            "intent": intent,
            "produces": [{"artifact": a, "slo_hours": s} for a, s in produces]}


def _manifest(agents, artifacts=()):
    return {"schema_version": 1, "agents": list(agents),
            "artifacts": [dict(a) for a in artifacts]}


def _write(root: Path, manifest) -> Path:
    (root / "architecture").mkdir(parents=True, exist_ok=True)
    (root / "architecture" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root


#: Сцена «как в живом дереве»: наблюдатель раз в 5 минут, пересчёт раз в сутки.
def _scene_live():
    return _manifest([
        _agent("obs.fast", "interval:300s", "monitoring",
               [("data/apy_ranking.json", 3.0)]),
        _agent("recalc.daily", "calendar:08:00", "allocation",
               [("data/allocation_rationale.json", 26.0)]),
    ])


# ---------------------------------------------------------------------------
# Ввоз словарей
# ---------------------------------------------------------------------------

def test_vocabularies_are_imported_not_reprinted():
    """Своей копии ввезённого словаря у прибора нет, и ввоз СОСТОЯЛСЯ."""
    assert cc._VOCAB_ERRORS == [], cc._VOCAB_ERRORS
    from spa_core.analytics.new_capital_census import MONEY_PATH_20, SURFACES_20
    assert cc.SURFACES_21[:len(SURFACES_20)] == tuple(SURFACES_20)
    assert cc.SURFACES_21[len(SURFACES_20):] == ("observation", "recalculation")
    assert tuple(MONEY_PATH_20) == tuple(cc.MONEY_PATH_20)


def test_unmeasured_is_the_imported_one_not_a_local_string():
    from spa_core.analytics.transaction_economics import UNMEASURED
    assert cc.UNMEASURED is UNMEASURED or cc.UNMEASURED == UNMEASURED
    for scale in (cc.TACT_KINDS, cc.ENFORCEMENT_KINDS, cc.COUPLING_KINDS,
                  cc.EVENT_KINDS, cc.RAISE_PURPOSES):
        assert UNMEASURED in scale, scale


# ---------------------------------------------------------------------------
# Текст ТЗ против пересказа заказа
# ---------------------------------------------------------------------------

def test_owner_named_eleven_events_not_eight():
    """Заказ G952 п. 1 назвал ВОСЕМЬ; в §21 их одиннадцать.

    Контроль в обе стороны: число совпадает с объявленным И в перечне есть
    ровно те три, которые пересказ потерял. Потеряны были не случайные: у всех
    трёх в системе есть живой наблюдатель, значит пересказ смещал ответ.
    """
    assert len(cc.OWNER_EVENTS) == cc.OWNER_EVENTS_DECLARED == 11
    assert len(set(cc.OWNER_EVENTS)) == 11, "повтор в перечне событий"
    for lost in ("liquidity change", "Tier change", "security alert"):
        assert lost in cc.OWNER_EVENTS, lost


def test_every_event_has_a_declared_system_vocabulary_or_is_unreachable():
    """У события либо объявлены фрагменты, либо оно названо недостижимым.

    Событие без того и другого прибор отвечал бы `unmeasured` МОЛЧА — то есть
    «не измерено» было бы неотличимо от «нет читателя».
    """
    for event in cc.OWNER_EVENTS:
        assert (event in cc.EVENT_ARTIFACT_FRAGMENTS
                or event in cc.EVENTS_UNREACHABLE), event


# ---------------------------------------------------------------------------
# (а) Такт
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("schedule,expected", [
    ("interval:300s", 300.0),
    ("interval:3600s", 3600.0),
    ("interval:21600", 21600.0),
    ("calendar:08:00", 86400.0),
    ("calendar:00:00,06:00,12:00,18:00", 21600.0),
    ("calendar:wd0·10:00", 604800.0),
    ("calendar:minute:30", 3600.0),
])
def test_tact_is_parsed_from_the_declared_form(schedule, expected):
    seconds, why = cc.tact_seconds(schedule)
    assert seconds == pytest.approx(expected), why
    assert why, "форма разобрана, но причина не названа"


@pytest.mark.parametrize("schedule", ["daemon", "manual", "event:watchpaths",
                                      "", None, "whenever-i-feel-like-it"])
def test_a_schedule_without_a_tact_is_a_third_outcome_with_a_reason(schedule):
    """Третий исход (инв. #17): такта нет — и сказано, ПОЧЕМУ его нет."""
    seconds, why = cc.tact_seconds(schedule)
    assert seconds is None
    assert why and len(why) > 10, repr(why)


def test_mixed_calendar_refuses_instead_of_inventing_one_tact():
    """`calendar:` с недельными И суточными отметками одного такта не имеет."""
    seconds, why = cc.tact_seconds("calendar:wd0·10:00,08:00")
    assert seconds is None
    assert "смешивает" in why


def test_enforced_seconds_takes_the_strictest_declared_deadline():
    agent = _agent("a", "interval:300s", "monitoring",
                   [("x.json", 26.0), ("y.json", 3.0), ("z.json", 168.0)])
    enf, slos = cc.enforced_seconds(agent)
    assert enf == pytest.approx(3.0 * 3600)
    assert slos == [3.0, 26.0, 168.0]
    empty, none = cc.enforced_seconds(_agent("b", "interval:1s", "monitoring"))
    assert empty is None and none == []


def test_two_deadlines_are_both_printed_and_never_reduced_to_one():
    """Заказ требует ТРЕТЬЕГО исхода, а не выбора срока.

    Контроль в обе стороны: при слабом сроке — род `enforced_looser` с числом;
    при сроке того же порядка — `enforced_at_tact`. Если бы прибор «выбирал»
    один из двух сроков, оба случая выглядели бы одинаково.
    """
    looser, why1 = cc._enforcement_kind(300.0, 604800.0)
    assert looser == "enforced_looser" and "2016" in why1
    same, _ = cc._enforcement_kind(3600.0, 7200.0)
    assert same == "enforced_at_tact"
    nosl, _ = cc._enforcement_kind(300.0, None)
    assert nosl == "no_slo_declared"
    # Срок объявлен, такта нет — отношение не вычисляется, и это НЕ ноль.
    unk, why2 = cc._enforcement_kind(None, 3600.0)
    assert unk == cc.UNMEASURED and why2


def test_observation_tact_is_the_finest_declared_observer(tmp_path):
    root = _write(tmp_path, _manifest([
        _agent("obs.slow", "interval:3600s", "monitoring"),
        _agent("obs.fast", "interval:300s", "monitoring"),
        _agent("not.observer", "interval:1s", "allocation"),
        _agent("obs.retired", "interval:1s", "monitoring", intent="retired"),
    ]))
    manifest, err = cc.load_manifest(root)
    assert err is None
    obs = cc.observation_tact(manifest)
    assert obs["finest"] == "obs.fast", obs
    assert obs["tact_s"] == 300.0
    assert obs["kind"] == "within_benchmark"


def test_recalc_agent_is_measured_from_the_declaration_not_hardcoded(tmp_path):
    """Положительный контроль: переименуй производителя — прибор назовёт НОВОЕ имя.

    Это единственный способ отличить «имя измерено» от «имя зашито»: на живом
    дереве оба ответа совпадают с `com.spa.daily_cycle`.
    """
    root = _write(tmp_path, _manifest([
        _agent("some.other.name", "interval:3600s", "allocation",
               [("data/allocation_rationale.json", 26.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    label, arts, why = cc.recalc_agent(manifest)
    assert label == "some.other.name", (label, why)
    assert arts == ["data/allocation_rationale.json"]
    rec = cc.recalculation_tact(manifest)
    assert rec["label"] == "some.other.name"
    assert rec["tact_s"] == 3600.0
    assert rec["kind"] == "within_benchmark"


def test_two_declared_producers_give_the_third_outcome_not_the_first_one(tmp_path):
    """Два производителя одного предмета ⇒ единственного ответа нет."""
    root = _write(tmp_path, _manifest([
        _agent("first", "interval:60s", "allocation",
               [("data/allocation_rationale.json", 26.0)]),
        _agent("second", "calendar:08:00", "allocation",
               [("data/rebalance_trigger.json", 26.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    label, names, why = cc.recalc_agent(manifest)
    assert label is None, "прибор выбрал одного из двух вместо отказа"
    assert names == ["first", "second"]
    assert "единственного" in why
    rec = cc.recalculation_tact(manifest)
    assert rec["kind"] == cc.UNMEASURED


def test_unreadable_declaration_is_unmeasured_and_never_a_clean_pass(tmp_path):
    report = cc.census(tmp_path)
    assert cc.verdict_code(report) == 2
    assert report["unmeasured"]
    assert "не прочитан" in " ".join(report["unmeasured"])
    # Отчёт обязан рендериться и в этом состоянии: падение рендера скрыло бы
    # «не измерено» так же надёжно, как молчание.
    assert "НЕ ИЗМЕРЕНО" in cc.render(report)


def test_declaration_missing_one_half_is_unmeasured(tmp_path):
    (tmp_path / "architecture").mkdir()
    (tmp_path / "architecture" / "manifest.json").write_text(
        json.dumps({"agents": []}), encoding="utf-8")
    manifest, err = cc.load_manifest(tmp_path)
    assert manifest is None and "artifacts" in err


# ---------------------------------------------------------------------------
# Объединение двух половин объявления — регрессионный контроль
# ---------------------------------------------------------------------------

def test_both_halves_of_the_declaration_are_read(tmp_path):
    """Регрессия цикла #1082: первая редакция читала ОДНУ половину.

    На живом объявлении 73 артефакта объявлены ТОЛЬКО на стороне агентов, и
    прибор выдал шесть «ИЗМЕРЕННЫХ НУЛЕЙ» — в том числе про событие, чьё
    наблюдение демонстративно читает измеренная дверь подъёма. Сцена
    воспроизводит ровно это: артефакт объявлен только в `produces`.
    """
    root = _write(tmp_path, _manifest(
        agents=[_agent("obs", "interval:300s", "monitoring",
                       [("data/red_flags.json", 3.0)])],
        artifacts=[{"path": "data/unrelated.json", "producer": "obs"}],
    ))
    manifest, _ = cc.load_manifest(root)
    prod = cc.declared_productions(manifest)
    assert "data/red_flags.json" in prod, prod
    assert prod["data/red_flags.json"] == ["obs"]
    rows = cc._artifacts_for_event(manifest, ("red_flag",))
    assert [r["artifact"] for r in rows] == ["data/red_flags.json"]
    assert rows[0]["tact_s"] == 300.0


def test_only_active_producers_count(tmp_path):
    root = _write(tmp_path, _manifest(
        agents=[_agent("dead", "interval:300s", "monitoring",
                       [("data/red_flags.json", 3.0)], intent="retired")],
    ))
    manifest, _ = cc.load_manifest(root)
    assert cc.declared_productions(manifest) == {}


# ---------------------------------------------------------------------------
# (б) Связь тактов — дифференциально, с контролем
# ---------------------------------------------------------------------------

def test_decoupled_when_the_recalc_tact_lives_on_its_own_calendar(tmp_path):
    root = _write(tmp_path, _scene_live())
    manifest, _ = cc.load_manifest(root)
    c = cc.coupling(manifest)
    assert c["kind"] == "decoupled", c
    assert c["control_moved"] is True
    assert c["perturbed_observation_s"] < c["base_observation_s"]
    assert c["perturbed_recalc_s"] == c["base_recalc_s"]


def test_coupled_is_reachable_when_the_recalc_agent_is_itself_an_observer(tmp_path):
    """Положительный контроль оси (б): род `coupled` ДОСТИЖИМ.

    Сцена, в которой пересчёт объявлен наблюдателем: возмущение такта
    наблюдения двигает и его. Без этой сцены `decoupled` на живом дереве было
    бы неотличимо от прибора, который не умеет отвечать иначе.
    """
    root = _write(tmp_path, _manifest([
        _agent("both", "interval:300s", "monitoring",
               [("data/allocation_rationale.json", 26.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    c = cc.coupling(manifest)
    assert c["kind"] == "coupled", c
    assert c["perturbed_recalc_s"] != c["base_recalc_s"]


def test_coupling_is_unmeasured_when_there_is_nothing_to_perturb(tmp_path):
    """Наблюдатели без формы `interval:` ⇒ возмущать нечем, ответ не выдаётся."""
    root = _write(tmp_path, _manifest([
        _agent("obs.daemon", "daemon", "monitoring"),
        _agent("recalc", "calendar:08:00", "allocation",
               [("data/allocation_rationale.json", 26.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    c = cc.coupling(manifest)
    assert c["kind"] == cc.UNMEASURED
    assert "возмутить" in c["why"]


def test_coupling_is_unmeasured_when_the_recalc_tact_is_unmeasured(tmp_path):
    root = _write(tmp_path, _manifest([
        _agent("obs", "interval:300s", "monitoring"),
    ]))
    manifest, _ = cc.load_manifest(root)
    c = cc.coupling(manifest)
    assert c["kind"] == cc.UNMEASURED
    assert "такт пересчёта не измерен" in c["why"]


def test_positive_control_failure_withholds_the_coupling_answer(tmp_path, monkeypatch):
    """Контроль не сдвинул такт пересчёта ⇒ ответ о связи НЕ ВЫДАЁТСЯ.

    Возмущение контроля глушится подменой ЕДИНСТВЕННОЙ двери возмущения —
    замер становится замером о приборе, и прибор обязан это сказать, а не
    напечатать `decoupled`.
    """
    root = _write(tmp_path, _scene_live())
    manifest, _ = cc.load_manifest(root)
    monkeypatch.setattr(cc, "_perturb_recalc",
                        lambda m, label, seconds: json.loads(json.dumps(m)))
    c = cc.coupling(manifest)
    assert c["kind"] == cc.UNMEASURED, c
    assert c["control_moved"] is False
    assert "контроль" in c["why"]


# ---------------------------------------------------------------------------
# Двери подъёма — измерены по дереву
# ---------------------------------------------------------------------------

_DOOR_FSTRING = '''
import os, subprocess
def go():
    subprocess.run(["launchctl", "kickstart", "-k",
                    f"gui/{os.getuid()}/recalc.label"], timeout=5)
def read():
    return open("data/red_flags.json").read()
'''

_DOOR_HELPER = '''
def _kickstart(label):
    return label
def go():
    _kickstart("recalc.label")
def read():
    return open("data/paper_trading_status.json").read()
'''

_NOT_A_DOOR = '''
# упоминает и слово, и метку, но ни в одном ВЫЗОВЕ они не встречаются вместе
NOTE = "kickstart"
LABEL = "recalc.label"
'''


def _tree_with_doors(tmp_path: Path, files) -> Path:
    (tmp_path / "spa_core" / "monitoring").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    for name, body in files.items():
        (tmp_path / "spa_core" / "monitoring" / name).write_text(
            textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def test_both_living_forms_of_a_raise_door_are_found(tmp_path):
    """f-строка метки И вызов локального помощника — ДВЕ формы живого дерева.

    Разбор, смотрящий только на `ast.Constant` верхнего уровня, нашёл бы вторую
    и пропустил первую — а первая и есть единственная дверь снижения риска.
    """
    root = _tree_with_doors(tmp_path, {
        "fstring_door.py": _DOOR_FSTRING,
        "helper_door.py": _DOOR_HELPER,
        "not_a_door.py": _NOT_A_DOOR,
    })
    out = cc.raise_doors(root, "recalc.label", {})
    files = {d["file"] for d in out["doors"]}
    assert files == {"spa_core/monitoring/fstring_door.py",
                     "spa_core/monitoring/helper_door.py"}, out


def test_a_mention_outside_a_call_is_not_a_door(tmp_path):
    root = _tree_with_doors(tmp_path, {"not_a_door.py": _NOT_A_DOOR})
    out = cc.raise_doors(root, "recalc.label", {})
    assert out["doors"] == []


def test_unparsable_candidate_is_named_not_dropped(tmp_path):
    """Файл, который не разбирается, попадает в `unparsed`, а не исчезает."""
    root = _tree_with_doors(tmp_path, {
        "broken.py": 'subprocess.run(["kickstart", "recalc.label"\n',
    })
    out = cc.raise_doors(root, "recalc.label", {})
    assert out["doors"] == []
    assert any("SyntaxError" in u for u in out["unparsed"]), out
    assert out["kind"] == cc.UNMEASURED


def test_doors_are_not_searched_when_the_recalc_label_is_unmeasured(tmp_path):
    out = cc.raise_doors(tmp_path, None)
    assert out["kind"] == cc.UNMEASURED
    assert "не измерена" in out["why"]


def test_missing_search_dir_is_named_as_unmeasured(tmp_path):
    out = cc.raise_doors(tmp_path, "recalc.label", {})
    assert out["kind"] == cc.UNMEASURED
    assert any("каталога нет" in u for u in out["unparsed"]), out


# ---------------------------------------------------------------------------
# Цель подъёма
# ---------------------------------------------------------------------------

def test_a_door_touching_the_kill_switch_is_derisk_even_if_it_reads_events():
    kind, why = cc._raise_purpose(
        ["data/kill_switch_active.json", "data/red_flags.json"],
        {"red_flags.json": ["security alert"]})
    assert kind == "derisk", why


def test_a_door_reading_no_event_observation_is_liveness_repair():
    """Регрессия цикла #1082: `self_heal` сначала вышел `improvement`.

    Первая редакция спрашивала «читает ли дверь только вывод пересчёта», и
    собственные файлы статуса двери делали её «улучшением». Мера привязана к
    предмету §21: улучшение — это подъём ОТ НАБЛЮДЕНИЯ СОБЫТИЯ.
    """
    kind, why = cc._raise_purpose(
        ["data/self_heal_status.json", "data/self_heal_revivals.json",
         "paper_trading_status.json", "telegram_bot_capabilities.json"],
        {"red_flags.json": ["security alert"]})
    assert kind == "liveness_repair", why


def test_a_door_reading_an_event_observation_is_improvement():
    kind, why = cc._raise_purpose(
        ["data/apy_ranking.json"], {"apy_ranking.json": ["APY movement"]})
    assert kind == "improvement", why


def test_a_door_with_no_artifact_names_is_unmeasured():
    kind, why = cc._raise_purpose([], {"x.json": ["APY movement"]})
    assert kind == cc.UNMEASURED and why


def test_event_vocabulary_is_shared_between_the_purpose_and_the_event_axis(tmp_path):
    """Словарь «что считается наблюдением события» ОДИН на обе оси.

    Разойдись он — дверь получила бы цель по одному словарю, а событие
    читателя по другому, и две шкалы об одном предмете расползлись бы молча.
    """
    root = _write(tmp_path, _manifest([
        _agent("obs", "interval:300s", "monitoring",
               [("data/apy_ranking.json", 3.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    names = cc.event_artifact_names(manifest)
    assert names.get("apy_ranking.json") == ["APY movement"]
    rows = cc._artifacts_for_event(
        manifest, cc.EVENT_ARTIFACT_FRAGMENTS["APY movement"])
    assert [r["artifact"] for r in rows] == ["data/apy_ranking.json"]


# ---------------------------------------------------------------------------
# (в) События
# ---------------------------------------------------------------------------

def test_no_reader_is_a_measured_zero(tmp_path):
    root = _write(tmp_path, _scene_live())
    manifest, _ = cc.load_manifest(root)
    ev = cc.events(manifest, {"doors": []}, "recalc.daily")
    row = next(r for r in ev["rows"] if r["event"] == "TVL movement")
    assert row["kind"] == "no_reader"
    assert "ИЗМЕРЕННЫЙ ноль" in row["why"]


def test_an_event_observed_only_by_the_recalc_itself_is_not_event_driven(tmp_path):
    """Род `read_at_recalc_tact`: эффективный такт события = такт пересчёта."""
    root = _write(tmp_path, _manifest([
        _agent("recalc.daily", "calendar:08:00", "allocation",
               [("data/allocation_rationale.json", 26.0),
                ("data/tier_curator_report.json", 26.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    ev = cc.events(manifest, {"doors": []}, "recalc.daily")
    row = next(r for r in ev["rows"] if r["event"] == "Tier change")
    assert row["kind"] == "read_at_recalc_tact", row
    assert ev["raises"] == 0


def test_raises_recalc_reports_the_fastest_raising_observation(tmp_path):
    """Печатается ОДНА строка целиком, а не производитель из одной и такт из другой.

    Регрессия цикла #1082: у `security alert` поднятых наблюдений три, и первая
    редакция приписала такт самого частого наблюдателя агенту, работающему раз
    в сутки.
    """
    root = _write(tmp_path, _manifest([
        _agent("slow", "calendar:08:00", "allocation",
               [("data/emergency_status.json", 26.0),
                ("data/allocation_rationale.json", 26.0)]),
        _agent("fast", "interval:300s", "monitoring",
               [("data/peg_report.json", 3.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    doors = {"doors": [{"file": "d.py", "reads": ["emergency_status.json",
                                                  "peg_report.json"],
                        "purpose": "improvement"}]}
    ev = cc.events(manifest, doors, "slow")
    row = next(r for r in ev["rows"] if r["event"] == "security alert")
    assert row["kind"] == "raises_recalc", row
    assert row["fastest_raise_s"] == 300.0
    assert "peg_report" in row["why"] and "fast" in row["why"]
    assert "slow" not in row["why"], "такт одной строки приписан другой"


def test_observed_only_when_nothing_reads_the_observation(tmp_path):
    root = _write(tmp_path, _manifest([
        _agent("obs", "interval:300s", "monitoring",
               [("data/apy_ranking.json", 3.0)]),
        _agent("recalc.daily", "calendar:08:00", "allocation",
               [("data/allocation_rationale.json", 26.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    ev = cc.events(manifest, {"doors": []}, "recalc.daily")
    row = next(r for r in ev["rows"] if r["event"] == "APY movement")
    assert row["kind"] == "observed_only", row


def test_new_capital_is_unreachable_by_construction_not_answered_no(tmp_path):
    """Контрапункт §20: иначе «не поднимает» было бы верно СЛУЧАЙНО."""
    root = _write(tmp_path, _scene_live())
    manifest, _ = cc.load_manifest(root)
    ev = cc.events(manifest, {"doors": []}, "recalc.daily")
    row = next(r for r in ev["rows"] if r["event"] == "new capital")
    assert row["kind"] == "unreachable_by_construction"
    assert "ADR-963" in row["why"]


def test_raises_for_improvement_is_zero_when_the_only_door_is_derisk(tmp_path):
    """Главное число §21 — подъём РАДИ УЛУЧШЕНИЯ, и дерисковый подъём его не даёт.

    Без этого разделения «двое событий поднимают пересчёт» читалось бы как
    частичное исполнение §21, хотя подъём ради снижения риска §21 не заказывал
    (его заказал ADR-070).
    """
    root = _write(tmp_path, _manifest([
        _agent("obs", "interval:300s", "monitoring",
               [("data/red_flags.json", 3.0)]),
        _agent("recalc.daily", "calendar:08:00", "allocation",
               [("data/allocation_rationale.json", 26.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    doors = {"doors": [{"file": "d.py", "reads": ["red_flags.json"],
                        "purpose": "derisk"}]}
    ev = cc.events(manifest, doors, "recalc.daily")
    assert ev["raises"] >= 1
    assert ev["raises_for_improvement"] == 0, ev
    assert ev["improvement_doors"] == []


# ---------------------------------------------------------------------------
# Вердикт
# ---------------------------------------------------------------------------

def test_unmeasured_outranks_a_finding_in_the_verdict():
    """«Не измерено» решается ПЕРВЫМ (инв. #17): это отдельный исход."""
    report = {"vocab_errors": [], "unmeasured": ["что-то"],
              "observation": {"kind": "within_benchmark"},
              "recalculation": {"kind": "coarser_than_benchmark"},
              "coupling": {"kind": "decoupled"},
              "enforcement": {"looser_count": 3},
              "events": {"raises": 0, "declared": 11,
                         "raises_for_improvement": 0}}
    assert cc.verdict_code(report) == 2


def test_a_fully_compliant_scene_gives_zero(tmp_path):
    """Род «§21 исполняется» ДОСТИЖИМ — иначе вердикт 0 был бы мёртвым."""
    root = _write(tmp_path, _manifest([
        _agent("obs", "interval:300s", "monitoring",
               [("data/apy_ranking.json", 0.2)]),
        _agent("recalc", "interval:3600s", "allocation",
               [("data/allocation_rationale.json", 1.0)]),
    ]))
    manifest, _ = cc.load_manifest(root)
    report = {
        "vocab_errors": [], "unmeasured": [],
        "observation": cc.observation_tact(manifest),
        "recalculation": cc.recalculation_tact(manifest),
        "coupling": {"kind": "decoupled"},
        "enforcement": cc.enforcement_spread(manifest),
        "events": {"raises": 10, "declared": 11, "raises_for_improvement": 10},
    }
    assert report["enforcement"]["looser_count"] == 0, report["enforcement"]
    assert cc.verdict_code(report) == 0, (report["observation"]["kind"],
                                          report["recalculation"]["kind"])


def test_live_tree_answers_and_renders(tmp_path):
    """На живом дереве прибор обязан ДОЙТИ до вердикта и отрендериться."""
    root = Path(__file__).resolve().parents[2]
    report = cc.census(root)
    assert report["root"] == str(root)
    assert report["root_defaulted"] is False
    code = cc.verdict_code(report)
    assert code in (0, 1, 2)
    text = cc.render(report)
    assert "§21" in text and "ADVISORY" in text
    assert "ПОДЪЁМ РАДИ УЛУЧШЕНИЯ" in text


def test_default_root_is_printed_as_such():
    report = cc.census(None)
    assert report["root_defaulted"] is True
    assert "УМОЛЧАНИЕ" in cc.render(report)


# ---------------------------------------------------------------------------
# Проба, нашедшая в §20 четыре ошибки замера
# ---------------------------------------------------------------------------

def test_every_declared_kind_is_reachable_by_some_scene(tmp_path):
    """КАЖДЫЙ объявленный род обязан достигаться сценой.

    Род, объявленный в шкале и не достигаемый ничем, есть ровно дефект
    `named_but_unreachable`, найденный §19 у потолка T3 (ADR-962): прибор,
    повторяющий собой находку, хуже отсутствия прибора. Сцены здесь строятся
    так, чтобы каждый род шкалы получил хотя бы одну.
    """
    seen = {"tact": set(), "enforcement": set(), "coupling": set(),
            "event": set(), "purpose": set()}

    # --- TACT_KINDS
    for sched, bench in (("interval:300s", cc.OBSERVATION_BENCHMARK_S),
                         ("interval:1s", cc.OBSERVATION_BENCHMARK_S),
                         ("calendar:08:00", cc.RECALC_BENCHMARK_S),
                         ("daemon", cc.RECALC_BENCHMARK_S)):
        t, why = cc.tact_seconds(sched)
        seen["tact"].add(_tact_kind(t, bench, why))
    seen["tact"].add(cc.UNMEASURED)  # достигается recalculation_tact ниже

    # --- ENFORCEMENT_KINDS
    for tact, enf in ((300.0, 604800.0), (3600.0, 7200.0), (300.0, None),
                      (None, 3600.0)):
        seen["enforcement"].add(cc._enforcement_kind(tact, enf)[0])

    # --- COUPLING_KINDS
    seen["coupling"].add(cc.coupling(cc.load_manifest(_write(
        tmp_path / "c1", _scene_live()))[0])["kind"])
    seen["coupling"].add(cc.coupling(cc.load_manifest(_write(
        tmp_path / "c2", _manifest([
            _agent("both", "interval:300s", "monitoring",
                   [("data/allocation_rationale.json", 26.0)])])))[0])["kind"])
    seen["coupling"].add(cc.coupling(cc.load_manifest(_write(
        tmp_path / "c3", _manifest([
            _agent("obs", "interval:300s", "monitoring")])))[0])["kind"])

    # --- EVENT_KINDS
    m_live = cc.load_manifest(_write(tmp_path / "e1", _scene_live()))[0]
    for row in cc.events(m_live, {"doors": []}, "recalc.daily")["rows"]:
        seen["event"].add(row["kind"])
    m_self = cc.load_manifest(_write(tmp_path / "e2", _manifest([
        _agent("recalc.daily", "calendar:08:00", "allocation",
               [("data/allocation_rationale.json", 26.0),
                ("data/tier_curator_report.json", 26.0)])])))[0]
    for row in cc.events(m_self, {"doors": []}, "recalc.daily")["rows"]:
        seen["event"].add(row["kind"])
    m_raise = cc.load_manifest(_write(tmp_path / "e3", _manifest([
        _agent("obs", "interval:300s", "monitoring",
               [("data/red_flags.json", 3.0)]),
        _agent("recalc.daily", "calendar:08:00", "allocation",
               [("data/allocation_rationale.json", 26.0)])])))[0]
    for row in cc.events(m_raise, {"doors": [
            {"file": "d.py", "reads": ["red_flags.json"],
             "purpose": "derisk"}]}, "recalc.daily")["rows"]:
        seen["event"].add(row["kind"])
    # род `unmeasured` оси событий: событие без объявленного словаря
    saved = cc.EVENT_ARTIFACT_FRAGMENTS.pop("utilization")
    try:
        for row in cc.events(m_live, {"doors": []}, "recalc.daily")["rows"]:
            seen["event"].add(row["kind"])
    finally:
        cc.EVENT_ARTIFACT_FRAGMENTS["utilization"] = saved

    # --- RAISE_PURPOSES
    ev_names = {"red_flags.json": ["security alert"]}
    for reads in ([cc.KILL_SWITCH_ARTIFACT], ["data/other.json"],
                  ["data/red_flags.json"], []):
        seen["purpose"].add(cc._raise_purpose(reads, ev_names)[0])

    missing = {
        "TACT_KINDS": set(cc.TACT_KINDS) - seen["tact"],
        "ENFORCEMENT_KINDS": set(cc.ENFORCEMENT_KINDS) - seen["enforcement"],
        "COUPLING_KINDS": set(cc.COUPLING_KINDS) - seen["coupling"],
        "EVENT_KINDS": set(cc.EVENT_KINDS) - seen["event"],
        "RAISE_PURPOSES": set(cc.RAISE_PURPOSES) - seen["purpose"],
    }
    assert not any(missing.values()), (
        "объявленные роды НЕ ДОСТИГАЮТСЯ ни одной сценой: {}".format(
            {k: sorted(v) for k, v in missing.items() if v}))


def _tact_kind(tact_s, benchmark, why):
    return cc._tact_kind_vs(tact_s, benchmark, why)[0]
