"""Храповик класса «предикат ИСЧЕЗАЕТ, когда содержимого очереди в дереве нет».

Что здесь закреплено (ADR-906, заказ G898 п. 1 по ADR-905)
------------------------------------------------------------------------------
ADR-905 измерил класс «вердикт теста есть свойство СОДЕРЖИМОГО дерева»: **15** тестов
в 13 файлах. Направления оказались РАЗНЫЕ, и четыре предмета в сцене «карточек нет»
не краснели и не проходили — они ИСЧЕЗАЛИ (`→ SKIPPED`), а глазами это читается как
«всё в порядке» (урок #465). Этот файл держит ДВА утверждения:

1. **Ни один предикат набора не исчезает по отсутствию очереди.** База — ПУСТАЯ
   (`tree_content_skip_baseline.json`), то есть любая новая такая площадка краснеет
   сразу. На `origin/main` 58dd64e7e их было ДЕСЯТЬ в семи файлах.
2. **Дверь третьего исхода ведёт себя как обещано** — отказ ГРОМКИЙ, с предметом и
   причиной, и он `AssertionError`, а не `Skipped`: контроль в обе стороны пишется
   обычным `pytest.raises`, а исход у pytest выходит `failed`.

Каждая проверка ниже — положительный контроль измеренной формы, а не выдуманной:
формы взяты с девяти настоящих площадок (`not TRACKER_DIR.exists()` ·
`not card_path.exists()` · `X not in cards` · `not tracker.is_dir()`).

Литеральных дат здесь нет: предмет — разбор исходников, календарь на него не влияет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from spa_core.tests._tree_content_observation import (
    CANON_TEST_ROOTS,
    PREFIX,
    TreeContentUnmeasured,
    measure_queue_content_skips,
    require_member,
    require_tree_content,
    unmeasured,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent / "tree_content_skip_baseline.json"


def _baseline() -> set[tuple[str, int]]:
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {(s["path"], s["line"]) for s in doc["sites"]}


# ══════════════════════════════ 1. сам храповик ══════════════════════════════

def test_no_predicate_vanishes_when_the_queue_content_is_absent() -> None:
    """База пуста ⇒ любая новая исчезающая площадка краснит дерево сразу."""
    res = measure_queue_content_skips(REPO_ROOT, CANON_TEST_ROOTS)
    assert not res["roots_missing"], (
        f"{PREFIX}: корней переписи нет в этом дереве: {res['roots_missing']} — "
        "перепись НЕ состоялась, и это не «класс пуст»")
    assert not res["unmeasured"], (
        f"{PREFIX}: файлы не разобраны: {res['unmeasured']} — "
        "перепись неполна, судить о классе нельзя")
    found = {(s["path"], s["line"]) for s in res["sites"]}
    new = found - _baseline()
    assert not new, (
        "новые ИСЧЕЗАЮЩИЕ предикаты (skip по отсутствию очереди карточек): "
        + "; ".join(f"{p}:{ln}" for p, ln in sorted(new))
        + ". Выход — spa_core/tests/_tree_content_observation.py "
          "(require_tree_content / require_member): отсутствие содержимого обязано "
          "быть ГРОМКИМ «НЕ ИЗМЕРЕНО», а не скипом (инв. #17). Дописывать базу "
          "ЗАПРЕЩЕНО (инв. #16)")


def test_the_baseline_can_only_shrink() -> None:
    """Храповик: база не имеет права вырасти относительно замера ADR-906 (ноль)."""
    assert _baseline() == set(), (
        "база класса обязана оставаться ПУСТОЙ: замер ADR-906 закрыл все девять "
        "площадок, и любая запись здесь есть дописка ради зелёного (инв. #16)")


# ═══════════════════ 2. контроль переписи в ОБЕ стороны ═══════════════════
#
# Сцена — одноразовое дерево с подставленными корнями переписи: мера обязана
# НАХОДИТЬ каждую из девяти измеренных форм и НЕ находить починенную.

_SHAPES = {
    "exists_on_tracker_dir": """
        from pathlib import Path
        import pytest
        TRACKER_DIR = Path(__file__).parent / "nimbalyst-local" / "tracker"
        def test_x():
            if not TRACKER_DIR.exists():
                pytest.skip("трекера нет в этом дереве")
            assert True
    """,
    "exists_on_a_card_path": """
        from pathlib import Path
        import pytest
        TRACKER_DIR = Path("/tmp/nimbalyst-local/tracker")
        def test_x():
            card_path = TRACKER_DIR / "own-a.md"
            if not card_path.exists():
                pytest.skip("живая карточка отсутствует в этом дереве")
            assert True
    """,
    "member_of_a_set_read_from_the_queue": """
        from pathlib import Path
        import pytest
        CARD = "inbox-a"
        def _real_cards():
            tracker = Path("/tmp") / "nimbalyst-local" / "tracker"
            return sorted(tracker.glob("*.md"))
        def test_x():
            cards = {c.stem: c for c in _real_cards()}
            if CARD not in cards:
                pytest.skip("карточки нет в этом дереве")
            assert True
    """,
    "is_dir_on_a_local_tracker_binding": """
        from pathlib import Path
        import pytest
        ROOT = Path("/tmp")
        def test_x():
            tracker = ROOT / "nimbalyst-local" / "tracker"
            if not tracker.is_dir():
                pytest.skip("трекера нет")
            assert True
    """,
    "os_path_isdir_is_a_separate_door": """
        import os
        import unittest
        _REPO = os.path.dirname(__file__)
        class T(unittest.TestCase):
            def test_x(self):
                tracker = os.path.join(_REPO, "nimbalyst-local", "tracker")
                if not os.path.isdir(tracker):
                    self.skipTest("трекера нет в этом дереве")
    """,
    "unittest_skipTest_counts_too": """
        import unittest
        from pathlib import Path
        TRACKER_DIR = Path("/tmp/nimbalyst-local/tracker")
        class T(unittest.TestCase):
            def test_x(self):
                if not TRACKER_DIR.is_dir():
                    self.skipTest("трекера нет в этом дереве")
    """,
}

_FIXED = """
    from pathlib import Path
    from spa_core.tests._tree_content_observation import require_tree_content
    TRACKER_DIR = Path(__file__).parent / "nimbalyst-local" / "tracker"
    def test_x():
        require_tree_content(TRACKER_DIR, "очередь карточек", kind="каталог")
        assert True
