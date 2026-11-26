#!/usr/bin/env python3
"""Полон ли ЗАКРЫТЫЙ перечень известных членов класса — и спрашивает ли об этом кто-нибудь.

ПРЕДМЕТ
───────────────────────────────────────────────────────────────────────────────
У переписи есть перечень «известных членов класса» — случаи, найденные руками.
Он стои́т ПОЛОЖИТЕЛЬНЫМ КОНТРОЛЕМ: потерян хоть один ⇒ перепись обязана
ОТКАЗАТЬ, а не печатать число.

Замер 26.11 (ADR-1113) нашёл дефект у самого механизма: такой перечень **ЗАКРЫТ
и сам не растёт**. У переписи производных артефактов (ADR-1074) он был заморожен
на трёх членах, четвёртый (ADR-1112) найден через три дня и в перечень не попал —
а строка «✅ все 3 известных члена ВНУТРИ предмета» оставалась ПРАВДОЙ. Она
отвечала о СПИСКЕ, а не о КЛАССЕ: **контроль, не знающий о члене, не может быть
им опровергнут — он зелен ПО ПОСТРОЕНИЮ.**

Население класса за пределами той одной переписи до этого прибора было
НЕ ИЗМЕРЕНО, и нулём это не считалось (инв. #17). Карточка —
`inbox-zakrytyi-perechen-izvestnyh-chlenov-klas`, заказ G1088 п. 2.

ДВЕ ПОЛОВИНЫ, И ОНИ ОТВЕЧАЮТ НА РАЗНЫЕ ВОПРОСЫ
───────────────────────────────────────────────────────────────────────────────
  `--surface`   НАСЕЛЕНИЕ: какие перечни стоя́т положительным контролем и
                НЕ спрашивают, полны ли они.
  `--verdict`   ВЕРДИКТ по перечню, ОБЪЯВИВШЕМУ источник полноты:
                ПОЛОН на сегодня · ОТСТАЛ (пропущенные названы поимённо) ·
                НЕ ИЗМЕРЕНО с названной причиной.

РОЛЬ, А НЕ ИМЯ (п. 1 метода карточки)
───────────────────────────────────────────────────────────────────────────────
Искать по слову `KNOWN` значило бы ответить на вопрос «как называется
константа» — дословный урок ADR-1074 (`ast.walk` вместо каталога) и ADR-1096
(белый список имён). Поэтому роль решает **НАПРАВЛЕНИЕ сверки**, и оно же
отделяет наш класс от соседнего:

    ┌─ `positive_control`  перечень обязан быть ВНУТРИ вычисленного предмета
    │                      (`NAME - computed`, `for k in NAME: if k not in …`)
    │                      ⇒ ЭТО наш класс: потеря члена меняет вердикт;
    ├─ `allowlist`         наоборот, ПРЕДМЕТ обязан быть внутри перечня
    │                      (`computed - NAME`, `if x not in NAME`) ⇒ это
    │                      храповик/белый список: его полнота — другой вопрос;
    ├─ `no_comparison`     имя ни с чем не сверяется ⇒ обычная константа;
    └─ `unresolved_role`   сверка есть, второй операнд НЕ РАЗОБРАН ⇒ **третий
                           исход** (инв. #17): вилка, а не ноль и не «не член».

**Ошибка сужения выбрана в сторону БОЛЬШЕЙ поверхности:** перечень, у которого
нашлись ОБА направления, числится положительным контролем, и это ПЕЧАТАЕТСЯ.
Мера, ошибающаяся в сторону меньшей, умеет сказать «поверхность исчерпана» про
поверхность, которой не видела.

ПОЛНОТА СПРАШИВАЕТСЯ У РЕЕСТРА РЕШЕНИЙ, А НЕ У САМОЙ МЕРКИ (п. 2 метода)
───────────────────────────────────────────────────────────────────────────────
Член класса рождается ADR-ом, значит у вопроса «все ли ADR-ы этого класса
названы» есть ВНЕШНИЙ источник — реестр решений. Сверять перечень с самим собой
было бы тавтологией.

Но **ОДНОГО совпадения по слову заголовка для вердикта НЕ ХВАТАЕТ, и это
ИЗМЕРЕНО:** строк реестра со словом «доставк» — 34, и заказ G1088 п. 5 прямо
говорит, что четыре двери доставки «по узкой оси одним классом НЕ являются».
Генератор-одиночка объявил бы членами 30 чужих решений — ровно та подмена,
против которой написан п. 1.

Поэтому объявление несёт ДВЕ части, и обе проверяемы:

  1. **генератор** — чем узнаётся КАНДИДАТ в реестре (слова заголовка);
  2. **приговор каждому кандидату** — `members` (член, с причиной) либо
     `non_members` (НЕ член, с причиной).

Тогда «полон на сегодня» = каждая строка реестра, которую производит
генератор, ПРИГОВОРЕНА. Реестр растёт извне; выросшая и не приговорённая
строка есть НАХОДКА, а не молчание. Это не тавтология: источник чужой.

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — НАСТОЯЩАЯ ИСТОРИЯ, А НЕ ВЫДУМАННАЯ СЦЕНА (п. 4)
───────────────────────────────────────────────────────────────────────────────
На вершине `fbb0fa45a` (26.11, вход цикла #1259) реестр УЖЕ нёс строку
ADR-1112, а `KNOWN_MEMBERS` переписи производных артефактов нёс ТРИ члена.
Прибор, не сказавший про эту вершину «ОТСТАЛ, пропущен ADR-1112», ОПРОВЕРГНУТ:
он не находит отставания, которое там БЫЛО.

КОДЫ ВОЗВРАТА
───────────────────────────────────────────────────────────────────────────────
  0 — находок нет (население класса пусто, все объявления ПОЛНЫ)
  1 — находки НАЗВАНЫ (население непусто либо перечень ОТСТАЛ)
  2 — НЕ ИЗМЕРЕНО с названной причиной (нечитаемое названное дерево, реестр не
      прочитан, объявление расходится со своим перечнем, генератор опровергнут)

Прибор только ЧИТАЕТ: ни одного перечня он не правит, в `data/` не пишет, сети
и часов не спрашивает.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys

# ── объявленный ОХВАТ (граница, а не замер пустоты остального) ───────────────
SOURCE_DIRS: tuple[str, ...] = ("scripts", "spa_core")
REGISTRY_PATHS: tuple[str, ...] = (
    "docs/decisions/INDEX.md",
    "docs/decisions/INDEX-ARCHIVE.md",
)
#: имя объявления источника полноты — ЕДИНСТВЕННАЯ дверь, по которой прибор
#: узнаёт, что перечень о своей полноте спрашивает.
DECLARATION_NAME = "KNOWN_MEMBERS_SOURCE"
MIN_ENTRIES = 2

POSITIVE_CONTROL = "positive_control"
ALLOWLIST = "allowlist"
NO_COMPARISON = "no_comparison"
UNRESOLVED_ROLE = "unresolved_role"
ROLES: tuple[str, ...] = (POSITIVE_CONTROL, ALLOWLIST, NO_COMPARISON, UNRESOLVED_ROLE)

COMPLETE = "ПОЛОН"
LAGGING = "ОТСТАЛ"
UNMEASURED = "НЕ ИЗМЕРЕНО"
VERDICTS: tuple[str, ...] = (COMPLETE, LAGGING, UNMEASURED)

_ADR_RE = re.compile(r"ADR-[0-9]{2,4}")
_ROW_RE = re.compile(r"^\|\s*(ADR-[0-9A-Za-z.\- ()]+?)\s*\|\s*(.*?)\s*\|")


# ─────────────────────────── реестр решений (внешний источник) ───────────────
def read_registry(root: pathlib.Path,
                  paths: tuple[str, ...] = REGISTRY_PATHS,
                  ) -> tuple[dict[str, str], list[str]]:
    """Строки реестра `{номер: заголовок}` и причины НЕ ИЗМЕРЕНО.

    Реестр живёт в ДВУХ файлах (ADR-1046: решения ≤ 900 переехали в архивную
    часть). Прочитать только `INDEX.md` значило бы потерять ADR-889, то есть
    молча недосчитать известного члена — поэтому отсутствие ЛЮБОГО объявленного
    файла есть названная причина, а не ноль.
    """
    rows: dict[str, str] = {}
    unreadable: list[str] = []
    for rel in paths:
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            unreadable.append(f"{rel}: {type(exc).__name__}: {exc}")
            continue
        except UnicodeDecodeError as exc:
            unreadable.append(f"{rel}: не декодируется ({exc})")
            continue
        for line in text.splitlines():
            m = _ROW_RE.match(line)
            if m:
                rows.setdefault(m.group(1).strip(), m.group(2))
    return rows, unreadable


def generated_candidates(rows: dict[str, str], generator: dict) -> list[str]:
    """Кандидаты класса: строки реестра, которые производит ОБЪЯВЛЕННЫЙ генератор."""
    need_all = tuple(str(w).lower() for w in generator.get("all", ()))
    need_any = tuple(str(w).lower() for w in generator.get("any", ()))
    out = []
    for num, title in rows.items():
        low = title.lower()
        if need_all and not all(w in low for w in need_all):
            continue
        if need_any and not any(w in low for w in need_any):
            continue
        out.append(num)
    return sorted(out)


def verdict_for_declaration(decl: dict,
                            rows: dict[str, str],
                            named_in_list: set[str],
                            *,
                            unreadable: tuple[str, ...] = (),
                            ) -> tuple[str, str]:
    """ПОЛОН / ОТСТАЛ / НЕ ИЗМЕРЕНО — вердикт об ОДНОМ объявлении.

    `named_in_list` — номера ADR, названные в самом перечне, который объявление
    описывает. Разойдись они с `members` — объявление говорит о другом перечне,
    и это НЕ ИЗМЕРЕНО, а не «полон»: прозу, отставшую от списка, нельзя читать
    как ответ о списке.
    """
    if unreadable:
        return UNMEASURED, "реестр решений не прочитан: " + "; ".join(unreadable)
    if not rows:
        return UNMEASURED, "реестр решений не дал ни одной строки в объявленной форме"
    if not isinstance(decl.get("generator"), dict):
        return UNMEASURED, "объявление не несёт генератора кандидатов"
    members = dict(decl.get("members") or {})
    non_members = dict(decl.get("non_members") or {})
    if not members:
        return UNMEASURED, "объявление не называет ни одного члена класса"
    for num, why in list(members.items()) + list(non_members.items()):
        if not str(why).strip():
            return UNMEASURED, f"приговор {num} объявлен без причины"

    candidates = generated_candidates(rows, decl["generator"])
    if not candidates:
        return UNMEASURED, "генератор не производит ни одной строки реестра — мерка слепа"

    # Контроль генератора: он ОБЯЗАН производить каждого объявленного члена.
    # Иначе объявление и генератор говорят о разных классах, и «приговорены
    # все кандидаты» было бы правдой о пустом пересечении.
    lost = sorted(set(members) - set(candidates))
    if lost:
        return UNMEASURED, ("генератор НЕ производит объявленного члена "
                            f"{', '.join(lost)} — мерка опровергнута")

    if set(members) != set(named_in_list):
        only_decl = sorted(set(members) - named_in_list)
        only_list = sorted(named_in_list - set(members))
        return UNMEASURED, ("объявление расходится со своим перечнем: "
                            f"только в объявлении {only_decl or '—'}, "
                            f"только в перечне {only_list or '—'}")

    unjudged = [c for c in candidates if c not in members and c not in non_members]
    if unjudged:
        return LAGGING, ("кандидаты реестра без приговора: "
                         + ", ".join(unjudged)
                         + f" (кандидатов {len(candidates)}, членов {len(members)}, "
                           f"НЕ членов {len(non_members)})")
    return COMPLETE, (f"приговорены все {len(candidates)} кандидат(а/ов) реестра "
                      f"(членов {len(members)}, НЕ членов {len(non_members)})")


# ─────────────────────────── поверхность: роль вхождения ────────────────────
def _is_closed_string_collection(node: ast.AST) -> int | None:
    """Число элементов, если узел — ЗАКРЫТЫЙ литерал строк; иначе `None`."""
    if isinstance(node, ast.Dict):
        keys = node.keys
        if keys and all(isinstance(k, ast.Constant) and isinstance(k.value, str)
                        for k in keys):
            return len(keys)
        return None
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        elts = node.elts
        if elts and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in elts):
            return len(elts)
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in {"frozenset", "set", "dict", "tuple", "list"} \
            and len(node.args) == 1:
        return _is_closed_string_collection(node.args[0])
    return None


def _root_name(node: ast.AST) -> str | None:
    """Имя, от которого берётся значение: `NAME`, `NAME.items()`, `set(NAME)`."""
    seen = 0
    while seen < 4:
        seen += 1
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
            continue
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "items", "keys", "values"}:
                node = node.func.value
                continue
            if isinstance(node.func, ast.Name) and node.func.id in {
                    "set", "frozenset", "list", "tuple", "sorted"} and node.args:
                node = node.args[0]
                continue
        return None
    return None


def _computed(node: ast.AST, names: set[str]) -> bool:
    """Второй операнд ВЫЧИСЛЕН, а не является другим закрытым литералом."""
    if _is_closed_string_collection(node) is not None:
        return False
    root = _root_name(node)
    if root is not None and root in names:
        return False
    return True


def classify_role(tree: ast.AST, name: str, closed_names: set[str]) -> str:
    """Роль вхождения имени `name` — по НАПРАВЛЕНИЮ сверки."""
    positive = allow = unresolved = False

    for node in ast.walk(tree):
        # NAME - computed  /  computed - NAME
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            left, right = _root_name(node.left), _root_name(node.right)
            if left == name:
                positive = positive or _computed(node.right, closed_names)
                unresolved = unresolved or not _computed(node.right, closed_names)
            elif right == name:
                allow = allow or _computed(node.left, closed_names)
                unresolved = unresolved or not _computed(node.left, closed_names)

        # for k in NAME: ... k not in computed     (включая comprehension)
        gens: list[ast.comprehension] = []
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                             ast.GeneratorExp)):
            gens = list(node.generators)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            gens = [ast.comprehension(target=node.target, iter=node.iter,
                                      ifs=_tests_in(node), is_async=0)]
        for gen in gens:
            if _root_name(gen.iter) != name:
                continue
            bound = _bound_names(gen.target)
            for test in gen.ifs:
                for cmp_node in ast.walk(test):
                    if not isinstance(cmp_node, ast.Compare):
                        continue
                    for op, comparator in zip(cmp_node.ops, cmp_node.comparators):
                        if not isinstance(op, (ast.In, ast.NotIn)):
                            continue
                        if _root_name(cmp_node.left) in bound:
                            if _computed(comparator, closed_names):
                                positive = True
                            else:
                                unresolved = True

        # x not in NAME  — предмет обязан быть внутри перечня (белый список)
        if isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) \
                        and _root_name(comparator) == name \
                        and _root_name(node.left) != name:
                    allow = True

    if positive:
        return POSITIVE_CONTROL
    if unresolved:
        return UNRESOLVED_ROLE
    if allow:
        return ALLOWLIST
    return NO_COMPARISON


def _tests_in(node: ast.For | ast.AsyncFor) -> list[ast.expr]:
    """Условия `if` в теле цикла — тот же смысл, что `ifs` у comprehension."""
    return [stmt.test for stmt in ast.walk(node) if isinstance(stmt, ast.If)]


def _bound_names(target: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


class Entry:
    __slots__ = ("path", "name", "entries", "role", "declares", "adr_backed")

    def __init__(self, path: str, name: str, entries: int, role: str,
                 declares: bool, adr_backed: bool) -> None:
        self.path, self.name, self.entries = path, name, entries
        self.role, self.declares = role, declares
        #: перечень НАЗЫВАЕТ ADR-ы в своих элементах ⇒ у вопроса «полон ли он»
        #: есть ВНЕШНИЙ источник (реестр решений), то есть это класс карточки в
        #: узком смысле. Не называет ⇒ реестр ответить не может, и это ТРЕТЬЕ
        #: ведро, а не ноль и не член.
        self.adr_backed = adr_backed


def measure_surface(root: pathlib.Path,
                    source_dirs: tuple[str, ...] = SOURCE_DIRS,
                    ) -> tuple[list[Entry], list[str]]:
    """Все закрытые перечни объявленного охвата с их РОЛЬЮ. Второе — причины НЕ РАЗОБРАНО."""
    out: list[Entry] = []
    unparsed: list[str] = []
    for d in source_dirs:
        base = root / d
        if not base.is_dir():
            unparsed.append(f"{d}: каталога нет в названном дереве")
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
                unparsed.append(f"{rel}: {type(exc).__name__}: {exc}")
                continue
            closed: dict[str, int] = {}
            for stmt in tree.body:
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    targets = stmt.targets if isinstance(stmt, ast.Assign) \
                        else [stmt.target]
                    if stmt.value is None:
                        continue
                    n = _is_closed_string_collection(stmt.value)
                    if n is None or n < MIN_ENTRIES:
                        continue
                    for t in targets:
                        if isinstance(t, ast.Name):
                            closed[t.id] = n
            if not closed:
                continue
            # «Объявил источник полноты» — свойство ПЕРЕЧНЯ, а не модуля.
            # Первая редакция прибора читала наличие объявления у ФАЙЛА и
            # зачла соседний `SANDBOX_MARKERS` в том же модуле как спрашивающий
            # о своей полноте — дефект МОЕЙ меры в сторону «чисто». Объявление
            # называет описываемый перечень полем `describes`, и зачитывается
            # РОВНО он.
            described = _described_by_declaration(tree)
            literals = _module_literals(tree)
            for name, n in closed.items():
                if name == DECLARATION_NAME:
                    continue
                blob = json.dumps(literals.get(name), ensure_ascii=False,
                                  default=str)
                out.append(Entry(rel, name, n,
                                 classify_role(tree, name, set(closed)),
                                 name == described,
                                 bool(_ADR_RE.search(blob))))
    return out, unparsed


def _described_by_declaration(tree: ast.AST) -> str | None:
    """Имя перечня, о котором говорит объявление источника полноты."""
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, ast.Assign) and stmt.value is not None \
                and DECLARATION_NAME in {t.id for t in stmt.targets
                                         if isinstance(t, ast.Name)}:
            try:
                decl = ast.literal_eval(stmt.value)
            except (ValueError, SyntaxError):
                return None
            if isinstance(decl, dict) and isinstance(decl.get("describes"), str):
                return decl["describes"]
    return None


def _module_literals(tree: ast.AST) -> dict[str, object]:
    """Значения закрытых литералов модуля — чтобы спросить, назван ли в них ADR."""
    out: dict[str, object] = {}
    for stmt in getattr(tree, "body", []):
        if isinstance(stmt, ast.Assign) and stmt.value is not None:
            try:
                value = ast.literal_eval(stmt.value)
            except (ValueError, SyntaxError):
                continue
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = value
    return out


# ────────────────────────────────── печать ──────────────────────────────────
def render_surface(root: pathlib.Path, entries: list[Entry],
                   unparsed: list[str]) -> tuple[str, int]:
    counts = {r: sum(1 for e in entries if e.role == r) for r in ROLES}
    form = [e for e in entries if e.role == POSITIVE_CONTROL and not e.declares]
    # КЛАСС КАРТОЧКИ УЖЕ ФОРМЫ, и смешивать их значило бы объявить членами 156
    # перечней «обязательных полей», у которых внешнего источника полноты нет
    # ВОВСЕ. Член класса рождается ADR-ом (п. 2 метода), поэтому предметом
    # числится перечень, НАЗЫВАЮЩИЙ ADR в своих элементах: только у него реестр
    # способен ответить «полон ли он».
    subject = [e for e in form if e.adr_backed]
    no_source = [e for e in form if not e.adr_backed]
    asking = [e for e in entries if e.role == POSITIVE_CONTROL and e.declares]
    fork_hi = len(subject) + counts[UNRESOLVED_ROLE]

    lines = [
        f"дерево: {root}  (ВЫБОР НАПЕЧАТАН, не угадан)",
        f"охват: {', '.join(SOURCE_DIRS)} — это ГРАНИЦА охвата, а не замер пустоты "
        "остальных каталогов",
        f"закрытых перечней ({MIN_ENTRIES}+ строковых элементов) найдено: {len(entries)}",
        "  по РОЛИ вхождения (направление сверки, не имя константы):",
    ]
    for r in ROLES:
        lines.append(f"    {r}: {counts[r]}")
    lines.append("")
    lines.append(f"ФОРМА (положительный контроль БЕЗ объявленного источника "
                 f"полноты): {len(form)}")
    lines.append(f"  из них ПРЕДМЕТ класса — называют ADR, то есть реестр способен "
                 f"ответить: {len(subject)}")
    lines.append(f"  внешнего источника полноты НЕТ ВОВСЕ (ADR не назван) — третье "
                 f"ведро, не ноль и не член: {len(no_source)}")
    lines.append(f"  спрашивают о своей полноте: {len(asking)}")
    lines.append(f"  ВИЛКА населения предмета: {len(subject)} … {fork_hi} "
                 f"(+{counts[UNRESOLVED_ROLE]} НЕ РАЗОБРАННОЙ роли — это не ноль)")
    if unparsed:
        lines.append(f"  НЕ РАЗОБРАНО файлов: {len(unparsed)} — "
                     f"{'; '.join(unparsed[:3])}")
    if asking:
        lines.append("")
        lines.append("ОБЪЯВИЛИ ИСТОЧНИК ПОЛНОТЫ:")
        for e in asking:
            lines.append(f"  • {e.path}::{e.name} ({e.entries} элемент(а/ов))")
    unres = [e for e in entries if e.role == UNRESOLVED_ROLE]
    if unres:
        lines.append("")
        lines.append("ВИЛКА ПОИМЁННО (роль НЕ РАЗОБРАНА — второй операнд сверки не "
                     "привязан; это не ноль):")
        for e in unres:
            lines.append(f"  ? {e.path}::{e.name} ({e.entries} элемент(а/ов))")
    if subject:
        lines.append("")
        lines.append("ПРЕДМЕТ ПОИМЁННО (называет ADR, полноту не спрашивает никто):")
        for e in subject:
            lines.append(f"  • {e.path}::{e.name} ({e.entries} элемент(а/ов))")
    code = 2 if unparsed and not entries else (1 if subject or unparsed else 0)
    return "\n".join(lines), code


def _declaration_of(root: pathlib.Path, rel: str) -> tuple[dict | None, set[str], str]:
    """Объявление и номера ADR самого перечня — РАЗБОРОМ, без исполнения байтов.

    Исполнять уезжающий модуль, чтобы узнать, что он о себе говорит, значило бы
    поверить ему на слово (дословный порядок ADR-1073 п. 4).
    """
    p = root / rel
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return None, set(), f"{rel} не разобран: {type(exc).__name__}: {exc}"
    decl = None
    named: set[str] = set()
    described = None
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or stmt.value is None:
            continue
        names = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
        if DECLARATION_NAME in names:
            try:
                decl = ast.literal_eval(stmt.value)
            except (ValueError, SyntaxError) as exc:
                return None, set(), (f"{rel}: объявление {DECLARATION_NAME} не "
                                     f"является литералом ({exc})")
            if isinstance(decl, dict):
                described = decl.get("describes")
    if decl is None:
        return None, set(), f"{rel}: объявления {DECLARATION_NAME} нет"
    if not described:
        return None, set(), (f"{rel}: объявление не называет поля `describes` — "
                             "неизвестно, о каком перечне оно говорит")
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and described in {
                t.id for t in stmt.targets if isinstance(t, ast.Name)}:
            try:
                value = ast.literal_eval(stmt.value)
            except (ValueError, SyntaxError) as exc:
                return None, set(), (f"{rel}: перечень `{described}` не является "
                                     f"литералом ({exc})")
            blob = json.dumps(value, ensure_ascii=False)
            named = set(_ADR_RE.findall(blob))
            return decl, named, ""
    return None, set(), f"{rel}: перечня `{described}`, о котором говорит объявление, нет"


def render_verdicts(root: pathlib.Path, entries: list[Entry]) -> tuple[str, int]:
    rows, unreadable = read_registry(root)
    lines = [f"дерево: {root}  (ВЫБОР НАПЕЧАТАН, не угадан)",
             f"реестр решений: {len(rows)} строк(и) из {len(REGISTRY_PATHS)} файл(ов)"]
    if unreadable:
        lines.append("  НЕ ПРОЧИТАНО: " + "; ".join(unreadable))
    paths = sorted({e.path for e in entries if e.declares})
    if not paths:
        lines.append("ни один перечень охвата не объявил источника полноты — "
                     f"вердикт выносить нечему (НЕ ИЗМЕРЕНО)")
        return "\n".join(lines), 2
    worst = 0
    for rel in paths:
        decl, named, why = _declaration_of(root, rel)
        if decl is None:
            lines.append(f"  {UNMEASURED}  {rel}: {why}")
            worst = max(worst, 2)
            continue
        verdict, detail = verdict_for_declaration(
            decl, rows, named, unreadable=tuple(unreadable))
        mark = {COMPLETE: "✅", LAGGING: "🚨", UNMEASURED: "⚠️"}[verdict]
        lines.append(f"  {mark} {verdict}  {rel}::{decl.get('describes')} — {detail}")
        worst = max(worst, {COMPLETE: 0, LAGGING: 1, UNMEASURED: 2}[verdict])
    return "\n".join(lines), worst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=None,
                    help="дерево замера; умолчание — дерево этого файла (ПЕЧАТАЕТСЯ)")
    ap.add_argument("--surface", action="store_true", help="население класса")
    ap.add_argument("--verdict", action="store_true",
                    help="ПОЛОН / ОТСТАЛ / НЕ ИЗМЕРЕНО по объявившим источник")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    default_root = pathlib.Path(__file__).resolve().parent.parent
    root = pathlib.Path(args.repo_root).resolve() if args.repo_root else default_root
    if not root.is_dir():
        print(f"НЕ ИЗМЕРЕНО: названного дерева нет: {root}", file=sys.stderr)
        return 2
    if args.repo_root is None:
        print(f"дерево НЕ НАЗВАНО — умолчание {root} (печатается, а не угадывается)")

    entries, unparsed = measure_surface(root)
    if args.json:
        rows, unreadable = read_registry(root)
        payload = {
            "root": str(root),
            "scope": list(SOURCE_DIRS),
            "counts": {r: sum(1 for e in entries if e.role == r) for r in ROLES},
            "form": [f"{e.path}::{e.name}" for e in entries
                     if e.role == POSITIVE_CONTROL and not e.declares],
            "subject": [f"{e.path}::{e.name}" for e in entries
                        if e.role == POSITIVE_CONTROL and not e.declares
                        and e.adr_backed],
            "no_external_source": [f"{e.path}::{e.name}" for e in entries
                                   if e.role == POSITIVE_CONTROL
                                   and not e.declares and not e.adr_backed],
            "declaring": [f"{e.path}::{e.name}" for e in entries
                          if e.role == POSITIVE_CONTROL and e.declares],
            "unparsed": unparsed,
            "registry_rows": len(rows),
            "registry_unreadable": unreadable,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if payload["subject"] or unparsed else 0

    codes = []
    if args.verdict or not args.surface:
        text, code = render_verdicts(root, entries)
        print("— ВЕРДИКТ по объявившим источник полноты —")
        print(text)
        codes.append(code)
    if args.surface or not args.verdict:
        text, code = render_surface(root, entries, unparsed)
        print("— НАСЕЛЕНИЕ класса «закрытый перечень не спрашивает, полон ли он» —")
        print(text)
        codes.append(code)
    return max(codes) if codes else 0


if __name__ == "__main__":
    raise SystemExit(main())
