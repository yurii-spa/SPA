"""Одно правило — две копии: перепись пар «исполнитель × сторож».

Заказ **G41, п. 1** приказа владельца «Portfolio CIO» (хвост ADR-416).

## Вопрос, на который прибор отвечает

ADR-416 закрыл ОДИН экземпляр класса: храповик приёмки
(`spa_core/tests/test_inbox_acceptance_ratchet.py`) судил карточку своей копией
правила, а отказывала карточке ДРУГАЯ копия — в исполнителе
(`spa_core.owner_queue.queue.set_status`). Копии разошлись, и красным стал
`main` при ВЕРНОМ состоянии дерева. Заказ поставил вопрос шире и отдельным
циклом: *«У скольких правил этого репозитория есть ИСПОЛНИТЕЛЬ (очередь, гейт)
и СТОРОЖ (тест), проверяющие одно и то же условие РАЗНЫМ кодом?»*

Прибор отвечает переписью, а не догадкой, и дописывать условия по одному
запрещено самим заказом: список лечил бы поводы.

## Что считается ОДНИМ правилом в двух копиях

Координата — **имя верхнего уровня с КОНСТАНТНЫМ значением**, объявленное и у
сторожа, и у исполнителя. Пара попадает в находку, когда

1. имя совпало;
2. **значение совпало** после нормализации (`ast.unparse`);
3. исполнитель у имени **ровно один** — иначе имя не называет одно правило;
4. сторож **не достаёт** исполнителя ни одной из четырёх дверей (ниже).

Тогда правка значения у исполнителя не краснит сторожа, а правка у сторожа не
краснит ничего: копии расходятся молча, и обе стороны выглядят исправно.

## Почему имени МАЛО — это замер, а не осторожность

Первая редакция этого прибора связывала копии по одному имени. Замер на дереве
`c32b997b`: **49 249** пар, из них `ROOT` — 19 118, `main` — 12 599,
`run` — 5 440. Такое имя есть соглашение об именовании, а не правило; связывать
по нему значит объявить находкой каждый модуль репозитория. Требование равного
КОНСТАНТНОГО значения оставляет 14 пар — и вред у каждой ровно тот, что описан
выше: числу/множеству есть где разойтись.

Обратная сторона сказана вслух: равенство значения — условие НЕОБХОДИМОЕ и не
достаточное. `SEED = 42` у теста и у `monte_carlo` может быть совпадением
двух независимых решений. Прибор называет пару, а не выносит приговор её
происхождению.

## Четыре двери к исполнителю, и проверять надо ВСЕ

Сторож может достать исполнителя не только `import`. Считать дверью только
ввоз значило бы выдумать находку у теста, который честно зовёт исполнителя
подпроцессом:

* `import spa_core.x.y` / `from spa_core.x.y import …`;
* загрузка по ПУТИ (`spec_from_file_location`, `SourceFileLoader`) — путь
  модуля стоит строковым литералом;
* подпроцесс `python3 -m spa_core.x.y` — имя модуля стоит литералом;
* `sys.path` + ввоз по короткому имени — тот же литерал имени модуля.

Все четыре ищутся по ТЕКСТУ модульного пути и точечного имени: дверь опознаётся
по тому, что исполнитель НАЗВАН, а не по форме зова.

## Слепота правила имени ИЗМЕРЕНА, а не обещана

Копия, которую **переименовали**, правилу имени невидима навсегда. Ровно так
выглядит второй половина экземпляра ADR-416: `has_acceptance_criterion`
у исполнителя против `has_criterion` у сторожа, `_carried_ok` против
`carried_home` — одно условие, разные имена. Поэтому поверхность считается
ОТДЕЛЬНО: сторожа, которые трогают состояние репозитория и при этом не достают
дерево-предмет НИ ОДНОЙ из четырёх дверей. У такого сторожа копия правила своя
**по построению** — это доказательство, а не эвристика; число ограничивает
класс сверху и существует затем, чтобы «мы не нашли» не читалось как «их нет».

## Три исхода различимы (инв. #17) и учёт тождественен

* `scanned == classified + unreadable` — закреплено тестом, вход нельзя уронить
  молча;
* имя с ДВУМЯ и более исполнителями не находка и не «сошлось», а отдельная
  корзина `ambiguous_executor`;
* значение неконстантно хотя бы у одной стороны ⇒ `not_constant` — «сравнить
  было нечем», а не «различаются»;
* корень населения не прочитан ⇒ `UNMEASURED` и ненулевой код возврата.

## Чего перепись НЕ доказывает

* **Что у найденной пары копия вредна СЕГОДНЯ.** Вред приходит с правкой одной
  из копий; перепись мерит поверхность, а не список аварий.
* **Что совпавшее значение имеет общее происхождение.** См. выше про `SEED`.
* **Что население полно.** Переименованная копия невидима; ширина названа
  числом `renamed_copy_surface`, и это **доказанный минимум, а не потолок**:
  сторож, ни разу не упомянувший дерево-предмет, копию держит наверняка, но
  сторож, упомянувший его в одной строке докстринга, в поверхность не войдёт,
  хотя копию держать может. Ошибка направлена в безопасную сторону — число
  не даёт права сказать «больше нет».
* **Что сторож из `delegates` не держит ВТОРОЙ копии рядом.** Дверь к
  исполнителю найдена — значит копия достижима; пользуется ли сторож ею у
  КАЖДОГО условия, прибор не спрашивает.
* **Что у пары `subject_unproven` предмет РАЗНЫЙ.** Свидетель односторонний
  (ниже); «не доказан» — третий исход, а не «совпадение».

## Форма починки — замер, а не глаз (заказ **G42, п. 1**)

Заказ приказал разделить находки по двум формам починки ЗАМЕРОМ и чинить
формами, а не по одной. Разделение стоит на двух вопросах, и порядок их
важен, потому что первый — про границу владельца, а не про удобство.

**1. Не лежит ли величина у порога RiskPolicy?** Значение находки сверяется с
ЧИСЛОВЫМИ порогами, объявленными в `spa_core/risk/policy.py` (верхний уровень
и умолчания полей). Совпало ⇒ `owner_subject`: предмет №1 границы
[ADR-285](../../docs/decisions/ADR-285-owner-boundary-by-subject.md), агент
такую пару НЕ чинит. Замер 19.09 нашёл ровно её: `MIN_CASH = 0.05`
(`spa_core/backtesting/tier1/limits.py`) стои́т рядом с `min_cash_pct = 0.05`
у RiskPolicy — одна ли это величина или две одинаковых, решает владелец.
Сверка одностороння НАМЕРЕННО: равенство числа не доказывает общего
происхождения, но ошибается в сторону «спросить», а не «починить молча».
Пороги не прочитаны ⇒ `UNMEASURED`, а не «совпадений нет».

**2. Назвал ли один сторону другую?** Свидетель общего предмета — ТЕКСТ:
сторож (или исполнитель) упоминает файл другой стороны по имени модуля
(`owner_queue.queue`) или по имени файла (`baseanalytics_migration_summary.py`)
где угодно, включая комментарий и докстринг. Это слабее двери из `reaches`
(упоминание исполнителем НЕ является) и ровно поэтому годится в свидетели:
сторож, который ЗНАЕТ про чужую копию и всё равно держит свою, копией правила
владеет заведомо. Назвал ⇒ `single_copy_by_import`: копий становится одна
ввозом, правка на строку.

**Не назвал ⇒ `subject_unproven`, и это третий исход, а не «совпадение».**
Замер 19.09: `tests/test_preflight.py` дословно повторяет константы
`scripts/preflight_day1.py` (`EXPECTED_START_DATE`, `MIN_ADAPTERS`) и нигде
его не называет — свидетеля нет, и объявить пару совпадением было бы неправдой
той же природы, что объявить её копией. Такая пара НЕ чинится и стои́т в
отчёте поимённо.

**Заказ ждал ДВУХ форм починки, замер даёт ОДНУ.** Разделение «сторож ввозит
константу» против «сторож спрашивает перечень у исполнителя» на доказанном
населении не даёт разных правок: перечень модулей `PHASE_1/2/3` спрашивается
у исполнителя тем же ввозом, каким берётся `INTAKE_STATUSES`. Формой здесь
оказалась не разница в починке, а разница в ПРАВЕ чинить (п. 1 выше).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "rule_second_copy_census.json"
#: Какой МОДУЛЬ собрал документ (константа; на вопрос «кто позвал» отвечает
#: `invoked_by` — ADR-412, это разные вопросы).
PRODUCER = "spa_core/monitoring/rule_second_copy_census.py"

#: Каталоги сторожей — РОВНО те, что гейтят CI (`CLAUDE.md`, предписанный
#: прогон). Сторож — файл, который pytest СОБИРАЕТ, то есть `test_*.py`:
#: модуль рядом с тестами, который pytest не собирает, ничего не сторожит.
GUARD_DIRS = ("tests", "spa_core/tests", "scripts/tests",
              "research/cards", "spa_core/analytics/gross_of")
#: Каталоги исполнителей — два дерева рабочего кода этого репозитория.
EXECUTOR_DIRS = ("spa_core", "scripts")
#: `scripts/archive/` — отставленный код: правило оттуда никого не гейтит.
_EXECUTOR_SKIP = ("scripts/archive/",)

#: Конструкторы контейнеров, при которых значение остаётся константным:
#: `frozenset({...})` есть запись множества, а не вычисление.
_CONST_CTORS = frozenset({"frozenset", "set", "tuple", "dict", "list"})

CLASS_TWO_COPIES = "two_copies"
CLASS_DELEGATES = "delegates"
CLASS_VALUE_DIFFERS = "value_differs"
CLASS_NOT_CONSTANT = "not_constant"
CLASS_AMBIGUOUS = "ambiguous_executor"
_FINDING_CLASSES = (CLASS_TWO_COPIES,)

#: Модуль, объявляющий пороги RiskPolicy v1.0. Величина, равная одному из них,
#: есть предмет №1 границы ADR-285 и агентом не чинится.
RISK_POLICY_MODULE = "spa_core/risk/policy.py"

#: Форма починки находки (заказ G42 п. 1). Порядок объявления — порядок
#: разбора: право чинить спрашивается ПЕРВЫМ.
REMEDY_OWNER = "owner_subject"
REMEDY_IMPORT = "single_copy_by_import"
REMEDY_UNPROVEN = "subject_unproven"
REMEDY_UNREADABLE = "remedy_unreadable"
_REMEDY_CLASSES = (REMEDY_OWNER, REMEDY_IMPORT, REMEDY_UNPROVEN, REMEDY_UNREADABLE)

#: След состояния репозитория в тексте сторожа. Нужен только для ПОВЕРХНОСТИ
#: слепоты: сторож, который ничего из репозитория не читает, своей копии
#: правила и не держит.
_REPO_STATE_MARKS = ("nimbalyst-local", "data/", "docs/", "landing/",
                     "architecture/", "KANBAN", ".claude/")


class NotMeasured(RuntimeError):
    """Корень населения не прочитан — третий исход, а не пустая перепись."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def const_value(node: ast.AST) -> Optional[str]:
    """Нормализованный исходник значения — или ``None``, если оно не константно.

    Константным считается выражение без единого обращения наружу: ни вызова
    (кроме конструктора контейнера), ни имени, ни атрибута, ни подписки, ни
    f-строки, ни включения. `Path(__file__).resolve()` константой не является
    и сравнивать его с чужим `Path(...)` было бы сравнением ТЕКСТА, а не
    значения — отсюда корзина ``not_constant``, а не «различаются».
    """
    for sub in ast.walk(node):
        # Отдельной ветки на `ast.Call` здесь НЕТ, и это решение, а не пропуск:
        # у любого вызова функция есть либо имя, либо атрибут, либо лямбда — то
        # есть отвергается ветками ниже. Ветка на `Call` отвергала бы то же
        # самое на узел раньше, и батарея мутаций показала её выживающей:
        # неотличимая от умолчания проверка есть украшение, а не сторож.
        if isinstance(sub, ast.Name):
            if sub.id in _CONST_CTORS:
                continue
            return None
        if isinstance(sub, (ast.Attribute, ast.Subscript, ast.Lambda, ast.JoinedStr,
                            ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
                            ast.Await, ast.Starred)):
            return None
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 — ast.unparse на экзотике
        return None


