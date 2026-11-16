"""Контроли прибора «упомянут ≠ приписан» — в ОБЕ стороны, на настоящем приборе.

# LLM_FORBIDDEN

Главный контроль здесь ДИФФЕРЕНЦИАЛЬНЫЙ, и он же есть доказательство, что
класс существует отдельно от соседей: на двух сценах из почти одних байтов
единственное упоминание субъекта меняется с `x_monitor` на `x_monitors` — то
есть остаётся НАСТОЯЩИМ кодом, прозой не становится и комментарием тоже.
`_mention_wiring` (ADR-1027) отвечает `REACHABLE` на ОБЕИХ (он слеп по
построению), `_call_wiring` (ADR-1028) — `CALLED` на ОБЕИХ (касание корня
dotted-цепочки ему достаточно), а этот прибор — `ATTRIBUTED` и `AMBIGUOUS`.

Каждая сцена — одноразовое дерево в `tmp_path`; живое дерево не читается и не
пишется. Пол непустоты поверхности сдвигается явно (`min_subjects=1`).

# FROZEN-DATE-OK: нет ни одной литеральной даты — вопрос прибора не о свежести
"""
from __future__ import annotations

import pathlib

import pytest

from spa_core.tests import _mention_wiring as mw
from spa_core.tests import _name_prefix_axis as npa

SUBJ_DIR = "spa_core/monitoring"
SUBJECT = "x_monitor"
SUBJ_REL = f"{SUBJ_DIR}/{SUBJECT}.py"
ENTRY = '\n\ndef main():\n    return 0\n'


def _write(root: pathlib.Path, rel: str, body: str) -> pathlib.Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _scene(root: pathlib.Path, *, mentioner_body: str,
           mentioner: str = "scripts/caller.py",
           extra: dict | None = None) -> dict:
    """Дерево из субъекта, упоминающего и одного стороннего корня."""
    _write(root, SUBJ_REL, f'"""{SUBJECT}."""{ENTRY}')
    _write(root, mentioner, mentioner_body)
    _write(root, "scripts/unrelated_root.sh", "#!/bin/bash\necho hi\n")
    for rel, body in (extra or {}).items():
        _write(root, rel, body)
    return npa.measure(root, min_subjects=1)


def _verdict(rep: dict) -> str:
    return rep["status"][SUBJ_REL]


def _row(rep: dict) -> dict:
    return next(r for r in rep["rows"] if r["module"] == SUBJ_REL)


# ── ДИФФЕРЕНЦИАЛЬНЫЙ КОНТРОЛЬ: ось отдельна от обоих соседей ────────────────

_USE_EXACT = ("from spa_core.monitoring import x_monitor\n"
              "\n\ndef go():\n    return x_monitor.main()\n")
#: Те же байты, но имя ДЛИННЕЕ на один символ: упоминается ДРУГОЙ объект.
_USE_GLUED = ("from spa_core.monitoring import x_monitors\n"
              "\n\ndef go():\n    return x_monitors.main()\n")


def test_lengthening_the_mentioned_name_by_one_char_flips_only_this_axis(tmp_path):
    """Склейка — предмет класса, и соседи её НЕ видят. Это и есть доказательство."""
    exact, glued = tmp_path / "exact", tmp_path / "glued"
    rep_exact = _scene(exact, mentioner_body=_USE_EXACT)
    rep_glued = _scene(glued, mentioner_body=_USE_GLUED)

    assert _verdict(rep_exact) == npa.ATTRIBUTED, "целый контур обязан быть ATTRIBUTED"
    assert _verdict(rep_glued) == npa.AMBIGUOUS, (
        "звено «границы идентификатора»: `x_monitors` субъекта `x_monitor` НЕ называет")

    old_exact = mw.measure(exact, min_subjects=1)
    old_glued = mw.measure(glued, min_subjects=1)
    assert old_exact["status"][SUBJ_REL] == mw.REACHABLE
    assert old_glued["status"][SUBJ_REL] == mw.REACHABLE, (
        "ЕСЛИ сосед здесь покраснел — дверь уже закрыта и этот прибор не о ней; "
        "вердикт обязан остаться REACHABLE")


