"""Приёмка переписи связывания политики (ADR-481, критерий §49 `Risk`).

Каждый тест — либо воспроизведение НАСТОЯЩЕГО исхода из журнала ходов, либо
контроль одного звена в ОБРАТНУЮ сторону: звено названо в имени теста. Порядок
тот же, что у `test_book_oscillation_census.py` (ADR-480).

FROZEN-DATE-OK: дата здесь — САМ ПРЕДМЕТ замера, а не отметка свежести. Прибор
сравнивает день исполненного состояния книги с днём рождения порога; ни одна
дата в этом файле не сравнивается с настенными часами, а там, где часы есть
вовсе (`generated_at` артефакта), они ИНЪЕКТИРУЮТСЯ параметром ``now=``.
"""
# FROZEN-DATE-OK: дата здесь — САМ ПРЕДМЕТ замера (день исполненного состояния
# книги против дня рождения порога), а не отметка свежести; ни одна дата в этом
# файле не сравнивается с настенными часами, а часы там, где они есть вовсе,
# инъектируются параметром `now=` (см. NOW ниже и `run_census(..., now=)`).
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import policy_binding_census as pbc

NOW = datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc)

#: Пороги-фикстура. Числа НЕ взяты из `RiskConfig` намеренно: тест проверяет
#: арифметику прибора, а не значения политики, и совпадение с боевыми порогами
#: сделало бы тест зелёным при подстановке своих чисел в прибор.
FAKE = {
    "max_concentration_t1": 0.40,
    "max_concentration_t2": 0.20,
    "max_total_t2_allocation": 0.50,
    "max_total_t3_allocation": 0.15,
    "min_cash_pct": 0.05,
    "max_protocols": 8,
}


def _sources(**named) -> dict:
    """Копии ярлыка в форме, которую отдаёт :func:`read_label_sources`."""
    return {name: {"labels": labels} for name, labels in named.items()}


# ─── пороги: читаются из политики, не подставляются ──────────────────────────


def test_thresholds_come_from_risk_config_not_from_this_module():
    from spa_core.risk.policy import RiskConfig

    got = pbc.load_thresholds()
    cfg = RiskConfig()
    for field in pbc.THRESHOLD_FIELDS:
        assert got[field] == pytest.approx(float(getattr(cfg, field)))


def test_missing_threshold_field_refuses_instead_of_substituting():
    class Half:
        max_concentration_t1 = 0.40
        max_concentration_t2 = 0.20
        max_total_t2_allocation = 0.50
        max_total_t3_allocation = 0.15
        min_cash_pct = 0.05
        # max_protocols отсутствует намеренно

    with pytest.raises(pbc.NotMeasured) as err:
        pbc.load_thresholds(Half())
    assert "max_protocols" in str(err.value)


def test_non_numeric_threshold_is_absence_not_zero():
    class Junk:
        max_concentration_t1 = 0.40
        max_concentration_t2 = 0.20
        max_total_t2_allocation = 0.50
        max_total_t3_allocation = 0.15
        min_cash_pct = True          # «да» числом не является (инв. #17)
        max_protocols = 8

    with pytest.raises(pbc.NotMeasured) as err:
        pbc.load_thresholds(Junk())
    assert "min_cash_pct" in str(err.value)


def test_module_carries_no_copy_of_the_threshold_numbers():
    """§22 приказа: «Не hardcode». Четвёртой копии порогов в приборе быть не может.

    Контроль на СВОЙ файл: если кто-то впишет сюда 0.20/0.40/0.50, прибор
    перестанет отвечать на вопрос владельца и начнёт отвечать на свой.
    """
    source = Path(pbc.__file__).read_text(encoding="utf-8")
    body = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    for literal in ("0.40", "0.20", "0.50", "0.15", "0.05"):
        assert literal not in body, f"копия порога {literal} в приборе"


# ─── история: срок порога измеряется, а поверхностный клон — третий исход ────


def _repo(path: Path, *, branch: str = "main") -> None:
    """Одноразовый репозиторий. Имя ветки — ВХОД сцены (`git init -b`), не хоста."""
    subprocess.run(["git", "init", "-b", branch, "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)


def _commit(path: Path, rel: str, text: str, when: str) -> None:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", rel], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", rel,
                    "--date", when],
                   check=True, env={"GIT_COMMITTER_DATE": when, "PATH": "/usr/bin:/bin",
                                    "HOME": str(path)})


