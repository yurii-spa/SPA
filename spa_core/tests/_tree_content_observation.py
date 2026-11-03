"""Третий исход у предиката о СОДЕРЖИМОМ дерева: «НЕ ИЗМЕРЕНО», а не исчезновение.

Зачем
------------------------------------------------------------------------------
ADR-905 (цикл #1016) ИЗМЕРИЛ десятую дверь семейства «вердикт зависит не от кода»:
вердикт **15** тестов набора есть свойство СОДЕРЖИМОГО дерева — достаточно закрыть
карточку или очистить очередь, и вердикт переворачивается при неизменных байтах кода.
Направления оказались РАЗНЫЕ, и три из четырёх не «краснеет»:

    PASSED→FAILED 10 · PASSED→SKIPPED 3 · FAILED→SKIPPED 1 · FAILED→PASSED 1

**Четыре предмета в сцене «карточек нет» ИСЧЕЗАЮТ**, и они опаснее остальных
одиннадцати: в дифференциальном замере такой тест не краснеет и не проходит — его
вердикта просто нет, а глазами это читается как «всё в порядке» (урок #465). Форма у
всех четырёх одна:

    if not <путь в очереди>.exists():
        pytest.skip("карточки нет в этом дереве")

То есть **предпосылка предиката не обеспечена, а исход выдан за благополучие** — ровно
инвариант #17 `CLAUDE.md`: отсутствие наблюдения обязано быть представлено ОТДЕЛЬНЫМ
значением, а не пустотой и не успехом. `.claude/rules/deployment.md` говорит это же
дважды и дословно: «Скип вместо замера — не выход: молча снимает проверку сторожа,
„не измерено“ становится неотличимо от „прошло“» и «тест, не обеспечивший свою
предпосылку, обязан сказать это вслух, а не судить».

Премиса самих скипов ОПРОВЕРГНУТА замером
------------------------------------------------------------------------------
Скипы оправдывались строкой «`nimbalyst-local/` не возит ни автосинк, ни CI-чекаут
(урок #193)». Половина про автосинк верна — зеркало `docs/` и `nimbalyst-local/` не
возит НИКОГДА (ADR-152). Половина про **CI-чекаут неверна, и это измерено** на
`origin/main` 58dd64e7e:

* `git ls-files nimbalyst-local/tracker` → **1569** файлов: очередь git-tracked;
* `sparse-checkout` не объявлен НИ В ОДНОМ воркфлоу `.github/workflows/*.yml`;
* все три названных предмета лежат в индексе: `_BOARD.md`,
  `inbox-razobrat-52-kartochki-s-vetki-work-statu.md`,
  `own-rnd-xsd-rank-demotion-allocator.md`.

Значит в CI содержимое есть ВСЕГДА, и эти скипы там не срабатывают НИ РАЗУ: они не
защищают прогон от свойства раннера (это был бы класс § «GIT-ОКРУЖЕНИЕ в тестах»), а
только гасят предикат там, где дерево НЕПОЛНО — то есть ровно там, где о неполноте и
надо сказать вслух (урок ADR-904: у КРАСНОГО прогона «ноль записей» не есть ответ).

Что эта дверь делает и чего НЕ делает
------------------------------------------------------------------------------
`require_tree_content` / `unmeasured` поднимают `TreeContentUnmeasured` —
**потомок `AssertionError`**, поэтому исход у pytest получается `failed`, а не
`skipped`: предмет перестаёт исчезать. Потомок именно `AssertionError`, а не
`BaseException`-потомок `pytest.fail`, сознательно: контроль в обе стороны пишется
обычным `pytest.raises(AssertionError)`, и ветка «предпосылка не обеспечена» сама
получает положительный контроль (`.claude/rules/deployment.md`: «Контроль на такой
отказ обязан ловить `BaseException`» — у `pytest.skip`/`pytest.fail` он бы его и
требовал, у этой двери не требует).

Дверь НЕ судит о том, ВЕРНО ли содержимое: это предмет самого предиката. Она
отвечает ровно на один вопрос — «названное содержимое вообще есть?» — и у ответа
три исхода, различимых вызывающим: есть (вернулся путь) · нет (ОТКАЗ с названной
причиной) · спросили не о том (`ValueError` на пустом предмете, то есть дефект
вызывающего, а не наблюдение).
"""
# LLM_FORBIDDEN
from __future__ import annotations