def test_the_glued_scene_is_code_not_prose(tmp_path):
    """Контроль на подстроку: склейка не снимается ни одним стриппером.

    Если бы сцена работала прозой, её поймали бы прежние ужесточения храповика,
    и прибор был бы не нужен. Поэтому текст сцены обязан ОСТАТЬСЯ в сканe.
    """
    rep = _scene(tmp_path, mentioner_body=_USE_GLUED)
    row = _row(rep)
    assert row["grades"][npa.GLUED] > 0, (
        "звено «текст доехал до скана»: приклеенных вхождений ноль — значит "
        "стриппер срезал сцену, и прибор мерил пустоту")
    assert row["grades"][npa.QUALIFIED] == 0
    assert row["grades"][npa.BARE] == 0


# ── КОНТРОЛИ НА КАЖДУЮ СТЕПЕНЬ ПРИПИСЫВАЕМОСТИ, звено НАЗВАНО ───────────────

def test_a_bare_mention_with_a_unique_stem_is_attributed(tmp_path):
    """Звено «уникальность стема»: голое имя приписываемо, пока омонима нет."""
    rep = _scene(tmp_path, mentioner_body='LABEL = "x_monitor"\n')
    row = _row(rep)
    assert row["grades"][npa.BARE] == 1, "голое вхождение обязано быть ровно одно"
    assert row["stem_unique"] is True
    assert _verdict(rep) == npa.ATTRIBUTED


def test_the_same_bare_mention_becomes_ambiguous_once_a_homonym_exists(tmp_path):
    """То же вхождение, ОДИН добавленный файл-омоним — вердикт обязан перевернуться."""
    alone = _scene(tmp_path / "alone", mentioner_body='LABEL = "x_monitor"\n')
    with_hom = _scene(
        tmp_path / "hom", mentioner_body='LABEL = "x_monitor"\n',
        extra={f"spa_core/analytics/{SUBJECT}.py": '"""омоним."""\n'})
    assert _verdict(alone) == npa.ATTRIBUTED
    assert _verdict(with_hom) == npa.AMBIGUOUS, (
        "звено «омоним базового имени»: голое имя двух файлов не различает")
    assert _row(with_hom)["homonyms"] == [f"spa_core/analytics/{SUBJECT}.py"]


def test_a_qualified_mention_survives_a_homonym(tmp_path):
    """Звено «квалифицированная форма»: каталог в ссылке снимает двусмысленность."""
    rep = _scene(
        tmp_path, mentioner_body=_USE_EXACT,
        extra={f"spa_core/analytics/{SUBJECT}.py": '"""омоним."""\n'})
    row = _row(rep)
    assert row["stem_unique"] is False, "сцена обязана нести омоним"
    assert row["grades"][npa.QUALIFIED] > 0
    assert _verdict(rep) == npa.ATTRIBUTED


def test_a_path_literal_is_a_qualified_mention(tmp_path):
    """Вторая квалифицированная форма — путь-литерал, а не только dotted."""
    rep = _scene(
        tmp_path, mentioner_body='TARGET = "spa_core/monitoring/x_monitor.py"\n',
        extra={f"spa_core/analytics/{SUBJECT}.py": '"""омоним."""\n'})
    assert _row(rep)["grades"][npa.QUALIFIED] > 0
    assert _verdict(rep) == npa.ATTRIBUTED


def test_a_subject_nobody_mentions_is_CENSUS_not_AMBIGUOUS(tmp_path):
    """Третий исход: «не упоминает никто» уже на учёте храповика — не предмет."""
    rep = _scene(tmp_path, mentioner_body='LABEL = "something else"\n')
    assert _verdict(rep) == npa.CENSUS, (
        "звено «ноль упоминаний»: CENSUS и AMBIGUOUS — РАЗНЫЕ исходы, и смешать "
        "их значило бы вписать в класс чужое население")
    assert SUBJ_REL not in rep["ambiguous"]


# ── ОСЬ ПАР: ни достаточна, ни необходима — и это ЗАМЕР ─────────────────────

def test_the_pair_relation_is_not_sufficient(tmp_path):
    """Пара есть, а субъект приписан: быть в паре и быть слепым — разные вещи."""
    rep = _scene(
        tmp_path, mentioner_body=_USE_EXACT,
        extra={f"{SUBJ_DIR}/{SUBJECT}s.py": f'"""сосед."""{ENTRY}'})
    assert rep["pairs"], "сцена обязана нести пару (стем A ⊂ имя B)"
    assert SUBJ_REL in rep["pair_members"]
    assert _verdict(rep) == npa.ATTRIBUTED, (
        "звено «пара ≠ слепота»: у субъекта есть квалифицированное упоминание")
    assert SUBJ_REL not in rep["pair_members_ambiguous"]


