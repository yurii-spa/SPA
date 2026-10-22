"""Перепись оси РАБОТНИКА зовётся ежечасным пульсом флота, а не лежит файлом.

Карточка `inbox-perepis-osi-rabotnika-napisana-i-ne-pozv`: прибор
`scripts/worker_axis_census.py` (ADR-722, G721 п. 3) пришёл циклом #866 и не звался
ничем — храповик сирот был красен на чистой вершине. Подключение — side-car ежечасного
`agent_health_monitor` по шаблону `_write_orphaned_pytest` (новый агент не добавляется).

Каждая проверка ниже краснеет на своём порванном звене: вызов убран из `main` ·
третий исход схлопнут в «чисто» · находка схлопнута в «чисто» · сломанный прибор
выдаёт выдуманный артефакт. Перепись ИНЪЕКТИРУЕТСЯ: без этого тест судил бы о том,
какие запуски живы на хосте сейчас.

Оффлайн, stdlib, пути инжектируются. LLM_FORBIDDEN.
"""
from __future__ import annotations

import ast
import inspect
import json

from spa_core.monitoring import agent_health_monitor as ahm


def _rep(*, visible: bool = True, measurable: bool = True) -> dict:
    return {
        "rows_total": 10, "env_readable": 4 if measurable else 0,
        "env_blind": 6 if measurable else 10,
        "readable_share": 0.4 if measurable else 0.0,
        "blind_by_class": {"платформенный Apple (/usr/)": 6},
        "axis_measurable": measurable,
        "runs": [{"label": "orchestrator-1-AB", "launcher_pids": [11],
                  "worker_pids": [12] if visible else [], "visible": visible,
                  "counts": {"env": 1 if visible else 0, "cmdline": 0, "unmeasured": 0},
                  "self": []}],
    }


def _doc(tmp_path) -> dict:
    return json.loads((tmp_path / ahm.WORKER_AXIS_ARTIFACT).read_text(encoding="utf-8"))


def test_the_sidecar_is_called_by_the_hourly_agent():
    """Проводка: перепись, которую никто не зовёт, — это ADR-259 в чистом виде."""
    tree = ast.parse(inspect.getsource(ahm.main).lstrip())
    names = {getattr(n.func, "id", None) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "_write_worker_axis_census" in names, "ежечасный агент не зовёт перепись оси"


def test_the_sidecar_calls_the_real_instrument_by_path():
    """Side-car грузит ИМЕННО `scripts/worker_axis_census.py`, а не однофамильца."""
    mod = ahm._load_worker_axis_census()
    assert mod.__file__.endswith("scripts/worker_axis_census.py")
    for attr in ("census", "findings", "NotMeasured"):
        assert hasattr(mod, attr), f"у прибора нет {attr!r} — side-car звал бы пустоту"


def test_a_clean_census_is_written_as_clear(tmp_path):
    ahm._write_worker_axis_census(tmp_path, census=lambda: _rep())
    doc = _doc(tmp_path)
    assert doc["status"] == "clear"
    assert doc["findings"] == []
    assert doc["rows_total"] == 10 and doc["env_readable"] == 4
    assert doc["runs"][0]["visible"] is True


def test_an_invisible_worker_is_a_finding_not_clear(tmp_path):
    """«Запускатель жив, работника не видно» обязано доехать до файла находкой."""
    ahm._write_worker_axis_census(tmp_path, census=lambda: _rep(visible=False))
    doc = _doc(tmp_path)
    assert doc["status"] == "finding", "находка схлопнута в «чисто»"
    assert any("orchestrator-1-AB" in f for f in doc["findings"])


def test_the_third_outcome_reaches_the_artifact(tmp_path):
    """`ps` не ответил ⇒ «НЕ ИЗМЕРЕНО» с причиной, а не «чисто» и не пустой список."""
    mod = ahm._load_worker_axis_census()

    def blind():
        raise mod.NotMeasured("снимок процессов не снят: ps отказал")

    ahm._write_worker_axis_census(tmp_path, census=blind)
    doc = _doc(tmp_path)
    assert doc["status"] == "unmeasured", "третий исход схлопнут"
    assert "ps отказал" in doc["reason"]
    assert doc["findings"] is None, "«не измерено» неотличимо от «находок ноль»"


def test_a_broken_instrument_never_breaks_the_heartbeat(tmp_path, monkeypatch):
    """Прибора нет — пульс флота живёт, а артефакт НЕ выдумывается."""
    monkeypatch.setattr(ahm, "_PROJECT_ROOT", tmp_path / "no_such_tree")
    ahm._write_worker_axis_census(tmp_path)          # не поднимает исключение
    assert not (tmp_path / ahm.WORKER_AXIS_ARTIFACT).is_file(), (
        "прибор не загрузился, а артефакт всё равно записан — это выдуманный ответ")


def test_the_artifact_is_declared_with_its_producer():
    """Объявление в конституции: без него шаг 0-офис файла не откроет, SLO не назначен."""
    from pathlib import Path
    manifest = json.loads((Path(ahm._PROJECT_ROOT) / "architecture" / "manifest.json")
                          .read_text(encoding="utf-8"))
    agent = [a for a in manifest["agents"] if a["label"] == "com.spa.agent_health"][0]
    produced = {p["artifact"] for p in agent["produces"]}
    assert "data/" + ahm.WORKER_AXIS_ARTIFACT in produced
    arts = {a["path"]: a for a in manifest["artifacts"]}
    assert arts["data/" + ahm.WORKER_AXIS_ARTIFACT]["producer"] == "com.spa.agent_health"