from pathlib import Path
from typing import NoReturn

PREFIX = "НЕ ИЗМЕРЕНО"

#: Как читателю отказа вернуть предпосылку. Печатается в каждом отказе: иначе
#: следующая сессия «починит» красный возвратом скипа, то есть вернёт дефект.
_HOWTO = (
    "предпосылка НЕ ОБЕСПЕЧЕНА — это НЕ ИЗМЕРЕНО, а не «проверка прошла». "
    "Чинить ДЕРЕВОМ (прогон из полного рабочего дерева на origin/main), "
    "а НЕ возвратом pytest.skip: очередь git-tracked (1569 файлов) и "
    "sparse-checkout в воркфлоу не объявлен, поэтому в CI содержимое есть всегда "
    "(замер ADR-906). Молчаливое ослабление запрещено — инв. #16"
)


class TreeContentUnmeasured(AssertionError):
    """Предпосылка предиката о содержимом дерева не обеспечена.

    Потомок `AssertionError` намеренно (см. модульную строку): исход у pytest —
    `failed`, а контроль в обе стороны пишется обычным `pytest.raises`.
    """

    def __init__(self, subject: str, reason: str, path: Path | None = None) -> None:
        self.subject = subject
        self.reason = reason
        self.path = path
        where = f" ({path})" if path is not None else ""
        super().__init__(f"{PREFIX}: {subject}{where} — {reason}. {_HOWTO}")


def unmeasured(subject: str, reason: str, *, path: Path | None = None) -> NoReturn:
    """ГРОМКО отказать: наблюдения нет, и это отдельный исход, а не успех.

    `subject` — О ЧЁМ не удалось измерить (предмет предиката), `reason` — ПОЧЕМУ.
    Обе строки обязательны и непустые: отказ без предмета неотличим от отказа без
    причины, а именно различимость здесь и есть вся работа.
    """
    if not subject.strip():
        raise ValueError("отказ без предмета: назвать, О ЧЁМ наблюдения нет")
    if not reason.strip():
        raise ValueError("отказ без причины: назвать, ПОЧЕМУ наблюдения нет")
    raise TreeContentUnmeasured(subject, reason, path)


def require_tree_content(path: Path, subject: str, *, kind: str = "файл") -> Path:
    """Вернуть `path`, если содержимое в дереве есть; иначе ГРОМКО отказать.

    `kind` — чем предмет обязан быть (`файл` / `каталог`): «каталога нет» и «на этом
    месте не каталог» — разные состояния дерева, и путать их значило бы судить о
    втором по первому.
    """
    if kind not in ("файл", "каталог"):
        raise ValueError(f"неизвестный род содержимого: {kind!r}")
    if not path.exists():
        unmeasured(subject, f"{kind}а нет в этом дереве", path=path)
    if kind == "каталог" and not path.is_dir():
        unmeasured(subject, "на этом месте не каталог", path=path)
    if kind == "файл" and not path.is_file():
        unmeasured(subject, "на этом месте не файл", path=path)
    return path


def require_member(name: str, present: object, subject: str) -> None:
    """Предмет обязан БЫТЬ в прочитанном наборе; его отсутствие — отказ, не скип.

    Нужна отдельно от `require_tree_content`: предикат, читающий очередь ЦЕЛИКОМ,
    судит о члене набора, а не о пути, и «в наборе его нет» у него единственная
    форма отсутствия.
    """
    try:
        found = name in present  # type: ignore[operator]
    except TypeError as exc:  # pragma: no cover — дефект вызывающего, не наблюдение
        raise ValueError(f"набор не поддерживает проверку вхождения: {exc}") from exc
    if not found:
        unmeasured(subject, f"{name} не найден в прочитанном наборе этого дерева")


