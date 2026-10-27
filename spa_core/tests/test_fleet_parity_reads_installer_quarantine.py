"""Отложенный агент — не «retired, но устанавливается».

Замер 27.10: `fleet_parity.json` называл пять меток `retired_but_installed`
(bts-feed, bts-monitor, dfb_capture, governance_watcher, source_discovery), и все
пять — в `attic/agents/QUARANTINE.json` по решениям владельца 29–30.08. Установщик
их НЕ ставит: он сверяет каждую метку с реестром (test_installer_respects_quarantine).
Сторож читал строки установщика статически и пропуска не видел — пять ложных находок
из пяти, проблема `fleet.retired_but_loaded` висела OPEN на шуме.

Контроль в обе стороны: та же метка БЕЗ записи в реестре по-прежнему находка;
нечитаемый реестр — «не измерено» (DRIFT + None), а не пустой карантин.
"""
import importlib
import json

fpc = importlib.import_module("scripts.fleet_parity_check")

_LBL = "com.spa.zombie"


def _scene(monkeypatch, tmp_path, registry):
    q = tmp_path / "QUARANTINE.json"
    if registry is not None:
        q.write_text(registry if isinstance(registry, str) else json.dumps(registry))
    monkeypatch.setattr(fpc, "_QUARANTINE", q)
    monkeypatch.setattr(fpc, "declared_labels", lambda: {"com.spa.a", _LBL})
    monkeypatch.setattr(fpc, "plist_labels", lambda: {"com.spa.a", _LBL})
    monkeypatch.setattr(fpc, "retired_labels", lambda: {_LBL})
    monkeypatch.setattr(fpc, "_live_labels", lambda: None)
    return fpc.build_report(write=False)


def test_quarantined_label_is_skipped_not_installed(monkeypatch, tmp_path):
    rep = _scene(monkeypatch, tmp_path, {"quarantined": {_LBL: {"at": "x"}}})
    assert rep["retired_but_installed"] == []
    assert rep["quarantined_skipped_by_installer"] == [_LBL]
    assert rep["quarantine_registry"] == "read"
    assert rep["status"] == "OK"


def test_list_form_and_bare_name_parse_like_the_installer(monkeypatch, tmp_path):
    rep = _scene(monkeypatch, tmp_path, {"quarantined": [{"label": "zombie"}]})
    assert rep["retired_but_installed"] == []
    assert rep["quarantined_skipped_by_installer"] == [_LBL]


def test_control_same_label_without_quarantine_is_still_a_finding(monkeypatch, tmp_path):
    rep = _scene(monkeypatch, tmp_path, {"quarantined": {}})
    assert rep["retired_but_installed"] == [_LBL]
    assert rep["status"] == "DRIFT"


def test_absent_registry_skips_nobody(monkeypatch, tmp_path):
    rep = _scene(monkeypatch, tmp_path, None)
    assert rep["quarantine_registry"] == "absent"
    assert rep["retired_but_installed"] == [_LBL]


def test_unreadable_registry_is_unmeasured_not_empty(monkeypatch, tmp_path):
    rep = _scene(monkeypatch, tmp_path, "{not json")
    assert rep["quarantine_registry"] == "unreadable"
    assert rep["quarantined_skipped_by_installer"] is None
    assert rep["status"] == "DRIFT"
    assert rep["retired_but_installed"] == [_LBL]
