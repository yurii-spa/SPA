"""
Tests for scripts/pat_rotation_helper.py — MP-071
Run: pytest spa_core/tests/test_pat_rotation.py -v
"""

# FROZEN-DATE-OK: injected-clock — каждая литеральная дата здесь идёт В ПАРЕ с
# `now=`/`state_file=`, отданными коду под проверкой (`_compute_status(state, now=…)`,
# `cmd_mark_rotated(now=…, state_file=…)`), и ВСЕ отметки выведены из того же якоря:
# 2026-08-25 → 2026-11-23 это +90 дней, 89 дней это тот же якорь при now=2026-08-26,
# 2026-01-01/2026-04-01 сравниваются только с переданным now. Обе стороны закреплены,
# календарь на вердикт не влияет — это преференция #1 `.claude/rules/deployment.md`,
# а не литерал против настенных часов. Ни одна дата не сверяется с `date.today()`:
# фикстуры `state_ok`/`state_warning`/`state_overdue` относительные и такими остались.

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pytest

# Allow importing the script from the project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import pat_rotation_helper as prh


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_state_file(tmp_path, monkeypatch):
    """Redirect STATE_FILE to a temp directory for isolation."""
    fake_state = tmp_path / "data" / "pat_rotation_state.json"
    monkeypatch.setattr(prh, "STATE_FILE", fake_state)
    return fake_state


@pytest.fixture()
def state_ok(tmp_state_file):
    """State with 60 days remaining (well within threshold)."""
    today = date.today()
    last = today - timedelta(days=30)
    nxt = today + timedelta(days=60)
    data = {
        "last_rotation": last.isoformat(),
        "next_rotation": nxt.isoformat(),
        "keychain_service": "spa-claude-pat",
    }
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_state_file, "w") as f:
        json.dump(data, f)
    return data


@pytest.fixture()
def state_warning(tmp_state_file):
    """State with 7 days remaining (inside 14-day warning window)."""
    today = date.today()
    last = today - timedelta(days=83)
    nxt = today + timedelta(days=7)
    data = {
        "last_rotation": last.isoformat(),
        "next_rotation": nxt.isoformat(),
        "keychain_service": "spa-claude-pat",
    }
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_state_file, "w") as f:
        json.dump(data, f)
    return data


@pytest.fixture()
def state_overdue(tmp_state_file):
    """State that is 5 days overdue."""
    today = date.today()
    last = today - timedelta(days=95)
    nxt = today - timedelta(days=5)
    data = {
        "last_rotation": last.isoformat(),
        "next_rotation": nxt.isoformat(),
        "keychain_service": "spa-claude-pat",
    }
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_state_file, "w") as f:
        json.dump(data, f)
    return data


# ────────────────────────────────────────────────────────────────────────────
# 1. Отсутствующее состояние = «НЕ ИЗВЕСТНО», а не «ротация была сегодня»
#
# НАМЕРЕННАЯ ПРАВКА ТЕСТОВ (инвариант #16, обоснование — здесь, в теле коммита
# и в docs/journal/2026-W35.md). Три теста этого раздела —
# `test_state_created_when_absent`, `test_state_created_next_rotation_is_90_days`,
# `test_state_created_contains_keychain_service` — ЗАКРЕПЛЯЛИ дефект, а не защищали
# от него: они требовали, чтобы `_load_state()` при отсутствующем файле СОЧИНИЛ
# `last_rotation = сегодня`. Именно из-за этого `--check` возвращал 0 ровно потому,
# что его спросили впервые (карточка `inbox-strazh-rotatsii-pat-sam-sochinyaet-datu`,
# замер цикла #379: в прод-дереве файла не было, один `--status` создал его с датой,
# в которую никакой ротации не было).
#
# Проверка не ослаблена, а РАЗВЁРНУТА: вместо «файл создаётся» теперь проверяется
# «файл НЕ создаётся, а состояние называется неизвестным», и к этому добавлены
# проверки эффекта (`--check` = 1, `--status` = 2), которых не было вовсе. Тесты
# ниже — положительные контроли: на НЕИСПРАВЛЕННОМ модуле каждый краснеет.
# ────────────────────────────────────────────────────────────────────────────

