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


# ══════════════════════════════════════════════════════════════════════════════
# ПЕРЕПИСЬ КЛАССОВ ПОТЕРИ СОДЕРЖИМОГО (заказ G729 п. 3, цикл #876)
#
# Выше меряется проводка ОДНОГО названного сторожа: «ветка → дверь → вот эта
# проверка». Вопрос, которого там нет: сошёлся ли ПЕРЕЧЕНЬ классов с перечнем
# вызовов двери. Замер #876 (дифференциально, радиус 53 файла тестов пушера):
# пятый класс, дословно повторяющий контракт четырёх существующих и НИКЕМ не
# вызванный, оставляет весь радиус ЗЕЛЁНЫМ. То есть новая единица смысла,
# добавленная без вызова, остаётся сторожем, которого нет, — и об этом не
# краснеет ничего. Сам диспетчер называет эту опасность в своём docstring с
# цикла #874, но проза не есть мера.
#
# Мерится ДВУМЯ осями, и у каждой СВОЁ население — ни одна не покрывает другую:
#
#   * ось СИГНАТУРЫ — функция, несущая контракт класса (имена позиционных
#     аргументов ровно `CONTRACT_ARGS`, возврат `str`), обязана вызываться
#     ДВЕРЬЮ. Ловит класс, приколоченный мимо двери прямо в `guard_overwrite`, —
#     то есть «четвёртую реализацию», ради запрета которой дверь и заводили.
#   * ось ИМЕНИ — любая функция `guard_*_loss` обязана быть ДОСТИЖИМА из
#     `guard_overwrite` (прямо или через дверь). Ловит класс ИНОЙ формы, который
#     ось сигнатуры не видит вовсе.
#
# Третий исход назван отдельно (инв. #17): пушер не разобран · двери нет ·
# корня нет · население ПУСТО — это `Unmeasured`, а не «чисто». «Классов найдено
# ноль» есть подделка доказательства, а не зелёный ответ (урок ADR-468).
# ══════════════════════════════════════════════════════════════════════════════

#: Контракт КЛАССА потери содержимого: имена позиционных аргументов ровно эти.
CONTRACT_ARGS = ("repo_path", "remote_bytes", "content_bytes", "remote_sha",
                 "allow_overwrite")

#: Дверь, через которую классы и обязаны зваться (одна на всех).
CONTENT_DOOR = "guard_content_loss"

#: Корень сторожей потери: ветка расхождения зовёт их только отсюда.
LOSS_ROOT = "guard_overwrite"


class Unmeasured(AssertionError):
    """НЕ ИЗМЕРЕНО с названной причиной — третий исход, а не «чисто»."""


def _functions(source: str = None) -> dict:
    """Функции верхнего уровня пушера. Не разобрался ⇒ третий исход."""
    text = source if source is not None else PUSHER.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: пушер не разобран ({exc})") from exc
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def contract_classes(source: str = None) -> set:
    """Классы потери содержимого ПО КОНТРАКТУ ПОДПИСИ, без самой двери."""
    funcs = _functions(source)
    carriers = {
        name for name, node in funcs.items()
        if tuple(a.arg for a in node.args.args) == CONTRACT_ARGS
        and isinstance(node.returns, ast.Name) and node.returns.id == "str"}
    if CONTENT_DOOR not in carriers:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: двери `{CONTENT_DOOR}` с контрактом класса в пушере "
            f"нет — мерить перечень вызовов нечем (найдено: {sorted(carriers)})")
    classes = carriers - {CONTENT_DOOR}
    if not classes:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: по контракту {CONTRACT_ARGS} не найдено НИ ОДНОГО "
            f"класса — ноль классов есть подделка доказательства, а не чисто")
    return classes


def loss_guard_names(source: str = None) -> set:
    """Функции пушера, назвавшие себя сторожем потери (`guard_*_loss`)."""
    names = {n for n in _functions(source)
             if n.startswith("guard_") and n.endswith("_loss")}
    if not names:
        raise Unmeasured(
            "НЕ ИЗМЕРЕНО: в пушере нет ни одной функции `guard_*_loss` — "
            "население оси ИМЕНИ пусто, а не чисто")
    return names


def reachable_from(root: str, source: str = None) -> set:
    """Транзитивное замыкание вызовов от `root` (по AST, не по тексту)."""
    funcs = _functions(source)
    if root not in funcs:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: корня `{root}` в пушере нет — достижимость "
            f"сторожей потери мерить не от чего")
    seen, queue = set(), [root]
    while queue:
        name = queue.pop()
        for called in calls_of(name, source):
            if called in funcs and called not in seen:
                seen.add(called)
                queue.append(called)
    return seen
