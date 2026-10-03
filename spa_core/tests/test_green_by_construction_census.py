"""Батарея переписи «зелёный по построению» (заказ G92 п. 2, ADR-504).

Устройство батареи — порядок `.claude/rules/acceptance.md` п. 3: мера проверяется
на ЦЕЛОМ контуре (одноразовый мини-репозиторий со своим прибором и своими тестами,
настоящие прогоны pytest) и КРАСНЕЕТ на каждом порванном звене, с НАЗВАННЫМ звеном.
Контур мал намеренно: предмет меры — её собственная проводка, а не чужой прибор.
"""
# FROZEN-DATE-OK: injected-clock — у такта ступени ЗАКРЕПЛЕНЫ ОБЕ стороны, и это
# приём №1 из `.claude/rules/deployment.md`, а не записка рядом со стенными часами:
# отметка прошлого замера пишется литералом в артефакт (`_stamp`), а «сейчас»
# ПЕРЕДАЁТСЯ входом `now=` в `gbc.run`. Ни одна из проверок такта не спрашивает
# времени у машины, поэтому сдвиг календаря их не красит.

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import green_by_construction_census as gbc  # noqa: E402


# ── 1. разбор прибора ────────────────────────────────────────────────────────

_SRC = textwrap.dedent('''\
    # коммент с кириллицей: ё, щ, — чтобы байтовый столбец разошёлся с символьным
    def _probe_one(flag, items):
        """Док."""
        if flag:                      # решение 1
            return "satisfied", "да"
        kept = [i for i in items if i > 0]      # решение 2 (фильтр включения)
        return ("not_satisfied" if kept else "unmeasured"), str(kept)  # решение 3


    def helper(flag):
        if flag:                      # НЕ решение: имя без префикса
            return 1
        return 0
    ''')


def test_decision_points_sees_three_kinds_and_only_prefixed_functions():
    found = gbc.decision_points(_SRC, "_probe_")
    kinds = sorted(d["kind"] for d in found)
    assert kinds == ["comprehension", "if", "ifexp"], found
    assert all(d["func"] == "_probe_one" for d in found), found


def test_decision_ids_address_by_name_and_coordinate_not_by_ordinal():
    found = gbc.decision_points(_SRC, "_probe_")
    assert all(d["id"].startswith("_probe_one:") for d in found)
    # Тот же разбор дважды — те же имена: координата устойчива к повтору.
    again = gbc.decision_points(_SRC, "_probe_")
    assert [d["id"] for d in found] == [d["id"] for d in again]


def test_span_is_counted_in_BYTES_not_characters():
    """Положительный контроль ловушки: ``col_offset`` у AST — БАЙТЫ utf-8.

    Строка-ловушка несёт кириллицу ПЕРЕД условием; символьный срез уехал бы
    ровно на число непечатных ascii-байт, и принуждение встало бы мимо.
    """
    src = 'def _probe_x(a):\n    if a:  # хвост\n        return 1\n    return 0\n'
    dec = [d for d in gbc.decision_points(src, "_probe_") if d["kind"] == "if"][0]
    forced = gbc.force_source(src, dec, True)
    assert forced is not None
    assert "if True:  # хвост" in forced, forced


def test_force_source_writes_BOTH_sides_and_they_differ():
    """D3 убит здесь, у контракта функции: принуждение, пишущее одну и ту же
    сторону дважды, превратило бы двусторонний замер в односторонний молча —
    и ни одна сцена контура этого не увидела бы (сцена инертна к такой подмене)."""
    src = 'def _probe_x(a):\n    if a:\n        return 1\n    return 0\n'
    dec = gbc.decision_points(src, "_probe_")[0]
    yes, no = gbc.force_source(src, dec, True), gbc.force_source(src, dec, False)
    assert yes is not None and no is not None
    assert "if True:" in yes and "if False:" not in yes, yes
    assert "if False:" in no and "if True:" not in no, no


def test_instrumented_source_parses_and_keeps_every_byte_outside_the_spans():
    found = gbc.decision_points(_SRC, "_probe_")
    out = gbc.instrument_source(_SRC, found)
    compile(out, "<inst>", "exec")           # разбирается
    assert "# коммент с кириллицей" in out   # комментарии НЕ снесены (не unparse)
    assert out.count("_GBC_REC(") == len(found) + 1   # +1 — определение записи


