"""S5 (E8.2/E8.3): три сквозных сценария на стенде — продукт, дефект, paper-исследование — каждый с отказом без
допуска, SIGKILL на границе applied и холодным продолжением новым процессом. Провайдер тестовый (synthetic)."""
import subprocess

from spa_core.studio_os import executor as ex
from spa_core.tests import s5_stand_scenarios as s5


def test_three_scenarios_end_to_end_with_interruption_and_cold_resume(tmp_path):
    r = s5.run(tmp_path / "s5")                       # tmp_path лежит во временном каталоге системы — admission стенда
    for name, sc in r["scenarios"].items():
        assert sc["verdict"] == "OK", (name, sc)
        assert sc["unapproved"]["refused"] and sc["unapproved"]["state"] == "new", name     # без допуска — ни шага
        assert sc["killed_at"] == "applied", name                                           # прерван на границе
        assert sc["no_double_effect"] and sc["model_calls"] <= ex.MAX_CALLS, name          # без повтора эффекта/вызова
        assert sc["synthetic"] is True and sc["owner_interventions"] == 0, name
    assert r["scenarios"]["B_defect"]["defect_reproduced"] is True
    c = r["scenarios"]["C_research"]["role"]
    assert c["attempts_used"] == 1 and len(c["prereg_sha256"]) == 64
    leftovers = subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True).stdout
    assert str(tmp_path) not in leftovers                                                    # процессов сцены не осталось
