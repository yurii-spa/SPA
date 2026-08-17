"""Отказ замка отличим от аварии (карточка `inbox-otkaz-zamka-tsikla-neotlichim-ot-avarii`).

Карточка требовала ДВЕ половины сразу: «развести коды — правка обёртки И читателя;
новый код без правки читателя даст то же жёлтое, то есть смену цифры без смены смысла».
Цикл #219 сделал первую (авария — 1, отказ замка — 2), вторую оставил.

Замер, ради которого всё это: 2026-08-08 дневной цикл звали 20 раз, **18 — отказ
замка, ни одной аварии**, и пульт показывал `⚠️ com.spa.daily_cycle last_exit=2` —
тот же жёлтый, что при поломке.

Ключевое решение, которое эти тесты держат в ОБЕ стороны: **тишина покупается
доказательством, а не цифрой.** Отказ замка порождается двумя противоположными
причинами — живой цикл держит замок (защита работает) и МЁРТВЫЙ держит (цикл встал;
оба инцидента 08.08 именно такие). Молча погасить двойку значило бы заглушить вторую
вместе с первой, то есть починить тишину вместо сигнала.

**Где живёт решение.** Вывод из состояния замка — предмет именно этого сторожа,
поэтому он в `cycle_lock_watch.judge_lock_refusal`, а не в читателе: читателю
(`agent_health_monitor`, файл закреплён за другим агентом в этой волне) остаётся
вызов в три строки. Точный патч места вызова — в отчёте цикла.

Часы: в проверках сторожа время не участвует вовсе; там, где отметку ставит сам
bash, окно задано ОТНОСИТЕЛЬНО текущего момента. Литеральных дат в фикстурах нет.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import cycle_lock_watch as clw
from spa_core.paper_trading import cycle_exit as ce

_WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "run_daily_paper_cycle.sh"


def _verdict(state: str, pid: int | None = 4242) -> clw.CycleLockVerdict:
    """Вердикт замка нужного состояния — ровно то, что возвращает `check_cycle_lock`."""
    dead = state == clw.STATE_HELD_DEAD
    return clw.CycleLockVerdict(
        state=state, severity=clw.CRITICAL if dead else clw.OK, detail="", pid=pid,
        issue=f"cycle lock застрял: держатель pid={pid} МЁРТВ" if dead else None)


# ════════════════════════════════════════════════════════════════════════════
# 1. Отказ при ЖИВОМ держателе — информация, а не предупреждение
# ════════════════════════════════════════════════════════════════════════════
def test_refusal_with_a_live_holder_is_not_a_warning():
    """ЗАМЕР 08.08: 18 отказов из 20 вызовов, ни одной аварии — и жёлтый пульт.

    Положительный контроль: до правки тот же вход давал WARNING (см.
    `test_the_unfixed_reader_reproduces_the_defect` ниже — он воспроизводит
    прежнее поведение читателя и показывает, что оно НЕ различало исходы).
    """
    severity, words = clw.judge_lock_refusal(_verdict(clw.STATE_HELD_ALIVE, pid=98535))

    assert severity == clw.OK
    # И НЕ молчит: исход назван вслух вместе с доказательством.
    assert "ЗАКОНЕН" in words
    assert "98535" in words and "ЖИВ" in words


def test_a_live_holder_without_a_pid_is_still_legitimate():
    """Номер держателя — украшение вердикта, а не условие его законности."""
    severity, words = clw.judge_lock_refusal(_verdict(clw.STATE_HELD_ALIVE, pid=None))

    assert severity == clw.OK
    assert "pid=" not in words


# ════════════════════════════════════════════════════════════════════════════
# 2. Обратная сторона: тишина куплена ДОКАЗАТЕЛЬСТВОМ, а не цифрой
# ════════════════════════════════════════════════════════════════════════════
def test_refusal_with_a_DEAD_holder_stays_loud():
    """Оба инцидента 08.08 — именно этот случай: замок держал труп, цикл встал.

    Мутация «гасить код 2 всегда» красит ровно этот тест — и это его работа.
    """
    severity, words = clw.judge_lock_refusal(_verdict(clw.STATE_HELD_DEAD))

    assert severity == clw.WARNING
    assert "НЕ ДОКАЗАНА" in words
    assert clw.STATE_HELD_DEAD in words


@pytest.mark.parametrize(
    "state",
    [clw.STATE_HELD_EXPIRED, clw.STATE_UNCHECKED, clw.STATE_NO_LOCK],
)
def test_any_state_short_of_a_live_holder_stays_loud(state):
    """Fail-CLOSED: «не труп» ≠ «доказано законно». Доказательство одно — живой держатель."""
    severity, words = clw.judge_lock_refusal(_verdict(state))

    assert severity == clw.WARNING
    assert "НЕ ДОКАЗАНА" in words and state in words


def test_an_unmeasured_lock_is_not_a_permission_to_be_quiet():
    """Вердикт не измерен вовсе (`None`) — прежняя громкость, а не тишина."""
    severity, words = clw.judge_lock_refusal(None)

    assert severity == clw.WARNING
    assert "НЕ ИЗМЕРЕНО" in words


@pytest.mark.parametrize("code", [0, ce.EXIT_ERROR, ce.EXIT_POLICY_REFUSED,
                                  ce.EXIT_NO_LIVE_DATA, None, "2"])
def test_a_foreign_outcome_is_not_judged_here(code):
    """Живой замок НЕ индульгенция: чужой код сторож не судит и не гасит."""
    assert clw.judge_lock_refusal(_verdict(clw.STATE_HELD_ALIVE), code) is None


def test_the_two_outcomes_are_finally_distinguishable():
    """Суть карточки одной строкой: один и тот же замок, два разных ответа."""
    lock = _verdict(clw.STATE_HELD_ALIVE)
    refusal = clw.judge_lock_refusal(lock, ce.EXIT_LOCK_REFUSED)
    crash = clw.judge_lock_refusal(lock, ce.EXIT_ERROR)

    assert refusal is not None and refusal[0] == clw.OK
    assert crash is None, "авария обязана уйти к прежнему, громкому разбору"


def test_the_unfixed_reader_reproduces_the_defect():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на коде ДО правки: прежний читатель не различал.

    Воспроизводится дословно правило `agent_health_monitor` в его нынешнем
    (незатронутом) виде: штатным считается ровно один исход — отказ политики,
    а значит код 2 красит одинаково и при живом держателе, и при трупе.
    Пока этот тест зелёный, вторая половина карточки в читателе НЕ применена.
    """
    from spa_core.paper_trading.cycle_exit import is_by_design

    assert is_by_design(ce.EXIT_LOCK_REFUSED) is False
    # Прежняя логика читателя видит только код — и для живого, и для мёртвого
    # держателя выдаёт один и тот же жёлтый.
    old_reader = lambda code, verdict: "OK" if is_by_design(code) else "WARNING"  # noqa: E731
    assert (old_reader(ce.EXIT_LOCK_REFUSED, _verdict(clw.STATE_HELD_ALIVE))
            == old_reader(ce.EXIT_LOCK_REFUSED, _verdict(clw.STATE_HELD_DEAD)))
    # А новый различает — ровно то, чего требовала карточка.
    assert (clw.judge_lock_refusal(_verdict(clw.STATE_HELD_ALIVE))[0]
            != clw.judge_lock_refusal(_verdict(clw.STATE_HELD_DEAD))[0])


