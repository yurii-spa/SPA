"""spa_core/monitoring/cio_substitution_census.py — где ещё функция, не сумевшая
получить вход, возвращает ПРАВДОПОДОБНОЕ число вместо отказа, и доходит ли хоть
одно такое число до решения о капитале (заказ циклов #518/#519, ТЗ CIO §5).

Цикл #518 нашёл класс «выдумать вместо отказа» на ОДНОЙ поверхности — личность
нашего счёта, 6 модулей — и ровно потому, что смотрел туда. Цикл #519, снимая
приёмку, сформулировал урок шире: **найдя форму контроля, применять её ко всему
классу, для которого она верна, а не к её поводу.** Этот модуль и есть такое
применение: тот же вопрос, заданный всему дереву.

Заказ назвал три ловушки заранее. Все три здесь разобраны ЗАМЕРОМ, а не фразой:

1. **«Дефолт есть» ≠ «значение подставлено».** ``None`` / ``""`` / ``0`` /
   ``False`` / пустой контейнер — МЕТКА ОТСУТСТВИЯ: она заставляет вызывающего
   проверить. Подстановка — только ПРАВДОПОДОБНОЕ значение, неотличимое от
   настоящего. Сюда же — и это уточнение, добытое замером, а не взятое из
   заказа: **дефолт необязательного параметра подстановкой НЕ является**.
   ``timeout = timeout if timeout is not None else ADAPTER_TIMEOUT_SEC`` — вход
   не спрашивали, значит и не теряли; это объявленный дефолт вызова. До этого
   исключения ЧЕТЫРЕ из десяти достижимых «находок» были именно им.
2. **«Возвращает в ветке» ≠ «возвращает в ветке ОТСУТСТВИЯ».** Ветка НАЛИЧИЯ
   исключена ЯВНО: разбираются только ``except``, ``if not <значение>``,
   ``if <значение> is None``, ``else`` от ``is not None`` и терминальный проход
   мимо всех попыток. Порог-лестница (``if x > 0.5: return 22.0``) в предмет не
   попадает вовсе — первая редакция замера её считала и давала 609 «находок»
   там, где их 211.
3. **Счёт мест — НЕ ответ.** Головное число здесь — не «сколько мест
   подставляют», а «сколько подстановок ДОХОДИТ до решения о капитале».
   Провенанс меряется ОТ ПОТРЕБИТЕЛЯ НАЗАД до неподвижной точки, и каналов
   два, а не один:

   * **импорт** — замыкание импортов от модулей ступеней решения;
   * **артефакт** — ступень решения читает продукт другой ступени ⇒ замыкание
     ПРОИЗВОДИТЕЛЯ продукта тоже достижимо.

   Второй канал в этой системе главный: аллокатор не импортирует адаптеры, он
   читает их снимок. Замер импортом в одиночку ответил бы «ноль» на живой
   находке.

**Обратная сторона, названная заказом, тоже меряется.** ``[FALLBACK]`` на
риск-пути может быть осознанным консервативным значением, а не дефектом. Поэтому
у каждой достижимой подстановки спрашивается НАПРАВЛЕНИЕ: двигает ли она решение
к входу или к отказу. Двигающая к ОТКАЗУ — не этот класс и исключается С
ПРИЧИНОЙ. Ось не опознана ⇒ третий исход ``UNCHECKED``, сказанный вслух, а не
молчаливое «безопасно».

**И четвёртый замер, которого заказ не называл, а #518 назвал причиной вреда:
РАЗЛИЧИМОСТЬ.** «Подстановка опаснее пустоты» — потому что потребитель не может
её отличить. Значит вопрос не только «подставляет ли», но и «доезжает ли до
потребителя ПРИЗНАК, что подставлено». Замер это разделяет, и разделение не
академическое: ``_REGISTRY_FALLBACK_TVL_USD`` (аллокатор, $50M) — подстановка
ПОМЕЧЕННАЯ (``tvl_source="static"``, ADR-053), и гейт по ней отказывает; а
подстановка книги в ``portfolio_rebalancer`` метки не несёт ни одной.

**Что замер нашёл (числа — прогон, не память).** Перепись: 516 подстановок в 321
файле; подстановочных констант с объявляющим именем — 115 в 96 файлах.
**Население — функция ДЕРЕВА, поэтому названо вместе с ним:** замер снят на
`origin/main` 6967185e6 (цикл #523). В дереве цикла #521 (`e498c85ad`, на шесть
файлов меньше) тот же код даёт 513 / 319 — расхождение объясняется составом
`spa_core/` + `scripts/`, а не сменой прибора. Числа без имени дерева здесь
бессмысленны, и первая редакция этой строки (568 / 346, 114 / 95) была именно
такой: она пережила последние правки прибора и не воспроизводилась НИ В ОДНОМ
дереве — поймано приёмкой #523. До решения о капитале доходят единицы, и среди
них — одна находка, которой не было ни в одном разборе:

    ``spa_core/tuner/portfolio_rebalancer.py``: когда цель тюнера ОТВЕРГНУТА
    валидатором политики, книга не отказывает — она подставляет захардкоженный
    ``_SAFE_FALLBACK_POSITIONS`` ($88 000 по семи поимённым протоколам) и пишет
    его в ``current_positions.json``. Сама подстановка объявлена и обоснована
    (ADR-001, «policy-compliant portfolio»), и валидатор её перепроверяет.
    Дефект в другом: **поля-спутники пережили подстановку**. В артефакт уходят
    ``tuner_expected_apy`` / ``tuner_expected_sharpe`` / ``tuner_objective_score``
    из ``result`` — из ТОЙ САМОЙ аллокации, которую только что отвергли, — и
    стоят рядом с книгой, которой они не описывают. Поля ``source`` у обоих
    путей одно и то же (``portfolio_rebalancer_v1``), поля «это подстановка» нет
    ни одного: читающий книгу не может отличить цель тюнера от аварийной
    раскладки, а приложенная к ней ожидаемая доходность относится к другому
    портфелю.

Отсюда общее правило класса, шире своего повода: **подстановка обязана уносить с
собой ВСЕ производные отвергнутого значения.** Заменили величину — либо замените
её спутников, либо снимите их; спутник, переживший подстановку, врёт тем
опаснее, что выглядит измерением.

**Граница замера сказана вслух.** Мера отвечает на вопрос «может ли подставленное
число ДОЙТИ до ступени решения», а НЕ «читает ли ступень именно это поле».
Достижимость здесь — свойство графа (импорт + артефакт), и она заведомо ШИРЕ
употребления: ``health_score`` доезжает до аллокатора внутри снимка, но ранжирует
аллокатор не им. Сузить до употребления значило бы разбирать поле за полем сквозь
две сериализации, и первая же ошибка такого разбора дала бы уверенный неверный
ответ в сторону «всё чисто». Поэтому широкая мера с названной границей, а не
узкая с невидимой. Головные находки от границы не зависят: они предъявлены
поимённо, с файлом и строкой, и проверяются глазами.

Отдельно: ``main()``-коды возврата попадают в третий исход (ось не опознана), и
это не недосмотр — «отсутствие входа» у них другой природы, а прятать их
эвристикой значило бы завести правило, которое однажды спрячет настоящую находку.

ADVISORY. Ни один вызов не изменён, ни одна подстановка не удалена, пороги
RiskPolicy не тронуты, капитал не сдвинут. Правка любого из найденных мест — это
money-path и решение владельца (вопрос заведён карточкой).

Состав ступеней решения НЕ дублируется (§3 ТЗ — прямая инструкция владельца не
заводить параллельные модели): берётся из
:data:`spa_core.monitoring.cio_component_map.STAGES` по ключам
:data:`DECISION_STAGE_KEYS`. Ключа нет ⇒ громкий ``UNCHECKED``, а не своя копия.

CLI::  python3 -m spa_core.monitoring.cio_substitution_census
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

REPORT_REL = "data/cio_substitution_census.json"

#: Корни, в которых ищем. ``scripts/`` включён намеренно: подставлять число
#: умеет и отдельный скрипт, а не только модуль пакета.
SCAN_ROOTS = ("spa_core", "scripts")

#: Ступени, чей продукт И ЕСТЬ решение о капитале — «аллокатор, гейт, книга»
#: словами заказа. Ключи, а не модули: состав берётся из ``cio_component_map``.
DECISION_STAGE_KEYS = (
    "portfolio_state",       # книга: current_positions.json
    "portfolio_optimizer",   # аллокатор: target_allocation
    "target_allocation",     # цель с обоснованием
    "rebalance_evaluator",   # «пора ли перекладывать»
    "risk_gate",             # последняя дверь перед ходом
)

#: Слова, которыми ИМЯ константы САМО объявляет её заменой. ``DEFAULT`` сюда
#: НЕ входит, и это решение с причиной: дефолт применяется, когда вход не
#: спрашивали, а подстановка — когда спросили и не получили. Замер: с
#: ``DEFAULT`` население 598 констант, без него 114, и разница почти целиком
#: конфигурационные умолчания (таймауты, размеры страниц), к классу не
#: относящиеся.
SUBSTITUTION_TOKENS = (
    "FALLBACK", "MOCK", "STUB", "PLACEHOLDER", "SYNTHETIC", "DUMMY", "ASSUMED",
)

#: Оси, на которых бо́льшее значение двигает решение К ВХОДУ (подставить тут =
#: облегчить покупку). ОБЪЯВЛЕНИЕ с причиной, не вывод: смысл оси задаёт
#: политика (TVL-floor, полоса APY), из кода его не вывести.
AXIS_TOWARD_ENTRY = (
    "apy", "apr", "yield", "rate", "tvl", "liquidity", "balance", "supply",
    "score", "health", "capacity", "depth",
)

#: Оси, на которых бо́льшее значение двигает решение К ОТКАЗУ. Подстановка на
#: такой оси — консервативное значение, а НЕ этот класс (обратная сторона,
#: названная заказом).
AXIS_TOWARD_REFUSAL = (
    "cost", "gas", "fee", "slippage", "impact", "drawdown", "risk_penalty",
    "payback", "spread", "loss", "haircut",
)

#: Поля, которыми подстановка МОЖЕТ объявить себя потребителю. Есть такое поле
#: рядом с числом ⇒ потребитель способен отказать (и, как показывает ADR-053 /
#: ADR-061, отказывает). Нет ⇒ подстановка неотличима от наблюдения.
LABEL_KEYS = (
    "source", "apy_source", "tvl_source", "live_data", "is_fallback",
    "provenance", "evidence", "evidence_level", "fallback", "observed",
)

# ── исходы направления ───────────────────────────────────────────────────────
DIR_ENTRY = "TOWARD_ENTRY"        #: двигает решение к покупке/удержанию
DIR_REFUSAL = "TOWARD_REFUSAL"    #: двигает к отказу — НЕ этот класс
DIR_UNCHECKED = "UNCHECKED"       #: ось не опознана — третий исход, вслух

# ── формы ветки ОТСУТСТВИЯ (ветка НАЛИЧИЯ исключена явно) ────────────────────
FORM_EXCEPT = "except → return"
FORM_NOT = "if not <значение> → return"
FORM_IS_NONE = "if <значение> is None → return"
FORM_ELSE_NOT_NONE = "else от `is not None` → return"
FORM_OR = "`X or <подстановка>`"
FORM_IFEXP_TRUTHY = "`A if X else B` — рука отсутствия"
FORM_IFEXP_IS_NONE = "`A if X is None else B` — рука отсутствия"
FORM_IFEXP_NOT_NONE = "`A if X is not None else B` — рука отсутствия"
FORM_FALLTHROUGH = "проход мимо всех попыток"

ABSENCE_FORMS = (
    FORM_EXCEPT, FORM_NOT, FORM_IS_NONE, FORM_ELSE_NOT_NONE, FORM_OR,
    FORM_IFEXP_TRUTHY, FORM_IFEXP_IS_NONE, FORM_IFEXP_NOT_NONE, FORM_FALLTHROUGH,
)


# ─────────────────────────── разбор: общие помощники ─────────────────────────

def _iter_py(root: Path, sub: str) -> Iterable[Path]:
    base = root / sub
    if not base.is_dir():
        return
    for p in sorted(base.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if "/tests/" in rel or rel.startswith("tests/"):
            continue
        if "/test_" in rel or Path(rel).name.startswith("test_"):
            continue
        yield p


def _parse(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None


def _module_dotted(rel: str) -> str:
    return rel[:-3].replace("/", ".").removesuffix(".__init__")


def _path_of(root: Path, dotted: str) -> Optional[Path]:
    p = root / (dotted.replace(".", "/") + ".py")
    if p.is_file():
        return p
    p2 = root / (dotted.replace(".", "/") + "/__init__.py")
    return p2 if p2.is_file() else None


def _is_value(node: ast.AST) -> bool:
    """Узел — ЗНАЧЕНИЕ (имя/атрибут/подписка/вызов), а не сравнение.

    Это и есть механизм ловушки 2: тест вроде ``if x > 0.5`` значением не
    является, поэтому порог-лестница в предмет не попадает вовсе.
    """
    return isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.Call))


def _root_name(node: ast.AST) -> str:
    """Корневое имя выражения-значения (``a.b[0]`` → ``a``)."""
    while True:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return ""


# ───────────────── ловушка 1: что считается ПОДСТАНОВКОЙ ─────────────────────

def plausible_value(node: ast.AST, consts: dict[str, tuple[bool, str]],
                    depth: int = 0) -> tuple[bool, str]:
    """Правдоподобно ли значение узла — и почему.

    ПРАВДОПОДОБНО только то, что потребитель не отличит от настоящего
    измерения: ненулевое число, контейнер с ненулевыми числами, выражение от
    них. ``None`` / ``""`` / ``0`` / ``False`` / пустой контейнер —
    МЕТКА ОТСУТСТВИЯ и подстановкой НЕ являются: они заставляют вызывающего
    проверить, а не вводят его в заблуждение. Это ловушка 1 заказа, и она
    здесь механизм, а не оговорка.

    ``0`` исключён и по существу: на осях этой системы ноль двигает решение к
    ОТКАЗУ (нулевой APY не пройдёт полосу 1…30 %, нулевой TVL не пройдёт floor
    $5M), то есть попадает под обратную сторону класса.
    """
    if depth > 6:
        return False, "разбор глубже 6 уровней — не разобрано"
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return False, "bool — не число"
        if isinstance(v, (int, float)):
            if v == 0:
                return False, "ноль — метка отсутствия, не подстановка"
            return True, f"литерал {v!r}"
        if v is None:
            return False, "None — метка отсутствия"
        if isinstance(v, str):
            return False, "строка — не число"
        return False, f"константа {type(v).__name__}"
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    if isinstance(node, ast.Attribute) and node.attr in consts:
        # self.FALLBACK_APY / cls.FALLBACK_APY — классовая константа
        return consts[node.attr]
    if isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
        elts = list(node.values) if isinstance(node, ast.Dict) else list(node.elts)
        if not elts:
            return False, "пустой контейнер — метка отсутствия"
        for e in elts:
            ok, _ = plausible_value(e, consts, depth + 1)
            if ok:
                return True, "контейнер с ненулевыми числами"
        return False, "контейнер без чисел"
    if isinstance(node, ast.BinOp):
        lo, _ = plausible_value(node.left, consts, depth + 1)
        ro, _ = plausible_value(node.right, consts, depth + 1)
        if lo or ro:
            return True, "выражение от правдоподобного"
        return False, "выражение без правдоподобного"
    if isinstance(node, ast.Call):
        for a in node.args:
            ok, _ = plausible_value(a, consts, depth + 1)
            if ok:
                return True, "вызов от правдоподобного"
        return False, "вызов без правдоподобного аргумента"
    return False, "не разобрано"


def module_constants(tree: ast.AST) -> dict[str, tuple[bool, str]]:
    """Модульные И классовые константы: имя → (правдоподобно?, почему).

    Классовые нужны ради ``self.FALLBACK_APY`` — самой распространённой формы
    подстановки у адаптеров (``spa_core/base.py``).
    """
    out: dict[str, tuple[bool, str]] = {}

    def scan(body: list[ast.stmt]) -> None:
        for n in body:
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        out[t.id] = plausible_value(n.value, {})
            elif isinstance(n, ast.ClassDef):
                scan(n.body)

    scan(getattr(tree, "body", []))
    return out


# ───────── ловушка 2: ветка ОТСУТСТВИЯ, и ТОЛЬКО она ─────────────────────────

def optional_none_params(fn: ast.AST) -> set[str]:
    """Параметры функции, у которых дефолт — ``None``.

    Такой параметр — объявленный ДЕФОЛТ ВЫЗОВА, а не потерянный вход: значения
    у функции не спрашивали. ``timeout if timeout is not None else
    ADAPTER_TIMEOUT_SEC`` подстановкой не является, и это не тонкость: до
    введения исключения ЧЕТЫРЕ из десяти достижимых «находок» были ровно им
    (``run_orchestrator``, ``_build_safe_fallback_positions`` и два разбора
    ``argv`` в ``main``).
    """
    args = getattr(fn, "args", None)
    if args is None:
        return set()
    out: set[str] = set()
    positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
    defaults = list(args.defaults)
    if defaults:
        for arg, dflt in zip(positional[-len(defaults):], defaults):
            if isinstance(dflt, ast.Constant) and dflt.value is None:
                out.add(arg.arg)
    for arg, dflt in zip(args.kwonlyargs, args.kw_defaults):
        if isinstance(dflt, ast.Constant) and dflt.value is None:
            out.add(arg.arg)
    return out


def absence_sites(fn: ast.AST) -> Iterable[tuple[str, ast.AST, int]]:
    """``(форма, узел-значение, строка)`` для веток ОТСУТСТВИЯ функции.

    Ветка НАЛИЧИЯ не рассматривается ВООБЩЕ — ни у ``if``, ни у ``IfExp``.
    Тест обязан быть ЗНАЧЕНИЕМ (:func:`_is_value`) либо сравнением значения с
    ``None``; ``if apy > SUSPICIOUS: return 22.0`` под это не подходит и в
    предмет не попадает.

    Дефолт необязательного параметра исключается здесь же: если тестируемое
    имя — параметр с дефолтом ``None``, ветка описывает НЕПЕРЕДАННЫЙ аргумент,
    а не потерянный вход.
    """
    skip = optional_none_params(fn)

    def _tested_is_optional_param(test_value: ast.AST) -> bool:
        return _root_name(test_value) in skip

    for n in ast.walk(fn):
        if isinstance(n, ast.ExceptHandler):
            for stmt in n.body:
                for r in ast.walk(stmt):
                    if isinstance(r, ast.Return) and r.value is not None:
                        yield FORM_EXCEPT, r.value, r.lineno
            continue

        if isinstance(n, ast.If):
            body, form = None, ""
            t = n.test
            if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not) \
                    and _is_value(t.operand):
                if _tested_is_optional_param(t.operand):
                    continue
                body, form = n.body, FORM_NOT
            elif isinstance(t, ast.Compare) and len(t.ops) == 1 and _is_value(t.left):
                cmpv = t.comparators[0]
                is_none = isinstance(cmpv, ast.Constant) and cmpv.value is None
                if is_none and _tested_is_optional_param(t.left):
                    continue
                if is_none and isinstance(t.ops[0], ast.Is):
                    body, form = n.body, FORM_IS_NONE
                elif is_none and isinstance(t.ops[0], ast.IsNot):
                    body, form = n.orelse, FORM_ELSE_NOT_NONE
            if body:
                for stmt in body:
                    for r in ast.walk(stmt):
                        if isinstance(r, ast.Return) and r.value is not None:
                            yield form, r.value, r.lineno
            continue

        if isinstance(n, ast.IfExp):
            t, arm, form = n.test, None, ""
            if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not) \
                    and _is_value(t.operand):
                if _tested_is_optional_param(t.operand):
                    continue
                arm, form = n.body, FORM_IFEXP_TRUTHY
            elif isinstance(t, ast.Compare) and len(t.ops) == 1 and _is_value(t.left):
                cmpv = t.comparators[0]
                is_none = isinstance(cmpv, ast.Constant) and cmpv.value is None
                if is_none and _tested_is_optional_param(t.left):
                    continue
                if is_none and isinstance(t.ops[0], ast.Is):
                    arm, form = n.body, FORM_IFEXP_IS_NONE
                elif is_none and isinstance(t.ops[0], ast.IsNot):
                    arm, form = n.orelse, FORM_IFEXP_NOT_NONE
            elif _is_value(t):
                if _tested_is_optional_param(t):
                    continue
                arm, form = n.orelse, FORM_IFEXP_TRUTHY
            if arm is not None:
                yield form, arm, getattr(arm, "lineno", n.lineno)
            continue

        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or) \
                and len(n.values) >= 2 and _is_value(n.values[0]):
            if _root_name(n.values[0]) in skip:
                continue
            last = n.values[-1]
            yield FORM_OR, last, getattr(last, "lineno", n.lineno)

    # Терминальный проход: цикл попыток, каждая из которых МОЖЕТ вернуть, — и
    # значение после цикла. «Ни одна попытка не сработала, вот вам число».
    body = list(getattr(fn, "body", []))
    if body and isinstance(body[-1], ast.Return) and body[-1].value is not None:
        for stmt in body[:-1]:
            if isinstance(stmt, (ast.For, ast.While, ast.AsyncFor)):
                if any(isinstance(x, ast.Return) for x in ast.walk(stmt)):
                    yield FORM_FALLTHROUGH, body[-1].value, body[-1].lineno
                    break


# ─────────── обратная сторона: КУДА подстановка двигает решение ──────────────

def _tokens(*names: str) -> set[str]:
    """Идентификаторы → множество СЛОВ.

    Ось опознаётся по слову, а не по подстроке, и это не педантизм: первая
    редакция мерила ``token in hay`` и объявила ``portfolio_rebalancer``
    носителем оси ``balance`` — слово оказалось своей же меткой внутри
    «rebalancer», и код выхода ``return 1`` из ``main()`` уехал в находки как
    «подстановка, двигающая ко входу». Родственный урок уже записан в правилах
    про жадные регулярки.
    """
    out: set[str] = set()
    for name in names:
        if not name:
            continue
        buf = ""
        for ch in name.rsplit(".", 1)[0]:
            if ch.isupper() and buf and not buf[-1].isupper():
                out.add(buf.lower()); buf = ch
            elif ch.isalnum():
                buf += ch
            else:
                if buf:
                    out.add(buf.lower())
                buf = ""
        if buf:
            out.add(buf.lower())
    return out


def direction_of(*names: str) -> tuple[str, str]:
    """``(исход, причина)`` — к входу, к отказу или НЕ ИЗМЕРЕНО.

    Заказ назвал это прямо: ``[FALLBACK]`` на риск-пути может быть осознанным
    консервативным значением. Мок, двигающий к ОТКАЗУ, — не этот класс, и
    объявлять его находкой значило бы наказать здоровый код.

    Ось не опознана ⇒ ТРЕТИЙ ИСХОД, а не «безопасно». Урок #519: у «не
    измерено» два выхода, и молчаливое превращение его в благополучный вердикт
    — тот же дефект, ради которого замер и пишется.
    """
    words = _tokens(*names)
    hit_refusal = [t for t in AXIS_TOWARD_REFUSAL if t in words]
    hit_entry = [t for t in AXIS_TOWARD_ENTRY if t in words]
    if hit_refusal and not hit_entry:
        return DIR_REFUSAL, f"ось {hit_refusal[0]!r}: больше = ближе к отказу"
    if hit_entry and not hit_refusal:
        return DIR_ENTRY, f"ось {hit_entry[0]!r}: больше = ближе ко входу"
    if hit_entry and hit_refusal:
        return DIR_UNCHECKED, (f"осей две сразу ({hit_entry[0]!r} и "
                               f"{hit_refusal[0]!r}) — направление не определено")
    return DIR_UNCHECKED, "ось не опознана по именам — направление не измерено"


def _label_keys_in(node: ast.AST) -> list[str]:
    """Поля-метки «это подставлено», видимые в узле."""
    found: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            for k in sub.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str) \
                        and k.value in LABEL_KEYS and k.value not in found:
                    found.append(k.value)
    return found


# ────────────────────────── замер 1: перепись ────────────────────────────────

def census(root: Path) -> list[dict[str, Any]]:
    """Все подстановки дерева. НЕ ответ на вопрос заказа — только население."""
    rows: list[dict[str, Any]] = []
    for sub in SCAN_ROOTS:
        for path in _iter_py(root, sub):
            tree = _parse(path)
            if tree is None:
                continue
            consts = module_constants(tree)
            rel = path.relative_to(root).as_posix()
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                seen: set[tuple[str, int]] = set()
                for form, value, line in absence_sites(fn):
                    ok, why = plausible_value(value, consts)
                    if not ok or (fn.name, line) in seen:
                        continue
                    seen.add((fn.name, line))
                    labels = _label_keys_in(value) or _label_keys_in(fn)
                    # Имя ФАЙЛА осью не считается намеренно: оно называет
                    # предмет модуля, а не величину, и как источник оси даёт
                    # шум (`portfolio_rebalancer` ≠ «баланс»).
                    direction, dir_why = direction_of(fn.name, *_dict_keys(value))
                    rows.append({
                        "file": rel, "func": fn.name, "line": line,
                        "form": form, "value": why,
                        "direction": direction, "direction_why": dir_why,
                        "labelled": bool(labels), "labels": labels,
                    })
    return rows


def _dict_keys(node: ast.AST) -> list[str]:
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            for k in sub.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.append(k.value)
    return out


# ───────────────── замер 2: подстановочные константы по ИМЕНИ ────────────────

def substitution_constants(root: Path) -> list[dict[str, Any]]:
    """Константы, чьё ИМЯ само объявляет их заменой, а значение правдоподобно.

    Вторая половина замера, и она нужна: перепись веток ловит форму, но не
    ловит подстановку, спрятанную за вызовом (``_build_safe_fallback_positions``
    в ветке отвергнутой валидации — именно такой случай, и он оказался главной
    находкой). Имя даёт АВТОР — это объявление, а не вывод.
    """
    rows: list[dict[str, Any]] = []
    for sub in SCAN_ROOTS:
        for path in _iter_py(root, sub):
            tree = _parse(path)
            if tree is None:
                continue
            rel = path.relative_to(root).as_posix()

            def scan(body: list[ast.stmt], cls: Optional[str] = None) -> None:
                for n in body:
                    if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
                        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                        for t in targets:
                            if not isinstance(t, ast.Name):
                                continue
                            if not any(tok in t.id.upper() for tok in SUBSTITUTION_TOKENS):
                                continue
                            ok, why = plausible_value(n.value, {})
                            if not ok:
                                continue
                            direction, dir_why = direction_of(t.id, cls or "")
                            rows.append({
                                "file": rel, "name": t.id, "line": n.lineno,
                                "class": cls, "value": why,
                                "direction": direction, "direction_why": dir_why,
                            })
                    elif isinstance(n, ast.ClassDef):
                        scan(n.body, n.name)

            scan(list(tree.body))
    return rows


# ───── ловушка 3: провенанс ОТ ПОТРЕБИТЕЛЯ НАЗАД, до неподвижной точки ───────

def _first_party_imports(tree: ast.AST) -> list[str]:
    out: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.append(n.module)
            out += [f"{n.module}.{a.name}" for a in n.names]
    return [m for m in out if m.split(".")[0] in SCAN_ROOTS]


def import_closure(root: Path, seeds: Iterable[str]) -> set[str]:
    """Замыкание импортов до НЕПОДВИЖНОЙ ТОЧКИ от seed-модулей.

    Обход идёт по ВСЕМУ дереву модуля, включая импорты внутри функций: в этой
    системе отложенный импорт — обычный приём обхода стены инварианта #6, и
    считать его несуществующим значило бы занизить достижимость.
    """
    closure: set[str] = set()
    queue = [m for m in seeds]
    while queue:
        mod = queue.pop()
        if mod in closure:
            continue
        closure.add(mod)
        path = _path_of(root, mod)
        if path is None:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for imp in _first_party_imports(tree):
            if imp not in closure and _path_of(root, imp) is not None:
                queue.append(imp)
    return closure


def _string_constants(tree: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def artifact_channel(root: Path, decision_closure: set[str],
                     stages: Any) -> list[dict[str, str]]:
    """Продукты ЧУЖИХ ступеней, которые читает замыкание решения.

    Второй канал провенанса, и в этой системе — главный. Аллокатор не
    импортирует адаптеры: он читает их СНИМОК. Замер только импортом ответил бы
    «до решения не доходит ничего», и это был бы верный ответ на не тот вопрос.
    """
    out: list[dict[str, str]] = []
    products = {s.product: s for s in stages
                if getattr(s, "product", "") and s.key not in DECISION_STAGE_KEYS}
    for mod in sorted(decision_closure):
        path = _path_of(root, mod)
        if path is None:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        strings = _string_constants(tree)
        for product, stage in products.items():
            stem = product.split("{")[0]
            if not stem:
                continue
            if any(stem in s for s in strings):
                key = (product, stage.module, mod)
                if not any((r["product"], r["producer"], r["reader"]) == key for r in out):
                    out.append({"product": product, "producer": stage.module,
                                "reader": mod, "producer_stage": stage.key})
    return out


# ── замер 5: поле-спутник, ПЕРЕЖИВШЕЕ подстановку ────────────────────────────

def _names_read(node: ast.AST) -> set[str]:
    """Все имена, ЧИТАЕМЫЕ выражением.

    ``round(result.expected_apy, 4)`` читает ``result`` — и это ровно тот
    случай, на котором первая редакция замера промахнулась: она брала
    «корневое имя» и получала ``round``, то есть имя встроенной функции вместо
    источника величины.
    """
    return {n.id for n in ast.walk(node)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def stale_companions(tree: ast.AST) -> list[dict[str, Any]]:
    """Поля артефакта, ПЕРЕЖИВШИЕ подстановку заменённой ими величины.

    Общее правило класса, шире своего повода: **подстановка обязана уносить с
    собой все производные заменённого значения.**

    Признак измеряемый и узкий, и узость здесь — не осторожность, а
    правильность. Недостаточно «поле читает имя, связанное до ветки»: под это
    подходит и отметка времени, и ключ протокола, и первая редакция замера дала
    именно такой мусор — десять «находок», из которых настоящей не было ни
    одной, а настоящая была пропущена. Признак: поле читает имя ``Q``, ИЗ
    КОТОРОГО происходила ЗАМЕНЁННАЯ величина до подстановки. Тогда после
    подстановки поле описывает источник, к записанной величине уже не
    относящийся.

    Найдено на ``portfolio_rebalancer``: цель тюнера отвергнута валидатором,
    книга подставлена из ``_SAFE_FALLBACK_POSITIONS`` — а ``tuner_expected_apy``
    уезжает в артефакт из ``result``, то есть из ОТВЕРГНУТОЙ аллокации, и
    стои́т рядом с книгой, которой не описывает.
    """
    out: list[dict[str, Any]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for branch in ast.walk(fn):
            if not isinstance(branch, ast.If):
                continue
            b_line = branch.lineno
            rebound: set[str] = set()
            for stmt in ast.walk(branch):
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    tg = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    for t in tg:
                        rebound |= {n.id for n in ast.walk(t)
                                    if isinstance(n, ast.Name)}
            # Быстрый выход, ЭКВИВАЛЕНТНЫЙ проверке ниже (замер приёмки #521):
            # ключи `origin` — это `targets & rebound`, поэтому пустой `rebound`
            # даёт пустой `origin`, и `if not origin` сказал бы то же самое.
            # Мутация, снимающая эту строку, ВЫЖИВАЕТ и обязана выживать —
            # сцены у неё нет и быть не может; названо вслух, чтобы следующая
            # приёмка не искала несуществующий пробел.
            if not rebound:
                continue
            # источник КАЖДОЙ заменённой величины ДО подстановки
            origin: dict[str, set[str]] = {}
            for stmt in ast.walk(fn):
                if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) \
                        or stmt.lineno >= b_line or stmt.value is None:
                    continue
                tgts = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                targets = {n.id for t in tgts for n in ast.walk(t)
                           if isinstance(n, ast.Name)}
                for name in targets & rebound:
                    origin.setdefault(name, set()).update(_names_read(stmt.value))
            if not origin:
                continue
            # Имя-источник обязано быть ПРОИЗВОДНЫМ локальным, а не параметром.
            # Параметр на обеих ветках один и тот же ПО ПОСТРОЕНИЮ (капитал не
            # меняется от того, что раскладку подставили), и считать его
            # «пережившим подстановку» значило бы покрасить здоровый код —
            # ровно ложная находка, которую дала первая редакция признака.
            params = {a.arg for a in
                      list(getattr(fn.args, "posonlyargs", [])) + list(fn.args.args)
                      + list(fn.args.kwonlyargs)}
            derived: set[str] = set()
            for stmt in ast.walk(fn):
                if isinstance(stmt, (ast.Assign, ast.AnnAssign)) \
                        and stmt.lineno < b_line \
                        and isinstance(stmt.value, ast.Call):
                    tg = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    derived |= {n.id for t in tg for n in ast.walk(t)
                                if isinstance(n, ast.Name)}
            derived -= params
            if not derived:
                continue
            # Имя, которое читает и САМА подстановка, входом ОБЕИХ ветвей
            # является и подстановку не «переживает». В аллокаторе так
            # устроен ключ протокола: он читается и до ветки, и в ней, и
            # объявить его пережившим значило бы дать вторую ложную находку —
            # ту же по природе, что параметр.
            branch_reads: set[str] = set()
            for stmt in branch.body + branch.orelse:
                branch_reads |= _names_read(stmt)
            # Второй быстрый выход, ЭКВИВАЛЕНТНЫЙ вычитанию `- branch_reads`
            # в самом вердикте ниже (замер приёмки #521): если КАЖДОЕ
            # производное имя читается веткой, то и `stale` каждого поля пуст.
            # Мутация этой строки тоже выживает по построению.
            if not (derived - branch_reads):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Dict) or node.lineno <= b_line:
                    continue
                pairs = [(k.value, v) for k, v in zip(node.keys, node.values)
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                carried = {p: k for k, v in pairs for p in origin
                           if p in _names_read(v)}
                if not carried:
                    continue
                sources = set().union(*(origin[p] for p in carried))
                for key, value in pairs:
                    if key in carried.values():
                        continue
                    stale = ((_names_read(value) & sources & derived)
                             - rebound - branch_reads)
                    for q in sorted(stale):
                        out.append({
                            "func": fn.name, "branch_line": b_line,
                            "dict_line": node.lineno,
                            "substituted": sorted(carried),
                            "stale_field": key, "reads": q,
                        })
    return out


# ───────────────────────────── сборка замера ─────────────────────────────────

def _stages() -> tuple[Any, ...]:
    """Ступени берутся из карты компонентов, а не заводятся своей копией (§3)."""
    from spa_core.monitoring.cio_component_map import STAGES
    return STAGES


def measure(root: Path, stages: Optional[tuple[Any, ...]] = None) -> dict[str, Any]:
    """Полный замер класса «подстановка вместо отказа»."""
    if stages is None:
        try:
            stages = _stages()
        except Exception as exc:                                   # pragma: no cover
            return {
                "status": "UNCHECKED",
                "unchecked_reason": (
                    f"состав ступеней решения недоступен "
                    f"({exc.__class__.__name__}) — своей копии таблицы здесь нет "
                    f"намеренно (§3 ТЗ), поэтому замер отказывает громко"
                ),
            }

    by_key = {s.key: s for s in stages}
    missing = [k for k in DECISION_STAGE_KEYS if k not in by_key]
    if missing:
        return {
            "status": "UNCHECKED",
            "unchecked_reason": (
                "в карте компонентов нет ступен(и/ей) решения: "
                + ", ".join(missing)
                + " — достижимость мерить не от чего"
            ),
        }

    seeds = [_module_dotted(by_key[k].module) for k in DECISION_STAGE_KEYS]
    dec_closure = import_closure(root, seeds)
    artifacts = artifact_channel(root, dec_closure, stages)
    art_closure = import_closure(root, [_module_dotted(a["producer"]) for a in artifacts])
    reachable_mods = dec_closure | art_closure

    def channels(rel: str) -> list[str]:
        mod = _module_dotted(rel)
        out = []
        if mod in dec_closure:
            out.append("импорт")
        if mod in art_closure:
            out.append("артефакт")
        return out

    all_rows = census(root)
    all_consts = substitution_constants(root)

    reach_rows = [dict(r, channels=channels(r["file"]))
                  for r in all_rows if channels(r["file"])]
    reach_consts = [dict(c, channels=channels(c["file"]))
                    for c in all_consts if channels(c["file"])]

    # Обратная сторона: двигающие к ОТКАЗУ — не этот класс.
    def split(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return {
            "toward_entry": [r for r in rows if r["direction"] == DIR_ENTRY],
            "toward_refusal": [r for r in rows if r["direction"] == DIR_REFUSAL],
            "unchecked": [r for r in rows if r["direction"] == DIR_UNCHECKED],
        }

    # Поля-спутники — только у ступеней решения (там, где артефакт и есть ход).
    companions: list[dict[str, Any]] = []
    for key in DECISION_STAGE_KEYS:
        rel = by_key[key].module
        path = root / rel
        tree = _parse(path) if path.is_file() else None
        if tree is None:
            continue
        for row in stale_companions(tree):
            companions.append(dict(row, file=rel, stage=key))

    reach_split = split(reach_rows)
    unlabelled_entry = [r for r in reach_split["toward_entry"] if not r["labelled"]]

    return {
        "status": "MEASURED",
        "census": {
            "substitutions": len(all_rows),
            "files": len({r["file"] for r in all_rows}),
            "by_form": {f: sum(1 for r in all_rows if r["form"] == f)
                        for f in ABSENCE_FORMS},
            "constants": len(all_consts),
            "constant_files": len({c["file"] for c in all_consts}),
        },
        "closure": {
            "decision_stages": list(DECISION_STAGE_KEYS),
            "import_modules": len(dec_closure),
            "artifact_modules": len(art_closure),
            "modules": len(reachable_mods),
            "artifact_edges": artifacts,
        },
        "reachable": {
            "substitutions": reach_rows,
            "constants": reach_consts,
            "by_direction": {k: len(v) for k, v in reach_split.items()},
            "unlabelled_toward_entry": unlabelled_entry,
        },
        "stale_companions": companions,
    }


# ───────────────────────── находки и отчёт ───────────────────────────────────

def _findings(meas: dict[str, Any]) -> list[dict[str, str]]:
    if meas.get("status") != "MEASURED":
        return [{"severity": "UNCHECKED",
                 "text": meas.get("unchecked_reason", "замер не состоялся")}]

    out: list[dict[str, str]] = []
    cen, reach = meas["census"], meas["reachable"]
    clo = meas["closure"]

    out.append({"severity": "INFO", "text": (
        f"перепись: {cen['substitutions']} подстановок в {cen['files']} файлах; "
        f"подстановочных констант с объявляющим именем — {cen['constants']} "
        f"в {cen['constant_files']} файлах. Это НАСЕЛЕНИЕ, а не находка: "
        f"счёт мест на вопрос заказа не отвечает")})

    out.append({"severity": "INFO", "text": (
        f"замыкание от решения до неподвижной точки: {clo['import_modules']} "
        f"модул(ь/я/ей) каналом импорта + {clo['artifact_modules']} каналом "
        f"артефакта = {clo['modules']}; рёбер-артефактов "
        f"{len(clo['artifact_edges'])}. Канал артефакта здесь главный: "
        f"аллокатор не импортирует адаптеры, он читает их снимок")})

    for row in reach["unlabelled_toward_entry"]:
        out.append({"severity": "CRITICAL", "text": (
            f"{row['file']}:{row['line']} `{row['func']}` подставляет "
            f"{row['value']} в ветке отсутствия ({row['form']}); "
            f"{row['direction_why']}, и МЕТКИ «это подставлено» рядом нет — "
            f"потребитель не отличит подстановку от наблюдения. "
            f"Канал: {'+'.join(row['channels'])}")})

    for row in reach["substitutions"]:
        if row["direction"] == DIR_REFUSAL:
            out.append({"severity": "INFO", "text": (
                f"{row['file']}:{row['line']} `{row['func']}` — подстановка "
                f"достижима, но {row['direction_why']}: это ОБРАТНАЯ сторона "
                f"класса (консервативное значение), не находка")})
        elif row["direction"] == DIR_UNCHECKED:
            out.append({"severity": "UNCHECKED", "text": (
                f"{row['file']}:{row['line']} `{row['func']}` — подстановка "
                f"достижима, но {row['direction_why']}; называть её находкой "
                f"или оправдывать одинаково нечем")})
        elif row["labelled"]:
            out.append({"severity": "INFO", "text": (
                f"{row['file']}:{row['line']} `{row['func']}` — подстановка "
                f"достижима и двигает ко входу, НО помечена "
                f"({', '.join(row['labels'])}): потребитель СПОСОБЕН отказать")})

    for c in reach["constants"]:
        sev = "WARN" if c["direction"] != DIR_REFUSAL else "INFO"
        out.append({"severity": sev, "text": (
            f"{c['file']}:{c['line']} `{c['name']}` — константа, чьё имя само "
            f"объявляет её заменой ({c['value']}), достижима от решения "
            f"каналом {'+'.join(c['channels'])}; {c['direction_why']}")})

    for comp in meas["stale_companions"]:
        out.append({"severity": "CRITICAL", "text": (
            f"{comp['file']}:{comp['dict_line']} ступень `{comp['stage']}`: "
            f"подстановка в ветке строки {comp['branch_line']} заменила "
            f"{', '.join(comp['substituted'])}, а поле `{comp['stale_field']}` "
            f"того же артефакта читает `{comp['reads']}` — величину, связанную "
            f"ДО ветки и подстановкой НЕ заменённую. Поле описывает то, чего в "
            f"артефакте нет: подстановка обязана уносить с собой ВСЕ "
            f"производные заменённого значения")})

    return out


def status_of(findings: list[dict[str, str]]) -> str:
    sev = {f["severity"] for f in findings}
    if "CRITICAL" in sev:
        return "CRITICAL"
    if "UNCHECKED" in sev:
        return "UNCHECKED"
    if "WARN" in sev:
        return "WARN"
    return "OK"


def run(root: Optional[str | Path] = None, *, write: bool = True,
        now: Optional[datetime] = None) -> dict[str, Any]:
    """Замерить и (по умолчанию) записать отчёт."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    meas = measure(base)
    findings = _findings(meas)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    counts = {k.lower(): sum(1 for f in findings if f["severity"] == k)
              for k in ("CRITICAL", "WARN", "INFO", "UNCHECKED")}
    doc = {
        "generated_at": stamp,
        # `overall` — имя семейства cio_*; `positive_control` объявлен рядом с
        # вердиктом намеренно: без пройденного контроля «находок нет» означает
        # не чистое дерево, а неисправный измеритель.
        "overall": status_of(findings),
        "positive_control": positive_control(),
        "counts": counts,
        "question": ("где функция, не сумевшая получить вход, возвращает "
                     "правдоподобное число вместо отказа — и доходит ли хоть "
                     "одно такое число до решения о капитале"),
        "advisory": ("ADVISORY: ни один вызов не изменён, ни одна подстановка "
                     "не удалена, пороги RiskPolicy не тронуты — правка любого "
                     "найденного места это money-path и решение владельца"),
        "measurement": meas,
        "findings": findings,
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        out = base / REPORT_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(out))
    return doc


