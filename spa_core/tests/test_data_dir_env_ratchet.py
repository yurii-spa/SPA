"""Храповик: класс «каталог состояния мимо ``SPA_DATA_DIR``» может только уменьшаться.

Что за класс
------------------------------------------------------------------------------
Заслон герметичности тестов (``tests/conftest.py::_isolate_data_dir``) обещает, что
«любой код, разрешающий свой каталог состояния штатным механизмом, никогда не
прочитает и не запишет живой ``data/``». Механизм ровно один — переменная
``SPA_DATA_DIR``. Модуль, который вместо неё берёт ``_REPO_ROOT / "data"``
константой на уровне модуля, под заслон не попадает НИКОГДА: константа вычисляется
при импорте, а фикстура выставляет переменную на каждый тест — намного позже.

Цена этого измерена, а не предположена (цикл #361, карточка
``inbox-zaslon-izolyatsii-data-v-testah-pokryvae``):
``_adapter_class_gate("spark_susds")`` создаёт настоящий адаптер, тот читает живой
``data/adapter_status.json`` мимо заслона, и ОДИН И ТОТ ЖЕ код давал
``(False, 'gsm_not_confirmed')`` в worktree на каноне ``origin/main`` и
``(True, None)`` в боевом дереве, где фид уже наблюдал 48-часовую задержку GSM.
Вердикт теста-сторожа денежного гейта решал файл данных, а не код.

Почему храповик, а не запрет
------------------------------------------------------------------------------
Замер этого файла: модулей рантайма с такой константой — **242**. Запрет в лоб
покрасил бы их все разом, а правило Yield Lab запрещает big-bang; научил бы он
ровно одному — отключать сторожа. Образец решения — ``test_frozen_date_ratchet.py``
(тот же класс: «состояние/время как окружение, а не как вход»):

* зафиксированная база перечисляет модули, которые уже несут риск;
* НОВЫЙ модуль, вошедший в класс, красит этот тест;
* починенный модуль просто выпадает из базы — база может только уменьшаться,
  и уменьшать её и есть смысл;
* добавлять модуль в базу, чтобы погасить падение, ЗАПРЕЩЕНО — чинить надо модуль.

Чем «починен» отличается от «обёрнут»
------------------------------------------------------------------------------
Починка — одна строка: умолчание разрешается В МОМЕНТ ВЫЗОВА через
``spa_core.utils.data_dir.own_data_dir``. В проде ``SPA_DATA_DIR`` не выставлена,
поэтому поведение остаётся бит-в-бит прежним; меняется только то, что у заслона
появляется точка входа. Образец — ``spa_core/adapters/status_reader.py``.

Что детектор НЕ ловит и почему это названо, а не спрятано
------------------------------------------------------------------------------
1. Локальные выражения внутри функций (``root / "data"`` в теле) — это другая
   форма: она вычисляется при вызове и часто законна (вызывающий сам передал
   корень). Детектор смотрит ТОЛЬКО на присваивания уровня модуля — ровно ту
   форму, которая гарантированно не увидит фикстуру.
2. Модуль, который слово ``SPA_DATA_DIR`` упоминает, но константу всё равно
   читает мимо неё. Признак — исходный, а не семантический: доказать, что
   переменная доходит до КАЖДОГО чтения, регуляркой нельзя, и сторож, который
   бы это утверждал, был бы тем самым fail-OPEN, за который проект уже платил.
   Поэтому упоминание считается заявкой, а её честность проверяют тесты модуля.
3. ``spa_core/adapters/apy_aggregator.py`` стоит в базе с МЁРТВОЙ константой:
   ``_DEFAULT_DATA_DIR`` там определён и не читается ни разу (``load(data_dir)``
   требует каталог явно). Обернуть её значило бы поставить украшение; честная
   починка — удалить, и это отдельное решение, а не попутное.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_PKG_ROOT = _TESTS_DIR.parent                 # spa_core/
_REPO_ROOT = _PKG_ROOT.parent
_BASELINE = _TESTS_DIR / "data_dir_env_baseline.json"

#: Признаки того, что модуль спрашивает переменную (сам или через хелпер).
#: Намеренно ИСХОДНЫЙ признак — см. п. 2 докстринга.
_CONSULTS = ("SPA_DATA_DIR", "own_data_dir", "live_data_dir")


def _module_level_data_dir_consts(src: str) -> list:
    """Имена констант уровня модуля, связанных с ``<что-то> / "data"``.

    Разбор через ``ast``, а не регуляркой: форм записи корня в репо больше
    десятка (``_REPO_ROOT``, ``_PROJECT_ROOT``, ``_ROOT``, ``Path(__file__)…``),
    и перечислять их списком значило бы завести сторожа, слепого к следующей.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    names = []
    for node in tree.body:                      # ТОЛЬКО уровень модуля
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)):
            continue
        right = value.right
        if not (isinstance(right, ast.Constant) and right.value == "data"):
            continue
        names.extend(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _runtime_modules() -> list:
    """Модули рантайма пакета — без тестов (у тестов свой каталог по построению)."""
    out = []
    for p in sorted(_PKG_ROOT.rglob("*.py")):
        rel = p.relative_to(_REPO_ROOT).as_posix()
        if "/tests/" in rel or p.name.startswith("test_"):
            continue
        out.append(p)
    return out


def _bypassing_modules() -> set:
    """Модули с константой-каталогом уровня модуля, не спрашивающие переменную."""
    out = set()
    for p in _runtime_modules():
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _module_level_data_dir_consts(src):
            continue
        if any(marker in src for marker in _CONSULTS):
            continue
        out.add(p.relative_to(_REPO_ROOT).as_posix())
    return out


def _remediation_text() -> str:
    return (
        "Такой модуль решает свой каталог состояния ПРИ ИМПОРТЕ, поэтому autouse-заслон\n"
        "тестов (SPA_DATA_DIR) до него не доходит никогда — вердикт теста начинает\n"
        "решать живой файл хоста, а не код.\n"
        "Починка — одна строка в точке ЧТЕНИЯ умолчания:\n"
        "    from spa_core.utils.data_dir import own_data_dir\n"
        "    ...  else own_data_dir(_DEFAULT_DATA_DIR)\n"
        "В проде переменная не выставлена ⇒ поведение бит-в-бит прежнее.\n"
        "Образец: spa_core/adapters/status_reader.py.\n"
        "Добавлять модуль в базу, чтобы погасить это падение, ЗАПРЕЩЕНО: база только "
        "уменьшается.")


def _baseline():
    try:
        return set(json.loads(_BASELINE.read_text(encoding="utf-8"))["modules"])
    except Exception:  # noqa: BLE001 — пропавшая база не должна пройти молча
        return None


def test_baseline_exists_and_is_readable() -> None:
    """Нет базы ⇒ храповик ничего не меряет. Fail-CLOSED."""
    assert _baseline() is not None, (
        f"{_BASELINE.name} отсутствует или нечитаем — храповик не отличит новых "
        f"нарушителей от старых и не имеет права пройти тихо")


def test_no_new_module_bypasses_the_data_dir_env() -> None:
    """Единственное утверждение, ради которого файл существует: класс не растёт."""
    base, now = _baseline(), _bypassing_modules()
    assert base is not None
    added = sorted(now - base)
    assert not added, (
        "Новый модуль(и) рантайма берёт каталог состояния константой мимо SPA_DATA_DIR:\n  "
        + "\n  ".join(added) + "\n\n" + _remediation_text())


def test_baseline_does_not_list_modules_that_no_longer_exist() -> None:
    """База из призраков молча ослабляет храповик."""
    base = _baseline()
    assert base is not None
    ghosts = sorted(m for m in base if not (_REPO_ROOT / m).is_file())
    assert not ghosts, (
        "база перечисляет несуществующие модули: " + ", ".join(ghosts)
        + " — убрать, чтобы храповик продолжал мерить реальность")


def test_baseline_holds_nothing_that_is_no_longer_bypassing() -> None:
    """Направление храповика — механикой, а не на доверии.

    Без этого «может только уменьшаться» остаётся комментарием: починенный модуль
    сидел бы в базе вечно, и в день, когда он снова заведёт константу мимо
    переменной, храповик пропустил бы его — он же в списке.
    """
    base, now = _baseline(), _bypassing_modules()
    assert base is not None
    stale = sorted(base - now)
    assert not stale, (
        "база перечисляет модуль(и), которые больше не в классе:\n  "
        + "\n  ".join(stale)
        + "\n\nОни починены — уберите имена ТЕМ ЖЕ изменением: база уменьшается, "
          "в этом весь смысл.")


def test_detector_sees_the_shape_it_claims_to_see() -> None:
    """Положительный контроль самого детектора — он обязан ловить обе формы.

    Сторож, никогда не видевший поломки, — украшение
    (`.claude/rules/deployment.md`, «проверка сторожа сторожей»).
    """
    assert _module_level_data_dir_consts(
        '_REPO_ROOT = Path("/x")\n_DEFAULT_DATA_DIR = _REPO_ROOT / "data"\n'
    ) == ["_DEFAULT_DATA_DIR"]
    assert _module_level_data_dir_consts(
        '_D: Path = Path(__file__).resolve().parents[2] / "data"\n'
    ) == ["_D"]
    # …и не обязан считать классом локальное выражение внутри функции (п. 1).
    assert _module_level_data_dir_consts(
        'def f(root):\n    return root / "data"\n'
    ) == []
    # …и не путать соседний каталог с искомым.
    assert _module_level_data_dir_consts('_D = _ROOT / "docs"\n') == []


def test_the_module_this_ratchet_recommends_is_the_one_that_exists() -> None:
    """Совет в тексте падения обязан указывать на живой символ, а не на замысел."""
    from spa_core.utils.data_dir import own_data_dir  # noqa: F401
