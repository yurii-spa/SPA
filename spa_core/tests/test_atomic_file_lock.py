"""Tests for the AUD-10 cross-process lock helpers in spa_core.utils.atomic.

Covers file_lock (fcntl.flock advisory lock on a sidecar .lock) and
locked_append_ring (locked read-modify-write ring buffer).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.utils.atomic import file_lock, locked_append_ring  # noqa: E402


def test_file_lock_acquires_when_free(tmp_path):
    p = str(tmp_path / "ring.json")
    with file_lock(p) as got:
        assert got is True
    # sidecar lives next to the target, not the target itself
    assert Path(p + ".lock").exists()
    assert not Path(p).exists()


def test_file_lock_mutual_exclusion(tmp_path):
    """A second acquirer cannot take the lock while the first holds it.

    flock locks are per open-file-description, so two independent os.open()
    calls conflict even within the same process — exactly the cross-process
    semantics we rely on.
    """
    p = str(tmp_path / "ring.json")
    with file_lock(p) as got1:
        assert got1 is True
        with file_lock(p, timeout=0.1) as got2:
            assert got2 is False  # held by the outer context → cannot acquire
    # released on exit → acquirable again
    with file_lock(p, timeout=0.5) as got3:
        assert got3 is True


def test_locked_append_ring_appends_and_caps(tmp_path):
    p = str(tmp_path / "ring.json")
    for i in range(5):
        n = locked_append_ring({"i": i}, p, cap=3)
    assert n == 3
    data = json.loads(Path(p).read_text())
    assert data == [{"i": 2}, {"i": 3}, {"i": 4}]


def test_locked_append_ring_list_key_format(tmp_path):
    p = str(tmp_path / "ring.json")
    locked_append_ring({"x": 1}, p, cap=10, list_key="history")
    locked_append_ring({"x": 2}, p, cap=10, list_key="history")
    data = json.loads(Path(p).read_text())
    assert isinstance(data, dict)
    assert data["history"] == [{"x": 1}, {"x": 2}]


def test_locked_append_ring_tolerates_corrupt_file(tmp_path):
    p = tmp_path / "ring.json"
    p.write_text("{not valid json", encoding="utf-8")
    n = locked_append_ring({"i": 0}, str(p), cap=3)
    assert n == 1
    assert json.loads(p.read_text()) == [{"i": 0}]