def positive_control() -> dict[str, Any]:
    """Положительный контроль: замер обязан отличать четыре вещи.

    Проверка, никогда не видевшая настоящей поломки, — украшение
    (`.claude/rules/deployment.md`). Здесь контроль воспроизводит ровно те
    четыре различения, на которых замер держится, и каждое взято из реальной
    ошибки первых редакций этого же прибора.
    """
    consts: dict[str, tuple[bool, str]] = {}
    cases = {
        # ловушка 1: метка отсутствия — НЕ подстановка
        "absence_marker_is_not_substitution": not plausible_value(
            ast.parse("None", mode="eval").body, consts)[0],
        "zero_is_not_substitution": not plausible_value(
            ast.parse("0", mode="eval").body, consts)[0],
        "empty_container_is_not_substitution": not plausible_value(
            ast.parse("{}", mode="eval").body, consts)[0],
        "plausible_number_is_substitution": plausible_value(
            ast.parse("4.2", mode="eval").body, consts)[0],
        # ловушка 2: ветка НАЛИЧИЯ не считается
        "threshold_ladder_is_not_absence": not list(absence_sites(
            ast.parse("def f(x):\n    if x > 0.5:\n        return 22.0\n"
                      "    return 1.0\n").body[0])),
        "absence_branch_is_absence": any(
            f == FORM_IS_NONE for f, _, _ in absence_sites(
                ast.parse("def f(x):\n    if x is None:\n        return 4.2\n"
                          "    return x\n").body[0])),
        # уточнение ловушки 1: дефолт необязательного параметра — не подстановка
        "optional_param_default_is_not_substitution": not any(
            True for _ in absence_sites(ast.parse(
                "def f(t=None):\n    return t if t is not None else 30\n"
            ).body[0])),
        # обратная сторона: движение к отказу — не этот класс
        "cost_axis_moves_toward_refusal":
            direction_of("_move_cost_usd")[0] == DIR_REFUSAL,
        "apy_axis_moves_toward_entry":
            direction_of("fallback_apy")[0] == DIR_ENTRY,
        "unknown_axis_is_third_outcome":
            direction_of("zzz_unknown")[0] == DIR_UNCHECKED,
        # замер 5: спутник, переживший подстановку
        "stale_companion_is_seen": bool(stale_companions(ast.parse(
            "def w():\n"
            "    result = tune()\n"
            "    positions = to_usd(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "    doc = {'positions': positions,\n"
            "           'expected_apy': result.expected_apy}\n"
            "    return doc\n"))),
        "companion_replaced_is_not_seen": not stale_companions(ast.parse(
            "def w():\n"
            "    result = tune()\n"
            "    positions = to_usd(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "        result = describe(positions)\n"
            "    doc = {'positions': positions,\n"
            "           'expected_apy': result.expected_apy}\n"
            "    return doc\n")),
    }
    return {"passed": all(cases.values()),
            "cases": {k: bool(v) for k, v in cases.items()}}


def main() -> int:
    doc = run()
    print(f"подстановка вместо отказа: {doc['overall']} "
          f"(critical={doc['counts']['critical']} warn={doc['counts']['warn']} "
          f"info={doc['counts']['info']} unchecked={doc['counts']['unchecked']})")
    for f in doc["findings"]:
        print(f"   [{f['severity']}] {f['text']}")
    print(f"   {doc['advisory']}")
    return {"CRITICAL": 2, "UNCHECKED": 2, "WARN": 1, "OK": 0}[doc["overall"]]


if __name__ == "__main__":                                        # pragma: no cover
    raise SystemExit(main())