def toplevel_constants(tree: ast.Module) -> Dict[str, Optional[str]]:
    """Имена верхнего уровня и их значения (``None`` — значение не константно).

    Только верхний уровень: константа внутри функции никому не видна и второй
    копией правила быть не может.
    """
    out: Dict[str, Optional[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = const_value(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            out[node.target.id] = const_value(node.value)
    return out


def imported_modules(tree: ast.Module) -> set:
    """Полные имена модулей, которые файл ВВОЗИТ, включая форму `from pkg import mod`.

    Разбирать ввоз текстом нельзя: `from spa_core.backtesting.tier1 import
    monte_carlo` не содержит строки «spa_core.backtesting.tier1.monte_carlo»
    ни разу, и текстовое правило объявило бы такого сторожа НЕ достающим
    исполнителя — то есть выдумало бы находку ровно там, где сторож честно
    делегирует. Имя собирается из модуля и КАЖДОГО псевдонима: какой из них
    подмодуль, а какой — имя внутри модуля, по одному тексту не различить,
    поэтому в набор кладутся оба прочтения.
    """
    out: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            out.add(node.module)
            for alias in node.names:
                out.add(f"{node.module}.{alias.name}")
    return out


def reaches(source: str, imported: set, module_rel: str) -> bool:
    """Достаёт ли сторож исполнителя ХОТЬ ОДНОЙ из четырёх дверей.

    Дверь опознаётся по тому, что исполнитель НАЗВАН, а не по форме зова:

    * ввоз — разбором AST (`imported_modules`), а не текстом;
    * загрузка по ПУТИ (`spec_from_file_location`, `SourceFileLoader`) — путь
      модуля стоит строковым литералом;
    * подпроцесс `python3 -m spa_core.x.y` — точечное имя стоит литералом;
    * `sys.path` + ввоз по короткому имени — тот же литерал.

    Проверять только `import` значило бы выдумать находку у теста, который
    честно зовёт исполнителя подпроцессом.
    """
    dotted = module_rel[:-3].replace("/", ".") if module_rel.endswith(".py") else module_rel
    if dotted in imported:
        return True
    return dotted in source or module_rel in source


def risk_policy_thresholds(root: Path) -> Dict[str, List[str]]:
    """Числовой порог RiskPolicy -> ВСЕ имена, под которыми он объявлен.

    Имён у одного числа бывает несколько, и называть первое попавшееся нельзя:
    замер 19.09 дал у ``0.05`` сразу три порога — `max_drawdown_stop`,
    `max_var_pct`, `min_cash_pct`. Первая редакция этой функции хранила одно
    имя и приписала бы `MIN_CASH` соседство со стоп-краном вместо буфера кэша,
    то есть соврала бы ровно тем способом, против которого написан весь прибор:
    равенство величины НЕ есть тождество смысла.

    Берутся и константы верхнего уровня, и умолчания полей (пороги живут
    полями датакласса `RiskConfig`, поэтому обходится ВЕСЬ модуль, а не
    `tree.body`). Только числа: порог есть величина, и строковая версия
    политики порогом не является — сверка по ней объявила бы предметом
    владельца каждую пару со значением ``'v1.0'``.

    Модуль не прочитан ⇒ ``NotMeasured``: молча решить, что совпадений с
    порогами нет, значило бы выдать «не измерено» за «чисто» и дать агенту
    право чинить то, что он чинить не вправе.
    """
    path = Path(root) / RISK_POLICY_MODULE
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(
            f"пороги RiskPolicy не прочитаны ({RISK_POLICY_MODULE}): "
            f"{type(exc).__name__}: {exc}") from exc
    out: Dict[str, str] = {}
    for node in ast.walk(tree):
        pairs: List[Tuple[str, ast.AST]] = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            pairs.append((node.target.id, node.value))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    pairs.append((target.id, node.value))
        for name, value_node in pairs:
            if name.startswith("_"):
                continue
            if not (isinstance(value_node, ast.Constant)
                    and isinstance(value_node.value, (int, float))
                    and not isinstance(value_node.value, bool)):
                continue
            text = const_value(value_node)
            if text is not None and name not in out.setdefault(text, []):
                out[text].append(name)
    return {value: sorted(names) for value, names in out.items()}


def subject_witness(text: str, module_rel: str) -> Optional[str]:
    """Называет ли ТЕКСТ файл `module_rel` — по имени модуля или по имени файла.

    Свидетель ОДНОСТОРОННИЙ и слабее двери из :func:`reaches`: упоминание
    исполнителя дверью к нему не является (ADR-417), но доказывает, что о
    чужой копии ЗНАЮТ. Ищется точечный хвост длиной от двух звеньев
    (``owner_queue.queue``) и имя файла (``baseanalytics_migration_summary.py``).

    Граница слева и справа обязательна: голое ``queue.py`` совпало бы внутри
    ``orchestrator_queue.py`` и выдумало бы свидетеля там, где назван СОСЕД.

    **У исполнителя из двух звеньев пути свидетель-хвост СОВПАДАЕТ с дверью**
    (``spa_core/e.py`` → ``spa_core.e``), и такая пара находкой быть перестаёт
    ещё в :func:`reaches` — до разбора форм. Свидетелем там остаётся только имя
    файла. Это не изъян: совпадение означает, что проводка уже есть.
    """
    if not module_rel.endswith(".py"):
        return None
    parts = module_rel[:-3].split("/")
    candidates = [f"{parts[-1]}.py"]
    candidates += [".".join(parts[-n:]) for n in range(2, len(parts) + 1)]
    for cand in candidates:
        if re.search(r"(?<![\w.])" + re.escape(cand) + r"(?![\w])", text):
            return cand
    return None


def classify_remedy(row: dict, *, guard_text: Optional[str],
                    executor_text: Optional[str],
                    thresholds: Dict[str, List[str]]) -> dict:
    """Форма починки одной находки (заказ G42 п. 1). Возвращает поля строки.

    Порядок ветвей — не стилистика: право чинить спрашивается раньше способа
    чинить. Пара, чья величина совпала с порогом RiskPolicy, уходит владельцу
    ДО того, как прибор вообще посмотрит на свидетеля.
    """
    owner_names = thresholds.get(row.get("value")) or []
    if owner_names:
        named = ", ".join(f"`{n}`" for n in owner_names)
        return {"remedy": REMEDY_OWNER, "owner_threshold_names": list(owner_names),
                "remedy_evidence": (
                    f"значение равно порог{'ам' if len(owner_names) > 1 else 'у'} "
                    f"RiskPolicy {named} ({RISK_POLICY_MODULE}) — предмет №1 "
                    f"границы ADR-285; какой из них ТОТ САМЫЙ, прибор не решает")}
    if guard_text is None or executor_text is None:
        side = "guard" if guard_text is None else "executor"
        return {"remedy": REMEDY_UNREADABLE,
                "remedy_evidence": f"текст стороны `{side}` не прочитан повторно"}
    witness = subject_witness(guard_text, row["executor"])
    if witness is not None:
        return {"remedy": REMEDY_IMPORT, "witness_side": "guard",
                "remedy_evidence": f"сторож называет исполнителя: `{witness}`"}
    witness = subject_witness(executor_text, row["guard"])
    if witness is not None:
        return {"remedy": REMEDY_IMPORT, "witness_side": "executor",
                "remedy_evidence": f"исполнитель называет сторожа: `{witness}`"}
    return {"remedy": REMEDY_UNPROVEN,
            "remedy_evidence": ("ни одна сторона не называет другую — общий предмет "
                                "НЕ ДОКАЗАН (это не «совпадение»)")}


def _guard_files(root: Path) -> List[Path]:
    seen: set = set()
    out: List[Path] = []
    for sub in GUARD_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            if path in seen:
                continue
            seen.add(path)
            out.append(path)
    if not out:
        raise NotMeasured(f"в дереве {root} не нашлось ни одного файла-сторожа")
    return out


def _executor_files(root: Path) -> List[Path]:
    out: List[Path] = []
    for sub in EXECUTOR_DIRS:
        base = root / sub
        if not base.is_dir():
            raise NotMeasured(f"каталог исполнителей не прочитан: {base}")
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
                continue
            if any(rel.startswith(skip) for skip in _EXECUTOR_SKIP):
                continue
            if rel == PRODUCER:      # сам прибор исполнителем правил не является
                continue
            out.append(path)
    if not out:
        raise NotMeasured(f"в дереве {root} не нашлось ни одного файла-исполнителя")
    return out


def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    """Перепись пар «сторож × исполнитель × имя»."""
    root = Path(root)
    if not root.is_dir():
        raise NotMeasured(f"корень дерева не прочитан: {root}")

    unreadable: List[dict] = []

    # --- сторона исполнителя: имя -> [(модуль, значение)] --------------------
    executors: Dict[str, List[Tuple[str, Optional[str]]]] = {}
    executor_files = _executor_files(root)
    for path in executor_files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            unreadable.append({"file": rel, "side": "executor",
                               "reason": f"{type(exc).__name__}: {exc}"})
            continue
        for name, value in toplevel_constants(tree).items():
            if name.startswith("_"):
                continue        # приватное имя правилом наружу не является
            executors.setdefault(name, []).append((rel, value))

    # --- сторона сторожа ----------------------------------------------------
    rows: List[dict] = []
    counts = {CLASS_TWO_COPIES: 0, CLASS_DELEGATES: 0, CLASS_VALUE_DIFFERS: 0,
              CLASS_NOT_CONSTANT: 0, CLASS_AMBIGUOUS: 0}
    surface: List[str] = []
    guard_files = _guard_files(root)
    # Пороги спрашиваются ПОСЛЕ корней населения и ДО разбора форм. Порядок
    # обоих отказов измерен тестами: «корень не прочитан» остаётся первым
    # (он отменяет перепись целиком), а «пороги не прочитаны» отменяет право
    # чинить — и ни один из них не выдаётся за пустой результат.
    thresholds = risk_policy_thresholds(root)
    for path in guard_files:
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception as exc:  # noqa: BLE001
            unreadable.append({"file": rel, "side": "guard",
                               "reason": f"{type(exc).__name__}: {exc}"})
            continue

        guard_imports = imported_modules(tree)
        touches_state = any(mark in source for mark in _REPO_STATE_MARKS)

        for name, guard_value in toplevel_constants(tree).items():
            if name.startswith("_") or name.startswith("test_"):
                continue
            side = executors.get(name)
            if not side:
                continue
            if len(side) > 1:
                # Имя, объявленное многими исполнителями, не называет ОДНО
                # правило. Это не находка и не «сошлось» — это своя корзина.
                counts[CLASS_AMBIGUOUS] += 1
                continue
            exec_rel, exec_value = side[0]
            if guard_value is None or exec_value is None:
                counts[CLASS_NOT_CONSTANT] += 1
                continue
            if guard_value != exec_value:
                counts[CLASS_VALUE_DIFFERS] += 1
                continue
            if reaches(source, guard_imports, exec_rel):
                counts[CLASS_DELEGATES] += 1
                continue
            counts[CLASS_TWO_COPIES] += 1
            rows.append({
                "verdict": CLASS_TWO_COPIES,
                "guard": rel,
                "executor": exec_rel,
                "name": name,
                "value": guard_value,
            })

        # Сторож трогает состояние репозитория и НИ ОДНОЙ дверью не достаёт
        # дерева-предмета ⇒ каждое проверяемое им условие — его собственная
        # копия ПО ПОСТРОЕНИЮ. Переименованную копию правило имени не видит
        # никогда, и вот её верхняя граница.
        if touches_state and not _reaches_subject_tree(source):
            surface.append(rel)

    rows.sort(key=lambda r: (r["guard"], r["name"]))

    # --- форма починки у каждой находки (заказ G42 п. 1) --------------------
    remedy_counts = {cls: 0 for cls in _REMEDY_CLASSES}
    text_cache: Dict[str, Optional[str]] = {}

    def _text(rel: str) -> Optional[str]:
        if rel not in text_cache:
            try:
                text_cache[rel] = (root / rel).read_text(encoding="utf-8")
            except OSError:
                text_cache[rel] = None
        return text_cache[rel]

    for row in rows:
        if row["verdict"] not in _FINDING_CLASSES:
            continue
        row.update(classify_remedy(row, guard_text=_text(row["guard"]),
                                   executor_text=_text(row["executor"]),
                                   thresholds=thresholds))
        remedy_counts[row["remedy"]] += 1

    scanned = len(guard_files) + len(executor_files)
    classified = scanned - len(unreadable)
    findings = [r for r in rows if r["verdict"] in _FINDING_CLASSES]
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "FINDING" if findings else "CLEAN",
        "question": "у скольких правил есть ИСПОЛНИТЕЛЬ и СТОРОЖ, проверяющие одно условие РАЗНЫМ кодом",
        "population_rule": (
            "сторож — собираемый pytest файл test_*.py из каталогов предписанного "
            "прогона; исполнитель — не-тестовый модуль spa_core/ + scripts/ (без "
            "scripts/archive/); координата — имя верхнего уровня с КОНСТАНТНЫМ "
            "значением, у которого исполнитель РОВНО ОДИН"
        ),
        "scanned": scanned,
        "guards": len(guard_files),
        "executors": len(executor_files),
        "counts": dict(counts, unreadable=len(unreadable)),
        "remedy_counts": remedy_counts,
        "risk_policy_thresholds": len(thresholds),
        "classified": classified,
        "rows": rows,
        "unreadable": unreadable,
        # Доказанный МИНИМУМ переименованных копий: сторож, ни разу не
        # упомянувший дерево-предмет, держит свою копию наверняка. Потолком это
        # число не является — см. docstring.
        "renamed_copy_surface": sorted(surface),
        "what_it_does_not_prove": [
            "что у найденной пары копия вредит СЕГОДНЯ — вред приходит с правкой одной из копий",
            "что совпавшее значение имеет общее происхождение (SEED = 42 может быть совпадением)",
            "что население полно — переименованная копия невидима; renamed_copy_surface есть доказанный МИНИМУМ, а не потолок",
            "что сторож из delegates не держит второй копии рядом — дверь найдена, пользование ею не спрошено",
            "что пара subject_unproven есть СОВПАДЕНИЕ — свидетель общего предмета односторонний, «не доказан» третий исход",
            "что пара owner_subject есть ОДНА величина — равенство с порогом RiskPolicy отправляет её владельцу, а не выносит приговор",
        ],
    }


def _reaches_subject_tree(source: str) -> bool:
    """Достаёт ли сторож дерево-предмет хоть как-нибудь.

    Отдельная функция, а не выражение на месте: поверхность слепоты — второе
    по важности число прибора, и правило её отбора обязано быть одним и
    проверяемым тестом.
    """
    return ("spa_core" in source) or ("scripts" in source)


def report(doc: dict, *, max_rows: int = 20) -> List[str]:
    """Строки отчёта. Единственное место, где перепись превращается в текст."""
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    out = [
        f"одно правило — две копии (заказ G41 п. 1): {status} · "
        f"две копии {counts.get(CLASS_TWO_COPIES)} · "
        f"сторож достаёт исполнителя {counts.get(CLASS_DELEGATES)} · "
        f"значения разные {counts.get(CLASS_VALUE_DIFFERS)} · "
        f"сравнить нечем {counts.get(CLASS_NOT_CONSTANT)} · "
        f"исполнитель не один {counts.get(CLASS_AMBIGUOUS)}",
        f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}",
        f"[УЧЁТ] осмотрено {doc.get('scanned')} = разобрано {doc.get('classified')} "
        f"+ не разобрано {counts.get('unreadable')} "
        f"(сторожей {doc.get('guards')}, исполнителей {doc.get('executors')})",
    ]
    remedy = observed(doc, "remedy_counts", kind=dict)
    if remedy is None:
        out.append("[ФОРМА ПОЧИНКИ] НЕ ИЗМЕРЕНА — перепись собрана без разбора форм")
    else:
        out.append(
            f"[ФОРМА ПОЧИНКИ] ввозом {remedy.get(REMEDY_IMPORT)} · "
            f"предмет владельца {remedy.get(REMEDY_OWNER)} · "
            f"предмет НЕ доказан {remedy.get(REMEDY_UNPROVEN)} · "
            f"не разобрано {remedy.get(REMEDY_UNREADABLE)}")
    findings = [r for r in (doc.get("rows") or []) if r["verdict"] in _FINDING_CLASSES]
    for row in findings[:max_rows]:
        tail = ""
        if row.get("remedy"):
            tail = f" · {row['remedy']}: {row.get('remedy_evidence', 'основание не записано')}"
        out.append(
            f"[НАХОДКА] {row['name']} = {row['value']} — сторож {row['guard']} "
            f"против исполнителя {row['executor']}{tail}")
    if len(findings) > max_rows:
        # Умолчание об укорочении и есть способ соврать усечением.
        out.append(f"[…] показаны {max_rows} находки из {len(findings)}; "
                   f"полный перечень — в артефакте")
    surface = doc.get("renamed_copy_surface") or []
    out.append(
        f"[ГРАНИЦА ПРАВИЛА ИМЕНИ] сторожей, читающих состояние репозитория и не "
        f"упоминающих дерево-предмет ни разу: {len(surface)} — у них копия своя "
        f"ПО ПОСТРОЕНИЮ; это доказанный МИНИМУМ переименованных копий, не потолок"
        + (f"; напр. {', '.join(surface[:3])}" if surface else ""))
    out.append("НЕ ДОКЛАДЫВАЕТ: вредит ли найденная копия сегодня; общее ли "
               "происхождение у совпавшего значения; является ли "
               "`subject_unproven` совпадением — свидетель односторонний")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Отрисовка для шага 0-офис. Второй копии правила отрисовки здесь НЕТ:
    ветка офиса делегирует сюда, а эта функция — в ``report``."""
    lines = report(doc, max_rows=max_rows)
    if str(doc.get("status")) == "FINDING":
        lines[0] = f"⚠️ {lines[0]}"
    return lines


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        data_dir: Optional[Path] = None, write: bool = True,
        now: Optional[dt.datetime] = None) -> dict:
    """Один прогон переписи для ступени моста.

    **Гейта такта здесь нет, и это замер, а не поблажка.** Зов есть разбор AST
    в одном процессе; цена названа в ADR-417. Недельный такт не купил бы
    ничего, а завёл бы ровно ту вторую копию правила о сроке, которую сосед
    (`tact_gate_census`) и ищет.
    """
    root = Path(root)
    target = (Path(dest) if dest is not None
              else (Path(data_dir) if data_dir is not None else root / "data") / ARTIFACT)
    try:
        doc = measure(root, now=now)
    except NotMeasured as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись «одно правило — две копии»: исполнитель против сторожа (G41 п. 1)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    outcome = run(Path(args.root),
                  dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    doc = outcome["doc"]
    for line in report(doc):
        print(line)
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