def test_absent_state_is_not_invented(tmp_state_file):
    """Нет файла ⇒ `_load_state` возвращает None и НИЧЕГО не пишет.

    Положительный контроль: на старом модуле здесь возвращался словарь с
    `last_rotation = сегодня`, а файл появлялся на диске.
    """
    assert not tmp_state_file.exists()
    assert prh._load_state() is None
    assert not tmp_state_file.exists(), "страж сочинил состояние, о котором отчитывается"


def test_absent_state_stays_absent_after_every_read_command(tmp_state_file):
    """Ни `--check`, ни `--status`, ни режим по умолчанию не создают состояние."""
    for argv in ([], ["--check"], ["--status"]):
        prh.main(argv)
        assert not tmp_state_file.exists(), f"{argv or ['(default)']} создал файл состояния"


def test_check_refuses_when_rotation_date_unknown(tmp_state_file):
    """`--check` при неизвестной дате = 1 (fail-CLOSED), критерий карточки.

    Положительный контроль: на старом модуле ровно этот вызов давал 0.
    """
    assert not tmp_state_file.exists()
    assert prh.main(["--check"]) == 1


def test_status_exit_2_when_rotation_date_unknown(tmp_state_file, capsys):
    """`--status` при неизвестной дате: код 2 («не измерено») + honest JSON."""
    assert prh.main(["--status"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["rotation_date_known"] is False
    assert "НЕ ИЗВЕСТНА" in data["unknown_reason"]


def test_unknown_status_carries_no_falsy_judgment_keys(tmp_state_file):
    """У статуса «не знаю» ключей-суждений НЕТ вовсе — присутствующий и ложный ключ
    читается наивным потребителем как «всё хорошо», и именно так дефект и держался."""
    status = prh._compute_status(prh._load_state(), now=date(2026, 8, 25))
    for key in ("days_until_rotation", "is_overdue", "needs_rotation_soon",
                "last_rotation", "next_rotation"):
        assert key not in status, f"ключ {key} присутствует в статусе «не измерено»"


def test_default_mode_refuses_when_rotation_date_unknown(tmp_state_file, capsys):
    """Режим по умолчанию печатает ОТКАЗ и выходит 1, а не «✅ PAT rotation OK»."""
    assert prh.main([]) == 1
    out = capsys.readouterr().out
    assert "НЕ ИЗВЕСТНА" in out
    assert "✅" not in out


def test_unreadable_state_is_unknown_not_a_crash(tmp_state_file):
    """Битый JSON — тот же вид, что «файла нет»: наблюдения нет, ответа «ok» тоже."""
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_state_file.write_text("{ это не json", encoding="utf-8")
    assert prh._load_state() is None
    assert prh.main(["--check"]) == 1


def test_state_without_any_usable_date_is_unknown(tmp_state_file):
    """Словарь без пригодной даты раньше ронял KeyError/ValueError наружу."""
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_state_file.write_text(json.dumps({"keychain_service": "spa-claude-pat"}),
                              encoding="utf-8")
    status = prh._compute_status(prh._load_state(), now=date(2026, 8, 25))
    assert status["rotation_date_known"] is False
    assert prh.main(["--check"]) == 1


def test_mark_rotated_is_the_only_writer(tmp_state_file):
    """Обе стороны: до отметки — отказ, после отметки — счётчик идёт (обратный контроль)."""
    assert prh.main(["--check"]) == 1
    assert not tmp_state_file.exists()

    prh.cmd_mark_rotated(now=date(2026, 8, 25), state_file=tmp_state_file)

    assert tmp_state_file.exists()
    written = json.loads(tmp_state_file.read_text())
    assert written["last_rotation"] == "2026-08-25"
    assert written["next_rotation"] == "2026-11-23"  # +90 дней, посчитано вручную

    status = prh._compute_status(prh._load_state(), now=date(2026, 8, 26))
    assert status["rotation_date_known"] is True
    assert status["days_until_rotation"] == 89
    assert prh.cmd_check(status) == 0


def test_now_is_an_input_not_the_wall_clock(tmp_state_file):
    """Время — вход: обе стороны сравнения закреплены, тест не зависит от календаря
    (`.claude/rules/deployment.md`, раздел про фиксированные даты)."""
    state = {"last_rotation": "2026-01-01", "next_rotation": "2026-04-01",
             "keychain_service": "spa-claude-pat"}
    assert prh._compute_status(state, now=date(2026, 3, 1))["days_until_rotation"] == 31
    assert prh._compute_status(state, now=date(2026, 4, 1))["days_until_rotation"] == 0
    assert prh._compute_status(state, now=date(2026, 4, 10))["is_overdue"] is True
    # тот же вход, другой «сейчас» ⇒ другой ответ: часы действительно снаружи
    assert prh._compute_status(state, now=date(2026, 3, 1))["needs_rotation_soon"] is False
    assert prh._compute_status(state, now=date(2026, 3, 25))["needs_rotation_soon"] is True


def test_state_loaded_from_existing_file(tmp_state_file, state_ok):
    """_load_state returns existing state without overwriting it."""
    loaded = prh._load_state()
    assert loaded["last_rotation"] == state_ok["last_rotation"]
    assert loaded["next_rotation"] == state_ok["next_rotation"]


# ────────────────────────────────────────────────────────────────────────────
# 2. days_until_rotation
# ────────────────────────────────────────────────────────────────────────────

def test_days_until_rotation_ok(state_ok):
    """With 60 days left, days_until_rotation returns ~60."""
    status = prh._compute_status(state_ok)
    assert status["days_until_rotation"] == 60


def test_days_until_rotation_warning(state_warning):
    """With 7 days left, days_until_rotation returns 7."""
    status = prh._compute_status(state_warning)
    assert status["days_until_rotation"] == 7


def test_days_until_rotation_overdue(state_overdue):
    """Overdue state returns negative days_until_rotation."""
    status = prh._compute_status(state_overdue)
    assert status["days_until_rotation"] == -5


def test_days_until_rotation_exact_boundary(tmp_state_file):
    """Exactly on the next_rotation date → 0 days."""
    today = date.today()
    data = {
        "last_rotation": (today - timedelta(days=90)).isoformat(),
        "next_rotation": today.isoformat(),
        "keychain_service": prh.KEYCHAIN_SERVICE,
    }
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_state_file, "w") as f:
        json.dump(data, f)
    status = prh._compute_status(data)
    assert status["days_until_rotation"] == 0


# ────────────────────────────────────────────────────────────────────────────
# 3. Warning threshold
# ────────────────────────────────────────────────────────────────────────────

def test_no_warning_when_ok(state_ok):
    """60 days remaining → needs_rotation_soon is False."""
    status = prh._compute_status(state_ok)
    assert status["needs_rotation_soon"] is False


def test_warning_triggered_at_13_days(tmp_state_file):
    """13 days remaining → needs_rotation_soon is True."""
    today = date.today()
    data = {
        "last_rotation": (today - timedelta(days=77)).isoformat(),
        "next_rotation": (today + timedelta(days=13)).isoformat(),
        "keychain_service": prh.KEYCHAIN_SERVICE,
    }
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_state_file, "w") as f:
        json.dump(data, f)
    status = prh._compute_status(data)
    assert status["needs_rotation_soon"] is True


