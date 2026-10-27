"""Исход каждой сессии Claude записывается с причиной — а не только цифрой во /tmp.

27.10: недельные коды 1 оркестратора (14–21.10) разобрать было нечем — журнал во /tmp
перезаписан; у novel_edge 20.10 в журнале стояло «Failed to authenticate: OAuth session
expired», а пульс видел `exit_nonzero:1`. Тесты гоняют НАСТОЯЩИЙ main() раннера с
поддельной командой; журнал исходов — во временном каталоге.
"""
import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "claude_run_with_timeout_ledger_ut", _ROOT / "scripts" / "claude_run_with_timeout.py")
crt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crt)


def _main(tmp_path, code: str, *, ledger=True, monkeypatch=None):
    log = tmp_path / "agent.log"
    log.write_text("старый вывод: Failed to authenticate (ДРУГОЙ прогон)\n", encoding="utf-8")
    argv = ["--timeout-s", "30", "--label", "unit", "--log", str(log)]
    if ledger:
        argv += ["--ledger", str(tmp_path / "runs.jsonl")]
    argv += ["--", sys.executable, "-c", code]
    return crt.main(argv), tmp_path / "runs.jsonl", log


def test_auth_expiry_is_named_and_rc_is_unchanged(tmp_path):
    rc, ledger, _ = _main(tmp_path, "print('Failed to authenticate: OAuth session expired'); raise SystemExit(1)")
    assert rc == 1
    rec = json.loads(ledger.read_text().splitlines()[-1])
    assert (rec["cause"], rec["rc"], rec["label"]) == ("auth_expired", 1, "unit")


def test_only_this_runs_output_is_read(tmp_path):
    """Прошлая ошибка авторизации в том же журнале НЕ приписывается новому падению."""
    rc, ledger, _ = _main(tmp_path, "raise SystemExit(3)")
    rec = json.loads(ledger.read_text().splitlines()[-1])
    assert (rc, rec["cause"]) == (3, "error")


def test_success_is_ok(tmp_path):
    rc, ledger, log = _main(tmp_path, "print('done')")
    assert rc == 0 and json.loads(ledger.read_text())["cause"] == "ok"
    assert "OUTCOME" in log.read_text()


def test_unnamed_ledger_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(crt.LEDGER_ENV, raising=False)
    rc, ledger, log = _main(tmp_path, "print('x')", ledger=False)
    assert rc == 0 and not ledger.exists()
    assert "НЕ записан" not in log.read_text()


def test_timeout_codes_map_to_their_causes():
    assert crt.classify(124, "") == "timeout_closed"
    assert crt.classify(125, "Failed to authenticate") == "timeout_unresolved"
    assert crt.classify(0, "Failed to authenticate") == "ok"


def test_unwritable_ledger_never_changes_the_run_code(tmp_path):
    bad = tmp_path / "file_not_dir"
    bad.write_text("x")
    log = tmp_path / "a.log"
    rc = crt.main(["--timeout-s", "30", "--label", "u", "--log", str(log),
                   "--ledger", str(bad / "runs.jsonl"), "--", sys.executable, "-c", "raise SystemExit(2)"])
    assert rc == 2 and "НЕ записан" in log.read_text()
