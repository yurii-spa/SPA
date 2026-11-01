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


def test_step_reason_mentioning_arb_does_not_change_the_item_state_for_either_reader(tmp_path):
    """Ревью S4: «ждёт ARB» в причине ШАГА роняло активный эпик у генератора контекста, но не у пульта."""
    from spa_core.studio_os.memory import continuity as c
    text = RM.replace("ждёт допуска владельца", "ждёт ARB")
    assert _rm(tmp_path, text)["current"]["epic"] == "The goal"
    assert c.roadmap_view(text, lambda a: "ACCEPTED")["active"]["name"] == "The goal"


def test_unknown_step_state_is_named_not_dropped(tmp_path):
    text = RM.replace("    - step S3 · Третий — BLOCKED: после S2 · executor: — · last: —",
                      "    - step S3 · Третий — QUEUED · executor: — · last: —")
    g = ow.goal({"overview": {"now": {}}}, _truth(_rm(tmp_path, text)))
    s3 = next(s for s in g["steps"] if s["id"] == "S3")
    assert s3["state_ru"] == "Состояние не распознано"


def _ct_truth(r):
    """Ячейка через НАСТОЯЩИЙ `company_truth.studio_roadmap` — тот же путь, что у пульта."""
    from spa_core.studio_os import company_truth as ct
    return {"studio": {"roadmap": ct.studio_roadmap(r)}}


def _first_level(g):
    """Всё, что пульт показывает на первом уровне цели (renderGoal), — без технических подробностей."""
    parts = [g.get("summary_kind"), g.get("recorded_ru"), g.get("plan_confirmed_ru"), g.get("text")]
    for st in g.get("steps") or []:
        parts += [st.get("state_ru"), st.get("executor"), st.get("last_confirmed"), st.get("waiting"), st.get("reason")]
    return " ".join(str(x) for x in parts if x)


def test_goal_is_labelled_as_a_recorded_plan_summary_not_a_measurement(tmp_path):
    """ARB 01.11 (п. 2в + поправка п. 1): сводка из плана; дата её записи неизвестна; дата подтверждения ПЛАНА —
    только из строки канона; время файла — отдельно названное техническое свойство."""
    text = RM.replace("# Roadmap\n", "# Roadmap\n> Last confirmed by the owner: **2026-10-01** (directive).\n")
    g = ow.goal({"overview": {"now": {}}}, _ct_truth(_rm(tmp_path, text)))
    assert "не автоматический замер" in g["summary_kind"]
    assert g["recorded_ru"] == "дата записи сводки неизвестна"
    assert g["plan_confirmed_ru"].startswith("план подтверждён владельцем 2026-10-01")
    tech = [k for k in g["technical"] if k.startswith("время изменения файла ROADMAP")]
    assert tech and "не дата записи и не подтверждение плана" in tech[0]
    g2 = ow.goal({"overview": {"now": {}}}, _ct_truth(_rm(tmp_path / "x", RM)))
    assert g2["plan_confirmed_ru"] == "дата подтверждения плана владельцем в ROADMAP не записана"


def test_touching_only_the_file_time_does_not_make_the_summary_fresher(tmp_path):
    """ARB 01.11 п. 1: mtime сдвинут на год вперёд при НЕИЗМЕННОМ содержимом — первый уровень цели не меняется
    ни на символ, и ни одна дата из mtime на него не попадает. Обратный контроль: время файла действительно
    сменилось и видно в технических подробностях — то есть тест мерит именно подмену, а не её отсутствие."""
    import os
    text = RM.replace("# Roadmap\n", "# Roadmap\n> Last confirmed by the owner: **2026-10-01** (directive).\n")
    r1 = _rm(tmp_path, text)
    g1 = ow.goal({"overview": {"now": {}}}, _ct_truth(r1))
    p = tmp_path / "docs" / "ROADMAP.md"
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 365 * 86400))
    r2 = mc._roadmap(tmp_path)
    assert r2["file_mtime"] != r1["file_mtime"]                       # обратный контроль: подмена произошла
    assert r2["confirmed"] == r1["confirmed"] == "2026-10-01"
    g2 = ow.goal({"overview": {"now": {}}}, _ct_truth(r2))
    assert _first_level(g2) == _first_level(g1)
    assert r2["file_mtime"][:4] not in _first_level(g2)              # год из mtime на первый уровень не попал
    assert g2["technical"] != g1["technical"]                         # а в подробностях время файла видно
