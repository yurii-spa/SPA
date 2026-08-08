"""Замок дневного цикла спрашивает, ЖИВ ЛИ ДЕРЖАТЕЛЬ, а не только возраст файла.

Решение владельца 2026-08-08, вариант 1 карточки
`owner-decision-zamok-dnevnogo-tsikla-ne-sprashivaet-zhi`.

**Замеренная авария, которую воспроизводит каждый тест ниже.** 2026-08-08 03:34 UTC цикл взял
замок и умер, не отпустив его (процесс 99899 мёртв, файл остался). За следующие полтора часа
цикл звали **20 раз, и 18 раз он получил отказ** — при том, что держателя давно не было в живых,
а его номер лежал В САМОМ ФАЙЛЕ ЗАМКА. День трека спасли 26 минут запаса до планового прогона в
06:00 UTC. Пропущенный день не лечится: два таких (19.07 и 27.07) висят навсегда.

**Почему три состояния, а не два.** «Не измерено» (сбой `ps`, битый файл) не имеет права:
* ломать замок — иначе защита от одновременных циклов исчезает при первом же сбое измерения,
  а два цикла, записавшие один день трека, делают трек недостоверным;
* блокировать навсегда — это класс «необратимое не-измерено», уже стоивший очереди владельца.

Поэтому при UNKNOWN работает ПРЕЖНЕЕ правило возраста (2 часа), и это проверяется отдельно.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.paper_trading import cycle_runner as cr


def _write_lock(data_dir, *, pid: int, ts: datetime, pid_start: str | None = None) -> None:
    doc = {"pid": pid, "ts": ts.isoformat()}
    if pid_start is not None:
        doc["pid_start"] = pid_start
    (data_dir / cr.CYCLE_LOCK_FILE).write_text(json.dumps(doc), encoding="utf-8")


def _dead_pid() -> int:
    """Номер, которого заведомо нет в системе."""
    return 999_999


# ── положительный контроль настоящей аварии ─────────────────────────────────

def test_dead_holder_lock_is_broken_immediately(tmp_path, monkeypatch):
    """Ровно ночная авария: держатель мёртв, замок свежий (11 минут).

    До правки здесь был ОТКАЗ — и так 18 раз подряд.
    """
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (1, ""))
    _write_lock(tmp_path, pid=_dead_pid(),
                ts=datetime.now(timezone.utc) - timedelta(minutes=11))

    fd = cr._acquire_cycle_lock(tmp_path)
    assert fd not in (None, False), "мёртвый держатель обязан отдавать замок сразу"
    cr._release_cycle_lock(fd, tmp_path)


def test_dead_holder_is_not_made_to_wait_two_hours(tmp_path, monkeypatch):
    """Даже через минуту после смерти держателя замок обязан сниматься."""
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (1, ""))
    _write_lock(tmp_path, pid=_dead_pid(), ts=datetime.now(timezone.utc))

    fd = cr._acquire_cycle_lock(tmp_path)
    assert fd not in (None, False)
    cr._release_cycle_lock(fd, tmp_path)


# ── контроль в обратную сторону: живой держатель по-прежнему держит ──────────

def test_live_holder_still_refuses(tmp_path, monkeypatch):
    """Без этого «починка» вида «всегда снимай замок» была бы зелёной.

    Два цикла, записавшие один день трека, делают трек недостоверным — это
    ровно то, ради чего замок существует.
    """
    started = "Fri Aug  8 03:34:00 2026"
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (0, started))
    _write_lock(tmp_path, pid=4242,
                ts=datetime.now(timezone.utc) - timedelta(minutes=5),
                pid_start=started)

    assert cr._acquire_cycle_lock(tmp_path) is None


def test_live_holder_refuses_even_when_lock_is_old(tmp_path, monkeypatch):
    """Живость важнее возраста в ОБЕ стороны.

    Прогон 2026-08-05 растянулся с 03:30 до 08:43 (пять часов). По старому
    правилу второй цикл снял бы замок у ЖИВОГО прогона и записал бы день трека
    вдвоём. Живой держатель держит замок независимо от возраста файла.
    """
    started = "Fri Aug  8 00:00:00 2026"
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (0, started))
    _write_lock(tmp_path, pid=4242,
                ts=datetime.now(timezone.utc) - timedelta(hours=5),
                pid_start=started)

    assert cr._acquire_cycle_lock(tmp_path) is None


# ── переиспользованный номер процесса ────────────────────────────────────────

def test_reused_pid_counts_as_dead_holder(tmp_path, monkeypatch):
    """ОС отдала номер другому процессу — держателя нет, замок снимается."""
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (0, "Fri Aug  8 09:00:00 2026"))
    _write_lock(tmp_path, pid=4242,
                ts=datetime.now(timezone.utc) - timedelta(minutes=3),
                pid_start="Fri Aug  8 03:34:00 2026")   # записан ДРУГОЙ старт

    fd = cr._acquire_cycle_lock(tmp_path)
    assert fd not in (None, False)
    cr._release_cycle_lock(fd, tmp_path)


def test_legacy_lock_without_pid_start_uses_start_time(tmp_path, monkeypatch):
    """Замок старого формата: сверка идёт со временем ВЗЯТИЯ замка.

    Процесс, стартовавший ПОСЛЕ того, как замок был взят, физически не может
    быть его держателем.
    """
    taken = datetime(2026, 8, 8, 3, 34, tzinfo=timezone.utc)
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (0, "Fri Aug  8 09:00:00 2026"))
    _write_lock(tmp_path, pid=4242, ts=taken)           # pid_start отсутствует

    fd = cr._acquire_cycle_lock(tmp_path)
    assert fd not in (None, False)
    cr._release_cycle_lock(fd, tmp_path)


# ── «не измерено» — ни поломка, ни вечная блокировка ─────────────────────────

def test_unmeasurable_holder_falls_back_to_age_rule_and_refuses_fresh_lock(tmp_path, monkeypatch):
    """`ps` сломался, замок свежий ⇒ отказ. Сбой измерения не смеет открывать шлюз."""
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (2, ""))
    _write_lock(tmp_path, pid=4242, ts=datetime.now(timezone.utc) - timedelta(minutes=5))

    assert cr._acquire_cycle_lock(tmp_path) is None


def test_unmeasurable_holder_still_expires_by_age(tmp_path, monkeypatch):
    """`ps` сломался, замок старше 2 часов ⇒ снимается.

    Зеркало предыдущего теста: «не измерено» не имеет права стать вечным замком.
    """
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (2, ""))
    path = tmp_path / cr.CYCLE_LOCK_FILE
    _write_lock(tmp_path, pid=4242,
                ts=datetime.now(timezone.utc) - timedelta(hours=3))
    old = os.stat(path).st_mtime - cr.CYCLE_LOCK_STALE_SECONDS - 60
    os.utime(path, (old, old))

    fd = cr._acquire_cycle_lock(tmp_path)
    assert fd not in (None, False)
    cr._release_cycle_lock(fd, tmp_path)


def test_corrupt_lock_file_is_unmeasured_not_dead(tmp_path, monkeypatch):
    """Битый файл замка — «не измерено», а не «держатель мёртв».

    Прочитать «мёртв» из мусора значило бы открыть шлюз одной сломанной записью.
    """
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (0, "Fri Aug  8 03:34:00 2026"))
    (tmp_path / cr.CYCLE_LOCK_FILE).write_text("НЕ JSON{{", encoding="utf-8")

    state, why = cr._holder_state(tmp_path / cr.CYCLE_LOCK_FILE)
    assert state == cr._HOLDER_UNKNOWN, why
    assert cr._acquire_cycle_lock(tmp_path) is None


# ── новый замок несёт время старта своего процесса ───────────────────────────

def test_new_lock_records_pid_start(tmp_path):
    """Без этого поля переиспользованный pid не отличить от живого держателя."""
    fd = cr._acquire_cycle_lock(tmp_path)
    assert fd not in (None, False)
    try:
        doc = json.loads((tmp_path / cr.CYCLE_LOCK_FILE).read_text(encoding="utf-8"))
        assert doc["pid"] == os.getpid()
        assert "pid_start" in doc, "замок обязан писать время старта своего процесса"
        assert doc["pid_start"], "время старта пустое — на этой машине `ps` не отработал"
    finally:
        cr._release_cycle_lock(fd, tmp_path)


def test_holder_state_explains_itself_in_words(tmp_path, monkeypatch):
    """Каждое состояние объясняется словами — иначе отказ снова будет немым.

    18 ночных отказов были немыми ровно потому, что замок не говорил, КОГО он
    считает держателем и почему.
    """
    monkeypatch.setattr(cr, "_ps_start", lambda pid: (1, ""))
    _write_lock(tmp_path, pid=_dead_pid(), ts=datetime.now(timezone.utc))
    state, why = cr._holder_state(tmp_path / cr.CYCLE_LOCK_FILE)
    assert state == cr._HOLDER_DEAD
    assert str(_dead_pid()) in why and "мёртв" in why


def test_ps_failure_never_raises(monkeypatch):
    """Измерение живости не смеет уронить цикл."""
    import subprocess

    def _boom(*a, **k):
        raise OSError("ps недоступен")

    monkeypatch.setattr(subprocess, "run", _boom)
    rc, out = cr._ps_start(1)
    assert rc not in (0, 1) and out == ""


@pytest.mark.parametrize("text,ok", [
    ("Fri Aug  8 03:34:00 2026", True),
    ("Fri  8 Aug 03:34:00 2026", True),
    ("совершенно не дата", False),
    ("", False),
])
def test_ps_lstart_parsing(text, ok):
    assert (cr._parse_ps_lstart(text) is not None) is ok


def test_decisive_control_runs_on_both_versions(tmp_path):
    """РЕШАЮЩИЙ контроль: без единого monkeypatch, работает и на старом коде.

    Остальные тесты этого файла подменяют `_ps_start` — символа, которого на
    версии до правки НЕТ, поэтому там они падают по имени, а не по поведению.
    Этот падает именно ПО ПОВЕДЕНИЮ: свежий замок держит заведомо мёртвый
    номер процесса.

      старый замок: возраст 0 минут < 2 часов  ⇒ ОТКАЗ  (ночная авария, 18 раз)
      новый замок:  держателя нет в живых      ⇒ замок снимается
    """
    _write_lock(tmp_path, pid=_dead_pid(), ts=datetime.now(timezone.utc))
    fd = cr._acquire_cycle_lock(tmp_path)
    assert fd not in (None, False), (
        "свежий замок мёртвого держателя не снят — это и есть авария 2026-08-08")
    cr._release_cycle_lock(fd, tmp_path)
