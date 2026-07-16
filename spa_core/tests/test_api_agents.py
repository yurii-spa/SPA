"""Pin the /api/agents/registry surface: the read-only fleet registry that feeds the internal
/admin/agents management dashboard. Direct-call unit tests (no ASGI lifespan) — deterministic
via monkeypatch, no dependency on the live launchctl fleet."""
import json

from spa_core.api.routers import agents as AG


def _fixture(generated_at):
    return {
        "model": "agent_registry",
        "generated_at": generated_at,
        "total_loaded": 2,
        "total_known": 3,
        "by_role": {"infra": 1, "monitoring": 1},
        "problem_count": 1,
        "roles": AG._ROLES,
        "agents": [
            {"label": "com.spa.apiserver", "short": "apiserver", "role": "infra",
             "schedule": "KeepAlive", "loaded": True, "pid": 123, "last_exit": 0,
             "retired": False, "reboot_safe": True, "problems": []},
            {"label": "com.spa.resilience", "short": "resilience", "role": "monitoring",
             "schedule": "каждые 1ч", "loaded": True, "pid": None, "last_exit": 0,
             "retired": False, "reboot_safe": False,
             "problems": ["загружен, но НЕ переживёт reboot"]},
        ],
    }


def test_fresh_cached_snapshot_served_verbatim(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    reg = _fixture(now)
    p = tmp_path / "agent_registry.json"
    p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(AG, "_REGISTRY", p)
    # a fresh snapshot must be served directly, never triggering a live launchctl rebuild
    monkeypatch.setattr(AG, "_regenerate", lambda: (_ for _ in ()).throw(AssertionError("should not rebuild")))
    d = AG.agents_registry()
    assert d["problem_count"] == 1
    assert d["total_loaded"] == 2
    assert {a["short"] for a in d["agents"]} == {"apiserver", "resilience"}
    assert d["roles"] == AG._ROLES


def test_stale_snapshot_triggers_rebuild(monkeypatch, tmp_path):
    reg = _fixture("2020-01-01T00:00:00+00:00")  # ancient → stale
    p = tmp_path / "agent_registry.json"
    p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(AG, "_REGISTRY", p)
    rebuilt = _fixture("2026-07-16T00:00:00+00:00")
    rebuilt["problem_count"] = 9
    monkeypatch.setattr(AG, "_regenerate", lambda: rebuilt)
    d = AG.agents_registry()
    assert d["problem_count"] == 9  # served the live rebuild, not the stale cache


def test_stale_snapshot_falls_back_to_cache_when_rebuild_fails(monkeypatch, tmp_path):
    reg = _fixture("2020-01-01T00:00:00+00:00")
    p = tmp_path / "agent_registry.json"
    p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(AG, "_REGISTRY", p)
    monkeypatch.setattr(AG, "_regenerate", lambda: None)  # rebuild unavailable
    d = AG.agents_registry()
    # honest: serve the (stale) last-known snapshot rather than a fabricated/empty fleet
    assert d["problem_count"] == 1
    assert d["total_known"] == 3


def test_fail_safe_when_registry_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(AG, "_REGISTRY", tmp_path / "does_not_exist.json")
    monkeypatch.setattr(AG, "_regenerate", lambda: None)  # no builder available
    d = AG.agents_registry()
    assert d["agents"] == []
    assert d["problem_count"] == 0
    assert d["total_loaded"] == 0
    assert d["roles"] == AG._ROLES
    assert "note" in d and "build_agent_registry" in d["note"]
