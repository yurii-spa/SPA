"""Q3-2 · the fleet-parity guard must actually BE CALLED — and must catch a real missing plist.

Замер 2026-08-05 (карточка `agent-fleet-parity-guard-never-scheduled`): `data/fleet_parity.json`
не обновлялся 597 часов (25 суток). Проверка была исправна — её просто **некому было звать**:
ни plist в `launchd/`, ни шага в дневном цикле. `agent_health` всё это время честно писал
`fleet parity stale 595.0h` в пустоту. Классический «сигнал есть, адресата нет».

Существующий `test_fleet_parity_check.py` проверяет ЛОГИКУ на подменённых множествах меток
(`monkeypatch` поверх `declared_labels`/`plist_labels`) — и ни один его тест не покраснел бы
от того, что проверку 25 суток никто не запускал, а также от того, что разбор установщика
или чтение каталога plist'ов сломались.

Здесь — три вещи, которых там нет, каждая из них воспроизводит настоящую аварию:

1. **Расписание**: дневной цикл обязан звать `scripts/fleet_parity_check.py`. Уберите строку —
   тест краснеет; ровно этим состоянием система жила 25 суток.
2. **Кадэнс vs окно**: суточный кадэнс обязан помещаться в окно свежести `agent_health`
   (`FLEET_PARITY_STALE_H`). Иначе штатный запуск сам себя объявит протухшим.
3. **Положительный контроль на НАСТОЯЩЕМ дереве**: сносим plist объявленного агента с диска
   (и кладём лишний, не объявленный установщиком) — проверка обязана это увидеть, пройдя
   реальный разбор `install_all_agents.sh` и реальный `glob` по каталогам, без подмен.
"""
import importlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring.agent_health_monitor import (
    FLEET_PARITY_STALE_H,
    WARNING,
    check_system,
)

fpc = importlib.import_module("scripts.fleet_parity_check")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CYCLE_SH = _REPO_ROOT / "scripts" / "run_daily_paper_cycle.sh"

# Кадэнс дневного цикла: launchd com.spa.daily_cycle — раз в сутки.
_DAILY_CADENCE_H = 24.0


def _cycle_source() -> str:
    assert _CYCLE_SH.is_file(), f"канонический раннер цикла пропал: {_CYCLE_SH}"
    return _CYCLE_SH.read_text(encoding="utf-8")


def _uncommented_lines(text: str):
    """Строки скрипта без shell-комментариев — упоминание в комментарии вызовом не является."""
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            yield code


# ---------------------------------------------------------------------------
# 1. Расписание — то, чего не было 25 суток
# ---------------------------------------------------------------------------
def test_daily_cycle_actually_invokes_the_fleet_parity_guard():
    """Проверку кто-то обязан звать. Строка исчезнет — тест покраснеет."""
    calls = [ln for ln in _uncommented_lines(_cycle_source())
             if "scripts/fleet_parity_check.py" in ln]
    assert calls, (
        "дневной цикл больше не зовёт scripts/fleet_parity_check.py — сторож паритета флота "
        "снова остался без расписания (ровно состояние 2026-08-05: 597ч тишины)"
    )


def test_the_parity_step_cannot_fail_the_money_path_cycle():
    """DRIFT — это находка, а не поломка цикла: шаг обязан быть незавершающим (non-fatal)."""
    src = _cycle_source()
    call_lines = [ln for ln in _uncommented_lines(src) if "scripts/fleet_parity_check.py" in ln]
    assert call_lines
    # хвост шага: либо `|| ...` в самой строке, либо перенос строки с последующим `|| ...`
    idx = src.index("scripts/fleet_parity_check.py")
    tail = src[idx:idx + 400]
    assert "||" in tail.split("\n\n")[0], (
        "шаг паритета обязан быть non-fatal (`|| echo ...`): проверка выходит с кодом 1 при DRIFT, "
        "и без этого дневной цикл — money-path — падал бы из-за advisory-находки"
    )
    # `set -e` ищем только в КОДЕ: в шапке скрипта эта строка живёт в комментарии-объяснении
    assert not any(re.match(r"set\s+-\w*e", ln.strip()) for ln in _uncommented_lines(src)), (
        "в дневном цикле появился `set -e` — non-fatal шаги (паритет, снимок сайта) перестанут быть non-fatal"
    )


def test_the_guard_is_not_scheduled_by_growing_the_fleet():
    """Флот не должен расти на единицу ради наблюдения за самим собой (вариант 2 карточки)."""
    plists = list((_REPO_ROOT / "launchd").glob("com.spa.*parity*.plist"))
    plists += list((_REPO_ROOT / "scripts").glob("com.spa.*parity*.plist"))
    assert not plists, (
        f"появился отдельный агент под проверку паритета ({[p.name for p in plists]}) — "
        "выбран был вариант «шаг в дневном цикле»; если решение пересмотрено, "
        "обнови этот тест ВМЕСТЕ с обоснованием (инвариант #16)"
    )


# ---------------------------------------------------------------------------
# 2. Кадэнс vs окно свежести agent_health
# ---------------------------------------------------------------------------
def test_daily_cadence_fits_inside_the_agent_health_freshness_window():
    """Раз в сутки обязано помещаться в окно 26ч — иначе штатный запуск сам себя объявит протухшим."""
    assert _DAILY_CADENCE_H < FLEET_PARITY_STALE_H, (
        f"кадэнс {_DAILY_CADENCE_H}ч не помещается в окно свежести {FLEET_PARITY_STALE_H}ч: "
        "либо расширить окно, либо звать проверку чаще"
    )


