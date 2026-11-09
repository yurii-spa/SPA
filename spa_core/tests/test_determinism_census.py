"""Контроли §26 ТЗ «Portfolio CIO» — ADR-969.

Каждая проверка здесь — контроль ОДНОГО звена прибора
:mod:`spa_core.analytics.determinism_census`, и у каждой несущей претензии есть
контроль В ОБЕ СТОРОНЫ: зелёный на целом контуре и КРАСНЫЙ на порванном звене,
с названным звеном (правило `.claude/rules/acceptance.md`, п. 3).

ВРЕМЯ — ВХОД, А НЕ ОКРУЖЕНИЕ. Литеральных дат в файле нет ни одной: сцены
строятся от ОДНОГО якоря, полученного в рантайме, и тот же якорь передаётся
прибору аргументом ``now=``. Обе стороны сравнения закреплены, поэтому файл не
краснеет от сдвига календаря — и `FROZEN-DATE-OK` ему не нужен, потому что
замораживать нечего (`.claude/rules/deployment.md`, § «Время в тестах»).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

import pytest

from spa_core.analytics import determinism_census as DC
from spa_core.analytics.transaction_economics import UNMEASURED


# ───────────────────────────── сцена: один якорь ──────────────────────────────

def _anchor() -> dt.datetime:
    """Якорь сцены. Рантайм, а не литерал — см. докстринг модуля."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _iso(moment: dt.datetime) -> str:
    return moment.isoformat()


def _scene(tmp: str, *, orch_age_h: float, status_age_h: float,
           anchor: dt.datetime) -> str:
    """Каталог-снимок: один протокол у КАЖДОГО источника доказательности.

    ``orchestrator_live`` и ``adapter_status_live`` — РАЗНЫЕ источники, и
    развести их по отдельным протоколам обязательно: слитые в один они
    затёрли бы друг друга тай-брейком по свежести, и ось C отвечала бы о
    тай-брейке вместо окна свежести.
    """
    data = os.path.join(tmp, "data")
    os.makedirs(data, exist_ok=True)
    orch_ts = _iso(anchor - dt.timedelta(hours=orch_age_h))
    st_ts = _iso(anchor - dt.timedelta(hours=status_age_h))
    with open(os.path.join(data, "adapter_orchestrator_status.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"generated_at": orch_ts,
                   "adapters": [{"protocol": "from_orchestrator",
                                 "live_data": True, "status": "ok",
                                 "apy_pct": 5.0}]}, fh)
    with open(os.path.join(data, "adapter_status.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"generated_at": st_ts,
                   "adapters": {"from_status": {"live_apy": 4.0,
                                                "live_apy_as_of": st_ts}}}, fh)
    return data


# ─────────────────────── паритет: константа ↔ карточка ────────────────────────

def test_constants_agree_with_the_real_owner_card():
    """Несущая претензия: 4 входа / 3 разрешено / 4 запрещено — ПО КАРТОЧКЕ.

    Это и есть паритет ADR-913/ADR-919: число живёт дважды, и producer —
    разбор карточки, а не вторая копия константы.
    """
    card = os.path.join(DC.REPO_ROOT, DC.CARD_REL)
    if not os.path.isfile(card):
        pytest.fail(f"карточка приказа не найдена в дереве: {card} — "
                    f"паритет НЕ ИЗМЕРЕН, и это не повод его пропустить")
    result = DC.parity(card)
    assert result["parsed"]["measured"], result["parsed"]["reason"]
    assert result["agrees"] is True, result["mismatches"]
    assert len(result["parsed"]["inputs"]) == DC.OWNER_INPUTS_DECLARED == 4
    assert len(result["parsed"]["permitted"]) == DC.OWNER_PERMITTED_DECLARED == 3
    assert len(result["parsed"]["forbidden"]) == DC.OWNER_FORBIDDEN_DECLARED == 4


