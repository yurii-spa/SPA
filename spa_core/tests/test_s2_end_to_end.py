"""S2 T09 в CI: сквозной сценарий ``s2_e2e_scene`` с ТЕСТОВЫМ адаптером (моделирование провайдера).

Всё, кроме ответа модели, — настоящее: процессы исполнителя (с SIGKILL и продолжением), коммит, манифест,
материализация, лаунчер с ``execv``, замер ACTIVE по процессам. Реальный провайдер в CI не зовётся; его прогон —
отдельное доказательство (``python -m spa_core.tests.s2_e2e_scene --provider claude_subscription_cli``)."""
from spa_core.tests import s2_e2e_scene as E2E


def test_end_to_end_chain_with_the_test_adapter(tmp_path):
    rec = E2E.run(tmp_path / "e2e", "fixture_test_adapter")
    steps = [s["step"] for s in rec["steps"]]
    assert rec["verdict"] == "OK", rec
    assert steps == ["A.committed", "propose", "approval", "executor-1.killed", "executor-2.refused_while_claim_alive",
                     "executor-2.continued", "B.committed", "run_A", "run_B", "rollback_A"], steps
    by = {s["step"]: s for s in rec["steps"]}
    assert by["propose"]["real_provider"] is False                       # честно помечено: тестовый адаптер
    assert by["executor-1.killed"]["state"] == "applied"
    assert by["executor-2.refused_while_claim_alive"]["rc"] == 3
    assert by["executor-2.continued"]["states"] == ["started", "applied", "checked:satisfied"]
    assert by["executor-2.continued"]["model_calls"] == 1                # модель повторно не звали
    assert tuple(by["B.committed"]["manifest_matches"]) == (True, "") and by["B.committed"]["manifest_on_A"][0] is False
    assert [by[k]["heartbeat"]["note_present"] for k in ("run_A", "run_B", "rollback_A")] == [False, True, False]
    assert rec["leftovers"] == [] and rec["prod_unchanged"] is True
