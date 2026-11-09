#!/usr/bin/env python3
"""Батарея переписи §19 «Candidate и Tier» (ADR-962, цикл #1080).

Каждая проба отвечает на СВОЙ вопрос, и у каждой оси есть положительный
контроль — тест, который КРАСНЕЕТ, если звено порвано. Проверка, никогда не
видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Время и личность процесса здесь не участвуют: прибор о свежести не судит, ни
одной литеральной даты в файле нет (храповик замороженных дат — не предмет).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.analytics import tier_candidate_census as tcc


# ---------------------------------------------------------------------------
# Сцена: одноразовое дерево с РЕЕСТРОМ, который мы объявляем сами. Живой
# трекер и живое `data/` не тронуты (инв.: прибор только читает).
# ---------------------------------------------------------------------------
def _tree(tmp_path: Path, adapters: dict, snapshot: list | None = None) -> Path:
    root = tmp_path / "tree"
    (root / "data").mkdir(parents=True)
    (root / "data" / "adapter_registry.json").write_text(
        json.dumps({"version": "test", "adapters": adapters}, ensure_ascii=False),
        encoding="utf-8")
    if snapshot is not None:
        (root / "data" / "adapter_orchestrator_status.json").write_text(
            json.dumps({"adapters": snapshot}, ensure_ascii=False), encoding="utf-8")
    return root


def _entry(**kw):
    base = {"tier": 2, "protocol": "P", "chain": "ethereum", "fallback_apy": 0.05,
            "research_only": False, "per_protocol_cap": 0.2, "status": "active"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Словари: ВВЕЗЕНЫ, а не перепечатаны
# ---------------------------------------------------------------------------
def test_unmeasured_is_imported_not_redeclared():
    """Вторая копия шкалы = две шкалы, расходящиеся молча."""
    from spa_core.analytics.transaction_economics import UNMEASURED as canon
    assert tcc.UNMEASURED == canon
    assert not tcc._VOCAB_ERRORS, f"словарь не ввезён: {tcc._VOCAB_ERRORS}"


def test_kind_vocabularies_are_declared_sets_not_derived_from_branches():
    """Ветка `else` не может сказать, какие роды существуют (урок ADR-357 п. 3)."""
    assert tcc.UNMEASURED in tcc.DISTINCTION_19
    assert tcc.UNMEASURED in tcc.SIZE_ROLE_KINDS
    assert len(set(tcc.DISTINCTION_19)) == len(tcc.DISTINCTION_19)
    assert len(set(tcc.SIZE_ROLE_KINDS)) == len(tcc.SIZE_ROLE_KINDS)


def test_every_axis_kind_belongs_to_its_declared_vocabulary():
    rep = tcc.census()
    assert rep["candidate"]["kind"] in tcc.DISTINCTION_19
    assert rep["size_role"]["kind"] in tcc.SIZE_ROLE_KINDS


# ---------------------------------------------------------------------------
# Третий исход (инв. #17): «не измерено» — значение, а не ноль и не успех
# ---------------------------------------------------------------------------
def test_missing_registry_is_unmeasured_not_an_empty_answer(tmp_path):
    root = tmp_path / "empty"
    (root / "data").mkdir(parents=True)
    reg, why = tcc.load_registry(root)
    assert reg is None and "реестра нет" in why


def test_unparsable_registry_is_unmeasured_with_a_named_reason(tmp_path):
    root = tmp_path / "bad"
    (root / "data").mkdir(parents=True)
    (root / "data" / "adapter_registry.json").write_text("{не json", encoding="utf-8")
    reg, why = tcc.load_registry(root)
    assert reg is None and "не разобран" in why


def test_registry_without_the_adapters_mapping_is_unmeasured(tmp_path):
    root = tmp_path / "noads"
    (root / "data").mkdir(parents=True)
    (root / "data" / "adapter_registry.json").write_text('{"version": "x"}', encoding="utf-8")
    reg, why = tcc.load_registry(root)
    assert reg is None and "adapters" in why


def test_unmeasured_outranks_a_finding_in_the_verdict(tmp_path):
    """Прибор, не обеспечивший предпосылку, обязан сказать это, а не отвечать частично."""
    rep = tcc.census(tmp_path)          # дерева с реестром нет вовсе
    assert tcc.verdict_code(rep) == 2
    assert rep["unmeasured"], "код 2 без НАЗВАННОЙ причины — та же тишина"


def test_named_tree_that_does_not_exist_refuses_with_code_two(tmp_path, capsys):
    code = tcc.main(["--repo-root", str(tmp_path / "нет-такого")])
    assert code == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_default_tree_is_printed_not_silently_assumed(capsys):
    """Умолчание — не ошибка, но читатель обязан узнать, о чьём дереве ответ."""
    tcc.main([])
    assert "дерево НЕ НАЗВАНО входом" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Ось (а): сколько определений
# ---------------------------------------------------------------------------
def test_axis_a_counts_the_label_vocabulary_against_the_cap_vocabulary(tmp_path):
    """§19 спрашивает об ОПРЕДЕЛЕНИИ, а не о разборе: шкалы могут быть разной длины."""
    rep = tcc.census(_tree(tmp_path, {"k": _entry()}))
    sides = {s["side"]: s for s in rep["definitions"]["sides"]}
    assert sides["label"]["distinct"] == 3            # KNOWN_TIERS
    assert sides["per_protocol_cap"]["distinct"] == 2  # t1 / t2, поля t3 нет
    assert "max_concentration_t3" in sides["per_protocol_cap"]["missing_fields"]


def test_axis_a_reports_registry_encodings_without_inventing_a_normaliser(tmp_path):
    """Форм хранения ярлыка в ОДНОМ файле может быть больше одной."""
    root = _tree(tmp_path, {"a": _entry(tier=2), "b": _entry(tier="T1")})
    sides = {s["side"]: s for s in tcc.census(root)["definitions"]["sides"]}
    assert sides["registry_encoding"]["encodings"] == {"int": 1, "str": 1}


def test_axis_a_reproduces_the_known_disagreement_kind(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: засеянное расхождение нормализатора и авторитета видно.

    Род `disagree` уже меряет сосед (`defi_engine.tiers`, 8 копий) — здесь он
    служит контролем, что ось вообще работает, а не новой находкой.
    """
    root = _tree(tmp_path, {"aave_v3": _entry(tier=3)})   # авторитет знает aave_v3 как T1
    agr = tcc.census(root)["definitions"]["agreement"]
    assert agr["kind"] == "disagree"
    assert agr["disagreeing"][0]["key"] == "aave_v3"
    assert agr["disagreeing"][0]["normaliser"] == "T3"