def test_parity_names_the_drift_instead_of_hiding_it(tmp_path):
    """ОБРАТНЫЙ контроль: текст владельца поехал ⇒ расхождение НАЗВАНО.

    Порванное звено — состав перечня. Прибор, который здесь промолчит, и есть
    сторож, сверяющий свои константы сам с собой.
    """
    card = tmp_path / "card.md"
    card.write_text(
        f"{DC.SECTION_HEAD}\n"
        f"{DC._INPUTS_LEAD}\n"
        "market snapshot\nportfolio state\nrisk policy\n"
        f"{DC._RESULT_LINE}\n"
        f"{DC._PERMITTED_LEAD}\nобъяснять;\nsummarise;\n"
        "формировать owner-facing recommendation.\n"
        f"{DC._FORBIDDEN_LEAD}\nарифметику;\nallocation constraints;\n"
        "финансовые расчеты;\npolicy pass/fail.\n"
        f"{DC.NEXT_SECTION_HEAD}\n", encoding="utf-8")
    result = DC.parity(str(card))
    assert result["agrees"] is False
    assert any("inputs" in m for m in result["mismatches"]), result["mismatches"]


def test_unreadable_card_is_a_third_outcome_not_a_fallback_to_constants(tmp_path):
    """Нечитаемая карточка ⇒ `measured=False` с причиной, а НЕ тихое согласие."""
    result = DC.parity(str(tmp_path / "does-not-exist.md"))
    assert result["agrees"] is None
    assert result["parsed"]["measured"] is False
    assert "не прочитана" in result["parsed"]["reason"]


def test_missing_second_border_refuses_to_count(tmp_path):
    """Нет заголовка §27 ⇒ перечень НЕ ограничен ⇒ счёт не выдаётся.

    Ровно ловушка §25: без второй границы в перечень попадает заголовок
    следующего раздела, и наивный счёт даёт на единицу больше.
    """
    card = tmp_path / "card.md"
    card.write_text(f"{DC.SECTION_HEAD}\n{DC._INPUTS_LEAD}\nmarket snapshot\n",
                    encoding="utf-8")
    parsed = DC.owner_section_from_card(str(card))
    assert parsed["measured"] is False
    assert DC.NEXT_SECTION_HEAD in parsed["reason"]


# ───────────────────── ось A: пришпиливаемость входов §26 ─────────────────────

def test_axis_a_declaration_is_checked_against_the_live_signature():
    """Объявленные аргументы ОБЯЗАНЫ существовать у точки входа субъекта."""
    pin = DC.measure_pinnability(DC.REPO_ROOT)
    assert pin["measured"], pin["reason"]
    tuner = pin["subjects"]["tuner"]
    for owner_input in DC.INPUTS_26:
        assert tuner[owner_input]["kind"] == "pinnable_named", \
            (owner_input, tuner[owner_input])


def test_axis_a_reddens_when_the_declaration_drifts_from_the_signature(monkeypatch):
    """ПОРВАННОЕ ЗВЕНО: объявлен аргумент, которого у субъекта нет.

    Прибор обязан ответить `unmeasured` с названным аргументом, а НЕ
    «пришпилено»: расхождение объявления с кодом — это молчащее слепое пятно.
    """
    drifted = {k: dict(v) for k, v in DC.INPUT_MAP.items()}
    drifted["tuner"]["configuration"] = ("no_such_parameter_at_all",)
    monkeypatch.setattr(DC, "INPUT_MAP", drifted)
    pin = DC.measure_pinnability(DC.REPO_ROOT)
    row = pin["subjects"]["tuner"]["configuration"]
    assert row["kind"] == UNMEASURED
    assert "no_such_parameter_at_all" in row["reason"]


def test_allocator_does_not_read_the_book_and_a_comment_does_not_refute_it():
    """`not_an_input` доказан РАЗБОРОМ КОДА, а не отсутствием аргумента.

    Обратная сторона того же контроля: слово «portfolio» живёт в аллокаторе
    РОВНО в комментарии, и наивный ``grep`` опроверг бы верную претензию.
    Поэтому свидетельство берётся у AST без докстрок и без комментариев.
    """
    pin = DC.measure_pinnability(DC.REPO_ROOT)
    row = pin["subjects"]["allocator"]["portfolio state"]
    assert row["kind"] == "not_an_input", row
    assert row["proof"]["words_absent_from_code"] is True, row["proof"]
    assert row["proof"]["hits"] == []