def test_the_pair_relation_is_not_necessary(tmp_path):
    """Слепота без пары: склеивает ИМЯ ДАННЫХ, а не имя субъекта."""
    rep = _scene(tmp_path, mentioner_body='P = "data/x_monitors.json"\n')
    assert rep["pairs"] == [], "в сцене нет второго субъекта — пар быть не должно"
    assert _verdict(rep) == npa.AMBIGUOUS
    assert rep["ambiguous_outside_pairs"] == [SUBJ_REL], (
        "звено «слепой вне пар»: ось пар этого члена не нашла бы вовсе")


# ── ТРЕТИЙ ИСХОД (инв. #17): НЕ ИЗМЕРЕНО отличимо от нуля находок ───────────

def test_a_thin_surface_is_unmeasured_not_zero(tmp_path):
    """Пол непустоты: «членов нет» не имеет права значить «мерить было нечем»."""
    _write(tmp_path, SUBJ_REL, f'"""{SUBJECT}."""{ENTRY}')
    with pytest.raises(npa.Unmeasured) as exc:
        npa.measure(tmp_path)
    assert "субъектов всего" in str(exc.value)


def test_an_empty_scan_surface_is_unmeasured_not_zero(tmp_path):
    """Нет ни одного `.py` в поверхности ⇒ «омонимов нет» мерить нечем."""
    with pytest.raises(npa.Unmeasured):
        npa.stem_population(tmp_path)


def test_an_unreadable_surface_file_is_unmeasured(tmp_path, monkeypatch):
    """Нечитаемый файл поверхности поднимается наверх соседом, а не глотается."""
    def boom(root):
        raise mw.Unmeasured("файл поверхности скана не прочитан: X")
    monkeypatch.setattr(mw, "tree_texts", boom)
    _write(tmp_path, SUBJ_REL, f'"""{SUBJECT}."""{ENTRY}')
    _write(tmp_path, "scripts/caller.py", _USE_EXACT)
    with pytest.raises(npa.Unmeasured) as exc:
        npa.measure(tmp_path, min_subjects=1)
    assert "не прочитан" in str(exc.value)


