"""Батарея §29 ТЗ «Portfolio CIO» — ``spa_core/analytics/emergency_mode_census.py``.

Каждая ось проверяется в обе стороны: сцена, где находка ЕСТЬ, и сцена, где её нет,
с названным звеном. Литеральных дат нет: момент сцены — вход (``now``), книги и
капитал ввозятся у §22, порядок шагов цикла подаётся ТЕКСТОМ.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
import types

import pytest

from spa_core.analytics import emergency_mode_census as EM
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

ROOT = EM.REPO_ROOT


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _card(tmp, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


_GOOD_CARD = """\
    ---
    title: x
    ---
    28. Decision expiry
    что-то
    29. Emergency mode
    Обычная yield optimization и emergency risk management — разные процессы.
    При:
    exploit
    depeg
    oracle failure
    withdrawal issue
    protocol suspension
    critical security alert
    сохранность капитала имеет приоритет над:
    gas
    APY
    break-even
    cooldown
    turnover
    Использовать существующую emergency policy либо спроектировать extension отдельно.


    ⸻


    30. Shadow Mode — обязательный этап
    Не подключать реальный capital execution сразу.
    """


def _order_text(*, breaker_first: bool = True, drop: str | None = None,
                dup: str | None = None) -> str:
    """Синтетический cycle_runner: три маркера в заданном порядке."""
    br = "                return _eb_cycle_result\n"
    st = '                    status=f"blocked_by_emergency_{x}",\n'
    ks = "    target_usd = apply_kill_switch_override(target_usd)\n"
    tr = "    _churn = _churn_decide(current_positions, target_usd)\n"
    parts = [st, br, ks, tr] if breaker_first else [ks, tr, st, br]
    text = "".join(parts)
    if drop:
        text = text.replace(EM.ORDER_MARKERS[drop], "nothing_here(")
    if dup:
        text += {"breaker_return": br, "kill_switch_override": ks, "trade_damper": tr}[dup]
    return text


def _halt_order() -> dict:
    return {"kind": "halt_precedes_exit", "lines": {"breaker_return": 10,
                                                      "kill_switch_override": 20,
                                                      "trade_damper": 30}}


def _exit_order() -> dict:
    return {"kind": "exit_precedes_halt", "lines": {"breaker_return": 30,
                                                      "kill_switch_override": 10,
                                                      "trade_damper": 20}}


# ───────────────────── паритет: константы ↔ карточка ─────────────────────────

def test_constants_agree_with_the_real_owner_card():
    card = os.path.join(ROOT, EM.CARD_REL)
    if not os.path.exists(card):
        pytest.fail(f"карточка приказа не найдена: {card} — паритет НЕ ИЗМЕРЕН")
    p = EM.parity(card)
    assert p["agrees"] is True, p["mismatches"] or p["parsed"]
    assert p["order_undercount"] == 0
    assert p["order_priorities_counted"] is False  # заказ хвост не читал — это печатается
    assert len(EM.OWNER_TRIGGERS) == EM.OWNER_TRIGGERS_DECLARED == 6
    assert len(EM.OWNER_PRIORITIES) == EM.OWNER_PRIORITIES_DECLARED == 5


def test_parity_on_a_faithful_scene_card(tmp_path):
    p = EM.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True and p["order_undercount"] == 0


def test_parity_names_a_missing_trigger(tmp_path):
    p = EM.parity(_card(tmp_path, _GOOD_CARD.replace("    withdrawal issue\n", "")))
    assert p["agrees"] is False
    assert any("триггеры карточки" in m for m in p["mismatches"])


def test_parity_names_an_extra_priority(tmp_path):
    p = EM.parity(_card(tmp_path, _GOOD_CARD.replace("    turnover\n", "    turnover\n    slippage\n")))
    assert p["agrees"] is False
    assert any("приоритеты карточки" in m for m in p["mismatches"])


def test_parity_names_a_lost_separation_line(tmp_path):
    body = _GOOD_CARD.replace("    Обычная yield optimization и emergency risk management — разные процессы.\n", "")
    p = EM.parity(_card(tmp_path, body))
    assert p["agrees"] is False and any("разные процессы" in m for m in p["mismatches"])


def test_missing_second_border_refuses_to_count(tmp_path):
    body = _GOOD_CARD.replace("30. Shadow Mode — обязательный этап", "30. Something else")
    p = EM.parity(_card(tmp_path, body))
    assert p["agrees"] is None
    assert "вторая граница" in p["parsed"]["reason"]


def test_unreadable_card_is_a_third_outcome_not_a_fallback(tmp_path):
    p = EM.parity(str(tmp_path / "absent.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────── порядок шагов цикла ───────────────────────────────────

def test_live_cycle_runner_has_the_breaker_return_before_the_exit_legs():
    o = EM.measure_cycle_order(ROOT)
    assert o["kind"] == "halt_precedes_exit", o
    ln = o["lines"]
    assert ln["breaker_return"] < ln["kill_switch_override"] < ln["trade_damper"]
    assert o["breaker_status_marker_hits"] >= 1


def test_order_flips_when_the_exit_legs_precede_the_breaker():
    o = EM.measure_cycle_order(text=_order_text(breaker_first=False))
    assert o["kind"] == "exit_precedes_halt"


def test_order_with_a_missing_marker_is_unmeasured_not_a_verdict():
    o = EM.measure_cycle_order(text=_order_text(drop="kill_switch_override"))
    assert o["kind"] == UNMEASURED and "0 раз" in o["reason"]


def test_order_with_a_duplicated_marker_is_unmeasured():
    o = EM.measure_cycle_order(text=_order_text(dup="trade_damper"))
    assert o["kind"] == UNMEASURED and "2 раз" in o["reason"]


def test_order_unreadable_source_is_unmeasured(tmp_path):
    o = EM.measure_cycle_order(str(tmp_path))
    assert o["kind"] == UNMEASURED and "не прочитан" in o["reason"]


# ───────────────────── ось A: триггеры ───────────────────────────────────────

def test_axis_a_on_the_live_tree_exploit_holds_depeg_exits_security_is_declared_only():
    a = EM.measure_triggers(EM.measure_cycle_order(ROOT), _now())
    assert a["measured"], a
    t = a["triggers"]
    assert t["exploit"]["reach"] == "holds_the_book"
    assert t["exploit"]["doors"]["eb01"]["verdict"] == "HALT"
    assert t["oracle failure"]["reach"] == "holds_the_book"
    assert t["depeg"]["reach"] == "exits_the_book"
    assert t["protocol suspension"]["reach"] == "exits_the_book"
    assert t["withdrawal issue"]["reach"] == "exits_the_book"
    assert t["critical security alert"]["reach"] == "declared_by_registry"
    assert sum(a["tally"].values()) == len(EM.OWNER_TRIGGERS)
    assert a["exit_leg"]["passes"] is True


def test_axis_a_eb_reach_flips_with_the_cycle_order():
    a = EM.measure_triggers(_exit_order(), _now())
    assert a["triggers"]["exploit"]["reach"] == "exits_the_book"
    assert a["triggers"]["exploit"]["doors"]["eb01"]["verdict"] == "HALT"


def test_axis_a_eb_reach_is_unmeasured_when_the_order_is_unmeasured():
    a = EM.measure_triggers({"kind": UNMEASURED, "reason": "x", "lines": {}}, _now())
    assert a["triggers"]["exploit"]["doors"]["eb01"]["reach"] == UNMEASURED
    assert a["triggers"]["exploit"]["reach"] == UNMEASURED


def test_axis_a_reactor_data_dir_is_restored_even_when_the_scene_fails():
    from spa_core.monitoring import threat_reactor as TR
    before = TR._DATA
    with pytest.raises(RuntimeError):
        with EM._reactor_data("/nonexistent/scene"):
            assert str(TR._DATA) == "/nonexistent/scene"
            raise RuntimeError("scene failed")
    assert TR._DATA is before


def test_axis_a_threat_reactor_names_a_depeg_on_the_scene_and_stays_quiet_on_a_calm_one():
    now = _now()
    hot = EM._door_threat_reactor({
        "peg_report.json": {"generated_at": now.isoformat(), "overall_status": "RED",
                            "critical": 1, "worst_adapter": "aave_v3", "worst_deviation_pct": 3.0},
        "emergency_status.json": {"status": "CLEAR"},
        "current_positions.json": {"positions": {"aave_v3": 1.0}}}, now)
    assert hot["detected"] and any("depeg" in t for t in hot["threats"])
    calm = EM._door_threat_reactor({
        "peg_report.json": {"generated_at": now.isoformat(), "overall_status": "GREEN",
                            "critical": 0, "worst_deviation_pct": 0.01},
        "emergency_status.json": {"status": "CLEAR"},
        "current_positions.json": {"positions": {"aave_v3": 1.0}}}, now)
    assert calm["measured"] and calm["detected"] is False


def test_axis_a_governance_pause_tag_is_critical_by_the_real_classifier():
    cls = EM._door_governance_classifier()
    assert cls["measured"] and cls["critical"] is True
    assert "pause" in cls["critical_tags"]


def test_axis_a_rtmr_oracle_freezes_and_liquidity_exits():
    assert EM._door_rtmr("oracle")["action"] == "FREEZE"
    liq = EM._door_rtmr("liquidity")
    assert liq["action"] == "FULL_EXIT" and liq["exits"] is True
    assert EM._door_rtmr("peg", severity="info")["action"] is None


def test_axis_a_posture_exited_zeroes_only_the_scene_protocol():
    pg = EM._door_posture_gate(100_000.0)
    assert pg["measured"] and pg["zeroed"] is True and pg["other_untouched"] is True


def test_axis_a_tier_a_registry_names_security_modules_but_no_exploit_module():
    names, why = EM._tier_a_names()
    assert names is not None, why
    sec = [n for n in names if any(h in n for h in EM.TIER_A_NAME_HINTS["critical security alert"])]
    assert sec, names
    assert not [n for n in names if "exploit" in n]


def test_axis_a_scene_doors_outrank_registry_and_unmeasured_outranks_declared(monkeypatch):
    # реестр недоступен ⇒ tier_a НЕ ИЗМЕРЕН, но триггер с дверью-сценой всё равно получает род
    monkeypatch.setattr(EM, "_tier_a_names", lambda: (None, "реестр не ввезён"))
    a = EM.measure_triggers(_halt_order(), _now())
    assert a["triggers"]["depeg"]["reach"] == "exits_the_book"
    assert a["triggers"]["depeg"]["doors"]["tier_a"]["reach"] == UNMEASURED
    # у триггера без дверей-сцен недоступный реестр даёт НЕ «undetected», а третий исход
    assert a["triggers"]["critical security alert"]["reach"] != "undetected"


def test_axis_a_a_damper_that_blocks_the_exit_turns_depeg_into_a_hold(monkeypatch):
    def block(current, target, trades, capital, now):
        return {"measured": True, "decision": "BLOCK", "reason": "min_hold",
                "is_pure_reduction": False}
    monkeypatch.setattr(EM, "_door_damper", block)
    a = EM.measure_triggers(_halt_order(), _now())
    assert a["exit_leg"]["passes"] is False
    assert a["triggers"]["depeg"]["reach"] == "holds_the_book"
    assert a["triggers"]["withdrawal issue"]["reach"] == "holds_the_book"


# ───────────────────── ось B: приоритеты ─────────────────────────────────────

def test_axis_b_on_the_live_tree_gas_vetoes_and_the_other_four_yield():
    b = EM.measure_priorities(EM.measure_cycle_order(ROOT))
    assert b["measured"], b
    k = {p: r["kind"] for p, r in b["priorities"].items()}
    assert k == {"gas": "vetoes_exit", "APY": "yields_to_exit", "break-even": "yields_to_exit",
                 "cooldown": "yields_to_exit", "turnover": "yields_to_exit"}
    assert b["priorities"]["gas"]["exit_scene"]["verdict"] == "PAUSE"
    assert b["priorities"]["gas"]["control"]["verdict"] == "CLEAR"
    assert b["priorities"]["cooldown"]["control"]["decision"] == "BLOCK"
    assert b["priorities"]["cooldown"]["exit_scene"]["reason"] == "derisk_never_damped"
    assert b["priorities"]["APY"]["shadow_reason"] and b["priorities"]["break-even"]["shadow_reason"]


def test_axis_b_gas_yields_when_the_exit_legs_precede_the_breaker():
    b = EM.measure_priorities(_exit_order())
    assert b["priorities"]["gas"]["kind"] == "yields_to_exit"


def test_axis_b_gas_is_unmeasured_when_the_order_is_unmeasured():
    b = EM.measure_priorities({"kind": UNMEASURED, "reason": "x", "lines": {}})
    assert b["priorities"]["gas"]["kind"] == UNMEASURED


def test_axis_b_gas_control_failure_is_unmeasured_not_a_veto(monkeypatch):
    monkeypatch.setattr(EM, "_door_eb",
                        lambda check, **scene: {"measured": True, "verdict": "PAUSE", "id": "EB-03"})
    b = EM.measure_priorities(_halt_order())
    assert b["priorities"]["gas"]["kind"] == UNMEASURED
    assert "контроль не прошёл" in b["priorities"]["gas"]["why"]


def test_axis_b_cooldown_control_failure_is_unmeasured_not_yielding(monkeypatch):
    def allow_everything(current, target, trades, capital, now):
        return {"measured": True, "decision": "ALLOW", "reason": "within_limits",
                "is_pure_reduction": False}
    monkeypatch.setattr(EM, "_door_damper", allow_everything)
    b = EM.measure_priorities(_halt_order())
    assert b["priorities"]["cooldown"]["kind"] == UNMEASURED
    assert "контроль не прошёл" in b["priorities"]["cooldown"]["why"]


def test_axis_b_a_damper_that_blocks_the_exit_is_a_veto(monkeypatch):
    def block_everything(current, target, trades, capital, now):
        return {"measured": True, "decision": "BLOCK", "reason": "min_hold",
                "is_pure_reduction": False}
    monkeypatch.setattr(EM, "_door_damper", block_everything)
    b = EM.measure_priorities(_halt_order())
    assert b["priorities"]["cooldown"]["kind"] == "vetoes_exit"


def test_axis_b_a_live_door_refusing_the_exit_is_a_veto_on_apy(monkeypatch):
    monkeypatch.setattr(EM, "_door_cio_arming",
                        lambda c, t, r: {"measured": True, "allowed": False, "decision": "HOLD",
                                         "why": "ждём вердикт"})
    b = EM.measure_priorities(_halt_order())
    assert b["priorities"]["APY"]["kind"] == "vetoes_exit"


def test_axis_b_every_kind_is_in_the_declared_vocabulary():
    b = EM.measure_priorities(_halt_order())
    assert all(r["kind"] in EM.PRIORITY_KINDS for r in b["priorities"].values())
    assert sum(b["tally"].values()) == len(EM.OWNER_PRIORITIES)


# ───────────────────── ось C: процессы ───────────────────────────────────────

def _data_dir(tmp, health: dict | None) -> str:
    d = tmp / "data"
    (d / "monitoring").mkdir(parents=True, exist_ok=True)
    if health is not None:
        (d / "agent_health.json").write_text(json.dumps(health), encoding="utf-8")
    return str(d)


def test_axis_c_cycle_links_are_inside_the_yield_cycle_and_agents_are_separate(tmp_path):
    health = {"agents": {h["host"]: {"status": "OK", "last_exit": 0}
                         for h in EM.PROCESS_LINKS.values() if h["host"] != "cycle"}}
    c = EM.measure_processes(ROOT, _data_dir(tmp_path, health))
    kinds = {l: r["kind"] for l, r in c["links"].items()}
    assert kinds["kill_switch_override"] == "inside_yield_cycle"
    assert kinds["trade_step_3"] == "inside_yield_cycle"
    assert kinds["emergency_breakers"] == "inside_yield_cycle"
    assert kinds["threat_reactor"] == "separate_agent"
    assert c["tally"]["inside_yield_cycle"] == 3 and c["tally"]["separate_agent"] == 4
    rk = c["reactor_kickstarts_cycle"]
    assert rk["kickstart"] is True and rk["trades_itself"] is False


def test_axis_c_missing_agent_health_leaves_agents_unmeasured_not_separate(tmp_path):
    c = EM.measure_processes(ROOT, _data_dir(tmp_path, None))
    assert c["links"]["threat_reactor"]["kind"] == UNMEASURED
    assert c["links"]["kill_switch_override"]["kind"] == "inside_yield_cycle"


def test_axis_c_unknown_label_is_unmeasured(tmp_path):
    c = EM.measure_processes(ROOT, _data_dir(tmp_path, {"agents": {"com.spa.other": {}}}))
    assert c["links"]["peg_monitor"]["kind"] == UNMEASURED
    assert "не в agent_health.json" in c["links"]["peg_monitor"]["why"]


# ───────────────────── ось D: инвентарь policy ───────────────────────────────

def test_axis_d_breakers_have_no_exit_rtmr_has_and_cio_has_no_emergency_input():
    d = EM.measure_policy_inventory()
    assert d["breakers"]["has_exit"] is False and "HALT" in d["breakers"]["vocabulary"]
    assert d["rtmr_reaction"]["has_exit"] is True
    assert d["cio_door"]["has_emergency_input"] is False
    assert d["cio_door"]["emergency_params"] == [] and d["cio_door"]["emergency_fields"] == []


def test_axis_d_an_emergency_parameter_on_the_cio_door_would_be_seen(monkeypatch):
    from spa_core.allocator import rebalance_economics as E
    def evaluate(*, current_positions, target_positions, emergency_mode=False):  # noqa: D401
        return None
    monkeypatch.setattr(E, "evaluate", evaluate)
    d = EM.measure_policy_inventory()
    assert d["cio_door"]["has_emergency_input"] is True
    assert d["cio_door"]["emergency_params"] == ["emergency_mode"]


# ───────────────────── живое состояние ───────────────────────────────────────

def test_live_state_absent_files_are_named_not_zero(tmp_path):
    ls = EM.measure_live_state(_data_dir(tmp_path, None))
    assert ls["emergency_status"]["reason"] == "absent"
    assert ls["kill_switch"]["present"] is False
    assert ls["threat_reactor"]["reason"] == "absent"


def test_live_state_reads_the_scene(tmp_path):
    d = _data_dir(tmp_path, None)
    (tmp_path / "data" / "emergency_status.json").write_text(
        json.dumps({"status": "HALT", "triggered": ["EB-01"], "checked_at": "x"}), encoding="utf-8")
    (tmp_path / "data" / "kill_switch_active.json").write_text(json.dumps({"active": True}),
                                                                encoding="utf-8")
    (tmp_path / "data" / "monitoring" / "risk_posture.json").write_text(
        json.dumps({"portfolio": "DEFENSIVE", "entries": {"aave_v3": {}}}), encoding="utf-8")
    ls = EM.measure_live_state(d)
    assert ls["emergency_status"]["status"] == "HALT"
    assert ls["kill_switch"] == {"present": True, "active": True}
    assert ls["posture"] == {"portfolio": "DEFENSIVE", "entries": ["aave_v3"]}


# ───────────────────── прогон целиком ────────────────────────────────────────

def _root(tmp) -> str:
    root = tmp / "root"
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
    (root / "data").mkdir()
    (root / EM.CARD_REL).write_text(textwrap.dedent(_GOOD_CARD), encoding="utf-8")
    # исходник цикла — настоящий (порядок читается из него)
    src = os.path.join(ROOT, EM.CYCLE_RUNNER_REL)
    (root / EM.CYCLE_RUNNER_REL).parent.mkdir(parents=True)
    with open(src, encoding="utf-8") as fh:
        (root / EM.CYCLE_RUNNER_REL).write_text(fh.read(), encoding="utf-8")
    tr = "spa_core/monitoring/threat_reactor.py"
    (root / tr).parent.mkdir(parents=True, exist_ok=True)
    with open(os.path.join(ROOT, tr), encoding="utf-8") as fh:
        (root / tr).write_text(fh.read(), encoding="utf-8")
    return str(root)


def test_run_on_the_scene_root_is_critical_with_both_inversions_named(tmp_path):
    doc = EM.run(root=_root(tmp_path), write=False, now=_now())
    assert doc["overall"] == "CRITICAL" and doc["applied"] is False
    codes = {f["code"] for f in doc["findings"]}
    assert "breaker_halt_precedes_the_exit" in codes
    assert "priority_outranks_capital_preservation:gas" in codes
    assert "exit_leg_lives_in_the_yield_process" in codes
    assert "trigger_declared_only:critical security alert" in codes
    assert doc["counts"]["critical"] == 2
    assert doc["parity"]["agrees"] is True


def test_run_every_kind_printed_belongs_to_a_declared_vocabulary(tmp_path):
    doc = EM.run(root=_root(tmp_path), write=False, now=_now())
    for r in doc["axis_a_triggers"]["triggers"].values():
        assert r["reach"] in EM.REACH_KINDS
        for d in r["doors"].values():
            assert d["reach"] in EM.REACH_KINDS
    for r in doc["axis_b_priorities"]["priorities"].values():
        assert r["kind"] in EM.PRIORITY_KINDS
    for r in doc["axis_c_processes"]["links"].values():
        assert r["kind"] in EM.PROCESS_KINDS
    assert doc["cycle_order"]["kind"] in EM.ORDER_KINDS


def test_run_with_the_exit_legs_first_drops_both_criticals(tmp_path, monkeypatch):
    monkeypatch.setattr(EM, "measure_cycle_order", lambda root=None, text=None: _exit_order())
    doc = EM.run(root=_root(tmp_path), write=False, now=_now())
    codes = {f["code"] for f in doc["findings"]}
    assert "breaker_halt_precedes_the_exit" not in codes
    assert "priority_outranks_capital_preservation:gas" not in codes
    assert doc["counts"]["critical"] == 0


def test_run_unreadable_card_is_unmeasured_not_a_finding(tmp_path):
    root = _root(tmp_path)
    os.remove(os.path.join(root, EM.CARD_REL))
    doc = EM.run(root=root, write=False, now=_now())
    assert any("паритет с карточкой" in u for u in doc["unmeasured"])
    assert not any(f["code"] == "card_parity_mismatch" for f in doc["findings"])


def test_run_write_true_calls_atomic_save_with_data_then_path(tmp_path, monkeypatch):
    calls = []
    import spa_core.utils.atomic as atomic
    monkeypatch.setattr(atomic, "atomic_save", lambda data, path: calls.append((data, path)))
    root = _root(tmp_path)
    EM.run(root=root, write=True, now=_now())
    assert len(calls) == 1
    data, path = calls[0]
    assert isinstance(data, dict) and data["schema"] == "emergency_mode_census/v1"
    assert path == os.path.join(root, EM.REPORT_REL)


def test_parse_now_is_an_input_and_refuses_garbage():
    anchor = _now()  # момент — вход сцены, не литерал календаря
    ts, why = EM.parse_now(anchor.isoformat())
    assert why is None and ts == anchor and ts.tzinfo is not None
    assert EM.parse_now(None) == (None, None)
    assert EM.parse_now("")[1] and EM.parse_now("вчера")[1]


def test_main_refuses_an_unparsable_now_with_code_2(capsys):
    assert EM.main(["--now", "вчера", "--no-write"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_main_on_the_scene_root_returns_1_and_prints_the_verdict(tmp_path, capsys):
    code = EM.main(["--root", _root(tmp_path), "--no-write"])
    out = capsys.readouterr().out
    assert code == 1
    assert "CRITICAL" in out and "halt_precedes_exit" in out and "«gas»" in out


# ───────────────────── проба приёмки ─────────────────────────────────────────

PROBE = "emergency_exit_outranks_the_breaker"


def test_probe_is_registered_and_validates():
    assert PROBE in CA.PROBES
    assert CA.validate_spec(PROBE) is None


def test_probe_on_the_live_tree_is_not_satisfied_and_names_the_lines():
    status, reason = CA.PROBES[PROBE](None)
    assert status == CA.NOT_SATISFIED, reason
    assert "строка" in reason and "all-cash" in reason


def test_probe_three_outcomes_are_distinct(monkeypatch):
    monkeypatch.setattr(EM, "measure_cycle_order",
                        lambda root=None, text=None: {"kind": UNMEASURED, "reason": "нет файла"})
    assert CA.PROBES[PROBE](None)[0] == CA.UNMEASURED
    monkeypatch.setattr(EM, "measure_cycle_order", lambda root=None, text=None: _halt_order())
    assert CA.PROBES[PROBE](None)[0] == CA.NOT_SATISFIED
    monkeypatch.setattr(EM, "measure_cycle_order", lambda root=None, text=None: _exit_order())
    status, reason = CA.PROBES[PROBE](None)
    assert status == CA.SATISFIED and "строка" in reason


def test_probe_import_failure_is_unmeasured(monkeypatch):
    import sys
    import spa_core.analytics as pkg
    # `from pkg import mod` сначала берёт АТРИБУТ пакета, и только без него идёт в sys.modules;
    # `None` там заставляет интерпретатор поднять ImportError — штатная дверь, не подделка
    monkeypatch.delattr(pkg, "emergency_mode_census", raising=False)
    monkeypatch.setitem(sys.modules, "spa_core.analytics.emergency_mode_census", None)
    status, reason = CA.PROBES[PROBE](None)
    assert status == CA.UNMEASURED and "не импортирован" in reason
