"""spa_core/tests/test_mission_rebuild_from_canon.py — RM-TRUTH-01 / ADR-580 C4: Company Truth
is "computed on read", with no stored artifact as its own source of truth. Deleting the whole
bundle cache and rebuilding from the SAME canon + the SAME injected clock must reproduce BYTE
(JSON)-identical output — nothing here is accumulated, cached-and-drifted, or randomised.

Also checked: ``company_truth.py`` writes nothing — no ``open(..., "w")`` anywhere in its own
AST, and a scratch directory's listing is unchanged before/after calling ``build()``.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed into mc.build(MCInputs(now=NOW, ...)) and into
# mission_build.build_bundle(..., now=NOW, build_fn=...) identically on both the A and the B
# side of the rebuild; nothing here reads the real clock.
from __future__ import annotations

import ast
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from spa_core.studio_os import company_truth as ct
from spa_core.studio_os import mission_build
from spa_core.studio_os import mission_control as mc

NOW = datetime.fromtimestamp(1_790_100_000, tz=timezone.utc)
ISO = "%Y-%m-%dT%H:%M:%SZ"


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _scene(tmp_path: Path) -> SimpleNamespace:
    repo, mirror = tmp_path / "prod", tmp_path / "mirror"
    (mirror / "nimbalyst-local" / "tracker").mkdir(parents=True)
    (repo / "data").mkdir(parents=True)
    (mirror / "docs").mkdir(parents=True)
    (mirror / "docs" / "ROADMAP.md").write_text(
        "# Roadmap\n\nLast confirmed by the owner: **2026-10-05**\n\n## Order of the next epics\n\n"
        "1. RM-TRUTH-01 — in progress\n\n## Other\n", encoding="utf-8")
    data = repo / "data"
    _w(data / "resource_health.json", {"generated_at": NOW.strftime(ISO), "overall": "OK",
                                       "disk": {"state": "OK", "free_gb": 100, "warn_free_gb": 25, "critical_free_gb": 10},
                                       "memory": {"state": "OK", "pressure_level": 1, "swap": {"used_pct": 10}},
                                       "processes": {"rss_mb_by_class": {}, "top": []}})
    _w(data / "code_sync_status.json", {"result": "IN_SYNC", "origin_main": "a" * 40, "timestamp": NOW.strftime(ISO)})
    _w(data / "paper_trading_status.json", {"execution_mode": "read_only_simulation"})
    (data / "telegram").mkdir()
    _w(data / "telegram" / "push_state.json", {"updated_at": NOW.strftime(ISO), "events": {}})
    return SimpleNamespace(repo=repo, mirror=mirror, data=data)


def _inputs(s) -> mc.MCInputs:
    return mc.MCInputs(repo=s.repo, mirror=s.mirror, now=NOW, measure_host=False,
                       mirror_synced_at=NOW - timedelta(minutes=5),
                       collect=lambda: {"status": "green", "alerts": [], "services": [],
                                       "kill_switch_active": False, "derisk_active": False, "claude_sessions": 0},
                       packages=lambda: None, git_log=lambda h: None, leases=lambda: [],
                       launchctl_full=lambda: None)


def test_rebuild_from_canon_gives_byte_identical_mission_json(tmp_path):
    s = _scene(tmp_path)
    root_a, root_b = tmp_path / "bundles_a", tmp_path / "bundles_b"
    ui_dir = Path(mc.__file__).resolve().parent / "mission_ui"

    def build_fn():
        return mc.build(_inputs(s))

    res_a = mission_build.build_bundle(root_a, now=NOW, build_fn=build_fn, ui_dir=ui_dir)
    model_a = json.loads((root_a / res_a["bundle"] / "mission.json").read_text(encoding="utf-8"))

    shutil.rmtree(root_a)  # the WHOLE cache is gone — nothing survives to be "reused"
    assert not root_a.exists()

    res_b = mission_build.build_bundle(root_b, now=NOW, build_fn=build_fn, ui_dir=ui_dir)
    model_b = json.loads((root_b / res_b["bundle"] / "mission.json").read_text(encoding="utf-8"))

    assert json.dumps(model_a, sort_keys=True) == json.dumps(model_b, sort_keys=True)
    assert model_a["truth"]["schema"] == ct.SCHEMA
    assert model_a["truth"] == model_b["truth"]


def test_rebuild_is_identical_at_the_mc_build_level_too(tmp_path):
    """The same property one level down, without the bundle/UI machinery — in case a future
    change to mission_build (e.g. a bundle id embedded in the model) would otherwise mask a
    real drift in mc.build() itself behind "excluded fields"."""
    s = _scene(tmp_path)
    inp = _inputs(s)
    m1 = mc.build(inp)
    m2 = mc.build(inp)
    assert json.dumps(m1, sort_keys=True, default=str) == json.dumps(m2, sort_keys=True, default=str)


def test_company_truth_module_contains_no_write_open_in_its_ast():
    src = Path(ct.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            mode_arg = None
            if len(node.args) >= 2:
                mode_arg = node.args[1]
            for kw in node.keywords:
                if kw.arg == "mode":
                    mode_arg = kw.value
            if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                assert "w" not in mode_arg.value and "a" not in mode_arg.value, ast.dump(node)


def test_company_truth_touches_nothing_on_a_scratch_directory(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    before = sorted(os.listdir(scratch))
    inp = ct.TruthInputs(data=scratch / "data", mirror=scratch / "mirror", repo=scratch, now=NOW,
                         measure_host=False, roadmap={"items": None, "current": None, "confirmed": None})
    (scratch / "data").mkdir()
    (scratch / "mirror").mkdir()
    before = sorted(os.listdir(scratch))
    ct.build(inp)
    after = sorted(os.listdir(scratch))
    assert before == after