def test_code_identifiers_ignores_comments_and_docstrings(tmp_path):
    """Прямой контроль свидетельства: комментарий и докстрока НЕ считаются.

    Сцена разводит ДВА ответа на одном файле: в сырых байтах слово ЕСТЬ, среди
    имён и литералов кода его НЕТ. Без этой стороны претензия «меряем AST»
    держалась бы на слове, а не на замере.
    """
    module = tmp_path / "m.py"
    module.write_text(
        '"""Докстрока упоминает portfolio."""\n'
        "# и комментарий тоже упоминает portfolio\n"
        "X = 1\n", encoding="utf-8")
    ids, why = DC._code_identifiers(str(module))
    assert ids is not None, why
    assert "portfolio" in module.read_text(encoding="utf-8")
    assert not any("portfolio" in i for i in ids), sorted(ids)


def test_code_identifiers_unparsable_module_is_a_named_reason(tmp_path):
    """Не разобрали ⇒ названная причина, а НЕ пустое множество имён.

    Пустое множество означало бы «слов нет», то есть подтвердило бы любую
    претензию `not_an_input` на сломанном файле.
    """
    broken = tmp_path / "broken.py"
    broken.write_text("def oops(\n", encoding="utf-8")
    ids, why = DC._code_identifiers(str(broken))
    assert ids is None
    assert "SyntaxError" in why


def test_not_an_input_claim_is_refuted_by_a_real_code_mention(monkeypatch):
    """ПОРВАННОЕ ЗВЕНО: претензия «книгу не читает» опровергается замером.

    Если слово-свидетель ВСТРЕЧАЕТСЯ в коде, прибор обязан снять претензию и
    сказать `unmeasured`, а не повторить объявление.
    """
    proof = dict(DC.NOT_AN_INPUT_PROOF)
    # `status_path` — настоящий аргумент аллокатора, то есть слово заведомо
    # ЕСТЬ в коде: сцена ломает именно звено «претензия подтверждается кодом».
    proof[("allocator", "portfolio state")] = (
        "spa_core/allocator/allocator.py", ("status_path",))
    monkeypatch.setattr(DC, "NOT_AN_INPUT_PROOF", proof)
    pin = DC.measure_pinnability(DC.REPO_ROOT)
    row = pin["subjects"]["allocator"]["portfolio state"]
    assert row["kind"] == UNMEASURED
    assert "ОПРОВЕРГНУТА" in row["reason"]


def test_fifth_input_is_not_pinnable_at_either_entry_point():
    """Несущая находка §26: `now` не пришпилить у точки входа ни у кого."""
    pin = DC.measure_pinnability(DC.REPO_ROOT)
    for subject, row in pin["fifth_input"]["subjects"].items():
        assert row["kind"] == "unpinnable_ambient", (subject, row)
        assert "now" in row["reason"]


# ──────────────── ось C: пятый вход, дифференциально ─────────────────────────

def test_axis_c_result_changes_from_the_clock_alone(tmp_path):
    """НЕСУЩАЯ НАХОДКА: байты входа те же, меняется РОВНО `now`.

    Сцена построена так, что источник ``adapter_status`` стои́т близко к краю
    окна: на якоре он доказателен, на сдвиге за окно — нет.
    """
    anchor = _anchor()
    data = _scene(str(tmp_path), orch_age_h=1.0, status_age_h=1.0, anchor=anchor)
    out = DC.measure_fifth_input(data, offsets_h=(0.0, 48.0), now=anchor)
    assert out["measured"], out["reason"]
    assert out["depends_on_clock"] is True
    assert out["changed_at_offsets"] == [48.0]
    assert out["rows"][0]["apy_evidenced"] == ["from_orchestrator", "from_status"]
    assert out["rows"][1]["apy_evidenced"] == ["from_orchestrator"]