def test_threshold_birth_is_the_day_the_field_name_first_appeared(tmp_path):
    repo = tmp_path / "full"
    _repo(repo)
    _commit(repo, "spa_core/risk/policy.py",
            "max_concentration_t1 = 0.40\n", "2026-06-14T10:00:00+0000")
    _commit(repo, "spa_core/risk/policy.py",
            "max_concentration_t1 = 0.40\nmax_protocols = 8\n",
            "2026-06-28T10:00:00+0000")

    births, reason = pbc.threshold_birth(
        repo, ("max_concentration_t1", "max_protocols"))
    assert reason is None
    assert births["max_concentration_t1"] == "2026-06-14"
    assert births["max_protocols"] == "2026-06-28"


def test_threshold_birth_of_a_name_never_present_is_absent_not_early(tmp_path):
    repo = tmp_path / "full"
    _repo(repo)
    _commit(repo, "spa_core/risk/policy.py", "max_protocols = 8\n",
            "2026-06-28T10:00:00+0000")

    births, reason = pbc.threshold_birth(repo, ("min_cash_pct",))
    assert reason is None
    assert births["min_cash_pct"] is None, (
        "имя, которого в истории нет, обязано быть НЕ ИЗМЕРЕНО, а не «было всегда»")


def test_shallow_clone_gives_the_third_outcome_not_the_graft_date(tmp_path):
    """Тот самый fail-OPEN, который прибор нашёл у себя на проде.

    Поверхностный клон на `git log -S…` отвечает ДАТОЙ — датой границы обрезки.
    Первый прогон поверил ей и объявил все шесть порогов рождёнными 2026-09-21.
    """
    origin = tmp_path / "origin"
    _repo(origin)
    _commit(origin, "spa_core/risk/policy.py", "max_protocols = 8\n",
            "2026-06-28T10:00:00+0000")
    _commit(origin, "spa_core/risk/policy.py", "max_protocols = 8\n# later\n",
            "2026-09-21T10:00:00+0000")
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-local",
                    f"file://{origin}", str(clone)], check=True)

    full_ok, _ = pbc.history_available(origin)
    shallow_ok, reason = pbc.history_available(clone)
    assert full_ok is True
    assert shallow_ok is False
    assert "ПОВЕРХНОСТНЫЙ" in (reason or "")

    births, birth_reason = pbc.threshold_birth(clone, ("max_protocols",))
    assert births["max_protocols"] is None
    assert "ПОВЕРХНОСТНЫЙ" in (birth_reason or "")


def test_history_absent_entirely_is_named_not_silently_full(tmp_path):
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    ok, reason = pbc.history_available(not_a_repo)
    assert ok is False and reason


# ─── переигрывание одного состояния ─────────────────────────────────────────


def test_t2_position_over_its_cap_is_named_with_both_numbers():
    out = pbc.replay_state({"morpho_steakhouse": 40000.0, "pendle": 20000.0,
                            "compound_v3": 35000.0},
                           100000.0,
                           {"morpho_steakhouse": "T2", "pendle": "T2",
                            "compound_v3": "T1"}, FAKE)
    texts = [v["text"] for v in out["violations"]]
    assert any("morpho_steakhouse[T2] 40.00% > 20%" in t for t in texts)
    assert any("t2_total 60.00% > 50%" in t for t in texts)


def test_t1_position_exactly_at_its_cap_is_not_a_violation():
    out = pbc.replay_state({"compound_v3": 40000.0}, 100000.0,
                           {"compound_v3": "T1"}, FAKE)
    assert [v["text"] for v in out["violations"]] == []


def test_same_position_flips_verdict_when_only_the_label_changes():
    """Ядро находки: 40 % — потолок T1 и двукратное превышение T2."""
    positions, capital = {"morpho_steakhouse": 40000.0}, 100000.0
    as_t1 = pbc.replay_state(positions, capital, {"morpho_steakhouse": "T1"}, FAKE)
    as_t2 = pbc.replay_state(positions, capital, {"morpho_steakhouse": "T2"}, FAKE)
    assert as_t1["violations"] == []
    assert len(as_t2["violations"]) >= 1


