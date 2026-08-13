"""Код выхода дневного цикла: штатный отказ отличим от аварии (цикл #219).

Каждый тест здесь — **положительный контроль**: он воспроизводит замер
2026-08-13, когда `com.spa.daily_cycle` четыре прогона подряд (05:14, 05:29,
06:01, 06:56 UTC) возвращал `exit=1` при статусе `blocked_by_policy` — то есть
при ИСПРАВНОЙ работе, — а `agent_health` держал агента в WARNING с текстом
`last_exit=1`, неотличимым от настоящей аварии.

Проверка идёт в ОБЕ стороны, как требует карточка
`inbox-kod-vyhoda-tsikla-ne-otlichaet-shtatnyi`:

* отказ политики больше НЕ красит здоровье агента;
* авария, отсутствие живых данных, неотработавшая проверка безопасности и
  сработавшая защита — по-прежнему красят, и каждый своими словами.

Время здесь входит только через `NOW` и рукотворные отметки файлов
(`.claude/rules/deployment.md`): литеральных дат, от которых тест испортится со
сдвигом календаря, в фикстурах нет.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.paper_trading import cycle_exit as ce

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)

# Замер живого прода 2026-08-13: ровно этот статус выставлял цикл на каждом из
# четырёх прогонов (`logs/daily_cycle_*.log`: "status=blocked_by_policy",
# причина — "Chain concentration on ethereum after trade 95.0% exceeds
# single-chain limit 90.0%"). Сам лимит — money-path и здесь не проверяется.
PROD_REFUSAL_STATUS = "blocked_by_policy"


def _lc(label: str, pid: int = 0, exit_code: int | None = None) -> dict:
    return {label: {"pid": pid, "exit": exit_code}}


def _daily_plist(log_path) -> dict:
    """Плист дневного цикла в той же форме, что живой com.spa.daily_cycle."""
    return {"StartCalendarInterval": {"Hour": 8, "Minute": 0},
            "StandardOutPath": str(log_path)}


def _fresh_log(tmp_path, name: str = "cycle.log"):
    p = tmp_path / name
    p.write_text("x")
    ts = (NOW - timedelta(minutes=5)).timestamp()
    os.utime(p, (ts, ts))
    return p


# ── Словарь исходов ─────────────────────────────────────────────────────────
def test_policy_refusal_is_not_exit_one():
    """АВАРИЯ 13.08: штатный отказ уезжал кодом 1 — тем же, что поломка."""
    code = ce.exit_code_for_status(PROD_REFUSAL_STATUS)
    assert code != ce.EXIT_ERROR
    assert code == ce.EXIT_POLICY_REFUSED
    assert ce.is_by_design(code) is True


def test_daily_limits_share_the_policy_code():
    # Оба исхода означают одно: гейт отработал, капитал не сдвинулся.
    assert ce.exit_code_for_status("blocked_by_daily_limits") == ce.EXIT_POLICY_REFUSED


@pytest.mark.parametrize(
    "status, expected",
    [
        ("ok", ce.EXIT_OK),
        ("skipped_no_live_data", ce.EXIT_NO_LIVE_DATA),
        ("blocked_safety_check_error", ce.EXIT_SAFETY_UNMEASURED),
        ("kill_switch", ce.EXIT_PROTECTION_TRIGGERED),
        ("blocked_by_emergency_halt", ce.EXIT_PROTECTION_TRIGGERED),
    ],
)
def test_every_known_status_has_its_own_code(status, expected):
    assert ce.exit_code_for_status(status) == expected


@pytest.mark.parametrize("status", ["", "wat", "OK", None, 3, object()])
def test_unknown_status_is_a_crash_not_a_shrug(status):
    """Fail-CLOSED: исход, который словарь не понимает, — авария."""
    assert ce.exit_code_for_status(status) == ce.EXIT_ERROR
    assert ce.is_by_design(ce.exit_code_for_status(status)) is False


def test_only_policy_refusal_is_by_design():
    """Задача — перестать путать отказ с аварией, а не сделать пульт зеленее."""
    by_design = {c for c in range(0, 10) if ce.is_by_design(c)}
    assert by_design == {ce.EXIT_POLICY_REFUSED}


def test_lock_code_did_not_move_and_new_codes_do_not_pollute_its_counter(tmp_path):
    """Двойка занята замком: по ней считает `cycle_lock_watch.count_refusals`.

    Положительный контроль в обе стороны: отказ замка по-прежнему считается, а
    новый код штатного отказа политики в этот счётчик НЕ попадает — иначе
    сторож застрявшего замка начал бы видеть отказы там, где их не было.
    """
    from spa_core.monitoring import cycle_lock_watch as clw

    assert ce.EXIT_LOCK_REFUSED == 2
    log = tmp_path / "spa_daily_cycle.launchd.out"
    log.write_text(
        f"[2030-01-01T10:00:00Z] cycle_runner exit={ce.EXIT_LOCK_REFUSED}\n"
        f"[2030-01-01T10:10:00Z] cycle_runner exit={ce.EXIT_POLICY_REFUSED}\n"
        f"[2030-01-01T10:20:00Z] cycle_runner exit={ce.EXIT_POLICY_REFUSED}\n"
    )
    since = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
    assert clw.count_refusals(log, since=since, now=NOW) == 1


def test_every_code_has_words_and_unknown_says_so():
    for code in (ce.EXIT_OK, ce.EXIT_ERROR, ce.EXIT_LOCK_REFUSED,
                 ce.EXIT_POLICY_REFUSED, ce.EXIT_NO_LIVE_DATA,
                 ce.EXIT_SAFETY_UNMEASURED, ce.EXIT_PROTECTION_TRIGGERED):
        assert ce.describe_exit(code).strip()
    assert "неизвестный" in ce.describe_exit(99)
    assert "неизвестный" in ce.describe_exit(None)


def test_codes_are_distinct_and_launchd_safe():
    codes = [ce.EXIT_OK, ce.EXIT_ERROR, ce.EXIT_LOCK_REFUSED,
             ce.EXIT_POLICY_REFUSED, ce.EXIT_NO_LIVE_DATA,
             ce.EXIT_SAFETY_UNMEASURED, ce.EXIT_PROTECTION_TRIGGERED]
    assert len(set(codes)) == len(codes)
    # 78 — EX_CONFIG у launchd (наш давний exit-78), занимать его нельзя.
    assert 78 not in codes
    assert all(0 <= c < 126 for c in codes)


# ── Цикл действительно пользуется словарём ──────────────────────────────────
def test_cycle_runner_returns_the_taxonomy_code(monkeypatch, capsys):
    """Сам цикл: `blocked_by_policy` ⇒ 3, `ok` ⇒ 0, сломанный статус ⇒ 1."""
    from spa_core.paper_trading import cycle_runner as cr

    def _result(status):
        return cr.CycleResult(
            run_ts="2030-01-01T00:00:00Z", date="2030-01-01", status=status,
            traded=False, trade_id=None, live_data=True, num_adapters_live=3,
            current_equity=100_000.0, daily_yield_usd=0.0, daily_return_pct=0.0,
            apy_today_pct=0.0, total_return_pct=0.0, days_running=1,
            model_used=None, strategy_loop_active=False,
        )

    for status, expected in (
        (PROD_REFUSAL_STATUS, ce.EXIT_POLICY_REFUSED),
        ("ok", ce.EXIT_OK),
        ("this_status_does_not_exist", ce.EXIT_ERROR),
    ):
        monkeypatch.setattr(cr, "run_cycle", lambda status=status, **kw: _result(status))
        assert cr._main_inner(["--dry-run"]) == expected
    # Исход назван словами в выводе цикла, а не только цифрой.
    assert "исход" in capsys.readouterr().out


# ── Читатель: agent_health называет исходы разными словами ──────────────────
def test_policy_refusal_no_longer_reddens_the_cycle_agent(tmp_path):
    """ЗАМЕР 13.08: агент висел в WARNING сутки на исправной работе."""
    plist = _daily_plist(_fresh_log(tmp_path))
    h = ahm.check_agent(ce.CYCLE_AGENT_LABEL, plist, True,
                        _lc(ce.CYCLE_AGENT_LABEL, pid=0, exit_code=ce.EXIT_POLICY_REFUSED),
                        NOW)
    assert h.status == ahm.OK
    assert h.issue == ""
    # Но и НЕ молчит: штатный отказ назван вслух отдельным полем.
    assert "штатный отказ политики" in h.note
    assert f"last_exit={ce.EXIT_POLICY_REFUSED}" in h.note


def test_real_crash_still_reddens_the_cycle_agent(tmp_path):
    """Обратная сторона: авария обязана краснеть, иначе мы починили тишину."""
    plist = _daily_plist(_fresh_log(tmp_path))
    h = ahm.check_agent(ce.CYCLE_AGENT_LABEL, plist, True,
                        _lc(ce.CYCLE_AGENT_LABEL, pid=0, exit_code=ce.EXIT_ERROR),
                        NOW)
    assert h.status == ahm.WARNING
    assert "last_exit=1" in h.issue
    assert "АВАРИЯ" in h.issue
    assert h.note == ""


@pytest.mark.parametrize(
    "code, word",
    [
        (ce.EXIT_LOCK_REFUSED, "замка"),
        (ce.EXIT_NO_LIVE_DATA, "живых данных"),
        (ce.EXIT_SAFETY_UNMEASURED, "безопасности"),
        (ce.EXIT_PROTECTION_TRIGGERED, "защита"),
    ],
)
def test_other_outcomes_stay_visible_with_their_own_words(tmp_path, code, word):
    """Громкость НЕ снижена ни для одного исхода, кроме отказа политики."""
    plist = _daily_plist(_fresh_log(tmp_path, f"c{code}.log"))
    h = ahm.check_agent(ce.CYCLE_AGENT_LABEL, plist, True,
                        _lc(ce.CYCLE_AGENT_LABEL, pid=0, exit_code=code), NOW)
    assert h.status == ahm.WARNING
    assert f"last_exit={code}" in h.issue
    assert word in h.issue


def test_dictionary_applies_only_to_the_cycle_agent(tmp_path):
    """Fail-CLOSED: у ЧУЖОГО агента тройка означает что угодно — не молчать."""
    plist = {"StartInterval": 300, "StandardOutPath": str(_fresh_log(tmp_path, "o.log"))}
    h = ahm.check_agent("com.spa.some_other_agent", plist, True,
                        _lc("com.spa.some_other_agent", pid=0,
                            exit_code=ce.EXIT_POLICY_REFUSED), NOW)
    assert h.status == ahm.WARNING
    assert "last_exit=3" in h.issue
    assert "штатный" not in h.issue
    assert h.note == ""


def test_note_reaches_the_report_file(tmp_path):
    """Слова обязаны доехать до data/agent_health.json, иначе их никто не прочтёт."""
    plist = _daily_plist(_fresh_log(tmp_path))
    h = ahm.check_agent(ce.CYCLE_AGENT_LABEL, plist, True,
                        _lc(ce.CYCLE_AGENT_LABEL, pid=0, exit_code=ce.EXIT_POLICY_REFUSED),
                        NOW)
    d = h.to_dict()
    assert "note" in d and "штатный отказ политики" in d["note"]
    assert d["issue"] == ""
    assert d["status"] == ahm.OK


def test_by_design_refusal_does_not_feed_the_wake_storm(tmp_path):
    """Побочно: штатный отказ больше не считается за павшего агента."""
    plist = _daily_plist(_fresh_log(tmp_path))
    ok_cycle = ahm.check_agent(
        ce.CYCLE_AGENT_LABEL, plist, True,
        _lc(ce.CYCLE_AGENT_LABEL, pid=0, exit_code=ce.EXIT_POLICY_REFUSED), NOW)
    assert ahm.detect_wake_storm([ok_cycle], min_agents=1) is None
    crashed = ahm.check_agent(
        ce.CYCLE_AGENT_LABEL, plist, True,
        _lc(ce.CYCLE_AGENT_LABEL, pid=0, exit_code=ce.EXIT_ERROR), NOW)
    assert ahm.detect_wake_storm([crashed], min_agents=1) is not None


def test_dictionary_adds_no_money_path_import_to_the_monitor():
    """Словарь не тянет в read-only слой НИЧЕГО сверх самого пакета (инв. #6).

    Меряется ДЕЛЬТА, а не абсолютный список: `import spa_core` сам по себе уже
    затягивает `spa_core.risk.policy` (это предсуществующее свойство пакета, и
    мониторинг живёт с ним давно). Утверждение теста — ровно то, на которое он
    имеет право: `cycle_exit` не добавляет к этому ни одного модуля.

    Замер — в ДОЧЕРНЕМ процессе: под pytest половина дерева уже импортирована,
    и одно-процессная проверка была бы слепа к настоящему эффекту.
    """
    import json
    import subprocess
    import sys

    code = (
        "import sys, json; import spa_core; base=set(sys.modules); "
        "import spa_core.paper_trading.cycle_exit; "
        "print(json.dumps(sorted(set(sys.modules) - base)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(_repo_root()))
    assert out.returncode == 0, out.stderr
    added = json.loads(out.stdout.strip().splitlines()[-1])
    assert not [m for m in added if m.startswith(("spa_core.execution", "spa_core.risk"))]
    # Дельта — только сам модуль и его пустой пакет; ничего тяжёлого.
    assert set(added) <= {"spa_core.paper_trading", "spa_core.paper_trading.cycle_exit"}


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]
