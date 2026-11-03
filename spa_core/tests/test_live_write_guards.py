"""ARB-мандат 02 п. 1 и п. 3: тест и диагностика не пишут ни в настоящий LaunchAgents, ни в настоящий трекер владельца.

Настоящие пути не трогаются: «домашний каталог» и «живой корень» подменяются временными, сторож мерится на них.
Положительный контроль самого класса: `plutil -extract … json` БЕЗ `-o -` перезаписывает plist (так 01.11 испорчены
два живых plist флота), а читалка `plist_read` — нет."""
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from spa_core.owner_queue import owner_answer as oa
from spa_core.owner_queue import queue as q
from spa_core.telegram import inbox_intake as ii
from spa_core.utils import atomic, live_paths, plist_read

REPO = Path(__file__).resolve().parents[2]


def _md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def plist(tmp_path):
    p = tmp_path / "com.spa.demo.plist"
    with open(p, "wb") as fh:
        plistlib.dump({"Label": "com.spa.demo", "StartCalendarInterval": {"Hour": 9, "Minute": 45}}, fh)
    return p


@pytest.mark.skipif(shutil.which("plutil") is None, reason="plutil есть только на macOS — на Linux класс не воспроизводится")
def test_control_plutil_extract_json_without_o_overwrites_the_plist(plist):
    before = _md5(plist)
    subprocess.run(["plutil", "-extract", "StartCalendarInterval", "json", str(plist)], capture_output=True)
    assert _md5(plist) != before                                      # ровно авария 01.11
    assert json.loads(plist.read_text()) == {"Hour": 9, "Minute": 45}


def test_plist_reader_never_writes(plist):
    before = _md5(plist)
    assert plist_read.extract(plist, "StartCalendarInterval") == {"Hour": 9, "Minute": 45}
    assert plist_read.read_plist(plist)["Label"] == "com.spa.demo"
    assert _md5(plist) == before


def test_plist_reader_names_a_corrupted_file(tmp_path):
    bad = tmp_path / "bad.plist"
    bad.write_text('{"Hour":9,"Minute":45}')
    with pytest.raises(plist_read.PlistUnreadable):
        plist_read.read_plist(bad)


def test_a_test_cannot_write_into_launchagents(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(atomic.LaunchAgentsWriteInTest):
        atomic.atomic_save_text("<plist/>", str(home / "Library" / "LaunchAgents" / "com.spa.x.plist"))
    with pytest.raises(atomic.LaunchAgentsWriteInTest):
        atomic.atomic_save({"a": 1}, str(home / "Library" / "LaunchAgents" / "x.json"))
    atomic.atomic_save_text("ok", str(home / "elsewhere.plist"))          # рядом — можно
    assert list((home / "Library" / "LaunchAgents").iterdir()) == []


def test_the_permission_model_denies_plutil_extract_and_launchagents_writes():
    deny = json.loads((REPO / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert "Bash(plutil -extract:*)" in deny
    assert "Write(~/Library/LaunchAgents/**)" in deny and "Edit(~/Library/LaunchAgents/**)" in deny


# ── трекер владельца: известные альтернативные двери записи ───────────────────────────────────────────────────
@pytest.fixture
def live_tracker(tmp_path, monkeypatch):
    live = tmp_path / "live"
    tr = live / "nimbalyst-local" / "tracker"
    tr.mkdir(parents=True)
    monkeypatch.setattr(live_paths, "DEFAULT_LIVE_ROOT", live)
    return tr


def test_intake_door_is_refused(live_tracker):
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        ii.save_inbox_task("задание из теста", source="telegram", tracker_dir=live_tracker, merge_open_twin=False)


def test_status_probe_and_owner_answer_doors_are_refused(live_tracker, tmp_path):
    card = live_tracker / "inbox-existing.md"
    card.write_text("---\ntitle: t\nstatus: new\n---\nbody\n", encoding="utf-8")   # сцена готовит файл сама
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        q.set_status(card, "in-progress")
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        q.set_acceptance_probe(card, "never_used_probe")
    od = live_tracker / "owner-decision-x.md"
    od.write_text("---\ntitle: t\nstatus: needs-owner\n---\n## Варианты\n1. Да\n", encoding="utf-8")
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        oa.record_owner_answer(od, choice_num="1", choice_label="Да", actor_chat_id="1", owner_chat_id="1")
    assert "status: new" in card.read_text() and "status: needs-owner" in od.read_text()   # не тронуты


def test_queue_cli_door_is_refused(live_tracker):
    import importlib.util
    spec = importlib.util.spec_from_file_location("_oq", REPO / "scripts" / "orchestrator_queue.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        m.main(["create", "--type", "inbox", "--title", "из теста", "--tracker-dir", str(live_tracker)])
    assert list(live_tracker.glob("inbox-*.md")) == []