def test_axis_a_separates_authority_silence_from_disagreement(tmp_path):
    """Молчание авторитета — ТРЕТИЙ исход, а не согласие и не расхождение."""
    root = _tree(tmp_path, {"нет-такого-ключа": _entry(tier=1)})
    agr = tcc.census(root)["definitions"]["agreement"]
    assert agr["kind"] == "authority_silent"
    assert agr["disagreeing"] == []
    assert "нет-такого-ключа" in agr["authority_silent_while_registry_names"]


def test_axis_a_reports_agreement_when_both_doors_agree(tmp_path):
    """ОБРАТНЫЙ КОНТРОЛЬ: не найти расхождения там, где его нет."""
    root = _tree(tmp_path, {"aave_v3": _entry(tier=1)})
    agr = tcc.census(root)["definitions"]["agreement"]
    assert agr["kind"] == "agree" and agr["disagreeing"] == []


# ---------------------------------------------------------------------------
# Ось (б): кандидат против допущенного
# ---------------------------------------------------------------------------
def test_axis_b_calls_the_declared_one_door_not_a_private_copy():
    """Своя копия правила запрета означала бы два ответа, расходящиеся молча."""
    import inspect
    from spa_core.allocator.allocator import declared_ban
    src = inspect.getsource(tcc)
    assert "from spa_core.allocator.allocator import declared_ban" in src
    assert "research_only" in inspect.getsource(declared_ban)


