"""S4 K2 · поправка ARB 01.11 п. 1: дата сводки плана на пульте — не время файла.

Вынесено из `test_owner_goal_steps.py`: этим тестам нужна НАСТОЯЩАЯ ячейка `company_truth.studio_roadmap`
(тот же путь, что у пульта), а импорт `company_truth` вне `mission_control` разрешён только файлам `test_mission_*`
(`test_company_truth_import_ratchet.py`).
"""
from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import owner_view as ow

from spa_core.tests.test_owner_goal_steps import RM, _rm


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