def test_force_source_refuses_an_edit_that_does_not_parse():
    """Контракт проверяется У САМОЙ функции, а не у потребителя (ADR-504, порядок
    разбора выживших): через `decision_points` негодный пролёт не построить."""
    src = 'def _probe_x(a):\n    if a:\n        return 1\n    return 0\n'
    broken = {"id": "x", "func": "_probe_x", "kind": "if",
              "lineno": 2, "col_offset": 4, "end_lineno": 2, "end_col_offset": 10}
    assert gbc.force_source(src, broken, True) is None


# ── 2. классификация (чистая функция) ────────────────────────────────────────

def test_a_test_absent_from_the_baseline_record_is_unmeasured():
    verdict, why = gbc.classify_test(baseline_outcome=None, reached=["d"],
                                     red_under=[], vanished_under=[],
                                     unforceable_reached=[])
    assert verdict == gbc.VERDICT_UNMEASURED and "базового прогона" in why


@pytest.mark.parametrize("outcome", ["failed", "error", "skipped"])
def test_a_test_not_green_on_the_baseline_is_unmeasured_not_clean(outcome):
    verdict, _ = gbc.classify_test(baseline_outcome=outcome, reached=["d"],
                                   red_under=[], vanished_under=[],
                                   unforceable_reached=[])
    assert verdict == gbc.VERDICT_UNMEASURED


def test_positive_evidence_beats_a_gap_in_the_remainder():
    """`sensitive` решается ПЕРВЫМ: тест, упавший хотя бы от одного принуждения,
    доказал свою зависимость, и отдать его в `unmeasured` из-за несобравшейся
    соседней правки значило бы потерять доказанный зелёный."""
    verdict, _ = gbc.classify_test(baseline_outcome="passed", reached=["a", "b"],
                                   red_under=["a"], vanished_under=[],
                                   unforceable_reached=["b"])
    assert verdict == gbc.VERDICT_SENSITIVE


def test_a_decision_that_could_not_be_forced_leaves_the_test_unmeasured():
    """Несобравшаяся правка — третий исход, а не «принуждение ничего не изменило»:
    иначе дыра в приборе читалась бы как находка о тесте."""
    verdict, why = gbc.classify_test(baseline_outcome="passed", reached=["a"],
                                     red_under=[], vanished_under=[],
                                     unforceable_reached=["a"])
    assert verdict == gbc.VERDICT_UNMEASURED and "не принудить" in why


def test_skipped_is_NOT_red__a_vanished_test_must_not_count_as_a_kill():
    """Урок #465 закреплён у САМОЙ константы, а не только в прозе: припиши
    `skipped` к красному — и исчезнувший тест засчитался бы в убийство мутанта."""
    assert "skipped" not in gbc.RED_OUTCOMES
    assert set(gbc.RED_OUTCOMES) == {"failed", "error"}


def test_a_scene_that_reaches_nothing_is_named_not_clean():
    verdict, why = gbc.classify_test(baseline_outcome="passed", reached=[],
                                     red_under=[], vanished_under=[],
                                     unforceable_reached=[])
    assert verdict == gbc.VERDICT_NOT_REACHED and "ни одного решения" in why


def test_vanishing_under_force_is_named_in_the_detail_not_counted_as_a_kill():
    """Урок #465: в дифференциальном замере тест, ставший `skipped`, не краснеет
    и не проходит — он ИСЧЕЗАЕТ. Исчезновение НЕ засчитывается в убийство."""
    verdict, why = gbc.classify_test(baseline_outcome="passed", reached=["a"],
                                     red_under=[], vanished_under=["a"],
                                     unforceable_reached=[])
    assert verdict == gbc.VERDICT_GREEN_BY_CONSTRUCTION
    assert "ИСЧЕЗАЕТ" in why


def test_summarise_counts_every_verdict_including_the_empty_ones():
    counts = gbc.summarise([{"verdict": gbc.VERDICT_SENSITIVE}])
    assert counts[gbc.VERDICT_SENSITIVE] == 1
    assert counts[gbc.VERDICT_GREEN_BY_CONSTRUCTION] == 0
    assert set(counts) >= {gbc.VERDICT_SENSITIVE, gbc.VERDICT_GREEN_BY_CONSTRUCTION,
                           gbc.VERDICT_NOT_REACHED, gbc.VERDICT_UNMEASURED}


