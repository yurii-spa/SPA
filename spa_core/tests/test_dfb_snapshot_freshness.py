"""DFB: ответ называет истинный момент снимка и его возраст — архив не выдаётся за текущее.

27.10: `/api/dfb/pools` отдавал `generated_at` = время ЗАПРОСА и строки с `data_source:
"live"`, а снимок стоял с 30.08 (производитель в карантине), `as_of` строк — 25.06.
Блок `snapshot` — ДОПОЛНИТЕЛЬНЫЙ: строки не трогаются (у них свой row_hash).
"""
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from spa_core.api import server
from spa_core.api.routers import dfb

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — now_dt=NOW


def test_stale_snapshot_is_named_archive_with_its_true_time():
    f = dfb.snapshot_freshness({"generated_at": "2026-08-30T07:30:39+00:00", "as_of": "2026-06-25",
                                "pools": []}, now_dt=NOW)
    assert f["stale"] is True and f["age_hours"] > 1000
    assert f["snapshot_generated_at"].startswith("2026-08-30") and f["snapshot_as_of"] == "2026-06-25"
    assert "АРХИВ" in f["words"]


def test_fresh_snapshot_is_fresh():
    f = dfb.snapshot_freshness({"generated_at": "2026-10-27T07:00:00+00:00"}, now_dt=NOW)
    assert f["stale"] is False and f["age_hours"] == 5.0


def test_missing_or_bare_list_is_unmeasured_not_fresh():
    for raw in ({"pools": []}, [], None, {"generated_at": "не дата"}):
        f = dfb.snapshot_freshness(raw if raw is not None else {}, now_dt=NOW)
        assert f["stale"] is None and f["age_hours"] is None, raw
        assert "НЕ ИЗМЕРЕН" in f["words"]


def test_threshold_is_the_same_as_system_health():
    from spa_core.monitoring.system_health_monitor import DFB_FRESH_H
    assert dfb.SNAPSHOT_FRESH_H == DFB_FRESH_H


def test_endpoints_carry_the_snapshot_block_and_rows_stay_verbatim(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    row = {"pool_id": "p1", "data_source": "live", "as_of": "2026-06-25", "row_hash": "h"}
    (tmp_path / "dfb").mkdir()
    (tmp_path / "dfb" / "pools.json").write_text(json.dumps(
        {"generated_at": "2026-08-30T07:30:39+00:00", "as_of": "2026-06-25", "pools": [row]}))
    c = TestClient(server.app)
    body = c.get("/api/dfb/pools").json()
    assert body["snapshot"]["snapshot_generated_at"].startswith("2026-08-30")
    assert body["snapshot"]["stale"] is True
    assert body["pools"] == [], "вариант отказа: устаревшие строки не отдаются"
    assert c.get("/api/dfb/summary").json()["snapshot"]["stale"] is True


def test_refusal_variant_withholds_stale_rows_on_every_door(tmp_path, monkeypatch):
    """ВАРИАНТ ОТКАЗА (решение владельца): устаревший снимок — ни одной строки ни в /pools, ни в v1."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    (tmp_path / "dfb").mkdir()
    (tmp_path / "dfb" / "pools.json").write_text(json.dumps(
        {"generated_at": "2026-08-30T07:30:39+00:00", "pools": [{"pool_id": "p1"}]}))
    body = TestClient(server.app).get("/api/dfb/pools").json()
    assert body["pools"] == [] and body["available"] is False and body["snapshot"]["stale"] is True
    assert "older than" in body["note"]
