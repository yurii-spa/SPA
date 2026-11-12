"""Тесты §49 ВТОРОЙ осью — свежа ли ПОВЕРХНОСТЬ приёмки (ADR-994, заказ G982 п. 1).

Каждый тест — положительный контроль на замер 2026-11-12 (цикл #1113: все
13 входов сводки старше своего SLO, один производитель на всех и он выключен,
замороженная сводка расходится с живой у трёх критериев) либо на ловушку
третьего исхода (инв. #17). Тест, никогда не видевший настоящей поломки, —
украшение (`.claude/rules/deployment.md`).

Время — ВХОД: `measure(now=...)`; флот — ВХОД (`loaded=`, `fleet_asked=`);
живые строки сводки — ВХОД (`live_rows=`). Живого `launchctl`, живого `data/` и
живой сводки сцены не касаются; реальное дерево судится только там, где предмет
теста — проводка.
"""

# FROZEN-DATE-OK: injected-clock — единственный литерал даты в файле это `NOW`, и
# он уходит аргументом `now=NOW` в `M.measure(...)`/`M.run(...)`; отметки
# артефактов сцены считаются ОТ него (`stamp(hours_ago)`), поэтому обе стороны
# сравнения закреплены и тест бессмертен к календарю. Маркер обязан быть
# КОММЕНТАРИЕМ: храповик ищет `#\s*FROZEN-DATE-OK`.

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from spa_core.monitoring import s49_surface_freshness as M
from spa_core.monitoring import s49_tally_tact as stt

_REPO = Path(__file__).resolve().parents[2]
NOW = dt.datetime(2026, 11, 12, 16, 0, tzinfo=dt.timezone.utc)

CRITERIA = ["Architecture", "Economics", "Persistence", "Costs", "Marginal return",
            "Risk", "Determinism", "Anti-churn", "Pre-trade safety", "Auditability",
            "Owner visibility", "Shadow verification", "No regression"]