# ── 3. ЦЕЛЫЙ КОНТУР: настоящий прогон на одноразовом мини-репозитории ────────

_MINI_INSTRUMENT = textwrap.dedent('''\
    """Мини-прибор контура: одна проба, три решения."""


    def _probe_agree(left, right):
        if left is None or right is None:
            return "unmeasured", "нечего сверять"
        if left == right:
            return "satisfied", "сошлись"
        return "not_satisfied", "разошлись"
    ''')

_MINI_TESTS = textwrap.dedent('''\
    import instr


    def test_sensitive_reads_the_verdict():
        assert instr._probe_agree("a", "a")[0] == "satisfied"


    def test_green_by_construction_asserts_nothing_the_decisions_can_move():
        verdict, detail = instr._probe_agree("a", "a")
        assert isinstance(verdict, str) and isinstance(detail, str)


    def test_scene_never_calls_the_instrument():
        assert 2 + 2 == 4


    def test_reads_only_the_source_never_the_decisions():
        # Решения не вычисляет ВОВСЕ, но от принуждения краснеет: строка пропала.
        # Инструментовка её сохраняет (оборачивается условие целиком).
        with open(instr.__file__, encoding="utf-8") as fh:
            assert "left == right" in fh.read()


    def test_vanishes_instead_of_reddening_when_the_probe_refuses():
        import pytest
        verdict, _ = instr._probe_agree("a", "a")
        if verdict != "satisfied":
            pytest.skip("предпосылка не обеспечена")
        assert verdict == "satisfied"
    ''')


def _mini_repo(tmp_path: Path) -> Path:
    root = tmp_path / "mini"
    root.mkdir()
    (root / "instr.py").write_text(_MINI_INSTRUMENT, encoding="utf-8")
    (root / "test_mini.py").write_text(_MINI_TESTS, encoding="utf-8")
    return root


def _contour(root: Path, workdir: Path) -> dict:
    return gbc.run_differential(root, instrument="instr.py", module="instr",
                                func_prefix="_probe_",
                                test_files=["test_mini.py"], workers=1,
                                timeout=300, workdir=workdir)


def _verdicts(doc: dict) -> dict:
    return {row["nodeid"].rsplit("::", 1)[-1]: row["verdict"]
            for row in doc.get("rows") or ()}


