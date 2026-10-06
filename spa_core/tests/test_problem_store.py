"""Тесты C6 Problem-store (ADR-580 §C6, REVIEW_1 amendment).

Положительные контроли — каждый воспроизводит конкретный отказ из задания RM-TRUTH-01
workstream C6 / A4_reliability.md §2:

  (a) один агент падает повторно 5 прогонов подряд ⇒ РОВНО одна Problem, РОВНО одна
      карточка, occurrences=5 (замер A4: 7 «bootstrap failed» за 35 минут слали 7 алертов);
  (b) один CRIT внутри иначе зелёного флота ОСТАЁТСЯ видимым (не теряется под агрегатом);
  (c) закрытие БЕЗ RCA даёт MITIGATED, НИКОГДА CLOSED (буквальная формулировка REVIEW_1);
  (d) нечитаемый источник ⇒ НЕ ИЗМЕРЕНО, Problem не закрывается автоматически (инвариант #17).

Плюс контроль наоборот (ADR-333): проба/поиск по id — точным совпадением, не подстрокой.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import problem_store as ps

# FROZEN-DATE-OK: injected-clock — every staleness/window/occurrence decision in
# problem_store (`collect`, `run_once`, `_prune_window`, `record_rca`) is driven by
# the `now=` parameter, and every call below passes T0 (or T0 + a timedelta) for it.
# The `"timestamp"` field inside the `_agent_health*` fixture dicts is the SAME
# literal written as a plain string (not derived from T0 in code) but is never
# read by problem_store for any freshness comparison — only agent_health_monitor's
# format_alert reads that field, to re-render it as display text, a path this file
# does not exercise. No calendar move can flip this file's verdict.
T0 = datetime(2026, 10, 5, 8, 0, 0, tzinfo=timezone.utc)


def _agent_health(label: str, status: str, issue: str, *, others_ok: int = 3) -> dict:
    agents = [{"label": label, "status": status, "pid": 0, "last_exit": 0,
              "log_age_min": 0.0, "category": "daily", "loaded": True, "issue": issue}]
    for i in range(others_ok):
        agents.append({"label": f"com.spa.ok{i}", "status": "OK", "pid": 0, "last_exit": 0,
                       "log_age_min": 0.0, "category": "daily", "loaded": True, "issue": ""})
    return {"timestamp": "2026-10-05T08:00:00+00:00", "overall_status": status,
            "agents": agents, "system_issues": []}


def _write(data_dir: Path, name: str, doc: dict) -> None:
    (data_dir / name).write_text(json.dumps(doc), encoding="utf-8")


# ── (a) 5 повторов одного агента ⇒ одна Problem, одна карточка, occurrences=5 ──

def test_repeated_failure_opens_exactly_one_problem_and_one_card(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    tracker_dir = tmp_path / "tracker"
    doc = _agent_health("com.spa.novel_edge_rnd", "CRITICAL", "last_exit=124")
    _write(data_dir, "agent_health.json", doc)

    total_cards = 0
    for i in range(5):
        report = ps.run_once(data_dir, now=T0 + timedelta(hours=i), tracker_dir=tracker_dir)
        assert "error" not in report
        total_cards += len(report["cards_created"])

    store = ps.load_store(data_dir)
    key = ps.problem_key("com.spa.novel_edge_rnd", "exit_nonzero:124")
    entry = store["problems"][key]
    assert entry["occurrences"] == 5
    assert entry["status"] == ps.STATUS_OPEN
    assert total_cards == 1
    assert entry["card_path"] is not None
    assert len(list(tracker_dir.glob("agent-task-*.md"))) == 1


def test_first_sighting_alone_does_not_open_a_problem(tmp_path):
    """Ниже порога (OPEN_THRESHOLD=2) — INCIDENT, карточки ещё нет (иначе любой одиночный
    блип плодил бы карточку, тот же класс шума, против которого написан C6)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write(data_dir, "agent_health.json",
          _agent_health("com.spa.x", "WARNING", "last_exit=1"))
    report = ps.run_once(data_dir, now=T0, tracker_dir=tmp_path / "tracker")
    assert report["cards_created"] == []
    store = ps.load_store(data_dir)
    key = ps.problem_key("com.spa.x", "exit_nonzero:1")
    assert store["problems"][key]["status"] == ps.STATUS_INCIDENT
    assert store["problems"][key]["occurrences"] == 1


