"""Проводка сторожей пушера: ветка → ДВЕРЬ → проверка. Одна реализация на всех.

**Зачем отдельный модуль.** Три файла тестов независимо спрашивали ТЕКСТ ветки
`guard_overwrite` на литерал `guard_entry_loss` — каждый своей строкой. Пока
проверка записей вызывалась из ветки напрямую, три копии совпадали; как только
у пушера появилась вторая охраняемая единица смысла (раздел `.claude/rules/*.md`,
подъём #467) и ветки стали звать ОДНУ дверь `guard_content_loss`, все три
покраснели на верном коде — по причине, к предмету каждого из них отношения не
имеющей. Три копии одного вопроса — три места, где его чинят по-разному.

**Что здесь измеряется.** Ровно два звена, и оба ФОРМОЙ ВЫЗОВА, а не наличием
имени:

1. ветка зовёт дверь — в тексте ветки есть `<дверь>(`;
2. дверь доказанно ведёт к проверке — у `ast`-разбора тела двери среди вызовов
   есть нужное имя.

Второе звено меряется разбором намеренно. Первая редакция искала подстроку в
теле диспетчера и была УКРАШЕНИЕМ: мутация «убрать вызов из диспетчера» прошла
ЗЕЛЁНОЙ, потому что имя осталось в его же docstring (``:func:`guard_entry_loss```).
Проза — не вызов.
"""
import ast
from pathlib import Path

PUSHER = Path(__file__).resolve().parents[2] / "push_to_github.py"

#: Двери, любая из которых считается вызовом проверки из ветки.
DOORS = ("guard_content_loss", "guard_entry_loss", "guard_rules_section_loss")


def calls_of(func_name: str, source: str = None) -> set:
    """Имена функций, ВЫЗЫВАЕМЫХ внутри `func_name` пушера (по AST, не по тексту)."""
    tree = ast.parse(source if source is not None
                     else PUSHER.read_text(encoding="utf-8"))
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == func_name), None)
    if node is None:
        raise AssertionError(f"функции `{func_name}` в пушере больше нет")
    return {c.func.id for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}


def branch_of(state: str, source: str = None) -> str:
    """Текст ветки `guard_overwrite` по имени состояния расхождения."""
    src = source if source is not None else PUSHER.read_text(encoding="utf-8")
    if state == "DIVERGENCE_SAFE":
        return src.split("if state == DIVERGENCE_SAFE:")[1].split(
            "if state == DIVERGENCE_UNMEASURED")[0]
    if state == "DIVERGENCE_UNMEASURED":
        return src.split("DIVERGENCE_UNMEASURED:")[1].split("# DIVERGENCE_DIVERGED")[0]
    raise AssertionError(f"неизвестная ветка {state}")


def assert_branch_reaches(fragment: str, target: str, where: str) -> None:
    """Ветка зовёт дверь, и дверь доказанно доходит до `target`. Иначе — падение."""
    doors = [d for d in DOORS if f"{d}(" in fragment]
    assert doors, (
        f"{where}: ни одна из дверей {DOORS} не ВЫЗВАНА — проверка `{target}` "
        f"до этой ветки не доходит")
    if target in doors:
        return
    for door in doors:
        if target in calls_of(door):
            return
    raise AssertionError(
        f"{where}: дверь(и) {doors} вызваны, но ни одна не зовёт `{target}` — "
        f"точка встраивания цела, а ЦЕПОЧКА оборвана: сторож остался в коде и "
        f"перестал существовать у двери")