def test_unnamed_tier_is_unpriced_not_silently_clean():
    """Контроль на fail-OPEN, который прибор имел в первом прогоне.

    Ключ без тира не получал потолка и МОЛЧА выпадал из проверки: состояние с
    40 % книги в одном протоколе печаталось как `violations: []`.
    """
    out = pbc.replay_state({"mystery": 40000.0}, 100000.0, {"mystery": None}, FAKE)
    assert out["unpriced_keys"] == ["mystery"]
    assert out["unpriced_usd"] == 40000.0
    assert out["violations"] == []  # именно поэтому вызывающий обязан смотреть на unpriced


def test_t3_has_no_per_protocol_cap_and_that_is_not_unmeasured():
    """Тир НАЗВАН, персонального потолка у него в политике нет — разные вещи."""
    out = pbc.replay_state({"susde": 10000.0}, 100000.0, {"susde": "T3"}, FAKE)
    assert out["unpriced_keys"] == []
    assert out["no_per_protocol_cap"] == {"T3": ["susde"]}


def test_t3_total_cap_still_binds_a_named_t3():
    out = pbc.replay_state({"susde": 20000.0}, 100000.0, {"susde": "T3"}, FAKE)
    assert any("t3_total 20.00% > 15%" in v["text"] for v in out["violations"])


def test_cash_below_the_floor_is_named():
    out = pbc.replay_state({"compound_v3": 39000.0, "aave_v3": 38000.0,
                            "spark_susds": 21000.0},
                           100000.0,
                           {"compound_v3": "T1", "aave_v3": "T1",
                            "spark_susds": "T1"}, FAKE)
    assert any("cash 2.00% < 5%" in v["text"] for v in out["violations"])


def test_protocol_count_over_the_diversification_floor_is_named():
    positions = {f"p{i}": 1000.0 for i in range(9)}
    out = pbc.replay_state(positions, 100000.0,
                           {k: "T1" for k in positions}, FAKE)
    assert any("protocols 9 > 8" in v["text"] for v in out["violations"])


def test_every_violation_carries_the_field_name_history_will_be_asked_about():
    out = pbc.replay_state({"x": 30000.0}, 100000.0, {"x": "T2"}, FAKE)
    assert out["violations"] and all(
        v["field"] in pbc.THRESHOLD_FIELDS for v in out["violations"])


# ─── связывание ярлыка ──────────────────────────────────────────────────────


def test_all_copies_agreeing_determines_the_tier():
    got = pbc.bind_label("maple", _sources(
        orchestrator_snapshot={"maple": "T2"},
        registry_file_live={"maple": "T2"}))
    assert got["state"] == "determined" and got["tier"] == "T2"


def test_copies_disagreeing_leaves_the_tier_unchosen():
    got = pbc.bind_label("morpho_steakhouse", _sources(
        orchestrator_snapshot={"morpho_steakhouse": "T2"},
        adapter_metadata_code={"morpho_steakhouse": "T1"}))
    assert got["state"] == "disagreement"
    assert got["tier"] is None, "прибор не вправе выбрать копию за политику"
    assert got["candidates"] == ["T1", "T2"]


def test_a_copy_that_does_not_know_the_key_does_not_vote():
    got = pbc.bind_label("maple", _sources(
        orchestrator_snapshot={"maple": "T2"},
        adapter_metadata_code={"aave_v3": "T1"}))
    assert got["state"] == "determined"
    assert "adapter_metadata_code" not in got["votes"]


def test_a_copy_holding_the_key_without_a_tier_does_not_vote_either():
    got = pbc.bind_label("maple", _sources(
        orchestrator_snapshot={"maple": "T2"},
        registry_file_live={"maple": None}))
    assert got["state"] == "determined" and got["votes"] == {
        "orchestrator_snapshot": "T2"}


def test_no_copy_knowing_the_key_is_unknown_not_a_default_tier():
    got = pbc.bind_label("ghost", _sources(orchestrator_snapshot={"maple": "T2"}))
    assert got["state"] == "unknown" and got["tier"] is None


def test_disagreement_reports_whether_the_gate_copies_themselves_agree():
    both_gate = pbc.bind_label("k", _sources(
        orchestrator_snapshot={"k": "T1"},
        registry_file_live={"k": "T2"}))
    assert both_gate["gate_determined"] is False

    outside_only = pbc.bind_label("k", _sources(
        orchestrator_snapshot={"k": "T2"},
        registry_file_live={"k": "T2"},
        adapter_metadata_code={"k": "T1"}))
    assert outside_only["gate_determined"] is True


