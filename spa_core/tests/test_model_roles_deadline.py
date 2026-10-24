# LLM_FORBIDDEN
"""Срок вызова через существующий `claude_run_with_timeout.py` — на временной сцене БЕЗ модели.

`subprocess.run(timeout=…)` убивает только прямого ребёнка; отделившийся потомок (своя сессия) остаётся
жить. Адаптер Claude поэтому ведёт запуск через помощник срока: он завершает только тех, чья
принадлежность ЭТОМУ запуску доказана, и никого чужого не трогает (ARB 18.09). Здесь «claude» — поддельный
скрипт: он порождает внука в НОВОЙ сессии (как Bash-инструмент Claude) и зависает. Рядом — процесс,
запущенный ТЕСТОМ до вызова и к запуску не принадлежащий: он обязан пережить срыв срока.
Номера процессов берутся у живой ОС (`os.getpid` потомков), литеральных pid нет.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles import contract as c

REQ = c.Request("architect", "deadline-scene", "say ok", "ctx")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # зомби — не живой процесс
    try:
        st = subprocess.run(["ps", "-o", "state=", "-p", str(pid)], capture_output=True, text=True).stdout
    except OSError:
        return True
    return bool(st.strip()) and not st.strip().startswith("Z")


def _fake_claude(tmp: Path, body: str) -> str:
    script = tmp / "claude"
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body), encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def _wait_gone(pid: int, s: float = 10.0) -> bool:
    end = time.monotonic() + s
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.2)
    return not _alive(pid)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-сцена процессов")
def test_a_hung_call_times_out_and_only_our_detached_descendant_is_finished(tmp_path):
    marker = tmp_path / "grandchild.pid"
    binary = _fake_claude(tmp_path, f"""
        import os, subprocess, sys, time
        # внук в СВОЕЙ сессии — как Bash-инструмент Claude; `subprocess.run(timeout)` до него не дотянется
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
        open({str(marker)!r}, "w").write(str(p.pid))
        time.sleep(300)
    """)
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
                               start_new_session=True)
    try:
        adapter = ad.claude_cli(binary=binary, runner=ad.helper_runner(grace_s=3.0))
        t0 = time.monotonic()
        out = adapter(REQ, timeout_s=3.0, tools=[])
        took = time.monotonic() - t0
        assert out.status == "timeout", out.detail
        assert "rc=124" in out.detail and "every process of this run finished" in out.detail, out.detail
        grandchild = int(marker.read_text())
        assert _wait_gone(grandchild), "отделившийся потомок ЭТОГО запуска пережил срок"
        assert _alive(foreign.pid), "помощник срока тронул чужой процесс"
        assert took < 60, f"срок 3 с, а вызов занял {took:.1f} с"
    finally:
        foreign.send_signal(signal.SIGKILL)
        foreign.wait(timeout=10)


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-сцена процессов")
def test_a_normal_answer_passes_through_the_helper_unchanged(tmp_path):
    doc = {"type": "result", "is_error": False, "result": "ok через помощника",
           "usage": {"input_tokens": 3, "output_tokens": 2}, "total_cost_usd": None}
    binary = _fake_claude(tmp_path, f"""
        import json, sys
        assert "--tools" in sys.argv and sys.argv[sys.argv.index("--tools") + 1] == ""
        print(json.dumps({doc!r}))
    """)
    out = ad.claude_cli(binary=binary, runner=ad.helper_runner(grace_s=1.0))(REQ, timeout_s=30, tools=[])
    assert out.status == "ok" and out.text == "ok через помощника", out.detail
    assert out.usage["input_tokens"] == 3 and out.usage["cost_reported_usd"] is None


def test_a_missing_helper_is_an_error_not_a_bare_run(tmp_path):
    runner = ad.helper_runner(helper_path=tmp_path / "нет-помощника.py")
    out = ad.claude_cli(binary="/nonexistent/claude", runner=runner)(REQ, timeout_s=1, tools=[])
    assert out.status == "error" and "deadline helper unusable" in out.detail


def test_the_contract_never_runs_the_claude_seam_without_the_helper():
    """Обратная сторона: адаптер по умолчанию идёт через помощник, а не через голый subprocess."""
    import inspect
    src = inspect.getsource(ad.claude_cli)
    assert "helper_runner()" in src and "subprocess.run" not in src
    assert ad.TIMEOUT_HELPER.name == "claude_run_with_timeout.py" and ad.TIMEOUT_HELPER.exists()
    assert json.loads(json.dumps(list(ad.TIMEOUT_CODES))) == [124, 125]


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-сцена процессов")
def test_the_old_way_leaves_the_detached_descendant_alive(tmp_path):
    """Положительный контроль: прежний `subprocess.run(timeout=…)` внука НЕ завершает.

    Без этого теста зелёная сцена выше могла бы быть зелёной по построению (внук умирал бы сам)."""
    marker = tmp_path / "grandchild.pid"
    binary = _fake_claude(tmp_path, f"""
        import subprocess, sys, time
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
        open({str(marker)!r}, "w").write(str(p.pid))
        time.sleep(300)
    """)
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([binary], capture_output=True, timeout=3)
    grandchild = int(marker.read_text())
    try:
        assert _alive(grandchild), "внук умер сам — сцена не воспроизводит предмет"
    finally:
        os.kill(grandchild, signal.SIGKILL)


def test_without_an_injected_runner_the_adapter_goes_through_the_helper(monkeypatch):
    """Мутация «по умолчанию запускать мимо помощника» обязана краснеть: вызов по умолчанию = helper_runner."""
    calls = []

    def spy_factory(**kw):
        def run(cmd, timeout_s, log_path, out_path, cwd=None):
            calls.append((cmd[0], timeout_s))
            out_path.write_text(json.dumps({"is_error": False, "result": "ok"}), encoding="utf-8")
            return 0
        return run
    monkeypatch.setattr(ad, "helper_runner", spy_factory)
    out = ad.claude_cli(binary="/nonexistent/claude")(REQ, timeout_s=7, tools=[])
    assert out.status == "ok" and calls == [("/nonexistent/claude", 7)]


# ── ARB 24.10: рабочий каталог CLI и аргументы без интерполяции ─────────────────────────────

@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-сцена процессов")
def test_the_cli_runs_in_its_own_temp_dir_with_literal_arguments(tmp_path):
    """Фактический cwd ДОЧЕРНЕГО процесса — свой временный каталог; аргументы доходят буквально."""
    probe = tmp_path / "probe.json"
    pwned = tmp_path / "PWNED"
    binary = _fake_claude(tmp_path, f"""
        import json, os, sys
        json.dump({{"cwd": os.getcwd(), "argv": sys.argv[1:]}}, open({str(probe)!r}, "w"))
        print(json.dumps({{"is_error": False, "result": "ok"}}))
    """)
    nasty = c.Request("architect", "t", f'$(touch {pwned}) "; touch {pwned}; echo `id`', "ctx $HOME")
    parent_cwd = os.getcwd()
    out = ad.claude_cli(binary=binary, runner=ad.helper_runner(grace_s=1.0))(nasty, timeout_s=30, tools=[])
    assert out.status == "ok", out.detail
    seen = json.loads(probe.read_text())
    child_cwd = os.path.realpath(seen["cwd"])
    assert child_cwd != os.path.realpath(parent_cwd), "CLI унаследовал рабочий каталог вызывающего"
    assert os.path.basename(child_cwd) == "cwd" and "spa_model_roles_" in child_cwd, child_cwd
    assert os.getcwd() == parent_cwd, "cwd родительского процесса изменён"
    assert not pwned.exists(), "аргумент интерпретирован оболочкой"
    argv = seen["argv"]
    assert argv[argv.index("-p") + 1] == ad.render_prompt(nasty), "промпт дошёл не буквально"
    assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv


# ── ARB 24.10: 125 — отдельный неповторяемый исход ─────────────────────────────────────────

def _sequence_runner(codes, calls, log_text=""):
    ok = json.dumps({"is_error": False, "result": "УСПЕХ, КОТОРЫЙ НЕДОСТИЖИМ"})

    def run(cmd, timeout_s, log_path, out_path, cwd=None):
        rc = codes[len(calls)]
        calls.append(rc)
        out_path.write_text(ok if rc == 0 else "", encoding="utf-8")
        log_path.write_text(log_text, encoding="utf-8")
        return rc
    return run


def test_125_is_not_retried_and_success_after_it_is_unreachable():
    calls = []
    log = "⏱ TIMEOUT: ВЛАДЕНИЕ НЕ ЗАКРЫТО — 1 процесс(ов) выжили:\n    SURVIVOR pid=4242 tree pytest"
    adapters = {"claude_cli": ad.claude_cli(binary="/nonexistent/claude",
                                            runner=_sequence_runner([125, 0], calls, log))}
    r = c.execute(REQ, config=c.load_config(), provider_id="claude_subscription_cli", adapters=adapters)
    assert calls == [125], "после 125 запущен второй вызов"
    assert r.status == "ownership_unresolved" and r.attempts == 1 and r.text == ""
    assert "SURVIVOR pid=4242" in r.reason, "диагностика помощника потеряна"


def test_124_with_closed_ownership_is_still_retried_and_distinct_from_125():
    calls = []
    adapters = {"claude_cli": ad.claude_cli(binary="/nonexistent/claude",
                                            runner=_sequence_runner([124, 0], calls))}
    r = c.execute(REQ, config=c.load_config(), provider_id="claude_subscription_cli", adapters=adapters)
    assert calls == [124, 0] and r.status == "ok" and r.attempts == 2


def test_ask_turns_125_into_an_empty_answer_with_rc_125(monkeypatch):
    from spa_core.studio_os.memory import answer
    monkeypatch.setattr(answer.asm, "assemble", lambda q, budget_chars=12000: {"evidence_sufficiency": {"verdict": "X"}})
    monkeypatch.setattr(answer.asm, "render_markdown", lambda pkg: "ctx")
    calls = []
    r = answer.ask("q", adapters={"claude_cli": ad.claude_cli(
        binary="/nonexistent/claude", runner=_sequence_runner([125, 0], calls, "SURVIVOR pid=7"))})
    assert calls == [125] and r["answer"] == "" and r["rc"] == 125
    assert r["status"] == "ownership_unresolved" and "NOT closed" in r["reason"] and "SURVIVOR pid=7" in r["reason"]
