"""Owner Remote shared logic — classifier safety, investment slice, gateway plan + idempotency.

Hermetic: the idempotency test redirects the pending ledger to a tmp file and stubs the canonical
task writer, so no real tracker card is created. RED must win over YELLOW/GREEN everywhere.
"""

import pytest

from spa_core.owner_remote import answers, gateway
from spa_core.owner_remote.intent import classify, is_red
from spa_core.owner_remote.slice import build_investment_slice


# ── classifier (the safety authority) ────────────────────────────────────────────────────
RED = [
    "переведи деньги", "переведи 10000 в aave", "купи BTC", "продай позицию pendle",
    "выведи весь кэш", "подпиши транзакцию", "включи live execution", "перейти на live",
    "измени risk limit", "отключи стоп-кран", "transfer money", "sell the position",
    "sign the transaction", "enable live execution", "disable kill switch",
    # ambiguous → RED wins over the task verb
    "создай задачу перевести деньги в aave", "поставь задачу продать pendle",
]
YELLOW = ["создай задачу проверить APY Morpho", "запиши решение пока не запускать X",
          "create a task to review adapters"]
GREEN = ["покажи капитал", "какие стратегии в paper", "что требует моего внимания",
         "почему Aave заблокирован", "открой систему", "статус Aave", "запиши идею про Base"]


@pytest.mark.parametrize("t", RED)
def test_red_never_downgraded(t):
    assert classify(t)["zone"] == "RED", t
    assert is_red(t), t


@pytest.mark.parametrize("t", YELLOW)
def test_yellow(t):
    assert classify(t)["zone"] == "YELLOW", t


@pytest.mark.parametrize("t", GREEN)
def test_green(t):
    assert classify(t)["zone"] == "GREEN", t


# ── investment slice (Aave vertical) ─────────────────────────────────────────────────────
def test_slice_aave_is_honest():
    s = build_investment_slice("aave_v3")
    assert s["entity"]["protocol"] == "aave_v3"
    # opportunity is real, APY/TVL unevidenced
    assert s["opportunity"]["protocol"]["status"] == "AVAILABLE"
    assert "UNEVIDENCED" in s["opportunity"]["apy_evidence"]["value"]
    # no paper position → position + capital marked honestly, never invented
    assert s["result"]["held"]["value"] is False
    assert s["position"]["position_id"]["status"] == "MISSING"
    assert s["capital"]["allocated_to_this"]["value"] in (0, 0.0)
    # EXECUTED RiskPolicy provenance + the two failing gates
    assert s["risk"]["policy_version"]["value"] == "v1.0"
    assert s["risk"]["policy_kind"]["value"] == "EXECUTED"
    assert s["risk"]["fundable"]["value"] is False
    gates = {g["rule"]: g["pass"] for g in s["risk"]["gates"]["value"]}
    assert any("evidenced" in r and not p for r, p in gates.items())   # APY-evidence gate fails
    assert any("TVL" in r and not p for r, p in gates.items())          # static-TVL floor fails
    # every field carries a real status enum, never blank
    for stage in ("opportunity", "strategy", "position", "capital"):
        for f in s[stage].values():
            assert f["status"] in ("AVAILABLE", "DERIVABLE", "PARTIAL", "MISSING", "NOT_APPLICABLE")


def test_slice_pendle_held_surfaces_discrepancy():
    """Pendle HAS a paper position; the position-recorded APY (live) may differ from the adapter
    snapshot (unevidenced). Both must be shown; the discrepancy is never silently reconciled."""
    s = build_investment_slice("pendle")
    assert s["result"]["held"]["value"] is True
    assert s["position"]["position_id"]["status"] == "AVAILABLE"
    assert s["capital"]["allocated_to_this"]["value"] == 20000.0
    # position-recorded APY is live-evidenced …
    assert s["position"]["position_apy_source"]["value"] == "live"
    # … while the adapter opportunity snapshot is unevidenced — a real, surfaced discrepancy
    assert "UNEVIDENCED" in s["opportunity"]["apy_evidence"]["value"]
    assert s["position"]["gross_apy"]["value"] != s["opportunity"]["apy_pct"]["value"]
    assert "HELD" in s["result"]["label"]["value"]


