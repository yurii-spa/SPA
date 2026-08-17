"""Код отказа замка принадлежит ЗАМКУ — авария им притвориться не может.

Карточка `inbox-otkaz-zamka-tsikla-neotlichim-ot-avarii`. Две трети её уже сделаны
и здесь НЕ переделываются: коды разведены (#219, `cycle_exit`), а читатель покупает
тишину доказательством живого держателя (`cycle_lock_watch.judge_lock_refusal`).

Осталась дыра ровно посередине — **двойку производил не только замок**. Замер на
этом дереве 2026-08-17, до правки::

    $ python3 -m spa_core.paper_trading.cycle_runner --nonexistent-flag
    cycle_runner: error: unrecognized arguments: --nonexistent-flag
    exit = 2                       # ← тот же байт, что «цикл уже идёт»

и сквозь НАСТОЯЩЕГО читателя при живом держателе замка::

    health: OK · note: last_exit=2 — отказ замка: цикл уже шёл;
                       отказ ЗАКОНЕН: держатель pid=98535 ЖИВ — цикл идёт, трек защищён

То есть авария, при которой цикл ВООБЩЕ НЕ ЗАПУСКАЛСЯ (аргументы не разобраны,
дня трека нет), получала вердикт «трек защищён» и молчала. Зеркальный fail-OPEN к
тому, ради которого карточка заведена: раньше защита кричала как поломка, теперь
поломка молчала как защита. Обёртка при том же коде пишет «Cycle REFUSED (замок
занят)» и пропускает шаги отчётности, а `count_refusals` засчитывает аварию в
счётчик отказов.

Правка — у ПРОИЗВОДИТЕЛЯ и про владение кодом, а не про argparse: код отказа
выходит из программы ровно из одной ветки — той, где замок действительно занят.
Всё, что вернулось или вылетело из `_main_inner`, двойкой притвориться не может.

**Контроль в обе стороны** (мутации проверены поимённо, см. отчёт цикла):

* законный отказ по-прежнему отвечает кодом отказа и по-прежнему НЕ поднимает
  тревогу — мутация «пусть замок тоже возвращает EXIT_ERROR» красит §1–§2;
* авария, не запускавшая цикл, отличима и ГРОМКА даже при живом держателе —
  мутация «вернуть код как есть» (снять правку) красит §3–§5.

Часы: время здесь либо не участвует, либо задано ОТНОСИТЕЛЬНО фиксированной точки
`_NOW`; литеральных дат в фикстурах нет.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import cycle_lock_watch as clw
from spa_core.paper_trading import cycle_exit as ce
from spa_core.paper_trading import cycle_runner as cr

_NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


# ── Инструменты ─────────────────────────────────────────────────────────────
def _run_cycle_process(data_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """НАСТОЯЩИЙ процесс цикла — так его видит launchd (только код возврата).

    `--data-dir` уводит и замок, и запись в песочницу: живой трек не трогается.
    """
    return subprocess.run(
        [sys.executable, "-m", "spa_core.paper_trading.cycle_runner",
         "--data-dir", str(data_dir), *args],
        capture_output=True, text=True, timeout=300,
        cwd=str(Path(__file__).resolve().parents[2]),
    )


def _hold_the_lock_alive(data_dir: Path) -> int:
    """Положить замок от ЖИВОГО держателя — сам процесс тестов.

    Время старта берётся тем же измерителем, что у цикла, иначе переиспользованный
    ОС номер читался бы как чужой.
    """
    rc, started = cr._ps_start(os.getpid())
    (data_dir / cr.CYCLE_LOCK_FILE).write_text(json.dumps({
        "pid": os.getpid(),
        "pid_start": started if rc == 0 else "",
        "ts": datetime.now(timezone.utc).isoformat(),
    }))
    return os.getpid()


def _live_holder_verdict(pid: int) -> clw.CycleLockVerdict:
    """Вердикт замка «держит ЖИВОЙ» — ровно то, что вернёт `check_cycle_lock`."""
    return clw.CycleLockVerdict(state=clw.STATE_HELD_ALIVE, severity=clw.OK,
                                detail="", pid=pid, issue=None)


def _read_cycle_agent(tmp_path: Path, exit_code: int, verdict) -> object:
    """Прогнать НАСТОЯЩЕГО читателя (`agent_health_monitor.check_agent`)."""
    from spa_core.monitoring import agent_health_monitor as ahm

    log = tmp_path / f"cycle_{exit_code}.log"
    log.write_text("x")
    ts = (_NOW - timedelta(minutes=5)).timestamp()
    os.utime(log, (ts, ts))          # свежий лог: мерим исход, а не свежесть
    return ahm.check_agent(
        ce.CYCLE_AGENT_LABEL,
        {"StartCalendarInterval": {"Hour": 8, "Minute": 0}, "StandardOutPath": str(log)},
        True, {ce.CYCLE_AGENT_LABEL: {"pid": 0, "exit": exit_code}}, _NOW,
        tmp_path, cycle_lock=verdict)


# ════════════════════════════════════════════════════════════════════════════
# 1. Законный отказ НЕ СЛОМАН правкой: замок по-прежнему отвечает своим кодом
# ════════════════════════════════════════════════════════════════════════════
def test_a_busy_lock_still_answers_with_the_refusal_code(tmp_path):
    """Живой держатель ⇒ настоящий процесс цикла выходит кодом отказа.

    Сквозной, а не на моках: launchd видит РОВНО это число и ничего больше.
    """
    pid = _hold_the_lock_alive(tmp_path)

    proc = _run_cycle_process(tmp_path, "--verbose")

    assert proc.returncode == ce.EXIT_LOCK_REFUSED, proc.stderr[-2000:]
    # И цикл действительно не пошёл: замок остался чужим, своего он не писал.
    assert json.loads((tmp_path / cr.CYCLE_LOCK_FILE).read_text())["pid"] == pid


def test_the_refusal_branch_is_the_one_that_produces_the_code(monkeypatch):
    """Мутация «пусть и эта ветка отдаёт EXIT_ERROR» красит именно этот тест."""
    monkeypatch.setattr(cr, "_acquire_cycle_lock", lambda _d: None)
    monkeypatch.setattr(cr, "_main_inner", lambda _a: pytest.fail("цикл не должен идти"))

    assert cr.main(["--verbose"]) == ce.EXIT_LOCK_REFUSED


# ════════════════════════════════════════════════════════════════════════════
# 2. …и по-прежнему НЕ поднимает тревогу у читателя (сторона «норма»)
# ════════════════════════════════════════════════════════════════════════════
def test_a_genuine_refusal_raises_no_alarm(tmp_path):
    """Замер 08.08: 18 отказов из 20 вызовов, ни одной аварии — и жёлтый пульт.

    Код берётся не литералом, а ИЗМЕРЯЕТСЯ живым процессом: тест ловит и случай,
    когда отказ перестал быть отличим на стороне производителя.
    """
    sandbox = tmp_path / "box"
    sandbox.mkdir()
    pid = _hold_the_lock_alive(sandbox)
    measured = _run_cycle_process(sandbox, "--verbose").returncode

    health = _read_cycle_agent(tmp_path, measured, _live_holder_verdict(pid))

    assert health.status == clw.OK
    assert not health.issue                       # тревоги нет
    assert "ЗАКОНЕН" in (health.note or "")       # но и молчания нет
    assert str(pid) in health.note


# ════════════════════════════════════════════════════════════════════════════
# 3. Настоящая авария: цикл НЕ ЗАПУСКАЛСЯ — и это не отказ замка
# ════════════════════════════════════════════════════════════════════════════
def test_a_breakage_that_never_ran_the_cycle_is_not_a_refusal(tmp_path):
    """Положительный контроль замера 17.08: до правки здесь стояло 2.

    Неверный аргумент — не выдумка: обёртка передаёт циклу пять флагов, и любой
    из них, разошедшийся с парсером после доставки, даёт ровно этот исход —
    день трека не записан.
    """
    proc = _run_cycle_process(tmp_path, "--nonexistent-flag")

    assert proc.returncode != ce.EXIT_LOCK_REFUSED, (
        "авария вернула код отказа замка — снаружи она неотличима от защиты")
    assert proc.returncode == ce.EXIT_ERROR
    assert "unrecognized arguments" in proc.stderr
    # И словарь называет это аварией, а не «цикл уже шёл».
    assert ce.describe_exit(proc.returncode) == ce.describe_exit(ce.EXIT_ERROR)
    assert not ce.is_by_design(proc.returncode)


def test_the_breakage_did_not_even_take_the_lock(tmp_path):
    """Доказательство, что исход разошёлся с отказом ПО СУЩЕСТВУ, а не по цифре."""
    _run_cycle_process(tmp_path, "--nonexistent-flag")

    assert not (tmp_path / cr.CYCLE_LOCK_FILE).exists()


# ════════════════════════════════════════════════════════════════════════════
# 4. …и она ГРОМКА даже там, где живой держатель покупал тишину
# ════════════════════════════════════════════════════════════════════════════
def test_a_breakage_stays_loud_even_with_a_live_holder(tmp_path):
    """Сердце карточки, обратная сторона: доказательство живого держателя
    относится к ОТКАЗУ и не имеет права глушить чужой исход.

    До правки этот же вход давал `OK · трек защищён` (замер в шапке файла).
    """
    sandbox = tmp_path / "box"
    sandbox.mkdir()
    measured = _run_cycle_process(sandbox, "--nonexistent-flag").returncode

    health = _read_cycle_agent(tmp_path, measured, _live_holder_verdict(98535))

    assert health.status == clw.WARNING
    assert f"last_exit={measured}" in (health.issue or "")
    assert "ЗАКОНЕН" not in (health.note or "")


def test_the_breakage_does_not_inflate_the_refusal_counter(tmp_path):
    """Счётчик отказов (по нему сторож судит о трупе в замке) не пухнет от аварии.

    Обе строки написаны ОБЁРТКОЙ в её формате; отличаются они ровно кодом —
    тем самым, который правка развела.
    """
    measured = _run_cycle_process(tmp_path, "--nonexistent-flag").returncode
    stamp = (_NOW - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    log = tmp_path / "daily_cycle.log"
    log.write_text(f"[{stamp}] cycle_runner exit={measured} — {ce.describe_exit(measured)}\n")
    since = _NOW - timedelta(hours=1)

    assert clw.count_refusals(log, since, _NOW) == 0

    # Контроль осмысленности: настоящий отказ в том же формате счётчик видит.
    log.write_text(f"[{stamp}] cycle_runner exit={ce.EXIT_LOCK_REFUSED} — отказ\n")
    assert clw.count_refusals(log, since, _NOW) == 1


# ════════════════════════════════════════════════════════════════════════════
# 5. Правило держится дверью, а не списком известных производителей двойки
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("outcome", [
    ce.EXIT_LOCK_REFUSED,                        # возврат
    "raise",                                     # SystemExit(2) — argparse и родня
])
def test_no_inner_outcome_can_impersonate_a_refusal(monkeypatch, outcome):
    """Чужой `sys.exit(2)` завтра закрыт тем же правилом, что argparse сегодня."""
    def _inner(_argv):
        if outcome == "raise":
            raise SystemExit(ce.EXIT_LOCK_REFUSED)
        return outcome

    monkeypatch.setattr(cr, "_main_inner", _inner)

    assert cr._run_inner_owning_the_refusal_code([]) == ce.EXIT_ERROR


@pytest.mark.parametrize("code", [
    ce.EXIT_OK, ce.EXIT_ERROR, ce.EXIT_POLICY_REFUSED,
    ce.EXIT_NO_LIVE_DATA, ce.EXIT_SAFETY_UNMEASURED, ce.EXIT_PROTECTION_TRIGGERED,
])
def test_every_other_outcome_passes_through_untouched(monkeypatch, code):
    """Правка обязана трогать РОВНО один код: штатный отказ политики (3) не смеет
    превратиться в аварию — на этом стоит вся работа цикла #219."""
    monkeypatch.setattr(cr, "_main_inner", lambda _a: code)

    assert cr._run_inner_owning_the_refusal_code([]) == code