def test_the_cli_distinguishes_all_three_outcomes(tmp_path, capsys):
    """Коды возврата: 0 — ноль членов · 1 — находка · 2 — НЕ ИЗМЕРЕНО."""
    clean = tmp_path / "clean"
    _write(clean, SUBJ_REL, f'"""{SUBJECT}."""{ENTRY}')
    _write(clean, "scripts/caller.py", _USE_EXACT)
    _write(clean, "scripts/unrelated_root.sh", "#!/bin/bash\n")
    monkey = npa.MIN_SUBJECTS

    # 2 — НЕ ИЗМЕРЕНО: тонкая поверхность (пол не сдвинут)
    assert npa.main(["--root", str(clean)]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err
    assert monkey == npa.MIN_SUBJECTS, "прибор не имеет права менять свой пол"


def test_the_zero_is_printed_as_a_line_not_as_silence(tmp_path):
    """Ноль членов обязан быть НАПЕЧАТАН: молчание читалось бы как «не мерили»."""
    rep = _scene(tmp_path, mentioner_body=_USE_EXACT)
    assert rep["ambiguous"] == []
    lines = "\n".join(npa.report(rep))
    assert "ДВУСМЫСЛЕННЫХ 0 — это ЗАМЕР, а не молчание" in lines


def test_the_floor_is_declared_in_the_document(tmp_path):
    """Знак ошибки объявлен МАШИНОЧИТАЕМО, а не только прозой модуля."""
    rep = _scene(tmp_path, mentioner_body=_USE_EXACT)
    assert rep["floor_not_ceiling"] is True
    assert "ПОЛ класса" in "\n".join(npa.report(rep))


def test_the_rule_of_mention_has_no_second_copy():
    """Поверхность, субъекты и стрипперы берутся у СОСЕДА, своей копии нет."""
    assert npa.SCAN_SUBDIRS is mw.SCAN_SUBDIRS
    assert npa.MIN_SUBJECTS == mw.MIN_SUBJECTS
    src = pathlib.Path(npa.__file__).read_text(encoding="utf-8")
    for forbidden in ("_code_only", "_without_test_paths", "has_entrypoint"):
        assert forbidden not in src, (
            f"звено «одно правило — одна копия»: {forbidden} переписан здесь "
            "вместо того, чтобы быть взятым у соседа")


def test_two_subjects_with_the_SAME_stem_are_not_a_prefix_pair(tmp_path):
    """Страж равных стемов: омоним — ДРУГАЯ ось, и смешать их нельзя.

    Без этого стража `policy.py` в трёх каталогах дал бы шесть «пар», и ось
    пар доложила бы о населении, которого у неё нет: подстрока имени там
    совпадает ЦЕЛИКОМ, а это уже вопрос омонима (`homonym_candidates`).
    """
    rep = _scene(
        tmp_path, mentioner_body=_USE_EXACT,
        extra={f"spa_core/governance/{SUBJECT}.py": f'"""омоним."""{ENTRY}'})
    assert f"spa_core/governance/{SUBJECT}.py" in rep["status"], (
        "сцена обязана нести ВТОРОГО субъекта с тем же стемом")
    assert rep["pairs"] == [], (
        "звено «страж равных стемов»: совпадение стема целиком парой не является")
    assert SUBJ_REL in rep["homonym_candidates"], (
        "та же сцена обязана попасть в ось ОМОНИМА — у неё и спрашивают")


def test_a_subject_cannot_attribute_a_mention_to_ITSELF(tmp_path):
    """Файл сам себе упоминанием не является — то же правило, что у храповика.

    Без этого звена модуль, назвавший свой собственный путь в собственном теле
    (а так делает почти каждый писатель артефакта), выходил бы `ATTRIBUTED` на
    своём же тексте — fail-OPEN тише красного теста.
    """
    self_qualified = (f'"""{SUBJECT}."""\nTARGET = "{SUBJ_DIR}/{SUBJECT}.py"'
                      f'\nNAME = "{SUBJECT}"{ENTRY}')
    _write(tmp_path, SUBJ_REL, self_qualified)
    _write(tmp_path, "scripts/caller.py", f'P = "data/{SUBJECT}s.json"\n')
    _write(tmp_path, "scripts/unrelated_root.sh", "#!/bin/bash\n")
    rep = npa.measure(tmp_path, min_subjects=1)
    row = _row(rep)
    assert row["grades"][npa.QUALIFIED] == 0, (
        "звено «сам себе не упоминание»: квалифицированная ссылка субъекта на "
        "СЕБЯ засчитана как проводка")
    assert row["grades"][npa.BARE] == 0
    assert _verdict(rep) == npa.AMBIGUOUS


def test_evidence_quality_is_a_separate_question_from_the_verdict(tmp_path):
    """Храповик бывает ПРАВ о проводке и неправ о причине — это ДВА вопроса.

    Сцена несёт одно квалифицированное вхождение и три приклеенных: вердикт
    обязан быть `ATTRIBUTED`, а доля приписываемого доказательства — меньше
    половины, то есть субъект попадает в `majority_unattributable` НЕ будучи
    членом класса.
    """
    body = (_USE_EXACT
            + 'A = "x_monitors"\nB = "x_monitors"\nC = "x_monitors"\n')
    rep = _scene(tmp_path, mentioner_body=body)
    row = _row(rep)
    assert _verdict(rep) == npa.ATTRIBUTED, "проводка цела — вердикт верен"
    assert row["grades"][npa.GLUED] == 3
    assert rep["evidence_attributable_share"] < 0.5
    assert SUBJ_REL in rep["majority_unattributable"], (
        "звено «качество ≠ вердикт»: субъект с негодным большинством обязан "
        "быть НАЗВАН, оставаясь приписанным")
    assert SUBJ_REL not in rep["ambiguous"]


def test_zero_occurrences_make_the_share_unmeasured_not_zero(tmp_path):
    """Доля на пустом знаменателе — НЕ ноль, а `None` с печатью причины (инв. #17).

    Ноль здесь читался бы как «ничего не приписывается», то есть как худший
    возможный результат вместо «мерить было нечего».
    """
    _write(tmp_path, SUBJ_REL, f'"""{SUBJECT}."""{ENTRY}')
    _write(tmp_path, f"{SUBJ_DIR}/other_guard.py", '"""другой."""' + ENTRY)
    _write(tmp_path, "scripts/unrelated_root.sh", "#!/bin/bash\n")
    rep = npa.measure(tmp_path, min_subjects=1)
    assert rep["evidence_total"] == 0
    assert rep["evidence_attributable_share"] is None, (
        "звено «пустой знаменатель»: доля обязана быть None, а не 0.0")
    assert "НЕ ИЗМЕРЕНО: вхождений ноль" in "\n".join(npa.report(rep))
    assert rep["majority_unattributable"] == []