@pytest.fixture(scope="module")
def contour(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gbc_contour")
    doc = _contour(_mini_repo(tmp), tmp / "work")
    return doc


def test_whole_contour_separates_the_three_outcomes(contour):
    assert contour["status"] == "OK", contour.get("reason")
    got = _verdicts(contour)
    assert got["test_sensitive_reads_the_verdict"] == gbc.VERDICT_SENSITIVE, got
    assert got["test_green_by_construction_asserts_nothing_the_decisions_can_move"] \
        == gbc.VERDICT_GREEN_BY_CONSTRUCTION, got
    assert got["test_scene_never_calls_the_instrument"] == gbc.VERDICT_NOT_REACHED, got


def test_a_test_reddened_by_the_edit_but_reaching_nothing_is_NOT_a_subject(contour):
    """Положительный контроль приписывания: краснота под принуждением сама по себе
    НЕ делает тест наблюдателем решения. Этот тест читает ИСХОДНИК прибора и от
    правки краснеет, но ни одного решения не вычисляет — записать его в
    `sensitive` значило бы зачесть чужую красноту в защиту."""
    got = _verdicts(contour)
    assert got["test_reads_only_the_source_never_the_decisions"] == \
        gbc.VERDICT_NOT_REACHED, got


def test_a_test_that_VANISHES_under_force_is_named_so_and_not_counted_as_a_kill(contour):
    row = [r for r in contour["rows"]
           if r["nodeid"].endswith("test_vanishes_instead_of_reddening_when_the_probe_refuses")][0]
    assert row["verdict"] == gbc.VERDICT_GREEN_BY_CONSTRUCTION, row
    assert row["vanished_under"], row
    assert "ИСЧЕЗАЕТ" in row["detail"], row


def test_every_reached_decision_is_forced_in_BOTH_directions(contour):
    """Одна сторона — половина замера: решение, принуждённое только к тому
    значению, которое оно и так приняло, не способно уронить ни один тест, и
    «не покраснел» перестало бы что-либо значить."""
    assert contour["forced_runs"] == 2 * contour["decisions_reached"], contour


def test_the_producer_DECLARES_its_population_as_a_field(contour):
    """Поле пишет ПРОИЗВОДИТЕЛЬ, и проверяется это у него, а не у заглушки:
    «зелёных по построению 1» без объявленного населения прочлось бы как «во всём
    наборе один», тогда как ступень меряет один файл проб."""
    assert contour["stage_population"] == contour["test_files"], contour
    assert contour["stage_population"] == ["test_mini.py"], contour


def test_contour_noise_control_is_clean_on_an_instrument_that_reads_no_source(contour):
    noise = contour["noise_control"]
    assert noise["diverged"] == [] and noise["lost"] == [], noise
    assert noise["base_tests"] == 5, noise


def test_broken_link_reach__without_the_recorder_every_scene_looks_ineligible(
        tmp_path, monkeypatch):
    """Порванное звено 1: запись достижимости. Без неё перепись объявила бы
    КАЖДЫЙ тест «вне населения» — молчаливый ноль вместо находки."""
    monkeypatch.setattr(gbc, "instrument_source", lambda src, dec: src)
    doc = _contour(_mini_repo(tmp_path), tmp_path / "work")
    got = _verdicts(doc)
    assert set(got.values()) <= {gbc.VERDICT_NOT_REACHED, gbc.VERDICT_UNMEASURED}, got
    assert got["test_green_by_construction_asserts_nothing_the_decisions_can_move"] \
        == gbc.VERDICT_NOT_REACHED, got
    assert got["test_sensitive_reads_the_verdict"] == gbc.VERDICT_NOT_REACHED, got


def test_broken_link_force__without_the_forcing_the_sensitive_test_looks_vacuous(
        tmp_path, monkeypatch):
    """Порванное звено 2: принуждение. Если правка не доезжает до копии, зелёный
    теста перестаёт что-либо значить, и честный тест попадает в находки."""
    monkeypatch.setattr(gbc, "force_source", lambda src, dec, value: src)
    doc = _contour(_mini_repo(tmp_path), tmp_path / "work")
    got = _verdicts(doc)
    assert got["test_sensitive_reads_the_verdict"] == \
        gbc.VERDICT_GREEN_BY_CONSTRUCTION, got


def test_broken_link_noise__an_instrumentation_that_changes_behaviour_is_caught(
        tmp_path, monkeypatch):
    """Порванное звено 3: контроль шума. Инструментовка, меняющая поведение,
    обязана выйти в `unmeasured`, а не раствориться в населении."""
    def _poison(src, decisions):
        return src.replace('return "satisfied", "сошлись"',
                           'return "not_satisfied", "шум"') \
            + gbc._RECORDER_SRC
    monkeypatch.setattr(gbc, "instrument_source", _poison)
    doc = _contour(_mini_repo(tmp_path), tmp_path / "work")
    got = _verdicts(doc)
    assert got["test_sensitive_reads_the_verdict"] == gbc.VERDICT_UNMEASURED, got
    assert "test_sensitive_reads_the_verdict" in \
        " ".join(doc["noise_control"]["diverged"]), doc["noise_control"]


def test_an_absent_instrument_is_unmeasured_not_an_empty_clean_run(tmp_path):
    doc = gbc.run_differential(tmp_path, instrument="нет-такого.py",
                               module="instr", test_files=["test_mini.py"],
                               workers=1, workdir=tmp_path / "w")
    assert doc["status"] == "UNMEASURED" and "прибора нет" in doc["reason"]


def test_a_population_without_tests_is_unmeasured_not_zero_findings(tmp_path):
    root = _mini_repo(tmp_path)
    doc = gbc.run_differential(root, instrument="instr.py", module="instr",
                               test_files=[], workers=1, workdir=tmp_path / "w")
    assert doc["status"] == "UNMEASURED" and "ни одного теста" in doc["reason"]


def test_report_of_an_unmeasured_run_says_so_and_names_the_reason():
    lines = gbc.report({"status": "UNMEASURED", "reason": "дверь молчит"})
    assert lines and lines[0].startswith("НЕ ИЗМЕРЕНО") and "дверь молчит" in lines[0]


def test_exit_code_tells_the_three_outcomes_apart(tmp_path, monkeypatch):
    """Код возврата читает скрипт цикла, и три исхода обязаны быть различимы
    ИМЕННО там (инв. #17): 0 — измерено и находок нет, 1 — находки,
    2 — не измерено."""
    calls = {}

    def _fake(root, **kw):
        return calls["doc"]
    monkeypatch.setattr(gbc, "run_differential", _fake)

    calls["doc"] = {"status": "UNMEASURED", "reason": "дверь молчит"}
    assert gbc.main(["--no-write"]) == 2

    calls["doc"] = {"status": "OK", "counts": {gbc.VERDICT_SENSITIVE: 3},
                    "rows": [], "test_files": []}
    assert gbc.main(["--no-write"]) == 0

    calls["doc"] = {"status": "OK",
                    "counts": {gbc.VERDICT_GREEN_BY_CONSTRUCTION: 1},
                    "rows": [], "test_files": []}
    assert gbc.main(["--no-write"]) == 1

    calls["doc"] = {"status": "OK", "rows": [], "test_files": []}   # поля нет
    assert gbc.main(["--no-write"]) == 2


# ── 4. ступень моста: такт и урезанное население ────────────────────────────

def _stamp(path: Path, iso: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"generated_at": "%s", "status": "OK"}' % iso, encoding="utf-8")


def test_inside_the_tact_the_stage_does_NOT_measure_and_says_so(tmp_path,
                                                                monkeypatch):
    """«Не мерили» и «измерено» — РАЗНЫЕ исходы (инв. #17): внутри такта ноль
    находок был бы утверждением о населении, которого никто не смотрел."""
    called = []
    monkeypatch.setattr(gbc, "run_differential",
                        lambda *a, **kw: called.append(1) or {"status": "OK"})
    art = tmp_path / "data" / gbc.ARTIFACT
    _stamp(art, "2026-10-03T00:00:00+00:00")
    import datetime as dt
    out = gbc.run(tmp_path, dest=art, write=False,
                  now=dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc))
    assert out["measured"] is False and "прошло" in out["reason"], out
    assert called == [], "внутри такта прибор звать не должны"