# ─── зависимость вердикта от копии ──────────────────────────────────────────


def test_verdict_depending_on_the_copy_is_flagged():
    positions = {"morpho_steakhouse": 40000.0}
    got = pbc.replay_by_label_source(
        positions, 100000.0,
        _sources(orchestrator_snapshot={"morpho_steakhouse": "T2"},
                 adapter_metadata_code={"morpho_steakhouse": "T1"}),
        {"morpho_steakhouse": None}, FAKE)
    assert got["label_dependent"] is True
    assert got["per_source"]["adapter_metadata_code"] == []
    assert got["per_source"]["orchestrator_snapshot"]


def test_disagreement_that_changes_nothing_is_not_label_dependent():
    """5 % книги проходит и как T1, и как T2 — спор копий вердикт не меняет."""
    got = pbc.replay_by_label_source(
        {"morpho_steakhouse": 5000.0}, 100000.0,
        _sources(orchestrator_snapshot={"morpho_steakhouse": "T2"},
                 adapter_metadata_code={"morpho_steakhouse": "T1"}),
        {"morpho_steakhouse": None}, FAKE)
    assert got["label_dependent"] is False


def test_a_copy_ignorant_of_a_held_key_answers_unmeasured_not_clean():
    got = pbc.replay_by_label_source(
        {"morpho_steakhouse": 40000.0}, 100000.0,
        _sources(orchestrator_snapshot={"morpho_steakhouse": "T2"},
                 adapter_metadata_code={"aave_v3": "T1"}),
        {"morpho_steakhouse": None}, FAKE)
    assert got["per_source"]["adapter_metadata_code"][0].startswith("НЕ ИЗМЕРЕНО")


def test_gate_verdict_is_reported_separately_from_the_five_copy_dispute():
    got = pbc.replay_by_label_source(
        {"morpho_steakhouse": 40000.0}, 100000.0,
        _sources(orchestrator_snapshot={"morpho_steakhouse": "T2"},
                 registry_file_live={"morpho_steakhouse": "T2"},
                 adapter_metadata_code={"morpho_steakhouse": "T1"}),
        {"morpho_steakhouse": None}, FAKE)
    assert got["label_dependent"] is True
    assert got["gate_agrees"] is True
    assert got["gate_violations"], "деньги связывает то, что прочёл гейт"


# ─── копии: нечитаемая копия не есть согласная ───────────────────────────────


def _tree(tmp_path: Path, *, registry: object, snapshot: object) -> tuple[Path, Path]:
    root = tmp_path / "tree"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "adapter_registry.json").write_text(
        registry if isinstance(registry, str) else json.dumps(registry), encoding="utf-8")
    (data / "adapter_orchestrator_status.json").write_text(
        snapshot if isinstance(snapshot, str) else json.dumps(snapshot), encoding="utf-8")
    return root, data


def test_unreadable_copy_is_named_not_treated_as_empty(tmp_path):
    root, data = _tree(tmp_path, registry="{ не json",
                       snapshot={"adapters": [{"protocol": "maple", "tier": "T2"}]})
    got = pbc.read_label_sources(root, data)
    assert "unreadable" in got["registry_file_live"]
    assert "labels" in got["orchestrator_snapshot"]


def test_registry_without_adapters_map_is_unreadable_not_silently_agreeing(tmp_path):
    root, data = _tree(tmp_path, registry={"version": "1.0"},
                       snapshot={"adapters": []})
    got = pbc.read_label_sources(root, data)
    assert "unreadable" in got["registry_file_live"]


def test_adapter_registry_copy_reads_the_tier_from_the_tuple_not_a_class_attr():
    """Форму копии надо ЗНАТЬ: `getattr(cls, "TIER")` давал None у всех 36.

    Нечитаемая копия, выданная за согласную, — тише красного и потому опаснее.
    """
    from spa_core.adapters import ADAPTER_REGISTRY

    labels = pbc._labels_from_adapter_registry()
    assert labels, "копия ADAPTER_REGISTRY обязана быть прочитана"
    silent = sorted(k for k, v in labels.items() if v is None)
    assert not silent, (
        "копия, МОЛЧА не назвавшая тир, согласна со всеми по этим ключам: "
        + ", ".join(silent))
    assert len(labels) == len({e[0] for e in ADAPTER_REGISTRY
                               if isinstance(e, (list, tuple)) and e}), (
        "копия обязана быть прочитана ЦЕЛИКОМ: «назвала пару и смолчала про "
        "остальных» — тот же fail-OPEN, только частичный")