def test_a_missed_days_worth_of_runs_is_still_alarmed(tmp_path):
    """Если шаг перестанет отрабатывать — тишина обязана быть слышна, а не сойти за норму."""
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    stale_ts = (now - timedelta(hours=FLEET_PARITY_STALE_H + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "fleet_parity.json").write_text(
        json.dumps({"generated_at": stale_ts, "status": "OK"}), encoding="utf-8"
    )
    checks, status, issues = check_system(tmp_path, now, autopush_log="/nonexistent/autopush.log")
    assert status == WARNING
    assert any("fleet parity stale" in i for i in issues), issues

    # …и наоборот: свежий (суточный) запуск тревогу о протухании НЕ поднимает
    fresh_ts = (now - timedelta(hours=_DAILY_CADENCE_H - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "fleet_parity.json").write_text(
        json.dumps({"generated_at": fresh_ts, "status": "OK"}), encoding="utf-8"
    )
    _checks, _status, issues2 = check_system(tmp_path, now, autopush_log="/nonexistent/autopush.log")
    assert not any("fleet parity stale" in i for i in issues2), issues2


# ---------------------------------------------------------------------------
# 3. Положительный контроль на настоящем дереве (без подмен множеств)
# ---------------------------------------------------------------------------
_PLIST_STUB = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
    '<key>Label</key><string>{label}</string></dict></plist>\n'
)


def _real_tree(tmp_path, labels_with_plists, extra_plists=(), declared_without_plist=()):
    """Настоящее дерево: установщик-скрипт на диске + каталог plist-файлов. Разбор — боевой."""
    scripts_dir = tmp_path / "scripts"
    launchd_dir = tmp_path / "launchd"
    scripts_dir.mkdir()
    launchd_dir.mkdir()

    lines = ["#!/bin/bash", "# fixture installer"]
    for label in list(labels_with_plists) + list(declared_without_plist):
        lines.append(f'install_agent "{label}" "launchd/{label}.plist"')
    (scripts_dir / "install_all_agents.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for label in list(labels_with_plists) + list(extra_plists):
        (launchd_dir / f"{label}.plist").write_text(_PLIST_STUB.format(label=label), encoding="utf-8")
    return scripts_dir, launchd_dir


def _point_at(monkeypatch, tmp_path, scripts_dir, launchd_dir, retired=()):
    monkeypatch.setattr(fpc, "_INSTALLER", scripts_dir / "install_all_agents.sh")
    monkeypatch.setattr(fpc, "_PLIST_DIRS", (scripts_dir, launchd_dir))
    monkeypatch.setattr(fpc, "_OUT", tmp_path / "fleet_parity.json")
    monkeypatch.setattr(fpc, "retired_labels", lambda: set(retired))
    monkeypatch.setattr(fpc, "_live_labels", lambda: None)   # как в CI: launchctl недоступен


def test_removing_a_declared_agents_plist_is_caught_on_a_real_tree(monkeypatch, tmp_path):
    """Снимаем plist у объявленного агента — проверка обязана это увидеть (контроль из карточки)."""
    scripts_dir, launchd_dir = _real_tree(tmp_path, ["com.spa.alpha", "com.spa.beta"])
    _point_at(monkeypatch, tmp_path, scripts_dir, launchd_dir)

    before = fpc.build_report(write=False)
    assert before["status"] == "OK", before          # контроль в обратную сторону: до сноса — чисто
    assert before["n_declared"] == 2 and before["n_plist"] == 2

    (launchd_dir / "com.spa.beta.plist").unlink()    # ← настоящая авария: установщик зовёт, файла нет

    after = fpc.build_report(write=False)
    assert after["status"] == "DRIFT"
    assert after["broken_declared_no_plist"] == ["com.spa.beta"]


def test_an_undeclared_plist_on_disk_is_caught_on_a_real_tree(monkeypatch, tmp_path):
    """Зеркальная авария: plist живёт на диске, установщик о нём не знает (сегодня таких 22)."""
    scripts_dir, launchd_dir = _real_tree(
        tmp_path, ["com.spa.alpha"], extra_plists=["com.spa.ghost"]
    )
    _point_at(monkeypatch, tmp_path, scripts_dir, launchd_dir)

    rep = fpc.build_report(write=False)
    assert rep["status"] == "DRIFT"
    assert rep["orphan_plist_not_declared"] == ["com.spa.ghost"]

    # …а объявленный retired-меткой — орфаном НЕ считается (иначе сторож кричал бы на by-design)
    _point_at(monkeypatch, tmp_path, scripts_dir, launchd_dir, retired=["com.spa.ghost"])
    rep2 = fpc.build_report(write=False)
    assert rep2["status"] == "OK", rep2


def test_a_scheduled_run_writes_a_status_file_agent_health_can_read(monkeypatch, tmp_path):
    """Сквозной шаг: запуск пишет файл, который agent_health считает СВЕЖИМ. Ради этого всё и делалось."""
    scripts_dir, launchd_dir = _real_tree(tmp_path, ["com.spa.alpha"])
    _point_at(monkeypatch, tmp_path, scripts_dir, launchd_dir)

    rc = fpc.main()
    assert rc == 0
    out = tmp_path / "fleet_parity.json"
    assert out.is_file(), "штатный запуск обязан оставить после себя data/fleet_parity.json"

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", payload["generated_at"]), payload
    assert payload["is_advisory"] is True and payload["llm_forbidden"] is True

    checks, _status, issues = check_system(
        tmp_path, datetime.now(timezone.utc), autopush_log="/nonexistent/autopush.log"
    )
    assert checks["fleet_parity_age_h"] is not None and checks["fleet_parity_age_h"] < 1.0
    assert not any("fleet parity stale" in i for i in issues), issues