def test_axis_c_says_not_dependent_when_nothing_moves(tmp_path):
    """ОБРАТНЫЙ контроль: внутри окна набор НЕ меняется ⇒ находки нет.

    Без этой стороны «зависит от часов» было бы свойством прибора, а не мира.
    """
    anchor = _anchor()
    data = _scene(str(tmp_path), orch_age_h=1.0, status_age_h=1.0, anchor=anchor)
    out = DC.measure_fifth_input(data, offsets_h=(0.0, 1.0, 2.0), now=anchor)
    assert out["measured"], out["reason"]
    assert out["depends_on_clock"] is False
    assert out["changed_at_offsets"] == []


def test_axis_c_names_the_source_that_never_ages(tmp_path):
    """Вторая находка: ветка снимка оркестратора окна свежести НЕ применяет.

    На сдвиге в год источник ``adapter_status`` вымирает весь, а
    ``orchestrator_live`` остаётся — то есть `_fundable` на нём НИКОГДА не
    скажет `unevidenced`.
    """
    anchor = _anchor()
    data = _scene(str(tmp_path), orch_age_h=1.0, status_age_h=1.0, anchor=anchor)
    out = DC.measure_fifth_input(data, offsets_h=(0.0, 8760.0), now=anchor)
    assert out["measured"], out["reason"]
    assert out["never_aging"]["apy_by_source"] == {"orchestrator_live": 1}
    assert out["never_aging"]["apy_evidenced"] == ["from_orchestrator"]


def test_axis_c_missing_snapshot_is_unmeasured_not_equal_sets(tmp_path):
    """Снимка нет ⇒ названная причина, а НЕ «наборы совпали».

    Пустая сцена дала бы одинаковые (пустые) наборы на всех сдвигах, то есть
    зелёный ответ «от часов не зависит» — ровно fail-OPEN, тише красного.
    """
    out = DC.measure_fifth_input(str(tmp_path / "nowhere"), now=_anchor())
    assert out["measured"] is False
    assert "снимок не прочитан" in out["reason"]
    assert out["depends_on_clock"] is not True


def test_axis_c_refuses_when_the_injection_door_is_gone(monkeypatch, tmp_path):
    """ПОРВАННОЕ ЗВЕНО: дверь инъекции часов исчезла ⇒ ось НЕ ИЗМЕРЕНА."""
    anchor = _anchor()
    data = _scene(str(tmp_path), orch_age_h=1.0, status_age_h=1.0, anchor=anchor)
    from spa_core.allocator import allocator as A
    monkeypatch.delattr(A, "_EVIDENCE_MAX_AGE_H")
    out = DC.measure_fifth_input(data, now=anchor)
    assert out["measured"] is False
    assert "_EVIDENCE_MAX_AGE_H" in out["reason"]


# ───────────── ось B: соль хеша и ОБЯЗАТЕЛЬНЫЙ свидетель непустоты ───────────

def test_axis_b_vacuous_scene_is_a_third_outcome_not_sameness():
    """ГЛАВНЫЙ контроль оси B (контрапункт (а) заказа G957 п. 1).

    Четыре пустых ответа дают ОДИН хеш, то есть «одинаково» верно случайно.
    Прибор обязан это заметить и отказаться от вердикта.
    """
    empty = {"timestamp": "x", "apy_used": {}, "allocated_pct": 0.0}
    why = DC._scene_is_vacuous(empty)
    assert why is not None
    assert "apy_used" in why


def test_axis_b_missing_witness_field_is_also_vacuity():
    """Поле-свидетель переехало ⇒ непустота НЕ ПОДТВЕРЖДЕНА.

    «Поля нет» не равно «поле пусто», но для вердикта оба означают одно:
    сказать о непустоте нечем.
    """
    why = DC._scene_is_vacuous({"timestamp": "x", "allocated_pct": 0.9})
    assert why is not None
    assert "apy_used" in why


def test_axis_b_live_scene_is_not_vacuous():
    """ОБРАТНАЯ сторона: настоящий ответ субъекта свидетелями НЕ пуст."""
    assert DC._scene_is_vacuous(
        {"timestamp": "x", "apy_used": {"aave_v3": 3.7},
         "allocated_pct": 0.9}) is None


