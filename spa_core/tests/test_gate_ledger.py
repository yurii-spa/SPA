"""Предгейтовая цель обязана сохраняться РЯДОМ с послегейтовой.

Находка (карточка `agent-predgateovaya-tsel-ne-sohranyaetsya`, 08.08): чтобы
воспроизвести цикл и ответить «что аллокатор ПРОСИЛ, что зарубил гейт и по
какому правилу», не хватало самого предмета отказа. `_pre_gate_target` жил
только в памяти `run_cycle`; в артефакт попадало производное — `policy_refusals`
(и только по TVL-замороженным пулам) плюс строка в `cash_attribution`. Приёмка
ADR-073 из-за этого осталась модульной, а не сквозной, и это записано в самом
ADR как ограничение.

Файл — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ В ОБЕ СТОРОНЫ, и обе стороны обязательны:

* авария видна: раскладка, зарубленная гейтом, лежит в артефакте вместе с
  названным правилом и суммой (тесты 1, 5);
* ложной аварии нет: раскладка, прошедшая гейт целиком, НЕ порождает ни одной
  «зарубленной» строки (тесты 2, 6).

И третья, отдельная граница: «не измерено» ≠ «причин нет» (тесты 3, 4, 7).
Снятие, которое гейт не объяснил, обязано остаться неатрибутированным и попасть
в `unnamed_removed_usd`, а не тихо получить ближайшее правдоподобное правило.

Наблюдаемость: ни один тест здесь не трогает пороги RiskPolicy, веса, kill-switch
или живой трек. Числа взяты из реального цикла 2026-08-06 06:00 UTC.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from spa_core.paper_trading.allocation_rationale import (
    RATIONALE_FILENAME,
    write_shadow_rationale,
)
from spa_core.paper_trading.cycle_gates import GATE_LEDGER_SCHEMA, build_gate_ledger

CAP = 100_000.0

# Цель аллокатора того цикла: 95 % развёрнуто.
PRE = {"aave_v3": 40_000.0, "pendle": 20_000.0, "maple": 20_000.0,
       "morpho_blue_base": 10_000.0, "morpho_steakhouse": 5_000.0}
# ADR-053 обнулил ногу без живого TVL; перераздачи не было.
POST_FROZEN = dict(PRE, morpho_blue_base=0.0)

GATE_FROZE = {"error": None, "approved": True, "trimmed": False,
              "violations": [], "tvl_unverified": ["morpho_blue_base"]}
GATE_CLEAN = {"error": None, "approved": True, "trimmed": False,
              "violations": [], "tvl_unverified": []}


def _ledger(**kw):
    kw.setdefault("allocator_target", PRE)
    kw.setdefault("pre_gate_target", PRE)
    kw.setdefault("post_gate_target", POST_FROZEN)
    kw.setdefault("gate", GATE_FROZE)
    kw.setdefault("frozen_pools", ["morpho_blue_base"])
    return build_gate_ledger(**kw)


def _change(led, proto):
    return next((c for c in led["changes"] if c["protocol"] == proto), None)


# ── 1. АВАРИЯ ВИДНА: что просили, что осталось, кто и по какому правилу срезал ──

def test_gate_removal_is_recorded_with_its_named_rule():
    led = _ledger()

    # Сам предмет отказа — обе цели лежат рядом.
    assert led["pre_gate_target"]["morpho_blue_base"] == 10_000.0
    assert led["post_gate_target"]["morpho_blue_base"] == 0.0

    row = _change(led, "morpho_blue_base")
    assert row is not None, "зарубленная гейтом нога исчезла из ledger'а"
    assert row["direction"] == "removed"
    assert row["delta_usd"] == -10_000.0
    assert row["rule"] == "tvl_unverified_fail_closed"
    assert row["rule_ref"] == "ADR-053"
    assert row["attributed"] is True
    assert row["status"] == "named"

    s = led["summary"]
    assert s["asked_usd"] == 95_000.0
    assert s["kept_usd"] == 85_000.0
    assert s["removed_usd"] == 10_000.0
    assert s["named_removed_usd"] == 10_000.0
    assert s["unnamed_removed_usd"] == 0.0
    assert s["attribution_complete"] is True
    assert led["schema"] == GATE_LEDGER_SCHEMA


# ── 2. ЛОЖНОЙ АВАРИИ НЕТ: цель, прошедшая целиком, не рождает «зарубленных» ──

def test_untouched_target_produces_no_phantom_removals():
    led = _ledger(post_gate_target=dict(PRE), gate=GATE_CLEAN, frozen_pools=[])
    assert led["changes"] == []
    assert led["summary"]["removed_usd"] == 0.0
    assert led["summary"]["added_usd"] == 0.0
    assert led["summary"]["asked_usd"] == led["summary"]["kept_usd"] == 95_000.0
    assert led["summary"]["attribution_complete"] is True


# ── 3. «Не измерено» ≠ «причин нет» ──────────────────────────────────────────

def test_unnamed_removal_stays_unattributed_and_is_counted():
    """Гейт срезал, но правила не назвал — правдоподобное подставлять нельзя."""
    led = _ledger(post_gate_target=dict(PRE, pendle=12_000.0),
                  gate=GATE_CLEAN, frozen_pools=[])
    row = _change(led, "pendle")
    assert row["direction"] == "removed"
    assert row["rule"] is None
    assert row["attributed"] is False
    assert row["status"] == "not_measured"
    assert led["summary"]["unnamed_removed_usd"] == 8_000.0
    assert led["summary"]["named_removed_usd"] == 0.0
    # Полнота атрибуции — утверждение, а не умолчание.
    assert led["summary"]["attribution_complete"] is False


def test_gate_error_never_lends_its_rule_to_a_removal():
    """Гейт не вычислен ⇒ ни одно снятие не смеет получить его правило."""
    led = _ledger(gate={"error": "boom", "approved": False, "trimmed": True,
                        "violations": [], "tvl_unverified": ["morpho_blue_base"]})
    assert led["gate_evaluated"] is False
    assert led["gate_error"] == "boom"
    row = _change(led, "morpho_blue_base")
    assert row["rule"] is None and row["attributed"] is False
    assert row["status"] == "not_measured"
    assert led["summary"]["attribution_complete"] is False


def test_min_cash_trim_is_named_only_when_the_gate_declared_it():
    trimmed_gate = dict(GATE_CLEAN, trimmed=True)
    led = _ledger(post_gate_target=dict(PRE, maple=15_000.0),
                  gate=trimmed_gate, frozen_pools=[])
    row = _change(led, "maple")
    assert row["rule"] == "min_cash_buffer_trim"
    assert row["attributed"] is True
    assert led["summary"]["named_removed_usd"] == 5_000.0


# ── 4. Итог перераздачи ADR-072 — вместе с freed_usd ─────────────────────────

def test_redistribution_outcome_and_freed_budget_are_recorded():
    led = _ledger(
        post_gate_target=dict(POST_FROZEN, compound_v3=10_000.0),
        redistribution={"status": "applied", "freed_usd": 10_000.0,
                        "added": {"compound_v3": 10_000.0},
                        "second_gate_violations": []},
    )
    assert led["redistribution"]["status"] == "applied"
    assert led["redistribution"]["freed_usd"] == 10_000.0
    row = _change(led, "compound_v3")
    assert row["direction"] == "added"
    assert row["rule"] == "adr_072_redistribution"
    assert led["summary"]["added_usd"] == 10_000.0


def test_rejected_redistribution_keeps_the_second_gate_violation():
    led = _ledger(redistribution={"status": "rejected_by_second_gate",
                                  "freed_usd": 10_000.0, "added": {},
                                  "second_gate_violations": ["Chain concentration"]})
    assert led["redistribution"]["status"] == "rejected_by_second_gate"
    assert led["redistribution"]["second_gate_violations"] == ["Chain concentration"]
    # Слово гейта принято: в книге ноги нет.
    assert led["post_gate_target"]["morpho_blue_base"] == 0.0


def test_missing_redistribution_reads_as_not_attempted_not_as_nothing_freed():
    led = _ledger(redistribution=None)
    assert led["redistribution"]["status"] == "not_attempted"
    assert led["redistribution"]["freed_usd"] is None


# ── 5/6/7. Тот же контроль в обе стороны — уже В АРТЕФАКТЕ, не в памяти ──────

def _write(tmp_path: Path, **kw) -> dict:
    kw.setdefault("data_dir", tmp_path)
    kw.setdefault("current_positions", {"aave_v3": 40_000.0})
    kw.setdefault("target_positions", POST_FROZEN)
    kw.setdefault("apy_pct", {"aave_v3": 4.99})
    kw.setdefault("apy_sources", {"aave_v3": "live"})
    kw.setdefault("capital_usd", CAP)
    kw.setdefault("cycle_date", "2026-08-06")
    kw.setdefault("run_ts", "2026-08-06T06:00:30Z")
    write_shadow_rationale(**kw)
    return json.loads((tmp_path / RATIONALE_FILENAME).read_text(encoding="utf-8"))


def test_artifact_carries_the_pre_gate_ask_beside_the_post_gate_book(tmp_path):
    doc = _write(tmp_path, gate_ledger=_ledger())
    led = doc["gate_ledger"]
    assert led["pre_gate_target"]["morpho_blue_base"] == 10_000.0
    assert led["post_gate_target"]["morpho_blue_base"] == 0.0
    assert _change(led, "morpho_blue_base")["rule"] == "tvl_unverified_fail_closed"


def test_artifact_shows_no_removal_when_the_gate_took_nothing(tmp_path):
    doc = _write(tmp_path, gate_ledger=_ledger(post_gate_target=dict(PRE),
                                               gate=GATE_CLEAN, frozen_pools=[]))
    assert doc["gate_ledger"]["changes"] == []
    assert doc["gate_ledger"]["summary"]["removed_usd"] == 0.0


def test_artifact_says_not_measured_when_the_cycle_supplied_no_ledger(tmp_path):
    """Отсутствие ledger'а обязано читаться как «не измерено», не как «чисто»."""
    doc = _write(tmp_path)
    assert doc["gate_ledger"]["status"] == "not_measured"
    assert "unknown" in doc["gate_ledger"]["reason"]
    assert "changes" not in doc["gate_ledger"]


# ── Проводка: цикл обязан ПЕРЕДАВАТЬ ledger, иначе всё выше — украшение ──────

def test_cycle_runner_is_wired_to_build_and_pass_the_ledger():
    assert "gate_ledger" in inspect.signature(write_shadow_rationale).parameters
    src = Path(__file__).resolve().parents[1] / "paper_trading" / "cycle_runner.py"
    text = src.read_text(encoding="utf-8")
    assert "build_gate_ledger(" in text, "цикл не строит ledger"
    assert "gate_ledger=_gate_ledger" in text, "ledger не доезжает до артефакта"
