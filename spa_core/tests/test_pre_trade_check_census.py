"""Контроли §27 ТЗ «Portfolio CIO» — ADR-970.

Каждая проверка — контроль ОДНОГО звена прибора
:mod:`spa_core.analytics.pre_trade_check_census`, и у каждой несущей претензии
есть контроль В ОБЕ СТОРОНЫ: зелёный на целом контуре и КРАСНЫЙ на порванном
звене, с названным звеном (`.claude/rules/acceptance.md`, п. 3).

ВРЕМЯ — ВХОД, А НЕ ОКРУЖЕНИЕ. Литеральных дат нет: единственный якорь берётся в
рантайме и передаётся прибору аргументом ``now=`` (ось B — ввоз ADR-487 —
принимает его и считает окно от отметок цепочки, а не от стенных часов).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap

import pytest

from spa_core.analytics import pre_trade_check_census as PC
from spa_core.analytics import decision_type_census as S24
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import pre_trade_recheck_census as S49


# ───────────────────────────── сцены ─────────────────────────────────────────

def _anchor() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _event(eid: str, etype: str, ts: dt.datetime, snap: str,
           prev: str | None = None, data: dict | None = None) -> dict:
    return {"event_id": eid, "correlation_id": f"c-{eid}", "snapshot_id": snap,
            "event_type": etype, "timestamp": ts.isoformat(),
            "data": data or {}, "prev_event_id": prev}


def _chain(anchor: dt.datetime, *, exec_snapshot: str | None = None) -> list[dict]:
    """Живая форма: предложение → вердикт → исполнение на ТОМ ЖЕ снимке."""
    t0 = anchor - dt.timedelta(hours=1)
    snap = "scene:snapshot"
    return [
        _event("p", S49.EVENT_PROPOSAL, t0, snap),
        _event("v", S49.EVENT_VERDICT, t0 + dt.timedelta(seconds=0.2), snap, "p"),
        _event("x", S49.EVENT_EXECUTED, t0 + dt.timedelta(seconds=0.6),
               exec_snapshot or snap, "v", {"trade_id": "T1"}),
    ]


def _data_dir(tmp, rows: list[dict] | None) -> str:
    d = tmp / "data"
    d.mkdir(parents=True, exist_ok=True)
    if rows is not None:
        (d / S49.CHAIN_FILENAME).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(d)


def _card(tmp, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


_GOOD_CARD = """\
    ---
    title: x
    ---
    26. Determinism
    что-то
    27. Pre-trade check
    Между recommendation и execution обязательно выполнить повторную проверку.
    Проверить:
    fresh APY
    fresh gas
    fresh liquidity
    fresh slippage
    withdraw simulation
    deposit simulation
    position impact
    policy
    expected economics
    Если opportunity исчезла:
    CANCEL / DEFER
    а не исполнять устаревшее решение.


    ⸻


    28. Decision expiry
    Каждое investment decision должно иметь TTL.
    """


# ───────────────────── паритет: константа ↔ карточка ─────────────────────────

def test_constants_agree_with_the_real_owner_card():
    """Несущая претензия: 9 проверок / 2 исхода — ПО КАРТОЧКЕ, не по константе."""
    card = os.path.join(PC.REPO_ROOT, PC.CARD_REL)
    if not os.path.isfile(card):
        pytest.fail(f"карточка приказа не найдена: {card} — паритет НЕ ИЗМЕРЕН")
    r = PC.parity(card)
    assert r["parsed"]["measured"], r["parsed"]["reason"]
    assert r["agrees"] is True, r["mismatches"]
    assert len(r["parsed"]["checks"]) == PC.OWNER_CHECKS_DECLARED == 9
    assert r["parsed"]["outcomes"] == ["CANCEL", "DEFER"]
    # Недосчёт заказа ИЗМЕРЕН, а не замечен глазами.
    assert r["order_undercount"] == 9 - PC.ORDER_G958_NAMED == 6


def test_parity_on_a_faithful_scene_card(tmp_path):
    r = PC.parity(_card(tmp_path, _GOOD_CARD))
    assert r["agrees"] is True, r["mismatches"]


def test_parity_names_the_drift_instead_of_hiding_it(tmp_path):
    """Порванное звено: в карточке пропала одна проверка — расхождение НАЗВАНО."""
    r = PC.parity(_card(tmp_path, _GOOD_CARD.replace("fresh slippage\n", "")))
    assert r["agrees"] is False
    assert any("число проверок: карточка 8" in m for m in r["mismatches"]), r["mismatches"]


def test_parity_outcomes_are_split_on_the_slash(tmp_path):
    r = PC.parity(_card(tmp_path, _GOOD_CARD.replace("CANCEL / DEFER", "CANCEL")))
    assert r["agrees"] is False
    assert any("число исходов: карточка 1" in m for m in r["mismatches"])


def test_unreadable_card_is_a_third_outcome_not_a_fallback(tmp_path):
    r = PC.parity(str(tmp_path / "нет-такого.md"))
    assert r["agrees"] is None
    assert "не прочитана" in r["parsed"]["reason"]
    assert r["order_undercount"] is None


def test_missing_second_border_refuses_to_count(tmp_path):
    r = PC.parity(_card(tmp_path, _GOOD_CARD.replace("28. Decision expiry", "28. Другое")))
    assert r["agrees"] is None
    assert "вторая граница" in r["parsed"]["reason"]


def test_missing_anchor_is_named(tmp_path):
    r = PC.parity(_card(tmp_path, _GOOD_CARD.replace("Проверить:", "Проверим:")))
    assert r["agrees"] is None
    assert "Проверить:" in r["parsed"]["reason"]


# ───────────────────────────── ось A: второе событие ─────────────────────────

def test_axis_a_real_execution_is_absent_by_construction_on_the_live_tree():
    """Инвариант #6 МЕРИТСЯ, не утверждается: ни один модуль поверхности не
    ввозит `spa_core.execution`."""
    files, missing = PC.money_path_files(PC.REPO_ROOT)
    assert files, missing
    out = PC.measure_second_event(os.path.join(PC.REPO_ROOT, "data"), PC.REPO_ROOT)
    assert out["real_onchain"]["kind"] == "none", out["real_onchain"]
    assert out["real_onchain"]["files_scanned"] == len(files)


def test_axis_a_reddens_when_a_money_path_module_imports_execution(tmp_path, monkeypatch):
    """Порванное звено: модуль поверхности ввозит пакет исполнения."""
    root = tmp_path / "root"
    (root / "spa_core" / "risk").mkdir(parents=True)
    (root / "spa_core" / "risk" / "policy.py").write_text(
        "from spa_core.execution import safety_checks\n", encoding="utf-8")
    monkeypatch.setattr(PC, "MONEY_PATH_PREFIXES", ("spa_core/risk/",))
    monkeypatch.setattr(PC, "MONEY_PATH_EXTENSION", ())
    out = PC.measure_second_event(_data_dir(tmp_path, None), str(root))
    assert out["real_onchain"]["kind"] == "present"
    assert out["real_onchain"]["importers"] == ["spa_core/risk/policy.py"]


def test_axis_a_unparsed_surface_file_is_unmeasured_not_none(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "spa_core" / "risk").mkdir(parents=True)
    (root / "spa_core" / "risk" / "broken.py").write_text("def (:\n", encoding="utf-8")
    monkeypatch.setattr(PC, "MONEY_PATH_PREFIXES", ("spa_core/risk/",))
    monkeypatch.setattr(PC, "MONEY_PATH_EXTENSION", ())
    out = PC.measure_second_event(_data_dir(tmp_path, None), str(root))
    assert out["real_onchain"]["kind"] == UNMEASURED
    assert "broken.py" in out["real_onchain"]["reason"]


def test_axis_a_paper_execution_present_when_the_chain_has_trade_executed(tmp_path):
    out = PC.measure_second_event(_data_dir(tmp_path, _chain(_anchor())), PC.REPO_ROOT)
    assert out["paper_virtual"]["kind"] == "present"
    assert out["paper_virtual"]["executions"] == 1


def test_axis_a_paper_execution_none_vs_unmeasured_are_distinct(tmp_path):
    no_exec = [_chain(_anchor())[0]]
    out = PC.measure_second_event(_data_dir(tmp_path, no_exec), PC.REPO_ROOT)
    assert out["paper_virtual"]["kind"] == "none"
    out2 = PC.measure_second_event(_data_dir(tmp_path / "b", None), PC.REPO_ROOT)
    assert out2["paper_virtual"]["kind"] == UNMEASURED
    assert out2["paper_virtual"]["reason"]


# ───────────────────────────── поверхность ───────────────────────────────────

def test_surface_extension_claims_are_proven_by_cycle_imports():
    s = PC.measure_surface(PC.REPO_ROOT)
    bad = {k: v for k, v in s["extension"].items() if v["kind"] != "imported_by_cycle"}
    assert not bad, bad
    assert s["missing"] == []


def test_surface_extension_drift_is_named(monkeypatch):
    monkeypatch.setattr(PC, "MONEY_PATH_EXTENSION",
                        (("spa_core/analytics/pre_trade_check_census.py", "самозванец"),))
    s = PC.measure_surface(PC.REPO_ROOT)
    row = s["extension"]["spa_core/analytics/pre_trade_check_census.py"]
    assert row["kind"] == "not_imported_by_cycle"


# ───────────────────────────── ось B: ввоз ADR-487 ───────────────────────────

def test_axis_b_imports_the_verdict_and_keeps_its_window(tmp_path):
    a = _anchor()
    r = PC.import_recheck_verdict(_data_dir(tmp_path, _chain(a)), PC.REPO_ROOT, now=a)
    assert r["measured"] and r["status"] == S49.STATUS_WARNING
    assert r["no_recheck"] == 1 and r["executions_measurable"] == 1
    assert r["window_s_max"] == pytest.approx(0.6, abs=0.01)
    # ИЗМЕНЕНО НАМЕРЕННО (ADR-972, инв. #16): до 10.11 свежесть судить было нечем —
    # у владельца не было ручки. Ответ 27.10 исполнен: ввезённый вердикт судит числом
    # владельца (60 с на бумаге), и окно 0,6 с внутри допуска.
    assert r["freshness_judgeable"] is True
    assert r["freshness_unjudgeable_reason"] is None
    assert "ADR-487" in r["source"]


def test_axis_b_second_observation_flips_the_imported_status(tmp_path):
    a = _anchor()
    r = PC.import_recheck_verdict(
        _data_dir(tmp_path, _chain(a, exec_snapshot="scene:other")), PC.REPO_ROOT, now=a)
    assert r["status"] == S49.STATUS_OK and r["no_recheck"] == 0


def test_axis_b_missing_chain_is_unmeasured_with_the_neighbours_reason(tmp_path):
    r = PC.import_recheck_verdict(_data_dir(tmp_path, None), PC.REPO_ROOT, now=_anchor())
    assert r["measured"] is False
    assert "ADR-487" in r["reason"]


# ───────────────────────────── ось C: наблюдатели ────────────────────────────

def test_axis_c_every_declaration_is_confirmed_by_the_live_tree():
    """Несущая претензия: ни одно объявление OBSERVER_MAP не разошлось с кодом."""
    o = PC.measure_observers(PC.REPO_ROOT)
    assert o["measured"]
    unm = {k: v["reason"] for k, v in o["checks"].items() if v["kind"] == UNMEASURED}
    assert not unm, unm
    kinds = {k: v["kind"] for k, v in o["checks"].items()}
    assert kinds["withdraw simulation"] == "door_without_caller"
    assert kinds["deposit simulation"] == "door_without_caller"
    assert kinds["fresh slippage"] == "tree_constant"
    assert kinds["fresh gas"] == "live_observation"
    assert o["checks"]["fresh gas"]["also"]["kind"] == "tree_constant"
    assert set(kinds) == set(PC.CHECKS_27)


def test_axis_c_declaration_drift_is_unmeasured_not_a_kind(monkeypatch):
    """Порванное звено: названное имя в коде отсутствует — ответ «не измерено»."""
    bad = dict(PC.OBSERVER_MAP)
    bad["policy"] = dict(bad["policy"], evidence={"spa_core/risk/policy.py": ("нет_такого",)})
    monkeypatch.setattr(PC, "OBSERVER_MAP", bad)
    o = PC.measure_observers(PC.REPO_ROOT)
    row = o["checks"]["policy"]
    assert row["kind"] == UNMEASURED
    assert "нет_такого" in row["reason"]


def test_axis_c_definition_counts_as_evidence_but_a_string_does_not(tmp_path):
    """Дверь определений: `def simulate_deposit` — свидетельство; упоминание
    в строке — нет (на этом четыре объявления вышли красными в #1088)."""
    root = tmp_path / "root"
    (root / "spa_core" / "adapters").mkdir(parents=True)
    (root / "spa_core" / "adapters" / "a.py").write_text(
        "def simulate_deposit(x):\n    return x\n", encoding="utf-8")
    (root / "spa_core" / "adapters" / "b.py").write_text(
        "MSG = 'simulate_withdraw: нет'\n", encoding="utf-8")
    ok_a, _ = PC._check_evidence(str(root), {"spa_core/adapters/a.py": ("simulate_deposit",)}, {})
    ok_b, pr = PC._check_evidence(str(root), {"spa_core/adapters/b.py": ("simulate_withdraw",)}, {})
    assert ok_a is True
    # Строка — тоже идентификатор кода по двери §26 (строковые литералы входят),
    # но ИМЯ внутри строки с двоеточием им не является.
    assert ok_b is False and "simulate_withdraw" in pr[0]


def test_axis_c_absence_claim_is_refuted_by_a_real_caller(monkeypatch):
    """Претензия «зовущего нет» опровергается, если слово есть в коде поверхности."""
    bad = dict(PC.OBSERVER_MAP)
    bad["withdraw simulation"] = dict(bad["withdraw simulation"],
                                      absent_from_callers=("RiskPolicy",))
    monkeypatch.setattr(PC, "OBSERVER_MAP", bad)
    o = PC.measure_observers(PC.REPO_ROOT)
    row = o["checks"]["withdraw simulation"]
    assert row["kind"] == UNMEASURED
    assert "ОПРОВЕРГНУТА" in row["reason"]


def test_axis_c_a_comment_does_not_refute_an_absence_claim(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "spa_core" / "paper_trading").mkdir(parents=True)
    (root / "spa_core" / "paper_trading" / "cycle_runner.py").write_text(
        "# simulate_withdraw упомянут только здесь\nx = 1\n", encoding="utf-8")
    monkeypatch.setattr(PC, "CALLER_SURFACE", ("spa_core/paper_trading/cycle_runner.py",))
    hits, unm = PC._callers_mention(str(root), ("simulate_withdraw",), {})
    assert hits == [] and unm == []


def test_axis_c_unreadable_caller_surface_is_a_third_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(PC, "CALLER_SURFACE", ("spa_core/нет.py",))
    hits, unm = PC._callers_mention(str(tmp_path), ("x",), {})
    assert hits is None and unm


def test_axis_c_freshness_capability_follows_the_kind():
    o = PC.measure_observers(PC.REPO_ROOT)
    for check, row in o["checks"].items():
        if row["kind"] == UNMEASURED:
            continue
        assert row["freshness_capable"] == (row["kind"] in PC.FRESHNESS_CAPABLE), check
    assert o["checks"]["fresh slippage"]["freshness_capable"] is False
    assert o["checks"]["fresh APY"]["freshness_capable"] is True


# ───────────────────────────── ось D: часы ───────────────────────────────────

def test_axis_d_cycle_entry_has_now_but_subjects_do_not():
    d = PC.measure_clock_at_both_events(PC.REPO_ROOT)
    assert d["cycle_entry"]["kind"] == "pinnable_named"
    assert "now" in d["cycle_entry"]["params"]
    assert d["subjects"] == {"allocator": "unpinnable_ambient",
                             "tuner": "unpinnable_ambient"}


def test_axis_d_clock_names_are_an_input_not_a_guess(monkeypatch):
    monkeypatch.setattr(PC, "CLOCK_PARAM_NAMES", ("нет_такого",))
    d = PC.measure_clock_at_both_events(PC.REPO_ROOT)
    assert d["cycle_entry"]["kind"] == "unpinnable_ambient"


# ───────────────────────────── ось E: словарь ────────────────────────────────

def test_axis_e_cancel_is_outside_section_24_and_defer_inside():
    e = PC.measure_outcome_vocabulary(PC.REPO_ROOT)
    assert e["outcomes"]["CANCEL"]["in_section_24_vocabulary"] is False
    assert e["outcomes"]["DEFER"]["in_section_24_vocabulary"] is True
    assert "DEFER" in S24.OWNER_DECISION_TYPES and "CANCEL" not in S24.OWNER_DECISION_TYPES
    assert e["outcomes"]["DEFER"]["presence_source"].startswith("§24")
    assert e["outcomes"]["CANCEL"]["presence_source"].startswith("AST")


def test_axis_e_cancel_presence_flips_when_a_door_emits_it(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "spa_core" / "paper_trading").mkdir(parents=True)
    (root / "spa_core" / "paper_trading" / "cycle_runner.py").write_text(
        "VERDICT = 'CANCEL'\n", encoding="utf-8")
    monkeypatch.setattr(PC, "CALLER_SURFACE", ("spa_core/paper_trading/cycle_runner.py",))
    monkeypatch.setattr(PC._s24, "census", lambda _root: {"types": []})
    e = PC.measure_outcome_vocabulary(str(root))
    assert e["outcomes"]["CANCEL"]["presence_on_doors"] == "emitted_only"


def test_axis_e_fallen_section_24_census_is_named_not_swallowed(monkeypatch):
    def boom(_root):
        raise RuntimeError("сцена не построена")
    monkeypatch.setattr(PC._s24, "census", boom)
    e = PC.measure_outcome_vocabulary(PC.REPO_ROOT)
    assert "перепись §24 упала" in e["outcomes"]["DEFER"]["presence_reason"]
    assert e["outcomes"]["DEFER"]["presence_on_doors"] == UNMEASURED


# ───────────────────────────── отчёт ─────────────────────────────────────────

def _full_run(tmp_path, **kw):
    a = _anchor()
    data = _data_dir(tmp_path, _chain(a))
    card = _card(tmp_path, _GOOD_CARD)
    return PC.run(root=PC.REPO_ROOT, data_dir=data, card_path=card,
                  write=False, now=a, **kw)


def test_report_is_advisory_and_critical_on_the_live_tree(tmp_path):
    doc = _full_run(tmp_path)
    assert doc["applied"] is False
    assert doc["overall"] == "CRITICAL", doc["findings"]
    codes = [f["code"] for f in doc["findings"]]
    assert codes.count("check_never_observed_on_money_path") == 2
    assert "no_second_observation_between_events" in codes
    assert "second_event_is_paper_within_one_process" in codes
    assert "outcome_absent_from_section_24_vocabulary" in codes
    assert "order_undercounted_checks" in codes
    assert "fresh_needs_now_as_input_and_it_is_not" in codes
    assert doc["counts"]["info"] >= 1
    # INFO не поднимает вердикт: сними критические и предупреждения — будет не CRITICAL.
    assert all(f["severity"] in ("CRITICAL", "WARN", "INFO") for f in doc["findings"])


def test_report_writes_the_artifact_with_the_canonical_argument_order(tmp_path):
    """Контроль дефекта, найденного у соседа §26: (data, path), а не наоборот."""
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    a = _anchor()
    data = _data_dir(root, _chain(a))
    card = _card(root, _GOOD_CARD)
    # Поверхность кода берём у живого дерева через monkeypatch REPO_ROOT? Нет —
    # прибор читает код по `root`, поэтому сцена даёт UNCHECKED; важна ЗАПИСЬ.
    doc = PC.run(root=str(root), data_dir=data, card_path=card, write=True, now=a)
    path = root / PC.REPORT_REL
    assert path.is_file(), "артефакт не записан"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema"] == doc["schema"] == "pre_trade_check_census/v1"


def test_overall_is_unchecked_when_only_unmeasured_remains(tmp_path, monkeypatch):
    """Третий исход не является находкой и не красит зелёным."""
    monkeypatch.setattr(PC, "_findings", lambda *a, **k: ([], ["ось X: не измерено"]))
    doc = _full_run(tmp_path)
    assert doc["overall"] == "UNCHECKED"
    assert doc["counts"]["unmeasured"] == 1


def test_main_exit_codes_follow_the_verdict(tmp_path, monkeypatch, capsys):
    a = _anchor()
    data = _data_dir(tmp_path, _chain(a))
    card = _card(tmp_path, _GOOD_CARD)
    rc = PC.main(["--data-dir", data, "--card", card, "--no-write"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "§27" in out and "[CRITICAL]" in out
    monkeypatch.setattr(PC, "_findings", lambda *a, **k: ([], ["x"]))
    assert PC.main(["--data-dir", data, "--card", card, "--no-write"]) == 2


def test_order_undercount_is_printed_as_info_not_as_a_defect(tmp_path):
    doc = _full_run(tmp_path)
    row = next(f for f in doc["findings"] if f["code"] == "order_undercounted_checks")
    assert row["severity"] == "INFO" and "3" in row["message"] and "9" in row["message"]


def test_axis_e_exact_token_does_not_match_a_longer_word(tmp_path, monkeypatch):
    """Разводящая сцена для `exact=True`: слово `CANCELLED` в коде поверхности
    НЕ есть выданный токен `CANCEL` (по основе оно бы совпало — на этом и
    покраснел первый прогон батареи с `DEFER`/`DEFERRED`)."""
    root = tmp_path / "root"
    (root / "spa_core" / "paper_trading").mkdir(parents=True)
    (root / "spa_core" / "paper_trading" / "cycle_runner.py").write_text(
        "STATE = 'CANCELLED'\n", encoding="utf-8")
    monkeypatch.setattr(PC, "CALLER_SURFACE", ("spa_core/paper_trading/cycle_runner.py",))
    exact, _ = PC._callers_mention(str(root), ("CANCEL",), {}, exact=True)
    stem, _ = PC._callers_mention(str(root), ("CANCEL",), {}, exact=False)
    assert exact == [] and stem == ["spa_core/paper_trading/cycle_runner.py:CANCEL"]
    monkeypatch.setattr(PC._s24, "census", lambda _root: {"types": []})
    e = PC.measure_outcome_vocabulary(str(root))
    assert e["outcomes"]["CANCEL"]["presence_on_doors"] == "absent_from_every_door"