def test_axis_b_finds_the_door_blind_to_admission_status(tmp_path):
    """Дифференциал: возмущается РОВНО status, всё прочее бит в бит."""
    root = _tree(tmp_path, {"k": _entry(status="active")})
    cand = tcc.census(root)["candidate"]
    assert cand["kind"] == "declared_door_blind"
    assert cand["door_blind"] is True
    # База и каждое возмущение дают ОДИН вердикт — это и есть слепота.
    assert all(p["verdict"] == cand["scene_base_verdict"] for p in cand["perturbations"])
    # Дословное слово владельца спрошено прямо, а не выведено.
    assert "candidate" in {p["status"] for p in cand["perturbations"]}


def test_axis_b_positive_controls_must_move_the_verdict(tmp_path):
    """Контроль — не украшение: «не изменился» и «прибор не работает» похожи."""
    cand = tcc.census(_tree(tmp_path, {"k": _entry()}))["candidate"]
    verdicts = {c["field"]: c["verdict"] for c in cand["controls"]}
    assert verdicts["research_only"] == "registry_research_only"
    assert verdicts["per_protocol_cap"] == "registry_cap_zero"


def test_axis_b_refuses_to_answer_when_its_control_is_dead(tmp_path, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ НА КОНТРОЛЬ: мёртвая дверь ⇒ ответ НЕ ВЫДАЁТСЯ."""
    doors, err = tcc.load_doors()
    assert err is None
    monkeypatch.setitem(doors, "declared_ban", lambda entry: None)   # дверь, которая всё пускает
    reg, why = tcc.load_registry(_tree(tmp_path, {"k": _entry()}))
    assert why is None
    cand = tcc.candidate_distinction(tmp_path, doors, reg)
    assert cand["kind"] == tcc.UNMEASURED
    assert "контроль" in cand["reason"]


def test_axis_b_reports_absent_when_the_admission_field_does_not_exist(tmp_path):
    entry = _entry()
    entry.pop("status")
    root = _tree(tmp_path, {"k": entry})
    cand = tcc.census(root)["candidate"]
    assert cand["kind"] == "absent"


def test_axis_b_refuses_when_the_scene_is_not_available(tmp_path):
    """Нет ни одной допущенной незабаненной записи ⇒ громкий отказ, не догадка."""
    root = _tree(tmp_path, {"k": _entry(research_only=True)})
    cand = tcc.census(root)["candidate"]
    assert cand["kind"] == tcc.UNMEASURED
    assert "сцена не обеспечена" in cand["reason"]


def test_axis_b_keeps_todays_exposure_separate_from_the_doors_blindness(tmp_path):
    """Ловушка 2: сегодняшний ноль в снимке защитой не является.

    Сцена: НЕдопущенный ключ, ничем не забаненный, которого в снимке НЕТ.
    Дверь слепа (находка), exposure сегодня пуста (отдельное число) — и вердикт
    стои́т на первом, иначе завтрашний снимок унёс бы защиту с собой.
    """
    root = _tree(tmp_path,
                 {"ok": _entry(status="active"), "cand": _entry(status="in_development")},
                 snapshot=[{"protocol": "ok", "status": "ok"}])
    cand = tcc.census(root)["candidate"]
    reach = cand["reachable_today"]
    assert cand["door_blind"] is True
    assert reach["not_admitted_in_snapshot"] == []          # exposure СЕГОДНЯ пуста
    assert reach["latent_not_admitted_unbanned"] == ["cand"]  # и всё же род НЕ ПУСТ
    assert tcc.verdict_code(tcc.census(root)) == 1


def test_axis_b_names_a_not_admitted_key_that_reaches_the_door_healthy(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ exposure: ключ в снимке здоров и НЕ допущен."""
    root = _tree(tmp_path,
                 {"ok": _entry(status="active"), "cand": _entry(status="watchlist")},
                 snapshot=[{"protocol": "ok", "status": "ok"},
                           {"protocol": "cand", "status": "ok"}])
    reach = tcc.census(root)["candidate"]["reachable_today"]
    assert reach["not_admitted_in_snapshot"] == ["cand"]
    assert reach["not_admitted_and_unbanned"] == ["cand"]


def test_axis_b_missing_snapshot_is_unmeasured_exposure_not_zero(tmp_path):
    cand = tcc.census(_tree(tmp_path, {"k": _entry()}))["candidate"]
    assert cand["reachable_today"] is None
    assert "снимка оркестратора нет" in cand["reachable_reason"]


# ---------------------------------------------------------------------------
# Ось (в): тир ограничивает или фиксирует
# ---------------------------------------------------------------------------
def test_axis_c_ladder_crosses_every_declared_cap():
    """Сцена, не пересёкшая порог, отвечает не на тот вопрос (урок §16)."""
    from spa_core.risk.policy import RiskConfig
    cfg = RiskConfig()
    for cap in (cfg.max_concentration_t1, cfg.max_concentration_t2,
                cfg.max_total_t3_allocation):
        assert min(tcc._LADDER) < cap < max(tcc._LADDER), f"лестница не пересекает {cap}"


def test_axis_c_tier_grades_the_refusal_threshold():
    """Тир ОГРАНИЧИВАЕТ: порог первого отказа у каждого тира свой."""
    rep = tcc.census()
    thr = rep["size_role"]["per_tier"]["first_refused_share"]
    assert thr["T1"] > thr["T2"] > thr["T3"], thr


def test_axis_c_names_the_unreachable_per_protocol_cap():
    """T3 не имеет СВОЕГО потолка на протокол, и названный им не связывает один."""
    rep = tcc.census()
    size = rep["size_role"]
    assert size["kind"] == "named_but_unreachable"
    assert size["per_tier"]["tiers_without_own_per_protocol_cap"] == ["T3"]
    sole = size["per_tier"]["per_protocol_cap_ever_sole_binder"]
    assert sole["T1"] is True and sole["T2"] is True and sole["T3"] is False


def test_axis_c_unknown_tier_control_is_fail_closed():
    """ADR-357 п. 3: незнакомый ярлык ОТКАЗЫВАЕТ, а не получает потолок T2."""
    ctrl = {c["control"]: c for c in tcc.census()["size_role"]["controls"]}
    assert ctrl["unknown_tier"]["approved"] is False


def test_axis_c_refuses_to_answer_when_the_label_is_not_read(monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: дверь, одобряющая любой ярлык, ⇒ ответ НЕ ВЫДАЁТСЯ."""
    doors, err = tcc.load_doors()
    assert err is None
    cfg, cfg_err = tcc.load_policy()
    assert cfg_err is None

    class _AlwaysYes:
        def __init__(self, _cfg):
            pass

        def check_new_position(self, *a, **kw):
            class R:
                approved = True
                violations: list = []
            return R()

    monkeypatch.setitem(doors, "RiskPolicy", _AlwaysYes)
    out = tcc.tier_size_role(doors, cfg)
    assert out["kind"] == tcc.UNMEASURED
    assert "контроль" in out["reason"]


def test_axis_c_refuses_when_the_amount_control_is_dead(monkeypatch):
    """Вторая сторона того же контроля: дверь, отказывающая всегда."""
    doors, _ = tcc.load_doors()
    cfg, _ = tcc.load_policy()

    class _AlwaysNo:
        def __init__(self, _cfg):
            pass

        def check_new_position(self, *a, **kw):
            class R:
                approved = False
                violations = ["нет"]
            return R()

    monkeypatch.setitem(doors, "RiskPolicy", _AlwaysNo)
    out = tcc.tier_size_role(doors, cfg)
    assert out["kind"] == tcc.UNMEASURED


def test_axis_c_missing_policy_door_is_unmeasured():
    out = tcc.tier_size_role({}, None)
    assert out["kind"] == tcc.UNMEASURED and out["reason"]


# ---------------------------------------------------------------------------
# Прибор НИЧЕГО не правит
# ---------------------------------------------------------------------------
def test_census_writes_nothing_into_the_tree(tmp_path):
    root = _tree(tmp_path, {"k": _entry()}, snapshot=[{"protocol": "k", "status": "ok"}])
    before = {p: p.read_bytes() for p in sorted((root / "data").iterdir())}
    tcc.census(root)
    after = {p: p.read_bytes() for p in sorted((root / "data").iterdir())}
    assert before == after, "прибор ОБЯЗАН только читать"


def test_module_declares_llm_forbidden_and_imports_no_llm():
    src = Path(tcc.__file__).read_text(encoding="utf-8")
    assert "LLM_FORBIDDEN" in src
    for banned in ("anthropic", "openai", "subprocess"):
        assert banned not in src, f"запрещённая дверь: {banned}"


def test_render_is_total_over_every_report_it_can_produce(tmp_path):
    """Отчёт, который не печатается, читателю не достаётся."""
    for root in (tmp_path, _tree(tmp_path, {"k": _entry()})):
        text = tcc.render(tcc.census(root))
        assert "§19" in text and "ADVISORY" in text


@pytest.mark.parametrize("code", [0, 1, 2])
def test_verdict_codes_are_all_reachable(code, tmp_path, monkeypatch):
    """Три исхода обязаны быть РАЗЛИЧИМЫ, иначе инв. #17 нарушен по построению."""
    if code == 2:
        rep = tcc.census(tmp_path)
    else:
        rep = tcc.census(_tree(tmp_path, {"k": _entry()}))
        if code == 0:
            # «нечего сказать» достижимо: снимаем КАЖДУЮ находку разом. Перечень
            # обязан совпадать с тем, что читает verdict_code, — иначе код 0
            # станет недостижим молча, и три исхода перестанут быть различимы.
            rep["candidate"]["kind"] = "declared_and_read"
            rep["size_role"]["kind"] = "limits"
            rep["definitions"]["agreement"]["kind"] = "agree"
            rep["doors"]["class_gate_claim"] = "honoured"
            rep["doors"]["refused_by_nothing"] = []
    assert tcc.verdict_code(rep) == code


def test_axis_c_unknown_tier_guard_is_tested_in_ISOLATION(monkeypatch):
    """Мутант М7 (цикл #1080) ВЫЖИЛ у первой редакции батареи, и это была её слабость.

    Снятие стража «незнакомый ярлык одобрен ⇒ ответ не выдаётся» не краснило
    ничего: соседний страж (контроль суммы) ловил ту же подменённую дверь, и
    два стража проверялись ОДНИМ тестом. Здесь дверь читает СУММУ и игнорирует
    ЯРЛЫК — тогда поймать её может только страж ярлыка.
    """
    doors, _ = tcc.load_doors()
    cfg, _ = tcc.load_policy()

    class _AmountOnly:
        """Отказывает по сумме (контроль суммы жив), но любой ярлык ей знаком."""

        def __init__(self, _cfg):
            pass

        def check_new_position(self, state, key, tier, amount, *a, **kw):
            ok = amount <= state.total_capital_usd * 0.5

            class R:
                approved = ok
                violations = [] if ok else ["amount"]
            return R()

    monkeypatch.setitem(doors, "RiskPolicy", _AmountOnly)
    out = tcc.tier_size_role(doors, cfg)
    assert out["kind"] == tcc.UNMEASURED, \
        "дверь не читает ярлык, а прибор всё равно ответил об ограничении"
    assert "незнакомого ярлыка" in out["reason"]


def test_a_kind_outside_its_vocabulary_is_unmeasured_not_printed_as_an_answer(tmp_path,
                                                                             monkeypatch):
    """Мутант М9 (цикл #1080) ВЫЖИЛ: сверка рода со словарём не имела читателя.

    Проверять «род лежит в словаре» на ИСПРАВНОМ приборе бессмысленно — он там
    лежит всегда. Предмет сверки — род, которого в словаре НЕТ: он обязан
    превратить ответ в НЕ ИЗМЕРЕНО, а не напечататься как находка.
    """
    root = _tree(tmp_path, {"k": _entry()})
    real = tcc.candidate_distinction
    monkeypatch.setattr(tcc, "candidate_distinction",
                        lambda *a, **kw: {**real(*a, **kw), "kind": "выдуманный_род"})
    rep = tcc.census(root)
    assert any("DISTINCTION_19" in u for u in rep["unmeasured"])
    assert tcc.verdict_code(rep) == 2


def test_size_role_kind_outside_its_vocabulary_is_unmeasured_too(tmp_path, monkeypatch):
    """Та же сверка на ВТОРОЙ оси: один читатель на две шкалы — не читатель."""
    root = _tree(tmp_path, {"k": _entry()})
    real = tcc.tier_size_role
    monkeypatch.setattr(tcc, "tier_size_role",
                        lambda *a, **kw: {**real(*a, **kw), "kind": "выдуманный_род"})
    rep = tcc.census(root)
    assert any("SIZE_ROLE_KINDS" in u for u in rep["unmeasured"])
    assert tcc.verdict_code(rep) == 2


# ---------------------------------------------------------------------------
# Ось (б2): какая дверь ДЕЙСТВИТЕЛЬНО отказывает недопущенному ключу
# ---------------------------------------------------------------------------
def test_axis_b2_measures_the_class_gate_claim_instead_of_trusting_its_docstring():
    """Притязание «не знаем — не финансируем» меряется НЕВОЗМОЖНЫМ именем.

    Текст класс-гейта заявляет решение владельца 12.09 (ADR-357 п. 3,
    «исполнено ADR-359»), а тело держит `if cls is None: return True, None`.
    Читать это глазами нельзя: прибор обязан спросить саму дверь.
    """
    doors = tcc.doors_refusing(None)
    assert doors["class_gate_claim"] in ("honoured", "claimed_not_honoured")
    assert "allowed" in doors["class_gate_on_impossible_key"]


def test_axis_b2_impossible_key_is_not_an_existing_one():
    """Контроль самого контроля: имя обязано быть ЗАВЕДОМО отсутствующим."""
    from spa_core.adapters import ADAPTER_REGISTRY
    assert tcc._IMPOSSIBLE_KEY not in {e[0] for e in ADAPTER_REGISTRY}
    assert tcc._IMPOSSIBLE_KEY, "пустая строка — у неё своя ветка, контролем быть не может"


def test_axis_b2_names_the_key_no_door_refuses(tmp_path):
    """Недопущенный ключ, у которого ни одна дверь не возражает, НАЗВАН поимённо."""
    root = _tree(tmp_path, {"ok": _entry(status="active"),
                            "cand": _entry(status="in_development")})
    doors = tcc.census(root)["doors"]
    assert doors["refused_by_nothing"] == ["cand"]
    row = next(r for r in doors["per_key"] if r["key"] == "cand")
    assert row["refused_by"] == [] and row["refused_by_nothing"] is True


def test_axis_b2_does_not_call_a_refusal_by_another_door_a_refusal_by_admission(tmp_path):
    """ОБРАТНЫЙ КОНТРОЛЬ: отказ СОСЕДНЕЙ двери назван ИМЕНЕМ этой двери.

    Иначе «ключ не финансируется» подменило бы «дверь допуска его не пускает» —
    ровно та ошибка, которую §16 и §18 исправляли своим же замером.
    """
    root = _tree(tmp_path, {"ok": _entry(status="active"),
                            "ro": _entry(status="research", research_only=True),
                            "t": _entry(status="watchlist", tier=9)})
    doors = tcc.census(root)["doors"]
    rows = {r["key"]: r["refused_by"] for r in doors["per_key"]}
    assert rows["ro"] == ["declared_ban:registry_research_only"]
    assert rows["t"] == ["tier_unknown"]
    assert doors["refused_by_nothing"] == []


def test_axis_b2_unreadable_registry_is_unmeasured_with_a_reason():
    doors = tcc.doors_refusing(None)
    assert doors["per_key"] == [] and "реестр не прочитан" in doors["reason"]


def test_axis_b2_findings_reach_the_verdict(tmp_path):
    """Находка, которую отчёт печатает, но вердикт не считает, — украшение."""
    root = _tree(tmp_path, {"ok": _entry(status="active"),
                            "cand": _entry(status="in_development")})
    rep = tcc.census(root)
    assert rep["doors"]["refused_by_nothing"] == ["cand"]
    assert tcc.verdict_code(rep) == 1


def test_axis_b2_claim_is_DERIVED_from_the_door_in_both_directions(monkeypatch):
    """Мутант М14 ВЫЖИЛ: тест проверял, что род ОДИН ИЗ ДВУХ, а не что он ИЗМЕРЕН.

    «Притязание исполнено» обязано происходить от ОТВЕТА двери. Сцена гоняется
    дважды, и дверь отвечает ПРОТИВОПОЛОЖНО — иначе константа `honoured`
    неотличима от замера.
    """
    import spa_core.allocator.allocator as alloc

    monkeypatch.setattr(alloc, "_adapter_class_gate", lambda key: (False, "unknown_key"))
    assert tcc.doors_refusing(None)["class_gate_claim"] == "honoured"

    monkeypatch.setattr(alloc, "_adapter_class_gate", lambda key: (True, None))
    assert tcc.doors_refusing(None)["class_gate_claim"] == "claimed_not_honoured"


def test_axis_b2_is_the_SOLE_finding_and_still_reaches_the_verdict(tmp_path):
    """Мутант М18 ВЫЖИЛ: вердикт был 1 из-за СОСЕДНЕЙ находки, не из-за этой.

    Находку надо предъявлять в ОДИНОЧЕСТВЕ, иначе тест измеряет чужой бит.
    """
    rep = tcc.census(_tree(tmp_path, {"ok": _entry(status="active"),
                                      "cand": _entry(status="in_development")}))
    # гасим ВСЕ соседние находки — остаётся ровно ось (б2)
    rep["candidate"]["kind"] = "declared_and_read"
    rep["size_role"]["kind"] = "limits"
    rep["definitions"]["agreement"]["kind"] = "agree"
    rep["doors"]["class_gate_claim"] = "honoured"
    assert rep["doors"]["refused_by_nothing"] == ["cand"]
    assert tcc.verdict_code(rep) == 1, "находка оси (б2) до вердикта не доходит"

    # и вторая находка той же оси — тоже в одиночестве
    rep["doors"]["refused_by_nothing"] = []
    rep["doors"]["class_gate_claim"] = "claimed_not_honoured"
    assert tcc.verdict_code(rep) == 1


def test_axis_b2_unmeasured_claim_outranks_every_finding(tmp_path):
    """Мутант М20 ВЫЖИЛ: третий исход оси (б2) вердиктом не читался."""
    rep = tcc.census(_tree(tmp_path, {"k": _entry()}))
    rep["doors"]["class_gate_claim"] = tcc.UNMEASURED
    assert tcc.verdict_code(rep) == 2, \
        "НЕ ИЗМЕРЕНО у оси (б2) не старше находки — инв. #17 нарушен"
