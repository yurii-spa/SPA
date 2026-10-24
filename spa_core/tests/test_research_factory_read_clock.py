# LLM_FORBIDDEN
"""B-11 (ARB 2026-10-24): `research_factory.read.latest` не берёт стенные часы в документ.

* пустая лента — `generated_at` = None (не «прогон только что»);
* лента с прогоном — `generated_at` = время РЕАЛЬНОГО события, при любых настоящих часах;
* момент вызывающего (`now=`) — опора суждений о свежести, когда момента события нет.
Часы управляемые (подмена `read.datetime`), паузы нет.
"""
# FROZEN-DATE-OK: injected-clock — NOW передаётся run_once(…, NOW) и latest(now=…); стенные часы подменены
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from spa_core.research_factory import read

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


class _Wall:
    def __init__(self, real, at):
        self._real, self.at = real, at

    def now(self, tz=None):
        return self.at.astimezone(tz) if tz else self.at.replace(tzinfo=None)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_an_empty_ledger_has_no_moment_whatever_the_wall_clock(tmp_path, monkeypatch):
    docs = []
    for wall in (NOW + timedelta(days=1), NOW + timedelta(days=9, seconds=3)):
        monkeypatch.setattr(read, "datetime", _Wall(datetime, wall))
        docs.append(read.latest(tmp_path, now=NOW))
    assert docs[0]["generated_at"] is None and docs[0] == docs[1]


def test_a_recorded_run_keeps_its_own_time_whatever_the_wall_clock(tmp_path, monkeypatch):
    import spa_core.research_factory.run as run_mod
    monkeypatch.setattr(run_mod, "_discover_scanners", lambda: [])
    run_mod.run_once(tmp_path, NOW)
    seen = []
    for wall in (NOW + timedelta(days=2), NOW + timedelta(days=40)):
        monkeypatch.setattr(read, "datetime", _Wall(datetime, wall))
        seen.append(read.latest(tmp_path)["generated_at"])
    assert seen[0] == seen[1] and seen[0] is not None
    assert seen[0].startswith(NOW.strftime("%Y-%m-%dT%H:%M")), seen[0]
