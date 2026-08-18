"""Одна команда владельцу — и она обязана только ПЕЧАТАТЬ.

Каждый тест здесь — уже случившаяся авария или уже написанное правило, а не
гипотеза:

* **08.08 / 09.08** — долгожители (`apiserver` 23 сут, `familyfund` 38) крутят
  код многонедельной давности; сторож их называет, но собрать наряд на
  перезапуск владельцу было нечем (`test_stale_longliver_gets_a_ready_command`).
* **08.08, второй раз за день** — «проверить, запустив разок» подняло ВТОРОЙ
  `telegram_bot` на том же токене: 409-конфликты `getUpdates`, нажатия владельца
  теряются. Поэтому подсказчик перезапуска не имеет права ничего запускать
  (`test_script_never_executes_a_mutating_command`).
* **Правило доставки, п. 6** — перезапуск прод-агента делает владелец; агент
  готовит и ждёт (`test_report_says_the_restart_belongs_to_the_owner`).
* **Fail-CLOSED** — «не измерено» не сливается с «перезапускать некого»
  (`test_unchecked_is_not_reported_as_nothing_to_do`).

Литеральных дат нет: воспроизводится ФОРМА (разрыв в N часов), обе стороны
сравнения — вход, а не календарь (`.claude/rules/deployment.md`, «время в тестах»).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "print_stale_agent_restarts.py"
_spec = importlib.util.spec_from_file_location("print_stale_agent_restarts", _SCRIPT)
psr = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(psr)


UID = 501
_MUTATING = ("kickstart", "bootout", "bootstrap", "unload", "load", "kill", "stop")


def _agent(label: str, state: str, gap_hours=None, **kw) -> dict:
    doc = {"label": label, "state": state, "severity": "WARNING",
           "detail": "{}: подробности".format(label), "pid": 4242,
           "gap_hours": gap_hours, "notes": []}
    doc.update(kw)
    return doc


def _doc(agents) -> dict:
    stale = [a for a in agents if a["state"] == psr.STATE_STALE]
    unchecked = [a for a in agents if a["state"] == psr.STATE_UNCHECKED]
    return {"monitor": "agent_code_freshness", "status": "WARNING",
            "agents": agents, "long_lived_total": len(agents),
            "stale_count": len(stale), "unchecked_count": len(unchecked),
            "issues": [], "reasons": []}


# ── 1. Наряд собирается ─────────────────────────────────────────────────────
def test_stale_longliver_gets_a_ready_command():
    """Несвежий долгожитель ⇒ готовая команда с правильным доменом `gui/<uid>`.

    Положительный контроль замера 09.08: до этого скрипта владелец имел только
    слова сторожа («работает с кодом от 17 июля») и должен был сам вспомнить
    имя job'а и домен launchd.
    """
    doc = _doc([_agent("com.spa.apiserver", psr.STATE_STALE, gap_hours=23 * 24.0)])

    lines, cmds, code = psr.build_report(doc, uid=UID)
    text = "\n".join(lines)

    assert cmds == ["launchctl kickstart -k gui/501/com.spa.apiserver"]
    assert code == 1
    assert "com.spa.apiserver" in text
    assert "23.0 сут" in text, text
    # Приёмка ДО и ПОСЛЕ — часть наряда, а не память владельца.
    assert text.count("deployment_acceptance") >= 2, text
    assert "launchctl list" in text


def test_telegram_bot_is_covered_by_the_same_command():
    """Сегодняшний живой пример класса — бот — попадает в тот же наряд.

    И рядом обязано стоять предупреждение про гейт: `check_agent_before_deploy.sh`
    на долгожителе поднимает второй поллер на том же токене (замер 08.08).
    """
    doc = _doc([_agent("com.spa.telegram_bot", psr.STATE_STALE, gap_hours=72.0)])

    lines, cmds, _code = psr.build_report(doc, uid=UID)
    text = "\n".join(lines)

    assert cmds == ["launchctl kickstart -k gui/501/com.spa.telegram_bot"]
    assert "check_agent_before_deploy" in text and "НЕ применять" in text, text


def test_report_says_the_restart_belongs_to_the_owner():
    """Правило доставки п. 6 названо в самом отчёте, а не только в шапке файла."""
    doc = _doc([_agent("com.spa.apiserver", psr.STATE_STALE, gap_hours=100.0)])
    text = "\n".join(psr.build_report(doc, uid=UID)[0])
    assert "НЕ делает" in text and "п. 6" in text, text


# ── 2. И НИЧЕГО не запускает ────────────────────────────────────────────────
def test_script_never_executes_a_mutating_command(monkeypatch):
    """Подсказчик перезапуска не имеет права перезапускать.

    Положительный контроль аварии 08.08: «проверить, запустив разок» подняло
    второй поллер Telegram на том же токене. Проверяется не обещание в шапке, а
    поведение: любой вызов `subprocess`/`os.system` с мутирующим глаголом —
    красный тест.
    """
    import os as _os
    import subprocess as _sp

    seen = []

    def _trap(name):
        def f(*a, **kw):
            seen.append((name, a, kw))
            raise AssertionError("скрипт вызвал {}: {!r}".format(name, a))
        return f

    for mod, attr in ((_sp, "run"), (_sp, "Popen"), (_sp, "call"),
                      (_sp, "check_call"), (_sp, "check_output"),
                      (_os, "system"), (_os, "execv"), (_os, "spawnv")):
        monkeypatch.setattr(mod, attr, _trap("{}.{}".format(mod.__name__, attr)),
                            raising=False)

    doc = _doc([_agent("com.spa.apiserver", psr.STATE_STALE, gap_hours=500.0),
                _agent("com.spa.telegram_bot", psr.STATE_STALE, gap_hours=72.0)])

    code = psr.main([], checker=lambda **_kw: doc, uid=UID)

    assert code == 1
    assert seen == [], "скрипт что-то выполнил: {}".format(seen)


def test_commands_are_only_printed_never_returned_as_actions():
    """Мутирующий глагол встречается ТОЛЬКО как текст команды, ни разу — как вызов."""
    doc = _doc([_agent("com.spa.familyfund", psr.STATE_STALE, gap_hours=38 * 24.0)])
    _lines, cmds, _code = psr.build_report(doc, uid=UID)
    assert all(c.startswith("launchctl kickstart -k gui/") for c in cmds)
    assert all(isinstance(c, str) for c in cmds), "команда — строка, а не callable"


# ── 3. Fail-CLOSED ──────────────────────────────────────────────────────────
def test_unchecked_is_not_reported_as_nothing_to_do():
    """«Не измерено» ≠ «перезапускать некого».

    Пустой список команд рядом с непрочитанным plist'ом читался бы как чистый
    счёт — та же подмена «не измерено» → «в порядке», от которой написан сторож.
    """
    doc = _doc([_agent("com.spa.broken", psr.STATE_UNCHECKED,
                       detail="plist не читается")])

    lines, cmds, code = psr.build_report(doc, uid=UID)
    text = "\n".join(lines)

    assert cmds == []
    assert code == 2, "не измерено обязано отличаться кодом возврата от «всё чисто»"
    assert "НЕ ИЗМЕРЕНО" in text and "НЕПОЛОН" in text, text


def test_all_fresh_is_a_quiet_zero():
    """Обратное плечо: измерили всё, несвежих нет ⇒ 0 и тишина.

    Без него предыдущий тест закрывался бы вечной двойкой, и код возврата
    перестал бы что-либо значить.
    """
    doc = _doc([_agent("com.spa.apiserver", "fresh", gap_hours=-5.0)])
    lines, cmds, code = psr.build_report(doc, uid=UID)
    assert (cmds, code) == ([], 0)
    assert "Перезапускать нечего." in "\n".join(lines)


def test_gap_under_threshold_is_visible_but_not_a_restart_order():
    """Разрыв меньше порога ВИДЕН, но наряда не порождает.

    Пуши идут ежедневно: наряд после каждого — наряд, который перестают читать.
    """
    doc = _doc([_agent("com.spa.apiserver", psr.STATE_STALE, gap_hours=3.0)])
    lines, cmds, code = psr.build_report(doc, uid=UID)
    text = "\n".join(lines)
    assert cmds == [] and code == 0
    assert "Ниже порога" in text and "3.0 ч" in text, text


def test_threshold_is_a_knob_not_a_wall():
    """Тот же разрыв с порогом 1 ч обязан дать наряд — иначе тишина выше ложна."""
    doc = _doc([_agent("com.spa.apiserver", psr.STATE_STALE, gap_hours=3.0)])
    _lines, cmds, code = psr.build_report(doc, uid=UID, min_gap_hours=1.0)
    assert cmds and code == 1


def test_plist_form_note_reaches_the_owner():
    """Замечание сторожа о нестандартном `KeepAlive` доезжает до наряда.

    Иначе владелец перезапустит агента, не узнав, что его plist подозрителен.
    """
    doc = _doc([_agent("com.spa.apiserver", psr.STATE_STALE, gap_hours=100.0,
                       notes=["KeepAlive задан ПУСТЫМ словарём — форма нестандартная"])])
    text = "\n".join(psr.build_report(doc, uid=UID)[0])
    assert "ПУСТЫМ словарём" in text, text


@pytest.mark.parametrize("verb", _MUTATING)
def test_source_has_no_mutating_call(verb):
    """Храповик по исходнику: мутирующий глагол живёт только в печатаемой строке.

    Тест выше ловит вызов в рантайме на своих данных; этот не даёт мутирующему
    вызову появиться в ветке, до которой тесты не дошли.
    """
    src = _SCRIPT.read_text()
    for line in src.splitlines():
        stripped = line.strip()
        if verb not in stripped:
            continue
        assert not stripped.startswith(("subprocess.", "os.system", "os.exec")), stripped
        assert "subprocess.run(" not in stripped, stripped
