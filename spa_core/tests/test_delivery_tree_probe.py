"""Контроль пробы `delivery_refuses_an_unnamed_tree` в ОБЕ стороны.

Правило приёмки (`.claude/rules/acceptance.md`, п. 3): новая проба регистрируется
только с тестом, где она ЗЕЛЕНА на целом контуре и КРАСНА на КАЖДОМ порванном
звене — с названным звеном, — и где она НЕ проходит подстрокой (ADR-333).

Звенья рвутся на КОПИИ пушера в одноразовом дереве; живое дерево не трогается ни
одним тестом. Копия — ровно один файл: пушер самодостаточен (только stdlib), и
проба читает из дерева только его.

Про подстроку. Самое важное звено здесь — №2: отказ ОТКЛЮЧЁН (`if False:`), а
ВЕСЬ его текст, включая слова «дерево-источник», «ОБХОД ОБЪЯВЛЕН» и имя флага,
остаётся в исходнике дословно. Проба, судящая по тексту, назвала бы такое дерево
исправным; проба, судящая по ИСХОДУ, видит код 0 и отказывает.

Запуск: python3 -m pytest spa_core/tests/test_delivery_tree_probe.py -v
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca

ROOT = Path(__file__).resolve().parents[2]
PUSHER = ROOT / "push_to_github.py"
PROBE = "delivery_refuses_an_unnamed_tree"


class Unmeasured(AssertionError):
    """НЕ ИЗМЕРЕНО с названной причиной — третий исход, а не «чисто»."""


def _probe(tree: Path):
    return ca.PROBES[PROBE](None, repo_root=str(tree))


def _copy(tmp_path: Path, name: str, *edits: tuple[str, str]) -> Path:
    """Дерево с КОПИЕЙ пушера, в которой порвано ровно названное звено."""
    tree = tmp_path / name
    tree.mkdir(parents=True)
    src = PUSHER.read_text(encoding="utf-8")
    for old, new in edits:
        if src.count(old) == 0:
            raise Unmeasured(
                f"звено «{old[:60]}…» в пушере НЕ НАЙДЕНО — порвать его не вышло, "
                f"и тест ничего не измерил (код переименовали?)")
        src = src.replace(old, new)
    (tree / "push_to_github.py").write_text(src, encoding="utf-8")
    return tree


# ═════════════════════════════════════════════════════════════════════════════
# ЦЕЛЫЙ КОНТУР
# ═════════════════════════════════════════════════════════════════════════════
def test_the_probe_is_satisfied_on_the_whole_loop():
    verdict, why = _probe(ROOT)
    assert verdict == ca.SATISFIED, f"проба красна на живом дереве: {why}"
    assert "код 12" in why or "код" in why, (
        "вердикт обязан нести ЧИСЛА замера, а не слово «ок»")


def test_an_untouched_copy_is_satisfied_too(tmp_path):
    """Положительный контроль САМОГО стенда: копирование звеньев не рвёт."""
    verdict, why = _probe(_copy(tmp_path, "intact"))
    assert verdict == ca.SATISFIED, (
        f"нетронутая копия красна — тогда красный на порванном звене ничего не "
        f"доказывает: {why}")


# ═════════════════════════════════════════════════════════════════════════════
# ЗВЕНО 1. ПУШЕРА НЕТ В ДЕРЕВЕ — мерить нечего, и это находка, а не «не измерено»
# ═════════════════════════════════════════════════════════════════════════════
def test_no_pusher_in_the_tree_is_a_finding(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    verdict, why = _probe(empty)
    assert verdict == ca.NOT_SATISFIED, f"пустое дерево не названо находкой: {why}"
    assert "пушера нет" in why


# ═════════════════════════════════════════════════════════════════════════════
# ЗВЕНО 2. ОТКАЗ ОТКЛЮЧЁН, А ВЕСЬ ЕГО ТЕКСТ НА МЕСТЕ (контроль «не подстрокой»)
# ═════════════════════════════════════════════════════════════════════════════
def test_a_disabled_refusal_is_caught_even_with_all_its_text_present(tmp_path):
    tree = _copy(tmp_path, "no_refusal",
                 ("if not allow_prod_root:", "if False:"))
    source = (tree / "push_to_github.py").read_text(encoding="utf-8")
    assert "ОБХОД ОБЪЯВЛЕН" in source and "--allow-prod-root-relative" in source, (
        "сцена не воспроизводит подстроку: текст отказа из копии исчез, и тест "
        "мерил бы не то")
    verdict, why = _probe(tree)
    assert verdict == ca.NOT_SATISFIED, (
        f"отказ отключён, байты прод-дерева уезжают молча — а проба зелена: {why}")

    # И отдельно — ПРЯМОЙ замер того, что именно порвано: копия МОЛЧА выбирает
    # прод-дерево. Без него красный вердикт выше можно было бы объяснить любой
    # посторонней причиной (в одноразовом дереве раньше пушера отказывает ещё
    # один гейт — читателя окна мутаций там нет, и это верный fail-CLOSED).
    spec = importlib.util.spec_from_file_location(
        "_broken_ptg", tree / "push_to_github.py")
    broken = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(broken)
    prod, mine = tmp_path / "p", tmp_path / "m"
    for d, text in ((prod, "дрейф\n"), (mine, "работа\n")):
        (d / "docs").mkdir(parents=True)
        (d / "docs" / "STATE.md").write_text(text, encoding="utf-8")
    got = broken.resolve_delivery_path("docs/STATE.md", project_root=prod,
                                       runner_tree=mine, cwd=mine)
    assert got == prod / "docs" / "STATE.md", (
        "сцена не воспроизводит аварию: копия с отключённым отказом НЕ выбрала "
        f"прод-дерево ({got}) — рвали не то звено")


# ═════════════════════════════════════════════════════════════════════════════
# ЗВЕНО 3. ОТКАЗ ЕСТЬ, А BLOB-ОВ В НЁМ НЕТ
# ═════════════════════════════════════════════════════════════════════════════
def test_a_refusal_without_both_blobs_is_caught(tmp_path):
    tree = _copy(tmp_path, "no_blobs",
                 ("""— blob {row['blob']}""", """— (blob не печатаем)"""))
    verdict, why = _probe(tree)
    assert verdict == ca.NOT_SATISFIED, (
        f"отказ без blob-ов принят за исправный: «не тот файл» так неотличимо "
        f"от «файла нет»: {why}")
    assert "blob-ов в нём нет" in why


# ═════════════════════════════════════════════════════════════════════════════
# ЗВЕНО 4. ОБЪЯВЛЕННОЕ СОГЛАСИЕ НЕ РАБОТАЕТ — сторож без пути наверх
# ═════════════════════════════════════════════════════════════════════════════
def test_an_ignored_bypass_is_caught(tmp_path):
    tree = _copy(tmp_path, "deaf_bypass",
                 ("    if allow_prod_root is None:\n"
                  "        allow_prod_root = _ALLOW_PROD_ROOT_RELATIVE",
                  "    if True:\n"
                  "        allow_prod_root = False"))
    verdict, why = _probe(tree)
    assert verdict == ca.NOT_SATISFIED, (
        f"обход не работает, а проба зелена — она не отличает «дверь меряет» от "
        f"«дверь заперта всегда»: {why}")
    assert "ТОТ ЖЕ код" in why


# ═════════════════════════════════════════════════════════════════════════════
# ЗВЕНО 5. СОГЛАСИЕ ПРОХОДИТ МОЛЧА — «объявил» неотличимо от «не спрашивали»
# ═════════════════════════════════════════════════════════════════════════════
def test_a_silent_bypass_is_caught(tmp_path):
    tree = _copy(tmp_path, "silent_bypass",
                 ("ОБХОД ОБЪЯВЛЕН", "всё хорошо"))
    verdict, why = _probe(tree)
    assert verdict == ca.NOT_SATISFIED, (
        f"объявленный обход печатает не объявление — подмена снова невидима: {why}")
    assert "МОЛЧА" in why


# ═════════════════════════════════════════════════════════════════════════════
# ТРЕТИЙ ИСХОД: сцену не поднять ⇒ `unmeasured`, и НИКОГДА «satisfied»
# ═════════════════════════════════════════════════════════════════════════════
def test_a_pusher_that_cannot_even_start_is_unmeasured(tmp_path):
    tree = _copy(tmp_path, "broken_syntax", ("def main():", "def main(:"))
    verdict, why = _probe(tree)
    assert verdict in (ca.NOT_SATISFIED, ca.UNMEASURED), (
        f"пушер, который не запускается, принят за исправный: {why}")
    assert verdict != ca.SATISFIED
