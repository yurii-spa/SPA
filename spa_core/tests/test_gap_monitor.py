"""MP-009: тесты gap_monitor — детектор пропущенных дней paper trading цикла."""
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from spa_core.paper_trading import gap_monitor


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Перенаправляет файлы gap_monitor во временную директорию."""
    equity = tmp_path / "equity_curve_daily.json"
    status = tmp_path / "gap_monitor.json"
    monkeypatch.setattr(gap_monitor, "DATA_DIR", tmp_path)
    monkeypatch.setattr(gap_monitor, "EQUITY_FILE", equity)
    monkeypatch.setattr(gap_monitor, "GAP_STATUS_FILE", status)
    return tmp_path, equity, status


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_ok(env):
    _, equity, _ = env
    equity.write_text(json.dumps([
        {"timestamp": _iso(5), "is_demo": False, "equity": 100010.0},
    ]))
    r = gap_monitor.check_gaps()
    assert r["gap_detected"] is False
    assert r["status"] == "ok"


def test_gap(env):
    _, equity, _ = env
    equity.write_text(json.dumps([
        {"timestamp": _iso(30), "is_demo": False, "equity": 100010.0},
    ]))
    r = gap_monitor.check_gaps()
    assert r["gap_detected"] is True
    assert r["status"] == "gap"


def test_no_file(env):
    r = gap_monitor.check_gaps()
    assert r["gap_detected"] is True
    assert r["status"] == "no_data"


def test_only_demo_entries(env):
    _, equity, _ = env
    equity.write_text(json.dumps([
        {"timestamp": _iso(1), "is_demo": True},
        {"timestamp": _iso(2), "is_demo": True},
    ]))
    r = gap_monitor.check_gaps()
    assert r["gap_detected"] is True
    assert r["status"] == "no_real_entries"


def test_no_timestamp(env):
    _, equity, _ = env
    equity.write_text(json.dumps([
        {"is_demo": False, "equity": 100000.0},
    ]))
    r = gap_monitor.check_gaps()
    assert r["gap_detected"] is True
    assert r["status"] == "no_timestamp"


def test_write_atomic(env):
    _, equity, status = env
    equity.write_text(json.dumps([
        {"timestamp": _iso(1), "is_demo": False},
    ]))
    gap_monitor.check_gaps()
    assert status.exists()
    on_disk = json.loads(status.read_text())
    assert on_disk["gap_detected"] is False
    assert not status.with_suffix(".tmp").exists()


def test_exit_code(env, tmp_path):
    """Standalone-запуск с gap → exit code 1; без gap → 0."""
    project_root = Path(gap_monitor.__file__).parent.parent.parent
    script = (
        "from pathlib import Path\n"
        "import json, sys\n"
        "from spa_core.paper_trading import gap_monitor as gm\n"
        f"gm.EQUITY_FILE = Path({str(tmp_path / 'eq.json')!r})\n"
        f"gm.GAP_STATUS_FILE = Path({str(tmp_path / 'gap.json')!r})\n"
        "r = gm.check_gaps()\n"
        "sys.exit(1 if r['gap_detected'] else 0)\n"
    )
    # gap: файла нет
    proc = subprocess.run([sys.executable, "-c", script], cwd=project_root)
    assert proc.returncode == 1
    # без gap: свежий бар
    (tmp_path / "eq.json").write_text(json.dumps([
        {"timestamp": _iso(1), "is_demo": False},
    ]))
    proc = subprocess.run([sys.executable, "-c", script], cwd=project_root)
    assert proc.returncode == 0


def test_hours_since_calculated(env):
    _, equity, _ = env
    equity.write_text(json.dumps([
        {"timestamp": _iso(10), "is_demo": False},
        {"timestamp": _iso(34), "is_demo": False},
    ]))
    r = gap_monitor.check_gaps()
    # берётся самый свежий бар (10ч назад)
    assert r["hours_since_last_entry"] == pytest.approx(10, abs=0.1)
    assert r["last_entry_date"] is not None
    assert r["gap_detected"] is False


def test_cycle_runner_doc_format(env):
    """Формат документа cycle_runner: is_demo на уровне документа, бары в daily."""
    _, equity, _ = env
    equity.write_text(json.dumps({
        "source": "cycle_runner",
        "is_demo": False,
        "daily": [{"date": datetime.now(timezone.utc).date().isoformat(),
                   "close_equity": 100010.09}],
    }))
    r = gap_monitor.check_gaps()
    assert r["gap_detected"] is False
    assert r["status"] == "ok"


def test_parse_error(env):
    _, equity, _ = env
    equity.write_text("{not valid json")
    r = gap_monitor.check_gaps()
    assert r["gap_detected"] is True
    assert r["status"] == "parse_error"
