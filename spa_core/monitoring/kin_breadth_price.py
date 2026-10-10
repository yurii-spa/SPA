"""Цена ШИРИНЫ двери родни: что именно прячет «тот же каталог» — заказ G112 п. 3 (ADR-538).

Дословно заказ:

    **Доставка под СОВСЕМ другим путём не измерена вовсе.** Родня ищется в том же
    каталоге; исход orphan-работы на базе есть (``ADR-304`` + ``check_concurrent_pytest``),
    и мера его не видит. Стоит ли расширять родню на дерево целиком — вопрос цены
    ложных срабатываний, и его надо ИЗМЕРИТЬ, а не решить вкусом.

Прибор ТОЛЬКО ЧИТАЕТ: он не правит дверь соседа (`duplicate_subject_census.kin_of`),
а считает, ЧТО БЫЛО БЫ, если расширить её по каждой оси порознь. Расширять вслепую
запретил ADR-682 прямо; этот модуль добывает число, без которого расширение было бы
вкусом.

Почему оси ПОРОЗНЬ, а не одна «дерево целиком»
----------------------------------------------
Заказ называет одну ось — каталог. Замер показал, что названный им случай
(``ADR-156-orphan-test-runs-have-no-guard.md`` ↔ доставленный
``ADR-304-orphaned-pytest-runs-get-a-schedule-not-an-executioner.md``) каталогом
НЕ ОБЪЯСНЯЕТСЯ ВОВСЕ: оба документа лежат в ``docs/decisions/``, то есть в ОДНОМ
каталоге, и дверь соседа смотрит ровно туда. Прячут его две ДРУГИЕ оси:

* **начало имени** — родство мерится общим ПРЕФИКСОМ токенов, а истинная родня
  делит токены не началом (``runs`` третий у одного и третий у другого, но
  первые токены расходятся);
* **морфология** — ``orphan`` против ``orphaned``: для сравнения строк это
  разные токены, для предмета — одно слово.

Поэтому мерить одну ось значило бы ответить на СВОЙ вопрос, а не на нужный:
расширение каталога названный случай не достаёт ни при каком пороге. Оси
объявлены в :data:`AXES` и комбинируются, чтобы цена каждой была видна ПОРОЗНЬ
и в сумме.

Валюта цены — НЕ «ложные срабатывания», а ТИШИНА
------------------------------------------------
Ложная родня здесь опасна односторонне: вердикт координаты уезжает из
``absent_lost`` в ``absent_kin``, и это читается как «похоже, переименовали,
работа доехала». Потеря перестаёт быть находкой МОЛЧА. Поэтому цена считается в
двух разных валютах, и смешивать их нельзя:

* :data:`SILENCED` — сколько координат, сегодня честно отсутствующих, широкая
  дверь объявила бы роднёй (подозрение вместо потери);
* :data:`PREEMPTED` — сколько координат с СЕГОДНЯШНИМ ДОКАЗАННЫМ вердиктом
  (``retired_at_base`` несёт sha коммита) широкая дверь перебила бы подозрением.
  Это цена, которой заказ не предполагал: она про ПОРЯДОК дверей, а не про их
  ширину, и она отрицательна — замер теряет доказательство, а не добавляет его.

Истинность кандидата — ТРЕТИЙ ИСХОД, а не ноль
----------------------------------------------
Оракула «та же это работа или нет» не существует: родство доказывается ADR-ом и
коммитом, а не похожестью имён. Поэтому у каждого кандидата ровно три исхода —
``true`` (есть строка :data:`GROUND_TRUTH` с доказательством), ``false`` (есть
строка, и она говорит «не та работа») и ``unmeasured``. Считать неизвестных
ложными значило бы завысить цену и зарубить расширение числом, которого никто
не мерил; считать истинными — наоборот. Обе подстановки запрещены.

Пересечение РОДА файла считается отдельно
-----------------------------------------
``.py``-координата, чьим «кандидатом» оказался ``.md``, — не переименование.
Это закрытие ПРЕДМЕТА другим путём, и дверь родни отвечает не на тот вопрос:
она про координату. Число — ``kind_crossing``; без него ось «набор токенов +
морфология» выглядела бы успешной ровно там, где она меняет вопрос.

Третий исход прибора
--------------------
Население берётся у СОСЕДА-раскрывателя (``duplicate_subject_census.run_census``),
а не добывается вторым поиском: второй поиск того же предмета расходится с
первым (урок ADR-682). Сосед не измерил / база не прочитана / население пусто ⇒
``measured=False`` с названной причиной. Пустое население НЕ выдаётся за «цена
ноль»: цена без населения не измерена.

Коды возврата: 0 — находки нет (ни одна ось не платит тишиной и не перебивает
доказательство) · 1 — находка · 2 — НЕ ИЗМЕРЕНО с названной причиной.

ADVISORY: пороги RiskPolicy v1.0, стоп-кран, аллокатор, живой трек и ``landing/``
НЕ трогаются; прибор читает журнал объявлений и дерево базового ref.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

#: Имя артефакта (читает шаг 0-офис поимённой ветвью).
ARTIFACT = "kin_breadth_price.json"

#: Оси расширения двери родни. Каждая — ОДНО изменение сравнения имён, и каждая
#: мерится порознь, потому что платят они разным.
AXES: Tuple[Tuple[str, Dict[str, bool]], ...] = (
    # Сегодняшняя дверь соседа. Служит НУЛЁМ отсчёта: «новых кандидатов» считают
    # относительно неё, иначе прирост был бы неотличим от населения.
    ("baseline", {}),
    # Ось, которую назвал заказ.
    ("whole_tree", {"whole_tree": True}),
    # Ось, которой заказ не предполагал: токены делятся НЕ началом.
    ("token_set", {"token_set": True}),
    # Ось, которой заказ не предполагал: orphan против orphaned.
    ("stemmed", {"stemmed": True}),
    ("whole_tree+token_set", {"whole_tree": True, "token_set": True}),
    ("token_set+stemmed", {"token_set": True, "stemmed": True}),
    ("all_three", {"whole_tree": True, "token_set": True, "stemmed": True}),
)

#: Вердикты соседа, которые расширенная дверь ПЕРЕБИЛА БЫ, встань она на то же
#: место в порядке проверок. Порядок у соседа: `at_base` → «база старше
#: объявления» → РОДНЯ → списание. Значит родня перебивает всё, что стои́т ПОСЛЕ
#: неё, и не трогает `at_base`. Претензия проверяется ИСХОДОМ на герметичной
#: сцене (`test_kin_breadth_price.py::test_kin_door_preempts_the_retirement_door`),
#: а не чтением кода соседа: чтение подтвердило бы только то, что я его прочёл.
KIN_PRECEDES: Tuple[str, ...] = ("absent_lost", "absent_retirement_unmeasured",
                                 "retired_at_base")

#: Вердикты, у которых СЕГОДНЯ есть доказательство: их перебитие — цена
#: отрицательная (замер теряет sha коммита и получает подозрение).
EVIDENCED: Tuple[str, ...] = ("retired_at_base",)

#: Вердикты, которые расширение превратило бы в подозрение «переименовали».
SILENCEABLE: Tuple[str, ...] = ("absent_lost", "absent_retirement_unmeasured")

#: Что известно про истинность КОНКРЕТНЫХ пар — и чем известно. Строка живёт
#: только с доказательством (ADR + коммит/файл на базе); без него пара остаётся
#: `unmeasured`. Таблица мала намеренно: она не классификатор, а оракул для
#: положительного контроля, и выдумывать в неё строки запрещено.
GROUND_TRUTH: Tuple[Dict[str, str], ...] = (
    {
        "coordinate": "scripts/day30_review.py",
        "candidate": "spa_core/riskwire/day30_review.py",
        "truth": "true",
        "relation": "retired_wrapper_over_this_module",
        "evidence": "ADR-538 ОТВЕТ 1: обёртка из 23 строк sys.path-шима над "
                    "spa_core.riskwire.day30_review списана коммитом d45cb4a3c "
                    "(2026-08-19), достижимость замены закреплена "
                    "test_day30_review_cli_contract.py",
    },
    {
        "coordinate": "docs/decisions/ADR-365-capital-observability-over-history.md",
        "candidate": "docs/decisions/ADR-366-capital-observability-over-history.md",
        "truth": "true",
        "relation": "renumbered_before_push",
        "evidence": "ADR-538 ОТВЕТ 2: слаг совпадает дословно, причина названа в "
                    "сообщении коммита 32e03c3a5",
    },
    {
        "coordinate": "docs/decisions/ADR-156-orphan-test-runs-have-no-guard.md",
        "candidate": "docs/decisions/"
                     "ADR-304-orphaned-pytest-runs-get-a-schedule-not-an-executioner.md",
        "truth": "subject_closed_elsewhere",
        "relation": "same_subject_other_number_and_slug",
        "evidence": "ADR-304 (10.09) называет scripts/check_concurrent_pytest.py "
                    "РАБОТАЮЩЕЙ проверкой того же класса и выдаёт ей расписание; "
                    "объявленный ADR-156 заявлял, что сторожа НЕТ. Предмет закрыт, "
                    "но ЭТО НЕ ПЕРЕИМЕНОВАНИЕ объявленной координаты — лифта "
                    "работы никто не мерил",
    },
    {
        "coordinate": "docs/decisions/ADR-156-orphan-test-runs-have-no-guard.md",
        "candidate": "docs/decisions/"
                     "ADR-174-guard-subject-is-the-live-tree-not-the-tree-it-runs-from.md",
        "truth": "false",
        "relation": "shares_the_word_guard_only",
        "evidence": "ADR-174 про ПРЕДМЕТ сторожа (живое дерево против дерева "
                    "запуска) и к брошенным прогонам отношения не имеет; общее — "
                    "слово guard",
    },
    {
        "coordinate": "docs/decisions/ADR-156-orphan-test-runs-have-no-guard.md",
        "candidate": "docs/decisions/"
                     "ADR-622-which-tracked-artifacts-have-no-declared-writer.md",
        "truth": "false",
        "relation": "shares_have_no_only",
        "evidence": "ADR-622 про артефакты без объявленного писателя; общее с "
                    "объявленным именем — служебные токены have/no",
    },
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def stem(token: str) -> str:
    """Грубое усечение окончания: ``orphaned`` → ``orphan``. ``runs`` НЕ трогается.

    Грубость объявлена, а не скрыта: это не морфология языка, а мера ОДНОГО
    наблюдённого расхождения (#830, пара ADR-156/ADR-304 — ``orphan`` против
    ``orphaned``). Порог длины щадит токены в четыре знака и короче, поэтому
    ``runs`` остаётся ``runs``: иначе ``runs``, ``run`` и ``ru`` склеились бы, и
    цена оси выросла бы от самой МЕРЫ, а не от предмета. Односторонность
    осознанная — мера скорее НЕ найдёт родню, чем выдумает её.
    """
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def kin_at_breadth(coordinate: str, base_paths: Iterable[str], *,
                   tokens: Callable[[str], List[str]],
                   shared_prefix: Callable[[Sequence[str], Sequence[str]], int],
                   numbered: Callable[[Sequence[str]], Optional[Tuple[str, List[str]]]],
                   need_tokens: int,
                   whole_tree: bool = False,
                   token_set: bool = False,
                   stemmed: bool = False) -> List[str]:
    """Родня координаты при ЗАДАННОЙ ширине двери.

    Разборщики имени (``tokens`` / ``shared_prefix`` / ``numbered``) и порог
    ``need_tokens`` подаются ВХОДОМ и берутся у соседа: своя копия разбора
    разошлась бы с его дверью, и тогда «цена расширения» мерила бы разницу двух
    разборов, а не ширину. Это та же ошибка, что второй поиск предмета.
    """
    directory, _, leaf = coordinate.rpartition("/")
    mine_raw = tokens(leaf)
    if not mine_raw:
        return []
    mine = [stem(t) for t in mine_raw] if stemmed else list(mine_raw)
    need = min(need_tokens, len(mine))
    mine_numbered = numbered(mine)
    mine_set = {t for t in mine if not t.isdigit()}
    found: List[str] = []
    for path in base_paths:
        other_dir, _, other_leaf = path.rpartition("/")
        if not whole_tree and other_dir != directory:
            continue
        if path == coordinate:
            continue
        # Тот же лист в ДРУГОМ каталоге — главный предмет оси `whole_tree`,
        # поэтому отбрасывать его по равенству листа можно только пока дверь
        # заперта в своём каталоге.
        if not whole_tree and other_leaf == leaf:
            continue
        theirs_raw = tokens(other_leaf)
        theirs = [stem(t) for t in theirs_raw] if stemmed else list(theirs_raw)
        if token_set:
            if mine_set and len({t for t in theirs if not t.isdigit()} & mine_set) >= min(
                    need, len(mine_set)):
                found.append(path)
            continue
        if shared_prefix(mine, theirs) >= need:
            found.append(path)
            continue
        theirs_numbered = numbered(theirs)
        if mine_numbered is None or theirs_numbered is None:
            continue
        if mine_numbered[0] != theirs_numbered[0]:
            continue
        my_slug, their_slug = mine_numbered[1], theirs_numbered[1]
        if shared_prefix(my_slug, their_slug) >= min(need_tokens, len(my_slug)):
            found.append(path)
    return sorted(found)


def _truth_of(coordinate: str, candidate: str) -> Dict[str, str]:
    for row in GROUND_TRUTH:
        if row["coordinate"] == coordinate and row["candidate"] == candidate:
            return {"truth": row["truth"], "relation": row["relation"],
                    "evidence": row["evidence"]}
    return {"truth": "unmeasured",
            "relation": "доказательства родства нет ни в ADR, ни в коммите",
            "evidence": ""}


def _kind_of(path: str) -> str:
    leaf = path.rpartition("/")[2]
    return leaf.rsplit(".", 1)[1] if "." in leaf else ""


def price_of_axes(findings: Sequence[Dict[str, Any]], base_paths: Sequence[str], *,
                  tokens: Callable[[str], List[str]],
                  shared_prefix: Callable[[Sequence[str], Sequence[str]], int],
                  numbered: Callable[[Sequence[str]], Optional[Tuple[str, List[str]]]],
                  need_tokens: int,
                  named_case: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    """Цена каждой объявленной оси на ЗАДАННОМ населении находок соседа."""
    baseline_pairs: Optional[set] = None
    axes: Dict[str, Any] = {}
    for axis, flags in AXES:
        rows: List[Dict[str, Any]] = []
        pairs: set = set()
        for finding in findings:
            coordinate = str(finding.get("coordinate") or "")
            if not coordinate:
                continue
            current = str(finding.get("verdict") or "")
            for candidate in kin_at_breadth(
                    coordinate, base_paths, tokens=tokens,
                    shared_prefix=shared_prefix, numbered=numbered,
                    need_tokens=need_tokens, **flags):
                pairs.add((coordinate, candidate))
                truth = _truth_of(coordinate, candidate)
                rows.append({
                    "coordinate": coordinate,
                    "candidate": candidate,
                    "current_verdict": current,
                    # Перебивает ли расширенная дверь сегодняшний вердикт —
                    # вопрос ПОРЯДКА проверок у соседа, а не ширины.
                    "would_become": "absent_kin" if current in KIN_PRECEDES else current,
                    "silences_a_loss": current in SILENCEABLE,
                    "preempts_evidence": current in EVIDENCED,
                    "kind_crossing": _kind_of(coordinate) != _kind_of(candidate),
                    **truth,
                })
        if baseline_pairs is None:
            baseline_pairs = set(pairs)
        new_pairs = pairs - baseline_pairs
        reaches = None if named_case is None else (named_case in pairs)
        axes[axis] = {
            "flags": dict(flags),
            "candidates": len(rows),
            "candidates_new_vs_baseline": len(new_pairs),
            "coordinates_gaining": sorted({c for c, _ in new_pairs}),
            "silenced": len({r["coordinate"] for r in rows if r["silences_a_loss"]}),
            "preempted_evidence": len({r["coordinate"] for r in rows
                                       if r["preempts_evidence"]}),
            "verified_true": sum(1 for r in rows if r["truth"] == "true"),
            "verified_false": sum(1 for r in rows if r["truth"] == "false"),
            "subject_closed_elsewhere": sum(1 for r in rows
                                            if r["truth"] == "subject_closed_elsewhere"),
            "truth_unmeasured": sum(1 for r in rows if r["truth"] == "unmeasured"),
            "kind_crossing": sum(1 for r in rows if r["kind_crossing"]),
            "reaches_named_case": reaches,
            "rows": rows,
        }
    return axes


def _base_paths(repo_root: Path, *,
                tree_reader: Optional[Callable[[Path], Optional[List[str]]]] = None
                ) -> Tuple[Optional[List[str]], Optional[str]]:
    """Пути базового дерева. Чтение — ВХОД, чтобы сцена не звала живой git."""
    if tree_reader is not None:
        paths = tree_reader(repo_root)
        return (None, "читатель дерева вернул None") if paths is None else (paths, None)
    import subprocess
    try:
        done = subprocess.run(["git", "-C", str(repo_root), "ls-tree", "-r",
                               "--name-only", "HEAD"],
                              capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001 — дверь не смеет валить прибор
        return None, f"git недоступен: {type(exc).__name__}: {exc}"
    if done.returncode != 0:
        return None, f"git ls-tree код {done.returncode}: {done.stderr.strip()[:200]}"
    return done.stdout.splitlines(), None


def measure(repo_root: Path, data_dir: Path, *, now: Optional[datetime] = None,
            census: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
            tree_reader: Optional[Callable[[Path], Optional[List[str]]]] = None
            ) -> Dict[str, Any]:
    """Замер цены ширины. Население — у соседа, дерево — у базового ref."""
    moment = now or _utcnow()
    report: Dict[str, Any] = {
        "generated_at": _iso(moment),
        "order": "G112 п. 3 (ADR-538) — цена расширения двери родни",
        "measured": False,
        "status": "НЕ ИЗМЕРЕНО",
        "reason": None,
        "population": None,
        "named_case": None,
        "axes": None,
        "verdict": None,
    }

    resolver = census
    if resolver is None:
        def resolver() -> Optional[Dict[str, Any]]:
            from spa_core.monitoring import duplicate_subject_census as neighbour
            history_root = None
            try:
                from spa_core.monitoring.history_door_price import resolve_history_root
                history_root = resolve_history_root(repo_root)["root"]
            except Exception:  # noqa: BLE001 — дверь истории не смеет валить прибор
                history_root = None
            return neighbour.run_census(data_dir, repo_root=repo_root, now=moment,
                                        history_root=history_root)

    try:
        neighbour_report = resolver()
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"сосед-раскрыватель не ответил: {type(exc).__name__}: {exc}"
        return report
    if not isinstance(neighbour_report, dict):
        report["reason"] = "сосед-раскрыватель вернул не отчёт"
        return report
    if not neighbour_report.get("measured"):
        report["reason"] = ("сосед не измерил население: "
                            f"{neighbour_report.get('reason') or 'причина не названа'}")
        return report
    price = observed(neighbour_report, "price", kind=dict)
    findings = None if price is None else observed(price, "findings", kind=list)
    if findings is None:
        report["reason"] = ("у соседа нет раздела находок — население НЕ ИЗМЕРЕНО "
                            "(пустой список и отсутствие раздела здесь РАЗНОЕ)")
        return report
    if not findings:
        # Пустое население — не «цена ноль»: мерить нечего, и сказать это надо
        # вслух, иначе ноль прочитается как «расширение бесплатно».
        report["reason"] = ("население пусто: у соседа ни одной находки, цена ширины "
                            "на пустом населении НЕ ОПРЕДЕЛЕНА")
        return report

    paths, why = _base_paths(repo_root, tree_reader=tree_reader)
    if paths is None:
        report["reason"] = f"дерево базового ref не прочитано: {why}"
        return report
    if not paths:
        report["reason"] = "дерево базового ref пусто — читали не то дерево"
        return report

    from spa_core.monitoring import duplicate_subject_census as neighbour_mod
    named_case = None
    for row in GROUND_TRUTH:
        if row["truth"] == "subject_closed_elsewhere":
            named_case = (row["coordinate"], row["candidate"])
            break

    axes = price_of_axes(
        findings, paths,
        tokens=neighbour_mod._tokens,
        shared_prefix=neighbour_mod._shared_prefix,
        numbered=neighbour_mod._numbered,
        need_tokens=neighbour_mod._KIN_TOKENS,
        named_case=named_case,
    )

    ordered = {str(f.get("coordinate")): str(f.get("verdict")) for f in findings}
    report["population"] = {
        "source": "duplicate_subject_census.run_census (сосед-раскрыватель)",
        "findings": len(findings),
        "silenceable": sum(1 for v in ordered.values() if v in SILENCEABLE),
        "evidenced": sum(1 for v in ordered.values() if v in EVIDENCED),
        "base_paths": len(paths),
        "need_tokens": neighbour_mod._KIN_TOKENS,
        "base_ref": observed(neighbour_report, "base_ref", kind=dict),
    }
    asked = AXES[1][0]  # ось, которую назвал заказ
    report["named_case"] = {
        "coordinate": None if named_case is None else named_case[0],
        "candidate": None if named_case is None else named_case[1],
        "same_directory": None if named_case is None else (
            named_case[0].rpartition("/")[0] == named_case[1].rpartition("/")[0]),
        "reached_by": sorted(name for name, data in axes.items()
                             if data["reaches_named_case"]),
        "reached_by_the_asked_axis": axes[asked]["reaches_named_case"],
    }
    report["axes"] = axes
    report["measured"] = True

    asked_axis = axes[asked]
    finding = bool(asked_axis["preempted_evidence"] or asked_axis["silenced"]
                   or not asked_axis["reaches_named_case"])
    report["status"] = "НАХОДКА" if finding else "ЧИСТО"
    report["verdict"] = {
        "asked_axis": asked,
        "asked_axis_new_candidates": asked_axis["candidates_new_vs_baseline"],
        "asked_axis_preempts_evidence": asked_axis["preempted_evidence"],
        "asked_axis_silences_losses": asked_axis["silenced"],
        "asked_axis_reaches_named_case": asked_axis["reaches_named_case"],
        "premise_of_the_order_holds": report["named_case"]["same_directory"] is False,
        "widening_applied": False,
        "why": ("дверь соседа НЕ расширена: расширение — отдельное решение, "
                "а прибор добывает его цену (ADR-682 запретил починку вслепую)"),
    }
    return report


def render(report: Dict[str, Any]) -> List[str]:
    lines = [f"[ЦЕНА ШИРИНЫ РОДНИ] заказ {report.get('order')} · "
             f"{report.get('generated_at')}"]
    if not report.get("measured"):
        lines.append(f"НЕ ИЗМЕРЕНО: {report.get('reason')}")
        return lines
    pop = report["population"]
    lines.append(f"население соседа: находок {pop['findings']} "
                 f"(из них могут быть заглушены {pop['silenceable']}, "
                 f"несут доказательство {pop['evidenced']}) · "
                 f"дерево базы {pop['base_paths']} путей · порог токенов "
                 f"{pop['need_tokens']}")
    named = report["named_case"]
    lines.append(f"[НАЗВАННЫЙ ЗАКАЗОМ СЛУЧАЙ] {named['coordinate']} ↔ "
                 f"{named['candidate']}: один каталог "
                 f"{'ДА' if named['same_directory'] else 'нет'}; ось заказа "
                 f"достаёт: {'ДА' if named['reached_by_the_asked_axis'] else 'НЕТ'}; "
                 f"достают оси: {', '.join(named['reached_by']) or '—'}")
    for axis, _ in AXES:
        data = report["axes"][axis]
        lines.append(
            f"[ОСЬ {axis}] кандидатов {data['candidates']} "
            f"(новых {data['candidates_new_vs_baseline']}) · заглушила бы потерь "
            f"{data['silenced']} · перебила бы доказательств "
            f"{data['preempted_evidence']} · истинных {data['verified_true']} · "
            f"ложных {data['verified_false']} · предмет закрыт иначе "
            f"{data['subject_closed_elsewhere']} · истинность НЕ ИЗМЕРЕНА "
            f"{data['truth_unmeasured']} · смена рода файла {data['kind_crossing']}")
    verdict = report["verdict"]
    lines.append(f"[ВЕРДИКТ] посылка заказа «прячет каталог» "
                 f"{'ВЕРНА' if verdict['premise_of_the_order_holds'] else 'НЕВЕРНА'}; "
                 f"дверь НЕ расширена ({verdict['why']})")
    lines.append("НЕ ДОКЛАДЫВАЕТ: истинность кандидатов без строки доказательства "
                 "(третий исход, не ноль) · была ли работа ПОДНЯТА или сделана "
                 "заново · родство по СОДЕРЖИМОМУ файла — мера смотрит только на имя")
    lines.append("ADVISORY: пороги RiskPolicy v1.0, стоп-кран, аллокатор, живой трек "
                 "и landing/ НЕ трогаются — прибор только ЧИТАЕТ")
    return lines


def format_report(report: Dict[str, Any]) -> List[str]:
    """Имя, которое зовёт шаг 0-офис. Правило отрисовки живёт у ПРОИЗВОДИТЕЛЯ."""
    return render(report)


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = Path(data_dir) / ARTIFACT
    atomic_save(report, str(path))
    return path


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до читателя, иначе шаг 0-офис не отличит его от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    data_dir = repo_root / "data"
    report = measure(repo_root, data_dir, now=now)
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=None, help="корень дерева (умолчание — своё)")
    parser.add_argument("--json", action="store_true", help="машинный вывод")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run(root=args.root)
    report = result["doc"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for line in render(report):
            print(line)
    if not report.get("measured"):
        return 2
    return 1 if report.get("status") == "НАХОДКА" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