def stamp(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


def bound(criterion: str, artifact: str, slo: float) -> dict:
    return {"criterion": criterion, "state": stt.TACT_BOUND, "slo_hours": slo,
            "artifact": artifact, "why": f"вход {artifact} объявлен со сроком {slo:g} ч"}


def manifest_for(rows: list[dict], *, producer: str | None = "com.spa.decision_loop",
                 tally_slo: float | None = 14) -> dict:
    arts = []
    for r in rows:
        if r.get("artifact"):
            entry = {"path": r["artifact"], "status": "active", "slo_hours": r.get("slo_hours")}
            if producer is not None:
                entry["producer"] = producer
            arts.append(entry)
    tally = {"path": M.TALLY_REL, "status": "active", "producer": "com.spa.decision_loop"}
    if tally_slo is not None:
        tally["slo_hours"] = tally_slo
    arts.append(tally)
    return {"artifacts": arts, "agents": []}


def write_artifact(data_dir: Path, artifact: str, *, hours_ago: float | None = 1.0,
                   extra: dict | None = None, raw: str | None = None) -> Path:
    path = M.artifact_path(data_dir, artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return path
    doc = dict(extra or {})
    if hours_ago is not None:
        doc["generated_at"] = stamp(hours_ago)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def frozen_tally(data_dir: Path, rows: list[tuple[str, str]], *, hours_ago: float = 342.0) -> None:
    counts = {v: 0 for v in stt.VERDICT_VOCABULARY}
    for _, v in rows:
        counts[v] += 1
    write_artifact(data_dir, M.TALLY_REL, hours_ago=hours_ago,
                   extra={"status": "OK", "tally": counts,
                          "tally_rows": [{"criterion": c, "probe": "p", "verdict": v}
                                         for c, v in rows]})


def scene(tmp_path: Path, *, ages: dict[str, float] | None = None,
          slo: float = 12.0, tally_rows: list[tuple[str, str]] | None = None,
          tally_age: float = 342.0) -> tuple[Path, list[dict], dict]:
    """Сцена цикла #1113: 13 критериев, один производитель, замороженная сводка."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    rows = [bound(c, f"data/{c.lower().replace(' ', '_')}.json", slo) for c in CRITERIA]
    ages = ages if ages is not None else {c: 342.0 for c in CRITERIA}
    for r in rows:
        if r["criterion"] in ages:
            write_artifact(data, r["artifact"], hours_ago=ages[r["criterion"]])
    if tally_rows is None:
        tally_rows = FROZEN_1113
    frozen_tally(data, tally_rows, hours_ago=tally_age)
    return data, rows, manifest_for(rows)


#: Замороженная сводка прода 29.10 (0 · 11 · 2): не измерены Owner visibility и No regression.
FROZEN_1113 = [(c, stt.UNMEASURED if c in ("Owner visibility", "No regression") else stt.NOT_SATISFIED)
               for c in CRITERIA]

#: Живая сводка 12.11 (1 · 9 · 3).
LIVE_1113 = ([(c, stt.NOT_SATISFIED) for c in CRITERIA if c not in
              ("Determinism", "Owner visibility", "Shadow verification", "No regression")]
             + [("Determinism", stt.UNMEASURED), ("Owner visibility", stt.SATISFIED),
                ("Shadow verification", stt.UNMEASURED), ("No regression", stt.UNMEASURED)])


def live_rows(rows: list[tuple[str, str]]) -> list[dict]:
    return [{"criterion": c, "verdict": v} for c, v in rows]


# ─────────────────────────── 1. свежесть входов ───────────────────────────

class TestInputFreshness:
    def test_age_above_slo_is_stale_and_names_both_numbers(self, tmp_path):
        data, rows, _ = scene(tmp_path, ages={"Economics": 342.1}, slo=12)
        row = next(r for r in M.input_rows(rows, data_dir=data, now=NOW)
                   if r["criterion"] == "Economics")
        assert row["state"] == M.STALE
        assert row["age_hours"] == pytest.approx(342.1, abs=0.01)
        assert "342.1" in row["why"] and "12" in row["why"]

    def test_age_equal_to_slo_is_still_fresh(self, tmp_path):
        """Срок — предел включительно: «не старше SLO» и есть свежий."""
        data, rows, _ = scene(tmp_path, ages={"Costs": 12.0}, slo=12)
        row = next(r for r in M.input_rows(rows, data_dir=data, now=NOW) if r["criterion"] == "Costs")
        assert row["state"] == M.FRESH

    def test_auditability_live_control_10_3h_over_9_28(self, tmp_path):
        """Замер 12.11: единственный «почти свежий» вход тоже старше своего срока."""
        data = tmp_path / "data"
        data.mkdir()
        rows = [bound("Auditability", "data/decision_audit_trail.json", 9.28)]
        write_artifact(data, "data/decision_audit_trail.json", hours_ago=10.3)
        row = M.input_rows(rows, data_dir=data, now=NOW)[0]
        assert row["state"] == M.STALE

    def test_missing_file_is_absent_not_stale(self, tmp_path):
        data, rows, _ = scene(tmp_path, ages={})
        states = {r["criterion"]: r["state"] for r in M.input_rows(rows, data_dir=data, now=NOW)}
        assert set(states.values()) == {M.ABSENT}

    def test_file_without_clock_is_no_clock_not_fresh(self, tmp_path):
        data, rows, _ = scene(tmp_path, ages={})
        write_artifact(data, rows[0]["artifact"], hours_ago=None, extra={"status": "OK"})
        row = M.input_rows(rows[:1], data_dir=data, now=NOW)[0]
        assert row["state"] == M.NO_CLOCK
        assert row["age_hours"] is None

    def test_unparsable_clock_is_no_clock(self, tmp_path):
        data, rows, _ = scene(tmp_path, ages={})
        write_artifact(data, rows[0]["artifact"], hours_ago=None,
                       extra={"generated_at": "вчера"})
        assert M.input_rows(rows[:1], data_dir=data, now=NOW)[0]["state"] == M.NO_CLOCK

    def test_unreadable_json_is_absent_with_the_reason(self, tmp_path):
        data, rows, _ = scene(tmp_path, ages={})
        write_artifact(data, rows[0]["artifact"], raw="{не json")
        row = M.input_rows(rows[:1], data_dir=data, now=NOW)[0]
        assert row["state"] == M.ABSENT
        assert "не прочитан" in row["why"]

    def test_unbound_row_is_unbound_not_absent(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        rows = [{"criterion": "Forecast accuracy", "state": stt.TACT_UNBOUND,
                 "slo_hours": None, "artifact": None, "why": "мерой не объявлен ни один артефакт"}]
        row = M.input_rows(rows, data_dir=data, now=NOW)[0]
        assert row["state"] == M.UNBOUND
        assert "мерой не объявлен" in row["why"]

    def test_bound_without_slo_is_unbound(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        rows = [{"criterion": "X", "state": stt.TACT_BOUND_WITHOUT_SLO, "slo_hours": None,
                 "artifact": "data/x.json", "why": "slo_hours не объявлен"}]
        write_artifact(data, "data/x.json", hours_ago=1)
        assert M.input_rows(rows, data_dir=data, now=NOW)[0]["state"] == M.UNBOUND

    def test_nested_artifact_path_keeps_its_subdirectory(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        rows = [bound("X", "data/investment_os/outcomes.json", 31)]
        write_artifact(data, "data/investment_os/outcomes.json", hours_ago=1)
        assert M.input_rows(rows, data_dir=data, now=NOW)[0]["state"] == M.FRESH
        assert M.artifact_path(data, "data/a/b.json") == data / "a" / "b.json"

    def test_input_counts_cover_every_state(self):
        rows = [{"state": s} for s in M.INPUT_STATES] + [{"state": M.STALE}]
        counts = M.input_counts(rows)
        assert counts[M.STALE] == 2
        assert set(counts) == set(M.INPUT_STATES)


# ─────────────────────────── 2. производители и флот ───────────────────────────

class TestProducers:
    def test_one_dead_producer_holds_all_thirteen(self, tmp_path):
        data, rows, man = scene(tmp_path)
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        prod = M.producer_rows(inputs, manifest=man, loaded={"com.spa.other"}, now=NOW)
        assert len(prod) == 1
        assert prod[0]["producer"] == "com.spa.decision_loop"
        assert prod[0]["state"] == M.NOT_LOADED
        assert prod[0]["criteria_count"] == 13 and prod[0]["stale_count"] == 13

    def test_loaded_producer_is_loaded(self, tmp_path):
        data, rows, man = scene(tmp_path)
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        prod = M.producer_rows(inputs, manifest=man, loaded={"com.spa.decision_loop"}, now=NOW)
        assert prod[0]["state"] == M.LOADED

    def test_fleet_not_asked_is_unmeasured_not_dead(self, tmp_path):
        data, rows, man = scene(tmp_path)
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        prod = M.producer_rows(inputs, manifest=man, loaded=None, now=NOW)
        assert prod[0]["state"] == M.FLEET_UNMEASURED

    def test_unknown_producer_is_named_unknown(self, tmp_path):
        data, rows, _ = scene(tmp_path)
        man = manifest_for(rows, producer=None)
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        prod = M.producer_rows(inputs, manifest=man, loaded=set(), now=NOW)
        assert prod[0]["state"] == M.PRODUCER_UNKNOWN

    def test_silence_is_the_newest_artifact_and_it_is_named(self, tmp_path):
        """Замер 12.11: входы 342 ч, но один из них 10,3 ч — молчание 10,3, и файл назван."""
        ages = {c: 342.0 for c in CRITERIA}
        ages["Auditability"] = 10.3
        data, rows, man = scene(tmp_path, ages=ages)
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        prod = M.producer_rows(inputs, manifest=man, loaded=set(), now=NOW)[0]
        assert prod["silent_hours"] == pytest.approx(10.3, abs=0.01)
        assert prod["last_seen_artifact"] == "data/auditability.json"

    def test_silence_without_any_clock_is_none(self, tmp_path):
        data, rows, man = scene(tmp_path, ages={})
        for r in rows:
            write_artifact(data, r["artifact"], hours_ago=None, extra={})
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        prod = M.producer_rows(inputs, manifest=man, loaded=set(), now=NOW)[0]
        assert prod["silent_hours"] is None and prod["last_seen"] is None

    def test_unbound_rows_do_not_invent_a_producer(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        rows = [{"criterion": "X", "state": stt.TACT_UNBOUND, "slo_hours": None,
                 "artifact": None, "why": "нет"}]
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        assert M.producer_rows(inputs, manifest={"artifacts": []}, loaded=set(), now=NOW) == []

    def test_two_producers_are_two_rows(self, tmp_path):
        data, rows, _ = scene(tmp_path)
        man = manifest_for(rows)
        man["artifacts"][0]["producer"] = "com.spa.daily_cycle"
        inputs = M.input_rows(rows, data_dir=data, now=NOW)
        prod = M.producer_rows(inputs, manifest=man, loaded=set(), now=NOW)
        assert [p["producer"] for p in prod] == ["com.spa.daily_cycle", "com.spa.decision_loop"]
        assert prod[0]["criteria_count"] == 1 and prod[1]["criteria_count"] == 12


class TestFleetDoor:
    def test_launchctl_lines_become_labels(self):
        def runner(*_a, **_k):
            return subprocess.CompletedProcess([], 0, stdout="PID\tStatus\tLabel\n-\t0\tcom.spa.a\n123\t0\tcom.spa.b\n", stderr="")
        assert M.fleet_loaded(runner) == {"com.spa.a", "com.spa.b"}

    def test_failed_launchctl_is_none_not_empty(self):
        def runner(*_a, **_k):
            return subprocess.CompletedProcess([], 1, stdout="", stderr="boom")
        assert M.fleet_loaded(runner) is None

    def test_missing_launchctl_is_none(self):
        def runner(*_a, **_k):
            raise OSError("no launchctl")
        assert M.fleet_loaded(runner) is None


# ─────────────────────────── 3. сводка: замороженная против живой ───────────────────────────

class TestTally:
    def test_frozen_tally_342h_over_14_is_stale_with_counts(self, tmp_path):
        data, _, man = scene(tmp_path)
        t = M.tally_state(data, manifest=man, now=NOW)
        assert t["state"] == M.STALE
        assert t["counts"] == {stt.SATISFIED: 0, stt.NOT_SATISFIED: 11, stt.UNMEASURED: 2}
        assert len(t["rows"]) == 13
        assert "342.0" in t["why"] and "14" in t["why"]

    def test_fresh_tally(self, tmp_path):
        data, _, man = scene(tmp_path, tally_age=1.0)
        assert M.tally_state(data, manifest=man, now=NOW)["state"] == M.FRESH

    def test_absent_tally(self, tmp_path):
        data, _, man = scene(tmp_path)
        M.artifact_path(data, M.TALLY_REL).unlink()
        t = M.tally_state(data, manifest=man, now=NOW)
        assert t["state"] == M.ABSENT and t["counts"] is None and t["rows"] == []

    def test_tally_without_clock(self, tmp_path):
        data, _, man = scene(tmp_path)
        write_artifact(data, M.TALLY_REL, hours_ago=None, extra={"tally": {}})
        assert M.tally_state(data, manifest=man, now=NOW)["state"] == M.NO_CLOCK

    def test_tally_without_declared_slo_is_unbound(self, tmp_path):
        data, rows, _ = scene(tmp_path)
        man = manifest_for(rows, tally_slo=None)
        t = M.tally_state(data, manifest=man, now=NOW)
        assert t["state"] == M.UNBOUND and t["age_hours"] == pytest.approx(342.0, abs=0.01)


class TestDrift:
    def test_no_live_rows_is_unchecked_not_zero(self):
        d = M.drift([{"criterion": "A", "verdict": stt.SATISFIED}], None)
        assert d["verdict"] == M.DRIFT_UNCHECKED
        assert d["live_counts"] is None and d["rows"] == []

    def test_identical_rows_have_no_drift(self):
        rows = live_rows(LIVE_1113)
        d = M.drift(rows, rows)
        assert d["verdict"] == M.DRIFT_MEASURED and d["rows"] == [] and d["changed"] == 0

    def test_live_control_1113_three_criteria_changed(self):
        d = M.drift(live_rows(FROZEN_1113), live_rows(LIVE_1113))
        changed = {r["criterion"]: (r["frozen"], r["live"]) for r in d["rows"]}
        assert changed == {
            "Determinism": (stt.NOT_SATISFIED, stt.UNMEASURED),
            "Owner visibility": (stt.UNMEASURED, stt.SATISFIED),
            "Shadow verification": (stt.NOT_SATISFIED, stt.UNMEASURED),
        }
        assert d["changed"] == 3
        assert d["frozen_counts"] == {stt.SATISFIED: 0, stt.NOT_SATISFIED: 11, stt.UNMEASURED: 2}
        assert d["live_counts"] == {stt.SATISFIED: 1, stt.NOT_SATISFIED: 9, stt.UNMEASURED: 3}

    def test_criterion_missing_on_one_side_is_a_missing_row(self):
        d = M.drift([{"criterion": "A", "verdict": stt.SATISFIED}],
                    [{"criterion": "A", "verdict": stt.SATISFIED},
                     {"criterion": "B", "verdict": stt.UNMEASURED}])
        assert [r["kind"] for r in d["rows"]] == ["missing"]
        assert d["changed"] == 0

    def test_live_rows_from_rollup_requires_rows(self):
        with pytest.raises(M.Unmeasured):
            M.live_rows_from_rollup({"population": 13})
        assert M.live_rows_from_rollup({"rows": [{"criterion": "A", "verdict": "x", "detail": 1}]}) \
            == [{"criterion": "A", "verdict": "x"}]


# ─────────────────────────── 4. находки и сводный вердикт ───────────────────────────

class TestFindings:
    def test_live_control_1113_is_critical_and_names_the_producer(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set(), live_rows=live_rows(LIVE_1113))
        assert doc["overall"] == M.OVERALL_CRITICAL
        crit = [f for f in doc["findings"] if f["severity"] == "critical"]
        assert len(crit) == 1 and crit[0]["key"] == "surface_frozen"
        assert "13 из 13" in crit[0]["text"] and "com.spa.decision_loop" in crit[0]["text"]
        assert doc["counts"] == {"critical": 1, "warn": 2, "info": 1, "unchecked": 0}
        keys = {f["key"] for f in doc["findings"]}
        assert {"surface_frozen", "single_producer", "tally_stale", "tally_drift"} == keys

    def test_stale_inputs_with_a_loaded_producer_is_warn_not_critical(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded={"com.spa.decision_loop"},
                        live_rows=live_rows(LIVE_1113))
        assert doc["overall"] == M.OVERALL_WARN
        assert any(f["key"] == "inputs_stale" for f in doc["findings"])
        assert not any(f["severity"] == "critical" for f in doc["findings"])

    def test_fleet_unmeasured_is_an_unchecked_finding(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=None, fleet_asked=True,
                        live_rows=live_rows(LIVE_1113))
        assert doc["fleet_measured"] is False
        assert any(f["key"] == "fleet_unmeasured" and f["severity"] == "unchecked"
                   for f in doc["findings"])
        assert not any(f["key"] == "surface_frozen" for f in doc["findings"])

    def test_fresh_surface_is_ok(self, tmp_path):
        ages = {c: 1.0 for c in CRITERIA}
        data, rows, man = scene(tmp_path, ages=ages, tally_age=1.0)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded={"com.spa.decision_loop"},
                        live_rows=live_rows(FROZEN_1113))
        assert doc["overall"] == M.OVERALL_OK
        assert {f["key"] for f in doc["findings"]} == {"single_producer", "tally_same"}

    def test_drift_unchecked_alone_makes_overall_unchecked(self, tmp_path):
        ages = {c: 1.0 for c in CRITERIA}
        data, rows, man = scene(tmp_path, ages=ages, tally_age=1.0)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded={"com.spa.decision_loop"})
        assert doc["overall"] == M.OVERALL_UNCHECKED
        assert doc["drift"]["verdict"] == M.DRIFT_UNCHECKED

    def test_tally_stale_finding_quotes_what_the_reader_sees(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set(), live_rows=live_rows(LIVE_1113))
        f = next(f for f in doc["findings"] if f["key"] == "tally_stale")
        assert "ВЫПОЛНЕНО 0 · НЕ ВЫПОЛНЕНО 11 · НЕ ИЗМЕРЕНО 2" in f["text"]

    def test_drift_finding_names_criteria_and_both_counts(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set(), live_rows=live_rows(LIVE_1113))
        f = next(f for f in doc["findings"] if f["key"] == "tally_drift")
        assert "Owner visibility: unmeasured → satisfied" in f["text"]
        assert "0·11·2" in f["text"] and "1·9·3" in f["text"]

    def test_absent_and_no_clock_inputs_are_separate_findings(self, tmp_path):
        data, rows, man = scene(tmp_path, ages={"Economics": 1.0})
        write_artifact(data, rows[0]["artifact"], hours_ago=None, extra={})
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set(), live_rows=live_rows(LIVE_1113))
        keys = {f["key"] for f in doc["findings"]}
        assert {"inputs_absent", "inputs_no_clock"} <= keys
        assert "surface_frozen" not in keys

    def test_single_producer_info_needs_more_than_one_input(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        rows = [bound("A", "data/a.json", 9)]
        write_artifact(data, "data/a.json", hours_ago=1)
        man = manifest_for(rows)
        frozen_tally(data, [("A", stt.SATISFIED)], hours_ago=1)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=["A"], tact_rows=rows,
                        manifest=man, loaded={"com.spa.decision_loop"},
                        live_rows=live_rows([("A", stt.SATISFIED)]))
        assert not any(f["key"] == "single_producer" for f in doc["findings"])


# ─────────────────────────── 5. measure/run — входы и отказы ───────────────────────────

class TestMeasureAndRun:
    def test_now_is_an_input(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set())
        assert doc["generated_at"] == NOW.isoformat()
        assert doc["schema"] == M.SCHEMA and doc["adr"] == "ADR-994"

    def test_empty_population_is_unmeasured(self, tmp_path):
        with pytest.raises(M.Unmeasured):
            M.measure(tmp_path, data_dir=tmp_path, now=NOW, criteria=[], tact_rows=[],
                      manifest={"artifacts": []}, loaded=set())

    def test_missing_constitution_is_unmeasured(self, tmp_path):
        with pytest.raises(M.Unmeasured) as exc:
            M.measure(tmp_path, data_dir=tmp_path, now=NOW, criteria=CRITERIA, loaded=set())
        assert "конституция" in str(exc.value)

    def test_run_writes_the_artifact_atomically(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.run(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                    manifest=man, loaded=set())
        on_disk = json.loads((tmp_path / M.REPORT_REL).read_text(encoding="utf-8"))
        assert on_disk["generated_at"] == doc["generated_at"]
        assert on_disk["overall"] == doc["overall"]

    def test_run_without_write_leaves_no_artifact(self, tmp_path):
        data, rows, man = scene(tmp_path)
        M.run(tmp_path, data_dir=data, now=NOW, write=False, criteria=CRITERIA, tact_rows=rows,
              manifest=man, loaded=set())
        assert not (tmp_path / M.REPORT_REL).exists()

    def test_rollup_json_feeds_the_drift_axis(self, tmp_path):
        data, rows, man = scene(tmp_path)
        rj = tmp_path / "rollup.json"
        rj.write_text(json.dumps({"rows": [{"criterion": c, "verdict": v, "detail": "x"}
                                           for c, v in LIVE_1113]}), encoding="utf-8")
        doc = M.run(tmp_path, data_dir=data, now=NOW, write=False, rollup_json=rj,
                    criteria=CRITERIA, tact_rows=rows, manifest=man, loaded=set())
        assert doc["drift"]["verdict"] == M.DRIFT_MEASURED and doc["drift"]["changed"] == 3

    def test_missing_rollup_json_is_unmeasured(self, tmp_path):
        data, rows, man = scene(tmp_path)
        with pytest.raises(M.Unmeasured):
            M.run(tmp_path, data_dir=data, now=NOW, write=False, rollup_json=tmp_path / "нет.json",
                  criteria=CRITERIA, tact_rows=rows, manifest=man, loaded=set())

    def test_main_returns_2_when_unmeasured(self, tmp_path, capsys):
        rc = M.main(["--root", str(tmp_path), "--data-dir", str(tmp_path), "--no-write"])
        assert rc == 2
        assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err

    def test_main_returns_1_on_findings_and_prints_json(self, tmp_path, capsys, monkeypatch):
        data, rows, man = scene(tmp_path)
        monkeypatch.setattr(M, "measure", lambda *a, **k: {
            "overall": M.OVERALL_CRITICAL, "counts": {"critical": 1, "warn": 0, "info": 0,
                                                       "unchecked": 0}})
        rc = M.main(["--root", str(tmp_path), "--data-dir", str(data), "--no-write", "--json"])
        assert rc == 1
        assert json.loads(capsys.readouterr().out)["overall"] == M.OVERALL_CRITICAL


# ─────────────────────────── 6. отрисовка ───────────────────────────

class TestReport:
    def test_format_report_names_the_adr_and_delegates(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set(), live_rows=live_rows(LIVE_1113))
        lines = M.format_report(doc)
        assert "ADR-994" in lines[0]
        assert len(lines) == len(M.report(doc)) + 1
        text = "\n".join(lines)
        assert "протухших 13" in text and "[not_loaded] com.spa.decision_loop" in text
        assert "расхождений 3" in text

    def test_the_blindness_is_named_in_the_report_itself(self, tmp_path):
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set())
        text = "\n".join(M.report(doc))
        assert "НЕ ДОКЛАДЫВАЕТ" in text and "ADVISORY" in text
        assert "живая против замороженной: НЕ ИЗМЕРЕНО" in text

    def test_missing_counters_print_unmeasured_not_none(self):
        lines = M.report({"overall": None})
        assert "НЕ ИЗМЕРЕНО" in lines[0] and "None" not in lines[0]
        assert "НЕ ИЗМЕРЕНО" in lines[1]


# ─────────────────────────── 7. проводка и живая конституция ───────────────────────────

class TestWiring:
    """Написать прибор и не позвать его — то же, что не написать."""

    def test_the_real_constitution_binds_all_thirteen(self):
        """Живой контроль: привязки соседа дают 13 bound строк — дверь не выдумана."""
        rows = stt.tact_floor(CRITERIA, repo_root=str(_REPO))["rows"]
        assert [r["state"] for r in rows] == [stt.TACT_BOUND] * 13
        assert all(r["artifact"].startswith("data/") for r in rows)

    def test_the_real_constitution_names_one_producer_for_all(self):
        from spa_core.monitoring import s49_criterion_price as price_meter
        man = price_meter.read_manifest(str(_REPO))
        rows = stt.tact_floor(CRITERIA, repo_root=str(_REPO))["rows"]
        producers = {M.producer_of(man, r["artifact"]) for r in rows}
        assert producers == {"com.spa.decision_loop"}

    def test_the_stage_is_declared_in_the_bridge_composition(self):
        from spa_core.monitoring import findings_bridge as fb
        assert "s49_surface_freshness" in fb.CENSUS_STAGE
        assert fb.CENSUS_PRODUCT["s49_surface_freshness"] == {
            "module": "spa_core/monitoring/s49_surface_freshness.py",
            "artifact": "data/s49_surface_freshness.json"}
        assert "data/s49_surface_freshness.json" in fb.PRODUCES

    def test_the_bridge_main_actually_calls_the_stage(self):
        source = (_REPO / "spa_core" / "monitoring" / "findings_bridge.py").read_text(encoding="utf-8")
        assert "s49_surface_freshness.run(root=args.root)" in source
        assert 'census_skipped(_skipped, "s49_surface_freshness", e)' in source

    def test_the_artifact_is_declared_in_the_manifest_with_a_producer_and_an_slo(self):
        man = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        entry = next(a for a in man["artifacts"] if a.get("path") == M.REPORT_REL)
        assert entry["producer"] == "com.spa.decision_loop"
        assert entry["status"] == "active"
        assert entry["slo_hours"] == 14
        agent = next(a for a in man["agents"] if a.get("label") == "com.spa.decision_loop")
        assert {"artifact": M.REPORT_REL, "slo_hours": 14} in agent["produces"]

    def test_the_office_step_has_a_NAMED_branch_for_the_artifact(self):
        source = (_REPO / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        assert 'elif name == "s49_surface_freshness.json":' in source
        assert "from spa_core.monitoring.s49_surface_freshness import format_report" in source
        assert '"s49_surface_freshness.json": ("schema", "overall"' in source

    def test_the_office_branch_prints_the_producer_report(self, tmp_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "consume_office_reports_under_test", _REPO / "scripts" / "consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        data, rows, man = scene(tmp_path)
        doc = M.measure(tmp_path, data_dir=data, now=NOW, criteria=CRITERIA, tact_rows=rows,
                        manifest=man, loaded=set(), live_rows=live_rows(LIVE_1113))
        out = "\n".join(str(x) for x in mod._summarize_json(
            "data/s49_surface_freshness.json", doc, now=NOW, root=str(_REPO)))
        assert "ADR-994" in out and "протухших 13" in out
