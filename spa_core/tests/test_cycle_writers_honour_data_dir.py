"""run_cycle(data_dir=X) пишет состояние цикла В X — и только туда.

Замер 22.10 (одноразовое дерево, audit-хук на open/os.rename): каждый
прогон ``run_cycle(data_dir=tmp)`` — 23 тест-файла, ~3000 записей за один
широкий прогон — переписывал четыре ОТСЛЕЖИВАЕМЫХ файла в ``data/`` ДЕРЕВА
КОДА, мимо переданного каталога:

  * ``adapter_status.json``   ← ``adapter_status_generator.run_and_write()``
    без аргументов (cycle_runner, Step 0-pre);
  * ``gap_monitor.json``, ``risk_alerts.json`` ← ``gap_monitor.check_gaps()``
    без аргументов (cycle_reporting) — монитор к тому же СУДИЛ equity curve
    дерева кода, а не трек этого цикла, хотя MP-111 тремя строками ниже
    читает ``ddir / "gap_monitor.json"``;
  * ``apy_milestone_log.json`` ← ``ApyMilestoneTracker()`` без ``data_dir``.

Дерево кода на хосте владельца — боевое. Значит, тот же набор, запущенный из
``~/Documents/SPA_Claude``, писал в живой ``data/``: CRITICAL-алерт
``cycle_gap`` в ``risk_alerts.json`` или его снятие, чужой статус адаптеров.
И то же самое делал dev-запуск цикла, который write-interlock
(``_cycle_io.resolve_data_dir``) честно увёл в песочницу: interlock
перенаправлял ``ddir``, а эти три писателя ``ddir`` не спрашивали.

Проверка в обе стороны: выход есть в ``tmp`` (положительная сторона — шаг
действительно отработал, а не молча пропущен) И файлы ``data/`` дерева кода
не тронуты ни байтом, ни inode, ни mtime.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from spa_core.paper_trading import cycle_runner as cr
from spa_core.tests.test_cycle_runner_characterization import _run

_CODE_TREE_DATA = Path(cr.__file__).resolve().parents[2] / "data"
_WRITTEN = ("adapter_status.json", "gap_monitor.json", "risk_alerts.json",
            "apy_milestone_log.json")


def _fingerprint(path: Path):
    """(inode, mtime_ns, sha256) — или None, если файла нет. Атомарная запись
    (tmp + os.replace) меняет inode даже при тех же байтах."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())


def test_cycle_writes_its_state_into_the_given_data_dir_not_the_code_tree(tmp_path):
    # Реестр в каталоге цикла есть ⇒ генератор статуса обязан отработать В НЁМ.
    # Содержимое минимально намеренно: предмет — место записи, а не состав.
    (tmp_path / "adapter_registry.json").write_text('{"adapters": {}}', encoding="utf-8")
    before = {n: _fingerprint(_CODE_TREE_DATA / n) for n in _WRITTEN}

    result = _run(tmp_path)
    assert result is not None

    after = {n: _fingerprint(_CODE_TREE_DATA / n) for n in _WRITTEN}
    touched = [n for n in _WRITTEN if before[n] != after[n]]
    assert not touched, (
        f"run_cycle(data_dir={tmp_path}) переписал data/ дерева кода: {touched}"
    )

    # Положительная сторона: каждый из четырёх шагов отработал — в своём каталоге.
    gap = json.loads((tmp_path / "gap_monitor.json").read_text(encoding="utf-8"))
    assert "checked_at" in gap and "gap_detected" in gap
    status = json.loads((tmp_path / "adapter_status.json").read_text(encoding="utf-8"))
    assert "schema_version" in status and "generated_at" in status
    milestone = json.loads((tmp_path / "apy_milestone_log.json").read_text(encoding="utf-8"))
    assert milestone, "apy_milestone_log.json в каталоге цикла пуст"
    # risk_alerts.json пишется только при gap/снятии алерта; здесь трек из одного
    # бара за _NOW ⇒ монитор видит gap и обязан положить алерт в СВОЙ каталог.
    if gap.get("gap_detected"):
        alerts = json.loads((tmp_path / "risk_alerts.json").read_text(encoding="utf-8"))
        assert any(a.get("source") == "gap_monitor" for a in alerts.get("alerts", []))


def test_without_a_registry_the_cycle_keeps_the_status_file_on_disk(tmp_path):
    """Нет реестра в каталоге цикла ⇒ генерировать не из чего. Генератор в этом
    случае пишет статус БЕЗ ЕДИНОГО адаптера; положить его поверх существующего
    файла значило бы выдать «не измерено» за «адаптеров нет» (инв. #17)."""
    seeded = '{"seeded": "by the test", "adapters": {"aave_v3": {"apy_pct": 3.5}}}'
    (tmp_path / "adapter_status.json").write_text(seeded, encoding="utf-8")
    before = _fingerprint(_CODE_TREE_DATA / "adapter_status.json")

    _run(tmp_path)

    # Файл в каталоге цикла законно трогают и другие шаги (MP-389 обновляет его
    # на месте), поэтому сверяется не байт, а то, что его не ЗАМЕНИЛ генератор:
    # посеянное содержимое на месте, документа генератора нет.
    after = json.loads((tmp_path / "adapter_status.json").read_text(encoding="utf-8"))
    assert after.get("seeded") == "by the test"
    assert "aave_v3" in (after.get("adapters") or {})
    assert "schema_version" not in after
    assert _fingerprint(_CODE_TREE_DATA / "adapter_status.json") == before


def test_gap_monitor_judges_and_writes_the_given_data_dir(tmp_path):
    """Сам монитор: явный data_dir ⇒ вход и выход внутри него."""
    from spa_core.paper_trading import gap_monitor as gm

    before = {n: _fingerprint(_CODE_TREE_DATA / n) for n in ("gap_monitor.json", "risk_alerts.json")}
    r = gm.check_gaps(data_dir=tmp_path)
    after = {n: _fingerprint(_CODE_TREE_DATA / n) for n in ("gap_monitor.json", "risk_alerts.json")}

    # В пустом каталоге трека нет — это ответ про ЭТОТ каталог, а не про дерево кода.
    assert r["status"] == "no_data"
    assert json.loads((tmp_path / "gap_monitor.json").read_text())["status"] == "no_data"
    alerts = json.loads((tmp_path / "risk_alerts.json").read_text())["alerts"]
    assert [a["type"] for a in alerts] == ["cycle_gap"]
    assert before == after


def test_hy_regime_log_is_written_where_it_is_read(tmp_path, monkeypatch):
    """Engine B: get_hy_regime() читает ``_HY_REGIME_LOG_PATH``, а запись шла в
    ``<дерево кода>/data/hy_regime_log.json`` — мимо пути чтения. Теперь писатель
    и читатель — один файл; дерево кода не тронуто."""
    from spa_core.paper_trading import hy_cycle

    log_path = tmp_path / "hy_regime_log.json"
    monkeypatch.setattr(hy_cycle, "_HY_REGIME_LOG_PATH", log_path)
    before = _fingerprint(_CODE_TREE_DATA / "hy_regime_log.json")

    hy_cycle.refresh_hy_regime("EXIT", 0.0)

    assert log_path.is_file(), "журнал режима не записан по пути чтения"
    written = json.loads(log_path.read_text(encoding="utf-8"))["current_state"]
    assert hy_cycle.get_hy_regime() == written
    assert _fingerprint(_CODE_TREE_DATA / "hy_regime_log.json") == before