# ─── перепись целиком ───────────────────────────────────────────────────────


def _journal(tmp_path: Path, moves: list, *, registry: dict, snapshot: dict,
             births: dict | None = None) -> tuple[Path, Path]:
    root = tmp_path / "census"
    data = root / "data"
    data.mkdir(parents=True)
    (data / "trades.json").write_text(json.dumps(moves), encoding="utf-8")
    (data / "adapter_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    (data / "adapter_orchestrator_status.json").write_text(
        json.dumps(snapshot), encoding="utf-8")
    return root, data


def _seal_code_copies(monkeypatch, labels: dict) -> None:
    """Запечатать КОДОВЫЕ копии ярлыка теми же значениями, что у сцены.

    Без этого сцена течёт в боевой реестр: имя вроде `pendle` живёт в настоящих
    `ADAPTER_REGISTRY`/`ADAPTER_METADATA`, и сцена, назвавшая его иначе, честно
    получала «копии спорят». Спор — предмет ОТДЕЛЬНЫХ тестов ниже, и они рвут
    ровно одну копию явно.
    """
    monkeypatch.setattr(pbc, "_labels_from_adapter_registry", lambda: dict(labels))
    monkeypatch.setattr(pbc, "_labels_from_adapter_metadata", lambda: dict(labels))
    monkeypatch.setattr(pbc, "_git_show",
                        lambda *a, **k: json.dumps(
                            {"adapters": {k2: {"tier": v} for k2, v in labels.items()}}))


def _fixture(tmp_path, positions, *, day="2026-08-27", tier_live="T2",
             capital=100000.0, trade_id="T016", monkeypatch=None):
    registry = {"adapters": {k: {"tier": tier_live} for k in positions}}
    snapshot = {"adapters": [{"protocol": k, "tier": tier_live} for k in positions]}
    moves = [{"trade_id": trade_id, "ts": f"{day}T10:00:00+00:00",
              "capital": capital, "to_allocation": dict(positions)}]
    if monkeypatch is not None:
        _seal_code_copies(monkeypatch, {k: tier_live for k in positions})
    return _journal(tmp_path, moves, registry=registry, snapshot=snapshot)


def _run(root: Path, data: Path, *, births: dict | None = None,
         monkeypatch=None) -> dict:
    if births is not None:
        assert monkeypatch is not None
        monkeypatch.setattr(pbc, "threshold_birth",
                            lambda *a, **k: (births, None))
    return pbc.run_census(root, data, now=NOW)


ALL_OLD = {f: "2026-06-01" for f in pbc.THRESHOLD_FIELDS}


def test_census_calls_a_real_breach_a_violation(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"morpho_steakhouse": 40000.0,
                                     "pendle": 20000.0, "maple": 20000.0,
                                     "fluid_usdc": 15000.0}, monkeypatch=monkeypatch)
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    state = report["states"][0]
    assert state["outcome"] == "violation"
    assert any("morpho_steakhouse[T2] 40.00% > 20%" in v for v in state["violations"])


def test_census_refuses_to_call_a_younger_rule_a_bypass(tmp_path, monkeypatch):
    # 24 × $3 900 = $93 600: кэш 6,4 % НАД полом, чтобы единственным нарушенным
    # порогом остался `max_protocols` — иначе тест мерил бы не то звено.
    positions = {f"p{i}": 3900.0 for i in range(24)}
    root, data = _fixture(tmp_path, positions, day="2026-06-20", tier_live="T1",
                          trade_id="T003", monkeypatch=monkeypatch)
    births = dict(ALL_OLD, max_protocols="2026-06-28")
    report = _run(root, data, births=births, monkeypatch=monkeypatch)
    state = report["states"][0]
    assert state["outcome"] == "rule_postdates_state"
    assert state["thresholds_not_yet_declared"] == ["max_protocols"]