def test_axis_b_declares_a_free_hash_seed_state():
    """Соль спрашивается и СВОБОДНОЙ — дверь, которой нет у соседа по §49.

    Сосед всегда выставляет ``PYTHONHASHSEED`` явно, то есть отвечает про
    НАСТРОЙКУ; живой дневной цикл её не пришпиливает.
    """
    assert any(seed is None for _state, seed in DC.SEED_STATES)
    assert any(seed is not None for _state, seed in DC.SEED_STATES)


def test_axis_b_unknown_subject_cannot_build_a_scene():
    """Субъекта нет у соседа ⇒ «сцену строить нечем», а не «совпало»."""
    out = DC.measure_seed_door("/nonexistent", subject_key="no_such_subject")
    assert out["measured"] is False
    assert "сцену строить нечем" in out["reason"]


# ───────────────────────── ось D: половина про LLM ───────────────────────────

def test_axis_d_every_forbidden_determination_has_a_living_answerer():
    """Все ЧЕТЫРЕ запрещённых §26 определения имеют ответчика в дереве."""
    llm = DC.measure_llm_half(DC.REPO_ROOT)
    assert sorted(llm["forbidden"]) == sorted(DC.FORBIDDEN_26)
    for item, row in llm["forbidden"].items():
        assert row["kind"] == "answered_elsewhere", (item, row)
        assert os.path.isfile(os.path.join(DC.REPO_ROOT, row["address"]))


def test_axis_d_absent_answerer_is_unmeasured(monkeypatch):
    """ПОРВАННОЕ ЗВЕНО: объявленный ответчик пропал из дерева."""
    table = dict(DC.LLM_ANSWERED_BY)
    table["арифметику"] = ("scripts/does_not_exist_at_all.py", "сцена")
    monkeypatch.setattr(DC, "LLM_ANSWERED_BY", table)
    llm = DC.measure_llm_half(DC.REPO_ROOT)
    assert llm["forbidden"]["арифметику"]["kind"] == UNMEASURED


# ───── §45: проба ОБЯЗАНА спрашивать ОБЕ двери сторожа (починка ADR-969) ─────

def test_guard_blindness_asks_both_doors_and_sees_the_subprocess_scene():
    """НЕСУЩАЯ ПОЧИНКА: сцена-subprocess ловится ВТОРОЙ дверью сторожа.

    До ADR-969 проба звала РОВНО ``run_lint`` («дверь первая — и только она»)
    и печатала из её нуля CRITICAL о СТОРОЖЕ. Двенадцать циклов подряд.
    """
    from spa_core.monitoring.cio_architecture_constraints import lint_blindness
    guard = lint_blindness(DC.REPO_ROOT)
    assert guard["measured"] is True, guard.get("reason")
    assert guard["control_ok"] is True
    sub = guard["scenes"]["subprocess_binary"]
    assert sub["all_doors_asked"] is True
    assert sub["seen"] is True
    assert sub["seen_by"] == ["subprocess_door"]
    assert guard["blind_to_subprocess"] is False


def test_guard_blindness_is_unmeasured_when_a_door_cannot_be_asked(tmp_path):
    """ПОРВАННОЕ ЗВЕНО: у сторожа нет второй точки входа.

    Тогда «не видит» утверждать НЕЛЬЗЯ — это третий исход. Подставить тут
    ``True`` значило бы вернуть исходный дефект с другой стороны.
    """
    from spa_core.monitoring.cio_architecture_constraints import lint_blindness
    fake_root = tmp_path / "tree"
    (fake_root / "scripts").mkdir(parents=True)
    # Сторож БЕЗ двери-запуска: только `run_lint`, и он ничего не находит.
    # Дверь-SDK обязана находить ТОЛЬКО свою сцену: поддельный сторож,
    # «видящий» всё, сделал бы сцену-subprocess пойманной первой дверью, и
    # тест проверял бы не то звено (сцена обязана нарушать ИМЕННО своё
    # ограничение — класс #511).
    (fake_root / "scripts" / "lint_llm_forbidden.py").write_text(
        "import os\n"
        "def run_lint(base_dir, strict=False):\n"
        "    hits = []\n"
        "    for root, _dirs, files in os.walk(base_dir):\n"
        "        for name in files:\n"
        "            p = os.path.join(root, name)\n"
        "            if 'import anthropic' in open(p, encoding='utf-8').read():\n"
        "                hits.append((p, 1, 'import anthropic'))\n"
        "    return 0, hits\n", encoding="utf-8")
    guard = lint_blindness(str(fake_root))
    assert guard["measured"] is True
    assert guard["blind_to_subprocess"] is None, guard
    assert "run_launch_lint" in guard["blind_unmeasured_reason"]