# ══════════════════════════════════════════════════════════════════════════════
# ПЕРЕПИСЬ КЛАССА: кто ещё исчезает при отсутствии содержимого очереди
# ══════════════════════════════════════════════════════════════════════════════
#
# Третий исход поставлен в шести файлах руками. Чтобы класс не набрался заново —
# перепись, и у неё база, которая может только УМЕНЬШАТЬСЯ (тот же порядок, что у
# `frozen_date_baseline.json` / `design_status_baseline.json` / `site_numbers_baseline.json`).
#
# Почему перепись УЗКАЯ. Наивное «skip под проверкой существования» даёт на том же
# `origin/main` 58dd64e7e **96** площадок в 71 файле (перемерено циклом #1018 ТЕМ ЖЕ
# словарём проб, что и узкая мера — обе ноги, `Path` и `os.path`); вариант словаря
# здесь существен, и его надо называть: только методами `Path` та же мера даёт 87 в 64,
# и ровно это число стоит в ADR-906 — оно верно для ПЕРВОЙ редакции словаря, не для
# нынешней. А снять разбор происхождения и оставить «файл где-то упоминает очередь»
# стои́т 16 площадок, из которых **6 ЛОЖНЫХ** (замер #1018 воспроизвёл их поимённо:
# `test_covariance_export` ×2, `test_cpa_integration`, `test_fill_agent_passports`,
# `test_company_truth_matches_ui_contract`, `test_atomic_migration_complete`).
# Запрет размера 96 был бы снят раньше, чем починен хоть один предмет (дословный урок
# `test_frozen_date_ratchet`: 346 файлов в классе, полный запрет невозможен). Поэтому членом класса считается только то, что и было измерено
# ADR-905: **skip, чья предпосылка — наличие в дереве ОЧЕРЕДИ КАРТОЧЕК**. Сходятся два
# признака: (а) предпосылкой служит проверка наличия (`exists`/`is_dir`/`is_file`) либо
# вхождения (`in` / `not in`); (б) предмет проверки происходит от очереди — её называет
# либо условие, либо тело функции, либо модульная привязка.
#
# Правило намеренно ГРУБОЕ и обязано ошибаться В СТОРОНУ НАХОДКИ: ложная находка
# стоит одного вызова двери, а пропуск возвращает исчезающий предикат.

import ast as _ast

_SKIP_NAMES = frozenset({"skip", "skipTest"})
#: Пробы наличия. Семейство `os.path` — ОТДЕЛЬНАЯ дверь, и её пропуск ИЗМЕРЕН:
#: первая редакция меры знала только методы `Path` и потеряла десятую площадку
#: `test_acceptance_probe_writer:341` (`os.path.isdir(tracker)`) — ровно тот файл,
#: на котором класс и был найден (ADR-905). Нашлась она не мерой, а грепом по
#: тексту причины; поэтому ноги у меры теперь ДВЕ, и обе названы.
_EXIST_PROBES = frozenset({"exists", "lexists", "is_dir", "isdir", "is_file", "isfile"})
#: Маркеры очереди карточек. `tracker` — в нижнем регистре подстрокой: имена
#: `tracker`, `TRACKER_DIR`, `TRACKER_REL`, `_TRACKER`, `tracker_dir` все про неё.
_QUEUE_MARKERS = ("nimbalyst", "tracker")
CANON_TEST_ROOTS = ("spa_core/tests", "scripts/tests", "tests")


def _is_skip_call(node: _ast.AST) -> bool:
    if not isinstance(node, _ast.Call):
        return False
    f = node.func
    if isinstance(f, _ast.Attribute):
        return f.attr in _SKIP_NAMES
    return isinstance(f, _ast.Name) and f.id in _SKIP_NAMES


def _has_precondition_probe(test: _ast.AST) -> bool:
    """Предпосылкой служит наличие пути ЛИБО вхождение в прочитанный набор."""
    for n in _ast.walk(test):
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute) \
                and n.func.attr in _EXIST_PROBES:
            return True
        if isinstance(n, _ast.Compare) and any(
                isinstance(op, (_ast.In, _ast.NotIn)) for op in n.ops):
            return True
    return False


def _names_the_queue(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _QUEUE_MARKERS)


