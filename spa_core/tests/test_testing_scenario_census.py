"""Батарея §37 ТЗ «Portfolio CIO» — ``spa_core/analytics/testing_scenario_census.py``.

Это и есть «scenario tests» владельца: каждая из пятнадцати сцен прогоняется через ЖИВУЮ
дверь денежного пути на литералах владельца (тест ``test_scene_NN_…``) и на ПОРВАННОЙ сцене
(``test_scene_NN_torn_…``), где ответ обязан смениться. Имена этих функций объявлены в
реестре прибора (``SCENE_TESTS``) и сверяются с деревом разбором AST — переименование здесь
краснит ``test_registry_refs_are_all_present_in_this_tree``.

Сцены 1 и 2 — КОНТРАРНЫЕ на живом дереве (замер #1100): их тест утверждает ИЗМЕРЕННЫЙ ответ
двери и называет причину числом двери, а не подгоняет ожидание под результат. Литеральных
дат нет, кроме якоря газового монитора, который передаётся входом (``today=``).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from pathlib import Path

from spa_core.analytics import testing_scenario_census as T
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

PROBE = "owner_scenes_pass_and_discriminate"
_REPO = T.REPO_ROOT
_LIVE_CARD = os.path.join(_REPO, T.CARD_REL)


def _card(tmp: Path, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def _good_card_text() -> str:
    """Карточка в форме владельца: заголовок, требование, 15 сцен, вторая граница."""
    out = ["---", "title: x", "---", "36. Owner UI", "что-то", T.SECTION_HEAD, T.OWNER_REQUIREMENT_LINE]
    for n, title, expected in T.OWNER_SCENES:
        out += [f"Test {n} — {title}", "вход сцены", "", "Expected:"]
        if n == 15:
            out.insert(len(out) - 1, "<!-- источник: inbox-x.md строки 1-2 -->")
        out += list(expected) + ["", "", "⸻", ""]
    out += [T.NEXT_SECTION_HEAD, "хвост"]
    return "\n".join(out) + "\n"


# ───────────────────────────── паритет с карточкой ────────────────────────────

def test_constants_agree_with_the_real_owner_card():
    p = T.parity(_LIVE_CARD)
    assert p["parsed"]["measured"], p["parsed"].get("reason")
    assert p["agrees"] is True, p["mismatches"]
    assert len(p["parsed"]["scenes"]) == T.OWNER_SCENES_DECLARED == 15


def test_parity_agrees_on_a_card_in_the_owner_form(tmp_path):
    p = T.parity(_card(tmp_path, _good_card_text()))
    assert p["agrees"] is True, p["mismatches"]


def test_parity_names_a_renamed_scene_instead_of_hiding_it(tmp_path):
    text = _good_card_text().replace("Test 12 — oscillating APYs", "Test 12 — oscillating rates")
    p = T.parity(_card(tmp_path, text))
    assert p["agrees"] is False
    assert any("Test 12" in m and "oscillating rates" in m for m in p["mismatches"])


def test_parity_names_a_changed_expectation(tmp_path):
    text = _good_card_text().replace("никакого churn.", "немного churn.")
    p = T.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("ожидание" in m for m in p["mismatches"])


def test_parity_names_a_missing_requirement_line(tmp_path):
    text = _good_card_text().replace(T.OWNER_REQUIREMENT_LINE + "\n", "")
    p = T.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("automated tests" in m for m in p["mismatches"])


def test_unreadable_card_is_a_third_outcome_not_a_fallback_to_constants(tmp_path):
    p = T.parity(str(tmp_path / "missing.md"))
    assert p["parsed"]["measured"] is False and p["agrees"] is None
    assert "не прочитана" in p["parsed"]["reason"]


def test_missing_second_border_refuses_to_count(tmp_path):
    text = _good_card_text().replace(T.NEXT_SECTION_HEAD, "38b. Something else")
    p = T.parity(_card(tmp_path, text))
    assert p["parsed"]["measured"] is False and "вторая граница" in p["parsed"]["reason"]


def test_parse_scenes_skips_html_comments_and_reads_expected_after_the_lead():
    body = ["Test 15 — same snapshot determinism", "", "<!-- источник: x -->", "", "100 запусков.",
            "Expected:", "идентичный calculation output.", "", "⸻"]
    got = T.parse_scenes(body)
    assert got == [{"n": 15, "title": "same snapshot determinism",
                    "expected": ["идентичный calculation output."], "inputs": ["100 запусков."]}]


def test_order_g970_named_no_count_so_no_shift_is_computed():
    assert T.ORDER_G970_NAMED["scenes"] is None and T.ORDER_G970_NAMED["example_named"] == "Test 1"
    assert T.parity(_LIVE_CARD)["order_undercount"] is None


# ───────────────────────────── контроль ───────────────────────────────────────

def test_control_is_ok_on_the_live_doors():
    ok, why, base = T.control()
    assert ok, why
    assert base == {"economics": "ACT", "gate_approved": True, "gate_error": None}


def test_a_broken_control_blocks_the_count(monkeypatch):
    monkeypatch.setattr(T, "control", lambda: (False, "сцена сломана: X", {}))
    doc = T.run(write=False)
    assert doc["scenes"] == {} and doc["tally"] is None
    assert doc["overall"] == "UNCHECKED"
    assert any("контрольная сцена сломана" in u and "X" in u for u in doc["unmeasured"])


# ───────────────────────────── сцены владельца (ось B/C) ───────────────────────

def test_scene_01_owner_numbers_cannot_reach_the_paper_gain_band():
    """Aave 40 %/3 %, Morpho 10 %/6 %: наибольший выигрыш ОДНОГО хода 0,45 пп < полосы 0,50 пп."""
    s = T.scene_01()
    assert s["door"]["kind"] == "present"
    assert s["owner"]["holds"] is False
    assert s["owner"]["full_move"]["token"] == "HOLD"
    assert any(r.startswith("move_turnover_over_budget") for r in s["owner"]["full_move"]["reasons"])
    assert s["owner"]["bounded_move"]["token"] == "HOLD"
    assert s["owner"]["bounded_move"]["reasons"] == ["gain_below_band:0.450pp<0.500pp"]
    assert s["owner"]["largest_gain_one_move_pp"] == 0.45 < s["owner"]["required_gain_pp"] == 0.5


def test_scene_01_torn_a_wider_spread_acts():
    s = T.scene_01()
    assert s["torn"]["holds"] is True
    assert s["torn"]["bounded_move"]["token"] == "ACT"
    assert s["torn"]["bounded_move"]["legs"] == {T.AAVE: -15000.0, T.MORPHO: 15000.0}


def test_scene_02_the_price_door_acts_on_a_captured_spike():
    s = T.scene_02()
    assert s["door"]["kind"] == "partial" and any("persistence" in m for m in s["door"]["missing_inputs"])
    assert s["owner"]["holds"] is False and s["owner"]["spike_captured"]["token"] == "ACT"


def test_scene_02_torn_the_rate_back_holds():
    s = T.scene_02()
    assert s["torn"]["holds"] is True and s["torn"]["rate_back"]["token"] == "HOLD"


def test_scene_03_two_points_hold_for_the_gain_band_not_persistence():
    s = T.scene_03()
    assert s["owner"]["holds"] is True and s["owner"]["two_points"]["token"] == "HOLD"
    assert any(r.startswith("gain_below_band") for r in s["owner"]["two_points"]["reasons"])
    assert any("persistence" in m for m in s["door"]["missing_inputs"])


def test_scene_03_torn_a_six_point_spread_acts():
    s = T.scene_03()
    assert s["torn"]["holds"] is False and s["torn"]["six_points"]["token"] == "ACT"


def test_scene_04_a_t3_candidate_at_twenty_percent_is_refused():
    s = T.scene_04()
    assert s["door"]["kind"] == "present" and s["owner"]["holds"] is True
    g = s["owner"]["t3_candidate"]
    assert g["approved"] is False and any("T3" in v for v in g["violations"])


def test_scene_04_torn_the_same_candidate_as_t1_passes():
    s = T.scene_04()
    assert s["torn"]["holds"] is False and s["torn"]["t1_candidate"]["approved"] is True


def test_scene_05_capacity_cap_shrinks_the_position():
    s = T.scene_05()
    assert s["owner"]["holds"] is True
    assert s["owner"]["shallow_pool"][T.CANDIDATE] == 5000.0 < s["owner"]["proposed_usd"]
    assert any("marginal APY" in m for m in s["door"]["missing_inputs"])


def test_scene_05_torn_a_deep_pool_is_not_capped():
    s = T.scene_05()
    assert s["torn"]["holds"] is False and s["torn"]["deep_pool"][T.CANDIDATE] == 20000.0


def test_scene_06_shared_chain_dependency_is_capped():
    s = T.scene_06()
    assert s["owner"]["holds"] is True
    assert any("L2" in v for v in s["owner"]["same_chain"]["violations"])
    assert any("СЕТЬ" in m for m in s["door"]["missing_inputs"])


def test_scene_06_torn_split_chains_pass():
    s = T.scene_06()
    assert s["torn"]["holds"] is False and s["torn"]["split_chains"]["approved"] is True


def test_scene_07_stale_liquidity_gets_no_fresh_capital():
    s = T.scene_07()
    assert s["door"]["kind"] == "present" and s["owner"]["holds"] is True
    g = s["owner"]["stale_liquidity"]
    assert T.MORPHO in g["tvl_unverified"] and T.MORPHO not in g["target_usd"]


def test_scene_07_torn_live_liquidity_is_funded():
    s = T.scene_07()
    assert s["torn"]["holds"] is False and s["torn"]["live_liquidity"]["target_usd"][T.MORPHO] == 20000.0


def test_scene_08_three_high_gas_days_zero_the_base_leg():
    s = T.scene_08()
    assert s["owner"]["holds"] is True
    g = s["owner"]["high_gas"]
    assert g["kill_switch_active"] is True and g["consecutive_above"] == 3
    assert g["target_usd"] == {T.BASE_VAULT: 0.0, T.AAVE: 30000.0}
    assert any("Ethereum" in m for m in s["door"]["missing_inputs"])


def test_scene_08_torn_low_gas_leaves_the_leg():
    s = T.scene_08()
    assert s["torn"]["holds"] is False and s["torn"]["low_gas"]["target_usd"][T.BASE_VAULT] == 20000.0


def test_scene_09_gas_falling_releases_the_leg():
    s = T.scene_09()
    assert s["owner"]["holds"] is True and s["owner"]["gas_falls"]["kill_switch_active"] is False
    assert s["owner"]["gas_falls"]["target_usd"][T.BASE_VAULT] == 20000.0


def test_scene_09_torn_gas_staying_high_keeps_it_zeroed():
    s = T.scene_09()
    assert s["torn"]["holds"] is False and s["torn"]["gas_stays"]["target_usd"][T.BASE_VAULT] == 0.0


def test_scene_10_new_cash_funds_the_gap_without_an_aave_leg():
    s = T.scene_10()
    assert s["owner"]["holds"] is True
    assert s["owner"]["economics"]["legs"] == {T.MORPHO: 10000.0}
    assert s["owner"]["economics"]["token"] == "ACT" and s["owner"]["damper"]["token"] == "ALLOW"
    assert any("allocate" in m for m in s["door"]["missing_inputs"])


def test_scene_10_torn_selling_aave_while_cash_idles_is_named():
    s = T.scene_10()
    assert s["torn"]["holds"] is False and s["torn"]["economics"]["legs"][T.AAVE] == -10000.0


def test_scene_11_recomputation_on_the_vanished_rate_holds():
    s = T.scene_11()
    assert s["owner"]["holds"] is True
    assert s["owner"]["at_recommendation"]["token"] == "ACT" and s["owner"]["re_evaluated"]["token"] == "HOLD"
    assert any("decision_ttl_s=600" in m for m in s["door"]["missing_inputs"])


def test_scene_11_torn_a_rate_that_stays_acts():
    s = T.scene_11()
    assert s["torn"]["holds"] is False and s["torn"]["re_evaluated"]["token"] == "ACT"


def test_scene_12_oscillation_never_moves_capital():
    s = T.scene_12()
    assert s["door"]["kind"] == "present" and s["owner"]["holds"] is True
    assert s["owner"]["step_1"]["token"] == "HOLD" and s["owner"]["step_2"]["token"] == "HOLD"
    assert any(r.startswith("reversal_of_recent_move") for r in s["owner"]["step_2"]["reasons"])
    assert s["owner"]["damper_step_2"] == {"token": "BLOCK", "reason": "min_hold"}


def test_scene_12_torn_a_wide_swing_acts_on_step_one():
    s = T.scene_12()
    assert s["torn"]["holds"] is False and s["torn"]["step_1"]["token"] == "ACT"


def test_scene_13_the_cap_binds_the_optimum():
    s = T.scene_13()
    assert s["owner"]["holds"] is True
    assert s["owner"]["allocator_capped"][T.CANDIDATE] == s["owner"]["t1_cap"] == 0.4
    g = s["owner"]["gate_on_optimum"]
    assert g["approved"] is False and any("70.0% exceeds T1 limit 40.0%" in v for v in g["violations"])
    assert "25 %" in s["door"]["note"] and "не сравниваются" in s["door"]["note"]


def test_scene_13_torn_a_target_under_the_cap_is_untouched():
    s = T.scene_13()
    assert s["torn"]["holds"] is False
    assert s["torn"]["was_capped"] is False and s["torn"]["gate_under_cap"]["approved"] is True


def test_scene_14_a_block_signal_zeroes_the_best_yield():
    s = T.scene_14()
    assert s["owner"]["holds"] is True
    assert s["owner"]["block_signal"]["target_usd"] == {T.AAVE: 0.0, T.MORPHO: 90000.0}
    det = s["owner"]["detectors"]
    assert det["tier_a_total"] >= 1
    assert [m["module"] for m in det["by_tier"]["C"] if "incident" in m["module"]] == ["protocol_security_incident_tracker"]
    assert any("тире C" in m for m in s["door"]["missing_inputs"])


def test_scene_14_torn_an_ok_signal_leaves_the_target():
    s = T.scene_14()
    assert s["torn"]["holds"] is False
    assert s["torn"]["ok_signal"]["target_usd"] == {T.AAVE: 50000.0, T.MORPHO: 40000.0}


def test_scene_15_hundred_runs_are_byte_identical():
    s = T.scene_15()
    assert s["owner"]["holds"] is True
    assert s["owner"]["runs"] == T.DETERMINISM_RUNS == 100
    assert s["owner"]["distinct_economics"] == 1 and s["owner"]["distinct_gate"] == 1


def test_scene_15_torn_the_comparator_sees_one_changed_run():
    s = T.scene_15()
    assert s["torn"]["holds"] is False and s["torn"]["distinct_economics"] == 2


def test_tier_a_patch_is_undone_after_the_scene():
    from spa_core.analytics import signal_aggregator
    before = signal_aggregator.run_tier_a
    T.scene_14()
    assert signal_aggregator.run_tier_a is before


def test_gas_scene_writes_nothing_into_the_tree():
    live = os.path.join(_REPO, "data", "base_gas_history.json")
    stamp = os.stat(live).st_mtime if os.path.exists(live) else None
    T.scene_08()
    assert (os.stat(live).st_mtime if os.path.exists(live) else None) == stamp


# ───────────────────────────── ось D: тест в репозитории ──────────────────────

def test_registry_refs_are_all_present_in_this_tree():
    for n in range(1, T.OWNER_SCENES_DECLARED + 1):
        got = T.test_presence(_REPO, T.SCENE_TESTS[n])
        assert got["kind"] == "present", (n, got)
        assert len(got["refs"]) >= 2


def test_registry_covers_every_declared_scene_with_a_pair_from_this_battery():
    for n, *_ in T.OWNER_SCENES:
        refs = T.SCENE_TESTS[n]
        own = [r for r in refs if r.startswith(T._BATTERY)]
        assert len(own) == 2 and any("_torn_" in r for r in own), (n, refs)


def test_a_stale_ref_is_named(tmp_path):
    (tmp_path / "t.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    got = T.test_presence(str(tmp_path), ["t.py::test_a", "t.py::test_missing"])
    assert got["kind"] == "stale"
    assert [r["kind"] for r in got["refs"]] == ["present", "stale"]
    assert "test_missing" in got["refs"][1]["reason"]


def test_a_method_inside_a_class_counts_as_present(tmp_path):
    (tmp_path / "t.py").write_text("class K:\n    def test_m(self):\n        pass\n", encoding="utf-8")
    assert T.test_presence(str(tmp_path), ["t.py::test_m"])["kind"] == "present"


def test_an_empty_registry_is_absent_not_present():
    assert T.test_presence(_REPO, ())["kind"] == "absent"


def test_an_unreadable_test_file_is_unmeasured_not_stale(tmp_path):
    got = T.test_presence(str(tmp_path), ["nope.py::test_x"])
    assert got["kind"] == UNMEASURED and "не прочитан" in got["refs"][0]["reason"]


def test_an_unparseable_test_file_is_unmeasured(tmp_path):
    (tmp_path / "t.py").write_text("def (:\n", encoding="utf-8")
    got = T.test_presence(str(tmp_path), ["t.py::test_x"])
    assert got["kind"] == UNMEASURED and "не разобран" in got["refs"][0]["reason"]


# ───────────────────────────── находки и артефакт ─────────────────────────────

def _fake_scene(door="present", owner=True, torn=False, missing=()):
    def _s():
        return {"door": T._door(door, ["x"], list(missing), note="нет двери"),
                "owner": {"holds": owner}, "torn": {"holds": torn, "what_changed": "y"}, "reading": "r"}
    return _s


def test_contrary_scene_is_critical_and_named(monkeypatch):
    monkeypatch.setitem(T.SCENES, 7, _fake_scene(owner=False, torn=True))
    doc = T.run(write=False, scenes=[7])
    r = doc["scenes"]["7"]
    assert r["scene_kind"] == "contrary" and r["tear_kind"] == "discriminates"
    codes = {(f["code"], f.get("scene")) for f in doc["findings"]}
    assert ("scene_contrary", 7) in codes and doc["overall"] == "CRITICAL"


def test_indiscriminate_tear_is_critical(monkeypatch):
    monkeypatch.setitem(T.SCENES, 7, _fake_scene(owner=True, torn=True))
    doc = T.run(write=False, scenes=[7])
    assert doc["scenes"]["7"]["tear_kind"] == "indiscriminate"
    assert any(f["code"] == "scene_indiscriminate" and f["severity"] == "CRITICAL" for f in doc["findings"])


def test_absent_door_is_unreachable_and_critical(monkeypatch):
    monkeypatch.setitem(T.SCENES, 6, _fake_scene(door="absent"))
    doc = T.run(write=False, scenes=[6])
    r = doc["scenes"]["6"]
    assert r["scene_kind"] == "unreachable" and r["tear_kind"] == "not_built"
    assert any(f["code"] == "door_absent" and "нет двери" in f["detail"] for f in doc["findings"])


def test_partial_door_is_a_warning_with_the_missing_input_named(monkeypatch):
    monkeypatch.setitem(T.SCENES, 7, _fake_scene(door="partial", missing=["вход Z"]))
    doc = T.run(write=False, scenes=[7])
    f = [f for f in doc["findings"] if f["code"] == "door_partial"]
    assert len(f) == 1 and f[0]["severity"] == "WARN" and "вход Z" in f[0]["detail"]


def test_a_scene_that_raises_is_unmeasured_not_a_zero(monkeypatch):
    def _boom():
        raise RuntimeError("дверь упала")
    monkeypatch.setitem(T.SCENES, 5, _boom)
    doc = T.run(write=False, scenes=[5])
    r = doc["scenes"]["5"]
    assert r["scene_kind"] == UNMEASURED and r["door"]["kind"] == UNMEASURED
    assert any("Test 5" in u and "дверь упала" in u for u in doc["unmeasured"])
    assert doc["tally"]["scene"][UNMEASURED] == 1


def test_stale_registry_is_a_warning(monkeypatch):
    monkeypatch.setitem(T.SCENE_TESTS, 7, ("spa_core/tests/test_testing_scenario_census.py::test_nope",))
    doc = T.run(write=False, scenes=[7])
    assert doc["scenes"]["7"]["tests"]["kind"] == "stale"
    assert any(f["code"] == "test_stale" and "test_nope" in f["detail"] for f in doc["findings"])


def test_empty_registry_is_a_warning(monkeypatch):
    monkeypatch.setitem(T.SCENE_TESTS, 7, ())
    doc = T.run(write=False, scenes=[7])
    assert doc["scenes"]["7"]["tests"]["kind"] == "absent"
    assert any(f["code"] == "test_absent" for f in doc["findings"])


def test_parity_mismatch_is_critical(tmp_path):
    text = _good_card_text().replace("никакого churn.", "немного churn.")
    doc = T.run(card_path=_card(tmp_path, text), write=False, scenes=[7])
    assert any(f["code"] == "parity_mismatch" and f["severity"] == "CRITICAL" for f in doc["findings"])


def test_unreadable_card_is_unmeasured_in_the_report(tmp_path):
    doc = T.run(card_path=str(tmp_path / "none.md"), write=False, scenes=[7])
    assert any("паритет с карточкой НЕ ИЗМЕРЕН" in u for u in doc["unmeasured"])


def test_tally_keys_are_the_declared_vocabularies():
    doc = T.run(write=False, scenes=[7, 13])
    t = doc["tally"]
    assert set(t["door"]) == set(T.DOOR_KINDS) and set(t["scene"]) == set(T.SCENE_KINDS)
    assert set(t["tear"]) == set(T.TEAR_KINDS) and set(t["tests"]) == set(T.TEST_KINDS)
    assert sum(t["scene"].values()) == 2


def test_live_tree_verdict_is_an_anchor():
    """Якорь против молчаливого регресса: что прибор говорит о ЖИВОМ дереве (#1100)."""
    doc = T.run(write=False)
    t = doc["tally"]
    assert doc["parity"]["agrees"] is True and doc["control"]["ok"]
    assert t["door"]["absent"] == 0 and t["door"][UNMEASURED] == 0
    assert t["tear"]["discriminates"] == 15
    assert t["tests"]["present"] == 15
    assert {int(f["scene"]) for f in doc["findings"] if f["code"] == "scene_contrary"} == {1, 2}
    assert doc["overall"] == "CRITICAL"


def test_run_writes_the_artifact_atomically_when_asked(tmp_path):
    (tmp_path / "data").mkdir()
    doc = T.run(root=str(tmp_path), card_path=_LIVE_CARD, write=True, scenes=[7])
    path = tmp_path / T.REPORT_REL
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema"] == "testing_scenario_census/v1" and on_disk["applied"] is False
    assert on_disk["scenes"]["7"]["scene_kind"] == doc["scenes"]["7"]["scene_kind"]
    assert on_disk["scenes"]["7"]["tests"]["kind"] == UNMEASURED   # реестр сверялся с ПУСТЫМ деревом tmp


def test_report_declares_applied_false_and_the_paper_column():
    doc = T.run(write=False, scenes=[7])
    assert doc["applied"] is False and "paper" in doc["declared"]["params_column"]
    assert doc["declared"]["scenes_declared"] == 15 and len(doc["declared"]["scenes"]) == 15


def test_main_rejects_an_unparseable_now(capsys):
    assert T.main(["--now", "вчера", "--no-write"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_now_is_an_input_not_the_clock():
    stamp = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)   # FROZEN-DATE-OK: injected-clock — now= передаётся входом run()
    doc = T.run(write=False, scenes=[7], now=stamp)
    assert doc["generated_at"] == stamp.isoformat()


def test_print_names_every_scene_and_finding(capsys):
    doc = T.run(write=False, scenes=[1, 7])
    T._print(doc)
    out = capsys.readouterr().out
    assert "Test  1" in out and "Test  7" in out and "scene_contrary" in out and "паритет с карточкой: СОВПАЛ" in out


# ───────────────────────────── проба приёмки ──────────────────────────────────

def test_probe_is_registered_with_repo_root_as_input():
    assert PROBE in CA.PROBES
    assert "repo_root" in CA.probe_tree_inputs(PROBE)


def test_probe_rejects_an_argument():
    status, why = CA.PROBES[PROBE]("x")
    assert status == CA.UNMEASURED and "аргумента" in why


def test_probe_is_not_satisfied_on_the_live_tree():
    status, why = CA.run_probe(PROBE, repo_root=_REPO)
    assert status == CA.NOT_SATISFIED, why
    assert "Test 1" in why and "Test 2" in why and "не исполнены 2" in why


def test_probe_is_satisfied_only_when_every_scene_holds_and_discriminates(monkeypatch):
    for n in T.SCENES:
        monkeypatch.setitem(T.SCENES, n, _fake_scene(owner=True, torn=False))
    status, why = CA.run_probe(PROBE, repo_root=_REPO)
    assert status == CA.SATISFIED, why
    assert "все 15 сцен" in why


def test_probe_is_not_satisfied_while_a_scene_does_not_discriminate(monkeypatch):
    for n in T.SCENES:
        monkeypatch.setitem(T.SCENES, n, _fake_scene(owner=True, torn=False))
    monkeypatch.setitem(T.SCENES, 4, _fake_scene(owner=True, torn=True))
    status, why = CA.run_probe(PROBE, repo_root=_REPO)
    assert status == CA.NOT_SATISFIED and "Test 4" in why and "порванная indiscriminate" in why


def test_probe_is_not_satisfied_while_a_door_is_absent(monkeypatch):
    for n in T.SCENES:
        monkeypatch.setitem(T.SCENES, n, _fake_scene(owner=True, torn=False))
    monkeypatch.setitem(T.SCENES, 6, _fake_scene(door="absent"))
    status, why = CA.run_probe(PROBE, repo_root=_REPO)
    assert status == CA.NOT_SATISFIED and "Test 6" in why and "двери нет" in why


def test_probe_is_not_satisfied_while_a_registry_ref_is_stale(monkeypatch):
    for n in T.SCENES:
        monkeypatch.setitem(T.SCENES, n, _fake_scene(owner=True, torn=False))
    monkeypatch.setitem(T.SCENE_TESTS, 9, ("spa_core/tests/test_testing_scenario_census.py::test_nope",))
    status, why = CA.run_probe(PROBE, repo_root=_REPO)
    assert status == CA.NOT_SATISFIED and "Test 9" in why and "тест stale" in why


def test_probe_is_unmeasured_when_the_control_is_broken(monkeypatch):
    monkeypatch.setattr(T, "control", lambda: (False, "X", {}))
    status, why = CA.run_probe(PROBE, repo_root=_REPO)
    assert status == CA.UNMEASURED and "контрольная сцена" in why


def test_probe_is_unmeasured_when_a_scene_raises(monkeypatch):
    def _boom():
        raise RuntimeError("дверь упала")
    monkeypatch.setitem(T.SCENES, 3, _boom)
    status, why = CA.run_probe(PROBE, repo_root=_REPO)
    assert status == CA.UNMEASURED and "'3'" in why


def test_probe_is_unmeasured_on_a_tree_without_the_card(tmp_path):
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path))
    assert status == CA.UNMEASURED and "паритет" in why