def test_section_45_no_longer_reports_the_stale_critical():
    """Секция §45 печатает ЗАКРЫТОЕ состояние, а не CRITICAL о слепоте."""
    from spa_core.monitoring.cio_architecture_constraints import run as run45
    doc = run45(DC.REPO_ROOT, write=False)
    codes = {f["code"] for f in doc["findings"]}
    assert "guard_blind_to_real_door" not in codes
    assert "guard_sees_the_real_door" in codes


# ─────────────────────────── отчёт целиком ───────────────────────────────────

def test_report_is_advisory_and_writes_nothing_when_asked_not_to(tmp_path):
    """Прибор ТОЛЬКО читает: `applied=False`, и живое `data/` не трогается."""
    anchor = _anchor()
    data = _scene(str(tmp_path), orch_age_h=1.0, status_age_h=1.0, anchor=anchor)
    before = sorted(os.listdir(data))
    doc = DC.run(root=DC.REPO_ROOT, data_dir=data, write=False,
                 with_seed_axis=False, now=anchor)
    assert doc["applied"] is False
    assert doc["schema"] == "determinism_census/v1"
    assert sorted(os.listdir(data)) == before


def test_overall_is_unchecked_when_an_axis_is_not_measured(tmp_path):
    """Третий исход доезжает до ВЕРДИКТА, а не теряется по пути."""
    doc = DC.run(root=DC.REPO_ROOT, data_dir=str(tmp_path / "nowhere"),
                 write=False, with_seed_axis=False, now=_anchor())
    assert doc["counts"]["unmeasured"] >= 1
    assert doc["overall"] in ("CRITICAL", "WARNING", "UNCHECKED")
    assert any("ось C" in u for u in doc["unmeasured"])


def test_missing_source_breakdown_is_unmeasured_not_absence_of_the_finding():
    """Контроль члена класса «отсутствие наблюдения = благополучие» (инв. #17).

    Первая редакция прибора писала `… .get("apy_by_source") or {}`, и тогда
    «состав источников не измерен» было НЕОТЛИЧИМО от «нестареющих источников
    нет»: находка просто не печаталась. Поймал это собственный храповик
    `test_absent_observation_ratchet`, а не ревью.
    """
    fifth = {"measured": True, "depends_on_clock": True,
             "changed_at_offsets": [48.0], "max_age_h": 36.0,
             "counts": {"apy_at_zero": 2, "apy_at_far": 1,
                        "tvl_at_zero": 1, "tvl_at_far": 0},
             "never_aging": {"offset_h": 8760.0}}  # БЕЗ `apy_by_source`
    findings, unmeasured = DC._findings(
        {"agrees": True, "mismatches": [], "parsed": {"measured": True}},
        {"measured": False, "reason": "ось A не нужна этой сцене"},
        {"measured": False, "reason": "ось B не нужна этой сцене"},
        fifth,
        {"forbidden": {}, "guard": {"measured": True,
                                    "blind_to_subprocess": False}})
    codes = {f["code"] for f in findings}
    assert "result_depends_on_the_clock" in codes
    assert "evidence_that_never_ages" not in codes
    assert any("не измерен" in u.lower() or "НЕ ИЗМЕРЕН" in u
               for u in unmeasured), unmeasured