def test_warning_not_triggered_at_14_days(tmp_state_file):
    """Exactly 14 days remaining → needs_rotation_soon is False (boundary)."""
    today = date.today()
    data = {
        "last_rotation": (today - timedelta(days=76)).isoformat(),
        "next_rotation": (today + timedelta(days=14)).isoformat(),
        "keychain_service": prh.KEYCHAIN_SERVICE,
    }
    tmp_state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_state_file, "w") as f:
        json.dump(data, f)
    status = prh._compute_status(data)
    assert status["needs_rotation_soon"] is False


def test_overdue_triggers_warning(state_overdue):
    """Overdue state → both is_overdue and needs_rotation_soon are True."""
    status = prh._compute_status(state_overdue)
    assert status["is_overdue"] is True
    assert status["needs_rotation_soon"] is True


# ────────────────────────────────────────────────────────────────────────────
# 4. --mark-rotated
# ────────────────────────────────────────────────────────────────────────────

def test_mark_rotated_updates_last_rotation(tmp_state_file, state_ok, capsys):
    """--mark-rotated sets last_rotation to today."""
    exit_code = prh.main(["--mark-rotated"])
    assert exit_code == 0
    state = json.loads(tmp_state_file.read_text())
    assert state["last_rotation"] == date.today().isoformat()


def test_mark_rotated_sets_next_rotation_90_days(tmp_state_file, state_ok, capsys):
    """--mark-rotated sets next_rotation to today + 90 days."""
    prh.main(["--mark-rotated"])
    state = json.loads(tmp_state_file.read_text())
    expected = (date.today() + timedelta(days=90)).isoformat()
    assert state["next_rotation"] == expected