def _queue_bindings(tree: _ast.Module) -> set[str]:
    """Имена, ЧЬЁ ЗНАЧЕНИЕ происходит от очереди — до неподвижной точки.

    Приём тот же, что у сторожа претензии `injected-clock` (`_injected_clock.py`):
    якорь → привязка → употребление. Без него перепись пришлось бы судить по
    «файл где-то упоминает трекер», и замер ADR-906 показал цену такой меры:
    ШЕСТЬ ложных находок из шести (`test_covariance_export`, `test_cpa_integration`
    и родня — слово-маркер там живёт в прозе, а предмет скипа к очереди отношения
    не имеет). Контейнер привязкой НЕ является по тому же основанию, что у
    `injected-clock`: «RHS где-то содержит маркер» оправдало бы прозу рядом.
    """
    names: set[str] = set()
    # ФУНКЦИЯ, чьё тело называет очередь, сама есть источник значения: `cards =
    # {c.stem: c for c in _real_cards()}` происходит от очереди через ВЫЗОВ, а не
    # через присваивание маркера. Без этой ноги перепись теряла площадку
    # `test_branch_queue_dropped_decision:361` — ровно ту форму «предмета нет в
    # прочитанном НАБОРЕ», и это ИЗМЕРЕНО (9 из 10 против 10 из 10; перемерено
    # циклом #1018 — у ADR-906 здесь стояло «8 из 9», своя же арифметика площадок).
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) \
                and _names_the_queue(_ast.unparse(node)):
            names.add(node.name)
    for _ in range(8):  # до неподвижной точки; 8 с запасом на цепочку присваиваний
        before = len(names)
        for node in _ast.walk(tree):
            if not isinstance(node, (_ast.Assign, _ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, _ast.Assign) else [node.target]
            if node.value is None:
                continue
            rhs = _ast.unparse(node.value)
            if not (_names_the_queue(rhs) or any(n in names for n in _referenced(node.value))):
                continue
            for t in targets:
                if isinstance(t, _ast.Name):
                    names.add(t.id)
        if len(names) == before:
            break
    return names


def _referenced(node: _ast.AST) -> set[str]:
    return {n.id for n in _ast.walk(node) if isinstance(n, _ast.Name)}


def measure_queue_content_skips(
    repo_root: Path, roots: tuple[str, ...] = CANON_TEST_ROOTS
) -> dict:
    """Перепись класса. Три исхода различимы (инв. #17).

    Возвращает ``{"sites": [...], "unmeasured": [...], "roots_missing": [...]}``:
    площадка названа файлом и строкой · НЕ ИЗМЕРЕНО с причиной (файл не разбирается
    или не читается) · корня переписи нет вовсе. Пустой список площадок при непустом
    ``unmeasured``/``roots_missing`` ответом «класс пуст» НЕ является — судить обязан
    вызывающий, и храповик ниже это и делает.
    """
    sites: list[dict] = []
    unmeasured: list[dict] = []
    roots_missing: list[str] = []
    for rel in roots:
        d = repo_root / rel
        if not d.is_dir():
            roots_missing.append(rel)
            continue
        for p in sorted(d.glob("test_*.py")):
            try:
                src = p.read_text(encoding="utf-8")
            except OSError as exc:
                unmeasured.append({"path": rel + "/" + p.name,
                                   "reason": f"файл не читается: {exc}"})
                continue
            try:
                tree = _ast.parse(src)
            except SyntaxError as exc:
                unmeasured.append({"path": rel + "/" + p.name,
                                   "reason": f"не разбирается: {exc}"})
                continue
            bindings = _queue_bindings(tree)
            for node in _ast.walk(tree):
                if not isinstance(node, _ast.If):
                    continue
                if not _has_precondition_probe(node.test):
                    continue
                cond = _ast.unparse(node.test)
                for inner in _ast.walk(node):
                    if not _is_skip_call(inner):
                        continue
                    # предмет происходит от очереди: её называет либо условие,
                    # либо привязка, на которую условие ссылается, либо причина скипа
                    reason = " ".join(_ast.unparse(a) for a in inner.args)
                    from_queue = (_names_the_queue(cond)
                                  or bool(_referenced(node.test) & bindings)
                                  or _names_the_queue(reason))
                    if not from_queue:
                        continue
                    sites.append({
                        "path": rel + "/" + p.name,
                        "line": inner.lineno,
                        "condition": cond[:120],
                    })
    return {"sites": sites, "unmeasured": unmeasured, "roots_missing": roots_missing}
