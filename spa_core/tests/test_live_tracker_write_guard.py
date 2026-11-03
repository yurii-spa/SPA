"""Мандат 01.11 §4: тест не вправе записать в НАСТОЯЩИЙ трекер владельца. Настоящий прод не трогается: путь
«живого корня по умолчанию» подменяется временным каталогом, и сторож мерится на нём."""
import pytest

from spa_core.owner_queue import queue as q
from spa_core.utils import atomic, live_paths


@pytest.fixture
def fake_live(tmp_path, monkeypatch):
    live = tmp_path / "live"
    (live / "nimbalyst-local" / "tracker").mkdir(parents=True)
    monkeypatch.setattr(live_paths, "DEFAULT_LIVE_ROOT", live)
    return live / "nimbalyst-local" / "tracker"


def test_a_test_cannot_write_into_the_real_tracker(fake_live):
    target = fake_live / "inbox-from-a-test.md"
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        atomic.atomic_save_text("x", str(target))
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        atomic.atomic_save({"a": 1}, str(fake_live / "x.json"))
    assert not target.exists()


def test_the_real_door_of_the_queue_is_covered(fake_live):
    with pytest.raises(atomic.LiveTrackerWriteInTest):
        q.create_card("inbox", "Задание из теста", tracker_dir=fake_live)
    assert list(fake_live.iterdir()) == []


def test_other_paths_and_explicit_trap_are_untouched(fake_live, tmp_path):
    trap = tmp_path / "trap"
    p = q.create_card("inbox", "Задание из теста", tracker_dir=trap)
    assert p.exists() and p.parent == trap                      # явная ловушка — работает как раньше
    atomic.atomic_save_text("ok", str(tmp_path / "elsewhere.md"))


def test_production_processes_are_not_affected(fake_live, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)   # не pytest ⇒ это агент, ему писать можно
    atomic.atomic_save_text("x", str(fake_live / "agent-card.md"))
    assert (fake_live / "agent-card.md").exists()
