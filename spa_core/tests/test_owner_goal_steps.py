"""S4 K2 (E7.1): цель, шаги, причина ожидания, исполнитель, последнее подтверждённое — из ЕДИНОГО roadmap."""
from pathlib import Path

from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import owner_view as ow

RM = """# Roadmap
## Order of the next epics
1. ~~Old~~ — done (ADR-1).
2. **Delivered thing** — in progress: delivered, awaiting ARB review
3. **The goal** — in progress (directive)
    - step S1 · Первый — DONE · executor: ARB · last: принято
    - step S2 · Второй — WAITING: ждёт допуска владельца · executor: владелец · last: пакет готов
    - step S3 · Третий — BLOCKED: после S2 · executor: — · last: —
4. **Later** — queued
## Next
"""


def _rm(tmp: Path, text: str = RM) -> dict:
    (tmp / "docs").mkdir(parents=True, exist_ok=True)
    (tmp / "docs" / "ROADMAP.md").write_text(text, encoding="utf-8")
    return mc._roadmap(tmp)


def test_awaiting_review_is_not_the_current_goal(tmp_path):
    r = _rm(tmp_path)
    assert [i["state"] for i in r["items"]] == ["DONE", "REVIEW", "IN_PROGRESS", "QUEUED"]
    assert r["current"]["epic"] == "The goal"


def test_steps_are_parsed_with_reason_executor_and_last(tmp_path):
    steps = _rm(tmp_path)["current"]["steps"]
    assert [s["state"] for s in steps] == ["DONE", "WAITING", "BLOCKED"]
    assert steps[1]["reason"] == "ждёт допуска владельца" and steps[1]["executor"] == "владелец"
    assert steps[0]["last_confirmed"] == "принято"


def _truth(r):
    return {"studio": {"roadmap": {"value": {"items": r["items"]}}}}


def test_goal_projection_names_waiting_and_has_no_percent(tmp_path):
    r = _rm(tmp_path)
    g = ow.goal({"overview": {"now": {}}}, _truth(r))
    assert g["declared"] and g["no_percent"] and g["steps_declared"]
    wait = next(s for s in g["steps"] if s["id"] == "S2")
    assert wait["state_ru"] == "Ждёт" and wait["waiting"] == "ждёт допуска владельца"
    assert g["counts"]["BLOCKED"] == 1 and "%" not in g["text"]


def test_no_goal_in_progress_is_said_not_guessed(tmp_path):
    r = _rm(tmp_path, RM.replace("in progress (directive)", "queued"))
    g = ow.goal({"overview": {"now": {}}}, _truth(r))
    assert g["declared"] is False and "не объявлена" in g["text"]


def test_goal_without_steps_says_so(tmp_path):
    text = "\n".join(l for l in RM.splitlines() if "- step" not in l)
    g = ow.goal({"overview": {"now": {}}}, _truth(_rm(tmp_path, text)))
    assert g["steps_declared"] is False and g["steps_missing_text"]


def test_real_roadmap_has_the_program_as_current_goal():
    r = mc._roadmap(Path(__file__).resolve().parents[2])
    assert r["current"] and "STUDIO-AUTONOMY-01" in r["current"]["epic"]
    assert {s["id"] for s in r["current"].get("steps", [])} >= {"S1", "S2", "S3", "S4", "S5"}
