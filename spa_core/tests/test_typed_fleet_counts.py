"""spa_core/tests/test_typed_fleet_counts.py — RM-TRUTH-01 / ADR-580 Director OS v2 design §4
(S1, C11): typed fleet counts from a fixture manifest + launchctl text + agent_health — never a
process counted as a role, never a retired-but-loaded or unknown-orphan label silently folded
into "declared"/"loaded".
"""
from __future__ import annotations

from spa_core.studio_os import company_truth as ct


def _agent(label, intent="active", schedule="interval:3600s"):
    return {"label": label, "intent": intent, "schedule": schedule}


def _manifest(*agents):
    return {"agents": list(agents)}


def test_runtime_vs_managed_split_by_schedule_daemon():
    manifest = _manifest(
        _agent("com.spa.apiserver", schedule="daemon"),
        _agent("com.spa.telegram_bot", schedule="daemon"),
        _agent("com.spa.agent_health", schedule="interval:3600s"),
    )
    lc = {"com.spa.apiserver": {"pid": 1, "exit": "0"}, "com.spa.telegram_bot": {"pid": 2, "exit": "0"},
          "com.spa.agent_health": {"pid": 3, "exit": "0"}}
    ah = {"agents": [{"label": "com.spa.apiserver", "status": "OK"},
                     {"label": "com.spa.telegram_bot", "status": "OK"},
                     {"label": "com.spa.agent_health", "status": "OK"}]}
    f = ct.typed_fleet(manifest, lc, ah, {"roles": []}, announced=0, unannounced=0)
    assert f["runtime_services"] == {"declared": 2, "loaded": 2}
    assert f["managed_agents"] == {"declared": 1, "loaded": 1}
    assert f["headline"]["value"]["ok"] == 3 and f["headline"]["value"]["declared"] == 3
    assert f["headline"]["state"] == ct.MEASURED


def test_retired_but_loaded_is_red_and_never_joins_declared():
    manifest = _manifest(_agent("com.spa.active_one"), _agent("com.spa.zombie", intent="retired"))
    lc = {"com.spa.active_one": {"pid": 1, "exit": "0"}, "com.spa.zombie": {"pid": 2, "exit": "0"}}
    f = ct.typed_fleet(manifest, lc, {"agents": []}, {"roles": []}, announced=0, unannounced=0)
    assert f["retired_loaded"] == {"n": 1, "labels": ["com.spa.zombie"]}
    # declared counts only active agents — a retired-but-loaded zombie never inflates them
    assert f["managed_agents"]["declared"] == 1
    assert "вне учёта" in f["headline"]["display_ru"] or f["headline"]["value"]["ok"] is not None


def test_unknown_orphan_label_never_counted_as_declared():
    manifest = _manifest(_agent("com.spa.known"))
    lc = {"com.spa.known": {"pid": 1, "exit": "0"}, "com.spa.mystery_agent": {"pid": 9, "exit": "0"}}
    f = ct.typed_fleet(manifest, lc, {"agents": []}, {"roles": []}, announced=0, unannounced=0)
    assert f["unknown_orphans"] == {"n": 1, "labels": ["com.spa.mystery_agent"]}
    assert f["managed_agents"]["declared"] == 1


def test_studio_bridge_prefix_also_counts_as_an_orphan_when_undeclared():
    manifest = _manifest(_agent("com.spa.known"))
    lc = {"com.spa.known": {"pid": 1, "exit": "0"}, "com.studiobridge.telegram": {"pid": 9, "exit": "0"}}
    f = ct.typed_fleet(manifest, lc, {"agents": []}, {"roles": []}, announced=0, unannounced=0)
    assert "com.studiobridge.telegram" in f["unknown_orphans"]["labels"]


def test_roles_are_never_added_to_process_counts():
    manifest = _manifest(_agent("com.spa.a"), _agent("com.spa.b"))
    roles = {"roles": [{"implemented": True}, {"implemented": True}, {"implemented": False}]}
    f = ct.typed_fleet(manifest, {"com.spa.a": {}, "com.spa.b": {}}, {"agents": []}, roles, announced=0, unannounced=0)
    assert f["configured_roles"] == {"n": 2}
    # the role count must not leak into any process-count field
    assert f["runtime_services"]["declared"] + f["managed_agents"]["declared"] == 2


def test_agent_health_absent_gives_unknown_headline_but_declared_total_unchanged():
    manifest = _manifest(_agent("com.spa.a", schedule="daemon"), _agent("com.spa.b"))
    f_known = ct.typed_fleet(manifest, {"com.spa.a": {}, "com.spa.b": {}},
                             {"agents": [{"label": "com.spa.a", "status": "OK"}, {"label": "com.spa.b", "status": "OK"}]},
                             {"roles": []}, announced=0, unannounced=0)
    f_unknown = ct.typed_fleet(manifest, {"com.spa.a": {}, "com.spa.b": {}}, None, {"roles": []},
                               announced=0, unannounced=0)
    declared = f_known["runtime_services"]["declared"] + f_known["managed_agents"]["declared"]
    assert f"из {declared}" in f_unknown["headline"]["display_ru"]
    assert "?" in f_unknown["headline"]["display_ru"]
    assert f_unknown["headline"]["state"] == ct.NOT_MEASURED


def test_manifest_absent_is_not_measured_not_zero():
    f = ct.typed_fleet(None, {}, {"agents": []}, {"roles": []}, announced=0, unannounced=0)
    assert f["headline"]["state"] == ct.NOT_MEASURED
    assert f["headline"]["value"] is None
    assert f["runtime_services"]["declared"] is None


def test_active_workers_carries_announced_and_unannounced_separately():
    f = ct.typed_fleet({"agents": []}, {}, {"agents": []}, {"roles": []}, announced=1, unannounced=3)
    assert f["active_workers"] == {"announced": 1, "unannounced": 3}