# ════════════════════════════════════════════════════════════════════════════
# 3. Счётчик отказов не должен зависеть от литерала
# ════════════════════════════════════════════════════════════════════════════
def test_the_counter_follows_the_dictionary_not_a_literal(tmp_path):
    """Код отказа теперь берётся из словаря исходов, а не переписан цифрой."""
    log = tmp_path / "wrapper.log"
    log.write_text(
        f"[2030-01-01T10:00:00Z] cycle_runner exit={ce.EXIT_LOCK_REFUSED}\n"
        f"[2030-01-01T10:10:00Z] cycle_runner exit={ce.EXIT_POLICY_REFUSED}\n"
        f"[2030-01-01T10:20:00Z] cycle_runner exit={ce.EXIT_ERROR}\n")
    since = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
    now = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)

    assert clw.count_refusals(log, since=since, now=now) == 1


# ════════════════════════════════════════════════════════════════════════════
# 4. Обёртка: отказ — это НЕ прогон
# ════════════════════════════════════════════════════════════════════════════
def _wrapper_text() -> str:
    return _WRAPPER.read_text(encoding="utf-8")


def _extract(pattern: str) -> str:
    m = re.search(pattern, _wrapper_text(), re.M | re.S)
    assert m, f"строка обёртки не найдена: {pattern}"
    return m.group(0)