@pytest.mark.parametrize("raised,expected", [
    (SystemExit(None), ce.EXIT_OK),              # --help
    (SystemExit(0), ce.EXIT_OK),
    (SystemExit(ce.EXIT_POLICY_REFUSED), ce.EXIT_POLICY_REFUSED),
    (SystemExit("аргумент словами"), ce.EXIT_ERROR),
])
def test_systemexit_keeps_its_code_except_the_one(monkeypatch, raised, expected):
    def _inner(_argv):
        raise raised

    monkeypatch.setattr(cr, "_main_inner", _inner)

    assert cr._run_inner_owning_the_refusal_code([]) == expected


def test_help_still_exits_zero(tmp_path):
    """Сквозная проверка, что дверь не сломала обычный выход argparse."""
    proc = _run_cycle_process(tmp_path, "--help")

    assert proc.returncode == ce.EXIT_OK
    assert "--live" in proc.stdout


def test_the_dry_run_door_is_guarded_too(monkeypatch):
    """Сухой прогон замок не берёт — тем более не имеет права говорить «занят»."""
    monkeypatch.setattr(cr, "_acquire_cycle_lock",
                        lambda _d: pytest.fail("сухой прогон не берёт замок"))
    monkeypatch.setattr(cr, "_main_inner", lambda _a: ce.EXIT_LOCK_REFUSED)

    assert cr.main(["--dry-run"]) == ce.EXIT_ERROR
