"""S4 K6 (E7.5): роли · провайдер · права · квота · исполнители — UNKNOWN честно, смена модели прав не добавляет."""
import json
from datetime import datetime, timezone
from pathlib import Path

from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import owner_view as ow

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — _roles_section(now=NOW)
REPO = Path(__file__).resolve().parents[2]


def _scene(tmp: Path, assignments=None, provider_perms=None):
    a = tmp / "architecture"
    a.mkdir(parents=True)
    mr = json.loads((REPO / "architecture" / "model_roles.json").read_text(encoding="utf-8"))
    if assignments is not None:
        mr["assignments"] = assignments
    if provider_perms is not None:
        for p in mr["providers"].values():
            p["permissions"] = provider_perms
    (a / "model_roles.json").write_text(json.dumps(mr), encoding="utf-8")
    (a / "roles.json").write_text((REPO / "architecture" / "roles.json").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp


def test_real_files_routing_off_quota_unknown(tmp_path):
    sec = mc._roles_section(REPO, None, NOW)
    assert sec["routing_enabled"] is False
    assert {r["provider_state"] for r in sec["model_roles"]} == {"NOT_ASSIGNED"}
    assert all(r["quota"] == "UNKNOWN" and r["quota_reason"] for r in sec["model_roles"])
    assert sec["executors"] is None, "трекер не прочитан — это не «никого нет»"


def test_rights_come_from_the_role_not_from_the_provider(tmp_path):
    root = _scene(tmp_path, assignments={"architect": "claude_subscription_cli", "worker": None},
                  provider_perms=["shell", "push"])
    sec = mc._roles_section(root, {}, NOW)
    arch = next(r for r in sec["model_roles"] if r["role"] == "architect")
    assert arch["provider"] == "claude_subscription_cli" and "shell" not in arch["permissions"]
    view = ow.roles({"studio": {"roles": sec}})
    assert "права принадлежат роли" in view["rule"] and "сейчас никто не держит" in view["executors"]


def test_executors_are_counted_from_claims_in_work(tmp_path):
    cards = {"a.md": {"fm": {"status": "in-progress", "claimed_by": "cycle-1"}},
             "b.md": {"fm": {"status": "in-progress", "claimed_by": "cycle-1"}},
             "c.md": {"fm": {"status": "done", "claimed_by": "cycle-2"}}}
    sec = mc._roles_section(REPO, cards, NOW)
    assert sec["executors"] == [{"executor": "cycle-1", "cards": 2}]


def test_unreadable_role_files_are_not_measured(tmp_path):
    assert mc._roles_section(tmp_path, None, NOW)["_meta"]["state"] == "NOT_MEASURED"