def test_mark_rotated_preserves_keychain_service(tmp_state_file, state_ok, capsys):
    """--mark-rotated preserves the keychain_service from existing state."""
    prh.main(["--mark-rotated"])
    state = json.loads(tmp_state_file.read_text())
    assert state["keychain_service"] == state_ok["keychain_service"]


def test_mark_rotated_atomic_write(tmp_state_file, state_ok, monkeypatch, capsys):
    """_atomic_write produces no leftover tmp file after successful write."""
    prh.main(["--mark-rotated"])
    tmp_files = list(tmp_state_file.parent.glob(".pat_rotation_tmp_*"))
    assert tmp_files == [], f"Leftover tmp files: {tmp_files}"


# ────────────────────────────────────────────────────────────────────────────
# 5. --check exit codes
# ────────────────────────────────────────────────────────────────────────────

def test_check_exit_0_when_ok(tmp_state_file, state_ok):
    """--check returns exit code 0 when rotation is not imminent."""
    exit_code = prh.main(["--check"])
    assert exit_code == 0


def test_check_exit_1_when_warning(tmp_state_file, state_warning):
    """--check returns exit code 1 when within warning threshold."""
    exit_code = prh.main(["--check"])
    assert exit_code == 1


def test_check_exit_1_when_overdue(tmp_state_file, state_overdue):
    """--check returns exit code 1 when rotation is overdue."""
    exit_code = prh.main(["--check"])
    assert exit_code == 1


# ────────────────────────────────────────────────────────────────────────────
# 6. --status JSON output
# ────────────────────────────────────────────────────────────────────────────

def test_status_outputs_valid_json(tmp_state_file, state_ok, capsys):
    """--status prints parseable JSON."""
    prh.main(["--status"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, dict)


def test_status_json_contains_required_keys(tmp_state_file, state_ok, capsys):
    """--status JSON includes all expected keys."""
    prh.main(["--status"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    for key in ("today", "last_rotation", "next_rotation",
                 "days_until_rotation", "is_overdue", "needs_rotation_soon",
                 "rotation_date_known"):
        assert key in data, f"Missing key: {key}"
    assert data["rotation_date_known"] is True


def test_status_exit_code_is_0_when_measured(tmp_state_file, state_ok):
    """--status = 0, но только когда дата ИЗМЕРЕНА (неизмеренная — 2, см. раздел 1)."""
    exit_code = prh.main(["--status"])
    assert exit_code == 0


# ────────────────────────────────────────────────────────────────────────────
# 7. Default mode (human-readable output)
# ────────────────────────────────────────────────────────────────────────────

def test_default_ok_exits_0(tmp_state_file, state_ok):
    """Default mode exits 0 when no rotation needed."""
    assert prh.main([]) == 0


def test_default_warning_exits_1(tmp_state_file, state_warning):
    """Default mode exits 1 when rotation warning is active."""
    assert prh.main([]) == 1


def test_default_warning_prints_checklist(tmp_state_file, state_warning, capsys):
    """Default mode prints rotation checklist when warning is active."""
    prh.main([])
    out = capsys.readouterr().out
    assert "PAT" in out
    assert "GitHub" in out.upper() or "github" in out.lower()


# ────────────────────────────────────────────────────────────────────────────
# 8. PAT never read
# ────────────────────────────────────────────────────────────────────────────

def test_no_pat_token_in_source():
    """The source file must not contain any hardcoded PAT-like strings."""
    source = (_PROJECT_ROOT / "scripts" / "pat_rotation_helper.py").read_text()
    # GitHub PATs start with ghp_ or github_pat_
    import re
    forbidden = re.findall(r"(ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)", source)
    assert forbidden == [], f"Hardcoded PAT tokens found: {forbidden}"


def test_keychain_read_never_called_during_status(tmp_state_file, state_ok, monkeypatch):
    """subprocess/os.popen/security CLI is never invoked during status check."""
    import subprocess
    original_run = subprocess.run
    calls = []

    def fake_run(*a, **kw):
        calls.append(a)
        return original_run(*a, **kw)

    monkeypatch.setattr(subprocess, "run", fake_run)
    prh.main(["--status"])
    keychain_calls = [c for c in calls if "security" in str(c)]
    assert keychain_calls == [], f"Unexpected keychain calls: {keychain_calls}"