def test_when_the_tact_is_over_the_stage_measures_its_DECLARED_population(
        tmp_path, monkeypatch):
    seen = {}

    def _fake(root, **kw):
        seen.update(kw)
        return {"status": "OK", "counts": {}}
    monkeypatch.setattr(gbc, "run_differential", _fake)
    art = tmp_path / "data" / gbc.ARTIFACT
    _stamp(art, "2026-09-01T00:00:00+00:00")
    import datetime as dt
    out = gbc.run(tmp_path, dest=art, write=False,
                  now=dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc))
    assert out["measured"] is True, out
    assert seen["test_files"] == list(gbc.STAGE_TEST_FILES), seen


def test_an_absent_artifact_means_MEASURE_not_skip(tmp_path, monkeypatch):
    """Артефакта нет ⇒ ПОРА. «Не смогли прочитать, когда мерили» не имеет
    права означать «мерили недавно»."""
    monkeypatch.setattr(gbc, "run_differential",
                        lambda root, **kw: {"status": "OK", "counts": {}})
    out = gbc.run(tmp_path, dest=tmp_path / "data" / gbc.ARTIFACT, write=False)
    assert out["measured"] is True, out


def test_the_office_rendering_names_the_subject_and_delegates_to_the_producer():
    lines = gbc.format_report({"status": "UNMEASURED", "reason": "дверь молчит"})
    assert lines[0].startswith("—") and "ПО ПОСТРОЕНИЮ" in lines[0]
    assert any("НЕ ИЗМЕРЕНО" in line for line in lines[1:]), lines


def test_discover_names_only_files_that_mention_the_instrument(tmp_path):
    root = tmp_path / "r"
    (root / "spa_core" / "tests").mkdir(parents=True)
    (root / "spa_core" / "tests" / "test_a.py").write_text(
        "import spa_core.monitoring.card_acceptance\n", encoding="utf-8")
    (root / "spa_core" / "tests" / "test_b.py").write_text("x = 1\n", encoding="utf-8")
    got = gbc.discover_test_files(root, gbc.DEFAULT_MODULE, "spa_core/tests")
    assert got == ["spa_core/tests/test_a.py"], got