"""


def _scene(tmp_path: Path, name: str, body: str) -> Path:
    for rel in CANON_TEST_ROOTS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / CANON_TEST_ROOTS[0] / f"test_{name}.py").write_text(
        textwrap.dedent(body).lstrip(), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_every_measured_shape_is_found(tmp_path: Path, shape: str) -> None:
    """Положительный контроль: каждая из ДЕСЯТИ настоящих площадок находится.

    Шестая форма (`os.path.isdir`) добавлена ЗАМЕРОМ, а не догадкой: первая
    редакция меры знала только методы `Path` и потеряла площадку
    `test_acceptance_probe_writer:341` — ровно тот файл, на котором класс и был
    найден (ADR-905). 9 из 10 против 10 из 10.
    """
    res = measure_queue_content_skips(_scene(tmp_path, shape, _SHAPES[shape]),
                                      CANON_TEST_ROOTS)
    assert res["unmeasured"] == [] and res["roots_missing"] == []
    assert len(res["sites"]) == 1, f"форма {shape} не найдена: {res['sites']}"


def test_the_fixed_form_is_not_found(tmp_path: Path) -> None:
    """Обратная сторона: починенный предикат членом класса НЕ является."""
    res = measure_queue_content_skips(_scene(tmp_path, "fixed", _FIXED),
                                      CANON_TEST_ROOTS)
    assert res["sites"] == [], res["sites"]


def test_a_skip_unrelated_to_the_queue_is_not_a_member(tmp_path: Path) -> None:
    """Мера УЗКАЯ намеренно: широкая даёт 96 площадок в 71 файле (перемер #1018
    тем же словарём проб; 87 в 64 — вариант «только методы Path», ADR-906).

    Эти шесть файлов мера находила, пока предмет скипа судился по «файл где-то
    упоминает трекер», и все шесть были ЛОЖНЫМИ.
    """
    body = """
        from pathlib import Path
        import pytest
        # слово-маркер живёт в ПРОЗЕ, а предмет скипа — чужой артефакт:
        # «tracker» тут про совсем другое.
        def test_x():
            p = Path("/tmp/covariance_export.json")
            if not p.exists():
                pytest.skip("выгрузки нет")
            assert True
    """
    res = measure_queue_content_skips(_scene(tmp_path, "unrelated", body),
                                      CANON_TEST_ROOTS)
    assert res["sites"] == [], res["sites"]


def test_an_unparseable_file_is_unmeasured_never_a_clean_zero(tmp_path: Path) -> None:
    """Третий исход у самой переписи (инв. #17): «не разобрали» ≠ «класс пуст»."""
    _scene(tmp_path, "ok", _FIXED)
    (tmp_path / CANON_TEST_ROOTS[0] / "test_broken.py").write_text(
        'TRACKER = "nimbalyst-local/tracker"\nif not x.exists(\n', encoding="utf-8")
    res = measure_queue_content_skips(tmp_path, CANON_TEST_ROOTS)
    assert res["unmeasured"], "сломанный файл обязан попасть в НЕ ИЗМЕРЕНО"
    assert "не разбирается" in res["unmeasured"][0]["reason"]


def test_a_missing_census_root_is_named_never_silently_skipped(tmp_path: Path) -> None:
    """Корня нет ⇒ он НАЗВАН, а не выпал из вопроса молча."""
    (tmp_path / CANON_TEST_ROOTS[0]).mkdir(parents=True)
    res = measure_queue_content_skips(tmp_path, CANON_TEST_ROOTS)
    assert set(res["roots_missing"]) == set(CANON_TEST_ROOTS[1:]), res["roots_missing"]


# ══════════════════════ 3. контроль самой двери ══════════════════════

def test_absent_content_fails_loudly_and_is_not_a_skip(tmp_path: Path) -> None:
    """Исход — `failed`, а не `skipped`: предмет перестаёт исчезать (урок #465)."""
    with pytest.raises(TreeContentUnmeasured) as exc:
        require_tree_content(tmp_path / "нет.md", "живая карточка контроля")
    assert isinstance(exc.value, AssertionError), (
        "отказ обязан быть потомком AssertionError: иначе контроль в обе стороны "
        "пришлось бы ловить BaseException (.claude/rules/deployment.md)")
    text = str(exc.value)
    assert text.startswith(PREFIX) and "живая карточка контроля" in text
    assert "нет.md" in text, "отказ обязан называть ПУТЬ, а не только предмет"
    assert "инв. #16" in text, "отказ обязан отговаривать от возврата скипа"


def test_present_content_returns_the_path(tmp_path: Path) -> None:
    """Обратная сторона: содержимое есть ⇒ дверь молчит и отдаёт путь."""
    card = tmp_path / "own-a.md"
    card.write_text("x", encoding="utf-8")
    assert require_tree_content(card, "карточка") == card
    assert require_tree_content(tmp_path, "очередь", kind="каталог") == tmp_path


def test_a_directory_where_a_file_was_asked_is_a_named_refusal(tmp_path: Path) -> None:
    """«Нет вовсе» и «на этом месте не файл» — РАЗНЫЕ состояния дерева."""
    with pytest.raises(TreeContentUnmeasured) as exc:
        require_tree_content(tmp_path, "карточка")
    assert "не файл" in str(exc.value)


def test_a_file_where_a_directory_was_asked_is_a_named_refusal(tmp_path: Path) -> None:
    f = tmp_path / "x"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(TreeContentUnmeasured) as exc:
        require_tree_content(f, "очередь", kind="каталог")
    assert "не каталог" in str(exc.value)


def test_member_absent_from_the_read_set_is_a_named_refusal() -> None:
    with pytest.raises(TreeContentUnmeasured) as exc:
        require_member("inbox-a", {"inbox-b": 1}, "карточка разбора")
    assert "inbox-a" in str(exc.value) and "карточка разбора" in str(exc.value)
    require_member("inbox-b", {"inbox-b": 1}, "карточка разбора")  # обратная сторона


def test_a_refusal_without_a_subject_or_reason_is_a_caller_defect() -> None:
    """Отказ без предмета неотличим от отказа без причины — это дефект вызывающего."""
    with pytest.raises(ValueError):
        unmeasured("", "причина есть")
    with pytest.raises(ValueError):
        unmeasured("предмет есть", "   ")


def test_an_unknown_kind_is_a_caller_defect(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        require_tree_content(tmp_path, "очередь", kind="нечто")