# ── (b) один CRIT в зелёном флоте остаётся видимым ──────────────────────────

def test_single_critical_in_an_otherwise_green_fleet_is_not_lost(tmp_path):
    doc = _agent_health("com.spa.lonely", "CRITICAL", "log stale 3.2d (>2.2d)", others_ok=50)
    data_dir = tmp_path
    _write(data_dir, "agent_health.json", doc)
    conditions, source_status = ps.collect(data_dir, now=T0)
    assert source_status[ps.SOURCE_AGENT_HEALTH]["status"] == "measured"
    matches = [c for c in conditions if c["agent"] == "com.spa.lonely"]
    assert len(matches) == 1
    assert matches[0]["cause_code"] == "stale_log"
    # the 50 healthy agents must not drown the one critical condition.
    assert len(conditions) == 1


# ── (c) закрытие БЕЗ RCA ⇒ MITIGATED, никогда CLOSED ────────────────────────

def test_closing_without_rca_gives_mitigated_not_closed(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    doc = _agent_health("com.spa.y", "CRITICAL", "last_exit=1")
    _write(data_dir, "agent_health.json", doc)

    # two sightings -> OPEN
    ps.run_once(data_dir, now=T0, tracker_dir=tmp_path / "tracker")
    ps.run_once(data_dir, now=T0 + timedelta(hours=1), tracker_dir=tmp_path / "tracker")
    store = ps.load_store(data_dir)
    key = ps.problem_key("com.spa.y", "exit_nonzero:1")
    assert store["problems"][key]["status"] == ps.STATUS_OPEN

    # condition clears (agent now OK) — no RCA recorded.
    _write(data_dir, "agent_health.json",
          _agent_health("com.spa.y", "OK", ""))
    for i in range(2, 6):
        ps.run_once(data_dir, now=T0 + timedelta(hours=i), tracker_dir=tmp_path / "tracker")
        store = ps.load_store(data_dir)
        # Even after MANY consecutive clean runs, without an RCA it never reaches CLOSED.
        assert store["problems"][key]["status"] == ps.STATUS_MITIGATED, (
            f"run {i}: {store['problems'][key]['status']}")


def test_closing_with_rca_and_absence_streak_reaches_closed(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    doc = _agent_health("com.spa.z", "CRITICAL", "last_exit=1")
    _write(data_dir, "agent_health.json", doc)
    ps.run_once(data_dir, now=T0, tracker_dir=tmp_path / "tracker")
    ps.run_once(data_dir, now=T0 + timedelta(hours=1), tracker_dir=tmp_path / "tracker")

    pid = ps.problem_id("com.spa.z", "exit_nonzero:1")
    ps.record_rca(data_dir, problem_id=pid, cause="disk full", fix_ref="PR#1",
                 regression_test="test_z_disk_full")

    _write(data_dir, "agent_health.json", _agent_health("com.spa.z", "OK", ""))
    key = ps.problem_key("com.spa.z", "exit_nonzero:1")
    # CLOSE_ABSENT_STREAK default = 2 clean runs after RCA.
    ps.run_once(data_dir, now=T0 + timedelta(hours=2), tracker_dir=tmp_path / "tracker")
    store = ps.load_store(data_dir)
    assert store["problems"][key]["status"] == ps.STATUS_OPEN  # 1st clean run — not yet enough
    ps.run_once(data_dir, now=T0 + timedelta(hours=3), tracker_dir=tmp_path / "tracker")
    store = ps.load_store(data_dir)
    assert store["problems"][key]["status"] == ps.STATUS_CLOSED


def test_record_rca_refuses_an_unopened_problem(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    ps.save_store(data_dir, {"problems": {}})
    with pytest.raises(KeyError):
        ps.record_rca(data_dir, problem_id="nope", cause="x")


# ── (d) нечитаемый источник ⇒ НЕ ИЗМЕРЕНО, Problem не закрывается ───────────

def test_unreadable_agent_health_is_not_measured_and_does_not_close_the_problem(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    doc = _agent_health("com.spa.w", "CRITICAL", "last_exit=1")
    _write(data_dir, "agent_health.json", doc)
    ps.run_once(data_dir, now=T0, tracker_dir=tmp_path / "tracker")
    ps.run_once(data_dir, now=T0 + timedelta(hours=1), tracker_dir=tmp_path / "tracker")
    key = ps.problem_key("com.spa.w", "exit_nonzero:1")
    store = ps.load_store(data_dir)
    assert store["problems"][key]["status"] == ps.STATUS_OPEN
    before = dict(store["problems"][key])

    # agent_health.json становится НЕЧИТАЕМЫМ (corrupt), не исчезает и не "чист".
    (data_dir / "agent_health.json").write_text("{not json", encoding="utf-8")
    report = ps.run_once(data_dir, now=T0 + timedelta(hours=2), tracker_dir=tmp_path / "tracker")
    assert report["sources"][ps.SOURCE_AGENT_HEALTH]["status"] == "not_measured"
    store = ps.load_store(data_dir)
    after = store["problems"][key]
    # Статус/occurrences/consecutive_absences НЕ ДОЛЖНЫ измениться — "не измерено"
    # никогда не читается как "условия больше нет".
    assert after["status"] == ps.STATUS_OPEN
    assert after["occurrences"] == before["occurrences"]
    assert after["consecutive_absences"] == before["consecutive_absences"]


def test_missing_agent_health_file_is_not_measured_not_a_clean_zero(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conditions, source_status = ps.collect(data_dir, now=T0)
    assert conditions == []
    assert source_status[ps.SOURCE_AGENT_HEALTH]["status"] == "not_measured"
    assert source_status[ps.SOURCE_AGENT_HEALTH]["reason"]


# ── источники, помимо agent_health ───────────────────────────────────────────

def test_system_health_domain_warning_becomes_a_condition(tmp_path):
    data_dir = tmp_path
    _write(data_dir, "system_health.json", {
        "overall_status": "WARNING",
        "domains": {"d5_code_integrity": {"status": "WARNING", "ms": 1},
                   "d4_external": {"status": "OK", "ms": 1}},
    })
    conditions, _ = ps.collect(data_dir, now=T0)
    assert conditions == [{"agent": "system_health", "cause_code": "domains_degraded",
                           "severity": "WARNING", "detail": "домены: d5_code_integrity WARNING",
                           "source": ps.SOURCE_SYSTEM_HEALTH}]


def test_seven_degraded_domains_are_ONE_root_cause_not_seven_problems(tmp_path):
    """Поправка владельца к Wave 0 (RM-TRUTH-01): замер на копии прода 05.10 открыл бы семь
    Problem на один вердикт system_health. Семь доменов ⇒ ОДНА причина; тяжесть — худшая."""
    doms = {f"d{i}_x": {"status": "WARNING"} for i in range(1, 7)}
    doms["d7_hygiene"] = {"status": "CRITICAL"}
    _write(tmp_path, "system_health.json", {"domains": doms})
    conditions, _ = ps.collect(tmp_path, now=T0)
    assert len(conditions) == 1
    assert conditions[0]["cause_code"] == "domains_degraded"
    assert conditions[0]["severity"] == "CRITICAL"
    assert "d7_hygiene CRITICAL" in conditions[0]["detail"]


# ── F10 (ADR-580 §C6 REVIEW_1): retired-but-loaded — ONE root, not N+1 Problems ──

def _agent_health_with_retired(*, per_agent_labels=(), fleet_issue=None, others_ok=2):
    agents = []
    for label in per_agent_labels:
        agents.append({
            "label": label, "status": "WARNING", "pid": 123, "last_exit": 1,
            "log_age_min": 0.0, "category": "on_demand", "loaded": True,
            "issue": ("retired_but_loaded — label is in RETIRED_LABELS but launchctl "
                      f"still has it loaded (owner: launchctl bootout gui/$(id -u)/{label})"),
        })
    for i in range(others_ok):
        agents.append({"label": f"com.spa.ok{i}", "status": "OK", "pid": 0, "last_exit": 0,
                       "log_age_min": 0.0, "category": "daily", "loaded": True, "issue": ""})
    doc = {"timestamp": "2026-10-05T08:00:00+00:00", "overall_status": "WARNING",
           "agents": agents, "system_issues": []}
    if fleet_issue:
        doc["system_issues"] = [fleet_issue]
    return doc


def test_three_retired_but_loaded_agents_plus_fleet_drift_is_ONE_problem(tmp_path):
    """Положительный контроль F10: замер REVIEW_1 — 3 per-agent WARNING
    (digest_weekly/tier1_digest/weekly_backup) + 1 системная строка fleet parity
    DRIFT о том же факте. До фикса это было 4 Problem; должна остаться ОДНА."""
    doc = _agent_health_with_retired(
        per_agent_labels=["com.spa.digest_weekly", "com.spa.tier1_digest",
                          "com.spa.weekly_backup"],
        fleet_issue="fleet parity DRIFT (3 retired-still-installed)")
    conditions = ps._conditions_from_agent_health(doc)
    retired = [c for c in conditions if c["cause_code"] == "retired_but_loaded"]
    assert len(retired) == 1, f"ожидалась ОДНА запись retired_but_loaded, получено {len(retired)}"
    assert retired[0]["agent"] == "fleet"
    for label in ("com.spa.digest_weekly", "com.spa.tier1_digest", "com.spa.weekly_backup"):
        assert label in retired[0]["detail"], "агент обязан быть назван поимённо в detail"
    assert "fleet parity DRIFT" in retired[0]["detail"]
    # ни один из трёх агентов не породил СВОЙ отдельный Problem
    assert not any(c["agent"] in ("com.spa.digest_weekly", "com.spa.tier1_digest",
                                  "com.spa.weekly_backup") for c in conditions)


def test_per_agent_retired_but_loaded_alone_still_opens_the_fleet_problem(tmp_path):
    """Без системной строки (fleet_parity.json не прочитан в этом прогоне) — per-agent
    находки одни ещё обязаны сложиться в fleet-level Problem, а не пропасть."""
    doc = _agent_health_with_retired(per_agent_labels=["com.spa.weekly_backup"])
    conditions = ps._conditions_from_agent_health(doc)
    retired = [c for c in conditions if c["cause_code"] == "retired_but_loaded"]
    assert len(retired) == 1
    assert "com.spa.weekly_backup" in retired[0]["detail"]


def test_no_retired_signal_means_no_fleet_problem(tmp_path):
    """Негативный контроль: без retired-сигналов вовсе — никакого fleet Problem."""
    doc = _agent_health_with_retired()
    conditions = ps._conditions_from_agent_health(doc)
    assert not any(c["cause_code"] == "retired_but_loaded" for c in conditions)


# ── F10: card text states PRECISELY what is/isn't suppressed (after F1) ────────

def test_card_body_does_not_claim_the_card_itself_silences_telegram():
    entry = {"agent": "com.spa.foo", "cause_code": "exit_nonzero:1",
             "problem_id": "com.spa.foo.exit_nonzero_1", "source": ps.SOURCE_AGENT_HEALTH}
    body = ps._card_body(entry, window_days=7, open_threshold=2, close_absent_streak=2)
    assert "не будит владельца" not in body, (
        "F10: прежняя формулировка приписывала тишину самой карточке — это неверно, "
        "тишину даёт push_policy edge-trigger у КОНКРЕТНОГО вызывающего")
    assert "push_policy" in body and "dedup_key" in body
    assert entry["source"] in body, "текст обязан назвать source, у которого своя проводка"


def test_site_freshness_code_becomes_a_condition(tmp_path):
    data_dir = tmp_path
    _write(data_dir, "site_freshness_report.json", {
        "ok": False,
        "fails": [{"code": "PUBLISHER_STUCK", "detail": "...", "severity": "CRITICAL"}],
    })
    conditions, _ = ps.collect(data_dir, now=T0)
    assert conditions[0]["agent"] == "site_freshness"
    assert conditions[0]["cause_code"] == "publication_behind"
    assert conditions[0]["severity"] == "CRITICAL"


def test_publication_family_collapses_but_an_unrelated_code_stays_separate(tmp_path):
    """Два взгляда на одну остановившуюся публикацию — одна Problem; код ВНЕ семьи
    (другая причина) остаётся отдельной — группировка не глотает разные корни."""
    _write(tmp_path, "site_freshness_report.json", {"ok": False, "fails": [
        {"code": "PUBLISHER_STUCK", "detail": "a", "severity": "CRITICAL"},
        {"code": "SITE_BEHIND_SNAPSHOT", "detail": "b", "severity": "WARNING"},
        {"code": "TLS_EXPIRING", "detail": "c", "severity": "WARNING"},
    ]})
    conditions, _ = ps.collect(tmp_path, now=T0)
    codes = sorted(c["cause_code"] for c in conditions)
    assert codes == ["TLS_EXPIRING", "publication_behind"]
    pub = next(c for c in conditions if c["cause_code"] == "publication_behind")
    assert pub["severity"] == "CRITICAL"
    assert "PUBLISHER_STUCK" in pub["detail"] and "SITE_BEHIND_SNAPSHOT" in pub["detail"]


def test_self_heal_failure_parses_agent_label_from_the_tail(tmp_path):
    data_dir = tmp_path
    _write(data_dir, "self_heal_status.json", {
        "failures": ["bootstrap failed com.spa.telegram_bot"],
    })
    conditions, _ = ps.collect(data_dir, now=T0)
    assert conditions[0]["agent"] == "com.spa.telegram_bot"
    assert conditions[0]["cause_code"] == "bootstrap_failed"


# ── ADR-333: сравнение по id — точное, не подстрокой ────────────────────────

def test_problem_id_lookup_is_exact_not_substring(tmp_path):
    data_dir = tmp_path
    long_id = ps.problem_id("com.spa.foo", "exit_nonzero:124")
    short_id = long_id[:-2]
    assert short_id != long_id
    doc = {"problems": {"k": {"problem_id": long_id, "status": ps.STATUS_CLOSED}}}
    ps.save_store(data_dir, doc)
    store = ps.load_store(data_dir)
    hit = next((p for p in store["problems"].values() if p.get("problem_id") == short_id), None)
    assert hit is None  # a truncated id must NOT match the real one


def test_run_once_never_raises_on_a_totally_empty_data_dir(tmp_path):
    report = ps.run_once(tmp_path / "data", now=T0, tracker_dir=tmp_path / "tracker")
    assert "error" not in report
    assert report["written"] is True
    assert all(v["status"] == "not_measured" for v in report["sources"].values())


# ── F1 (ADR-580 §C6, REVIEW_1): cause_from_agent_issue strips VOLATILE numbers ──
#
# Positive control replaying the review's own examples verbatim — a drifting
# age/duration/score inside an otherwise-unchanged issue string must normalise
# to the SAME cause_code, or the push-dedup fingerprint built from it re-fires
# on every number tick (the exact regression F1 reports).

@pytest.mark.parametrize(
    "a, b",
    [
        ("log stale 3.3d (>2.2d)", "log stale 3.7d (>2.2d)"),
        ("equity_curve stale 27.3h (>24h)", "equity_curve stale 41.0h (>24h)"),
        ("portfolio_health 70.0/100 (<75)", "portfolio_health 68.4/100 (<75)"),
        ("разрыв 3.7 суток", "разрыв 4.1 суток"),
    ],
)
def test_cause_from_agent_issue_ignores_a_drifting_number(a, b):
    ca, cb = ps.cause_from_agent_issue(a), ps.cause_from_agent_issue(b)
    assert ca == cb, f"{a!r} -> {ca!r} vs {b!r} -> {cb!r} must be the SAME cause"
    assert ca  # not None/empty — the texts are non-empty and non-exit-code


def test_cause_from_agent_issue_still_distinguishes_different_causes():
    # negative control: the normalisation must not collapse EVERYTHING into one
    # bucket — a genuinely different root cause still differs.
    assert ps.cause_from_agent_issue("equity_curve stale 27.3h (>24h)") != (
        ps.cause_from_agent_issue("portfolio_health 70.0/100 (<75)")
    )
    assert ps.cause_from_agent_issue("last_exit=1") != ps.cause_from_agent_issue("last_exit=2")
