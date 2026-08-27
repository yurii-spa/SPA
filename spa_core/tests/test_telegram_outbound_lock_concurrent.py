"""spa_core/tests/test_telegram_outbound_lock_concurrent.py

Реальный межпроцессный прогон ``telegram_client.outbound_lock()`` — не юнит-имитация.

Зачем (карточка про безопасность 2 параллельных циклов оркестратора, замер 26.08):
``guard_outbound`` РЕШАЕТ «слать/не слать» чтением истории и фиксирует решение записью
в неё же, которая происходит ПОСЛЕ фактической отправки. При одном процессе-отправителе
окно между чтением и записью неопасно (следующий вызов — от того же процесса,
последовательно). При ДВУХ параллельных процессах (ровно то, что владелец хочет включить)
оба читают «повторов нет» одновременно и оба шлют — дубль владельцу. Ревью безопасности
параллельных циклов явно потребовало «live two-process dry run, not just static reading» —
статическое чтение кода не доказывает, что лок реально исключает пересечение по времени
у ДВУХ ОТДЕЛЬНЫХ ОС-процессов, только у последовательных вызовов внутри одного.

Метод: два настоящих ``python3`` процесса (``subprocess.Popen``, не ``fork`` — иначе
путь лока унаследовался бы уже вычисленным из родителя и тест проверял бы
не то) входят в ``outbound_lock()`` на один и тот же файл (``SPA_DATA_DIR`` общий), каждый
спит внутри критической секции и пишет свои метки времени входа/выхода. Тест сравнивает
интервалы — они обязаны НЕ пересекаться. Часы — ``time.time()`` (wall clock), сравнимы
между процессами на одной машине без дополнительных допущений.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("python3") is None and sys.executable is None,
    reason="нужен настоящий python3-интерпретатор для дочерних процессов",
)

_WORKER = r"""
import os, sys, time
sys.path.insert(0, {root!r})
from spa_core.alerts import telegram_client as tc
sleep_s = float(sys.argv[1])
out_path = sys.argv[2]
with tc.outbound_lock():
    enter = time.time()
    time.sleep(sleep_s)
    exitt = time.time()
with open(out_path, "w") as f:
    f.write("%r %r" % (enter, exitt))
"""


def _run_worker(tmp_path: Path, sleep_s: float, out_name: str):
    out_path = tmp_path / out_name
    script = _WORKER.format(root=str(ROOT))
    env = dict(os.environ)
    env["SPA_DATA_DIR"] = str(tmp_path)
    env.pop("PYTEST_CURRENT_TEST", None)  # дочерний процесс — не под pytest
    return subprocess.Popen(
        [sys.executable, "-c", script, str(sleep_s), str(out_path)],
        env=env, cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ), out_path


class TestOutboundLockRealConcurrency:
    def test_two_real_processes_never_overlap_in_critical_section(self, tmp_path):
        proc_a, out_a = _run_worker(tmp_path, 0.4, "a.out")
        proc_b, out_b = _run_worker(tmp_path, 0.4, "b.out")

        stdout_a, stderr_a = proc_a.communicate(timeout=10)
        stdout_b, stderr_b = proc_b.communicate(timeout=10)
        assert proc_a.returncode == 0, f"процесс A упал: {stderr_a}"
        assert proc_b.returncode == 0, f"процесс B упал: {stderr_b}"

        a_enter, a_exit = (float(x) for x in out_a.read_text().split())
        b_enter, b_exit = (float(x) for x in out_b.read_text().split())

        overlap = max(a_enter, b_enter) < min(a_exit, b_exit)
        assert not overlap, (
            f"критические секции ПЕРЕСЕКЛИСЬ: A=({a_enter:.3f},{a_exit:.3f}) "
            f"B=({b_enter:.3f},{b_exit:.3f}) — лок не даёт взаимного исключения"
        )
        # Обе секции реально шли ~0.4с — не «повезло», а лок держал их порознь.
        assert (a_exit - a_enter) >= 0.35
        assert (b_exit - b_enter) >= 0.35

    def test_lock_path_is_shared_across_the_two_processes(self, tmp_path):
        """Оба процесса лочат ОДИН и тот же файл (общий SPA_DATA_DIR) — иначе тест
        выше ничего бы не проверял (два разных лока никогда не мешают друг другу)."""
        script = (
            "import sys; sys.path.insert(0, {root!r})\n"
            "from spa_core.alerts import telegram_client as tc\n"
            "print(tc._outbound_lock_path())\n"
        ).format(root=str(ROOT))
        env = dict(os.environ)
        env["SPA_DATA_DIR"] = str(tmp_path)
        env.pop("PYTEST_CURRENT_TEST", None)
        out1 = subprocess.run([sys.executable, "-c", script], env=env, cwd=str(ROOT),
                              capture_output=True, text=True, timeout=10)
        out2 = subprocess.run([sys.executable, "-c", script], env=env, cwd=str(ROOT),
                              capture_output=True, text=True, timeout=10)
        assert out1.returncode == 0, out1.stderr
        assert out2.returncode == 0, out2.stderr
        assert out1.stdout.strip() == out2.stdout.strip()
        assert out1.stdout.strip() == str(tmp_path / ".telegram_outbound.lock")