def test_wrapper_literal_matches_the_taxonomy():
    """Parity: bash не импортирует Python, поэтому копия кода не свободна."""
    m = re.search(r"^EXIT_LOCK_REFUSED=(\d+)$", _wrapper_text(), re.M)
    assert m, "литерал кода отказа исчез из обёртки"
    assert int(m.group(1)) == ce.EXIT_LOCK_REFUSED


def test_wrapper_is_still_valid_bash():
    r = subprocess.run(["bash", "-n", str(_WRAPPER)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_no_set_e_was_introduced():
    """Обёртка намеренно без `set -e`; правка не смеет это менять."""
    executable = [ln.strip() for ln in _wrapper_text().splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
    assert not [ln for ln in executable if re.match(r"set\s+-[a-z]*e", ln)]


def test_wrapper_is_executable():
    """Права — часть доставки: 100644 у скрипта launchd = мёртвый агент (exit 126)."""
    assert os.access(_WRAPPER, os.X_OK), "обёртка перестала быть исполняемой"


def test_the_exit_line_still_feeds_the_refusal_counter(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: слова дописаны, а счётчик отказов не ослеп.

    Берётся ДОСЛОВНАЯ строка из обёртки и исполняется настоящим bash — иначе
    проверялось бы намерение, а не то, что попадёт в лог.
    """
    line = _extract(r'^echo "\[\$\(date[^\n]*cycle_runner exit=\$CYCLE_EXIT[^\n]*$')
    log = tmp_path / "wrapper.log"
    script = (f'LOG_FILE="{log}"; CYCLE_EXIT={ce.EXIT_LOCK_REFUSED}; '
              f'CYCLE_WORDS="отказ замка: цикл уже шёл"; {line}')
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    now = datetime.now(timezone.utc)
    n = clw.count_refusals(log, since=now - timedelta(hours=1),
                           now=now + timedelta(hours=1))
    assert n == 1, f"счётчик отказов ослеп на строке: {log.read_text()!r}"
    assert "отказ замка" in log.read_text(), "исход по-прежнему без слов"


def test_a_refusal_stops_before_the_reporting_steps(tmp_path):
    """Отказавший прогон НЕ имеет права публиковать чужое полузаписанное состояние.

    Блок берётся из файла и ИСПОЛНЯЕТСЯ: проверяется поведение (выход с кодом 2 и
    строка-терминатор), а не наличие похожего текста.
    """
    block = _extract(r'^EXIT_LOCK_REFUSED=\d+\nif \[ "\$CYCLE_EXIT".*?\nfi$')
    log = tmp_path / "wrapper.log"
    r = subprocess.run(
        ["bash", "-c", f'LOG_FILE="{log}"; CYCLE_EXIT={ce.EXIT_LOCK_REFUSED}; '
                       f'{block}; echo STEP2_RAN'],
        capture_output=True, text=True)

    assert r.returncode == ce.EXIT_LOCK_REFUSED
    assert "STEP2_RAN" not in r.stdout, "шаги отчётности выполнились поверх чужой записи"
    assert "REFUSED" in r.stdout


def test_a_normal_run_still_reaches_the_reporting_steps(tmp_path):
    """Обратная сторона: обычный прогон не смеет обрываться на этой развилке."""
    block = _extract(r'^EXIT_LOCK_REFUSED=\d+\nif \[ "\$CYCLE_EXIT".*?\nfi$')
    log = tmp_path / "wrapper.log"
    for code in (0, ce.EXIT_ERROR, ce.EXIT_POLICY_REFUSED):
        r = subprocess.run(
            ["bash", "-c", f'LOG_FILE="{log}"; CYCLE_EXIT={code}; {block}; echo STEP2_RAN'],
            capture_output=True, text=True)
        assert "STEP2_RAN" in r.stdout, f"код {code} ошибочно принят за отказ замка"


def test_every_invocation_still_ends_with_a_terminator_line():
    """Признак УБИТОГО держателя — прогон вообще без завершающей строки.

    Замер 08.08: 10:04:57Z — единственная строка без парной завершающей, и по ней
    отличили убийство от падения. Если бы отказ тоже обрывался молча, признак
    перестал бы различать.
    """
    text = _wrapper_text()
    assert "Cycle REFUSED" in text
    assert "Cycle completed" in text