def test_census_will_not_call_a_breach_clean_when_the_rule_age_is_unmeasured(
        tmp_path, monkeypatch):
    positions = {f"p{i}": 3900.0 for i in range(24)}
    root, data = _fixture(tmp_path, positions, day="2026-06-20", tier_live="T1",
                          trade_id="T003", monkeypatch=monkeypatch)
    monkeypatch.setattr(pbc, "threshold_birth",
                        lambda *a, **k: ({f: None for f in pbc.THRESHOLD_FIELDS},
                                         "клон поверхностный"))
    report = pbc.run_census(root, data, now=NOW)
    state = report["states"][0]
    assert state["outcome"] == "violation_rule_birth_unmeasured"
    assert "клон поверхностный" in state["reason"]


def test_census_marks_a_state_undetermined_when_the_copies_change_the_verdict(
        tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"morpho_steakhouse": 40000.0,
                                     "compound_v3": 50000.0})
    # третья копия зовёт тот же протокол T1 — потолок 40 %, нарушения нет
    monkeypatch.setattr(pbc, "_labels_from_adapter_metadata",
                        lambda: {"morpho_steakhouse": "T1", "compound_v3": "T1"})
    monkeypatch.setattr(pbc, "_labels_from_adapter_registry",
                        lambda: {"morpho_steakhouse": "T2", "compound_v3": "T1"})
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    state = report["states"][0]
    assert state["outcome"] == "undetermined"
    assert state["violations"] is None, (
        "нарушения — ЗАМЕР; при неназванном тире его нет, и пустой список тут "
        "читался бы как «посмотрели и чисто» (инв. #17)")
    assert state["verdict_by_label_source"]


def test_census_reports_the_gate_verdict_even_while_the_copies_argue(
        tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"morpho_steakhouse": 40000.0,
                                     "compound_v3": 50000.0})
    monkeypatch.setattr(pbc, "_labels_from_adapter_metadata",
                        lambda: {"morpho_steakhouse": "T1", "compound_v3": "T1"})
    monkeypatch.setattr(pbc, "_labels_from_adapter_registry",
                        lambda: {"morpho_steakhouse": "T2", "compound_v3": "T1"})
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    assert report["gate_binding"]["violating_count"] == 1
    assert report["gate_binding"]["violating_states"][0]["trade_id"] == "T016"


def test_gate_count_does_not_include_a_rule_younger_than_the_state(
        tmp_path, monkeypatch):
    positions = {f"p{i}": 3900.0 for i in range(24)}
    root, data = _fixture(tmp_path, positions, day="2026-06-20", tier_live="T1",
                          trade_id="T003", monkeypatch=monkeypatch)
    births = dict(ALL_OLD, max_protocols="2026-06-28")
    report = _run(root, data, births=births, monkeypatch=monkeypatch)
    assert report["gate_binding"]["violating_count"] == 0
    assert report["gate_binding"]["rule_postdates_count"] == 1


def test_census_calls_a_compliant_book_clean(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"maple": 20000.0, "pendle": 20000.0},
                          tier_live="T2", monkeypatch=monkeypatch)
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    assert report["states"][0]["outcome"] == "clean"
    assert report["status"] == pbc.STATUS_OK


def test_status_is_critical_when_the_book_violates_TODAY(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"morpho_steakhouse": 40000.0,
                                     "maple": 20000.0, "pendle": 20000.0,
                                     "fluid_usdc": 15000.0}, monkeypatch=monkeypatch)
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    assert report["status"] == pbc.STATUS_CRITICAL


def test_status_is_only_warning_when_the_breach_is_history(tmp_path, monkeypatch):
    registry = {"adapters": {k: {"tier": "T2"} for k in
                             ("morpho_steakhouse", "maple", "pendle", "fluid_usdc")}}
    snapshot = {"adapters": [{"protocol": k, "tier": "T2"} for k in registry["adapters"]]}
    moves = [
        {"trade_id": "T016", "ts": "2026-08-27T10:00:00+00:00", "capital": 100000.0,
         "to_allocation": {"morpho_steakhouse": 40000.0, "maple": 20000.0,
                           "pendle": 20000.0, "fluid_usdc": 15000.0}},
        {"trade_id": "T034", "ts": "2026-09-11T10:00:00+00:00", "capital": 100000.0,
         "to_allocation": {"maple": 20000.0, "pendle": 20000.0}},
    ]
    root, data = _journal(tmp_path, moves, registry=registry, snapshot=snapshot)
    _seal_code_copies(monkeypatch, {k: "T2" for k in registry["adapters"]})
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    assert report["counts"]["violation"] == 1
    assert report["states"][-1]["outcome"] == "clean"
    assert report["status"] == pbc.STATUS_WARNING, (
        "сторож, красный от всей истории, красен навсегда и учит себя игнорировать")


