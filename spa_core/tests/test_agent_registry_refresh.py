"""Приёмка производителя `data/agent_registry.json` в расписании.

Каждый тест — воспроизведение реальной аварии, а не украшение (`.claude/rules/deployment.md`,
«проверка сторожа сторожей»):

* находка ADR-066 `B2:stale:data/agent_registry.json` — реестр 478ч при SLO 26ч;
* причина: `scripts/build_agent_registry.py` есть и покрыт тестами, но его НИКТО не зовёт
  (последний запуск руками 2026-07-17). Поэтому среди тестов есть тот, что проверяет
  ВЫЗОВ из часового агента, а не работоспособность функции: код, который никто не зовёт,
  проходит любой юнит-тест и при этом мёртв.

Время — вход, а не окружение: `now` фиксирован во всех тестах, литеральных дат в фикстурах
нет (`.claude/rules/deployment.md`, «время в тестах»).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import agent_registry_refresh as arr

NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _write_registry(data_dir: Path, generated_at, **extra) -> Path:
    path = data_dir / arr.REGISTRY_FILENAME
    payload = {"model": "agent_registry", "total_known": 1, "agents": [], **extra}
    if generated_at is not None:
        payload["generated_at"] = generated_at
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fake_builder(marker="rebuilt"):
    calls = []

    def build():
        calls.append(marker)
        return {
            "model": "agent_registry",
            "generated_at": NOW.isoformat(),
            "total_loaded": 70,
            "total_known": 71,
            "agents": [],
        }

    build.calls = calls  # type: ignore[attr-defined]
    return build


# ---------------------------------------------------------------------------
# 1. Сама авария: реестр протух на 478ч
# ---------------------------------------------------------------------------
def test_stale_registry_is_rebuilt(tmp_path):
    """478ч (ровно инцидент 2026-08-05) ⇒ пересборка, отметка становится свежей."""
    _write_registry(tmp_path, (NOW - timedelta(hours=478.1)).isoformat())
    builder = _fake_builder()

    report = arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)

    assert report["status"] == "refreshed"
    assert report["age_hours_before"] == pytest.approx(478.1, abs=0.05)
    assert builder.calls == ["rebuilt"]
    written = json.loads((tmp_path / arr.REGISTRY_FILENAME).read_text(encoding="utf-8"))
    assert written["generated_at"] == NOW.isoformat()
    # и главное — после пересборки возраст внутри SLO сторожа (26ч)
    assert arr.registry_age_hours(tmp_path / arr.REGISTRY_FILENAME, now=NOW) == 0.0


def test_stale_registry_stays_stale_without_the_refresher(tmp_path):
    """Отрицательный контроль: без вызова рефрешера файл не молодеет сам.

    Тест закрепляет, ПОЧЕМУ понадобился этот модуль: сборщик существовал все 478 часов."""
    path = _write_registry(tmp_path, (NOW - timedelta(hours=478.1)).isoformat())
    assert arr.registry_age_hours(path, now=NOW) > 26


# ---------------------------------------------------------------------------
# 2. Свежий реестр не трогаем — иначе часовая перезапись без причины
# ---------------------------------------------------------------------------
def test_fresh_registry_is_not_rebuilt(tmp_path):
    _write_registry(tmp_path, (NOW - timedelta(hours=1)).isoformat())
    builder = _fake_builder()

    report = arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)

    assert report["status"] == "fresh"
    assert builder.calls == []
    assert report["age_hours_before"] == pytest.approx(1.0, abs=0.01)


def test_threshold_is_the_boundary(tmp_path):
    """Ровно на пороге — пересобираем (граница на стороне свежести реестра)."""
    _write_registry(tmp_path, (NOW - timedelta(hours=arr.DEFAULT_MAX_AGE_HOURS)).isoformat())
    builder = _fake_builder()

    assert arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)["status"] == "refreshed"


def test_default_threshold_leaves_room_inside_the_slo():
    """Порог обязан быть заметно меньше SLO сторожа (26ч), иначе первый же пропуск = красный."""
    assert arr.DEFAULT_MAX_AGE_HOURS < 26 / 2


# ---------------------------------------------------------------------------
# 3. Неизвестный возраст = протух (fail-CLOSED), а не «наверное свежий»
# ---------------------------------------------------------------------------
def test_missing_file_is_treated_as_stale(tmp_path):
    builder = _fake_builder()
    report = arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)
    assert report["status"] == "refreshed"
    assert report["age_hours_before"] is None
    assert (tmp_path / arr.REGISTRY_FILENAME).exists()


def test_corrupt_json_is_treated_as_stale(tmp_path):
    (tmp_path / arr.REGISTRY_FILENAME).write_text("{битый", encoding="utf-8")
    builder = _fake_builder()
    assert arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)["status"] == "refreshed"


@pytest.mark.parametrize("bad", [None, "не-дата", 12345, ""])
def test_unreadable_timestamp_is_treated_as_stale(tmp_path, bad):
    _write_registry(tmp_path, bad)
    builder = _fake_builder()
    assert arr.refresh_if_stale(tmp_path, now=NOW, builder=builder)["status"] == "refreshed"


def test_naive_timestamp_is_read_as_utc(tmp_path):
    """Отметка без таймзоны не должна ни падать, ни давать фантомный возраст."""
    naive = (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    path = _write_registry(tmp_path, naive)
    assert arr.registry_age_hours(path, now=NOW) == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# 4. Сторож не убивает то, что охраняет
# ---------------------------------------------------------------------------
def test_builder_failure_never_raises(tmp_path):
    def boom():
        raise RuntimeError("launchctl недоступен")

    report = arr.refresh_if_stale(tmp_path, now=NOW, builder=boom)

    assert report["status"] == "failed"
    assert "launchctl недоступен" in report["error"]


def test_builder_returning_junk_is_a_failure_not_a_write(tmp_path):
    """Реестр без `generated_at` записывать нельзя: он вечно «неизвестного возраста»."""
    report = arr.refresh_if_stale(tmp_path, now=NOW, builder=lambda: {"agents": []})

    assert report["status"] == "failed"
    assert not (tmp_path / arr.REGISTRY_FILENAME).exists()


def test_failed_refresh_does_not_destroy_the_previous_registry(tmp_path):
    """Провал пересборки оставляет старый файл: протухший реестр лучше отсутствующего."""
    path = _write_registry(tmp_path, (NOW - timedelta(hours=478)).isoformat(), total_known=99)

    def boom():
        raise RuntimeError("нет прав")

    arr.refresh_if_stale(tmp_path, now=NOW, builder=boom)

    assert json.loads(path.read_text(encoding="utf-8"))["total_known"] == 99


# ---------------------------------------------------------------------------
# 5. Главный тест: часовой агент РЕАЛЬНО зовёт рефрешер
#    (класс «код доставлен, но никогда не вызывается» — причина этой находки)
# ---------------------------------------------------------------------------
def test_hourly_monitor_actually_calls_refresh(tmp_path, monkeypatch):
    from spa_core.monitoring import agent_health_monitor as ahm

    seen = {}

    def fake_refresh(data_dir, now=None, **kw):
        seen["data_dir"] = Path(data_dir)
        seen["now"] = now
        return {"status": "refreshed", "age_hours_before": 478.1}

    monkeypatch.setattr(ahm, "refresh_if_stale", fake_refresh)
    monitor = ahm.AgentHealthMonitor(
        data_dir=tmp_path,
        launch_agents_dir=tmp_path / "нет-такой-папки",
        launchctl_output="",
        now=NOW,
    )

    report = monitor.run(send=False)

    assert seen["data_dir"] == tmp_path, "часовой агент не позвал рефрешер реестра"
    assert seen["now"] == NOW, "рефрешеру не передали часы монитора"
    # и результат виден снаружи — в самом снимке здоровья, а не только в логе
    assert report["registry_refresh"]["status"] == "refreshed"
    written = json.loads((tmp_path / "agent_health.json").read_text(encoding="utf-8"))
    assert written["registry_refresh"]["age_hours_before"] == 478.1


def test_refresh_survives_a_broken_health_collect(tmp_path, monkeypatch):
    """Реестр обновляется ДАЖЕ ЕСЛИ сбор пульса упал по своей причине.

    Иначе чужая поломка вернула бы ровно ту аварию, которую этот модуль и чинит:
    реестр снова начал бы молча гнить, а виноват был бы совсем другой дефект."""
    from spa_core.monitoring import agent_health_monitor as ahm

    called = []
    monkeypatch.setattr(ahm, "refresh_if_stale",
                        lambda *a, **k: called.append(True) or {"status": "refreshed"})
    monitor = ahm.AgentHealthMonitor(
        data_dir=tmp_path,
        launch_agents_dir=tmp_path / "нет-такой-папки",
        launchctl_output="",
        now=NOW,
    )
    monkeypatch.setattr(monitor, "collect",
                        lambda: (_ for _ in ()).throw(RuntimeError("launchctl умер")))

    report = monitor.run(send=False)

    assert called, "сбор пульса упал — и реестр остался протухшим (порядок вызовов неверен)"
    assert report["overall_status"] == ahm.CRITICAL  # падение самого монитора видно


def test_registry_failure_does_not_break_the_health_snapshot(tmp_path, monkeypatch):
    """Правило 1 в сборе: рефрешер упал ⇒ пульс флота всё равно записан."""
    from spa_core.monitoring import agent_health_monitor as ahm

    monkeypatch.setattr(ahm, "refresh_if_stale",
                        lambda *a, **k: {"status": "failed", "error": "нет прав"})
    monitor = ahm.AgentHealthMonitor(
        data_dir=tmp_path,
        launch_agents_dir=tmp_path / "нет-такой-папки",
        launchctl_output="",
        now=NOW,
    )

    report = monitor.run(send=False)

    assert report.get("overall_status")
    assert "error" not in report, "падение рефрешера уронило сам монитор"
    assert (tmp_path / "agent_health.json").exists()


# ---------------------------------------------------------------------------
# 6. Настоящий производитель, а не подделка: рефрешер умеет его загрузить
# ---------------------------------------------------------------------------
def test_real_builder_is_loadable_and_shaped_right():
    """Без этого теста подмена `builder=` в остальных проверяла бы только саму себя."""
    module = arr._load_builder()
    assert callable(module.build)
    registry = module.build()  # читает launchctl/plists хоста, ничего не пишет
    assert registry["model"] == "agent_registry"
    assert registry["generated_at"]
    assert isinstance(registry["agents"], list)


def test_manifest_no_longer_declares_the_registry_producerless():
    """Манифест — объявленное намерение. Производитель появился ⇒ `producer: null` — ложь."""
    repo = Path(__file__).resolve().parents[2]
    manifest = json.loads((repo / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    entry = next(a for a in manifest["artifacts"]
                 if a["path"] == "data/agent_registry.json")
    assert entry["producer"], "у реестра снова нет объявленного производителя"
