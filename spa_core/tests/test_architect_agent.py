"""
Tests for ArchitectAgent (v2.4 — BL-002).

All tests are deterministic and offline: no network, no LLM, no real DB.
The MessageBus is mocked where needed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make spa_core importable
_SPA_CORE = Path(__file__).parent.parent
if str(_SPA_CORE) not in sys.path:
    sys.path.insert(0, str(_SPA_CORE))

from agents.architect_agent import ArchitectAgent  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_kanban() -> dict:
    """Mini KANBAN doska covering all relevant cases."""
    return {
        "last_updated": "2026-05-27T00:00:00Z",
        "updated_by": "test",
        "columns": {
            "ideas": [
                {"id": "IDEA-A", "title": "Some idea", "priority": "LOW",
                 "estimate": "5h", "tags": ["frontend"], "added": "2026-05-20"},
            ],
            "features": [
                {"id": "FEAT-001", "title": "Phase 3: Real Capital",
                 "priority": "HIGH", "estimate": "80h", "tags": ["backend"],
                 "sprint": "v2.0", "added": "2026-05-22"},
                {"id": "FEAT-007", "title": "Advanced Kelly Sizing",
                 "priority": "MEDIUM", "estimate": "10h", "tags": ["backend"],
                 "sprint": None, "added": "2026-05-22"},
            ],
            "backlog": [
                {"id": "BL-X1", "title": "Tester Agent Implementation",
                 "priority": "HIGH", "estimate": "10h", "tags": ["backend"],
                 "sprint": None, "added": "2026-05-22"},
                {"id": "BL-X2", "title": "Enable GitHub Pages (User Action)",
                 "priority": "HIGH", "estimate": "0.1h", "tags": ["infra"],
                 "sprint": None, "added": "2026-05-22"},
                {"id": "BL-X3", "title": "Fix go-live drawdown threshold",
                 "priority": "MEDIUM", "estimate": "1h", "tags": ["bug", "golive"],
                 "sprint": None, "added": "2026-05-22"},
                {"id": "BL-X4", "title": "Some medium task",
                 "priority": "MEDIUM", "estimate": "3h", "tags": ["backend"],
                 "sprint": None, "added": "2026-05-22"},
            ],
            "in_progress": [],
            "review": [
                # Stale: added 2026-05-10, "today" in our test is 2026-05-27
                {"id": "REV-OLD", "title": "Stale review item",
                 "priority": "HIGH", "estimate": "0.2h", "tags": ["frontend"],
                 "sprint": "v1.6", "added": "2026-05-10"},
                # Fresh: added 2026-05-26
                {"id": "REV-FRESH", "title": "Fresh review item",
                 "priority": "MEDIUM", "estimate": "0.2h", "tags": ["backend"],
                 "sprint": "v2.3", "added": "2026-05-26"},
            ],
            "done": [
                {"id": "OLD-1", "title": "old", "priority": "HIGH",
                 "estimate": "1h", "tags": ["backend"], "added": "2026-05-01",
                 "status": "done", "completed": "2026-05-02"},
            ],
        },
    }


@pytest.fixture
def kanban_file(tmp_path: Path, sample_kanban: dict) -> Path:
    p = tmp_path / "KANBAN.json"
    p.write_text(json.dumps(sample_kanban))
    return p


@pytest.fixture
def golive_file(tmp_path: Path) -> Path:
    p = tmp_path / "golive_readiness.json"
    p.write_text(json.dumps({
        "verdict": "PENDING — 7/56 days complete",
        "criteria_passed": 4,
        "criteria_total": 11,
        "days_remaining": 49,
        "criteria": {
            "max_drawdown":   {"status": "PASS", "note": "ok"},
            "concentration":  {"status": "PASS", "note": "ok"},
            "whitelist_only": {"status": "PASS", "note": "ok"},
            "risk_policy":    {"status": "PASS", "note": "ok"},
            "paper_duration": {"status": "PENDING", "note": "need more days"},
        },
    }))
    return p


@pytest.fixture
def agent(kanban_file: Path, golive_file: Path) -> ArchitectAgent:
    """ArchitectAgent wired to mocked bus + temp KANBAN/golive."""
    bus = MagicMock()
    bus.publish = MagicMock(return_value="msg-id-123")
    return ArchitectAgent(
        bus=bus,
        kanban_path=kanban_file,
        golive_path=golive_file,
    )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_load_kanban_returns_dict(agent: ArchitectAgent):
    kanban = agent.load_kanban()
    assert isinstance(kanban, dict)
    assert "columns" in kanban
    for col in ("ideas", "features", "backlog", "in_progress", "review", "done"):
        assert col in kanban["columns"]
        assert isinstance(kanban["columns"][col], list)


def test_load_kanban_missing_file_returns_empty(tmp_path: Path):
    bus = MagicMock()
    agent = ArchitectAgent(
        bus=bus,
        kanban_path=tmp_path / "does_not_exist.json",
        golive_path=tmp_path / "no_golive.json",
    )
    kanban = agent.load_kanban()
    assert kanban["columns"]["backlog"] == []
    assert kanban["columns"]["features"] == []
    assert kanban["columns"]["done"] == []


def test_analyze_state_totals_correct(agent: ArchitectAgent, sample_kanban: dict):
    state = agent.analyze_state()
    totals = state["totals"]
    cols = sample_kanban["columns"]
    assert totals["ideas"]       == len(cols["ideas"])       == 1
    assert totals["features"]    == len(cols["features"])    == 2
    assert totals["backlog"]     == len(cols["backlog"])     == 4
    assert totals["in_progress"] == len(cols["in_progress"]) == 0
    assert totals["review"]      == len(cols["review"])      == 2
    assert totals["done"]        == len(cols["done"])        == 1


def test_analyze_state_high_priority_open_filters_correctly(agent: ArchitectAgent):
    state = agent.analyze_state()
    ids = [t["id"] for t in state["high_priority_open"]]

    # Should include HIGH from backlog and features
    assert "BL-X1" in ids        # HIGH backlog (non-manual)
    assert "BL-X2" in ids        # HIGH backlog (manual — still HIGH-open, manual filter applies later)
    assert "FEAT-001" in ids     # HIGH feature

    # Should NOT include MEDIUM tasks
    assert "BL-X3" not in ids
    assert "BL-X4" not in ids
    assert "FEAT-007" not in ids

    # Should NOT include done tasks
    assert "OLD-1" not in ids

    # Should NOT include review items (they are not "open" sprint work here)
    assert "REV-OLD" not in ids


def test_propose_sprint_respects_target_hours(agent: ArchitectAgent):
    target = 8.0
    proposal = agent.propose_sprint(target_hours=target)

    assert proposal["target_hours"] == target
    assert isinstance(proposal["tasks"], list)
    assert proposal["total_estimate"] >= 0

    # Total estimate is capped at target + overshoot. We allow up to
    # target_hours + max(estimate of any picked task) to accommodate
    # the last task that pushed us over the bar.
    if proposal["tasks"]:
        max_est = max(t["estimate_hours"] for t in proposal["tasks"])
        assert proposal["total_estimate"] <= target + max_est

    # Manual task (BL-X2 with "User Action" + infra tag) must NOT be in proposal
    ids = [t["id"] for t in proposal["tasks"]]
    assert "BL-X2" not in ids
    # Done tasks must NOT be in proposal
    assert "OLD-1" not in ids


def test_propose_sprint_prefers_high_backlog_over_features(agent: ArchitectAgent):
    """Tier 0 (HIGH backlog non-manual) should be picked before Tier 1 (HIGH feature)."""
    proposal = agent.propose_sprint(target_hours=8.0)
    ids = [t["id"] for t in proposal["tasks"]]
    if "BL-X1" in ids and "FEAT-001" in ids:
        assert ids.index("BL-X1") < ids.index("FEAT-001")


def test_dump_proposal_writes_valid_json(agent: ArchitectAgent, tmp_path: Path):
    out_file = tmp_path / "architect_proposal.json"
    written = agent.dump_proposal(out_path=out_file)

    assert written == out_file
    assert out_file.exists()

    data = json.loads(out_file.read_text())
    assert "analysis" in data
    assert "proposal" in data
    assert "generated_at" in data
    assert data["agent"] == "architect_agent"

    # Sanity: analysis has expected keys
    for k in ("totals", "high_priority_open", "stale_review",
              "go_live_status", "next_sprint_candidates"):
        assert k in data["analysis"]

    # Sanity: proposal has expected keys
    for k in ("sprint_name", "target_hours", "tasks",
              "total_estimate", "rationale"):
        assert k in data["proposal"]


def test_run_publishes_to_bus(agent: ArchitectAgent):
    msg_ids = agent.run()

    assert msg_ids == ["msg-id-123"]
    agent.bus.publish.assert_called_once()

    # Inspect the call arguments
    args, kwargs = agent.bus.publish.call_args
    # publish(topic, sender, payload, priority)
    topic = args[0] if args else kwargs.get("topic")
    sender = args[1] if len(args) > 1 else kwargs.get("sender")
    payload = args[2] if len(args) > 2 else kwargs.get("payload")

    assert topic == "architect.proposal"
    assert sender == "architect_agent"
    assert "analysis" in payload
    assert "proposal" in payload
    assert "tasks" in payload["proposal"]