def test_empty_state_is_unmeasured_not_clean(tmp_path, monkeypatch):
    registry = {"adapters": {"maple": {"tier": "T2"}}}
    snapshot = {"adapters": [{"protocol": "maple", "tier": "T2"}]}
    moves = [{"trade_id": "T004", "ts": "2026-06-20T10:00:00+00:00",
              "capital": 100000.0, "to_allocation": {}}]
    root, data = _journal(tmp_path, moves, registry=registry, snapshot=snapshot)
    _seal_code_copies(monkeypatch, {"maple": "T2"})
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    assert report["states"][0]["outcome"] == "unmeasured"


def test_state_without_capital_is_unmeasured_not_judged_on_a_guess(
        tmp_path, monkeypatch):
    registry = {"adapters": {"maple": {"tier": "T2"}}}
    snapshot = {"adapters": [{"protocol": "maple", "tier": "T2"}]}
    moves = [{"trade_id": "T001", "ts": "2026-06-18T10:00:00+00:00",
              "to_allocation": {"maple": 40000.0}}]
    root, data = _journal(tmp_path, moves, registry=registry, snapshot=snapshot)
    _seal_code_copies(monkeypatch, {"maple": "T2"})
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    assert report["states"][0]["outcome"] == "unmeasured"
    assert "капитала" in report["states"][0]["reason"]


def test_empty_journal_refuses_rather_than_reporting_a_clean_book(tmp_path):
    registry = {"adapters": {"maple": {"tier": "T2"}}}
    snapshot = {"adapters": []}
    root, data = _journal(tmp_path, [], registry=registry, snapshot=snapshot)
    with pytest.raises(pbc.NotMeasured):
        pbc.run_census(root, data, now=NOW)


def test_all_label_copies_unreadable_refuses(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"maple": 20000.0})
    (data / "adapter_registry.json").write_text("{ broken", encoding="utf-8")
    (data / "adapter_orchestrator_status.json").write_text("{ broken", encoding="utf-8")
    for name in ("_labels_from_adapter_registry", "_labels_from_adapter_metadata"):
        monkeypatch.setattr(pbc, name,
                            lambda: (_ for _ in ()).throw(pbc.NotMeasured("нет")))
    monkeypatch.setattr(pbc, "_git_show",
                        lambda *a, **k: (_ for _ in ()).throw(pbc.NotMeasured("нет")))
    with pytest.raises(pbc.NotMeasured) as err:
        pbc.run_census(root, data, now=NOW)
    assert "ни одна копия" in str(err.value)


# ─── артефакт и коды возврата: читать ДИСК, а не возвращённое значение ───────


def test_run_writes_the_artifact_to_disk(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"maple": 20000.0, "pendle": 20000.0},
                          monkeypatch=monkeypatch)
    monkeypatch.setattr(pbc, "threshold_birth", lambda *a, **k: (ALL_OLD, None))
    result = pbc.run(root=str(root), now=NOW, data_dir=str(data))
    path = data / pbc.ARTIFACT_NAME
    assert result["measured"] is True
    assert path.is_file(), "measured=True при отсутствующем артефакте — ADR-480"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["status"] == result["doc"]["status"]
    assert on_disk["generated_at"] == NOW.isoformat()