def test_comparison_is_factual_not_ranking():
    from spa_core.owner_remote.compare import compare_slices
    c = compare_slices("aave_v3", "pendle")
    assert "ranking" in c["kind"].lower() and "not" in c["kind"].lower()
    # both objects present with the SAME row keys read from the SAME projection
    assert c["a"]["protocol"] and c["b"]["protocol"]
    assert c["a"]["held"] is False and c["b"]["held"] is True
    assert c["b"]["paper_capital_usd"] == 20000.0
    # no score/rank field is emitted
    assert not any(k in c for k in ("score", "rank", "winner", "recommendation"))


def test_telegram_os_operational_queries():
    """Telegram Studio-OS queries answer deterministically from the SAME projections as desktop."""
    r = answers.route_green
    assert "актив" in r("Какие задачи активны?", None).lower() or "нет" in r("Какие задачи активны?", None).lower()
    assert "заблок" in r("Что заблокировано?", None).lower()
    assert "решени" in r("Какие решения ждут меня?", None).lower()
    assert "заверш" in r("Что было сделано сегодня?", None).lower()
    assert "следующ" in r("Какой следующий шаг по Earn DeFi?", None).lower()
    # "decided about X" resolves to decisions/reports, never invents
    ans = r("Что мы решили по Position Passport?", None)
    assert "Position Passport" in ans


def test_telegram_comparison_answer():
    a = answers.route_green("Сравни Aave и Pendle", None)
    assert "Aave" in a and "Pendle" in a
    assert "рекомендаци" not in a.lower() or "не рекомендация" in a.lower()  # explicitly not advice


def test_answers_read_same_truth():
    # the Telegram answer for Aave states the SAME result the slice computes
    a = answers.answer_slice("aave_v3")
    assert "NOT FUNDABLE" in a and "Aave" in a
    cap = answers.answer_capital()
    assert "PAPER" in cap  # never REAL for the current paper book


# ── gateway plan + allow-list + idempotency ──────────────────────────────────────────────
def test_gateway_plans():
    assert gateway.plan("Переведи 10000 в Aave", source="telegram_text")["action"] == "block"
    assert gateway.plan("Создай задачу перевести деньги", source="telegram_text")["action"] == "block"  # RED wins
    p = gateway.plan("Создай задачу проверить Morpho", source="telegram_text", message_id=1)
    assert p["action"] == "confirm_task" and p["token"] == "telegram_text:1"
    assert gateway.plan("Покажи капитал", source="telegram_text")["action"] == "answer"
    assert gateway.plan("Запиши решение не запускать X", source="telegram_text")["action"] == "decision_draft"


def test_is_owner_allow_list():
    assert gateway.is_owner("123", "123") is True
    assert gateway.is_owner("999", "123") is False
    assert gateway.is_owner("123", None) is False      # fail-closed when owner unset
    assert gateway.is_owner(None, "123") is False


def test_confirm_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "PENDING", tmp_path / "pending.json")
    created = []

    def fake_save(text, source="telegram", transcript=None):
        pathobj = tmp_path / f"card-{len(created)}.md"
        created.append(pathobj)
        return pathobj, "проверить Morpho"

    import spa_core.telegram.inbox_intake as ii
    monkeypatch.setattr(ii, "save_inbox_task", fake_save)

    tok = gateway.token_for("telegram_text", 42)
    gateway.register_pending(tok, title="проверить Morpho", body="проверить Morpho", source="telegram_text")
    r1 = gateway.confirm_task(tok)
    r2 = gateway.confirm_task(tok)          # Telegram retry / double-tap
    assert r1["ok"] and r2["ok"]
    assert r2["idempotent"] is True
    assert r1["id"] == r2["id"]
    assert len(created) == 1, "double-confirm must create exactly ONE canonical task"


def test_cancel_blocks_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "PENDING", tmp_path / "pending.json")
    tok = gateway.token_for("telegram_text", 7)
    gateway.register_pending(tok, title="x", body="x", source="telegram_text")
    gateway.cancel(tok)
    r = gateway.confirm_task(tok)
    assert r["ok"] is False and r["error"] == "cancelled"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
