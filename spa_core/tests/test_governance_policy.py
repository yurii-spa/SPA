"""Tests for spa_core.governance.policy (Governance-as-Code).

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.governance import policy as gp


# ─── required_authority per category ────────────────────────────────────────────


@pytest.mark.parametrize("action", list(gp._AUTO_ACTIONS))
def test_auto_actions_are_auto(action):
    assert gp.required_authority(action) == gp.AUTO
    assert gp.is_ai_permitted(action) is True


@pytest.mark.parametrize("action", list(gp._HUMAN_SINGLE_ACTIONS))
def test_human_single_actions(action):
    assert gp.required_authority(action) == gp.HUMAN_SINGLE
    assert gp.is_ai_permitted(action) is False


@pytest.mark.parametrize("action", list(gp._HUMAN_DUAL_ACTIONS))
def test_human_dual_actions(action):
    assert gp.required_authority(action) == gp.HUMAN_DUAL
    assert gp.is_ai_permitted(action) is False


def test_unknown_action_default_deny():
    assert gp.required_authority("totally_made_up_action") == gp.UNKNOWN
    assert gp.is_ai_permitted("totally_made_up_action") is False
    res = gp.check_action("totally_made_up_action", actor="ai")
    assert res["permitted"] is False
    assert res["required"] == gp.UNKNOWN


def test_non_string_action_default_deny():
    assert gp.required_authority(None) == gp.UNKNOWN  # type: ignore[arg-type]
    assert gp.is_ai_permitted(None) is False  # type: ignore[arg-type]


# ─── is_ai_permitted: only AUTO ─────────────────────────────────────────────────


def test_only_auto_is_ai_permitted():
    assert gp.is_ai_permitted("run_backtest") is True
    assert gp.is_ai_permitted("freeze_on_risk_invariant") is True
    assert gp.is_ai_permitted("change_allocations") is False
    assert gp.is_ai_permitted("deposit") is False


# ─── check_action signature rules ───────────────────────────────────────────────


def test_deposit_requires_two_sigs():
    assert gp.check_action("deposit", "owner", signatures=0)["permitted"] is False
    assert gp.check_action("deposit", "owner", signatures=1)["permitted"] is False
    res = gp.check_action("deposit", "owner", signatures=2)
    assert res["permitted"] is True
    assert res["required"] == gp.HUMAN_DUAL
    assert res["provided"] == 2


def test_withdraw_requires_two_sigs():
    assert gp.check_action("withdraw", "owner", 1)["permitted"] is False
    assert gp.check_action("withdraw", "owner", 2)["permitted"] is True


def test_change_allocations_needs_one_human_sig():
    assert gp.check_action("change_allocations", "owner", 0)["permitted"] is False
    res = gp.check_action("change_allocations", "owner", 1)
    assert res["permitted"] is True
    assert res["required"] == gp.HUMAN_SINGLE


def test_auto_permitted_with_zero_sigs():
    res = gp.check_action("github_commit", "ai", 0)
    assert res["permitted"] is True
    assert res["required"] == gp.AUTO


def test_check_action_result_shape():
    res = gp.check_action("deposit", "owner", 2)
    for key in ("permitted", "reason", "required", "provided", "action", "actor"):
        assert key in res
    assert res["action"] == "deposit"
    assert res["actor"] == "owner"


def test_negative_or_bad_signatures_clamped():
    assert gp.check_action("deposit", "x", -5)["provided"] == 0
    assert gp.check_action("deposit", "x", "bad")["provided"] == 0  # type: ignore[arg-type]


# ─── policy_manifest ─────────────────────────────────────────────────────────────


def test_policy_manifest_structure():
    m = gp.policy_manifest()
    assert m["version"] == gp.GOVERNANCE_POLICY_VERSION
    assert m["default_policy"] == "DENY"
    assert set(m["levels"]) == {gp.AUTO, gp.HUMAN_SINGLE, gp.HUMAN_DUAL}
    assert m["levels"][gp.AUTO]["required_signatures"] == 0
    assert m["levels"][gp.HUMAN_SINGLE]["required_signatures"] == 1
    assert m["levels"][gp.HUMAN_DUAL]["required_signatures"] == 2
    assert m["levels"][gp.AUTO]["ai_permitted"] is True
    assert m["levels"][gp.HUMAN_DUAL]["ai_permitted"] is False
    assert m["action_count"] == len(m["by_action"]) > 0


def test_manifest_by_action_consistent():
    m = gp.policy_manifest()
    for action, level in m["by_action"].items():
        assert gp.required_authority(action) == level


# ─── dual_control_posture ───────────────────────────────────────────────────────


def test_dual_control_advisory_when_no_config(tmp_path):
    posture = gp.dual_control_posture(data_dir=tmp_path)
    assert posture["enforced"] is False
    assert posture["mechanism"] == "advisory"
    assert "multisig" in posture["note"].lower()


def test_dual_control_enforced_with_valid_config(tmp_path):
    cfg = {"threshold": 2, "signers": ["a", "b", "c"]}
    (tmp_path / "multisig_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    posture = gp.dual_control_posture(data_dir=tmp_path)
    assert posture["enforced"] is True
    assert posture["mechanism"] == "multisig"
    assert posture["threshold"] == 2
    assert posture["signers"] == 3


def test_dual_control_not_enforced_threshold_one(tmp_path):
    cfg = {"threshold": 1, "signers": ["a"]}
    (tmp_path / "multisig_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert gp.dual_control_posture(data_dir=tmp_path)["enforced"] is False


# ─── build_report ────────────────────────────────────────────────────────────────


def test_build_report_no_write():
    report = gp.build_report(write=False)
    assert "manifest" in report
    assert "dual_control_posture" in report
    assert report["version"] == gp.GOVERNANCE_POLICY_VERSION
    assert "generated_at" in report


def test_build_report_writes_atomically(tmp_path):
    report = gp.build_report(write=True, data_dir=tmp_path)
    out = tmp_path / gp.GOVERNANCE_POLICY_FILENAME
    assert out.exists()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk["manifest"] == report["manifest"]
    assert on_disk["dual_control_posture"]["enforced"] is False


# ─── determinism ─────────────────────────────────────────────────────────────────


def test_manifest_deterministic():
    assert gp.policy_manifest() == gp.policy_manifest()


def test_check_action_deterministic():
    a = gp.check_action("deposit", "owner", 2)
    b = gp.check_action("deposit", "owner", 2)
    assert a == b