def test_refusal_also_lands_on_disk_so_silence_is_not_success(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"maple": 20000.0})
    (data / "trades.json").write_text("[]", encoding="utf-8")
    result = pbc.run(root=str(root), now=NOW, data_dir=str(data))
    assert result["measured"] is False
    on_disk = json.loads((data / pbc.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert on_disk["status"] == pbc.STATUS_UNMEASURED and on_disk["reason"]


def test_missing_data_dir_is_normal_in_a_worktree_and_says_so(tmp_path):
    result = pbc.run(root=str(tmp_path), now=NOW,
                     data_dir=str(tmp_path / "absent"))
    assert result["measured"] is False
    assert "ШТАТНО" in result["doc"]["reason"]


def test_main_returns_two_when_nothing_was_measured(tmp_path, capsys):
    code = pbc.main(["--root", str(tmp_path), "--data-dir", str(tmp_path / "gone")])
    assert code == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_main_returns_one_on_a_finding_and_zero_on_a_clean_book(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pbc, "threshold_birth", lambda *a, **k: (ALL_OLD, None))
    root, data = _fixture(tmp_path, {"morpho_steakhouse": 40000.0,
                                     "maple": 20000.0, "pendle": 20000.0,
                                     "fluid_usdc": 15000.0}, monkeypatch=monkeypatch)
    assert pbc.main(["--root", str(root), "--data-dir", str(data)]) == 1
    capsys.readouterr()

    root2, data2 = _fixture(tmp_path / "ok", {"maple": 20000.0, "pendle": 20000.0},
                            monkeypatch=monkeypatch)
    assert pbc.main(["--root", str(root2), "--data-dir", str(data2)]) == 0


# ─── отрисовка для шага 0-офис ──────────────────────────────────────────────


def test_office_lines_name_the_dispute_and_the_gate_verdict(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"morpho_steakhouse": 40000.0,
                                     "compound_v3": 50000.0})
    monkeypatch.setattr(pbc, "_labels_from_adapter_metadata",
                        lambda: {"morpho_steakhouse": "T1", "compound_v3": "T1"})
    monkeypatch.setattr(pbc, "_labels_from_adapter_registry",
                        lambda: {"morpho_steakhouse": "T2", "compound_v3": "T1"})
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    lines = "\n".join(pbc.format_report(report))
    assert "ЯРЛЫК СПОРЕН" in lines and "morpho_steakhouse" in lines
    assert "ПО КОПИЯМ ГЕЙТА" in lines
    assert "НЕ ДОКАЗЫВАЕТ" in lines


def test_office_lines_of_a_refusal_say_so_and_nothing_else():
    lines = pbc.format_report(pbc._unmeasured("журнала нет", NOW))
    assert len(lines) == 1 and lines[0].startswith("[НЕ ИЗМЕРЕНО]")


def test_report_states_out_loud_what_it_does_not_prove(tmp_path, monkeypatch):
    root, data = _fixture(tmp_path, {"maple": 20000.0, "pendle": 20000.0},
                          monkeypatch=monkeypatch)
    report = _run(root, data, births=ALL_OLD, monkeypatch=monkeypatch)
    assert "не доказывает" in report["what_it_does_not_prove"].lower()


# ─── проводка: артефакт объявлен и читается поимённой ветвью ─────────────────


def test_stage_is_declared_in_the_bridge():
    from spa_core.monitoring import findings_bridge as fb
    assert f"data/{pbc.ARTIFACT_NAME}" in fb.PRODUCES
    assert "policy_binding_census" in fb.CENSUS_STAGE
    assert fb.CENSUS_PRODUCT["policy_binding_census"]["artifact"] == \
        f"data/{pbc.ARTIFACT_NAME}"


def test_office_has_a_named_branch_for_the_artifact():
    """Без поимённой ветви артефакт читался бы ВХОЛОСТУЮ (дефект tier_curator)."""
    source = Path("scripts/consume_office_reports.py").read_text(encoding="utf-8")
    assert pbc.ARTIFACT_NAME in source
    assert "policy_binding_census import format_report" in source


def test_summary_of_a_report_without_counts_says_unmeasured_not_zeroes():
    """Инв. #17 у СВОДКИ: `.get("counts") or {}` дал бы шесть нулей.

    «Не измерено» стало бы «измерено и равно нулю», а код возврата — 0, то есть
    неизмеренный отчёт читался бы как чистая книга.
    """
    broken = {"measured": True, "status": pbc.STATUS_OK, "states": []}
    assert "НЕ ИЗМЕРЕНО" in pbc.summary_line(broken)


def test_main_returns_two_on_a_report_that_lost_its_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(pbc, "run", lambda **k: {
        "measured": True, "doc": {"measured": True, "status": pbc.STATUS_OK}})
    assert pbc.main(["--root", str(tmp_path)]) == 2
