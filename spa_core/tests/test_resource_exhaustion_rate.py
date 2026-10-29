# LLM_FORBIDDEN
"""ADR-862 · «свободно 9,7 ГБ» и «свободно 9,7 ГБ, падает 17,9 ГБ/ч» требуют РАЗНЫХ действий.

Замер 2026-10-29. `com.spa.resource_guard` работает каждые 5 минут и публикует только УРОВЕНЬ
свободного места. Поэтому скорость два цикла подряд (#978, #979) мерили РУКАМИ sleep-циклом, а в
карточке владельца стояло «около 28 минут», когда измеренный ответ был 33: при 17.87 ГБ/ч и 9.7 ГБ
свободных. Премиса, на которой стоят сами пороги файла политики, — «40 GB leaves a day of the worst
measured growth (~30 GB/day)» — в тот же день измерена ложной в **14.3 раза** (428.9 ГБ/сут).

Положительный контроль здесь — ровно эта авария (`test_the_2026_10_29_incident_*`), и к каждой сцене
приложена ОБРАТНАЯ: там, где скорость обязана поднять вердикт, соседняя сцена отличается РОВНО
скоростью и вердикт поднимать не должна. Иначе тест мерил бы свой словарь, а не проводку.

Время и история замеров — ВХОДЫ (`.claude/rules/deployment.md`): закреплены оба конца, поэтому тест
не краснеет от сдвига календаря и не зависит от свободного места на машине, где он идёт.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from spa_core.monitoring import resource_guard as rg

GB = rg.GB

# FROZEN-DATE-OK: injected-clock — якорь ANCHOR уходит аргументом now= в measure_exhaustion() и
# build_report(), а КАЖДАЯ отметка истории замеров выведена из него же (sample(ago_s=...)). Закреплены
# оба конца, поэтому сдвиг календаря и часы хоста на вердикт не влияют (.claude/rules/deployment.md).
#: Якорь сцены — день самой аварии; все прочие отметки производны от него, своих часов тест не знает.
ANCHOR = datetime(2026, 10, 29, 18, 0, 0, tzinfo=timezone.utc)
NOW = ANCHOR.timestamp()


def policy(**over):
    p = json.loads(json.dumps(rg.load_policy()))      # глубокая копия канонической политики, не ручная
    p["disk"].update(over)
    return p


def sample(ago_s: float, free_gb: float) -> dict:
    return {"ts": NOW - ago_s, "free_bytes": int(free_gb * GB)}


def disk(free_gb: float, state=rg.OK) -> dict:
    return {"state": state, "free_bytes": int(free_gb * GB), "free_gb": round(free_gb, 1)}


# ── 1. сама авария 29.10 ────────────────────────────────────────────────────

def test_the_2026_10_29_incident_is_named_as_a_rate_not_a_level():
    """Пролёт 300 с: было 11.19 ГБ, стало 9.70 ГБ ⇒ 17.9 ГБ/ч и 33 минуты до нуля."""
    p = policy()
    e = rg.measure_exhaustion(disk(9.70), p, samples=[sample(300, 11.19)], now=NOW)
    assert e["state"] == rg.FALLING
    assert e["gb_per_hour"] == pytest.approx(17.9, abs=0.1)      # измеренные в тот день 17.87
    assert e["minutes_to_full"] == pytest.approx(32.6, abs=0.5)  # а НЕ «около 28 минут»


def test_the_level_alone_cannot_tell_those_two_days_apart():
    """ОБРАТНАЯ сцена: то же свободное место, скорости нет ⇒ срока до нуля НЕТ, и это ответ."""
    p = policy()
    falling = rg.measure_exhaustion(disk(9.70), p, samples=[sample(300, 11.19)], now=NOW)
    steady = rg.measure_exhaustion(disk(9.70), p, samples=[sample(300, 9.70)], now=NOW)
    assert falling["free_gb"] == steady["free_gb"]               # уровень ОДИН И ТОТ ЖЕ
    assert falling["state"] == rg.FALLING and steady["state"] == rg.STEADY
    assert falling["minutes_to_full"] is not None and steady["minutes_to_full"] is None


# ── 2. главное: скорость поднимает вердикт РАНЬШЕ, чем уровень ──────────────

def test_the_rate_raises_the_verdict_an_hour_before_the_level_line():
    """18 ГБ свободно — ВЫШЕ порога CRITICAL (15 ГБ), то есть по уровню это всего лишь WARN.

    При измеренных 29.10 18 ГБ/ч до нуля ровно час ⇒ CRITICAL. Это и есть то, чего уровень не
    способен заметить по построению.
    """
    p = policy()
    assert 18.0 > p["disk"]["critical_free_gb"]                  # предпосылка сцены названа
    fast = rg.measure_exhaustion(disk(18.0, rg.WARN), p, samples=[sample(3600, 36.0)], now=NOW)
    assert fast["state"] == rg.FALLING
    assert rg.exhaustion_state(fast, p) == rg.CRITICAL

    # ОБРАТНАЯ сцена — отличается РОВНО скоростью, и вердикт остаётся прежним
    slow = rg.measure_exhaustion(disk(18.0, rg.WARN), p, samples=[sample(3600, 18.2)], now=NOW)
    assert slow["state"] == rg.FALLING and slow["gb_per_hour"] == pytest.approx(0.2, abs=0.05)
    assert rg.exhaustion_state(slow, p) == rg.OK


def test_a_calm_rate_can_never_talk_a_critical_level_down():
    """fail-CLOSED (инв. #2): скорость голосует ТОЛЬКО на повышение."""
    p = policy()
    steady = rg.measure_exhaustion(disk(2.0, rg.CRITICAL), p, samples=[sample(600, 2.0)], now=NOW)
    assert steady["state"] == rg.STEADY
    assert rg.exhaustion_state(steady, p) == rg.OK               # сама скорость спокойна
    rep = {"disk": disk(2.0, rg.CRITICAL), "memory": {"state": rg.OK}, "processes": {"state": rg.OK},
           "exhaustion": steady}
    overall = max((rep["disk"]["state"], rep["memory"]["state"], rep["processes"]["state"],
                   rg.exhaustion_state(steady, p)), key=lambda s: rg._RANK[s])
    assert overall == rg.CRITICAL                               # но уровень вниз не уводит


# ── 3. три исхода различимы (инв. #17) ──────────────────────────────────────

def test_three_outcomes_are_three_different_values():
    """Измерено · измерено и равно нулю · НЕ измерено — ни одно не подменяет другое."""
    p = policy()
    measured = rg.measure_exhaustion(disk(50.0), p, samples=[sample(600, 55.0)], now=NOW)
    zero = rg.measure_exhaustion(disk(50.0), p, samples=[sample(600, 50.0)], now=NOW)
    nothing = rg.measure_exhaustion(disk(50.0), p, samples=[], now=NOW)
    blind = rg.measure_exhaustion(disk(50.0), p, samples=[], now=NOW, samples_error="JSONDecodeError")
    assert len({measured["state"], zero["state"], nothing["state"], blind["state"]}) == 4
    assert zero["gb_per_hour"] == 0.0 and "minutes_to_full" in zero   # ноль НАПЕЧАТАН, не опущен
    assert nothing["state"] == rg.WARMING_UP and "нет прежнего замера" in nothing["reason"]
    assert blind["state"] == rg.UNMEASURED and "JSONDecodeError" in blind["reason"]


def test_an_unreadable_level_is_not_a_rate_of_zero():
    p = policy()
    e = rg.measure_exhaustion({"state": rg.UNMEASURED, "reason": "volume absent"}, p,
                              samples=[sample(600, 50.0)], now=NOW)
    assert e["state"] == rg.UNMEASURED and "volume absent" in e["reason"]
    assert "gb_per_hour" not in e                               # число не выдумано


def test_a_clock_that_ran_backwards_refuses_instead_of_inventing_a_rate():
    p = policy()
    e = rg.measure_exhaustion(disk(50.0), p, samples=[{"ts": NOW + 600, "free_bytes": int(90 * GB)}],
                              now=NOW)
    assert e["state"] == rg.UNMEASURED and "часы шли назад" in e["reason"]


@pytest.mark.parametrize("ago,why", [(60, "короче объявленного минимума"), (10_000, "нет прежнего замера")])
def test_a_span_outside_the_declared_window_is_warming_up_never_a_stale_rate(ago, why):
    """Пролёт короче 240 с — дрожание, а не скорость; старше 7200 с — ничего не говорит о «сейчас»."""
    p = policy()
    e = rg.measure_exhaustion(disk(9.0), p, samples=[sample(ago, 90.0)], now=NOW)
    assert e["state"] == rg.WARMING_UP and why in e["reason"]
    assert "minutes_to_full" not in e


def test_warming_up_is_not_an_incident_but_a_blind_sensor_is_still_named():
    """«Двух замеров ещё нет» — штатный старт, а не слепой сторож (урок ADR-400: два разных вопроса).

    Но молчанием это не становится: оба исхода обязаны быть НАПЕЧАТАНЫ.
    """
    p = policy()
    warming = rg.measure_exhaustion(disk(50.0), p, samples=[], now=NOW)
    blind = rg.measure_exhaustion(disk(50.0), p, samples=[], now=NOW, samples_error="boom")
    assert rg.exhaustion_state(warming, p) == rg.OK and rg.exhaustion_state(blind, p) == rg.OK
    assert "rate not yet measured" in rg.exhaustion_line({"exhaustion": warming})
    assert "rate NOT MEASURED" in rg.exhaustion_line({"exhaustion": blind})


# ── 4. почему делим неокруглённые байты ─────────────────────────────────────

def test_the_rate_is_divided_from_unrounded_bytes():
    """free_gb округлён до 0.1 ГБ (= 107 МБ). Скорость из округлённых уровней квантуется на 5-минутном
    пролёте шагом ~1.3 ГБ/ч — то есть медленный расход печатался бы нулём."""
    p = policy()
    fine = rg.measure_exhaustion(disk(9.70), p, samples=[sample(300, 9.74)], now=NOW)
    assert fine["state"] == rg.FALLING and fine["gb_per_hour"] > 0.0
    rounded_in, rounded_out = round(9.74, 1), round(9.70, 1)
    assert rounded_in == rounded_out            # по округлённым числам расхода не видно ВОВСЕ


def test_measure_disk_publishes_free_bytes_for_that_reason():
    p = policy()

    class U:
        free, total, used = int(9.7 * GB) + 12_345, int(460 * GB), 0

    d = rg.measure_disk(p, disk_usage=lambda _v: U())
    assert d["free_bytes"] == U.free             # неокруглённое
    assert d["free_gb"] == round(U.free / GB, 1)


# ── 5. у числа есть ЧИТАТЕЛИ ────────────────────────────────────────────────

def test_the_owner_is_told_the_speed_in_words():
    p = policy()
    e = rg.measure_exhaustion(disk(9.70), p, samples=[sample(300, 11.19)], now=NOW)
    stamp = ANCHOR.strftime("%Y-%m-%dT%H:%M:%SZ")
    body = rg.owner_body({"generated_at": stamp, "disk": disk(9.70, rg.CRITICAL),
                          "memory": {"state": rg.OK, "pressure_level": 1}, "exhaustion": e})
    assert "Скорость:" in body and "17,88 ГБ/ч" in body and "33 мин" in body


def test_the_summary_line_carries_the_rate():
    p = policy()
    e = rg.measure_exhaustion(disk(9.70), p, samples=[sample(300, 11.19)], now=NOW)
    line = rg.summary_line({"overall": rg.CRITICAL, "disk": disk(9.70, rg.CRITICAL),
                            "memory": {"state": rg.OK, "pressure_level": 1,
                                       "swap": {"used_pct": 4.0}}, "exhaustion": e})
    assert "falling 17.88 GB/h" in line and "full in 32.6 min" in line


def test_build_report_measures_the_rate_and_lets_it_decide(tmp_path):
    """Сквозная сцена на НАСТОЯЩЕМ build_report: 18 ГБ свободно (уровень WARN) + измеренные 18 ГБ/ч."""
    p = policy()
    (tmp_path / "resource_free_samples.json").write_text(json.dumps(
        {"schema": "resource-free-samples/1", "samples": [sample(3600, 36.0)]}), encoding="utf-8")

    class U:
        free, total, used = int(18 * GB), int(460 * GB), 0

    rep = rg.build_report(p, disk_usage=lambda _v: U(), run=_healthy_run,
                          now=ANCHOR, data_dir=tmp_path)
    assert rep["disk"]["state"] == rg.WARN                      # по УРОВНЮ — всего лишь WARN
    assert rep["memory"]["state"] == rg.OK and rep["processes"]["state"] == rg.OK
    assert rep["exhaustion"]["state"] == rg.FALLING
    assert rep["exhaustion"]["state_vote"] == rg.CRITICAL
    assert rep["overall"] == rg.CRITICAL                        # вердикт поднят СКОРОСТЬЮ

    # ОБРАТНАЯ сцена: отличается РОВНО историей замеров
    (tmp_path / "resource_free_samples.json").write_text(json.dumps(
        {"schema": "resource-free-samples/1", "samples": [sample(3600, 18.1)]}), encoding="utf-8")
    calm = rg.build_report(p, disk_usage=lambda _v: U(), run=_healthy_run,
                           now=ANCHOR, data_dir=tmp_path)
    assert calm["exhaustion"]["state_vote"] == rg.OK and calm["overall"] == rg.WARN


def test_the_history_keeps_the_declared_tail_and_a_broken_path_costs_only_the_next_rate(tmp_path):
    p = policy()
    keep = p["disk"]["exhaustion"]["max_samples"]
    path = tmp_path / "resource_free_samples.json"
    rows = [sample(600 - i, 50.0) for i in range(keep + 10)]
    rg.record_sample(path, disk(49.0), p, samples=rows, now=NOW)
    saved = json.loads(path.read_text(encoding="utf-8"))["samples"]
    assert len(saved) == keep                                   # хвост объявлен политикой
    assert saved[-1]["free_bytes"] == int(49.0 * GB)            # и последний — этот замер
    assert saved == sorted(saved, key=lambda r: r["ts"])

    # непишущийся путь не роняет 5-минутный прогон сторожа
    rg.record_sample(tmp_path / "nope" / "deep" / "x.json", disk(49.0), p, samples=[], now=NOW)


def test_a_malformed_history_file_is_read_as_not_measured_not_as_empty(tmp_path):
    path = tmp_path / "resource_free_samples.json"
    path.write_text("{ this is not json", encoding="utf-8")
    rows, err = rg.load_samples(path)
    assert rows == [] and err and "resource_free_samples.json" in err
    absent, no_err = rg.load_samples(tmp_path / "never_written.json")
    assert absent == [] and no_err is None                      # отсутствие файла — ПЕРВЫЙ прогон


def test_the_policy_declares_every_number_the_sensor_uses():
    cfg = rg.load_policy()["disk"]["exhaustion"]
    for key in ("min_span_s", "max_span_s", "max_samples",
                "warn_minutes_to_full", "critical_minutes_to_full", "_why"):
        assert key in cfg, key
    assert cfg["min_span_s"] < cfg["max_span_s"]
    assert cfg["critical_minutes_to_full"] < cfg["warn_minutes_to_full"]
    assert "ADR-862" in cfg["_why"]


def test_the_false_premise_is_corrected_where_it_was_declared():
    """Премиса «~30 GB/day» стояла в `_why` самих порогов и была ложна x14.3 — она исправлена ТАМ ЖЕ,
    а не опровергнута в соседнем файле, который читатель порога не открывает."""
    why = rg.load_policy()["disk"]["_why"]
    assert "428.9 GB/day" in why and "x14.3" in why and "ADR-862" in why


def _healthy_run(cmd):
    """Здоровая машина: давление 1, своп почти пуст, ps отдаёт разборную строку."""
    joined = " ".join(cmd)
    if "kern.memorystatus_vm_pressure_level" in joined:
        return "1"
    if "vm.swapusage" in joined:
        return "total = 3072,00M  used = 100,00M  free = 2972,00M"
    if "hw.memsize" in joined:
        return str(16 * GB)
    if cmd[0] == "ps":
        return "501 1 102400 0 01:00 /usr/bin/python3 -m spa_core.paper_trading.cycle_runner"
    if cmd[0] == "launchctl":
        return "PID\tStatus\tLabel\n501\t0\tcom.spa.daily_cycle"
    return ""
